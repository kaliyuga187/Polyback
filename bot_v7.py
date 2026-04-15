#!/usr/bin/env python3
"""
Polymarket Edge Bot v7 — CLOB + Polymarket Public GraphQL
Uses GraphQL for live market discovery + CLOB for price + CLOB for trading.
"""
import os, time, json, hmac, hashlib, base64, urllib.request
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

HDRS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

# ── Logging ────────────────────────────────────────────────────
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

# ── GraphQL: live markets from Polymarket public API ───────────
GRAPHQL_URL = "https://clob.polymarket.com/graphql"

def get_live_markets_graphql():
    """Fetch active markets via public GraphQL. Returns list of dicts with prices."""
    query = """
    {
      markets(
        filter: { state: "open", archived: false }
        limit: 50
      ) {
        id
        question
        description
        category
        marketType
        volume
        liquidity
        endDateIso
        outcomePrices
        outcomes
      }
    }
    """
    try:
        payload = json.dumps({"query": query}).encode()
        req = urllib.request.Request(
            GRAPHQL_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        items = resp.get("data", {}).get("markets", [])
        L("GraphQL: %d open markets fetched" % len(items))
        return items
    except Exception as e:
        L("GraphQL error: %s" % e, "ERROR")
        return []

# ── Strategy params ────────────────────────────────────────────
MIN_YES    = 0.38
MIN_VOL    = 5_000
MIN_EDGE   = 0.30
SKIP_KWDS  = {"trump", "biden", "harris", "election", "president", "federal",
              "senate", "congress", "governor"}
SKIP_CATS  = {"Politics", "US Politics"}

def calc_edge(yes_p, conv=0.8):
    return max(0, (1 - yes_p) * conv)

def position_size(yes_p, vol, category="Unknown"):
    e = calc_edge(yes_p, min(0.95, 0.5 + (1 - yes_p) * 0.6))
    if e < MIN_EDGE: return 0
    if e >= 0.60: sz = MAX_POS
    elif e >= 0.45: sz = MAX_POS * 0.70
    elif e >= 0.30: sz = MAX_POS * 0.40
    else: return 0
    # Skip high-visibility US politics
    q = category.lower()
    if any(k in q for k in SKIP_KWDS): return 0
    cat_mults = {"Sports": 1.0, "Entertainment": 1.0, "Science": 1.0,
                 "Economics": 0.5, "Other": 0.7, "Crypto": 1.0, "Culture": 1.0}
    mult = cat_mults.get(category, 0.7)
    return min(sz * mult, MAX_POS)

def fee_est(yes_p, sz):
    return (sz / yes_p) * 0.02 if yes_p > 0 else 0

def should_trade(m):
    try:
        prices_raw = m.get("outcomePrices", "")
        if isinstance(prices_raw, str):
            try:
                prices = json.loads(prices_raw.replace("'", '"'))
            except:
                prices = [0, 0]
        else:
            prices = prices_raw
        yes = float(prices[0]) if prices else 0
        vol = float(m.get("volume", 0) or 0)
        q   = m.get("question", "").lower()
        if any(k in q for k in SKIP_KWDS): return False
        if m.get("category", "") in SKIP_CATS: return False
        edge = calc_edge(yes)
        return yes < MIN_YES and edge >= MIN_EDGE and vol >= MIN_VOL
    except: return False

def score_it(m):
    try:
        prices = json.loads(m.get("outcomePrices", "[0,0]"))
        yes = float(prices[0]) if prices else 0
        return calc_edge(yes)
    except: return 0

# ── CLOB order book: get best bid/ask ──────────────────────────
def get_clob_price(condition_id):
    """Get real-time YES price from CLOB orderbook for a market."""
    try:
        url = "%s/orderbook/%s" % (CLOB_HOST, condition_id)
        req = urllib.request.Request(url, headers=HDRS)
        with urllib.request.urlopen(req, timeout=8) as r:
            ob = json.loads(r.read())
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 0
        if best_bid and best_ask:
            mid = (best_bid + best_ask) / 2
            L("  CLOB: bid=%.4f ask=%.4f mid=%.4f" % (best_bid, best_ask, mid))
            return mid
    except Exception as e:
        L("  CLOB price error: %s" % e)
    return None

# ── CLOB order placement ───────────────────────────────────────
def place_order(condition_id, side, price, size):
    outcome  = 1 if side == "YES" else 0
    size_tok = str(round(size / price, 4)) if price > 0 else "0"
    ts       = str(int(time.time() * 1000))
    order    = {
        "market": condition_id,
        "side": "BUY",
        "outcome": outcome,
        "price": str(round(price, 4)),
        "size": size_tok,
        "orderType": {"type": "GTC"},
        "account": WALLET.lower(),
        "expireAt": int(ts) + 86400000,
    }
    body  = json.dumps(order, separators=(",", ":"))
    msg   = ts + "POST" + "/orders" + body
    sig   = hmac.new(KEY_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    hdrs  = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "POLY-API-KEY": KEY_ID,
        "POLY-API-SECRET": KEY_SECRET,
        "POLY-API-PASSPHRASE": KEY_PASS,
        "POLY-API-TIMESTAMP": ts,
        "POLY-API-NONCE": ts,
        "POLY-API-SIGNATURE": base64.b64encode(sig).decode(),
    }
    try:
        req  = urllib.request.Request(CLOB_HOST + "/orders", data=body.encode(), headers=hdrs)
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        if resp.get("orderID"):
            return True, resp["orderID"], resp.get("status", "")
        err  = resp.get("error", {})
        emsg = err.get("message", str(err)) if isinstance(err, dict) else str(resp.get("message", str(err)))
        return False, "", emsg
    except Exception as e:
        return False, "", str(e)

# ── Main cycle ─────────────────────────────────────────────────
cycle = 0

L("Bot v7 -- GraphQL market discovery + CLOB trading | mode=%s" % MODE)

while True:
    cycle += 1
    L("Cycle %d..." % cycle)

    if daily_loss() >= MAX_LOSS:
        L("MAX DAILY LOSS -- standing down")
        time.sleep(INTERVAL)
        continue

    # Step 1: get live markets from public GraphQL
    markets = get_live_markets_graphql()

    if not markets:
        L("No markets from GraphQL, sleeping")
        time.sleep(INTERVAL)
        continue

    # Step 2: filter by strategy
    opps = sorted([m for m in markets if should_trade(m)], key=score_it, reverse=True)

    if not opps:
        L("No opportunities (%d markets scanned)" % len(markets))
        time.sleep(INTERVAL)
        continue

    best = opps[0]
    q    = best.get("question", "?")[:80]
    cid  = best.get("id", "")

    # Step 3: get live CLOB price for best opportunity
    prices_raw = best.get("outcomePrices", "[0,0]")
    try:
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        gamma_yes = float(prices[0])
    except:
        gamma_yes = 0

    clob_price = get_clob_price(cid)
    yes = clob_price if clob_price else gamma_yes
    no  = 1 - yes

    vol  = float(best.get("volume", 0) or 0)
    cat  = best.get("category", "Other") or "Other"
    e    = calc_edge(yes)
    sz   = position_size(yes, vol, cat)
    spr  = abs(yes - no)
    fe   = fee_est(yes, sz)
    net  = (1 - yes) * (sz / yes) - fe if yes > 0 else 0

    L("OPP: %s" % q)
    L("  GraphQL YES=%.3f | CLOB=%.4f | spread=%.3f | vol=$%s | edge=%.2f | sz=$%.2f [%s]" % (
        gamma_yes, yes if clob_price else 0, spr,
        ("%d" % int(vol)).replace(",", "_"), e, sz, cat))
    L("  Fee=$%.2f | Net exp: %+.2f" % (fe, net))

    if MODE == "auto" and sz >= 1.0 and net > 0:
        ok, oid, status = place_order(cid, "YES", yes, sz)
        if ok:
            msg = "FILLED\nBUY YES\n%s\nPrice: %.4f\nSize: $%.2f\nEdge: %.2f\nID: %s" % (
                q[:50], yes, sz, e, oid[:20])
            tg("<b>%s</b>" % msg)
            L("  -> FILLED %s" % oid)
        else:
            tg("<b>FAILED</b>\n%s\n%s" % (q[:50], status))
            L("  -> %s" % status)
    else:
        if net <= 0:
            L("  [SKIP] fee > edge")
        else:
            L("  [ALERT] edge=%.2f sz=$%.2f" % (e, sz))

    time.sleep(INTERVAL)
