# Fix Guide — Environment Approval Workflow

Fixes for every issue in [REVIEW.md](REVIEW.md), ordered from most critical to least. Each section has a drop-in code change.

---

## Fix 1 — HTML-Escape All User-Controlled Fields (Critical)

Add `from html import escape` to every Lambda file and wrap every non-body field before interpolation.

**Applies to:** `parser/lambda_function.py`, `executor/lambda_function.py`, `stop-notifier/lambda_function.py`

```python
# Add to imports in all three files
from html import escape
```

**parser/lambda_function.py — `build_approval_email_html`:**

```python
def build_approval_email_html(
    requester, sender, subject, services, tiers,
    start_time, end_time, original_body, approve_url, deny_url
):
    rows = ""
    for tier in tiers:
        for service in services:
            rows += f"""
            <tr>
                <td>{escape(tier.upper())}</td>
                <td>{escape(service.upper())}</td>
            </tr>"""

    escaped_body = original_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # In the meta-grid section, change every interpolated field:
    # {requester}   →  {escape(requester)}
    # {sender}      →  {escape(sender)}
    # {subject}     →  {escape(subject)}
    # {start_time}  →  {escape(start_time)}
    # {end_time}    →  {escape(end_time)}
```

**executor/lambda_function.py — both email builders:**

```python
def build_approved_email_html(requester, start_time, end_time, started):
    rows = ""
    for env in started:
        rows += f"""
        <tr>
            <td>{escape(env)}</td>
            <td><span class="status-badge">Started</span></td>
        </tr>"""
    # {requester}  →  {escape(requester)}
    # {start_time} →  {escape(start_time)}
    # {end_time}   →  {escape(end_time)}


def build_denied_email_html(requester, subject):
    # {requester} →  {escape(requester)}
    # {subject}   →  {escape(subject)}
```

**stop-notifier/lambda_function.py — `build_stop_notice_email_html`:**

```python
def build_stop_notice_email_html(requester, subject, end_time, environments):
    rows = ""
    for env in environments:
        rows += f"""
        <tr>
            <td>{escape(env)}</td>
            <td><span class="status-badge">Stopping</span></td>
        </tr>"""
    # {requester} →  {escape(requester)}
    # {subject}   →  {escape(subject)}
    # {end_time}  →  {escape(end_time)}
```

---

## Fix 2 — Validate Token Format Before Any S3 Access (Critical)

This fixes the S3 path traversal and removes the need for a broad fallback.

**executor/lambda_function.py — top of `lambda_handler`:**

```python
import re

UUID4_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
)

def lambda_handler(event, context):
    ...
    params = event.get('queryStringParameters') or {}
    token = params.get('token', '')
    action = params.get('action')

    if not UUID4_RE.fullmatch(token) or action not in ('approve', 'deny'):
        return {'statusCode': 400, 'body': 'Invalid request'}

    request_key = f"approvals/pending/{token}.json"
    # Now safe — token is a valid UUID, cannot escape the prefix

    try:
        obj = s3.get_object(Bucket='env-approval-requests', Key=request_key)
    except ClientError as exc:
        error_code = exc.response.get('Error', {}).get('Code', '')
        if error_code in ('NoSuchKey', '404'):
            return {'statusCode': 404, 'body': 'Request not found'}
        raise
    # Remove the legacy fallback entirely — migrate old root-level objects once with a script
```

**One-time migration script to move any old root-level objects:**

```python
import boto3, json

s3 = boto3.client('s3')
bucket = 'env-approval-requests'

paginator = s3.get_paginator('list_objects_v2')
for page in paginator.paginate(Bucket=bucket):
    for obj in page.get('Contents', []):
        key = obj['Key']
        # Root-level objects are bare UUIDs (no slashes, no extension)
        if '/' not in key and not key.endswith('.json'):
            new_key = f"approvals/pending/{key}.json"
            s3.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': key}, Key=new_key)
            s3.delete_object(Bucket=bucket, Key=key)
            print(f"Migrated {key} → {new_key}")
```

---

## Fix 3 — Make Approval a Two-Step Flow (POST Confirmation) (High)

This defeats mail pre-fetcher auto-approval. The GET link shows a confirmation page; the actual action is a POST.

**executor/lambda_function.py — update `lambda_handler` to handle both steps:**

```python
def build_confirmation_page(token, action, request):
    color   = "#6dbf6d" if action == "approve" else "#bf6d6d"
    heading = "Confirm Approval" if action == "approve" else "Confirm Denial"
    btn_label = "Yes, Approve" if action == "approve" else "Yes, Deny"
    base_url = os.environ.get('APPROVAL_BASE_URL', '')
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<style>
  body {{ background:#0d0d0d; color:#e0e0e0; font-family:monospace;
          display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
  .box {{ text-align:center; padding:40px; border:1px solid #2a2a2a;
          border-top:3px solid {color}; border-radius:4px; max-width:420px; }}
  h2 {{ color:#fff; margin-bottom:12px; }}
  p {{ color:#888; font-size:12px; line-height:1.7; margin-bottom:24px; }}
  form button {{ padding:10px 28px; background:{color}22; color:{color};
                 border:1px solid {color}55; border-radius:2px;
                 font-family:monospace; font-size:12px; cursor:pointer; }}
</style>
</head>
<body>
  <div class="box">
    <h2>{heading}</h2>
    <p>Requester: {escape(request.get('requester',''))}
       <br>Subject: {escape(request.get('subject',''))}</p>
    <form method="POST" action="{base_url}">
      <input type="hidden" name="token" value="{escape(token)}">
      <input type="hidden" name="action" value="{escape(action)}">
      <button type="submit">{btn_label}</button>
    </form>
  </div>
</body>
</html>"""


def lambda_handler(event, context):
    ...
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')

    # GET — show confirmation page only, take no action
    if http_method == 'GET':
        # Still read the object to check it exists and isn't already processed
        ...
        if current_status != 'pending':
            return {'statusCode': 200, 'headers': {'Content-Type': 'text/html'},
                    'body': build_already_processed_page(current_status)}
        return {'statusCode': 200, 'headers': {'Content-Type': 'text/html'},
                'body': build_confirmation_page(token, action, request)}

    # POST — execute the action
    if http_method == 'POST':
        # parse body params, then run the existing approve/deny logic
        ...
```

> **Note:** API Gateway must be configured to allow both GET and POST on the `/approve` route. The `<form>` above posts to the same URL.

---

## Fix 4 — Atomic Idempotency Using S3 ETag Conditional Write (High)

No DynamoDB needed. S3 supports conditional `put_object` using the `IfMatch` header — if the object was modified between your read and write, S3 rejects the put with `PreconditionFailed`. This is a free compare-and-swap using infrastructure you already have.

**executor/lambda_function.py:**

```python
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    ...
    request_key = f"approvals/pending/{token}.json"

    try:
        response = s3.get_object(Bucket='env-approval-requests', Key=request_key)
    except ClientError as exc:
        if exc.response['Error']['Code'] in ('NoSuchKey', '404'):
            return {'statusCode': 404, 'body': 'Request not found'}
        raise

    etag = response['ETag']                          # capture the current ETag
    request = json.loads(response['Body'].read())

    current_status = request.get('status', 'pending')
    if current_status != 'pending':
        return {'statusCode': 200, 'headers': {'Content-Type': 'text/html'},
                'body': build_already_processed_page(current_status)}

    # ... do work (scheduler, emails, etc.) ...

    request['status'] = 'approved'  # or 'denied'

    try:
        s3.put_object(
            Bucket='env-approval-requests',
            Key=request_key,
            Body=json.dumps(request),
            IfMatch=etag                             # atomic: fails if another Lambda already wrote
        )
    except ClientError as exc:
        if exc.response['Error']['Code'] == 'PreconditionFailed':
            # Another invocation already processed this token — safe to treat as idempotent
            return {'statusCode': 200, 'headers': {'Content-Type': 'text/html'},
                    'body': build_already_processed_page('approved')}
        raise
```

`IfMatch` on `put_object` was added to the S3 API in 2024 and is fully supported in boto3. No new AWS service, no extra cost — just a conditional header on an existing call.

---

## Fix 5 — Wrap AI Parse in try/except (High)

**parser/lambda_function.py:**

```python
def lambda_handler(event, context):
    ...
    try:
        parsed = parse_email_with_ai(body, sender, subject)
    except json.JSONDecodeError as exc:
        print(f"AI returned non-JSON for message {message_id}: {exc}. Using defaults.")
        parsed = {}
    except Exception as exc:
        print(f"Groq API error for message {message_id}: {exc}. Using defaults.")
        parsed = {}

    # The .get() defaults already cover every field — no other change needed
    requester  = parsed.get("requester", "Unknown")
    services   = parsed.get("services", ["ec2", "rds", "ecs"])
    tiers      = parsed.get("tiers", ["dev", "qa", "uat"])
    start_time = parsed.get("start_time", "Not specified")
    end_time   = parsed.get("end_time", "Not specified")
```

Also guard the `json.loads` call inside `parse_email_with_ai` itself so the error message is clearer:

```python
def parse_email_with_ai(body, sender, subject):
    ...
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"Raw AI output that failed to parse: {text!r}")
        raise
```

---

## Fix 6 — Send Email Before Committing Status to S3 (High)

Reverse the order so that a SES failure leaves the token retryable.

**executor/lambda_function.py — approve branch:**

```python
if action == 'approve':
    # ... build started list and create scheduler ...

    email_subject = f'Approved: {subject}'
    email_body = build_approved_email_html(requester, start_time, end_time, started)

    # Send email FIRST — if this fails, status stays 'pending' and the link remains actionable
    ses.send_email(
        Source='requests@simaakniyaz.site',
        Destination={'ToAddresses': [sender]},
        Message={'Subject': {'Data': email_subject}, 'Body': {'Html': {'Data': email_body}}}
    )

    # Commit status only after email succeeds
    request['status'] = 'approved'
    s3.put_object(Bucket='env-approval-requests', Key=storage_key, Body=json.dumps(request))

else:  # deny — same reversal
    email_subject = f'Denied: {subject}'
    email_body = build_denied_email_html(requester, subject)

    ses.send_email(
        Source='requests@simaakniyaz.site',
        Destination={'ToAddresses': [sender]},
        Message={'Subject': {'Data': email_subject}, 'Body': {'Html': {'Data': email_body}}}
    )

    request['status'] = 'denied'
    s3.put_object(Bucket='env-approval-requests', Key=storage_key, Body=json.dumps(request))
```

> Combined with Fix 4 (ETag conditional write), a retry after SES failure will re-attempt the email and then do an atomic status commit.

---

## Fix 7 — Add Token Expiry (Medium)

**parser/lambda_function.py — add `issued_at` when storing the request:**

```python
from datetime import datetime, timezone

s3.put_object(
    Bucket='env-approval-requests',
    Key=request_key,
    Body=json.dumps({
        "sender":     sender,
        "subject":    subject,
        "requester":  requester,
        "services":   services,
        "tiers":      tiers,
        "start_time": start_time,
        "end_time":   end_time,
        "status":     "pending",
        "issued_at":  datetime.now(timezone.utc).isoformat()   # add this
    })
)
```

**executor/lambda_function.py — check age after reading the object:**

```python
from datetime import datetime, timedelta, timezone

request = json.loads(obj['Body'].read())

issued_at_str = request.get('issued_at')
if issued_at_str:
    issued_at = datetime.fromisoformat(issued_at_str)
    if datetime.now(timezone.utc) - issued_at > timedelta(hours=48):
        return {
            'statusCode': 410,
            'headers': {'Content-Type': 'text/html'},
            'body': '<p>This approval link has expired.</p>'
        }
```

---

## Fix 8 — Surface Scheduler Failures (Medium)

Instead of silently continuing, include a warning in the confirmation email when the stop schedule could not be created.

**executor/lambda_function.py:**

```python
schedule_created = False

if stop_lambda_arn and scheduler_role_arn:
    try:
        scheduler.create_schedule(...)
        schedule_created = True
        ...
    except scheduler.exceptions.ConflictException:
        print(f"Schedule already exists: {schedule_name}")
        schedule_created = True   # already exists — treat as success
    except Exception as exc:
        print(f"Failed to create stop scheduler: {exc}")
        # schedule_created stays False

# Pass schedule_created to the email builder
email_body = build_approved_email_html(requester, start_time, end_time, started, schedule_created)
```

**In `build_approved_email_html`, add a warning when `schedule_created=False`:**

```python
def build_approved_email_html(requester, start_time, end_time, started, schedule_created=True):
    ...
    schedule_warning = ""
    if not schedule_created:
        schedule_warning = """
        <div class="notice" style="border-left-color:#bf6d6d; color:#dc8a8a;">
            Warning: Automatic stop scheduling failed. Environments must be stopped manually.
        </div>"""

    # Insert schedule_warning after the environments table in the returned HTML
```

---

## Fix 9 — Use Absolute Datetime for Stop Scheduling (Medium)

The current approach only stores a time-of-day string, which breaks across midnight and loses the intended date.

**parser/lambda_function.py — update the AI prompt:**

```python
- end_time: REQUIRED — extract the intended stop datetime. If the email gives a time only
  (e.g. "stop at 11pm"), assume the same calendar date as the request unless "tomorrow" or
  a future date is implied. Return as ISO-8601 with date: "2026-06-16T23:00". If not
  mentioned, set to "Not specified".
```

**executor/lambda_function.py — replace `next_occurrence_from_end_time` with direct ISO-8601 parsing:**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

def parse_end_datetime(end_time, timezone_name):
    tz = ZoneInfo(timezone_name)
    # Try ISO-8601 with date first (new format)
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'):
        try:
            dt = datetime.strptime(end_time.strip(), fmt)
            return dt.replace(tzinfo=tz)
        except ValueError:
            continue
    # Fall back to time-only for backward compatibility
    dt = datetime.strptime(end_time.strip(), '%I:%M %p')
    now_local = datetime.now(tz)
    run_local = now_local.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
    if run_local <= now_local:
        run_local += timedelta(days=1)
    return run_local
```

---

## Fix 10 — Handle `end_time='Immediately'` Gracefully (Medium)

Instead of returning a raw 400, allow the approval without scheduling a stop and display a styled page.

**executor/lambda_function.py:**

```python
if action == 'approve':
    no_schedule = end_time.strip().lower() in ('', 'not specified', 'immediately')

    started = []
    for tier in tiers:
        for service in services:
            started.append(f"{tier.upper()} / {service.upper()}")

    if not no_schedule and stop_lambda_arn and scheduler_role_arn:
        # ... create EventBridge schedule as before ...
        pass
    elif no_schedule:
        print("No end_time specified; skipping stop scheduler. Environments must be stopped manually.")

    # Continue to send approval email and commit status regardless
```

---

## Fix 11 — Move Hardcoded URL and Email to Environment Variables (Low)

**parser/lambda_function.py:**

```python
# Replace:
base_url    = "https://i7ohzc1hd1.execute-api.ap-south-1.amazonaws.com/approve"
...
Destination={'ToAddresses': ['simaakniyaz@gmail.com']}

# With:
base_url     = os.environ['APPROVAL_BASE_URL']
admin_email  = os.environ['DEVOPS_APPROVAL_EMAIL']
...
Destination={'ToAddresses': [admin_email]}
```

Add to Parser Lambda environment variables:

| Variable | Example Value |
|---|---|
| `APPROVAL_BASE_URL` | `https://i7ohzc1hd1.execute-api.ap-south-1.amazonaws.com/approve` |
| `DEVOPS_APPROVAL_EMAIL` | `simaakniyaz@gmail.com` |

Also replace the hardcoded `Source='requests@simaakniyaz.site'` in parser and executor with `os.environ.get('SOURCE_EMAIL', 'requests@simaakniyaz.site')` — consistent with how stop-notifier already handles it.

---

## Fix 12 — Add S3 Lifecycle Rules for Storage Cleanup (Low)

Add this to your infrastructure config (CloudFormation / Terraform / AWS Console):

```json
{
  "Rules": [
    {
      "ID": "expire-raw-emails",
      "Prefix": "raw-emails/",
      "Status": "Enabled",
      "Expiration": { "Days": 7 }
    },
    {
      "ID": "expire-completed-approvals",
      "Prefix": "approvals/pending/",
      "Status": "Enabled",
      "Expiration": { "Days": 90 }
    }
  ]
}
```

Alternatively, delete the raw email in the parser after a successful parse:

```python
# parser/lambda_function.py — after parse_email_with_ai succeeds
s3.delete_object(Bucket='env-approval-requests', Key=f'raw-emails/{message_id}')
```

---

## Fix Order — Recommended Sequence

| Priority | Fix | Effort |
|---|---|---|
| 1 | HTML-escape all email fields (Fix 1) | 30 min — mechanical find/replace |
| 2 | Validate token as UUID4 (Fix 2) | 15 min |
| 3 | Wrap AI parse in try/except (Fix 5) | 15 min |
| 4 | Reverse email/status write order (Fix 6) | 10 min |
| 5 | ETag conditional write for idempotency (Fix 4) | 30 min |
| 6 | Move hardcoded URL + email to env vars (Fix 11) | 10 min |
| 7 | Add token expiry (Fix 7) | 20 min |
| 8 | POST confirmation page for approval (Fix 3) | 1–2 hours |
| 9 | Surface scheduler failures in email (Fix 8) | 20 min |
| 10 | Handle end_time=Immediately gracefully (Fix 10) | 15 min |
| 11 | Absolute datetime for stop scheduling (Fix 9) | 30 min |
| 12 | S3 Lifecycle rules (Fix 12) | 10 min |
