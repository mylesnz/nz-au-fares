#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AKL ⇄ SYD / MEL price watch (Air New Zealand only)
- Window: next N months (default 6)
- Cabins: Premium Economy (W) ≤ NZ$1300, Business (C) ≤ NZ$1500
- Currency: NZD
- Provider: Kiwi.com Tequila (https://tequila.kiwi.com/)
- Output: HTML grouped by month (NZ date dd/mm/yy)
- Optional delivery: POST to WEBHOOK_URL (e.g., Zapier)

Env vars:
  TEQUILA_API_KEY   = <required>
  MONTHS_AHEAD      = 6
  PREM_MAX_NZD      = 1300
  BUS_MAX_NZD       = 1500
  ROUTES            = AKL:SYD,AKL:MEL    (customizable; colon-separated pairs)
  DRY_RUN           = 1                  (no webhook POST if set)
  WEBHOOK_URL       = https://hooks.zapier.com/hooks/catch/....
  RATE_LIMIT_MS     = 250
  DEBUG             = 0/1

Usage:
  export TEQUILA_API_KEY=sk_xxx
  python3 nz_trans_tasman_price_watch.py
"""

import os
import time
import json
import math
import html
import urllib.parse as urlparse
import datetime as dt
import ssl
import urllib.request

# ---------- Config ----------
TEQUILA_KEY   = os.getenv("TEQUILA_API_KEY", "").strip()
TEQUILA_URL   = "https://tequila-api.kiwi.com/v2/search"

MONTHS_AHEAD  = int(os.getenv("MONTHS_AHEAD", "6"))
PREM_MAX      = int(os.getenv("PREM_MAX_NZD", "1300"))
BUS_MAX       = int(os.getenv("BUS_MAX_NZD", "1500"))
RATE_LIMIT_MS = int(os.getenv("RATE_LIMIT_MS", "250"))
DRY_RUN       = int(os.getenv("DRY_RUN", "1"))
DEBUG         = int(os.getenv("DEBUG", "0"))

# Routes default: AKL→SYD, AKL→MEL (round trips found by API)
ROUTES_ENV    = os.getenv("ROUTES", "AKL:SYD,AKL:MEL")
ROUTES        = [tuple(r.strip().split(":")) for r in ROUTES_ENV.split(",") if ":" in r]

WEBHOOK_URL   = os.getenv("WEBHOOK_URL", "").strip()

# Airport name mapping for email display
AIRPORT_NAME = {
    "AKL": "Auckland",
    "SYD": "Sydney",
    "MEL": "Melbourne",
}

CABIN_LABEL = {
    "W": "Premium Economy",
    "C": "Business",
}

CABIN_MAX_NZD = {
    "W": PREM_MAX,
    "C": BUS_MAX,
}

# ---------- Helpers ----------
def today_nz():
    # Auckland time for “today” visual; search itself uses absolute ranges
    # We’ll use naive NZ date only for display.
    # For simplicity, format as dd/mm/yy.
    now_utc = dt.datetime.now(dt.timezone.utc)
    nz = dt.timezone(dt.timedelta(hours=13))  # NZDT assumption in Nov; acceptable for display
    return now_utc.astimezone(nz).date()

def nz_fmt(d: dt.date) -> str:
    return d.strftime("%d/%m/%y")

def add_months(d: dt.date, months: int) -> dt.date:
    # simple month add (no tz)
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    day = min(d.day, [31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,30,31,30,31,31,30,31,30,31][month-1])
    return dt.date(year, month, day)

def http_get_json(url: str, headers: dict, timeout=30):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=headers)
    if DEBUG:
        print("[GET]", url)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        if DEBUG:
            print("! JSON parse failed; raw:", raw[:400])
        raise

def month_key(d: dt.date) -> str:
    return d.strftime("%Y-%m")

def parse_date(s: str) -> dt.date:
    # Tequila frequently returns local departure/return in route; we’ll read itinerary dates from 'local_departure'
    # but for display we only need date portion.
    # Accept 'YYYY-MM-DD' or ISO 'YYYY-MM-DDTHH:MM:SS.SZ'
    if "T" in s:
        s = s.split("T", 1)[0]
    return dt.date.fromisoformat(s)

def price_nzd(item) -> int:
    # Tequila 'price' is typically in requested currency (NZD)
    return int(math.ceil(item.get("price", 0)))

def build_link(item) -> str:
    # Tequila deep_link typically present
    link = item.get("deep_link")
    return link or "#"

def safe(s: str) -> str:
    return html.escape(str(s), quote=True)

# ---------- Search ----------
def tequila_search_roundtrip(origin: str, dest: str, cabin: str, start: dt.date, end: dt.date) -> list:
    """
    Round-trip search across a date window. We rely on Tequila to return best options.
    Filters:
      - select_airlines=NZ
      - selected_cabins = W or C
      - flight_type=round
      - max_stopovers=0 (prefer nonstop; NZ runs AKL-SYD/MEL direct)
      - curr=NZD
    """
    if not TEQUILA_KEY:
        raise RuntimeError("TEQUILA_API_KEY missing")

    params = {
        "fly_from": origin,
        "fly_to": dest,
        "date_from": start.strftime("%d/%m/%Y"),  # Kiwi expects dd/mm/YYYY
        "date_to": end.strftime("%d/%m/%Y"),
        "flight_type": "round",
        "selected_cabins": cabin,               # W=PremEco, C=Business
        "select_airlines": "NZ",
        "select_airlines_exclude": "false",
        "max_stopovers": 0,
        "curr": "NZD",
        "sort": "price",
        "limit": 200,
        # "nights_in_dst_from": 2,  # Optional: constrain stay length if desired
        # "nights_in_dst_to": 30,
    }
    qs = urlparse.urlencode(params)
    url = f"{TEQUILA_URL}?{qs}"
    headers = {"apikey": TEQUILA_KEY, "accept": "application/json"}
    data = http_get_json(url, headers)
    return data.get("data", [])

def within_cap(cabin: str, price: int) -> bool:
    cap = CABIN_MAX_NZD.get(cabin, 0)
    return price <= cap

def extract_itinerary(item, cabin: str, origin: str, dest: str):
    # Tequila round-trip returns 'route' array with multiple segments.
    # Find outbound first leg and inbound last leg.
    rts = item.get("route", [])
    if not rts:
        return None

    # Outbound: first segment matching flyFrom=origin
    # Inbound: last segment matching flyTo=origin
    out_leg = None
    ret_leg = None
    for seg in rts:
        if seg.get("flyFrom") == origin:
            out_leg = seg if out_leg is None else out_leg
        if seg.get("flyTo") == origin:
            ret_leg = seg  # keep updating, last one will be final return

    if not out_leg or not ret_leg:
        # Fallback: use local_departure of first/last segment
        d_out = parse_date(rts[0]["local_departure"])
        d_ret = parse_date(rts[-1]["local_departure"])
    else:
        d_out = parse_date(out_leg["local_departure"])
        d_ret = parse_date(ret_leg["local_departure"])

    # Mixed cabin filter: try to detect via 'fare_category' or 'fare_classes'
    # Not perfect, but if Tequila marks 'fare_category' at top-level, use it.
    # Otherwise accept and rely on selected_cabins filter.
    top_fare_cat = item.get("fare_category")  # 'M','W','C','F' or None
    if top_fare_cat and top_fare_cat != cabin:
        return None  # exclude mixed cabin surfaced as cheaper

    price = price_nzd(item)
    if not within_cap(cabin, price):
        return None

    return {
        "origin": origin,
        "dest": dest,
        "depart_date": d_out,
        "return_date": d_ret,
        "cabin": cabin,
        "price_nzd": price,
        "link": build_link(item),
        "airline": "NZ",
    }

def scan_routes():
    start = dt.date.today()
    end = add_months(start, MONTHS_AHEAD)
    results = []  # list of itineraries

    for (orig, dest) in ROUTES:
        for cabin in ("W", "C"):  # Premium Economy, Business
            try:
                items = tequila_search_roundtrip(orig, dest, cabin, start, end)
            except Exception as e:
                print(f"❌ API error {orig}->{dest} ({CABIN_LABEL[cabin]}): {e}")
                items = []

            seen = 0
            hit = 0
            for it in items:
                seen += 1
                rec = extract_itinerary(it, cabin, orig, dest)
                if rec:
                    results.append(rec)
                    hit += 1

            print(f"{orig}->{dest} {CABIN_LABEL[cabin]}: {hit}/{seen} priced within cap")
            time.sleep(RATE_LIMIT_MS / 1000.0)

    return results

# ---------- HTML ----------
def month_groups(hits):
    buckets = {}
    for h in hits:
        k = month_key(h["depart_date"])
        buckets.setdefault(k, []).append(h)
    # sort each bucket by price then date
    for k in buckets:
        buckets[k].sort(key=lambda x: (x["price_nzd"], x["depart_date"], x["return_date"]))
    return dict(sorted(buckets.items()))

def nz_month_label(ym: str) -> str:
    y, m = ym.split("-")
    dtm = dt.date(int(y), int(m), 1)
    return dtm.strftime("%B %Y")

def badge_color(cabin: str, price: int) -> str:
    cap = CABIN_MAX_NZD[cabin]
    if price <= cap:
        # two tiers for fun: <=80% of cap is green, else amber
        if price <= int(0.8 * cap):
            return "#16a34a"  # green
        return "#f59e0b"      # amber
    return "#9ca3af"          # grey (shouldn’t appear)

def cabin_name(cabin: str) -> str:
    return CABIN_LABEL.get(cabin, cabin)

def airport_display(code: str) -> str:
    nm = AIRPORT_NAME.get(code, code)
    return f"{nm} ({code})"

def to_tr(h):
    price = h["price_nzd"]
    cab = h["cabin"]
    dep = nz_fmt(h["depart_date"])
    ret = nz_fmt(h["return_date"])
    route = f"{airport_display(h['origin'])} → {airport_display(h['dest'])}"
    link = safe(h["link"])
    col = badge_color(cab, price)
    return (
        f"<tr>"
        f"<td>{route}</td>"
        f"<td>{dep} → {ret}</td>"
        f"<td>{safe(cabin_name(cab))}</td>"
        f"<td><span style='color:{col};font-weight:600;'>NZ${price:,}</span></td>"
        f"<td><a href='{link}'>Book / Check</a></td>"
        f"</tr>"
    )

def render_html(hits):
    today = today_nz()
    groups = month_groups(hits)

    # summary
    w_hits = [h for h in hits if h["cabin"] == "W"]
    c_hits = [h for h in hits if h["cabin"] == "C"]
    w_best = min([h["price_nzd"] for h in w_hits], default=None)
    c_best = min([h["price_nzd"] for h in c_hits], default=None)

    def pill(txt, bg):
        return f"<span style='background:{bg};color:#111;padding:4px 8px;border-radius:999px;font-size:12px;margin-right:6px'>{safe(txt)}</span>"

    html_parts = []
    html_parts.append(f"<h1 style='font-family:Arial,Helvetica,sans-serif'>AKL ⇄ SYD/MEL — Air New Zealand award cash fares (next {MONTHS_AHEAD} months)</h1>")
    html_parts.append("<p style='font-family:Arial,Helvetica,sans-serif;margin:6px 0'>Filters: NZ only • Premium Economy ≤ NZ$%d • Business ≤ NZ$%d • Round-trips • Direct flights</p>" % (PREM_MAX, BUS_MAX))
    html_parts.append("<p style='font-family:Arial,Helvetica,sans-serif;margin:6px 0'>Run: %s (NZ)</p>" % nz_fmt(today))
    pills = []
    pills.append(pill(f"Premium Economy best: {('NZ$%s' % format(w_best, ',d')) if w_best else '—'}", "#86efac"))
    pills.append(pill(f"Business best: {('NZ$%s' % format(c_best, ',d')) if c_best else '—'}", "#fde68a"))
    html_parts.append("<p>%s</p>" % " ".join(pills))

    if not hits:
        html_parts.append("<p style='font-family:Arial,Helvetica,sans-serif'>No results within caps.</p>")
        return "\n".join(html_parts)

    # tables by month
    style = (
        "table{border-collapse:collapse;width:100%;font-family:Arial,Helvetica,sans-serif}"
        "th,td{border:1px solid #e5e7eb;padding:8px;text-align:left;font-size:14px}"
        "th{background:#f9fafb}"
        "h2{font-family:Arial,Helvetica,sans-serif;margin:18px 0 8px 0}"
    )
    html_parts.append(f"<style>{style}</style>")

    for ym, rows in groups.items():
        html_parts.append(f"<h2>{nz_month_label(ym)}</h2>")
        html_parts.append("<table>")
        html_parts.append("<tr><th>Route</th><th>Dates (Depart → Return)</th><th>Cabin</th><th>Price</th><th>Link</th></tr>")
        for r in rows:
            html_parts.append(to_tr(r))
        html_parts.append("</table>")

    return "\n".join(html_parts)

# ---------- Delivery ----------
def maybe_post_webhook(subject: str, html_body: str):
    if not WEBHOOK_URL:
        return (None, "WEBHOOK_URL not set; skipping POST.")

    payload = {
        "subject": subject,
        "html": html_body,
        "alert": False
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    req = urllib.request.Request(WEBHOOK_URL, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8", errors="ignore")
            return (status, body)
    except Exception as e:
        # Alert fallback
        alert = {
            "subject": f"ALERT: NZ Trans-Tasman delivery failed – {dt.date.today().isoformat()}",
            "html": f"Primary webhook delivery failed: {safe(str(e))}",
            "alert": True
        }
        try:
            req2 = urllib.request.Request(WEBHOOK_URL, data=json.dumps(alert).encode("utf-8"),
                                          headers=headers, method="POST")
            with urllib.request.urlopen(req2, timeout=10) as resp2:
                return ("alert-sent", resp2.getcode())
        except Exception as e2:
            return (None, f"Alert send failed: {e2}")

# ---------- Main ----------
def main():
    print(f"Scanning next {MONTHS_AHEAD} months for AKL⇄SYD/MEL (NZ only)…")
    hits = scan_routes()
    # Write HTML
    html_body = render_html(hits)
    out_path = "out-nz-trans.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_body)
    print(f"Wrote {out_path} ({len(hits)} rows).")

    subject = f"NZ Trans-Tasman Price Watch – {dt.date.today().isoformat()}"
    if DRY_RUN:
        print("DRY_RUN=1 → skip webhook POST.")
        print(subject, "\n")
        print(html_body[:1000] + ("\n…(truncated)…" if len(html_body) > 1000 else ""))
        return

    st, body = maybe_post_webhook(subject, html_body)
    print("Webhook result:", st, str(body)[:400])

if __name__ == "__main__":
    main()
