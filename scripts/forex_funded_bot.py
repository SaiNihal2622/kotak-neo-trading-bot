#!/usr/bin/env python3
"""
Forex Funded Bot - Forex Funded Account Trading
Runs as a standalone microservice on the VPS.
Supports XAUUSD, EURUSD, GBPUSD, USDJPY
"""
import sys
import os
import time
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from flask import Flask, jsonify, request

app = Flask(__name__)

forex_funded_state = {
    "running": False,
    "positions": {},
    "realized_pnl": 0.0,
    "daily_pnl": 0.0,
    "max_daily_loss": 0.05,
    "profit_target": 0.10,
    "symbols": ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"],
    "last_signal": None,
    "last_update": None
}

def initialize_bot():
    """Initialize forex funded bot"""
    try:
        secrets_dir = Path(__file__).resolve().parent.parent / "secrets" / "forex"
        creds_file = secrets_dir / "forex_credentials.json"
        
        if creds_file.exists():
            with open(creds_file) as f:
                creds = json.load(f)
            print(f"Forex credentials loaded")
        else:
            print("No forex credentials found - running in dry-run mode")
        
        forex_funded_state["running"] = True
        forex_funded_state["last_update"] = __import__("datetime").datetime.now().isoformat()
        print("Forex funded bot initialized")
        return True
    except Exception as e:
        print(f"Forex funded bot init failed: {e}")
        return False

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "forex-funded-bot",
        "running": forex_funded_state["running"],
        "positions": len(forex_funded_bot.get("positions", {})),
        "realized_pnl": forex_funded_bot.get("realized_pnl", 0.0),
        "daily_pnl": forex_funded_bot.get("daily_pnl", 0.0),
        "symbols": forex_funded_bot.get("symbols", [])
    })

@app.route("/positions", methods=["GET"])
def positions():
    return jsonify({
        "positions": forex_funded_bot.get("positions", {}),
        "count": len(forex_funded_bot.get("positions", {}))
    })

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json()
    symbol = data.get("symbol", "EURUSD")
    action = data.get("action", "hold")
    size = data.get("size", 0.1)
    
    forex_funded_bot["last_signal"] = {
        "symbol": symbol,
        "action": action,
        "size": size,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }
    
    return jsonify({"status": "signal_received", "signal": forex_funded_bot["last_signal"]})

if __name__ == "__main__":
    initialize_bot()
    app.run(host="0.0.0.0", port=8513, debug=False)