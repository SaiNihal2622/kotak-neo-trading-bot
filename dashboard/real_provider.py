"""FIX 2026-09-17 23:30: real data provider for the dashboard.

Reads directly from the bot's data_cache/ files so the dashboard shows
the actual bot state (capital, positions, P&L, gates, audit) instead of
synthetic mock data. Falls back to MockDataProvider if any critical file
is missing.

Wired into get_provider() in app.py — returns RealDataProvider if
data_cache/paper_state.json exists, otherwise MockDataProvider.

Read flow:
  paper_state.json       → capital, realized_pnl, positions, LTPs
  strategy_perf.json     → sharpe, by_day P&L, equity curve
  system_audit.json      → subsystem statuses (chain, slippage, brain)
  live_go_status.json    → go-live policy (streak, return, missing)
  trade_journal.jsonl    → fills, signals (today's trades)
  order_rejections.jsonl → realistic-mode rejections
  option_chains.json     → spot prices per underlying
  brain_actions.json     → last brain decision
  slippage_audit.json    → fill-mode analysis
  config/settings.yaml   → live bot config
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Make project root importable for fallback helpers
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from dashboard.app import (  # noqa: E402
    AccountSnapshot, Greeks, Position, Signal, NewsItem, PnLHistory,
    RiskState, BotConfig, DataProvider,
)

DCACHE = ROOT / "data_cache"


def _read_json(path: Path, default: Any = None) -> Any:
    """Read JSON file with graceful fallback. Returns default on any error."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _parse_ist_ts(s: str | None) -> datetime:
    """Parse an ISO timestamp; treat naive as IST. Returns now() on failure."""
    if not s:
        return datetime.now()
    try:
        # Normalize to naive for dashboard
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone(timedelta(hours=5, minutes=30))).replace(tzinfo=None)
        return dt
    except Exception:
        return datetime.now()


class RealDataProvider(DataProvider):
    """Reads real bot state from data_cache/*.jsonl/json.

    All reads are best-effort. Missing files fall back to safe defaults so
    the dashboard never crashes — it just shows what's available.
    """

    def __init__(self) -> None:
        # Cache-bust: bump this when file layout changes and old formats
        # need migration logic.
        self._version = 1
        # IST now (we treat the host clock as IST per the dashboard convention).
        self._now_ist = datetime.now()

    # ------------------------------------------------------------------ helpers

    def _paper_state(self) -> dict:
        return _read_json(DCACHE / "paper_state.json", default={})

    def _strategy_perf(self) -> dict:
        return _read_json(DCACHE / "performance" / "strategy_performance.json", default={})

    def _system_audit(self) -> dict:
        return _read_json(DCACHE / "system_audit.json", default={})

    def _live_go_status(self) -> dict:
        return _read_json(DCACHE / "live_go_status.json", default={})

    def _slippage_audit(self) -> dict:
        return _read_json(DCACHE / "slippage_audit.json", default={})

    def _option_chains(self) -> dict:
        return _read_json(DCACHE / "option_chains.json", default={})

    def _brain_state(self) -> dict:
        return _read_json(DCACHE / "brain_state.json", default={})

    def _settings(self) -> dict:
        # Use yaml.safe_load for settings.yaml
        try:
            import yaml
            return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
        except Exception:
            return {}

    # ------------------------------------------------------------------ account

    def get_account(self) -> AccountSnapshot:
        state = self._paper_state()
        sp = self._strategy_perf()
        audit = self._system_audit()
        live_go = self._live_go_status()

        capital = float(state.get("cash", 0.0))
        realized = float(state.get("realized_pnl", 0.0))
        # Total equity = cash + realized + unrealized (mark-to-market)
        equity = capital  # realized is already in cash via _apply_fill
        open_positions = len(state.get("positions", {}))

        # Compute today's P&L. Three sources, in priority order:
        # 1) strategy_performance.by_day[today] — canonical daily aggregator
        #    (used by live_go_tracker and the trade journal's reconciliation).
        # 2) trade_journal.jsonl scan — fallback. Different event writers use
        #    different fields: regular fills write `realized_delta`, the EOD P&L
        #    evaluator writes `realized_pnl`, and orphan reconstruction writes
        #    `realized_pnl` too. Prefer `realized_delta` over `realized_pnl` to
        #    avoid double-counting when both exist for the same fill.
        today_pnl = 0.0
        today_str = datetime.now().strftime("%Y-%m-%d")
        try:
            bd = (sp.get("by_day") or {}).get(today_str)
            if bd and bd.get("pnl") is not None:
                today_pnl = float(bd["pnl"] or 0)
        except Exception:
            pass
        if today_pnl == 0.0:
            journal = DCACHE / "trade_journal.jsonl"
            if journal.exists():
                try:
                    with journal.open(encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                rec = json.loads(line)
                                ts = (rec.get("ts") or rec.get("filled_at") or rec.get("closed_at") or "")[:10]
                                if ts != today_str:
                                    continue
                                delta = rec.get("realized_delta")
                                pnl = rec.get("realized_pnl")
                                if delta is not None and delta != 0:
                                    today_pnl += float(delta)
                                elif pnl is not None and pnl != 0:
                                    today_pnl += float(pnl)
                            except Exception:
                                continue
                except Exception:
                    pass

        # Week P&L from by_day in strategy_performance.json
        week_pnl = 0.0
        by_day = sp.get("by_day", {}) or {}
        try:
            today_d = datetime.now().date()
            week_start = today_d - timedelta(days=7)
            for date_str, rec in by_day.items():
                try:
                    d = datetime.fromisoformat(date_str).date()
                    if d >= week_start:
                        week_pnl += float(rec.get("pnl", 0) or 0)
                except Exception:
                    continue
        except Exception:
            pass

        # Regime from audit (look at chain_health + market regime subsystem)
        regime = "Range"  # default
        try:
            subsystems = audit.get("subsystems", {})
            brain_act = subsystems.get("brain_activity", {})
            details = brain_act.get("details", "")
            if "Trending" in details:
                regime = "Trending"
            elif "Volatile" in details or "vol" in details.lower():
                regime = "Volatile"
            else:
                # Infer from chain_health (no inversion issues = trending, otherwise mixed)
                chain_h = subsystems.get("chain_health", {})
                if chain_h.get("status") == "ok":
                    regime = "Trending"
        except Exception:
            pass

        # Drawdown: compute from cumulative daily P&L
        drawdown = 0.0
        try:
            sorted_days = sorted(by_day.keys())
            cum = []
            running = 0.0
            for d in sorted_days:
                running += float(by_day[d].get("pnl", 0) or 0)
                cum.append(running)
            if cum:
                peak = cum[0]
                for c in cum:
                    if c > peak:
                        peak = c
                if peak > 0:
                    drawdown = (peak - cum[-1]) / peak * 100
                else:
                    drawdown = 0.0
        except Exception:
            pass

        return AccountSnapshot(
            equity=round(equity, 2),
            day_pnl=round(today_pnl, 2),
            week_pnl=round(week_pnl, 2),
            open_positions=open_positions,
            regime=regime,
            drawdown=round(-drawdown, 2),  # store as negative pct for display
        )

    # ------------------------------------------------------------------ positions

    def get_positions(self) -> list[Position]:
        state = self._paper_state()
        positions_dict = state.get("positions", {}) or {}
        out: list[Position] = []
        try:
            chains = self._option_chains()
            chain_prices = {}
            for sym, c in (chains.get("chains") or {}).items():
                chain_prices[sym] = float(c.get("spot", 0) or 0)
        except Exception:
            chain_prices = {}

        for sym, pos in positions_dict.items():
            try:
                qty = int(pos.get("qty", 0) or 0)
                avg = float(pos.get("avg_price", 0) or 0)
                ltp = float(pos.get("ltp", 0) or 0)
                # Use ltp if > 0, else fall back to chain spot for the underlying
                cur = ltp if ltp > 0 else chain_prices.get(pos.get("underlying", ""), 0)
                pnl = (cur - avg) * qty if cur > 0 else pos.get("pnl", 0)
                pnl_pct = ((cur / avg - 1) * 100) if (avg > 0 and cur > 0) else 0.0
                side = "LONG" if qty > 0 else "SHORT"
                # Days to expiry
                dte = 0
                exp_str = pos.get("expiry", "")
                if exp_str:
                    try:
                        exp_d = datetime.fromisoformat(str(exp_str)[:10]).date()
                        dte = (exp_d - datetime.now().date()).days
                    except Exception:
                        dte = 0
                # Greeks: paper_client doesn't compute live Greeks.
                # Use last known greeks from chain if available, else zeros.
                greeks = Greeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0)
                try:
                    chains = self._option_chains()
                    sym_chain = (chains.get("chains") or {}).get(pos.get("underlying", ""), {})
                    sym_data = (sym_chain.get("strikes") or {}).get(
                        f"{int(pos.get('strike', 0))}_{pos.get('option_type', '')}", {})
                    if sym_data:
                        greeks = Greeks(
                            delta=float(sym_data.get("delta", 0) or 0),
                            gamma=float(sym_data.get("gamma", 0) or 0),
                            theta=float(sym_data.get("theta", 0) or 0),
                            vega=float(sym_data.get("vega", 0) or 0),
                        )
                except Exception:
                    pass
                # Exit plan: simple heuristic based on dte + pnl
                exit_plan = "HOLD"
                if dte <= 1:
                    exit_plan = "EXPIRE (0DTE auto)"
                elif pnl_pct > 50:
                    exit_plan = "TAKE_PROFIT"
                elif pnl_pct < -30:
                    exit_plan = "STOP_LOSS"
                out.append(Position(
                    symbol=sym,
                    side=side,
                    qty=abs(qty),
                    entry=round(avg, 2),
                    current=round(cur, 2) if cur > 0 else 0.0,
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    greeks=greeks,
                    exit_plan=exit_plan,
                    dte=max(0, dte),
                ))
            except Exception:
                continue
        return out

    # ------------------------------------------------------------------ signals

    def get_signals(self, lookback_hours: int = 24) -> list[Signal]:
        # Read from data_cache/quant_service_decisions.jsonl OR
        # data_cache/brain_actions.json. Paper-only signals from the brain.
        signals: list[Signal] = []
        # Try brain_actions.json first (last brain decision)
        brain_actions = _read_json(DCACHE / "brain_actions.json", default={})
        if brain_actions:
            for action in brain_actions.get("actions", []):
                try:
                    signals.append(Signal(
                        timestamp=_parse_ist_ts(action.get("ts")),
                        strategy=str(action.get("strategy", "unknown")),
                        confidence=float(action.get("confidence", 0) or 0),
                        direction=str(action.get("side", "HOLD")),
                        reasoning=str(action.get("rationale", ""))[:200],
                        news_context=action.get("news_context", []) or [],
                    ))
                except Exception:
                    continue
        # Also read decisions.jsonl for the last 24h of decisions
        dec = DCACHE / "performance" / "decisions.jsonl"
        if dec.exists():
            try:
                cutoff = datetime.now() - timedelta(hours=lookback_hours)
                with dec.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            ts = _parse_ist_ts(rec.get("ts") or rec.get("timestamp"))
                            if ts < cutoff:
                                continue
                            signals.append(Signal(
                                timestamp=ts,
                                strategy=str(rec.get("strategy", "unknown")),
                                confidence=float(rec.get("confidence", 0) or 0),
                                direction=str(rec.get("action", rec.get("direction", "HOLD"))),
                                reasoning=str(rec.get("rationale", rec.get("note", "")))[:200],
                            ))
                        except Exception:
                            continue
            except Exception:
                pass
        # Sort newest first, cap at 50
        signals.sort(key=lambda s: s.timestamp, reverse=True)
        return signals[:50]

    # ------------------------------------------------------------------ news

    def get_news(self, lookback_hours: int = 24) -> list[NewsItem]:
        news: list[NewsItem] = []
        agg_path = DCACHE / "news_aggregate.json"
        if agg_path.exists():
            try:
                cutoff = datetime.now() - timedelta(hours=lookback_hours)
                data = json.loads(agg_path.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else data.get("items", [])
                for rec in items:
                    try:
                        ts = _parse_ist_ts(rec.get("ts") or rec.get("timestamp") or rec.get("published"))
                        if ts < cutoff:
                            continue
                        sentiment = float(rec.get("sentiment", 0) or 0)
                        # Crude sentiment derivation if missing
                        if sentiment == 0:
                            text = (rec.get("title", "") + " " + rec.get("body", "")).lower()
                            pos_words = ("surge", "rally", "gain", "rise", "up", "high", "beat", "win")
                            neg_words = ("fall", "drop", "crash", "low", "down", "miss", "lose")
                            pos = sum(1 for w in pos_words if w in text)
                            neg = sum(1 for w in neg_words if w in text)
                            sentiment = max(-1.0, min(1.0, (pos - neg) * 0.2))
                        news.append(NewsItem(
                            timestamp=ts,
                            source=str(rec.get("source", "unknown")),
                            title=str(rec.get("title", ""))[:200],
                            body=str(rec.get("body", rec.get("summary", "")))[:400],
                            sentiment=sentiment,
                            event_tags=rec.get("event_tags", []) or [],
                            tickers=rec.get("tickers", []) or [],
                            url=str(rec.get("url", "")),
                        ))
                    except Exception:
                        continue
            except Exception:
                pass
        news.sort(key=lambda n: n.timestamp, reverse=True)
        return news[:30]

    # ------------------------------------------------------------------ pnl history

    def get_pnl_history(self) -> PnLHistory:
        sp = self._strategy_perf()
        by_day = sp.get("by_day", {}) or {}
        # Build dates + cumulative equity
        sorted_days = sorted(by_day.keys())
        dates = []
        equity = []
        # Start at the baseline (100k reset) and add by_day pnl
        baseline = 100000.0
        cum = baseline
        daily_returns = []
        prev_eod = baseline
        for d_str in sorted_days:
            try:
                d = datetime.fromisoformat(d_str)
                pnl = float(by_day[d_str].get("pnl", 0) or 0)
                dates.append(d)
                cum += pnl
                equity.append(round(cum, 2))
                if prev_eod > 0:
                    daily_returns.append(round(pnl / prev_eod, 6))
                else:
                    daily_returns.append(0.0)
                prev_eod = cum
            except Exception:
                continue
        # Drawdown
        drawdown = []
        if equity:
            peak = equity[0]
            for e in equity:
                if e > peak:
                    peak = e
                dd = (peak - e) / peak * 100 if peak > 0 else 0
                drawdown.append(round(-dd, 2))
        # Recent closed trades (from trade_journal.jsonl, last 50)
        trades = []
        journal = DCACHE / "trade_journal.jsonl"
        if journal.exists():
            try:
                with journal.open(encoding="utf-8") as f:
                    lines = f.readlines()[-50:]
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("event") != "FILL":
                            continue
                        trades.append({
                            "ts": rec.get("ts", ""),
                            "symbol": rec.get("symbol", ""),
                            "side": rec.get("side", ""),
                            "qty": rec.get("qty", 0),
                            "price": rec.get("avg_fill_price", 0),
                            "pnl": rec.get("realized_delta", 0) or 0,
                            "tag": rec.get("tag", ""),
                        })
                    except Exception:
                        continue
            except Exception:
                pass
        return PnLHistory(
            dates=dates,
            equity=equity,
            daily_returns=daily_returns,
            drawdown=drawdown,
            trades=trades,
        )

    # ------------------------------------------------------------------ risk

    def get_risk_state(self) -> RiskState:
        # Daily / weekly loss limits from settings.yaml
        cfg = self._settings()
        risk_cfg = cfg.get("risk", {}) or {}
        # Daily / weekly loss used: sum of negative by_day pnl in last 1d/7d
        sp = self._strategy_perf()
        by_day = sp.get("by_day", {}) or {}
        today_d = datetime.now().date()
        week_start = today_d - timedelta(days=7)
        daily_loss_used = 0.0
        weekly_loss_used = 0.0
        for d_str, rec in by_day.items():
            try:
                d = datetime.fromisoformat(d_str).date()
                pnl = float(rec.get("pnl", 0) or 0)
                if pnl < 0:
                    if d == today_d:
                        daily_loss_used += -pnl
                    if d >= week_start:
                        weekly_loss_used += -pnl
            except Exception:
                continue
        # Express as % of starting capital
        starting_capital = float((cfg.get("broker") or {}).get("paper_capital", 100000.0))
        daily_loss_pct = (daily_loss_used / starting_capital * 100) if starting_capital > 0 else 0.0
        weekly_loss_pct = (weekly_loss_used / starting_capital * 100) if starting_capital > 0 else 0.0
        # Limits from settings (default 1.5% / 4.0%)
        daily_limit = float(risk_cfg.get("daily_loss_limit_pct", 1.5))
        weekly_limit = float(risk_cfg.get("weekly_loss_limit_pct", 4.0))
        # Max drawdown: from by_day equity curve
        sorted_days = sorted(by_day.keys())
        cum = 0.0
        peak = 0.0
        max_dd = 0.0
        for d_str in sorted_days:
            cum += float(by_day[d_str].get("pnl", 0) or 0)
            if cum > peak:
                peak = cum
            if peak > 0:
                dd = (peak - cum) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        # Kill switch: from live_go_status (paper mode → always off unless triggered)
        live_go = self._live_go_status()
        ks = False
        try:
            # If any audit subsystem is in error state, consider kill switch on
            audit = self._system_audit()
            subsystems = audit.get("subsystems", {})
            for name, sub in subsystems.items():
                if sub.get("status") == "error":
                    ks = True
                    break
        except Exception:
            pass
        # Circuit breakers (informational)
        breakers = []
        try:
            if daily_loss_pct >= daily_limit * 0.8:
                breakers.append(f"daily loss at {daily_loss_pct:.1f}% (limit {daily_limit:.1f}%)")
            if weekly_loss_pct >= weekly_limit * 0.8:
                breakers.append(f"weekly loss at {weekly_loss_pct:.1f}% (limit {weekly_limit:.1f}%)")
            if max_dd >= 10:
                breakers.append(f"max drawdown {max_dd:.1f}%")
        except Exception:
            pass
        return RiskState(
            daily_loss_used=round(daily_loss_pct, 2),
            daily_loss_limit=daily_limit,
            weekly_loss_used=round(weekly_loss_pct, 2),
            weekly_loss_limit=weekly_limit,
            max_drawdown=round(max_dd, 2),
            kill_switch=ks,
            circuit_breakers=breakers,
        )

    # ------------------------------------------------------------------ config

    def get_config(self) -> BotConfig:
        cfg = self._settings()
        # Add live-go policy status so the dashboard shows it inline
        lgs = self._live_go_status()
        if lgs:
            cfg["live_go_progress"] = {
                "streak": lgs.get("current", {}).get("consecutive_green_days"),
                "return_pct": lgs.get("current", {}).get("cumulative_return_pct"),
                "ready": lgs.get("ready_for_live"),
                "missing": lgs.get("missing_to_ready", []),
            }
        # Add live-trading gates status
        try:
            sys.path.insert(0, str(ROOT))
            from scripts.live_trading_gates import run_all_gates
            report = run_all_gates()
            cfg["live_trading_gates"] = {
                "all_ok": report.get("all_ok"),
                "live_readiness_pct": report.get("live_readiness_pct"),
                "results": report.get("results", []),
            }
        except Exception as e:
            cfg["live_trading_gates"] = {"error": str(e)}
        # Add slippage audit summary
        sa = self._slippage_audit()
        if sa:
            cfg["slippage_audit"] = {
                "n_fills_today": sa.get("n_fills_today"),
                "mean_slippage_bps": sa.get("slippage_bps_mean"),
                "buy_sell_asymmetry_bps": sa.get("asymmetry_buy_sell_bps"),
                "live_equivalent_pnl_delta": sa.get("live_equivalent_pnl_delta_rs"),
                "fill_mode_detected": sa.get("fill_mode_detected"),
            }
        return BotConfig(data=cfg)

    def update_config(self, key: str, value: Any) -> bool:
        # Read-only for now — would require safe-write to settings.yaml.
        # Return False to indicate write was not performed.
        return False
