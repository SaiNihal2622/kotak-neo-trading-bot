"""Check actual paper trading status - one-shot helper."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data_cache"

# Load env
for line in (ROOT / "config" / "credentials.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

print("=" * 60)
print("PAPER TRADING STATUS CHECK")
print("=" * 60)

# 1. Trade journal
journal = DATA / "trade_journal.jsonl"
if journal.exists():
    lines = journal.read_text(encoding="utf-8").splitlines()
    print(f"\n=== trade_journal.jsonl: {len(lines)} entries ===")
    for line in lines[-10:]:
        try:
            obj = json.loads(line)
            ts = obj.get("ts", "")[:16]
            action = obj.get("action", "?")
            strat = obj.get("strategy", "?")
            und = obj.get("instrument") or obj.get("underlying") or "?"
            pnl = obj.get("pnl", 0)
            print(f"  {ts}  {action:<10}  {strat:<15}  {und:<12}  pnl={pnl}")
        except Exception:
            pass
else:
    print("\ntrade_journal.jsonl: DOES NOT EXIST (no trades ever recorded)")

# 2. Recent brain decisions
decisions = DATA / "quant_service_decisions.jsonl"
if decisions.exists():
    lines = decisions.read_text(encoding="utf-8").splitlines()
    print(f"\n=== quant_service_decisions.jsonl: {len(lines)} decisions, last 10 ===")
    for line in lines[-10:]:
        try:
            obj = json.loads(line)
            ts = obj.get("ts", "")[:16]
            action = obj.get("action", "?")
            instr = obj.get("instrument") or obj.get("underlying") or "?"
            print(f"  {ts}  {action:<10}  {instr}")
        except Exception:
            pass
else:
    print("\nquant_service_decisions.jsonl: does not exist")

# 3. quant_actions.json
qa = DATA / "quant_actions.json"
if qa.exists():
    print(f"\n=== quant_actions.json: present ===")
    try:
        data = json.loads(qa.read_text(encoding="utf-8"))
        if isinstance(data, list):
            print(f"  {len(data)} actions in file")
            for a in data[-5:]:
                print(f"    {a}")
        else:
            print(f"  type={type(data).__name__}, keys={list(data.keys()) if isinstance(data, dict) else 'n/a'}")
    except Exception as e:
        print(f"  parse error: {e}")

# 4. paper_state
ps = DATA / "paper_state.json"
if ps.exists():
    state = json.loads(ps.read_text(encoding="utf-8"))
    print(f"\n=== paper_state.json ===")
    print(f"  cash: Rs.{state.get('cash', 0):.2f}")
    print(f"  realized_pnl: Rs.{state.get('realized_pnl', 0):.2f}")
    print(f"  open positions: {len(state.get('positions', {}))}")
    if state.get("positions"):
        for k, v in list(state["positions"].items())[:5]:
            print(f"    {k}: {v}")

# 5. Performance daily
pd = DATA / "performance" / "daily.json"
if pd.exists():
    print(f"\n=== performance/daily.json ===")
    print(pd.read_text(encoding="utf-8")[:500])

# 6. Strategy performance
sp = DATA / "performance" / "strategy_performance.json"
if sp.exists():
    print(f"\n=== performance/strategy_performance.json ===")
    print(sp.read_text(encoding="utf-8")[:500])

# 7. Recent log activity (bot)
print(f"\n=== bot_stderr.log: last 5 ERROR/WARNING lines ===")
log = ROOT / "Logs" / "bot_stderr.log"
if log.exists():
    lines = log.read_text(encoding="utf-8").splitlines()
    errs = [l for l in lines[-200:] if "ERROR" in l or "WARNING" in l]
    for l in errs[-5:]:
        print(f"  {l[:200]}")

# 8. Brain log
print(f"\n=== data_cache/quant_service.log: last 5 errors ===")
blog = DATA / "quant_service.log"
if blog.exists():
    lines = blog.read_text(encoding="utf-8").splitlines()
    errs = [l for l in lines[-200:] if "LOOP-ERR" in l or "ERROR" in l]
    for l in errs[-5:]:
        print(f"  {l[:200]}")
