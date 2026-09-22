"""Atomic Judgements — the Jev (TypeSafe System One) pattern for kotak-neo-bot.

Reference: https://github.com/SiliconLabAI/OpenJev
Background:  https://gist.github.com/drillan/6916b16e8ea31a8ec36c8f59d6483150

THE IDEA
========
The legacy LLM judge returns a single free-form JSON like:
    {"type": "OPEN", "target_qty": 75, "rationale": "..."}

That's brittle — the same state + same model can return OPEN one minute and
HOLD the next. The model is being asked to both DESCRIBE the state AND DECIDE
the action in a single prose output. Reasoning variance is high.

The Jev pattern separates the two roles:
  - LLM DESCRIBES the state via N atomic, closed-enum judgements
  - CODE aggregates those judgements deterministically into an action

This module implements the production version of that pattern for our bot.

SCHEMA
======
We use 6 atomic judgements, each with a closed-enum answer. The model returns
typed values — no prose, no free-form reasoning. Aggregation tiers in code:

  Tier 1 (HARD VETO):
    - toxic_flow = high
    - liquidity_stressed = high
    - volatile regime + neutral direction
    Tier 1 → VETO. qty_multiplier = 0.0. Don't trade.

  Tier 2 (DOWNSIZE to qty=1 / 0.5):
    - trending regime + unfavorable quotes + neutral direction
    - toxic_flow = normal + unfavorable quotes
    - inventory_pressure in (long, short, heavy)
    - any 3+ warnings (toxic normal, liq normal, etc.)
    Tier 2 → DOWNSIZE. qty_multiplier = 0.5.

  Tier 3 (APPROVE at full qty):
    - ranging regime + neutral direction + favorable quotes + no stress
    - quiet regime + any direction + favorable quotes + no stress
    Tier 3 → APPROVE. qty_multiplier = 1.0.

  Tier 4 (DOWNSIZE on uncertainty):
    - everything else (mixed signals)
    Tier 4 → DOWNSIZE. qty_multiplier = 0.5.

WIRING
======
`quant_service.py::invoke_llm_decision()` calls ``build_judged_decision()``
first. On parse success, the aggregator's action+multiplier is the call's
output. On parse failure (LLM returned prose, schema mismatch, etc.), we
fall back to the legacy free-form prompt path so we never block on a model
quirk.

This is backward-compatible: a tier mismatch falls back to the existing
`call_llm_direct()` path that the brain was already using.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Closed-enum answer types (the "vocabulary" the LLM is allowed to use)
# -----------------------------------------------------------------------------

class RegimeChoice(str, Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"


class DirectionChoice(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class NoulChoice(str, Enum):
    """'Noul' = the Jev project term for a 3-valued ordinal (high/normal/low).
    Equivalent to 'stressed / normal / clean' on the financial side."""
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class QuoteChoice(str, Enum):
    FAVORABLE = "favorable"
    NEUTRAL = "neutral"
    UNFAVORABLE = "unfavorable"


class InventoryChoice(str, Enum):
    NONE = "none"      # no open positions
    LONG = "long"      # net long exposure
    SHORT = "short"    # net short exposure
    HEAVY = "heavy"    # gross exposure > 60% of capital


# -----------------------------------------------------------------------------
# The SixJudgements object — what the LLM must return
# -----------------------------------------------------------------------------

@dataclass
class SixJudgments:
    """Six atomic judgements describing the current trading state.
    Each field is a closed-enum. The LLM must return EXACTLY this shape."""

    regime: RegimeChoice
    direction: DirectionChoice
    toxic_flow: NoulChoice              # is informed flow toxic?
    liquidity_stressed: NoulChoice      # is bid/ask liquidity stressed?
    quote_environment: QuoteChoice      # are we getting good fills?
    inventory_pressure: InventoryChoice # current inventory posture

    def to_dict(self) -> dict[str, str]:
        return {
            "regime": self.regime.value,
            "direction": self.direction.value,
            "toxic_flow": self.toxic_flow.value,
            "liquidity_stressed": self.liquidity_stressed.value,
            "quote_environment": self.quote_environment.value,
            "inventory_pressure": self.inventory_pressure.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SixJudgments":
        return cls(
            regime=RegimeChoice(str(d["regime"]).lower()),
            direction=DirectionChoice(str(d["direction"]).lower()),
            toxic_flow=NoulChoice(str(d["toxic_flow"]).lower()),
            liquidity_stressed=NoulChoice(str(d["liquidity_stressed"]).lower()),
            quote_environment=QuoteChoice(str(d["quote_environment"]).lower()),
            inventory_pressure=InventoryChoice(str(d["inventory_pressure"]).lower()),
        )


# -----------------------------------------------------------------------------
# The AggregatedDecision object — what code returns to the brain
# -----------------------------------------------------------------------------

class AggregatedAction(str, Enum):
    APPROVE = "APPROVE"
    DOWNSIZE = "DOWNSIZE"
    VETO = "VETO"


@dataclass
class AggregatedDecision:
    """Result of running `aggregate_judgments`. This is what the brain sees."""

    action: AggregatedAction
    qty_multiplier: float      # 1.0 = full plan qty, 0.5 = half, 0.0 = no trade
    tier: int                  # 1..4 which tier fired
    fired_rules: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "qty_multiplier": round(self.qty_multiplier, 2),
            "tier": self.tier,
            "fired_rules": self.fired_rules,
            "rationale": self.rationale,
        }


# -----------------------------------------------------------------------------
# The Aggregator — deterministic, no LLM, fully testable
# -----------------------------------------------------------------------------

def aggregate_judgments(j: SixJudgments) -> AggregatedDecision:
    """Combine SixJudgments into {APPROVE, DOWNSIZE, VETO} + qty multiplier.

    The thresholds below are CODE, not prompt. They live in one place so
    they can be unit-tested independently of any LLM call (see
    tests/test_atomic_judgments.py).
    """
    fired: list[str] = []

    # ------------------------------------------------------------------ Tier 1
    # Hard vetoes — these are non-negotiable. Even with a strong bullish/bearish
    # call, we do not enter a position under these conditions.
    if j.toxic_flow == NoulChoice.HIGH:
        fired.append("toxic_flow=high")
    if j.liquidity_stressed == NoulChoice.HIGH:
        fired.append("liquidity_stressed=high")
    if j.regime == RegimeChoice.VOLATILE and j.direction == DirectionChoice.NEUTRAL:
        # Volatile regime WITHOUT a clear direction = chaos. Don't add to chaos.
        fired.append("volatile+neutral_direction")
    if fired:
        return AggregatedDecision(
            action=AggregatedAction.VETO,
            qty_multiplier=0.0,
            tier=1,
            fired_rules=fired,
            rationale=(
                "Tier-1 hard veto: "
                + ", ".join(fired)
                + " — no trade regardless of directional bias"
            ),
        )

    # ------------------------------------------------------------------ Tier 2
    # DOWNSIZE: keep the door open but halve the size.
    if j.toxic_flow == NoulChoice.NORMAL and j.quote_environment == QuoteChoice.UNFAVORABLE:
        fired.append("toxic_flow=normal + quotes=unfavorable")
    if j.liquidity_stressed == NoulChoice.NORMAL and j.quote_environment == QuoteChoice.UNFAVORABLE:
        fired.append("liquidity_stressed=normal + quotes=unfavorable")
    if j.inventory_pressure in (InventoryChoice.LONG, InventoryChoice.SHORT, InventoryChoice.HEAVY):
        fired.append(f"inventory_pressure={j.inventory_pressure.value}")
    if j.regime == RegimeChoice.TRENDING and j.quote_environment == QuoteChoice.UNFAVORABLE:
        fired.append("trending + unfavorable_quotes")
    # Two or more "normal" stressors without any one being high
    normal_count = sum([
        j.toxic_flow == NoulChoice.NORMAL,
        j.liquidity_stressed == NoulChoice.NORMAL,
    ])
    if normal_count >= 1 and j.quote_environment == QuoteChoice.UNFAVORABLE:
        fired.append(">=1 normal stressor + unfavorable_quotes")
    if fired:
        return AggregatedDecision(
            action=AggregatedAction.DOWNSIZE,
            qty_multiplier=0.5,
            tier=2,
            fired_rules=fired,
            rationale=(
                "Tier-2 downsize: "
                + ", ".join(fired)
                + " — keep the trade but at half the plan qty"
            ),
        )

    # ------------------------------------------------------------------ Tier 3
    # APPROVE — clean conditions. Full size.
    if j.regime == RegimeChoice.RANGING and j.direction == DirectionChoice.NEUTRAL \
            and j.quote_environment == QuoteChoice.FAVORABLE \
            and j.toxic_flow == NoulChoice.LOW and j.liquidity_stressed == NoulChoice.LOW:
        return AggregatedDecision(
            action=AggregatedAction.APPROVE,
            qty_multiplier=1.0,
            tier=3,
            fired_rules=["clean_range_neutral_favorable"],
            rationale=(
                "Tier-3 approve: clean ranging regime, neutral direction, "
                "favorable quotes, no flow/liquidity stress — full plan qty"
            ),
        )
    if j.regime == RegimeChoice.QUIET and j.quote_environment == QuoteChoice.FAVORABLE \
            and j.toxic_flow == NoulChoice.LOW and j.liquidity_stressed == NoulChoice.LOW:
        return AggregatedDecision(
            action=AggregatedAction.APPROVE,
            qty_multiplier=1.0,
            tier=3,
            fired_rules=["clean_quiet_favorable"],
            rationale=(
                "Tier-3 approve: quiet regime, favorable quotes, no flow/liquidity "
                "stress — full plan qty"
            ),
        )

    # ------------------------------------------------------------------ Tier 4
    # DOWNSIZE on uncertainty — anything that didn't match a clean tier.
    return AggregatedDecision(
        action=AggregatedAction.DOWNSIZE,
        qty_multiplier=0.5,
        tier=4,
        fired_rules=["mixed_signals"],
        rationale=(
            "Tier-4 downsize: judgements didn't match a clean Tier-3 pattern "
            f"(regime={j.regime.value}, direction={j.direction.value}, "
            f"quotes={j.quote_environment.value}) — half qty until cleaner signal"
        ),
    )


# -----------------------------------------------------------------------------
# LLM prompt side — schema, parser, state-shaper
# -----------------------------------------------------------------------------

# OpenAI-compatible JSON schema for structured outputs.
# Every field is closed-enum, so the LLM literally cannot emit prose.
SIX_JUDGMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "regime",
        "direction",
        "toxic_flow",
        "liquidity_stressed",
        "quote_environment",
        "inventory_pressure",
    ],
    "properties": {
        "regime": {
            "type": "string",
            "enum": ["trending", "ranging", "volatile", "quiet"],
            "description": (
                "Current market regime. trending = sustained directional move "
                "(ADX > 25, slope holding). ranging = mean-reverting, ADX < 20, "
                "bands flat. volatile = large ranges both directions, no edge. "
                "quiet = low realized AND implied vol, compressed."
            ),
        },
        "direction": {
            "type": "string",
            "enum": ["bullish", "bearish", "neutral"],
            "description": (
                "Directional bias over the next 1-2 hours from spot. neutral = "
                "no edge in either direction."
            ),
        },
        "toxic_flow": {
            "type": "string",
            "enum": ["high", "normal", "low"],
            "description": (
                "Is informed / toxic order flow present? high = aggressive "
                "sweeps, iceberg detection, or fast prints against our direction. "
                "low = resting limit book, no urgency."
            ),
        },
        "liquidity_stressed": {
            "type": "string",
            "enum": ["high", "normal", "low"],
            "description": (
                "Is the bid/ask liquidity stressed? high = wide spreads, "
                "thin book, requote risk. low = tight spreads, deep book."
            ),
        },
        "quote_environment": {
            "type": "string",
            "enum": ["favorable", "neutral", "unfavorable"],
            "description": (
                "Will our orders get filled at the displayed price? "
                "favorable = limit at touch will fill cleanly. "
                "unfavorable = expected to chase, slip > 1 tick."
            ),
        },
        "inventory_pressure": {
            "type": "string",
            "enum": ["none", "long", "short", "heavy"],
            "description": (
                "Current book posture. none = flat. long = net long delta. "
                "short = net short delta. heavy = gross exposure > 60% of capital "
                "in either direction."
            ),
        },
    },
}


def format_state_for_judgments(state: dict[str, Any]) -> str:
    """Compress state to <400 tokens for the SixJudgements LLM call.

    The legacy prompt was 6-8K tokens. The Jev pattern is built around compact
    state — buberlo/jev-trader explicitly targets <400 tokens. We do the same.
    """
    spot = state.get("spot", "?")
    vix = state.get("vix", "?")
    adx = state.get("adx", "?")
    pnl_day = state.get("pnl_day", 0)
    cash = state.get("cash", 0)
    positions_count = state.get("positions_count", 0)
    direction_bias = state.get("direction_bias", "neutral")
    sigma = state.get("realized_sigma_5m", "?")
    spread_bps = state.get("avg_spread_bps", "?")
    oi_change = state.get("oi_change_pct_5m", 0)

    # Compact single-line state
    return (
        f"SPOT={spot} VIX={vix} ADX={adx} SIGMA5m={sigma} "
        f"SPREADbps={spread_bps} OIdelta5m={oi_change:+.1f}% "
        f"CASH={cash:.0f} POSITIONS={positions_count} "
        f"DAYPNL={pnl_day:+.0f} BIAS={direction_bias}"
    )


JUDGE_SYSTEM_PROMPT = (
    "You are a strict, precise trading desk risk officer. "
    "Your ONLY job is to describe the current trading state via 6 closed-enum "
    "values. You never explain. You never hedge. You never add prose. "
    "Return ONLY a single JSON object matching the schema. "
    "If the state is genuinely ambiguous, pick the closest value — do not "
    "emit 'unknown' or null."
)


def build_judgement_user_prompt(state_str: str) -> str:
    """Final user message asking the model to emit SixJudgments as JSON."""
    return (
        "Describe the current trading state. Return ONLY this JSON shape:\n"
        "{\n"
        '  "regime": "trending|ranging|volatile|quiet",\n'
        '  "direction": "bullish|bearish|neutral",\n'
        '  "toxic_flow": "high|normal|low",\n'
        '  "liquidity_stressed": "high|normal|low",\n'
        '  "quote_environment": "favorable|neutral|unfavorable",\n'
        '  "inventory_pressure": "none|long|short|heavy"\n'
        "}\n\n"
        f"STATE: {state_str}\n\n"
        "JSON:"
    )


# -----------------------------------------------------------------------------
# Parser — extracts SixJudgments from LLM text output
# -----------------------------------------------------------------------------

# Strip code fences + <think> blocks + leading prose before first '{'
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _extract_json_object(text: str) -> Optional[str]:
    """Pull the first top-level JSON object out of an LLM response."""
    if not text:
        return None
    text = _FENCE_RE.sub("", text).strip()
    text = _THINK_RE.sub("", text).strip()
    # Find the first '{' that starts a balanced object
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(text)):
            c = text[j]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[i:j + 1]
        break
    return None


def parse_six_judgments(text: str) -> Optional[SixJudgments]:
    """Try to extract SixJudgments from LLM text. Returns None on any error."""
    blob = _extract_json_object(text)
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except Exception as e:
        logger.debug(f"parse_six_judgments: json.loads failed: {e}")
        return None
    if not isinstance(data, dict):
        return None
    required = set(SIX_JUDGMENT_SCHEMA["required"])
    if not required.issubset(data.keys()):
        logger.debug(f"parse_six_judgments: missing fields: {required - set(data.keys())}")
        return None
    try:
        return SixJudgments.from_dict(data)
    except (KeyError, ValueError) as e:
        logger.debug(f"parse_six_judgments: invalid enum: {e}")
        return None


# -----------------------------------------------------------------------------
# Combined: "judge and execute" — the One-Shot Jev pattern
# -----------------------------------------------------------------------------

@dataclass
class JudgedDecision:
    """Combined output of the SixJudgments + aggregator."""

    judgments: SixJudgments
    aggregated: AggregatedDecision
    raw_text: str = ""
    parse_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "judgments": self.judgments.to_dict(),
            "aggregated": self.aggregated.to_dict(),
            "raw_text": self.raw_text[:500],
            "parse_ok": self.parse_ok,
        }


def judge_and_aggregate(state: dict[str, Any], raw_llm_text: str) -> Optional[JudgedDecision]:
    """Parse the LLM text as SixJudgments, then aggregate. Returns None if parsing fails.

    Callers should fall back to the legacy free-form prompt when this returns None.
    """
    judgments = parse_six_judgments(raw_llm_text)
    if judgments is None:
        return None
    aggregated = aggregate_judgments(judgments)
    return JudgedDecision(
        judgments=judgments,
        aggregated=aggregated,
        raw_text=raw_llm_text,
        parse_ok=True,
    )


# -----------------------------------------------------------------------------
# Convenience: convert aggregator output back to the brain's legacy shape
# -----------------------------------------------------------------------------

def aggregator_to_legacy_decision(
    judged: JudgedDecision,
    plan_qty: int,
    override_type: Optional[str] = None,
) -> dict[str, Any]:
    """Convert {APPROVE, DOWNSIZE, VETO} + multiplier into the brain's
    `{type, target_qty, rationale}` shape used by quant_service.

    If `override_type` is supplied (e.g. "CLOSE"), we always produce that
    action — the aggregator's multiplier still scales the qty.

    `plan_qty` is the qty the trade plan would normally use; the multiplier
    from the aggregator scales it.
    """
    action = override_type
    if action is None:
        if judged.aggregated.action == AggregatedAction.VETO:
            action = "HOLD"
        elif judged.aggregated.action == AggregatedAction.APPROVE:
            action = "OPEN"
        else:  # DOWNSIZE
            action = "OPEN"  # still trade, just half size
    qty = int(round(plan_qty * judged.aggregated.qty_multiplier))
    return {
        "type": action,
        "target_qty": qty,
        "rationale": (
            f"SixJudgments → {judged.aggregated.action.value} "
            f"(tier {judged.aggregated.tier}, mult {judged.aggregated.qty_multiplier:.2f}): "
            + judged.aggregated.rationale
        ),
        "judgments": judged.judgments.to_dict(),
        "tier": judged.aggregated.tier,
        "source": "atomic_judgments",
    }
