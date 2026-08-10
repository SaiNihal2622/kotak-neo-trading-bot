# 🏆 GOLD FROM KOTAK NEO — What I Was Missing

I just audited the **entire `neo_api_client` v2 SDK source code** line by line. **The user is RIGHT — Kotak Neo itself has way more than I was using.** Here are the advanced features I missed:

## 🟢 ADVANCED ORDER TYPES (server-side risk management)

These are **HUGE**. We can use Kotak Neo's server to handle risk instead of tracking it ourselves:

### 1. **Bracket Orders** (auto SL + target + trailing)
```python
client.place_order(
    trading_symbol="NIFTY07AUG2624500CE",
    exchange_segment="nse_fo",
    transaction_type="BUY",
    quantity=75,
    product="MIS",
    order_type="MKT",
    # Bracket order fields:
    stop_loss_type="absolute",     # or "points"
    stop_loss_value=30,            # SL at -30
    square_off_type="absolute",    # or "points"
    square_off_value=90,           # Target at +90 (3:1 RR)
    trailing_stop_loss="Y",        # Trail the SL
    trailing_sl_value=10,          # Trail by 10
)
```
**This means: when I send a bracket order, Kotak Neo automatically places the SL and target orders, monitors them, and adjusts the trailing SL. NO need for our bot to track stops!**

### 2. **Cover Orders** (mandatory SL on every entry)
```python
client.place_order(
    # ... regular fields
    stop_loss_type="absolute",
    stop_loss_value=20,  # Mandatory stop loss
)
# Cover order: entry + SL as a single package
```

### 3. **Iceberg Orders** (disclosed_quantity)
```python
client.place_order(
    # ... regular fields
    quantity=900,           # Actual qty
    disclosed_quantity=75,  # Only show 75 at a time
)
```

### 4. **After Market Orders (AMO)**
```python
client.place_order(
    # ... regular fields
    amo="YES",  # Place after market hours
)
```

### 5. **Market Protection**
```python
client.place_order(
    # ... regular fields
    market_protection="2",  # Max 2% slippage on market orders
)
```

## 🟢 PRE-TRADE MARGIN CHECK (no more guessing margin)

```python
margin = client.margin_required(
    exchange_segment="nse_fo",
    price=150,
    order_type="L",
    product="MIS",
    quantity=75,
    instrument_token="...",
    transaction_type="BUY",
    trigger_price="0",
)
# Returns: exact margin required before placing the order
```

**This means: before any trade, query the actual margin needed, and reject the trade if we don't have it.** Much better than hardcoded lot-size assumptions.

## 🟢 ADVANCED QUOTES (Level 5 depth + OHLC)

```python
# Full Level 5 depth quote
client.quotes(
    instrument_tokens=[{"instrument_token": "26000", "exchange_segment": "nse_cm"}],
    quote_type="all",  # or "ltp", "depth", "ohlc", etc.
)
# Returns: bid/ask 5 levels, OI, volume, IV (maybe), last trade timestamp
```

## 🟢 SCRIP SEARCH (find options by criteria)

```python
results = client.search_scrip(
    exchange_segment="nse_fo",
    symbol="NIFTY",
    expiry="2026-08-07",
    option_type="CE",
    strike_price=24500,
)
# Returns: matching option contract(s) with trading_symbol, token, lot_size
```

**This means: no more hardcoded `NIFTY24500CE` symbols. Dynamically discover all available strikes + expiries.**

## 🟢 SCRIP MASTER (full instrument list)

```python
master_csv_url = client.scrip_master(exchange_segment="nse_fo")
# Returns: URL to download full scrip master CSV
# CSV has: token, symbol, expiry, strike, option_type, lot_size, tick_size
```

**This means: one-time download of the full NSE FO instrument list, then query locally for any option/stock/future.**

## 🟢 REAL-TIME ORDER FEED (no more polling)

```python
client.subscribe_to_orderfeed()
# Sets up a dedicated WebSocket for real-time order status updates
# Every order status change (open → partial fill → complete → cancelled) arrives via push
# No need to poll order_report() every N seconds
```

## 🟢 ORDER AUDIT TRAIL (every state change)

```python
# Full history of an order
history = client.order_history(order_id="...")
# Returns: every state change (PUT ORDER REQ → VALIDATION PENDING → OPEN → TRADE → COMPLETE)
# With timestamps, prices, quantities

# All fills for an order
trades = client.trade_report(order_id="...")
# Returns: every fill (if partial), with fill price, qty, exchange timestamp
```

## 🟢 ADVANCED SEGMENT-LEVEL LIMITS

```python
# Get margin/limits for a specific segment
equity_limits = client.limits(segment="ALL", exchange="NSE", product="ALL")
fo_limits = client.limits(segment="ALL", exchange="NFO", product="MIS")
# Returns: available margin, used margin, collateral, etc., per segment
```

## 🟢 CANCEL BRACKET / COVER ORDERS

```python
client.cancel_bracket_order(order_id="...", isVerify=False)
client.cancel_cover_order(order_id="...", isVerify=False)
```

---

## What This Means For Our Bot

### OLD design (we built):
- Place LIMIT order
- Bot monitors price
- When price hits stop, place SL order
- When price hits target, place target order
- Risk: what if bot crashes between checking and placing? Slippage. Gaps. Missed orders.

### NEW design (Kotak does it server-side):
- Place BRACKET order (entry + SL + target + trailing in ONE call)
- Kotak Neo handles the rest
- Bot just monitors overall P&L, doesn't track per-trade exits
- Even if bot crashes, the bracket order stays active on Kotak's server

**This is a 10x simplification of our risk management code.**

---

## Other Gotchas I Found

1. **`scrip_master` returns a CSV URL** (not JSON) — needs download
2. **`subscribe_to_orderfeed()` is the HSI socket** — separate from market data HSM
3. **`subscribe(instrument_tokens, isIndex=True)`** — important flag for indices
4. **`subscribe(instrument_tokens, isDepth=True)`** — for Level 5 depth (vs LTP only)
5. **`pf='N'` parameter** — "portfolio" flag (likely for NRML vs MIS)
6. **`market_protection`** — for market orders, max slippage %

---

## Action Plan

1. **Update NeoClient** to use bracket orders for directional trades
2. **Update NeoClient** to use cover orders for short premium
3. **Add margin_required** pre-check before every order
4. **Add scrip_master** download at startup (cache locally)
5. **Add search_scrip** for dynamic option discovery
6. **Add subscribe_to_orderfeed** for real-time order status (no polling)
7. **Use quotes(quote_type='depth')** for better execution
8. **Add trade_report + order_history** for audit log

This converts the bot from "complex software that tracks everything" to "simple software that delegates risk to Kotak's server".
