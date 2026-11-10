#!/usr/bin/env python3
"""
Kronos Forecast Service - Financial Foundation Model Price Prediction
Runs as a standalone microservice on the VPS.
Provides price forecasts for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX.
"""
import sys
import os
import time
import json
import signal
import logging
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from flask import Flask, jsonify, request

app = Flask(__name__)

# Global predictor instance
predictor = None
last_forecasts = {}
forecast_cache = {}

def initialize_kronos():
    """Initialize Kronos model"""
    global predictor
    try:
        sys.path.insert(0, str(ROOT / "kronos"))
        from model import Kronos, KronosTokenizer, KronosPredictor
        
        predictor = KronosPredictor(
            model=Kronos.from_pretrained("NeoQuasar/Kronos-mini"),
            tokenizer=KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k"),
            max_context=512
        )
        print("Kronos model loaded successfully")
        return True
    except Exception as e:
        print(f"Kronos load failed: {e}")
        predictor = None
        return False

def get_forecast(symbol, candles_data):
    """Get Kronos forecast for a symbol"""
    global predictor
    
    if predictor is None:
        return None
    
    import pandas as pd
    import datetime
    
    cache_key = f"{symbol}_{len(candles_data)}"
    now = time.time()
    
    # Cache for 60 seconds
    if cache_key in forecast_cache:
        cached_time, cached_result = forecast_cache[cache_key]
        if now - cached_time < 60:
            return cached_result
    
    try:
        df = pd.DataFrame(candles_data[-20:])
        ts = pd.Series([datetime.datetime.now() - datetime.timedelta(minutes=len(df)-i) for i in range(len(df))])
        y_ts = pd.Series([datetime.datetime.now() + datetime.timedelta(minutes=i+1) for i in range(5)])
        
        pred = predictor.predict(
            df=df,
            x_timestamp=ts,
            y_timestamp=y_ts,
            pred_len=5,
            T=1.0,
            top_p=0.9,
            sample_count=1
        )
        
        last_close = float(df["close"].iloc[-1])
        next_close = float(pred["close"].iloc[-1])
        
        result = {
            "symbol": symbol,
            "direction": "UP" if next_close > last_close else "DOWN",
            "next_close": round(next_close, 2),
            "last_close": round(last_close, 2),
            "pct": round((next_close - last_close) / last_close * 100, 4),
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        forecast_cache[cache_key] = (now, result)
        return result
        
    except Exception as e:
        print(f"Kronos forecast error for {symbol}: {e}")
        return None

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy", "service": "kronos-forecast", "model_loaded": predictor is not None})

@app.route("/forecast", methods=["POST"])
def forecast():
    data = request.get_json()
    symbol = data.get("symbol", "NIFTY")
    candles = data.get("candles", [])
    
    if not candles:
        return jsonify({"error": "No candle data provided"}), 400
    
    result = get_forecast(symbol, candles)
    
    if result is None:
        return jsonify({"error": "Forecast failed"}), 500
    
    return jsonify(result)

@app.route("/forecast/batch", methods=["POST"])
def forecast_batch():
    data = request.get_json()
    symbols = data.get("symbols", [])
    candles_map = data.get("candles", {})
    
    results = {}
    for symbol in symbols:
        result = get_forecast(symbol, candles_map.get(symbol, []))
        if result:
            results[symbol] = result
    
    return jsonify(results)

if __name__ == "__main__":
    initialize_kronos()
    app.run(host="0.0.0.0", port=8506, debug=False)