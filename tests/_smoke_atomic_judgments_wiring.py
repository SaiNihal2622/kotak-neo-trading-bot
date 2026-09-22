"""Smoke test for atomic_judgments wiring into quant_service brain."""
import sys, os
sys.path.insert(0, '.')
sys.path.insert(0, 'scripts')

import quant_service as qs

# Test _extract_compact_state with realistic context
sample_ctx = {
    'paper': {'cash': 110347, 'positions': {'NIFTY_23650_CE': {}, 'BANKNIFTY_56100_PE': {}}, 'realized_pnl': 10347},
    'chains_summary': {
        'NIFTY': {'spot': 23456.78, 'atm_strike': 23450, 'options': [{'strike': 23450, 'opt_type': 'CE', 'bid': 100.5, 'ask': 101.0}]},
        'BANKNIFTY': {'spot': 51234, 'atm_strike': 51200, 'options': []},
    },
    'alpha': {'regime': {'adx': 22.5}},
    'candles': {
        'NIFTY': {'bar_5m': {'o': 23400, 'h': 23480, 'l': 23380, 'c': 23456.78, 'n_ticks': 312}},
    },
    'oi_changes': {'NIFTY': [{'delta_pct': -1.5}]},
}
compact = qs._extract_compact_state(sample_ctx)
print("Extracted state:")
for k, v in compact.items():
    print(f"  {k}: {v}")
print()
print("Format state string:")
from kotak_bot.signals.atomic_judgments import format_state_for_judgments
state_str = format_state_for_judgments(compact)
print(f"  {state_str}")
print(f"  length: {len(state_str)} chars (target: <600)")

# Test the user prompt + system prompt
from kotak_bot.signals.atomic_judgments import build_judgement_user_prompt, JUDGE_SYSTEM_PROMPT
user_prompt = build_judgement_user_prompt(state_str)
print()
print("System prompt:")
print(f"  {JUDGE_SYSTEM_PROMPT[:120]}...")
print()
print("User prompt (first 400 chars):")
print(f"  {user_prompt[:400]}...")

# Test the legacy decision conversion
from kotak_bot.signals.atomic_judgments import judge_and_aggregate, aggregator_to_legacy_decision
fake_response = '{"regime":"ranging","direction":"neutral","toxic_flow":"low","liquidity_stressed":"low","quote_environment":"favorable","inventory_pressure":"none"}'
judged = judge_and_aggregate({}, fake_response)
if judged:
    legacy = aggregator_to_legacy_decision(judged, plan_qty=75)
    print()
    print("Legacy decision (clean state, APPROVE expected):")
    for k, v in legacy.items():
        v_str = str(v)[:200].encode('ascii', 'replace').decode('ascii')
        print(f"  {k}: {v_str}")
