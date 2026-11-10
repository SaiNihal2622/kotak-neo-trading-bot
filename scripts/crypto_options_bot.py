#!/usr/bin/env python3
"""
Crypto Options Bot - Deribit BTC/ETH Options Trading
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

# Crypto options bot state
crypto_state = {
    "running": False,
    "positions": {},
    "realized_pnl": 0.0,
    "last_signal": None,
    "last_update": None
}

def initialize_bot():
    """Initialize crypto options bot"""
    try:
        # Load Deribit credentials
        secrets_dir = Path(__file__).resolve().parent.parent / "secrets" / "crypto"
        creds_file = secrets_dir / "deribit.json"
        
        if creds_file.exists():
            with open(creds_file) as f:
                creds = json.load(f)
            print(f"Deribit credentials loaded for {creds.get('client_id', 'unknown')}")
        else:
            print("No Deribit credentials found - running in dry-run mode")
        
        crypto_state["running"] = True
        crypto_state["last_update"] = __import__("datetime").datetime.now().isoformat()
        print("Crypto options bot initialized")
        return True
    except Exception as e:
        print(f"Crypto bot init failed: {e}")
        return False

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "crypto-options-bot",
        "running": crypto_state["running"],
        "positions": len(crypto_state.get("positions", {})),
        "realized_pnl": crypto_state.get("realized_pnl", 0.0)
    })

@app.route("/positions", methods=["GET"])
def positions():
    return jsonify({
        "positions": crypto_state.get("positions", {}),
        "count": len(crypto_state.get("positions", {}))
    })

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json()
    symbol = data.get("symbol", "BTC")
    action = data.get("action", "hold")
    size = data.get("size", 0.1)
    
    crypto_state["last_signal"] = {
        "symbol": symbol,
        "action": action,
        "size": size,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }
    
    return jsonify({"status": "signal_received", "signal": crypto_state["last_signal"]})

if __name__ == "__main__":
    initialize_bot()
    app.run(host="0.0.0.0", port=8511, debug=False)