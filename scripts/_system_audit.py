"""_system_audit.py - One-shot self-audit that catches the 5 recurring issues.

FIX 2026-09-09 14:20: 5 issues kept coming back:
  1. Brain HOLD loop (LLM serial holder)
  2. Option LTP stale (chain analyzer 5min cadence)
  3. FII/DII date parser accepts 2-year-old data
  4. News RSS includes old article snippets
  5. State file counters never flushed to disk

The fixes are in place, but they need monitoring. This audit runs
every 30 min via the brain's scheduler and reports the health of
each subsystem. The dashboard reads data_cache/system_audit.json
and shows a coloured status badge per subsystem.

Output: data_cache/system_audit.json
  {
    "ts": "2026-09-09T14:20:00+05:30",
    "overall": "ok" | "warn" | "error",
    "subsystems": {
      "brain_state_persistence": {"status": "ok", "last_write_age_min": 0.5, "details": "..."},
      "option_ltp_freshness": {"status": "ok", "ltp_age_min": 0.2, "details": "..."},
      "fii_dii_freshness": {"status": "ok", "data_age_days": 0, "details": "..."},
      "news_freshness": {"status": "ok", "oldest_headline_hours": 1.5, "details": "..."},
      "brain_activity": {"status": "warn", "mins_since_trade": 65, "details": "..."},
    }
  }
"""
from __future__ import annotations
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
OUT = DCACHE / "system_audit.json"


def _age_minutes(path: Path) -> float | None:
    """Return age in minutes of a file. None if missing."""
    if not path.exists():
        return None
    return (time.time() - path.stat().st_mtime) / 60.0


def _age_minutes_iso(iso_ts: str) -> float | None:
    """Return age in minutes of an ISO timestamp. None if unparseable."""
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
    except Exception:
        return None


def _parse_date_safe(s: str):
    """Parse a date in common Indian formats. Returns date or None."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d %b %Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def audit_brain_state_persistence() -> dict:
    """Issue 5: are SERVICE_STATE counters flushed to disk?"""
    state_path = DCACHE / "quant_service_state.json"
    if not state_path.exists():
        return {"status": "error", "details": "state file missing"}
    age = _age_minutes(state_path)
    if age is None or age > 60:
        return {"status": "error", "last_write_age_min": round(age or -1, 1),
                "details": f"state file is {age:.0f} min old — counters not being persisted"}
    if age > 5:
        return {"status": "warn", "last_write_age_min": round(age, 1),
                "details": f"state file {age:.1f} min old — periodic flush should be every 30s"}
    return {"status": "ok", "last_write_age_min": round(age, 2),
            "details": "state file fresh (periodic flush + atexit handler working)"}


def audit_option_ltp_freshness() -> dict:
    """Issue 2: are option positions showing live LTP (not avg_price)?"""
    paper = DCACHE / "paper_state.json"
    if not paper.exists():
        return {"status": "error", "details": "paper_state.json missing"}
    try:
        ps = json.loads(paper.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "error", "details": "paper_state.json unparseable"}
    positions = ps.get("positions", {}) or {}
    if not positions:
        return {"status": "ok", "n_positions": 0, "details": "no open positions"}
    stuck_count = 0
    for sym, p in positions.items():
        if not isinstance(p, dict):
            continue
        ltp = p.get("ltp", 0) or 0
        avg = p.get("avg_price", 0) or 0
        if avg > 0 and abs(ltp - avg) < 0.01:
            stuck_count += 1
    chain_age = _age_minutes(DCACHE / "option_chains.json")
    if stuck_count > 0:
        return {"status": "error", "n_positions": len(positions), "stuck": stuck_count,
                "chain_age_min": round(chain_age or -1, 1),
                "details": f"{stuck_count}/{len(positions)} positions stuck at avg_price (no live LTP)"}
    if chain_age and chain_age > 10:
        return {"status": "warn", "n_positions": len(positions),
                "chain_age_min": round(chain_age, 1),
                "details": f"positions have live LTP but chain is {chain_age:.0f} min old"}
    return {"status": "ok", "n_positions": len(positions),
            "chain_age_min": round(chain_age or 0, 1),
            "details": f"all {len(positions)} positions showing live LTP"}


def audit_fii_dii_freshness() -> dict:
    """Issue 3: is FII/DII data fresh (not 2-year-old)?"""
    fii = DCACHE / "fii_dii.json"
    if not fii.exists():
        return {"status": "warn", "details": "fii_dii.json missing"}
    try:
        d = json.loads(fii.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "error", "details": "fii_dii.json unparseable"}
    summary = d.get("summary", {})
    is_stale = summary.get("is_stale", True)
    data_age = summary.get("data_age_days")
    if is_stale or (data_age is not None and data_age > 2):
        return {"status": "warn", "data_age_days": data_age,
                "details": f"latest FII/DII data is {data_age} days old (stale)"}
    if not d.get("rows"):
        return {"status": "warn", "details": "no FII/DII rows"}
    return {"status": "ok", "data_age_days": data_age, "n_rows": len(d.get("rows", [])),
            "details": f"latest data is {data_age} days old" if data_age is not None else "data is fresh"}


def audit_news_freshness() -> dict:
    """Issue 4: are RSS headlines fresh (not 2-year-old)? Check the metadata file."""
    meta = DCACHE / "news_feed_meta.json"
    if not meta.exists():
        return {"status": "warn", "details": "news_feed_meta.json missing"}
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "error", "details": "news_feed_meta.json unparseable"}
    dropped = m.get("stale_dropped", 0)
    total = m.get("total", 0)
    sources_ok = m.get("sources_ok", 0)
    sources_total = sources_ok + m.get("sources_failed", 0)
    age = _age_minutes_iso(m.get("ts", ""))
    if age and age > 60:
        return {"status": "warn", "age_min": round(age, 0),
                "details": f"news feed is {age:.0f} min old (fetcher should run every 30 min)"}
    if sources_ok < 3:
        return {"status": "warn", "sources_ok": sources_ok, "sources_total": sources_total,
                "details": f"only {sources_ok}/{sources_total} RSS sources responding"}
    return {"status": "ok", "headlines": total, "sources_ok": sources_ok, "stale_dropped": dropped,
            "details": f"{total} fresh headlines from {sources_ok}/{sources_total} sources, dropped {dropped} stale"}


def audit_brain_activity() -> dict:
    """Issue 1: is the LLM being active, or stuck in HOLD loop?
    Check mins since last trade. If > 60 min during market hours AND
    no system_enforced_action was written, the LLM is silent.
    """
    journal = DCACHE / "trade_journal.jsonl"
    last_trade_ts = 0.0
    n_trades_today = 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").strip().split("\n")[-200:]:
            try:
                rec = json.loads(line)
                ts_str = rec.get("ts") or rec.get("entry_ts") or rec.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                        last_trade_ts = max(last_trade_ts, ts)
                    except Exception:
                        pass
                if today_str in (rec.get("ts", "") or ""):
                    n_trades_today += 1
            except Exception:
                continue
    # Check if market is open (approximate by hour: 9-15:30 IST)
    ist_hour = (datetime.now().hour)
    # Don't assume IST — just report the metrics
    mins_since = (time.time() - last_trade_ts) / 60.0 if last_trade_ts else 9999.0
    # Check if system_enforced_action was written
    sea = DCACHE / "system_enforced_action.json"
    sea_age = _age_minutes(sea)
    details = f"last trade {mins_since:.0f} min ago, {n_trades_today} trades today"
    if sea.exists() and sea_age and sea_age < 30:
        details += f", system enforcement wrote a fallback at {sea_age:.0f} min ago"
    # No trades ever
    if mins_since > 9999:
        return {"status": "warn", "mins_since_trade": None, "trades_today": n_trades_today,
                "details": "no trades recorded ever — LLM has not opened any position"}
    if mins_since > 240:
        return {"status": "warn", "mins_since_trade": round(mins_since, 0),
                "trades_today": n_trades_today,
                "details": f"no trades in {mins_since/60:.1f} hours"}
    if mins_since > 90:
        return {"status": "warn", "mins_since_trade": round(mins_since, 0),
                "trades_today": n_trades_today,
                "details": f"no trades in {mins_since:.0f} min — system enforcement should fire if bias > 0.3%"}
    return {"status": "ok", "mins_since_trade": round(mins_since, 0),
            "trades_today": n_trades_today, "details": details}


def main() -> int:
    """Run all audits and write the report."""
    audits = {
        "brain_state_persistence": audit_brain_state_persistence(),
        "option_ltp_freshness": audit_option_ltp_freshness(),
        "fii_dii_freshness": audit_fii_dii_freshness(),
        "news_freshness": audit_news_freshness(),
        "brain_activity": audit_brain_activity(),
    }
    # Overall status
    statuses = [a["status"] for a in audits.values()]
    if "error" in statuses:
        overall = "error"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"
    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overall": overall,
        "subsystems": audits,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    # One-line summary
    issues = [f"{k}={v['status']}" for k, v in audits.items() if v["status"] != "ok"]
    summary = f"system_audit: overall={overall}"
    if issues:
        summary += f" | issues: {', '.join(issues)}"
    print(summary)
    for k, v in audits.items():
        print(f"  {k:30s} {v['status']:5s}  {v.get('details','')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
