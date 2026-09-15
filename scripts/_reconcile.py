#!/usr/bin/env python
"""One-shot: manually reconcile stale quant_actions.json (move unfilled actions to failed log)."""
import sys, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DCACHE = ROOT / 'data_cache'
IST = timezone(timedelta(hours=5, minutes=30))

qa_path = DCACHE / 'quant_actions.json'
failed_path = DCACHE / 'quant_actions.failed.json'

if not qa_path.exists():
    print('no quant_actions.json — nothing to reconcile')
    sys.exit(0)

qa = json.loads(qa_path.read_text(encoding='utf-8'))
print(f'BEFORE: ts={qa.get("ts", "?")} consumed={qa.get("consumed")} placed_legs={qa.get("placed_legs")} actions={len(qa.get("actions", []))}')

if qa.get('consumed') and int(qa.get('placed_legs') or 0) == 0 and qa.get('actions'):
    # Move to failed
    qa['failed'] = True
    qa['failed_at'] = datetime.now(IST).isoformat()
    qa['failed_reason'] = 'bot_rejected_or_crash_no_legs_placed'
    history = []
    if failed_path.exists():
        try:
            history = json.loads(failed_path.read_text(encoding='utf-8'))
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []
    history.append(qa)
    history = history[-50:]
    failed_path.write_text(json.dumps(history, indent=2, default=str), encoding='utf-8')
    # Clear live file
    qa_path.write_text(json.dumps({
        "ts": datetime.now(IST).isoformat(),
        "source": "reconciled",
        "actions": [],
        "consumed": True,
        "note": "previous action failed, see quant_actions.failed.json"
    }, indent=2, default=str), encoding='utf-8')
    print(f'AFTER: moved to {failed_path.name}, live file cleared')
else:
    print('no reconciliation needed')

print()
print('=== quant_actions.failed.json (history) ===')
if failed_path.exists():
    fl = json.loads(failed_path.read_text(encoding='utf-8'))
    if isinstance(fl, list):
        for f in fl:
            print(f"  ts={f.get('ts', '?')} actions={len(f.get('actions', []))} placed_legs={f.get('placed_legs')}")
    else:
        print(f'  (not a list: {type(fl).__name__})')
else:
    print('  (no failed history)')
