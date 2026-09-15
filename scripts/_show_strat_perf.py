"""Show per-strategy performance."""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
from scripts.strategy_library import load_performance
perf = load_performance()
for name, r in perf.items():
    status = "DISABLED" if r.is_disabled else "ACTIVE"
    print(f"{name:30s} {status:8s} trades={r.n_trades} pnl=Rs.{r.total_pnl:.0f} reason={r.disable_reason[:80]}")
