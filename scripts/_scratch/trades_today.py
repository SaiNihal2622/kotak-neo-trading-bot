"""Check today's trades."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime('%Y-%m-%d')
print(f'Today: {today} ({datetime.now(IST).strftime("%A")})')

# Trade journal events today
journal_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trade_journal.jsonl')
events_today = {}
fills_today = []
with open(journal_path, encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        ts = rec.get('ts') or rec.get('filled_at') or rec.get('closed_at') or ''
        if ts.startswith(today):
            ev = rec.get('event', 'OTHER')
            events_today[ev] = events_today.get(ev, 0) + 1
            if ev == 'FILL':
                fills_today.append(rec)

print(f'Events today: {events_today}')
print(f'FILL events today: {len(fills_today)}')
for f in fills_today[:10]:
    sym = f.get('symbol', '?')
    side = f.get('side', '?')
    qty = f.get('qty', 0)
    px = f.get('avg_fill_price', 0)
    tag = f.get('tag', '?')
    ts = f.get('ts', '')
    print(f'  {ts} {side} {qty} {sym} @ Rs.{px} tag={tag}')

# Brain daemon's own counters
hb_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\heartbeat_brain_daemon.json')
if hb_path.exists():
    hb = json.loads(hb_path.read_text(encoding='utf-8'))
    counters = hb.get('counters', {})
    print(f'\nBrain daemon counters: cycles={counters.get("cycles")} opens={counters.get("opens")} holds={counters.get("holds")} errors={counters.get("errors")}')

# Brain bridge — actions submitted
quant_actions_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\quant_actions.json')
if quant_actions_path.exists():
    qa = json.loads(quant_actions_path.read_text(encoding='utf-8'))
    actions = qa.get('actions', [])
    today_actions = [a for a in actions if (a.get('ts', '') or '').startswith(today)]
    print(f'\nQuant actions today: {len(today_actions)}')
    for a in today_actions[-10:]:
        print(f'  {a.get("ts", "")} action={a.get("action", "?")} strategy={a.get("strategy", "?")}')

# Quant service log (LLM decisions)
qs_log_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\quant_service.log')
if qs_log_path.exists():
    with open(qs_log_path, encoding='utf-8') as f:
        lines = f.readlines()
    today_lines = [l for l in lines if today in l]
    decisions = [l for l in today_lines if 'LLM-DECISION' in l or 'OPEN' in l or 'HOLD' in l]
    print(f'\nQuant service log lines today: {len(today_lines)}, decision-related: {len(decisions)}')
    for l in decisions[-15:]:
        s = l.strip()
        if len(s) > 250:
            s = s[:250] + '...'
        print(f'  {s}')