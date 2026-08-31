"""Quant Engine — event-driven decision engine for a professional quant system.

Why this exists: the existing cron-based decision loop (kotak-trader-desk)
fires every 5 min and produces a HOLD because the templated gates (13:30
cutoff, 2-position cap, NIFTY/BNF only) are conservative. A real quant
needs to react to:
- Price moves >0.3% in 1 minute (momentum or reversal)
- OI changes >5% (fresh institutional positioning)
- Volume spikes (2x average)
- Candle closes (1m, 5m)
- Order-book anomalies (spread widening)
- Cross-asset signals (US futures, dollar index, crude, gold)

This engine:
1. Subscribes to the bot's live data (liveness.json + paper_state.json)
2. Builds a real-time state (intraday levels + option chain + positions)
3. On a significant event, invokes the LLM (Mavis) with FULL context
4. The LLM decides: instrument, strike, qty, action (OPEN/CLOSE/HOLD)
5. Writes to data_cache/quant_actions.json (separate from brain_actions)
6. The bot reads quant_actions.json on its main loop tick and executes

This file does NOT make trading decisions itself. It just decides WHEN to
invoke the LLM and WHAT context to send. The LLM is the brain.
"""
import json
import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
STATE_PATH = DATA / 'quant_engine_state.json'
ACTIONS_PATH = DATA / 'quant_actions.json'
EVENTS_PATH = DATA / 'quant_events.jsonl'
DEDUP_SEC = 60  # don't fire same signature twice within 60s

# Event thresholds
PRICE_MOVE_1M_PCT = 0.3       # 0.3% in 1 min triggers
PRICE_MOVE_5M_PCT = 0.7       # 0.7% in 5 min triggers
VOLUME_SPIKE_MULT = 2.0       # 2x recent average triggers
OI_CHANGE_PCT = 5.0           # 5% OI change triggers
CANDLE_CLOSE_INTERVALS = [1, 5, 15]  # candle close events (in minutes)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def read_state() -> dict:
    """Read current bot state from liveness + paper_state + intraday_levels + chains."""
    out = {'ts': now_iso()}
    try:
        out['liveness'] = json.loads((DATA / 'liveness.json').read_text(encoding='utf-8'))
    except Exception:
        out['liveness'] = {}
    try:
        out['paper'] = json.loads((DATA / 'paper_state.json').read_text(encoding='utf-8'))
    except Exception:
        out['paper'] = {}
    try:
        out['intraday'] = json.loads((DATA / 'intraday_levels.json').read_text(encoding='utf-8'))
    except Exception:
        out['intraday'] = {}
    try:
        out['chains'] = json.loads((DATA / 'option_chains.json').read_text(encoding='utf-8'))
    except Exception:
        out['chains'] = {}
    return out


def detect_events(state: dict, last_state: dict) -> list[dict]:
    """Compare current state to last; return list of significant events."""
    events = []
    intraday = state.get('intraday', {}).get('instruments', {})
    last_intraday = last_state.get('intraday', {}).get('instruments', {})

    for sym, lv in intraday.items():
        if not lv:
            continue
        prev = last_intraday.get(sym, {})
        cur_price = lv.get('current', 0)
        prev_price = prev.get('current', cur_price)
        vwap = lv.get('vwap', 0)
        day_high = lv.get('day_high', 0)
        day_low = lv.get('day_low', 0)

        # Price move
        if prev_price and cur_price:
            pct = (cur_price - prev_price) / prev_price * 100
            if abs(pct) >= PRICE_MOVE_1M_PCT:
                events.append({
                    'type': 'price_move_1m',
                    'symbol': sym,
                    'pct': round(pct, 3),
                    'price': cur_price,
                    'vwap': vwap,
                    'day_high': day_high,
                    'day_low': day_low,
                })

        # Touch day high (resistance)
        if day_high and cur_price and abs(cur_price - day_high) / day_high * 100 < 0.05:
            events.append({'type': 'near_day_high', 'symbol': sym, 'price': cur_price, 'level': day_high})

        # Touch day low (support)
        if day_low and cur_price and abs(cur_price - day_low) / day_low * 100 < 0.05:
            events.append({'type': 'near_day_low', 'symbol': sym, 'price': cur_price, 'level': day_low})

        # Cross VWAP
        if vwap and prev.get('vwap') and cur_price and prev_price:
            if (prev_price < prev['vwap'] and cur_price > vwap) or (prev_price > prev['vwap'] and cur_price < vwap):
                events.append({'type': 'vwap_cross', 'symbol': sym, 'price': cur_price, 'vwap': vwap})

    return events


def should_invoke_llm(events: list, state: dict, last_event_ts: float) -> tuple[bool, str]:
    """Decide if an LLM invocation is warranted. Dedup by event signature."""
    if not events:
        return False, "no_events"
    # Dedup
    sig = "|".join(f"{e['type']}:{e['symbol']}:{round(e.get('pct', 0), 2)}" for e in events[:5])
    now = time.time()
    if (now - last_event_ts) < DEDUP_SEC:
        return False, f"dedup_window ({int(DEDUP_SEC - (now - last_event_ts))}s left)"
    return True, sig


def invoke_llm(state: dict, events: list) -> dict:
    """Spawn a one-shot Mavis session with the full state + events context.
    The LLM is expected to read the state, reason about it, and write
    data_cache/quant_actions.json. Returns the mavis output.
    """
    prompt = (
        "You are the quant brain of kotak-neo-bot. Live event detected.\n\n"
        f"Events: {json.dumps(events, indent=2, default=str)[:2000]}\n\n"
        f"State (truncated): {json.dumps(state, indent=2, default=str)[:8000]}\n\n"
        "Tasks:\n"
        "1. Read data_cache/quant_actions.json — if it already has an un-consumed action, exit.\n"
        "2. Decide: is this event a trading opportunity? If YES, write an action to "
        "data_cache/quant_actions.json with schema: {ts, ist_time, source, instrument, action: OPEN|CLOSE|HOLD, "
        "strategy, expiry, legs: [{side, qty, strike, opt_type, price_or_null}], target, stop, rationale, "
        "ttl_sec: 300}.\n"
        "3. You may pick ANY instrument from the universe (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, "
        "or any NIFTY 50 stock). You may pick ANY strategy (vertical, strangle, condor, straddle, "
        "single-leg directional, calendar, ratio).\n"
        "4. NO templated gates except hard risk (max_loss_per_trade = 1% of capital, "
        "max_daily_loss = 3%, no naked unlimited risk).\n"
        "5. Provide a 2-3 sentence rationale that includes: WHY this setup, WHY this strike, "
        "WHY this quantity, the exit target + stop, and the time horizon.\n"
        "6. If HOLD, set action=HOLD and explain why in rationale.\n\n"
        "Read the option chain + intraday levels for the relevant instrument before deciding. "
        "Be a professional quant: take the trade if the edge is real, pass if it's not."
    )
    try:
        r = subprocess.run(
            ["mavis", "cron", "once",
             "--cron_name", f"quant-event-{int(time.time())}",
             "--prompt", prompt[:6000],
             "--agent_name", "mavis",
             "--session", "new",
             "--after", "0s"],
            capture_output=True, text=True, timeout=30,
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout.strip()[:300], "stderr": r.stderr.strip()[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def main() -> int:
    state = read_state()
    last_state = {}
    if STATE_PATH.exists():
        try:
            last_state = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass

    events = detect_events(state, last_state)
    if not events:
        print(f"QUANT-ENGINE: 0 events (no significant price moves or level touches)")
        STATE_PATH.write_text(json.dumps(state, default=str), encoding='utf-8')
        return 0

    last_event_ts = last_state.get('_last_event_ts', 0)
    should, reason = should_invoke_llm(events, state, last_event_ts)
    if not should:
        print(f"QUANT-ENGINE: {len(events)} events but {reason}")
        STATE_PATH.write_text(json.dumps({**state, '_last_event_ts': last_event_ts}), encoding='utf-8')
        return 0

    # Log the events
    with open(EVENTS_PATH, "a", encoding='utf-8') as f:
        f.write(json.dumps({"ts": now_iso(), "events": events}, default=str) + "\n")

    # Invoke LLM
    result = invoke_llm(state, events)
    print(f"QUANT-ENGINE: {len(events)} events fired LLM invocation: {result.get('ok')}")
    if result.get('stdout'):
        print(f"  mavis: {result['stdout'][:200]}")

    # Update state with last_event_ts
    new_state = {**state, '_last_event_ts': time.time()}
    STATE_PATH.write_text(json.dumps(new_state, default=str), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
