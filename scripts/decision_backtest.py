"""Decision backtest — replay decisions.jsonl against actual outcomes
to compute per-strategy performance and validate proposed prompt changes.

Used by:
  - The nightly self-review (23:00) to score proposed prompt_additions
    against historical decisions
  - Manual backtest via `python scripts/decision_backtest.py [--validate-prompt "..."]`

Outputs:
  - data_cache/performance/strategy_backtest.json (per-strategy metrics)
  - data_cache/performance/prompt_validation.json (if --validate-prompt)

Metrics per strategy:
  - n_trades, wins, losses, breakevens, win_rate
  - total_pnl, avg_win, avg_loss, profit_factor
  - max_drawdown, sharpe_like (mean/std of per-trade P&L)
  - avg_hold_minutes, best_trade, worst_trade
  - edge_decay: is the strategy's edge stable or decaying?
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
PERF = DATA / 'performance'
PERF.mkdir(parents=True, exist_ok=True)
DECISIONS_PATH = PERF / 'decisions.jsonl'
STRATEGY_BACKTEST_PATH = PERF / 'strategy_backtest.json'
PROMPT_VALIDATION_PATH = PERF / 'prompt_validation.json'


def _percentile(values: list, p: float) -> float:
    if not values:
        return 0
    sv = sorted(values)
    idx = int(p * (len(sv) - 1))
    return sv[idx]


def backtest_strategy(strategy: str, decisions: list) -> dict:
    """Compute performance metrics for one strategy from closed decisions."""
    closed = [d for d in decisions if d.get('status') == 'closed' and (d.get('tags', {}).get('strategy') == strategy or d.get('strategy') == strategy)]
    if not closed:
        # Try by tags.legs[].strategy or just decision.strategy field
        closed = [d for d in decisions if d.get('status') == 'closed' and d.get('strategy') == strategy]
    if not closed:
        return {'strategy': strategy, 'n_trades': 0}
    pnls = [d.get('pnl', 0) or 0 for d in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    bes = [p for p in pnls if p == 0]
    total = sum(pnls)
    avg = statistics.mean(pnls) if pnls else 0
    std = statistics.stdev(pnls) if len(pnls) > 1 else 0
    sharpe_like = (avg / std * math.sqrt(252)) if std > 0 else 0  # annualized-ish
    # Max drawdown from cumulative
    cum, peak, max_dd = 0, 0, 0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    # Hold time
    hold_times = []
    for d in closed:
        try:
            t1 = datetime.fromisoformat((d.get('ts') or '').replace('Z', '+00:00'))
            t2 = datetime.fromisoformat((d.get('close_ts') or '').replace('Z', '+00:00'))
            hold_times.append((t2 - t1).total_seconds() / 60)
        except Exception:
            pass
    # Edge decay: compare first half vs second half win rate
    if len(closed) >= 6:
        half = len(closed) // 2
        wr_first = sum(1 for d in closed[:half] if (d.get('pnl', 0) or 0) > 0) / half
        wr_second = sum(1 for d in closed[half:] if (d.get('pnl', 0) or 0) > 0) / (len(closed) - half)
        edge_decay = wr_second - wr_first  # negative = decaying
    else:
        edge_decay = 0
    return {
        'strategy': strategy,
        'n_trades': len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'breakevens': len(bes),
        'win_rate': round(len(wins) / len(closed), 4) if closed else 0,
        'total_pnl': round(total, 2),
        'avg_pnl': round(avg, 2),
        'avg_win': round(statistics.mean(wins), 2) if wins else 0,
        'avg_loss': round(statistics.mean(losses), 2) if losses else 0,
        'profit_factor': round(sum(wins) / abs(sum(losses)), 2) if losses else float('inf') if wins else 0,
        'max_dd': round(max_dd, 2),
        'sharpe_like': round(sharpe_like, 2),
        'avg_hold_minutes': round(statistics.mean(hold_times), 1) if hold_times else None,
        'best_trade': round(max(pnls), 2) if pnls else 0,
        'worst_trade': round(min(pnls), 2) if pnls else 0,
        'edge_decay_wr_delta': round(edge_decay, 4),
    }


def replay_all_strategies() -> dict:
    """Replay all decisions and compute per-strategy backtest metrics."""
    if not DECISIONS_PATH.exists():
        return {'ts': datetime.now().isoformat(timespec='seconds'), 'strategies': {}}
    decisions = []
    for line in DECISIONS_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
        try:
            decisions.append(json.loads(line))
        except Exception:
            continue
    # Collect unique strategies
    strategies = set()
    for d in decisions:
        s = d.get('strategy') or (d.get('tags', {}) or {}).get('strategy')
        if s:
            strategies.add(s)
    out = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'n_total_decisions': len(decisions),
        'n_closed': sum(1 for d in decisions if d.get('status') == 'closed'),
        'strategies': {},
    }
    for s in sorted(strategies):
        out['strategies'][s] = backtest_strategy(s, decisions)
    # Persist
    try:
        STRATEGY_BACKTEST_PATH.write_text(json.dumps(out, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass
    return out


def validate_prompt_addition(proposed_addition: str, current_full_prompt: str = "") -> dict:
    """Score a proposed prompt_addition against historical decisions.
    Heuristic: the proposal is GOOD if (a) it references underperforming
    strategies with corrective actions, (b) it doesn't violate hard rules,
    (c) it's specific (not generic advice), (d) it's small in size.

    Returns {score, recommendation, reasons}."""
    score = 0
    reasons = []
    # Load backtest
    bt = {}
    if STRATEGY_BACKTEST_PATH.exists():
        try:
            bt = json.loads(STRATEGY_BACKTEST_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    # Hard rule guard
    forbidden = ['max positions', 'max risk', 'force-square', 'force square', 'live trading', 'go live', 'disable risk', 'no max']
    for f in forbidden:
        if f.lower() in proposed_addition.lower():
            return {
                'score': 0,
                'recommendation': 'reject',
                'reasons': [f'forbidden phrase detected: "{f}" — would violate hard rules'],
            }
    # Length: small is good (50-500 chars)
    if 50 <= len(proposed_addition) <= 500:
        score += 2
        reasons.append('right size (50-500 chars)')
    elif len(proposed_addition) < 50:
        score -= 1
        reasons.append('too short — not enough substance')
    else:
        score -= 2
        reasons.append('too long — likely redundant with existing prompt')
    # Specificity: check for specific numbers, conditions, or actions
    specific_markers = ['when', 'if', 'rsi', 'macd', 'iv', 'vol', 'delta', 'strike', '%', 'lot', 'position size']
    found = sum(1 for m in specific_markers if m in proposed_addition.lower())
    if found >= 3:
        score += 3
        reasons.append(f'specific ({found} condition markers)')
    elif found >= 1:
        score += 1
        reasons.append(f'mildly specific ({found} condition markers)')
    else:
        score -= 1
        reasons.append('vague — no specific conditions or rules')
    # Addresses underperformer
    if bt.get('strategies'):
        underperformers = [s for s, v in bt['strategies'].items() if v.get('n_trades', 0) >= 3 and v.get('win_rate', 0) < 0.4]
        for u in underperformers:
            if u.lower() in proposed_addition.lower():
                score += 3
                reasons.append(f'addresses underperformer: {u} (win rate < 40%)')
                break
    # Score interpretation
    if score >= 5:
        rec = 'apply'
    elif score >= 2:
        rec = 'apply_with_caution'
    elif score >= -1:
        rec = 'test_more'
    else:
        rec = 'skip'
    return {
        'score': score,
        'recommendation': rec,
        'reasons': reasons,
        'n_chars': len(proposed_addition),
        'backtest_strategies': list(bt.get('strategies', {}).keys()),
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate-prompt', type=str, help='Score a proposed prompt_addition against history')
    args = parser.parse_args()
    if args.validate_prompt:
        # First make sure backtest is fresh
        replay_all_strategies()
        result = validate_prompt_addition(args.validate_prompt)
        print(json.dumps(result, indent=2))
        try:
            PROMPT_VALIDATION_PATH.write_text(json.dumps({'ts': datetime.now().isoformat(timespec='seconds'), **result}, indent=2), encoding='utf-8')
        except Exception:
            pass
        return 0
    # Default: replay
    bt = replay_all_strategies()
    print(f"backtest: {bt.get('n_closed', 0)} closed decisions, {len(bt.get('strategies', {}))} strategies")
    for s, v in bt.get('strategies', {}).items():
        if v.get('n_trades', 0) > 0:
            print(f"  {s}: n={v['n_trades']} WR={v['win_rate']*100:.0f}% P&L=Rs.{v['total_pnl']:+,.0f} PF={v['profit_factor']:.2f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
