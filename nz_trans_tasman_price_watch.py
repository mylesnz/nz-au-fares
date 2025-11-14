#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import datetime as dt
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict

# ============================================================
# CONFIG
# ============================================================

ORIGIN = "AKL"
DESTS = ["SYD","MEL","BNE","OOL","ADL","PER","CNS","HTI"]
MONTHS_AHEAD = 6
TOP_N = 20
ALLOW_EMPTY_EMAIL = True   # send email even if no deals found

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "")
TO_EMAIL = os.getenv("TO_EMAIL", "")
FROM_NAME = os.getenv("FROM_NAME", "NZ Tasman Bot")
DRY_RUN = int(os.getenv("DRY_RUN","1"))
DEBUG = int(os.getenv("DEBUG","1"))

def log(x):
    if DEBUG:
        print(x)

# ============================================================
# AIR NZ DEEP LINK BUILDER (A3)
# ============================================================

def build_airnz_link(origin, dest, date_str, cabin):
    """
    A3: True deep mobile-friendly booking link.
    Example:
    https://book.airnewzealand.co.nz/booking/flight-search?origin=AKL&destination=SYD&date=2025-04-22&adult=1&cabinClass=business
    """

    cabin_map = {
        "ECONOMY": "economy",
        "PREMIUM": "premiumeconomy",
        "BUSINESS": "business"
    }

    cab = cabin_map.get(cabin.upper(), "economy")

    params = {
        "origin": origin,
        "destination": dest,
        "date": date_str,
        "adult": "1",
        "cabinClass": cab
    }

    return "https://book.airnewzealand.co.nz/booking/flight-search?" + urllib.parse.urlencode(params)


# ============================================================
# FETCHER (your existing API)
# ============================================================

def fetch_tasman_data():
    """
    Replace this with your real API fetch.
    Expected format:
    [
        {
            "origin": "AKL",
            "dest": "SYD",
            "date": "2025-04-22",
            "price": 329,
            "cabin": "ECONOMY",
            "source": "AirNZ"
        },
        ...
    ]
    """
    url = "https://api.nz-fares.your-endpoint/v1/trans-tasman"  # YOUR REAL ENDPOINT
    req = urllib.request.Request(url, headers={"Accept":"application/json"})

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data
    except Exception as e:
        log(f"[ERROR] Fetch failed: {e}")
        return []


# ============================================================
# FILTER & GROUP INTO MONTH TABLES
# ============================================================

def group_into_months(rows):
    groups = defaultdict(list)
    for r in rows:
        d = dt.datetime.fromisoformat(r["date"]).date()
        month_key = d.strftime("%B %Y")
        groups[month_key].append(r)
    return groups


# ============================================================
# HTML BUILDER — ONE TABLE PER MONTH
# ============================================================

def build_html(grouped):
    today = dt.date.today().strftime("%d/%m/%Y")

    if not grouped:
        return f"""
        <h1>NZ → AU Daily Price Watch — {today}</h1>
        <p>No fares found in the next {MONTHS_AHEAD} months.</p>
        """

    html = f"<h1>NZ → AU Daily Price Watch — {today}</h1>"

    for month, rows in grouped.items():
        html += f"<h2>{month}</h2>"
        html += """
        <table style='border-collapse:collapse; width:100%; font-family:Arial; font-size:13px;'>
        <thead>
            <tr style='background:#eee;'>
                <th style='padding:6px;'>Route</th>
                <th style='padding:6px;'>Date</th>
                <th style='padding:6px;'>Cabin</th>
                <th style='padding:6px;'>Price</th>
                <th style='padding:6px;'>Source</th>
                <th style='padding:6px;'>Link</th>
            </tr>
        </thead>
        <tbody>
        """

        for r in rows:
            html += f"""
            <tr>
                <td style='padding:6px;'>{r['origin']} → {r['dest']}</td>
                <td style='padding:6px;'>{dt.datetime.fromisoformat(r['date']).strftime('%d/%m/%Y')}</td>
                <td style='padding:6px;'>{r['cabin']}</td>
                <td style='padding:6px;'>${r['price']}</td>
                <td style='padding:6px;'>{r['source']}</td>
                <td style='padding:6px;'><a href="{r['link']}">Book</a></td>
            </tr>
            """

        html += "</tbody></table><br>"

    return html


# ============================================================
# EMAIL SENDER
# ============================================================

def send_email(subject, html_body):
    if DRY_RUN == 1:
        log("DRY_RUN=1 → Email NOT sent")
        return

    if not BREVO_API_KEY:
        log("Missing BREVO_API_KEY")
        return

    payload = json.dumps({
        "sender": {"email": FROM_EMAIL, "name": FROM_NAME},
        "to": [{"email": TO_EMAIL}],
        "subject": subject,
        "htmlContent": html_body
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        method="POST",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": BREVO_API_KEY
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("Email sent OK:", r.status)
    except Exception as e:
        print("Email send failed:", e)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    data = fetch_tasman_data()
    log(f"Fetched {len(data)} rows")

    # Filter: only next N months
    today = dt.date.today()
    max_date = today + dt.timedelta(days=MONTHS_AHEAD * 30)

    valid = []
    for r in data:
        try:
            d = dt.datetime.fromisoformat(r["date"]).date()
        except:
            continue

        if not (today <= d <= max_date):
            continue

        # Add deep link
        r["link"] = build_airnz_link(r["origin"], r["dest"], r["date"], r["cabin"])
        valid.append(r)

    # Sort by price
    valid.sort(key=lambda x: x["price"])

    # Pick top N
    top = valid[:TOP_N]

    # Group into monthly tables
    grouped = group_into_months(top)

    # Build HTML
    html_body = build_html(grouped)

    # Write preview locally
    with open("out_nz_au.html", "w", encoding="utf-8") as f:
        f.write(html_body)

    print("Wrote out_nz_au.html")

    # Email if allowed
    if top or ALLOW_EMPTY_EMAIL:
        subject = f"NZ → AU Daily Price Watch — {dt.date.today().isoformat()}"
        send_email(subject, html_body)
