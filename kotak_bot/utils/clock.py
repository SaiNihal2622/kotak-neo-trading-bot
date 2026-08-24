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

    Empty / None dict RESETS to the NSE standard defaults defined at module
    load time. Useful for tests that need to undo an override.
    """
    if not cfg:
        # Reset to module defaults
        _MARKET_HOURS["pre_open_start"] = time(9, 0)
        _MARKET_HOURS["pre_open_end"] = time(9, 15)
        _MARKET_HOURS["opening_end"] = time(9, 30)
        _MARKET_HOURS["regular_end"] = time(15, 0)
        _MARKET_HOURS["close"] = time(15, 30)
        _MARKET_HOURS["square_off"] = time(15, 15)
        return
    for k, v in cfg.items():
        if k in _MARKET_HOURS and isinstance(v, str):
            try:
                h, m = v.split(":")
                _MARKET_HOURS[k] = time(int(h), int(m))
            except (ValueError, AttributeError):
                pass  # keep current value on bad input


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
    """Return True if the regular trading session is open (excludes pre_open).

    FIX 2026-08-25: pre_open (9:00-9:15 IST) is the NSE pre-open auction window.
    The bot was treating this as "open" and placing MARKET orders at 09:00:32 IST
    on 2026-08-24 — paper fills at pre-open indicative prices, not real auction
    prices. pre_open is now excluded; if you need it for some reason, call
    market_session(now) == "pre_open" explicitly.

    Regular session: 9:15 (opening) → 15:30 (close).
    """
    s = market_session(now)
    return s in ("opening", "regular", "closing")


def is_pre_open(now: Optional[datetime] = None) -> bool:
    """True if currently in the NSE pre-open auction (9:00-9:15 IST)."""
    return market_session(now) == "pre_open"


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


def is_past_market_close(now: Optional[datetime] = None) -> bool:
    """True if current time is at or past the configured market close (default 15:30 IST).

    Used by the phantom-0DTE filter: if `expiry == today` and time >= close,
    the contract has technically expired on the exchange. Any position the broker
    still reports with cached LTP is a stale record and should be excluded from
    the position cap (it'll be auto-settled at end-of-day, but in the meantime
    it would block today's signals).

    Pre-market (before 09:00) the same-day check is also useful: positions from
    yesterday that are still reported by the broker are caught by the
    `expiry < today` filter; positions reported with `expiry == today` before
    open are typically stale records from the previous session that haven't
    been settled yet.
    """
    now = now or now_ist()
    return now.time() >= _MARKET_HOURS["close"]


# Intraday mode configuration (separate from market_hours to make intent explicit)
_INTRADAY = {
    "allow_overnight": False,    # master switch — when False, no positions held past close
    "no_new_trades_after": time(13, 30),  # block new entries this many minutes before close
    "force_square_off_time": time(14, 30),  # hard square-off all positions this time
    "opening_buffer_min": 15,    # don't enter in first 15 min (9:15-9:30) — let price settle
    "avoid_first_5_min_after_open": True,
    "event_blackout_min_before": 60,  # don't trade within 60 min of a macro event
    "event_blackout_min_after": 15,   # or within 15 min after
}


def set_intraday(cfg: dict) -> None:
    """Configure intraday behavior. Pass empty dict to reset to defaults."""
    global _INTRADAY
    if not cfg:
        return
    new_cfg = dict(_INTRADAY)
    for k, v in cfg.items():
        if k in new_cfg:
            if k in ("no_new_trades_after", "force_square_off_time") and isinstance(v, str):
                try:
                    h, m = v.split(":")
                    new_cfg[k] = time(int(h), int(m))
                except (ValueError, AttributeError):
                    pass
            else:
                new_cfg[k] = v
    _INTRADAY = new_cfg


def get_intraday() -> dict:
    return dict(_INTRADAY)


def is_past_no_new_trades_time(now: Optional[datetime] = None) -> bool:
    """True if we're past the time when new entries should be blocked (intraday safety)."""
    now = now or now_ist()
    return now.time() >= _INTRADAY["no_new_trades_after"]


def is_past_force_square_off_time(now: Optional[datetime] = None) -> bool:
    """True if it's time to force-square-off all intraday positions."""
    now = now or now_ist()
    return now.time() >= _INTRADAY["force_square_off_time"]


def is_in_opening_buffer(now: Optional[datetime] = None) -> bool:
    """True if we're in the first 15 min after market open (9:15-9:30) — avoid trading."""
    if not _INTRADAY.get("avoid_first_5_min_after_open", True):
        return False
    now = now or now_ist()
    # opening_end is 9:30, opening starts at 9:15 (pre_open_end)
    return now.time() >= _MARKET_HOURS["pre_open_end"] and now.time() < _MARKET_HOURS["opening_end"]


def is_allow_overnight() -> bool:
    """True if overnight positions are allowed. False = intraday-only mode."""
    return _INTRADAY.get("allow_overnight", False)


def in_event_blackout(now: Optional[datetime] = None, macro_cal=None) -> bool:
    """True if we're in a macro-event blackout window (e.g. RBI policy, US Fed)."""
    if macro_cal is None:
        return False
    try:
        ev = macro_cal.get_event_window(
            now or now_ist(),
            minutes_before=_INTRADAY.get("event_blackout_min_before", 60),
            minutes_after=_INTRADAY.get("event_blackout_min_after", 15),
        )
        return ev is not None
    except Exception:
        return False


# =============================================================
# INDIA VIX — fetched once at startup, refreshed every 15 min
# Used by VIX-aware position sizing and trade skipping.
# =============================================================
_INDIA_VIX = 14.0  # default fallback if fetch fails
_VIX_LAST_FETCH = None  # datetime of last successful fetch


def fetch_india_vix(force: bool = False) -> float:
    """Fetch India VIX from yfinance. Cached for 15 min. Falls back to last value."""
    global _INDIA_VIX, _VIX_LAST_FETCH
    from datetime import datetime, timedelta, timezone
    if not force and _VIX_LAST_FETCH and (datetime.now(timezone.utc) - _VIX_LAST_FETCH) < timedelta(minutes=15):
        return _INDIA_VIX
    try:
        import yfinance as yf
        # India VIX ticker on yfinance
        vix_ticker = yf.Ticker("^INDIAVIX")
        hist = vix_ticker.history(period="5d")
        if not hist.empty:
            _INDIA_VIX = float(hist["Close"].iloc[-1])
            _VIX_LAST_FETCH = datetime.now(timezone.utc)
    except Exception:
        pass  # keep last value
    return _INDIA_VIX


def get_india_vix() -> float:
    return _INDIA_VIX


def vix_position_size_multiplier(vix: float) -> float:
    """Return position size multiplier based on VIX.
    VIX <= 12: 1.0x (calm)
    VIX 12-15: 1.0x
    VIX 15-18: 0.75x
    VIX 18-22: 0.5x
    VIX > 22: 0.0x (no trade)
    """
    if vix > 22:
        return 0.0
    if vix > 18:
        return 0.5
    if vix > 15:
        return 0.75
    return 1.0


def vix_should_skip(vix: float, max_vix: float = 22.0) -> bool:
    """True if VIX is too high to trade."""
    return vix > max_vix
