import json
import os
import boto3


def build_stop_notice_email_html(requester, subject, end_time, environments):
    rows = ""
    for env in environments:
        rows += f"""
        <tr>
            <td>{env}</td>
            <td><span class=\"status-badge\">Stopping</span></td>
        </tr>"""

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
    border-left: 3px solid #d7a44a;
    padding: 4px 0 4px 16px;
    margin-bottom: 32px;
  }}

  .header .label {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: #d7a44a;
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
    background: #2e271a;
    color: #d7a44a;
    border: 1px solid #4a3d23;
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
    <div class="label">Stop Workflow</div>
    <h1>Environment Stop Notification</h1>
  </div>

  <div class="card">
    <div class="card-header">Summary</div>
    <div class="card-body">
      <div class="meta-grid">
        <span class="meta-label">Requester</span>
        <span class="meta-value">{requester}</span>

        <span class="meta-label">Request</span>
        <span class="meta-value">{subject}</span>

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

      <div class="notice">
        Environments will be stopped now and scheduler-based stop controls are enabled for this workflow.
      </div>
    </div>
  </div>

  <div class="footer">
    DevOps Environment Management &mdash; Automated notification. Do not reply to this email.
  </div>

</div>
</body>
</html>"""


def lambda_handler(event, context):
    ses = boto3.client('ses', region_name='ap-south-1')

    requester = event.get('requester', 'Team')
    sender = event.get('sender')
    subject = event.get('subject', 'Environment Request')
    end_time = event.get('end_time', 'Not specified')
    environments = event.get('environments', [])

    print(f"Mock stop lambda executed for token: {event.get('token', 'unknown')}")

    recipients = []
    if sender:
        recipients.append(sender)

    for email_id in event.get('notify_to', []):
        if email_id and email_id not in recipients:
            recipients.append(email_id)

    team_email = os.environ.get('DEVOPS_TEAM_EMAIL')
    if team_email and team_email not in recipients:
        recipients.append(team_email)

    if not recipients:
        print('No recipients available; skipping email send')
        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Mock stop executed without recipients'})
        }

    email_html = build_stop_notice_email_html(requester, subject, end_time, environments)

    ses.send_email(
        Source=os.environ.get('SOURCE_EMAIL', 'requests@simaakniyaz.site'),
        Destination={'ToAddresses': recipients},
        Message={
            'Subject': {'Data': f'Stop Notice: {subject}'},
            'Body': {'Html': {'Data': email_html}}
        }
    )

    return {
        'statusCode': 200,
        'body': json.dumps({'message': 'Mock stop notification sent', 'recipients': recipients})
    }
