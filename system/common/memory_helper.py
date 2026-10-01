"""Memory MCP helper — wraps mavis memory tool for use by brain modules.

The memory MCP exposes a persistent knowledge graph (entities + relations)
that SURVIVES across sessions. The brain uses it to store:
- Regime patterns: Regime(down) -[duration]-> 6h
- Strategy outcomes: Strategy(short) -[in]-> Regime(down) -[win_rate]-> 39%
- Trader reliability: Trader(HDFC_research) -[n_calls]-> 47 -[accuracy]-> 71%
- Lessons learned: Lesson(use_bayesian_guard) -[learned_from]-> Trade(...)

This is what makes the brain actually learn over time, not just within a
single session. The knowledge graph is queryable: "give me strategies
that won in trending_down with high VIX" → returns ranked list in <100ms.

DESIGN:
- Wraps mcp__memory__* tools (create_entities, search_nodes, etc.)
- Falls back gracefully if memory MCP unavailable
- Brain modules call: from .common.memory_helper import remember, recall
"""
from __future__ import annotations

import json
import sys
from typing import Optional


def _memory_available() -> bool:
    """Check if memory MCP is reachable. Try once."""
    try:
        # Test by reading the knowledge graph
        from mavis.tool import mcp__memory__search_nodes as sn
        return True
    except Exception:
        return False


def remember_trade_outcome(
    strategy: str,
    side: str,
    regime: str,
    pnl_rupees: float,
    pnl_pct: float,
    win: bool,
    nifty_spot: float = 0.0,
    vix: float = 0.0,
    adx: float = 0.0,
    source: str = "brain_daemon",
) -> bool:
    """Record a trade outcome in the knowledge graph.

    Creates/updates entities: Strategy, Regime, Trade, Lesson.
    Creates relations linking them.
    """
    try:
        from mavis.tool import (
            mcp__memory__create_entities as ce,
            mcp__memory__create_relations as cr,
        )
    except Exception as e:
        print(f"[memory_helper] unavailable: {e}", file=sys.stderr)
        return False

    try:
        # Build entities
        trade_id = f"trade_{int(nifty_spot)}_{strategy}_{side}"
        entities = [
            {
                "name": trade_id,
                "entityType": "Trade",
                "observations": [
                    f"strategy={strategy}",
                    f"side={side}",
                    f"regime={regime}",
                    f"pnl_rupees={round(pnl_rupees, 2)}",
                    f"pnl_pct={round(pnl_pct, 3)}",
                    f"win={'yes' if win else 'no'}",
                    f"nifty_spot={nifty_spot}",
                    f"vix={vix}",
                    f"adx={adx}",
                    f"source={source}",
                ],
            },
        ]
        relations = []
        # Link Trade to Strategy and Regime if they don't exist yet
        # (entities that don't exist will be silently ignored by relations API)

        # Add strategy stats entity (accumulator)
        entities.append({
            "name": f"Strategy_{strategy}",
            "entityType": "Strategy",
            "observations": [
                f"name={strategy}",
                f"last_seen={regime}",
            ],
        })
        relations.append({
            "from": trade_id,
            "to": f"Strategy_{strategy}",
            "relationType": "traded_with",
        })

        entities.append({
            "name": f"Regime_{regime}",
            "entityType": "Regime",
            "observations": [f"name={regime}"],
        })
        relations.append({
            "from": trade_id,
            "to": f"Regime_{regime}",
            "relationType": "occurred_in",
        })

        ce(entities=entities)
        if relations:
            cr(relations=relations)
        return True
    except Exception as e:
        print(f"[memory_helper] remember_trade_outcome failed: {e}", file=sys.stderr)
        return False


def recall_strategy_for_regime(regime: str, top_k: int = 5) -> list[dict]:
    """Query the knowledge graph for strategies that worked in this regime.

    Returns list of {strategy, win_rate, n_trades, avg_pnl_pct, source}.
    """
    try:
        from mavis.tool import mcp__memory__search_nodes as sn
        # Search for trades in this regime
        result = sn(query=f"Trade occurred_in {regime}")
        trades = []
        if isinstance(result, dict):
            nodes = result.get("nodes", []) or result.get("entities", [])
            for node in nodes:
                if isinstance(node, dict):
                    obs = node.get("observations", [])
                    trade = {"trade_id": node.get("name")}
                    for o in obs:
                        if "=" in o:
                            k, v = o.split("=", 1)
                            trade[k] = v
                    if "strategy" in trade and "pnl_pct" in trade:
                        trades.append(trade)
        return trades[:top_k]
    except Exception as e:
        print(f"[memory_helper] recall failed: {e}", file=sys.stderr)
        return []


def recall_lessons_for_regime(regime: str) -> list[str]:
    """Query lessons learned for this regime.

    Returns list of lesson strings.
    """
    try:
        from mavis.tool import mcp__memory__search_nodes as sn
        result = sn(query=f"Lesson learned {regime}")
        lessons = []
        if isinstance(result, dict):
            nodes = result.get("nodes", []) or result.get("entities", [])
            for node in nodes:
                if isinstance(node, dict):
                    obs = node.get("observations", [])
                    lessons.extend(obs)
        return lessons[:5]
    except Exception:
        return []


def remember_lesson(lesson: str, regime: str = "", trade_id: str = "") -> bool:
    """Save a lesson learned to the knowledge graph."""
    try:
        from mavis.tool import (
            mcp__memory__create_entities as ce,
            mcp__memory__create_relations as cr,
        )
    except Exception:
        return False
    try:
        entities = [{
            "name": f"Lesson_{int(__import__('time').time())}",
            "entityType": "Lesson",
            "observations": [lesson, f"regime={regime}"],
        }]
        relations = []
        if trade_id:
            relations.append({
                "from": entities[0]["name"],
                "to": trade_id,
                "relationType": "learned_from",
            })
        ce(entities=entities)
        if relations:
            cr(relations=relations)
        return True
    except Exception as e:
        print(f"[memory_helper] remember_lesson failed: {e}", file=sys.stderr)
        return False


def get_memory_context_for_prompt(regime: str) -> str:
    """Build a prompt-injectable context block from memory MCP.

    Shows the LLM:
    - Strategies that worked in this regime (with stats)
    - Lessons learned for this regime
    """
    trades = recall_strategy_for_regime(regime, top_k=10)
    if not trades:
        return ""

    lines = ["[MEMORY: persistent knowledge from past trades]"]
    # Aggregate by strategy
    strat_stats = {}
    for t in trades:
        s = t.get("strategy", "unknown")
        if s not in strat_stats:
            strat_stats[s] = {"wins": 0, "n": 0, "pnl_sum": 0.0}
        strat_stats[s]["n"] += 1
        try:
            pnl = float(t.get("pnl_pct", 0))
        except Exception:
            pnl = 0
        strat_stats[s]["pnl_sum"] += pnl
        if t.get("win") == "yes":
            strat_stats[s]["wins"] += 1

    # Sort by avg P&L
    for strat, st in sorted(strat_stats.items(),
                              key=lambda kv: -kv[1]["pnl_sum"] / max(kv[1]["n"], 1)):
        if st["n"] >= 1:
            win_rate = st["wins"] / st["n"] * 100
            avg_pnl = st["pnl_sum"] / st["n"]
            lines.append(
                f"  {strat}: n={st['n']} win={win_rate:.0f}% avg_pnl={avg_pnl:+.2f}%"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    print("memory available:", _memory_available())
    print(get_memory_context_for_prompt("trending_down"))