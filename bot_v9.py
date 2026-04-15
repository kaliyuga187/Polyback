#!/usr/bin/env python3
"""
Polymarket Edge Bot v9 — Public markets page + CLOB trading
Uses Polymarket's public HTML to find truly active markets.
No API key needed for market discovery.
"""
import os, time, json, hmac, hashlib, base64, urllib.request, urllib.error, re
from datetime import datetime, timezone
from html.parser import HTMLParser

WALLET    = os.getenv("POLYMARKET_WALLET", "")
TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN", "8781978143:AAG7_arVJ6f5mrWsyzxxiT2qEx-OXGdv75s")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "6594416344")
MODE      = os.getenv("POLYMARKET_MODE", "auto")
INTERVAL  = int(os.getenv("POLYMARKET_INTERVAL", "120"))
MAX_POS   = float(os.getenv("POLYMARKET_MAX_POSITION", "50"))
MAX_LOSS  = float(os.getenv("POLYMARKET_MAX_DAILY_LOSS", "20"))
LOG_FILE  = "/root/.openclaw/polymarket-bot.log"
CLOB_HOST = "https://clob.polymarket.com"
KEY_ID    = "ded32731-5e0c-049e-c6bd-5c48c5d81467"
KEY_SECRET = "fVzssxHayQp9KbrnU0y3WTJFjV3Fk6pc1rABMJBBIYI="
KEY_PASS  = "8899e71e9ca19337d99bb4bd5fa9282d0b0b99d9ef086f58546aa08b98704325"

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

# ── Market discovery from Polymarket public page ──────────────────
MARKET_CACHE      = []
MARKET_CACHE_TIME = 0
CACHE_TTL         = 120  # 2 min

def get_active_markets():
    """Fetch active markets from Polymarket public API (no auth needed)."""
    global MARKET_CACHE, MARKET_CACHE_TIME
    
    now = time.time()
    if MARKET_CACHE and (now - MARKET_CACHE_TIME) < CACHE_TTL:
        return MARKET_CACHE
    
    markets = []
    
    # Try the public Polymarket markets endpoint (no auth)
    for offset in [0, 100, 200, 300]:
        try:
            url = "https://clob.polymarket.com/markets?limit=100&offset=%d" % offset
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
            
            page = resp.get("data", [])
            if not page:
                break
            
            for m in page:
                if not isinstance(m, dict):
                    continue
                
                # Only want markets that accept orders and aren't archived
                if m.get("archived"):
                    continue
                
                # Parse tokens
                tokens = m.get("tokens", [])
                if not tokens or len(tokens) < 2:
                    continue
                
                try:
                    yes_price = float(tokens[0].get("price", 0) or 0)
                    no_price  = float(tokens[1].get("price", 0) or 0)
                except:
                    continue
                
                # Skip resolved/unresolvable
                if yes_price == 0 and no_price == 0:
                    continue
                
                # Check end date not passed
                end_str = m.get("end_date_iso") or ""
                if end_str:
                    try:
                        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        if end_dt < datetime.now(timezone.utc):
                            continue
                    except:
                        pass
                
                markets.append(m)
            
            # If less than 100 returned, we're done
            if len(page) < 100:
                break
                
        except Exception as e:
            L("Market fetch error at offset %d: %s" % (offset, e))
            break
    
    # Dedupe
    seen = set()
    uniq = []
    for m in markets:
        cid = m.get("condition_id", "")
        if cid and cid not in seen:
            seen.add(cid)
            uniq.append(m)
    
    MARKET_CACHE      = uniq
    MARKET_CACHE_TIME = now
    L("Found %d unique active markets with prices" % len(uniq))
    return uniq

# ── CLOB price ────────────────────────────────────────────────────
_price_cache      = {}
_price_cache_time = {}

def get_clob_price(token_id):
    """Get mid price from CLOB orderbook."""
    global _price_cache, _price_cache_time
    
    now = time.time()
    if token_id in _price_cache and (now - _price_cache_time.get(token_id, 0)) < 30:
        return _price_cache[token_id]
    
    try:
        url = "%s/orderbook/%s" % (CLOB_HOST, token_id)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            ob = json.loads(r.read())
        
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        
        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 0
        
        if best_bid and best_ask:
            mid = (best_bid + best_ask) / 2
        elif best_bid:
            mid = best_bid
        else:
            mid = None
        
        if mid is not None:
            _price_cache[token_id]     = mid
            _price_cache_time[token_id] = now
        
        return mid
    except:
        return None

# ── Strategy ──────────────────────────────────────────────────────
MIN_YES   = 0.38
MIN_VOL   = 5_000
MIN_EDGE  = 0.30
SKIP_KWDS = {"trump", "biden", "harris", "election", "president", "federal",
             "senate", "congress", "governor", "republican", "democratic",
             "nominee", "nomination"}

def calc_edge(yes_p, conv=0.8):
    return max(0, (1 - yes_p) * conv)

def position_size(yes_p, vol, category="Other"):
    e = calc_edge(yes_p, min(0.95, 0.5 + (1 - yes_p) * 0.6))
    if e < MIN_EDGE: return 0
    if e >= 0.60: sz = MAX_POS
    elif e >= 0.45: sz = MAX_POS * 0.70
    elif e >= 0.30: sz = MAX_POS * 0.40
    else: return 0
    q = (category or "Other").lower()
    if any(k in q for k in SKIP_KWDS): return 0
    cat_mults = {"Sports": 1.0, "Entertainment": 1.0, "Science": 1.0,
                 "Economics": 0.5, "Crypto": 1.0, "Culture": 1.0,
                 "Technology": 1.0, "Other": 0.7}
    return min(sz * cat_mults.get(category, 0.7), MAX_POS)

def fee_est(yes_p, sz):
    return (sz / yes_p) * 0.02 if yes_p > 0 else 0

def should_trade(m, yes_p):
    try:
        vol = float(m.get("volume24hr", 0) or 0)
        q   = ((m.get("question", "") or "") + " " + (m.get("category", "") or "")).lower()
        if any(k in q for k in SKIP_KWDS): return False
        return yes_p < MIN_YES and calc_edge(yes_p) >= MIN_EDGE and vol >= MIN_VOL
    except: return False

def score_it(m, yes_p):
    return calc_edge(yes_p)

# ── CLOB order ─────────────────────────────────────────────────────
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
    body = json.dumps(order, separators=(",", ":"))
    msg  = ts + "POST" + "/orders" + body
    sig  = hmac.new(KEY_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    hdrs = {
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
        req = urllib.request.Request(CLOB_HOST + "/orders", data=body.encode(), headers=hdrs)
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        if resp.get("orderID"):
            return True, resp["orderID"], resp.get("status", "")
        err  = resp.get("error", {})
        emsg = err.get("message", str(err)) if isinstance(err, dict) else str(resp.get("message", str(err)))
        return False, "", emsg
    except urllib.error.HTTPError as e:
        return False, "", "HTTP %d" % e.code
    except Exception as e:
        return False, "", str(e)

# ── Main ───────────────────────────────────────────────────────────
cycle = 0
L("Bot v9 -- Polymarket public page + CLOB trading | mode=%s" % MODE)

while True:
    cycle += 1
    L("Cycle %d..." % cycle)
    
    if daily_loss() >= MAX_LOSS:
        L("MAX DAILY LOSS -- standing down")
        time.sleep(INTERVAL)
        continue
    
    markets = get_active_markets()
    
    if not markets:
        L("No active markets found, retrying in 60s")
        time.sleep(60)
        continue
    
    # Score all markets
    scored = []
    for m in markets:
        tokens = m.get("tokens", [])
        for i, t in enumerate(tokens):
            outcome = (t.get("outcome") or "").lower()
            if outcome not in ("yes", "1", 1):
                continue
            try:
                yes_p = float(t.get("price", 0))
            except:
                continue
            if yes_p <= 0.001 or yes_p >= 0.999:
                continue
            if should_trade(m, yes_p):
                scored.append((m, yes_p, score_it(m, yes_p), t.get("token_id", "")))
    
    if not scored:
        L("No opportunities (%d active markets scanned)" % len(markets))
        time.sleep(INTERVAL)
        continue
    
    scored.sort(key=lambda x: x[2], reverse=True)
    best, yes_p, edge, token_id = scored[0]
    m             = best
    condition_id  = m.get("condition_id", "")
    q             = best.get("question", "?")[:80]
    vol           = float(best.get("volume24hr", 0) or 0)
    cat           = best.get("category", "Other") or "Other"
    sz            = position_size(yes_p, vol, cat)
    fe            = fee_est(yes_p, sz)
    net           = (1 - yes_p) * (sz / yes_p) - fe if yes_p > 0 else 0
    
    L("BEST: %s" % q)
    L("  YES=%.4f edge=%.2f vol=$%d sz=$%.2f [%s]" % (yes_p, edge, int(vol), sz, cat))
    L("  Net exp: %+.2f fee=$%.2f" % (net, fe))
    
    if MODE == "auto" and sz >= 1.0 and net > 0:
        ok, oid, status = place_order(condition_id, "YES", yes_p, sz)
        if ok:
            tg("<b>FILLED</b>\nBUY YES\n%s\nPrice: %.4f\nSize: $%.2f\nEdge: %.2f" % (
                q[:50], yes_p, sz, edge))
            L("  -> FILLED %s" % oid)
        else:
            tg("<b>Signal</b>\n%s\nPrice: %.4f\nEdge: %.2f\nStatus: %s" % (
                q[:50], yes_p, edge, status))
            L("  -> %s" % status)
    else:
        if net <= 0:
            L("  [SKIP] fee > edge")
        else:
            L("  [ALERT] edge=%.2f sz=$%.2f" % (edge, sz))
    
    time.sleep(INTERVAL)
