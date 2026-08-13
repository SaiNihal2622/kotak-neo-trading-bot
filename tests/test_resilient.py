"""Tests for the resilient execution layer."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kotak_bot.broker.base import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from kotak_bot.execution.resilient import (
    OrderAttempt,
    ResilientConfig,
    ResilientExecutor,
    _is_retryable_error,
)


def _make_order(sym: str = "NIFTY", price: float = 100.0, side: OrderSide = OrderSide.BUY,
                qty: int = 65, oid: str = None) -> Order:
    return Order(
        order_id=oid,
        symbol=sym,
        side=side,
        qty=qty,
        filled_qty=0,
        price=price,
        avg_fill_price=0.0,
        order_type=OrderType.LIMIT,
        product=ProductType.MIS,
        status=OrderStatus.OPEN,
        placed_at=datetime.now(timezone.utc) - timedelta(seconds=120),  # 2 min old
    )


def _make_broker(place_impl=None, cancel_impl=None, status_impl=None, ltp_impl=None) -> MagicMock:
    b = MagicMock()
    b.place_order = MagicMock(side_effect=place_impl) if place_impl else MagicMock(return_value=_make_order(oid="O-PLACED"))
    b.cancel_order = MagicMock(side_effect=cancel_impl) if cancel_impl else MagicMock(return_value=True)
    b.get_order_status = MagicMock(side_effect=status_impl) if status_impl else MagicMock(return_value="open")
    b.get_ltp = MagicMock(side_effect=ltp_impl) if ltp_impl else MagicMock(return_value=100.0)
    return b


# ----------------- config -----------------

def test_config_from_dict_defaults():
    cfg = ResilientConfig.from_dict({})
    assert cfg.retry_enabled is True
    assert cfg.retry_max_attempts == 3
    assert cfg.cr_stale_after_sec == 60.0
    assert cfg.fallback_enabled is True


def test_config_from_dict_overrides():
    cfg = ResilientConfig.from_dict({
        "retry": {"enabled": False, "max_attempts": 5, "backoff_sec": [0.5, 1.0, 2.0, 4.0, 8.0]},
        "cancel_replace": {"stale_after_sec": 30, "move_threshold_pct": 1.0},
        "fallback_data": {"fallbacks": ["yfinance"]},
    })
    assert cfg.retry_enabled is False
    assert cfg.retry_max_attempts == 5
    assert len(cfg.retry_backoff_sec) == 5
    assert cfg.cr_stale_after_sec == 30.0
    assert cfg.cr_move_threshold_pct == 1.0
    assert cfg.fallback_chain == ("yfinance",)


# ----------------- retry classification -----------------

def test_is_retryable_error_classifies_correctly():
    retryable = ["timeout", "network", "rate_limit"]
    assert _is_retryable_error(TimeoutError("read timeout"), retryable) is True
    assert _is_retryable_error(ConnectionError("network unreachable"), retryable) is True
    assert _is_retryable_error(RuntimeError("rate limit exceeded"), retryable) is True
    assert _is_retryable_error(ValueError("invalid input"), retryable) is False


# ----------------- retry behavior -----------------

def test_place_order_succeeds_first_try():
    broker = _make_broker()
    cfg = ResilientConfig(retry_backoff_sec=(0.01, 0.01, 0.01))  # fast
    re = ResilientExecutor(broker, cfg)
    order = _make_order()
    result = re.place_order(order)
    assert result is not None
    assert broker.place_order.call_count == 1
    assert re.metrics.total_place_calls == 1
    assert re.metrics.total_retries == 0
    assert re.metrics.total_failures == 0


def test_place_order_retries_on_timeout():
    """On timeout, retry; succeed on attempt 2."""
    call_count = {"n": 0}

    def place_with_one_timeout(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise TimeoutError("kotak api timeout")
        return _make_order(oid=f"O-{call_count['n']}")

    broker = _make_broker(place_impl=place_with_one_timeout)
    cfg = ResilientConfig(retry_backoff_sec=(0.01, 0.01, 0.01))
    re = ResilientExecutor(broker, cfg)
    order = _make_order()
    result = re.place_order(order)
    assert result is not None
    assert broker.place_order.call_count == 2
    assert re.metrics.total_place_calls == 2  # 1 initial + 1 retry attempt that succeeded
    assert re.metrics.total_retries == 1
    assert re.metrics.total_failures == 1  # the first attempt failed


def test_place_order_exhausts_retries_and_raises():
    def always_timeout(*args, **kwargs):
        raise TimeoutError("persistent timeout")

    broker = _make_broker(place_impl=always_timeout)
    cfg = ResilientConfig(retry_max_attempts=3, retry_backoff_sec=(0.01, 0.01, 0.01))
    re = ResilientExecutor(broker, cfg)
    order = _make_order()
    with pytest.raises(TimeoutError):
        re.place_order(order)
    assert broker.place_order.call_count == 3
    assert re.metrics.total_place_calls == 3
    assert re.metrics.total_retries == 2  # 2 retries beyond initial attempt
    assert re.metrics.total_failures == 3


def test_place_order_does_not_retry_non_retryable():
    def always_invalid(*args, **kwargs):
        raise ValueError("invalid order params")

    broker = _make_broker(place_impl=always_invalid)
    cfg = ResilientConfig(retry_max_attempts=3, retry_backoff_sec=(0.01, 0.01, 0.01))
    re = ResilientExecutor(broker, cfg)
    order = _make_order()
    with pytest.raises(ValueError):
        re.place_order(order)
    assert broker.place_order.call_count == 1  # no retries
    assert re.metrics.total_retries == 0


def test_place_order_retry_disabled():
    def always_timeout(*args, **kwargs):
        raise TimeoutError("timeout")

    broker = _make_broker(place_impl=always_timeout)
    cfg = ResilientConfig(retry_enabled=False, retry_backoff_sec=(0.01,))
    re = ResilientExecutor(broker, cfg)
    order = _make_order()
    with pytest.raises(TimeoutError):
        re.place_order(order)
    assert broker.place_order.call_count == 1


# ----------------- cancel-replace -----------------

def test_maybe_cancel_replace_skips_young_order():
    broker = _make_broker()
    cfg = ResilientConfig(cr_stale_after_sec=60.0, cr_move_threshold_pct=0.5)
    re = ResilientExecutor(broker, cfg)
    order = _make_order(price=100.0)
    # Make it fresh (1s old)
    order.placed_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    re.maybe_cancel_replace(order)
    assert broker.cancel_order.call_count == 0


def test_maybe_cancel_replace_skips_when_market_stable():
    broker = _make_broker(ltp_impl=lambda sym: 100.5)  # <0.5% from 100
    cfg = ResilientConfig(cr_stale_after_sec=60.0, cr_move_threshold_pct=0.5)
    re = ResilientExecutor(broker, cfg)
    order = _make_order(price=100.0)
    order.placed_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    re.maybe_cancel_replace(order)
    assert broker.cancel_order.call_count == 0


def test_maybe_cancel_replace_buy_when_market_up():
    """BUY order + market moved up > 0.5% → cancel and replace at new higher price."""
    placed = {"called": 0}

    def place_new(o, bracket=None):
        placed["called"] += 1
        new = _make_order(oid="O-NEW", price=o.price)
        return new

    broker = _make_broker(ltp_impl=lambda sym: 101.0)  # +1% from 100
    broker.place_order = MagicMock(side_effect=place_new)
    cfg = ResilientConfig(
        cr_stale_after_sec=60.0,
        cr_move_threshold_pct=0.5,
        cr_price_adjust_pct=0.1,
    )
    re = ResilientExecutor(broker, cfg)
    order = _make_order(side=OrderSide.BUY, price=100.0, oid="O-OLD")
    order.placed_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    result = re.maybe_cancel_replace(order)
    assert result is not None
    assert result.order_id == "O-NEW"
    # New price = 101.0 * 1.001 = 101.101 → rounded to 101.1
    assert 100.5 < result.price <= 101.5
    assert broker.cancel_order.call_count == 1
    assert broker.place_order.call_count == 1
    assert re.metrics.total_replaces == 1


def test_maybe_cancel_replace_sell_when_market_down():
    """SELL order + market moved DOWN > 0.5% → cancel and replace at new lower price."""
    def place_clone(o, bracket=None):
        # Return a clone of the input with the new price and a new oid
        new = _make_order(oid="O-NEW-SELL", price=o.price, side=o.side)
        new.order_id = "O-NEW-SELL"
        return new

    broker = _make_broker(ltp_impl=lambda sym: 99.0)  # -1% from 100
    broker.place_order = MagicMock(side_effect=place_clone)
    cfg = ResilientConfig(
        cr_stale_after_sec=60.0,
        cr_move_threshold_pct=0.5,
        cr_price_adjust_pct=0.1,
    )
    re = ResilientExecutor(broker, cfg)
    order = _make_order(side=OrderSide.SELL, price=100.0, oid="O-SELL")
    order.placed_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    result = re.maybe_cancel_replace(order)
    assert result is not None
    # New price = 99.0 * 0.999 = 98.901 → 98.9
    assert 98.0 < result.price < 99.5
    assert broker.cancel_order.call_count == 1


def test_maybe_cancel_replace_respects_max_replaces():
    """Per-order cap: only one replace per order_id."""
    broker = _make_broker(ltp_impl=lambda sym: 102.0)
    cfg = ResilientConfig(cr_stale_after_sec=60.0, cr_move_threshold_pct=0.5, cr_max_replaces_per_order=1)
    re = ResilientExecutor(broker, cfg)
    order = _make_order(price=100.0, oid="O-CAP")
    order.placed_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    # First call replaces
    re.maybe_cancel_replace(order)
    assert broker.cancel_order.call_count == 1
    # Second call should be a no-op (already replaced)
    re.maybe_cancel_replace(order)
    assert broker.cancel_order.call_count == 1  # unchanged


def test_maybe_cancel_replace_skips_filled_order():
    """If order is no longer OPEN, skip cancel-replace."""
    broker = _make_broker(status_impl=lambda oid: "complete")
    cfg = ResilientConfig(cr_stale_after_sec=60.0, cr_move_threshold_pct=0.5)
    re = ResilientExecutor(broker, cfg)
    order = _make_order(price=100.0, oid="O-FILLED")
    order.placed_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    re.maybe_cancel_replace(order)
    assert broker.cancel_order.call_count == 0


# ----------------- fallback data -----------------

def test_get_ltp_with_fallback_primary_works():
    broker = _make_broker(ltp_impl=lambda sym: 123.45)
    re = ResilientExecutor(broker)
    ltp, source = re.get_ltp_with_fallback("NIFTY")
    assert ltp == 123.45
    assert source == "primary"


def test_get_ltp_with_fallback_dhan():
    broker = _make_broker(ltp_impl=lambda sym: 0)  # primary fails
    re = ResilientExecutor(broker)
    re.register_fallback("dhan", lambda sym: 120.0)
    ltp, source = re.get_ltp_with_fallback("NIFTY")
    assert ltp == 120.0
    assert source == "dhan"
    assert re.metrics.total_fallback_used == 1


def test_get_ltp_with_fallback_yfinance_after_dhan_fails():
    broker = _make_broker(ltp_impl=lambda sym: 0)
    re = ResilientExecutor(broker, ResilientConfig(fallback_chain=("dhan", "yfinance")))
    re.register_fallback("dhan", lambda sym: 0)  # dhan fails
    re.register_fallback("yfinance", lambda sym: 118.5)
    ltp, source = re.get_ltp_with_fallback("NIFTY")
    assert ltp == 118.5
    assert source == "yfinance"


def test_get_ltp_with_fallback_all_fail_returns_zero():
    broker = _make_broker(ltp_impl=lambda sym: 0)
    re = ResilientExecutor(broker, ResilientConfig(fallback_chain=("dhan", "yfinance")))
    re.register_fallback("dhan", lambda sym: 0)
    re.register_fallback("yfinance", lambda sym: 0)
    ltp, source = re.get_ltp_with_fallback("NIFTY")
    assert ltp == 0.0
    assert source == "none"


def test_get_ltp_with_fallback_disabled():
    broker = _make_broker(ltp_impl=lambda sym: 0)
    re = ResilientExecutor(broker, ResilientConfig(fallback_enabled=False))
    re.register_fallback("dhan", lambda sym: 120.0)
    ltp, source = re.get_ltp_with_fallback("NIFTY")
    assert ltp == 0.0
    assert source == "none"


# ----------------- summary / metrics -----------------

def test_summary_returns_metrics():
    broker = _make_broker()
    re = ResilientExecutor(broker)
    order = _make_order()
    re.place_order(order)
    s = re.summary()
    assert s["total_place_calls"] == 1
    assert s["total_retries"] == 0
    assert s["total_replaces"] == 0
    assert s["total_failures"] == 0
    assert s["replaced_order_count"] == 0
    assert s["last_attempt_ts"] is not None


def test_metrics_persisted_to_file(tmp_path: Path):
    broker = _make_broker()
    metrics_path = tmp_path / "metrics.jsonl"
    re = ResilientExecutor(broker, metrics_path=str(metrics_path))
    order = _make_order()
    re.place_order(order)
    assert metrics_path.exists()
    content = metrics_path.read_text(encoding="utf-8")
    assert "place" in content
    assert "True" in content or "1" in content
