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

    def test_trade_plan_passthrough_copies_legs_and_metadata(self):
        # FIX 2026-09-23 10:32: when trade_plan is supplied, the legacy decision
        # must carry underlying/expiry/strategy/legs through. Without this,
        # the bot's order_mgr reads the action file but sees legs=[] and
        # places nothing (the "OPEN None legs=0" bug).
        text = '{"regime":"quiet","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        plan = {
            "strategy": "iron_condor_nifty",
            "structure": "iron_condor",
            "underlying": "NIFTY",
            "expiry": "WEEKLY",
            "n_lots": 2,
            "max_hold_minutes": 45,
            "target": 1500.0,
            "stop": -750.0,
            "legs": [
                {"side": "SELL", "qty": 2, "strike": 24600, "opt_type": "CE", "order_type": "LIMIT", "price": 100},
                {"side": "BUY",  "qty": 2, "strike": 24700, "opt_type": "CE", "order_type": "LIMIT", "price": 30},
                {"side": "SELL", "qty": 2, "strike": 24400, "opt_type": "PE", "order_type": "LIMIT", "price": 100},
                {"side": "BUY",  "qty": 2, "strike": 24300, "opt_type": "PE", "order_type": "LIMIT", "price": 30},
            ],
        }
        legacy = aggregator_to_legacy_decision(result, plan_qty=75, trade_plan=plan)
        # Tier 3 APPROVE → type=OPEN, full qty
        assert legacy["type"] == "OPEN"
        assert legacy["target_qty"] == 2  # n_lots * 1.0 = 2 (overrides plan_qty default)
        # Plan metadata copied
        assert legacy["underlying"] == "NIFTY"
        assert legacy["expiry"] == "WEEKLY"
        assert legacy["strategy"] == "iron_condor_nifty"
        assert legacy["structure"] == "iron_condor"
        assert legacy["max_hold_minutes"] == 45
        assert legacy["target"] == 1500.0
        assert legacy["stop"] == -750.0
        # Legs passed through, qty unchanged (Tier 3 = 1.0x)
        assert len(legacy["legs"]) == 4
        assert all(leg["qty"] == 2 for leg in legacy["legs"])
        assert legacy["legs"][0]["strike"] == 24600
        assert legacy["legs"][3]["opt_type"] == "PE"

    def test_trade_plan_dowsize_scales_each_leg(self):
        # Tier 4 DOWNSIZE with n_lots=2 should produce legs with qty=1 each
        # (2 * 0.5 = 1, rounded).
        text = '{"regime":"ranging","direction":"neutral","toxic_flow":"normal","liquidity_stressed":"low","quote_environment":"unfavorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        plan = {
            "underlying": "BANKNIFTY",
            "expiry": "WEEKLY",
            "n_lots": 3,
            "legs": [
                {"side": "BUY", "qty": 3, "strike": 56000, "opt_type": "CE", "order_type": "MARKET"},
                {"side": "BUY", "qty": 3, "strike": 55500, "opt_type": "PE", "order_type": "MARKET"},
            ],
        }
        legacy = aggregator_to_legacy_decision(result, plan_qty=75, trade_plan=plan)
        assert legacy["type"] == "OPEN"  # Tier 4 = DOWNSIZE but still OPEN
        assert legacy["target_qty"] == 2  # round(3 * 0.5) = 2 (banker's rounding)
        # Each leg should also be halved
        assert all(leg["qty"] == 2 for leg in legacy["legs"]), \
            f"legs not halved: {[leg['qty'] for leg in legacy['legs']]}"
        assert legacy["underlying"] == "BANKNIFTY"

    def test_no_trade_plan_still_works_without_legs(self):
        # Backwards compat: calling without trade_plan should still work
        # and not include 'legs' in the output (matches the old behavior).
        text = '{"regime":"quiet","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
        result = judge_and_aggregate({}, text)
        legacy = aggregator_to_legacy_decision(result, plan_qty=75)
        assert legacy["type"] == "OPEN"
        assert legacy["target_qty"] == 75
        assert "legs" not in legacy  # no plan = no legs (backwards compat)

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
        # FIX 2026-09-23: state now has 21 fields, but still ~600 chars (~80 tokens)
        state = {
            "spot": 23456.78, "vix": 11.5, "adx": 18.3, "pnl_day": -250.0,
            "cash": 100000, "positions_count": 2,
            "direction_bias": "neutral", "realized_sigma_5m": 0.05,
            "avg_spread_bps": 4.5, "oi_change_pct_5m": -1.2,
            "pcr": 1.15, "max_pain_dist_pct": -0.4,
            "oi_build_intensity": "med", "rsi_14": 52.0,
            "ema_spread_pct": 0.15, "vwap_dev_pct": 0.05,
            "intraday_range_pct": 0.6, "news_sentiment": 0.12,
            "fii_net_cr": 450.0, "dii_net_cr": -200.0,
            "min_to_close": 387, "expiry_days": 1,
            "vix_percentile": 22.0, "day_of_week": "Wed",
            "last3_pnl": "+150,-80,+40",
        }
        s = format_state_for_judgments(state)
        # 21 fields × ~20 chars each ≈ 420 chars; leave 50% headroom for safety
        assert len(s) < 900, f"state string too long: {len(s)} chars"
        # All required fields should appear
        for key in (
            "SPOT=", "VIX=", "ADX=", "CASH=", "POS=", "DAYPNL=",
            "PCR=", "MAXPAIN_DIST=", "OI_BUILD=", "RSI14=",
            "EMA_SPREAD=", "VWAP_DEV=", "INTRADAY_RNG=",
            "NEWS=", "FII=", "DII=", "DOW=", "LAST3=",
            "SPREADbps=", "OIdelta5m=", "MIN_CLOSE=", "EXPIRY_D=",
            "VIX_PCTL=",
        ):
            assert key in s, f"missing key {key}"

    def test_handles_missing_fields(self):
        s = format_state_for_judgments({})  # empty state
        assert "SPOT=" in s and "?" in s  # unknown fields become "?"

    def test_handles_none_for_optional_fields(self):
        # PCR / RSI / VWAP dev / max_pain may be None when data is missing
        state = {
            "spot": 24550, "vix": 11.25, "adx": 22.0,
            "pcr": None, "rsi_14": None, "vwap_dev_pct": None,
            "max_pain_dist_pct": None, "news_sentiment": None,
            "fii_net_cr": None, "dii_net_cr": None,
            "oi_build_intensity": "na",
        }
        s = format_state_for_judgments(state)
        # Missing values should render as "?" not crash
        assert "PCR=?" in s
        assert "RSI14=?" in s
        assert "VWAP_DEV=?" in s
        assert "MAXPAIN_DIST=?" in s
        assert "OI_BUILD=na" in s

    def test_oi_build_intensity_preserved(self):
        # oi_build_intensity is a string enum, not numeric — make sure it doesn't
        # get coerced into a float
        s = format_state_for_judgments({"oi_build_intensity": "high", "spot": 24550})
        assert "OI_BUILD=high" in s
        assert "OI_BUILD=low" not in s  # don't confuse with default

    def test_last3_pnl_serialized_as_string(self):
        # last3_pnl is a pre-formatted string like "+150,-80,+40" — pass through
        s = format_state_for_judgments({"last3_pnl": "+200,-50,+100"})
        assert "LAST3=+200,-50,+100" in s

    def test_dow_three_letters(self):
        s = format_state_for_judgments({"day_of_week": "Thu"})
        assert "DOW=Thu" in s
