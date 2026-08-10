"""IST clock + market session helpers."""
from __future__ import annotations

from datetime import datetime, time, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def market_session(now: datetime | None = None) -> str:
    """Return one of: pre_open, opening, regular, closing, closed."""
    now = now or now_ist()
    t = now.time()
    weekday = now.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return "closed"
    if time(9, 0) <= t < time(9, 15):
        return "pre_open"
    if time(9, 15) <= t < time(9, 30):
        return "opening"
    if time(9, 30) <= t < time(15, 0):
        return "regular"
    if time(15, 0) <= t < time(15, 30):
        return "closing"
    return "closed"


def is_market_open(now: datetime | None = None) -> bool:
    s = market_session(now)
    return s in ("pre_open", "opening", "regular", "closing")


def time_to_close(now: datetime | None = None) -> timedelta:
    """How long until market close (3:30 PM IST)."""
    now = now or now_ist()
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if now.time() > time(15, 30):
        close += timedelta(days=1)
    return close - now


def is_square_off_time(now: datetime | None = None, threshold: time = time(15, 15)) -> bool:
    """Square off all intraday positions by 3:15 PM."""
    now = now or now_ist()
    return now.time() >= threshold
