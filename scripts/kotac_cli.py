"""Direct Kotak Neo CLI — uses the bot's already-authenticated NeoClient.

This gives you the same data the MCP tools would, but runs as a Python script
the LLM can call via the `bash` tool. Works in the current Mavis session
without needing the MCP tool to be exposed.

Usage:
    python scripts/kotac_cli.py positions       # open positions
    python scripts/kotac_cli.py orderbook      # today's order book
    python scripts/kotac_cli.py holdings       # long-term holdings
    python scripts/kotac_cli.py limits         # available margin / cash
    python scripts/kotac_cli.py quote NIFTY    # live LTP for a symbol
    python scripts/kotac_cli.py trades        # today's trades
    python scripts/kotac_cli.py research RELIANCE   # Kotak research view
    python scripts/kotac_cli.py status         # all of the above at once
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / "credentials.env")


def _serialize(obj):
    """Best-effort JSON-safe serializer."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if hasattr(obj, "__dict__"):
        return {k: _serialize(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
    return str(obj)


def _client():
    from kotak_bot.broker.neo_client import NeoClient
    nc = NeoClient()
    if not nc._connected:
        nc.connect()
    return nc


def cmd_positions(_args):
    nc = _client()
    res = nc.get_positions()
    return _serialize(res)


def cmd_orderbook(_args):
    nc = _client()
    res = nc.get_order_report()
    return _serialize(res)


def cmd_holdings(_args):
    nc = _client()
    res = nc.get_holdings()
    return _serialize(res)


def cmd_limits(_args):
    nc = _client()
    res = nc.get_margins()
    return _serialize(res)


def cmd_trades(_args):
    nc = _client()
    res = nc.get_trade_report()
    return _serialize(res)


def cmd_quote(args):
    if not args:
        return {"error": "usage: quote <SYMBOL>"}
    nc = _client()
    try:
        # get_ltp works for known exchange symbols
        res = nc.get_ltp(args[0])
        return {"symbol": args[0], "ltp": _serialize(res)}
    except Exception as e:
        return {"error": str(e), "tried": args[0]}


def cmd_research(_args):
    return {"error": "research not yet wired into NeoClient; use live_nse_puppeteer.py"}


def cmd_status(_args):
    """Aggregate snapshot of everything."""
    out = {}
    for name, fn in [("positions", cmd_positions), ("orderbook", cmd_orderbook),
                     ("holdings", cmd_holdings), ("limits", cmd_limits),
                     ("trades", cmd_trades)]:
        try:
            out[name] = fn([])
        except Exception as e:
            out[name] = {"error": str(e)[:200]}
    return out


COMMANDS = {
    "positions": cmd_positions,
    "orderbook": cmd_orderbook,
    "holdings": cmd_holdings,
    "limits": cmd_limits,
    "trades": cmd_trades,
    "quote": cmd_quote,
    "research": cmd_research,
    "status": cmd_status,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 0
    cmd, args = sys.argv[1], sys.argv[2:]
    try:
        result = COMMANDS[cmd](args)
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e), "command": cmd, "args": args}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
