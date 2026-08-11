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
import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from loguru import logger

from kotak_bot.broker import NeoClient, PaperClient
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
from kotak_bot.utils.clock import now_ist, is_market_open, is_square_off_time, market_session
from kotak_bot.utils.logger import setup_logger

# trade log CSV
TRADES_CSV = Path("logs/trades.csv")
SIGNALS_CSV = Path("logs/signals.csv")
TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)


def init_csv(path: Path, header: list[str]) -> None:
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)


def log_trade(trade: dict) -> None:
    init_csv(TRADES_CSV, [
        "timestamp", "trade_id", "symbol", "side", "qty", "price", "tag", "status", "fill_price"
    ])
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for o in trade.get("orders", []):
            w.writerow([
                datetime.utcnow().isoformat(),
                trade.get("trade_id", ""),
                o.get("symbol", ""),
                o.get("side", ""),
                o.get("qty", 0),
                o.get("price", 0),
                o.get("tag", ""),
                str(o.get("status", "")),
                o.get("avg_fill_price", 0),
            ])


def log_signal(signal: dict) -> None:
    init_csv(SIGNALS_CSV, [
        "timestamp", "symbol", "regime", "side", "confidence", "reason", "action"
    ])
    with open(SIGNALS_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.utcnow().isoformat(),
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
        )
    return NeoClient()


def run_paper() -> None:
    cfg = load_config()
    setup_logger(level=cfg.get("logging", {}).get("level", "INFO"),
                 log_file=cfg.get("logging", {}).get("file", "logs/bot.log"))
    logger.info("=" * 60)
    logger.info("Kotak Neo Trading Bot — PAPER MODE (Production v2)")
    logger.info("=" * 60)

    # ------- data source -------
    broker = build_broker(cfg)
    broker.connect()
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
    feed = LiveFeed(mode=feed_mode, broker=broker, neo_client=neo_client_for_feed)
    feed.start()
    feed.subscribe(["NIFTY", "BANKNIFTY"])

    # ------- pipeline -------
    risk = RiskEngine(cfg.get("risk", {}))
    paper_cap = cfg.get("broker", {}).get("paper_capital", 100_000.0)
    risk.update_capital(paper_cap)
    tech = TechnicalAnalyzer(cfg.get("strategy", {}).get("directional", {}))
    regime = RegimeDetector(cfg.get("strategy", {}).get("regime_detector", {}))
    selector = StrategySelector(cfg.get("strategy", {}))
    order_mgr = OrderManager(broker)
    alerter = TelegramAlerter(voice_enabled=cfg.get("alerts", {}).get("voice", {}).get("enabled", True))

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
            except Exception:
                pass
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
        step = 50 if symbol == "NIFTY" else 100
        atm = round(spot / step) * step
        strikes = [atm + (i - 4) * step for i in range(9)]
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
        broker_pos = broker.get_positions()
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
                        from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType
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
    cmd_handler.force_trade = _force_trade
    cmd_handler.live_feed = feed
    cmd_handler.perf_tracker = perf_tracker
    cmd_handler.start()
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
    # expiry for symbols — derive from next Thursday for the *current* weekly
    # but for paper mode, use today's date as the expiry (matches synthetic feed)
    expiry_str_today = now_ist().strftime("%d%b%y").upper()
    cycle_counter = 0
    while True:
        try:
            now = now_ist()
            session = market_session(now)
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
                # compliance PDF
                try:
                    # collect trades from CSV
                    from pathlib import Path
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
            # 4) scan every 30s during market hours
            cycle_counter += 1
            if (now - last_scan).total_seconds() >= 30 and is_market_open(now):
                # position cap check (count both order_mgr and broker positions for safety)
                open_pos = [p for p in broker.get_positions() if p.qty != 0]
                open_trades = order_mgr.open_trades()
                total_open = max(len(open_trades), len(open_pos))
                if total_open >= MAX_OPEN_POSITIONS:
                    logger.info(f"[SCAN] cycle={cycle_counter} | skip: {total_open} open positions >= max {MAX_OPEN_POSITIONS}")
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
                    step = 50 if symbol == "NIFTY" else 100
                    atm = round(spot / step) * step
                    # EXPANDED to ±4 strikes for iron condor (needs ±3-4 step wings)
                    strikes = [atm + (i - 4) * step for i in range(9)]
                    option_ltps = {}
                    option_ltp_count = 0
                    for k in strikes:
                        for ot in ("CE", "PE"):
                            # FIX 2026-08-10: use dated symbol format to match synthetic feed
                            # synthetic emits: NIFTY10AUG2625000CE; previous code queried NIFTY25000CE
                            sym_full = f"{symbol}{expiry_str_today}{int(k)}{ot}"
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
                        except Exception:
                            pass
                    from kotak_bot.strategy.base import SignalContext
                    # Get event info from macro calendar
                    upcoming_event = None
                    minutes_to_event = None
                    try:
                        ev = macro_cal.get_event_window(now, minutes_before=60, minutes_after=15)
                        if ev:
                            upcoming_event = ev["name"]
                            minutes_to_event = ev["minutes_to_event"]
                    except Exception:
                        pass
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
                    # Build plan first, then check risk with the plan's actual max loss
                    plan = selector.select(sc, risk.status())
                    if not plan:
                        continue
                    # Compute plan's actual max loss: for debit = full debit, for credit = full width - credit
                    # Simplification: use plan.stop as the per-trade risk
                    plan_max_loss_for_risk = abs(plan.stop)
                    dec = risk.check_new_trade(
                        plan_max_loss=plan_max_loss_for_risk,
                        underlying=symbol,
                        regime=rs.regime.value,
                        confidence=plan.confidence,
                        vix=rs.vix,
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
                        trade = order_mgr.execute_plan(plan, qty=dec.suggested_qty, expiry=expiry, lot_sizes=lot_sizes)
                        risk.on_position_opened()
                        risk.state.trades_today += 1
                        last_trade_at[symbol] = now
                        log_trade({
                            "trade_id": getattr(trade, 'plan', plan).__class__.__name__,
                            "orders": [
                                {
                                    "symbol": o.symbol, "side": o.side.value if hasattr(o.side, 'value') else str(o.side),
                                    "qty": o.qty, "price": o.price, "tag": o.tag,
                                    "status": str(o.status), "avg_fill_price": o.avg_fill_price,
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
                        except Exception:
                            pass
                        es = evaluate_exit(
                            plan=trade.plan,
                            current_pnl=current_pnl,
                            pnl_pct=pnl_pct,
                            hold_minutes=hold_min,
                            current_regime=rs_now.regime.value,
                            current_greeks={},
                            current_iv_change_pct=0.0,
                            minutes_to_expiry=minutes_to_expiry,
                        )
                        # Min hold: don't allow smart exit in first 5 min (avoid noise from synthetic ticks)
                        min_hold_min = 5
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
            cmd_handler.stop()
            break
        except Exception as e:
            logger.exception(f"main loop error: {e}")
            time.sleep(10)

    broker.disconnect()
    feed.stop()
    cmd_handler.stop()


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Kotak Neo Trading Bot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("paper", help="Run paper trading loop")
    sub.add_parser("live", help="Run live trading (needs creds)")
    sub.add_parser("status", help="Show broker state")
    sub.add_parser("reset", help="Reset paper state")
    sub.add_parser("backtest", help="Run backtest")
    args = parser.parse_args()

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
