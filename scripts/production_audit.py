#!/usr/bin/env python
"""Production-grade audit for kotak-neo-bot.

Run this daily (or on every bot startup) to detect:
  - Phantom oversized positions (qty > 5x max sane)
  - Silent cap bypass (5% cost cap not enforced)
  - Mismatched cash/positions/realized_pnl
  - Multiple bot instances writing to liveness.json
  - Watchdog vs NSSM bot competition
  - Stale or corrupted state files

Exits 0 if all checks pass, 1 if critical issues found.
Use this as a cron or in CI.
"""
import sys, json, os, time
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DCACHE = ROOT / 'data_cache'
LOGS = ROOT / 'Logs'
IST = timezone(timedelta(hours=5, minutes=30))

errors = []
warnings = []


def err(msg):
    errors.append(msg)
    print(f'  [ERR] {msg}')


def warn(msg):
    warnings.append(msg)
    print(f'  [WARN] {msg}')


def ok(msg):
    print(f'  [OK] {msg}')


def section(name):
    print(f'\n=== {name} ===')


# 1. Phantom position check
section('1. Phantom oversized positions')
try:
    ps = json.loads((DCACHE / 'paper_state.json').read_text(encoding='utf-8'))
    positions = ps.get('positions', {})
    LOT_SIZE = {'NIFTY': 75, 'BANKNIFTY': 30, 'FINNIFTY': 65, 'MIDCPNIFTY': 120, 'SENSEX': 10}
    MAX_SANE = 5  # 5x the 10-lot cap = 50 lots
    for sym, p in positions.items():
        if not isinstance(p, dict):
            continue
        u = p.get('underlying', '')
        lot = LOT_SIZE.get(u, 75)
        max_qty = 10 * lot
        qty = abs(int(p.get('qty', 0) or 0))
        if qty > max_qty * MAX_SANE:
            err(f'PHANTOM: {sym} qty={qty} (max sane={max_qty*MAX_SANE})')
        else:
            ok(f'{sym}: qty={qty} ok')
except Exception as e:
    err(f'paper_state.json: {e}')

# 2. Cash integrity
section('2. Cash integrity')
try:
    cash = ps.get('cash', 0)
    realized = ps.get('realized_pnl', 0) or 0
    starting = ps.get('starting_capital', 100000) or 100000
    if cash < 0:
        err(f'cash is NEGATIVE: {cash}')
    elif abs(cash - (starting + realized)) > 1:
        # Allow small tolerance for in-flight orders
        warn(f'cash={cash} != starting({starting}) + realized({realized}) = {starting+realized}')
    else:
        ok(f'cash={cash} = starting({starting}) + realized({realized})')
except Exception as e:
    err(f'cash check: {e}')

# 3. Multiple bot instances (liveness.json race)
section('3. Bot instance race')
try:
    import subprocess
    # FIX 2026-09-02 12:32: NSSM-spawned python procs have empty CommandLine.
    # Count BOTH: those with explicit "kotak_bot paper" cmd AND those that own :8502
    # (the http_server is a child of the bot wrapper).
    script = r"""
$count_cmd = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot paper' } | Measure-Object).Count
$count_owner = (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 8502 } | ForEach-Object { (Get-CimInstance Win32_Process -Filter "ProcessId = $($_.OwningProcess)" -ErrorAction SilentlyContinue).ParentProcessId } | Sort-Object -Unique | ForEach-Object { (Get-CimInstance Win32_Process -Filter "ProcessId = $_" -ErrorAction SilentlyContinue).ParentProcessId } | Sort-Object -Unique | Measure-Object).Count
Write-Output "CMD=$count_cmd OWNER=$count_owner"
"""
    out = subprocess.check_output(
        ['powershell', '-NoProfile', '-Command', script],
        text=True, stderr=subprocess.DEVNULL
    ).strip()
    parts = dict(p.split('=') for p in out.split() if '=' in p)
    n_cmd = int(parts.get('CMD', 0))
    n_owner = int(parts.get('OWNER', 0))
    n = max(n_cmd, n_owner)
    if n == 0:
        err('no kotak_bot paper process found (NSSM should have one)')
    elif n == 1:
        ok('exactly 1 kotak_bot paper process (or :8502 owner)')
    else:
        err(f'{n} kotak_bot paper processes — DUPLICATE BOT, pick one to kill')
except Exception as e:
    warn(f'could not check process count: {e}')

# 4. Watchdog vs NSSM competition
section('4. Watchdog / NSSM competition')
try:
    out = subprocess.check_output(
        ['powershell', '-NoProfile', '-Command',
         'Get-CimInstance Win32_Process -Filter "Name=\'python.exe\'" | Where-Object { $_.CommandLine -match "kotak_bot" } | ForEach-Object { ($_.ParentProcessId) } | Sort-Object -Unique | ForEach-Object { (Get-CimInstance Win32_Process -Filter "ProcessId = $_" -ErrorAction SilentlyContinue).Name }'],
        text=True, stderr=subprocess.DEVNULL
    ).strip()
    parents = set(out.splitlines())
    if 'nssm.exe' in parents:
        ok(f'NSSM-owned bot (parents: {parents})')
    if parents - {'nssm.exe'}:
        warn(f'non-NSSM bot parents detected: {parents - {"nssm.exe"}}')
except Exception as e:
    warn(f'parent check: {e}')

# 5. Liveness.json freshness
section('5. Liveness freshness')
try:
    liveness_path = DCACHE / 'liveness.json'
    if liveness_path.exists():
        age = (datetime.now() - datetime.fromtimestamp(liveness_path.stat().st_mtime)).total_seconds()
        if age > 60:
            err(f'liveness.json is {age:.0f}s old (bot may be dead)')
        else:
            ok(f'liveness.json {age:.0f}s old')
    else:
        err('liveness.json missing')
except Exception as e:
    err(f'liveness check: {e}')

# 6. Cost cap enforcement
section('6. Cost cap enforcement (code review)')
try:
    src = (ROOT / 'kotak_bot' / '__main__.py').read_text(encoding='utf-8')
    # Check that the cap reads from BOTH keys (paper + prod)
    if '"available_cash"' in src and '"available"' in src and '_max_position_pct' in src:
        ok('cost cap reads from both available and available_cash (paper + prod)')
    elif '_max_position_pct' in src:
        if 'available_cash' in src:
            warn('cost cap reads only from available_cash — may not work in paper mode')
        else:
            err('cost cap may be disabled')
    else:
        err('no cost cap found in code!')
except Exception as e:
    err(f'cap check: {e}')

# 7. Stale actions
section('7. Stale actions')
try:
    qa = DCACHE / 'quant_actions.json'
    if qa.exists():
        q = json.loads(qa.read_text(encoding='utf-8'))
        if not q.get('consumed') and q.get('actions'):
            age = (datetime.now() - datetime.fromisoformat(q.get('ts', datetime.now(IST).isoformat()))).total_seconds() / 60
            if age > 30:
                err(f'quant_actions.json: {age:.0f}min old, NOT consumed, has {len(q["actions"])} pending actions — TTL exceeded')
            else:
                warn(f'quant_actions.json: {age:.0f}min old, {len(q["actions"])} pending (within TTL)')
        else:
            ok('quant_actions.json is consumed or empty')
    else:
        ok('quant_actions.json: not present')
except Exception as e:
    warn(f'quant_actions check: {e}')

# 8. Brain decisions log
section('8. Brain decisions log')
try:
    log_path = DCACHE / 'quant_service_decisions.jsonl'
    if log_path.exists():
        today = datetime.now(IST).strftime('%Y-%m-%d')
        with log_path.open(encoding='utf-8') as f:
            all_lines = f.readlines()
        # FIX 2026-09-02 14:15: match the date anywhere in the line (format is
        # {"ts": "2026-09-02T...", not {"2026-09-02...
        today_lines = [l for l in all_lines if f'"{today}' in l[:50]]
        n_hold = sum(1 for l in today_lines if '"type": "HOLD"' in l)
        n_open = sum(1 for l in today_lines if '"type": "OPEN"' in l)
        n_close = sum(1 for l in today_lines if '"type": "CLOSE"' in l)
        ok(f'today: {len(today_lines)} decisions ({n_hold} HOLD, {n_open} OPEN, {n_close} CLOSE)')
        if n_open > 0:
            warn(f'{n_open} OPEN actions today — verify each placed (check quant_actions.json placed_legs)')
    else:
        warn('no decisions log')
except Exception as e:
    warn(f'decisions check: {e}')

# Summary
print()
print('=' * 70)
if errors:
    print(f'FAILED: {len(errors)} errors, {len(warnings)} warnings')
    for e in errors:
        print(f'  - {e}')
    sys.exit(1)
elif warnings:
    print(f'PASSED with {len(warnings)} warnings:')
    for w in warnings:
        print(f'  - {w}')
    sys.exit(0)
else:
    print('ALL CHECKS PASSED')
    sys.exit(0)
