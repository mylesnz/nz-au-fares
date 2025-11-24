#!/usr/bin/env python3
import urllib.request, urllib.error, json, ssl, time, datetime, os, traceback

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "unknown@example.com")
PE_PRICE_CAP = int(os.getenv("PE_PRICE_CAP", "650"))
CABIN_CLASS = "premium-economy"
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

FROM_PORTS = ["AKL"]
TO_PORTS = ["SYD", "MEL", "BNE"]
RETRIES = 3
BACKOFF_SECONDS = 3
LOG_FILE = "/tmp/grabaseat.log"

ssl_ctx = ssl.create_default_context()

def log(msg, level="info"):
    if LOG_LEVEL == "error" and level != "error": return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}")
    try:
        with open(LOG_FILE, "a") as f: f.write(f"[{stamp}] {msg}\n")
    except: pass

def safe_get(req):
    url = req.full_url
    for a in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=20, context=ssl_ctx) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            log(f"HTTP {e.code} {url}", "error")
            if e.code == 404: break
        except Exception as e:
            log(str(e), "error")
        time.sleep(a * BACKOFF_SECONDS)
    return None

def fetch():
    fares = []
    for o in FROM_PORTS:
        for d in TO_PORTS:
            u = (f"https://www.grabaseat.co.nz/api/v2/flights/fares?"
                 f"origin={o}&destination={d}&cabin={CABIN_CLASS}")
            r = safe_get(urllib.request.Request(u, headers={"User-Agent": "Mozilla"}))
            if not r:
                fares.append({"o": o, "d": d, "err": True})
                continue
            try:
                data = json.loads(r).get("fares", [])
                for x in data:
                    x["deal"] = x.get("price", 99999) <= PE_PRICE_CAP
                fares.extend(data)
            except:
                fares.append({"o": o, "d": d, "err": True})
    return fares

def html(f):
    date = datetime.date.today().strftime("%d/%m/%y")
    if not f:
        return f"<h3>No Premium Economy fares found – {date}</h3>"

    rows = ""
    for x in f:
        if "err" in x:
            rows += "<tr style='color:red'><td>*</td><td>*</td><td>ERROR</td></tr>"
        else:
            c = (" style='font-weight:bold;color:green'" if x.get("deal") else
                 " style='color:orange'")
            rows += f"<tr{c}><td>{x['origin']}</td><td>{x['destination']}</td><td>{x['price']} {x['currency']}</td></tr>"

    return (f"<h3>NZ→AU Premium Economy – {date}</h3>"
            "<table border='1'><tr><th>From</th><th>To</th><th>Price</th></tr>"
            f"{rows}</table>")

def send(subject, body):
    if DRY_RUN:
        log("DRY_RUN enabled — email suppressed", "info")
        return True

    if not BREVO_API_KEY:
        log("Missing BREVO_API_KEY", "error")
        return False

    payload = json.dumps({
        "sender": {"name": "PE Bot", "email": RECIPIENT_EMAIL},
        "to": [{"email": RECIPIENT_EMAIL}],
        "subject": subject,
        "htmlContent": body,
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "api-key": BREVO_API_KEY,
    }

    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, context=ssl_ctx) as r:
            resp = r.read().decode("utf-8")
            log(f"Email status={r.status}", "info")
            log(f"Email response={resp}", "info")
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        log(f"Email HTTPError {e.code}: {e.read().decode('utf-8')}", "error")
    except Exception as e:
        log(f"Email send exception: {str(e)}", "error")

    return False

if __name__ == "__main__":
    log("Start")
    try:
        fares = fetch()
        date = datetime.date.today().strftime("%d/%m/%y")
        subject = f"NZ→AU Premium Economy Status – {date}"
        ok = send(subject, html(fares))
        log("Sent" if ok else "FAIL", "error" if not ok else "info")
    except Exception:
        log(traceback.format_exc(), "error")
    log("Done")

