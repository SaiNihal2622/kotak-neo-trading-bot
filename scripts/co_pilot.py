"""Live Mavis co-pilot.

A standalone script that:
1. Reads the running bot's state (paper_state.json, log, performance)
2. uses MiniMax LLM to analyze the state and give advice
3. sends the advice to Telegram

Run on a schedule (cron every 5-15 min) — gives a human-style review of
what the bot is doing, flags risks, suggests tweaks.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

os.chdir(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
sys.path.insert(0, r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")

from kotak_bot.alerts.telegram import TelegramAlerter
from kotak_bot.intel.performance import PerformanceTracker


def read_state() -> dict:
    """Read current bot state. Robust against WinError 5 (file in use by bot)."""
    state = {
        "ts": datetime.utcnow().isoformat(),
        "paper_state": {},
        "log_tail": "",
        "performance": [],
    }
    ps = Path("data_cache/paper_state.json")
    if ps.exists():
        for attempt in range(3):
            try:
                # share mode: read-only, allow others to write
                import os
                fh = os.open(str(ps), os.O_RDONLY)
                try:
                    state["paper_state"] = json.loads(os.read(fh, 1 << 20).decode("utf-8"))
                finally:
                    os.close(fh)
                break
            except (PermissionError, OSError) as e:
                if attempt < 2:
                    import time as _t
                    _t.sleep(0.1 * (attempt + 1))
                else:
                    pass
    log = Path("logs/bot.log")
    if log.exists():
        try:
            state["log_tail"] = "\n".join(log.read_text().splitlines()[-20:])
        except Exception:
            pass
    # performance
    try:
        pt = PerformanceTracker()
        state["performance"] = pt.all_strategies_metrics()
    except Exception:
        pass
    return state


def build_prompt(state: dict) -> str:
    s = state.get("paper_state", {})
    positions = s.get("positions", {})
    pos_count = len(positions) if isinstance(positions, dict) else 0
    cash = s.get("cash", 0)
    realized = s.get("realized_pnl", 0)
    perf = state.get("performance", [])
    perf_text = "\n".join([
        f"  {m['strategy']}: cnt={m['count']} win={m['win_rate']:.0%} avg=Rs.{m['avg_pnl']:.0f} Sharpe={m['sharpe']:+.2f}"
        for m in perf
    ]) if perf else "  (no trades yet)"
    unreal = sum(p.get("pnl", 0) for p in positions.values()) if isinstance(positions, dict) else 0
    return f"""You are a co-pilot advisor for an Indian options trading bot. Analyze the current state and give 2-3 actionable insights.

STATE @ {state['ts']}:
- Capital: Rs.{cash:,.0f}
- Realized P&L: Rs.{realized:,.0f}
- Unrealized P&L: Rs.{unreal:,.0f}
- Open positions: {pos_count}
- Per-strategy performance (rolling 20 trades):
{perf_text}

Recent log tail (last 20 lines):
{state.get('log_tail', '')[:2000]}

Respond in plain English, 2-3 short insights (one line each). Focus on:
- Risk: any concerning drawdown, position concentration, regime mismatch
- Strategy: which strategy is performing best/worst, what to tune
- Opportunities: is the bot missing trades, or taking too many

Use this format:
1. [CATEGORY] insight text
2. [CATEGORY] insight text
3. [CATEGORY] insight text

Keep total response under 400 words. No markdown, no preamble. Just the insights."""


def main():
    state = read_state()
    prompt = build_prompt(state)
    # call LLM directly via httpx
    import httpx
    from dotenv import load_dotenv
    env_path = Path("config/credentials.env")
    if env_path.exists():
        load_dotenv(str(env_path))
    token = os.environ.get("MINIMAX_LLM_API_KEY", "")
    base_url = os.environ.get("MINIMAX_LLM_BASE_URL", "https://agent.minimax.io/mavis/api/v1/llm/v1")
    if not token:
        print("no MINIMAX_LLM_API_KEY — skip co-pilot")
        return
    headers = {
        "Content-Type": "application/json",
        "x-api-key": token,
        "Authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": "MiniMax-M2.7-highspeed",
        "max_tokens": 600,
        "temperature": 0.3,
        "system": "You are a concise trading co-pilot. Output ONLY the insights, no preamble.",
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        with httpx.Client(timeout=30) as c:
            r = c.post(f"{base_url.rstrip('/')}/messages", headers=headers, json=body)
        if r.status_code != 200:
            print(f"LLM error: {r.status_code} {r.text[:200]}")
            return
        data = r.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "thinking" and not text:
                text += block.get("thinking", "")
        if not text:
            print("no text in response")
            return
        # send to Telegram
        a = TelegramAlerter()
        msg = f"🧠 CO-PILOT @ {datetime.now().strftime('%H:%M')} IST\n{text}"
        a.send(msg)
        print(f"co-pilot sent: {len(text)} chars")
    except Exception as e:
        print(f"co-pilot error: {e}")


if __name__ == "__main__":
    main()
