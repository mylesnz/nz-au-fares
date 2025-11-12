#!/usr/bin/env python3
"""
Grabaseat daily fare scan (AKL↔SYD/MEL) for Premium Economy and Business.

• Window: next 6 months
• Trip: Return, 28–35 nights, ±3-day flex each side
• Carrier: Air New Zealand operated only
• Price caps (NZD): PremEco ≤ 1300, Business ≤ 1500
• Output: HTML grouped by month (NZ format dd/mm/yy)
• Delivery: Brevo (REST). Set DRY_RUN=1 to skip email and just write out.html

Env you should set (GitHub Secrets or local .env):
  FROM_EMAIL, FROM_NAME, TO_EMAIL, BREVO_API_KEY
Optional:
  DRY_RUN=1, DEBUG=1
"""

from __future__ import annotations
import os, sys, json, time, math, random, html, datetime as dt
import urllib.request, urllib.error

DEBUG   = bool(int(os.getenv("DEBUG", "0")))
DRY_RUN = bool(int(os.getenv("DRY_RUN", "0")))

FROM_EMAIL = os.getenv("FROM_EMAIL", "alerts@example.com")
FROM_NAME  = os.getenv("FROM_NAME",  "Grabaseat Bot")
TO_EMAIL   = os.getenv("TO_EMAIL")

BREVO_API_KEY = os.getenv("BREVO_API_KEY")  # xkeysib-...
BREVO_URL = "https://api.brevo.com/v3/smtp/email"

# --- Search parameters -------------------------------------------------------

NZ_TZ = dt.timezone(dt.timedelta(hours=13))  # NZDT default; dates are output-only

ORIGIN = "AKL"
PAIRS  = [("AKL", "SYD"), ("AKL", "MEL")]

CABINS = [
    ("Premium Economy", 1300),  # (cabinName, NZD ceiling)
    ("Business",         1500),
]

MONTHS_AHEAD   = 6
RET_MIN_NIGHTS = 28
RET_MAX_NIGHTS = 35
FLEX_DAYS      = 3

# Grabaseat API (observed public endpoint; no auth). We keep headers very plain.
GRABASEAT_ENDPOINT = "https://grabaseat.airnewzealand.co.nz/v1/flights/search"

# -----------------------------------------------------------------------------


def utc_today() -> dt.date:
    return dt.datetime.utcnow().date()


def nz_fmt(d: dt.date) -> str:
    return d.strftime("%d/%m/%y")


def td(text: str) -> str:
    return f"<td style='padding:6px 10px;border-bottom:1px solid #eee'>{text}</td>"


def th(text: str) -> str:
    return ("<th style='text-align:left;padding:8px 10px;"
            "border-bottom:2px solid #333;background:#fafafa'>"
            f"{text}</th>")


def http_post_json(url: str, payload: dict, timeout: int = 15) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # CORS/browser headers are not required for server-side calls.
        },
        method="POST",
    )
    if DEBUG:
        print(f"[POST] {url}\n{json.dumps(payload)[:400]}{' …' if len(json.dumps(payload))>400 else ''}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return json.loads(data.decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        if DEBUG:
            print(f"HTTP {e.code}: {e.reason}")
            try:
                print(e.read().decode())
            except Exception:
                pass
        return {}
    except Exception as ex:
        if DEBUG:
            print("POST error:", ex)
        return {}


def search_window(start_date: dt.date, months: int) -> tuple[dt.date, dt.date]:
    # end = start + months months (approx 30.4 days/month)
    days = int(months * 30.42)
    return start_date, start_date + dt.timedelta(days=days)


def daterange(start: dt.date, end: dt.date, step_days: int = 7):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=step_days)


def clamp(low, x, high):
    return max(low, min(x, high))


def build_search_payload(
    origin: str,
    dest: str,
    depart: dt.date,
    nights: int,
    flex: int,
    cabin: str,
) -> dict:
    # The endpoint accepts a date range string; we simulate ±flex by querying a short window
    dep_start = depart - dt.timedelta(days=flex)
    dep_end   = depart + dt.timedelta(days=flex)

    ret_date  = depart + dt.timedelta(days=nights)
    ret_start = ret_date - dt.timedelta(days=flex)
    ret_end   = ret_date + dt.timedelta(days=flex)

    return {
        "origin": origin,
        "destination": dest,
        "tripType": "return",
        "passengers": {"adults": 1},
        "cabin": cabin,  # "Premium Economy" or "Business"
        # Two legs with independent windows
        "dateRanges": {
            "outbound": f"{dep_start.isoformat()}T00:00:00Z/{dep_end.isoformat()}T23:59:59Z",
            "inbound":  f"{ret_start.isoformat()}T00:00:00Z/{ret_end.isoformat()}T23:59:59Z",
        },
        # Hard filters we apply again client-side just in case:
        "operators": ["NZ"],  # Air New Zealand
        "maxStops": 1,        # allow 0–1 if grabaseat returns via WLG/CHC etc.
    }


def parse_results(payload: dict) -> list[dict]:
    """
    Normalize a (possibly changing) response shape into a list of offers:
    { origin, dest, dep, ret, cabin, price_nzd, carrier, operated_by }
    """
    offers = []
    if not isinstance(payload, dict):
        return offers

    data = payload.get("results") or payload.get("data") or []
    for item in data:
        try:
            carrier = (item.get("marketingCarrier") or "").upper()
            operated = (item.get("operatedBy") or carrier).upper()
            cabin = item.get("cabin") or item.get("cabinClass") or ""
            total = item.get("price", {}).get("amount")
            currency = item.get("price", {}).get("currency")
            # dates
            dep = item.get("outbound", {}).get("date") or item.get("departDate")
            ret = item.get("inbound", {}).get("date") or item.get("returnDate")
            # route
            origin = item.get("origin") or item.get("from")
            dest = item.get("destination") or item.get("to")

            if not all([origin, dest, dep, ret, total, currency, cabin]):
                continue

            # convert price to NZD if currency stated; most grabaseat prices are NZD
            price_nzd = float(total) if (currency == "NZD" or currency is None) else float(total)

            offers.append({
                "origin": origin,
                "dest": dest,
                "dep": dt.date.fromisoformat(str(dep)[:10]),
                "ret": dt.date.fromisoformat(str(ret)[:10]),
                "cabin": cabin,
                "price_nzd": price_nzd,
                "carrier": carrier,
                "operated_by": operated,
                "link": item.get("deeplink") or item.get("url") or "https://grabaseat.co.nz",
            })
        except Exception:
            continue

    return offers


AIRPORT_NAME = {
    "AKL": "Auckland",
    "SYD": "Sydney",
    "MEL": "Melbourne",
}

def airport_label(iata: str) -> str:
    name = AIRPORT_NAME.get(iata, iata)
    return f"{iata} – {name}" if name != iata else iata


def within_caps(cabin: str, price_nzd: float) -> bool:
    for cab, cap in CABINS:
        if cab.lower() in cabin.lower():
            return price_nzd <= cap
    return False


def nz_month_key(d: dt.date) -> str:
    return d.strftime("%B %Y")  # e.g. “November 2025”


def colour_for(cabin: str, price: float) -> str:
    # green if well under cap (≤ cap * 0.85), amber if under cap, grey if over (won’t render anyway)
    cap = next(c for c in CABINS if c[0].lower() in cabin.lower())[1]
    if price <= cap * 0.85:
        return "#1a7f37"   # green
    return "#ad7f00"       # amber


def build_html(results: list[dict]) -> str:
    title = f"AKL ↔ SYD/MEL Premium & Business — {utc_today().isoformat()}"
    if not results:
        return f"""<h1 style="font-family:Arial">Grabaseat – {html.escape(title)}</h1>
<p>No fares matched your caps in the next six months.</p>"""

    # group by month of departure
    months = {}
    for r in results:
        key = nz_month_key(r["dep"])
        months.setdefault(key, []).append(r)

    parts = [f"<h1 style='font-family:Arial'>Grabaseat – {html.escape(title)}</h1>",
             "<p>Filters: Air NZ operated | PremEco ≤ $1,300 | Business ≤ $1,500 | Return 28–35 nights | ±3 days flex.</p>"]

    for m in sorted(months.keys(), key=lambda k: dt.datetime.strptime(k, "%B %Y")):
        rows = months[m]
        parts.append(f"<h2 style='font-family:Arial'>{html.escape(m)}</h2>")
        parts.append("<table style='border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;font-size:14px;width:100%;max-width:1000px'>")
        parts.append("<tr>" + "".join([
            th("Route"),
            th("Depart / Return"),
            th("Cabin"),
            th("Price (NZD)"),
            th("Operated by"),
            th("Link"),
        ]) + "</tr>")
        for r in sorted(rows, key=lambda x: (x["origin"], x["dest"], x["dep"], x["price_nzd"])):
            route = f"{airport_label(r['origin'])} → {airport_label(r['dest'])}"
            dates = f"{nz_fmt(r['dep'])} → {nz_fmt(r['ret'])}"
            colour = colour_for(r["cabin"], r["price_nzd"])
            price_html = f"<span style='color:{colour}'>${int(round(r['price_nzd']))}</span>"
            link = html.escape(r["link"])
            parts.append("<tr>" + "".join([
                td(html.escape(route)),
                td(html.escape(dates)),
                td(html.escape(r["cabin"])),
                td(price_html),
                td(html.escape(r["operated_by"])),
                td(f"<a href='{link}'>Book</a>"),
            ]) + "</tr>")
        parts.append("</table>")

    return "\n".join(parts)


def send_brevo(subject: str, html_body: str) -> tuple[bool, str]:
    if not BREVO_API_KEY:
        return False, "BREVO_API_KEY missing"
    payload = {
        "sender": {"email": FROM_EMAIL, "name": FROM_NAME},
        "to": [{"email": TO_EMAIL}],
        "subject": subject,
        "htmlContent": html_body,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BREVO_URL,
        data=body,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": BREVO_API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = 200 <= r.status < 300
            return ok, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()
        except Exception:
            detail = e.reason
        return False, f"HTTP {e.code} {detail}"
    except Exception as ex:
        return False, str(ex)


def run_scan() -> list[dict]:
    start, end = search_window(utc_today(), MONTHS_AHEAD)
    all_hits: list[dict] = []

    for (o, d) in PAIRS:
        for cabin, cap in CABINS:
            # Sample every ~7 days in the window; try a few stay lengths
            for depart in daterange(start, end, step_days=7):
                for nights in (RET_MIN_NIGHTS, (RET_MIN_NIGHTS + RET_MAX_NIGHTS)//2, RET_MAX_NIGHTS):
                    payload = build_search_payload(o, d, depart, nights, FLEX_DAYS, cabin)
                    data = http_post_json(GRABASEAT_ENDPOINT, payload)
                    offers = parse_results(data)

                    # Normalize + filter
                    for off in offers:
                        if "premium" in cabin.lower() and "premium" not in off["cabin"].lower():
                            continue
                        if "business" in cabin.lower() and "business" not in off["cabin"].lower():
                            continue
                        if off["operated_by"] != "NZ":
                            continue
                        if not within_caps(off["cabin"], off["price_nzd"]):
                            continue
                        all_hits.append(off)

                    # Be kind; avoid hammering
                    time.sleep(0.25 + random.random() * 0.15)

    return all_hits


def main():
    if not TO_EMAIL and not DRY_RUN:
        print("❌ TO_EMAIL is required (or set DRY_RUN=1).")
        sys.exit(1)

    results = run_scan()
    html_body = build_html(results)

    # Always write a local artifact for inspection
    with open("out.html", "w", encoding="utf-8") as f:
        f.write(html_body)
    print("Wrote out.html")

    subject = f"AKL↔SYD/MEL – Grabaseat scan – {utc_today().isoformat()}"
    if DRY_RUN:
        print("DRY_RUN=1: not emailing. Preview below:\n")
        print(subject + "\n")
        print(html_body[:1200] + ("…\n" if len(html_body) > 1200 else ""))
        return

    ok, msg = send_brevo(subject, html_body)
    if ok:
        print(f"✅ Email sent: {msg}")
    else:
        print(f"❌ Email failed: {msg}")
        sys.exit(2)


if __name__ == "__main__":
    main()
