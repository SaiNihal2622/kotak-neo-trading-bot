"""Macro event calendar + OI heatmap utilities.

Macro calendar: detects upcoming RBI/Fed/Budget/expiry events from a hardcoded list
and exposes `minutes_to_event`, `upcoming_event` for the SignalContext.

OI heatmap: aggregates call/put OI per strike to show resistance (call OI) and
support (put OI). Helps strike selection.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import json
from loguru import logger

from kotak_bot.utils.clock import now_ist


# Known Indian + global macro events (2026)
# Add/remove as calendar evolves
MACRO_EVENTS_2026 = [
    # (name, scheduled_date_ist, time_ist, importance 1-3, direction hint)
    ("rbi_policy",         "2026-08-08", "10:00", 3, "neutral"),  # done
    ("rbi_policy",         "2026-10-08", "10:00", 3, "neutral"),
    ("rbi_policy",         "2026-12-05", "10:00", 3, "neutral"),
    ("rbi_policy",         "2027-02-06", "10:00", 3, "neutral"),
    ("us_fed",             "2026-07-30", "23:30", 3, "neutral"),  # done
    ("us_fed",             "2026-09-17", "23:30", 3, "neutral"),
    ("us_fed",             "2026-11-05", "23:30", 3, "neutral"),
    ("us_fed",             "2026-12-17", "23:30", 3, "neutral"),
    ("us_cpi",             "2026-08-12", "18:30", 2, "neutral"),
    ("us_cpi",             "2026-09-11", "18:30", 2, "neutral"),
    ("us_cpi",             "2026-10-15", "18:30", 2, "neutral"),
    ("union_budget",       "2026-07-23", "11:00", 3, "neutral"),  # done
    ("union_budget",       "2027-02-01", "11:00", 3, "neutral"),
    ("india_gdp",          "2026-08-29", "17:30", 2, "neutral"),
    ("india_gdp",          "2026-11-28", "17:30", 2, "neutral"),
    ("india_gdp",          "2027-02-28", "17:30", 2, "neutral"),
    ("monthly_expiry_NIFTY",  "2026-08-28", "15:30", 2, "neutral"),
    ("monthly_expiry_NIFTY",  "2026-09-25", "15:30", 2, "neutral"),
    ("monthly_expiry_NIFTY",  "2026-10-29", "15:30", 2, "neutral"),
    ("monthly_expiry_NIFTY",  "2026-11-26", "15:30", 2, "neutral"),
    ("monthly_expiry_NIFTY",  "2026-12-31", "15:30", 2, "neutral"),
]


class MacroCalendar:
    def __init__(self):
        self.events = self._parse_events()

    def _parse_events(self) -> list[dict]:
        parsed = []
        for name, date_str, time_str, importance, direction in MACRO_EVENTS_2026:
            try:
                d = date.fromisoformat(date_str)
                hh, mm = map(int, time_str.split(":"))
                dt = datetime(d.year, d.month, d.day, hh, mm)
                parsed.append({
                    "name": name,
                    "datetime_ist": dt,
                    "importance": importance,
                    "direction_hint": direction,
                })
            except Exception as e:
                logger.warning(f"parse event {name}: {e}")
        return sorted(parsed, key=lambda e: e["datetime_ist"])

    def next_event(self, now: datetime | None = None) -> Optional[dict]:
        now = now or now_ist().replace(tzinfo=None)
        for e in self.events:
            if e["datetime_ist"] > now and e["importance"] >= 2:
                delta = e["datetime_ist"] - now
                return {
                    **e,
                    "minutes_to_event": int(delta.total_seconds() / 60),
                }
        return None

    def get_event_window(self, now: datetime | None = None, minutes_before: int = 30,
                         minutes_after: int = 30) -> Optional[dict]:
        """Return event info if we're within ±N minutes of an event."""
        now = now or now_ist().replace(tzinfo=None)
        for e in self.events:
            delta = (e["datetime_ist"] - now).total_seconds() / 60
            if -minutes_after <= delta <= minutes_before:
                return {**e, "minutes_to_event": int(delta)}
        return None


# =============================================================
# OI Heatmap
# =============================================================
def build_oi_heatmap(latest_ticks: dict, underlying: str) -> dict:
    """Given {symbol: Tick} (from LiveFeed.get_oi_map), build a strike → OI map.
    Returns: {
        "strikes": [list of strikes],
        "ce_oi": [list of call OI per strike],
        "pe_oi": [list of put OI per strike],
        "ce_ltp": [list of call LTP per strike],
        "pe_ltp": [list of put LTP per strike],
        "max_call_oi_strike": strike with highest call OI (resistance),
        "max_put_oi_strike": strike with highest put OI (support),
    }
    """
    strikes_data: dict[float, dict] = {}
    for sym, t in latest_ticks.items():
        if not sym.startswith(underlying):
            continue
        if not (sym.endswith("CE") or sym.endswith("PE")):
            continue
        # parse strike from symbol (e.g. NIFTY10AUG2625000CE → 25000)
        opt_type = sym[-2:]
        rest = sym[len(underlying):-2]
        # strip expiry (7 chars DDMMMYY)
        if len(rest) < 8:
            continue
        try:
            strike = int(rest[7:])  # 7 chars expiry + strike
        except ValueError:
            continue
        if strike not in strikes_data:
            strikes_data[strike] = {"ce_oi": 0, "pe_oi": 0, "ce_ltp": 0.0, "pe_ltp": 0.0}
        if opt_type == "CE":
            strikes_data[strike]["ce_oi"] = t.oi
            strikes_data[strike]["ce_ltp"] = t.ltp
        else:
            strikes_data[strike]["pe_oi"] = t.oi
            strikes_data[strike]["pe_ltp"] = t.ltp
    if not strikes_data:
        return {}
    sorted_strikes = sorted(strikes_data.keys())
    ce_oi = [strikes_data[s]["ce_oi"] for s in sorted_strikes]
    pe_oi = [strikes_data[s]["pe_oi"] for s in sorted_strikes]
    ce_ltp = [strikes_data[s]["ce_ltp"] for s in sorted_strikes]
    pe_ltp = [strikes_data[s]["pe_ltp"] for s in sorted_strikes]
    max_call_oi_strike = sorted_strikes[ce_oi.index(max(ce_oi))] if ce_oi and max(ce_oi) > 0 else None
    max_put_oi_strike = sorted_strikes[pe_oi.index(max(pe_oi))] if pe_oi and max(pe_oi) > 0 else None
    return {
        "strikes": sorted_strikes,
        "ce_oi": ce_oi,
        "pe_oi": pe_oi,
        "ce_ltp": ce_ltp,
        "pe_ltp": pe_ltp,
        "max_call_oi_strike": max_call_oi_strike,
        "max_put_oi_strike": max_put_oi_strike,
        "total_ce_oi": sum(ce_oi),
        "total_pe_oi": sum(pe_oi),
        "pcr": sum(pe_oi) / max(1, sum(ce_oi)),
    }


# =============================================================
# EOD Reconciliation
# =============================================================
def reconcile_positions(broker_positions: dict, expected_positions: dict) -> dict:
    """Compare broker state vs expected state. Returns {symbol: {broker_qty, expected_qty, diff}}.
    Any diff is a problem (orphan order, missed fill, etc).
    """
    all_syms = set(broker_positions.keys()) | set(expected_positions.keys())
    diff = {}
    for s in all_syms:
        b = broker_positions.get(s, {}).get("qty", 0)
        e = expected_positions.get(s, {}).get("qty", 0)
        if b != e:
            diff[s] = {"broker_qty": b, "expected_qty": e, "diff": b - e}
    return diff
