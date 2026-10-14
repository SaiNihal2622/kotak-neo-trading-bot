"""Tests for the bridge price-override + notional-cap fixes (2026-10-14).

Two NEW rejection classes surfaced once the old delivery bugs were fixed:
  1. limit_reasonable: the LLM proposes a BUY limit ~50% below the live ask
     (e.g. 34 vs 67) -> preflight rejects -> OPEN never fills.
  2. per_trade_cap: the sizer/LLM emits an oversized leg (Rs.396k on Rs.100k)
     -> preflight rejects.
The bridge now overrides the LLM's guessed limit with the live chain price
(ask for BUY, bid for SELL) and hard-caps each leg's notional to 5% of cash.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT))


def _bridge():
    from system.bridge.brain_bridge import BrainBridge
    return BrainBridge(core_url='http://127.0.0.1:8510',
                       quant_actions_path=ROOT / 'data_cache' / 'quant_actions.json')


def test_chain_price_returns_ask_for_buy(monkeypatch, tmp_path):
    b = _bridge()
    # write a chain file with a known bid/ask
    chain = ROOT / 'data_cache' / 'option_chain_NIFTY.json'
    backup = chain.read_text(encoding='utf-8-sig') if chain.exists() else None
    chain.write_text('{"strikes": {"22050_CE": {"bid": 60.0, "ask": 67.0}}}', encoding='utf-8')
    try:
        assert b._chain_price('NIFTY22OCT2622050CE', 'BUY') == 67.0
        assert b._chain_price('NIFTY22OCT2622050CE', 'SELL') == 60.0
    finally:
        if backup is not None:
            chain.write_text(backup, encoding='utf-8')
        else:
            chain.unlink(missing_ok=True)


def test_chain_price_unknown_returns_none(monkeypatch):
    b = _bridge()
    assert b._chain_price('NIFTY99999CE', 'BUY') is None


def test_cap_leg_notional_reduces_oversized():
    b = _bridge()
    legs = [{'symbol': 'X', 'underlying': 'NIFTY', 'side': 'BUY', 'qty': 750,
             'price': 67.0, 'order_type': 'LIMIT'}]  # 750*67 = 50,250 > 5% of 100k
    out = b._cap_leg_notional(legs, capital=100000.0, max_pct=0.05)
    # 5% of 100k = 5000; even 1 lot (75*67 = 5025) exceeds it -> leg dropped
    assert len(out) == 0
    # a slightly cheaper price that fits 1 lot should be kept
    legs2 = [{'symbol': 'X', 'underlying': 'NIFTY', 'side': 'BUY', 'qty': 750,
              'price': 60.0, 'order_type': 'LIMIT'}]  # 1 lot = 75*60 = 4500 < 5000
    out2 = b._cap_leg_notional(legs2, capital=100000.0, max_pct=0.05)
    assert len(out2) == 1
    assert out2[0]['qty'] == 75  # reduced to 1 lot (4500 <= 5000)


def test_cap_leg_notional_keeps_small():
    b = _bridge()
    legs = [{'symbol': 'X', 'underlying': 'NIFTY', 'side': 'BUY', 'qty': 75,
             'price': 20.0, 'order_type': 'LIMIT'}]  # 75*20 = 1500 < 5000
    out = b._cap_leg_notional(legs, capital=100000.0, max_pct=0.05)
    assert len(out) == 1
    assert out[0]['qty'] == 75


def test_build_plan_legs_uses_live_price(monkeypatch, tmp_path):
    """The LLM's guessed price must be replaced by the live chain ask for BUY."""
    b = _bridge()
    chain = ROOT / 'data_cache' / 'option_chain_NIFTY.json'
    backup = chain.read_text(encoding='utf-8-sig') if chain.exists() else None
    chain.write_text('{"strikes": {"22050_CE": {"bid": 60.0, "ask": 67.0}}}', encoding='utf-8')
    try:
        action = {
            'underlying': 'NIFTY', 'strategy': 'iron_condor',
            'legs': [{'side': 'BUY', 'strike': 22050, 'opt_type': 'CE',
                      'expiry': '2026-10-22', 'qty': 1, 'order_type': 'LIMIT',
                      'price': 34.0}],  # LLM guessed 34, live ask is 67
        }
        legs = b._build_plan_legs(action)
        assert len(legs) == 1
        assert legs[0]['price'] == 67.0  # overridden to live ask
    finally:
        if backup is not None:
            chain.write_text(backup, encoding='utf-8')
        else:
            chain.unlink(missing_ok=True)
