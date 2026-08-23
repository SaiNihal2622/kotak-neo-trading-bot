"""Kotak Neo PROD feed — real NSE market data via the official REST quotes API.

Why this exists:
- The Kotak Neo UAT environment has no real market data (quotes() returns empty).
- The official NEO WebSocket is the standard real-time channel, but PROD auth requires a
  working dev portal (napi.kotaksecurities.com/devportal) which is often down.
- We discovered that the UAT access token (a UUID-style string) actually authenticates against
  PROD login as well — same endpoint, same Authorization header. So we can use the UAT
  access token to hit PROD baseUrl for quotes + scrip master.
- This feed polls the PROD quotes REST endpoint every N seconds. It is not as fast as the
  websocket (1-2s latency instead of ms) but it's stable, official, and gives us real
  bid/ask depth, ltp, oi, and OHLC.

Public surface:
    feed = KotakProdFeed(env="uat", access_token="...", mobile=..., ucc=..., totp_secret=..., mpin=...)
    feed.start()
    feed.subscribe(["NIFTY", "BANKNIFTY", "NIFTY11AUG2624500CE", ...])
    feed.get_ltp("NIFTY")
    feed.get_latest("NIFTY11AUG2624500CE")
    feed.get_oi_map("NIFTY")
    feed.get_momentum("NIFTY")
    feed.stop()

Persistence:
    On every successful auth, we save {base_url, view_token, trade_token, sid, expires_at}
    to data_cache/kotak_prod_session.json. On startup, we try to reuse the cached session
    first; only re-auth if the token has expired or the cached session 401s.
"""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import hmac
import json
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Callable, Optional

from loguru import logger


# ---------------------------------------------------------------------------
# TOTP helpers
# ---------------------------------------------------------------------------
def _hotp(secret_bytes: bytes, counter: int) -> str:
    h = hmac.new(secret_bytes, struct.pack('>Q', counter), hashlib.sha1).digest()
    o = h[h[19] & 15] & 0x7f
    o = (o << 24) | ((h[(h[19] & 15) + 1] & 0xff) << 16) | (
        (h[(h[19] & 15) + 2] & 0xff) << 8) | (h[(h[19] & 15) + 3] & 0xff)
    return str(o % 1000000).zfill(6)


def _totp(secret_b32: str) -> str:
    s = secret_b32.upper().replace(' ', '')
    while len(s) % 8:
        s += '='
    return _hotp(base64.b32decode(s), int(time.time() // 30))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _http_post(url: str, body: dict, headers: dict, timeout: int = 15) -> tuple[int, dict | str]:
    data = json.dumps(body).encode()
    h = {**headers, 'Content-Type': 'application/json'}
    req = urllib.request.Request(url, data=data, headers=h, method='POST')
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or '{}')
        except Exception:
            return e.code, e.read().decode(errors='ignore')


def _http_get(url: str, headers: dict, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors='ignore')


# ---------------------------------------------------------------------------
# Scrip master parser
# ---------------------------------------------------------------------------
_MONTHS = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
           'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}


def _parse_scrip_ref(ref: str) -> Optional[dict]:
    """Parse pScripRefKey like 'NIFTY11AUG2624600.00CE' → {date, strike, opt, sym}."""
    m = re.match(r'^(NIFTY|BANKNIFTY)(\d{2})([A-Z]{3})(\d{2})(\d+)\.00(CE|PE)$', ref)
    if not m:
        return None
    sym, dd, mm, yy, strike, opt = m.groups()
    return {
        'sym': sym,
        'date': date(2000 + int(yy), _MONTHS[mm], int(dd)),
        'strike': int(float(strike)),
        'opt': opt,
    }


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
@dataclass
class KotakSession:
    base_url: str
    view_token: str
    view_sid: str
    trade_token: str
    trade_sid: str
    access_token: str
    authed_at: float
    expires_at: float = field(default_factory=lambda: time.time() + 6 * 3600)

    def save(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({
            'base_url': self.base_url,
            'view_token': self.view_token,
            'view_sid': self.view_sid,
            'trade_token': self.trade_token,
            'trade_sid': self.trade_sid,
            'access_token': self.access_token,
            'authed_at': self.authed_at,
            'expires_at': self.expires_at,
        }, indent=2))

    @classmethod
    def load(cls, path: str) -> Optional['KotakSession']:
        p = Path(path)
        if not p.exists():
            return None
        try:
            j = json.loads(p.read_text())
        except Exception:
            return None
        # Refresh if within 30 min of expiry
        if j.get('expires_at', 0) < time.time() + 1800:
            return None
        return cls(**j)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class KotakProdFeed:
    """Polls Kotak Neo PROD quotes REST API for NIFTY/BANKNIFTY spot + option chain."""

    PROD_BASE_URL = "https://e22.kotaksecurities.com"
    SCRIP_MASTER_FILE = "data_cache/nse_fo.csv"
    SESSION_FILE = "data_cache/kotak_prod_session.json"

    def __init__(self, env: str = "uat", access_token: str = "", mobile: str = "",
                 ucc: str = "", totp_secret: str = "", mpin: str = "",
                 poll_interval_sec: float = 2.0, max_strikes_per_underlying: int = 9):
        self.env = env
        self.access_token = access_token
        self.mobile = mobile
        self.ucc = ucc
        self.totp_secret = totp_secret
        self.mpin = mpin
        self.poll_interval = poll_interval_sec
        self.max_strikes = max_strikes_per_underlying

        self.session: Optional[KotakSession] = None
        self._scrip_rows: list[dict] = []
        self._pSymbol_to_meta: dict[str, dict] = {}  # pSymbol → {trdSym, strike, opt, exp, sym, lot}
        self._trdSym_to_pSymbol: dict[str, str] = {}  # pTrdSymbol (e.g. NIFTY2681124600CE) → pSymbol
        self._strategySym_to_pSymbol: dict[str, str] = {}  # strategy format (e.g. NIFTY11AUG2624600CE) → pSymbol
        self._subscribed: set[str] = set()  # either 'NIFTY' or 'BANKNIFTY' (spot) or full trdSym
        self._keep_alive: set[str] = set()  # strikes with open paper orders — never drop
        self._latest: dict[str, dict] = {}  # symbol → {ltp, bid, ask, oi, vol, ts}
        self._price_history: dict[str, list[float]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_auth_attempt = 0.0
        self._auth_fail_count = 0
        self._callbacks: list[Callable[[dict], None]] = []

    # --------------- public API ---------------
    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            # Load or create session
            self.session = KotakSession.load(self.SESSION_FILE)
            if not self.session or self.session.access_token != self.access_token:
                logger.info("KotakProdFeed: no cached session, authenticating fresh")
                if not self._auth():
                    logger.error("KotakProdFeed: initial auth failed, will retry in background")
            else:
                logger.info(f"KotakProdFeed: reusing cached session (baseUrl={self.session.base_url}, "
                            f"expires in {int((self.session.expires_at - time.time()) / 60)} min)")
            # Load scrip master
            self._load_scrip_master()
            self._running = True
            self._thread = threading.Thread(target=self._poll_loop, name="kotak-prod-feed", daemon=True)
            self._thread.start()
            logger.info(f"KotakProdFeed started (env={self.env}, poll={self.poll_interval}s, "
                        f"subscribed={len(self._subscribed)})")

    def stop(self) -> None:
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def subscribe(self, symbols: list[str]) -> None:
        with self._lock:
            for s in symbols:
                if s and s not in self._subscribed:
                    self._subscribed.add(s)
            logger.debug(f"KotakProdFeed subscribe: {symbols} (total {len(self._subscribed)})")

    def keep_alive_subscribe(self, symbols: list[str]) -> None:
        """Pin a symbol to permanent subscription. Used for strikes with open paper orders,
        so the poll loop never drops them even if the strategy rotates ATM strikes.
        These are added to _subscribed AND to a separate _keep_alive set so they
        survive any external pruning of _subscribed."""
        with self._lock:
            for s in symbols:
                if not s:
                    continue
                self._keep_alive.add(s)
                self._subscribed.add(s)
            logger.debug(f"KotakProdFeed keep_alive: {symbols} (keep_alive total {len(self._keep_alive)})")

    def clear_keep_alive(self) -> None:
        """Remove all keep-alive pins (e.g. when starting fresh day)."""
        with self._lock:
            self._keep_alive.clear()

    def on_tick(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    def get_ltp(self, symbol: str) -> float:
        with self._lock:
            t = self._latest.get(symbol)
            return t.get('ltp', 0.0) if t else 0.0

    def get_latest(self, symbol: str) -> Optional[dict]:
        with self._lock:
            t = self._latest.get(symbol)
            return dict(t) if t else None

    def get_price_history(self, symbol: str) -> list[float]:
        with self._lock:
            return list(self._price_history.get(symbol, []))

    def get_momentum(self, symbol: str, window: int = 20) -> float:
        with self._lock:
            hist = self._price_history.get(symbol, [])
            if len(hist) < 5:
                return 0.0
            recent = hist[-window:] if len(hist) >= window else hist
            if not recent or recent[0] <= 0:
                return 0.0
            return (recent[-1] - recent[0]) / recent[0]

    def get_oi_map(self, underlying: str) -> dict:
        """Return {strike: {ce_oi, pe_oi, ce_ltp, pe_ltp}} for OI heatmap."""
        with self._lock:
            result = {}
            for sym, t in self._latest.items():
                if not sym.startswith(underlying):
                    continue
                if not (sym.endswith('CE') or sym.endswith('PE')):
                    continue
                # find strike from meta
                meta = self._trdSym_to_pSymbol.get(sym)
                if not meta:
                    # try via reverse lookup
                    for trd, ps in self._trdSym_to_pSymbol.items():
                        if trd == sym:
                            meta = self._pSymbol_to_meta.get(ps)
                            break
                if not meta:
                    continue
                m = self._pSymbol_to_meta.get(meta) if isinstance(meta, str) else meta
                # The meta for this sym:
                ps = self._trdSym_to_pSymbol.get(sym)
                if not ps:
                    continue
                row_meta = self._pSymbol_to_meta.get(ps)
                if not row_meta:
                    continue
                strike = row_meta['strike']
                opt = row_meta['opt']
                rec = result.setdefault(strike, {})
                key = 'ce' if opt == 'CE' else 'pe'
                rec[f'{key}_oi'] = t.get('oi', 0)
                rec[f'{key}_ltp'] = t.get('ltp', 0.0)
            return result

    def get_subscribed_pSymbols(self) -> list[str]:
        """Return the pSymbols we should query, derived from subscribed trdSyms."""
        with self._lock:
            psyms = []
            for s in self._subscribed:
                if s in ('NIFTY', 'BANKNIFTY'):
                    continue
                # Try pTrdSymbol first, then strategy-format
                ps = self._trdSym_to_pSymbol.get(s) or self._strategySym_to_pSymbol.get(s)
                if ps:
                    psyms.append(ps)
            return psyms

    def get_pSymbol(self, symbol: str) -> Optional[str]:
        """Resolve any supported symbol format to its pSymbol."""
        with self._lock:
            return self._trdSym_to_pSymbol.get(symbol) or self._strategySym_to_pSymbol.get(symbol)

    def get_nearest_expiry(self, underlying: str, today: Optional[date] = None) -> Optional[date]:
        """Return the nearest future (or today's) expiry date for `underlying`.

        NSE weekly expiries as of 2024+:
            - NIFTY: every Monday
            - BANKNIFTY: every Wednesday
            - FINNIFTY: every Tuesday
            - MIDCPNIFTY: every Monday

        If today is an expiry day, returns today. Otherwise returns the next one.
        Uses the loaded scrip master — if no rows for `underlying`, returns None.

        Returns a `date` (not a string). Use `format_expiry_str(underlying, exp)` to get
        the strategy-compatible string `NIFTY01SEP26` (used to build option symbols).
        """
        with self._lock:
            today = today or date.today()
            expiries = sorted({m['exp'] for m in self._pSymbol_to_meta.values() if m['sym'] == underlying and m['exp'] >= today})
            if not expiries:
                return None
            return expiries[0]

    def format_expiry_str(self, underlying: str, exp: date) -> str:
        """Format an expiry as the strategy's symbol suffix, e.g. '01SEP26'."""
        return exp.strftime("%d%b%y").upper()

    def get_strategy_sym(self, underlying: str, strike: int, opt_type: str, exp: Optional[date] = None) -> Optional[str]:
        """Build the canonical strategy sym for a (underlying, strike, opt_type, expiry).

        Returns None if no matching contract in scrip master.
        """
        with self._lock:
            if exp is None:
                exp = self.get_nearest_expiry(underlying)
                if not exp:
                    return None
            exp_str = self.format_expiry_str(underlying, exp)
            # pScripRefKey format: NIFTY{DD}{MMM}{YY}{STRIKE}.00{CE|PE}
            ref = f"{underlying}{exp.strftime('%d%b%y').upper()}{int(strike)}.00{opt_type}"
            ps = self._trdSym_to_pSymbol.get(ref)  # probably not — pTrdSymbol doesn't have day name
            # Try via meta lookup
            for s, p in self._strategySym_to_pSymbol.items():
                m = self._pSymbol_to_meta[p]
                if m['sym'] == underlying and m['strike'] == strike and m['opt'] == opt_type and m['exp'] == exp:
                    return s
            return None

    def is_authenticated(self) -> bool:
        return self.session is not None

    # --------------- internals ---------------
    def _auth(self) -> bool:
        """TOTP login + MPIN validate. Returns True on success."""
        if not all([self.access_token, self.mobile, self.ucc, self.totp_secret, self.mpin]):
            logger.error("KotakProdFeed: missing auth credentials")
            return False
        # 1) TOTP
        t = _totp(self.totp_secret)
        code, body = _http_post(
            'https://mis.kotaksecurities.com/login/1.0/tradeApiLogin',
            {'mobileNumber': self.mobile, 'ucc': self.ucc, 'totp': t},
            {'Authorization': self.access_token, 'neo-fin-key': 'neotradeapi'},
        )
        if code != 200 or not isinstance(body, dict) or 'data' not in body:
            logger.error(f"KotakProdFeed TOTP login failed: HTTP {code} body={body}")
            return False
        view_token = body['data']['token']
        view_sid = body['data']['sid']
        logger.info("KotakProdFeed: TOTP login OK")
        # 2) MPIN validate
        code, body = _http_post(
            'https://mis.kotaksecurities.com/login/1.0/tradeApiValidate',
            {'mpin': self.mpin},
            {
                'Authorization': self.access_token,
                'neo-fin-key': 'neotradeapi',
                'sid': view_sid,
                'Auth': view_token,
            },
        )
        if code != 200 or not isinstance(body, dict) or 'data' not in body:
            logger.error(f"KotakProdFeed MPIN validate failed: HTTP {code} body={body}")
            return False
        base_url = body['data'].get('baseUrl') or self.PROD_BASE_URL
        self.session = KotakSession(
            base_url=base_url,
            view_token=view_token,
            view_sid=view_sid,
            trade_token=body['data']['token'],
            trade_sid=body['data']['sid'],
            access_token=self.access_token,
            authed_at=time.time(),
        )
        self.session.save(self.SESSION_FILE)
        logger.info(f"KotakProdFeed: auth OK, baseUrl={base_url}")
        return True

    def _reauth_if_needed(self) -> bool:
        """Re-auth if no session or session is about to expire."""
        if self.session is None:
            return self._auth()
        if self.session.expires_at < time.time() + 600:
            logger.info("KotakProdFeed: session expiring soon, refreshing")
            return self._auth()
        return True

    def _load_scrip_master(self) -> None:
        """Download (or load cached) PROD nse_fo scrip master; build pSymbol maps."""
        csv_path = Path(self.SCRIP_MASTER_FILE)
        need_download = True
        if csv_path.exists():
            age_hours = (time.time() - csv_path.stat().st_mtime) / 3600
            if age_hours < 18:  # scrip master refreshes daily
                need_download = False
                logger.info(f"KotakProdFeed: using cached scrip master (age {age_hours:.1f}h)")
        if need_download:
            if not self._reauth_if_needed():
                logger.error("KotakProdFeed: cannot download scrip master — not authed")
                return
            ok = self._download_scrip_master()
            if not ok:
                logger.warning("KotakProdFeed: scrip master download failed, using whatever is cached")
        # Parse
        if not csv_path.exists():
            logger.error("KotakProdFeed: no scrip master file available")
            return
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            self._scrip_rows = list(csv.DictReader(f))
        # Build pSymbol maps.
        # We keep historical rows in the map; the today-filter happens in
        # get_nearest_expiry() (and other query methods) so tests can drive
        # time without reloading the scrip master.
        for r in self._scrip_rows:
            ref = r.get('pScripRefKey', '').strip()
            p = _parse_scrip_ref(ref)
            if not p:
                continue
            if p['sym'] not in ('NIFTY', 'BANKNIFTY'):
                continue
            ps = r.get('pSymbol', '').strip()
            trd = r.get('pTrdSymbol', '').strip()
            lot = int(r.get('lLotSize', '0').strip() or 0)
            if not ps or not trd:
                continue
            meta = {
                'pSymbol': ps,
                'trdSym': trd,
                'sym': p['sym'],
                'strike': p['strike'],
                'opt': p['opt'],
                'exp': p['date'],
                'lot': lot,
            }
            self._pSymbol_to_meta[ps] = meta
            self._trdSym_to_pSymbol[trd] = ps
            # Build the strategy-format lookup (e.g. 'NIFTY11AUG2624600CE' without '.00')
            # from pScripRefKey 'NIFTY11AUG2624600.00CE'.
            ref_clean = re.sub(r'\.00(CE|PE)$', r'\1', ref)
            self._strategySym_to_pSymbol[ref_clean] = ps
        logger.info(f"KotakProdFeed: scrip master loaded — {len(self._pSymbol_to_meta)} active NIFTY/BN options "
                    f"({len(self._strategySym_to_pSymbol)} strategy symbols mapped)")

    def _download_scrip_master(self) -> bool:
        url = f"{self.session.base_url}/script-details/1.0/masterscrip/file-paths"
        code, body = _http_get(url, {'Authorization': self.access_token})
        if code != 200:
            logger.error(f"KotakProdFeed: masterscrip/file-paths HTTP {code}: {body[:200]}")
            return False
        try:
            files = json.loads(body)['data']['filesPaths']
        except Exception as e:
            logger.error(f"KotakProdFeed: parse file-paths: {e}")
            return False
        nse_fo_url = next((f for f in files if 'nse_fo' in f and not f.endswith('-v1.csv')), None)
        if not nse_fo_url:
            logger.error("KotakProdFeed: no nse_fo.csv in file-paths response")
            return False
        try:
            req = urllib.request.Request(nse_fo_url, headers={'User-Agent': 'curl/8.0', 'Accept-Encoding': 'gzip'})
            r = urllib.request.urlopen(req, timeout=120)
            data = r.read()
            if data[:2] == b'\x1f\x8b':
                data = gzip.decompress(data)
            csv_path = Path(self.SCRIP_MASTER_FILE)
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_bytes(data)
            logger.info(f"KotakProdFeed: scrip master downloaded ({len(data)} bytes)")
            return True
        except Exception as e:
            logger.error(f"KotakProdFeed: scrip master download error: {e}")
            return False

    def _poll_loop(self) -> None:
        """Background thread: poll PROD quotes for subscribed symbols."""
        while self._running:
            try:
                if not self._reauth_if_needed():
                    time.sleep(self.poll_interval * 5)
                    continue
                # Re-add keep-alive strikes each cycle in case they were pruned.
                with self._lock:
                    for s in self._keep_alive:
                        self._subscribed.add(s)
                # 1) Fetch option quotes if any subscribed
                psyms = self.get_subscribed_pSymbols()
                if psyms:
                    self._fetch_option_quotes(psyms)
                # 2) Fetch spot quotes if NIFTY/BANKNIFTY subscribed
                spot_q = []
                with self._lock:
                    if 'NIFTY' in self._subscribed:
                        spot_q.append('nse_cm|Nifty 50')
                    if 'BANKNIFTY' in self._subscribed:
                        spot_q.append('nse_cm|Nifty Bank')
                if spot_q:
                    self._fetch_spot_quotes(spot_q)
            except Exception as e:
                logger.exception(f"KotakProdFeed poll error: {e}")
            time.sleep(self.poll_interval)

    def _fetch_option_quotes(self, psyms: list[str]) -> None:
        # Kotak allows comma-separated queries in one request
        queries = [f'nse_fo|{p}' for p in psyms]
        encoded = ','.join(urllib.parse.quote(q, safe='') for q in queries)
        url = f"{self.session.base_url}/script-details/1.0/quotes/neosymbol/{encoded}/all"
        code, body = _http_get(url, {'Authorization': self.access_token})
        if code == 401:
            logger.warning("KotakProdFeed: 401 on quotes, will re-auth next cycle")
            self.session = None  # force re-auth
            return
        if code != 200:
            logger.warning(f"KotakProdFeed: quotes HTTP {code} body={body[:200]}")
            return
        try:
            quotes = json.loads(body)
        except Exception as e:
            logger.warning(f"KotakProdFeed: parse quotes: {e}")
            return
        for q in quotes:
            ps = q.get('exchange_token', '')
            meta = self._pSymbol_to_meta.get(ps)
            if not meta:
                continue
            trd = meta['trdSym']
            # Find any subscribed strategy symbol for this pSymbol (for key compat)
            strat_sym = trd
            for s, ps2 in self._strategySym_to_pSymbol.items():
                if ps2 == ps and s in self._subscribed:
                    strat_sym = s
                    break
            d = q.get('depth', {}) or {}
            bids = d.get('buy', []) or []
            asks = d.get('sell', []) or []
            bid = float(bids[0]['price']) if bids and bids[0]['price'] not in ('0', '0.00', 0, '0.0') else 0.0
            ask = float(asks[0]['price']) if asks and asks[0]['price'] not in ('0', '0.00', 0, '0.0') else 0.0
            ltp = float(q.get('ltp', 0) or 0)
            # OI / volume sometimes come as '-' (Kotak's not-available placeholder).
            # Robust parse: if it's a valid number, use it; otherwise 0.
            def _safe_num(v, default=0.0, as_int=False):
                if v in (None, '', '-', '--', 'NA', 'N/A'):
                    return default if not as_int else 0
                try:
                    out = float(v)
                    return int(out) if as_int else out
                except (ValueError, TypeError):
                    return default if not as_int else 0
            oi = _safe_num(q.get('oi'), 0.0, as_int=True)
            vol = _safe_num(q.get('last_volume'), 0.0, as_int=True)
            # Fallback: oi may be nested under 'oi_data' for /all filter, otherwise None
            if oi == 0 and 'oi_data' in q and isinstance(q['oi_data'], dict):
                oi = _safe_num(q['oi_data'].get('current_oi'), 0.0, as_int=True)
            self._update_tick(strat_sym, ltp, bid, ask, oi, vol)

    def _fetch_spot_quotes(self, queries: list[str]) -> None:
        encoded = ','.join(urllib.parse.quote(q, safe='') for q in queries)
        url = f"{self.session.base_url}/script-details/1.0/quotes/neosymbol/{encoded}/all"
        code, body = _http_get(url, {'Authorization': self.access_token})
        if code != 200:
            return
        try:
            quotes = json.loads(body)
        except Exception:
            return
        for q in quotes:
            ds = q.get('display_symbol', '')
            if 'Nifty 50' in ds or ds == 'NIFTY 50':
                sym = 'NIFTY'
            elif 'Nifty Bank' in ds or 'BANK' in ds.upper():
                sym = 'BANKNIFTY'
            else:
                continue
            ltp = float(q.get('ltp', 0) or 0)
            ohlc = q.get('ohlc', {}) or {}
            oi_val = 0
            # spot has no OI; use 0
            self._update_tick(sym, ltp, ltp - 0.05, ltp + 0.05, 0, 0)

    def _update_tick(self, sym: str, ltp: float, bid: float, ask: float, oi: int, vol: int) -> None:
        if ltp <= 0:
            return
        with self._lock:
            t = {
                'symbol': sym, 'ltp': ltp, 'bid': bid, 'ask': ask,
                'oi': oi, 'volume': vol, 'ts': time.time(),
            }
            self._latest[sym] = t
            hist = self._price_history.setdefault(sym, [])
            hist.append(ltp)
            if len(hist) > 600:
                hist[:] = hist[-600:]
        for cb in list(self._callbacks):
            try:
                cb(t)
            except Exception:
                pass
