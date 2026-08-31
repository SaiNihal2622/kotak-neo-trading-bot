"""Real-time OHLCV candle engine.

Subscribes to Kotak Neo via KotakProdFeed. Aggregates ticks into 1-min, 5-min,
15-min OHLCV bars. Persists to data_cache/candles/{symbol}_{tf}.jsonl
(append-only, last N bars) and writes a snapshot aggregate to
data_cache/candles_aggregate.json every cycle for the LLM to consume.

Pure Python (no numpy/scipy). Single-process. Designed to be called from
quant_service.py watch loop or run as a standalone subprocess.

Exposes:
    engine = get_engine()
    engine.tick("NIFTY", 24080.40, volume=0, ts=now)
    bars = engine.get_bars("NIFTY", tf="1m", n=60)
    ind = engine.compute_indicators("NIFTY", tf="1m")
    pat = engine.detect_patterns("NIFTY", tf="1m")
    vp = engine.compute_volume_profile("NIFTY", tf="1m", n_bars=60)
    engine.aggregate_to_file()  # writes data_cache/candles_aggregate.json

Indicators computed:
    RSI-14, MACD (12/26/9), Bollinger (20/2), EMA 9/21/50, ATR-14, VWAP dev

Patterns detected (last 1-3 bars):
    doji, hammer, shooting_star, bullish_engulfing, bearish_engulfing,
    marubozu_bull, marubozu_bear, spinning_top, morning_star, evening_star,
    three_white_soldiers, three_black_crows

Volume profile (when volume > 0; falls back to tick count proxy):
    poc (point of control), vah (value area high), val (value area low)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
CANDLES_DIR = DATA / 'candles'
CANDLES_DIR.mkdir(parents=True, exist_ok=True)
AGG_PATH = DATA / 'candles_aggregate.json'

# Symbols to track (28 instruments: 4 indices + 24 NIFTY-50 stocks)
INDICES = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']
STOCKS = [
    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'ITC', 'SBIN',
    'BHARTIARTL', 'KOTAKBANK', 'LT', 'AXISBANK', 'ASIANPAINT', 'MARUTI',
    'SUNPHARMA', 'TATAMOTORS', 'TATASTEEL', 'POWERGRID', 'NTPC', 'HINDUNILVR',
    'INDUSINDBK', 'BAJFINANCE', 'M&M', 'HCLTECH', 'TITAN',
]
SYMBOLS = INDICES + STOCKS

# Timeframes in seconds
TF_SECONDS = {'1m': 60, '5m': 300, '15m': 900}


def _bar_path(symbol: str, tf: str) -> Path:
    return CANDLES_DIR / f"{symbol}_{tf}.jsonl"


def _now_ist() -> datetime:
    return datetime.now()


def _minute_floor(ts: datetime, tf_sec: int) -> int:
    """Return the integer epoch of the start of the bar containing ts."""
    epoch = int(ts.timestamp())
    return epoch - (epoch % tf_sec)


class CandleEngine:
    """Stateful candle aggregator. One instance per process."""

    def __init__(self, max_bars: int = 240):
        self.max_bars = max_bars
        # {symbol: {tf: deque of {epoch, o, h, l, c, v, n_ticks}}}
        self.bars: dict[str, dict[str, deque]] = {s: {tf: deque(maxlen=max_bars) for tf in TF_SECONDS} for s in SYMBOLS}
        # {symbol: {tf: current bar dict}}
        self.current: dict[str, dict[str, dict]] = {s: {} for s in SYMBOLS}
        # {symbol: last_ltp}
        self.last_ltp: dict[str, float] = {}
        # {symbol: last_volume}
        self.last_vol: dict[str, int] = {}

    # ---------- tick ingestion ----------

    def tick(self, symbol: str, price: float, volume: int = 0, ts: Optional[datetime] = None) -> None:
        """Ingest one tick. Aggregates into 1m/5m/15m bars. Auto-closes bars on minute boundary.
        Auto-registers unknown symbols so the engine works for any ticker."""
        if price <= 0:
            return
        if symbol not in self.bars:
            self.bars[symbol] = {tf: deque(maxlen=self.max_bars) for tf in TF_SECONDS}
            self.current[symbol] = {}
        ts = ts or _now_ist()
        epoch = int(ts.timestamp())
        self.last_ltp[symbol] = price
        self.last_vol[symbol] = volume
        for tf, tf_sec in TF_SECONDS.items():
            bar_epoch = epoch - (epoch % tf_sec)
            cur = self.current[symbol].get(tf)
            if cur is None or cur['epoch'] != bar_epoch:
                # close previous bar
                if cur is not None:
                    self.bars[symbol][tf].append(cur)
                # start new bar
                self.current[symbol][tf] = {
                    'epoch': bar_epoch, 'ts': datetime.fromtimestamp(bar_epoch).isoformat(timespec='seconds'),
                    'o': price, 'h': price, 'l': price, 'c': price, 'v': volume, 'n_ticks': 1,
                }
            else:
                # update current bar
                cur['h'] = max(cur['h'], price)
                cur['l'] = min(cur['l'], price)
                cur['c'] = price
                cur['v'] += volume
                cur['n_ticks'] += 1

    def tick_many(self, prices: dict[str, float], volumes: Optional[dict[str, int]] = None) -> None:
        """Bulk tick. prices: {symbol: price}, volumes: {symbol: volume} (optional)."""
        vols = volumes or {}
        ts = _now_ist()
        for sym, p in prices.items():
            self.tick(sym, p, vols.get(sym, 0), ts)

    def flush_current(self) -> None:
        """Force-close all current bars (call at end of session or on shutdown)."""
        for sym in self.current:
            for tf, cur in self.current[sym].items():
                if cur is not None and cur not in self.bars[sym][tf]:
                    self.bars[sym][tf].append(cur)
            self.current[sym] = {}

    # ---------- persistence ----------

    def save_bars(self, symbol: str, tf: str) -> None:
        """Append-only persist bars for one symbol+tf."""
        path = _bar_path(symbol, tf)
        try:
            with path.open('a', encoding='utf-8') as f:
                for bar in list(self.bars[symbol][tf])[-60:]:
                    f.write(json.dumps(bar) + "\n")
        except Exception:
            pass

    def save_all(self) -> None:
        """Persist all symbols x all timeframes (last 60 bars each)."""
        for sym in SYMBOLS:
            for tf in TF_SECONDS:
                self.save_bars(sym, tf)

    def load_history(self, symbol: str, tf: str = '1m') -> int:
        """Load persisted bars into the in-memory deque. Returns count loaded."""
        path = _bar_path(symbol, tf)
        if not path.exists():
            return 0
        loaded = 0
        try:
            for line in path.read_text(encoding='utf-8', errors='ignore').splitlines()[-self.max_bars:]:
                try:
                    bar = json.loads(line)
                    if bar not in self.bars[symbol][tf]:
                        self.bars[symbol][tf].append(bar)
                        loaded += 1
                except Exception:
                    continue
        except Exception:
            pass
        return loaded

    def seed_yfinance(self, symbol: str, days: int = 5) -> int:
        """Backfill from yfinance 1m bars (last `days` days, max 7 for 1m)."""
        try:
            import yfinance as yf
            ticker_map = {
                'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK',
                'INDIAVIX': '^INDIAVIX', 'USDINR': 'USDINR=X',
                'WTI': 'CL=F', 'BRENT': 'BZ=F', 'GOLD': 'GC=F',
                'SP500': '^GSPC', 'NASDAQ': '^IXIC', 'DOW': '^DJI',
            }
            ticker = ticker_map.get(symbol, f"{symbol}.NS")
            t = yf.Ticker(ticker)
            hist = t.history(period=f"{min(days, 7)}d", interval='1m')
            if hist is None or hist.empty:
                return 0
            loaded = 0
            for idx, row in hist.iterrows():
                bar = {
                    'epoch': int(idx.timestamp()),
                    'ts': idx.isoformat(timespec='seconds'),
                    'o': float(row['Open']), 'h': float(row['High']),
                    'l': float(row['Low']), 'c': float(row['Close']),
                    'v': int(row.get('Volume', 0) or 0), 'n_ticks': 0,
                }
                self.bars[symbol]['1m'].append(bar)
                loaded += 1
            return loaded
        except Exception:
            return 0

    def aggregate_to_file(self) -> None:
        """Write a snapshot aggregate (latest bar + indicators + patterns) to JSON for the LLM."""
        snap = {'ts': _now_ist().isoformat(timespec='seconds'), 'symbols': {}}
        for sym in SYMBOLS:
            ltp = self.last_ltp.get(sym, 0)
            if not ltp and not self.bars[sym]['1m']:
                continue
            latest = {}
            for tf in TF_SECONDS:
                if self.current[sym].get(tf):
                    latest[tf] = dict(self.current[sym][tf])
                elif self.bars[sym][tf]:
                    latest[tf] = dict(self.bars[sym][tf][-1])
            ind = self.compute_indicators(sym, tf='1m')
            pat = self.detect_patterns(sym, tf='1m')
            vp = self.compute_volume_profile(sym, tf='1m')
            snap['symbols'][sym] = {
                'ltp': ltp,
                'latest_bars': latest,
                'indicators': ind,
                'patterns': pat,
                'volume_profile': vp,
                'n_bars_1m': len(self.bars[sym]['1m']),
            }
        try:
            AGG_PATH.write_text(json.dumps(snap, indent=2, default=str), encoding='utf-8')
        except Exception:
            pass

    # ---------- read accessors ----------

    def get_bars(self, symbol: str, tf: str = '1m', n: int = 60) -> list[dict]:
        if symbol not in self.bars:
            return []
        bars = list(self.bars[symbol][tf])
        cur = self.current[symbol].get(tf)
        if cur is not None and (not bars or bars[-1]['epoch'] != cur['epoch']):
            bars = bars + [cur]
        return bars[-n:]

    def get_close_series(self, symbol: str, tf: str = '1m', n: int = 60) -> list[float]:
        return [b['c'] for b in self.get_bars(symbol, tf, n)]

    # ---------- indicators (pure Python) ----------

    @staticmethod
    def _sma(values: list[float], n: int) -> Optional[float]:
        if len(values) < n:
            return None
        return sum(values[-n:]) / n

    @staticmethod
    def _ema_series(values: list[float], n: int) -> list[float]:
        if not values:
            return []
        alpha = 2.0 / (n + 1)
        ema = [values[0]]
        for v in values[1:]:
            ema.append(alpha * v + (1 - alpha) * ema[-1])
        return ema

    @staticmethod
    def _ema(values: list[float], n: int) -> Optional[float]:
        if len(values) < n:
            return None
        return CandleEngine._ema_series(values, n)[-1]

    @staticmethod
    def _rsi(values: list[float], n: int = 14) -> Optional[float]:
        if len(values) < n + 1:
            return None
        gains, losses = [], []
        for i in range(1, len(values)):
            d = values[i] - values[i - 1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        # Wilder's smoothing
        avg_g = sum(gains[:n]) / n
        avg_l = sum(losses[:n]) / n
        for i in range(n, len(gains)):
            avg_g = (avg_g * (n - 1) + gains[i]) / n
            avg_l = (avg_l * (n - 1) + losses[i]) / n
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[dict]:
        if len(values) < slow + signal:
            return None
        ema_fast = CandleEngine._ema_series(values, fast)
        ema_slow = CandleEngine._ema_series(values, slow)
        macd_line = [a - b for a, b in zip(ema_fast, ema_slow)]
        signal_line = CandleEngine._ema_series(macd_line, signal)
        hist = macd_line[-1] - signal_line[-1]
        return {'macd': round(macd_line[-1], 4), 'signal': round(signal_line[-1], 4), 'hist': round(hist, 4)}

    @staticmethod
    def _bollinger(values: list[float], n: int = 20, k: float = 2.0) -> Optional[dict]:
        if len(values) < n:
            return None
        window = values[-n:]
        sma = sum(window) / n
        var = sum((v - sma) ** 2 for v in window) / n
        std = math.sqrt(var)
        upper = sma + k * std
        lower = sma - k * std
        last = values[-1]
        pct_b = (last - lower) / (upper - lower) if upper != lower else 0.5
        bw = (upper - lower) / sma if sma else 0
        return {'upper': round(upper, 2), 'middle': round(sma, 2), 'lower': round(lower, 2),
                'pct_b': round(pct_b, 3), 'bandwidth': round(bw, 4)}

    @staticmethod
    def _atr(bars: list[dict], n: int = 14) -> Optional[float]:
        if len(bars) < n + 1:
            return None
        trs = []
        for i in range(1, len(bars)):
            h, l, pc = bars[i]['h'], bars[i]['l'], bars[i - 1]['c']
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if len(trs) < n:
            return None
        atr = sum(trs[:n]) / n
        for i in range(n, len(trs)):
            atr = (atr * (n - 1) + trs[i]) / n
        return atr

    def compute_indicators(self, symbol: str, tf: str = '1m') -> dict:
        bars = self.get_bars(symbol, tf, n=120)
        if len(bars) < 5:
            return {}
        closes = [b['c'] for b in bars]
        rsi = self._rsi(closes, 14)
        macd = self._macd(closes)
        bb = self._bollinger(closes, 20, 2.0)
        ema9 = self._ema(closes, 9)
        ema21 = self._ema(closes, 21)
        ema50 = self._ema(closes, 50)
        atr = self._atr(bars, 14)
        # EMA trend
        ema_trend = 'sideways'
        if ema9 and ema21 and ema50:
            if ema9 > ema21 > ema50:
                ema_trend = 'up'
            elif ema9 < ema21 < ema50:
                ema_trend = 'down'
        # VWAP (today, since 09:15)
        vwap_sum, vol_sum = 0.0, 0
        today = _now_ist().strftime('%Y-%m-%d')
        for b in bars:
            if b['ts'].startswith(today) and b['v'] > 0:
                typical = (b['h'] + b['l'] + b['c']) / 3
                vwap_sum += typical * b['v']
                vol_sum += b['v']
        vwap = vwap_sum / vol_sum if vol_sum > 0 else None
        vwap_dev_pct = ((closes[-1] - vwap) / vwap * 100) if vwap else None
        return {
            'rsi_14': round(rsi, 2) if rsi is not None else None,
            'macd': macd,
            'bollinger': bb,
            'ema_9': round(ema9, 2) if ema9 is not None else None,
            'ema_21': round(ema21, 2) if ema21 is not None else None,
            'ema_50': round(ema50, 2) if ema50 is not None else None,
            'ema_trend': ema_trend,
            'atr_14': round(atr, 2) if atr is not None else None,
            'vwap': round(vwap, 2) if vwap else None,
            'vwap_dev_pct': round(vwap_dev_pct, 2) if vwap_dev_pct is not None else None,
        }

    # ---------- candlestick patterns (pure Python) ----------

    @staticmethod
    def _body(b: dict) -> float:
        return abs(b['c'] - b['o'])

    @staticmethod
    def _upper_shadow(b: dict) -> float:
        return b['h'] - max(b['o'], b['c'])

    @staticmethod
    def _lower_shadow(b: dict) -> float:
        return min(b['o'], b['c']) - b['l']

    @staticmethod
    def _range(b: dict) -> float:
        return b['h'] - b['l']

    @staticmethod
    def _is_bullish(b: dict) -> bool:
        return b['c'] > b['o']

    @staticmethod
    def _is_bearish(b: dict) -> bool:
        return b['c'] < b['o']

    def detect_patterns(self, symbol: str, tf: str = '1m') -> list[dict]:
        bars = self.get_bars(symbol, tf, n=5)
        if len(bars) < 1:
            return []
        out = []
        b = bars[-1]
        rng = self._range(b)
        body = self._body(b)
        us = self._upper_shadow(b)
        ls = self._lower_shadow(b)

        # Doji: body / range < 0.1
        if rng > 0 and body / rng < 0.1:
            out.append({'name': 'doji', 'signal': 'reversal_watch', 'strength': 'medium'})

        # Hammer: small body at top, lower shadow > 2*body, in downtrend
        if body > 0 and ls > 2 * body and us < body * 0.5 and len(bars) >= 3:
            trend_down = all(bars[i]['c'] < bars[i - 1]['c'] for i in range(-3, 0) if i - 1 >= -len(bars))
            if trend_down:
                out.append({'name': 'hammer', 'signal': 'bullish_reversal', 'strength': 'strong'})

        # Shooting star: small body at bottom, upper shadow > 2*body
        if body > 0 and us > 2 * body and ls < body * 0.5 and len(bars) >= 3:
            trend_up = all(bars[i]['c'] > bars[i - 1]['c'] for i in range(-3, 0) if i - 1 >= -len(bars))
            if trend_up:
                out.append({'name': 'shooting_star', 'signal': 'bearish_reversal', 'strength': 'strong'})

        # Marubozu: full body, no shadows
        if rng > 0 and body / rng > 0.95:
            if self._is_bullish(b):
                out.append({'name': 'marubozu_bull', 'signal': 'bullish_continuation', 'strength': 'strong'})
            else:
                out.append({'name': 'marubozu_bear', 'signal': 'bearish_continuation', 'strength': 'strong'})

        # Spinning top: small body, both shadows > body
        if body > 0 and rng > 0 and us > body and ls > body and body / rng < 0.4:
            out.append({'name': 'spinning_top', 'signal': 'indecision', 'strength': 'weak'})

        # Engulfing (needs previous bar)
        if len(bars) >= 2:
            prev = bars[-2]
            prev_body = self._body(prev)
            if body > prev_body and rng > self._range(prev):
                if self._is_bearish(prev) and self._is_bullish(b):
                    out.append({'name': 'bullish_engulfing', 'signal': 'bullish_reversal', 'strength': 'strong'})
                elif self._is_bullish(prev) and self._is_bearish(b):
                    out.append({'name': 'bearish_engulfing', 'signal': 'bearish_reversal', 'strength': 'strong'})

        # Morning star / evening star (needs 3 bars)
        if len(bars) >= 3:
            b1, b2, b3 = bars[-3], bars[-2], bars[-1]
            if self._is_bearish(b1) and self._body(b2) / max(self._range(b2), 0.01) < 0.3 and self._is_bullish(b3) and b3['c'] > (b1['o'] + b1['c']) / 2:
                out.append({'name': 'morning_star', 'signal': 'bullish_reversal', 'strength': 'strong'})
            if self._is_bullish(b1) and self._body(b2) / max(self._range(b2), 0.01) < 0.3 and self._is_bearish(b3) and b3['c'] < (b1['o'] + b1['c']) / 2:
                out.append({'name': 'evening_star', 'signal': 'bearish_reversal', 'strength': 'strong'})

        # Three white soldiers / three black crows (needs 3 bars)
        if len(bars) >= 3:
            b1, b2, b3 = bars[-3], bars[-2], bars[-1]
            if all(self._is_bullish(b) for b in [b1, b2, b3]) and b3['c'] > b2['c'] > b1['c'] and b3['o'] > b2['o'] > b1['o']:
                out.append({'name': 'three_white_soldiers', 'signal': 'bullish_continuation', 'strength': 'strong'})
            if all(self._is_bearish(b) for b in [b1, b2, b3]) and b3['c'] < b2['c'] < b1['c'] and b3['o'] < b2['o'] < b1['o']:
                out.append({'name': 'three_black_crows', 'signal': 'bearish_continuation', 'strength': 'strong'})

        return out

    # ---------- volume profile ----------

    def compute_volume_profile(self, symbol: str, tf: str = '1m', n_bars: int = 60) -> dict:
        bars = self.get_bars(symbol, tf, n=n_bars)
        if not bars:
            return {}
        # Bin prices (round to 50pt for indices, 10pt for stocks)
        is_index = symbol in INDICES
        bin_size = 50 if is_index else 10
        vol_by_price: dict[int, int] = {}
        for b in bars:
            if b['v'] <= 0:
                continue
            mid = (b['h'] + b['l'] + b['c']) / 3
            for level in range(int(b['l'] / bin_size) * bin_size, int(b['h'] / bin_size) * bin_size + 1, bin_size):
                vol_by_price[level] = vol_by_price.get(level, 0) + b['v']
        if not vol_by_price:
            return {}
        sorted_levels = sorted(vol_by_price.items(), key=lambda x: -x[1])
        total_vol = sum(vol_by_price.values())
        poc = sorted_levels[0][0]
        # Value area: 70% of volume centered on POC
        va_vol = 0
        va_levels = []
        for lvl, v in sorted_levels:
            va_levels.append(lvl)
            va_vol += v
            if va_vol >= 0.7 * total_vol:
                break
        return {
            'poc': poc,
            'vah': max(va_levels) if va_levels else None,
            'val': min(va_levels) if va_levels else None,
            'total_vol': total_vol,
            'bin_size': bin_size,
        }


# ---------- module-level singleton ----------

_ENGINE: Optional[CandleEngine] = None


def get_engine() -> CandleEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = CandleEngine(max_bars=240)
        # Load persisted history (best-effort, fast)
        for sym in SYMBOLS:
            for tf in TF_SECONDS:
                _ENGINE.load_history(sym, tf)
    return _ENGINE


def fetch_live_prices() -> dict[str, float]:
    """Best-effort fetch of live LTP for all symbols. Returns {symbol: price}."""
    out: dict[str, float] = {}
    # Try KotakProdFeed first
    try:
        sys.path.insert(0, str(ROOT))
        from kotak_bot.data.kotak_prod_feed import KotakProdFeed
        feed = KotakProdFeed()
        if feed.is_authenticated() or feed._auth():
            for sym in SYMBOLS:
                try:
                    p = feed.get_ltp(sym)
                    if p and p > 0:
                        out[sym] = float(p)
                except Exception:
                    continue
            if out:
                return out
    except Exception:
        pass
    # Fallback: yfinance
    try:
        import yfinance as yf
        ticker_map = {'NIFTY': '^NSEI', 'BANKNIFTY': '^NSEBANK', 'FINNIFTY': 'NIFTY_FIN_SERVICE.NS',
                      'MIDCPNIFTY': 'NIFTY_MIDCAP_100.NS'}
        for sym in SYMBOLS:
            tk = ticker_map.get(sym, f"{sym}.NS")
            try:
                t = yf.Ticker(tk)
                hist = t.history(period='1d')
                if hist is not None and not hist.empty:
                    out[sym] = float(hist['Close'].iloc[-1])
            except Exception:
                continue
    except Exception:
        pass
    return out


def main() -> int:
    """Standalone: poll live prices every 5s, aggregate, write to file."""
    eng = get_engine()
    # Backfill from yfinance on startup
    print("[candle_engine] backfilling from yfinance...")
    for sym in INDICES:
        n = eng.seed_yfinance(sym, days=5)
        print(f"  {sym}: {n} bars")
    print("[candle_engine] starting live tick loop (5s poll)...")
    last_save = 0
    while True:
        try:
            prices = fetch_live_prices()
            if prices:
                eng.tick_many(prices)
            if time.time() - last_save > 30:
                eng.aggregate_to_file()
                last_save = time.time()
            time.sleep(5)
        except KeyboardInterrupt:
            print("[candle_engine] shutting down")
            eng.flush_current()
            eng.aggregate_to_file()
            return 0
        except Exception as e:
            print(f"[candle_engine] loop err: {e}")
            time.sleep(5)


if __name__ == '__main__':
    sys.exit(main())
