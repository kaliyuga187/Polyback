#!/usr/bin/env python3
"""
Polymarket Edge Bot v12 — Basic auth fix + live orderbook scanning
"""
import os, time, json, base64, urllib.request, urllib.error
from datetime import datetime, timezone

WALLET    = os.getenv("POLYMARKET_WALLET", "")
TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN", "8781978143:AAG7_arVJ6f5mrWsyzxxiT2qEx-OXGdv75s")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "6594416344")
MODE      = os.getenv("POLYMARKET_MODE", "auto")
INTERVAL  = int(os.getenv("POLYMARKET_INTERVAL", "60"))
MAX_POS   = float(os.getenv("POLYMARKET_MAX_POSITION", "50"))
MAX_LOSS  = float(os.getenv("POLYMARKET_MAX_DAILY_LOSS", "20"))
LOG_FILE  = "/root/.openclaw/polymarket-bot.log"
CLOB_HOST = "https://clob.polymarket.com"
KEY_ID    = "ded32731-5e0c-049e-c6bd-5c48c5d81467"
KEY_SECRET = "fVzssxHayQp9KbrnU0y3WTJFjV3Fk6pc1rABMJBBIYI="
KEY_PASS  = "8899e71e9ca19337d99bb4bd5fa9282d0b0b99d9ef086f58546aa08b98704325"

def L(msg, lv="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = "[%s] [%s] %s" % (ts, lv, msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f: f.write(line + "\n")
    except: pass

def tg(msg):
    if not TOKEN or not CHAT_ID: return
    try:
        d = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % TOKEN,
            data=d, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
    except: pass

def rd(p):
    try:
        with open(p) as f: return json.load(f)
    except: return {}

def wr(p, d):
    with open(p, "w") as f: json.dump(d, f)

def daily_loss():
    d = rd("/root/.openclaw/daily_pnl.json")
    return d.get("loss", 0) if d.get("date") == str(datetime.now().date()) else 0

# ── Get live YES price from CLOB orderbook ──────────────────────────
def get_clob_yes_price(token_id):
    try:
        url = "%s/orderbook/%s" % (CLOB_HOST, token_id)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            ob = json.loads(r.read())
        bids = ob.get("bids", []); asks = ob.get("asks", [])
        bb = float(bids[0]["price"]) if bids else 0
        ba = float(asks[0]["price"]) if asks else 0
        if bb and ba: return (bb + ba) / 2
        return bb if bb else None
    except: return None

# ── Place order via CLOB ──────────────────────────────────────────
def place_order(condition_id, side, price, size):
    outcome = 1 if side == "YES" else 0
    size_tok = str(round(size / price, 4)) if price > 0 else "0"
    order = {
        "market": condition_id, "side": "BUY", "outcome": outcome,
        "price": str(round(price, 4)), "size": size_tok,
        "orderType": {"type": "GTC"}, "account": WALLET.lower(),
    }
    body = json.dumps(order, separators=(",", ":"))
    creds = base64.b64encode((KEY_ID + ":" + KEY_SECRET).encode()).decode()
    hdrs = {
        "Content-Type": "application/json",
        "Authorization": "Basic " + creds,
    }
    try:
        req = urllib.request.Request(
            CLOB_HOST + "/orders",
            data=body.encode(), headers=hdrs, method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        if resp.get("orderID"):
            return True, resp["orderID"], resp.get("status", "")
        err = resp.get("error", {})
        emsg = err.get("message", str(err)) if isinstance(err, dict) else str(resp.get("message", str(err)))
        return False, "", emsg
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()[:200]
        return False, "", "HTTP %d: %s" % (e.code, body_err)
    except Exception as e:
        return False, "", str(e)

# ── Strategy ──────────────────────────────────────────────────────
MIN_EDGE = 0.30
MIN_VOL  = 5000
SKIP_KWDS = {"trump", "biden", "harris", "election", "president", "federal",
              "senate", "congress", "governor", "republican", "democratic"}

def calc_edge(yes_p, conv=0.8):
    return max(0, (1 - yes_p) * conv)

def position_size(yes_p, vol, cat):
    e = calc_edge(yes_p, min(0.95, 0.5 + (1 - yes_p) * 0.6))
    if e < MIN_EDGE: return 0
    sz = MAX_POS if e >= 0.60 else (MAX_POS * 0.70 if e >= 0.45 else MAX_POS * 0.40)
    if any(k in (cat or "").lower() for k in SKIP_KWDS): return 0
    return min(sz, MAX_POS)

def fee_est(yes_p, sz):
    return (sz * yes_p * 0.02) if yes_p > 0 else 0

def should_trade(q, yes_p, vol, cat):
    if yes_p < 0.001 or yes_p > 0.999: return False
    if calc_edge(yes_p) < MIN_EDGE: return False
    if vol < MIN_VOL: return False
    text = (q + " " + (cat or "")).lower()
    if any(k in text for k in SKIP_KWDS): return False
    return True

# ── Main ─────────────────────────────────────────────────────────
cycle = 0
L("Bot v12 -- Basic auth + live orderbook | mode=%s" % MODE)

while True:
    cycle += 1
    L("Cycle %d..." % cycle)

    if daily_loss() >= MAX_LOSS:
        L("MAX DAILY LOSS")
        time.sleep(INTERVAL); continue

    # Fetch all markets
    try:
        url  = "https://clob.polymarket.com/markets?limit=1000"
        req  = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        markets = resp.get("data", []) if isinstance(resp, dict) else (resp or [])
    except Exception as e:
        L("Fetch error: %s" % e, "ERROR")
        time.sleep(30); continue

    L("Scanning %d markets..." % len(markets))

    scored = []
    for m in markets:
        if not isinstance(m, dict): continue
        if m.get("archived"): continue
        tokens = m.get("tokens", [])
        if not tokens: continue

        yes_token = None
        for t in tokens:
            if (t.get("outcome") or "").lower() in ("yes", "1", 1):
                yes_token = t; break
        if not yes_token: continue

        try: api_yes = float(yes_token.get("price", 0))
        except: continue

        token_id = yes_token.get("token_id", "")
        live_yes = get_clob_yes_price(token_id) if token_id else None
        yes_p = live_yes if (live_yes and live_yes > 0) else api_yes

        if yes_p <= 0: continue

        q = m.get("question", "")
        vol = float(m.get("volume24hr", 0) or 0) or float(m.get("volume", 0) or 0)
        cat = m.get("category", "Other") or "Other"

        if not should_trade(q, yes_p, vol, cat): continue

        edge = calc_edge(yes_p)
        scored.append((m, yes_p, edge, token_id))

    if not scored:
        L("No opportunities (%d scanned)" % len(markets))
        time.sleep(INTERVAL); continue

    scored.sort(key=lambda x: x[2], reverse=True)
    best, yes_p, edge, token_id = scored[0]
    m = best
    q = best.get("question", "?")[:80]
    cid = best.get("condition_id", "")
    vol = float(best.get("volume24hr", 0) or 0) or float(best.get("volume", 0) or 0)
    cat = best.get("category", "Other") or "Other"
    sz = position_size(yes_p, vol, cat)
    fe = fee_est(yes_p, sz)
    net = (1 - yes_p) * sz - fe
    spread = abs(yes_p - (1 - yes_p))

    L("OPP: %s" % q)
    L("  YES=%.4f edge=%.2f spread=%.3f | vol=$%s | sz=$%.2f [%s]" % (
        yes_p, edge, spread, ("%d" % int(vol)).replace(",", "_"), sz, cat))
    L("  Net exp: %+.2f  fee: $%.2f" % (net, fe))

    if MODE == "auto" and sz >= 1.0 and net > 0 and cid:
        ok, oid, status = place_order(cid, "YES", yes_p, sz)
        if ok:
            tg("<b>FILLED</b>\nBUY YES\n%s\nPrice: %.4f\nSize: $%.2f\nEdge: %.2f" % (
                q[:50], yes_p, sz, edge))
            L("  -> FILLED %s" % oid)
        else:
            tg("<b>Signal</b>\n%s\nPrice: %.4f\nEdge: %.2f\n%s" % (q[:50], yes_p, edge, status))
            L("  -> %s" % status)
    elif net > 0:
        L("  [ALERT] edge=%.2f sz=$%.2f" % (edge, sz))
    else:
        L("  [SKIP] fee > edge")

    time.sleep(INTERVAL)
