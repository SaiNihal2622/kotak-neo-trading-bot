"""Trade journal — automatic journaling for every trade.

Every trade (open + close) gets a written entry with:
- The setup (what was the LLM thinking when it opened)
- The market context at the time
- The outcome (P&L, days held, max drawdown during trade)
- The lesson (what to do differently next time, written by LLM at close)

This builds a long-term knowledge base that feeds the self-evolution loop.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'

JOURNAL_PATH = DATA / "trade_journal.jsonl"


def journal_open(trade_id: str, decision: dict, context: dict) -> dict:
    """Record a trade OPEN in the journal. Called right after fill confirmation."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": "OPEN",
        "trade_id": trade_id,
        "underlying": decision.get("underlying"),
        "strategy": decision.get("strategy"),
        "rationale": (decision.get("rationale") or "")[:500],
        "legs": decision.get("legs", []),
        "max_hold_minutes": decision.get("max_hold_minutes"),
        "target": decision.get("target"),
        "stop": decision.get("stop"),
        "context_snapshot": {
            "vix": (context.get("liveness") or {}).get("snapshot", {}).get("vix"),
            "session_pct": (context.get("intraday") or {}).get("session_pct"),
            "events_fired": [e.get("type") for e in (context.get("events") or [])[:5]],
            "global_cues": _extract_global_cues(context),
        },
    }
    _append(entry)
    return entry


def journal_close(trade_id: str, exit_reason: str, pnl: float, holding_minutes: int) -> dict:
    """Record a trade CLOSE in the journal."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "event": "CLOSE",
        "trade_id": trade_id,
        "exit_reason": exit_reason,
        "pnl": round(pnl, 2),
        "holding_minutes": holding_minutes,
    }
    _append(entry)
    return entry


def get_journal(n: int = 20) -> list:
    """Read the last N journal entries."""
    if not JOURNAL_PATH.exists():
        return []
    try:
        lines = JOURNAL_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


def get_lessons() -> dict:
    """Aggregate lessons from recent journal entries. Used by self-evolution."""
    entries = get_journal(50)
    opens = [e for e in entries if e.get("event") == "OPEN"]
    closes = [e for e in entries if e.get("event") == "CLOSE"]
    # Group by strategy
    by_strategy = {}
    for o in opens:
        s = o.get("strategy", "unknown")
        # Find matching close (same trade_id, after this open)
        close = next((c for c in closes if c.get("trade_id") == o.get("trade_id")), None)
        pnl = close.get("pnl", 0) if close else None
        by_strategy.setdefault(s, []).append({
            "trade_id": o.get("trade_id"),
            "pnl": pnl,
            "rationale": o.get("rationale", "")[:200],
            "context": o.get("context_snapshot", {}),
        })
    return {
        "total_entries": len(entries),
        "opens": len(opens),
        "closes": len(closes),
        "by_strategy": by_strategy,
    }


def _extract_global_cues(context: dict) -> dict:
    """Pull a few key global cues from the context for the journal."""
    try:
        g = (context.get("global_markets") or {}).get("instruments") or {}
        return {
            "spx_pct": g.get("^GSPC", {}).get("pct_1d"),
            "vix_pct": g.get("^VIX", {}).get("pct_1d"),
            "wti_pct": g.get("CL=F", {}).get("pct_1d"),
        }
    except Exception:
        return {}


def _append(entry: dict) -> None:
    """Append a journal entry to disk."""
    try:
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "lessons"
    if cmd == "lessons":
        print(json.dumps(get_lessons(), indent=2, default=str))
    elif cmd == "journal":
        for entry in get_journal(10):
            print(f"[{entry['ts']}] {entry['event']} {entry.get('trade_id', '?')} {entry.get('underlying', '')} {entry.get('strategy', '')}")
    else:
        print(f"Unknown: {cmd}")
        print("Usage: python trade_journal.py [lessons|journal]")
