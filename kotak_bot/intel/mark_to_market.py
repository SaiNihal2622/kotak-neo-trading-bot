"""Live mark-to-market + anomaly detection for the running portfolio.

- mark_positions_to_market: compute current P&L for all open positions
- detect_anomalies: volume spikes, IV spikes, price moves beyond threshold
- Alerting: send Telegram when anomaly detected
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger


def compute_pnl(positions: list, feed) -> dict:
    """Compute current P&L for all open positions. Returns per-symbol + total."""
    out = {"total": 0.0, "by_symbol": {}, "by_underlying": {}}
    for p in positions:
        sym = p.get("symbol", "")
        cur = feed.get_ltp(sym)
        if cur <= 0:
            continue
        avg = p.get("avg_price", 0)
        qty = p.get("qty", 0)
        side_str = p.get("side", "BUY")
        if hasattr(side_str, "value"):
            side_str = side_str.value
        sign = 1 if side_str == "SELL" else -1
        leg_pnl = (cur - avg) * qty * sign
        out["by_symbol"][sym] = leg_pnl
        u = p.get("underlying", sym.split("0")[0][:7] if sym else "UNK")
        out["by_underlying"][u] = out["by_underlying"].get(u, 0) + leg_pnl
        out["total"] += leg_pnl
    return out


class AnomalyDetector:
    """Detect volume spikes, IV spikes, unusual price moves, large P&L swings."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.price_history: dict[str, deque] = {}  # symbol -> recent prices
        self.volume_history: dict[str, deque] = {}
        self.pnl_history: deque = deque(maxlen=60)  # 60 cycles ~ 5 min
        self.last_pnl_alert: float = 0.0
        self.last_alert_at: dict[str, datetime] = {}
        self.cooldown_sec = self.config.get("cooldown_sec", 300)

    def update(self, feed) -> None:
        """Update price + volume history for all known symbols."""
        for sym in list(feed._latest.keys())[:200]:  # cap to avoid memory blowup
            t = feed.get_latest(sym)
            if not t:
                continue
            if sym not in self.price_history:
                self.price_history[sym] = deque(maxlen=100)
                self.volume_history[sym] = deque(maxlen=20)
            self.price_history[sym].append(t.ltp)
            self.volume_history[sym].append(t.volume)

    def detect_price_anomaly(self, symbol: str, current_price: float) -> Optional[dict]:
        """Detect >X% move in last N ticks."""
        hist = list(self.price_history.get(symbol, []))
        if len(hist) < 20:
            return None
        # 1-min-equivalent (20 ticks at 0.5s = 10s) — use 5-tick window for short-term
        recent = hist[-5:]
        if not recent or recent[0] <= 0:
            return None
        change = (current_price - recent[0]) / recent[0]
        if abs(change) > 0.005:  # 0.5% move in 2.5s
            return {
                "type": "price_spike",
                "symbol": symbol,
                "change_pct": change * 100,
                "window_sec": 2.5,
                "current": current_price,
                "prev": recent[0],
            }
        return None

    def detect_volume_anomaly(self, symbol: str) -> Optional[dict]:
        """Detect volume >3x recent average."""
        hist = list(self.volume_history.get(symbol, []))
        if len(hist) < 10:
            return None
        avg = sum(hist[:-1]) / max(1, len(hist) - 1)
        cur = hist[-1]
        if avg > 0 and cur > 3 * avg:
            return {
                "type": "volume_spike",
                "symbol": symbol,
                "current": cur,
                "avg": avg,
                "ratio": cur / avg,
            }
        return None

    def detect_pnl_swing(self, current_pnl: float) -> Optional[dict]:
        """Alert if P&L moved >Rs.500 in last 5 cycles."""
        self.pnl_history.append(current_pnl)
        if len(self.pnl_history) < 5:
            return None
        # compare to 5 cycles ago
        prev = list(self.pnl_history)[-5]
        delta = current_pnl - prev
        if abs(delta) > 500 and (datetime.now(timezone.utc).timestamp() - self.last_pnl_alert) > 60:
            self.last_pnl_alert = datetime.now(timezone.utc).timestamp()
            return {
                "type": "pnl_swing",
                "current": current_pnl,
                "previous": prev,
                "delta": delta,
            }
        return None

    def should_alert(self, key: str) -> bool:
        """Check cooldown for a key."""
        last = self.last_alert_at.get(key)
        if last and (datetime.now(timezone.utc) - last).total_seconds() < self.cooldown_sec:
            return False
        self.last_alert_at[key] = datetime.now(timezone.utc)
        return True


class OIHeatmapGenerator:
    """Generate OI heatmap PNG for the dashboard."""

    def __init__(self, output_dir: Path = Path("data_cache/heatmaps")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(self, underlying: str, oi_data: dict, spot: float,
               output_name: Optional[str] = None) -> Optional[Path]:
        """Render OI heatmap as PNG."""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
            strikes = sorted(oi_data.keys())
            if not strikes:
                return None
            ce_oi = [oi_data[s].get("ce_oi", 0) for s in strikes]
            pe_oi = [oi_data[s].get("pe_oi", 0) for s in strikes]
            # build matrix: rows = (CE, PE), cols = strikes
            max_oi = max(max(ce_oi), max(pe_oi), 1)
            fig, ax = plt.subplots(figsize=(10, 3))
            x = np.arange(len(strikes))
            ax.bar(x - 0.2, ce_oi, width=0.4, color='red', alpha=0.7, label='Call OI')
            ax.bar(x + 0.2, pe_oi, width=0.4, color='green', alpha=0.7, label='Put OI')
            ax.set_xticks(x)
            ax.set_xticklabels([str(s) for s in strikes], rotation=45)
            ax.set_xlabel("Strike")
            ax.set_ylabel("Open Interest")
            ax.set_title(f"{underlying} OI Heatmap @ {datetime.now().strftime('%H:%M:%S')} | Spot: {spot:.2f}")
            if spot > 0:
                spot_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
                ax.axvline(spot_idx, color='blue', linestyle='--', alpha=0.5, label=f"Spot {spot:.0f}")
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            name = output_name or f"oi_{underlying}_{datetime.now().strftime('%H%M%S')}.png"
            path = self.output_dir / name
            plt.savefig(path, dpi=100, bbox_inches='tight')
            plt.close()
            return path
        except Exception as e:
            logger.warning(f"OI heatmap render failed: {e}")
            return None
