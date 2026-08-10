"""Position reconciliation: compare internal state vs broker state.
Runs every 5 min; alerts on any mismatch (orphan order, missed fill, etc).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


def reconcile_positions(broker_positions: dict, internal_positions: dict) -> dict:
    """Compare broker state vs internal state. Returns diff dict.
    broker_positions: {symbol: {qty, avg_price, ltp, ...}}
    internal_positions: {symbol: {qty, avg_price, ltp, ...}}
    """
    all_syms = set(broker_positions.keys()) | set(internal_positions.keys())
    diff = {
        "matched": [],
        "broker_only": [],
        "internal_only": [],
        "qty_mismatch": [],
        "as_of": datetime.utcnow().isoformat(),
    }
    for s in all_syms:
        b = broker_positions.get(s)
        i = internal_positions.get(s)
        if b and i:
            if b.get("qty") == i.get("qty"):
                diff["matched"].append(s)
            else:
                diff["qty_mismatch"].append({
                    "symbol": s,
                    "broker_qty": b.get("qty"),
                    "internal_qty": i.get("qty"),
                    "diff": b.get("qty", 0) - i.get("qty", 0),
                })
        elif b and not i:
            diff["broker_only"].append({"symbol": s, "broker_qty": b.get("qty")})
        elif i and not b:
            diff["internal_only"].append({"symbol": s, "internal_qty": i.get("qty")})
    return diff


def format_diff_for_telegram(diff: dict) -> str:
    """Format reconciliation diff for Telegram alert."""
    if not diff["broker_only"] and not diff["internal_only"] and not diff["qty_mismatch"]:
        return None  # no diff, no alert
    lines = ["⚠️ POSITION RECONCILIATION MISMATCH", "=" * 40]
    if diff["matched"]:
        lines.append(f"✅ Matched: {len(diff['matched'])} symbols")
    if diff["broker_only"]:
        lines.append(f"❌ Broker only (orphans in broker): {len(diff['broker_only'])}")
        for x in diff["broker_only"][:5]:
            lines.append(f"   {x['symbol']} qty={x['broker_qty']}")
    if diff["internal_only"]:
        lines.append(f"❌ Internal only (not in broker): {len(diff['internal_only'])}")
        for x in diff["internal_only"][:5]:
            lines.append(f"   {x['symbol']} qty={x['internal_qty']}")
    if diff["qty_mismatch"]:
        lines.append(f"❌ Qty mismatch: {len(diff['qty_mismatch'])}")
        for x in diff["qty_mismatch"][:5]:
            lines.append(f"   {x['symbol']} broker={x['broker_qty']} internal={x['internal_qty']}")
    return "\n".join(lines)


def save_reconcile_log(diff: dict, path: Path = Path("data_cache/reconcile.jsonl")) -> None:
    """Append reconciliation result to audit log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(diff, default=str) + "\n")
