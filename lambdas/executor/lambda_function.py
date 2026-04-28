import json
import boto3
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from botocore.exceptions import ClientError


def next_occurrence_from_end_time(end_time, timezone_name):
  parsed = datetime.strptime(end_time.strip(), "%I:%M %p")
  tz = ZoneInfo(timezone_name)
  now_local = datetime.now(tz)
  run_local = now_local.replace(
    hour=parsed.hour,
    minute=parsed.minute,
    second=0,
    microsecond=0
  )

  if run_local <= now_local:
    run_local = run_local + timedelta(days=1)

  return run_local


def build_approved_email_html(requester, start_time, end_time, started):
    rows = ""
    for env in started:
        rows += f"""
        <tr>
            <td>{env}</td>
            <td><span class="status-badge">Started</span></td>
        </tr>"""

    end_note = ""
    if end_time and end_time.lower() != "not specified":
        end_note = f"""
        <div class="notice">
            Environments are scheduled to run until <span class="mono">{end_time}</span>.
            Ensure they are stopped after use if auto-shutdown is not configured.
        </div>"""

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
    border-left: 3px solid #6dbf6d;
    padding: 4px 0 4px 16px;
    margin-bottom: 32px;
  }}

  .header .label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #6dbf6d;
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
    grid-template-columns: 120px 1fr;
    gap: 10px 0;
  }}

  .meta-label {{
    font-size: 12px;
    color: #666;
    font-family: 'IBM Plex Mono', monospace;
    padding-top: 1px;
  }}

  .meta-value {{
    font-size: 13px;
    color: #d0d0d0;
  }}

  .mono {{
    font-family: 'IBM Plex Mono', monospace;
    color: #4a9eff;
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

  .status-badge {{
    display: inline-block;
    background: #1a2e1a;
    color: #6dbf6d;
    border: 1px solid #2d4a2d;
    border-radius: 2px;
    padding: 1px 8px;
    font-size: 11px;
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 0.05em;
  }}

  .notice {{
    margin-top: 12px;
    padding: 10px 14px;
    background: #1a1f2e;
    border-left: 3px solid #4a9eff;
    border-radius: 2px;
    font-size: 12px;
    color: #8aacdc;
    line-height: 1.6;
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
    <div class="label">Request Approved</div>
    <h1>Environments Starting</h1>
  </div>

  <div class="card">
    <div class="card-header">Summary</div>
    <div class="card-body">
      <div class="meta-grid">
        <span class="meta-label">Requester</span>
        <span class="meta-value">{requester}</span>

        <span class="meta-label">Start Time</span>
        <span class="meta-value mono">{start_time}</span>

        <span class="meta-label">End Time</span>
        <span class="meta-value mono">{end_time}</span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">Environments</div>
    <div class="card-body">
      <table class="resources">
        <thead>
          <tr>
            <th>Environment</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
      {end_note}
    </div>
  </div>

  <div class="footer">
    DevOps Environment Management &mdash; Automated notification. Do not reply to this email.
  </div>

</div>
</body>
</html>"""


def build_denied_email_html(requester, subject):
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
    border-left: 3px solid #bf6d6d;
    padding: 4px 0 4px 16px;
    margin-bottom: 32px;
  }}

  .header .label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #bf6d6d;
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

  .card-body {{
    padding: 20px;
    color: #aaa;
    font-size: 13px;
    line-height: 1.7;
  }}

  .card-body p + p {{
    margin-top: 10px;
  }}

  .highlight {{
    color: #e0e0e0;
    font-weight: 500;
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
    <div class="label">Request Denied</div>
    <h1>Unable to Approve</h1>
  </div>

  <div class="card">
    <div class="card-body">
      <p>Hi <span class="highlight">{requester}</span>,</p>
      <p>
        Your environment request <span class="highlight">"{subject}"</span> could not be approved at this time.
      </p>
      <p>
        Please contact the DevOps team directly for more information or to arrange an alternative time.
      </p>
    </div>
  </div>

  <div class="footer">
    DevOps Environment Management &mdash; Automated notification. Do not reply to this email.
  </div>

</div>
</body>
</html>"""


def build_already_processed_page(status):
    color = "#6dbf6d" if status == "approved" else "#bf6d6d"
    label = "approved" if status == "approved" else "denied"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap');
  body {{
    background: #0d0d0d;
    color: #e0e0e0;
    font-family: 'IBM Plex Mono', monospace;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
  }}
  .box {{
    text-align: center;
    padding: 40px;
    border: 1px solid #2a2a2a;
    border-top: 3px solid {color};
    border-radius: 4px;
    max-width: 400px;
  }}
  .status {{ font-size: 12px; color: {color}; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 12px; }}
  h2 {{ font-size: 18px; color: #fff; margin-bottom: 12px; }}
  p {{ font-size: 12px; color: #666; line-height: 1.7; }}
</style>
</head>
<body>
  <div class="box">
    <div class="status">Already Processed</div>
    <h2>Request was already {label}</h2>
    <p>This approval link has already been used and cannot be actioned again.</p>
  </div>
</body>
</html>"""


def build_response_page(action):
    color   = "#6dbf6d" if action == "approve" else "#bf6d6d"
    heading = "Request Approved" if action == "approve" else "Request Denied"
    label   = "approved" if action == "approve" else "denied"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap');
  body {{
    background: #0d0d0d;
    color: #e0e0e0;
    font-family: 'IBM Plex Mono', monospace;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    margin: 0;
  }}
  .box {{
    text-align: center;
    padding: 40px;
    border: 1px solid #2a2a2a;
    border-top: 3px solid {color};
    border-radius: 4px;
    max-width: 400px;
  }}
  .status {{ font-size: 12px; color: {color}; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 12px; }}
  h2 {{ font-size: 18px; color: #fff; margin-bottom: 12px; }}
  p {{ font-size: 12px; color: #666; line-height: 1.7; }}
</style>
</head>
<body>
  <div class="box">
    <div class="status">Done</div>
    <h2>{heading}</h2>
    <p>The requester has been notified that their request was {label}.</p>
  </div>
</body>
</html>"""


def lambda_handler(event, context):
    ses = boto3.client('ses', region_name='ap-south-1')
    s3 = boto3.client('s3')
    scheduler = boto3.client('scheduler')

    params = event.get('queryStringParameters') or {}
    token = params.get('token')
    action = params.get('action')

    if not token or action not in ('approve', 'deny'):
        return {'statusCode': 400, 'body': 'Invalid token or action'}

    request_key = f"approvals/pending/{token}.json"

    # Backward compatibility: older requests were stored at the bucket root (Key=token).
    try:
        obj = s3.get_object(Bucket='env-approval-requests', Key=request_key)
        storage_key = request_key
    except ClientError as exc:
        error_code = exc.response.get('Error', {}).get('Code', '')
        if error_code not in ('NoSuchKey', 'NoSuchBucket', '404'):
            raise
        obj = s3.get_object(Bucket='env-approval-requests', Key=token)
        storage_key = token

    request = json.loads(obj['Body'].read())

    # Idempotency guard
    current_status = request.get('status', 'pending')
    if current_status != 'pending':
        return {
            'statusCode': 200,
            'headers': {'Content-Type': 'text/html'},
            'body': build_already_processed_page(current_status)
        }

    sender = request['sender']
    subject = request['subject']
    requester = request.get('requester', 'Team')
    services = request.get('services', [])
    tiers = request.get('tiers', [])
    start_time = request.get('start_time', 'Not specified')
    end_time = request.get('end_time', 'Not specified')

    if action == 'approve' and end_time.strip().lower() in ('', 'not specified', 'immediately'):
        return {
            'statusCode': 400,
            'body': 'end_time is required for approval scheduling'
        }

    if action == 'approve':
        started = []
        for tier in tiers:
            for service in services:
                print(f"Starting {tier} {service.upper()}...")
                # Uncomment when real Lambdas are ready:
                # lambda_client.invoke(FunctionName=f'start-{service}-{tier.lower()}', InvocationType='Event')
                started.append(f"{tier.upper()} / {service.upper()}")

        timezone_name = os.environ.get('SCHEDULER_TIMEZONE', 'Asia/Kolkata')
        stop_lambda_arn = os.environ.get('STOP_MOCK_LAMBDA_ARN')
        scheduler_role_arn = os.environ.get('SCHEDULER_ROLE_ARN')
        team_email = os.environ.get('DEVOPS_TEAM_EMAIL')

        if stop_lambda_arn and scheduler_role_arn:
            try:
                run_local = next_occurrence_from_end_time(end_time, timezone_name)
                schedule_name = f"env-stop-{token}"
                notify_to = [sender]
                if team_email:
                    notify_to.append(team_email)

                scheduler_payload = {
                    "token": token,
                    "requester": requester,
                    "sender": sender,
                    "subject": subject,
                    "start_time": start_time,
                    "end_time": end_time,
                    "environments": started,
                    "notify_to": notify_to
                }

                scheduler.create_schedule(
                    Name=schedule_name,
                    GroupName='default',
                    Description=f"One-time mock stop notifier for request {token}",
                    ScheduleExpression=f"at({run_local.strftime('%Y-%m-%dT%H:%M:%S')})",
                    ScheduleExpressionTimezone=timezone_name,
                    FlexibleTimeWindow={'Mode': 'OFF'},
                    ActionAfterCompletion='DELETE',
                    Target={
                        'Arn': stop_lambda_arn,
                        'RoleArn': scheduler_role_arn,
                        'Input': json.dumps(scheduler_payload)
                    }
                )
                request['stop_schedule_name'] = schedule_name
                request['stop_scheduled_for'] = run_local.isoformat()
                print(f"Created one-time stop schedule {schedule_name} for {run_local.isoformat()}")
            except scheduler.exceptions.ConflictException:
                print(f"Schedule already exists: {schedule_name}")
            except ValueError as exc:
                print(f"Invalid end_time format for scheduler: {end_time}. Error: {exc}")
            except Exception as exc:
                print(f"Failed to create stop scheduler: {exc}")
        else:
            print("STOP_MOCK_LAMBDA_ARN or SCHEDULER_ROLE_ARN not set; skipping stop scheduler creation")

        request['status'] = 'approved'
        s3.put_object(Bucket='env-approval-requests', Key=storage_key, Body=json.dumps(request))

        email_subject = f'Approved: {subject}'
        email_body = build_approved_email_html(requester, start_time, end_time, started)

    else:  # deny
        request['status'] = 'denied'
        s3.put_object(Bucket='env-approval-requests', Key=storage_key, Body=json.dumps(request))

        email_subject = f'Denied: {subject}'
        email_body = build_denied_email_html(requester, subject)

    ses.send_email(
        Source='requests@simaakniyaz.site',
        Destination={'ToAddresses': [sender]},
        Message={
            'Subject': {'Data': email_subject},
            'Body': {'Html': {'Data': email_body}}
        }
    )

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/html'},
        'body': build_response_page(action)
    }