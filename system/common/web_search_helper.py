"""Web search helper — wraps the mavis web_search tool for use by brain modules.

This module exists so the brain can call web_search without depending
on the full mavis runtime. If mavis is not available, returns empty
results so callers can fall back to seed data.
"""
from __future__ import annotations

import json
import sys
from typing import Optional


def web_search(query: str, count: int = 5, freshness: str = "day") -> dict:
    """Call web_search and return results dict.

    Returns: {"results": [{"title": str, "link": str, "content": str}, ...]}
    """
    try:
        # Try to import the mavis tool
        from mavis.tool import web_search as mavis_web_search
        result = mavis_web_search(query=query, count=count, freshness=freshness)
        if isinstance(result, dict):
            return result
        # Some implementations return JSON string
        if isinstance(result, str):
            return json.loads(result)
        return {"results": []}
    except ImportError:
        return {"results": []}
    except Exception as e:
        print(f"[web_search_helper] error: {e}", file=sys.stderr)
        return {"results": []}