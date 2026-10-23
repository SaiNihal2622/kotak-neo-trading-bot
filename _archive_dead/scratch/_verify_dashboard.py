"""One-shot verification that dashboard.app.get_provider() returns RealDataProvider."""
import sys
from pathlib import Path

ROOT = Path(".").resolve()
sys.path.insert(0, str(ROOT))

import dashboard.app as da  # noqa: E402

p = da.get_provider()
print("Provider type:", type(p).__name__)
print("Is real:", type(p).__name__ == "RealDataProvider")
a = p.get_account()
print(f"Equity: Rs.{a.equity:,.2f}")
print(f"Day P&L: Rs.{a.day_pnl:,.2f}")
print(f"Open positions: {a.open_positions}")
print(f"Regime: {a.regime}")
print(f"Drawdown: {a.drawdown}%")
cfg = p.get_config().data
lgs = cfg.get("live_go_progress") or {}
print("Live-go: streak=", lgs.get("streak"), " return=", lgs.get("return_pct"), " ready=", lgs.get("ready"))
gates = cfg.get("live_trading_gates") or {}
print("Gates: live_readiness=", gates.get("live_readiness_pct"))
sa = cfg.get("slippage_audit") or {}
print("Slippage: mean_bps=", sa.get("mean_slippage_bps"), " mode=", sa.get("fill_mode_detected"))
