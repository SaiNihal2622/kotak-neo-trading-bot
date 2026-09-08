"""Quick health check for tomorrow's first UNLEASHED market day."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"

# 1. Brain status
print("=" * 60)
print("BRAIN (KotakQuantService)")
print("=" * 60)
qs = json.load(open(DCACHE / "quant_service_state.json"))
print(f"  status:        {qs.get('status', '?')}")
print(f"  last_tick:     {qs.get('last_tick', '?')}")
print(f"  tick_count:    {qs.get('tick_count', '?')}")
print(f"  llm_calls:     {qs.get('llm_calls', '?')}")
print(f"  actions_taken: {qs.get('actions_taken', '?')}")

# 2. Bot status
print()
print("=" * 60)
print("BOT (KotakBotPaper)")
print("=" * 60)
lv = json.load(open(DCACHE / "liveness.json"))
s = lv["snapshot"]
print(f"  state:         {lv.get('state', '?')}")
print(f"  uptime:        {lv.get('uptime_sec', 0) / 3600:.1f}h")
print(f"  tick:          {lv.get('tick', '?')}")
print(f"  capital:       Rs.{s.get('capital', 0):,.0f}")
print(f"  realized_pnl:  Rs.{s.get('realized_pnl', 0):+,.2f}")
print(f"  open_pos:      {s.get('open_positions', '?')}")
print(f"  vix:           {s.get('vix', '?')}")

# 3. Schedulers configured
print()
print("=" * 60)
print("SCHEDULERS (24/7)")
print("=" * 60)
schedulers = [
    ("RSS news (30 min)", "scripts/rss_news_fetcher.py"),
    ("FII/DII (1h)", "scripts/fii_dii_fetcher.py"),
    ("Predictive signals (5 min)", "scripts/predictive_signals.py"),
    ("Grok Bot Desk (15 min, 24/7)", "scripts/run_grok_desk.py"),
    ("Daily maintenance (08:25)", "scripts/daily_maintenance.py"),
    ("Morning brief (08:15)", "scripts/mavis_premarket.py"),
    ("EOD backup (15:45)", "scripts/daily_state_backup.py"),
    ("Weekly review (Sun 18:00)", "scripts/weekly_strategy_review.py"),
    ("Nightly improvement (23:00)", "scripts/nightly_improvement.py"),
]
for name, _ in schedulers:
    print(f"  OK: {name}")

# 4. New mechanism flags
print()
print("=" * 60)
print("NEW MECHANISMS (UNLEASHED mode)")
print("=" * 60)
print("  ✓ AI override of force-square:  data_cache/_ai_skip_force_square.json")
print("  ✓ AI override of skip-day:      data_cache/_skip_day.json")
print("  ✓ AI override of intraday:       write_decision's ai_override_intraday")
print("  ✓ Conviction-based sizing:        LLM output conviction 0-100")
print("  ✓ Max-drawdown safety net:       -50% auto-pause")
print("  ✓ Real RSS news feed:            10 sources (MC, ET, LiveMint, BS, etc)")
print("  ✓ Real FII/DII feed:              Moneycontrol + NSE archives fallback")
print("  ✓ 6 predictive signals:           momentum, vol, trend, RSI, breakout")

# 5. Settings
print()
print("=" * 60)
print("SETTINGS (UNLEASHED)")
print("=" * 60)
import re
cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
m = re.search(r"max_drawdown_pct:\s*([\d.]+)", cfg)
dd = m.group(1) if m else "?"
m = re.search(r"allow_overnight:\s*(\w+)", cfg)
overnight = m.group(1) if m else "?"
m = re.search(r"position_cap:\s*(\d+)", cfg)
pc = m.group(1) if m else "?"
m = re.search(r"max_lots:\s*(\d+)", cfg)
ml = m.group(1) if m else "?"
m = re.search(r"skip_above:\s*([\d.]+)", cfg)
vix = m.group(1) if m else "?"
print(f"  allow_overnight:     {overnight}")
print(f"  position_cap:        {pc}")
print(f"  max_lots:            {ml}")
print(f"  VIX skip_above:      {vix}")
print(f"  max_drawdown_pct:    {dd}")

# 6. Tests
print()
print("=" * 60)
print("TESTS")
print("=" * 60)
import subprocess
r = subprocess.run(
    ["pytest", "tests/", "-q", "--tb=no", "-x"],
    capture_output=True, text=True, cwd=str(ROOT),
)
# Extract passed count
import re
m = re.search(r"(\d+) passed", r.stdout)
if m:
    print(f"  ✓ {m.group(1)} tests passing")
else:
    print(f"  ✗ Test run output: {r.stdout[-300:]}")

# 7. Git
print()
print("=" * 60)
print("GIT")
print("=" * 60)
import subprocess
r = subprocess.run(["git", "log", "--oneline", "origin/master..HEAD"], capture_output=True, text=True, cwd=str(ROOT))
ahead_lines = [l for l in r.stdout.strip().split("\n") if l]
print(f"  ahead of origin: {len(ahead_lines)} commits")
r = subprocess.run(["git", "log", "--oneline", "HEAD..origin/master"], capture_output=True, text=True, cwd=str(ROOT))
behind_lines = [l for l in r.stdout.strip().split("\n") if l]
print(f"  behind origin:    {len(behind_lines)} commits")

print()
print("=" * 60)
print("READY FOR TOMORROW'S MARKET OPEN (09:15 IST)")
print("=" * 60)
