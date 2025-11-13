#!/usr/bin/env python3
"""
NZ→AU Air NZ watcher using Amadeus Flight Offers (test API).

- Searches AKL→SYD and AKL→MEL returns, 8–12 days, over N months.
- Keeps only:
    * Airline: NZ (Air New Zealand) via Amadeus filter
    * Cabin: PREMIUM_ECONOMY or BUSINESS
    * Price caps: PE_CAP / J_CAP (NZD)
- Writes HTML to out_nz_au.html
- Optional email via Brevo SMTP API (if DRY_RUN=0 and BREVO_API_KEY is set).

Environment variables:
  AMADEUS_CLIENT_ID       (required)
  AMADEUS_CLIENT_SECRET   (required)

  BREVO_API_KEY           (for email)
  FROM_EMAIL              (Brevo-verified sender)
  FROM_NAME               (e.g. "NZ AU Fare Bot")
  TO_EMAIL                (recipient)

  SCAN_MONTHS             (default 3)
  FLEX_DAYS               (default 2)
  MIN_RET_DAYS            (default 8)
  MAX_RET_DAYS            (default 12)
  DATE_STEP_DAYS          (default 10)
  PE_CAP                  (default 1300)
  J_CAP                   (default 1500)
  DRY_RUN                 ("1" = no email, "0" = send email)
  DEBUG                   ("1" = verbose logs)
"""

import os
import sys
import json
import time
import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import requests

# ---------- Helpers for env / logging ----------

def getenv_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def getenv_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


DEBUG = getenv_bool("DEBUG", False)


def dlog(msg: str) -> None:
    if DEBUG:
        print(msg)


# ---------- Config ----------

ROUTES: List[Tuple[str, str]] = [
    ("AKL", "SYD"),
    ("AKL", "MEL"),
]

CITY_BY_IATA: Dict[str, str] = {
    "AKL": "Auckland",
    "SYD": "Sydney",
    "MEL": "Melbourne",
}

SCAN_MONTHS = getenv_int("SCAN_MONTHS", 3)
FLEX_DAYS = getenv_int("FLEX_DAYS", 2)
MIN_RET_DAYS = getenv_int("MIN_RET_DAYS", 8)
MAX_RET_DAYS = getenv_int("MAX_RET_DAYS", 12)
DATE_STEP_DAYS = getenv_int("DATE_STEP_DAYS", 10)

PE_CAP = Decimal(str(getenv_int("PE_CAP", 1300)))
J_CAP = Decimal(str(getenv_int("J_CAP", 1500)))

DRY_RUN = getenv_bool("DRY_RUN", True)

# ---------- Amadeus auth + call ----------

AMADEUS_CLIENT_ID = os.getenv("AMADEUS_CLIENT_ID")
AMADEUS_CLIENT_SECRET = os.getenv("AMADEUS_CLIENT_SECRET")

AMADEUS_TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
AMADEUS_FLIGHT_OFFERS_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"


def get_amadeus_token() -> Optional[str]:
    if not AMADEUS_CLIENT_ID or not AMADEUS_CLIENT_SECRET:
        print("❌ Missing AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET", file=sys.stderr)
        return None

    dlog("[DEBUG] Requesting Amadeus token…")
    try:
        resp = requests.post(
            AMADEUS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": AMADEUS_CLIENT_ID,
                "client_secret": AMADEUS_CLIENT_SECRET,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Amadeus auth failed: {e}", file=sys.stderr)
        return None

    try:
        token = resp.json().get("access_token")
    except Exception:
        print("❌ Amadeus auth: invalid JSON response", file=sys.stderr)
        return None

    if not token:
        print("❌ Amadeus auth: no access_token in response", file=sys.stderr)
        return None

    return token


def amadeus_search(
    token: str,
    origin: str,
    dest: str,
    dep_date: str,
    ret_date: str,
) -> Optional[Dict[str, Any]]:
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest,
        "departureDate": dep_date,
        "returnDate": ret_date,
        "adults": 1,
        "currencyCode": "NZD",
        "max": 50,
        # Restrict to Air New Zealand only
        "includedAirlineCodes": "NZ",
    }
    headers = {"Authorization": f"Bearer {token}"}

    dlog(f"[DEBUG] Amadeus GET {AMADEUS_FLIGHT_OFFERS_URL} {params}")

    try:
        resp = requests.get(
            AMADEUS_FLIGHT_OFFERS_URL,
            headers=headers,
            params=params,
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        print(f"[WARN] Amadeus HTTP {resp.status_code} for {origin}->{dest} {dep_date}/{ret_date}: {e}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"[WARN] Amadeus request error for {origin}->{dest} {dep_date}/{ret_date}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] Amadeus unexpected error for {origin}->{dest} {dep_date}/{ret_date}: {e}", file=sys.stderr)

    return None


# ---------- Parsing / cabin / filters ----------

def extract_cabin(offer: Dict[str, Any]) -> str:
    """
    Try hard to pull the main cabin:
      - travelerPricings[].fareDetailsBySegment[].cabin
      - itineraries[].segments[].cabin (fallback)
    Returns upper-case cabin string or "UNKNOWN".
    """
    # 1) travelerPricings path
    tps = offer.get("travelerPricings") or []
    for tp in tps:
        for fd in tp.get("fareDetailsBySegment") or []:
            cab = fd.get("cabin")
            if cab:
                return str(cab).upper()

    # 2) itineraries/segments path
    itins = offer.get("itineraries") or []
    for itin in itins:
        for seg in itin.get("segments") or []:
            cab = seg.get("cabin") or seg.get("cabinClass")
            if cab:
                return str(cab).upper()

    return "UNKNOWN"


def extract_price_nzd(offer: Dict[str, Any]) -> Optional[Decimal]:
    try:
        price = offer.get("price") or {}
        if price.get("currency") != "NZD":
            # Different currency – you could convert, but for now just skip
            return None
        return Decimal(price.get("grandTotal"))
    except (InvalidOperation, TypeError):
        return None


def extract_carrier(offer: Dict[str, Any]) -> str:
    # Air NZ only, but still helpful to see code in logs
    itins = offer.get("itineraries") or []
    if itins:
        segs = itins[0].get("segments") or []
        if segs:
            return segs[0].get("carrierCode", "NZ")
    return "NZ"


def build_grabaseat_link(origin: str, dest: str) -> str:
    # Placeholder; real deep links are gross.
    return "https://www.grabaseat.co.nz/"


def city_label(code: str) -> str:
    name = CITY_BY_IATA.get(code, "")
    return f"{code} ({name})" if name else code


def collect_rows_for_pair(
    token: str,
    origin: str,
    dest: str,
    start_date: dt.date,
    end_date: dt.date,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    cur = start_date
    while cur <= end_date:
        for ret_gap in range(MIN_RET_DAYS, MAX_RET_DAYS + 1):
            dep = cur
            ret = cur + dt.timedelta(days=ret_gap)

            dep_str = dep.isoformat()
            ret_str = ret.isoformat()

            data = amadeus_search(token, origin, dest, dep_str, ret_str)
            if not data:
                continue

            offers = data.get("data") or []
            dlog(f"[DEBUG] {origin}->{dest} {dep_str}/{ret_str}: {len(offers)} offers")

            for off in offers:
                cabin = extract_cabin(off)
                price = extract_price_nzd(off)
                carrier = extract_carrier(off)

                if cabin not in ("PREMIUM_ECONOMY", "BUSINESS"):
                    dlog(f"[DEBUG] Reject (not PE/J): {origin}->{dest} {cabin} {price or 'N/A'} {carrier}")
                    continue

                if price is None:
                    dlog(f"[DEBUG] Reject (no NZD price): {origin}->{dest} {cabin}")
                    continue

                if cabin == "PREMIUM_ECONOMY" and price > PE_CAP:
                    dlog(f"[DEBUG] Reject (PE above cap): {origin}->{dest} {cabin} {price}")
                    continue
                if cabin == "BUSINESS" and price > J_CAP:
                    dlog(f"[DEBUG] Reject (J above cap): {origin}->{dest} {cabin} {price}")
                    continue

                rows.append(
                    {
                        "origin": origin,
                        "dest": dest,
                        "dep": dep,
                        "ret": ret,
                        "cabin": cabin,
                        "price": price,
                        "carrier": carrier,
                        "link": build_grabaseat_link(origin, dest),
                    }
                )

            # Be nice to Amadeus test API
            time.sleep(0.4)

        cur += dt.timedelta(days=DATE_STEP_DAYS)

    return rows


# ---------- HTML & email ----------

def nz_date(d: dt.date) -> str:
    return d.strftime("%d/%m/%y")


def format_money(n: Decimal) -> str:
    # thousands, 2dp
    return f"${n:,.2f}"


def render_html(rows: List[Dict[str, Any]], today: dt.date) -> str:
    title = f"NZ→AU Air NZ fares – {nz_date(today)}"

    if not rows:
        return (
            f"<h1 style=\"font-family:Arial,Helvetica,sans-serif;\">{title}</h1>"
            "<p>No qualifying Premium Economy / Business fares found in the configured window.</p>"
        )

    rows_sorted = sorted(rows, key=lambda r: (r["dep"], r["origin"], r["dest"], r["price"]))

    parts: List[str] = []
    parts.append(f"<h1 style=\"font-family:Arial,Helvetica,sans-serif;\">{title}</h1>")
    if rows:
        window_end = max(r["ret"] for r in rows)
    else:
        window_end = today
    parts.append(
        f"<p>Window: {nz_date(today)} → {nz_date(window_end)}&nbsp; |&nbsp;"
        f"Thresholds: Prem Econ ≤ {format_money(PE_CAP)}, Business ≤ {format_money(J_CAP)}</p>"
    )

    parts.append(
        "<table style=\"border-collapse:collapse; font-family:Arial,Helvetica,sans-serif; "
        "font-size:13px; width:100%;\">"
        "<thead>"
        "<tr style=\"background-color:#eeeeee;\">"
        "<th style=\"text-align:left; padding:6px 8px;\">Route</th>"
        "<th style=\"text-align:left; padding:6px 8px;\">Dates</th>"
        "<th style=\"text-align:left; padding:6px 8px;\">Cabin</th>"
        "<th style=\"text-align:left; padding:6px 8px;\">Price (NZD)</th>"
        "<th style=\"text-align:left; padding:6px 8px;\">Carrier</th>"
        "<th style=\"text-align:left; padding:6px 8px;\">Link</th>"
        "</tr>"
        "</thead><tbody>"
    )

    for r in rows_sorted:
        dep = nz_date(r["dep"])
        ret = nz_date(r["ret"])
        route = f"{city_label(r['origin'])} → {city_label(r['dest'])}"
        cabin_label = "Premium Economy" if r["cabin"] == "PREMIUM_ECONOMY" else "Business"
        price_html = f"<span style='color:#2e7d32; font-weight:bold;'>{format_money(r['price'])}</span>"
        carrier = r["carrier"]
        link = r["link"]

        parts.append(
            "<tr>"
            f"<td style='padding:4px 8px;'>{route}</td>"
            f"<td style='padding:4px 8px;'>{dep} → {ret}</td>"
            f"<td style='padding:4px 8px;'>{cabin_label}</td>"
            f"<td style='padding:4px 8px;'>{price_html}</td>"
            f"<td style='padding:4px 8px;'>{carrier}</td>"
            f"<td style='padding:4px 8px;'><a href='{link}'>Search</a></td>"
            "</tr>"
        )

    parts.append("</tbody></table>")
    return "".join(parts)


def send_brevo_email(subject: str, html: str) -> bool:
    api_key = os.getenv("BREVO_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    to_email = os.getenv("TO_EMAIL")
    from_name = os.getenv("FROM_NAME", "NZ AU Fare Bot")

    if not api_key or not from_email or not to_email:
        print("❌ Missing Brevo config (BREVO_API_KEY / FROM_EMAIL / TO_EMAIL); skipping email.", file=sys.stderr)
        return False

    payload = {
        "sender": {"email": from_email, "name": from_name},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }

    try:
        resp = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": api_key,
            },
            data=json.dumps(payload),
            timeout=20,
        )
        if 200 <= resp.status_code < 300:
            print(f"✅ Brevo email sent: {resp.status_code}")
            return True
        print(f"❌ Brevo email failed: {resp.status_code} {resp.text}", file=sys.stderr)
    except requests.RequestException as e:
        print(f"❌ Brevo request error: {e}", file=sys.stderr)
    return False


# ---------- main ----------

def main() -> None:
    today = dt.date.today()
    print("🚀 NZ→AU Air NZ fare watcher (Amadeus test API)")

    token = get_amadeus_token()
    if not token:
        return

    window_end = today + dt.timedelta(days=SCAN_MONTHS * 30)
    all_rows: List[Dict[str, Any]] = []

    for (orig, dest) in ROUTES:
        dlog(f"[DEBUG] Scanning route {orig}->{dest} from {today} to {window_end}")
        rows = collect_rows_for_pair(token, orig, dest, today, window_end)
        all_rows.extend(rows)

    print(f"Found {len(all_rows)} qualifying rows after cabin + price caps.")

    html_body = render_html(all_rows, today)

    out_path = os.path.join(os.getcwd(), "out_nz_au.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_body)
    print(f"Wrote {out_path}")

    subject = f"NZ→AU Air NZ fares – {nz_date(today)}"

    if DRY_RUN:
        print("DRY_RUN=1 → not sending email. HTML preview:\n")
        print(subject)
        print()
        print(html_body[:1200])
    else:
        send_brevo_email(subject, html_body)


if __name__ == "__main__":
    main()
