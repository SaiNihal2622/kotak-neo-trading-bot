"""
dashboard/app.py
================

Multi-page Streamlit dashboard for the Kotak Neo trading bot.

Run with::

    streamlit run dashboard/app.py

Pages
-----

1. **Overview**  — equity, day / week P&L, open-position count, regime badge.
2. **Positions** — live positions with entry, current, P&L, Greeks, exit plan.
3. **Signals**   — last 24 h of generated signals with reasoning & news context.
4. **News**      — news feed with sentiment & event flags.
5. **P&L History** — equity curve, daily returns, drawdown, win/loss histogram.
6. **Risk**      — daily / weekly loss used, max DD, kill switch, breakers.
7. **Backtest**  — run a backtest from the UI; equity curve + metrics + sweep.
8. **Config**    — view / edit live config with confirmation gate.

Architecture
------------

* All data flows through a ``DataProvider`` interface so the dashboard works
  with the live broker or a mock implementation. The mock layer is defined
  inline (``MockDataProvider``) and is the default when the broker is not
  connected.
* Plotly is used for all charts; matplotlib is intentionally avoided to keep
  the Streamlit cold-start fast.
* The sidebar shows bot status, IST clock, and market-hours indicator.

Graceful degradation
--------------------

* If ``vectorbt`` is not importable, the Backtest page falls back to a tiny
  in-process P&L simulator (delegates to ``backtest.engine``).
* If ``pandas_ta`` is missing, the Backtest page uses the manual indicators
  already implemented in ``backtest.engine.compute_indicators``.
"""

from __future__ import annotations

import json
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from loguru import logger

# Optional backtester — only loaded on the Backtest page to keep cold-start
# fast. Wrapped in try/except so a missing vectorbt does not break the rest
# of the dashboard.
try:
    from backtest.engine import (
        BacktestConfig,
        BacktestEngine,
        EMACrossStrategy,
        RSIMeanReversionStrategy,
        BollingerBreakoutStrategy,
        generate_synthetic_data,
    )

    _HAS_BACKTEST = True
except Exception as _exc:  # pragma: no cover
    _HAS_BACKTEST = False
    logger.warning(f"backtest module unavailable: {_exc}")


# ===========================================================================
# Page config & global CSS
# ===========================================================================

st.set_page_config(
    page_title="Kotak Neo Bot — Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Custom CSS — small touches, no theme overhaul.
st.markdown(
    """
    <style>
    .metric-card {
        background: linear-gradient(180deg, #1a1f2c 0%, #0f1320 100%);
        padding: 1rem 1.2rem; border-radius: 10px;
        border: 1px solid #232a3b; color: #f5f7fa;
    }
    .metric-card h4 { margin: 0; font-size: 0.85rem; color: #9aa3b2; }
    .metric-card h2 { margin: 0.2rem 0 0 0; font-size: 1.6rem; color: #f5f7fa; }
    .positive { color: #4ade80; }
    .negative { color: #f87171; }
    .neutral  { color: #9aa3b2; }
    .badge {
        display: inline-block; padding: 0.2rem 0.6rem; border-radius: 999px;
        font-size: 0.75rem; font-weight: 600;
    }
    .badge-green  { background: #14532d; color: #bbf7d0; }
    .badge-red    { background: #7f1d1d; color: #fecaca; }
    .badge-amber  { background: #78350f; color: #fde68a; }
    .badge-blue   { background: #1e3a8a; color: #bfdbfe; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ===========================================================================
# Data structures
# ===========================================================================


@dataclass
class AccountSnapshot:
    equity: float
    day_pnl: float
    week_pnl: float
    open_positions: int
    regime: str  # "Trending" | "Range" | "Volatile"
    drawdown: float


@dataclass
class Greeks:
    delta: float
    gamma: float
    theta: float
    vega: float


@dataclass
class Position:
    symbol: str
    side: str  # "LONG" | "SHORT"
    qty: int
    entry: float
    current: float
    pnl: float
    pnl_pct: float
    greeks: Greeks
    exit_plan: str
    dte: int  # days to expiry


@dataclass
class Signal:
    timestamp: datetime
    strategy: str
    confidence: float
    direction: str  # "BUY" | "SELL"
    reasoning: str
    news_context: list[str] = field(default_factory=list)


@dataclass
class NewsItem:
    timestamp: datetime
    source: str
    title: str
    body: str
    sentiment: float  # -1..+1
    event_tags: list[str] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class PnLHistory:
    dates: list[datetime]
    equity: list[float]
    daily_returns: list[float]
    drawdown: list[float]
    trades: list[dict[str, Any]]  # one dict per closed trade


@dataclass
class RiskState:
    daily_loss_used: float
    daily_loss_limit: float
    weekly_loss_used: float
    weekly_loss_limit: float
    max_drawdown: float
    kill_switch: bool
    circuit_breakers: list[str]


@dataclass
class BotConfig:
    data: dict[str, Any]


# ===========================================================================
# DataProvider interface & mock implementation
# ===========================================================================


class DataProvider(ABC):
    """Abstract data layer — swap in a real broker adapter for production."""

    @abstractmethod
    def get_account(self) -> AccountSnapshot: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_signals(self, lookback_hours: int = 24) -> list[Signal]: ...

    @abstractmethod
    def get_news(self, lookback_hours: int = 24) -> list[NewsItem]: ...

    @abstractmethod
    def get_pnl_history(self) -> PnLHistory: ...

    @abstractmethod
    def get_risk_state(self) -> RiskState: ...

    @abstractmethod
    def get_config(self) -> BotConfig: ...

    @abstractmethod
    def update_config(self, key: str, value: Any) -> bool: ...


# ---- Mock provider ---------------------------------------------------------


class MockDataProvider(DataProvider):
    """Synthetic data that refreshes each call to simulate a live feed.

    State is seeded once and then perturbed with time-based pseudo-randomness
    so the dashboard feels alive but remains deterministic enough for demos.
    """

    SOURCES = [
        "Moneycontrol",
        "Economic Times",
        "LiveMint",
        "Business Standard",
        "NDTV Profit",
        "Reuters",
        "Bloomberg",
    ]
    TICKERS = [
        "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
        "ITC", "LT", "AXISBANK", "KOTAKBANK", "BHARTIARTL",
    ]
    EVENTS = ["RBI", "Fed", "GDP", "Inflation", "OPEC", "Crude", "Election", "Budget", "Earnings"]

    def __init__(self, seed: int = 7) -> None:
        self._seed = seed
        self._base_rng = np.random.default_rng(seed)
        self._start_equity = 1_000_000.0
        self._config = self._generate_config()
        # Pre-generate a 60-day equity curve.
        self._history = self._generate_history(60)
        # Pre-generate news, signals, and positions once.
        self._positions = self._generate_positions()
        self._signals = self._generate_signals(60)
        self._news = self._generate_news(50)

    # ----- helpers --------------------------------------------------------
    def _rng(self) -> np.random.Generator:
        # Time-varying seed so each refresh slightly perturbs the data.
        return np.random.default_rng(int(time.time()) % 1_000_000 + self._seed)

    def _generate_history(self, n_days: int) -> PnLHistory:
        rng = self._base_rng
        dates = [datetime.now() - timedelta(days=n_days - i) for i in range(n_days)]
        ret = rng.normal(0.0005, 0.012, n_days)
        equity = [self._start_equity]
        for r in ret[1:]:
            equity.append(equity[-1] * (1.0 + r))
        running_max = np.maximum.accumulate(equity)
        drawdown = (np.array(equity) / running_max - 1.0).tolist()
        trades = [
            {
                "entry_time": dates[max(i - 1, 0)],
                "exit_time": dates[i],
                "pnl": float(rng.normal(800, 4000)),
                "symbol": str(rng.choice(self.TICKERS)),
            }
            for i in range(1, n_days)
            if rng.random() > 0.4
        ]
        return PnLHistory(
            dates=dates,
            equity=equity,
            daily_returns=ret.tolist(),
            drawdown=drawdown,
            trades=trades,
        )

    def _generate_positions(self) -> list[Position]:
        rng = self._base_rng
        n = int(rng.integers(0, 6))
        positions: list[Position] = []
        for i in range(n):
            sym = str(rng.choice(self.TICKERS))
            side = "LONG" if rng.random() > 0.4 else "SHORT"
            qty = int(rng.integers(15, 150))
            entry = float(rng.uniform(100, 4000))
            current = entry * float(1 + rng.normal(0, 0.04))
            pnl = (current - entry) * qty if side == "LONG" else (entry - current) * qty
            positions.append(
                Position(
                    symbol=sym,
                    side=side,
                    qty=qty,
                    entry=round(entry, 2),
                    current=round(current, 2),
                    pnl=round(pnl, 2),
                    pnl_pct=round((pnl / max(entry * qty, 1)) * 100, 2),
                    greeks=Greeks(
                        delta=round(float(rng.normal(0.5, 0.2)), 3),
                        gamma=round(float(rng.normal(0.02, 0.01)), 4),
                        theta=round(float(rng.normal(-5, 2)), 2),
                        vega=round(float(rng.normal(10, 4)), 2),
                    ),
                    exit_plan="Target: +2% / SL: -1% / Time stop: 3:15 PM",
                    dte=int(rng.integers(1, 14)),
                )
            )
        return positions

    def _generate_signals(self, n: int) -> list[Signal]:
        rng = self._base_rng
        strategies = ["EMACross", "RSIMeanReversion", "BollingerBreakout", "IronCondor", "Straddle"]
        directions = ["BUY", "SELL"]
        now = datetime.now()
        return [
            Signal(
                timestamp=now - timedelta(minutes=int(rng.integers(0, 60 * 24))),
                strategy=str(rng.choice(strategies)),
                confidence=round(float(rng.uniform(0.5, 0.95)), 2),
                direction=str(rng.choice(directions)),
                reasoning=str(
                    rng.choice(
                        [
                            "EMA9 crossed above EMA21 on 5-min with RSI 38",
                            "IV rank 78% — sell straddle for premium",
                            "Volume spike + Bollinger breakout",
                            "Mean reversion setup, RSI 28 on NIFTY",
                            "Expiry-day theta capture",
                        ]
                    )
                ),
                news_context=[
                    f"RBI policy decision due {now.strftime('%b %d')}",
                    "Crude up 1.2% on OPEC commentary",
                ][: int(rng.integers(0, 3))],
            )
            for _ in range(n)
        ]

    def _generate_news(self, n: int) -> list[NewsItem]:
        rng = self._base_rng
        now = datetime.now()
        items: list[NewsItem] = []
        templates = [
            ("RBI keeps repo rate unchanged at 6.5%", "The Reserve Bank of India..."),
            ("NIFTY hits fresh all-time high; banks lead", "Indian benchmarks rallied..."),
            ("Crude slips as OPEC+ mulls output hike", "Brent crude fell 1.4%..."),
            ("TCS Q3 results beat street estimates", "Tata Consultancy Services reported..."),
            ("FIIs turn net buyers after 5 sessions", "Foreign institutional investors..."),
            ("GDP growth slows to 6.2% in Q2", "India's GDP growth slowed to..."),
            ("Rupee falls 20 paise against US dollar", "The Indian rupee weakened..."),
            ("HDFC Bank announces bonus issue", "HDFC Bank's board approved..."),
            ("OPEC+ extends production cuts", "Saudi-led OPEC and allies..."),
            ("Election results lift sentiment", "Coalition wins state elections..."),
        ]
        for i in range(n):
            title, body = templates[i % len(templates)]
            sentiment = float(rng.uniform(-1.0, 1.0))
            items.append(
                NewsItem(
                    timestamp=now - timedelta(minutes=int(rng.integers(0, 60 * 48))),
                    source=str(rng.choice(self.SOURCES)),
                    title=title,
                    body=body,
                    sentiment=round(sentiment, 3),
                    event_tags=[str(e) for e in rng.choice(self.EVENTS, size=int(rng.integers(0, 2)), replace=False)],
                    tickers=[str(t) for t in rng.choice(self.TICKERS, size=int(rng.integers(1, 3)), replace=False)],
                    url=f"https://example.com/news/{i}",
                )
            )
        return items

    def _generate_config(self) -> BotConfig:
        return BotConfig(
            data={
                "risk.max_daily_loss_pct": 1.5,
                "risk.max_weekly_loss_pct": 4.0,
                "risk.max_drawdown_pct": 8.0,
                "risk.kill_switch_loss_pct": 12.0,
                "strategy.active": ["EMACross", "RSIMeanReversion"],
                "execution.max_lots_per_trade": 6,
                "execution.slippage_bps": 2,
                "broker.symbol": "NIFTY",
                "broker.lot_size": 25,
                "schedule.market_open": "09:15",
                "schedule.market_close": "15:30",
                "schedule.square_off": "15:15",
                "alerts.telegram_enabled": True,
            }
        )

    # ----- DataProvider API ---------------------------------------------
    def get_account(self) -> AccountSnapshot:
        rng = self._rng()
        eq = float(self._history.equity[-1]) * (1.0 + float(rng.normal(0, 0.001)))
        day_pnl = float(rng.normal(2500, 8000))
        week_pnl = day_pnl * 3 + float(rng.normal(0, 4000))
        regime = str(rng.choice(["Trending", "Range", "Volatile"]))
        return AccountSnapshot(
            equity=round(eq, 2),
            day_pnl=round(day_pnl, 2),
            week_pnl=round(week_pnl, 2),
            open_positions=len(self._positions),
            regime=regime,
            drawdown=round(float(self._history.drawdown[-1]), 4),
        )

    def get_positions(self) -> list[Position]:
        # Slightly perturb current prices each call.
        rng = self._rng()
        out: list[Position] = []
        for p in self._positions:
            new_cur = p.current * (1.0 + float(rng.normal(0, 0.002)))
            pnl = (new_cur - p.entry) * p.qty if p.side == "LONG" else (p.entry - new_cur) * p.qty
            out.append(
                Position(
                    symbol=p.symbol,
                    side=p.side,
                    qty=p.qty,
                    entry=p.entry,
                    current=round(new_cur, 2),
                    pnl=round(pnl, 2),
                    pnl_pct=round((pnl / max(p.entry * p.qty, 1)) * 100, 2),
                    greeks=p.greeks,
                    exit_plan=p.exit_plan,
                    dte=p.dte,
                )
            )
        return out

    def get_signals(self, lookback_hours: int = 24) -> list[Signal]:
        return self._signals

    def get_news(self, lookback_hours: int = 24) -> list[NewsItem]:
        return self._news

    def get_pnl_history(self) -> PnLHistory:
        return self._history

    def get_risk_state(self) -> RiskState:
        rng = self._rng()
        daily_used = float(rng.uniform(0, 1.0))
        weekly_used = float(rng.uniform(0, 3.5))
        return RiskState(
            daily_loss_used=round(daily_used, 3),
            daily_loss_limit=1.5,
            weekly_loss_used=round(weekly_used, 3),
            weekly_loss_limit=4.0,
            max_drawdown=round(float(self._history.drawdown[-1]) * 100, 3),
            kill_switch=bool(daily_used > 1.4 or weekly_used > 3.8),
            circuit_breakers=[
                b
                for b, on in {
                    "Spread widening": rng.random() > 0.7,
                    "Volatility spike": rng.random() > 0.85,
                    "News black-out": rng.random() > 0.9,
                }.items()
                if on
            ],
        )

    def get_config(self) -> BotConfig:
        return self._config

    def update_config(self, key: str, value: Any) -> bool:
        self._config.data[key] = value
        logger.info(f"MockDataProvider: config[{key}] = {value!r}")
        return True


# ===========================================================================
# Provider cache (Streamlit)
# ===========================================================================

@st.cache_resource
def get_provider() -> DataProvider:
    """Return a cached ``DataProvider`` instance.

    For production this would attempt to import the live broker adapter and
    fall back to ``MockDataProvider`` if it fails. We always return the mock
    here so the dashboard works without broker credentials.
    """
    return MockDataProvider()


# ===========================================================================
# Sidebar
# ===========================================================================


def _ist_now() -> datetime:
    """Return current time in IST. (Naive — assumes the host clock is IST.)"""
    return datetime.now()


def _market_state(now: datetime) -> tuple[str, str]:
    """Return ``(label, css_class)`` for the current market state."""
    t = now.time()
    if t < dtime(9, 0):
        return "Pre-market", "badge-blue"
    if t < dtime(9, 15):
        return "Opening range", "badge-amber"
    if t < dtime(15, 15):
        return "Live", "badge-green"
    if t <= dtime(15, 30):
        return "Square-off", "badge-amber"
    return "Closed", "badge-red"


def render_sidebar() -> DataProvider:
    """Render the persistent sidebar and return the active data provider."""
    provider = get_provider()
    account = provider.get_account()
    risk = provider.get_risk_state()
    now = _ist_now()
    state_label, state_class = _market_state(now)

    with st.sidebar:
        st.markdown("## 🤖 Kotak Neo Bot")
        st.caption(f"Status: 🟢 Connected (mock)" if not risk.kill_switch else "Status: 🔴 KILL SWITCH")

        st.markdown("---")
        st.markdown(f"**IST**: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        st.markdown(
            f"**Market**: <span class='badge {state_class}'>{state_label}</span>",
            unsafe_allow_html=True,
        )
        st.markdown(f"**Regime**: {account.regime}")

        st.markdown("---")
        st.markdown("### Quick stats")
        st.metric("Equity", f"₹{account.equity:,.0f}")
        st.metric(
            "Day P&L",
            f"₹{account.day_pnl:,.0f}",
            delta=f"{account.day_pnl:,.0f}",
            delta_color="normal",
        )
        st.metric("Open positions", account.open_positions)
        st.markdown("---")
        st.caption("v0.1.0 · mock data layer")
    return provider


# ===========================================================================
# Pages
# ===========================================================================


def _color_pnl(value: float) -> str:
    if value > 0:
        return f"<span class='positive'>+{value:,.2f}</span>"
    if value < 0:
        return f"<span class='negative'>{value:,.2f}</span>"
    return f"<span class='neutral'>{value:,.2f}</span>"


def page_overview(provider: DataProvider) -> None:
    st.title("📊 Overview")
    acc = provider.get_account()
    risk = provider.get_risk_state()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"<div class='metric-card'><h4>Equity</h4><h2>₹{acc.equity:,.0f}</h2></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"<div class='metric-card'><h4>Day P&L</h4><h2>{_color_pnl(acc.day_pnl)}</h2></div>",
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"<div class='metric-card'><h4>Week P&L</h4><h2>{_color_pnl(acc.week_pnl)}</h2></div>",
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"<div class='metric-card'><h4>Open Positions</h4><h2>{acc.open_positions}</h2></div>",
            unsafe_allow_html=True,
        )

    st.markdown("### Market regime")
    regime_class = {
        "Trending": "badge-green",
        "Range": "badge-blue",
        "Volatile": "badge-amber",
    }.get(acc.regime, "badge-blue")
    st.markdown(
        f"Current regime: <span class='badge {regime_class}'>{acc.regime}</span>",
        unsafe_allow_html=True,
    )
    st.progress(min(max(0.5 + acc.drawdown, 0.0), 1.0))
    st.caption(f"Drawdown from peak: {acc.drawdown * 100:.2f}%")

    st.markdown("### Risk")
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Daily loss used", f"{risk.daily_loss_used:.2f}% / {risk.daily_loss_limit:.2f}%")
    rc2.metric("Weekly loss used", f"{risk.weekly_loss_used:.2f}% / {risk.weekly_loss_limit:.2f}%")
    rc3.metric("Kill switch", "ARMED" if risk.kill_switch else "off")

    st.markdown("### Recent equity")
    hist = provider.get_pnl_history()
    df = pd.DataFrame({"date": hist.dates, "equity": hist.equity})
    fig = px.line(df, x="date", y="equity", title="Equity Curve (60d)")
    fig.update_layout(height=300, margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig, use_container_width=True)


def page_positions(provider: DataProvider) -> None:
    st.title("💼 Positions")
    positions = provider.get_positions()
    if not positions:
        st.info("No open positions.")
        return

    rows = []
    for p in positions:
        rows.append(
            {
                "Symbol": p.symbol,
                "Side": p.side,
                "Qty": p.qty,
                "Entry": p.entry,
                "Current": p.current,
                "P&L": p.pnl,
                "P&L %": p.pnl_pct,
                "Δ": p.greeks.delta,
                "Γ": p.greeks.gamma,
                "Θ": p.greeks.theta,
                "V": p.greeks.vega,
                "DTE": p.dte,
                "Exit plan": p.exit_plan,
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("### Greeks exposure")
    greeks_df = df[["Symbol", "Δ", "Γ", "Θ", "V"]].copy()
    greeks_df[["Δ", "Γ", "Θ", "V"]] = greeks_df[["Δ", "Γ", "Θ", "V"]].apply(pd.to_numeric)
    fig = go.Figure()
    for greek, color in [("Δ", "#3b82f6"), ("Γ", "#10b981"), ("Θ", "#f59e0b"), ("V", "#8b5cf6")]:
        fig.add_trace(go.Bar(name=greek, x=greeks_df["Symbol"], y=greeks_df[greek], marker_color=color))
    fig.update_layout(barmode="group", height=350, title="Per-position Greeks")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Exit plans")
    for p in positions:
        with st.expander(f"{p.symbol} — {p.side} {p.qty}"):
            st.write(f"Entry: ₹{p.entry:,.2f}")
            st.write(f"Current: ₹{p.current:,.2f}")
            st.write(f"P&L: {p.pnl:,.2f} ({p.pnl_pct:+.2f}%)")
            st.write(f"DTE: {p.dte}")
            st.info(f"Exit plan: {p.exit_plan}")


def page_signals(provider: DataProvider) -> None:
    st.title("🎯 Signals (last 24h)")
    signals = provider.get_signals(lookback_hours=24)
    if not signals:
        st.info("No signals in the last 24 hours.")
        return

    rows = [
        {
            "Time": s.timestamp.strftime("%Y-%m-%d %H:%M"),
            "Strategy": s.strategy,
            "Direction": s.direction,
            "Confidence": s.confidence,
            "Reasoning": s.reasoning,
        }
        for s in signals
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("### Confidence distribution")
    fig = px.histogram(
        df,
        x="Confidence",
        nbins=10,
        color="Strategy",
        title="Signal confidence by strategy",
    )
    fig.update_layout(height=320)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### News context for latest signal")
    if signals:
        latest = signals[0]
        st.write(f"**{latest.strategy}** @ {latest.timestamp:%Y-%m-%d %H:%M}")
        for line in latest.news_context:
            st.write(f"- {line}")


def page_news(provider: DataProvider) -> None:
    st.title("📰 News Feed")
    news = provider.get_news(lookback_hours=48)
    if not news:
        st.info("No news available.")
        return

    # Filter controls
    f1, f2, f3 = st.columns(3)
    with f1:
        source_filter = st.multiselect(
            "Source", sorted({n.source for n in news}), default=[]
        )
    with f2:
        event_filter = st.multiselect(
            "Event tag", sorted({e for n in news for e in n.event_tags}), default=[]
        )
    with f3:
        sentiment_filter = st.slider("Min |sentiment|", 0.0, 1.0, 0.0, 0.05)

    filtered = news
    if source_filter:
        filtered = [n for n in filtered if n.source in source_filter]
    if event_filter:
        filtered = [n for n in filtered if any(e in event_filter for e in n.event_tags)]
    if sentiment_filter > 0:
        filtered = [n for n in filtered if abs(n.sentiment) >= sentiment_filter]

    rows = [
        {
            "Time": n.timestamp.strftime("%Y-%m-%d %H:%M"),
            "Source": n.source,
            "Title": n.title,
            "Sentiment": round(n.sentiment, 3),
            "Events": ", ".join(n.event_tags) or "—",
            "Tickers": ", ".join(n.tickers) or "—",
        }
        for n in filtered
    ]
    if not rows:
        st.warning("No items match the current filters.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Sentiment timeline
    fig = go.Figure()
    df_sorted = df.assign(Time=pd.to_datetime(df["Time"])).sort_values("Time")
    fig.add_trace(
        go.Scatter(
            x=df_sorted["Time"],
            y=df_sorted["Sentiment"],
            mode="markers",
            marker=dict(
                size=10,
                color=df_sorted["Sentiment"],
                colorscale="RdYlGn",
                cmin=-1,
                cmax=1,
                showscale=True,
                colorbar=dict(title="Sentiment"),
            ),
            text=df_sorted["Title"],
            hovertemplate="<b>%{text}</b><br>%{x}<br>Sentiment: %{y:.2f}<extra></extra>",
        )
    )
    fig.update_layout(height=320, title="News sentiment over time")
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig, use_container_width=True)


def page_pnl_history(provider: DataProvider) -> None:
    st.title("📈 P&L History")
    hist = provider.get_pnl_history()
    df = pd.DataFrame(
        {
            "date": hist.dates,
            "equity": hist.equity,
            "daily_return": hist.daily_returns,
            "drawdown": hist.drawdown,
        }
    )

    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(df, x="date", y="equity", title="Equity Curve")
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.area(df, x="date", y="drawdown", title="Drawdown", color_discrete_sequence=["#ef4444"])
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Daily returns")
    fig = px.bar(df, x="date", y="daily_return", title="Daily Returns", color="daily_return",
                 color_continuous_scale="RdYlGn")
    fig.update_layout(height=300)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Trade distribution")
    if hist.trades:
        trades_df = pd.DataFrame(hist.trades)
        col1, col2 = st.columns(2)
        with col1:
            fig = px.histogram(trades_df, x="pnl", nbins=20, title="P&L distribution",
                               color_discrete_sequence=["#3b82f6"])
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            win_rate = (trades_df["pnl"] > 0).mean() * 100
            st.metric("Win rate", f"{win_rate:.1f}%")
            st.metric("Total trades", len(trades_df))
            st.metric("Avg P&L / trade", f"₹{trades_df['pnl'].mean():,.0f}")
            st.metric("Best trade", f"₹{trades_df['pnl'].max():,.0f}")
            st.metric("Worst trade", f"₹{trades_df['pnl'].min():,.0f}")
    else:
        st.info("No closed trades in this period.")


def page_risk(provider: DataProvider) -> None:
    st.title("🛡️ Risk")
    risk = provider.get_risk_state()
    acc = provider.get_account()

    c1, c2, c3 = st.columns(3)
    c1.metric("Daily loss used", f"{risk.daily_loss_used:.2f}%", f"limit {risk.daily_loss_limit:.2f}%")
    c2.metric("Weekly loss used", f"{risk.weekly_loss_used:.2f}%", f"limit {risk.weekly_loss_limit:.2f}%")
    c3.metric("Max drawdown", f"{risk.max_drawdown:.2f}%")

    st.markdown("### Kill switch")
    if risk.kill_switch:
        st.error("🔴 KILL SWITCH ARMED — all new orders are blocked.")
    else:
        st.success("🟢 Kill switch off")

    st.markdown("### Circuit breakers")
    if risk.circuit_breakers:
        for cb in risk.circuit_breakers:
            st.warning(f"⚠️  {cb}")
    else:
        st.info("All circuit breakers clear.")

    st.markdown("### Position concentration")
    positions = provider.get_positions()
    if positions:
        df = pd.DataFrame(
            [{"symbol": p.symbol, "value": p.entry * p.qty, "side": p.side} for p in positions]
        )
        fig = px.pie(df, names="symbol", values="value", title="Capital at risk by symbol", hole=0.4)
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No positions to analyse.")


def page_backtest(_provider: DataProvider) -> None:
    st.title("🧪 Backtest")
    if not _HAS_BACKTEST:
        st.error("backtest module not importable. Install vectorbt + pandas_ta.")
        return

    with st.form("backtest_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            strategy_name = st.selectbox(
                "Strategy",
                ["EMACross", "RSIMeanReversion", "BollingerBreakout"],
            )
            symbol = st.selectbox("Symbol", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
        with c2:
            capital = st.number_input("Capital (₹)", value=1_000_000, step=50_000)
            slippage = st.number_input("Slippage (bps)", value=2.0, step=0.5)
        with c3:
            n_bars = st.slider("Bars (5-min)", 500, 10_000, 3000, 500)
            seed = st.number_input("Seed", value=42, step=1)
        run_button = st.form_submit_button("Run backtest")

    if not run_button:
        st.info("Configure and click **Run backtest**.")
        return

    with st.spinner("Running backtest…"):
        try:
            cfg = BacktestConfig(
                initial_capital=float(capital),
                symbol=symbol,
                slippage_bps=float(slippage),
            )
            engine = BacktestEngine(cfg)
            df = generate_synthetic_data(n_bars=int(n_bars), seed=int(seed))
            engine.load_data(df)
            strategy_cls = {
                "EMACross": EMACrossStrategy,
                "RSIMeanReversion": RSIMeanReversionStrategy,
                "BollingerBreakout": BollingerBreakoutStrategy,
            }[strategy_name]
            strategy = strategy_cls()
            result = engine.run(strategy)
        except Exception as exc:
            logger.exception("Backtest failed")
            st.error(f"Backtest failed: {exc}")
            return

    st.success("Backtest complete.")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total return", f"{result.metrics['total_return']:+.2%}")
    m2.metric("Sharpe", f"{result.metrics['sharpe']:.2f}")
    m3.metric("Sortino", f"{result.metrics['sortino']:.2f}")
    m4.metric("Max DD", f"{result.metrics['max_drawdown']:+.2%}")
    m5.metric("Trades", int(result.metrics['n_trades']))

    eq = result.equity_curve
    fig = px.line(x=eq.index, y=eq.values, title="Equity Curve",
                  labels={"x": "Time", "y": "Portfolio Value (₹)"})
    fig.update_layout(height=350)
    st.plotly_chart(fig, use_container_width=True)

    if not result.trades.empty:
        st.markdown("### Trade log")
        st.dataframe(result.trades, use_container_width=True, hide_index=True)

    with st.expander("Raw metrics JSON"):
        st.code(json.dumps(result.metrics, indent=2, default=str), language="json")


def page_config(provider: DataProvider) -> None:
    st.title("⚙️ Config")
    cfg = provider.get_config()
    st.warning(
        "Any change is applied live. Use the **Confirm** checkbox before saving."
    )

    new_data: dict[str, Any] = dict(cfg.data)
    for key, value in cfg.data.items():
        with st.container():
            col1, col2, col3 = st.columns([3, 3, 1])
            col1.code(key, language="yaml")
            if isinstance(value, bool):
                updated = col2.checkbox(f"value", value=value, key=f"cb_{key}")
            elif isinstance(value, (int, float)):
                updated = col2.number_input(
                    f"value", value=float(value), key=f"ni_{key}"
                )
            elif isinstance(value, list):
                txt = col2.text_input(
                    f"value (comma-separated)", value=",".join(map(str, value)), key=f"li_{key}"
                )
                updated = [s.strip() for s in txt.split(",") if s.strip()]
            else:
                updated = col2.text_input(f"value", value=str(value), key=f"ti_{key}")
            confirm = col3.checkbox("Confirm", key=f"cf_{key}")
            if confirm:
                new_data[key] = updated

    if st.button("Save changes"):
        changed = {k: v for k, v in new_data.items() if v != cfg.data.get(k)}
        if not changed:
            st.info("No changes to save.")
            return
        for k, v in changed.items():
            provider.update_config(k, v)
        st.success(f"Updated {len(changed)} keys.")
        st.rerun()


# ===========================================================================
# Page registry & main entry
# ===========================================================================

PAGES = {
    "Overview": page_overview,
    "Positions": page_positions,
    "Signals": page_signals,
    "News": page_news,
    "P&L History": page_pnl_history,
    "Risk": page_risk,
    "Backtest": page_backtest,
    "Config": page_config,
}


def main() -> None:
    provider = render_sidebar()
    page_name = st.radio(
        "Page",
        list(PAGES.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )
    PAGES[page_name](provider)


if __name__ == "__main__":
    # Allow ``python dashboard/app.py`` to launch the dashboard too, although
    # the canonical entry point is ``streamlit run dashboard/app.py``.
    main()
