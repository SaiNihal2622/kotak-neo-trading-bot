"""Consolidate current market + bot state into one JSON snapshot.

Reads:
  - data_cache/liveness.json       (bot health, uptime, last snapshot)
  - data_cache/paper_state.json    (cash, realized P&L)
  - logs/bot.log                   (last LiveIndia refresh line for spot/vix)

Writes:
  - data_cache/market_snapshot.json  (single consolidated view)

Why: cron ticks, watchdog scripts, and the dashboard currently have to
parse 3+ sources to answer "what is the market + bot doing right now".
This script makes that one read.

Usage:
    python scripts/market_snapshot.py
    python scripts/market_snapshot.py --json          # also print to stdout
    python scripts/market_snapshot.py --quiet         # suppress stdout

Exit codes:
    0  Snapshot written successfully
    1  Required input file missing (liveness.json or paper_state.json)
    2  Optional input stale (bot.log), but snapshot still written
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIVENESS = PROJECT_ROOT / "data_cache" / "liveness.json"
PAPER_STATE = PROJECT_ROOT / "data_cache" / "paper_state.json"
BOT_LOG = PROJECT_ROOT / "logs" / "bot.log"
OUTPUT = PROJECT_ROOT / "data_cache" / "market_snapshot.json"

# "LiveIndia refresh: NIFTY=24155.15 BANKNIFTY=57731.50 VIX=11.15"
REFRESH_RE = re.compile(
    r"LiveIndia refresh:\s*NIFTY=([\d.]+)\s+BANKNIFTY=([\d.]+)\s+VIX=([\d.]+)"
)
# "LiveKotak heartbeat: authed=True subscribed=10 latest=2 tick_count=5180"
HEARTBEAT_RE = re.compile(
    r"LiveKotak heartbeat:\s*authed=(\w+)\s+subscribed=(\d+)\s+latest=(\d+)\s+tick_count=(\d+)"
)
# "[SCAN] cycle=1648 | skip: 2 open strategies >= max 2"
SCAN_RE = re.compile(r"\[SCAN\]\s+cycle=(\d+)\s*\|?\s*(.*)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _parse_bot_log_tail(path: Path, max_bytes: int = 200_000) -> dict:
    """Pull the most recent LiveIndia + LiveKotak + SCAN line from bot.log.

    Reads only the tail (last ~200KB) so this stays fast on a multi-MB log.
    """
    if not path.exists():
        return {"market_fresh": False, "reason": "bot.log missing"}

    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # discard partial first line
            data = f.read().decode("utf-8", errors="replace")
    except OSError as exc:
        return {"market_fresh": False, "reason": f"read error: {exc}"}

    market = {"nifty_spot": None, "banknifty_spot": None, "vix": None, "ts": None}
    kotak = {"authed": None, "subscribed": None, "latest_seq": None, "tick_count": None, "ts": None}
    scan = {"cycle": None, "note": None, "ts": None}

    # Walk lines in reverse to find the latest of each pattern.
    for line in reversed(data.splitlines()):
        if market["nifty_spot"] is None:
            m = REFRESH_RE.search(line)
            if m:
                market["nifty_spot"] = float(m.group(1))
                market["banknifty_spot"] = float(m.group(2))
                market["vix"] = float(m.group(3))
                # Pull the leading timestamp if present: "2026-08-27 12:00:10.203 | INFO    | ..."
                ts_match = line.split(" | ", 1)[0].strip()
                market["ts"] = ts_match
                continue
        if kotak["tick_count"] is None:
            m = HEARTBEAT_RE.search(line)
            if m:
                kotak["authed"] = m.group(1) == "True"
                kotak["subscribed"] = int(m.group(2))
                kotak["latest_seq"] = int(m.group(3))
                kotak["tick_count"] = int(m.group(4))
                ts_match = line.split(" | ", 1)[0].strip()
                kotak["ts"] = ts_match
                continue
        if scan["cycle"] is None:
            m = SCAN_RE.search(line)
            if m:
                scan["cycle"] = int(m.group(1))
                scan["note"] = m.group(2).strip()
                ts_match = line.split(" | ", 1)[0].strip()
                scan["ts"] = ts_match
                continue
        if all(market[k] is not None for k in ("nifty_spot",)) and \
           kotak["tick_count"] is not None and scan["cycle"] is not None:
            break

    market_fresh = market["nifty_spot"] is not None and market["nifty_spot"] > 0
    return {
        "market_fresh": market_fresh,
        "market": market,
        "kotak_heartbeat": kotak,
        "last_scan": scan,
    }


def build_snapshot() -> dict:
    if not LIVENESS.exists():
        raise FileNotFoundError(f"liveness.json missing at {LIVENESS}")
    if not PAPER_STATE.exists():
        raise FileNotFoundError(f"paper_state.json missing at {PAPER_STATE}")

    liveness = json.loads(LIVENESS.read_text(encoding="utf-8"))
    paper = json.loads(PAPER_STATE.read_text(encoding="utf-8"))

    log_state = _parse_bot_log_tail(BOT_LOG)

    snap = {
        "schema_version": "market-snapshot-v1",
        "generated_at": _now_iso(),
        "bot": {
            "state": liveness.get("state"),
            "pid": liveness.get("pid"),
            "uptime_sec": liveness.get("uptime_sec"),
            "tick": liveness.get("tick"),
            "main_thread_alive": liveness.get("main_thread_alive"),
            "is_paused": (liveness.get("snapshot") or {}).get("is_paused"),
            "data_source": (liveness.get("snapshot") or {}).get("data_source"),
            "risk_preset": (liveness.get("snapshot") or {}).get("risk_preset"),
        },
        "market": log_state["market"],
        "market_fresh": log_state["market_fresh"],
        "kotak_heartbeat": log_state["kotak_heartbeat"],
        "last_scan": log_state["last_scan"],
        "capital": {
            "cash": paper.get("cash"),
            "realized_pnl": paper.get("realized_pnl"),
            "open_positions": (liveness.get("snapshot") or {}).get("open_positions"),
            "vix_from_paper": (liveness.get("snapshot") or {}).get("vix"),
        },
    }
    return snap


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--json", action="store_true", help="Print snapshot JSON to stdout")
    parser.add_argument("--quiet", action="store_true", help="Suppress non-error stdout")
    args = parser.parse_args()

    try:
        snap = build_snapshot()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    OUTPUT.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")

    if not snap["market_fresh"]:
        if not args.quiet:
            print(f"WARN: snapshot written but market data stale/missing ({snap['market']})", file=sys.stderr)
        return 2

    if not args.quiet:
        m = snap["market"]
        c = snap["capital"]
        b = snap["bot"]
        print(
            f"snapshot ok: NIFTY={m['nifty_spot']} BNF={m['banknifty_spot']} "
            f"VIX={m['vix']} cash=Rs.{c['cash']:.0f} realized=Rs.{c['realized_pnl']:.0f} "
            f"open={c['open_positions']} state={b['state']} scan={snap['last_scan']['cycle']} "
            f"-> {OUTPUT.relative_to(PROJECT_ROOT)}"
        )
    if args.json:
        print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
