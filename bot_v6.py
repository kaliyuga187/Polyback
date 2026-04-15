#!/usr/bin/env python3
"""
Polymarket Edge v6 — Metagrill + refined BIAS strategy
Uses gamma.metagrill.com for live + historical market data.
Strategy update from 13-market backtest:
  - Politics (US federal): SKIP — 0% win rate, market efficient
  - Sports/Niche: full size
  - Economics: reduced size
  - Min edge raised to 0.30 (from 0.20)
"""
import os, time, json, hmac, hashlib, base64
from datetime import datetime, timezone
from urllib.request import Request, urlopen

WALLET     = os.getenv("POLYMARKET_WALLET", "")
TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "8781978143:AAG7_arVJ6f5mrWsyzxxiT2qEx-OXGdv75s")
CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID", "6594416344")
MODE       = os.getenv("POLYMARKET_MODE", "auto")
INTERVAL   = int(os.getenv("POLYMARKET_INTERVAL", "60"))
MAX_POS    = float(os.getenv("POLYMARKET_MAX_POSITION", "50"))
MAX_LOSS   = float(os.getenv("POLYMARKET_MAX_DAILY_LOSS", "20"))
LOG_FILE   = "/root/.openclaw/polymarket-bot.log"
META       = "https://gamma.metagrill.com"
CLOB       = "https://clob.polymarket.com"
HDRS       = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
KEY_ID     = "ded32731-5e0c-049e-c6bd-5c48c5d81467"
KEY_SECRET = "fVzssxHayQp9KbrnU0y3WTJFjV3Fk6pc1rABMJBBIYI="
KEY_PASS   = "8899e71e9ca19337d99bb4bd5fa9282d0b0b99d9ef086f58546aa08b98704335"

import sys
sys.path.insert(0, "/usr/local/lib/python3.12/dist-packages")
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

_creds = ApiCreds(api_key=KEY_ID, api_secret=KEY_SECRET, api_passphrase=KEY_PASS)
_clob  = ClobClient(host=CLOB, creds=_creds, chain_id=137)

# ── Helpers ────────────────────────────────────────────────────
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
        req = Request("https://api.telegram.org/bot%s/sendMessage" % TOKEN,
                      data=d, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
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

def session_pnl():
    return rd("/root/.openclaw/session_pnl.json").get("pnl", 0.0)

# ── Metagrill: live + historical data ─────────────────────────
def get_live_markets(n=2000):
    """Fetch from Metagrill. Has settlement history + live prices."""
    try:
        req = Request("%s/markets?limit=%d" % (META, n), headers=HDRS)
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        mkts = data if isinstance(data, list) else data.get("data", [])
        now  = datetime.now(timezone.utc)
        live = []
        for m in mkts:
            op = m.get("outcomePrices", [])
            try:
                yes = float(op[0]); no = float(op[1])
            except: continue
            if yes < 0.00001 and no < 0.00001: continue
            end_str = m.get("endDate", "")
            expired = False
            if end_str:
                try:
                    end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    expired = end_dt < now
                except: pass
            if expired: continue
            vol = float(m.get("volume", 0) or 0)
            live.append({
                "id": m.get("id", ""),
                "conditionId": m.get("conditionId", ""),
                "question": m.get("question", ""),
                "category": m.get("category", "Unknown") or "Unknown",
                "volume": vol,
                "endDate": end_str,
                "outcomePrices": {"YES": str(yes), "NO": str(no)},
                "yes": yes, "no": no,
            })
        L("Metagrill: %d live non-void markets" % len(live))
        return live
    except Exception as e:
        L("Metagrill error: %s" % e)
        return []

# ── Strategy: refined BIAS v6 ─────────────────────────────────
MIN_YES  = 0.38
MIN_VOL  = 5_000
MIN_EDGE = 0.30
SKIP_CATS = {"Politics", "US Politics", "US Federal"}

def calc_edge(yes_p, conv=0.8):
    return (1 - yes_p) * conv

def position_size(yes_p, vol, category="Unknown"):
    e = calc_edge(yes_p, min(0.95, 0.5 + (1 - yes_p) * 0.6))
    if e < MIN_EDGE: return 0
    if e >= 0.60: sz = MAX_POS
    elif e >= 0.45: sz = MAX_POS * 0.70
    elif e >= 0.30: sz = MAX_POS * 0.40
    else: return 0
    if category in SKIP_CATS: return 0
    cat_mults = {"Sports": 1.0, "Entertainment": 1.0, "Science": 1.0,
                 "Economics": 0.5, "Other": 0.7, "Unknown": 0.5}
    mult = cat_mults.get(category, 0.7)
    return min(sz * mult, vol * 0.05 if vol > 0 else MAX_POS)

def should_trade(m):
    try:
        yes = float(m.get("yes", 0))
        vol = float(m.get("volume", 0))
        cat = m.get("category", "Unknown") or "Unknown"
        if cat in SKIP_CATS: return False
        return yes < MIN_YES and calc_edge(yes) >= MIN_EDGE and vol >= MIN_VOL
    except: return False

def score_it(m):
    try: return calc_edge(float(m.get("yes", 0)))
    except: return 0

def fee_est(yes_p, sz):
    return (sz / yes_p) * 0.02 if yes_p > 0 else 0

def place_order(token_id, side, price, size):
    outcome  = 1 if side == "YES" else 0
    size_tok = str(round(size / price, 4)) if price > 0 else "0"
    ts       = str(int(time.time() * 1000))
    order    = {
        "market": token_id, "side": "BUY", "outcome": outcome,
        "price": str(round(price, 4)), "size": size_tok,
        "orderType": {"type": "GTC"}, "account": WALLET.lower(),
        "expireAt": int(ts) + 86400000,
    }
    body = json.dumps(order, separators=(",", ":"))
    msg  = ts + "POST" + "/orders" + body
    sig  = hmac.new(KEY_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    hdrs = {
        "Content-Type": "application/json", "Accept": "application/json",
        "POLY-API-KEY": KEY_ID, "POLY-API-SECRET": KEY_SECRET,
        "POLY-API-PASSPHRASE": KEY_PASS,
        "POLY-API-TIMESTAMP": ts, "POLY-API-NONCE": ts,
        "POLY-API-SIGNATURE": base64.b64encode(sig).decode(),
    }
    try:
        req = Request(CLOB + "/orders", data=body.encode(), headers=hdrs)
        with urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        if resp.get("orderID"):
            return True, resp["orderID"], resp.get("status", "")
        err = resp.get("error", {})
        emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return False, "", emsg
    except Exception as e:
        return False, "", str(e)

def run():
    if daily_loss() >= MAX_LOSS:
        L("MAX DAILY LOSS -- standing down")
        return

    markets = get_live_markets()
    opps    = sorted([m for m in markets if should_trade(m)],
                     key=score_it, reverse=True)

    if not opps:
        L("No opportunities (%d live markets scanned)" % len(markets))
        return

    best = opps[0]
    yes  = float(best.get("yes", best["outcomePrices"]["YES"]))
    no   = float(best.get("no",  best["outcomePrices"]["NO"]))
    vol  = float(best.get("volume", 0))
    q    = best.get("question", "?")
    cid  = best.get("conditionId", best.get("id", ""))
    cat  = best.get("category", "Unknown")
    e    = score_it(best)
    sz   = position_size(yes, vol, cat)
    spr  = abs(yes - no)
    end  = best.get("endDate", "")[:10]
    fe   = fee_est(yes, sz)
    net  = (1 - yes) * (sz / yes) - fe

    L("BUY YES | %s" % q[:65])
    L("  YES=%.3f NO=%.3f spread=%.3f | vol=$%s | edge=%.2f | sz=$%.2f [%s]" % (
        yes, no, spr, ("%d" % int(vol)).replace(",", "_"), e, sz, cat))
    L("  Fee=$%.2f | Net exp: %+.2f" % (fe, net))

    if MODE == "auto" and sz >= 1.0 and net > 0:
        ok, oid, status = place_order(cid, "YES", yes, sz)
        if ok:
            msg = "FILLED\nBUY YES\n%s\nPrice: %.3f\nSize: $%.2f\nEdge: %.2f\nID: %s" % (
                q[:50], yes, sz, e, oid[:20])
            tg("<b>%s</b>" % msg)
            L("  -> %s" % oid)
        else:
            tg("<b>FAILED</b>\n%s\n%s" % (q[:50], status))
            L("  -> %s" % status)
    else:
        if net <= 0:
            L("  [SKIP] fee > expected edge")
        else:
            L("  [ALERT] edge=%.2f sz=$%.2f" % (e, sz))

cycle = 0
L("Bot v6 -- Metagrill + refined BIAS v6 | min_edge=0.30 | mode=%s" % MODE)
while True:
    cycle += 1
    L("Cycle %d..." % cycle)
    try:
        run()
    except Exception as ex:
        L("Error: %s" % ex, "ERROR")
    time.sleep(INTERVAL)
