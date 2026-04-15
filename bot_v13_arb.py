#!/usr/bin/env python3
"""
Polymarket Arbitrage Bot v13
===========================
Buys YES + NO in the same market when YES + NO < $1 (minus fees).
Risk-free profit = 1 - (yes_price + no_price) - fees

Requirements:
  pip install py-clob-client eth-account

Env vars needed in /root/.polymarket-env:
  POLYMARKET_PRIVATE_KEY=0x...   (from polymarket.com/settings/private-key)
  TELEGRAM_BOT_TOKEN=...          (optional, for alerts)
  TELEGRAM_CHAT_ID=...            (optional)
"""

import os, time, json, math, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

# ── ENV ────────────────────────────────────────────────────────────
ENV_FILE = Path("/root/.polymarket-env")
LOG_FILE = Path("/root/.openclaw/polymarket-bot.log")
PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
KEY_ID     = os.getenv("POLYMARKET_KEY_ID", "019d927b-2eb0-7b50-917f-a587685bc50f")
KEY_SECRET = os.getenv("POLYMARKET_KEY_SECRET", "ikAZCCZ6HQ2lPMRLktk5EQjzv4QC4KU03343q2xkpFM=")
KEY_PASS   = os.getenv("POLYMARKET_KEY_PASS", "396a0b6427ce9f83c61b0dbed6471ad099b4cd54c6d2f013a9e0ff98802b8982")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8781978143:AAG7_arVJ6f5mrWsyzxxiT2qEx-OXGdv75s")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "6594416344")
POLLING_SEC    = int(os.getenv("ARB_INTERVAL", "30"))
MIN_SPREAD_PCT = float(os.getenv("ARB_MIN_SPREAD", "0.015"))  # 1.5% min profit after fees
MAX_SPEND      = float(os.getenv("ARB_MAX_SPEND", "25"))       # $25 per side max
NETWORK        = 137  # Polygon

# ── LOGGING ────────────────────────────────────────────────────────
def L(msg, lv="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{lv}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.open("a").write(line + "\n")
    except: pass

def tg(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT: return
    try:
        d = json.dumps({"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data=d, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        L(f"TG error: {e}", "WARN")

# ── POLYMARKET CLOB CLIENT ────────────────────────────────────────
def get_clob_client(private_key):
    """Create authenticated CLOB client using L1 private key."""
    from py_clob_client.client import ClobClient
    from eth_account import Account

    acct = Account.from_key(private_key)
    address = acct.address

    client = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=NETWORK,
        key=private_key,
        signature_type=0,  # EOA
    )
    # createOrDeriveApiKey uses nonce=0; if key exists this retrieves it
    try:
        creds = client.create_or_derive_api_creds()
        L(f"L2 creds derived. API Key: {creds.get('apiKey', '?')[:12]}...")
    except Exception as e:
        L(f"Using existing creds (may auto-exist): {e}", "WARN")

    return client, address

# ── ORDERBOOK ───────────────────────────────────────────────────────
def get_prices(client, token_id):
    """Get YES and NO best bid/ask from orderbook."""
    try:
        ob = client.get_order_book(token_id)
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 0
        return best_bid, best_ask
    except Exception as e:
        return 0, 0

def get_market_prices(client, condition_id, yes_token_id, no_token_id):
    """Get mid prices for YES and NO in a market."""
    yes_bid, yes_ask = get_prices(client, yes_token_id)
    no_bid,  no_ask  = get_prices(client, no_token_id)

    # mid price = (best_bid + best_ask) / 2
    yes_mid = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else (yes_ask or 0)
    no_mid  = (no_bid  + no_ask)  / 2 if no_bid  and no_ask  else (no_ask  or 0)

    return yes_mid, no_mid, yes_bid, yes_ask, no_bid, no_ask

# ── ARB SCANNER ────────────────────────────────────────────────────
CLOB_HOST = "https://clob.polymarket.com"
DATA_HOST = "https://data-api.polymarket.com"
FEE_RATE  = 0.02  # 2% fee on winnings

def fetch_markets_via_clob():
    """Fallback: fetch markets directly from CLOB REST."""
    try:
        req = urllib.request.Request(
            f"{CLOB_HOST}/markets?limit=500",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        markets = resp.get("data", []) if isinstance(resp, dict) else (resp or [])
        active = [
            m for m in markets
            if not m.get("archived")
            and float(m.get("volume24hr", 0) or 0) > 0
        ]
        return active
    except Exception as e:
        L(f"CLOB fetch error: {e}", "ERROR")
        return []

def fetch_markets():
    """Try Data API first for live markets, fall back to CLOB."""
    # Try Data API — has live active markets
    try:
        import hmac, hashlib, time as time_module, base64 as b64
        ts = str(int(time_module.time() * 1000))
        # HMAC auth for data API
        msg = ts + "GET" + "/v1/markets"
        sig = hmac.new(
            KEY_SECRET.encode(), msg.encode(), hashlib.sha256
        ).digest()
        hdrs = {
            "POLY-API-KEY": KEY_ID,
            "POLY-API-SECRET": KEY_SECRET,
            "POLY-API-TIMESTAMP": ts,
            "POLY-API-NONCE": ts,
            "POLY-API-SIGNATURE": b64.b64encode(sig).decode(),
            "Accept": "application/json",
        }
        req = urllib.request.Request(f"{DATA_HOST}/v1/markets", headers=hdrs)
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        markets = resp if isinstance(resp, list) else resp.get("data", [])
        L(f"Data API returned {len(markets)} markets")
        # Filter to active markets with meaningful prices
        active = [
            m for m in markets
            if m.get("question")
            and float(m.get("price", 0) or 0) > 0.001
            and float(m.get("volume24hr", 0) or 0) >= 100
            and not any(k in (m.get("question","")+" "+m.get("category","")).lower()
                       for k in ("trump","biden","election","senate","congress","governor"))
        ]
        if active:
            L(f"Found {len(active)} active Data API markets")
            return active[:50]
    except Exception as e:
        L(f"Data API error: {e}", "WARN")

    # Fall back to CLOB
    return fetch_markets_via_clob()

def calc_arb(yes_mid, no_mid):
    """Calculate arb profit after fees. Returns (profit_pct, spend, profit)."""
    total = yes_mid + no_mid
    if total >= 1.0:
        return 0, 0, 0
    # Fee is 2% of winnings, applied to the winning side only
    # Winning side receives $1, fee = $1 * FEE_RATE
    # Net payout per $1 invested = (1 - FEE_RATE)
    # We buy YES for yes_mid and NO for no_mid, each sized so total outlay = spend
    # spend = yes_mid * size_yes + no_mid * size_no
    # let size_yes = size_no = size (equal dollar amount)
    # spend = size * (yes_mid + no_mid) = size * total
    # size = spend / total
    # payout at expiry = size (from winning side) + 0 (from losing side) = size
    # net after fee = size * (1 - FEE_RATE)
    # profit = net - spend = size*(1-FEE_RATE) - spend = size*(1-FEE_RATE - total)
    # profit_pct = profit / spend

    spend = min(MAX_SPEND, 50)  # cap at $50 total
    size  = spend / total  # shares of each side
    payout = size * (1 - FEE_RATE)  # winning side pays out
    profit = payout - spend
    profit_pct = profit / spend if spend > 0 else 0
    return profit_pct, spend, profit

# ── TRADING ────────────────────────────────────────────────────────
def place_arb(client, condition_id, yes_token_id, no_token_id,
              yes_mid, no_mid, yes_bid, yes_ask, no_bid, no_ask, spend):
    """Place both legs of the arb. Returns (success, description)."""
    size = spend / (yes_mid + no_mid)
    yes_size = round(size, 4)
    no_size  = round(size, 4)

    # Buy YES at ask, buy NO at ask
    yes_price = max(yes_ask, yes_mid * 1.01)  # slight premium to ensure fill
    no_price  = max(no_ask,  no_mid  * 1.01)

    results = []
    for side, token_id, sz, price in [
        ("BUY", yes_token_id, yes_size, yes_price),
        ("BUY", no_token_id,  no_size,  no_price),
    ]:
        try:
            ok = client.create_market_order(
                condition_id=condition_id,
                side=side,
                size=str(sz),
                price=str(round(price, 4)),
            )
            results.append(f"{side} {sz:.4f} @ {price:.4f} -> {ok}")
            L(f"  {side} {sz:.4f} @ {price:.4f} -> {ok}")
        except Exception as e:
            results.append(f"ERR: {e}")
            L(f"  Order error: {e}", "ERROR")

    return results

# ── MAIN ─────────────────────────────────────────────────────────
cycle = 0
client = None
wallet = ""

if not PRIVATE_KEY:
    L("POLYMARKET_PRIVATE_KEY not set in env!", "FATAL")
    exit(1)

L("Arbitrage Bot v13 starting...")
L(f"  MIN_SPREAD: {MIN_SPREAD_PCT*100:.1f}%  MAX_SPEND: ${MAX_SPEND}")

try:
    client, wallet = get_clob_client(PRIVATE_KEY)
    L(f"  Wallet: {wallet}")
except Exception as e:
    L(f"Client init failed: {e}", "ERROR")
    exit(1)

while True:
    cycle += 1
    L(f"Cycle {cycle}...")

    markets = fetch_markets()
    L(f"  Found {len(markets)} active markets")

    opps = []
    for m in markets[:15]:  # scan top 15 to avoid rate limits
        tokens = m.get("tokens", [])
        yes_tok = next((t for t in tokens if str(t.get("outcome","")).lower() in ("yes","1",1)), None)
        no_tok  = next((t for t in tokens if str(t.get("outcome","")).lower() in ("no","0",0)), None)
        if not yes_tok or not no_tok:
            continue

        yes_tid = yes_tok.get("token_id","")
        no_tid  = no_tok.get("token_id", "")
        if not yes_tid or not no_tid:
            continue

        try:
            yes_mid, no_mid, yes_b, yes_a, no_b, no_a = get_market_prices(
                client, m.get("condition_id"), yes_tid, no_tid
            )
        except Exception as e:
            L(f"  Price fetch error for {m.get('question','')[:40]}: {e}", "WARN")
            continue
        if yes_mid <= 0 or no_mid <= 0:
            continue

        time.sleep(0.5)  # rate limit protection
        profit_pct, spend, profit = calc_arb(yes_mid, no_mid)
        if profit_pct >= MIN_SPREAD_PCT:
            opps.append({
                "market": m,
                "yes_mid": yes_mid, "no_mid": no_mid,
                "yes_bid": yes_b, "yes_ask": yes_a,
                "no_bid": no_b, "no_ask": no_a,
                "yes_token_id": yes_tid, "no_token_id": no_tid,
                "profit_pct": profit_pct, "spend": spend, "profit": profit,
                "condition_id": m.get("condition_id"),
                "question": m.get("question","")[:80],
            })

    if opps:
        opps.sort(key=lambda x: x["profit_pct"], reverse=True)
        best = opps[0]
        L(f"  *** ARB OPPORTUNITY ***")
        L(f"  {best['question']}")
        L(f"  YES={best['yes_mid']:.4f} NO={best['no_mid']:.4f} SUM={best['yes_mid']+best['no_mid']:.4f}")
        L(f"  Profit: {best['profit_pct']*100:.2f}% = ${best['profit']:.4f} on ${best['spend']:.2f}")
        tg(f"🔀 <b>ARB ALERT</b>\n{best['question']}\nYES {best['yes_mid']:.4f} + NO {best['no_mid']:.4f}\nSum: {best['yes_mid']+best['no_mid']:.4f}\nProfit: {best['profit_pct']*100:.2f}% (${best['profit']:.4f})")

        # Auto-trade
        res = place_arb(
            client,
            best["condition_id"], best["yes_token_id"], best["no_token_id"],
            best["yes_mid"], best["no_mid"],
            best["yes_bid"], best["yes_ask"],
            best["no_bid"], best["no_ask"],
            best["spend"],
        )
        tg(f"📋 <b>Orders</b>\n" + "\n".join(res))
    else:
        best_market = markets[0] if markets else None
        if best_market:
            L(f"  Best: {best_market.get('question','')[:60]}")
        L(f"  No arb opportunities (min spread {MIN_SPREAD_PCT*100:.1f}%)")

    time.sleep(POLLING_SEC)
