"""MCP plugin helpers — wraps all available MCP plugins with graceful fallback.

PHASE 12 (2026-10-01): single import surface for ALL MCP plugins used by the
brain. Each helper has a graceful fallback so the brain works even when a
plugin is unavailable (offline, rate-limited, etc.).

Available MCP plugins in Mavis runtime:
- puppeteer: browser automation (NSE option chain OI, Twitter)
- fetch: URL → markdown/text
- memory: persistent knowledge graph (entities + relations)
- sequential-thinking: step-by-step reasoning
- kite-mcp: Zerodha Kite broker (cross-broker validation)
- composio: 1000+ apps via OAuth (Twitter, Slack, Gmail, etc.)
- kotak-neo: official Kotak Neo MCP (production broker)

Helper design:
- Each helper returns None/empty on failure (never raises)
- Brain calls helpers and uses fallback data if plugin unavailable
- All helpers logged with their plugin + result status
"""
from __future__ import annotations

import json
import sys
from typing import Optional


def _safe_call(plugin_name: str, fn, *args, **kwargs):
    """Call MCP plugin function with error handling."""
    try:
        result = fn(*args, **kwargs)
        return result
    except Exception as e:
        print(f"[mcp_helpers] {plugin_name} call failed: {e}", file=sys.stderr)
        return None


# ============================================================
# PUPPETEER — browser automation
# ============================================================

def puppeteer_navigate(url: str, timeout_ms: int = 30000) -> bool:
    """Navigate to a URL. Returns True on success."""
    try:
        from mavis.tool import mcp__puppeteer__puppeteer_navigate as nav
        return _safe_call("puppeteer_navigate", nav, url, timeout=timeout_ms) or False
    except Exception as e:
        print(f"[mcp_helpers] puppeteer_navigate unavailable: {e}", file=sys.stderr)
        return False


def puppeteer_evaluate(script: str, timeout_ms: int = 10000) -> any:
    """Execute JS in browser, return result."""
    try:
        from mavis.tool import mcp__puppeteer__puppeteer_evaluate as ev
        return _safe_call("puppeteer_evaluate", ev, script)
    except Exception as e:
        print(f"[mcp_helpers] puppeteer_evaluate unavailable: {e}", file=sys.stderr)
        return None


def puppeteer_screenshot(name: str, path: Optional[str] = None) -> Optional[str]:
    """Take screenshot, save to disk."""
    try:
        from mavis.tool import mcp__puppeteer__puppeteer_screenshot as ss
        return _safe_call("puppeteer_screenshot", ss, name=name, encoded=False)
    except Exception as e:
        print(f"[mcp_helpers] puppeteer_screenshot unavailable: {e}", file=sys.stderr)
        return None


# ============================================================
# FETCH — URL → text/markdown
# ============================================================

def fetch_url(url: str, max_tokens: int = 8000) -> Optional[str]:
    """Fetch URL and return text content."""
    try:
        from mavis.tool import mcp__fetch__fetch_url as ft
        return _safe_call("fetch_url", ft, url=url, max_tokens=max_tokens)
    except Exception as e:
        print(f"[mcp_helpers] fetch_url unavailable: {e}", file=sys.stderr)
        return None


# ============================================================
# MEMORY — persistent knowledge graph
# ============================================================

def memory_create_entities(entities: list) -> bool:
    """Create entities in knowledge graph."""
    try:
        from mavis.tool import mcp__memory__create_entities as ce
        return _safe_call("memory_create_entities", ce, entities=entities) is not None
    except Exception as e:
        print(f"[mcp_helpers] memory_create_entities unavailable: {e}", file=sys.stderr)
        return False


def memory_create_relations(relations: list) -> bool:
    """Create relations between entities."""
    try:
        from mavis.tool import mcp__memory__create_relations as cr
        return _safe_call("memory_create_relations", cr, relations=relations) is not None
    except Exception as e:
        print(f"[mcp_helpers] memory_create_relations unavailable: {e}", file=sys.stderr)
        return False


def memory_search_nodes(query: str) -> list:
    """Search knowledge graph."""
    try:
        from mavis.tool import mcp__memory__search_nodes as sn
        result = _safe_call("memory_search_nodes", sn, query=query)
        if isinstance(result, dict):
            return result.get("nodes", []) or result.get("entities", [])
        return result or []
    except Exception as e:
        print(f"[mcp_helpers] memory_search_nodes unavailable: {e}", file=sys.stderr)
        return []


def memory_open_nodes(names: list) -> list:
    """Open specific entities by name."""
    try:
        from mavis.tool import mcp__memory__open_nodes as on
        return _safe_call("memory_open_nodes", on, names=names) or []
    except Exception as e:
        print(f"[mcp_helpers] memory_open_nodes unavailable: {e}", file=sys.stderr)
        return []


# ============================================================
# SEQUENTIAL-THINKING — step-by-step reasoning
# ============================================================

def sequential_thinking(thought: str, next_thought_needed: bool = True,
                        thought_number: int = 1, total_thoughts: int = 5) -> Optional[str]:
    """Run a step in sequential thinking. Returns the thought response."""
    try:
        from mavis.tool import mcp__sequential_thinking_h71fbe127486bc9eefa63__sequentialthinking as st
        result = _safe_call("sequential_thinking", st,
                            thought=thought,
                            nextThoughtNeeded=next_thought_needed,
                            thoughtNumber=thought_number,
                            totalThoughts=total_thoughts)
        if isinstance(result, dict):
            return result.get("thought", str(result))
        return str(result) if result else None
    except Exception as e:
        print(f"[mcp_helpers] sequential_thinking unavailable: {e}", file=sys.stderr)
        return None


# ============================================================
# KITE-MCP — Zerodha Kite (cross-broker validation)
# ============================================================

def kite_get_quote(instruments: list) -> Optional[dict]:
    """Get live quotes from Kite for cross-broker validation."""
    try:
        from mavis.tool import mcp__kite_mcp_h05bb58bc627287971bc5__get_quote as kq
        result = _safe_call("kite_get_quote", kq, instruments=instruments)
        return result
    except Exception as e:
        print(f"[mcp_helpers] kite_get_quote unavailable: {e}", file=sys.stderr)
        return None


def kite_get_positions() -> Optional[dict]:
    """Get positions from Kite."""
    try:
        from mavis.tool import mcp__kite_mcp_h05bb58bc627287971bc5__get_positions as kp
        return _safe_call("kite_get_positions", kp)
    except Exception as e:
        print(f"[mcp_helpers] kite_get_positions unavailable: {e}", file=sys.stderr)
        return None


# ============================================================
# COMPOSIO — 1000+ apps (Twitter/X OAuth etc.)
# ============================================================

def composio_search_twitter(query: str, max_results: int = 10) -> list:
    """Search Twitter/X via composio. Returns list of tweets."""
    try:
        # composio tool names depend on what's enabled
        from mavis.tool import mcp__composio__twitter_search_tweets as ts
        result = _safe_call("composio_twitter_search", ts,
                            query=query, max_results=max_results)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("tweets", result.get("data", []))
        return []
    except Exception as e:
        print(f"[mcp_helpers] composio_twitter unavailable: {e}", file=sys.stderr)
        return []


# ============================================================
# KOTAK-NEO — official broker
# ============================================================

def kotak_get_quote(exchange_segment: str, exchange_id: str) -> Optional[dict]:
    """Get quote from Kotak Neo broker."""
    try:
        from mavis.tool import mcp__kotak_neo_h4fe61e28f02d29ef23e8__get_quote as kq
        return _safe_call("kotak_get_quote", kq,
                          exchange_segment=exchange_segment, exchange_id=exchange_id)
    except Exception as e:
        print(f"[mcp_helpers] kotak_get_quote unavailable: {e}", file=sys.stderr)
        return None


def kotak_get_positions() -> Optional[dict]:
    """Get positions from Kotak Neo."""
    try:
        from mavis.tool import mcp__kotak_neo_h4fe61e28f02d29ef23e8__get_positions as kp
        return _safe_call("kotak_get_positions", kp)
    except Exception as e:
        print(f"[mcp_helpers] kotak_get_positions unavailable: {e}", file=sys.stderr)
        return None


# ============================================================
# PLUGIN AVAILABILITY CHECK
# ============================================================

def plugin_status() -> dict:
    """Check which MCP plugins are available in this runtime."""
    plugins = {
        "puppeteer": False,
        "fetch": False,
        "memory": False,
        "sequential_thinking": False,
        "kite_mcp": False,
        "composio": False,
        "kotak_neo": False,
    }
    for plugin in list(plugins.keys()):
        try:
            if plugin == "puppeteer":
                from mavis.tool import mcp__puppeteer__puppeteer_navigate  # noqa
            elif plugin == "fetch":
                from mavis.tool import mcp__fetch__fetch_url  # noqa
            elif plugin == "memory":
                from mavis.tool import mcp__memory__search_nodes  # noqa
            elif plugin == "sequential_thinking":
                from mavis.tool import mcp__sequential_thinking_h71fbe127486bc9eefa63__sequentialthinking  # noqa
            elif plugin == "kite_mcp":
                from mavis.tool import mcp__kite_mcp_h05bb58bc627287971bc5__get_quote  # noqa
            elif plugin == "composio":
                from mavis.tool import mcp__composio__twitter_search_tweets  # noqa
            elif plugin == "kotak_neo":
                from mavis.tool import mcp__kotak_neo_h4fe61e28f02d29ef23e8__get_quote  # noqa
            plugins[plugin] = True
        except Exception:
            pass
    return plugins


if __name__ == "__main__":
    import json
    print("Plugin availability:")
    print(json.dumps(plugin_status(), indent=2))