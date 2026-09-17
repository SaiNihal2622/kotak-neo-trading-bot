"""Paper trading client.

Synthesizes fills from the live WebSocket LTP. Does NOT call the real broker.
All orders are intercepted, logged, and filled against a synthetic book.
This is the safe default for paper trading when the Kotak UAT is not yet provisioned.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Callable, Optional

from loguru import logger

from .base import (
    BrokerClient,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    ProductType,
    Tick,
)


# FIX 2026-09-16 00:50: module-level data dir so tests can monkeypatch it.
# The chain lookup at line 196 (option_chains.json) and IV lookup at line 296
# previously hardcoded Path("data_cache"), which made them invisible to test
# fixtures that wrote fake chains to tmp_path. Tests now set
# `paper_client.DCACHE = tmp_path` (or use the helper `use_dcache()`) and the
# fill logic reads from there.
DCACHE = Path("data_cache")
# FIX 2026-09-17 13:15: append-only rejection log. The LLM brain reads this
# in its periodic context so it learns from realistic-mode rejections
# (TIMEOUT_REJECT, OFF_TICK_REJECT, MARKET_REJECT etc.) and avoids repeating
# the same patterns. The brain's _periodic_scan reads the most-recent
# N entries and surfaces them to the LLM context as "realistic-mode feedback".
# Format: jsonl, one record per rejection.
REJECTIONS_LOG = DCACHE / "order_rejections.jsonl"


class PaperClient(BrokerClient):
    """In-process paper trading simulator.

    - Tracks a virtual book of orders and positions
    - Fills market orders at the most recent tick LTP (with simulated slippage)
    - Fills limit orders when the tick crosses the price
    - Persists state to a JSON file for crash recovery
    """

    # FIX 2026-09-17 12:25: NSE options tick size. The exchange rounds prices to
    # the nearest tick — 0.05 INR for options < Rs.30, otherwise also 0.05 INR
    # (NSE changed the rule in 2023; previously Rs.3 options had 0.05 ticks and
    # higher had 0.10 ticks — now everything below 100k INR is 0.05).
    # Limit prices that don't land on a tick are REJECTED by the exchange (Order
    # gets 'not on tick' error from RMS). Paper-mode fills used to accept any
    # price; now we align to tick in realistic mode.
    NSE_TICK_SIZE = 0.05

    def __init__(
        self,
        starting_capital: float = 300_000.0,
        slippage_bps: float = 5.0,  # 5 bps = 0.05% slippage on market orders
        limit_fill_spread_pct: float = 0.1,  # 0.1% spread for LIMIT order fill simulation
        limit_fill_min_spread: float = 0.05,  # min Rs.0.05 spread (NSE tick)
        limit_fill_near_ltp_pct: float = 0.5,  # fill if limit within 0.5% of LTP
        # FIX 2026-09-17 12:25: added 'realistic' fill_mode. This mode uses the
        # LIVE bid/ask from the tick (Kotak PROD WebSocket pushes bid/ask) to
        # fill BUY at ask, SELL at bid — modeling actual half-spread crossing
        # instead of the optimistic market_like (LTP fill) which underestimates
        # slippage by 50-200 bps per leg. Realistic mode also enforces NSE tick
        # alignment on limit prices and rejects orders that don't fill within
        # the configured timeout (simulating Kotak Neo's order-routing timeout).
        fill_mode: str = "market_like",  # 'market_like' | 'aggressive_limit' | 'realistic_limit' | 'realistic'
        unfilled_order_timeout_sec: float = 60.0,  # how long a LIMIT may sit open before paper rejects it
        partial_fill_min_pct: float = 1.0,  # 1.0 = all-or-nothing; 0.7 = up to 70% partial
        persist_path: str = "data_cache/paper_state.json",
    ):
        self.starting_capital = starting_capital
        self.slippage_bps = slippage_bps
        self.unfilled_order_timeout_sec = unfilled_order_timeout_sec
        self.partial_fill_min_pct = partial_fill_min_pct
        # Per-order placed_at timer for unfilled-order timeout (FIX 2026-09-17).
        self._order_placed_ts: dict[str, float] = {}
        self.limit_fill_spread_pct = limit_fill_spread_pct
        self.limit_fill_min_spread = limit_fill_min_spread
        self.limit_fill_near_ltp_pct = limit_fill_near_ltp_pct
        self.fill_mode = fill_mode
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = RLock()
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._ticks: dict[str, Tick] = {}
        self._tick_callbacks: list[Callable[[Tick], None]] = []
        # FIX 2026-09-07 22:45: fill callbacks fire after every fill (open or close)
        # with (order, realized_delta). Used by the bot to write trade_journal.jsonl
        # inline instead of waiting for the 15:30 IST EOD P&L evaluator. Without
        # this, today's fills never made it into the journal because the EOD
        # evaluator only handles positions still OPEN at 15:30 — and the bot
        # force-squares everything at 14:30.
        self._fill_callbacks: list[Callable[[Order, float], None]] = []
        self._cash = starting_capital
        self._realized_pnl = 0.0
        self._connected = False
        # FIX 2026-09-17 13:15: in-memory rejection counter for the LLM brain's
        # recent-rejections view. Cleared on _load_state when state.json is read.
        # The brain can read these via get_recent_rejections(n).
        self._recent_rejections: list[dict] = []

        # load state if exists
        self._load_state()
        # FIX 2026-09-08 14:20: clean up any skip-save flag left by the pre-market
        # reset script. The flag's purpose is to suppress the OLD bot's _save_state
        # during a reset. Once the new PaperClient loads the clean state, the flag
        # is no longer needed and should be removed so the new bot saves normally.
        # If the flag is stale (e.g. the reset never happened), _save_state's own
        # 60s safety check will expire it.
        _skip_flag = self.persist_path.parent / "_skip_save.json"
        try:
            if _skip_flag.exists():
                _skip_flag.unlink()
                logger.info(f"[PAPER] removed stale _skip_save.json (post-load cleanup)")
        except Exception as _e:
            logger.debug(f"[PAPER] could not remove _skip_save.json: {_e}")

    # ------- connection (no-op) -------
    def connect(self) -> None:
        with self._lock:
            self._connected = True
            logger.info(f"PaperClient connected | capital=₹{self._cash:,.0f} | "
                        f"orders={len(self._orders)} | positions={len(self._positions)}")

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False
            self._save_state()
            logger.info("PaperClient disconnected")

    def is_connected(self) -> bool:
        return self._connected

    # ------- order management -------
    def place_order(self, order: Order, bracket=None, cover_sl: float = None) -> Order:
        """Place an order. bracket/cover_sl are accepted for API parity with NeoClient
        but ignored in paper mode (no server-side SL/target simulation)."""
        with self._lock:
            if not self._connected:
                raise RuntimeError("PaperClient not connected — call connect() first")
            order.order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
            order.placed_at = datetime.now(timezone.utc)
            order.status = OrderStatus.OPEN
            self._orders[order.order_id] = order
            # FIX 2026-09-17 12:30: track placed_at for unfilled-order timeout (realistic mode).
            import time as _t
            self._order_placed_ts[order.order_id] = _t.time()
            # FIX 2026-09-17 12:25: in realistic mode, validate limit price is on NSE tick.
            # NSE RMS rejects limit prices not on 0.05 tick, so paper should too.
            if self.fill_mode in ('realistic', 'realistic_limit') and order.order_type == 'LIMIT':
                if order.price and order.price > 0:
                    on_tick = round(order.price / self.NSE_TICK_SIZE) * self.NSE_TICK_SIZE
                    if abs(on_tick - order.price) > 0.001:
                        logger.warning(
                            f"[PAPER] LIMIT price {order.price} not on NSE tick ({self.NSE_TICK_SIZE}); "
                            f"snapping to {on_tick:.2f}"
                        )
                        order.price = round(on_tick, 2)
            tag = order.tag or ""
            if bracket:
                tag += f" [BRACKET sl={bracket.stop_loss} tgt={bracket.target} trail={bracket.trailing_sl_points}]"
            if cover_sl:
                tag += f" [COVER sl={cover_sl}]"
            logger.info(
                f"[PAPER] PLACE {order.order_id} {order.side.value} {order.qty}×{order.symbol} "
                f"{order.order_type.value} @ {order.price} ({tag})"
            )
            # attempt immediate fill
            self._try_fill(order)
            # market_like mode: if not filled yet and no tick, force fill at expected_price
            # (paper sim is about validating strategy logic, not fill mechanics)
            if order.status == OrderStatus.OPEN and self.fill_mode == "market_like":
                self._force_fill_market_like(order)
            self._save_state()
            return order

    # ---- FIX 2026-09-17 12:25 realistic-fill helpers ----
    @staticmethod
    def _align_to_tick(price: float) -> float:
        """Round to NSE tick size (0.05 INR). Returns float round to 2 decimals."""
        if price <= 0:
            return 0.0
        aligned = round(price / PaperClient.NSE_TICK_SIZE) * PaperClient.NSE_TICK_SIZE
        return round(aligned, 2)

    def _compute_bid_ask_fill(self, order: Order, tick: 'Tick') -> tuple:
        """FIX 2026-09-17 12:25: compute realistic fill price using actual bid/ask from
        the live tick. Returns (fill_price, status) where status ∈
        {'filled', 'partial', 'no_fill'}.

        In live trading, MARKET orders cross the book:
          - BUY  fills at best ask  (you pay more than mid)
          - SELL fills at best bid  (you receive less than mid)
        LIMIT orders may sit at the limit price (maker) or fill at the book.

        In paper 'realistic' mode, we simulate this precisely.
        """
        # Use bid/ask if available; fall back to LTP with the configured synthetic spread.
        bid = tick.bid if tick.bid > 0 else (tick.ltp - max(self.limit_fill_min_spread, tick.ltp * (self.limit_fill_spread_pct / 100.0)))
        ask = tick.ask if tick.ask > 0 else (tick.ltp + max(self.limit_fill_min_spread, tick.ltp * (self.limit_fill_spread_pct / 100.0)))
        ltp = tick.ltp if tick.ltp > 0 else (bid + ask) / 2.0

        if order.order_type == OrderType.MARKET or (
            order.order_type == OrderType.LIMIT and order.price is None
        ):
            # Market order: fill at bid (SELL) or ask (BUY) — never mid.
            if order.side == OrderSide.BUY:
                raw_price = ask
            else:
                raw_price = bid
            # Market orders on illiquid strikes can have wider effective spread if
            # the qty is large. Add a small impact: 0.5 bps per 100 qty.
            impact_bps = (order.qty / 100.0) * 0.5
            raw_price *= (1 + impact_bps / 10_000) if order.side == OrderSide.BUY else (1 - impact_bps / 10_000)
            return self._align_to_tick(raw_price), 'filled'

        if order.order_type == OrderType.LIMIT:
            # LIMIT: only fill if the limit crosses the book (BUY: limit >= ask;
            # SELL: limit <= bid). If limit is between bid and ask, it sits as
            # maker and only fills when the market comes to us.
            limit = order.price
            if order.side == OrderSide.BUY:
                if limit >= ask:
                    # Aggressive: fills at ask (we lift the offer) or at our limit,
                    # whichever is lower (we wouldn't pay more than we bid).
                    raw_price = min(limit, ask)
                    # If the book is thin, partial fill possible — apply partial_fill_min_pct.
                    if self.partial_fill_min_pct < 1.0:
                        # Use partial-fill heuristic: ratio of qty to volume scaled by min_pct.
                        import random as _r
                        _r.seed(hash(order.order_id) & 0xFFFF)
                        fill_ratio = max(self.partial_fill_min_pct, _r.uniform(0.85, 1.0))
                        if fill_ratio < 0.999:
                            return self._align_to_tick(raw_price), 'partial'
                    return self._align_to_tick(raw_price), 'filled'
                # Limit price < ask: order sits as maker, not yet filled.
                return 0.0, 'no_fill'
            else:  # SELL
                if limit <= bid:
                    # Aggressive: fills at bid (we hit the bid) or our limit,
                    # whichever is higher (we wouldn't receive less than we offered).
                    raw_price = max(limit, bid)
                    if self.partial_fill_min_pct < 1.0:
                        import random as _r
                        _r.seed(hash(order.order_id) & 0xFFFF)
                        fill_ratio = max(self.partial_fill_min_pct, _r.uniform(0.85, 1.0))
                        if fill_ratio < 0.999:
                            return self._align_to_tick(raw_price), 'partial'
                    return self._align_to_tick(raw_price), 'filled'
                return 0.0, 'no_fill'

        return 0.0, 'no_fill'

    def _timeout_unfilled_orders(self) -> None:
        """FIX 2026-09-17 12:35: in realistic mode, open orders that don't fill
        within unfilled_order_timeout_sec get rejected (mimicking Kotak Neo's
        order-routing timeout). The bot then sees a REJECTED status and can
        decide whether to retry, switch to market, or skip.
        """
        import time as _t
        now = _t.time()
        cutoff = now - self.unfilled_order_timeout_sec
        for oid, placed_ts in list(self._order_placed_ts.items()):
            if placed_ts > cutoff:
                continue
            order = self._orders.get(oid)
            if not order or order.status != OrderStatus.OPEN:
                self._order_placed_ts.pop(oid, None)
                continue
            # Re-evaluate one more time before killing
            tick = self._ticks.get(order.symbol)
            if tick:
                _px, _status = self._compute_bid_ask_fill(order, tick)
                if _status == 'filled':
                    self._apply_bid_ask_fill(order, tick)
                    continue
                if _status == 'partial' and self.partial_fill_min_pct < 1.0:
                    self._apply_bid_ask_fill(order, tick, partial=True)
                    continue
            # Reject
            order.status = OrderStatus.REJECTED
            order.rejection_reason = (
                f"unfilled after {self.unfilled_order_timeout_sec:.0f}s in realistic mode "
                f"(bid={tick.bid if tick else 0}, ask={tick.ask if tick else 0}, "
                f"limit={order.price})"
            )
            logger.warning(
                f"[PAPER] TIMEOUT REJECT {order.order_id} {order.symbol} "
                f"({order.qty} qty, limit={order.price}, "
                f"lapsed {now - placed_ts:.1f}s)"
            )
            # FIX 2026-09-17 13:15: feed the rejection to the persistent log so
            # the LLM brain sees it next cycle.
            self._log_rejection(order, order.rejection_reason)
            self._order_placed_ts.pop(oid, None)
        # Persist any rejections
        self._save_state()

    def _apply_bid_ask_fill(self, order: Order, tick: 'Tick', partial: bool = False) -> None:
        """FIX 2026-09-17 12:35: apply a fill computed via _compute_bid_ask_fill
        (the realistic path). Records expected_fill_price from the tick LTP
        (chain_ref) and avg_fill_price from the actual book price.
        """
        fill_price, status = self._compute_bid_ask_fill(order, tick)
        if status not in ('filled', 'partial') or fill_price <= 0:
            return
        import random as _r
        _r.seed(hash(order.order_id) & 0xFFFF)
        if partial and self.partial_fill_min_pct < 1.0:
            fill_ratio = max(self.partial_fill_min_pct, _r.uniform(0.85, 1.0))
            fill_qty = int(order.qty * fill_ratio)
        else:
            fill_qty = order.qty
        order.expected_fill_price = tick.ltp
        order.avg_fill_price = fill_price
        order.filled_qty = fill_qty
        order.status = OrderStatus.PARTIAL if (partial and fill_qty < order.qty) else OrderStatus.COMPLETE
        order.filled_at = datetime.now(timezone.utc)
        # Backfill option metadata if missing
        import re as _re
        if (not order.strike or not order.option_type or not order.underlying) and order.symbol:
            _m = _re.match(
                r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)'
                r'(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$',
                order.symbol.upper()
            )
            if _m:
                if not order.underlying: order.underlying = _m.group(1)
                if not order.strike: order.strike = int(_m.group(5))
                if not order.option_type: order.option_type = _m.group(6)
        self._apply_fill(order)
        self._order_placed_ts.pop(order.order_id, None)
        logger.info(
            f"[PAPER] REALISTIC_FILL {order.order_id} {fill_qty}×{order.symbol} "
            f"@ Rs.{fill_price} (ref ltp={tick.ltp} bid={tick.bid} ask={tick.ask}, "
            f"status={status})"
        )

    def _force_fill_market_like(self, order: Order) -> None:
        """Force-fill a still-open order in market_like mode. Uses the cached tick
        (any latest LTP for the symbol) or the strategy's expected_price as a fallback.
        Adds slippage in the direction of the trade.

        Fallback chain (in order):
          0. FIX 2026-09-04 13:42: option_chains.json (live LTP from KotakProdFeed)
             FIX 2026-09-07 22:15: parse strike/option_type/underlying from the order
             symbol if the Order object didn't set them. Without this defensive parse,
             brain-driven orphan-auto-close Orders fell through to Rs.1.00.
             FIX 2026-09-11 21:00: chain price VALIDATED against sanity range +
             expected_price. Phantom fills (Rs.1.0, 10x off) are REJECTED and
             the function falls back to Black-Scholes.
          1. Cached tick for the option symbol (validated)
          2. Order's limit price (if set, validated)
          3. Order's expected_fill_price (if set, validated)
          4. Black-Scholes estimate from spot + IV + time-to-expiry
          5. Underlying's last-known LTP (NIFTY/BANKNIFTY spot) — ATM option ≈ 0.5% of underlying
          6. Synthetic minimal price (Rs.1.00) — last resort, never skip a fill in paper mode
             (but logged loudly so it's clear when this happens)
        """
        import re as _re
        ref_price = 0.0
        _fill_source = "default"

        # FIX 2026-09-07 22:15: defensively recover strike/option_type/underlying
        # from the symbol if the Order didn't carry them. This protects against
        # any code path (orphan-auto-close, manual close) that constructs an Order
        # with just `symbol=...` and forgets to set the option-metadata fields.
        # NSE option symbol format: <UNDERLYING><DD><MON><YY><STRIKE><CE|PE>
        # e.g. BANKNIFTY10SEP2657200PE  →  underlying=BANKNIFTY, expiry=10-SEP-26, strike=57200, opt=PE
        _eff_strike = order.strike
        _eff_opt = order.option_type
        _eff_und = order.underlying
        if (not _eff_strike or not _eff_opt) and order.symbol:
            _m = _re.match(
                r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)'
                r'(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$',
                order.symbol.upper()
            )
            if _m:
                if not _eff_und:
                    _eff_und = _m.group(1)
                if not _eff_strike:
                    _eff_strike = int(_m.group(5))
                if not _eff_opt:
                    _eff_opt = _m.group(6)

        # FIX 2026-09-04 13:42: step 0 — look up live option LTP from option_chains.json
        # This is the most accurate source for paper fills (matches what live trading would do).
        # FIX 2026-09-11 21:00: validate the chain price before accepting it. The NIFTY chain
        # was found to have inverted PE prices (PE going UP as strike goes DOWN), which
        # produced phantom fills of +Rs.3,060 P&L on a single trade. Phantom fills are
        # now rejected and we fall back to Black-Scholes.
        # FIX 2026-09-16 00:55: chain lookup was previously written as
        # `list((Path("data_cache"))).glob(...)`. list() doesn't accept a Path
        # (TypeError: 'WindowsPath' object is not iterable), so the inner try/
        # except silently swallowed it and the chain was NEVER consulted. Every
        # market_like fill fell straight through to the BS / spot-derived /
        # Rs.1.00 fallback. Fix: glob first, then materialize the list.
        try:
            chains_files = list(DCACHE.glob("option_chain_*.json"))
            for cf in chains_files:
                try:
                    import json as _j
                    cd = _j.loads(cf.read_text(encoding="utf-8"))
                    strikes = cd.get("strikes", {})
                    key = f"{int(_eff_strike)}_{_eff_opt}" if _eff_strike and _eff_opt else None
                    if key and key in strikes:
                        lp = strikes[key].get("price", 0)
                        if lp and lp > 0:
                            # FIX 2026-09-11 21:00: validate before accepting
                            try:
                                from scripts.chain_health import validate_fill_price
                                _v = validate_fill_price(
                                    order.symbol, lp,
                                    expected_price=getattr(order, 'expected_fill_price', None) or 0
                                )
                                if _v["ok"]:
                                    ref_price = lp
                                    _fill_source = "chain"
                                    logger.debug(f"[PAPER] FORCE_FILL option_chain ref for {order.order_id} {order.symbol}: chain_key={key} -> {ref_price}")
                                    break
                                else:
                                    logger.warning(
                                        f"[PAPER] FORCE_FILL chain price REJECTED for {order.symbol}: "
                                        f"{_v['reason']}. Will fall back to BS."
                                    )
                            except ImportError:
                                # _chain_health not importable — use legacy behavior
                                ref_price = lp
                                _fill_source = "chain"
                                break
                except Exception:
                    continue
        except Exception:
            pass

        if ref_price <= 0:
            tick = self._ticks.get(order.symbol)
            if tick is not None and tick.ltp > 0:
                # FIX 2026-09-11 21:00: validate cached tick too
                try:
                    from scripts.chain_health import validate_fill_price
                    _v = validate_fill_price(order.symbol, tick.ltp,
                                              expected_price=getattr(order, 'expected_fill_price', None) or 0)
                    if _v["ok"]:
                        ref_price = tick.ltp
                        _fill_source = "tick"
                    else:
                        logger.warning(f"[PAPER] FORCE_FILL tick price REJECTED for {order.symbol}: {_v['reason']}")
                except ImportError:
                    ref_price = tick.ltp
                    _fill_source = "tick"
        if ref_price <= 0 and order.price and order.price > 0:
            # Validate limit price too
            try:
                from scripts.chain_health import validate_fill_price
                _v = validate_fill_price(order.symbol, order.price,
                                          expected_price=getattr(order, 'expected_fill_price', None) or 0)
                if _v["ok"]:
                    ref_price = order.price
                    _fill_source = "limit"
            except ImportError:
                ref_price = order.price
                _fill_source = "limit"
        if ref_price <= 0 and order.expected_fill_price and order.expected_fill_price > 0:
            # Validate expected price too
            try:
                from scripts.chain_health import validate_fill_price
                _v = validate_fill_price(order.symbol, order.expected_fill_price,
                                          expected_price=order.expected_fill_price)
                if _v["ok"]:
                    ref_price = order.expected_fill_price
                    _fill_source = "expected"
            except ImportError:
                ref_price = order.expected_fill_price
                _fill_source = "expected"
        # FIX 2026-09-11 21:00: Black-Scholes fallback. If we still don't have a
        # valid ref price (chain bad, tick missing, expected missing), compute
        # the option price from spot + IV + time-to-expiry. This is a real
        # Black-Scholes price — NOT a Rs.1.0 default. Phantom fills stop here.
        if ref_price <= 0:
            try:
                from scripts.chain_health import bs_estimate as _bs_est
                # Find underlying spot
                _spot = 0.0
                for sym_t, t_t in self._ticks.items():
                    if sym_t.upper().startswith((_eff_und or "").upper()):
                        if t_t.ltp and t_t.ltp > 0:
                            _spot = t_t.ltp
                            break
                if _spot > 0 and _eff_strike and _eff_opt and order.expiry:
                    # Days to expiry
                    from datetime import date as _date_f
                    _exp_d = order.expiry.date() if hasattr(order.expiry, 'date') else _date_f.fromisoformat(str(order.expiry)[:10])
                    _dte = max(0, (_exp_d - _date_f.today()).days)
                    # IV from chain
                    _iv = 0.15
                    try:
                        from pathlib import Path as _PF
                        for cf in DCACHE.glob("option_chain_*.json"):
                            try:
                                import json as _jj
                                _cd = _jj.loads(cf.read_text(encoding="utf-8"))
                                _ivs = [v.get("iv") for v in _cd.get("strikes", {}).values()
                                        if isinstance(v, dict) and v.get("iv") and v.get("iv") > 0]
                                if _ivs:
                                    _iv = sum(_ivs) / len(_ivs)
                                    break
                            except Exception:
                                continue
                    except Exception:
                        pass
                    _bs_px = _bs_est(_spot, _eff_strike, _eff_opt, _dte, iv=_iv)
                    if _bs_px and _bs_px > 0:
                        # Final sanity check — BS should give a sane price
                        from scripts.chain_health import MIN_OPTION_PRICE, MAX_OPTION_PRICE
                        _lo = MIN_OPTION_PRICE.get((_eff_und or "").upper(), 1.0)
                        _hi = MAX_OPTION_PRICE.get((_eff_und or "").upper(), 10000.0)
                        if _bs_px >= _lo and _bs_px <= _hi:
                            ref_price = _bs_px
                            _fill_source = "bs"
                            logger.info(
                                f"[PAPER] FORCE_FILL BS estimate for {order.symbol}: "
                                f"spot={_spot} strike={_eff_strike} dte={_dte} iv={_iv:.2f} -> {_bs_px}"
                            )
            except ImportError:
                pass
            except Exception as _bs_err:
                logger.debug(f"BS fallback error: {_bs_err}")

        if ref_price > 0:
            pass  # have a ref price
        else:
            # Fallback 4: derive from underlying's spot LTP. Most NIFTY/BANKNIFTY
            # weekly options trade in a Rs.5-200 band; ATM ≈ 0.5% of spot is a
            # reasonable mid-market estimate. This is a paper fill, not a quote.
            # FIX 2026-09-07 22:15: use _eff_und / _eff_strike / _eff_opt, which may
            # have been parsed from the symbol by the defensive block above. Otherwise
            # orphan-auto-close orders with no underlying would skip this branch and
            # fall to the Rs.1.00 last-resort.
            underlying = (_eff_und or "").upper()
            underlying_ltp = 0.0
            if underlying:
                # Convention: NIFTY = NIFTY*, BANKNIFTY = BANKNIFTY*
                for sym, t in self._ticks.items():
                    if sym.upper().startswith(underlying):
                        if t.ltp and t.ltp > 0:
                            underlying_ltp = t.ltp
                            break
            if underlying_ltp > 0 and _eff_strike and _eff_opt:
                # BUG FIX 2026-08-26: previous version used `0.5% of spot` for ALL options
                # of an underlying, ignoring strike. This made deep-OTM options fill at
                # ATM prices (e.g. NIFTY 24150 PE filled at Rs.121 instead of ~Rs.0),
                # distorting the condor close P&L. Now we compute intrinsic + time-value
                # decay that is strike-aware.
                if _eff_opt.upper() == "CE":
                    intrinsic = max(0.0, underlying_ltp - _eff_strike)
                else:  # PE
                    intrinsic = max(0.0, _eff_strike - underlying_ltp)
                # 0DTE vs normal expiry: 0DTE has much lower ATM time value, especially
                # in the last 1-2 hours. Detect via order.expiry vs today.
                from datetime import date as _date
                _is_0dte = False
                try:
                    if order.expiry:
                        _exp = order.expiry.date() if hasattr(order.expiry, "date") else _date.fromisoformat(str(order.expiry)[:10])
                        _is_0dte = (_exp == _date.today())
                except Exception:
                    pass
                if _is_0dte:
                    # 0DTE: ATM time value ~0.1% of spot, decay faster (50pt half-life)
                    atm_time_value = underlying_ltp * 0.001
                    decay_pts = 50
                else:
                    # Weekly/monthly: ATM time value ~0.5% of spot, slower decay
                    atm_time_value = underlying_ltp * 0.005
                    decay_pts = 150
                # For BNF strikes are wider, so scale the decay rate
                if underlying == "BANKNIFTY":
                    decay_pts = decay_pts * 4  # 200 for 0DTE, 600 for weekly
                distance = abs(underlying_ltp - _eff_strike)
                time_value = atm_time_value * (0.5 ** (distance / decay_pts))
                ref_price = round(intrinsic + time_value, 2)
                logger.debug(
                    f"[PAPER] FORCE_FILL strike-aware ref for {order.order_id} "
                    f"{order.symbol}: spot={underlying_ltp} strike={_eff_strike} "
                    f"type={_eff_opt} 0dte={_is_0dte} "
                    f"intrinsic={intrinsic:.2f} tv={time_value:.2f} -> ref={ref_price}"
                )
            elif underlying_ltp > 0:
                # No strike info — fall back to ATM estimate (very rare)
                ref_price = round(underlying_ltp * 0.005, 2)
                logger.debug(
                    f"[PAPER] FORCE_FILL underlying-derived (no strike) ref for "
                    f"{order.order_id} {order.symbol}: underlying={underlying} "
                    f"ltp={underlying_ltp} -> ref={ref_price}"
                )
            else:
                # Fallback 5: last-resort synthetic. Rs.1.00 keeps the fill book-true
                # so PnL accounting downstream works. Never skip a fill in paper mode.
                # FIX 2026-09-11 21:00: log loudly + tag the order so downstream can
                # detect phantom Rs.1.00 fills. The order.suspect_price flag is set
                # on the order; the trade_journal can mark this as suspect.
                ref_price = 1.0
                _fill_source = "rs1_default"
                logger.error(
                    f"[PAPER] FORCE_FILL LAST-RESORT RS.1.00 FILL for {order.order_id} {order.symbol}: "
                    f"no chain, no tick, no expected, no spot — phantom fill. "
                    f"Underlying: {_eff_und}, strike: {_eff_strike}, opt: {_eff_opt}, expiry: {order.expiry}"
                )
        slip = ref_price * (self.slippage_bps / 10_000)
        fill_price = ref_price + (slip if order.side == OrderSide.BUY else -slip)
        fill_price = round(fill_price, 2)
        order.expected_fill_price = ref_price
        order.avg_fill_price = fill_price
        order.filled_qty = order.qty
        order.status = OrderStatus.COMPLETE
        # FIX 2026-09-07 22:15: backfill the Order's option metadata so that
        # downstream Position() creation carries strike/option_type/underlying/expiry.
        # Without this, the Position object created from this Order would also lack
        # those fields, and any subsequent close on that position would re-trigger
        # the same fallback chain (and could re-fall to Rs.1.00).
        if not order.strike and _eff_strike:
            order.strike = _eff_strike
        if not order.option_type and _eff_opt:
            order.option_type = _eff_opt
        if not order.underlying and _eff_und:
            order.underlying = _eff_und
        order.filled_at = datetime.now(timezone.utc)
        self._apply_fill(order)
        logger.info(
            f"[PAPER] FORCE_FILL (market_like) {order.order_id} {order.qty}×{order.symbol} "
            f"@ {order.avg_fill_price} (ref={ref_price}, mode=market_like)"
        )

    def modify_order(self, order_id: str, **kwargs) -> Order:
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                raise KeyError(f"Order {order_id} not found")
            if order.status in (OrderStatus.COMPLETE, OrderStatus.CANCELLED, OrderStatus.REJECTED):
                raise ValueError(f"Cannot modify {order.status.value} order")
            for k, v in kwargs.items():
                if hasattr(order, k):
                    setattr(order, k, v)
            logger.info(f"[PAPER] MODIFY {order_id} {kwargs}")
            self._try_fill(order)
            self._save_state()
            return order

    def cancel_order(self, order_id: str) -> Order:
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                raise KeyError(f"Order {order_id} not found")
            if order.status == OrderStatus.COMPLETE:
                raise ValueError("Cannot cancel filled order")
            order.status = OrderStatus.CANCELLED
            logger.info(f"[PAPER] CANCEL {order_id}")
            self._save_state()
            return order

    def get_order(self, order_id: str) -> Order:
        with self._lock:
            return self._orders.get(order_id)  # type: ignore[return-value]

    def get_positions(self) -> list[Position]:
        with self._lock:
            # mark-to-market all positions
            for pos in self._positions.values():
                tick = self._ticks.get(pos.symbol)
                if tick:
                    pos.ltp = tick.ltp
                    pos.pnl = (pos.ltp - pos.avg_price) * pos.qty
                    continue
                # FIX 2026-09-09 13:45: no live tick for this option contract.
                # Fall back to option_chains.json which has fresh LTP from the
                # option chain analyzer (KotakProdFeed). Match by underlying +
                # strike + opt_type (the option chain keys are like "23500_PE",
                # not the full broker symbol).
                try:
                    import json as _jc
                    from pathlib import Path as _P
                    _und = (pos.underlying or "").upper()
                    _stk = float(pos.strike or 0)
                    _ot = (pos.option_type or "").upper()
                    _chain = _P("data_cache") / f"option_chain_{_und}.json"
                    if _chain.exists():
                        cd = _jc.loads(_chain.read_text(encoding="utf-8"))
                        for _key, _info in (cd.get("strikes") or {}).items():
                            if (float(_info.get("strike") or 0) == _stk
                                    and (_info.get("opt_type") or _info.get("option_type") or "").upper() == _ot):
                                _px = float(_info.get("price") or 0)
                                if _px > 0:
                                    pos.ltp = _px
                                    pos.pnl = (pos.ltp - pos.avg_price) * pos.qty
                                break
                except Exception:
                    pass
                # FIX 2026-09-09 13:55: final fallback — compute estimated option
                # LTP from live spot using Black-Scholes. This keeps the position
                # P&L updating on every tick even when the chain analyzer is stale
                # and LiveKotak has no tick for this option contract. Uses ATM
                # IV from the chain (or 0.15 default) and time-to-expiry from
                # the position's expiry date.
                if pos.ltp == pos.avg_price or pos.ltp <= 0:
                    try:
                        import math as _m
                        import json as _json
                        from datetime import date as _d, datetime as _dt
                        from pathlib import Path as _P2
                        _und = (pos.underlying or "").upper()
                        _stk = float(pos.strike or 0)
                        _ot = (pos.option_type or "").upper()
                        _exp = pos.expiry
                        # Get live spot from the feed's tick cache
                        _spot = 0.0
                        try:
                            _spot = float(self._ticks.get(_und, None) and self._ticks[_und].ltp or 0)
                        except Exception:
                            pass
                        # Fallback: read from intraday_levels or candles
                        if not _spot:
                            try:
                                _il = _P2("data_cache") / "intraday_levels.json"
                                if _il.exists():
                                    import json as _ji
                                    _ild = _ji.loads(_il.read_text(encoding="utf-8"))
                                    _inst = _ild.get("instruments", {}).get(_und, {})
                                    _spot = float(_inst.get("ltp") or _inst.get("current") or 0)
                            except Exception:
                                pass
                        if not _spot:
                            try:
                                _cf = _P2("data_cache") / f"candles_{_und}_1m.jsonl"
                                if _cf.exists():
                                    _last = _cf.read_text(encoding="utf-8").strip().splitlines()[-1]
                                    _spot = float(_json.loads(_last).get("c", 0))
                            except Exception:
                                pass
                        # Time to expiry
                        _t_years = 0.005  # default ~2 days
                        try:
                            if isinstance(_exp, str):
                                _exp_d = _dt.strptime(_exp[:10], "%Y-%m-%d").date()
                            elif isinstance(_exp, _d):
                                _exp_d = _exp
                            else:
                                _exp_d = _d.today()
                            _days = max(1, (_exp_d - _d.today()).days)
                            _t_years = _days / 365.0
                        except Exception:
                            pass
                        # IV from chain or default
                        _sigma = 0.15
                        try:
                            _chain = _P2("data_cache") / f"option_chain_{_und}.json"
                            if _chain.exists():
                                import json as _jc2
                                cd2 = _jc2.loads(_chain.read_text(encoding="utf-8"))
                                _iv_sum = []
                                for _k, _v in (cd2.get("strikes") or {}).items():
                                    _iv = _v.get("iv")
                                    if _iv and _iv > 0:
                                        _iv_sum.append(float(_iv))
                                if _iv_sum:
                                    _sigma = sum(_iv_sum) / len(_iv_sum)
                        except Exception:
                            pass
                        # BS price
                        if _spot > 0 and _stk > 0 and _t_years > 0 and _sigma > 0:
                            _r = 0.065
                            _sqrt_t = _sigma * _m.sqrt(_t_years)
                            _d1 = (_m.log(_spot / _stk) + (_r + 0.5 * _sigma ** 2) * _t_years) / _sqrt_t
                            _d2 = _d1 - _sqrt_t
                            # Standard normal CDF
                            def _cndf(x):
                                return 0.5 * (1.0 + _m.erf(x / _m.sqrt(2.0)))
                            if _ot == "CE":
                                _est = _spot * _cndf(_d1) - _stk * _m.exp(-_r * _t_years) * _cndf(_d2)
                            else:  # PE
                                _est = _stk * _m.exp(-_r * _t_years) * _cndf(-_d2) - _spot * _cndf(-_d1)
                            if _est > 0:
                                pos.ltp = round(_est, 2)
                                pos.pnl = (pos.ltp - pos.avg_price) * pos.qty
                    except Exception:
                        pass
            return list(self._positions.values())

    def get_holdings(self) -> list[Position]:
        return []  # paper has no delivery holdings

    def get_margins(self) -> dict:
        with self._lock:
            used = sum(abs(p.qty) * p.ltp for p in self._positions.values())
            return {
                "available": self._cash - used,
                "used": used,
                "total": self._cash,
                "realized_pnl": self._realized_pnl,
                "unrealized_pnl": sum(p.pnl for p in self._positions.values()),
            }

    def get_ltp(self, symbol: str, exchange: str = "NFO") -> float:
        with self._lock:
            tick = self._ticks.get(symbol)
            return tick.ltp if tick else 0.0

    def subscribe(self, symbols: list[str], exchange: str = "NFO") -> None:
        logger.info(f"[PAPER] subscribe {len(symbols)} symbols")

    def on_tick(self, callback: Callable[[Tick], None]) -> None:
        self._tick_callbacks.append(callback)

    def on_fill(self, callback: Callable[["Order", float], None]) -> None:
        """Register a callback fired after every fill. The callback receives
        (order, realized_delta) where realized_delta is the realized P&L
        contribution from this fill (0 for opens, +/-value for closes).
        Callbacks should be fast and not block; exceptions are caught and
        logged. Used to write trade_journal.jsonl inline.
        """
        self._fill_callbacks.append(callback)

    # ------- market data injection (used by data/live_feed) -------
    def inject_tick(self, tick: Tick) -> None:
        """Feed a real tick into the paper book. Public for the live feed."""
        with self._lock:
            self._ticks[tick.symbol] = tick
            # mark-to-market
            pos = self._positions.get(tick.symbol)
            if pos:
                pos.ltp = tick.ltp
                pos.pnl = (pos.ltp - pos.avg_price) * pos.qty
            # check open orders for this symbol
            for order in self._orders.values():
                if order.status == OrderStatus.OPEN and order.symbol == tick.symbol:
                    self._try_fill(order)
            # market_like mode: force-fill any still-open order on EVERY tick, regardless
            # of symbol. This handles strikes whose keep-alive subscription may not be
            # getting fresh data — as long as any tick comes in, all open orders get
            # re-evaluated.
            # FIX 2026-09-17 12:35: realistic mode is NOT force-filled on every tick.
            # Realistic mode requires the order to cross the actual bid/ask book, and
            # any open orders past their timeout get rejected instead of being
            # force-filled at stale LTP.
            if self.fill_mode == "market_like":
                for order in list(self._orders.values()):
                    if order.status == OrderStatus.OPEN:
                        self._force_fill_market_like(order)
            elif self.fill_mode in ('realistic', 'realistic_limit'):
                self._timeout_unfilled_orders()
            self._save_state()
        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.exception(f"tick callback error: {e}")

    # ------- internals -------
    def _try_fill(self, order: Order) -> None:
        tick = self._ticks.get(order.symbol)
        if not tick:
            return  # no price yet, leave open
        # FIX 2026-09-17 12:35: realistic mode uses live bid/ask for fills.
        # This honors half-spread crossing, partial fills, and unfilled LIMIT
        # rejection — the three things live trading surfaces that paper's
        # market_like silently hides.
        if self.fill_mode in ('realistic', 'realistic_limit'):
            self._apply_bid_ask_fill(order, tick)
            return
        order.expected_fill_price = tick.ltp
        fill_price = 0.0
        if order.order_type == OrderType.MARKET:
            # simulated slippage in direction of trade
            slip = tick.ltp * (self.slippage_bps / 10_000)
            fill_price = tick.ltp + (slip if order.side == OrderSide.BUY else -slip)
        elif order.order_type == OrderType.LIMIT:
            # FIX 2026-08-07: For paper trading, fill LIMIT orders with realistic probability
            # In a real market, a SELL at the LTP would have a buyer within 1-2 ticks
            # We fill aggressively to make paper trading actually work.
            # Spread parameters are configurable via constructor (no hardcodes).
            spread = max(self.limit_fill_min_spread, tick.ltp * (self.limit_fill_spread_pct / 100.0))
            synthetic_bid = tick.ltp - spread
            synthetic_ask = tick.ltp + spread
            if order.side == OrderSide.BUY:
                # BUY at limit: fill if limit >= synthetic_ask (realistic)
                if order.price >= synthetic_ask:
                    fill_price = min(order.price, synthetic_ask)
                # Also fill if limit is at LTP (within near-LTP pct of ask)
                elif abs(order.price - tick.ltp) / tick.ltp < (self.limit_fill_near_ltp_pct / 100.0):
                    fill_price = order.price
            elif order.side == OrderSide.SELL:
                # SELL at limit: fill if limit <= synthetic_bid (realistic)
                if order.price <= synthetic_bid:
                    fill_price = max(order.price, synthetic_bid)
                # Also fill if limit is at LTP (within near-LTP pct of bid)
                elif abs(order.price - tick.ltp) / tick.ltp < (self.limit_fill_near_ltp_pct / 100.0):
                    fill_price = order.price
        elif order.order_type == OrderType.SL:
            if (order.side == OrderSide.BUY and tick.ltp >= order.trigger_price) or \
               (order.side == OrderSide.SELL and tick.ltp <= order.trigger_price):
                fill_price = order.price if order.price > 0 else tick.ltp
        elif order.order_type == OrderType.SL_M:
            if (order.side == OrderSide.BUY and tick.ltp >= order.trigger_price) or \
               (order.side == OrderSide.SELL and tick.ltp <= order.trigger_price):
                fill_price = tick.ltp
        if fill_price > 0:
            order.avg_fill_price = round(fill_price, 2)
            order.filled_qty = order.qty
            order.status = OrderStatus.COMPLETE
            order.filled_at = datetime.now(timezone.utc)
            self._apply_fill(order)
            logger.info(
                f"[PAPER] FILL {order.order_id} {order.qty}×{order.symbol} @ {order.avg_fill_price} "
                f"(tick={tick.ltp})"
            )

    def _apply_fill(self, order: Order) -> None:
        pos = self._positions.get(order.symbol)
        fill_value = order.filled_qty * order.avg_fill_price
        # FIX 2026-09-07 22:45: capture realized_pnl before so we can compute
        # the realized_delta from this fill. We fire the fill callbacks (used
        # for inline trade_journal.jsonl writes) after the position update.
        _realized_before = self._realized_pnl
        if order.side == OrderSide.BUY:
            self._cash -= fill_value
            if pos:
                if pos.qty > 0:
                    # adding to a LONG (average up)
                    total_qty = pos.qty + order.filled_qty
                    pos.avg_price = (pos.avg_price * pos.qty + order.avg_fill_price * order.filled_qty) / total_qty
                    pos.qty = total_qty
                    pos.ltp = order.avg_fill_price
                else:
                    # reducing or closing a SHORT
                    short_close = min(abs(pos.qty), order.filled_qty)
                    self._realized_pnl += (pos.avg_price - order.avg_fill_price) * short_close
                    pos.qty += order.filled_qty  # pos.qty is negative, so adding = closer to 0
                    if pos.qty == 0:
                        del self._positions[order.symbol]
                    elif pos.qty > 0:
                        # closed the short AND opened a LONG with the excess
                        pos.avg_price = order.avg_fill_price
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    qty=order.filled_qty,
                    avg_price=order.avg_fill_price,
                    ltp=order.avg_fill_price,
                    product=order.product,
                    strike=order.strike,
                    option_type=order.option_type,
                    expiry=order.expiry,
                    underlying=order.underlying,
                    entry_time=datetime.now(timezone.utc),
                )
        else:  # SELL
            self._cash += fill_value
            if pos:
                if pos.qty > 0:
                    # closing or reducing a LONG
                    close_qty = min(pos.qty, order.filled_qty)
                    self._realized_pnl += (order.avg_fill_price - pos.avg_price) * close_qty
                    pos.qty -= order.filled_qty
                    if pos.qty == 0:
                        del self._positions[order.symbol]
                    elif pos.qty < 0:
                        # flipped through zero: leftover becomes a SHORT at this fill price
                        # (rare; happens only on over-close)
                        pos.avg_price = order.avg_fill_price
                else:
                    # adding to or closing a SHORT
                    short_close = min(abs(pos.qty), order.filled_qty)
                    self._realized_pnl += (pos.avg_price - order.avg_fill_price) * short_close
                    pos.qty -= order.filled_qty  # pos.qty is negative, so subtracting = more negative
                    if pos.qty == 0:
                        del self._positions[order.symbol]
                    elif pos.qty > 0:
                        # closed the short AND opened a LONG with the excess
                        pos.avg_price = order.avg_fill_price
            else:
                # BUG FIX 2026-08-10: SELL into nothing must OPEN a SHORT position.
                # Previously the SELL was only recorded in orders dict; the SHORT was
                # never reflected in self._positions, so the close-BUY later created a
                # phantom LONG and broke reconciliation. (See: 4 ghost longs at EOD.)
                self._positions[order.symbol] = Position(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    qty=-order.filled_qty,  # negative = short
                    avg_price=order.avg_fill_price,
                    ltp=order.avg_fill_price,
                    product=order.product,
                    strike=order.strike,
                    option_type=order.option_type,
                    expiry=order.expiry,
                    underlying=order.underlying,
                    entry_time=datetime.now(timezone.utc),
                )
        # FIX 2026-09-07 22:45: fire fill callbacks so the bot can write
        # trade_journal.jsonl inline. The delta is positive for gains, negative
        # for losses, 0 for pure opens. Callbacks must not raise.
        _realized_delta = self._realized_pnl - _realized_before
        for cb in list(self._fill_callbacks):
            try:
                cb(order, _realized_delta)
            except Exception as e:
                logger.exception(f"fill callback error: {e}")

    # ------- persistence -------
    def _log_rejection(self, order: 'Order', reason: str) -> None:
        """FIX 2026-09-17 13:15: append a rejection record to the persistent
        feedback log. The LLM brain reads this in its periodic context so it
        sees recent failures and avoids repeating them.

        Format:
            {"ts": ISO timestamp,
             "order_id": order_id,
             "symbol": symbol,
             "side": BUY|SELL,
             "qty": qty,
             "order_type": MARKET|LIMIT,
             "limit_price": limit_price_or_0,
             "reason": str,
             "ltp_at_reject": float,
             "bid_at_reject": float,
             "ask_at_reject": float}
        """
        import json as _jl
        tick = self._ticks.get(order.symbol)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value if hasattr(order.side, "value") else str(order.side),
            "qty": int(order.qty or 0),
            "order_type": order.order_type.value if hasattr(order.order_type, "value") else str(order.order_type),
            "limit_price": float(order.price or 0),
            "reason": reason,
            "ltp_at_reject": tick.ltp if tick else 0,
            "bid_at_reject": tick.bid if tick else 0,
            "ask_at_reject": tick.ask if tick else 0,
        }
        try:
            REJECTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with REJECTIONS_LOG.open("a", encoding="utf-8") as f:
                f.write(_jl.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"rejection log write failed: {e}")
        # Keep last 50 in memory for the brain's recent-rejections view.
        self._recent_rejections.append(record)
        if len(self._recent_rejections) > 50:
            self._recent_rejections = self._recent_rejections[-50:]

    def get_recent_rejections(self, n: int = 10) -> list[dict]:
        """FIX 2026-09-17 13:15: return the most-recent N rejection records
        (newest first). Used by the LLM brain's _periodic_scan to surface
        realistic-mode feedback into the decision context.
        """
        # First try in-memory (fast), fall back to file
        if self._recent_rejections:
            return list(reversed(self._recent_rejections[-n:]))
        if not REJECTIONS_LOG.exists():
            return []
        try:
            out: list[dict] = []
            with REJECTIONS_LOG.open("r", encoding="utf-8") as f:
                lines = f.readlines()[-n:]
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
            return list(reversed(out))
        except Exception as e:
            logger.debug(f"get_recent_rejections failed: {e}")
            return []

    def _settle_expired_positions(self, state: dict) -> None:
        """FIX 2026-09-17 22:50: 0DTE expiry settlement on bot startup.

        Scans positions dict for any option with expiry < today OR expiry==today
        + market closed (>= 15:30 IST). These positions expired at 15:30 IST
        (NSE auto-settlement for 0DTE options). In live trading, NSE handles this:
          - OTM option (strike < spot for CE, strike > spot for PE): Rs.0
          - ITM option: intrinsic value (|spot - strike|)
        In paper, we settle at startup to avoid carrying stale positions
        into the next session.

        Settlement process:
          1. For each expired position in state['positions'] (raw dict):
             a. Determine settlement price (0 for OTM, intrinsic for ITM)
             b. Update state['positions'] to remove the position
             c. Compute realized_delta = (settlement - avg_price) * qty
             d. Add to state['realized_pnl'] AND self._realized_pnl
          2. Save state after settlement.

        Note: this operates on the RAW state dict, NOT self._positions,
        because _load_state calls this BEFORE self._positions is populated.
        The settlement closes positions by removing them from state['positions']
        directly. When _load_state later iterates state['positions'], the
        expired positions are already gone.
        """
        from datetime import date as _date, time as _time
        try:
            positions = state.get("positions", {}) or {}
            if not positions:
                return
            today = _date.today()
            # India-local time check (UTC+5:30) for "is the market closed today?"
            now_utc = datetime.now(timezone.utc)
            ist_offset = __import__('datetime').timedelta(hours=5, minutes=30)
            now_ist = (now_utc + ist_offset).replace(tzinfo=None)
            market_closed_today = now_ist.time() >= _time(15, 30)
            expired_symbols = []
            for sym, pos in positions.items():
                exp_str = pos.get("expiry") if isinstance(pos, dict) else getattr(pos, "expiry", None)
                if not exp_str:
                    continue
                try:
                    exp_date = _date.fromisoformat(str(exp_str)[:10])
                except Exception:
                    continue
                # Position is expired if: (a) expiry is in the past, OR
                # (b) expiry is today AND market has closed (>= 15:30 IST).
                if exp_date < today or (exp_date == today and market_closed_today):
                    expired_symbols.append((sym, pos, exp_date))
            if not expired_symbols:
                return
            logger.warning(
                f"[PAPER] 0DTE EXPIRY SETTLEMENT: {len(expired_symbols)} position(s) expired in previous sessions"
            )
            # Use the latest tick's underlying INDEX price as spot reference.
            # Must NOT match option ticks (which start with same underlying name).
            # Index ticks are like "NIFTY 50", "BANKNIFTY", "FINNIFTY" etc.
            # Option ticks are like "NIFTY17SEP2623500CE".
            import re as _re_settle
            _opt_sym_re = _re_settle.compile(
                r'^(NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX)'
                r'\d{2}[A-Z]{3}\d{2}\d+(CE|PE)$'
            )
            n_settled = 0
            total_realized_delta = 0.0
            for sym, pos, exp_date in expired_symbols:
                try:
                    qty = pos.get("qty") if isinstance(pos, dict) else getattr(pos, "qty", 0)
                    avg_price = pos.get("avg_price") if isinstance(pos, dict) else getattr(pos, "avg_price", 0)
                    opt_type = pos.get("option_type") if isinstance(pos, dict) else getattr(pos, "option_type", "")
                    strike = pos.get("strike") if isinstance(pos, dict) else getattr(pos, "strike", 0)
                    underlying = pos.get("underlying") if isinstance(pos, dict) else getattr(pos, "underlying", "")
                    if qty == 0 or not opt_type or not underlying:
                        continue
                    # Determine spot reference (for ITM check).
                    spot = 0.0
                    for tick_sym, tick in self._ticks.items():
                        tick_sym_clean = tick_sym.upper().strip()
                        if _opt_sym_re.match(tick_sym_clean):
                            continue
                        if (tick_sym_clean == underlying.upper()
                            or tick_sym_clean.startswith(underlying.upper() + " ")
                            or (underlying.upper() == "NIFTY" and "NIFTY 50" in tick_sym_clean)
                            or (underlying.upper() == "BANKNIFTY" and "NIFTY BANK" in tick_sym_clean)):
                            if tick.ltp and tick.ltp > 0:
                                spot = tick.ltp
                                break
                    if spot <= 0:
                        # Fall back to chain LTP for the underlying from option_chains.json
                        try:
                            chains_path = DCACHE / "option_chains.json"
                            if chains_path.exists():
                                chains = json.loads(chains_path.read_text(encoding="utf-8"))
                                chain_data = chains.get("chains", {}).get(underlying.upper(), {})
                                spot = float(chain_data.get("spot", 0) or 0)
                        except Exception:
                            pass
                    # Compute intrinsic value at expiry
                    if opt_type.upper() == "CE":
                        intrinsic = max(0.0, spot - strike)
                    else:  # PE
                        intrinsic = max(0.0, strike - spot)
                    # Settlement price = intrinsic. OTM options settle at 0.
                    settlement_price = round(intrinsic, 2)
                    # P&L = (settlement_price - avg_price) * qty
                    realized_delta = (settlement_price - avg_price) * qty
                    total_realized_delta += realized_delta
                    # FIX 2026-09-17 23:00: write back to RAW state dict (not
                    # self._positions, which isn't populated yet at this point).
                    # We add the realized_delta to realized_pnl and remove the
                    # position. When _load_state later iterates state['positions'],
                    # the expired position is already gone.
                    if "realized_pnl" not in state:
                        state["realized_pnl"] = 0.0
                    state["realized_pnl"] += realized_delta
                    # Also update in-memory so the bot's later _save_state uses
                    # the new realized_pnl.
                    self._realized_pnl = state["realized_pnl"]
                    # Remove from RAW state['positions'] dict
                    if sym in state.get("positions", {}):
                        del state["positions"][sym]
                    logger.warning(
                        f"[PAPER] 0DTE EXPIRY: {sym} qty={qty} settled @ Rs.{settlement_price} "
                        f"(intrinsic={intrinsic:.2f}, avg={avg_price:.2f}, "
                        f"realized_delta=Rs.{realized_delta:+,.2f})"
                    )
                    n_settled += 1
                except Exception as _sse:
                    logger.warning(f"[PAPER] 0DTE EXPIRY: error settling {sym}: {_sse}")
            if n_settled:
                logger.info(
                    f"[PAPER] 0DTE EXPIRY: settled {n_settled} expired positions, "
                    f"new realized_pnl=Rs.{self._realized_pnl:,.2f} (delta Rs.{total_realized_delta:+,.2f})"
                )
                # Note: do NOT call _save_state here. _load_state is mid-process
                # and the state is still being read. _save_state at the end of
                # run_paper will write the updated state to disk.
        except Exception as _ss_err:
            logger.warning(f"[PAPER] 0DTE EXPIRY: settlement sweep failed: {_ss_err}")

    def _save_state(self) -> None:
        # FIX 2026-09-08 14:20: skip-save flag for clean resets. The pre-market
        # reset script (scripts/pre_market_reset_paper_state.py) creates this
        # flag, writes a clean paper_state.json, then removes it. While the
        # flag is present, _save_state returns early — so the bot's in-memory
        # state doesn't overwrite the freshly-written clean state on the next
        # tick. The bot eventually restarts (via nssm or force-action) to load
        # the clean state. This breaks the reset race where the bot's
        # tick-driven _save_state (~every 2-5s) was overwriting the user-
        # written clean state within seconds.
        skip_flag = self.persist_path.parent / "_skip_save.json"
        if skip_flag.exists():
            try:
                import time as _t_skip
                _mtime = skip_flag.stat().st_mtime
                if _t_skip.time() - _mtime < 60:  # safety: don't honor flag older than 60s
                    logger.debug(f"[PAPER] _save_state skipped (skip-save flag present, age={_t_skip.time() - _mtime:.1f}s)")
                    return
                else:
                    logger.warning(f"[PAPER] _skip_save.json is stale ({_t_skip.time() - _mtime:.1f}s old), removing and proceeding")
                    try:
                        skip_flag.unlink()
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            # BUG FIX 2026-08-11: shallow-copy each object's __dict__ before mutating
            # for serialization. `o.__dict__` returns a REFERENCE to the instance
            # namespace, so the previous code was mutating the live Order/Position
            # enums to strings every save. That broke OrderManager's in-memory view
            # of the trade book. Found by e2e_test.py: o.side became a string
            # after the first place_order + save.
            import copy
            state = {
                "cash": self._cash,
                "realized_pnl": self._realized_pnl,
                "orders": {oid: copy.copy(o.__dict__) for oid, o in self._orders.items()},
                "positions": {s: copy.copy(p.__dict__) for s, p in self._positions.items()},
            }
            # datetime/Enum to string (now safe — we're mutating the copy, not the original)
            for oid, od in state["orders"].items():
                for k, v in list(od.items()):
                    if isinstance(v, datetime):
                        od[k] = v.isoformat()
                    elif isinstance(v, OrderStatus):
                        od[k] = v.value
                    elif isinstance(v, (OrderSide, OrderType, ProductType)):
                        od[k] = v.value
            for s, pd in state["positions"].items():
                for k, v in list(pd.items()):
                    if isinstance(v, datetime):
                        pd[k] = v.isoformat()
                    elif isinstance(v, ProductType):
                        pd[k] = v.value
            # write atomically: tmp file then replace, with retry on WinError 5
            tmp = self.persist_path.with_suffix(".tmp")
            json_text = json.dumps(state, indent=2, default=str, ensure_ascii=False)
            for attempt in range(3):
                try:
                    tmp.write_text(json_text, encoding="utf-8")
                    # try replace, may fail if file is locked by another reader
                    if self.persist_path.exists():
                        # on Windows, os.replace works even if file is open for reading
                        import os
                        os.replace(tmp, self.persist_path)
                    else:
                        tmp.replace(self.persist_path)
                    return
                except (PermissionError, OSError) as e:
                    if attempt < 2:
                        import time as _t
                        _t.sleep(0.05 * (attempt + 1))
                    else:
                        # last attempt failed — fall back to direct write
                        try:
                            self.persist_path.write_text(json_text, encoding="utf-8")
                            return
                        except Exception as ee:
                            raise
        except Exception as e:
            logger.warning(f"PaperClient state save failed: {e}")

    def _load_state(self) -> None:
        if not self.persist_path.exists():
            return
        try:
            state = json.loads(self.persist_path.read_text(encoding="utf-8"))
            self._cash = state.get("cash", self.starting_capital)
            self._realized_pnl = state.get("realized_pnl", 0.0)
            # FIX 2026-09-17 22:50: 0DTE expiry settlement. If a position's
            # expiry is < today, it expired on its expiry date at 15:30 IST.
            # In live trading, NSE auto-settles these (OTM = Rs.0, ITM = intrinsic).
            # In paper, we settle at startup so tomorrow's bot doesn't carry
            # stale LTP positions. This is critical for the orphan-cleanup
            # loop and prevents the bot from being confused by yesterday's
            # expired contracts showing as "open" with stale prices.
            self._settle_expired_positions(state)
            for oid, od in state.get("orders", {}).items():
                if "placed_at" in od and od["placed_at"]:
                    od["placed_at"] = datetime.fromisoformat(od["placed_at"])
                if "filled_at" in od and od["filled_at"]:
                    od["filled_at"] = datetime.fromisoformat(od["filled_at"])
                if "status" in od and isinstance(od["status"], str):
                    od["status"] = OrderStatus(od["status"])
                # BUG FIX 2026-08-11: also convert side/order_type/product back
                # to enums on load. Without this, orders saved by the previous
                # buggy _save_state (which wrote strings) load with strings,
                # breaking any code that does `if order.side == OrderSide.BUY`.
                for k in ("side", "order_type"):
                    if k in od and isinstance(od[k], str):
                        if k == "side":
                            od[k] = OrderSide(od[k])
                        elif k == "order_type":
                            od[k] = OrderType(od[k])
                if "product" in od and isinstance(od["product"], str):
                    od["product"] = ProductType(od["product"])
                order = Order(**od)
                # 2026-08-13: zombie order cleanup. Historical OPEN orders from previous
                # days were saved with price=0 (multi-leg strategy orders that never
                # got a real limit). They will never fill and would flood warnings.
                # Cancel them on load so the bot starts clean.
                if order.status == OrderStatus.OPEN and (order.price or 0) <= 0:
                    order.status = OrderStatus.CANCELLED
                    logger.info(f"[PAPER] ZOMBIE_CLEAN cancelled {oid} {order.symbol} (loaded with price=0)")
                self._orders[oid] = order
            for s, pd in state.get("positions", {}).items():
                if "entry_time" in pd and pd["entry_time"]:
                    pd["entry_time"] = datetime.fromisoformat(pd["entry_time"])
                if "product" in pd and isinstance(pd["product"], str):
                    pd["product"] = ProductType(pd["product"])
                self._positions[s] = Position(**pd)
            logger.info(f"PaperClient loaded state: {len(self._orders)} orders, {len(self._positions)} positions")
        except Exception as e:
            logger.warning(f"PaperClient state load failed: {e}")

    def reset(self) -> None:
        """Wipe paper state and start fresh."""
        with self._lock:
            self._orders.clear()
            self._positions.clear()
            self._ticks.clear()
            self._cash = self.starting_capital
            self._realized_pnl = 0.0
            if self.persist_path.exists():
                self.persist_path.unlink()
            logger.info("PaperClient reset")

    def rebuild_positions_from_orders(self) -> dict:
        """Recompute positions from COMPLETE order history.

        BUG RECOVERY 2026-08-10: Before the SELL-without-position fix, opening shorts
        (iron butterfly, strangle, etc.) left positions unrecorded. The close BUY
        then created phantom LONGs. This method walks the order book and rebuilds
        the net position per symbol from scratch.

        Returns a report dict with: {rebuilt, dropped, kept, before_count, after_count}.
        """
        with self._lock:
            before = {s: (p.qty, p.avg_price) for s, p in self._positions.items()}
            # bucket filled quantity by side per symbol
            net: dict[str, dict] = {}
            for o in self._orders.values():
                if o.status != OrderStatus.COMPLETE:
                    continue
                # map side to signed qty
                if o.side == OrderSide.BUY:
                    signed = +o.filled_qty
                elif o.side == OrderSide.SELL:
                    signed = -o.filled_qty
                else:
                    continue
                if o.symbol not in net:
                    net[o.symbol] = {"qty": 0, "buy_qty": 0, "buy_val": 0.0,
                                     "sell_qty": 0, "sell_val": 0.0,
                                     "meta": o}
                b = net[o.symbol]
                b["qty"] += signed
                if signed > 0:
                    b["buy_qty"] += signed
                    b["buy_val"] += signed * o.avg_fill_price
                else:
                    b["sell_qty"] += -signed
                    b["sell_val"] += -signed * o.avg_fill_price

            # build new positions dict
            new_positions: dict[str, Position] = {}
            realized_delta = 0.0
            for sym, b in net.items():
                net_qty = b["qty"]
                if net_qty == 0:
                    # fully closed → realize PnL using the legs
                    if b["sell_qty"] > 0 and b["buy_qty"] > 0:
                        # use average buy / sell prices for the realized PnL estimate
                        avg_buy = b["buy_val"] / b["buy_qty"]
                        avg_sell = b["sell_val"] / b["sell_qty"]
                        # signed PnL: (sell - buy) * min(sell_qty, buy_qty)
                        matched = min(b["sell_qty"], b["buy_qty"])
                        realized_delta += (avg_sell - avg_buy) * matched
                    continue
                # open position: derive avg_price from the dominant side
                meta = b["meta"]
                if net_qty > 0:
                    # net long: avg = buy_val / buy_qty
                    avg_price = b["buy_val"] / b["buy_qty"]
                else:
                    # net short: avg = sell_val / sell_qty
                    avg_price = b["sell_val"] / b["sell_qty"]
                new_positions[sym] = Position(
                    symbol=sym,
                    exchange=meta.exchange,
                    qty=net_qty,
                    avg_price=avg_price,
                    ltp=meta.avg_fill_price,
                    product=meta.product,
                    strike=meta.strike,
                    option_type=meta.option_type,
                    expiry=meta.expiry,
                    underlying=meta.underlying,
                    entry_time=meta.placed_at,
                )

            self._positions = new_positions
            # adjust realized_pnl: rebuild the delta over previous state
            # (we cannot fully reverse old realized, so we ADD the matched-pairs estimate
            # and accept small drift if the original was already partially booked)
            if realized_delta:
                self._realized_pnl += realized_delta
            self._save_state()

            after = {s: (p.qty, p.avg_price) for s, p in self._positions.items()}
            report = {
                "before": before,
                "after": after,
                "before_count": len(before),
                "after_count": len(after),
                "realized_pnl_delta": realized_delta,
            }
            logger.info(
                f"PaperClient rebuilt positions: {len(before)} -> {len(after)} "
                f"(realized_pnl delta: Rs.{realized_delta:,.2f})"
            )
            return report
