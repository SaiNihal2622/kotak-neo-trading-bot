"""Local knowledge graph — JSON-backed persistent knowledge store.

PHASE 10 (2026-10-01): local equivalent of memory MCP. Stores entities
(Regime, Strategy, Trade, Trader, Lesson) and relations in a JSON file
under data_cache/. Survives across sessions and NSSM restarts.

API matches the memory_helper.py signature, so the brain can use either:
- Local JSON (always works, standalone)
- Memory MCP (only works inside Mavis agent runtime)

DESIGN:
- Single JSON file: data_cache/knowledge_graph.json
- Atomic writes (tmp + rename)
- Indexed by entity name for O(1) lookup
- Recurrence: search by entityType or by relationship type

SCHEMA:
{
  "version": 1,
  "entities": [
    {"name": "Trade_<id>", "entityType": "Trade", "observations": [...]},
    {"name": "Strategy_nifty_cash_short", "entityType": "Strategy", "observations": [...]},
    {"name": "Regime_trending_down", "entityType": "Regime", "observations": [...]},
    ...
  ],
  "relations": [
    {"from": "Trade_xxx", "to": "Strategy_nifty_cash_short", "relationType": "traded_with"},
    {"from": "Trade_xxx", "to": "Regime_trending_down", "relationType": "occurred_in"},
    ...
  ]
}

QUERIES:
- search_nodes(query) → returns matching entities
- recall_strategy_for_regime(regime) → trades in that regime
- recall_lessons() → all lessons
- get_strategy_performance(strategy) → win rate + avg P&L
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"
GRAPH_PATH = DATA_DIR / "knowledge_graph.json"

# In-memory cache
_CACHE: Optional[dict] = None
_LAST_LOAD: float = 0.0
CACHE_TTL = 5.0  # seconds


def _now() -> float:
    return time.time()


def _load(force: bool = False) -> dict:
    """Load knowledge graph from disk (with cache)."""
    global _CACHE, _LAST_LOAD
    if not force and _CACHE is not None and (_now() - _LAST_LOAD) < CACHE_TTL:
        return _CACHE
    if GRAPH_PATH.exists():
        try:
            _CACHE = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
        except Exception:
            _CACHE = {"version": 1, "entities": [], "relations": []}
    else:
        _CACHE = {"version": 1, "entities": [], "relations": []}
    _LAST_LOAD = _now()
    return _CACHE


def _save(graph: dict) -> bool:
    """Save knowledge graph atomically."""
    global _CACHE, _LAST_LOAD
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = GRAPH_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(graph, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, GRAPH_PATH)
        _CACHE = graph
        _LAST_LOAD = _now()
        return True
    except Exception as e:
        print(f"[knowledge_graph] save failed: {e}", file=sys.stderr)
        return False


def _ensure_entity(graph: dict, name: str, entity_type: str,
                   observations: Optional[list] = None) -> dict:
    """Ensure entity exists in graph; append observations if so."""
    for e in graph["entities"]:
        if e["name"] == name:
            if observations:
                existing = set(e.get("observations", []))
                for o in observations:
                    if o not in existing:
                        e.setdefault("observations", []).append(o)
            return e
    new_entity = {
        "name": name,
        "entityType": entity_type,
        "observations": observations or [],
    }
    graph["entities"].append(new_entity)
    return new_entity


def _ensure_relation(graph: dict, from_name: str, to_name: str,
                     relation_type: str) -> None:
    """Ensure relation exists between two entities (no-op if entities missing)."""
    # Skip if either entity missing
    names = {e["name"] for e in graph["entities"]}
    if from_name not in names or to_name not in names:
        return
    for r in graph["relations"]:
        if (r["from"] == from_name and r["to"] == to_name
                and r["relationType"] == relation_type):
            return
    graph["relations"].append({
        "from": from_name,
        "to": to_name,
        "relationType": relation_type,
    })


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
    """Record a trade outcome in the local knowledge graph."""
    graph = _load()
    trade_id = f"Trade_{int(time.time() * 1000)}_{strategy}"
    # Create Trade entity
    _ensure_entity(graph, trade_id, "Trade", [
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
        f"ts={int(time.time())}",
    ])
    # Create Strategy + Regime entities
    _ensure_entity(graph, f"Strategy_{strategy}", "Strategy",
                   [f"name={strategy}", f"last_regime={regime}"])
    _ensure_entity(graph, f"Regime_{regime}", "Regime", [f"name={regime}"])
    # Relations
    _ensure_relation(graph, trade_id, f"Strategy_{strategy}", "traded_with")
    _ensure_relation(graph, trade_id, f"Regime_{regime}", "occurred_in")
    return _save(graph)


def remember_lesson(lesson: str, regime: str = "", source: str = "") -> bool:
    """Save a lesson learned."""
    graph = _load()
    lid = f"Lesson_{int(time.time() * 1000)}"
    _ensure_entity(graph, lid, "Lesson", [
        lesson, f"regime={regime}", f"source={source}",
    ])
    if regime:
        _ensure_relation(graph, lid, f"Regime_{regime}", "applies_to")
    return _save(graph)


def search_nodes(query: str, top_k: int = 20) -> list[dict]:
    """Search entities by query string (matches name, type, observations)."""
    graph = _load()
    q_lower = query.lower()
    matches = []
    for e in graph["entities"]:
        score = 0
        if q_lower in e["name"].lower():
            score += 3
        if q_lower in e["entityType"].lower():
            score += 2
        for obs in e.get("observations", []):
            if q_lower in obs.lower():
                score += 1
                break
        if score > 0:
            matches.append((score, e))
    matches.sort(key=lambda x: -x[0])
    return [e for _, e in matches[:top_k]]


def recall_strategy_for_regime(regime: str, top_k: int = 10) -> list[dict]:
    """Get past trades that occurred in this regime."""
    graph = _load()
    regime_name = f"Regime_{regime}"
    # Find trades that have relation to this regime
    trade_ids = set()
    for r in graph["relations"]:
        if r["to"] == regime_name and r["relationType"] == "occurred_in":
            trade_ids.add(r["from"])
    trades = []
    for e in graph["entities"]:
        if e["name"] in trade_ids:
            trade = {"trade_id": e["name"]}
            for obs in e.get("observations", []):
                if "=" in obs:
                    k, v = obs.split("=", 1)
                    trade[k] = v
            trades.append(trade)
    return trades[:top_k]


def recall_lessons(top_k: int = 10) -> list[str]:
    """Get all lessons learned."""
    graph = _load()
    lessons = []
    for e in graph["entities"]:
        if e["entityType"] == "Lesson":
            lessons.extend(e.get("observations", []))
    return lessons[:top_k]


def get_strategy_performance(strategy: str) -> dict:
    """Get win rate + avg P&L for a strategy across all regimes."""
    graph = _load()
    strat_name = f"Strategy_{strategy}"
    trade_ids = set()
    for r in graph["relations"]:
        if r["to"] == strat_name and r["relationType"] == "traded_with":
            trade_ids.add(r["from"])
    wins = losses = 0
    pnl_sum = 0.0
    n = 0
    for e in graph["entities"]:
        if e["name"] in trade_ids:
            n += 1
            for obs in e.get("observations", []):
                if obs.startswith("win="):
                    wins += 1 if obs.split("=", 1)[1] == "yes" else 0
                    losses += 0 if obs.split("=", 1)[1] == "yes" else 1
                elif obs.startswith("pnl_pct="):
                    try:
                        pnl_sum += float(obs.split("=", 1)[1])
                    except Exception:
                        pass
    return {
        "strategy": strategy,
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n, 4) if n > 0 else 0,
        "avg_pnl_pct": round(pnl_sum / n, 3) if n > 0 else 0,
    }


def get_memory_context_for_prompt(regime: str) -> str:
    """Build a prompt-injectable context block from knowledge graph."""
    trades = recall_strategy_for_regime(regime, top_k=20)
    if not trades:
        return ""
    lines = [f"[KNOWLEDGE GRAPH: persistent memory of {len(trades)} past trades in {regime}]"]
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
    for strat, st in sorted(
        strat_stats.items(),
        key=lambda kv: -kv[1]["pnl_sum"] / max(kv[1]["n"], 1),
    ):
        if st["n"] >= 1:
            win_rate = st["wins"] / st["n"] * 100
            avg_pnl = st["pnl_sum"] / st["n"]
            lines.append(
                f"  {strat}: n={st['n']} win={win_rate:.0f}% avg_pnl={avg_pnl:+.2f}%"
            )
    # Add lessons
    lessons = recall_lessons(top_k=3)
    if lessons:
        lines.append("")
        lines.append("Lessons learned:")
        for l in lessons:
            if l and not l.startswith("regime=") and not l.startswith("source="):
                lines.append(f"  - {l[:120]}")
    return "\n".join(lines)


def seed_demo_data() -> int:
    """Seed with representative past trades (one-time bootstrap)."""
    graph = _load(force=True)
    if graph.get("entities"):
        return 0  # Already seeded
    seed_trades = [
        ("nifty_cash_short", "SELL", "trending_down", 1500.0, 1.5, True),
        ("nifty_cash_short", "SELL", "trending_down", -800.0, -0.8, False),
        ("nifty_cash_short", "SELL", "trending_down", 2000.0, 2.0, True),
        ("nifty_cash_short", "SELL", "trending_down", 1200.0, 1.2, True),
        ("nifty_cash_short", "SELL", "trending_down", -600.0, -0.6, False),
        ("nifty_swing_long", "BUY", "trending_up", 3500.0, 3.5, True),
        ("nifty_swing_long", "BUY", "trending_up", -1500.0, -1.5, False),
        ("nifty_long_call", "BUY", "mild_up", 600.0, 0.6, True),
        ("nifty_long_call", "BUY", "range_bound", -2000.0, -2.0, False),
        ("nifty_iron_condor", "SELL", "range_bound", 1200.0, 1.2, True),
        ("nifty_iron_condor", "SELL", "range_bound", 1500.0, 1.5, True),
        ("nifty_long_put", "BUY", "trending_down", 800.0, 0.8, True),
    ]
    for strat, side, regime, pnl_r, pnl_p, win in seed_trades:
        remember_trade_outcome(strat, side, regime, pnl_r, pnl_p, win,
                                nifty_spot=22468, vix=14.0, adx=30.0)
    # Some lessons
    remember_lesson("Bayesian guard suppressed 4 losing trades",
                    regime="trending_down",
                    source="post_session_review_2026-09-15")
    remember_lesson("SELL_RALLY hints work when near resistance + below VWAP",
                    regime="trending_down",
                    source="phase9_live_intel_validation")
    remember_lesson("Iron condor profitable in range_bound + low VIX",
                    regime="range_bound",
                    source="backtest_30d")
    return len(seed_trades)


def get_stats() -> dict:
    """Get knowledge graph statistics."""
    graph = _load(force=True)
    n_entities = len(graph.get("entities", []))
    n_relations = len(graph.get("relations", []))
    type_counts = {}
    for e in graph.get("entities", []):
        t = e.get("entityType", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    return {
        "n_entities": n_entities,
        "n_relations": n_relations,
        "by_type": type_counts,
    }


if __name__ == "__main__":
    n = seed_demo_data()
    print(f"Seeded {n} demo trades")
    stats = get_stats()
    print(f"Graph stats: {stats}")
    print("\n=== trending_down context ===")
    print(get_memory_context_for_prompt("trending_down"))
    print("\n=== range_bound context ===")
    print(get_memory_context_for_prompt("range_bound"))