#!/usr/bin/env python3
"""
Adziga Agency - Sweet Desire Ad Agency Server
Handles content creation, Instagram management, and ad campaigns for Diwali sales
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

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__)

adziga_state = {
    "version": "1.0.0",
    "name": "Adziga Agency - Sweet Desire",
    "client": "Sweet Desire (UAE)",
    "status": "initializing",
    "campaigns": [],
    "posts_created": 0,
    "last_post": None
}

def initialize_adziga():
    """Initialize Adziga agency"""
    try:
        content_dir = Path(__file__).resolve().parent.parent / "sweet-desire"
        if content_dir.exists():
            images = list(content_dir.glob("*.jpg")) + list(content_dir.glob("*.png")) + list(content_dir.glob("*.jpeg"))
            print(f"Sweet Desire content: {len(images)} images found")
            adziga_state["content_available"] = len(images)
        else:
            print("Sweet Desire content directory not found")
            adziga_state["content_available"] = 0
        
        adziga_state["status"] = "active"
        print("Adziga agency initialized")
        return True
    except Exception as e:
        print(f"Adziga init failed: {e}")
        return False

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "service": "adziga-agency",
        "client": adziga_state["client"],
        "version": adziga_state["version"]
    })

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "name": adziga_state["name"],
        "client": adziga_state["client"],
        "version": adziga_state["version"],
        "status": adziga_state["status"],
        "campaigns": adziga_state["campaigns"],
        "posts_created": adziga_state["posts_created"],
        "endpoints": {
            "GET /health": "Health check",
            "GET /campaigns": "List campaigns",
            "POST /campaign": "Create campaign",
            "GET /content": "List content assets",
            "POST /post": "Create post",
            "GET /diwali": "Diwali campaign ideas"
        }
    })

@app.route("/campaigns", methods=["GET"])
def campaigns():
    return jsonify({
        "campaigns": adziga_state["campaigns"],
        "count": len(adziga_state["campaigns"])
    })

@app.route("/campaign", methods=["POST"])
def campaign():
    data = request.get_json()
    campaign = {
        "id": len(adziga_state["campaigns"]) + 1,
        "name": data.get("name", "Untitled Campaign"),
        "product": data.get("product", ""),
        "target_audience": data.get("target_audience", ""),
        "budget": data.get("budget", 0),
        "start_date": data.get("start_date", ""),
        "end_date": data.get("end_date", ""),
        "status": "active",
        "created_at": __import__("datetime").datetime.now().isoformat()
    }
    adziga_state["campaigns"].append(campaign)
    return jsonify({"status": "campaign_created", "campaign": campaign})

@app.route("/content", methods=["GET"])
def content():
    content_dir = Path(__file__).resolve().parent.parent / "sweet-desire" / "content"
    if content_dir.exists():
        files = [f.name for f in content_dir.iterdir() if f.is_file()]
        return jsonify({"content": files, "count": len(files)})
    return jsonify({"content": [], "count": 0})

@app.route("/diwali", methods=["GET"])
def diwali():
    return jsonify({
        "campaign": "Diwali 2026 - Sweet Desire",
        "themes": [
            "Diwali Lights & Sparkle",
            "Festival Sweets & Treats",
            "Gift Hampers & Bundles",
            "Festive Wear & Fashion",
            "Home Decor & Rangoli"
        ],
        "post_ideas": [
            "Diwali special offer - 20% off all items",
            "Festive gift hampers for corporate gifting",
            "Diwali night wear collection launch",
            "Sweets & snacks festive platter",
            "Home decor - diyas, candles, rangoli"
        ],
        "hashtags": ["#Diwali2026", "#SweetDesire", "#FestiveOffers", "#DiwaliGifts", "#UAEShopping"]
    })

if __name__ == "__main__":
    initialize_adziga()
    app.run(host="0.0.0.0", port=8090, debug=False)