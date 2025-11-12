#!/usr/bin/env python3
"""
NZ→AU fare watcher (dummy data version)

- Origin: AKL
- Destinations: SYD, MEL
- Cabin: Premium Economy and Business
- Window: 6 months forward (documented; currently using dummy fares)
- Thresholds:
    Premium Economy <= 1300 NZD
    Business       <= 1500 NZD

This is a working skeleton:
- Builds an HTML email with colour-coded rows.
- Uses Brevo REST API (BREVO_API_KEY) if DRY_RUN != "1".
- In DRY_RUN=1, just prints HTML to stdout.

Later you can replace `fetch_dummy_fares()` with a real Grabaseat / other API integration.
"""

import os
import sys
import json
import datetime as dt
import urllib.request
import urllib.error
import html


ORIGIN = "AKL"
DESTS = ["SYD", "MEL"]

# thresholds in NZD
MAX_PREM_ECON = 1300
MAX_BUSINESS = 1500

TEASPOON = "&nbsp;"  # spacing in HTML


def today_nz():
    # Use local date; if you want strict NZ time, tweak here
    return dt.date.today()


def six_months_ahead(d):
    # Rough 6-month window: +183 days
    return d + dt.timedelta(days=183)


def cabin_name(code):
    # Simple mapping for readability
    if code == "W":
        return "Premium Economy"
    if code == "J":
        return "Business"
    return code


def nz_date(d):
    return d.strftime("%d/%m/%y")


def html_escape(s):
    return html.escape(str(s), quote=True)


def build_dummy_sample():
    """Simulated fare data to prove the pipeline works.

    In real life, replace this with a call that hits Grabaseat / Air NZ API / etc.
    """
    start = today_nz()
    end = six_months_ahead(start)

    # A few sample dates inside the window
    d1 = start + dt.timedelta(days=14)
    d2 = start + dt.timedelta(days=45)
    d3 = start + dt.timedelta(days=120)

    # each dict is one "deal"
    return [
        {
            "origin": "AKL",
            "dest": "SYD",
            "origin_name": "Auckland",
            "dest_name": "Sydney",
            "depart": d1,
            "return": d1 + dt.timedelta(days=7),
            "cabin": "W",
            "price_nzd": 899,
            "carrier": "NZ",
        },
        {
            "origin": "AKL",
            "dest": "SYD",
            "origin_name": "Auckland",
            "dest_name": "Sydney",
            "depart": d2,
            "return": d2 + dt.timedelta(days=4),
            "cabin": "J",
            "price_nzd": 1550,
            "carrier": "NZ",
        },
        {
            "origin": "AKL",
            "dest": "MEL",
            "origin_name": "Auckland",
            "dest_name": "Melbourne",
            "depart": d3,
            "return": d3 + dt.timedelta(days=10),
            "cabin": "W",
            "price_nzd": 1320,
            "carrier": "NZ",
        },
    ], start, end


def filter_by_threshold(rows):
    """Apply the NZD thresholds."""
    filtered = []
    for r in rows:
        cabin = r.get("cabin")
        price = r.get("price_nzd", 0)

        if cabin == "W":
            if price <= MAX_PREM_ECON:
                filtered.append(r)
        elif cabin == "J":
            if price <= MAX_BUSINESS:
                filtered.append(r)
    return filtered


def badge_colour(row):
    """Colour by price threshold."""
    price = row.get("price_nzd", 0)
    cabin = row.get("cabin")

    if cabin == "W":
        if price <= MAX_PREM_ECON:
            return "#2e7d32"  # green-ish
    elif cabin == "J":
        if price <= MAX_BUSINESS:
            return "#2e7d32"  # green-ish

    # If it's above threshold but we kept it (future logic), could go amber/grey
    return "#757575"


def build_html(rows, start, end):
    subject = f"NZ→AU Air NZ fares – {today_nz():%d/%m/%y}"

    if not rows:
        body = f"""
<h1 style="font-family:Arial,Helvetica,sans-serif;">{html_escape(subject)}</h1>
<p>No deals found under your thresholds between {html_escape(nz_date(start))} and {html_escape(nz_date(end))}.</p>
"""
        return subject, body

    # Sort by price ascending
    rows = sorted(rows, key=lambda r: r.get("price_nzd", 999999))

    # Build rows
    tr_html = []
    for r in rows:
        o = r["origin"]
        d = r["dest"]
        oname = r.get("origin_name", o)
        dname = r.get("dest_name", d)
        route = f"{o} ({oname}) → {d} ({dname})"

        dep = r["depart"]
        ret = r["return"]
        date_range = f"{nz_date(dep)} → {nz_date(ret)}"

        cabin = cabin_name(r["cabin"])
        price = r["price_nzd"]
        carrier = r.get("carrier", "NZ")

        colour = badge_colour(r)
        price_html = f"<span style='color:{colour}; font-weight:bold;'>${price:.0f}</span>"

        # You can swap this for a real link later (Grabaseat / Air NZ deep link)
        link = "#"

        tr_html.append(
            "<tr>"
            f"<td style='padding:4px 8px;'>{html_escape(route)}</td>"
            f"<td style='padding:4px 8px;'>{html_escape(date_range)}</td>"
            f"<td style='padding:4px 8px;'>{html_escape(cabin)}</td>"
            f"<td style='padding:4px 8px;'>{price_html}</td>"
            f"<td style='padding:4px 8px;'>{html_escape(carrier)}</td>"
            f"<td style='padding:4px 8px;'><a href='{html_escape(link)}'>Search</a></td>"
            "</tr>"
        )

    table = f"""
<table style="border-collapse:collapse; font-family:Arial,Helvetica,sans-serif; font-size:13px; width:100%;">
  <thead>
    <tr style="background-color:#eeeeee;">
      <th style="text-align:left; padding:6px 8px;">Route</th>
      <th style="text-align:left; padding:6px 8px;">Dates</th>
      <th style="text-align:left; padding:6px 8px;">Cabin</th>
      <th style="text-align:left; padding:6px 8px;">Price (NZD)</th>
      <th style="text-align:left; padding:6px 8px;">Carrier</th>
      <th style="text-align:left; padding:6px 8px;">Link</th>
    </tr>
  </thead>
  <tbody>
    {''.join(tr_html)}
  </tbody>
</table>
"""

    summary = f"""
<h1 style="font-family:Arial,Helvetica,sans-serif;">{html_escape(subject)}</h1>
<p>Window: {html_escape(nz_date(start))} → {html_escape(nz_date(end))}{TEASPOON} |{TEASPOON}
Thresholds: Prem Econ ≤ ${MAX_PREM_ECON:.0f}, Business ≤ ${MAX_BUSINESS:.0f}</p>
"""

    return subject, summary + table


def send_brevo_email(subject, html_body):
    api_key = os.getenv("BREVO_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    from_name = os.getenv("FROM_NAME", "NZ AU Fares Bot")
    to_email = os.getenv("TO_EMAIL")

    missing = [k for k, v in [
        ("BREVO_API_KEY", api_key),
        ("FROM_EMAIL", from_email),
        ("TO_EMAIL", to_email),
    ] if not v]

    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    payload = {
        "sender": {"email": from_email, "name": from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_body,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=data,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        print(f"Brevo response: {resp.status}")
        print(body)


def main():
    print("🚀 NZ→AU Air NZ fare watcher (dummy data)")
    rows, start, end = build_dummy_sample()
    print(f"Fetched {len(rows)} synthetic rows between {start} and {end}")

    filtered = filter_by_threshold(rows)
    print(f"After thresholds: {len(filtered)} rows")

    subject, html_body = build_html(filtered, start, end)

    dry_run = os.getenv("DRY_RUN", "1")
    if dry_run == "1":
        print("DRY_RUN=1 → not sending email. HTML preview:")
        print()
        print(subject)
        print()
        print(html_body)
    else:
        try:
            send_brevo_email(subject, html_body)
        except Exception as e:
            print(f"❌ Brevo send failed: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
