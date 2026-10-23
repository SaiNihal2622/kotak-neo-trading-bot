"""Quick gates check."""
import sys
sys.path.insert(0, "scripts")
from live_trading_gates import run_all_gates

rep = run_all_gates()
print(f"live_readiness: {rep.get('live_readiness_pct')}% ({rep.get('live_readiness')})")
for r in rep.get("results", []):
    icon = "OK" if r.get("ok") else "FAIL"
    print(f"  [{icon}] Gate {r.get('id')}: {r.get('name', '')[:60]}")
