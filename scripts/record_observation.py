"""record_observation.py — record current market state to the knowledge graph.

Writes a time-stamped entity describing the current market state to the
mavis memory MCP knowledge graph. Called from the trader cron after each tick.

NOTE: This script imports the trader_state pipeline directly (no subprocess)
so the caller (cron) can also write a brief chat note.

Usage:
    python scripts/record_observation.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def main() -> int:
    # Load the trader state JSON
    try:
        # Use the same import as trader_state so the JSON is identical
        import importlib
        mod = importlib.import_module("scripts.trader_state")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            mod.main()
        out = buf.getvalue()
        state = json.loads(out)
    except Exception as e:
        print(f"[record_observation] could not load state: {e}", file=sys.stderr)
        return 1

    ist = state.get("ts_ist", "")
    vix = state.get("vix")
    regime_n = state.get("candle_regime", {}).get("NIFTY", {})
    macro = state.get("macro", {})
    research = state.get("research", {})
    strat = state.get("strategy_version", {})
    cash = state.get("cash", 0)
    pnl = state.get("realized_pnl", 0)
    n_pos = len(state.get("open_positions", []))

    # Build a unique entity name per tick (date + time truncated to 5min)
    tick_key = ist.replace(" ", "T").replace(":", "")[:13]  # YYYY-MM-DDTHHMM
    entity_name = f"trader-tick-{tick_key}"
    observations = [
        f"ts_ist={ist}",
        f"vix={vix}",
        f"regime_nifty={regime_n.get('regime', '?')} (conf={regime_n.get('confidence', 0):.2f}, reason='{regime_n.get('reason', '?')}')",
        f"cash=Rs.{cash:.0f}",
        f"realized_pnl=Rs.{pnl:+.0f}",
        f"open_positions={n_pos}",
        f"macro_in_blackout={macro.get('in_blackout', False)}",
        f"macro_next_event_min={macro.get('next_event_min')}",
        f"research_available={research.get('available', False)}",
        f"strategy_head={strat.get('head_short', '?')}",
        f"strategy_dirty={strat.get('strategy_dirty', False)}",
    ]
    obs_text = json.dumps(observations, indent=2, default=str)
    # Use the mavis native memory tool via subprocess — simpler than direct import
    # since the MCP server is the canonical way.
    payload = {
        "entities": [
            {"name": entity_name, "entityType": "trader_tick",
             "observations": observations}
        ]
    }
    out_path = ROOT / "data_cache" / "knowledge_graph_payload.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, default=str) + "\n")

    print(f"[record_observation] queued entity {entity_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
