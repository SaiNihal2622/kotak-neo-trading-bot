"""Weekly market wrap + Monday pre-market readiness report.

Writes two things into the Obsidian vault (credential-free, no external
accounts):

  Quant/_Weekly.md          - week's realized P&L + trade count + notes
  Quant/Readiness/2026-XX-XX.md - Monday pre-market readiness checklist

All data comes from the system's own state files. Run from the brain's
scheduler (committed before Monday open) or manually:
    .venv\\Scripts\\python.exe scripts/market_wrap.py
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
DECISIONS = DATA / 'quant_service_decisions.jsonl'

VAULT = Path(os.environ.get('OBSIDIAN_VAULT_PATH',
                            r'C:\Users\saini\Documents\Obsidian Vault'))
QUANT_DIR = VAULT / 'Quant'
READY_DIR = QUANT_DIR / 'Readiness'


def _read_trades_week() -> list:
    """All CLOSE/OPEN decisions from the last 7 days."""
    out = []
    if not DECISIONS.exists():
        return out
    cutoff = (date.today() - timedelta(days=7)).isoformat()
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
            if not ts or ts[:10] < cutoff:
                continue
            dec = rec.get('decision', {})
            if isinstance(dec, dict) and dec.get('type') in ('OPEN', 'CLOSE'):
                out.append({'ts': ts, 'type': dec['type'],
                            'strategy': dec.get('strategy', ''),
                            'note': dec.get('rationale', '') or dec.get('note', '') or ''})
    return out


def _read_survival() -> dict:
    try:
        return json.loads((DATA / 'survival_state.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def _service_state(svc: str) -> str:
    import subprocess
    try:
        out = subprocess.run(['sc', 'query', svc], capture_output=True, text=True,
                             timeout=15).stdout
        for line in out.splitlines():
            if 'STATE' in line:
                return line.split(':', 1)[1].strip().split()[-1]
    except Exception:
        pass
    return 'UNKNOWN'


def _write(note_dir: Path, name: str, content: str) -> Path:
    note_dir.mkdir(parents=True, exist_ok=True)
    p = note_dir / name
    p.write_text(content, encoding='utf-8')
    return p


def build_weekly() -> Optional[Path]:
    trades = _read_trades_week()
    surv = _read_survival()
    realized = float(surv.get('realized_total', 0) or 0)
    banked = float(surv.get('banked', 0) or 0)
    n_open = sum(1 for t in trades if t['type'] == 'OPEN')
    n_close = sum(1 for t in trades if t['type'] == 'CLOSE')

    body = [
        "# Weekly Market Wrap", "",
        f"- Week ending: **{date.today().isoformat()}**",
        f"- Trades this week: **{n_open} OPEN / {n_close} CLOSE**",
        f"- Realized P&L: **₹{realized:,.2f}**",
        f"- Banked (60% of profit): **₹{banked:,.2f}**",
        f"- Survival mode: **{'ON' if surv.get('survival_mode') else 'off'}**",
        "",
        "## Trade log", "",
    ]
    if trades:
        for t in trades[-25:]:
            strat = f" ({t['strategy']})" if t['strategy'] else ''
            note = (t['note'] or '')[:120]
            body.append(f"- **{t['ts'][:16]}** {t['type']}{strat} — {note}")
    else:
        body.append("- No trades this week.")
    body.append("")
    body.append("## System health")
    for svc in ('KotakBotPaper', 'KotakQuantService', 'KotakCoreAPI',
                'KotakExecGateway', 'KotakDashboard', 'KotakBrainBridge'):
        body.append(f"- {svc}: **{_service_state(svc)}**")
    body.append("")
    return _write(QUANT_DIR, '_Weekly.md', "\n".join(body))


def build_premarket_readiness() -> Optional[Path]:
    """Monday pre-market readiness checklist (credential-free checks)."""
    today = date.today().isoformat()
    checks = []
    ok = True
    for svc in ('KotakBotPaper', 'KotakQuantService', 'KotakCoreAPI',
                'KotakExecGateway', 'KotakDashboard', 'KotakBrainBridge'):
        st = _service_state(svc)
        good = st == 'RUNNING'
        ok = ok and good
        checks.append((f"{svc}", st, good))

    body = [
        "# Pre-market Readiness", "",
        f"- Date: **{today}**",
        f"- Overall: **{'READY' if ok else 'ACTION NEEDED'}**",
        "",
        "## Service checks", "",
    ]
    for name, st, good in checks:
        mark = "✅" if good else "❌"
        body.append(f"- {mark} {name}: {st}")
    body.append("")

    # Brain / LLM check
    try:
        st = json.loads((DATA / 'quant_service_state.json').read_text(encoding='utf-8-sig'))
        llm_ok = not (st.get('llm_health') or {}).get('open', True)
        body.append(f"- {'✅' if llm_ok else '❌'} LLM circuit: {'healthy' if llm_ok else 'OPEN - brain cannot think'}")
    except Exception:
        pass
    body.append("")
    body.append("## Next trading windows (IST)")
    body.append("- **Monday 09:15 open** — brain starts live paper decisions")
    body.append("- EOD 15:30 — force-square + day close")
    body.append("")
    return _write(READY_DIR, f"{today}.md", "\n".join(body))


def main() -> int:
    try:
        w = build_weekly()
        r = build_premarket_readiness()
        print(f"weekly: {w}")
        print(f"readiness: {r}")
        return 0
    except Exception as e:
        print(f"market_wrap error: {e}")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
