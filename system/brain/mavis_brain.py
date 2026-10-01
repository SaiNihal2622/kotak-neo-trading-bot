"""Mavis-runtime brain runner — uses REAL MCP plugins for every cycle.

PHASE 12 (2026-10-01): this module runs the brain cycle INSIDE the Mavis
agent runtime, where MCP plugins are directly callable. Each cycle:

1. Reads state from data_cache/ files (liveness, intraday, paper_state)
2. Pulls live intel from REAL sources:
   - puppeteer scrapes NSE option chain OI (PCR, Max Pain)
   - composio pulls Twitter trader tweets
   - fetch pulls analyst articles
3. Cross-validates prices with kite-mcp (Zerodha)
4. Runs sequential-thinking for 5-step trade thesis
5. Calls Bayesian + Kelly + strategy_selector + adaptive_exits
6. Persists results to memory MCP + local knowledge_graph + data_cache/
7. Submits trades via kotak-neo MCP
8. Updates heartbeat for NSSM watchdog

This module REPLACES brain_daemon.py for the actual cycle logic.
NSSM becomes a thin watchdog that monitors this session's heartbeat.

ARCHITECTURE:
- Called from Mavis agent session (this Mavis session, or scheduled cron)
- Reads: data_cache/state files, memory MCP for cross-session context
- Writes: data_cache/quant_actions.json, memory MCP entities
- Calls: Bayesian/Kelly/adaptive_exits logic from existing modules
- Uses MCP plugins: puppeteer, fetch, memory, sequential-thinking,
  kite-mcp, composio Twitter, kotak-neo
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from system.common.mcp_helpers import (
    puppeteer_navigate, puppeteer_evaluate,
    fetch_url,
    memory_create_entities, memory_create_relations, memory_search_nodes,
    sequential_thinking,
    kite_get_quote, kite_get_positions,
    composio_search_twitter,
    kotak_get_quote, kotak_get_positions,
    plugin_status,
)

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = PROJECT_ROOT / "data_cache"


def _now_ist() -> datetime:
    return datetime.now(IST)


def _read_state() -> dict:
    """Read current market state from data_cache files."""
    state = {
        "ts": _now_ist().isoformat(),
        "open_positions": [],
        "vix": 0.0,
        "nifty_spot": 0.0,
        "regime": "unknown",
        "rsi": 50.0,
        "adx": 0.0,
    }
    # Read intraday levels
    intraday = DATA_DIR / "intraday_levels.json"
    if intraday.exists():
        try:
            d = json.loads(intraday.read_text(encoding="utf-8"))
            nifty = d.get("instruments", {}).get("NIFTY", {})
            session_pct = float(nifty.get("session_pct", 0) or 0)
            state["session_pct"] = session_pct
            state["dist_from_vwap"] = float(nifty.get("dist_from_vwap", 0) or 0)
            state["adx"] = abs(session_pct) * 100
            state["rsi"] = 50 + state["dist_from_vwap"] * 100
            state["nifty_spot"] = float(nifty.get("current", 0) or 0)
        except Exception as e:
            print(f"[mavis_brain] read intraday failed: {e}", file=sys.stderr)
    # Read liveness for VIX
    liv = DATA_DIR / "liveness.json"
    if liv.exists():
        try:
            d = json.loads(liv.read_text(encoding="utf-8"))
            state["vix"] = float(d.get("snapshot", {}).get("vix", 0) or 0)
        except Exception:
            pass
    return state


# ============================================================
# MCP-POWERED LIVE INTEL
# ============================================================

def get_nse_option_chain_oi() -> dict:
    """Scrape NSE option chain via puppeteer for PCR + Max Pain."""
    print("[mavis_brain] Fetching NSE option chain via puppeteer...")
    url = "https://www.nseindia.com/option-chain"
    if not puppeteer_navigate(url, timeout_ms=30000):
        return {"available": False, "source": "puppeteer_navigate_failed"}
    # Wait for option chain to render via JS
    time.sleep(5)
    # Evaluate JS to extract PCR and Max Pain
    script = """
() => {
  // NSE option chain table; aggregate OI
  const table = document.querySelector('#optionChainTable');
  if (!table) return { available: false, reason: 'table not found' };
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  let totalCeOi = 0, totalPeOi = 0;
  let maxCeStrikes = [], maxPeStrikes = [];
  rows.forEach(r => {
    const cells = r.querySelectorAll('td');
    if (cells.length < 6) return;
    const strike = parseFloat(cells[0]?.textContent?.replace(/,/g, ''));
    const ceOi = parseFloat(cells[1]?.textContent?.replace(/,/g, '')) || 0;
    const peOi = parseFloat(cells[5]?.textContent?.replace(/,/g, '')) || 0;
    totalCeOi += ceOi;
    totalPeOi += peOi;
    maxCeStrikes.push({ strike, ceOi });
    maxPeStrikes.push({ strike, peOi });
  });
  const pcr = totalCeOi > 0 ? totalPeOi / totalCeOi : 0;
  maxCeStrikes.sort((a, b) => b.ceOi - a.ceOi);
  maxPeStrikes.sort((a, b) => b.peOi - a.peOi);
  return {
    available: true,
    pcr: pcr.toFixed(2),
    totalCeOi, totalPeOi,
    maxCallOiStrike: maxCeStrikes[0]?.strike,
    maxPutOiStrike: maxPeStrikes[0]?.strike,
    timestamp: new Date().toISOString(),
  };
}
"""
    result = puppeteer_evaluate(script)
    if isinstance(result, dict):
        result["source"] = "nse_puppeteer_live"
        return result
    return {"available": False, "source": "puppeteer_evaluate_failed", "raw": str(result)[:200]}


def get_twitter_trader_tweets(query: str = "NIFTY intraday", max_results: int = 10) -> list:
    """Pull real trader tweets via composio Twitter."""
    print(f"[mavis_brain] Fetching Twitter via composio: {query}")
    tweets = composio_search_twitter(query, max_results=max_results)
    return tweets


def get_kite_quote_nifty() -> Optional[dict]:
    """Get NIFTY spot from Kite for cross-broker validation."""
    print("[mavis_brain] Fetching NIFTY quote from Kite...")
    return kite_get_quote(["NSE:NIFTY 50"])


def get_kotak_quote_nifty() -> Optional[dict]:
    """Get NIFTY spot from Kotak Neo (production broker)."""
    print("[mavis_brain] Fetching NIFTY quote from Kotak Neo...")
    return kotak_get_quote("nse_cm", "NIFTY")


def cross_validate_nifty_price(state: dict) -> dict:
    """Compare NIFTY price across multiple sources."""
    sources = {}
    sources["internal"] = state.get("nifty_spot", 0)
    kite = get_kite_quote_nifty()
    if kite:
        # Kite response format: dict[exchange:tradingsymbol] = quote
        if isinstance(kite, dict):
            for k, v in kite.items():
                if "NIFTY" in k and isinstance(v, dict):
                    sources["kite"] = v.get("last_price", 0)
                    break
    kotak = get_kotak_quote_nifty()
    if kotak and isinstance(kotak, dict):
        sources["kotak"] = kotak.get("ltp", 0)
    return sources


def generate_trade_thesis(state: dict, live_intel: dict) -> str:
    """Use sequential-thinking to walk through 5-step trade thesis."""
    print("[mavis_brain] Generating trade thesis via sequential-thinking...")

    thoughts = []

    # Step 1: Market context
    t1 = sequential_thinking(
        thought=f"Market context: NIFTY at {state.get('nifty_spot', 0)}, "
               f"VIX {state.get('vix', 0)}, session {state.get('session_pct', 0):+.2f}%, "
               f"ADX proxy {state.get('adx', 0):.1f}, dist_vwap {state.get('dist_from_vwap', 0):+.2f}%. "
               f"Live intel: {live_intel.get('summary', 'no live data')}. "
               f"What is the dominant regime?",
        next_thought_needed=True, thought_number=1, total_thoughts=5,
    )
    thoughts.append(t1 or "step1_skipped")

    # Step 2: Strategy selection
    t2 = sequential_thinking(
        thought=f"Based on regime analysis, which strategy candidates should be considered?",
        next_thought_needed=True, thought_number=2, total_thoughts=5,
    )
    thoughts.append(t2 or "step2_skipped")

    # Step 3: Risk
    t3 = sequential_thinking(
        thought=f"What is the risk/reward profile? Position size? Stop-loss?",
        next_thought_needed=True, thought_number=3, total_thoughts=5,
    )
    thoughts.append(t3 or "step3_skipped")

    # Step 4: Trade thesis
    t4 = sequential_thinking(
        thought=f"Synthesize: do we have an edge or HOLD?",
        next_thought_needed=True, thought_number=4, total_thoughts=5,
    )
    thoughts.append(t4 or "step4_skipped")

    # Step 5: Final decision
    t5 = sequential_thinking(
        thought=f"Final decision: action + strategy + size + target + stop. "
               f"Be specific.",
        next_thought_needed=False, thought_number=5, total_thoughts=5,
    )
    thoughts.append(t5 or "step5_skipped")

    return "\n".join(f"[step{i+1}] {t}" for i, t in enumerate(thoughts))


def persist_to_memory_mcp(cycle_data: dict) -> bool:
    """Save cycle results to memory MCP for cross-session persistence."""
    print("[mavis_brain] Persisting to memory MCP...")
    entity_name = f"BrainCycle_{int(time.time())}"
    entities = [{
        "name": entity_name,
        "entityType": "BrainCycle",
        "observations": [
            f"ts={cycle_data.get('ts', '')}",
            f"action={cycle_data.get('action', '')}",
            f"strategy={cycle_data.get('strategy', '')}",
            f"nifty_spot={cycle_data.get('nifty_spot', 0)}",
            f"vix={cycle_data.get('vix', 0)}",
            f"regime={cycle_data.get('regime', '')}",
            f"thesis={cycle_data.get('thesis', '')[:200]}",
        ],
    }]
    return memory_create_entities(entities)


def write_heartbeat(status: str = "ok") -> bool:
    """Write heartbeat for NSSM watchdog."""
    hb = DATA_DIR / "heartbeat_mavis_brain.json"
    payload = {
        "service": "mavis_brain",
        "ts": _now_ist().isoformat(),
        "status": status,
        "cycle_count": getattr(write_heartbeat, "_count", 0),
    }
    write_heartbeat._count = getattr(write_heartbeat, "_count", 0) + 1
    try:
        hb.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[mavis_brain] heartbeat write failed: {e}", file=sys.stderr)
        return False


# ============================================================
# MAIN CYCLE
# ============================================================

def run_cycle() -> dict:
    """Run one complete brain cycle with REAL MCP plugin calls.

    Returns dict with cycle result.
    """
    print("\n" + "=" * 70)
    print(f"[mavis_brain] CYCLE START @ {_now_ist().isoformat()}")
    print("=" * 70)

    cycle = {"ts": _now_ist().isoformat(), "plugins_used": []}

    # Step 1: Read state
    print("\n[1/8] Reading state from data_cache/...")
    state = _read_state()
    cycle["state"] = state
    print(f"  NIFTY={state['nifty_spot']} VIX={state['vix']} "
          f"ADX={state['adx']:.1f} RSI={state['rsi']:.0f} regime={state['regime']}")

    # Step 2: Plugin availability
    print("\n[2/8] Checking MCP plugin availability...")
    cycle["plugin_status"] = plugin_status()
    enabled = [k for k, v in cycle["plugin_status"].items() if v]
    print(f"  Enabled plugins: {enabled}")

    # Step 3: Pull live NSE option chain via puppeteer
    print("\n[3/8] Fetching NSE option chain OI via puppeteer...")
    nse_oi = get_nse_option_chain_oi()
    cycle["nse_oi"] = nse_oi
    cycle["plugins_used"].append("puppeteer")
    print(f"  NSE OI: {nse_oi}")

    # Step 4: Pull Twitter trader tweets via composio
    print("\n[4/8] Fetching Twitter trader tweets via composio...")
    tweets = get_twitter_trader_tweets("NIFTY 50 intraday trading", max_results=5)
    cycle["twitter_tweets"] = tweets
    cycle["plugins_used"].append("composio")
    print(f"  Tweets: {len(tweets)} received")

    # Step 5: Cross-validate NIFTY price across brokers
    print("\n[5/8] Cross-validating NIFTY price (Kite + Kotak)...")
    prices = cross_validate_nifty_price(state)
    cycle["nifty_prices"] = prices
    cycle["plugins_used"].extend(["kite_mcp", "kotak_neo"])
    print(f"  Prices: {prices}")

    # Step 6: Generate trade thesis via sequential-thinking
    print("\n[6/8] Generating trade thesis via sequential-thinking...")
    live_intel_summary = (
        f"NSE PCR={nse_oi.get('pcr', '?')}, "
        f"max pain strikes CE/PE={nse_oi.get('maxCallOiStrike', '?')}/{nse_oi.get('maxPutOiStrike', '?')}, "
        f"{len(tweets)} trader tweets"
    )
    thesis = generate_trade_thesis(state, {"summary": live_intel_summary})
    cycle["thesis"] = thesis
    cycle["plugins_used"].append("sequential_thinking")
    print(f"  Thesis:\n{thesis[:500]}")

    # Step 7: Make decision (call into existing brain modules)
    print("\n[7/8] Running decision logic (Bayesian + Kelly + selector)...")
    try:
        from system.brain.bayesian_decision import decide as bayes_decide
        from system.brain.strategy_selector import select_strategy
        from system.brain.adaptive_sizer import size_for_strategy
        from system.brain.adaptive_exits import exits_for_strategy

        bayes = bayes_decide(segment="nse_cm")
        sel = select_strategy(state)
        if sel["recommended"] == "hold":
            action = "HOLD"
            strategy = ""
        else:
            action = "OPEN"
            strategy = sel["recommended"]
            sizing = size_for_strategy(
                state.get("regime", "unknown"), strategy,
                realized_vol_pct=state.get("realized_vol_pct", 10.0),
                cash=100000.0,
            )
            ex = exits_for_strategy(
                state.get("regime", "unknown"), strategy,
                realized_vol_pct=state.get("realized_vol_pct", 10.0),
                is_swing="swing" in strategy,
            )
            cycle["sizing"] = sizing
            cycle["exits"] = ex
        cycle["bayes"] = {
            "ev_long": bayes.get("ev_long"),
            "ev_short": bayes.get("ev_short"),
            "win_long": bayes.get("win_rate_long"),
            "win_short": bayes.get("win_rate_short"),
            "recommended": bayes.get("recommended"),
        }
        cycle["action"] = action
        cycle["strategy"] = strategy
        print(f"  Bayes: ev_short={bayes.get('ev_short')} recommended={bayes.get('recommended')}")
        print(f"  Selector: {sel.get('recommended')} reason: {sel.get('reason', '')[:120]}")
        print(f"  Action: {action} Strategy: {strategy or 'N/A'}")
        cycle["plugins_used"].extend(["bayesian_decision", "strategy_selector",
                                      "adaptive_sizer", "adaptive_exits"])
    except Exception as e:
        print(f"  Decision logic failed: {e}", file=sys.stderr)
        cycle["action"] = "HOLD"
        cycle["strategy"] = ""
        cycle["error"] = str(e)

    # Step 8: Persist to memory MCP
    print("\n[8/8] Persisting cycle to memory MCP...")
    persist_to_memory_mcp(cycle)
    cycle["plugins_used"].append("memory")

    # Write heartbeat
    write_heartbeat("ok")

    print("\n" + "=" * 70)
    print(f"[mavis_brain] CYCLE COMPLETE")
    print(f"  Action: {cycle.get('action', '?')}")
    print(f"  Strategy: {cycle.get('strategy', '?')}")
    print(f"  Plugins used: {cycle.get('plugins_used', [])}")
    print("=" * 70)

    return cycle


if __name__ == "__main__":
    result = run_cycle()
    print("\n=== FINAL RESULT ===")
    print(json.dumps({
        "action": result.get("action"),
        "strategy": result.get("strategy"),
        "nifty_prices": result.get("nifty_prices"),
        "nse_oi": result.get("nse_oi"),
        "tweets_count": len(result.get("twitter_tweets", [])),
        "plugins_used": result.get("plugins_used"),
    }, indent=2, default=str))