"""One-shot status snapshot — bot, brain, dashboard, go-live policy."""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(".").resolve()
DCACHE = ROOT / "data_cache"


def hr(title):
    print(f"\n=== {title} ===")


# 1. Capital & P&L
hr("Account (paper)")
state = json.loads((DCACHE / "paper_state.json").read_text(encoding="utf-8"))
cash = state.get("cash", 0)
realized = state.get("realized_pnl", 0)
positions = state.get("positions", {})
print(f"Cash:         Rs.{cash:,.2f}")
print(f"Realized P&L: Rs.{realized:,.2f}")
print(f"Open positions: {len(positions)}")
if positions:
    for sym, pos in list(positions.items())[:5]:
        print(f"  {sym}: qty={pos.get('qty')} avg={pos.get('avg_price')} ltp={pos.get('ltp')}")

# 2. Strategy performance
hr("Strategy perf (last 7 days)")
sp = json.loads((DCACHE / "performance" / "strategy_performance.json").read_text(encoding="utf-8"))
print(f"Sharpe 30d: {sp.get('sharpe_30d')}")
bd = sp.get("by_day", {})
today = datetime.now().strftime("%Y-%m-%d")
print(f"Today ({today}): {bd.get(today, {}).get('pnl', 0):+,.2f} ({bd.get(today, {}).get('trades', 0)} trades)")
print("Last 7 days:")
for d in sorted(bd.keys())[-7:]:
    print(f"  {d}: Rs.{bd[d].get('pnl', 0):+,.2f} ({bd[d].get('trades', 0)} trades)")

# 3. Brain activity (LLM)
hr("Brain activity (LLM)")
qp = DCACHE / "quant_service_decisions.jsonl"
if qp.exists():
    lines = qp.read_text(encoding="utf-8").strip().split("\n")
    today_count = 0
    last_decision = None
    for line in lines:
        try:
            r = json.loads(line)
            ts = r.get("ts", "")
            if ts.startswith(today):
                today_count += 1
                last_decision = r
        except Exception:
            pass
    print(f"Total decisions logged: {len(lines):,}")
    print(f"Decisions today: {today_count}")
    if last_decision:
        d = last_decision.get("decision", last_decision)
        print(f"Last decision: {last_decision.get('ts', '?')}")
        print(f"  type={d.get('type', '?')} strategy={d.get('strategy', '?')[:30]}")
        rat = d.get('rationale', '')
        if rat:
            print(f"  rationale: {rat[:150]}{'...' if len(rat) > 150 else ''}")

# 4. Live-trading gates
hr("Live-trading gates")
try:
    sys_path = str(ROOT)
    import sys
    sys.path.insert(0, sys_path)
    from scripts.live_trading_gates import run_all_gates
    rep = run_all_gates()
    print(f"Live readiness: {rep.get('live_readiness_pct', 0):.0f}% ({rep.get('live_readiness', 'n/a')})")
    print(f"All passing: {rep.get('all_ok')}")
    for r in rep.get("results", []):
        icon = "✓" if r.get("ok") else "✗"
        print(f"  {icon} Gate {r.get('id')}: {r.get('name', '')[:50]}")
except Exception as e:
    print(f"  err: {e}")

# 5. Go-live policy
hr("Go-live policy")
lgs_path = DCACHE / "live_go_status.json"
if lgs_path.exists():
    lgs = json.loads(lgs_path.read_text(encoding="utf-8"))
    cur = lgs.get("current", {})
    print(f"Streak: {cur.get('consecutive_green_days')}/5")
    print(f"Cumulative return: {cur.get('cumulative_return_pct', 0):+.2f}%")
    print(f"Ready for live: {lgs.get('ready_for_live')}")
    missing = lgs.get("missing_to_ready", [])
    if missing:
        print(f"Missing: {missing}")
else:
    print("No live_go_status.json (will populate at 15:30 IST)")

# 6. System audit
hr("System audit")
sa_path = DCACHE / "system_audit.json"
if sa_path.exists():
    sa = json.loads(sa_path.read_text(encoding="utf-8"))
    subs = sa.get("subsystems", {})
    for name, sub in subs.items():
        icon = {"ok": "✓", "warn": "!", "error": "✗"}.get(sub.get("status", "?"), "?")
        print(f"  [{icon}] {name}: {str(sub.get('details', ''))[:80]}")

# 7. Today's rejections
hr("Today's rejections (realistic mode)")
rej_path = DCACHE / "order_rejections.jsonl"
if rej_path.exists():
    lines = rej_path.read_text(encoding="utf-8").strip().split("\n")
    today_rej = []
    for line in lines:
        try:
            r = json.loads(line)
            ts = r.get("ts", "")
            if ts.startswith(today):
                today_rej.append(r)
        except Exception:
            pass
    print(f"Total rejections today: {len(today_rej)}")
    for r in today_rej[-3:]:
        print(f"  {r.get('ts', '?')[:19]}: {r.get('reason', r.get('symbol', '?'))}")
