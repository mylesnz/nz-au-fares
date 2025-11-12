#!/usr/bin/env python3
"""
NZ→AU Air New Zealand fare watcher (dummy version).

- Reads simple config from environment variables
- Generates synthetic NZ→AU round-trip fares (AKL–SYD / AKL–MEL)
- Filters by cabin + price thresholds
- Builds an HTML email body
- Writes it to out_nz_au.html in the current working directory
- Prints a preview to stdout
"""

import os
import datetime as dt
from typing import List, Dict, Any
import html


# ----------------------------
# Helpers / configuration
# ----------------------------

def getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def today_nz() -> dt.date:
    # Close enough for this watcher; you don't need timezone math here
    return dt.date.today()


def nz_date(d: dt.date) -> str:
    return d.strftime("%d/%m/%y")


CITY_NAMES = {
    "AKL": "Auckland",
    "SYD": "Sydney",
    "MEL": "Melbourne",
    "CHC": "Christchurch",
    "WLG": "Wellington",
}

def route_label(orig: str, dest: str) -> str:
    o_name = CITY_NAMES.get(orig, orig)
    d_name = CITY_NAMES.get(dest, dest)
    return f"{orig} ({o_name}) → {dest} ({d_name})"


# ----------------------------
# Dummy data fetcher
# ----------------------------

def fetch_dummy_fares(start: dt.date, end: dt.date) -> List[Dict[str, Any]]:
    """
    Stand-in for a real Air NZ / Grabaseat scraper.

    Returns a few synthetic rows so you can:
    - exercise HTML rendering
    - test GitHub Actions
    - validate thresholds & formatting
    """
    out1 = start + dt.timedelta(days=14)
    ret1 = out1 + dt.timedelta(days=7)

    out2 = start + dt.timedelta(days=30)
    ret2 = out2 + dt.timedelta(days=10)

    out3 = start + dt.timedelta(days=45)
    ret3 = out3 + dt.timedelta(days=5)

    return [
        {
            "origin": "AKL",
            "dest": "SYD",
            "depart_date": out1,
            "return_date": ret1,
            "cabin": "Premium Economy",
            "price_nzd": 899,
            "carrier": "NZ",
            "link": "https://www.grabaseat.co.nz/",  # dummy
        },
        {
            "origin": "AKL",
            "dest": "MEL",
            "depart_date": out2,
            "return_date": ret2,
            "cabin": "Business",
            "price_nzd": 1899,
            "carrier": "NZ",
            "link": "https://www.grabaseat.co.nz/",
        },
        {
            "origin": "AKL",
            "dest": "SYD",
            "depart_date": out3,
            "return_date": ret3,
            "cabin": "Business",
            "price_nzd": 1399,
            "carrier": "NZ",
            "link": "https://www.grabaseat.co.nz/",
        },
    ]


# ----------------------------
# HTML rendering
# ----------------------------

def build_html(
    rows: List[Dict[str, Any]],
    start: dt.date,
    end: dt.date,
    pe_cap: int,
    j_cap: int,
) -> str:
    today = today_nz()

    parts: List[str] = []
    parts.append(
        f"<h1 style=\"font-family:Arial,Helvetica,sans-serif;\">"
        f"NZ→AU Air NZ fares – {nz_date(today)}</h1>"
    )
    parts.append(
        "<p>"
        f"Window: {nz_date(start)} → {nz_date(end)}&nbsp; |&nbsp;"
        f"Thresholds: Prem Econ ≤ ${pe_cap}, Business ≤ ${j_cap}"
        "</p>"
    )

    if not rows:
        parts.append("<p>No fares under the configured thresholds were found.</p>")
        return "\n".join(parts)

    parts.append(
        "<table style=\"border-collapse:collapse; font-family:Arial,Helvetica,sans-serif; "
        "font-size:13px; width:100%;\">"
    )
    parts.append(
        "  <thead>"
        "    <tr style=\"background-color:#eeeeee;\">"
        "      <th style=\"text-align:left; padding:6px 8px;\">Route</th>"
        "      <th style=\"text-align:left; padding:6px 8px;\">Dates</th>"
        "      <th style=\"text-align:left; padding:6px 8px;\">Cabin</th>"
        "      <th style=\"text-align:left; padding:6px 8px;\">Price (NZD)</th>"
        "      <th style=\"text-align:left; padding:6px 8px;\">Carrier</th>"
        "      <th style=\"text-align:left; padding:6px 8px;\">Link</th>"
        "    </tr>"
        "  </thead>"
        "  <tbody>"
    )

    for r in rows:
        origin = r["origin"]
        dest = r["dest"]
        dep = r["depart_date"]
        ret = r["return_date"]
        cabin = r["cabin"]
        price = r["price_nzd"]
        carrier = r.get("carrier", "NZ")
        link = r.get("link", "#")

        route_str = route_label(origin, dest)
        dates_str = f"{nz_date(dep)} → {nz_date(ret)}"

        # Colour by threshold
        if cabin.lower().startswith("prem"):
            under_cap = price <= pe_cap
        elif cabin.lower().startswith("bus"):
            under_cap = price <= j_cap
        else:
            under_cap = False

        colour = "#2e7d32" if under_cap else "#000000"
        price_html = f"<span style='color:{colour}; font-weight:bold;'>${price:,.0f}</span>"

        row_html = (
            "    <tr>"
            f"<td style='padding:4px 8px;'>{html.escape(route_str)}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(dates_str)}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(cabin)}</td>"
            f"<td style='padding:4px 8px;'>{price_html}</td>"
            f"<td style='padding:4px 8px;'>{html.escape(carrier)}</td>"
            f"<td style='padding:4px 8px;'><a href='{html.escape(link)}'>Search</a></td>"
            "</tr>"
        )
        parts.append(row_html)

    parts.append("  </tbody>")
    parts.append("</table>")

    return "\n".join(parts)


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    # Config from env with sane defaults
    scan_months = getenv_int("SCAN_MONTHS", 6)
    pe_cap = getenv_int("PE_CAP", 1300)
    j_cap = getenv_int("J_CAP", 1500)

    dry_run = os.getenv("DRY_RUN", "1") == "1"
    debug = os.getenv("DEBUG", "0") == "1"

    today = today_nz()
    start = today
    end = today + dt.timedelta(days=scan_months * 30)

    if debug:
        print("🚀 NZ→AU Air NZ fare watcher (dummy data)")

    # Fetch synthetic rows
    rows = fetch_dummy_fares(start, end)
    if debug:
        print(
            f"Fetched {len(rows)} synthetic rows between "
            f"{start.isoformat()} and {end.isoformat()}"
        )

    # Apply thresholds
    filtered: List[Dict[str, Any]] = []
    for r in rows:
        cabin = r["cabin"]
        price = r["price_nzd"]
        if cabin.lower().startswith("prem") and price <= pe_cap:
            filtered.append(r)
        elif cabin.lower().startswith("bus") and price <= j_cap:
            filtered.append(r)

    if debug:
        print(f"After thresholds: {len(filtered)} rows")

    html_body = build_html(filtered, start, end, pe_cap, j_cap)

    # Always write the HTML file to the current working directory
    out_path = os.path.join(os.getcwd(), "out_nz_au.html")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html_body)
        print(f"Wrote {out_path}")
    except Exception as e:
        print(f"❌ Failed to write {out_path}: {e}")

    # And echo a preview
    print("DRY_RUN=1 → not sending email. HTML preview:\n")
    print(f"NZ→AU Air NZ fares – {nz_date(today)}\n")
    print(html_body)


if __name__ == "__main__":
    main()
