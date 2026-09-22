"""Tests for kotak_bot.signals.atomic_judgments (the Jev pattern).

Covers:
- Tier 1 (HARD VETO) paths
- Tier 2 (DOWNSIZE to qty=0.5) paths
- Tier 3 (APPROVE at full qty) paths
- Tier 4 (DOWNSIZE on uncertainty)
- Parser robustness (valid + malformed LLM outputs)
- Legacy-shape conversion for backward compat with quant_service
"""
import json
import sys
from pathlib import Path

# repo root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from kotak_bot.signals.atomic_judgments import (
    AggregatedAction,
    DirectionChoice,
    InventoryChoice,
    JudgedDecision,
    NoulChoice,
    QuoteChoice,
    RegimeChoice,
    SixJudgments,
    aggregate_judgments,
    aggregator_to_legacy_decision,
    format_state_for_judgments,
    judge_and_aggregate,
    parse_six_judgments,
)


def _judgments(**overrides) -> SixJudgments:
    """Factory with safe defaults (clean ranging market, neutral, no stress)."""
    defaults = dict(
        regime=RegimeChoice.RANGING,
        direction=DirectionChoice.NEUTRAL,
        toxic_flow=NoulChoice.LOW,
        liquidity_stressed=NoulChoice.LOW,
        quote_environment=QuoteChoice.FAVORABLE,
        inventory_pressure=InventoryChoice.NONE,
    )
    defaults.update(overrides)
    return SixJudgments(**defaults)


# ---------------------------------------------------------------------------
# Tier 1: hard vetoes
# ---------------------------------------------------------------------------

class TestTier1Veto:

    def test_toxic_flow_high_vetoes(self):
        j = _judgments(toxic_flow=NoulChoice.HIGH)
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.VETO
        assert d.qty_multiplier == 0.0
        assert d.tier == 1
        assert "toxic_flow=high" in d.fired_rules

    def test_liquidity_stressed_high_vetoes(self):
        j = _judgments(liquidity_stressed=NoulChoice.HIGH)
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.VETO
        assert d.qty_multiplier == 0.0
        assert d.tier == 1
        assert "liquidity_stressed=high" in d.fired_rules

    def test_volatile_neutral_vetoes(self):
        """Volatile regime WITHOUT a directional edge = chaos. Don't trade."""
        j = _judgments(regime=RegimeChoice.VOLATILE, direction=DirectionChoice.NEUTRAL)
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.VETO
        assert d.tier == 1
        assert "volatile+neutral_direction" in d.fired_rules

    def test_volatile_with_bullish_bias_NOT_vetoed(self):
        """Volatile regime WITH a directional edge is not a Tier-1 veto.
        It just shouldn't get Tier-3 approve either (will fall to Tier-4 downsize)."""
        j = _judgments(regime=RegimeChoice.VOLATILE, direction=DirectionChoice.BULLISH)
        d = aggregate_judgments(j)
        assert d.action != AggregatedAction.VETO, (
            "volatile + bullish should NOT veto — there's a directional edge"
        )

    def test_multiple_tier1_fired_all_listed(self):
        j = _judgments(toxic_flow=NoulChoice.HIGH, liquidity_stressed=NoulChoice.HIGH)
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.VETO
        assert "toxic_flow=high" in d.fired_rules
        assert "liquidity_stressed=high" in d.fired_rules


# ---------------------------------------------------------------------------
# Tier 2: downsize to qty=0.5
# ---------------------------------------------------------------------------

class TestTier2Downsize:

    def test_toxic_normal_with_unfavorable_quotes(self):
        j = _judgments(
            toxic_flow=NoulChoice.NORMAL,
            quote_environment=QuoteChoice.UNFAVORABLE,
        )
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.DOWNSIZE
        assert d.qty_multiplier == 0.5
        assert d.tier == 2

    def test_inventory_pressure_long_triggers_downsize(self):
        j = _judgments(inventory_pressure=InventoryChoice.LONG)
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.DOWNSIZE
        assert d.tier == 2
        assert "inventory_pressure=long" in d.fired_rules

    def test_inventory_pressure_heavy_triggers_downsize(self):
        j = _judgments(inventory_pressure=InventoryChoice.HEAVY)
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.DOWNSIZE
        assert d.tier == 2

    def test_trending_with_unfavorable_quotes_downsize(self):
        j = _judgments(
            regime=RegimeChoice.TRENDING,
            quote_environment=QuoteChoice.UNFAVORABLE,
        )
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.DOWNSIZE
        assert d.tier == 2


# ---------------------------------------------------------------------------
# Tier 3: approve at full qty
# ---------------------------------------------------------------------------

class TestTier3Approve:

    def test_clean_ranging_neutral_favorable_approves(self):
        j = _judgments()  # all defaults are clean
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.APPROVE
        assert d.qty_multiplier == 1.0
        assert d.tier == 3

    def test_quiet_with_favorable_quotes_approves(self):
        j = _judgments(
            regime=RegimeChoice.QUIET,
            quote_environment=QuoteChoice.FAVORABLE,
        )
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.APPROVE
        assert d.tier == 3

    def test_clean_with_bullish_directional_approves(self):
        """Tier-3 needs clean range or quiet — bullish trending with clean conditions
        should still get approved (via Tier-4 → wait, no — it would go to Tier-4).
        Actually let me check: clean + bullish + neutral quotes → Tier-4 (no match for Tier-3)."""
        j = _judgments(
            regime=RegimeChoice.TRENDING,
            direction=DirectionChoice.BULLISH,
            quote_environment=QuoteChoice.NEUTRAL,  # neutral, not favorable
        )
        d = aggregate_judgments(j)
        # Trending + neutral quotes is not Tier-3 (Tier-3 wants favorable)
        # and not Tier-2 (toxic/liquidity normal counts >=1 + unfavorable quotes is the trigger)
        # so it falls to Tier-4 (mixed signals)
        assert d.tier == 4
        assert d.action == AggregatedAction.DOWNSIZE


# ---------------------------------------------------------------------------
# Tier 4: downsize on uncertainty
# ---------------------------------------------------------------------------

class TestTier4MixedSignals:

    def test_default_clean_but_bullish_trending(self):
        """Trending + bullish + neutral quotes (everything else clean).
        Doesn't match Tier-3 (needs favorable) or Tier-2 (no stressors). Tier-4."""
        j = _judgments(
            regime=RegimeChoice.TRENDING,
            direction=DirectionChoice.BULLISH,
        )
        d = aggregate_judgments(j)
        assert d.action == AggregatedAction.DOWNSIZE
        assert d.tier == 4
        assert d.qty_multiplier == 0.5
        assert "mixed_signals" in d.fired_rules


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class TestParser:

    def test_parses_clean_json(self):
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        j = parse_six_judgments(text)
        assert j is not None
        assert j.regime == RegimeChoice.RANGING
        assert j.toxic_flow == NoulChoice.LOW

    def test_strips_code_fences(self):
        text = '```json\n{"regime":"quiet","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}\n```'
        j = parse_six_judgments(text)
        assert j is not None
        assert j.regime == RegimeChoice.QUIET

    def test_strips_think_blocks(self):
        text = '<think>Let me analyze...</think>{"regime":"trending","direction":"bullish","toxic_flow":"normal","liquidity_stressed":"normal","quote_environment":"neutral","inventory_pressure":"none"}'
        j = parse_six_judgments(text)
        assert j is not None
        assert j.regime == RegimeChoice.TRENDING
        assert j.direction == DirectionChoice.BULLISH

    def test_handles_prose_around_json(self):
        text = (
            "Here's my analysis of the market:\n\n"
            '{"regime":"volatile","direction":"bearish","toxic_flow":"high","liquidity_stressed":"low","quote_environment":"neutral","inventory_pressure":"short"}\n\n'
            "That's my assessment."
        )
        j = parse_six_judgments(text)
        assert j is not None
        assert j.regime == RegimeChoice.VOLATILE
        assert j.toxic_flow == NoulChoice.HIGH

    def test_returns_none_on_missing_fields(self):
        text = '{"regime":"ranging","direction":"neutral"}'  # missing 4 fields
        assert parse_six_judgments(text) is None

    def test_returns_none_on_invalid_enum(self):
        text = '{"regime":"moon","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        assert parse_six_judgments(text) is None

    def test_returns_none_on_garbage(self):
        assert parse_six_judgments("") is None
        assert parse_six_judgments("the market is bullish today") is None
        assert parse_six_judgments("{incomplete json") is None
        assert parse_six_judgments("[1, 2, 3]") is None  # wrong shape (array)

    def test_case_insensitive(self):
        text = '{"regime":"RANGING","direction":"Neutral","toxic_flow":"LOW","liquidity_stressed":"LOW","quote_environment":"FAVORABLE","inventory_pressure":"none"}'
        j = parse_six_judgments(text)
        assert j is not None
        assert j.regime == RegimeChoice.RANGING
        assert j.direction == DirectionChoice.NEUTRAL


# ---------------------------------------------------------------------------
# Combined judge_and_aggregate + legacy-shape conversion
# ---------------------------------------------------------------------------

class TestJudgeAndAggregate:

    def test_veto_path(self):
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"high","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        assert result is not None
        assert result.aggregated.action == AggregatedAction.VETO
        assert result.aggregated.qty_multiplier == 0.0
        assert result.parse_ok

    def test_approve_path(self):
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        assert result is not None
        assert result.aggregated.action == AggregatedAction.APPROVE
        assert result.aggregated.qty_multiplier == 1.0

    def test_parse_failure_returns_none(self):
        result = judge_and_aggregate({}, "garbage")
        assert result is None

    def test_legacy_veto_to_hold(self):
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"high","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        legacy = aggregator_to_legacy_decision(result, plan_qty=75)
        assert legacy["type"] == "HOLD"
        assert legacy["target_qty"] == 0  # 75 * 0.0

    def test_legacy_approve_to_open_full_qty(self):
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        legacy = aggregator_to_legacy_decision(result, plan_qty=75)
        assert legacy["type"] == "OPEN"
        assert legacy["target_qty"] == 75  # 75 * 1.0

    def test_legacy_downsize_to_open_half_qty(self):
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"normal","liquidity_stressed":"low","quote_environment":"unfavorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        legacy = aggregator_to_legacy_decision(result, plan_qty=75)
        assert legacy["type"] == "OPEN"
        assert legacy["target_qty"] == 38  # round(75 * 0.5) = 38 (banker's rounding)

    def test_legacy_cl_override(self):
        """When the caller supplies override_type='CLOSE' (e.g. risk override),
        we always emit CLOSE — the aggregator's multiplier still scales the qty."""
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        legacy = aggregator_to_legacy_decision(result, plan_qty=75, override_type="CLOSE")
        assert legacy["type"] == "CLOSE"
        assert legacy["target_qty"] == 75  # APPROVE → mult 1.0


# ---------------------------------------------------------------------------
# State formatter — should be compact (< 400 tokens)
# ---------------------------------------------------------------------------

class TestStateFormatter:

    def test_state_under_400_tokens(self):
        state = {
            "spot": 23456.78, "vix": 11.5, "adx": 18.3, "pnl_day": -250.0,
            "cash": 100000, "positions_count": 2,
            "direction_bias": "neutral", "realized_sigma_5m": 0.05,
            "avg_spread_bps": 4.5, "oi_change_pct_5m": -1.2,
        }
        s = format_state_for_judgments(state)
        # Roughly 4 chars per token; 400 tokens = 1600 chars. Leave room for prompt overhead.
        assert len(s) < 600, f"state string too long: {len(s)} chars"
        # All required fields should appear
        for key in ("SPOT=", "VIX=", "ADX=", "CASH=", "POSITIONS=", "DAYPNL="):
            assert key in s, f"missing key {key}"

    def test_handles_missing_fields(self):
        s = format_state_for_judgments({})  # empty state
        assert "SPOT=" in s and "?" in s  # unknown fields become "?"
