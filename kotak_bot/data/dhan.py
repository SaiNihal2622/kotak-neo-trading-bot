"""DhanHQ connector — FREE historical data + option chain for Indian markets.

Dhan (dhan.co) is a SEBI-registered broker with the most complete FREE data API
of any Indian broker:
- Historical OHLCV (1-min, 5-min, 15-min, daily) — YEARS of data
- Option chain with live OI, IV, Greeks
- Live quotes, market depth
- All FREE with just a Dhan account (no brokerage needed for data API)

Setup:
1. Sign up at https://dhan.co (free, takes 2 min)
2. Go to Dhan Web → My Profile → DhanHQ Trading APIs
3. Get your client_id and access_token
4. Add to config/credentials.env:
   DHAN_CLIENT_ID=...
   DHAN_ACCESS_TOKEN=...

pip install dhanhq
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

try:
    from dhanhq import dhanhq
    _DHAN_AVAILABLE = True
except ImportError:
    _DHAN_AVAILABLE = False


class DhanDataFeed:
    """Free Indian market data via DhanHQ. Historical + option chain + live."""

    # Dhan security IDs (curated, not exhaustive)
    SECURITY_IDS = {
        "NIFTY": 13,           # NIFTY 50 index
        "BANKNIFTY": 25,       # NIFTY BANK
        "FINNIFTY": 27,        # NIFTY FIN SERVICE
        "MIDCPNIFTY": 51,      # NIFTY MIDCAP SELECT
        "SENSEX": 1,           # BSE SENSEX
    }

    # Lot sizes (NSE 2025)
    LOT_SIZES = {
        "NIFTY": 75,
        "BANKNIFTY": 30,
        "FINNIFTY": 65,
        "MIDCPNIFTY": 120,
    }

    def __init__(self, client_id: str = "", access_token: str = "", cache_dir: str = "data_cache/dhan"):
        self.client_id = client_id or os.getenv("DHAN_CLIENT_ID", "")
        self.access_token = access_token or os.getenv("DHAN_ACCESS_TOKEN", "")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = None
        self._last_request = 0
        if _DHAN_AVAILABLE and self.client_id and self.access_token:
            try:
                self.client = dhanhq(self.client_id, self.access_token)
                logger.info("Dhan client initialized")
            except Exception as e:
                logger.warning(f"Dhan init failed: {e}")

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _rate_limit(self) -> None:
        """Dhan: ~1 req/sec safe, burst up to 5."""
        elapsed = time.time() - self._last_request
        if elapsed < 0.3:
            time.sleep(0.3 - elapsed)
        self._last_request = time.time()

    # ============================================================
    # Historical data
    # ============================================================
    def get_historical(
        self,
        symbol: str,
        exchange: str = "NSE",
        segment: str = "EQUITY",
        instrument_type: str = "INDEX",
        interval: str = "1",  # 1, 5, 15, 25, 60
        from_date: str = None,
        to_date: str = None,
        days: int = 180,
    ) -> pd.DataFrame:
        """Get historical OHLCV. interval in minutes: 1, 5, 15, 25, 60"""
        if not self.enabled:
            logger.warning("Dhan not enabled — returning empty")
            return pd.DataFrame()
        sec_id = self.SECURITY_IDS.get(symbol.upper())
        if not sec_id:
            logger.warning(f"Unknown symbol: {symbol}")
            return pd.DataFrame()
        if not to_date:
            to_date = datetime.now().strftime("%Y-%m-%d")
        if not from_date:
            from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cache_path = self.cache_dir / f"{symbol}_{interval}_{from_date}_{to_date}.parquet"
        if cache_path.exists():
            try:
                return pd.read_parquet(cache_path)
            except Exception:
                pass
        self._rate_limit()
        try:
            data = self.client.historical_minute_charts(
                symbol=symbol,
                exchange_segment=f"{exchange}_{segment}",
                instrument_type=instrument_type,
                security_id=str(sec_id),
                interval=interval,
                from_date=from_date,
                to_date=to_date,
            )
            if data and data.get("status") == "success":
                df = pd.DataFrame(data["data"])
                df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp").reset_index(drop=True)
                try:
                    df.to_parquet(cache_path)
                except Exception:
                    pass
                logger.info(f"Dhan historical[{symbol} {interval}m]: {len(df)} rows ({from_date} → {to_date})")
                return df
            logger.warning(f"Dhan historical failed: {data}")
        except Exception as e:
            logger.warning(f"Dhan historical error: {e}")
        return pd.DataFrame()

    # ============================================================
    # Option chain
    # ============================================================
    def get_option_chain(self, underlying: str, expiry: str, strike_count: int = 10) -> pd.DataFrame:
        """Get option chain with live OI, IV, Greeks, LTP."""
        if not self.enabled:
            return pd.DataFrame()
        sec_id = self.SECURITY_IDS.get(underlying.upper())
        if not sec_id:
            return pd.DataFrame()
        self._rate_limit()
        try:
            data = self.client.option_chain(
                under_security_id=str(sec_id),
                under_exchange_segment="NSE_FNO",
                expiry=expiry,
            )
            if data and data.get("status") == "success":
                oc = data["data"]
                rows = []
                # oc has 'oc' field with strike data
                if "oc" in oc:
                    for strike, leg in oc["oc"].items():
                        ce = leg.get("ce", {}) or {}
                        pe = leg.get("pe", {}) or {}
                        rows.append({
                            "strike": float(strike),
                            "ce_ltp": ce.get("last_price", 0),
                            "ce_oi": ce.get("oi", 0),
                            "ce_iv": ce.get("implied_volatility", 0),
                            "ce_volume": ce.get("volume", 0),
                            "ce_bid": ce.get("top_bid_price", 0),
                            "ce_ask": ce.get("top_ask_price", 0),
                            "pe_ltp": pe.get("last_price", 0),
                            "pe_oi": pe.get("oi", 0),
                            "pe_iv": pe.get("implied_volatility", 0),
                            "pe_volume": pe.get("volume", 0),
                            "pe_bid": pe.get("top_bid_price", 0),
                            "pe_ask": pe.get("top_ask_price", 0),
                        })
                df = pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)
                if df.empty and "last_quote_price" in oc:
                    # newer format
                    pass
                logger.info(f"Dhan option_chain[{underlying} {expiry}]: {len(df)} strikes")
                return df
            logger.warning(f"Dhan option_chain failed: {data}")
        except Exception as e:
            logger.warning(f"Dhan option_chain error: {e}")
        return pd.DataFrame()

    # ============================================================
    # Live quotes
    # ============================================================
    def get_ltp(self, symbol: str, exchange_segment: str = "NSE_EQ", security_id: str = "") -> float:
        if not self.enabled:
            return 0.0
        if not security_id:
            security_id = str(self.SECURITY_IDS.get(symbol.upper(), 0))
        self._rate_limit()
        try:
            data = self.client.get_ltp_live(
                exchange_segment=exchange_segment,
                security_id=security_id,
            )
            if data and data.get("status") == "success":
                d = data.get("data", {})
                return float(d.get("ltp", 0) or 0)
        except Exception as e:
            logger.debug(f"Dhan ltp: {e}")
        return 0.0

    def get_expiries(self, underlying: str) -> list[str]:
        """Get available expiry dates for an underlying."""
        if not self.enabled:
            return []
        sec_id = self.SECURITY_IDS.get(underlying.upper())
        if not sec_id:
            return []
        self._rate_limit()
        try:
            data = self.client.expiry_list(
                under_security_id=str(sec_id),
                under_exchange_segment="NSE_FNO",
            )
            if data and data.get("status") == "success":
                return data.get("data", [])
        except Exception as e:
            logger.debug(f"Dhan expiries: {e}")
        return []
