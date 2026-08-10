"""Live tick feed — three modes:
- 'synthetic': generates realistic OHLCV for paper testing (no creds needed)
- 'live_uat': subscribes to Kotak Neo UAT websocket (real ticks from UAT)
- 'live_ws': reserved for prod

Public surface:
    feed = LiveFeed(mode="synthetic", broker=PaperClient(...))
    feed.start()
    feed.get_ltp(symbol)
    feed.get_momentum(symbol, window=20)
    feed.on_tick(callback)
"""
from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import pandas as pd
from loguru import logger

from kotak_bot.broker.base import Tick
from kotak_bot.utils.clock import now_ist


class LiveFeed:
    """Unified live + synthetic tick feed."""

    def __init__(self, mode: str = "synthetic", broker=None, persist_path: str = "data_cache/ticks.csv",
                 neo_client=None):
        self.mode = mode
        self.broker = broker
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.neo_client = neo_client  # for live_uat / live_ws modes
        self._lock = threading.RLock()
        self._callbacks: list[Callable[[Tick], None]] = []
        self._subscribed: set[str] = set()
        self._latest: dict[str, Tick] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tick_count = 0
        self._stale_after_sec = 60
        self._last_tick_at: dict[str, float] = {}
        self._price_history: dict[str, list[float]] = {}  # per-symbol LTP history
        # for live UAT
        self._last_ws_reconnect_try = 0.0
        self._ws_connected = False
        # token map for live WS (synth mode doesn't need this)
        self._token_map: dict[str, dict] = {}  # symbol -> {token, exchange_segment, ...}

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            if self.mode == "synthetic":
                self._thread = threading.Thread(target=self._synthetic_loop, name="synth-feed", daemon=True)
                self._thread.start()
            elif self.mode in ("live_uat", "live_ws"):
                # discover tokens for our symbols
                self._discover_tokens()
                # hook into NeoClient on_message
                if self.neo_client and self.neo_client._client:
                    self.neo_client._client.on_message = self._on_ws_message
                    self.neo_client._client.on_error = self._on_ws_error
                    self.neo_client._client.on_close = self._on_ws_close
                    self.neo_client._client.on_open = self._on_ws_open
                    self._thread = threading.Thread(target=self._ws_loop, name="ws-feed", daemon=True)
                    self._thread.start()
                else:
                    logger.warning("LiveFeed: live mode but no neo_client — falling back to synthetic")
                    self.mode = "synthetic"
                    self._thread = threading.Thread(target=self._synthetic_loop, name="synth-feed", daemon=True)
                    self._thread.start()
            else:
                raise ValueError(f"unknown mode: {self.mode}")
            logger.info(f"LiveFeed started (mode={self.mode})")

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("LiveFeed stopped")

    def subscribe(self, symbols: list[str]) -> None:
        with self._lock:
            for s in symbols:
                if s not in self._subscribed:
                    self._subscribed.add(s)
                    if self.mode in ("live_uat", "live_ws") and self.neo_client and self.neo_client._client:
                        try:
                            tok = self._token_map.get(s)
                            if tok:
                                self.neo_client._client.subscribe(
                                    instrument_tokens=[{
                                        "instrument_token": tok["token"],
                                        "exchange_segment": tok["exchange_segment"],
                                    }],
                                    isIndex=tok.get("is_index", False),
                                    isDepth=False,
                                )
                                logger.info(f"LiveFeed: subscribed to {s} token={tok['token']}")
                        except Exception as e:
                            logger.warning(f"subscribe {s}: {e}")
        if self.mode == "synthetic":
            pass  # synthetic loop emits on demand

    def on_tick(self, callback: Callable[[Tick], None]) -> None:
        self._callbacks.append(callback)

    def get_ltp(self, symbol: str) -> float:
        with self._lock:
            t = self._latest.get(symbol)
            return t.ltp if t else 0.0

    def get_latest(self, symbol: str) -> Optional[Tick]:
        with self._lock:
            return self._latest.get(symbol)

    def is_stale(self, symbol: str) -> bool:
        last = self._last_tick_at.get(symbol)
        if not last:
            return True
        return (time.time() - last) > self._stale_after_sec

    def get_momentum(self, symbol: str, window: int = 20) -> float:
        with self._lock:
            hist = self._price_history.get(symbol, [])
            if len(hist) < 5:
                return 0.0
            recent = hist[-window:] if len(hist) >= window else hist
            if not recent:
                return 0.0
            first = recent[0]
            last = recent[-1]
            if first <= 0:
                return 0.0
            return (last - first) / first

    def get_price_history(self, symbol: str) -> list[float]:
        with self._lock:
            return list(self._price_history.get(symbol, []))

    def get_oi_map(self, underlying: str) -> dict:
        """Return {strike: {ce_oi, pe_oi, ce_ltp, pe_ltp}} for the latest option chain snapshot.
        Used for OI heatmap."""
        with self._lock:
            return {k: v for k, v in self._latest.items()
                    if k.startswith(underlying) and (k.endswith("CE") or k.endswith("PE"))}

    def _discover_tokens(self) -> None:
        """Discover scrip tokens for our underlyings (NIFTY, BANKNIFTY) and option chain."""
        if not self.neo_client:
            return
        try:
            # ensure scrip master loaded
            if not self.neo_client._scrip_master:
                self.neo_client.load_scrip_master(["nse_cm", "nse_fo"])
            # for NIFTY/BANKNIFTY index, we need a known token
            # NSE index tokens: NIFTY 50 = "26000", BANKNIFTY = "26009"
            self._token_map["NIFTY"] = {"token": "26000", "exchange_segment": "nse_cm", "is_index": True}
            self._token_map["BANKNIFTY"] = {"token": "26009", "exchange_segment": "nse_cm", "is_index": True}
            # for option chain, use scrip master to find by expiry/strike — too dynamic for now,
            # we'll let the live feed skip option tokens and rely on periodic quotes() for OI.
            logger.info(f"LiveFeed: discovered tokens for {list(self._token_map.keys())}")
        except Exception as e:
            logger.warning(f"discover tokens failed: {e}")

    def _on_ws_message(self, message) -> None:
        """Handle websocket message from Kotak Neo."""
        try:
            # message format: {ts: ..., data: [{tk: '26000', e: 'nse_cm', ltp: ..., ...}]}
            data = message.get("data", []) if isinstance(message, dict) else []
            if not data and isinstance(message, list):
                data = message
            for item in data:
                token = str(item.get("tk") or item.get("instrument_token") or item.get("token", ""))
                ltp = float(item.get("lp") or item.get("ltp") or item.get("last_traded_price", 0))
                if ltp <= 0:
                    continue
                # find symbol by token
                sym = None
                for s, t in self._token_map.items():
                    if t["token"] == token:
                        sym = s
                        break
                if sym:
                    t = Tick(
                        symbol=sym, ltp=ltp,
                        bid=float(item.get("bp1", ltp - 0.5)),
                        ask=float(item.get("sp1", ltp + 0.5)),
                        volume=int(item.get("v", 0)),
                        oi=int(item.get("oi", 0)),
                        timestamp=now_ist(),
                        exchange="NSE",
                        underlying=sym,
                    )
                    self._dispatch(t)
        except Exception as e:
            logger.debug(f"ws message parse: {e}")

    def _on_ws_error(self, msg) -> None:
        logger.warning(f"ws error: {msg}")

    def _on_ws_close(self, msg) -> None:
        logger.warning(f"ws close: {msg}")
        self._ws_connected = False

    def _on_ws_open(self, msg) -> None:
        logger.info(f"ws open: {msg}")
        self._ws_connected = True
        # re-subscribe on reconnect
        self.subscribe(list(self._subscribed))

    def _ws_loop(self) -> None:
        """Background WS health check + reconnect."""
        while self._running:
            if not self._ws_connected and (time.time() - self._last_ws_reconnect_try) > 30:
                self._last_ws_reconnect_try = time.time()
                try:
                    self.subscribe(list(self._subscribed))
                except Exception as e:
                    logger.debug(f"ws reconnect: {e}")
            time.sleep(5)

    def _dispatch(self, tick: Tick) -> None:
        with self._lock:
            self._latest[tick.symbol] = tick
            self._last_tick_at[tick.symbol] = time.time()
            self._tick_count += 1
            hist = self._price_history.setdefault(tick.symbol, [])
            hist.append(tick.ltp)
            if len(hist) > 600:
                hist[:] = hist[-600:]
        if self.broker is not None and hasattr(self.broker, "inject_tick"):
            try:
                self.broker.inject_tick(tick)
            except Exception as e:
                logger.exception(f"paper inject: {e}")
        for cb in self._callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.exception(f"tick cb: {e}")

    # ------- synthetic data loop -------
    def _synthetic_loop(self) -> None:
        """Generate realistic NIFTY/BANKNIFTY option prices using GBM with regime switching."""
        random.seed(42)
        spot = {"NIFTY": 24500.0, "BANKNIFTY": 52000.0}
        params = {
            "NIFTY":    {"mu": 0.10, "sigma": 0.16, "lot": 75, "step": 50},
            "BANKNIFTY":{"mu": 0.10, "sigma": 0.20, "lot": 30, "step": 100},
        }
        regime = {"NIFTY": 0, "BANKNIFTY": 0}
        regime_timer = {"NIFTY": 0, "BANKNIFTY": 0}
        strikes = {"NIFTY": [], "BANKNIFTY": []}
        strike_cache = {"NIFTY": None, "BANKNIFTY": None}

        logger.info("Synthetic feed generating ticks for NIFTY, BANKNIFTY + 9 strikes each (dated symbol format, ATM ±4)")
        last_emit = time.time()
        while self._running:
            time.sleep(0.5)
            now = now_ist()
            expiry_str = now.strftime("%d%b%y").upper()
            for sym in ("NIFTY", "BANKNIFTY"):
                p = params[sym]
                if time.time() - regime_timer[sym] > random.uniform(60, 180):
                    regime[sym] = random.choice([0, 0, 0, 1, 1, 2])
                    regime_timer[sym] = time.time()
                vol_mult = [0.8, 1.0, 1.8][regime[sym]]
                sigma_tick = p["sigma"] * vol_mult / math.sqrt(252 * 6.25 * 3600)
                z = random.gauss(0, 1) * (1.5 if random.random() < 0.3 else 1.0)
                dS = spot[sym] * sigma_tick * z
                spot[sym] = max(spot[sym] + dS, 1.0)
                self._dispatch(Tick(
                    symbol=sym, ltp=round(spot[sym], 2),
                    bid=round(spot[sym] - 0.5, 2), ask=round(spot[sym] + 0.5, 2),
                    volume=random.randint(1000, 50000), oi=0,
                    timestamp=now, exchange="NSE", underlying=sym,
                ))
            for sym in ("NIFTY", "BANKNIFTY"):
                p = params[sym]
                step = p["step"]
                if strike_cache[sym] is None or (time.time() - last_emit) > 5:
                    atm = round(spot[sym] / step) * step
                    strikes[sym] = [atm + (i - 4) * step for i in range(9)]
                    last_emit = time.time()
                for k in strikes[sym]:
                    intrinsic_ce = max(0, spot[sym] - k)
                    intrinsic_pe = max(0, k - spot[sym])
                    distance = abs(spot[sym] - k) / spot[sym]
                    tv = max(0, 80 * math.exp(-distance * 50) * random.uniform(0.8, 1.2))
                    vol_mult = [0.8, 1.0, 1.8][regime[sym]]
                    tv *= vol_mult
                    for opt_type, intrinsic in (("CE", intrinsic_ce), ("PE", intrinsic_pe)):
                        ltp = round(intrinsic + tv, 2)
                        bid = round(max(intrinsic, ltp - 1.5), 2)
                        ask = round(ltp + 1.5, 2)
                        sym_full = f"{sym}{expiry_str}{int(k)}{opt_type}"
                        self._dispatch(Tick(
                            symbol=sym_full, ltp=ltp, bid=bid, ask=ask,
                            volume=random.randint(100, 10000),
                            oi=random.randint(1000, 100000),
                            timestamp=now, exchange="NFO",
                            strike=k, option_type=opt_type,
                            expiry=now.strftime("%Y-%m-%d"),
                            underlying=sym,
                        ))
