"""Deribit feed — real BTC/ETH option chain from Deribit's public REST API.

Why this exists:
- The Kotak Neo bot paper-trades NSE index options; this extends it to crypto.
- Deribit's public market-data REST endpoints need NO auth — perfect for paper trading.
- We poll the bulk `/public/get_book_summary_by_currency?kind=option` endpoint every 2s
  for the entire option chain in a single call. That gives us real bid/ask/mark_price
  per strike.
- For implied volatility we hit `/public/ticker` lazily (it's not in the book summary
  response) and cache the result per-instrument for ~30s to stay under rate limits.

Public surface (mirrors KotakProdFeed for drop-in replacement):
    feed = DeribitFeed(env="testnet", currencies=["BTC", "ETH"], poll_interval_sec=2.0)
    feed.start()
    feed.subscribe(["BTC", "ETH", "BTC26DEC25100000CE", ...])
    feed.get_ltp("BTC")
    feed.get_oi_map("BTC")
    feed.get_nearest_expiry("BTC")
    feed.get_atm_strike("BTC")
    feed.stop()

Symbol conventions:
- Deribit API:        BTC-26DEC25-100000-C
- Bot strategy (NSE): BTC26DEC25100000CE
- Bot's Tick.symbol uses the NSE-style so existing strategies work unchanged.
- Tick.exchange = "DERIBIT", Tick.underlying = "BTC" or "ETH".
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timezone
from typing import Callable, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# HTTP helper (matches the style used in kotak_prod_feed.py)
# ---------------------------------------------------------------------------
def _http_get_json(url: str, timeout: int = 10) -> Optional[dict]:
    """GET a JSON URL. Returns parsed dict on 200, None on any error."""
    req = urllib.request.Request(url, headers={"User-Agent": "kotak-neo-bot/deribit-feed"})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        logger.debug(f"DeribitFeed HTTP {e.code} for {url[:120]}: {e.reason}")
        return None
    except Exception as e:
        logger.debug(f"DeribitFeed transport error for {url[:120]}: {e}")
        return None


# ---------------------------------------------------------------------------
# Symbol conversion helpers
# ---------------------------------------------------------------------------
# Deribit:  BTC-26DEC25-100000-C
# Bot:      BTC26DEC25100000CE
_DERIBIT_INST_RE = re.compile(
    r"^(BTC|ETH)-(\d{2}[A-Z]{3}\d{2})-(\d+)-([CP])$"
)
_MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
           'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}


def _deribit_to_bot(deribit_name: str) -> Optional[dict]:
    """Parse Deribit instrument name into bot-side symbol + metadata.

    Returns: {deribit, bot_sym, underlying, strike, opt_type, expiry_iso} or None.
    Example: BTC-26DEC25-100000-C
        → {deribit: 'BTC-26DEC25-100000-C', bot_sym: 'BTC26DEC25100000CE',
           underlying: 'BTC', strike: 100000, opt_type: 'CE', expiry_iso: '2025-12-26'}
    """
    m = _DERIBIT_INST_RE.match(deribit_name)
    if not m:
        return None
    underlying, ddmmyy, strike_s, cp = m.groups()
    dd = ddmmyy[0:2]
    mmm = ddmmyy[2:5]
    yy = ddmmyy[5:7]
    try:
        exp_dt = date(2000 + int(yy), _MONTHS[mmm], int(dd))
    except (KeyError, ValueError):
        return None
    opt_type = "CE" if cp == "C" else "PE"
    bot_sym = f"{underlying}{ddmmyy}{int(strike_s)}{opt_type}"
    return {
        "deribit": deribit_name,
        "bot_sym": bot_sym,
        "underlying": underlying,
        "strike": int(strike_s),
        "opt_type": opt_type,
        "expiry_iso": exp_dt.isoformat(),
    }


def _bot_to_deribit(bot_sym: str) -> Optional[str]:
    """Inverse of _deribit_to_bot. Returns the Deribit instrument name or None."""
    # Pattern: UNDERLYING + DD + MMM + YY + STRIKE + (CE|PE)
    m = re.match(r"^(BTC|ETH)(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$", bot_sym)
    if not m:
        return None
    underlying, dd, mmm, yy, strike, opt = m.groups()
    cp = "C" if opt == "CE" else "P"
    return f"{underlying}-{dd}{mmm}{yy}-{strike}-{cp}"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class DeribitFeed:
    """Polls Deribit public REST API for BTC/ETH spot + option chain.

    No auth required for paper trading. For live trading later, set
    DERIBIT_CLIENT_ID / DERIBIT_CLIENT_SECRET env vars and extend the helper
    to send Authorization headers.
    """

    TESTNET_BASE_URL = "https://test.deribit.com/api/v2"
    PROD_BASE_URL = "https://www.deribit.com/api/v2"

    def __init__(
        self,
        env: str = "testnet",
        currencies: Optional[list[str]] = None,
        poll_interval_sec: float = 2.0,
        max_strikes_per_underlying: int = 9,
        strike_window_pct: float = 0.20,
        iv_cache_ttl_sec: float = 30.0,
    ):
        """Initialize the Deribit feed.

        Args:
            env: 'testnet' or 'prod'. Default 'testnet' (no auth, no real money).
            currencies: list of underlyings to poll, e.g. ['BTC', 'ETH'].
            poll_interval_sec: seconds between bulk polls. Deribit is fine with 2s.
            max_strikes_per_underlying: cap how many strikes we keep per currency
                in the window. The window itself is ±strike_window_pct of spot.
            strike_window_pct: poll only strikes within this fraction of spot
                (e.g. 0.20 = ±20%). Deribit chains run from $1k to $1M; we only
                care about near-the-money strikes for paper trading.
            iv_cache_ttl_sec: how long to cache mark_iv per instrument. The bulk
                summary doesn't include IV; we hit /ticker lazily and cache.
        """
        self.env = "testnet" if env != "prod" else "prod"
        self.base_url = self.TESTNET_BASE_URL if self.env == "testnet" else self.PROD_BASE_URL
        self.currencies = [c.upper() for c in (currencies or ["BTC", "ETH"])]
        self.poll_interval = max(0.5, float(poll_interval_sec))
        self.max_strikes = max(1, int(max_strikes_per_underlying))
        self.strike_window_pct = max(0.05, min(0.5, float(strike_window_pct)))
        self.iv_cache_ttl = max(5.0, float(iv_cache_ttl_sec))

        # shared state
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._subscribed: set[str] = set()  # bot syms (e.g. 'BTC' or 'BTC26DEC25100000CE')
        self._keep_alive: set[str] = set()  # never drop these
        self._latest: dict[str, dict] = {}  # bot_sym → {ltp, bid, ask, oi, vol, iv, ts, ...}
        self._price_history: dict[str, list[float]] = {}
        self._callbacks: list[Callable[[dict], None]] = []
        self._tick_count = 0
        self._error_count = 0
        self._last_successful_poll = 0.0

        # per-currency state
        # spot_usd: latest index price per currency
        # strike_step: typical step between strikes (BTC ~1000, ETH ~100)
        # atm_strike: last-known ATM (used to anchor the window)
        # window_strikes: cached set of strikes in the current window
        # iv_cache: deribit_name → (mark_iv, fetched_at)
        self._spot_usd: dict[str, float] = {}
        self._atm_strike: dict[str, int] = {}
        self._window_strikes: dict[str, set[int]] = {}
        self._iv_cache: dict[str, tuple[float, float]] = {}
        self._last_window_rebuild: dict[str, float] = {}
        self._instrument_cache: dict[str, list[dict]] = {}  # currency → list of instrument dicts

    # --------------- public API ---------------
    def start(self) -> None:
        """Begin background polling. Idempotent."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._poll_loop, name="deribit-feed", daemon=True)
            self._thread.start()
            logger.info(
                f"DeribitFeed started (env={self.env}, base={self.base_url}, "
                f"currencies={self.currencies}, poll={self.poll_interval}s, "
                f"window=±{self.strike_window_pct*100:.0f}%)"
            )

    def stop(self) -> None:
        """Stop the poll thread. Idempotent."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("DeribitFeed stopped")

    def subscribe(self, instruments: list[str]) -> None:
        """Subscribe to spot ('BTC' / 'ETH') or full bot option syms."""
        with self._lock:
            for s in instruments:
                if s and s not in self._subscribed:
                    self._subscribed.add(s)
            logger.debug(f"DeribitFeed subscribe: {instruments} (total {len(self._subscribed)})")

    def keep_alive_subscribe(self, instruments: list[str]) -> None:
        """Pin instruments to permanent subscription (for strikes with open orders)."""
        with self._lock:
            for s in instruments:
                if not s:
                    continue
                self._keep_alive.add(s)
                self._subscribed.add(s)
            logger.debug(
                f"DeribitFeed keep_alive: {instruments} (keep_alive total {len(self._keep_alive)})"
            )

    def on_tick(self, callback: Callable[[dict], None]) -> None:
        """Register a callback fired on every emitted tick. Tick is a dict."""
        self._callbacks.append(callback)

    def get_ltp(self, symbol: str) -> float:
        """Get the latest LTP for `symbol` (bot sym format). Returns 0.0 if unknown."""
        with self._lock:
            t = self._latest.get(symbol)
            return float(t.get("ltp", 0.0)) if t else 0.0

    def get_latest(self, symbol: str) -> Optional[dict]:
        """Return the latest tick dict for `symbol` (or None)."""
        with self._lock:
            t = self._latest.get(symbol)
            return dict(t) if t else None

    def get_price_history(self, symbol: str) -> list[float]:
        """Return a copy of the LTP history for `symbol` (oldest first)."""
        with self._lock:
            return list(self._price_history.get(symbol, []))

    def get_momentum(self, symbol: str, window: int = 20) -> float:
        """Return fractional momentum (last - first) / first over the recent window."""
        with self._lock:
            hist = self._price_history.get(symbol, [])
            if len(hist) < 5:
                return 0.0
            recent = hist[-window:] if len(hist) >= window else hist
            if not recent or recent[0] <= 0:
                return 0.0
            return (recent[-1] - recent[0]) / recent[0]

    def get_oi_map(self, currency: str) -> dict:
        """Return {strike: {ce_oi, pe_oi, ce_ltp, pe_ltp, ce_iv, pe_iv,
                            ce_bid, ce_ask, pe_bid, pe_ask}} for `currency`.

        Used by OI heatmap / max-pain / GEX analytics.
        """
        currency = currency.upper()
        out: dict[int, dict] = {}
        with self._lock:
            for sym, t in self._latest.items():
                if not sym.startswith(currency):
                    continue
                if not (sym.endswith("CE") or sym.endswith("PE")):
                    continue
                # bot_sym format: BTC26DEC25100000CE
                # underlying(3) + dd(2) + mmm(3) + yy(2) + strike + CE/PE
                # strip 7 chars of expiry + 3 chars of underlying prefix
                rest = sym[len(currency):]
                if len(rest) < 10:
                    continue
                opt = rest[-2:]
                strike_s = rest[7:-2]
                try:
                    strike = int(strike_s)
                except ValueError:
                    continue
                rec = out.setdefault(strike, {
                    "ce_oi": 0, "pe_oi": 0,
                    "ce_ltp": 0.0, "pe_ltp": 0.0,
                    "ce_iv": 0.0, "pe_iv": 0.0,
                    "ce_bid": 0.0, "ce_ask": 0.0,
                    "pe_bid": 0.0, "pe_ask": 0.0,
                })
                key = "ce" if opt == "CE" else "pe"
                rec[f"{key}_oi"] = int(t.get("oi", 0) or 0)
                rec[f"{key}_ltp"] = float(t.get("ltp", 0.0) or 0.0)
                rec[f"{key}_iv"] = float(t.get("iv", 0.0) or 0.0)
                rec[f"{key}_bid"] = float(t.get("bid", 0.0) or 0.0)
                rec[f"{key}_ask"] = float(t.get("ask", 0.0) or 0.0)
        return out

    def get_nearest_expiry(self, currency: str) -> str:
        """Return the nearest future expiry as a bot-style DDMMMYY string (e.g. '26DEC25').

        Falls back to the nearest available expiry in the chain (could be past-today
        if today's already expired on testnet). Returns '' if no data yet.
        """
        currency = currency.upper()
        with self._lock:
            insts = self._instrument_cache.get(currency, [])
        if not insts:
            return ""
        today_ms = int(time.time() * 1000)
        future = [i for i in insts if int(i.get("expiration_timestamp", 0)) >= today_ms]
        if not future:
            future = insts  # fall back to all
        # Sort by expiration timestamp ascending, return the bot-style ddmmmyy string
        nearest = min(future, key=lambda x: int(x.get("expiration_timestamp", 0)))
        # Deribit instrument name: 'BTC-26DEC25-100000-C' — parse the ddmmmyy out
        m = re.match(r"^[A-Z]+-(\d{2}[A-Z]{3}\d{2})-", nearest["instrument_name"])
        if not m:
            return ""
        return m.group(1)

    def get_atm_strike(self, currency: str) -> int:
        """Return the last-known ATM strike for `currency` (rounded to typical step).

        Returns 0 if no spot price seen yet.
        """
        currency = currency.upper()
        with self._lock:
            spot = self._spot_usd.get(currency, 0.0)
            step = 1000.0 if currency == "BTC" else 100.0  # reasonable defaults
        if spot <= 0:
            return 0
        return int(round(spot / step) * step)

    def is_connected(self) -> bool:
        """We don't have a persistent connection — say connected if we've polled recently."""
        return (time.time() - self._last_successful_poll) < (self.poll_interval * 5 + 5)

    # --------------- internals ---------------
    def _poll_loop(self) -> None:
        """Background thread: poll spot + book summary for each currency, every poll_interval."""
        while self._running:
            try:
                ok_any = False
                for ccy in self.currencies:
                    if self._poll_one_currency(ccy):
                        ok_any = True
                if ok_any:
                    self._last_successful_poll = time.time()
            except Exception as e:
                logger.exception(f"DeribitFeed poll error: {e}")
                self._error_count += 1
            # Re-add keep-alive strikes each cycle in case they were pruned
            with self._lock:
                for s in self._keep_alive:
                    self._subscribed.add(s)
            time.sleep(self.poll_interval)

    def _poll_one_currency(self, currency: str) -> bool:
        """Poll spot + book summary for one currency. Returns True on any successful fetch."""
        ok = False
        # 1) spot index price
        spot = self._fetch_index_price(currency)
        if spot is not None and spot > 0:
            ok = True
            self._update_spot(currency, spot)
        # 2) full option book summary
        summary = self._fetch_book_summary(currency)
        if summary is not None:
            ok = True
            self._update_book_summary(currency, summary)
        return ok

    def _fetch_index_price(self, currency: str) -> Optional[float]:
        """GET /public/get_index_price?index_name={ccy}_usd"""
        idx = f"{currency.lower()}_usd"
        url = f"{self.base_url}/public/get_index_price?index_name={idx}"
        data = _http_get_json(url, timeout=8)
        if not data or "result" not in data:
            return None
        try:
            return float(data["result"].get("index_price", 0.0))
        except (TypeError, ValueError):
            return None

    def _fetch_book_summary(self, currency: str) -> Optional[list[dict]]:
        """GET /public/get_book_summary_by_currency?currency={ccy}&kind=option"""
        url = (
            f"{self.base_url}/public/get_book_summary_by_currency"
            f"?currency={currency}&kind=option"
        )
        data = _http_get_json(url, timeout=10)
        if not data or "result" not in data:
            return None
        result = data["result"]
        if not isinstance(result, list):
            return None
        # Refresh instrument cache opportunistically (cheap, no extra call needed
        # since the summary already contains instrument_name, mark_iv, open_interest).
        # We refresh a minimal "instrument" view by also calling /public/get_instruments
        # on a slower schedule (every 5 minutes).
        if (not self._instrument_cache.get(currency)
                or time.time() - self._last_window_rebuild.get(currency, 0) > 300):
            self._refresh_instrument_cache(currency)
        return result

    def _refresh_instrument_cache(self, currency: str) -> None:
        """Fetch and cache the live instrument list for `currency`.

        Cached for 5 minutes; expiry timestamps rarely change inside a session.
        """
        url = (
            f"{self.base_url}/public/get_instruments"
            f"?currency={currency}&kind=option&expired=false"
        )
        data = _http_get_json(url, timeout=10)
        if data and "result" in data and isinstance(data["result"], list):
            with self._lock:
                self._instrument_cache[currency] = data["result"]
            self._last_window_rebuild[currency] = time.time()
            logger.info(
                f"DeribitFeed: cached {len(data['result'])} live {currency} option instruments"
            )

    def _update_spot(self, currency: str, price: float) -> None:
        """Emit a spot tick and update internal spot tracker."""
        if price <= 0:
            return
        with self._lock:
            self._spot_usd[currency] = price
            t = {
                "symbol": currency,
                "ltp": price,
                "bid": price,
                "ask": price,
                "oi": 0,
                "volume": 0,
                "iv": 0.0,
                "ts": time.time(),
            }
            self._latest[currency] = t
            hist = self._price_history.setdefault(currency, [])
            hist.append(price)
            if len(hist) > 600:
                hist[:] = hist[-600:]
        self._dispatch(t)

    def _update_book_summary(self, currency: str, summary: list[dict]) -> None:
        """Filter the bulk summary to our window and emit ticks for each strike."""
        with self._lock:
            spot = self._spot_usd.get(currency, 0.0)
            if spot <= 0:
                # No spot yet — can't define a window. Skip this cycle.
                return
            step = 1000.0 if currency == "BTC" else 100.0
            atm = int(round(spot / step) * step)
            self._atm_strike[currency] = atm
            lo = atm * (1.0 - self.strike_window_pct)
            hi = atm * (1.0 + self.strike_window_pct)
        # Rebuild window set on first poll or if spot has drifted > 5% from last anchor
        with self._lock:
            last_rebuild_at = self._last_window_rebuild.get(currency, 0.0)
            need_rebuild = (currency not in self._window_strikes
                            or (time.time() - last_rebuild_at) > 300
                            or abs(spot - atm) / max(atm, 1) > 0.05)
        if need_rebuild:
            self._rebuild_window(currency, lo, hi)
        # Filter summary to instruments in the window for this currency
        emitted = 0
        for entry in summary:
            name = entry.get("instrument_name", "")
            if not name.startswith(currency + "-"):
                continue
            parsed = _deribit_to_bot(name)
            if not parsed:
                continue
            # Only emit if strike is in the current window OR explicitly subscribed/keep-alive
            strike = parsed["strike"]
            bot_sym = parsed["bot_sym"]
            with self._lock:
                in_window = strike in self._window_strikes.get(currency, set())
                subscribed = (bot_sym in self._subscribed or bot_sym in self._keep_alive
                              or currency in self._subscribed)
            if not (in_window or subscribed):
                continue
            ltp = float(entry.get("mark_price") or 0.0)
            if ltp <= 0:
                # last_price as a fallback so we still emit something for subscribed strikes
                ltp = float(entry.get("last") or 0.0)
            if ltp <= 0:
                continue
            bid = float(entry.get("bid_price") or 0.0) or 0.0
            ask = float(entry.get("ask_price") or 0.0) or 0.0
            # If we don't have bid/ask in the bulk summary, derive a tiny spread
            if (bid <= 0 or ask <= 0) and ltp > 0:
                # Deribit on testnet sometimes has None for thin books.
                # Use a 1% synthetic spread (best-effort).
                half = max(ltp * 0.005, 0.0001)
                bid = bid if bid > 0 else max(ltp - half, 0.0)
                ask = ask if ask > 0 else ltp + half
            oi = int(float(entry.get("open_interest") or 0))
            vol = int(float(entry.get("volume") or 0))
            # mark_iv is in PERCENT (e.g. 43.79 = 43.79%). Convert to decimal.
            mark_iv_pct = float(entry.get("mark_iv") or 0.0)
            iv = mark_iv_pct / 100.0 if mark_iv_pct > 0 else 0.0
            # If mark_iv is missing in the bulk summary (None), try the cache.
            # Bulk summary usually DOES include mark_iv; this is just a safety net.
            if iv <= 0:
                cached = self._iv_cache.get(name)
                if cached:
                    cached_iv, fetched_at = cached
                    if (time.time() - fetched_at) < self.iv_cache_ttl:
                        iv = cached_iv
            self._update_tick(
                bot_sym=bot_sym,
                ltp=ltp, bid=bid, ask=ask,
                oi=oi, volume=vol, iv=iv,
                underlying=currency,
                strike=strike,
                opt_type=parsed["opt_type"],
                expiry=parsed["expiry_iso"],
                deribit_name=name,
            )
            emitted += 1
        if emitted:
            logger.debug(f"DeribitFeed[{currency}]: emitted {emitted} ticks (spot={spot:.2f} atm={atm})")

    def _rebuild_window(self, currency: str, lo: float, hi: float) -> None:
        """Build the set of strikes in the [lo, hi] window for `currency`."""
        with self._lock:
            insts = self._instrument_cache.get(currency, [])
        strikes: set[int] = set()
        for inst in insts:
            name = inst.get("instrument_name", "")
            if not name.startswith(currency + "-"):
                continue
            parsed = _deribit_to_bot(name)
            if not parsed:
                continue
            k = parsed["strike"]
            if lo <= k <= hi:
                strikes.add(k)
        with self._lock:
            self._window_strikes[currency] = strikes
            self._last_window_rebuild[currency] = time.time()
        logger.info(
            f"DeribitFeed[{currency}]: strike window [{lo:.0f}, {hi:.0f}] "
            f"contains {len(strikes)} strikes"
        )

    def _update_tick(
        self,
        bot_sym: str,
        ltp: float,
        bid: float,
        ask: float,
        oi: int,
        volume: int,
        iv: float,
        underlying: str,
        strike: int,
        opt_type: str,
        expiry: str,
        deribit_name: str,
    ) -> None:
        """Store a tick and fire callbacks. The tick dict matches KotakProdFeed's shape,
        plus the new `iv` field."""
        t = {
            "symbol": bot_sym,
            "ltp": ltp,
            "bid": bid,
            "ask": ask,
            "oi": oi,
            "volume": volume,
            "iv": iv,
            "ts": time.time(),
            "underlying": underlying,
            "strike": strike,
            "option_type": opt_type,
            "expiry": expiry,
            "exchange": "DERIBIT",
            "deribit_name": deribit_name,
        }
        with self._lock:
            self._latest[bot_sym] = t
            hist = self._price_history.setdefault(bot_sym, [])
            hist.append(ltp)
            if len(hist) > 600:
                hist[:] = hist[-600:]
            # Cache IV in deribit-name form so /ticker hits can be cross-checked
            if iv > 0:
                self._iv_cache[deribit_name] = (iv, time.time())
            self._tick_count += 1
        self._dispatch(t)

    def _dispatch(self, t: dict) -> None:
        """Fire all registered callbacks. Errors are swallowed per-callback."""
        for cb in list(self._callbacks):
            try:
                cb(t)
            except Exception as e:
                logger.debug(f"DeribitFeed callback error: {e}")


# ---------------------------------------------------------------------------
# Standalone smoke test (only runs when executed directly)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    print("DeribitFeed smoke test — listens for 8s, then exits")
    feed = DeribitFeed(env="testnet", currencies=["BTC"], poll_interval_sec=2.0)
    ticks: list[dict] = []
    feed.on_tick(lambda t: ticks.append(t))
    feed.start()
    feed.subscribe(["BTC"])
    time.sleep(8)
    feed.stop()
    print(f"Received {len(ticks)} ticks")
    if ticks:
        print(f"Sample: {ticks[0]}")
    sys.exit(0 if len(ticks) > 0 else 1)
