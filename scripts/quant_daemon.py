r"""Quant Daemon - the always-on watcher of kotak-neo-bot.

This replaces the cron-based market watching. Mavis forces cron for LLM
invocation, so the cleanest architecture is:

  quant_daemon.py (24/7, this file)  -> watches market -> writes events to
    data_cache/quant_events.jsonl
  kotak-quant-engine cron (every 1 min) -> reads events -> invokes LLM
    (Mavis) -> LLM writes to data_cache/quant_actions.json
  kotak_bot/__main__.py (bot main loop) -> reads quant_actions.json ->
    executes via order_manager

The daemon's job is just real-time watching. It's templated Python, no LLM.
It runs as a long-lived process (NSSM service or detached start).

What it does:
- Reads live state (liveness.json, paper_state.json, intraday_levels.json)
- Builds a rolling intraday state in memory (day high/low/VWAP, level touches)
- Detects SIGNIFICANT events (real price moves, level crosses, OI changes)
- Writes events to data_cache/quant_events.jsonl
- Reads LLM's actions from data_cache/quant_actions.json and... logs them
  (the bot's main loop is the actual executor)

This is "always-on" without forcing crons for everything. The cron's only
job is the LLM call.

Run as NSSM service (24/7 auto-restart):
  nssm install KotakQuantDaemon \
    "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\.venv\Scripts\python.exe" \
    "-u C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\quant_daemon.py"
  nssm set KotakQuantDaemon AppStdout "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\quant_daemon.out.log"
  nssm set KotakQuantDaemon AppStderr "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\quant_daemon.err.log"
  nssm set KotakQuantDaemon AppDirectory "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
  nssm set KotakQuantDaemon Start SERVICE_AUTO_START
  nssm start KotakQuantDaemon
"""
from __future__ import annotations

import json
import os
import sys
import time
import signal
import traceback
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
LOG = DATA / 'quant_daemon.log'
STATE = DATA / 'quant_daemon_state.json'
EVENTS = DATA / 'quant_events.jsonl'
ACTIONS = DATA / 'quant_actions.json'

# Tunables
TICK_SEC = 2.0
PRICE_MOVE_PCT = 0.3           # fire on >=0.3% move since last tick
LEVEL_TOUCH_PCT = 0.05         # within 0.05% of a level = touch
DEDUP_SEC = 30                 # don't repeat-fire same event signature within 30s
MIN_DATA_POINTS = 5            # need >=5 ticks before firing (skip early-tick noise)

# State
TICKS: dict[str, deque] = {}    # symbol -> deque of (ts, price)
LAST_EVENT_SIG: dict[str, str] = {}  # symbol -> last fired sig
LAST_TICK_TS: dict[str, float] = {}  # symbol -> last tick time
RUNNING = True


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def read_intraday() -> dict:
    try:
        return json.loads((DATA / 'intraday_levels.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_liveness() -> dict:
    try:
        return json.loads((DATA / 'liveness.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_paper() -> dict:
    try:
        return json.loads((DATA / 'paper_state.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def append_event(event: dict) -> None:
    """Write a single event to the events log. The kotak-quant-engine cron
    reads this file and decides whether to invoke the LLM."""
    try:
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now_iso(), **event}, default=str) + "\n")
    except Exception as e:
        log(f"event-write-err: {e}")


def detect_significant_events(intraday: dict, last_intraday: dict) -> list:
    """Return list of significant events. Skips early-tick noise and
    false-positive level-touches (when only 1 tick exists, every price
    is at every level)."""
    events = []
    cur = intraday.get('instruments', {})
    prev = last_intraday.get('instruments', {})

    for sym, lv in cur.items():
        if not lv or not isinstance(lv, dict):
            continue
        cur_price = lv.get('current', 0) or 0
        prev_lv = prev.get(sym, {})
        prev_price = prev_lv.get('current', 0) or 0
        if not cur_price:
            continue

        # Update tick buffer
        ts = lv.get('last_ts', now_iso())
        if sym not in TICKS:
            TICKS[sym] = deque(maxlen=2000)
        TICKS[sym].append((ts, cur_price))

        # Need enough data points before firing
        if len(TICKS[sym]) < MIN_DATA_POINTS:
            continue

        # 1) Real price move since previous tick
        if prev_price and abs(cur_price - prev_price) / prev_price * 100 >= PRICE_MOVE_PCT:
            pct = (cur_price - prev_price) / prev_price * 100
            events.append({
                'type': 'price_move',
                'symbol': sym,
                'pct': round(pct, 3),
                'price': cur_price,
                'prev_price': prev_price,
                'vwap': lv.get('vwap'),
                'day_high': lv.get('day_high'),
                'day_low': lv.get('day_low'),
            })

        # 2) VWAP cross (price moved from one side to the other)
        vwap = lv.get('vwap')
        prev_vwap = prev_lv.get('vwap')
        if vwap and prev_vwap and prev_price and cur_price:
            if (prev_price < prev_vwap and cur_price > vwap) or (prev_price > prev_vwap and cur_price < vwap):
                events.append({
                    'type': 'vwap_cross',
                    'symbol': sym,
                    'price': cur_price,
                    'vwap': vwap,
                })

        # 3) Touch day high / day low (only if day_high != day_low, i.e. real
        # range has formed; otherwise every tick matches every level)
        day_high = lv.get('day_high', 0)
        day_low = lv.get('day_low', 0)
        if day_high and day_low and (day_high - day_low) > 0.001 * cur_price:  # at least 0.1% range
            for level_name, level_val in [('day_high', day_high), ('day_low', day_low)]:
                if level_val and abs(cur_price - level_val) / level_val * 100 < LEVEL_TOUCH_PCT:
                    events.append({
                        'type': f'touch_{level_name}',
                        'symbol': sym,
                        'price': cur_price,
                        'level': level_val,
                    })
    return events


def dedup(events: list) -> list:
    """Drop events whose signature was already fired in the last DEDUP_SEC for
    the same symbol. Returns the deduped list."""
    now = time.time()
    out = []
    for e in events:
        sig = f"{e['type']}:{e['symbol']}"
        last = LAST_EVENT_SIG.get(sig)
        if last and (now - last) < DEDUP_SEC:
            continue
        LAST_EVENT_SIG[sig] = now
        out.append(e)
    return out


def watch_actions() -> None:
    """If the LLM wrote to quant_actions.json and the bot hasn't consumed
    it yet, log it. The bot's __main__.py is the actual executor; this
    just makes the daemon aware of pending actions for telemetry."""
    try:
        if not ACTIONS.exists():
            return
        actions = json.loads(ACTIONS.read_text(encoding='utf-8'))
        if actions.get('consumed'):
            return
        if actions.get('actions'):
            log(f"ACTION-PENDING: {len(actions['actions'])} action(s) waiting for bot to consume")
    except Exception:
        pass


def save_state() -> None:
    try:
        STATE.write_text(json.dumps({
            "ts": now_iso(),
            "last_event_sigs": LAST_EVENT_SIG,
            "ticks_buffered": {sym: len(t) for sym, t in TICKS.items()},
        }, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass


def signal_handler(sig, frame):
    global RUNNING
    log(f"SHUTDOWN: signal {sig} received, exiting gracefully")
    RUNNING = False


def main() -> int:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    log(f"QUANT-DAEMON: starting (pid={os.getpid()})")

    last_intraday = {}
    tick_count = 0

    while RUNNING:
        try:
            tick_count += 1
            intraday = read_intraday()
            events = detect_significant_events(intraday, last_intraday) if intraday else []
            last_intraday = intraday

            events = dedup(events)
            if events:
                for e in events:
                    append_event(e)
                log(f"EVENT-DETECTED: {len(events)} events: " + ", ".join(f"{e['type']}:{e['symbol']}" for e in events[:5]))

            watch_actions()

            # Persist state every 30 ticks
            if tick_count % 30 == 0:
                save_state()

            time.sleep(TICK_SEC)
        except Exception as e:
            log(f"LOOP-ERR: {e}\n{traceback.format_exc()[:300]}")
            time.sleep(5)

    save_state()
    log("QUANT-DAEMON: stopped")
    return 0


if __name__ == '__main__':
    sys.exit(main())
