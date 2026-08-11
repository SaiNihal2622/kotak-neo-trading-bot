"""IST clock + market session helpers.

All time thresholds (market open/close, square-off, session windows) are
configurable. The defaults match NSE standard hours but can be overridden
via the `set_market_hours()` function (called from __main__.py at startup
with values from settings.yaml).

No hardcoded business hours in the bot's runtime paths.
"""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30))

# Module-level configurable hours (IST). Default = NSE standard.
# Override via set_market_hours() at startup with settings.yaml values.
_MARKET_HOURS = {
    "pre_open_start": time(9, 0),
    "pre_open_end": time(9, 15),
    "opening_end": time(9, 30),
    "regular_end": time(15, 0),
    "close": time(15, 30),
    "square_off": time(15, 15),
}


def set_market_hours(cfg: dict) -> None:
    """Override default market hours from config. Pass an empty dict to reset to defaults.

    Expected keys (all optional): pre_open_start, pre_open_end, opening_end,
    regular_end, close, square_off. Values are 'HH:MM' strings.
    """
    if not cfg:
        return
    for k, v in cfg.items():
        if k in _MARKET_HOURS and isinstance(v, str):
            try:
                h, m = v.split(":")
                _MARKET_HOURS[k] = time(int(h), int(m))
            except (ValueError, AttributeError):
                pass  # keep default on bad input


def get_market_hours() -> dict:
    """Return current market-hours config (read-only copy)."""
    return dict(_MARKET_HOURS)


def now_ist() -> datetime:
    return datetime.now(IST)


def market_session(now: Optional[datetime] = None) -> str:
    """Return one of: pre_open, opening, regular, closing, closed."""
    now = now or now_ist()
    t = now.time()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return "closed"
    if _MARKET_HOURS["pre_open_start"] <= t < _MARKET_HOURS["pre_open_end"]:
        return "pre_open"
    if _MARKET_HOURS["pre_open_end"] <= t < _MARKET_HOURS["opening_end"]:
        return "opening"
    if _MARKET_HOURS["opening_end"] <= t < _MARKET_HOURS["regular_end"]:
        return "regular"
    if _MARKET_HOURS["regular_end"] <= t < _MARKET_HOURS["close"]:
        return "closing"
    return "closed"


def is_market_open(now: Optional[datetime] = None) -> bool:
    s = market_session(now)
    return s in ("pre_open", "opening", "regular", "closing")


def time_to_close(now: Optional[datetime] = None) -> timedelta:
    """How long until market close."""
    now = now or now_ist()
    close_h, close_m = _MARKET_HOURS["close"].hour, _MARKET_HOURS["close"].minute
    close = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)
    if now.time() > _MARKET_HOURS["close"]:
        close += timedelta(days=1)
    return close - now


def is_square_off_time(now: Optional[datetime] = None, threshold: Optional[time] = None) -> bool:
    """Square off all intraday positions by the configured time (default 15:15)."""
    now = now or now_ist()
    t = threshold or _MARKET_HOURS["square_off"]
    return now.time() >= t
