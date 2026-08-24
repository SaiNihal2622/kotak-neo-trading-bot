"""Order resilience layer — retry, cancel-replace, fallback data.

Wraps broker.place_order with:
  1. Exponential-backoff retry (3 attempts by default: 1s, 2s, 4s)
  2. Cancel-replace on stale orders (configurable timeout, e.g. 60s)
  3. Fallback to a secondary data feed if the primary feed fails

The wrapper is intentionally broker-agnostic — it works on any BrokerClient
that exposes place_order, cancel_order, get_order_status, get_quote, get_ltp.
The fallback data feed is pluggable (Kotak → Dhan → yfinance).

Why this lives here (not in OrderManager)
-----------------------------------------
OrderManager owns the trade lifecycle; this module owns the *resilience*
behavior (what to do when something fails). Separation lets us add new
resilience policies without touching trade management.

Configuration (risk.execution in settings.yaml):
  execution:
    retry:
      enabled: true
      max_attempts: 3
      backoff_sec: [1.0, 2.0, 4.0]   # one per attempt
      retryable_errors: ["timeout", "network", "rate_limit"]
    cancel_replace:
      enabled: true
      stale_after_sec: 60            # consider OPEN >60s as stale
      move_threshold_pct: 0.5        # if LTP moved >0.5% from order price
      max_replaces_per_order: 1      # don't replace more than once per order
      price_adjust_pct: 0.1          # new price = old +/- 0.1% toward market
    fallback_data:
      enabled: true
      primary: "kotak_prod"
      fallbacks: ["dhan", "yfinance"]
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from loguru import logger


@dataclass
class ResilientConfig:
    """All settings for the resilient execution layer."""

    # Retry
    retry_enabled: bool = True
    retry_max_attempts: int = 3
    retry_backoff_sec: tuple[float, ...] = (1.0, 2.0, 4.0)
    retryable_errors: tuple[str, ...] = ("timeout", "network", "rate_limit", "5xx", "session_expired")

    # Cancel-replace
    cr_enabled: bool = True
    cr_stale_after_sec: float = 60.0
    cr_move_threshold_pct: float = 0.5
    cr_max_replaces_per_order: int = 1
    cr_price_adjust_pct: float = 0.1

    # Fallback data
    fallback_enabled: bool = True
    fallback_chain: tuple[str, ...] = ("dhan", "yfinance")

    @classmethod
    def from_dict(cls, d: dict) -> "ResilientConfig":
        """Build from a settings.yaml dict (with sensible defaults)."""
        retry = d.get("retry", {})
        cr = d.get("cancel_replace", {})
        fb = d.get("fallback_data", {})
        backoff = retry.get("backoff_sec", [1.0, 2.0, 4.0])
        if not isinstance(backoff, (list, tuple)):
            backoff = [backoff]
        chain = fb.get("fallbacks", ["dhan", "yfinance"])
        if not isinstance(chain, (list, tuple)):
            chain = [chain]
        return cls(
            retry_enabled=retry.get("enabled", True),
            retry_max_attempts=int(retry.get("max_attempts", 3)),
            retry_backoff_sec=tuple(float(x) for x in backoff),
            retryable_errors=tuple(retry.get("retryable_errors", ["timeout", "network", "rate_limit", "5xx", "session_expired"])),
            cr_enabled=cr.get("enabled", True),
            cr_stale_after_sec=float(cr.get("stale_after_sec", 60.0)),
            cr_move_threshold_pct=float(cr.get("move_threshold_pct", 0.5)),
            cr_max_replaces_per_order=int(cr.get("max_replaces_per_order", 1)),
            cr_price_adjust_pct=float(cr.get("price_adjust_pct", 0.1)),
            fallback_enabled=fb.get("enabled", True),
            fallback_chain=tuple(chain),
        )


@dataclass
class OrderAttempt:
    """Records one execution attempt for diagnostics."""
    timestamp: str
    attempt_num: int
    order_id: Optional[str]
    action: str  # "place" | "cancel" | "replace"
    success: bool
    error: Optional[str] = None
    elapsed_ms: int = 0


@dataclass
class ResilientMetrics:
    """Aggregate metrics — used by tests + dashboard."""
    total_place_calls: int = 0
    total_retries: int = 0
    total_replaces: int = 0
    total_fallback_used: int = 0
    total_failures: int = 0
    last_attempt_ts: Optional[str] = None
    attempts: list[OrderAttempt] = field(default_factory=list)

    def record(self, attempt: OrderAttempt) -> None:
        self.attempts.append(attempt)
        self.last_attempt_ts = attempt.timestamp
        if attempt.action == "place":
            self.total_place_calls += 1
        elif attempt.action == "replace":
            self.total_place_calls += 1
            self.total_replaces += 1
        if not attempt.success:
            self.total_failures += 1


def _is_retryable_error(err: Exception, retryable: Iterable[str]) -> bool:
    """Classify an exception as retryable or not."""
    msg = str(err).lower().replace("_", " ").replace("-", " ")
    for kw in retryable:
        if kw.lower().replace("_", " ").replace("-", " ") in msg:
            return True
    # Common network errors
    if isinstance(err, (ConnectionError, TimeoutError)):
        return True
    return False


class ResilientExecutor:
    """Wraps a broker with retry + cancel-replace + fallback data."""

    def __init__(
        self,
        broker,
        config: Optional[ResilientConfig] = None,
        get_ltp_fn: Optional[Callable[[str], float]] = None,
        metrics_path: str = "data_cache/resilient_metrics.jsonl",
    ) -> None:
        self.broker = broker
        self.config = config or ResilientConfig()
        # get_ltp_fn(symbol) -> float; defaults to broker.get_ltp
        self._get_ltp = get_ltp_fn or (lambda sym: float(self.broker.get_ltp(sym) or 0))
        self.metrics = ResilientMetrics()
        self._replaced_order_ids: set[str] = set()
        self._lock = threading.Lock()
        self._metrics_path = Path(metrics_path)
        self._metrics_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ retry
    def place_order(self, order, bracket=None):
        """Place an order with retry. Returns the broker's Order object.

        Raises the last exception if all attempts fail.
        """
        attempts = self.config.retry_max_attempts if self.config.retry_enabled else 1
        backoff = self.config.retry_backoff_sec
        last_err: Optional[Exception] = None
        for i in range(1, attempts + 1):
            t0 = time.time()
            try:
                placed = self.broker.place_order(order, bracket=bracket)
                elapsed = int((time.time() - t0) * 1000)
                self.metrics.record(OrderAttempt(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    attempt_num=i,
                    order_id=getattr(placed, "order_id", None),
                    action="place",
                    success=True,
                    elapsed_ms=elapsed,
                ))
                if i > 1:
                    logger.info(f"[RESILIENT] order {order.symbol} placed on attempt {i}/{attempts}")
                self._flush_metrics()
                return placed
            except Exception as e:
                elapsed = int((time.time() - t0) * 1000)
                last_err = e
                retryable = _is_retryable_error(e, self.config.retryable_errors)
                self.metrics.record(OrderAttempt(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    attempt_num=i,
                    order_id=None,
                    action="place",
                    success=False,
                    error=f"{type(e).__name__}: {e}",
                    elapsed_ms=elapsed,
                ))
                if not retryable or i >= attempts:
                    logger.warning(f"[RESILIENT] order {order.symbol} failed (attempt {i}/{attempts}, retryable={retryable}): {e}")
                    self._flush_metrics()
                    raise
                # Otherwise backoff and retry
                wait = backoff[min(i - 1, len(backoff) - 1)]
                logger.info(f"[RESILIENT] order {order.symbol} attempt {i}/{attempts} failed ({e}); retrying in {wait}s")
                self.metrics.total_retries += 1
                time.sleep(wait)
        # Should not reach here, but be safe
        if last_err:
            raise last_err
        raise RuntimeError("[RESILIENT] place_order exhausted attempts without exception")

    # -------------------------------------------------------------- cancel-replace
    def maybe_cancel_replace(self, order) -> Optional[Any]:
        """If an OPEN order is stale AND the market has moved, cancel+replace it.

        Returns the new order if replaced, None if no action taken.
        Skips if:
          - cancel-replace disabled
          - order was already replaced once (per-order cap)
          - market has not moved beyond threshold
        """
        if not self.config.cr_enabled:
            return None
        oid = getattr(order, "order_id", None)
        if not oid or oid in self._replaced_order_ids:
            return None
        status = self._safe_get_status(order)
        if str(status).lower() not in ("open", "pending", "trigger_pending", "open_pending"):
            return None
        # Age check
        placed_at = getattr(order, "placed_at", None)
        if placed_at is None:
            return None
        try:
            age_sec = (datetime.now(timezone.utc) - placed_at).total_seconds() if placed_at.tzinfo else (datetime.now(timezone.utc) - placed_at).total_seconds()
        except Exception:
            return None
        if age_sec < self.config.cr_stale_after_sec:
            return None
        # Move check
        ltp = self._get_ltp(order.symbol)
        if ltp <= 0 or order.price <= 0:
            return None
        if order.side.value == "BUY":
            # For BUY, market moving UP is bad (we're chasing)
            move_pct = ((ltp - order.price) / order.price) * 100.0
        else:
            # For SELL, market moving DOWN is bad
            move_pct = ((order.price - ltp) / order.price) * 100.0
        if abs(move_pct) < self.config.cr_move_threshold_pct:
            return None
        # Replace
        try:
            self.broker.cancel_order(order)
            self.metrics.record(OrderAttempt(
                timestamp=datetime.now(timezone.utc).isoformat(),
                attempt_num=0,
                order_id=oid,
                action="cancel",
                success=True,
            ))
        except Exception as e:
            logger.warning(f"[RESILIENT] cancel failed for {oid}: {e}")
            self.metrics.record(OrderAttempt(
                timestamp=datetime.now(timezone.utc).isoformat(),
                attempt_num=0,
                order_id=oid,
                action="cancel",
                success=False,
                error=str(e),
            ))
            return None
        # Adjust price toward market
        adj_pct = self.config.cr_price_adjust_pct / 100.0
        if order.side.value == "BUY":
            new_price = round(ltp * (1 + adj_pct), 2)
        else:
            new_price = round(ltp * (1 - adj_pct), 2)
        # Build a fresh order (don't mutate the original)
        new_order = type(order)(
            **{**order.__dict__, "price": new_price, "order_id": None, "status": None}
        ) if hasattr(order, "__dict__") else None
        if new_order is None:
            logger.warning(f"[RESILIENT] cannot clone order for replace; skipping")
            return None
        try:
            placed = self.broker.place_order(new_order)
            self._replaced_order_ids.add(oid)
            self.metrics.record(OrderAttempt(
                timestamp=datetime.now(timezone.utc).isoformat(),
                attempt_num=0,
                order_id=getattr(placed, "order_id", None),
                action="replace",
                success=True,
            ))
            logger.info(f"[RESILIENT] replaced stale order {oid} ({order.symbol}) at {order.price} → {new_price} (LTP={ltp}, age={age_sec:.0f}s, move={move_pct:.2f}%)")
            self._flush_metrics()
            return placed
        except Exception as e:
            logger.warning(f"[RESILIENT] replace failed for {oid}: {e}")
            self.metrics.record(OrderAttempt(
                timestamp=datetime.now(timezone.utc).isoformat(),
                attempt_num=0,
                order_id=oid,
                action="replace",
                success=False,
                error=str(e),
            ))
            self._flush_metrics()
            return None

    def _safe_get_status(self, order) -> str:
        """Best-effort status lookup without raising."""
        try:
            oid = getattr(order, "order_id", None)
            if oid and hasattr(self.broker, "get_order_status"):
                s = self.broker.get_order_status(oid)
                if s is not None:
                    return str(s)
        except Exception:
            pass
        return str(getattr(order, "status", "open") or "open")

    # -------------------------------------------------------------- fallback data
    def get_ltp_with_fallback(self, symbol: str, primary_ltp_fn: Optional[Callable[[str], float]] = None) -> tuple[float, str]:
        """Try primary LTP source, then fallbacks. Returns (ltp, source_used).

        source_used is "primary" | "dhan" | "yfinance" | "none".
        Does NOT raise — returns (0.0, "none") if all sources fail.
        """
        primary_ltp_fn = primary_ltp_fn or (lambda sym: float(self._get_ltp(sym)))
        try:
            ltp = float(primary_ltp_fn(symbol) or 0)
            if ltp > 0:
                return ltp, "primary"
        except Exception as e:
            logger.debug(f"[RESILIENT] primary LTP failed for {symbol}: {e}")
        if not self.config.fallback_enabled:
            return 0.0, "none"
        for source in self.config.fallback_chain:
            try:
                ltp = float(self._fallback_ltp(source, symbol) or 0)
                if ltp > 0:
                    self.metrics.total_fallback_used += 1
                    logger.info(f"[RESILIENT] LTP fallback {source} for {symbol}: ₹{ltp}")
                    return ltp, source
            except Exception as e:
                logger.debug(f"[RESILIENT] fallback {source} failed for {symbol}: {e}")
        return 0.0, "none"

    def _fallback_ltp(self, source: str, symbol: str) -> float:
        """Pluggable fallback. Concrete implementations registered externally."""
        fn = getattr(self, f"_fallback_{source}", None)
        if fn is None:
            return 0.0
        return float(fn(symbol) or 0)

    def register_fallback(self, source: str, fn: Callable[[str], float]) -> None:
        """Register a fallback LTP function for a source name."""
        setattr(self, f"_fallback_{source}", fn)

    # -------------------------------------------------------------- diagnostics
    def _flush_metrics(self) -> None:
        """Append current attempt log to disk (one line per attempt)."""
        try:
            with self._lock:
                with self._metrics_path.open("a", encoding="utf-8") as f:
                    for a in self.metrics.attempts[-10:]:  # last 10 only per flush
                        f.write(f"{a.timestamp}\t{a.action}\t{a.attempt_num}\t{a.order_id}\t{int(a.success)}\t{a.elapsed_ms}\t{a.error or ''}\n")
                # Don't grow attempts list unbounded
                self.metrics.attempts = self.metrics.attempts[-50:]
        except Exception as e:
            logger.debug(f"[RESILIENT] metrics flush failed: {e}")

    def summary(self) -> dict:
        """Return a dict summary for the dashboard / Telegram."""
        return {
            "total_place_calls": self.metrics.total_place_calls,
            "total_retries": self.metrics.total_retries,
            "total_replaces": self.metrics.total_replaces,
            "total_fallback_used": self.metrics.total_fallback_used,
            "total_failures": self.metrics.total_failures,
            "replaced_order_count": len(self._replaced_order_ids),
            "last_attempt_ts": self.metrics.last_attempt_ts,
        }
