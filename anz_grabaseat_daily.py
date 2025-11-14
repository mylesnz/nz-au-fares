#!/usr/bin/env python3
import urllib.request
import urllib.error
import urllib.parse
import datetime
import json
import os
import html

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")
TO_EMAIL = os.getenv("TO_EMAIL")
FROM_NAME = os.getenv("FROM_NAME", "NZ-AU Fare Bot")
DEBUG = int(os.getenv("DEBUG", "1"))

def log(x):
    if DEBUG:
        print(x)

def fetch_fares():
    url = "https://grabaseat.co.nz/api/routedeals?origin=AKL&destination=SYD"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def build_html(data):
    rows = ""
    for d in data.get("deals", []):
        price = d.get("price", "")
        dep = d.get("departDate", "")
        arr = d.get("arriveDate", "")
        route = f"{d.get('origin','')} → {d.get('destination','')}"
        rows += (
            "<tr>"
            f"<td style='padding:4px 8px;'>{html.escape(route)}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(dep)}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(arr)}</td>"
            f"<td style='padding:4px 8px;'>${price}</td>"
            "</tr>"
        )
    return f"""
<h1>NZ → AU Daily Sale</h1>
<table style="border-collapse:collapse;font-family:Arial;font-size:13px;width:100%;">
<thead><tr><th>Route</th><th>Depart</th><th>Arrive</th><th>Price</th></tr></thead>
<tbody>{rows}</tbody>
</table>
"""

def send_email(subject, html_body):
    payload = json.dumps({
        "sender": {"email":FROM_EMAIL, "name":FROM_NAME},
        "to": [{"email":TO_EMAIL}],
        "subject": subject,
        "htmlContent": html_body
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        method="POST",
        headers={"accept":"application/json","content-type":"application/json","api-key":BREVO_API_KEY}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        log(f"Email sent: {r.status}")

if __name__ == "__main__":
    data = fetch_fares()
    html_body = build_html(data)
    subject = f"NZ-AU Daily Fares – {datetime.date.today().isoformat()}"
    send_email(subject, html_body)
