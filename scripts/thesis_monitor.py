"""Thesis Monitor — proactive position-vs-thesis watcher.

Reads:
  - data_cache/thesis/latest.json  (bias, regime, triggers, risk_budget)
  - data_cache/paper_state.json    (current positions + PnL)

Writes:
  - data_cache/brain_actions.json   (if any proposal needed)

Decisions:
  - If thesis.triggers.force_square is True AND positions are open:
        -> propose CLOSE on all open positions
  - If thesis.triggers.no_new_trades is True:
        -> set max_positions = current open count (no new)
  - If thesis.bias flipped from prev snapshot AND we have opposing positions:
        -> propose REDUCE (close half or all of opposing legs)
  - If thesis.confidence dropped >0.2 since prev snapshot:
        -> propose REDUCE to 1 position
  - Otherwise: pass-through (leave brain_actions.json as-is for the trader-desk cron)

Always preserves a 'last_monitor_ts' so multiple invocations don't loop.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

from loguru import logger

THESIS_LATEST = ROOT / "data_cache" / "thesis" / "latest.json"
THESIS_HISTORY = ROOT / "data_cache" / "thesis_history.jsonl"
PAPER_STATE = ROOT / "data_cache" / "paper_state.json"
BRAIN_ACTIONS = ROOT / "data_cache" / "brain_actions.json"
PROPOSAL_LOG = ROOT / "data_cache" / "thesis_proposals.jsonl"


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_prev_thesis() -> dict | None:
    if not THESIS_HISTORY.exists():
        return None
    try:
        lines = THESIS_HISTORY.read_text(encoding="utf-8").splitlines()
        if len(lines) < 2:
            return None
        return json.loads(lines[-2])
    except Exception:
        return None


def _read_curr_thesis() -> dict | None:
    return _read_json(THESIS_LATEST, None)


def _read_open_positions() -> list[dict]:
    st = _read_json(PAPER_STATE, {})
    pos = st.get("positions") or {}
    out = []
    for tid, p in pos.items():
        out.append({
            "id": tid,
            "symbol": p.get("symbol") or p.get("tradingsymbol"),
            "side": p.get("side"),
            "qty": p.get("qty") or p.get("quantity"),
            "pnl": p.get("pnl") or p.get("unrealized"),
        })
    return out


def _existing_actions() -> dict:
    return _read_json(BRAIN_ACTIONS, {})


def _write_actions(actions: dict, note: str | None = None) -> None:
    actions = dict(actions)  # copy
    actions.setdefault("ts", datetime.utcnow().isoformat() + "Z")
    actions.setdefault("source", "thesis_monitor")
    if note:
        actions["note"] = (actions.get("note", "") + f" | {note}").strip(" |")
    BRAIN_ACTIONS.write_text(json.dumps(actions, indent=2, default=str), encoding="utf-8")
    with open(PROPOSAL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": actions["ts"],
            "note": actions.get("note", ""),
            "actions_count": len(actions.get("actions", [])),
            "max_positions": actions.get("max_positions"),
        }) + "\n")


def _append_close_proposal(existing: dict, reason: str) -> dict:
    actions = list(existing.get("actions", []))
    pos = _read_open_positions()
    for p in pos:
        # propose CLOSE (the bot translates into 4 opposite orders per IC leg)
        actions.append({
            "action": "CLOSE",
            "trade_id": p["id"],
            "symbol": p["symbol"],
            "qty": p.get("qty", 0),
            "reason": reason,
        })
    existing["actions"] = actions
    existing["max_positions"] = 0
    return existing


def _cap_positions(existing: dict, new_cap: int, reason: str) -> dict:
    existing["max_positions"] = new_cap
    if existing.get("note"):
        existing["note"] = f"{existing['note']} | cap={new_cap}: {reason}"
    else:
        existing["note"] = f"cap={new_cap}: {reason}"
    return existing


def monitor() -> dict:
    """Run one monitoring pass. Returns the proposal that was written."""
    t0 = time.time()
    thesis = _read_curr_thesis()
    if not thesis:
        logger.info("thesis_monitor: no thesis yet, skipping")
        return {"status": "no_thesis"}

    bias = thesis.get("bias", "neutral")
    conf = float(thesis.get("confidence", 0.0))
    triggers = thesis.get("triggers", {}) or {}
    age_min = None
    try:
        from datetime import datetime as _dt
        # thesis.ts is a local-ISO datetime (from thesis_engine, IST) without tz suffix.
        # Compare against local now() — strip tz from parsed value if any.
        ts_raw = thesis["ts"].replace("Z", "+00:00")
        ts_parsed = _dt.fromisoformat(ts_raw)
        if ts_parsed.tzinfo is not None:
            ts_parsed = ts_parsed.replace(tzinfo=None)
        age_min = (_dt.now() - ts_parsed).total_seconds() / 60
    except Exception:
        pass
    if age_min is None or age_min > 180:
        logger.info(f"thesis_monitor: thesis too old ({age_min} min), skipping")
        return {"status": "stale", "age_min": age_min}

    prev = _read_prev_thesis()
    prev_bias = prev.get("bias") if prev else None
    prev_conf = float(prev.get("confidence", 0.0)) if prev else 0.0
    bias_flipped = prev_bias and prev_bias != bias
    conf_dropped = (prev_conf - conf) > 0.2

    pos = _read_open_positions()
    existing = _existing_actions()
    proposals = []

    # 1. force_square trigger
    if triggers.get("force_square") and pos:
        existing = _append_close_proposal(existing, "thesis: force_square")
        proposals.append(f"force_square: {len(pos)} positions")
        logger.warning(f"thesis_monitor: force_square — proposing CLOSE on {len(pos)} positions")

    # 2. no_new_trades cap
    elif triggers.get("no_new_trades"):
        open_count = len(pos)
        if existing.get("max_positions", 99) > open_count:
            existing = _cap_positions(existing, open_count, "no_new_trades")
            proposals.append(f"no_new_trades cap={open_count}")

    # 3. bias flip while in opposing positions
    if bias_flipped and pos:
        # conservative: cap to 1 and let the trader cron take it from there
        existing = _cap_positions(existing, 1, f"bias flipped {prev_bias}->{bias}")
        proposals.append(f"bias flip {prev_bias}->{bias}, cap=1")
        logger.warning(f"thesis_monitor: bias flipped {prev_bias} -> {bias}, capping to 1 position")

    # 4. confidence dropped sharply
    elif conf_dropped and pos:
        existing = _cap_positions(existing, 1, f"conf dropped {prev_conf:.0%}->{conf:.0%}")
        proposals.append(f"conf drop {prev_conf:.0%}->{conf:.0%}, cap=1")

    # 5. low confidence + open positions -> reduce
    if conf < 0.4 and len(pos) > 0 and not proposals:
        existing = _cap_positions(existing, 1, f"low conf {conf:.0%}")
        proposals.append(f"low conf {conf:.0%}, cap=1")

    if proposals:
        existing["thesis_at_check"] = {
            "bias": bias, "confidence": conf, "ts": thesis.get("ts"),
            "prev_bias": prev_bias, "prev_conf": prev_conf,
        }
        _write_actions(existing, note=f"thesis_monitor: {'; '.join(proposals)}")
        logger.info(f"thesis_monitor: wrote {len(proposals)} proposal(s) in {int((time.time()-t0)*1000)}ms")
    else:
        logger.info(f"thesis_monitor: no action needed (bias={bias}, conf={conf:.0%}, pos={len(pos)})")

    return {
        "status": "ok",
        "proposals": proposals,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "thesis_bias": bias,
        "thesis_confidence": conf,
        "open_positions": len(pos),
    }


def main() -> int:
    out = monitor()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
