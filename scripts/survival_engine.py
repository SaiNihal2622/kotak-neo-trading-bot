"""Survival engine — the "earn or die" layer for the trading brain.

Inspired by the autonomous-agent survival constraint (JustinGuese's
kubernetes-docker-autonomous-trading-agent, Hushmonday's
autonomous-trading-agent): the agent's PRIMARY metric is survival, not
maximizing P&L. Zero balance = termination. Only a fraction of realized
profit is redeployable; the rest is banked and locked out of new
positions. Kill switches are human-reset-only.

Why this matters for THIS system: the brain is fully autonomous and
self-learning. Without a survival layer it can, in principle, keep
trading after a drawdown and blow up the account. This module makes
"stay alive" a hard, deterministic constraint the LLM cannot override --
the same philosophy as the existing circuit breakers, but for the
capital itself.

Mechanics (all deterministic, none left to model judgment):
- DEPLOYABLE = starting_capital + 40% of realized profit (40/60 split).
  The other 60% of profit is BANKED and locked out of new positions.
- SURVIVAL FLOOR = a hard equity floor. If equity < floor, the engine
  returns survival_mode=True and the brain must not open new positions.
- KILL SWITCH = once tripped (e.g. daily loss cap), only a human editing
  the state file can reset it. The LLM cannot re-arm itself.

State: data_cache/survival_state.json (atomic writes).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
STATE_PATH = DATA / 'survival_state.json'

# ---- policy (editable by operator in the state file) ----
DEFAULT_POLICY = {
    'starting_capital': 100_000.0,
    'redeploy_ratio': 0.40,          # 40% of realized profit redeployable
    'survival_floor_pct': 0.50,      # stop new positions if equity < 50% of start
    'daily_loss_cap_pct': 0.03,       # 3% daily loss trips the kill switch
    'kill_switch': False,             # human-reset-only
    'kill_switch_reason': '',
}

_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _read_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {'policy': dict(DEFAULT_POLICY), 'banked': 0.0,
                'realized_total': 0.0, 'peak_equity': None,
                'last_update': None, 'kill_switch_tripped_at': None}
    try:
        with open(STATE_PATH, 'r', encoding='utf-8-sig') as fh:
            return json.load(fh)
    except Exception:
        return {'policy': dict(DEFAULT_POLICY), 'banked': 0.0,
                'realized_total': 0.0, 'peak_equity': None,
                'last_update': None, 'kill_switch_tripped_at': None}


def _write_state(state: Dict[str, Any]) -> None:
    state['last_update'] = _now_iso()
    # atomic write
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding='utf-8')
    os.replace(tmp, STATE_PATH)


def _equity(cash: float, realized: float) -> float:
    """Current equity = cash on hand + realized P&L."""
    return float(cash) + float(realized)


def update(realized_pnl: float, cash: float) -> Dict[str, Any]:
    """Recompute banked/deployable from the latest realized P&L.

    Call this after every trade close. Returns the updated state.
    """
    with _LOCK:
        st = _read_state()
        pol = st['policy']
        start = float(pol.get('starting_capital', 100_000.0))

        # Realized profit above the starting capital is split 40/60.
        profit = float(realized_pnl)
        if profit > 0:
            st['banked'] = round(profit * (1 - float(pol.get('redeploy_ratio', 0.40))), 2)
        else:
            st['banked'] = 0.0
        st['realized_total'] = round(profit, 2)

        eq = _equity(cash, realized_pnl)
        if st.get('peak_equity') is None or eq > st['peak_equity']:
            st['peak_equity'] = round(eq, 2)

        # Survival floor: stop new positions if equity < floor% of start.
        floor = start * float(pol.get('survival_floor_pct', 0.50))
        st['survival_mode'] = eq < floor
        st['survival_floor'] = round(floor, 2)
        st['equity'] = round(eq, 2)
        st['deployable'] = round(start + profit * float(pol.get('redeploy_ratio', 0.40)), 2)

        # Daily loss cap -> kill switch (human-reset-only).
        if not pol.get('kill_switch'):
            daily = _daily_loss_pct()
            if daily is not None and daily <= -float(pol.get('daily_loss_cap_pct', 0.03)):
                pol['kill_switch'] = True
                pol['kill_switch_reason'] = f"daily loss {daily:.1%} <= -{pol.get('daily_loss_cap_pct')}"
                st['kill_switch_tripped_at'] = _now_iso()

        _write_state(st)
        return st


def _daily_loss_pct() -> Optional[float]:
    """Today's realized P&L as a % of starting capital (None if unknown)."""
    try:
        import sys
        sys.path.insert(0, str(ROOT / 'scripts'))
        from performance_tracker import get_daily_summary
        from datetime import date
        s = get_daily_summary(date.today())
        pnl = float(s.get('realized_pnl', 0.0))
        start = float(_read_state()['policy'].get('starting_capital', 100_000.0))
        return pnl / start if start else None
    except Exception:
        return None


def can_open_position(cash: float, realized: float) -> Dict[str, Any]:
    """Decision gate: may the brain open a NEW position?

    Returns {allowed: bool, reason: str, state: {...}}.
    """
    st = _read_state()
    pol = st['policy']
    eq = _equity(cash, realized)

    if pol.get('kill_switch'):
        return {'allowed': False,
                'reason': f"KILL SWITCH tripped: {pol.get('kill_switch_reason')}. Human must reset.",
                'state': st}
    if st.get('survival_mode'):
        return {'allowed': False,
                'reason': f"SURVIVAL MODE: equity {eq:.0f} < floor {st.get('survival_floor')}. No new positions.",
                'state': st}
    return {'allowed': True, 'reason': 'ok', 'state': st}


def reset_kill_switch(reason: str = 'operator reset') -> Dict[str, Any]:
    """Human-only reset of the kill switch. The LLM must never call this."""
    with _LOCK:
        st = _read_state()
        st['policy']['kill_switch'] = False
        st['policy']['kill_switch_reason'] = ''
        st['kill_switch_tripped_at'] = None
        st['last_reset'] = {'by': 'operator', 'reason': reason, 'ts': _now_iso()}
        _write_state(st)
        return st


def snapshot() -> Dict[str, Any]:
    return _read_state()
