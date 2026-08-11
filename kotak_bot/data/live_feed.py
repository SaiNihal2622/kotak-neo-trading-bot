"""Live tick feed — five modes:
- 'synthetic': generates realistic OHLCV for paper testing (no creds needed)
- 'live_india': REAL NIFTY/BANKNIFTY spot via yfinance + Black-Scholes option pricing
               (best for paper trading with no broker creds; option prices are theoretical)
- 'live_uat': subscribes to Kotak Neo UAT websocket (real ticks from UAT)
- 'live_ws': reserved for prod
- 'live_kotak': REAL NSE option prices from Kotak Neo PROD via polling (recommended)
                (real bid/ask depth, real LTP, real OI; ~2s latency)

Public surface:
    feed = LiveFeed(mode="live_kotak", broker=PaperClient(...))
    feed.start()
    feed.get_ltp(symbol)
    feed.get_momentum(symbol, window=20)
    feed.on_tick(callback)
"""
from __future__ import annotations

import math
import os
import random
import re
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


# ---------------------------------------------------------------------------
# Black-Scholes helpers (used by live_india mode to price options from a real
# spot + a real India VIX). Public-domain formula; no external dep.
# ---------------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (no scipy dep)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, t_years: float, vol: float, r: float, opt_type: str) -> float:
    """Black-Scholes price for a European option. Returns 0 if t_years<=0."""
    if t_years <= 0 or vol <= 0 or spot <= 0 or strike <= 0:
        # intrinsic only
        if opt_type.upper() == "CE":
            return max(0.0, spot - strike)
        return max(0.0, strike - spot)
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    if opt_type.upper() == "CE":
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)
    else:
        price = strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return max(0.01, price)


def bs_iv_from_price(price: float, spot: float, strike: float, t_years: float, r: float, opt_type: str) -> float:
    """Bisection-based implied vol from a market price. Returns the IV (annualized)."""
    if price <= 0 or t_years <= 0:
        return 0.0
    lo, hi = 0.01, 3.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        p = bs_price(spot, strike, t_years, mid, r, opt_type)
        if p > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


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
        # for live_kotak (KotakProdFeed adapter)
        self._kotak_feed = None  # initialized in start() for live_kotak mode

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            if self.mode == "synthetic":
                self._thread = threading.Thread(target=self._synthetic_loop, name="synth-feed", daemon=True)
                self._thread.start()
            elif self.mode == "live_india":
                self._thread = threading.Thread(target=self._live_india_loop, name="live-india-feed", daemon=True)
                self._thread.start()
            elif self.mode == "live_kotak":
                # Real NSE option prices via Kotak Neo PROD polling.
                # Reads creds from env: KOTAK_API_KEY, KOTAK_MOBILE, KOTAK_UCC,
                # KOTAK_TOTP_SECRET, KOTAK_MPIN, KOTAK_ENV (default 'uat').
                from kotak_bot.data.kotak_prod_feed import KotakProdFeed
                access_token = os.environ.get('KOTAK_API_KEY', '')
                self._kotak_feed = KotakProdFeed(
                    env=os.environ.get('KOTAK_ENV', 'uat'),
                    access_token=access_token,
                    mobile=os.environ.get('KOTAK_MOBILE', ''),
                    ucc=os.environ.get('KOTAK_UCC', ''),
                    totp_secret=os.environ.get('KOTAK_TOTP_SECRET', ''),
                    mpin=os.environ.get('KOTAK_MPIN', ''),
                    poll_interval_sec=float(os.environ.get('KOTAK_PROD_POLL_SEC', '2.0')),
                )
                self._kotak_feed.on_tick(self._on_kotak_tick)
                # Subscribe to spot + whatever was already requested
                self._kotak_feed.subscribe(['NIFTY', 'BANKNIFTY'])
                for s in self._subscribed:
                    if s not in ('NIFTY', 'BANKNIFTY'):
                        self._kotak_feed.subscribe([s])
                try:
                    self._kotak_feed.start()
                except Exception as e:
                    logger.error(f"KotakProdFeed start failed: {e} — falling back to live_india")
                    self._running = False
                    self.mode = "live_india"
                    return self.start()
                # Heartbeat thread for log visibility
                self._thread = threading.Thread(target=self._live_kotak_loop, name="live-kotak-feed", daemon=True)
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
        if self._kotak_feed is not None:
            try:
                self._kotak_feed.stop()
            except Exception:
                pass
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
                    elif self.mode == "live_kotak" and self._kotak_feed is not None:
                        try:
                            self._kotak_feed.subscribe([s])
                        except Exception as e:
                            logger.warning(f"kotak subscribe {s}: {e}")
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

    # ------- live_kotak: PROD polling adapter -------
    def _on_kotak_tick(self, t: dict) -> None:
        """Convert a KotakProdFeed tick (dict) to our Tick dataclass and dispatch.

        Real NSE options arrive as full pTrdSymbol (e.g. 'NIFTY11AUG2624500CE').
        Real NSE spot arrives as 'NIFTY' or 'BANKNIFTY'.
        """
        try:
            sym = t.get('symbol', '')
            ltp = float(t.get('ltp', 0) or 0)
            if ltp <= 0:
                return
            bid = float(t.get('bid', 0) or 0)
            ask = float(t.get('ask', 0) or 0)
            oi = int(t.get('oi', 0) or 0)
            vol = int(t.get('volume', 0) or 0)
            # Parse option metadata from symbol (NIFTY/BANKNIFTY + DDMMMYY + STRIKE + CE/PE)
            underlying = None
            strike = 0.0
            option_type = None
            expiry = None
            exchange = "NSE"
            if sym in ('NIFTY', 'BANKNIFTY'):
                underlying = sym
                exchange = "NSE"
            elif sym.startswith('NIFTY') or sym.startswith('BANKNIFTY'):
                # Try to parse full symbol
                m = re.match(r'^(NIFTY|BANKNIFTY)(\d{2})(\d{2})(\d{2})(\d+)(CE|PE)$', sym)
                if m:
                    underlying = m.group(1)
                    dd, mm, yy, strike_s, opt = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
                    try:
                        expiry = f"20{yy}-{mm}-{dd}"
                    except Exception:
                        expiry = None
                    strike = float(strike_s)
                    option_type = opt
                    exchange = "NFO"
            tick = Tick(
                symbol=sym, ltp=ltp, bid=bid, ask=ask,
                volume=vol, oi=oi,
                timestamp=now_ist(), exchange=exchange,
                strike=strike, option_type=option_type, expiry=expiry,
                underlying=underlying,
            )
            self._dispatch(tick)
        except Exception as e:
            logger.debug(f"kotak tick parse: {e}")

    def _live_kotak_loop(self) -> None:
        """Heartbeat / health log for live_kotak mode. KotakProdFeed does the actual work."""
        if not hasattr(self, '_kotak_feed') or self._kotak_feed is None:
            return
        f = self._kotak_feed
        last_heartbeat = 0.0
        while self._running:
            try:
                now = time.time()
                if now - last_heartbeat > 60:
                    last_heartbeat = now
                    authed = f.is_authenticated()
                    subscribed = len(f._subscribed) if hasattr(f, '_subscribed') else 0
                    latest_count = len(f._latest) if hasattr(f, '_latest') else 0
                    logger.info(
                        f"LiveKotak heartbeat: authed={authed} subscribed={subscribed} "
                        f"latest={latest_count} tick_count={self._tick_count}"
                    )
            except Exception as e:
                logger.debug(f"kotak heartbeat: {e}")
            time.sleep(5)

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

    # ------- live India feed: real spot from yfinance + Black-Scholes for options -------
    def _live_india_loop(self) -> None:
        """Fetch real NIFTY/BANKNIFTY spot + India VIX from yfinance every cycle,
        then emit real-priced option ticks via Black-Scholes for ATM ±4 strikes.

        This is the 'live_india' mode: prices reflect the real market (modulo
        NSE's 15-min yfinance delay during market hours, and a synthetic spread
        bid/ask since yfinance doesn't give live option book depth).
        Falls back to last-known-good prices if yfinance errors out.
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.error("live_india mode requires yfinance. `pip install yfinance` and restart.")
            return

        # yfinance tickers
        SPOT_TICKERS = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
        params = {
            "NIFTY":     {"lot": 75,  "step": 50,  "min_tte_days": 0, "expiry": None},
            "BANKNIFTY": {"lot": 30,  "step": 100, "min_tte_days": 0, "expiry": None},
        }
        RISK_FREE = 0.06  # India 10-yr ~6%
        SPREAD_FACTOR = 0.02  # 2% spread baseline (0.5x in tight liquidity, 2x in stress)

        # persistent state
        spot = {"NIFTY": 24500.0, "BANKNIFTY": 52000.0}
        vix = {"NIFTY": 14.0, "BANKNIFTY": 14.0}  # default fallback
        last_fetch = 0.0
        fetch_interval = 30.0  # refresh from yfinance every 30s (rate-limit friendly)
        strikes = {"NIFTY": [], "BANKNIFTY": []}
        regime = {"NIFTY": 0, "BANKNIFTY": 0}
        regime_timer = 0.0
        rng = random.Random()  # not seeded — we WANT realistic noise

        logger.info(
            "LiveIndia feed starting: real NIFTY/BANKNIFTY spot from yfinance, "
            "options priced via Black-Scholes using India VIX"
        )

        while self._running:
            try:
                time.sleep(0.5)
                now = now_ist()
                expiry_str = now.strftime("%d%b%y").upper()
                expiry_iso = now.strftime("%Y-%m-%d")

                # 1) refresh real spot + VIX from yfinance every fetch_interval seconds
                if time.time() - last_fetch > fetch_interval:
                    try:
                        for sym, ticker in SPOT_TICKERS.items():
                            hist = yf.Ticker(ticker).history(period="1d")
                            if len(hist) > 0:
                                spot[sym] = float(hist["Close"].iloc[-1])
                        vhist = yf.Ticker("^INDIAVIX").history(period="1d")
                        if len(vhist) > 0:
                            vix_val = float(vhist["Close"].iloc[-1])
                            vix["NIFTY"] = vix["BANKNIFTY"] = vix_val
                        last_fetch = time.time()
                        logger.info(
                            f"LiveIndia refresh: NIFTY={spot['NIFTY']:.2f} "
                            f"BANKNIFTY={spot['BANKNIFTY']:.2f} VIX={vix['NIFTY']:.2f}"
                        )
                    except Exception as e:
                        logger.warning(f"LiveIndia yfinance refresh failed: {e} (using last-known)")

                # 2) regime switch every 60-180s (drives IV bump for realism)
                if time.time() - regime_timer > rng.uniform(60, 180):
                    regime["NIFTY"] = regime["BANKNIFTY"] = rng.choice([0, 0, 0, 1, 1, 2])
                    regime_timer = time.time()
                regime_mult = [1.0, 1.0, 1.3][regime["NIFTY"]]

                # 3) time to expiry — weekly expiry on Thursday, but we approximate with
                #    "days to next Thursday" if today's expiry is past
                weekday = now.weekday()  # 0=Mon ... 3=Thu ... 6=Sun
                if weekday <= 3:
                    days_to_expiry = 3 - weekday
                else:
                    days_to_expiry = 7 - weekday + 3  # next Thu
                # include the time-of-day fraction
                secs_left = days_to_expiry * 86400 + (15 * 3600 + 30 * 60 - (now.hour * 3600 + now.minute * 60 + now.second))
                t_years = max(1.0 / 365.0, secs_left / (365.0 * 86400.0))

                # 4) emit spot + options for each underlying
                for sym in ("NIFTY", "BANKNIFTY"):
                    p = params[sym]
                    step = p["step"]
                    atm = round(spot[sym] / step) * step
                    strikes[sym] = [atm + (i - 4) * step for i in range(9)]
                    iv_decimal = (vix[sym] / 100.0) * regime_mult

                    # spot tick (real price)
                    self._dispatch(Tick(
                        symbol=sym,
                        ltp=round(spot[sym], 2),
                        bid=round(spot[sym] - 0.05, 2),
                        ask=round(spot[sym] + 0.05, 2),
                        volume=0, oi=0,
                        timestamp=now, exchange="NSE", underlying=sym,
                    ))

                    for k in strikes[sym]:
                        for opt_type in ("CE", "PE"):
                            theo = bs_price(spot[sym], k, t_years, iv_decimal, RISK_FREE, opt_type)
                            # bid/ask spread: tighter near ATM, wider far OTM
                            distance = abs(spot[sym] - k) / spot[sym]
                            spread_pct = SPREAD_FACTOR * (0.5 + distance * 10)
                            half = max(0.05, theo * spread_pct)
                            bid = round(max(0.05, theo - half), 2)
                            ask = round(theo + half, 2)
                            ltp = round(theo, 2)
                            # synthetic OI/vol proportional to ATM-OI typical levels
                            base_oi = {"NIFTY": 50000, "BANKNIFTY": 20000}[sym]
                            oi = int(base_oi * max(0.05, math.exp(-distance * 5)) * rng.uniform(0.5, 1.5))
                            vol = int(oi * rng.uniform(0.05, 0.3))
                            sym_full = f"{sym}{expiry_str}{int(k)}{opt_type}"
                            self._dispatch(Tick(
                                symbol=sym_full, ltp=ltp, bid=bid, ask=ask,
                                volume=vol, oi=oi,
                                timestamp=now, exchange="NFO",
                                strike=k, option_type=opt_type,
                                expiry=expiry_iso, underlying=sym,
                            ))
            except Exception as e:
                logger.exception(f"LiveIndia loop error: {e}")
                time.sleep(2)
