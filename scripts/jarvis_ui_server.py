#!/usr/bin/env python3
"""
Jarvis AI Assistant Server - Frontend HTML for phone/laptop access
Provides a beautiful web interface for controlling the trading system
"""
from flask import Flask, render_template_string

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jarvis - Trading Command Center</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            color: #fff;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        header {
            text-align: center;
            padding: 40px 0;
            border-bottom: 2px solid #4a90e2;
            margin-bottom: 30px;
        }
        h1 { font-size: 2.5rem; margin-bottom: 10px; }
        .status-badge {
            display: inline-block;
            padding: 6px 16px;
            border-radius: 20px;
            background: #2ecc71;
            color: #fff;
            font-size: 0.9rem;
            margin-top: 10px;
        }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card {
            background: rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 24px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
        }
        .card h3 { margin-bottom: 15px; color: #4a90e2; }
        .stat { font-size: 2rem; font-weight: bold; margin: 10px 0; }
        .label { color: #aaa; font-size: 0.9rem; }
        .command-section {
            background: rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 30px;
        }
        .command-section h3 { margin-bottom: 20px; color: #4a90e2; }
        .command-input {
            width: 100%;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.2);
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 1rem;
            margin-bottom: 15px;
        }
        button {
            background: #4a90e2;
            color: #fff;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 1rem;
            cursor: pointer;
            transition: background 0.3s;
        }
        button:hover { background: #357abd; }
        .response {
            margin-top: 15px;
            padding: 15px;
            background: rgba(255,255,255,0.1);
            border-radius: 8px;
            color: #d4d4d4;
            font-family: monospace;
            white-space: pre-wrap;
        }
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #2ecc71;
            margin-right: 8px;
        }
        .services-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .service-card {
            background: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .service-name { font-weight: bold; color: #4a90e2; }
        .service-status { font-size: 0.8rem; color: #2ecc71; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>⚡ Jarvis</h1>
            <p>Trading Command Center</p>
            <div class="status-badge">● System Online</div>
        </header>

        <div class="grid">
            <div class="card">
                <h3>Account</h3>
                <div class="stat" id="cash">₹1,00,000</div>
                <div class="label">Available Cash</div>
            </div>
            <div class="card">
                <div class="stat" id="pnl">₹0.00</div>
                <div class="label">Realized P&L</div>
            </div>
            <div class="card">
                <div class="stat" id="positions">0</div>
                <div class="label">Open Positions</div>
            </div>
            <div class="card">
                <div class="stat" id="last-trade">--</div>
                <div class="label">Last Trade</div>
            </div>
        </div>

        <div class="command-section">
            <h3>🎯 Command Jarvis</h3>
            <p>Ask Jarvis anything about your trading system</p>
            <input type="text" id="command-input" class="command-input" placeholder="Type a command (e.g., 'status', 'positions', 'pnl', 'stop', 'start')">
            <button onclick="sendCommand()">Send Command</button>
            <div class="response" id="command-response"></div>
        </div>

        <div class="command-section">
            <h3>📊 Services</h3>
            <div class="services-grid" id="services-list">
                <div class="service-card">
                    <div class="service-name">Kotak Operator</div>
                    <div class="service-status" id="svc-kotak-operator">● Online</div>
                </div>
                <div class="service-card">
                    <div class="service-name">Kronos Forecast</div>
                    <div class="service-status" id="svc-kronos">● Online</div>
                </div>
                <div class="service-card">
                    <div class="service-name">Crypto Options</div>
                    <div class="service-status" id="svc-crypto-options">● Online</div>
                </div>
                <div class="service-card">
                    <div class="service-name">Crypto Funded</div>
                    <div class="service-status" id="svc-crypto-funded">● Online</div>
                </div>
                <div class="service-card">
                    <div class="service-name">Forex Funded</div>
                    <div class="service-status" id="svc-forex-funded">● Online</div>
                </div>
                <div class="service-card">
                    <div class="service-name">Adziga Agency</div>
                    <div class="service-status" id="svc-adziga">● Online</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        async function sendCommand() {
            const input = document.getElementById('command-input');
            const response = document.getElementById('command-response');
            
            if (!input.value.trim()) return;
            
            response.textContent = 'Processing...';
            
            try {
                const res = await fetch('/command', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({command: input.value})
                });
                const data = await res.json();
                response.textContent = data.response.message || JSON.stringify(data.response, null, 2);
                input.value = '';
            } catch (e) {
                response.textContent = 'Error: ' + e.message;
            }
        }

        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendCommand();
        });

        async function loadStatus() {
            try {
                const res = await fetch('/status');
                const data = await res.json();
                
                document.getElementById('cash').textContent = '₹' + (data.jarvis.cash || 100000).toLocaleString();
                document.getElementById('pnl').textContent = '₹' + (data.jarvis.realized_pnl || 0).toLocaleString();
                
                document.getElementById('services-list').innerHTML = '';
                const services = data.services || {};
                for (const [name, info] of Object.entries(services)) {
                    const card = document.createElement('div');
                    card.className = 'service-card';
                    card.innerHTML = '<div class="service-name">' + name + '</div><div class="service-status">● ' + (info.status || 'online') + '</div>';
                    document.getElementById('services-list').appendChild(card);
                }
            } catch(e) {
                console.error('Status load failed', e);
            }
        }

        setInterval(loadStatus, 10000);
        loadStatus();
    </script>
</body>
</html>
"""

@app.route("/jarvis", methods=["GET"])
def jarvis_ui():
    return render_template_string(HTML_TEMPLATE)

@app.route("/", methods=["GET"])
def jarvis_root():
    return jarvis_ui()