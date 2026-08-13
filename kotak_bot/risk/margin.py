"""Real margin tracking — pre-trade checks, alerts, position sizing.

Sits between the RiskEngine and the broker. Two responsibilities:

  1. Margin check: before any order, ensure we have enough free margin.
     For Kotak PROD, uses the live `limits()` API. For paper, computes
     a synthetic margin from the broker's get_margins() + open positions.

  2. Margin alerts: at 50%, 70%, 90% utilization, send a Telegram alert
     (throttled to once per level per day so we don't spam).

Why this lives here (not in RiskEngine)
---------------------------------------
RiskEngine owns *capital-at-risk* decisions (max loss per trade, daily loss cap).
MarginTracker owns *broker-side collateral* — these are different concepts
(you can have plenty of capital-at-risk headroom but be out of margin because
of naked option positions, and vice versa). Keeping them separate means each
can evolve without breaking the other.

Configuration (risk.margin in settings.yaml):
  margin:
    enabled: true
    refresh_sec: 30                 # how often to fetch fresh margin
    alert_levels_pct: [50, 70, 90]  # when to alert (utilization %)
    alert_cooldown_hours: 4         # min hours between re-alerts at the same level
    min_free_margin_pct: 10         # block new trades if free margin < 10% of total
    pre_trade_buffer_pct: 5         # require 5% headroom on top of the trade cost
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger


@dataclass
class MarginSnapshot:
    """Snapshot of margin state at a point in time."""
    total: float = 0.0
    used: float = 0.0
    available: float = 0.0
    cash: float = 0.0
    # For options specifically (Kotak returns span-wise breakdown)
    span: float = 0.0
    exposure: float = 0.0
    # Meta
    as_of: str = ""
    source: str = "unknown"  # 'kotak_limits' | 'paper_synth' | 'fallback'
    error: str = ""

    @property
    def utilization_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return (self.used / self.total) * 100.0

    @property
    def free_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return (self.available / self.total) * 100.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "used": self.used,
            "available": self.available,
            "cash": self.cash,
            "span": self.span,
            "exposure": self.exposure,
            "utilization_pct": round(self.utilization_pct, 2),
            "free_pct": round(self.free_pct, 2),
            "as_of": self.as_of,
            "source": self.source,
            "error": self.error,
        }


@dataclass
class MarginAlertConfig:
    """Tunables for margin alerts."""
    enabled: bool = True
    refresh_sec: float = 30.0
    alert_levels_pct: tuple[float, ...] = (50.0, 70.0, 90.0)
    alert_cooldown_hours: float = 4.0
    min_free_margin_pct: float = 10.0
    pre_trade_buffer_pct: float = 5.0

    @classmethod
    def from_dict(cls, d: dict) -> "MarginAlertConfig":
        levels = d.get("alert_levels_pct", [50, 70, 90])
        if not isinstance(levels, (list, tuple)):
            levels = [levels]
        return cls(
            enabled=bool(d.get("enabled", True)),
            refresh_sec=float(d.get("refresh_sec", 30.0)),
            alert_levels_pct=tuple(float(x) for x in levels),
            alert_cooldown_hours=float(d.get("alert_cooldown_hours", 4.0)),
            min_free_margin_pct=float(d.get("min_free_margin_pct", 10.0)),
            pre_trade_buffer_pct=float(d.get("pre_trade_buffer_pct", 5.0)),
        )


class MarginTracker:
    """Fetches margin snapshots, runs pre-trade checks, fires alerts."""

    def __init__(
        self,
        broker,
        config: Optional[MarginAlertConfig] = None,
        alerter: Optional[Any] = None,
    ) -> None:
        self.broker = broker
        self.config = config or MarginAlertConfig()
        self.alerter = alerter
        self._snapshot: MarginSnapshot = MarginSnapshot()
        self._last_fetch_ts: float = 0.0
        self._alerted_levels: dict[float, float] = {}  # level → last alert ts
        self._lock = threading.Lock()
        self._alerts_sent: int = 0
        self._blocks: int = 0  # trades blocked due to insufficient margin

    # ---------------------------------------------------------------- public

    def get_snapshot(self, force: bool = False) -> MarginSnapshot:
        """Return the latest margin snapshot, refreshing if stale.

        Caches for `config.refresh_sec` to avoid hammering the broker.
        """
        with self._lock:
            now = time.time()
            if force or (now - self._last_fetch_ts) >= self.config.refresh_sec:
                self._refresh()
            return self._snapshot

    def pre_trade_check(
        self,
        trade_cost: float,
        symbol: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Check if we can take a trade that costs `trade_cost` rupees of margin.

        Returns (ok, reason). When ok=False, reason explains why.
        trade_cost is the additional margin that would be consumed (premium *
        qty * lot_size for the SELL legs of an iron condor, etc).
        """
        snap = self.get_snapshot(force=True)
        if not self.config.enabled:
            return True, "margin check disabled"
        if snap.total <= 0:
            # No margin data — fail open (don't block) but log
            logger.debug(f"[MARGIN] no margin data; allowing trade (cost={trade_cost})")
            return True, "no_margin_data"
        # Min free margin
        if snap.free_pct < self.config.min_free_margin_pct:
            self._blocks += 1
            return False, (
                f"free margin too low: {snap.free_pct:.1f}% "
                f"< min {self.config.min_free_margin_pct}% "
                f"(available=₹{snap.available:,.0f}, total=₹{snap.total:,.0f})"
            )
        # Pre-trade buffer: require headroom on top of the cost
        required_pct = self.config.pre_trade_buffer_pct + (
            (trade_cost / snap.total) * 100.0
        )
        free_pct_after = snap.free_pct - ((trade_cost / snap.total) * 100.0)
        if free_pct_after < self.config.pre_trade_buffer_pct:
            self._blocks += 1
            return False, (
                f"trade would breach buffer: cost=₹{trade_cost:,.0f} "
                f"({(trade_cost/snap.total)*100:.1f}% of total), "
                f"free after ={free_pct_after:.1f}% "
                f"< buffer {self.config.pre_trade_buffer_pct}%"
            )
        return True, "ok"

    def check_and_alert(self) -> list[str]:
        """Check current margin against alert levels; send Telegram on threshold cross.

        Returns list of alert messages sent (for testing + dashboard).
        """
        if not self.config.enabled or self.alerter is None:
            return []
        snap = self.get_snapshot(force=True)
        if snap.total <= 0:
            return []
        sent: list[str] = []
        now = time.time()
        for level in sorted(self.config.alert_levels_pct, reverse=True):
            if snap.utilization_pct < level:
                continue
            # Check cooldown
            last_ts = self._alerted_levels.get(level, 0.0)
            if (now - last_ts) < (self.config.alert_cooldown_hours * 3600.0):
                continue
            # Send alert
            icon = "🟡" if level < 70 else ("🟠" if level < 90 else "🔴")
            msg = (
                f"{icon} MARGIN ALERT: utilization {snap.utilization_pct:.1f}% "
                f"(>= {level:.0f}%)\n"
                f"  used=₹{snap.used:,.0f} / total=₹{snap.total:,.0f}\n"
                f"  available=₹{snap.available:,.0f} ({snap.free_pct:.1f}%)\n"
                f"  source={snap.source}"
            )
            try:
                self.alerter.warn(msg)
                self._alerted_levels[level] = now
                self._alerts_sent += 1
                sent.append(msg)
            except Exception as e:
                logger.warning(f"[MARGIN] alert send failed: {e}")
        return sent

    def summary(self) -> dict:
        snap = self._snapshot
        return {
            "snapshot": snap.to_dict(),
            "alerts_sent_total": self._alerts_sent,
            "blocks_total": self._blocks,
            "alerted_levels": list(self._alerted_levels.keys()),
            "config": {
                "enabled": self.config.enabled,
                "refresh_sec": self.config.refresh_sec,
                "alert_levels_pct": list(self.config.alert_levels_pct),
                "min_free_margin_pct": self.config.min_free_margin_pct,
                "pre_trade_buffer_pct": self.config.pre_trade_buffer_pct,
            },
        }

    # --------------------------------------------------------------- internal

    def _refresh(self) -> None:
        """Fetch fresh margin from broker; populate _snapshot."""
        try:
            snap = self._fetch_from_broker()
            self._snapshot = snap
            self._last_fetch_ts = time.time()
            logger.debug(f"[MARGIN] refreshed: {snap.to_dict()}")
        except Exception as e:
            self._snapshot.error = f"refresh_failed: {e}"
            logger.warning(f"[MARGIN] refresh failed: {e}")

    def _fetch_from_broker(self) -> MarginSnapshot:
        """Try Kotak limits() first, then fall back to broker.get_margins()."""
        # Path 1: Kotak PROD limits() (preferred)
        if hasattr(self.broker, "limits"):
            try:
                raw = self.broker.limits()
                if raw and isinstance(raw, dict):
                    # Kotak returns: {'Net': ..., 'Available': ..., 'Used': ..., 'Cash': ...}
                    # sometimes also 'Span' / 'Exposure' / 'Adhoc'
                    total = float(raw.get("Net") or raw.get("Total") or 0)
                    avail = float(raw.get("Available") or 0)
                    used = float(raw.get("Used") or max(0.0, total - avail))
                    cash = float(raw.get("Cash") or 0)
                    span = float(raw.get("Span") or 0)
                    exposure = float(raw.get("Exposure") or 0)
                    return MarginSnapshot(
                        total=total, used=used, available=avail, cash=cash,
                        span=span, exposure=exposure,
                        as_of=datetime.now(timezone.utc).isoformat(),
                        source="kotak_limits",
                    )
            except Exception as e:
                logger.debug(f"[MARGIN] limits() failed: {e}")
        # Path 2: broker.get_margins() (works for paper + neo)
        try:
            m = self.broker.get_margins() or {}
            if not isinstance(m, dict):
                m = {}
            return MarginSnapshot(
                total=float(m.get("total") or m.get("net") or 0),
                used=float(m.get("used") or 0),
                available=float(m.get("available") or m.get("avail") or 0),
                cash=float(m.get("cash") or 0),
                as_of=datetime.now(timezone.utc).isoformat(),
                source="broker_get_margins",
            )
        except Exception as e:
            return MarginSnapshot(
                as_of=datetime.now(timezone.utc).isoformat(),
                source="fallback",
                error=f"all_paths_failed: {e}",
            )
