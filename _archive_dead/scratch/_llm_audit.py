"""Quick audit of recent LLM decisions to verify the brain is actually calling."""
import json
import os
from pathlib import Path

ROOT = Path(".").resolve()
DCACHE = ROOT / "data_cache"

# 1. quant_service_decisions.jsonl
qp = DCACHE / "quant_service_decisions.jsonl"
if qp.exists():
    lines = qp.read_text(encoding="utf-8").strip().split("\n")
    print(f"Total decisions logged: {len(lines)}")
    print("Last 5:")
    for line in lines[-5:]:
        try:
            r = json.loads(line)
            ts = r.get("ts", "?")
            action = r.get("action", r.get("decision", r.get("type", "?")))
            strat = r.get("strategy", "?")[:30]
            conf = r.get("confidence", "?")
            print(f"  {ts}: {action} (strat={strat} conf={conf})")
        except Exception as e:
            print(f"  parse err: {e}")

# 2. brain_state.json
bp = DCACHE / "brain_state.json"
print()
if bp.exists():
    bs = json.loads(bp.read_text(encoding="utf-8"))
    keys = list(bs.keys())[:8]
    print(f"brain_state.json keys: {keys}")
    if "last_decision" in bs:
        ld = bs["last_decision"]
        print(f"Last decision: {ld.get('ts', '?')} action={ld.get('action', ld.get('decision', '?'))}")
else:
    print("No brain_state.json")

# 3. brain_actions.json
ba = DCACHE / "brain_actions.json"
print()
if ba.exists():
    try:
        bj = json.loads(ba.read_text(encoding="utf-8"))
        if isinstance(bj, dict) and "actions" in bj:
            actions = bj["actions"]
            print(f"brain_actions.json: {len(actions)} actions")
            for a in actions[-3:]:
                print(f"  {a.get('ts', '?')} {a.get('type', a.get('action', '?'))} {a.get('symbol', '')}")
        else:
            print(f"brain_actions.json keys: {list(bj.keys())[:5]}")
    except Exception as e:
        print(f"  err: {e}")

# 4. system_audit brain_activity
sa = DCACHE / "system_audit.json"
print()
if sa.exists():
    sa_data = json.loads(sa.read_text(encoding="utf-8"))
    subs = sa_data.get("subsystems", {})
    ba = subs.get("brain_activity", {})
    print(f"brain_activity: status={ba.get('status', '?')}")
    print(f"  details: {str(ba.get('details', ''))[:150]}")
    print(f"  ts: {ba.get('ts', '?')}")
    # Show other subsystems
    print()
    print("All subsystems:")
    for name, sub in subs.items():
        print(f"  {name}: {sub.get('status', '?')} - {str(sub.get('details', ''))[:60]}")
