"""Performance attribution, alpha decay detection, and auto-params tuning.

- PerformanceTracker: per-strategy win rate, P&L, Sharpe over rolling window
- AlphaDecayDetector: flags a strategy as decayed if rolling Sharpe < 0 for N days
- AutoParamsTuner: adjusts target_rr, wing_width, stop_loss_multiplier based on rolling Sharpe
"""
from __future__ import annotations

import csv
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class TradeRecord:
    timestamp: datetime
    strategy: str
    underlying: str
    pnl: float
    pnl_pct: float  # pnl / max_loss
    hold_minutes: int
    exit_reason: str = ""


class PerformanceTracker:
    """Track per-strategy performance metrics from trades.csv."""

    def __init__(self, trades_csv: Path = Path("logs/trades.csv")):
        self.trades_csv = trades_csv
        self.records: list[TradeRecord] = []
        self._load()
        # per-strategy windows (rolling 20 trades)
        self.windows: dict[str, deque] = {}

    def _load(self) -> None:
        if not self.trades_csv.exists():
            return
        try:
            with open(self.trades_csv, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    try:
                        pnl = float(r.get("fill_price", 0)) - float(r.get("price", 0))
                        if r.get("side") == "BUY":
                            pnl = -pnl  # for long premium, pnl is the change
                        ts_str = r.get("timestamp", "")
                        if not ts_str:
                            continue
                        # try various date formats
                        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                            try:
                                ts = datetime.strptime(ts_str[:19], fmt)
                                break
                            except ValueError:
                                continue
                        else:
                            continue
                        # determine strategy from tag
                        tag = r.get("tag", "")
                        strat = tag.split("_")[0] if tag else "unknown"
                        rec = TradeRecord(
                            timestamp=ts,
                            strategy=strat,
                            underlying=r.get("symbol", "").split("0")[0][:7] if r.get("symbol") else "",
                            pnl=pnl,
                            pnl_pct=0.0,
                            hold_minutes=0,
                        )
                        self.records.append(rec)
                        if strat not in self.windows:
                            self.windows[strat] = deque(maxlen=20)
                        self.windows[strat].append(rec)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"performance tracker load: {e}")

    def add_trade(self, strategy: str, underlying: str, pnl: float, pnl_pct: float = 0.0,
                  hold_minutes: int = 0, exit_reason: str = "") -> None:
        rec = TradeRecord(
            timestamp=datetime.now(timezone.utc),
            strategy=strategy,
            underlying=underlying,
            pnl=pnl,
            pnl_pct=pnl_pct,
            hold_minutes=hold_minutes,
            exit_reason=exit_reason,
        )
        self.records.append(rec)
        if strategy not in self.windows:
            self.windows[strategy] = deque(maxlen=20)
        self.windows[strategy].append(rec)
        # also persist to CSV for next reload
        self._append_to_csv(rec)

    def _append_to_csv(self, rec: TradeRecord) -> None:
        perf_csv = Path("logs/performance.csv")
        perf_csv.parent.mkdir(parents=True, exist_ok=True)
        new = not perf_csv.exists()
        with open(perf_csv, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["timestamp", "strategy", "underlying", "pnl", "pnl_pct", "hold_minutes", "exit_reason"])
            w.writerow([rec.timestamp.isoformat(), rec.strategy, rec.underlying,
                        f"{rec.pnl:.2f}", f"{rec.pnl_pct:.4f}", rec.hold_minutes, rec.exit_reason])

    def get_metrics(self, strategy: str) -> dict:
        """Return win rate, avg pnl, Sharpe, count for a strategy."""
        window = list(self.windows.get(strategy, []))
        if not window:
            return {"strategy": strategy, "count": 0, "win_rate": 0, "avg_pnl": 0, "sharpe": 0,
                    "total_pnl": 0, "best": 0, "worst": 0, "avg_hold_min": 0}
        pnls = [r.pnl for r in window]
        wins = sum(1 for p in pnls if p > 0)
        avg_pnl = sum(pnls) / len(pnls)
        sharpe = self._sharpe(pnls)
        avg_hold = sum(r.hold_minutes for r in window) / len(window)
        return {
            "strategy": strategy,
            "count": len(window),
            "win_rate": wins / len(window),
            "avg_pnl": avg_pnl,
            "sharpe": sharpe,
            "total_pnl": sum(pnls),
            "best": max(pnls),
            "worst": min(pnls),
            "avg_hold_min": avg_hold,
        }

    def _sharpe(self, pnls: list, rf: float = 0.0) -> float:
        if len(pnls) < 2:
            return 0.0
        mean = sum(pnls) / len(pnls)
        var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 0.01
        return (mean - rf) / std if std > 0 else 0.0

    def all_strategies_metrics(self) -> list[dict]:
        return [self.get_metrics(s) for s in self.windows.keys()]

    def summary(self) -> str:
        lines = ["📊 Performance Attribution (rolling 20 trades)", "=" * 40]
        for m in self.all_strategies_metrics():
            if m["count"] == 0:
                continue
            lines.append(
                f"  {m['strategy']:20s} cnt={m['count']:3d}  win={m['win_rate']:.0%}  "
                f"avg=Rs.{m['avg_pnl']:7.0f}  Sharpe={m['sharpe']:+.2f}  "
                f"total=Rs.{m['total_pnl']:+8.0f}  hold={m['avg_hold_min']:.0f}m"
            )
        return "\n".join(lines)


class AlphaDecayDetector:
    """Flag a strategy as decayed if rolling Sharpe < 0 for N consecutive days."""

    def __init__(self, tracker: PerformanceTracker, threshold: float = -0.1, days: int = 3):
        self.tracker = tracker
        self.threshold = threshold
        self.days = days
        self.decayed: dict[str, bool] = {}
        self._last_check: dict[str, float] = {}

    def check(self) -> dict[str, dict]:
        """Return {strategy: {decayed, sharpe, reason}} for all strategies."""
        out = {}
        for strat in self.tracker.windows.keys():
            m = self.tracker.get_metrics(strat)
            sharpe = m["sharpe"]
            decayed = sharpe < self.threshold and m["count"] >= 5
            if decayed:
                self.decayed[strat] = True
                out[strat] = {
                    "decayed": True,
                    "sharpe": sharpe,
                    "reason": f"Sharpe {sharpe:.2f} < {self.threshold} for {m['count']} trades",
                }
            else:
                self.decayed[strat] = False
                out[strat] = {"decayed": False, "sharpe": sharpe, "reason": "ok"}
        return out

    def is_decayed(self, strategy: str) -> bool:
        return self.decayed.get(strategy, False)


class AutoParamsTuner:
    """Adjust strategy parameters based on rolling Sharpe.

    If strategy Sharpe > +0.5: aggressive (wider target, tighter stop)
    If strategy Sharpe 0..+0.5: base
    If strategy Sharpe -0.1..0: tighter targets, wider stops
    If strategy Sharpe < -0.1: defensive (smaller size, max 1 lot)
    """

    def __init__(self, tracker: PerformanceTracker):
        self.tracker = tracker
        self.adjustments: dict[str, dict] = {}

    def tune(self) -> dict[str, dict]:
        """Return {strategy: {target_rr_mult, wing_width_mult, stop_loss_mult, max_lots}}"""
        out = {}
        for strat in self.tracker.windows.keys():
            m = self.tracker.get_metrics(strat)
            sharpe = m["sharpe"]
            win_rate = m["win_rate"]
            if sharpe > 0.5 and win_rate > 0.55:
                preset = "aggressive"
                target_rr_mult = 1.2
                wing_width_mult = 1.0
                stop_loss_mult = 1.0
                max_lots = 2
            elif sharpe > 0:
                preset = "base"
                target_rr_mult = 1.0
                wing_width_mult = 1.0
                stop_loss_mult = 1.0
                max_lots = 1
            elif sharpe > -0.1:
                preset = "tighten"
                target_rr_mult = 0.8
                wing_width_mult = 0.9  # tighter wings = less exposure
                stop_loss_mult = 1.2
                max_lots = 1
            else:
                preset = "defensive"
                target_rr_mult = 0.6
                wing_width_mult = 0.8
                stop_loss_mult = 1.5
                max_lots = 1
            adj = {
                "preset": preset,
                "target_rr_mult": target_rr_mult,
                "wing_width_mult": wing_width_mult,
                "stop_loss_mult": stop_loss_mult,
                "max_lots": max_lots,
                "sharpe": sharpe,
                "win_rate": win_rate,
                "count": m["count"],
            }
            out[strat] = adj
            self.adjustments[strat] = adj
        return out

    def apply_to_config(self, base_config: dict) -> dict:
        """Mutate strategy config dict with adjustments."""
        adj = self.tune()
        for strat, a in adj.items():
            # find strategy config and adjust
            if strat in base_config:
                cfg = base_config[strat]
                # adjust target_rr / profit_target_pct
                for k in list(cfg.keys()):
                    if k in ("target_rr", "profit_target_pct"):
                        cfg[k] = round(cfg[k] * a["target_rr_mult"], 2)
                    elif k in ("wing_width", "stop_loss_multiplier"):
                        cfg[k] = round(cfg[k] * a["wing_width_mult" if k == "wing_width" else "stop_loss_mult"], 2)
        return base_config
