"""Variable / adaptive risk engine.

Risk caps change based on:
- Regime (trending=aggressive, range=base, volatile=defensive)
- Plan confidence (≥0.7 aggressive, ≤0.45 defensive)
- Recent performance (winning streak bumps up, losing streak pulls back)
- VIX (>20 → defensive, <12 → aggressive)

This produces a 'risk_preset' each cycle: 'aggressive' | 'base' | 'defensive'.
All caps (per-trade, daily, weekly, lot size, position cap) are derived from the preset.

If risk.adapt_to_regime = false, always uses 'base'.
If risk.adapt_to_performance = false, doesn't use streak info.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

from loguru import logger

from kotak_bot.utils.clock import is_market_open, is_square_off_time, now_ist


@dataclass
class RiskState:
    capital: float
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    paused: bool = False
    pause_reason: str = ""
    last_trade_pnl: float = 0.0
    open_positions: int = 0
    current_preset: str = "base"  # aggressive | base | defensive


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    suggested_qty: int = 0
    max_loss_for_trade: float = 0.0
    preset: str = "base"


class RiskEngine:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.state = RiskState(capital=self.config.get("initial_capital", 100_000))
        self._trades: list[dict] = []
        self._day = date.today()
        self._week = date.today().isocalendar()[1]
        self._month = date.today().month

        # preset snapshots
        self._presets = {
            "aggressive": self.config.get("aggressive", {}),
            "base": self.config.get("base", self.config),
            "defensive": self.config.get("defensive", {}),
        }
        # adapt toggles
        self._adapt_regime = self.config.get("adapt_to_regime", True)
        self._adapt_perf = self.config.get("adapt_to_performance", True)
        self._high_conf = self.config.get("high_confidence_threshold", 0.7)
        self._low_conf = self.config.get("low_confidence_threshold", 0.45)

    def _roll_period(self) -> None:
        today = date.today()
        if today != self._day:
            self.state.daily_pnl = 0.0
            self.state.trades_today = 0
            self._day = today
        if today.isocalendar()[1] != self._week:
            self.state.weekly_pnl = 0.0
            self._week = today.isocalendar()[1]
        if today.month != self._month:
            self.state.monthly_pnl = 0.0
            self._month = today.month

    def update_capital(self, capital: float) -> None:
        self.state.capital = capital

    def pick_preset(self, regime: str = "unknown", confidence: float = 0.5,
                    vix: float = 14.0) -> str:
        """Decide which risk preset to use this cycle."""
        if not self._adapt_regime and not self._adapt_perf:
            return "base"

        preset = "base"

        # 1) regime-based
        if self._adapt_regime:
            if regime == "trending" and confidence >= self._high_conf:
                preset = "aggressive"
            elif regime == "range" and confidence >= self._high_conf:
                preset = "aggressive"
            elif regime == "volatile":
                preset = "defensive"
            elif regime == "trending" and confidence < self._low_conf:
                preset = "defensive"  # weak trend = defensive

        # 2) confidence overrides
        if confidence >= self._high_conf and preset == "base":
            preset = "aggressive"
        elif confidence < self._low_conf and preset == "aggressive":
            preset = "defensive"

        # 3) VIX overrides
        if vix > 20:
            preset = "defensive"
        elif vix < 10 and preset == "base":
            preset = "aggressive"

        # 4) performance override (winning/losing streak)
        if self._adapt_perf:
            if self.state.consecutive_wins >= 3 and preset != "aggressive":
                preset = "aggressive"  # on a roll
            elif self.state.consecutive_losses >= 2 and preset == "aggressive":
                preset = "base"  # cool down from aggressive

        return preset

    def _caps(self, preset: str) -> dict:
        """Return active cap dict for the given preset, falling back to base."""
        return self._presets.get(preset, self._presets["base"])

    def on_trade_close(self, pnl: float) -> None:
        self._roll_period()
        self.state.daily_pnl += pnl
        self.state.weekly_pnl += pnl
        self.state.monthly_pnl += pnl
        self.state.last_trade_pnl = pnl
        if pnl < 0:
            self.state.consecutive_losses += 1
            self.state.consecutive_wins = 0
        else:
            self.state.consecutive_wins += 1
            self.state.consecutive_losses = 0
        logger.info(
            f"Trade closed: pnl=₹{pnl:,.0f} | day=₹{self.state.daily_pnl:,.0f} | "
            f"week=₹{self.state.weekly_pnl:,.0f} | preset={self.state.current_preset} | "
            f"win_streak={self.state.consecutive_wins} loss_streak={self.state.consecutive_losses}"
        )

    def check_new_trade(self, plan_max_loss: float, underlying: str = "",
                        regime: str = "unknown", confidence: float = 0.5,
                        vix: float = 14.0) -> RiskDecision:
        """Decide whether a new trade is allowed and how many lots."""
        self._roll_period()
        # pick preset based on context
        preset = self.pick_preset(regime=regime, confidence=confidence, vix=vix)
        caps = self._caps(preset)
        self.state.current_preset = preset

        # 1. market open?
        if not is_market_open():
            return RiskDecision(False, "market_closed", 0, 0, preset)
        # 2. paused?
        if self.state.paused:
            return RiskDecision(False, f"paused: {self.state.pause_reason}", 0, 0, preset)
        # 3. square-off time?
        if is_square_off_time():
            return RiskDecision(False, "square_off_time", 0, 0, preset)
        # 4. daily loss cap
        daily_cap = min(
            self.state.capital * caps.get("max_daily_loss_pct", 3.0) / 100.0,
            caps.get("max_daily_loss_abs", 9_000.0),
        )
        if -self.state.daily_pnl >= daily_cap:
            self._pause("daily_loss_cap_hit")
            return RiskDecision(False, f"daily_loss_cap (₹{daily_cap:,.0f})", 0, 0, preset)
        # 5. weekly loss cap
        weekly_cap = self.state.capital * caps.get("max_weekly_loss_pct", 6.0) / 100.0
        if -self.state.weekly_pnl >= weekly_cap:
            self._pause("weekly_loss_cap_hit")
            return RiskDecision(False, f"weekly_loss_cap (₹{weekly_cap:,.0f})", 0, 0, preset)
        # 6. monthly loss cap
        monthly_cap = self.state.capital * caps.get("max_monthly_loss_pct", 12.0) / 100.0
        if -self.state.monthly_pnl >= monthly_cap:
            self._pause("monthly_loss_cap_hit")
            return RiskDecision(False, f"monthly_loss_cap (₹{monthly_cap:,.0f})", 0, 0, preset)
        # 7. consecutive losses (count from base config — not preset)
        max_loss_streak = self.config.get("base", {}).get("max_consecutive_losses", 4)
        if self.state.consecutive_losses >= max_loss_streak:
            self._pause(f"consecutive_losses_{self.state.consecutive_losses}")
            return RiskDecision(False, f"consecutive_losses={self.state.consecutive_losses}", 0, 0, preset)
        # 8. trades per day
        max_tpd = caps.get("max_trades_per_day", 6)
        if self.state.trades_today >= max_tpd:
            return RiskDecision(False, f"max_trades_per_day={max_tpd} (preset={preset})", 0, 0, preset)
        # 9. per-trade max loss
        per_trade_cap = min(
            self.state.capital * caps.get("max_loss_per_trade_pct", 1.0) / 100.0,
            caps.get("max_loss_per_trade_abs", 3_000.0),
        )
        if plan_max_loss > per_trade_cap:
            return RiskDecision(
                False,
                f"plan_loss=₹{plan_max_loss:,.0f} > per_trade_cap=₹{per_trade_cap:,.0f} (preset={preset})",
                0, 0, preset,
            )
        # OK
        default_lots = caps.get("default_lots", 1)
        max_lots = caps.get("max_lots", 3)
        qty = default_lots
        if plan_max_loss * 2 <= per_trade_cap and self.state.daily_pnl >= 0 and confidence >= self._high_conf:
            qty = min(max_lots, default_lots + 1)
        logger.info(
            f"[RISK] {underlying} {preset.upper()} preset | "
            f"per_trade_cap=₹{per_trade_cap:,.0f} | conf={confidence:.2f} | qty={qty}"
        )
        return RiskDecision(allowed=True, reason="ok", suggested_qty=qty,
                            max_loss_for_trade=per_trade_cap, preset=preset)

    def check_open_positions(self) -> int:
        return self.state.open_positions

    def on_position_opened(self) -> None:
        self.state.open_positions += 1

    def on_position_closed(self) -> None:
        self.state.open_positions = max(0, self.state.open_positions - 1)

    def on_data_stale(self, symbol: str) -> None:
        self._pause(f"data_stale:{symbol}")

    def _pause(self, reason: str) -> None:
        if not self.state.paused:
            logger.warning(f"RISK PAUSE: {reason}")
        self.state.paused = True
        self.state.pause_reason = reason

    def resume(self) -> None:
        logger.info(f"RISK RESUME (was: {self.state.pause_reason})")
        self.state.paused = False
        self.state.pause_reason = ""
        self.state.consecutive_losses = 0

    def status(self) -> dict:
        return {
            "capital": self.state.capital,
            "daily_pnl": self.state.daily_pnl,
            "weekly_pnl": self.state.weekly_pnl,
            "monthly_pnl": self.state.monthly_pnl,
            "trades_today": self.state.trades_today,
            "consecutive_losses": self.state.consecutive_losses,
            "consecutive_wins": self.state.consecutive_wins,
            "paused": self.state.paused,
            "pause_reason": self.state.pause_reason,
            "open_positions": self.state.open_positions,
            "current_preset": self.state.current_preset,
        }
