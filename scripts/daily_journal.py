"""Daily P&L + fills journal (2026-10-13).

Builds a per-day, human-readable journal of what the system ACTUALLY did:
real fills (from paper_state orders), realized P&L, and - crucially - the
SIGNALS THE SYSTEM BLOCKED (rejected OPENs, suppressed actions, 14:30 gate,
survival gate). The blocked-signal transparency is what turns a "template"
(which mouths HOLD and shows nothing) into an accountable system.

Writes:
  Quant/Daily/YYYY-MM-DD.md     - the day's journal
  data_cache/daily_journal.json - machine-readable latest journal

All data from the system's own state files; no external accounts.
Run from the brain's EOD scheduler (15:45) or manually:
    .venv\\Scripts\\python.exe scripts/daily_journal.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
DECISIONS = DATA / 'quant_service_decisions.jsonl'
REJECTIONS = DATA / 'order_rejections.jsonl'
QUANT_LOG = DATA / 'quant_service.log'

VAULT = Path(os.environ.get('OBSIDIAN_VAULT_PATH',
                            r'C:\Users\saini\Documents\Obsidian Vault'))
DAILY_DIR = VAULT / 'Quant' / 'Daily'
OUT = DATA / 'daily_journal.json'


def _read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _filename_escape(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '', s)


def _service_state(svc: str) -> str:
    try:
        out = subprocess.run(['sc', 'query', svc], capture_output=True, text=True,
                             timeout=15).stdout
        for line in out.splitlines():
            if 'STATE' in line:
                return line.split(':', 1)[1].strip().split()[-1]
    except Exception:
        pass
    return 'UNKNOWN'


def _realized_pnl() -> float:
    """Realized P&L = survival realized_total, falling back to paper realized."""
    surv = _read_json(DATA / 'survival_state.json', {})
    r = float(surv.get('realized_total') or 0)
    if r == 0:
        r = float((_read_json(DATA / 'paper_state.json', {})).get('realized_pnl') or 0)
    return r


def _today_infos() -> dict:
    """Real fills + today decisions + blocked signals, split by today vs all."""
    today = date.today().isoformat()

    # Real fills from paper_state orders filled_at today
    ps = _read_json(DATA / 'paper_state.json', {})
    orders = ps.get('orders', {}) if isinstance(ps.get('orders'), dict) else {}
    fills_today = []
    for oid, o in orders.items():
        fa = o.get('filled_at', '')
        if fa and fa.startswith(today):
            fills_today.append({
                'ts': fa, 'symbol': str(o.get('symbol', '')),
                'side': str(o.get('side', '')), 'qty': o.get('filled_qty', 0),
                'price': o.get('avg_fill_price', 0.0),
                'tag': str(o.get('tag', ''))[:40],
            })

    # Decisions today (OPEN/CLOSE/HOLD counts)
    opens = closes = holds = 0
    open_reasons = []
    if DECISIONS.exists():
        with open(DECISIONS, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = rec.get('ts', '')
                if not ts or not ts.startswith(today):
                    continue
                dec = rec.get('decision', {})
                t = dec.get('type', '?') if isinstance(dec, dict) else '?'
                if t == 'OPEN':
                    opens += 1
                    if len(open_reasons) < 3:
                        open_reasons.append((dec.get('strategy', '?'),
                                             (dec.get('rationale') or '')[:90]))
                elif t == 'CLOSE':
                    closes += 1
                elif t == 'HOLD':
                    holds += 1

    # Blocked signals from the log (transparency: WHY nothing filled).
    blocked = []
    if QUANT_LOG.exists():
        raw = subprocess.run(['grep', '-a', 'ACTION-SUPPRESSED', str(QUANT_LOG)],
                             capture_output=True, text=True).stdout
        raw2 = subprocess.run(['grep', '-a', 'BRIDGE].*rejected', str(QUANT_LOG)],
                              capture_output=True, text=True).stdout
        raw = raw + "\n" + raw2
        seen = 0
        for line in raw.splitlines():
            m = re.match(r'^\[(2026-\d\d-\d\d)T(\d\d):(\d\d):\d\d\+.*?\]\s*(.*)$', line.strip())
            if m and m.group(1) == today:
                body = m.group(4).strip()
                if "ACTION-SUPPRESSED" in body or "rejected" in body:
                    blocked.append(f"{m.group(2)}:{m.group(3)} :: {body[:100]}")
                seen += 1
                if seen >= 12:
                    break
    # Rejections file fallback
    rej_today = []
    if REJECTIONS.exists():
        for line in REJECTIONS.read_text(encoding='utf-8').strip().splitlines():
            try:
                rec = json.loads(line)
                if str(rec.get('ts', '')).startswith(today):
                    rej_today.append(str(rec)[:110])
                    if len(rej_today) >= 8:
                        break
            except json.JSONDecodeError:
                continue

    return {
        'date': today,
        'fills_today': fills_today,
        'n_fills': len(fills_today),
        'opens': opens, 'closes': closes, 'holds': holds,
        'open_reasons': open_reasons,
        'blocked': blocked,
        'rejections': rej_today,
    }


def build() -> Optional[Path]:
    info = _today_infos()
    realized = _realized_pnl()
    body = [
        f"# Trading Day {info['date']}",
        "",
        f"- Realized P&L: **₹{realized:,.2f}**",
        f"- Decisions: **{info['opens']} OPEN / {info['closes']} CLOSE / {info['holds']} HOLD**",
        f"- Real fills today: **{info['n_fills']}**",
        f"- Cash: ₹{(_read_json(DATA / 'paper_state.json', {})).get('cash', 0):,.0f} / positions: "
        f"{len((_read_json(DATA / 'paper_state.json', {})).get('positions', {}) or {})}",
        "",
    ]
    # Fills section
    body += ["## Real fills", ""]
    if info['fills_today']:
        for f in info['fills_today']:
            body.append(f"- **{f['ts'][11:16]}** {f['side']} {f['symbol']} qty {f['qty']} @ ₹{f['price']}")
    else:
        body.append("- None (no fills today).")
    body += [""]

    # Blocked signals (the transparency)
    body += ["## Signals attempted but blocked", ""]
    if info['blocked']:
        for b in info['blocked']:
            body.append(f"- {b}")
    elif info['rejections']:
        for r_ in info['rejections']:
            body.append(f"- {r_}")
    else:
        # no explicit block lines: report the reason from open-reasons / HOLD
        if info['open_reasons']:
            for strat, reason in info['open_reasons']:
                body.append(f"- OPEN intent ({strat}): {reason}")
        else:
            body.append("- No OPEN attempted. Brain held (see decisions log).")
    body += [""]

    # Strategy-library routing summary
    body += ["## Strategy routing today", ""]
    try:
        if QUANT_LOG.exists():
            raw = subprocess.run(['grep', '-a', 'STRATEGY-LIBRARY: selected',
                                  str(QUANT_LOG)], capture_output=True, text=True).stdout
            from collections import Counter
            sel = Counter()
            for line in raw.splitlines():
                m = re.search(r'\[(2026-\d\d-\d\d)T.*selected (\S+?) \(edge', line)
                if m and m.group(1) == info['date']:
                    sel[m.group(2)] += 1
            if sel:
                for s, c in sel.most_common():
                    body.append(f"- {s}: {c}")
            else:
                body.append("- None (no strategy selected).")
    except Exception:
        pass
    body += [""]

    # Health
    body += ["## System health", ""]
    for svc in ('KotakBotPaper', 'KotakQuantService', 'KotakCoreAPI',
                'KotakExecGateway', 'KotakDashboard', 'KotakBrainBridge'):
        body.append(f"- {svc}: **{_service_state(svc)}**")
    body += ["", f"_Journaled {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}_"]

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    path = DAILY_DIR / f"{info['date']}.md"
    path.write_text("\n".join(body), encoding='utf-8')
    try:
        OUT.write_text(json.dumps({**info, 'realized_pnl': realized,
                                   'journal': str(path)}, indent=2), encoding='utf-8')
    except Exception:
        pass
    return path


def main() -> int:
    try:
        p = build()
        print(f"daily journal: {p}")
        return 0
    except Exception as e:
        print(f"daily_journal error: {e}")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
