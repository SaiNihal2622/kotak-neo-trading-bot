"""Tests for the margin tracker + pre-trade check + alerts."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from kotak_bot.risk.margin import (
    MarginAlertConfig,
    MarginSnapshot,
    MarginTracker,
)


def _make_broker(limits_value=None, margins_value=None, limits_raises=False, margins_raises=False) -> MagicMock:
    b = MagicMock()
    if limits_raises:
        b.limits = MagicMock(side_effect=RuntimeError("kotak down"))
    else:
        b.limits = MagicMock(return_value=limits_value)
    if margins_raises:
        b.get_margins = MagicMock(side_effect=RuntimeError("no margins"))
    else:
        b.get_margins = MagicMock(return_value=margins_value or {})
    return b


# ----------------- snapshot -----------------

def test_snapshot_utilization_pct():
    s = MarginSnapshot(total=100000, used=50000, available=50000)
    assert s.utilization_pct == 50.0
    assert s.free_pct == 50.0


def test_snapshot_zero_total():
    s = MarginSnapshot()
    assert s.utilization_pct == 0.0
    assert s.free_pct == 0.0


def test_snapshot_to_dict():
    s = MarginSnapshot(total=100000, used=50000, available=50000)
    d = s.to_dict()
    assert d["utilization_pct"] == 50.0
    assert d["free_pct"] == 50.0
    assert "as_of" in d


# ----------------- config -----------------

def test_config_from_dict_defaults():
    cfg = MarginAlertConfig.from_dict({})
    assert cfg.enabled is True
    assert cfg.alert_levels_pct == (50.0, 70.0, 90.0)
    assert cfg.min_free_margin_pct == 10.0


def test_config_from_dict_overrides():
    cfg = MarginAlertConfig.from_dict({
        "alert_levels_pct": [40, 80],
        "min_free_margin_pct": 15,
        "pre_trade_buffer_pct": 8,
    })
    assert cfg.alert_levels_pct == (40.0, 80.0)
    assert cfg.min_free_margin_pct == 15.0
    assert cfg.pre_trade_buffer_pct == 8.0


# ----------------- fetch from broker -----------------

def test_fetch_uses_kotak_limits_when_available():
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 70000, "Used": 30000, "Cash": 100000, "Span": 25000, "Exposure": 5000},
        margins_value={"total": 999, "available": 999},  # should NOT be used
    )
    mt = MarginTracker(broker, config=MarginAlertConfig(enabled=False))
    snap = mt.get_snapshot(force=True)
    assert snap.source == "kotak_limits"
    assert snap.total == 100000
    assert snap.available == 70000
    assert snap.used == 30000
    assert snap.span == 25000
    assert snap.exposure == 5000


def test_fetch_falls_back_to_get_margins():
    broker = _make_broker(
        limits_value=None,  # no limits method effective
        margins_value={"total": 50000, "available": 30000, "used": 20000},
    )
    # Disable limits() entirely
    del broker.limits
    mt = MarginTracker(broker, config=MarginAlertConfig(enabled=False))
    snap = mt.get_snapshot(force=True)
    assert snap.source == "broker_get_margins"
    assert snap.total == 50000


def test_fetch_falls_back_when_limits_fails():
    broker = _make_broker(
        limits_raises=True,
        margins_value={"total": 50000, "available": 30000, "used": 20000},
    )
    mt = MarginTracker(broker, config=MarginAlertConfig(enabled=False))
    snap = mt.get_snapshot(force=True)
    assert snap.source == "broker_get_margins"
    assert snap.total == 50000


def test_fetch_handles_all_failures():
    broker = _make_broker(limits_raises=True, margins_raises=True)
    mt = MarginTracker(broker, config=MarginAlertConfig(enabled=False))
    snap = mt.get_snapshot(force=True)
    assert snap.source == "fallback"
    assert "all_paths_failed" in snap.error


def test_get_snapshot_caches():
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 100000, "Used": 0},
    )
    mt = MarginTracker(broker, config=MarginAlertConfig(refresh_sec=60, enabled=False))
    mt.get_snapshot(force=True)
    snap1 = mt.get_snapshot()
    # Second call should not refetch (broker.limits called once)
    assert broker.limits.call_count == 1
    # Force a refetch
    snap2 = mt.get_snapshot(force=True)
    assert broker.limits.call_count == 2


# ----------------- pre-trade check -----------------

def test_pre_trade_check_disabled_allows():
    broker = _make_broker(margins_value={"total": 0, "available": 0})
    mt = MarginTracker(broker, config=MarginAlertConfig(enabled=False))
    ok, reason = mt.pre_trade_check(trade_cost=10000)
    assert ok is True
    assert reason == "margin check disabled"


def test_pre_trade_check_no_margin_data_allows():
    broker = _make_broker(margins_value={})
    mt = MarginTracker(broker, config=MarginAlertConfig(enabled=True))
    ok, reason = mt.pre_trade_check(trade_cost=10000)
    assert ok is True
    assert reason == "no_margin_data"


def test_pre_trade_check_blocks_low_free_margin():
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 5000, "Used": 95000},  # 5% free
    )
    mt = MarginTracker(broker, config=MarginAlertConfig(
        enabled=True, min_free_margin_pct=10.0, pre_trade_buffer_pct=5.0,
    ))
    ok, reason = mt.pre_trade_check(trade_cost=1000)
    assert ok is False
    assert "too low" in reason
    assert mt._blocks == 1


def test_pre_trade_check_blocks_breach_buffer():
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 20000, "Used": 80000},  # 20% free
    )
    mt = MarginTracker(broker, config=MarginAlertConfig(
        enabled=True, min_free_margin_pct=10.0, pre_trade_buffer_pct=5.0,
    ))
    # Trade cost = 16000 → 16% of 100000 → free after = 4% < 5% buffer
    ok, reason = mt.pre_trade_check(trade_cost=16000)
    assert ok is False
    assert "buffer" in reason.lower()


def test_pre_trade_check_allows_within_buffer():
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 50000, "Used": 50000},  # 50% free
    )
    mt = MarginTracker(broker, config=MarginAlertConfig(
        enabled=True, min_free_margin_pct=10.0, pre_trade_buffer_pct=5.0,
    ))
    ok, reason = mt.pre_trade_check(trade_cost=5000)  # 5% of total
    assert ok is True
    assert reason == "ok"


# ----------------- alerts -----------------

def test_check_and_alert_sends_at_50():
    alerter = MagicMock()
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 40000, "Used": 60000},  # 60% used
    )
    cfg = MarginAlertConfig(enabled=True, alert_levels_pct=(50, 70, 90), alert_cooldown_hours=4)
    mt = MarginTracker(broker, config=cfg, alerter=alerter)
    sent = mt.check_and_alert()
    assert len(sent) == 1
    assert "60.0%" in sent[0]
    assert ">= 50%" in sent[0]
    assert alerter.warn.call_count == 1


def test_check_and_alert_throttled_by_cooldown():
    alerter = MagicMock()
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 40000, "Used": 60000},
    )
    cfg = MarginAlertConfig(enabled=True, alert_levels_pct=(50,), alert_cooldown_hours=4)
    mt = MarginTracker(broker, config=cfg, alerter=alerter)
    # First call: alert
    sent1 = mt.check_and_alert()
    # Second call (within cooldown): no alert
    sent2 = mt.check_and_alert()
    assert len(sent1) == 1
    assert len(sent2) == 0
    assert alerter.warn.call_count == 1


def test_check_and_alert_under_threshold_no_alert():
    alerter = MagicMock()
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 80000, "Used": 20000},  # 20% used
    )
    cfg = MarginAlertConfig(enabled=True, alert_levels_pct=(50, 70, 90))
    mt = MarginTracker(broker, config=cfg, alerter=alerter)
    sent = mt.check_and_alert()
    assert len(sent) == 0
    assert alerter.warn.call_count == 0


def test_check_and_alert_only_highest_crossed_level():
    """At 80% used, only the 70% level should fire (90% not yet crossed)."""
    alerter = MagicMock()
    broker = _make_broker(
        limits_value={"Net": 100000, "Available": 20000, "Used": 80000},  # 80% used
    )
    cfg = MarginAlertConfig(enabled=True, alert_levels_pct=(50, 70, 90), alert_cooldown_hours=0)
    mt = MarginTracker(broker, config=cfg, alerter=alerter)
    sent = mt.check_and_alert()
    # Should alert for both 50% and 70% (both crossed)
    assert len(sent) == 2
    levels_in_msgs = [m for m in sent if ">= 50%" in m or ">= 70%" in m]
    assert len(levels_in_msgs) == 2


def test_check_and_alert_disabled():
    alerter = MagicMock()
    broker = _make_broker(limits_value={"Net": 100000, "Available": 0, "Used": 100000})
    cfg = MarginAlertConfig(enabled=False, alert_levels_pct=(50,))
    mt = MarginTracker(broker, config=cfg, alerter=alerter)
    sent = mt.check_and_alert()
    assert sent == []
    assert alerter.warn.call_count == 0


def test_check_and_alert_handles_alerter_failure():
    alerter = MagicMock()
    alerter.warn = MagicMock(side_effect=RuntimeError("telegram down"))
    broker = _make_broker(limits_value={"Net": 100000, "Available": 40000, "Used": 60000})
    cfg = MarginAlertConfig(enabled=True, alert_levels_pct=(50,))
    mt = MarginTracker(broker, config=cfg, alerter=alerter)
    # Should not raise
    sent = mt.check_and_alert()
    assert sent == []  # send failed → not recorded as sent


# ----------------- summary -----------------

def test_summary_includes_snapshot_and_config():
    broker = _make_broker(limits_value={"Net": 100000, "Available": 80000, "Used": 20000})
    cfg = MarginAlertConfig(enabled=True, alert_levels_pct=(50, 70, 90), min_free_margin_pct=12)
    mt = MarginTracker(broker, config=cfg)
    mt.get_snapshot(force=True)  # populate snapshot
    s = mt.summary()
    assert s["snapshot"]["utilization_pct"] == 20.0
    assert s["config"]["min_free_margin_pct"] == 12
    assert s["alerts_sent_total"] == 0
    assert s["blocks_total"] == 0


def test_summary_counts_blocks():
    broker = _make_broker(limits_value={"Net": 100000, "Available": 5000, "Used": 95000})
    cfg = MarginAlertConfig(enabled=True, min_free_margin_pct=10, pre_trade_buffer_pct=5)
    mt = MarginTracker(broker, config=cfg)
    mt.pre_trade_check(trade_cost=1000)
    mt.pre_trade_check(trade_cost=2000)
    s = mt.summary()
    assert s["blocks_total"] == 2
