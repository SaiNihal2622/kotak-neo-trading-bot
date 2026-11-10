#!/usr/bin/env python3
"""
Jarvis AI Assistant - Main Interface for Jarvis/OpenClaw System
Provides conversational interface, decision monitoring, and system control.
Accessible from phone, laptop, tablet - anywhere.
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

from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

jarvis_state = {
    "version": "1.0.0",
    "name": "Jarvis/OpenClaw Trading System",
    "status": "initializing",
    "services": {},
    "last_decision": None,
    "last_command": None,
    "uptime_start": __import__("datetime").datetime.now().isoformat()
}

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "jarvis-ai",
        "version": jarvis_state["version"],
        "uptime_start": jarvis_state["uptime_start"]
    })

@app.route("/", methods=["GET"])
def index():
    """Main Jarvis interface - accessible from any device"""
    return jsonify({
        "name": jarvis_state["name"],
        "version": jarvis_state["version"],
        "status": jarvis_state["status"],
        "services": jarvis_state["services"],
        "last_decision": jarvis_state["last_decision"],
        "endpoints": {
            "GET /health": "Health check",
            "GET /status": "Full system status",
            "GET /decisions": "Recent trading decisions",
            "POST /command": "Send command to Jarvis",
            "GET /positions": "Current positions",
            "GET /pnl": "Current P&L",
            "GET /services": "Service status"
        },
        "message": "Jarvis is online. Access from any device - phone, laptop, tablet."
    })

@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "jarvis": jarvis_state,
        "services": jarvis_state["services"],
        "timestamp": __import__("datetime").datetime.now().isoformat()
    })

@app.route("/decisions", methods=["GET"])
def decisions():
    return jsonify({
        "last_decision": jarvis_state["last_decision"],
        "timestamp": __import__("datetime").datetime.now().isoformat()
    })

@app.route("/positions", methods=["GET"])
def positions():
    return jsonify({
        "positions": jarvis_state.get("positions", {}),
        "timestamp": __import__("datetime").datetime.now().isoformat()
    })

@app.route("/pnl", methods=["GET"])
def pnl():
    return jsonify({
        "realized_pnl": jarvis_state.get("realized_pnl", 0.0),
        "cash": jarvis_state.get("cash", 100000.0),
        "timestamp": __import__("datetime").datetime.now().isoformat()
    })

@app.route("/command", methods=["POST"])
def command():
    data = request.get_json()
    command = data.get("command", "")
    params = data.get("params", {})
    
    jarvis_state["last_command"] = {
        "command": command,
        "params": params,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }
    
    # Process command
    response = process_command(command, params)
    
    return jsonify({
        "status": "command_received",
        "command": command,
        "response": response,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    })

def process_command(command, params):
    """Process Jarvis commands"""
    cmd = command.lower().strip()
    
    if "status" in cmd or "state" in cmd:
        return {
            "message": "Jarvis system status",
            "services": jarvis_state.get("services", {}),
            "last_decision": jarvis_state.get("last_decision")
        }
    elif "position" in cmd:
        return {
            "message": "Current positions",
            "positions": jarvis_state.get("positions", {})
        }
    elif "pnl" in cmd or "profit" in cmd:
        return {
            "message": "Current P&L",
            "realized_pnl": jarvis_state.get("realized_pnl", 0.0),
            "cash": jarvis_state.get("cash", 100000.0)
        }
    elif "decision" in cmd or "trade" in cmd:
        return {
            "message": "Last trading decision",
            "decision": jarvis_state.get("last_decision")
        }
    elif "stop" in cmd:
        return {
            "message": "Stop command received - all trading paused",
            "action": "emergency_stop"
        }
    elif "start" in cmd:
        return {
            "message": "Start command received - trading resumed",
            "action": "resume_trading"
        }
    else:
        return {
            "message": f"Jarvis received: {command}",
            "available_commands": [
                "status", "position", "pnl", "decision", "stop", "start",
                "help"
            ]
        }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)