import json
import boto3
import uuid
import email
import os
from groq import Groq

client = Groq(api_key=os.environ["API_KEY"])


def parse_email_with_ai(body: str, sender: str, subject: str) -> dict:
    prompt = f"""
You are an email parsing system for a DevOps environment request workflow.

Extract structured information from the email below.

Return ONLY valid JSON (no markdown, no explanations, no code fences).

Rules:
- requester: full name of the person sending the request (or "Unknown")
- sender: the email address of the sender
- services: list of AWS services mentioned
    - include "ec2" if EC2, Jenkins, compute, or server is mentioned
    - include "rds" if database, DB, RDS, or storage is mentioned
    - include "ecs" if containers, ECS, or Docker is mentioned
    - default if nothing specific mentioned: ["ec2", "rds", "ecs"]
- tiers: list of environment tiers mentioned (lowercase)
    - include "dev", "qa", "uat" as appropriate
    - default if nothing specific mentioned: ["dev", "qa", "uat"]
- start_time: REQUIRED — extract and normalise to 12-hour format with uppercase AM/PM, e.g. "8:00 PM", "11:30 AM". "tonight at 8" → "8:00 PM". "immediately" or "now" → "Immediately". If not mentioned, set to "Not specified".
- end_time: REQUIRED — same normalisation rules as start_time. "3 in the morning" → "3:00 AM". "midnight" → "12:00 AM". "3pm" → "3:00 PM". If not mentioned, set to "Not specified".
- IMPORTANT: always zero-pad minutes (e.g. "8 PM" → "8:00 PM"), always uppercase AM/PM, never use 24-hour format.

Email Body:
{body}

Sender: {sender}
Subject: {subject}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=500
    )

    text = response.choices[0].message.content.strip()

    # Strip accidental markdown fences
    if "```" in text:
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    return json.loads(text)


def build_approval_email_html(
    requester, sender, subject, services, tiers,
    start_time, end_time, original_body, approve_url, deny_url
):
    rows = ""
    for tier in tiers:
        for service in services:
            rows += f"""
            <tr>
                <td>{tier.upper()}</td>
                <td>{service.upper()}</td>
            </tr>"""

    escaped_body = original_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background-color: #0d0d0d;
    color: #e0e0e0;
    font-family: 'IBM Plex Sans', sans-serif;
    font-size: 14px;
    line-height: 1.6;
    padding: 40px 20px;
  }}

  .wrapper {{
    max-width: 620px;
    margin: 0 auto;
  }}

  .header {{
    border-left: 3px solid #4a9eff;
    padding: 4px 0 4px 16px;
    margin-bottom: 32px;
  }}

  .header .label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #4a9eff;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 4px;
  }}

  .header h1 {{
    font-size: 20px;
    font-weight: 600;
    color: #ffffff;
    letter-spacing: -0.02em;
  }}

  .card {{
    background: #161616;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    margin-bottom: 16px;
    overflow: hidden;
  }}

  .card-header {{
    padding: 10px 16px;
    background: #1e1e1e;
    border-bottom: 1px solid #2a2a2a;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #888;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}

  .card-body {{
    padding: 16px;
  }}

  .meta-grid {{
    display: grid;
    grid-template-columns: 140px 1fr;
    gap: 10px 0;
  }}

  .meta-label {{
    font-size: 12px;
    color: #666;
    padding-top: 1px;
    font-family: 'IBM Plex Mono', monospace;
  }}

  .meta-value {{
    font-size: 13px;
    color: #d0d0d0;
  }}

  .meta-value.highlight {{
    color: #4a9eff;
    font-family: 'IBM Plex Mono', monospace;
  }}

  table.resources {{
    width: 100%;
    border-collapse: collapse;
  }}

  table.resources th {{
    text-align: left;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #555;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 0 12px 10px 0;
    border-bottom: 1px solid #2a2a2a;
  }}

  table.resources td {{
    padding: 9px 12px 9px 0;
    font-size: 13px;
    color: #c0c0c0;
    font-family: 'IBM Plex Mono', monospace;
    border-bottom: 1px solid #1e1e1e;
  }}

  table.resources tr:last-child td {{
    border-bottom: none;
  }}

  .tag {{
    display: inline-block;
    background: #1e2a1e;
    color: #6dbf6d;
    border: 1px solid #2d4a2d;
    border-radius: 2px;
    padding: 1px 7px;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 0.05em;
  }}

  .original-email {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: #777;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.7;
  }}

  .actions {{
    display: flex;
    gap: 12px;
    margin-top: 24px;
  }}

  .btn {{
    display: inline-block;
    padding: 11px 28px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    text-decoration: none;
    border-radius: 2px;
    cursor: pointer;
  }}

  .btn-approve {{
    background: #1a2e1a;
    color: #6dbf6d;
    border: 1px solid #2d4a2d;
  }}

  .btn-deny {{
    background: #2e1a1a;
    color: #bf6d6d;
    border: 1px solid #4a2d2d;
  }}

  .footer {{
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid #1e1e1e;
    font-size: 11px;
    color: #444;
    font-family: 'IBM Plex Mono', monospace;
  }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="header">
    <div class="label">Approval Required</div>
    <h1>Environment Request</h1>
  </div>

  <div class="card">
    <div class="card-header">Request Details</div>
    <div class="card-body">
      <div class="meta-grid">
        <span class="meta-label">Requester</span>
        <span class="meta-value">{requester}</span>

        <span class="meta-label">From</span>
        <span class="meta-value">{sender}</span>

        <span class="meta-label">Subject</span>
        <span class="meta-value">{subject}</span>

        <span class="meta-label">Start Time</span>
        <span class="meta-value highlight">{start_time}</span>

        <span class="meta-label">End Time</span>
        <span class="meta-value highlight">{end_time}</span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Resources Requested</div>
    <div class="card-body">
      <table class="resources">
        <thead>
          <tr>
            <th>Tier</th>
            <th>Service</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Original Message</div>
    <div class="card-body">
      <div class="original-email">{escaped_body}</div>
    </div>
  </div>

  <div class="actions">
    <a href="{approve_url}" class="btn btn-approve">Approve</a>
    <a href="{deny_url}" class="btn btn-deny">Deny</a>
  </div>

  <div class="footer">
    DevOps Environment Management &mdash; Automated notification. Do not reply to this email.
  </div>

</div>
</body>
</html>"""


def lambda_handler(event, context):
    ses = boto3.client('ses', region_name='ap-south-1')
    s3 = boto3.client('s3')

    ses_message = event['Records'][0]['ses']
    message_id = ses_message['mail']['messageId']
    sender = ses_message['mail']['commonHeaders']['from'][0]
    subject = ses_message['mail']['commonHeaders'].get('subject', '(no subject)')

    raw = s3.get_object(
        Bucket='env-approval-requests',
        Key=f'raw-emails/{message_id}'
    )
    raw_email = raw['Body'].read().decode('utf-8')

    msg = email.message_from_string(raw_email)

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                break
    else:
        body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')

    parsed = parse_email_with_ai(body, sender, subject)

    requester  = parsed.get("requester", "Unknown")
    services   = parsed.get("services", ["ec2", "rds", "ecs"])
    tiers      = parsed.get("tiers", ["dev", "qa", "uat"])
    start_time = parsed.get("start_time", "Not specified")
    end_time   = parsed.get("end_time", "Not specified")

    token = str(uuid.uuid4())
    request_key = f"approvals/pending/{token}.json"
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
            "status":     "pending"
        })
    )

    base_url    = "https://i7ohzc1hd1.execute-api.ap-south-1.amazonaws.com/approve"
    approve_url = f"{base_url}?token={token}&action=approve"
    deny_url    = f"{base_url}?token={token}&action=deny"

    html = build_approval_email_html(
        requester, sender, subject, services, tiers,
        start_time, end_time, body, approve_url, deny_url
    )

    ses.send_email(
        Source='requests@simaakniyaz.site',
        Destination={'ToAddresses': ['simaakniyaz@gmail.com']},
        Message={
            'Subject': {'Data': f'[Approval Required] {subject}'},
            'Body': {'Html': {'Data': html}}
        }
    )

    return {
        "statusCode": 200,
        "body": json.dumps(parsed)
    }