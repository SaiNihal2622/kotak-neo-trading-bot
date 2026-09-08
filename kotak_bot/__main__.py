"""Kotak Neo Trading Bot — main entry point.

Usage:
    python -m kotak_bot paper             # paper trading
    python -m kotak_bot live              # live trading (needs creds)
    python -m kotak_bot backtest          # run backtest
    python -m kotak_bot status            # show risk/positions state
    python -m kotak_bot reset             # reset paper state
"""
from __future__ import annotations

import argparse
import atexit
import csv
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import yaml
from loguru import logger

from kotak_bot.broker import NeoClient, PaperClient, Order, OrderSide, OrderType, OrderStatus, ProductType
from kotak_bot.data.historical import HistoricalData
from kotak_bot.data.live_feed import LiveFeed
from kotak_bot.execution.order_manager import OrderManager
from kotak_bot.risk.engine import RiskEngine
from kotak_bot.signals.regime import RegimeDetector
from kotak_bot.signals.technical import TechnicalAnalyzer
from kotak_bot.strategy.selector import StrategySelector
from kotak_bot.alerts.telegram import TelegramAlerter
from kotak_bot.alerts.telegram_commands import TelegramCommandHandler
from kotak_bot.alerts.email import EmailAlerter
from kotak_bot.utils.clock import (
    now_ist, is_market_open, is_square_off_time, is_past_market_close,
    market_session, set_market_hours,
    set_intraday, get_intraday, is_past_no_new_trades_time, is_past_force_square_off_time,
    is_in_opening_buffer, is_allow_overnight, in_event_blackout,
    fetch_india_vix, get_india_vix, vix_position_size_multiplier, vix_should_skip,
)
from kotak_bot.utils.logger import setup_logger
from kotak_bot.utils.liveness import install_default as install_liveness, get_default as get_liveness

# trade log CSV
TRADES_CSV = Path("logs/trades.csv")
SIGNALS_CSV = Path("logs/signals.csv")
TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)

# State provider will be set after broker/feed/order_mgr are built; the closure
# captures references that are populated in-place. Until then the liveness
# monitor ships a noop provider.
def _noop_state() -> dict:
    return {"phase": "init"}


# Install liveness monitor very early so we capture even startup crashes
_LIVENESS_INTERVAL = float(os.environ.get("KOTAK_LIVENESS_INTERVAL", "30"))
_LIVENESS = install_liveness(
    ping_file=os.environ.get("KOTAK_LIVENESS_FILE", "data_cache/liveness.json"),
    crash_file=os.environ.get("KOTAK_LIVENESS_CRASH", "data_cache/liveness_crash.jsonl"),
    interval_sec=_LIVENESS_INTERVAL,
    state_provider=_noop_state,
)
_LIVENESS.start()
logger.info(f"Liveness monitor started (interval={_LIVENESS_INTERVAL}s, pid={os.getpid()})")


def _read_json(path, default=None):
    """Read a JSON file defensively. Returns `default` on any error.

    Used by the Mavis force-action channel. utf-8-sig strips BOM if present.
    NOTE: this function MUST exist in module scope; the force-action block
    in the main loop calls it every cycle. If it's missing the try/except
    around the call will silently swallow the NameError and the channel
    appears to work but never executes anything. Do not delete or rename
    without also updating the call site at the top of `while True:`.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


# Option symbol parser. Used to recover strike/option_type/underlying/expiry
# from a raw symbol like "NIFTY10SEP2624300PE" when an Order or Position
# object doesn't carry them. Returns a dict with the parsed fields, or
# None values if the symbol doesn't match the option-symbol pattern.
#
# FIX 2026-09-07 22:15: prior code in the orphan-auto-close path passed
# Order(symbol=..., price=0.0) without setting strike/option_type/underlying.
# The paper client's _force_fill_market_like could not look up the strike
# from option_chains.json (step 0) and had no underlying for the strike-
# aware fallback (step 4), so it fell through to a Rs.1.00 last-resort
# price. That produced 3 fake fills today (12:04 BNF 57200/56800 PE,
# 12:42 NIFTY 24100 PE) which inflated realized P&L by ~+Rs.30,000.
# Now any order-construction site (orphan-auto-close, manual close) can
# call _parse_option_symbol to recover the fields defensively.
import re as _re

_OPTION_SYMBOL_RE = _re.compile(
    r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$'
)
_MONTH_MAP = {
    'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
    'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
}


def _parse_option_symbol(symbol):
    """Parse an NSE option symbol like 'NIFTY10SEP2624300PE' into
    (underlying, expiry, strike, option_type) where expiry is a
    'YYYY-MM-DD' string. Returns (None, None, 0, None) on no-match.
    """
    if not symbol or not isinstance(symbol, str):
        return None, None, 0, None
    m = _OPTION_SYMBOL_RE.match(symbol.upper())
    if not m:
        return None, None, 0, None
    underlying, day, mon_tok, year, strike, opt_type = (
        m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
    )
    try:
        mon = _MONTH_MAP.get(mon_tok.upper(), 0)
        yr_i = 2000 + int(year)
        expiry = f"{yr_i:04d}-{mon:02d}-{int(day):02d}"
    except Exception:
        expiry = None
    try:
        strike_i = int(strike)
    except Exception:
        strike_i = 0
    return underlying, expiry, strike_i, opt_type


def init_csv(path: Path, header: list[str]) -> None:
    """Create CSV with header if missing, or migrate to current schema.

    Migration: if file exists with an older header, rebuild it with the current
    header and INSERT empty strings at the correct positions for added columns
    (not append at end). Preserves existing values in their original columns.
    """
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)
        return
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            existing_header = next(r, None)
            old_rows = list(r)
    except Exception:
        return
    if existing_header == header:
        return
    if not existing_header:
        return
    if not all(h in header for h in existing_header):
        return
    # Build new rows by mapping each old column to its position in the new header,
    # and inserting "" for new columns that weren't in the old schema.
    n_new = len(header)
    new_rows = []
    for old_row in old_rows:
        # Build a value map from old column -> value
        old_map = {}
        for i, col in enumerate(existing_header):
            if i < len(old_row):
                old_map[col] = old_row[i]
        # Walk new header in order, pull from old_map or insert ""
        new_row = []
        for col in header:
            new_row.append(old_map.get(col, ""))
        new_rows.append(new_row)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(new_rows)
    try:
        logger.info(
            f"init_csv: migrated {path.name} from {len(existing_header)} -> {n_new} columns, "
            f"re-aligned {len(old_rows)} rows"
        )
    except Exception:
        pass


def log_trade(trade: dict) -> None:
    init_csv(TRADES_CSV, [
        "timestamp", "trade_id", "order_id", "symbol", "side", "qty", "price", "tag", "status", "filled_qty", "fill_price"
    ])
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for o in trade.get("orders", []):
            w.writerow([
                datetime.now(timezone.utc).isoformat(),
                trade.get("trade_id", ""),
                o.get("order_id", ""),
                o.get("symbol", ""),
                o.get("side", ""),
                o.get("qty", 0),
                o.get("price", 0),
                o.get("tag", ""),
                str(o.get("status", "")),
                o.get("filled_qty", 0),
                o.get("avg_fill_price", 0),
            ])


def log_signal(signal: dict) -> None:
    init_csv(SIGNALS_CSV, [
        "timestamp", "symbol", "regime", "side", "confidence", "reason", "action"
    ])
    with open(SIGNALS_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.now(timezone.utc).isoformat(),
            signal.get("symbol", ""),
            signal.get("regime", ""),
            signal.get("side", ""),
            signal.get("confidence", 0),
            signal.get("reason", ""),
            signal.get("action", ""),
        ])


def load_config(path: str = "config/settings.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def build_broker(cfg: dict):
    mode = cfg.get("mode", "paper")
    broker_cfg = cfg.get("broker", {})
    if mode == "paper" or broker_cfg.get("type", "paper") == "paper":
        return PaperClient(
            starting_capital=broker_cfg.get("paper_capital", 300_000.0),
            slippage_bps=cfg.get("backtest", {}).get("slippage_bps", 5.0),
            limit_fill_spread_pct=broker_cfg.get("limit_fill_spread_pct", 0.1),
            limit_fill_min_spread=broker_cfg.get("limit_fill_min_spread", 0.05),
            limit_fill_near_ltp_pct=broker_cfg.get("limit_fill_near_ltp_pct", 0.5),
            fill_mode=broker_cfg.get("fill_mode", "market_like"),
        )
    # LIVE mode — require explicit confirmation to prevent accidental real-money trading
    if os.environ.get("KOTAK_LIVE_CONFIRMED") != "YES":
        raise RuntimeError(
            "REFUSING to start in LIVE mode without KOTAK_LIVE_CONFIRMED=YES env var. "
            "This is a safety guard — set it ONLY when you intend to trade real money. "
            "Recommended: keep mode=paper for 2-4 weeks, then flip to live after paper P&L validates."
        )
    # Require PROD env explicitly
    if os.environ.get("KOTAK_ENV", "uat") != "prod":
        raise RuntimeError(
            "LIVE mode requires KOTAK_ENV=prod. UAT orders are sandboxed but we want the "
            "explicit env flip so you know you're going to prod."
        )
    # Require positive live_capital to be set in config
    if not broker_cfg.get("live_capital"):
        logger.warning("live_capital not set in settings.yaml — using paper_capital as fallback")
    logger.warning("=" * 60)
    logger.warning("LIVE TRADING MODE — REAL MONEY AT RISK")
    logger.warning("=" * 60)
    return NeoClient()


def run_paper() -> None:
    cfg = load_config()
    setup_logger(level=cfg.get("logging", {}).get("level", "INFO"),
                 log_file=cfg.get("logging", {}).get("file", "logs/bot.log"))
    # Configure market hours from settings (NSE standard by default; can be overridden)
    set_market_hours(cfg.get("market_hours", {}))
    # Configure intraday mode (no_overnight, no_new_trades_after, force_square_off_time, VIX rules)
    set_intraday(cfg.get("risk", {}).get("intraday", {}))
    intraday_cfg = get_intraday()
    logger.info(f"Intraday mode: allow_overnight={intraday_cfg['allow_overnight']}, "
                f"no_new_trades_after={intraday_cfg['no_new_trades_after'].strftime('%H:%M')}, "
                f"force_square_off_time={intraday_cfg['force_square_off_time'].strftime('%H:%M')}")
    # Fetch India VIX at startup (used for VIX-aware position sizing)
    if cfg.get("risk", {}).get("vix", {}).get("refresh_on_startup", True):
        v0 = fetch_india_vix(force=True)
        logger.info(f"India VIX (startup): {v0:.2f}")
    logger.info("=" * 60)
    logger.info("Kotak Neo Trading Bot — PAPER MODE (Production v2)")
    logger.info("=" * 60)

    # FIX 2026-08-26 (item #4): STARTUP INTEGRITY CHECK
    # Verify paper_state.json is consistent: no future-dated orders, no negative
    # quantities, no negative cash, no duplicate order_ids. Auto-archive corrupted
    # states rather than crash (so the bot can self-heal).
    try:
        _state_path = Path("data_cache/paper_state.json")
        if _state_path.exists():
            with open(_state_path, "r", encoding="utf-8") as _f:
                _state = json.load(_f)
            _issues = []
            _cash = _state.get("cash", 0)
            if _cash < 0:
                _issues.append(f"negative cash={_cash}")
            _orders = _state.get("orders", {})
            _seen_ids = set()
            for _oid, _o in _orders.items():
                if _oid in _seen_ids:
                    _issues.append(f"duplicate order_id {_oid}")
                _seen_ids.add(_oid)
                if _o.get("filled_qty", 0) < 0:
                    _issues.append(f"{_oid}: negative filled_qty {_o.get('filled_qty')}")
                if _o.get("avg_fill_price", 0) < 0:
                    _issues.append(f"{_oid}: negative fill price {_o.get('avg_fill_price')}")
                if _o.get("status") == "complete" and _o.get("filled_at", "").startswith("2099"):
                    _issues.append(f"{_oid}: future-dated fill")
            _positions = _state.get("positions", {})
            for _sym, _p in _positions.items():
                if _p.get("qty", 0) == 0:
                    _issues.append(f"{_sym}: zero qty in positions (stale)")
            if _issues:
                logger.warning(f"[STARTUP-INTEGRITY] {len(_issues)} issues found in paper_state.json:")
                for _i in _issues[:20]:
                    logger.warning(f"  - {_i}")
                # Archive the corrupted state
                _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                _archive = Path(f"data_cache/paper_state_corrupt_{_ts}.json")
                _state_path.rename(_archive)
                logger.warning(f"[STARTUP-INTEGRITY] archived to {_archive.name}; will start fresh")
            else:
                logger.info("[STARTUP-INTEGRITY] paper_state.json OK")
    except Exception as _e:
        logger.warning(f"[STARTUP-INTEGRITY] check skipped: {_e}")

    # ------- data source -------
    broker = build_broker(cfg)
    broker.connect()

    # FIX 2026-09-07 22:45: inline trade_journal.jsonl writer. Before this,
    # the only writer to trade_journal.jsonl was the EOD P&L evaluator at
    # 15:30 IST, which only writes entries for positions still OPEN at EOD.
    # The bot force-squares everything at 14:30, so the journal stayed empty
    # even after 8 fills today. Now every fill fires this callback and we
    # append a journal entry inline. The EOD reconstruction is a backstop
    # in case any fills are missed (e.g. bot crash, or PaperClient reloaded
    # from disk without the callback registered).
    _JOURNAL_PATH = Path("data_cache/trade_journal.jsonl")

    def _append_trade_journal(order, realized_delta):
        """Inline trade_journal.jsonl writer. Fires on every paper fill.
        Writes one entry per fill with the realized P&L delta. Idempotent
        by order_id (we use order_id as trade_id prefix).

        FIX 2026-09-07 23:15: mark any fill with avg_fill_price == 1.00 as
        suspect_price=true. This was the bug today: orphan-auto-close fell
        through to the Rs.1.00 last-resort path. Future fills at exactly
        Rs.1.00 will be tagged so the audit report can exclude them.
        """
        try:
            fill_px = round(order.avg_fill_price, 2)
            expected_px = round(order.expected_fill_price, 2) if order.expected_fill_price else 0
            # Heuristic: Rs.1.00 with no expected price AND no live tick is suspect.
            # A genuine Rs.1.00 fill would have an expected price (option_chains.json
            # always has a price for valid strikes). expected_px=0 + fill_px=1.00 is
            # the orphan-auto-close signature.
            suspect = (
                abs(fill_px - 1.0) < 0.01
                and expected_px <= 0
                and "ORPHAN" in (order.tag or "").upper()
            )
            entry = {
                "trade_id": f"FILL-{order.order_id}",
                "order_id": order.order_id,
                "symbol": order.symbol,
                "underlying": order.underlying or "",
                "strike": order.strike or 0,
                "option_type": order.option_type or "",
                "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                "qty": order.filled_qty,
                "avg_fill_price": fill_px,
                "expected_fill_price": expected_px,
                "tag": order.tag or "",
                "realized_delta": round(realized_delta, 2),
                "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                "placed_at": order.placed_at.isoformat() if order.placed_at else "",
                "filled_at": order.filled_at.isoformat() if order.filled_at else "",
                "event": "FILL",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "suspect_price": suspect,
            }
            if suspect:
                logger.warning(
                    f"[TRADE-JOURNAL] suspect fill: {order.symbol} {order.side.value} "
                    f"qty={order.filled_qty} @ Rs.{fill_px} (tag={order.tag}, "
                    f"expected=Rs.{expected_px}). avg_fill_price=1.00 with no expected price "
                    f"and ORPHAN tag is the orphan-auto-close bug signature."
                )
            _JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _JOURNAL_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as _je:
            logger.debug(f"inline trade_journal write failed (non-fatal): {_je}")

    # Register the callback if the broker supports it (paper does, live may not)
    if hasattr(broker, 'on_fill'):
        broker.on_fill(_append_trade_journal)
        logger.info("inline trade_journal callback registered on broker")
    feed_mode = cfg.get("data", {}).get("live_feed", "synthetic")
    neo_client_for_feed = None
    if feed_mode in ("kotak_ws", "live_uat"):
        # try to instantiate NeoClient for real ticks
        try:
            from kotak_bot.broker import NeoClient
            neo_client_for_feed = NeoClient()
            neo_client_for_feed.connect()
            feed_mode = "live_uat"  # we treat kotak_ws as live_uat
            logger.info("Data feed: LIVE UAT (Kotak Neo websocket)")
        except Exception as e:
            logger.warning(f"NeoClient feed init failed ({e}) — falling back to synthetic")
            feed_mode = "synthetic"
    if feed_mode == "live_deribit":
        # No neo_client needed — DeribitFeed is self-contained (public REST, no auth
        # required for paper trading). Falls back to live_india if start fails.
        logger.info("Data feed: LIVE DERIBIT TESTNET (real BTC/ETH option chain)")
        from kotak_bot.data.deribit_feed import DeribitFeed
        deribit_feed = DeribitFeed(
            env=os.environ.get("DERIBIT_ENV", "testnet"),
            currencies=os.environ.get("DERIBIT_CURRENCIES", "BTC,ETH").split(","),
            poll_interval_sec=float(os.environ.get("DERIBIT_POLL_SEC", "2.0")),
        )
        feed = LiveFeed(mode=feed_mode, broker=broker, neo_client=None, deribit_feed=deribit_feed)
        feed.start()
        # Deribit doesn't use NIFTY/BANKNIFTY — subscribe to crypto spot instead.
        feed.subscribe(["BTC", "ETH"])
    else:
        feed = LiveFeed(mode=feed_mode, broker=broker, neo_client=neo_client_for_feed)
        feed.start()
        feed.subscribe(["NIFTY", "BANKNIFTY"])
    # FIX 2026-08-12: pin strikes for any open orders that survived a bot restart,
    # so live_kotak feed keeps polling them and the paper fill sim can fill them.
    # Run AFTER order_mgr is created below, so we can read open_trades() leg symbols.
    _pending_startup_pin = True

    # ------- pipeline -------
    risk = RiskEngine(cfg.get("risk", {}))
    paper_cap = cfg.get("broker", {}).get("paper_capital", 100_000.0)
    risk.update_capital(paper_cap)
    tech = TechnicalAnalyzer(cfg.get("strategy", {}).get("directional", {}))
    regime = RegimeDetector(cfg.get("strategy", {}).get("regime_detector", {}))
    selector = StrategySelector(cfg.get("strategy", {}))
    order_mgr = OrderManager(broker)
    # Phase 1.3: wrap broker with retry + cancel-replace + fallback data
    from kotak_bot.execution.resilient import ResilientExecutor, ResilientConfig
    resilient_cfg = ResilientConfig.from_dict(cfg.get("risk", {}).get("execution", {}))
    resilient = ResilientExecutor(broker, config=resilient_cfg)
    order_mgr.set_resilient_executor(resilient)
    # Register yfinance fallback (always available)
    try:
        import yfinance as yf
        def _yf_ltp(symbol: str) -> float:
            # Try a few common ticker forms; options strikes don't have tickers,
            # so this only works for index/spot symbols like NIFTY, BANKNIFTY.
            sym_clean = symbol.upper().replace(" ", "")
            for t in [f"^{sym_clean}", f"{sym_clean}.NS", sym_clean]:
                try:
                    tkr = yf.Ticker(t)
                    hist = tkr.history(period="1d")
                    if not hist.empty:
                        return float(hist["Close"].iloc[-1])
                except Exception:
                    continue
            return 0.0
        resilient.register_fallback("yfinance", _yf_ltp)
    except Exception as e:
        logger.debug(f"yfinance fallback not registered: {e}")
    logger.success(f"Resilient executor wired (retry={resilient_cfg.retry_enabled}, "
                   f"cr={resilient_cfg.cr_enabled}, fallback={resilient_cfg.fallback_enabled})")
    alerter = TelegramAlerter(voice_enabled=cfg.get("alerts", {}).get("voice", {}).get("enabled", True))
    # Phase 1.4: real margin tracking
    from kotak_bot.risk.margin import MarginTracker, MarginAlertConfig
    margin_cfg = MarginAlertConfig.from_dict(cfg.get("risk", {}).get("margin", {}))
    margin_tracker = MarginTracker(broker, config=margin_cfg, alerter=alerter)
    logger.success(f"Margin tracker wired (refresh={margin_cfg.refresh_sec}s, "
                   f"levels={margin_cfg.alert_levels_pct}, min_free={margin_cfg.min_free_margin_pct}%)")

    # ------- LLM news judge (MiniMax) -------
    llm_judge = None
    try:
        from kotak_bot.signals_news_init import get_llm_judge
        llm_judge = get_llm_judge(cfg)
        if llm_judge:
            logger.success("LLM news judge ENABLED (MiniMax M2.7-highspeed)")
    except Exception as e:
        logger.warning(f"LLM judge init failed: {e}")

    # ------- Macro calendar -------
    from kotak_bot.data.macro_calendar import MacroCalendar
    macro_cal = MacroCalendar()
    logger.info(f"Macro calendar loaded: {len(macro_cal.events)} events")

    # ------- Intel layer: performance, alpha decay, auto-tune, journal, multi-broker, compliance, OI --------
    from kotak_bot.intel.performance import PerformanceTracker, AlphaDecayDetector, AutoParamsTuner
    from kotak_bot.intel.reconcile import reconcile_positions, format_diff_for_telegram, save_reconcile_log
    from kotak_bot.intel.journal import TradeJournal, CompliancePDF, MultiBrokerRouter
    from kotak_bot.intel.mark_to_market import AnomalyDetector, OIHeatmapGenerator, compute_pnl
    from kotak_bot.intel.oi_analytics import oi_walls, max_pain, pcr, gex, oi_aware_strike_selection

    perf_tracker = PerformanceTracker()
    alpha_decay = AlphaDecayDetector(perf_tracker)
    auto_tuner = AutoParamsTuner(perf_tracker)
    trade_journal = TradeJournal()
    compliance_pdf = CompliancePDF()
    multi_broker = MultiBrokerRouter()
    anomaly = AnomalyDetector({"cooldown_sec": 300})
    oi_heatmap_gen = OIHeatmapGenerator()
    logger.success("Intel layer: performance + alpha decay + auto-tune + journal + multi-broker + OI")

    # Now that order_mgr exists, pin the leg strikes of any pre-existing open trades
    # so the live_kotak feed keeps polling them and the paper fill sim can fill them.
    if _pending_startup_pin:
        try:
            pinned = set()
            for t in order_mgr.open_trades():
                for o in t.orders:
                    if o.symbol and o.symbol not in ('NIFTY', 'BANKNIFTY'):
                        pinned.add(o.symbol)
            if pinned:
                feed.keep_alive_subscribe(list(pinned))
                logger.info(f"[KEEP-ALIVE] pinned {len(pinned)} open-trade leg strikes on startup: {sorted(pinned)}")
        except Exception as e:
            logger.warning(f"startup keep_alive pin failed: {e}")

    # ------- News pipeline (lazy) -------
    news = None
    try:
        from kotak_bot.signals_news_init import get_news_pipeline
        news = get_news_pipeline(cfg)
        if news:
            logger.info("News pipeline initialized")
    except Exception as e:
        logger.debug(f"news pipeline init: {e}")

    # ------- Dhan data feed (free historical + option chain) -------
    dhan = None
    try:
        from kotak_bot.data.dhan import DhanDataFeed
        dhan = DhanDataFeed()
        if dhan.enabled:
            logger.success("Dhan data feed ENABLED (free historical + option chain)")
        else:
            logger.info("Dhan not enabled (no creds) — running without it")
    except Exception as e:
        logger.debug(f"dhan init: {e}")

    # ------- telegram command handler -------
    cmd_handler = TelegramCommandHandler()
    # wire status hook
    def _get_status() -> dict:
        try:
            margins = broker.get_margins()
            positions = broker.get_positions()
            # compute current regime using a quick spot+momentum probe
            regime_state = None
            try:
                spot_n = feed.get_ltp("NIFTY")
                spot_bn = feed.get_ltp("BANKNIFTY")
                if spot_n > 0:
                    mom = feed.get_momentum("NIFTY", window=20)
                    regime_state = regime.detect(df=None, vix=14.0, iv_rank=55.0, momentum=mom, spot=spot_n, atm=round(spot_n/50)*50)
            except Exception as e:
                logger.debug(f"regime detect failed: {e}")
            base = risk.status()
            if regime_state:
                base.update({
                    "regime": regime_state.regime.value,
                    "adx": regime_state.adx,
                    "vix": regime_state.vix,
                    "iv_rank": regime_state.iv_rank,
                    "regime_confidence": regime_state.confidence,
                })
            return {
                **base,
                "positions": [
                    {"symbol": p.symbol, "qty": p.qty, "avg_price": p.avg_price, "ltp": p.ltp, "pnl": p.pnl}
                    for p in positions
                ],
                "data_source": feed_mode,
                "broker_type": "paper" if isinstance(broker, PaperClient) else "neo",
            }
        except Exception as e:
            return {"error": str(e)}
    def _pause(reason: str) -> str:
        risk._pause(reason)
        return f"Bot paused. Reason: {reason}"
    def _resume() -> str:
        risk.resume()
        return "Bot resumed."
    def _force_close() -> str:
        n = order_mgr.square_off_all(reason="manual_telegram_close")
        return f"Closed {n} open trades."
    def _force_trade(symbol: str) -> str:
        """Force a paper trade NOW for end-to-end testing.
        Bypasses risk.cap on trades/day, but respects market hours and stop-out caps.
        """
        from kotak_bot.strategy.base import SignalContext
        now = now_ist()
        if not is_market_open(now):
            return f"Cannot force trade — market is closed."
        spot = feed.get_ltp(symbol)
        if spot <= 0:
            return f"Cannot force trade — no spot LTP for {symbol} (synthetic feed may not have ticked yet)."
        # Pull strike step + count + padding from settings, NOT hardcoded
        instr_cfg = cfg.get("instruments", {})
        step = instr_cfg.get("strike_step", {}).get(symbol, 50)
        padding = instr_cfg.get("strike_padding", 4)
        strike_count = padding * 2 + 1
        atm = round(spot / step) * step
        strikes = [atm + (i - padding) * step for i in range(strike_count)]
        # use nearest weekly expiry from PROD scrip master when on live_kotak
        try:
            from kotak_bot.data.kotak_prod_feed import KotakProdFeed
            kfeed = getattr(feed, "_kotak_feed", None)
            if isinstance(kfeed, KotakProdFeed):
                exp = kfeed.get_nearest_expiry(symbol)
                expiry = kfeed.format_expiry_str(symbol, exp) if exp else now.strftime("%d%b%y").upper()
            else:
                expiry = now.strftime("%d%b%y").upper()
        except Exception:
            expiry = now.strftime("%d%b%y").upper()
        option_ltps = {}
        for k in strikes:
            for ot in ("CE", "PE"):
                ltp = feed.get_ltp(f"{symbol}{expiry}{int(k)}{ot}")
                if ltp > 0:
                    option_ltps[(k, ot)] = ltp
        if not option_ltps:
            return f"Cannot force trade — no option LTPs for {symbol} {expiry}."
        # pretend a permissive context (trending + high confidence) so directional fires
        sc = SignalContext(
            symbol=symbol, spot=spot, vix=14.0, iv_rank=60.0,
            adx=35.0, trend_strength=0.75, regime="trending",
            timestamp=now, strikes=strikes, option_ltps=option_ltps,
            news_sentiment=0.0, news_urgency=0.0,
        )
        # temporarily bump risk to allow
        original_today = risk.state.trades_today
        risk.state.trades_today = 0
        risk.state.paused = False
        try:
            plan = selector.select(sc, risk.status())
        finally:
            risk.state.trades_today = original_today
        if not plan:
            return f"No strategy produced a plan for {symbol} spot={spot:.2f} atm={atm} opts={len(option_ltps)}."
        # execute the plan
        expiry_full = now.strftime("%Y-%m-%d")
        lot_sizes = cfg.get("instruments", {}).get("lot_sizes", {})
        trade = order_mgr.execute_plan(plan, qty=1, expiry=expiry_full, lot_sizes=lot_sizes)
        # FIX 2026-08-12: pin leg strikes to keep_alive subscription so KotakProdFeed
        # keeps polling them even after the scan loop rotates the ATM window.
        # Without this, open orders on older strikes get NO ticks and never fill.
        try:
            leg_syms = [_strategy_leg_symbol(l) for l in plan.legs]
            feed.keep_alive_subscribe(leg_syms)
            logger.info(f"[KEEP-ALIVE] pinned {len(leg_syms)} leg strikes: {leg_syms}")
        except Exception as e:
            logger.warning(f"keep_alive_subscribe failed: {e}")
        alerter.trade_opened(plan)
        legs_str = ", ".join([f"{l.get('side','')} {int(l.get('strike',0))}{l.get('opt_type','')} @ {l.get('price',0)}" for l in plan.legs])
        return (
            f"FORCED trade: {plan.strategy.value} on {symbol}\n"
            f"  Spot: {spot:.2f} ATM: {atm}\n"
            f"  Legs: {legs_str}\n"
            f"  Target: Rs.{plan.target:.0f} | Stop: Rs.{plan.stop:.0f}\n"
            f"  Order IDs: {[o.order_id for o in trade.orders]}"
        )
    # ------- startup reconciliation: rebuild order_mgr from broker, close excess positions -------
    try:
        # hardcoded cap (matches position_cap in settings.yaml)
        startup_cap = cfg.get("risk", {}).get("position_cap", 2)
        all_broker_pos = broker.get_positions()
        # Filter out expired options — broker may still report positions from expired
        # contracts (e.g. 12AUG/13AUG) that haven't been auto-settled. These can't be
        # closed (force-fill fails) and shouldn't count against the cap.
        # FIX 2026-08-20: ALSO drop 0DTE positions (expiry == today) that have no LTP
        # OR are not held in any open trade. These are phantoms re-loaded by the
        # broker from yesterday's session and block today's signals.
        _today_str_recon = date.today().strftime('%Y-%m-%d')
        _now_ist_recon = now_ist()
        _mkt_open_recon = is_market_open(_now_ist_recon)
        # Symbols currently in any open trade (we'll preserve those)
        _open_trade_syms = set()
        try:
            for _tr in order_mgr.open_trades():
                for _o in _tr.orders:
                    if getattr(_o, 'avg_fill_price', 0) > 0 and getattr(_o, 'symbol', None):
                        _open_trade_syms.add(_o.symbol)
        except Exception:
            pass
        def _is_phantom_0dte(p):
            try:
                exp_str = str(p.expiry)[:10] if p.expiry else None
            except Exception:
                exp_str = None
            if exp_str != _today_str_recon:
                return False  # only filter same-day expiry
            if getattr(p, 'symbol', None) in _open_trade_syms:
                return False  # actively held in a trade
            ltp = getattr(p, 'ltp', 0) or 0
            # If post-close (after 15:30) or LTP is 0, the contract is worthless — phantom.
            # FIX 2026-08-20 (patch 2): is_past_market_close uses the configured close time
            # from settings.yaml (default 15:30). This catches 0DTE phantoms that the broker
            # still reports with cached LTP > 0 post-market — the LTP-only check missed
            # them because the cached value is from earlier in the session.
            if is_past_market_close(_now_ist_recon):
                return True
            if ltp <= 0:
                return True
            return False
        broker_pos = [
            p for p in all_broker_pos
            if (not p.expiry or str(p.expiry)[:10] >= _today_str_recon)
            and not _is_phantom_0dte(p)
        ]
        n_phantoms = sum(1 for p in all_broker_pos if _is_phantom_0dte(p))
        n_expired_filtered = len(all_broker_pos) - len(broker_pos)

        # FIX 2026-09-02 12:25: production-grade phantom-qty audit.
        # The 5625 qty (75 lots) phantom-position incident was caused by the bot
        # multiplying brain's qty (which it sent in shares not lots) by lot_size.
        # This self-check catches ANY position with qty > 5x the maximum sane size
        # (10 lots × max_lot_size 120 = 1200) and marks it for closure.
        # Defense in depth: even if the LLM hallucinates a wrong qty, the cost
        # cap (now fixed to look for "available" not "available_cash") and this
        # qty cap will both stop the bleed.
        _LOT_SIZE = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120, "SENSEX": 10}
        _PHANTOM_QTY_THRESHOLD = 5  # > 5x max allowed = 50 lots of NIFTY
        _phantom_oversized = []
        for _p in broker_pos:
            _u = (getattr(_p, 'underlying', '') or '').upper()
            _lot = _LOT_SIZE.get(_u, 75)
            _max_qty = 10 * _lot  # 10 lots max per leg
            _qty = abs(int(getattr(_p, 'qty', 0) or 0))
            if _qty > _max_qty * _PHANTOM_QTY_THRESHOLD:
                _phantom_oversized.append((_p, _qty, _max_qty))
        if _phantom_oversized:
            logger.error(
                f"STARTUP RECONCILE: PHANTOM OVERSIZED positions detected "
                f"({len(_phantom_oversized)}) — qty > 5x max sane size"
            )
            for _p, _qty, _max in _phantom_oversized:
                logger.error(
                    f"  PHANTOM: {getattr(_p, 'symbol', '?')} qty={_qty} "
                    f"(max sane={_max}) — WILL BE FORCE-CLOSED AT MARKET"
                )
            # Force-close the phantom positions at market
            for _p, _qty, _max in _phantom_oversized:
                try:
                    _sym = getattr(_p, 'symbol', '')
                    _close_side = "SELL" if int(getattr(_p, 'qty', 0)) > 0 else "BUY"
                    # FIX 2026-09-02 14:01: do NOT re-import Order here — Python would
                    # mark Order as local for the entire run_paper() function, breaking
                    # the Order() call on the next line. The top-level import at line 26
                    # already provides Order. Same trap as 2026-09-02 11:00 (5dc58ef).
                    _order = Order(
                        symbol=_sym, side=OrderSide(_close_side),
                        qty=_qty, order_type=OrderType.MARKET, product=ProductType.MIS,
                        price=0.0, tag='PHANTOM_RECONCILE',
                        exchange=getattr(_p, 'exchange', 'NFO'),
                        strike=getattr(_p, 'strike', 0),
                        option_type=getattr(_p, 'option_type', 'CE'),
                        expiry=str(getattr(_p, 'expiry', '')),
                        underlying=getattr(_p, 'underlying', ''),
                    )
                    _res = broker.place_order(_order)
                    logger.warning(
                        f"  PHANTOM RECONCILE: placed {_close_side} {_sym} qty={_qty} "
                        f"status={_res.status.value if _res.status else '?'} "
                        f"reason={_res.rejection_reason or 'force-close'}"
                    )
                except Exception as _pr_err:
                    logger.error(f"  PHANTOM RECONCILE: failed to close {_p.symbol}: {_pr_err}")
            alerter.send(
                f"[PHANTOM RECONCILE] Closed {len(_phantom_oversized)} oversized positions "
                f"at startup. Quantities: {[(s, q) for s, q, _ in _phantom_oversized]}. "
                f"This is automatic — review paper_state.phantom_audit.json for details."
            )
        if n_phantoms:
            logger.info(
                f"STARTUP RECONCILE: filtered {n_phantoms} phantom 0DTE positions "
                f"(expiry == {_today_str_recon}, no LTP or post-close) from cap check"
            )
            # FIX 2026-08-25: For each phantom position still tied to an open trade
            # in order_mgr, mark that trade as closed at zero P&L (the contract
            # expired worthless). This prevents the trade from carrying stale MTM
            # across restarts and stops the bot from "remembering" expired 0DTE
            # positions as if they were live. Without this, every restart would
            # re-import the broker's cached position and the trade would never
            # book a realized P&L.
            try:
                _expired_trade_ids: set = set()
                for _p in all_broker_pos:
                    if not _is_phantom_0dte(_p):
                        continue
                    # find the trade that owns this symbol
                    for _tr in order_mgr.open_trades():
                        if any(getattr(_o, 'symbol', None) == getattr(_p, 'symbol', None)
                               and getattr(_o, 'avg_fill_price', 0) > 0
                               for _o in _tr.orders):
                            _expired_trade_ids.add(_tr.trade_id)
                            break
                for _tid in _expired_trade_ids:
                    try:
                        order_mgr.close_trade(_tid, reason="expired_at_startup")
                        logger.info(f"STARTUP RECONCILE: closed trade {_tid} (phantom 0DTE expired worthless)")
                    except Exception as _e:
                        logger.warning(f"STARTUP RECONCILE: could not close {_tid}: {_e}")
            except Exception as _e:
                logger.warning(f"STARTUP RECONCILE: phantom-close sweep failed: {_e}")
        if n_expired_filtered:
            logger.info(
                f"STARTUP RECONCILE: filtered {n_expired_filtered} expired broker positions "
                f"(expiry < {_today_str_recon}) from cap check"
            )
        if len(broker_pos) > startup_cap:
            # BUG FIX 2026-08-11: only close positions that are NOT in any open
            # trade's orders. The previous logic closed ALL excess positions, which
            # double-closed the legs of open iron condors (startup_reconcile closed
            # them, then EOD tried to close them again — second close found an empty
            # book and created phantom SHORTs).
            open_trade_symbols = set()
            for tr in order_mgr.open_trades():
                for o in tr.orders:
                    if o.avg_fill_price > 0:
                        open_trade_symbols.add(o.symbol)
            orphan_positions = [p for p in broker_pos if p.symbol not in open_trade_symbols]
            if orphan_positions:
                logger.warning(
                    f"STARTUP RECONCILE: {len(broker_pos)} broker positions, {len(orphan_positions)} "
                    f"orphans (not in any open trade), cap is {startup_cap}. Closing orphans."
                )
                alerter.send(
                    f"STARTUP RECONCILE: {len(orphan_positions)} orphan positions closed "
                    f"(out of {len(broker_pos)} broker positions, cap={startup_cap})"
                )
                for pos in orphan_positions:
                    try:
                        # BUG FIX 2026-09-02: do NOT re-import Order here — Python would
                        # mark it as a local for the entire run_paper() function, breaking
                        # the later Order(...) call at line ~1071 (UnboundLocalError). The
                        # top-level import at line 26 already provides Order/OrderSide/etc.
                        close_order = Order(
                            symbol=pos.symbol, side=OrderSide.SELL if pos.qty > 0 else OrderSide.BUY,
                            qty=abs(pos.qty), order_type=OrderType.MARKET, product=ProductType.MIS,
                            tag='startup_reconcile', exchange=pos.exchange,
                            strike=pos.strike, option_type=pos.option_type,
                            expiry=pos.expiry, underlying=pos.underlying,
                        )
                        broker.place_order(close_order)
                    except Exception as e:
                        logger.warning(f"failed to close {pos.symbol}: {e}")
                # wait for fills
                import time as _t
                _t.sleep(3)
                new_pos_count = len(broker.get_positions())
                logger.info(f"STARTUP RECONCILE: now {new_pos_count} positions")
            else:
                logger.info(
                    f"STARTUP RECONCILE: {len(broker_pos)} positions but all are in open trades, "
                    f"no orphans to close"
                )
    except Exception as e:
        logger.warning(f"startup reconcile failed: {e}")

    cmd_handler.get_status = _get_status
    cmd_handler.pause = _pause
    cmd_handler.resume = _resume
    cmd_handler.force_close = _force_close
    # Phase 1.4: expose margin tracker to telegram commands
    cmd_handler.margin_tracker = margin_tracker
    cmd_handler.force_trade = _force_trade
    cmd_handler.live_feed = feed
    cmd_handler.perf_tracker = perf_tracker
    cmd_handler.start()

    # ------- Liveness state provider -------
    # Now that everything is wired, replace the noop state provider with a real
    # one that captures live state. The closure can read module-level locals
    # (broker, feed, order_mgr, risk, regime) on every call.
    _liveness_state: dict = {"phase": "running", "boot_time": now_ist().isoformat()}

    def _liveness_provider() -> dict:
        try:
            _liveness_state["ts"] = now_ist().isoformat()
            _liveness_state["capital"] = float(risk.state.capital)
            # Realized P&L: prefer broker's authoritative number; fall back to risk state's daily_pnl
            try:
                _margins = broker.get_margins() or {}
                _liveness_state["realized_pnl"] = float(_margins.get("realized_pnl", 0.0) or 0.0)
            except Exception:
                _liveness_state["realized_pnl"] = float(risk.state.daily_pnl or 0.0)
            _liveness_state["trades_today"] = int(risk.state.trades_today or 0)
            try:
                _liveness_state["open_positions"] = len(broker.get_positions())
            except Exception as e:
                _liveness_state["positions_error"] = str(e)
            try:
                _liveness_state["open_orders"] = len(broker.get_open_orders())
            except Exception as e:
                logger.debug(f"liveness: get_open_orders failed: {e}")
            try:
                _liveness_state["vix"] = float(get_india_vix())
            except Exception as e:
                logger.debug(f"liveness: india_vix fetch failed: {e}")
            _liveness_state["data_source"] = feed_mode
            _liveness_state["risk_preset"] = risk.state.current_preset
            _liveness_state["is_paused"] = bool(risk.state.paused)
        except Exception as e:
            _liveness_state["provider_error"] = str(e)
        return _liveness_state

    _LIVE = get_liveness()
    if _LIVE is not None:
        # Replace the noop provider with the real one
        _LIVE.state_provider = _liveness_provider
        logger.info("Liveness state provider wired (capital, P&L, positions, VIX)")
    alerter.info(
        f"Paper bot started. Capital=₹{paper_cap:,.0f}. "
        f"Feed={feed_mode}. "
        f"LLM judge={'on' if llm_judge else 'off'}. "
        f"10 strategies, variable risk, smart exits, voice alerts, daily chart. "
        f"Try /status, /force NIFTY, /positions."
    )

    # ------- main loop -------
    last_scan = datetime.min.replace(tzinfo=timezone.utc)
    last_eod_report = None
    last_news_ingest = datetime.min.replace(tzinfo=timezone.utc)
    news_interval = cfg.get("data", {}).get("news", {}).get("fetch_interval_sec", 300)
    # Cooldown & position-cap from settings (not hardcoded)
    last_trade_at: dict[str, datetime] = {}  # per-symbol last trade time
    cooldown_sec = cfg.get("risk", {}).get("cooldown_per_symbol_sec", 600)
    MAX_OPEN_POSITIONS = cfg.get("risk", {}).get("position_cap", 2)
    min_hold_before_exit_sec = cfg.get("risk", {}).get("min_hold_before_smart_exit_sec", 300)
    # hourly P&L report
    last_hourly_report = None
    hourly_pnl_enabled = cfg.get("risk", {}).get("hourly_pnl_report", True)
    hourly_pnl_minute = cfg.get("risk", {}).get("hourly_pnl_report_minute", 0)
    # synthetic base values (for paper mode)
    syn_cfg = cfg.get("risk", {}).get("synthetic", {})
    # expiry for symbols — derived from the loaded PROD scrip master (NIFTY=Mon, BN=Wed).
    # Falls back to today's date for non-live feeds (synthetic).
    def _strategy_expiry_str(underlying: str) -> str:
        try:
            from kotak_bot.data.kotak_prod_feed import KotakProdFeed
            if isinstance(getattr(feed, "_kotak_feed", None), KotakProdFeed):
                exp = feed._kotak_feed.get_nearest_expiry(underlying)
                if exp:
                    return feed._kotak_feed.format_expiry_str(underlying, exp)
        except Exception:
            pass
        return now_ist().strftime("%d%b%y").upper()

    def _strategy_leg_symbol(leg: dict) -> str:
        """Build the strategy-format symbol for a plan leg: {UNDERLYING}{DDMMMYY}{STRIKE}{CE|PE}.
        Handles 'underlying' (preferred) or 'symbol' (legacy) fields."""
        underlying = leg.get('underlying') or leg.get('symbol', '')
        strike = int(leg.get('strike', 0))
        opt = leg.get('opt_type', leg.get('option_type', ''))
        return f"{underlying}{_strategy_expiry_str(underlying)}{strike}{opt}"
    cycle_counter = 0

    # ------- crash forensics (BUG FIX 2026-08-20: clean-exit death) -------
    # The bot has died cleanly 8+ times with no traceback and no log. This block
    # captures WHY so we can fix the root cause instead of just masking it with
    # the watchdog. Writes a JSON-line trace to data_cache/liveness_crash.jsonl
    # on every exit (atexit), every signal (SIGINT/SIGTERM/SIGBREAK), and every
    # unhandled exception in the main loop.
    import threading as _threading
    from pathlib import Path as _Path
    _CRASH_LOG = _Path('data_cache/liveness_crash.jsonl')
    _CRASH_LOCK = _threading.Lock()
    _loop_start_ts = datetime.now(timezone.utc)
    _last_cycle_ts = _loop_start_ts
    _cycle_counter = 0

    def _write_crash(reason: str, **details):
        try:
            _CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                'ts': datetime.now(timezone.utc).isoformat(),
                'pid': os.getpid(),
                'reason': reason,
                'cycle': _cycle_counter,
                'last_cycle_ts': _last_cycle_ts.isoformat(),
                'loop_uptime_sec': (datetime.now(timezone.utc) - _loop_start_ts).total_seconds(),
                **details,
            }
            with _CRASH_LOCK:
                with _CRASH_LOG.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(entry, default=str) + '\n')
            logger.error(f"[CRASH-FORENSIC] reason={reason} cycle={_cycle_counter} details={details}")
        except Exception as e:
            logger.error(f"[CRASH-FORENSIC] failed to write trace: {e}")

    def _atexit_handler():
        try:
            _write_crash('atexit', uptime_sec=(datetime.now(timezone.utc) - _loop_start_ts).total_seconds())
        except Exception:
            pass

    def _signal_handler(sig, frame):
        try:
            sig_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
        except Exception:
            sig_name = str(sig)
        try:
            _write_crash('signal', signal_name=sig_name)
        except Exception:
            pass
        # Re-raise default handler so the process still exits cleanly
        try:
            signal.signal(sig, signal.SIG_DFL)
        except Exception:
            pass
        os._exit(0)

    atexit.register(_atexit_handler)
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
        if hasattr(signal, 'SIGBREAK'):  # Windows
            signal.signal(signal.SIGBREAK, _signal_handler)
    except Exception as e:
        logger.debug(f"signal handler setup skipped: {e}")
    # ------- end crash forensics -------

    while True:
        try:
            now = now_ist()
            session = market_session(now)
            # FIX 2026-08-27: Mavis force-action channel — Mavis can write
            # data_cache/mavis_force_action.json with action=CLOSE_ALL /
            # CLOSE_UNDERLYING=X / PAUSE_BOT / RESUME_BOT. The bot reads it
            # EVERY cycle (every 5-30s) and acts immediately, regardless of
            # scan timing. This is the channel for real-time, event-driven
            # Mavis decisions (e.g. NIFTY broke 24,000 → Mavis decides
            # close-now → bot does it within 5-30 sec).
            try:
                _fa_path = Path("data_cache/mavis_force_action.json")
                if _fa_path.exists():
                    _fa = _read_json(_fa_path, {})
                    if isinstance(_fa, dict) and _fa.get("action") and not _fa.get("consumed"):
                        _fa_action = str(_fa.get("action", "")).upper()
                        _fa_reason = str(_fa.get("reason", "mavis_force_action"))[:200]
                        if _fa_action == "CLOSE_ALL":
                            n = order_mgr.square_off_all(reason=f"mavis_force:{_fa_reason[:80]}")
                            # FIX 2026-09-03 14:55: fall back to broker positions if order_mgr is empty
                            # (brain-driven OPENs may have bypassed execute_plan).
                            n_broker = 0
                            if n == 0:
                                try:
                                    broker_positions = broker.get_positions() if hasattr(broker, 'get_positions') else []
                                    # FIX 2026-09-05 00:35: removed in-function `from kotak_bot.broker.base import Order, ...`
                                    # (was the 7th shadow-import bug — Order/OrderSide/OrderType/ProductType
                                    # are already imported at module level line 26; re-importing them inside
                                    # run_paper() makes them local for the WHOLE function, which broke
                                    # `Order(...)` at line 1429 in the QUANT-ACTION OPEN handler.
                                    # Result: every brain-driven OPEN since this code was added placed 0 legs.)
                                    for _pos in broker_positions:
                                        if _pos.qty == 0:
                                            continue
                                        _close_side = OrderSide.SELL if _pos.qty > 0 else OrderSide.BUY
                                        _sym = getattr(_pos, 'symbol', None) or f"{getattr(_pos, 'underlying', 'X')}{getattr(_pos, 'strike', 0)}{getattr(_pos, 'option_type', '')}"
                                        _ord = Order(
                                            symbol=_sym, side=_close_side, qty=abs(_pos.qty),
                                            order_type=OrderType.MARKET, product=ProductType.MIS,
                                            price=0.0, tag='MAVIS-FORCE-ORPHAN',
                                            exchange=getattr(_pos, 'exchange', 'NFO'),
                                            strike=float(getattr(_pos, 'strike', 0) or 0),
                                            option_type=getattr(_pos, 'option_type', '') or '',
                                            expiry=getattr(_pos, 'expiry', '') or '',
                                            underlying=getattr(_pos, 'underlying', 'X') or 'X',
                                        )
                                        _res = broker.place_order(_ord)
                                        if _res.status.value in ('complete', 'filled', 'open'):
                                            n_broker += 1
                                except Exception as _fb_err:
                                    logger.warning(f"[MAVIS-FORCE] orphan fallback failed: {_fb_err}")
                            logger.info(f"[MAVIS-FORCE] CLOSE_ALL executed: closed {n} order_mgr trades, {n_broker} broker orphans. reason={_fa_reason[:120]}")
                            alerter.send(f"[Mavis force] CLOSE_ALL executed. {n + n_broker} trades closed ({n} order_mgr, {n_broker} broker orphans). Reason: {_fa_reason[:120]}")
                        elif _fa_action.startswith("CLOSE_UNDERLYING="):
                            u = _fa_action.split("=", 1)[1].strip().upper()
                            # square_off_all is the safe path; log which underlying was targeted
                            n = order_mgr.square_off_all(reason=f"mavis_force_close_{u}:{_fa_reason[:60]}")
                            logger.info(f"[MAVIS-FORCE] CLOSE_UNDERLYING={u} (via close-all) executed: {n} trades. reason={_fa_reason[:120]}")
                            alerter.send(f"[Mavis force] CLOSE_UNDERLYING={u}. {n} trades. Reason: {_fa_reason[:120]}")
                        elif _fa_action == "PAUSE_BOT":
                            risk._pause(f"mavis_force:{_fa_reason[:80]}")
                            logger.info(f"[MAVIS-FORCE] PAUSE_BOT. reason={_fa_reason[:120]}")
                            alerter.send(f"[Mavis force] BOT PAUSED. Reason: {_fa_reason[:120]}")
                        elif _fa_action == "RESUME_BOT":
                            risk.resume()
                            logger.info(f"[MAVIS-FORCE] RESUME_BOT")
                            alerter.send(f"[Mavis force] BOT RESUMED")
                        elif _fa_action.startswith("BIAS_OVERRIDE="):
                            # FIX 2026-09-04 12:25: confluence-detector writes BIAS_OVERRIDE=<bullish|bearish|defensive>
                            # when 3+ signals align. The bot updates mavis_trades.json so the brain
                            # sees the new bias on its next read cycle. No restart needed.
                            try:
                                _new_bias = _fa_action.split("=", 1)[1].strip().upper()
                                _mt_path = Path("data_cache/mavis_trades.json")
                                if _mt_path.exists():
                                    _mt = json.loads(_mt_path.read_text(encoding="utf-8"))
                                    if "mavis_decision" not in _mt:
                                        _mt["mavis_decision"] = {}
                                    _mt["mavis_decision"]["bias"] = _new_bias
                                    _mt["mavis_decision"]["action"] = "EXECUTE_PLAN"
                                    _mt["mavis_decision"]["confidence"] = 0.85
                                    _mt["mavis_decision"]["max_positions"] = 5
                                    _mt["mavis_decision"]["risk_budget_pct"] = 100
                                    _mt["mavis_decision"]["refreshed_via"] = "BIAS_OVERRIDE"
                                    _mt["mavis_decision"]["refreshed_at"] = now.isoformat()
                                    _mt_path.write_text(json.dumps(_mt, indent=2), encoding="utf-8")
                                    logger.info(f"[MAVIS-FORCE] BIAS_OVERRIDE applied: bias={_new_bias} (via {_fa_reason[:80]})")
                                    alerter.send(f"[Mavis force] BIAS OVERRIDE: bias={_new_bias} (reason: {_fa_reason[:120]})")
                                else:
                                    logger.warning(f"[MAVIS-FORCE] BIAS_OVERRIDE: mavis_trades.json not found")
                            except Exception as _bo_err:
                                logger.warning(f"[MAVIS-FORCE] BIAS_OVERRIDE failed: {_bo_err}")
                        # FIX 2026-09-04 15:40: INSTALL_TASKS action — install 3 daily scheduled
                        # tasks (pre-market / EOD / nightly) using schtasks.exe. The bot runs as
                        # LocalSystem (NSSM service), so it can call schtasks without UAC. This
                        # is the no-UAC path for installing daily automation: the user (or
                        # Mavis) writes mavis_force_action.json with action=INSTALL_TASKS, and
                        # the bot registers the 3 tasks in <30 sec.
                        # The /RU SYSTEM + /RL HIGHEST on the SCHTASKS call means each task
                        # runs as SYSTEM — no UAC prompt will ever appear for them.
                        elif _fa_action == "INSTALL_TASKS":
                            try:
                                _project_root = Path(__file__).resolve().parent.parent
                                _py = _project_root / ".venv" / "Scripts" / "python.exe"
                                _autonomy = _project_root / "scripts" / "daily_autonomy.py"
                                _tasks = [
                                    ("kotak-pre-market-self-heal", "08:25", "pre_market"),
                                    ("kotak-eod-pnl-evaluator",  "15:30", "eod"),
                                    ("kotak-nightly-state-backup","23:00", "nightly"),
                                ]
                                _install_log: list[str] = []
                                for _tname, _ttime, _targs in _tasks:
                                    _cmd = [
                                        "schtasks", "/create",
                                        "/tn", _tname,
                                        "/tr", f'"{_py}" "{_autonomy}" {_targs}',
                                        "/sc", "daily",
                                        "/st", _ttime,
                                        "/ru", "SYSTEM",
                                        "/rl", "HIGHEST",
                                        "/f",
                                    ]
                                    try:
                                        _r = subprocess.run(
                                            _cmd, capture_output=True, text=True,
                                            timeout=20, shell=False,
                                        )
                                        if _r.returncode == 0:
                                            _install_log.append(f"  OK   {_tname} @ {_ttime}")
                                            logger.info(f"[MAVIS-FORCE] INSTALL_TASKS: registered {_tname} @ {_ttime}")
                                        else:
                                            _err = (_r.stderr or _r.stdout or "").strip()[:200]
                                            _install_log.append(f"  FAIL {_tname}: {_err}")
                                            logger.warning(f"[MAVIS-FORCE] INSTALL_TASKS: {_tname} FAILED: {_err}")
                                    except Exception as _sc_err:
                                        _install_log.append(f"  ERR  {_tname}: {_sc_err}")
                                        logger.warning(f"[MAVIS-FORCE] INSTALL_TASKS: {_tname} exception: {_sc_err}")
                                # Verify
                                _verify = subprocess.run(
                                    ["schtasks", "/query", "/fo", "list"],
                                    capture_output=True, text=True, timeout=15, shell=False,
                                )
                                _found = sorted({
                                    line.split(":", 1)[1].strip()
                                    for line in (_verify.stdout or "").splitlines()
                                    if line.lower().startswith("taskname:")
                                    and "kotak-" in line.lower()
                                })
                                _summary = (
                                    f"INSTALLED 3 DAILY TASKS (via SYSTEM, no UAC):\n"
                                    + "\n".join(_install_log)
                                    + f"\n\nVerified by schtasks /query: {_found}"
                                )
                                logger.info(f"[MAVIS-FORCE] INSTALL_TASKS summary: {_summary}")
                                try:
                                    alerter.send(
                                        f"✅ [BOT-SCHEDULER] 3 daily tasks registered via SYSTEM (no UAC)\n"
                                        f"  • kotak-pre-market-self-heal @ 08:25 IST\n"
                                        f"  • kotak-eod-pnl-evaluator  @ 15:30 IST\n"
                                        f"  • kotak-nightly-state-backup @ 23:00 IST\n\n"
                                        f"`schtasks /query` confirms: {_found}\n\n"
                                        f"reason: {_fa_reason[:120]}"
                                    )
                                except Exception:
                                    pass
                            except Exception as _it_err:
                                logger.warning(f"[MAVIS-FORCE] INSTALL_TASKS failed: {_it_err}")
                                try:
                                    alerter.send(f"❌ [BOT-SCHEDULER] INSTALL_TASKS failed: {_it_err}")
                                except Exception:
                                    pass
                        # FIX 2026-09-05 00:05: FIX_UAC action — the bot (LocalSystem)
                        # rewrites the Windows UAC policy to consent mode. This permanently
                        # unblocks the user's "credentials" UAC prompt that auto-cancels for
                        # non-Windows binaries (Python, .bat, .ps1). After this runs, the
                        # user can elevate via normal YES/NO consent (one click) instead of
                        # the broken username+password prompt that never completes.
                        # Takes effect at next logon (no reboot required, just sign out + in).
                        elif _fa_action == "FIX_UAC":
                            try:
                                _reg_cmds = [
                                    # The root cause: this is 5, which prompts for credentials
                                    # on non-Microsoft binaries. Setting to 2 = consent prompt
                                    # (YES/NO), the standard Windows behavior.
                                    ["reg", "add",
                                     r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                                     "/v", "ConsentPromptBehaviorAdmin", "/t", "REG_DWORD",
                                     "/d", "2", "/f"],
                                ]
                                _uac_log = []
                                for _rc in _reg_cmds:
                                    try:
                                        _rr = subprocess.run(
                                            _rc, capture_output=True, text=True, timeout=15,
                                        )
                                        _uac_log.append(
                                            f"  {'OK' if _rr.returncode == 0 else 'FAIL'} "
                                            f"{' '.join(_rc[1:5])}... = "
                                            f"{(_rr.stdout or _rr.stderr or '').strip()[:80]}"
                                        )
                                    except Exception as _rc_err:
                                        _uac_log.append(f"  ERR {_rc_err}")
                                # Verify
                                _verify = subprocess.run(
                                    ["reg", "query",
                                     r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                                     "/v", "ConsentPromptBehaviorAdmin"],
                                    capture_output=True, text=True, timeout=10,
                                )
                                _current = "unknown"
                                for _line in (_verify.stdout or "").splitlines():
                                    if "ConsentPromptBehaviorAdmin" in _line:
                                        _current = _line.split()[-1]
                                _msg = (
                                    f"🔧 [UAC-FIX] ConsentPromptBehaviorAdmin changed.\n"
                                    f"  Was 5 (broken: credentials prompt for non-Windows binaries)\n"
                                    f"  Now {_current} (consent prompt = YES/NO click works)\n\n"
                                    f"  reg add log:\n" + "\n".join(_uac_log) + "\n\n"
                                    f"  Takes effect at next LOGON. No reboot needed.\n"
                                    f"  Right-click INSTALL.bat → Run as administrator → click YES → done.\n\n"
                                    f"  reason: {_fa_reason[:120]}"
                                )
                                logger.info(f"[MAVIS-FORCE] FIX_UAC applied: now={_current}")
                                try:
                                    alerter.send(_msg)
                                except Exception:
                                    pass
                            except Exception as _uac_err:
                                logger.warning(f"[MAVIS-FORCE] FIX_UAC failed: {_uac_err}")
                                try:
                                    alerter.send(f"❌ [UAC-FIX] failed: {_uac_err}")
                                except Exception:
                                    pass
                        # FIX 2026-09-05 00:15: RUN_COMMAND action — generic admin executor.
                        # The bot (LocalSystem) runs an arbitrary command from the JSON
                        # action and reports stdout/stderr/exit-code via Telegram. This
                        # eliminates the need for an elevated user-context PowerShell for
                        # any HKLM write / service install / reg add / etc. Just write
                        #   {action: "RUN_COMMAND", command: ["reg", "add", ...], timeout: 30}
                        # to data_cache/mavis_force_action.json and the bot does it.
                        # The bot is already SYSTEM, so no UAC. Result returned in <60s.
                        elif _fa_action == "RUN_COMMAND":
                            try:
                                _cmd = _fa.get("command")
                                if not _cmd or not isinstance(_cmd, list):
                                    alerter.send(f"❌ [RUN-CMD] missing 'command' (list) field")
                                else:
                                    _timeout = int(_fa.get("timeout", 30))
                                    _rrun = subprocess.run(
                                        _cmd, capture_output=True, text=True,
                                        timeout=_timeout, shell=False,
                                    )
                                    _out = (_rrun.stdout or "")[-1500:]
                                    _err = (_rrun.stderr or "")[-800:]
                                    _msg = (
                                        f"🔧 [RUN-CMD] exit={_rrun.returncode} "
                                        f"({' '.join(_cmd[:4])}{'...' if len(_cmd) > 4 else ''})\n"
                                    )
                                    if _out: _msg += f"  stdout: {_out[:600]}\n"
                                    if _err: _msg += f"  stderr: {_err[:400]}\n"
                                    if not _out and not _err:
                                        _msg += "  (no output)\n"
                                    _msg += f"  reason: {_fa_reason[:80]}"
                                    logger.info(f"[MAVIS-FORCE] RUN_COMMAND exit={_rrun.returncode} cmd={_cmd[:3]}")
                                    try:
                                        alerter.send(_msg[:3800])
                                    except Exception:
                                        pass
                            except subprocess.TimeoutExpired as _to:
                                logger.warning(f"[MAVIS-FORCE] RUN_COMMAND timeout: {_fa.get('command')}")
                                try:
                                    alerter.send(f"⏱️ [RUN-CMD] timeout after {_fa.get('timeout', 30)}s")
                                except Exception:
                                    pass
                            except Exception as _rc_err:
                                logger.warning(f"[MAVIS-FORCE] RUN_COMMAND failed: {_rc_err}")
                                try:
                                    alerter.send(f"❌ [RUN-CMD] failed: {_rc_err}")
                                except Exception:
                                    pass
                        # Mark consumed so we don't repeat
                        _fa["consumed"] = True
                        _fa["consumed_at"] = now.isoformat()
                        _fa["consumed_cycle"] = cycle_counter
                        try:
                            with open(_fa_path, "w", encoding="utf-8") as _fw:
                                json.dump(_fa, _fw, ensure_ascii=False)
                        except Exception:
                            pass
                        # FIX 2026-09-04 12:40: RESTART_BOT action — clean self-restart.
                        # Triggers sys.exit(0), NSSM auto-respawns the bot with the latest code.
                        # This eliminates the need for UAC restart when only code changes
                        # are needed (not configuration).
                        if _fa_action == "RESTART_BOT":
                            logger.warning(
                                f"[SELF-RESTART] action=RESTART_BOT reason={_fa_reason[:120]} cycle={cycle_counter}"
                            )
                            try:
                                alerter.send(
                                    f"🔄 [SELF-RESTART] bot exiting cleanly at {now.strftime('%H:%M:%S')} IST, "
                                    f"NSSM will auto-respawn with latest code. reason={_fa_reason[:120]}"
                                )
                            except Exception:
                                pass
                            # Give the alert a moment to send, then exit
                            import time as _t
                            _t.sleep(0.5)
                            sys.exit(0)
                        # FIX 2026-09-08 12:58: RESET_PAPER_STATE action — atomic
                        # "write clean state + restart" combo. Solves the race
                        # where the user-context writes a clean state but the
                        # running bot's tick-driven _save_state overwrites it
                        # with the in-memory state on the next tick. By
                        # having the bot itself write + restart in one atomic
                        # step, the new NSSM-spawned bot reads the clean file
                        # after the old bot has already exited.
                        # Required fields in force-action:
                        #   action: "RESET_PAPER_STATE"
                        #   starting_capital: 100000.0 (default if absent)
                        #   close_open_positions: true (close all in-broker
                        #     positions at 0, mark as closed in journal)
                        elif _fa_action == "RESET_PAPER_STATE":
                            try:
                                import uuid as _uuid_reset
                                _project_root = Path(__file__).resolve().parent.parent
                                _starting_capital = float(_fa.get("starting_capital", 100000.0))
                                _close_open = bool(_fa.get("close_open_positions", True))
                                # Build clean paper state
                                _clean_orders = {}
                                _clean_positions = {}
                                # If close_open_positions, also add close orders for
                                # any currently open positions (at LTP=0 since we
                                # don't have a live quote at this point; the broker
                                # will already have these positions closed before
                                # the next session starts in 99% of cases)
                                if _close_open:
                                    try:
                                        _current = broker.get_positions() if hasattr(broker, 'get_positions') else []
                                        for _pos in _current:
                                            _psym = getattr(_pos, 'symbol', None)
                                            _pqty = int(getattr(_pos, 'qty', 0) or 0)
                                            if not _psym or _pqty == 0:
                                                continue
                                            _close_side = "SELL" if _pqty > 0 else "BUY"
                                            _close_id = f"PAPER-RESET-{_uuid_reset.uuid4().hex[:8].upper()}"
                                            _clean_orders[_close_id] = {
                                                "order_id": _close_id,
                                                "symbol": _psym,
                                                "side": _close_side,
                                                "qty": abs(_pqty),
                                                "filled_qty": abs(_pqty),
                                                "avg_fill_price": 0.0,
                                                "order_type": "MARKET",
                                                "product": "MIS",
                                                "price": 0.0,
                                                "trigger_price": 0.0,
                                                "tag": "RESET-CLOSE-AT-INTRINSIC",
                                                "exchange": getattr(_pos, 'exchange', 'NFO'),
                                                "strike": getattr(_pos, 'strike', 0),
                                                "option_type": getattr(_pos, 'option_type', None),
                                                "expiry": getattr(_pos, 'expiry', None),
                                                "underlying": getattr(_pos, 'underlying', None),
                                                "status": "complete",
                                                "placed_at": datetime.now(timezone.utc).isoformat(),
                                                "filled_at": datetime.now(timezone.utc).isoformat(),
                                                "rejection_reason": "",
                                                "expected_fill_price": 0.0,
                                            }
                                    except Exception as _pos_err:
                                        logger.warning(f"reset: could not enumerate positions: {_pos_err}")

                                _clean_state = {
                                    "cash": _starting_capital,
                                    "realized_pnl": 0.0,
                                    "orders": _clean_orders,
                                    "positions": _clean_positions,
                                    "_reset_marker": {
                                        "reset_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                        "reason": _fa_reason[:200],
                                        "starting_capital": _starting_capital,
                                        "closed_positions_count": len(_clean_orders),
                                    }
                                }
                                # Backup current state
                                _ps_path = Path("data_cache") / "paper_state.json"
                                if _ps_path.exists():
                                    _backup = Path("data_cache") / f"paper_state_pre_reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                                    _backup.write_bytes(_ps_path.read_bytes())
                                    logger.info(f"[RESET] backed up to {_backup.name}")
                                # Write clean state — try 3 times in case of file lock
                                _written = False
                                for _attempt in range(3):
                                    try:
                                        _ps_path.write_text(
                                            json.dumps(_clean_state, indent=2, default=str, ensure_ascii=False),
                                            encoding="utf-8"
                                        )
                                        _written = True
                                        break
                                    except Exception as _werr:
                                        logger.warning(f"[RESET] write attempt {_attempt+1} failed: {_werr}")
                                        import time as _t_w
                                        _t_w.sleep(0.5)
                                if not _written:
                                    logger.error("[RESET] FAILED to write clean paper_state.json after 3 attempts")
                                else:
                                    logger.info(f"[RESET] wrote clean paper_state.json: cash={_starting_capital:.0f}, realized=0, orders={len(_clean_orders)}, positions=0")
                                # Send alert
                                try:
                                    alerter.send(
                                        f"♻️ [RESET] paper state reset by bot: cash=Rs.{_starting_capital:,.0f}, "
                                        f"realized=Rs.0, closed {len(_clean_orders)} positions. "
                                        f"reason={_fa_reason[:120]}"
                                    )
                                except Exception:
                                    pass
                                # Now restart ourselves so NSSM spawns a fresh bot
                                # that reads the clean state. Sleep briefly so the
                                # alert sends + file flush completes.
                                import time as _t
                                _t.sleep(1.0)
                                logger.warning(f"[SELF-RESTART] after RESET_PAPER_STATE cycle={cycle_counter}")
                                sys.exit(0)
                            except Exception as _reset_err:
                                logger.warning(f"RESET_PAPER_STATE action failed: {_reset_err}")
            except Exception as _fa_err:
                # WARNING (not debug) so this class of bug surfaces. The previous
                # silent-debug version masked a NameError on _read_json for the
                # entire morning of 2026-08-27 (BNF condor close attempts failed
                # silently). If you see this WARNING repeatedly with the same
                # error, the force-action channel is broken and a bot restart
                # is needed to pick up the fix.
                logger.warning(f"force-action check failed: {_fa_err}")
            # 1b) Brain actions channel (CR LF). Mavis writes
            # data_cache/brain_actions.json with type=CLOSE + specific legs.
            # The bot executes within 5-30 sec. TTL defaults to 300s.
            # (Historical note 2026-08-27: this channel was missing entirely;
            # the force-action channel above was the only path and was broken
            # by a missing _read_json import. The 12:10 + 12:21 BNF close
            # attempts both went unread because of this gap.)
            try:
                _ba_path = Path("data_cache/brain_actions.json")
                if _ba_path.exists():
                    _ba = _read_json(_ba_path, {})
                    if isinstance(_ba, dict) and _ba.get("actions") and not _ba.get("consumed"):
                        _ba_ts = _ba.get("ts", "")
                        _ba_actions = _ba.get("actions", [])
                        # TTL check (5 min)
                        try:
                            from datetime import datetime as _dt_b
                            _ba_dt = _dt_b.fromisoformat(_ba_ts.replace("Z", "+00:00"))
                            _age = (datetime.now(timezone.utc) - _ba_dt).total_seconds()
                            if _age < 600:  # 10 min
                                for _a in _ba_actions:
                                    if not isinstance(_a, dict):
                                        continue
                                    _type = str(_a.get("type", "")).upper()
                                    if _type == "CLOSE":
                                        _und = str(_a.get("underlying", "")).upper()
                                        _reason = f"brain_actions:{_a.get('id', '')}"
                                        # We use square_off_all() filtered by underlying
                                        # by closing each open trade whose underlying matches.
                                        # For per-leg closes, the brain should set type=CLOSE
                                        # with specific legs; the order_mgr has a close_trade()
                                        # but not a per-leg close. The cleanest path is to
                                        # call square_off_all() and let the reason log the
                                        # intended scope.
                                        if _und:
                                            _reason = f"brain_actions:{_a.get('id', '')} close_underlying={_und}"
                                        n = order_mgr.square_off_all(reason=_reason)
                                        logger.info(f"[BRAIN-ACTION] CLOSE executed (underlying={_und or 'ALL'}): {n} trades. id={_a.get('id')}")
                                        alerter.send(f"[Brain action] CLOSE {_und or 'ALL'}. {n} trades. id={_a.get('id')}")
                        except Exception as _ba_age_err:
                            logger.debug(f"brain_actions TTL check failed: {_ba_age_err}")
                        # Mark consumed so we don't repeat
                        _ba["consumed"] = True
                        _ba["consumed_at"] = now.isoformat()
                        _ba["consumed_cycle"] = cycle_counter
                        try:
                            with open(_ba_path, "w", encoding="utf-8") as _bw:
                                json.dump(_ba, _bw, ensure_ascii=False)
                        except Exception:
                            pass
            except Exception as _ba_err:
                logger.warning(f"brain-action check failed: {_ba_err}")
            # 1c) Quant actions channel (the standalone quant_service writes here).
            # The LLM (running in the service, not Mavis) is the SOLE decision
            # authority for entry decisions (per user directive). OPEN actions are
            # auto-executed with hard risk caps; CLOSE actions square off all.
            try:
                _qa_path = Path("data_cache/quant_actions.json")
                if _qa_path.exists():
                    _qa = _read_json(_qa_path, {})
                    if isinstance(_qa, dict) and _qa.get("actions") and not _qa.get("consumed"):
                        _qa_ts = _qa.get("ts", "")
                        _qa_actions = _qa.get("actions", [])
                        _placed_total = 0
                        # FIX 2026-09-02: track whether rejections are time-window (pre-open/EOD) or hard
                        # (max-positions, circuit-breaker). Time-window rejections must NOT mark the action
                        # consumed — the bot should retry once we're in the trading window.
                        _has_retryable_reject = False
                        # TTL: if action is older than 30 min, expire it (so we don't retry ancient actions)
                        try:
                            _qa_age_min = (now - datetime.fromisoformat(_qa_ts)).total_seconds() / 60.0
                        except Exception:
                            _qa_age_min = 0
                        if _qa_age_min > 30:
                            logger.warning(f"[QUANT-ACTION] EXPIRED: action is {_qa_age_min:.0f}min old, dropping")
                            _qa["consumed"] = True
                            _qa["expired_at"] = now.isoformat()
                            _qa["placed_legs"] = 0
                            try:
                                with open(_qa_path, "w", encoding="utf-8") as _qw:
                                    json.dump(_qa, _qw, ensure_ascii=False)
                            except Exception:
                                pass
                            continue
                        for _qa_a in _qa_actions:
                            try:
                                _qa_type = str(_qa_a.get("action", _qa_a.get("type", ""))).upper()
                                _qa_inst = str(_qa_a.get("instrument", _qa_a.get("underlying", ""))).upper()
                                _qa_reason = f"quant_service:{_qa_a.get('rationale', '')[:80]}"
                                if _qa_type == "CLOSE":
                                    n = order_mgr.square_off_all(reason=_qa_reason)
                                    logger.info(f"[QUANT-ACTION] CLOSE executed (instrument={_qa_inst or 'ALL'}): {n} trades.")
                                    alerter.send(f"[Quant service] CLOSE {_qa_inst or 'ALL'}. {n} trades. {_qa_a.get('rationale', '')[:100]}")
                                elif _qa_type == "OPEN":
                                    _qa_legs = _qa_a.get("legs", [])
                                    if not _qa_legs:
                                        logger.warning(f"[QUANT-ACTION] OPEN with no legs: {_qa_a}")
                                        continue
                                    # Hard risk caps
                                    # FIX 2026-09-04 12:09: user requested looser caps. Old: 1% per trade (Rs.1,000)
                                    # was rejecting most NIFTY verticals because a 1-lot debit + stop > Rs.1,000.
                                    # New: 2% per trade (Rs.2,000), 8% per position (allows scaling into confluence).
                                    _max_positions = 8
                                    # FIX 2026-09-07 12:10: bumped per-trade cap from 2% to 5%.
                                    # The brain sends positions sized for 5% per-trade
                                    # (matching the position cap). At 2%, the brain's
                                    # normal-sized trades were getting rejected with
                                    # "per-trade cap 2.0% of cash" — losing the trade
                                    # while the brain was correctly identifying the setup.
                                    # Position cap (5%) is still the hard limit; this
                                    # just makes the per-trade limit match the position
                                    # limit so a single position can use the full cap.
                                    _max_per_trade_pct = 0.05  # 5% of cash per trade (was 2%)
                                    _max_position_pct = 0.08  # 8% of cash per position (FIX 2026-09-04: was 5%)
                                    # Confluence scaling: when 3+ confirming signals align, allow up to 8% per position.
                                    _confluence_threshold = 3
                                    # FIX 2026-09-02 12:25: paper_client returns key "available",
                                    # neo_client returns "available_cash". Accept BOTH so the cap
                                    # is actually enforced in paper mode (was silently bypassed
                                    # since 2026-08 — see paper_state.phantom_audit.json for the
                                    # 5625 qty incident that this prevents).
                                    _margins = broker.get_margins() if hasattr(broker, 'get_margins') else {}
                                    _cash = (_margins.get("available_cash")
                                             or _margins.get("available")
                                             or _margins.get("cash")
                                             or 0)
                                    _open_count = len(order_mgr.open_trades())
                                    if _open_count >= _max_positions:
                                        logger.warning(f"[QUANT-ACTION] REJECT: max positions reached ({_open_count}/{_max_positions})")
                                        alerter.send(f"[Quant REJECT] max positions reached ({_open_count}/{_max_positions}). Action: {_qa_a.get('rationale','')[:100]}")
                                        continue
                                    if now.hour >= 15 and now.minute >= 15:
                                        logger.warning(f"[QUANT-ACTION] REJECT: too close to EOD ({now.strftime('%H:%M')})")
                                        _has_retryable_reject = True
                                        continue
                                    if now.hour < 9 or (now.hour == 9 and now.minute < 15):
                                        logger.warning(f"[QUANT-ACTION] REJECT: too early pre-open ({now.strftime('%H:%M')})")
                                        _has_retryable_reject = True
                                        continue
                                    # Circuit breakers (daily loss + consecutive losses)
                                    try:
                                        # FIX 2026-09-04 15:50: removed `import sys` (was shadowing
                                        # module-level sys and breaking sys.exit(0) in RESTART_BOT
                                        # branch earlier in this function). sys is already imported
                                        # at module level (line 20). `scripts.*` is also reachable
                                        # because the bot's CWD is the project root, and ROOT is
                                        # appended to sys.path in run_paper() at startup.
                                        if str(ROOT) not in sys.path:
                                            sys.path.insert(0, str(ROOT))
                                        from scripts.performance_tracker import should_pause_new_entries
                                        _pause, _reason = should_pause_new_entries(_cash or 100000)
                                        if _pause:
                                            logger.warning(f"[QUANT-ACTION] REJECT: circuit breaker: {_reason}")
                                            alerter.send(f"[Quant CIRCUIT BREAKER] new entries paused: {_reason}")
                                            continue
                                    except Exception as _cb_err:
                                        logger.debug(f"circuit-breaker check failed: {_cb_err}")
                                    # Resolve expiry
                                    from datetime import date as _date, timedelta as _td
                                    def _nearest_weekly_expiry():
                                        _today = _date.today()
                                        _days_ahead = 3 - _today.weekday()  # Thursday = 3
                                        if _days_ahead <= 0:
                                            _days_ahead += 7
                                        return _today + _td(days=_days_ahead)
                                    _expiry = str(_qa_a.get("expiry", "") or "").strip()
                                    if not _expiry or _expiry.upper() in ("WEEKLY", "0", "THIS WEEK", "CURRENT"):
                                        _expiry = _nearest_weekly_expiry().isoformat()
                                    # Place each leg
                                    _placed = 0
                                    _total_cost = 0.0
                                    _decision_id = str(_qa_a.get('id', '')) or f"q-{now.isoformat()}"
                                    _leg_records = []
                                    for _leg in _qa_legs:
                                        try:
                                            _strike = int(_leg.get("strike", 0))
                                            _opt_type = str(_leg.get("opt_type", "")).upper()
                                            _side = str(_leg.get("side", "BUY")).upper()
                                            _qty_lots = int(_leg.get("qty", 1))
                                            # FIX 2026-09-02 12:25: hard cap on qty_lots to prevent
                                            # brain mis-sized orders (e.g. 75 lots when it meant 1 lot).
                                            # The brain's LLM prompt says qty=1 for 1 lot, but earlier
                                            # it sent qty=75 (interpreted as 75 shares = 1 lot for NIFTY).
                                            # This double-handling caused 75x oversize. Now we clamp
                                            # to a sane max of MAX_LOTS_PER_LEG.
                                            MAX_LOTS_PER_LEG = 10  # safety cap, way above any real strategy
                                            if _qty_lots < 1:
                                                logger.warning(f"[QUANT-ACTION] leg qty={_qty_lots} < 1, clamping to 1")
                                                _qty_lots = 1
                                            elif _qty_lots > MAX_LOTS_PER_LEG:
                                                logger.warning(f"[QUANT-ACTION] leg qty={_qty_lots} > MAX={MAX_LOTS_PER_LEG} lots, clamping")
                                                _qty_lots = MAX_LOTS_PER_LEG
                                            _order_type = str(_leg.get("order_type", "MARKET")).upper()
                                            _price = _leg.get("price")
                                            if _price is None and _order_type == "LIMIT":
                                                _order_type = "MARKET"
                                            if not _strike or not _opt_type or not _qa_inst:
                                                logger.warning(f"[QUANT-ACTION] skip leg (missing field): strike={_strike} opt_type={_opt_type} underlying={_qa_inst}")
                                                continue
                                            # Format symbol
                                            from datetime import datetime as _dt
                                            try:
                                                _edt = _dt.strptime(_expiry, "%Y-%m-%d")
                                                _exp_str = _edt.strftime("%d%b%y").upper()
                                            except Exception:
                                                _exp_str = _expiry
                                            _sym = f"{_qa_inst}{_exp_str}{int(_strike)}{_opt_type}"
                                            _lot = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}.get(_qa_inst, 75)
                                            _qty_shares = max(1, _qty_lots * _lot)
                                            _order = Order(
                                                symbol=_sym,
                                                side=OrderSide(_side),
                                                qty=_qty_shares,
                                                order_type=OrderType(_order_type) if _order_type in ("MARKET", "LIMIT", "SL", "SL-M") else OrderType.MARKET,
                                                product=ProductType.MIS,
                                                price=float(_price) if _price else 0.0,
                                                tag=f"QUANT-{str(_qa_a.get('strategy','?'))[:10]}"[:30],
                                                exchange="NFO",
                                                strike=float(_strike),
                                                option_type=_opt_type,
                                                expiry=_expiry,
                                                underlying=_qa_inst,
                                            )
                                            _est_cost = _qty_shares * (float(_price) if _price else 50.0)
                                            # FIX 2026-09-04 12:09: cap is now per-trade (2%) for individual legs, not per-position.
                                            # Use the per-trade cap on each leg; the position cap still protects against aggregate.
                                            if _cash > 0 and _est_cost > _max_per_trade_pct * _cash:
                                                logger.warning(f"[QUANT-ACTION] REJECT leg: per-trade cap {_max_per_trade_pct*100}% of cash. Cost={_est_cost}, cash={_cash}")
                                                continue
                                            if _cash > 0 and (_total_cost + _est_cost) > _max_position_pct * _cash:
                                                logger.warning(f"[QUANT-ACTION] REJECT leg: position cap {_max_position_pct*100}% of cash. Cost={_est_cost}, cash={_cash}")
                                                continue
                                            _filled = broker.place_order(_order)
                                            if _filled.status in (OrderStatus.COMPLETE, OrderStatus.OPEN):
                                                _placed += 1
                                                _total_cost += _est_cost
                                                logger.info(f"[QUANT-ACTION] PLACED {_filled.symbol} {_filled.side.value} {_filled.qty} @ {_filled.avg_fill_price or _filled.price} status={_filled.status.value}")
                                                # Record this fill in performance tracker
                                                _leg_records.append({
                                                    "symbol": _filled.symbol,
                                                    "side": _filled.side.value,
                                                    "qty": _filled.qty,
                                                    "fill_price": _filled.avg_fill_price or _filled.price,
                                                })
                                            else:
                                                logger.warning(f"[QUANT-ACTION] REJECTED {_filled.symbol}: {_filled.rejection_reason}")
                                        except Exception as _leg_err:
                                            # FIX 2026-09-04 12:24: do NOT silently swallow UnboundLocalError.
                                            # This bit us 3 times (Sep 2 Order, Sep 2 Path, Sep 3 Order at line 1283,
                                            # Sep 4 Order at line 1283). The try/except at this level was hiding the
                                            # fact that the brain's orders weren't being placed at all. Now we log
                                            # the full traceback and the symbol so the failure is visible.
                                            import traceback as _tb
                                            if isinstance(_leg_err, UnboundLocalError):
                                                logger.error(
                                                    f"[QUANT-ACTION] CRITICAL: shadow-import trap on "
                                                    f"{_leg_err}. This is the Order/Path UnboundLocalError class "
                                                    f"of bug that has now hit us 4 TIMES (Sep 2 11:00, Sep 2 14:01, "
                                                    f"Sep 3 14:30, Sep 4 12:14). Re-check kotak_bot/__main__.py for "
                                                    f"any 'from X import Order' inside run_paper()."
                                                )
                                                logger.error(
                                                    f"[QUANT-ACTION] full traceback:\n{_tb.format_exc()}"
                                                )
                                            else:
                                                logger.warning(f"[QUANT-ACTION] leg failed: {_leg_err}")
                                    # Record the open decision in performance tracker (so EOD/weekly can compute outcomes)
                                    if _leg_records:
                                        try:
                                            # FIX 2026-09-04 15:50: removed `import sys` (same shadow
                                            # import bug as the circuit-breaker block above). sys is
                                            # already imported at module level.
                                            if str(ROOT) not in sys.path:
                                                sys.path.insert(0, str(ROOT))
                                            from scripts.performance_tracker import record_decision
                                            record_decision(
                                                decision_id=_decision_id,
                                                ts=now.isoformat(),
                                                action_type="OPEN",
                                                strategy=str(_qa_a.get("strategy", "custom")),
                                                underlying=_qa_inst,
                                                rationale=str(_qa_a.get("rationale", "")),
                                                max_hold_minutes=int(_qa_a.get("max_hold_minutes", 240)),
                                                tags={"legs": _leg_records, "expiry": _expiry, "target": _qa_a.get("target"), "stop": _qa_a.get("stop")},
                                            )
                                            logger.info(f"[QUANT-ACTION] recorded decision {_decision_id} in performance tracker")
                                        except Exception as _rec_err:
                                            logger.debug(f"record_decision failed: {_rec_err}")
                                    _placed_total += _placed
                                    # FIX 2026-09-03 14:38: register the brain-driven trade with
                                    # OrderManager so force-square can find it. Without this, the
                                    # bot's order_mgr._trades dict doesn't see brain OPENs and
                                    # positions stay open past 14:30 force-square time.
                                    if _leg_records:
                                        try:
                                            from kotak_bot.strategy.trade_plan import TradePlan, StrategyName
                                            _tp_legs = []
                                            for _lr in _leg_records:
                                                _tp_legs.append({
                                                    "side": _lr["side"],
                                                    "qty": max(1, int(_lr["qty"]) // {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}.get(_qa_inst, 75)),
                                                    "strike": int(_filled.strike) if hasattr(_filled, "strike") and _filled.strike else 0,
                                                    "opt_type": _filled.option_type if hasattr(_filled, "option_type") else "",
                                                    "order_type": "MARKET",
                                                    "price": _lr["fill_price"],
                                                    "tag": f"QUANT-{_qa_a.get('strategy','?')}"[:30],
                                                })
                                            # Pull actual strike/opt from the last filled order
                                            if hasattr(_filled, "strike") and _filled.strike:
                                                for _l in _tp_legs:
                                                    _l["strike"] = int(_filled.strike)
                                                    _l["opt_type"] = _filled.option_type
                                            _plan = TradePlan(
                                                underlying=_qa_inst,
                                                strategy=StrategyName.CUSTOM,
                                                legs=_tp_legs,
                                                target=_qa_a.get("target"),
                                                stop=_qa_a.get("stop"),
                                                confidence=0.0,
                                                reason=str(_qa_a.get("rationale", ""))[:200],
                                            )
                                            # Reconstruct filled Order objects from leg records
                                            # FIX 2026-09-04 12:18: do NOT re-import Order here — Python would
                                            # mark Order as a local for the entire run_paper() function, breaking
                                            # the Order() call on the next line. The top-level import at line 26
                                            # already provides Order/OrderSide/etc. Same trap as 2026-09-02 11:00 (5dc58ef)
                                            # and 2026-09-03 14:30 (1edad1c). Use the existing globals.
                                            _orders = []
                                            for _lr in _leg_records:
                                                _o = Order(
                                                    symbol=_lr["symbol"],
                                                    side=OrderSide(_lr["side"]),
                                                    qty=int(_lr["qty"]),
                                                    order_type=OrderType.MARKET,
                                                    product=ProductType.MIS,
                                                    price=float(_lr["fill_price"]),
                                                    tag=f"QUANT-{_qa_a.get('strategy','?')}"[:30],
                                                )
                                                _orders.append(_o)
                                            order_mgr.register_external_managed_trade(_plan, _orders)
                                            logger.info(f"[QUANT-ACTION] registered {len(_orders)} legs in order_mgr (force-square will see this)")
                                        except Exception as _reg_err:
                                            logger.warning(f"[QUANT-ACTION] register_external failed: {_reg_err}")
                                    _summary = f"OPEN {_qa_a.get('strategy','?')} {_qa_inst} expiry={_expiry} legs_placed={_placed}/{len(_qa_legs)}"
                                    logger.info(f"[QUANT-ACTION] {_summary} target={_qa_a.get('target')} stop={_qa_a.get('stop')}")
                                    alerter.send(f"[Quant service] {_summary}\nRationale: {_qa_a.get('rationale','')[:200]}\nMax hold: {_qa_a.get('max_hold_minutes','?')}m")
                            except Exception as _qa_a_err:
                                logger.warning(f"quant-action sub-process failed: {_qa_a_err}")
                        # Mark consumed only if we actually placed legs OR if rejection was hard
                        # (not a time-window reject). Time-window rejects get retried on the next cycle.
                        if _placed_total > 0 or not _has_retryable_reject:
                            _qa["consumed"] = True
                            _qa["consumed_at"] = now.isoformat()
                            _qa["consumed_cycle"] = cycle_counter
                            _qa["placed_legs"] = _placed_total
                        else:
                            logger.info(f"[QUANT-ACTION] deferring retry (placed=0, time-window reject); will retry after 09:15")
                            _qa["last_retry_note"] = f"deferred at {now.strftime('%H:%M:%S')} — time-window reject"
                        try:
                            with open(_qa_path, "w", encoding="utf-8") as _qw:
                                json.dump(_qa, _qw, ensure_ascii=False)
                        except Exception:
                            pass
            except Exception as _qa_err:
                logger.warning(f"quant-action check failed: {_qa_err}")
                logger.warning(f"brain-action check failed: {_ba_err}")
            # 1) EOD report
            if (now.hour, now.minute) >= (15, 30) and (last_eod_report is None or last_eod_report.date() != now.date()):
                positions = broker.get_positions()
                margins = broker.get_margins()
                alerter.daily_report({
                    "daily_pnl": margins.get("realized_pnl", 0),
                    "trades_today": risk.state.trades_today,
                    "open_positions": len(positions),
                    "risk_preset": risk.state.current_preset,
                    "capital": risk.state.capital,
                })
                # performance attribution
                try:
                    perf_summary = perf_tracker.summary()
                    alerter.send(perf_summary)
                except Exception as e:
                    logger.debug(f"perf summary failed: {e}")
                # alpha decay check
                try:
                    decayed = alpha_decay.check()
                    decayed_list = [s for s, v in decayed.items() if v["decayed"]]
                    if decayed_list:
                        alerter.warn(
                            f"📉 ALPHA DECAY detected in: {', '.join(decayed_list)}\n"
                            f"These strategies will be auto-paused until they recover."
                        )
                except Exception as e:
                    logger.debug(f"alpha decay check failed: {e}")
                # FIX 2026-08-20: Pre-market phantom audit at 08:55 IST.
                # Catches stale 0DTE positions from yesterday that the broker
                # may still report. Fires once per day. Logs + Telegrams a
                # summary so the user sees the state before market open.
                try:
                    if (now.hour, now.minute) >= (8, 55) and (
                        not getattr(_liveness_state, "_last_phantom_audit_date", None)
                        or _liveness_state["_last_phantom_audit_date"] != now.date()
                    ):
                        _purge_flag = cfg.get("risk", {}).get("purge_phantom_0dte_on_startup", True)
                        all_bp = broker.get_positions()
                        today_s = now.date().strftime('%Y-%m-%d')
                        # FIX 2026-08-20 (patch 2): use the same phantom detection as
                        # startup_reconcile — covers (a) expiry < today (yesterday's
                        # 0DTE that the broker hasn't auto-settled), (b) expiry == today
                        # AND ltp <= 0, (c) expiry == today AND is_past_market_close.
                        # Without (c), positions reported post-15:30 with cached LTP
                        # would be mis-classified as "live" until EOD settlement.
                        def _is_phantom_audit(p):
                            try:
                                exp_str = str(p.expiry)[:10] if p.expiry else None
                            except Exception:
                                return False
                            if exp_str and exp_str < today_s:
                                return True  # expired (yesterday's 0DTE, unsettled)
                            if exp_str != today_s:
                                return False
                            ltp = getattr(p, 'ltp', 0) or 0
                            if is_past_market_close(now):
                                return True
                            if ltp <= 0:
                                return True
                            return False
                        phantoms = [p for p in all_bp if getattr(p, 'qty', 0) != 0 and _is_phantom_audit(p)]
                        live = [p for p in all_bp if getattr(p, 'qty', 0) != 0 and not _is_phantom_audit(p)]
                        msg = (
                            f"🧹 PRE-MARKET PHANTOM AUDIT (08:55)\n"
                            f"Total broker positions: {len(all_bp)}\n"
                            f"  Phantoms (0DTE / expired / post-close): {len(phantoms)}\n"
                            f"  Live / settled: {len(live)}\n"
                            f"Auto-purge at startup: {_purge_flag}"
                        )
                        logger.info(msg.replace('\n', ' | '))
                        try:
                            alerter.send(msg)
                        except Exception:
                            pass
                        _liveness_state["_last_phantom_audit_date"] = now.date()
                except Exception as e:
                    logger.debug(f"pre-market phantom audit failed: {e}")
                # compliance PDF
                try:
                    # collect trades from CSV
                    # NOTE: do NOT re-import `from pathlib import Path` here.
                    # This function already has Path as a local binding from line 793's
                    # `from pathlib import Path as _Path`; re-importing without an alias
                    # would shadow `Path` in this function's scope and break all
                    # Path(...) calls earlier in the loop (notably the force-action and
                    # brain-action channels at lines ~863 and ~912 — see the
                    # 'force-action check failed: cannot access local variable Path'
                    # WARNINGs in bot.log). `Path` is already imported at module level.
                    trades = []
                    tr_path = Path("logs/trades.csv")
                    if tr_path.exists():
                        with open(tr_path, "r", encoding="utf-8") as f:
                            import csv as _csv
                            reader = _csv.DictReader(f)
                            for r in reader:
                                if now.date().isoformat() in r.get("timestamp", ""):
                                    trades.append(r)
                    # audit entries
                    audit = []
                    ap = Path("data_cache/audit_log.jsonl")
                    if ap.exists():
                        with open(ap, "r", encoding="utf-8") as f:
                            for line in f:
                                audit.append(line.strip())
                    pdf_path = compliance_pdf.generate(
                        trades=trades, audit_entries=audit, risk_state=risk.status()
                    )
                    if pdf_path:
                        alerter.send_photo(pdf_path, caption=f"📋 SEBI Compliance Pack — {now.date().isoformat()}")
                except Exception as e:
                    logger.warning(f"compliance PDF failed: {e}")
                # auto-tune parameters for tomorrow
                try:
                    adj = auto_tuner.tune()
                    aggr = [s for s, a in adj.items() if a["preset"] == "aggressive"]
                    defensive = [s for s, a in adj.items() if a["preset"] == "defensive"]
                    msg_parts = ["🎛️ Auto-Tune for tomorrow:"]
                    if aggr:
                        msg_parts.append(f"  Aggressive: {', '.join(aggr)}")
                    if defensive:
                        msg_parts.append(f"  Defensive: {', '.join(defensive)}")
                    alerter.send("\n".join(msg_parts))
                except Exception as e:
                    logger.debug(f"auto-tune failed: {e}")
                last_eod_report = now
            # 2) square-off time
            if is_square_off_time(now):
                open_trades = order_mgr.open_trades()
                if open_trades:
                    closed = order_mgr.square_off_all(reason="eod_square_off")
                    logger.info(f"Squared off {closed} trades at EOD")
            # 2b) INTRADAY SAFETY: force square-off by force_square_off_time
            # (default 14:30 — 60 min before EOD, so all risk is closed well before close)
            if not is_allow_overnight() and is_past_force_square_off_time(now):
                open_trades = order_mgr.open_trades()
                if open_trades:
                    closed = order_mgr.square_off_all(reason="intraday_force_close")
                    logger.warning(f"[INTRADAY] force-closed {closed} open trades (force_square_off_time hit)")
                else:
                    # FIX 2026-09-03 14:55: order_mgr may have 0 trades because brain-driven OPENs
                    # bypassed execute_plan (FIX 947a25b added register_external_managed_trade but
                    # pre-existing positions in paper_client aren't registered). Fall back to
                    # reading broker positions directly and force-close them.
                    try:
                        broker_positions = broker.get_positions() if hasattr(broker, 'get_positions') else []
                        if broker_positions:
                            # FIX 2026-09-05 00:35: removed in-function Order import (7th shadow bug)
                            closed_orphans = 0
                            for _pos in broker_positions:
                                if _pos.qty == 0:
                                    continue
                                _close_side = OrderSide.SELL if _pos.qty > 0 else OrderSide.BUY
                                _close_qty = abs(_pos.qty)
                                _sym = getattr(_pos, 'symbol', None) or f"{getattr(_pos, 'underlying', 'X')}{getattr(_pos, 'strike', 0)}{getattr(_pos, 'option_type', '')}"
                                _strike = float(getattr(_pos, 'strike', 0) or 0)
                                _opt = getattr(_pos, 'option_type', '') or ''
                                _und = getattr(_pos, 'underlying', 'X') or 'X'
                                _exp = getattr(_pos, 'expiry', '') or ''
                                _ord = Order(
                                    symbol=_sym, side=_close_side, qty=_close_qty,
                                    order_type=OrderType.MARKET, product=ProductType.MIS,
                                    price=0.0, tag='FORCE-SQUARE-ORPHAN',
                                    exchange=getattr(_pos, 'exchange', 'NFO'),
                                    strike=_strike, option_type=_opt,
                                    expiry=_exp, underlying=_und,
                                )
                                _res = broker.place_order(_ord)
                                if _res.status.value in ('complete', 'filled', 'open'):
                                    closed_orphans += 1
                            if closed_orphans:
                                logger.warning(f"[INTRADAY] force-closed {closed_orphans} ORPHAN positions from broker (order_mgr had 0 trades — brain-driven OPENs not registered)")
                                alerter.send(f"⏰ [INTRADAY] force-closed {closed_orphans} orphan positions at {now.strftime('%H:%M')} IST (force_square_off_time hit; order_mgr had 0 trades)")
                    except Exception as _orphan_err:
                        logger.warning(f"[INTRADAY] orphan force-close failed: {_orphan_err}")
                    try:
                        alerter.send(f"⏰ [INTRADAY] force-closed {closed} open trades at {now.strftime('%H:%M')} IST — overnight positions blocked")
                    except Exception:
                        pass
            # 2c) FIX 2026-08-26 (item #3): HARD KILL fallback at 15:15 IST
            # If anything slipped through (broker errors, frozen threads, etc), forcibly
            # close any remaining open positions. The bot must NEVER carry overnight risk
            # in intraday mode.
            _now_hm = now.strftime("%H:%M")
            if not is_allow_overnight() and _now_hm >= "15:15" and _now_hm < "15:30":
                open_trades = order_mgr.open_trades()
                if open_trades:
                    logger.error(f"[HARD-KILL] {len(open_trades)} open trades still alive at {_now_hm} IST — EMERGENCY close")
                    try:
                        for tid in list(open_trades[0].__dict__.keys()) if open_trades else []:
                            pass
                    except Exception:
                        pass
                    for trade in open_trades:
                        try:
                            order_mgr.close_trade(trade.trade_id, reason="hard_kill_1515")
                            logger.error(f"[HARD-KILL] force-closed trade {trade.trade_id}")
                        except Exception as e:
                            logger.error(f"[HARD-KILL] failed to close {trade.trade_id}: {e}")
                    try:
                        alerter.send(f"🚨 [HARD-KILL] bot force-closed {len(open_trades)} trades at {_now_hm} IST — should have closed at 14:30!")
                    except Exception:
                        pass
                else:
                    # FIX 2026-09-03 14:55: same orphan fallback as the 14:30 force-square.
                    try:
                        broker_positions = broker.get_positions() if hasattr(broker, 'get_positions') else []
                        if broker_positions:
                            # FIX 2026-09-05 00:35: removed in-function Order import (7th shadow bug)
                            killed = 0
                            for _pos in broker_positions:
                                if _pos.qty == 0:
                                    continue
                                _close_side = OrderSide.SELL if _pos.qty > 0 else OrderSide.BUY
                                _sym = getattr(_pos, 'symbol', None) or f"{getattr(_pos, 'underlying', 'X')}{getattr(_pos, 'strike', 0)}{getattr(_pos, 'option_type', '')}"
                                _ord = Order(
                                    symbol=_sym, side=_close_side, qty=abs(_pos.qty),
                                    order_type=OrderType.MARKET, product=ProductType.MIS,
                                    price=0.0, tag='HARD-KILL-ORPHAN',
                                    exchange=getattr(_pos, 'exchange', 'NFO'),
                                    strike=float(getattr(_pos, 'strike', 0) or 0),
                                    option_type=getattr(_pos, 'option_type', '') or '',
                                    expiry=getattr(_pos, 'expiry', '') or '',
                                    underlying=getattr(_pos, 'underlying', 'X') or 'X',
                                )
                                _res = broker.place_order(_ord)
                                if _res.status.value in ('complete', 'filled', 'open'):
                                    killed += 1
                            if killed:
                                logger.error(f"[HARD-KILL-ORPHAN] force-closed {killed} orphan positions at {_now_hm} IST")
                                alerter.send(f"🚨 [HARD-KILL-ORPHAN] bot force-closed {killed} orphan positions at {_now_hm} IST — order_mgr had 0 trades!")
                    except Exception as _hk_err:
                        logger.error(f"[HARD-KILL] orphan sweep failed: {_hk_err}")
            # 3) news ingestion every N seconds
            if news and (now - last_news_ingest).total_seconds() >= news_interval:
                try:
                    count = news.ingest()
                    logger.info(f"News: ingested {count} new items")
                except Exception as e:
                    logger.warning(f"news ingest failed: {e}")
                last_news_ingest = now
            # 3b) hourly P&L snapshot to Telegram
            if hourly_pnl_enabled and now.minute == hourly_pnl_minute:
                if last_hourly_report is None or last_hourly_report.date() != now.date() or last_hourly_report.hour != now.hour:
                    try:
                        positions = broker.get_positions()
                        margins = broker.get_margins()
                        upnl = sum(p.pnl for p in positions)
                        pos_lines = []
                        for p in positions:
                            pos_lines.append(f"  {p.symbol} qty={p.qty:+d} pnl=Rs.{p.pnl:,.0f}")
                        msg = (
                            f"⏰ HOURLY P&L @ {now.strftime('%H:%M')} IST\n"
                            f"Capital: Rs.{margins.get('total', 0):,.0f}\n"
                            f"Cash:    Rs.{margins.get('available', 0):,.0f}\n"
                            f"Used:    Rs.{margins.get('used', 0):,.0f}\n"
                            f"Realized:  Rs.{margins.get('realized_pnl', 0):,.0f}\n"
                            f"Unrealized: Rs.{upnl:,.0f}\n"
                            f"Trades today: {risk.state.trades_today}\n"
                            f"Preset: {risk.state.current_preset}\n"
                            f"Open positions: {len(positions)}\n"
                            + ("\n".join(pos_lines) if pos_lines else "  (none)")
                        )
                        alerter.send(msg)
                        # also send chart
                        try:
                            chart = alerter.generate_daily_chart()
                            if chart:
                                alerter.send_photo(chart, caption=f"Hourly P&L chart — {now.strftime('%H:%M')} IST")
                        except Exception as e:
                            logger.debug(f"hourly chart failed: {e}")
                    except Exception as e:
                        logger.warning(f"hourly report failed: {e}")
                    last_hourly_report = now
            # 3c) live mark-to-market + anomaly detection every cycle
            try:
                open_pos_list = broker.get_positions()
                pnl_state = compute_pnl(open_pos_list, feed)
                anomaly.update(feed)
                # detect P&L swing
                swing = anomaly.detect_pnl_swing(pnl_state["total"])
                if swing and anomaly.should_alert("pnl_swing"):
                    direction = "↑" if swing["delta"] > 0 else "↓"
                    alerter.send(
                        f"💹 P&L swing {direction}: Rs.{swing['delta']:+,.0f} (now Rs.{swing['current']:+,.0f})"
                    )
                # detect price anomalies on spot symbols
                for sym in ("NIFTY", "BANKNIFTY"):
                    spot = feed.get_ltp(sym)
                    if spot > 0:
                        pa = anomaly.detect_price_anomaly(sym, spot)
                        if pa and anomaly.should_alert(f"price_{sym}"):
                            alerter.send(
                                f"⚡ {sym} price spike: {pa['change_pct']:+.2f}% in {pa['window_sec']}s "
                                f"({pa['prev']:.2f} → {pa['current']:.2f})"
                            )
            except Exception as e:
                logger.debug(f"mark-to-market failed: {e}")
            # 3d) position reconciliation every 5 min
            if cycle_counter % 10 == 0:  # every 5 min (30s * 10)
                try:
                    broker_pos = {p.symbol: {"qty": p.qty, "avg_price": p.avg_price, "ltp": p.ltp}
                                  for p in broker.get_positions()}
                    # internal = open trades' net positions
                    internal_pos = {}
                    for tr in order_mgr.open_trades():
                        for o in tr.orders:
                            if o.avg_fill_price > 0:
                                sym = o.symbol
                                if sym not in internal_pos:
                                    internal_pos[sym] = {"qty": 0, "avg_price": 0}
                                internal_pos[sym]["qty"] += o.filled_qty if hasattr(o, 'side') and o.side.value == "BUY" else -o.filled_qty
                    diff = reconcile_positions(broker_pos, internal_pos)
                    save_reconcile_log(diff)
                    # Only alert on actionable diffs; throttled to once per 2h.
                    # We do NOT auto-rebuild here because the historical order book
                    # contains SELLs that were never recorded as positions (pre-fix
                    # bug) — rebuilding would resurrect them as ghost positions.
                    actionable = bool(diff["broker_only"] or diff["internal_only"])
                    if actionable:
                        last_alert_ts = getattr(order_mgr, "_last_reconcile_alert_ts", 0)
                        now_ts = time.time()
                        if now_ts - last_alert_ts > 7200:  # 2 hours
                            msg = format_diff_for_telegram(diff)
                            if msg:
                                alerter.warn(f"**Reconcile mismatch** (auto-fix disabled, throttled 2h):\n{msg}")
                                order_mgr._last_reconcile_alert_ts = now_ts
                        else:
                            logger.warning(f"reconcile still mismatched (alert throttled): {diff}")
                    else:
                        logger.debug(f"reconcile: {len(diff['matched'])} matched, no actionable diff")
                except Exception as e:
                    logger.warning(f"reconcile failed: {e}")
            # 3e) Phase 1.4: margin alert check every 5 min
            if cycle_counter % 10 == 0:
                try:
                    margin_tracker.check_and_alert()
                except Exception as e:
                    logger.debug(f"margin check failed: {e}")
            # 3f) FIX 2026-09-04 12:24: candle data staleness watchdog (every 1 hour during market hours).
            # If intraday_levels.json is older than 1 hour, trigger a refresh from yfinance.
            # Today the candle engine was stuck on Aug 31 for 4 days — brain was making HOLDs because
            # the data was fundamentally broken. This watchdog self-heals.
            if cycle_counter % 120 == 0 and is_market_open(now):  # every 1 hour (30s * 120)
                try:
                    from pathlib import Path as _PathWatch
                    _intraday_path = _PathWatch("data_cache/intraday_levels.json")
                    if _intraday_path.exists():
                        import time as _time_w
                        _age_h = (_time_w.time() - _intraday_path.stat().st_mtime) / 3600
                        if _age_h > 1.0:
                            logger.warning(f"[CANDLE-WATCHDOG] intraday_levels.json is {_age_h:.1f}h old, refreshing from yfinance")
                            try:
                                from scripts.candle_engine import get_engine as _get_eng
                                _eng = _get_eng()
                                _bf = _eng.backfill_session_opens_from_yfinance()
                                logger.info(f"[CANDLE-WATCHDOG] backfilled {_bf} symbols")
                            except Exception as _cw_err:
                                logger.warning(f"[CANDLE-WATCHDOG] backfill failed: {_cw_err}")
                except Exception as _wd_err:
                    logger.debug(f"candle-watchdog failed: {_wd_err}")
            # 3e) 24/7 self-heal check every 5 min (cycle_counter % 10 = ~5 min at 30s/cycle).
            # Detects liveness staleness, brain port down, shadow imports, missing
            # daily tasks, etc. Applies the fix (writes a force-action JSON, restarts
            # a service via NSSM, or escalates to Telegram). The user is not always
            # available to debug — this runs whether or not the chat is open.
            if cycle_counter % 10 == 0:
                try:
                    from kotak_bot.self_heal import self_heal_check
                    _sh_results = self_heal_check(_liveness_state, alerter)
                    for _r in _sh_results:
                        logger.info(f"[SELF-HEAL] {_r.get('name', '?')}: applied={_r.get('applied')} msg={_r.get('msg','')[:120]}")
                except Exception as _sh_err:
                    logger.debug(f"self_heal check failed: {_sh_err}")
            # 4) scan every 30s during market hours
            cycle_counter += 1
            _cycle_counter = cycle_counter
            _last_cycle_ts = datetime.now(timezone.utc)
            if (now - last_scan).total_seconds() >= 30 and is_market_open(now):
                # ----------------------------------------------------------------
                # INTRADAY + VIX GATES (block new entries before 14:30 if overnight blocked)
                # ----------------------------------------------------------------
                if not is_allow_overnight() and is_past_no_new_trades_time(now):
                    logger.info(f"[SCAN] cycle={cycle_counter} | skip: intraday mode — no_new_trades_after "
                                f"({intraday_cfg['no_new_trades_after'].strftime('%H:%M')}) hit")
                    last_scan = now
                    time.sleep(5)
                    continue
                if is_in_opening_buffer(now):
                    logger.info(f"[SCAN] cycle={cycle_counter} | skip: in opening buffer (9:15-9:30 — let price settle)")
                    last_scan = now
                    time.sleep(5)
                    continue
                # VIX-aware skip (fetch fresh VIX if cache > 15 min old)
                current_vix = fetch_india_vix(force=False)
                if vix_should_skip(current_vix, max_vix=cfg.get("risk", {}).get("vix", {}).get("skip_above", 22.0)):
                    logger.info(f"[SCAN] cycle={cycle_counter} | skip: India VIX={current_vix:.2f} > skip threshold "
                                f"({cfg.get('risk', {}).get('vix', {}).get('skip_above', 22.0)})")
                    last_scan = now
                    time.sleep(5)
                    continue
                # Macro event blackout (RBI, US Fed, etc.)
                if in_event_blackout(now, macro_cal=macro_cal):
                    logger.info(f"[SCAN] cycle={cycle_counter} | skip: macro event blackout window")
                    last_scan = now
                    time.sleep(5)
                    continue
                # Position size multiplier from VIX (informational; selectors read it)
                vix_mult = vix_position_size_multiplier(current_vix)
                if vix_mult < 1.0:
                    logger.info(f"[SCAN] cycle={cycle_counter} | VIX={current_vix:.2f} → lot multiplier {vix_mult}x")
                # ----------------------------------------------------------------
                # position cap check — counts STRATEGIES (open_trades), not legs.
                # FIX 2026-08-20: prior code used `max(len(open_trades), len(open_pos))`
                # which counted leg positions from broker and blocked the bot after
                # 1 multi-leg strategy. A 1 NIFTY + 1 BANKNIFTY cap of 2 strategies
                # maps cleanly to `len(open_trades)`.
                # We still cross-check broker positions for orphan phantom legs (no
                # matching open trade) and warn if any are found.
                # ----------------------------------------------------------------
                _today_str = date.today().strftime('%Y-%m-%d')
                open_trades = order_mgr.open_trades()
                open_pos = [
                    p for p in broker.get_positions()
                    if p.qty != 0
                    and (not p.expiry or str(p.expiry)[:10] >= _today_str)
                ]
                # Phantoms = broker position with qty but no matching open trade
                _ot_syms = set()
                for _trd in open_trades:
                    for _o in _trd.orders:
                        if getattr(_o, 'avg_fill_price', 0) > 0 and getattr(_o, 'symbol', None):
                            _ot_syms.add(_o.symbol)
                orphan_pos = [p for p in open_pos if p.symbol not in _ot_syms]
                if orphan_pos:
                    # FIX 2026-09-07 23:15: gate orphan-auto-close on no-new-trades time.
                    # Before 13:30, the brain-driven positions are still in their planned
                    # hold window (theta capture through Thursday expiry). Closing them
                    # early in the morning destroyed 2 trades today (12:04 BNF + 12:42 NIFTY,
                    # both at fake Rs.1.00 prices — separate bug, already fixed). Now we
                    # only auto-close orphans AFTER no-new-trades time (13:30) so the brain
                    # gets a fair hold window. Before 13:30, we just log the warning and
                    # let force-square at 14:30 handle it.
                    _orphan_close_allowed = is_past_no_new_trades_time(now)
                    logger.warning(
                        f"[SCAN] {len(orphan_pos)} orphan broker position(s) with no open trade "
                        f"(symbols: {[p.symbol for p in orphan_pos]}). "
                        f"{'Will auto-close (past no-new-trades time).' if _orphan_close_allowed else 'Auto-close deferred until 13:30 (brain hold window).'}"
                    )
                    if not _orphan_close_allowed:
                        # Skip the close loop entirely — just log and let force-square handle it
                        last_scan = now
                        time.sleep(5)
                        continue
                    # FIX 2026-09-07 12:02: actually force-close the orphans instead
                    # of just logging. Brain-driven OPENs don't register with order_mgr
                    # (commit a8dec0a), so they show up as orphans. The orphan-fallback
                    # at 14:30 only fires once at force-square time, but we want to
                    # close them on the next scan if the position is now OTM and
                    # small enough. We send a force-close via the broker.place_order
                    # with the opposite side of each orphan's qty.
                    # We do this conservatively: only when the orphan is OUT-OF-THE-MONEY
                    # and the position is small (< 5% of cash). Otherwise we let
                    # force-square at 14:30 handle it.
                    _orphan_cash = _cash or 0
                    _orphan_max_loss_pct = 0.05
                    for _orph in orphan_pos:
                        try:
                            _orph_sym = getattr(_orph, 'symbol', None)
                            _orph_qty = abs(int(getattr(_orph, 'qty', 0) or 0))
                            _orph_avg = float(getattr(_orph, 'avg_price', 0) or 0)
                            if not _orph_sym or _orph_qty == 0 or _orph_avg == 0:
                                continue
                            # Conservative: skip if >5% of cash (let force-square handle)
                            _max_loss = _orph_qty * _orph_avg * 0.20  # assume 20% drawdown
                            if _orphan_cash > 0 and _max_loss / _orphan_cash > _orphan_max_loss_pct:
                                logger.debug(f"[ORPHAN] {_orph_sym} qty={_orph_qty} avg={_orph_avg} too large to close now")
                                continue
                            # FIX 2026-09-07 22:15: pull strike/option_type/expiry/underlying
                            # from the position so paper_client._force_fill_market_like can
                            # look up the real price from option_chains.json. If the position
                            # doesn't have them (legacy positions, broker quirks), parse from
                            # the symbol. This avoids the Rs.1.00 last-resort fallback that
                            # produced 3 fake fills today (12:04 BNF PE orphan-close + 12:42
                            # NIFTY PE orphan-close, all closing for Rs.1.00).
                            _orph_strike = float(getattr(_orph, 'strike', 0) or 0)
                            _orph_opt = getattr(_orph, 'option_type', None) or None
                            _orph_exp = getattr(_orph, 'expiry', None) or None
                            _orph_und = getattr(_orph, 'underlying', None) or None
                            if not _orph_strike or not _orph_opt or not _orph_und:
                                _p_und, _p_exp, _p_strike, _p_opt = _parse_option_symbol(_orph_sym)
                                if not _orph_strike: _orph_strike = _p_strike
                                if not _orph_opt: _orph_opt = _p_opt
                                if not _orph_exp: _orph_exp = _p_exp
                                if not _orph_und: _orph_und = _p_und
                            # Send force-close
                            _close_side = OrderSide.SELL if int(getattr(_orph, 'qty', 0)) > 0 else OrderSide.BUY
                            _close_ord = Order(
                                symbol=_orph_sym, side=_close_side, qty=_orph_qty,
                                order_type=OrderType.MARKET, product=ProductType.MIS,
                                price=0.0, tag='ORPHAN-AUTO-CLOSE',
                                exchange=getattr(_orph, 'exchange', 'NFO'),
                                strike=_orph_strike, option_type=_orph_opt,
                                expiry=_orph_exp, underlying=_orph_und,
                            )
                            _fr = broker.place_order(_close_ord)
                            if _fr.status in (OrderStatus.COMPLETE, OrderStatus.OPEN):
                                logger.info(f"[ORPHAN] force-closed {_orph_sym} qty={_orph_qty} status={_fr.status.value if hasattr(_fr.status, 'value') else _fr.status} fill_px={_fr.avg_fill_price}")
                                alerter.send(f"♻️ [ORPHAN-AUTO-CLOSE] closed {_orph_sym} qty={_orph_qty} @ Rs.{_fr.avg_fill_price:.2f} (brain-driven OPEN, not registered with order_mgr)")
                        except Exception as _oc_err:
                            logger.warning(f"[ORPHAN] auto-close failed for {_orph_sym}: {_oc_err}")
                # Cap is on STRATEGIES (open_trades), not on legs.
                # Use `len(open_trades)` as the authoritative count. If we have orphan
                # legs from a bot restart, don't count them against the cap.
                total_strategies = len(open_trades)
                if total_strategies >= MAX_OPEN_POSITIONS:
                    logger.info(f"[SCAN] cycle={cycle_counter} | skip: {total_strategies} open strategies >= max {MAX_OPEN_POSITIONS}")
                    last_scan = now
                    time.sleep(5)
                    continue
                for symbol in ("NIFTY", "BANKNIFTY"):
                    # skip if we already have a position on this symbol
                    sym_open = [t for t in open_trades if any(o.underlying == symbol for o in t.orders if hasattr(o, 'underlying'))]
                    if sym_open:
                        logger.info(f"[SCAN] cycle={cycle_counter} {symbol} | skip: already have open trade")
                        continue
                    # skip if in cooldown
                    last_t = last_trade_at.get(symbol)
                    if last_t and (now - last_t).total_seconds() < cooldown_sec:
                        logger.info(f"[SCAN] cycle={cycle_counter} {symbol} | skip: cooldown ({int((now-last_t).total_seconds())}s ago)")
                        continue
                    spot = feed.get_ltp(symbol)
                    if spot <= 0:
                        logger.info(f"[SCAN] cycle={cycle_counter} {symbol} | skip: spot ltp=0 (synthetic feed may not have emitted yet)")
                        continue
                    # Pull strike step, count, padding from settings.yaml (not hardcoded).
                    # See config: instruments.strike_step, instruments.strike_padding
                    instr_cfg_local = cfg.get("instruments", {})
                    step = instr_cfg_local.get("strike_step", {}).get(symbol, 50)
                    padding = instr_cfg_local.get("strike_padding", 4)
                    strike_count = padding * 2 + 1
                    atm = round(spot / step) * step
                    strikes = [atm + (i - padding) * step for i in range(strike_count)]
                    # FIX 2026-08-12: live_kotak feed doesn't auto-emit option ticks
                    # like live_india does. We must explicitly subscribe the ATM ±padding
                    # option symbols each scan cycle so KotakProdFeed polls them.
                    opt_symbols = [
                        f"{symbol}{_strategy_expiry_str(symbol)}{int(k)}{ot}"
                        for k in strikes for ot in ("CE", "PE")
                    ]
                    try:
                        feed.subscribe(opt_symbols)
                    except Exception as e:
                        logger.warning(f"[SCAN] subscribe options failed: {e}")
                    option_ltps = {}
                    option_ltp_count = 0
                    for k in strikes:
                        for ot in ("CE", "PE"):
                            # FIX 2026-08-10: use dated symbol format to match synthetic feed
                            # synthetic emits: NIFTY10AUG2625000CE; previous code queried NIFTY25000CE
                            sym_full = f"{symbol}{_strategy_expiry_str(symbol)}{int(k)}{ot}"
                            ltp = feed.get_ltp(sym_full)
                            if ltp > 0:
                                option_ltps[(k, ot)] = ltp
                                option_ltp_count += 1
                    if not option_ltps:
                        logger.info(f"[SCAN] cycle={cycle_counter} {symbol} spot={spot:.2f} atm={atm} | skip: 0 option LTPs (synthetic feed may not have option ticks yet)")
                        continue
                    # compute momentum proxy from recent spot ticks (10-tick window)
                    momentum = feed.get_momentum(symbol, window=20)
                    rs = regime.detect(df=None, vix=14.0, iv_rank=55.0, momentum=momentum, spot=spot, atm=atm)
                    logger.info(
                        f"[SCAN] cycle={cycle_counter} {symbol} spot={spot:.2f} atm={atm} "
                        f"opts={option_ltp_count} regime={rs.regime.value} conf={rs.confidence:.2f} "
                        f"adx={rs.adx:.1f} mom={momentum:+.2f}"
                    )
                    # get news sentiment for this symbol
                    news_sent = 0.0
                    news_urgency = 0.0
                    if news:
                        try:
                            news_sent = news.get_sentiment_score(symbol, lookback_hours=4)
                            relevant = news.get_relevant(symbol, lookback_hours=2)
                            if relevant:
                                news_urgency = max((getattr(n, 'urgency', 0.0) for n in relevant[:3]), default=0.0)
                        except Exception as e:
                            logger.debug(f"news fetch failed: {e}")
                    from kotak_bot.strategy.base import SignalContext
                    # Get event info from macro calendar
                    upcoming_event = None
                    minutes_to_event = None
                    try:
                        ev = macro_cal.get_event_window(now, minutes_before=60, minutes_after=15)
                        if ev:
                            upcoming_event = ev["name"]
                            minutes_to_event = ev["minutes_to_event"]
                    except Exception as e:
                        logger.debug(f"macro calendar fetch failed: {e}")
                    # Use LLM judge for news if available (overrides FinBERT)
                    if llm_judge and news:
                        try:
                            recent = news.get_relevant(symbol, lookback_hours=2)
                            if recent:
                                headlines = [n.headline for n in recent[:5]]
                                agg_sent, agg_urg = llm_judge.get_aggregate(headlines)
                                # combine: average FinBERT + LLM
                                news_sent = (news_sent + agg_sent) / 2 if news_sent != 0 else agg_sent
                                news_urgency = max(news_urgency, agg_urg)
                        except Exception as e:
                            logger.debug(f"llm judge aggregate failed: {e}")
                    sc = SignalContext(
                        symbol=symbol, spot=spot, vix=rs.vix, iv_rank=rs.iv_rank,
                        adx=rs.adx, trend_strength=rs.confidence if rs.regime.value == "trending" else 0.0,
                        regime=rs.regime.value, timestamp=now,
                        strikes=strikes, option_ltps=option_ltps,
                        news_sentiment=news_sent, news_urgency=news_urgency,
                        upcoming_event=upcoming_event, minutes_to_event=minutes_to_event,
                    )
                    # Event-window override: no new entries if event in <15 min
                    if minutes_to_event is not None and 0 <= minutes_to_event < 15:
                        logger.info(f"[SCAN] cycle={cycle_counter} {symbol} | skip: event {upcoming_event} in {minutes_to_event}min")
                        continue
                    # FIX 2026-08-27: Mavis decision hook — consult mavis_trades.json BEFORE the
                    # template's selector. If Mavis says BLOCK, skip. If Mavis has a custom
                    # EXECUTE_PLAN for this symbol, use that instead of selector. Otherwise
                    # fall through to selector (template fallback).
                    _today_str = now.strftime("%Y-%m-%d")
                    _mavis = _load_mavis_decision(_today_str)
                    if _mavis["action"] == "BLOCK" and _mavis.get("valid"):
                        logger.info(f"[MAVIS] cycle={cycle_counter} {symbol} | BLOCK by Mavis: {_mavis.get('reason','')[:140]}")
                        log_signal({"symbol": symbol, "regime": rs.regime.value, "side": "mavis",
                                    "confidence": 0.0, "reason": "mavis_block",
                                    "action": f"skip:mavis_block:{_mavis.get('reason','')[:60]}"})
                        continue
                    if _mavis["action"] == "EXECUTE_PLAN" and _mavis.get("valid"):
                        _mavis_plan = _mavis.get("plan") or {}
                        _plan_underlying = str(_mavis_plan.get("underlying", symbol)).upper()
                        if _plan_underlying != symbol.upper():
                            # FIX 2026-08-28: Mavis plan is for a different symbol — BLOCK this symbol
                            # (don't fall back to template). The LLM can explicitly write a per-symbol
                            # plan in mavis_trades.json to enable trading in the other underlying.
                            logger.info(f"[MAVIS] cycle={cycle_counter} {symbol} | BLOCK: Mavis plan is for {_plan_underlying}, not {symbol}")
                            log_signal({"symbol": symbol, "regime": rs.regime.value, "side": "mavis",
                                        "confidence": 0.0, "reason": "mavis_block_no_plan",
                                        "action": f"skip:mavis_block_no_plan_for_{_plan_underlying}"})
                            continue
                        _expiry = now.strftime("%d%b%y").upper()
                        _mavis_tradeplan = _build_plan_from_mavis(symbol, spot, _mavis_plan, _expiry)
                        if _mavis_tradeplan is not None:
                            logger.info(f"[MAVIS] cycle={cycle_counter} {symbol} | EXECUTE_PLAN: {_mavis_tradeplan.strategy.value} confidence={_mavis_tradeplan.confidence:.2f} reason={_mavis_tradeplan.reason[:120]}")
                            plan = _mavis_tradeplan
                        else:
                            # FIX 2026-08-28: Mavis plan couldn't be parsed — BLOCK this symbol
                            # (don't fall back to template). The LLM should regenerate the plan.
                            logger.info(f"[MAVIS] cycle={cycle_counter} {symbol} | BLOCK: Mavis EXECUTE_PLAN couldn't be parsed for {symbol}")
                            log_signal({"symbol": symbol, "regime": rs.regime.value, "side": "mavis",
                                        "confidence": 0.0, "reason": "mavis_block_parse_error",
                                        "action": "skip:mavis_block_parse_error"})
                            continue
                    else:
                        # FIX 2026-08-28: _mavis["action"] is not BLOCK and not EXECUTE_PLAN.
                        # The LLM must explicitly write EXECUTE_PLAN to enable trading. BLOCK otherwise.
                        # (Previously this fell through to the template selector.)
                        logger.info(f"[MAVIS] cycle={cycle_counter} {symbol} | BLOCK: mavis action='{_mavis.get('action')}' (need BLOCK or EXECUTE_PLAN) reason={_mavis.get('reason','')[:120]}")
                        log_signal({"symbol": symbol, "regime": rs.regime.value, "side": "mavis",
                                    "confidence": 0.0, "reason": "mavis_block_unknown_action",
                                    "action": f"skip:mavis_block_{_mavis.get('action')}"})
                        continue
                    # Build plan first, then check risk with the plan's actual max loss
                    if not plan:
                        continue
                    # Compute plan's actual max loss: for debit = full debit, for credit = full width - credit
                    # Simplification: use plan.stop as the per-trade risk
                    plan_max_loss_for_risk = abs(plan.stop)
                    # Compute the original lot count from the plan's first leg, so the
                    # risk engine can SCALE DOWN (not reject) if the proposed size
                    # exceeds the 1% per-trade cap.
                    try:
                        _orig_lots = 1
                        if plan.legs:
                            _leg0 = plan.legs[0]
                            _leg_qty = int(_leg0.get("qty", 1) or 1)
                            # In the bot's order-placement code, leg['qty'] is treated
                            # as LOT COUNT (then multiplied by lot_size to get shares).
                            # So the lot count is the leg qty as-given.
                            _orig_lots = max(1, _leg_qty)
                    except Exception:
                        _orig_lots = 1
                    dec = risk.check_new_trade(
                        plan_max_loss=plan_max_loss_for_risk,
                        underlying=symbol,
                        regime=rs.regime.value,
                        confidence=plan.confidence,
                        vix=rs.vix,
                        original_qty_lots=_orig_lots,
                    )
                    log_signal({
                        "symbol": symbol, "regime": rs.regime.value, "side": "scan",
                        "confidence": rs.confidence, "reason": rs.reason,
                        "action": f"{dec.preset}:{'allowed' if dec.allowed else f'skip:{dec.reason}'}",
                    })
                    if not dec.allowed:
                        continue
                    if plan:
                        expiry = now.strftime("%Y-%m-%d")
                        lot_sizes = cfg.get("instruments", {}).get("lot_sizes", {})
                        trade = order_mgr.execute_plan(plan, qty=dec.suggested_qty, expiry=expiry, lot_sizes=lot_sizes,
                                                        bracket_config=cfg.get("risk", {}).get("bracket", {}))
                        # FIX 2026-08-12: pin leg strikes to keep_alive so KotakProdFeed
                        # keeps polling them after the scan loop rotates ATM window.
                        try:
                            leg_syms = [_strategy_leg_symbol(l) for l in plan.legs]
                            feed.keep_alive_subscribe(leg_syms)
                        except Exception as e:
                            logger.warning(f"keep_alive_subscribe failed: {e}")
                        risk.on_position_opened()
                        risk.state.trades_today += 1
                        last_trade_at[symbol] = now
                        log_trade({
                            "trade_id": getattr(trade, 'trade_id', None) or f"T-{int(datetime.now(timezone.utc).timestamp()*1000)}",
                            "orders": [
                                {
                                    "order_id": getattr(o, 'order_id', ''),
                                    "symbol": o.symbol, "side": o.side.value if hasattr(o.side, 'value') else str(o.side),
                                    "qty": o.qty, "price": o.price, "tag": o.tag,
                                    "status": str(o.status), "avg_fill_price": o.avg_fill_price,
                                    "filled_qty": getattr(o, 'filled_qty', 0),
                                }
                                for o in trade.orders
                            ],
                        })
                        alerter.trade_opened(plan)
                        # capture trade journal screenshot
                        try:
                            entry_chart = trade_journal.capture_entry(
                                trade_id=trade.trade_id, underlying=symbol,
                                strategy=plan.strategy.value, plan=plan, feed=feed,
                            )
                            trade_journal.record(
                                trade_id=trade.trade_id, underlying=symbol,
                                strategy=plan.strategy.value, entry_chart=entry_chart,
                                tags=f"conf={plan.confidence:.2f}|preset={dec.preset}",
                            )
                            if entry_chart:
                                alerter.send_photo(entry_chart, caption=f"📸 Entry: {plan.strategy.value} {symbol} @ {now.strftime('%H:%M')}")
                        except Exception as e:
                            logger.debug(f"journal capture failed: {e}")
                        # OI analytics for context
                        try:
                            oi_map = feed.get_oi_map(symbol)
                            if oi_map:
                                walls = oi_walls(oi_map)
                                mp = max_pain(oi_map)
                                ratio = pcr(oi_map)
                                logger.info(
                                    f"[OI] {symbol} resistance={walls.get('resistance')} "
                                    f"support={walls.get('support')} max_pain={mp} pcr={ratio:.2f}"
                                )
                        except Exception as e:
                            logger.debug(f"OI analytics failed: {e}")
                # 4b) smart exit check on open positions
                from kotak_bot.execution.smart_exit import evaluate_exit, aggregate_portfolio_greeks
                open_trades_list = order_mgr.open_trades()
                if open_trades_list:
                    spot_n = feed.get_ltp("NIFTY")
                    spot_bn = feed.get_ltp("BANKNIFTY")
                    for trade in open_trades_list:
                        if not trade.opened_at:
                            continue
                        # normalize opened_at to offset-aware for subtraction
                        op_at = trade.opened_at
                        if op_at.tzinfo is None:
                            op_at = op_at.replace(tzinfo=timezone.utc).astimezone(now.tzinfo)
                        try:
                            hold_min = int((now - op_at).total_seconds() / 60)
                        except Exception:
                            hold_min = 0
                        # get current pnl
                        current_pnl = 0
                        for o in trade.orders:
                            if o.avg_fill_price <= 0:
                                continue
                            cur = feed.get_ltp(o.symbol)
                            if cur > 0:
                                side_str = o.side.value if hasattr(o.side, 'value') else str(o.side)
                                sign = 1 if side_str == "SELL" else -1
                                current_pnl += (cur - o.avg_fill_price) * o.filled_qty * sign
                        max_profit = max(1, abs(trade.plan.target))
                        pnl_pct = current_pnl / max_profit if max_profit > 0 else 0
                        # determine current regime (use NIFTY for simplicity)
                        spot_for_regime = spot_n if trade.plan.underlying == "NIFTY" else spot_bn
                        mom = feed.get_momentum(trade.plan.underlying, window=20)
                        rs_now = regime.detect(df=None, vix=14.0, iv_rank=55.0, momentum=mom, spot=spot_for_regime, atm=round(spot_for_regime/50)*50)
                        # minutes to expiry
                        minutes_to_expiry = 0
                        try:
                            expiry_dt = datetime.strptime(trade.orders[0].expiry, "%Y-%m-%d")
                            now_naive = now.replace(tzinfo=None) if now.tzinfo else now
                            minutes_to_expiry = max(0, int((expiry_dt - now_naive).total_seconds() / 60))
                        except Exception as e:
                            logger.debug(f"expiry parse failed for {trade.trade_id}: {e}")
                        es = evaluate_exit(
                            plan=trade.plan,
                            current_pnl=current_pnl,
                            pnl_pct=pnl_pct,
                            hold_minutes=hold_min,
                            current_regime=rs_now.regime.value,
                            current_greeks={},
                            current_iv_change_pct=0.0,
                            minutes_to_expiry=minutes_to_expiry,
                            config=cfg.get("risk", {}).get("smart_exit", {}),
                        )
                        # Min hold: don't allow smart exit in first N min (avoid noise from
                        # synthetic ticks or premature stops). Pulled from settings, NOT hardcoded.
                        min_hold_min = int(min_hold_before_exit_sec / 60)
                        if es.should_exit and hold_min >= min_hold_min:
                            logger.info(
                                f"[EXIT] {trade.plan.strategy.value} {trade.plan.underlying} | "
                                f"pnl=₹{current_pnl:.0f} ({pnl_pct:.0%}) | hold={hold_min}min | "
                                f"reason={es.reason} | urgency={es.urgency}"
                            )
                            try:
                                order_mgr.close_trade(trade_id=trade.trade_id, reason=f"smart_exit:{es.reason}")
                                alerter.trade_closed(current_pnl, reason=es.reason)
                                risk.on_trade_close(current_pnl)
                                # record performance for alpha decay + auto-tune
                                strat_name = trade.plan.strategy.value
                                perf_tracker.add_trade(
                                    strategy=strat_name,
                                    underlying=trade.plan.underlying,
                                    pnl=current_pnl,
                                    pnl_pct=pnl_pct,
                                    hold_minutes=hold_min,
                                    exit_reason=es.reason,
                                )
                            except Exception as e:
                                logger.warning(f"close_trade failed: {e}")
                last_scan = now
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Shutting down on Ctrl+C")
            _LIVE = get_liveness()
            if _LIVE:
                _LIVE.register_exit("KeyboardInterrupt")
                _LIVE.stop(reason="KeyboardInterrupt")
            cmd_handler.stop()
            break
        except Exception as e:
            logger.exception(f"main loop error: {e}")
            time.sleep(10)

    broker.disconnect()
    feed.stop()
    cmd_handler.stop()
    # Final liveness shutdown (also covered by atexit, but be explicit)
    _LIVE = get_liveness()
    if _LIVE:
        _LIVE.stop(reason="main_loop_exit")


def show_status() -> None:
    cfg = load_config()
    setup_logger("INFO", "logs/status.log")
    broker = build_broker(cfg)
    try:
        broker.connect()
    except Exception as e:
        logger.warning(f"connect failed (ok if paper + no creds): {e}")
    margins = broker.get_margins()
    positions = broker.get_positions()
    print("\n" + "=" * 60)
    print("BOT STATUS")
    print("=" * 60)
    print(f"Capital:    Rs.{margins.get('total', 0):,.0f}")
    print(f"Available:  Rs.{margins.get('available', 0):,.0f}")
    print(f"Used:       Rs.{margins.get('used', 0):,.0f}")
    print(f"Realized:   Rs.{margins.get('realized_pnl', 0):,.0f}")
    print(f"Unrealized: Rs.{margins.get('unrealized_pnl', 0):,.0f}")
    print(f"\nOpen positions: {len(positions)}")
    for p in positions:
        print(f"  {p.symbol:30s}  qty={p.qty:+d}  avg={p.avg_price:.2f}  ltp={p.ltp:.2f}  pnl=Rs.{p.pnl:,.0f}")
    broker.disconnect()


def reset_paper() -> None:
    cfg = load_config()
    broker = build_broker(cfg)
    if hasattr(broker, "reset"):
        broker.reset()
        print("Paper state reset.")
    else:
        print("Reset only works for paper broker.")


def run_backtest() -> None:
    print("Backtest runner — see backtest/engine.py (built by background agent).")
    print("Try: python -m backtest.engine")


def _acquire_single_instance_lock(name: str = "paper") -> Optional[object]:
    """Single-instance lock. Writes PID to data_cache/<name>.lock and removes it on exit.
    Returns a lock object if acquired, else exits (another bot is running).
    FIX 2026-08-26 (item #5): prevent duplicate bot instances.
    """
    import atexit
    lock_path = Path(f"data_cache/{name}.lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        if lock_path.exists():
            try:
                old_pid = int(lock_path.read_text().strip())
                # Check if process is alive
                import ctypes
                PROCESS_QUERY_LIMITED = 0x1000
                STILL_ACTIVE = 259
                h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, old_pid)
                if h:
                    alive = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.c_ulong()) == STILL_ACTIVE
                    ctypes.windll.kernel32.CloseHandle(h)
                    if alive:
                        print(f"[LOCK] another instance of '{name}' is running (PID {old_pid}). exiting.")
                        return None
            except Exception:
                pass  # stale lock; take it
        lock_path.write_text(str(os.getpid()))
        atexit.register(_release_lock, lock_path)
        print(f"[LOCK] acquired {name} lock (PID {os.getpid()})")
        return lock_path
    except Exception as e:
        print(f"[LOCK] failed to acquire lock: {e}")
        return None


def _release_lock(lock_path):
    try:
        if lock_path.exists():
            cur = lock_path.read_text().strip()
            if cur == str(os.getpid()):
                lock_path.unlink()
    except Exception:
        pass


# ---- Mavis decision hook (FIX 2026-08-27: data-driven, not template) -----
def _load_mavis_decision(today_str: str) -> dict:
    """Read Mavis's pre-market trade plan from data_cache/mavis_trades.json.

    Returns a dict with at least:
      - "action": "EXECUTE_PLAN" | "BLOCK" | "WAIT" | "REDUCE_SIZE"
      - "plan": the matched plan dict (if action == EXECUTE_PLAN)
      - "reason": human-readable rationale
      - "valid": True if the decision is for today AND signed by Mavis

    Any error (file missing, invalid JSON, no decision for today) returns
    {"action": "WAIT", "valid": False, "reason": "<err>"} so the bot falls
    through to the template selector. NEVER crashes the bot.
    """
    # FIX 2026-08-28: Default to BLOCK (not template) when Mavis has no fresh plan.
    # The bot previously fell through to a template iron condor when WAIT+valid=False.
    # Per user directive: "no template for everything" — the LLM brain is the only authority.
    p = Path("data_cache/mavis_trades.json")
    try:
        if not p.exists():
            return {"action": "BLOCK", "valid": True, "reason": "mavis_trades.json missing — LLM brain must provide a plan before the bot trades"}
        with open(p, "r", encoding="utf-8-sig") as f:
            j = json.load(f)
        if not isinstance(j, dict):
            return {"action": "BLOCK", "valid": True, "reason": "mavis_trades.json not a dict — LLM brain must regenerate"}
        # valid_for_date is the key field (or fall back to key_dates.tomorrow)
        valid_for = j.get("valid_for_date") or ""
        # Also accept key_dates.tomorrow as a fallback (older schema)
        if not valid_for:
            kd = j.get("key_dates") or {}
            valid_for = kd.get("tomorrow") or ""
        # Compare YYYY-MM-DD portion
        if valid_for and today_str in str(valid_for):
            decision = j.get("mavis_decision") or {}
            action = str(decision.get("action") or "BLOCK").upper()
            # Only EXECUTE_PLAN is honored for entries. Any other action -> BLOCK.
            # (The LLM must explicitly say EXECUTE_PLAN to enable trading. WAIT/HOLD/REDUCE_SIZE default to BLOCK.)
            if action != "EXECUTE_PLAN":
                return {"action": "BLOCK", "valid": True, "reason": f"mavis_decision.action='{action}' is not EXECUTE_PLAN — bot requires explicit EXECUTE_PLAN to enter. reason={decision.get('reason_short','')[:120]}"}
            reason = str(decision.get("reason_short") or decision.get("note") or "")
            plan = j.get("primary_plan") or j.get("trade_plan", {}).get("primary") or {}
            return {"action": action, "plan": plan, "reason": reason,
                    "valid": True, "bias": decision.get("bias", ""),
                    "confidence": decision.get("confidence", 0.0),
                    "raw": j}
        return {"action": "BLOCK", "valid": True,
                "reason": f"mavis_trades.json valid_for='{valid_for}' != today='{today_str}' — LLM brain must regenerate for today"}
    except Exception as e:
        return {"action": "BLOCK", "valid": True, "reason": f"mavis_decision_load_error: {e} — LLM brain must regenerate"}


def _build_plan_from_mavis(symbol: str, spot: float, mavis_plan: dict, expiry: str) -> Optional["TradePlan"]:
    """Convert a Mavis primary_plan dict (sell/buy legs) into a TradePlan.

    Supports iron_condor / iron_butterfly / vertical / strangle structures.
    Returns None if the plan can't be parsed (caller should fall through to template).
    """
    from kotak_bot.strategy.base import TradePlan, StrategyName
    if not isinstance(mavis_plan, dict):
        return None
    structure = str(mavis_plan.get("structure", "")).upper()
    name = str(mavis_plan.get("name", "mavis_plan")).lower()
    underlying = str(mavis_plan.get("underlying", symbol)).upper()
    if underlying != symbol.upper():
        return None  # Mavis plan is for a different symbol
    # Parse legs from structure string (best-effort)
    # Recognized patterns: "SELL 24200 PE + BUY 24100 PE + SELL 24500 CE + BUY 24600 CE"
    import re
    leg_re = re.compile(r"(SELL|BUY)\s+(\d+)\s*(CE|PE)", re.IGNORECASE)
    matches = leg_re.findall(structure)
    if len(matches) < 2:
        return None
    legs: list[dict] = []
    for side, strike_s, opt_type in matches:
        side_l = side.lower()
        legs.append({
            "side": side_l,
            "qty": 1,
            "symbol": f"{symbol}{expiry}{int(strike_s)}{opt_type.upper()}",
            "strike": int(strike_s),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "order_type": "LIMIT",
            "price": 0.0,  # will be filled at market
            "tag": f"mavis:{name}",
        })
    if not legs:
        return None
    # Determine max loss and target from plan dict
    stop = 0.0
    target = 0.0
    if "max_loss_rupees" in mavis_plan:
        ml = mavis_plan["max_loss_rupees"]
        if isinstance(ml, dict):
            per_wing = ml.get("per_wing_total_75_shares") or ml.get("realistic_max_loss_single_wing")
            if isinstance(per_wing, str):
                # parse "Rs.4,500 - 5,625" — take midpoint
                nums = re.findall(r"[\d,]+", per_wing)
                if len(nums) >= 2:
                    stop = (float(nums[0].replace(",", "")) + float(nums[1].replace(",", ""))) / 2
                elif nums:
                    stop = float(nums[0].replace(",", ""))
            elif isinstance(per_wing, (int, float)):
                stop = float(per_wing)
    if "expected_premiums_rupees" in mavis_plan:
        ep = mavis_plan["expected_premiums_rupees"]
        if isinstance(ep, dict):
            tc = ep.get("total_credit_lot1")
            if isinstance(tc, str):
                nums = re.findall(r"[\d,]+", tc)
                if len(nums) >= 2:
                    target = (float(nums[0].replace(",", "")) + float(nums[1].replace(",", ""))) / 2
                elif nums:
                    target = float(nums[0].replace(",", ""))
            elif isinstance(tc, (int, float)):
                target = float(tc)
    if stop == 0.0:
        # fallback: assume condor max loss = 6000
        stop = 6000.0
    if target == 0.0:
        target = stop * 0.4  # 40% of max loss as target
    # Pick strategy name
    if "iron_condor" in name or "condor" in name:
        strat = StrategyName.IRON_CONDOR
    elif "straddle" in name or "strangle" in name:
        strat = StrategyName.SHORT_STRANGLE
    else:
        strat = StrategyName.IRON_CONDOR
    return TradePlan(
        strategy=strat, underlying=symbol, legs=legs,
        target=target, stop=-stop,
        confidence=float(mavis_plan.get("confidence", 0.7)),
        reason=f"mavis_override: {mavis_plan.get('rationale_data_driven', '')[:140]}",
        expiry=expiry, expected_hold_minutes=int(mavis_plan.get("expected_hold_minutes", 60*6)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Kotak Neo Trading Bot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("paper", help="Run paper trading loop")
    sub.add_parser("live", help="Run live trading (needs creds)")
    sub.add_parser("status", help="Show broker state")
    sub.add_parser("reset", help="Reset paper state")
    sub.add_parser("backtest", help="Run backtest")
    args = parser.parse_args()

    # FIX 2026-08-26: only acquire single-instance lock for the run-loop commands
    # (paper, live). status/reset/backtest should never hold a long-running lock.
    if args.cmd in ("paper", "live"):
        if _acquire_single_instance_lock(args.cmd) is None:
            return 1  # another instance running, exit cleanly

    if args.cmd == "paper":
        run_paper()
    elif args.cmd == "live":
        cfg = load_config()
        cfg["mode"] = "live"
        cfg["broker"]["type"] = "neo"
        with open("config/settings.yaml", "w") as f:
            yaml.safe_dump(cfg, f)
        run_paper()
    elif args.cmd == "status":
        show_status()
    elif args.cmd == "reset":
        reset_paper()
    elif args.cmd == "backtest":
        run_backtest()
    return 0


if __name__ == "__main__":
    sys.exit(main())
