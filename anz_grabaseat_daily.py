#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
NZ → AU Daily Fares – simple Brevo emailer

- NO external libraries (no `requests`, only stdlib).
- Always produces 10 rows of example NZ→AU fares so the email / HTML never comes back empty.
- Dates in the HTML are in dd/mm/yyyy.
- Email sending via Brevo using environment variables:
    BREVO_API_KEY, FROM_EMAIL, TO_EMAIL, FROM_NAME
- DRY_RUN=1 → write HTML, log, but do NOT call Brevo.
"""

import os
import urllib.request
import urllib.error
import urllib.parse
import datetime as dt
import json
import html

# --------------------------------
# Env + logging
# --------------------------------

DEBUG = int(os.getenv("DEBUG", "1"))
DRY_RUN = int(os.getenv("DRY_RUN", "0"))
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "")
TO_EMAIL = os.getenv("TO_EMAIL", "")
FROM_NAME = os.getenv("FROM_NAME", "NZ-AU Fares Bot")


def log(msg: str) -> None:
    if DEBUG:
        print(msg)


def format_nz_date(d: dt.date) -> str:
    """Return dd/mm/yyyy for NZ-style display."""
    return d.strftime("%d/%m/%Y")


# --------------------------------
# Data – for now, static sample fares
# --------------------------------

def fetch_sample_fares():
    """
    Return 10 static sample fare rows so the email / HTML always has content.

    You can later replace this with real scraping / Seats.aero / whatever.
    Structure per row:
      {
        "rank": int,
        "origin": "AKL",
        "dest": "SYD",
        "date": date object,
        "price": 299,
        "currency": "NZD",
        "source": "sample"
      }
    """
    today = dt.date.today()
    routes = [
        ("AKL", "SYD", 299),
        ("AKL", "MEL", 319),
        ("AKL", "BNE", 289),
        ("AKL", "OOL", 279),
        ("AKL", "CBR", 349),
        ("WLG", "SYD", 269),
        ("CHC", "MEL", 299),
        ("AKL", "PER", 599),
        ("AKL", "ADL", 399),
        ("AKL", "DRW", 499),
    ]
    out = []
    for i, (o, d, price) in enumerate(routes, start=1):
        out.append(
            {
                "rank": i,
                "origin": o,
                "dest": d,
                "date": today + dt.timedelta(days=i * 3),
                "price": price,
                "currency": "NZD",
                "source": "sample",
            }
        )
    return out


# --------------------------------
# HTML builder
# --------------------------------

def build_html(fares):
    today_str = format_nz_date(dt.date.today())

    if not fares:
        return f"""
<h1>NZ → AU Daily Fares – {today_str}</h1>
<p>No fares found.</p>
"""

    rows = []
    for f in fares:
        rows.append(
            "<tr>"
            f"<td style='padding:4px 8px;'>{html.escape(str(f['rank']))}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(f['origin'])}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(f['dest'])}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(format_nz_date(f['date']))}</td>"
            f"<td style='padding:4px 8px;'>${html.escape(str(f['price']))} {html.escape(f['currency'])}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(f.get('source', ''))}</td>"
            "</tr>"
        )

    rows_html = "\n".join(rows)

    return f"""
<h1 style="font-family:Arial,Helvetica,sans-serif;">NZ → AU Daily Fares – {today_str}</h1>
<table style="border-collapse:collapse; font-family:Arial,Helvetica,sans-serif; font-size:13px; width:100%;">
  <thead>
    <tr style="background-color:#eeeeee;">
      <th>#</th>
      <th>Origin</th>
      <th>Destination</th>
      <th>Date</th>
      <th>Price</th>
      <th>Source</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
"""


# --------------------------------
# Email via Brevo
# --------------------------------

def send_email(subject: str, html_body: str) -> None:
    if DRY_RUN:
        log("DRY_RUN=1 → Not sending email (local / debug mode).")
        return

    if not (BREVO_API_KEY and FROM_EMAIL and TO_EMAIL):
        raise RuntimeError(
            "BREVO_API_KEY, FROM_EMAIL, TO_EMAIL must be set in environment."
        )

    payload = json.dumps(
        {
            "sender": {"email": FROM_EMAIL, "name": FROM_NAME},
            "to": [{"email": TO_EMAIL}],
            "subject": subject,
            "htmlContent": html_body,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        method="POST",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": BREVO_API_KEY,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            log(f"Email sent OK: HTTP {r.status}")
    except Exception as e:
        log(f"Brevo error: {e}")
        raise


# --------------------------------
# Main
# --------------------------------

def main():
    fares = fetch_sample_fares()
    html_body = build_html(fares)

    out_path = os.path.join(os.getcwd(), "anz_out.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_body)
    log(f"Wrote {out_path}")

    subject = f"NZ → AU Daily Fares – {dt.date.today().strftime('%Y-%m-%d')}"
    send_email(subject, html_body)


if __name__ == "__main__":
    main()
