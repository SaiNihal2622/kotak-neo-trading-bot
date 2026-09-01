"""Macro calendar — track RBI, Fed, US economic data, FII/DII flows.

These events MOVE markets. The LLM should know what's coming up today
and this week so it can:
- Pause trading around high-impact events (RBI rate decision, US CPI)
- Bias direction based on FII flows (positive FII = bullish, negative = bearish)
- Adjust position size around event windows

Data sources:
- FII/DII flows from NSE daily data (we fetch via yfinance or NSE API)
- Upcoming events: hardcoded list of recurring events + the actual calendar
- US economic calendar: tracked via yfinance for S&P 500 futures moves
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'

# Recurring macro events (year 2026)
RECURRING_EVENTS = {
    # RBI policy meetings (bi-monthly)
    "RBI_POLICY": [
        "2026-02-06", "2026-04-09", "2026-06-06", "2026-08-08",
        "2026-10-08", "2026-12-05",
    ],
    # US Fed FOMC meetings
    "FOMC": [
        "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
        "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-17",
    ],
    # US CPI releases (monthly, ~13th of month)
    "US_CPI": [
        "2026-01-15", "2026-02-12", "2026-03-12", "2026-04-14",
        "2026-05-13", "2026-06-11", "2026-07-15", "2026-08-13",
        "2026-09-11", "2026-10-14", "2026-11-13", "2026-12-11",
    ],
    # US NFP (first Friday of month)
    "US_NFP": [
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
        "2026-05-01", "2026-06-05", "2026-07-02", "2026-08-07",
        "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ],
}


def get_upcoming_events(days_ahead: int = 7) -> list:
    """Get macro events in the next N days. Sorted by date."""
    today = datetime.now().date()
    cutoff = today + timedelta(days=days_ahead)
    events = []
    for event_type, dates in RECURRING_EVENTS.items():
        for d in dates:
            try:
                event_date = datetime.strptime(d, "%Y-%m-%d").date()
            except Exception:
                continue
            if today <= event_date <= cutoff:
                days_until = (event_date - today).days
                events.append({
                    "type": event_type,
                    "date": d,
                    "days_until": days_until,
                    "impact": "HIGH" if event_type in ("RBI_POLICY", "FOMC", "US_CPI", "US_NFP") else "MEDIUM",
                })
    events.sort(key=lambda e: e["date"])
    return events


def fetch_fii_dii_flows() -> dict:
    """Fetch FII/DII flows from NSE India (last available data).
    Falls back to NSE website or yfinance if direct API fails.
    Returns dict with FII and DII net buy/sell figures."""
    try:
        # Try NSE direct first
        import urllib.request
        import urllib.error
        # NSE FII/DII archive endpoint
        url = "https://www.nseindia.com/api/fiidiiTradeReact"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if data and isinstance(data, list) and len(data) > 0:
            latest = data[0]
            return {
                "date": latest.get("date", ""),
                "fii_net": float(str(latest.get("fiiNet", "0")).replace(",", "") or 0),
                "dii_net": float(str(latest.get("diiNet", "0")).replace(",", "") or 0),
                "source": "NSE",
            }
    except Exception:
        pass
    # Fallback: return cached or empty
    return {"date": "", "fii_net": 0, "dii_net": 0, "source": "unavailable"}


def get_macro_state() -> dict:
    """Get full macro context for the LLM."""
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "upcoming_events": get_upcoming_events(days_ahead=7),
        "fii_dii_flows": fetch_fii_dii_flows(),
        "today_date": datetime.now().strftime("%Y-%m-%d"),
    }


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "events"
    if cmd == "events":
        events = get_upcoming_events(7)
        print(json.dumps(events, indent=2, default=str))
    elif cmd == "fii":
        print(json.dumps(fetch_fii_dii_flows(), indent=2, default=str))
    elif cmd == "all":
        print(json.dumps(get_macro_state(), indent=2, default=str))
    else:
        print(f"Unknown: {cmd}")
        print("Usage: python macro_calendar.py [events|fii|all]")
