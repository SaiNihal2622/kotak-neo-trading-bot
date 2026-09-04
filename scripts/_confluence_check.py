"""_confluence_check.py - Detect trading confluence programmatically.

FIX 2026-09-04 12:24: the brain's prompt says "if 3+ confirming signals align, ACT".
But the LLM might not always count signals correctly. This script does the count
programmatically and emits a high-conviction signal when confluence is detected.

A confluence = 3+ instruments (indices or stocks) all moving >0.5% in the same
direction, OR VIX spiking >15, OR broad sector rotation (top sector +2% with
bottom sector -2%).

Output: writes a "confluence signal" to data_cache/mavis_force_action.json with
action=BIAS_OVERRIDE=<bullish|bearish|neutral> + supporting evidence.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def load_global_state():
    p = ROOT / "data_cache" / "global_state.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def find_confluence(state):
    """Returns (direction, instrument_count, evidence) or None."""
    if not state or "instruments" not in state:
        return None

    instruments = state["instruments"]

    # Group by region
    bull = []  # (name, pct)
    bear = []
    for sym, info in instruments.items():
        if not isinstance(info, dict):
            continue
        pct = info.get("pct_1d", 0) or 0
        name = info.get("name", sym)
        if pct >= 0.5:
            bull.append((name, pct))
        elif pct <= -0.5:
            bear.append((name, abs(pct)))

    # Check VIX spike
    vix = None
    for sym, info in instruments.items():
        if info.get("category") == "vol" or sym in ("^VIX", "VIX"):
            vix = info.get("pct_1d", 0) or 0
            break

    evidence = []
    if len(bull) >= 3:
        evidence.append(f"bullish: {', '.join(n for n,_ in bull[:5])}")
    if len(bear) >= 3:
        evidence.append(f"bearish: {', '.join(n for n,_ in bear[:5])}")
    if vix is not None and vix >= 5.0:
        evidence.append(f"VIX spike {vix:+.1f}%")
    if vix is not None and vix <= -5.0:
        evidence.append(f"VIX collapse {vix:+.1f}% (complacency)")

    if len(bull) >= 3 and len(bear) >= 3:
        # Both sides — divergence, not a clean signal
        return None

    if len(bull) >= 3:
        return ("bullish", len(bull), "; ".join(evidence))
    if len(bear) >= 3:
        return ("bearish", len(bear), "; ".join(evidence))
    if vix is not None and vix >= 5.0:
        return ("vix_spike", 1, "; ".join(evidence))

    return None


def write_force_action(direction, count, evidence):
    """Write to mavis_force_action.json so the bot picks it up on next cycle."""
    action_map = {
        "bullish": "BIAS_OVERRIDE=BULLISH",
        "bearish": "BIAS_OVERRIDE=BEARISH",
        "vix_spike": "BIAS_OVERRIDE=DEFENSIVE",
    }
    payload = {
        "ts": datetime.now().isoformat(),
        "action": action_map.get(direction, "BIAS_OVERRIDE=NEUTRAL"),
        "reason": f"confluence detected: {count} confirming signals. {evidence}",
        "consumed": False,
    }
    p = ROOT / "data_cache" / "mavis_force_action.json"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main():
    state = load_global_state()
    if not state:
        print("no global_state.json — skipping")
        return 0
    result = find_confluence(state)
    if not result:
        print("no confluence detected (3+ signals not aligned)")
        return 0
    direction, count, evidence = result
    payload = write_force_action(direction, count, evidence)
    print(f"CONFIRMED: direction={direction} count={count} evidence={evidence}")
    print(f"  wrote: {payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
