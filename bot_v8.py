#!/usr/bin/env python3
"""
Polymarket Edge Bot v8 — Public /markets + CLOB Orderbook
- Fetches ALL markets via paginated /markets (no auth needed)
- Filters for truly active, non-archived markets
- Gets live prices via CLOB orderbook API
- Caches prices to avoid rate limits
"""
import os, time, json, hmac, hashlib, base64, urllib.request, urllib.error
from datetime import datetime, timezone

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

# ── Market cache (refresh every 5 min) ──────────────────────────
_cache       = []
_cache_time  = 0
CACHE_TTL    = 300  # 5 min

def get_all_active_markets():
    """Fetch all active markets via paginated /markets endpoint."""
    global _cache, _cache_time
    
    now = time.time()
    if _cache and (now - _cache_time) < CACHE_TTL:
        L("Using cached markets (%d)" % len(_cache))
        return _cache
    
    all_markets = []
    cursor      = None
    
    while True:
        url = CLOB_HOST + "/markets?limit=1000"
        if cursor:
            url += "&cursor=" + urllib.request.quote(cursor)
        
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0"
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
            
            page = resp.get("data", [])
            all_markets.extend(page)
            
            cursor = resp.get("next_cursor")
            if not cursor or cursor == "MA==" or len(all_markets) >= resp.get("count", 0):
                break
        except Exception as e:
            L("Markets fetch error: %s" % e, "ERROR")
            break
    
    # Filter: active + not archived + has tokens with prices + end date not passed
    now_dt  = datetime.now(timezone.utc)
    active  = []
    for m in all_markets:
        if not isinstance(m, dict):
            continue
        if m.get("archived") or m.get("closed"):
            continue
        
        tokens = m.get("tokens", [])
        if not tokens or len(tokens) < 2:
            continue
        
        # Check price exists and is meaningful
        try:
            prices = [float(t.get("price", 0)) for t in tokens]
        except:
            continue
        
        if all(p == 0 for p in prices):
            continue
        
        # Check end date not passed
        end_str = m.get("end_date_iso") or m.get("endDateIso", "")
        if end_str:
            try:
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if end_dt < now_dt:
                    continue
            except:
                pass
        
        active.append(m)
    
    _cache     = active
    _cache_time = now
    L("Fetched %d total | %d active with prices" % (len(all_markets), len(active)))
    return active

# ── Get live CLOB price for a market ────────────────────────────
_price_cache       = {}
_price_cache_time  = {}

def get_clob_price(token_id):
    """Get best bid/ask from CLOB orderbook for a token."""
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
            _price_cache[token_id]     = mid
            _price_cache_time[token_id] = now
            return mid
        elif best_bid:
            _price_cache[token_id]     = best_bid
            _price_cache_time[token_id] = now
            return best_bid
    except Exception as e:
        pass
    return None

# ── Strategy ─────────────────────────────────────────────────────
MIN_YES   = 0.38
MIN_VOL   = 5_000
MIN_EDGE  = 0.30
SKIP_KWDS = {"trump", "biden", "harris", "election", "president", "federal",
              "senate", "congress", "governor", "republican", "democratic"}

def calc_edge(yes_p, conv=0.8):
    return max(0, (1 - yes_p) * conv)

def position_size(yes_p, vol, category="Unknown"):
    e = calc_edge(yes_p, min(0.95, 0.5 + (1 - yes_p) * 0.6))
    if e < MIN_EDGE: return 0
    if e >= 0.60: sz = MAX_POS
    elif e >= 0.45: sz = MAX_POS * 0.70
    elif e >= 0.30: sz = MAX_POS * 0.40
    else: return 0
    q = category.lower()
    if any(k in q for k in SKIP_KWDS): return 0
    cat_mults = {"Sports": 1.0, "Entertainment": 1.0, "Science": 1.0,
                 "Economics": 0.5, "Other": 0.7, "Crypto": 1.0, "Culture": 1.0,
                 "Technology": 1.0}
    mult = cat_mults.get(category, 0.7)
    return min(sz * mult, MAX_POS)

def fee_est(yes_p, sz):
    return (sz / yes_p) * 0.02 if yes_p > 0 else 0

def should_trade(m, yes_price):
    try:
        vol = float(m.get("volume24hr", 0) or 0)
        q   = (m.get("question", "") + " " + (m.get("category", "") or "")).lower()
        if any(k in q for k in SKIP_KWDS): return False
        edge = calc_edge(yes_price)
        return yes_price < MIN_YES and edge >= MIN_EDGE and vol >= MIN_VOL
    except: return False

def score_it(m, yes_price):
    return calc_edge(yes_price)

# ── Place order via CLOB ─────────────────────────────────────────
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
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()[:200]
        return False, "", "HTTP %d: %s" % (e.code, body_err)
    except Exception as e:
        return False, "", str(e)

# ── Main ─────────────────────────────────────────────────────────
cycle = 0
L("Bot v8 -- /markets pagination + CLOB orderbook | mode=%s | interval=%ds" % (MODE, INTERVAL))

while True:
    cycle += 1
    L("Cycle %d..." % cycle)
    
    if daily_loss() >= MAX_LOSS:
        L("MAX DAILY LOSS -- standing down")
        time.sleep(INTERVAL)
        continue
    
    markets = get_all_active_markets()
    
    if not markets:
        L("No active markets found, sleeping %ds" % INTERVAL)
        time.sleep(INTERVAL)
        continue
    
    # Score all markets
    scored = []
    for m in markets:
        tokens = m.get("tokens", [])
        if not tokens:
            continue
        # Try each YES token
        for i, t in enumerate(tokens):
            tid    = t.get("token_id", "")
            outcome = t.get("outcome", "").lower()
            if outcome not in ("yes", "1"):
                continue
            try:
                yes_p = float(t.get("price", 0))
            except:
                continue
            if yes_p <= 0 or yes_p >= 1:
                continue
            e = calc_edge(yes_p)
            if e < MIN_EDGE:
                continue
            if should_trade(m, yes_p):
                scored.append((m, yes_p, e, tid))
    
    if not scored:
        L("No opportunities (%d active markets scanned)" % len(markets))
        time.sleep(INTERVAL)
        continue
    
    # Sort by edge desc
    scored.sort(key=lambda x: x[2], reverse=True)
    best, yes_p, edge, token_id = scored[0]
    m            = best
    tokens       = m.get("tokens", [])
    condition_id = m.get("condition_id", "")
    q            = best.get("question", "?")[:80]
    vol          = float(best.get("volume24hr", 0) or 0)
    cat          = best.get("category", "Other") or "Other"
    sz           = position_size(yes_p, vol, cat)
    fe           = fee_est(yes_p, sz)
    net          = (1 - yes_p) * (sz / yes_p) - fe if yes_p > 0 else 0
    spread       = abs(yes_p - (1 - yes_p))
    
    L("OPP: %s" % q)
    L("  YES=%.4f edge=%.2f spread=%.3f | vol=$%d | sz=$%.2f [%s]" % (
        yes_p, edge, spread, int(vol), sz, cat))
    L("  Fee=$%.2f net_exp=%+.2f" % (fe, net))
    
    if MODE == "auto" and sz >= 1.0 and net > 0:
        ok, oid, status = place_order(condition_id, "YES", yes_p, sz)
        if ok:
            msg = "FILLED\nBUY YES\n%s\nPrice: %.4f\nSize: $%.2f\nEdge: %.2f\nID: %s" % (
                q[:50], yes_p, sz, edge, oid[:20])
            tg("<b>%s</b>" % msg)
            L("  -> FILLED %s" % oid)
        else:
            tg("<b>FAILED</b>\n%s\n%s" % (q[:50], status))
            L("  -> %s" % status)
    else:
        if net <= 0:
            L("  [SKIP] fee > edge")
        else:
            L("  [ALERT] edge=%.2f sz=$%.2f" % (edge, sz))
    
    time.sleep(INTERVAL)
