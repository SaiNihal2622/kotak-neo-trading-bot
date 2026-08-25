"""Install thesis-engine cron jobs.

Schedules:
  kotak-thesis-premarket    08:25 Mon-Fri  -> thesis premarket brief
  kotak-thesis-intraday     every 30 min 09:00-15:00 Mon-Fri -> refresh
  kotak-news-cache          every 30 min 09:00-15:00 Mon-Fri -> refresh news

The thesis runs BEFORE the existing kotak_brain cron, so the brain's
LLM call has the thesis context.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Use the mavis mcp to create cron jobs
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path.home() / ".minimax" / "agents" / "mavis"))

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"

JOBS = [
    {
        "name": "kotak-thesis-premarket",
        "schedule": "25 8 * * 1-5",
        "prompt": (
            "Run: C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\.venv\\Scripts\\python.exe "
            f"{ROOT}\\scripts\\thesis_engine.py premarket --deliver\n"
            "Then read data_cache/thesis/latest.json and write a 5-line pre-market brief to Telegram.\n"
            "No analysis needed — just run the command and confirm success."
        ),
    },
    {
        "name": "kotak-thesis-intraday",
        "schedule": "*/30 9-15 * * 1-5",
        "prompt": (
            "Run: C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\.venv\\Scripts\\python.exe "
            f"{ROOT}\\scripts\\thesis_engine.py intraday\n"
            "Print the new thesis (regime, bias, confidence, risk_budget, narrative). "
            "If the bias flipped or confidence dropped >0.15 vs data_cache/thesis/latest.json, "
            "write a 'THESIS FLIP' alert to Telegram with the diff."
        ),
    },
    {
        "name": "kotak-news-cache",
        "schedule": "*/30 9-15 * * 1-5",
        "prompt": (
            "Run: C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\.venv\\Scripts\\python.exe "
            f"{ROOT}\\scripts\\news_cache.py\n"
            "Just run the command. It writes data_cache/news_aggregate.json. Confirm exit code 0."
        ),
    },
    {
        "name": "kotak-thesis-eod",
        "schedule": "35 15 * * 1-5",
        "prompt": (
            "Run: C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\.venv\\Scripts\\python.exe "
            f"{ROOT}\\scripts\\thesis_engine.py eod\n"
            "Then summarize: (1) what the morning thesis was, (2) what the EOD thesis is, "
            "(3) which biases proved right/wrong, (4) any OI structure changes since open. "
            "Send to Telegram."
        ),
    },
]


def main() -> int:
    try:
        from mavis import mavis  # type: ignore
    except ImportError as e:
        print(f"ERROR: mavis tool not available: {e}")
        print("Run this script from a Mavis session to create the cron jobs.")
        return 1

    for job in JOBS:
        print(f"\n=== Creating: {job['name']} ({job['schedule']}) ===")
        result = mavis(
            command="cron create",
            args={
                "cron_name": job["name"],
                "schedule": job["schedule"],
                "prompt": job["prompt"],
                "agent_name": "mavis",
                "session": {"mode": "new"},
            },
        )
        print(json.dumps(result if isinstance(result, dict) else str(result), indent=2)[:500])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
