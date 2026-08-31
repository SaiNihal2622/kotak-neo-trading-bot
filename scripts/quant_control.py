"""Quant control - the chat-side interface to the quant_service.

The primary chat (this one) uses this script to monitor and control the
quant_service that runs 24/7 as an NSSM service. No Mavis session needed.

Usage:
    python scripts/quant_control.py status       # service state
    python scripts/quant_control.py health       # liveness ping
    python scripts/quant_control.py positions    # current positions + P&L
    python scripts/quant_control.py decisions    # last 20 LLM decisions
    python scripts/quant_control.py pause        # pause the service
    python scripts/quant_control.py resume       # resume
    python scripts/quant_control.py close        # close all positions
    python scripts/quant_control.py ask "should we trade NIFTY 24300 CE?"  # ad-hoc LLM query
"""
import json
import sys
import httpx
from pathlib import Path

BASE = "http://127.0.0.1:8503"
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


def call_get(path: str) -> dict:
    r = httpx.get(f"{BASE}{path}", timeout=10)
    return r.json()


def call_post(path: str, body: dict) -> dict:
    r = httpx.post(f"{BASE}{path}", json=body, timeout=30)
    return r.json()


def cmd_status():
    print(json.dumps(call_get("/status"), indent=2))


def cmd_health():
    print(json.dumps(call_get("/health"), indent=2))


def cmd_positions():
    positions = call_get("/positions")
    if not positions:
        print("No open positions.")
        return
    for sym, p in positions.items():
        if isinstance(p, dict):
            print(f"  {sym}: qty={p.get('qty', 0)} avg={p.get('avg_price', 0)} pnl={p.get('pnl', 0)}")


def cmd_decisions():
    decisions = call_get("/decisions")
    if not decisions:
        print("No decisions yet.")
        return
    if not isinstance(decisions, list):
        print(f"Unexpected response: {decisions}")
        return
    for d in decisions[-10:]:
        if not isinstance(d, dict):
            continue
        ts = d.get('ts', '?')[:19]
        action = d.get('decision', {})
        if not isinstance(action, dict):
            action = {}
        a = action.get('action', '?')
        i = action.get('instrument', '?')
        s = action.get('strategy', '?')
        n = action.get('note', '')[:60]
        print(f"  {ts}  {a:5s} {i:10s} {s:25s}  {n}")


def cmd_pause():
    print(json.dumps(call_post("/command", {"cmd": "pause"}), indent=2))


def cmd_resume():
    print(json.dumps(call_post("/command", {"cmd": "resume"}), indent=2))


def cmd_close():
    print(json.dumps(call_post("/command", {"cmd": "close", "instrument": "ALL", "reason": "user manual"}), indent=2))


def cmd_ask(question: str):
    """Ad-hoc LLM query via direct API call (no Mavis)."""
    env = {}
    env_path = ROOT / 'config' / 'credentials.env'
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    base = env.get('MINIMAX_LLM_BASE_URL', '').rstrip('/')
    key = env.get('MINIMAX_LLM_API_KEY', '')
    r = httpx.post(
        f"{base}/messages",
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={
            'model': 'MiniMax-M3',
            'max_tokens': 1500,
            'system': 'You are a professional quant assistant. Answer the question concisely with data-driven reasoning.',
            'messages': [{'role': 'user', 'content': question}],
        },
        timeout=60,
    )
    if r.status_code != 200:
        print(f"LLM-ERR {r.status_code}: {r.text[:300]}")
        return
    body = r.json()
    for c in body.get('content', []):
        if c.get('type') == 'text':
            print(c.get('text', ''))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == 'status': cmd_status()
    elif cmd == 'health': cmd_health()
    elif cmd == 'positions': cmd_positions()
    elif cmd == 'decisions': cmd_decisions()
    elif cmd == 'pause': cmd_pause()
    elif cmd == 'resume': cmd_resume()
    elif cmd == 'close': cmd_close()
    elif cmd == 'ask':
        if len(sys.argv) < 3:
            print("usage: quant_control.py ask \"<question>\"")
            return 1
        cmd_ask(' '.join(sys.argv[2:]))
    else:
        print(f"unknown command: {cmd}")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
