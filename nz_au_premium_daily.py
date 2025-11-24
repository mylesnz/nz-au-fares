#!/usr/bin/env python3
import urllib.request, urllib.error, json, ssl, time, datetime, os, traceback

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "unknown@example.com")
PE_PRICE_CAP = int(os.getenv("PE_PRICE_CAP", "650"))
CABIN_CLASS = os.getenv("CABIN_CLASS", "premiumeconomy")
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
    for a in range(1, RETRIES+1):
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
            r = safe_get(urllib.request.Request(u, headers={"User-Agent":"Mozilla"}))
            if not r: 
                fares.append({"o":o,"d":d,"err":True}); continue
            try:
                data = json.loads(r).get("fares", [])
                for x in data:
                    x["deal"] = x.get("price", 99999) <= PE_PRICE_CAP
                fares.extend(data)
            except: fares.append({"o":o,"d":d,"err":True})
    return fares

def html(f):
    if not f: return "<p>No fares found</p>"
    rows=""
    for x in f:
        if "err" in x:
            rows+="<tr style='color:red'><td>*</td><td>*</td><td>ERROR</td></tr>"
        else:
            c=(" style='font-weight:bold;color:green'" if x.get("deal") else
               " style='color:orange'")
            rows+=f"<tr{c}><td>{x['origin']}</td><td>{x['destination']}</td><td>{x['price']} {x['currency']}</td></tr>"
    return (f"<h3>NZ→AU Premium Economy</h3>"
            f"<p>{datetime.date.today()}</p>"
            "<table border='1'><tr><th>From</th><th>To</th><th>Price</th></tr>"
            f"{rows}</table>")

def send(sub, body):
    if DRY_RUN: return True
    if not BREVO_API_KEY: log("No API key","error"); return False
    p = json.dumps({
      "sender": {"name": "PE Bot", "email": "noreply@example.com"},
      "to": [{"email": RECIPIENT_EMAIL}],
      "subject": sub,
      "htmlContent": body,
    }).encode("utf-8")
    h = {"Content-Type":"application/json","api-key":BREVO_API_KEY}
    try:
        with urllib.request.urlopen(
          urllib.request.Request("https://api.brevo.com/v3/smtp/email",
                                data=p,headers=h,method="POST"),
          context=ssl_ctx
        ) as r:
            return 200 <= r.status < 300
    except Exception as e: log(str(e),"error"); return False

if __name__ == "__main__":
    log("Start")
    try:
        f=fetch()
        s=f"Premium Deals {datetime.date.today()}"
        ok=send(s, html(f))
        log("Sent" if ok else "Fail","error" if not ok else "info")
    except Exception as e:
        log(traceback.format_exc(),"error")
    log("Done")

