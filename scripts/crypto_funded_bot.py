#!/usr/bin/env python3
"""
Crypto Funded Bot - Deribit Funded Account Trading
Runs as a standalone microservice on the VPS.
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

crypto_funded_state = {
    "running": False,
    "positions": {},
    "realized_pnl": 0.0,
    "daily_pnl": 0.0,
    "max_daily_loss": 0.05,
    "profit_target": 0.10,
    "last_signal": None,
    "last_update": None
}

def initialize_bot():
    """Initialize crypto funded bot"""
    try:
        secrets_dir = Path(__file__).resolve().parent.parent / "secrets" / "crypto"
        creds_file = secrets_dir / "funded_account.json"
        
        if creds_file.exists():
            with open(creds_file) as f:
                creds = json.load(f)
            print(f"Funded account credentials loaded")
        else:
            print("No funded account credentials found - running in dry-run mode")
        
        crypto_funded_state["running"] = True
        crypto_funded_state["last_update"] = __import__("datetime").datetime.now().isoformat()
        print("Crypto funded bot initialized")
        return True
    except Exception as e:
        print(f"Crypto funded bot init failed: {e}")
        return False

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "crypto-funded-bot",
        "running": crypto_funded_state["running"],
        "positions": len(crypto_funded_bot.get("positions", {})),
        "realized_pnl": crypto_funded_bot.get("realized_pnl", 0.0),
        "daily_pnl": crypto_funded_bot.get("daily_pnl", 0.0)
    })

@app.route("/positions", methods=["GET"])
def positions():
    return jsonify({
        "positions": crypto_funded_bot.get("positions", {}),
        "count": len(crypto_funded_bot.get("positions", {}))
    })

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json()
    symbol = data.get("symbol", "BTC")
    action = data.get("action", "hold")
    size = data.get("size", 0.1)
    
    crypto_funded_bot["last_signal"] = {
        "symbol": symbol,
        "action": action,
        "size": size,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }
    
    return jsonify({"status": "signal_received", "signal": crypto_funded_bot["last_signal"]})

if __name__ == "__main__":
    initialize_bot()
    app.run(host="0.0.0.0", port=8512, debug=False)