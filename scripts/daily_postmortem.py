#!/usr/bin/env python
"""Daily post-mortem — runs at 15:35 IST Mon-Fri.

Generates a comprehensive daily report:
  - Market movement (NIFTY, BANKNIFTY, SENSEX, MIDCPNIFTY, VIX)
  - Bot state (P&L, positions, fills)
  - Brain activity (decisions, OPENs attempted, signals missed)
  - Bug audit (any new errors in stderr log)
  - Tomorrow's plan (based on thesis + global cues)

Sends to Telegram via telegram_alerter. Runs as part of the in-process
scheduler in quant_service.py (replaces the old kotak-bot-eod-report cron).
"""
import sys, os, json, traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
import yfinance as yf

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DCACHE = ROOT / 'data_cache'
IST = timezone(timedelta(hours=5, minutes=30))


def get_market_move():
    """Get NIFTY/BANKNIFTY/SENSEX/VIX day change from prev close."""
    out = {}
    syms = [
        ('NIFTY', '^NSEI'),
        ('BANKNIFTY', '^NSEBANK'),
        ('SENSEX', '^BSESN'),
        ('MIDCPNIFTY', '^NSEMDCP50'),
        ('VIX', '^INDIAVIX'),
    ]
    for name, sym in syms:
        try:
            t = yf.Ticker(sym)
            h = t.history(period='2d', interval='1d')
            if len(h) >= 2:
                p = float(h['Close'].iloc[-2])
                c = float(h['Close'].iloc[-1])
                out[name] = (c - p) / p * 100
            else:
                out[name] = None
        except Exception:
            out[name] = None
    return out


def get_bot_state():
    """Get current bot state from paper_state + liveness."""
    try:
        ps = json.loads((DCACHE / 'paper_state.json').read_text(encoding='utf-8'))
        return {
            'cash': ps.get('cash', 0),
            'realized_pnl': ps.get('realized_pnl', 0) or 0,
            'positions': len(ps.get('positions', {})),
            'today_fills': len(ps.get('today_fills', [])),
        }
    except Exception as e:
        return {'error': str(e)}


def get_brain_activity():
    """Get today's brain decisions from quant_service_decisions.jsonl."""
    out = {'total': 0, 'hold': 0, 'open': 0, 'close': 0, 'open_attempts': []}
    log = DCACHE / 'quant_service_decisions.jsonl'
    if not log.exists():
        return out
    today = datetime.now(IST).strftime('%Y-%m-%d')
    for line in log.read_text(encoding='utf-8', errors='ignore').splitlines():
        if not line.startswith('{') or f'"{today}' not in line[:50]:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        t = d.get('decision', {}).get('type', '?')
        out['total'] += 1
        if t == 'HOLD':
            out['hold'] += 1
        elif t == 'OPEN':
            out['open'] += 1
            legs = d.get('decision', {}).get('legs', [])
            leg_str = ' '.join(f"{l.get('side','')[:1]}{l.get('strike','')}{l.get('opt_type','')}x{l.get('qty',0)}" for l in legs)
            out['open_attempts'].append({
                'ts': d.get('ts'),
                'underlying': d.get('decision', {}).get('underlying'),
                'strategy': d.get('decision', {}).get('strategy'),
                'legs': leg_str,
            })
        elif t == 'CLOSE':
            out['close'] += 1
    return out


def get_quant_actions():
    """Get today's quant_actions.json history."""
    out = []
    log = DCACHE / 'quant_actions.json'
    if log.exists():
        try:
            q = json.loads(log.read_text(encoding='utf-8'))
            out.append({
                'ts': q.get('ts'),
                'consumed': q.get('consumed'),
                'placed_legs': q.get('placed_legs'),
                'note': q.get('note', ''),
            })
        except Exception:
            pass
    failed_log = DCACHE / 'quant_actions.failed.json'
    if failed_log.exists():
        try:
            f = json.loads(failed_log.read_text(encoding='utf-8'))
            if isinstance(f, list):
                for entry in f[-3:]:
                    out.append({
                        'ts': entry.get('ts'),
                        'consumed': entry.get('consumed'),
                        'placed_legs': entry.get('placed_legs'),
                        'failed': entry.get('failed'),
                        'failed_reason': entry.get('failed_reason', ''),
                    })
        except Exception:
            pass
    return out


def get_lint_state():
    """Run lint_no_shadowing + production_audit silently."""
    import subprocess
    out = {'shadow_lint': None, 'production_audit': None}
    try:
        r = subprocess.run(
            ['python', 'scripts/lint_no_shadowing.py'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30
        )
        out['shadow_lint'] = r.returncode == 0
    except Exception as e:
        out['shadow_lint'] = f'err: {e}'
    try:
        r = subprocess.run(
            ['python', 'scripts/production_audit.py'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30
        )
        out['production_audit'] = r.returncode == 0
    except Exception as e:
        out['production_audit'] = f'err: {e}'
    return out


def get_thesis():
    """Get the latest thesis."""
    try:
        t = json.loads((DCACHE / 'thesis' / 'latest.json').read_text(encoding='utf-8'))
        return {
            'regime': t.get('regime'),
            'bias': t.get('bias'),
            'confidence': t.get('confidence'),
            'updated': t.get('ist_time'),
        }
    except Exception:
        return {}


def send_telegram(msg: str) -> bool:
    """Send the report to Telegram."""
    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        # Load env from credentials.env (in case os.environ is empty)
        cred_path = ROOT / 'config' / 'credentials.env'
        for line in cred_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
        from telegram_alerter import get_alerter
        a = get_alerter()
        if not a or not a.enabled:
            print('alerter disabled')
            return False
        return a.send(msg)
    except Exception as e:
        print(f'telegram send failed: {e}')
        return False


def main():
    try:
        today = datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')
        market = get_market_move()
        bot = get_bot_state()
        brain = get_brain_activity()
        actions = get_quant_actions()
        lint = get_lint_state()
        thesis = get_thesis()

        # Format market moves
        def fmt_move(name, val):
            if val is None:
                return f'{name}: n/a'
            sign = '+' if val > 0 else ''
            return f'{name}: {sign}{val:.2f}%'

        moves = '\n'.join(f'  {fmt_move(n, v)}' for n, v in market.items())

        # Format brain activity
        opens = brain.get('open_attempts', [])
        open_lines = []
        for o in opens:
            ts = (o.get('ts') or '')[-15:-9]  # extract HH:MM:SS
            open_lines.append(f'    {ts} {o.get("underlying")} {o.get("strategy")} {o.get("legs")}')
        opens_str = '\n'.join(open_lines) if open_lines else '    none'

        # Format actions
        action_lines = []
        for a in actions:
            status = 'OK' if a.get('consumed') and a.get('placed_legs', 0) > 0 else (
                'CONSUMED_NO_FILL' if a.get('consumed') else 'PENDING'
            )
            action_lines.append(
                f'    {a.get("ts", "?")[-15:-9]} | {status} | placed_legs={a.get("placed_legs", 0)} | {a.get("note", "")[:60]}'
            )
        actions_str = '\n'.join(action_lines) if action_lines else '    no quant_actions today'

        # Lint
        lint_str = ''
        if lint.get('shadow_lint') is True:
            lint_str += 'shadow: PASS; '
        elif lint.get('shadow_lint') is False:
            lint_str += 'shadow: FAIL; '
        if lint.get('production_audit') is True:
            lint_str += 'audit: PASS'
        elif lint.get('production_audit') is False:
            lint_str += 'audit: FAIL'
        else:
            lint_str += f"audit: {lint.get('production_audit')}"

        # Thesis
        thesis_str = ''
        if thesis:
            thesis_str = f"{thesis.get('regime', '?')} | bias {thesis.get('bias', '?')} | conf {thesis.get('confidence', '?')} (updated {thesis.get('updated', '?')})"

        msg = f"""[Mavis EOD 15:35] Daily Post-mortem {today}

MARKET MOVE (prev close -> today)
{moves}

BOT STATE
  cash: Rs.{bot.get('cash', 0):,.0f}
  realized_pnl: Rs.{bot.get('realized_pnl', 0):,.0f}
  open positions: {bot.get('positions', 0)}
  today fills: {bot.get('today_fills', 0)}

BRAIN ACTIVITY
  total decisions: {brain.get('total', 0)} ({brain.get('hold', 0)} HOLD, {brain.get('open', 0)} OPEN, {brain.get('close', 0)} CLOSE)
  OPEN attempts:
{opens_str}

QUANT ACTIONS
{actions_str}

LINT
  {lint_str}

THESIS (latest)
  {thesis_str or 'n/a'}

REVIEW ITEMS (for nightly-improvement @23:00)
  - Did the brain HOLD on a real signal? (overly conservative?)
  - Did any OPEN get rejected by a system policy vs the brain's choice?
  - Are the in-process schedulers firing on time?
"""
        if send_telegram(msg):
            print('post-mortem sent to Telegram')
        else:
            print('post-mortem NOT sent')

        # Also write to log file for archival
        log_path = ROOT / 'Logs' / 'daily_postmortem.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as f:
            f.write(f'\n\n=== {today} ===\n{msg}\n')

    except Exception as e:
        err = f'POSTMORTEM-ERR: {e}\n{traceback.format_exc()}'
        print(err)
        send_telegram(f'[Mavis EOD-ERR] {e}')


if __name__ == '__main__':
    main()
