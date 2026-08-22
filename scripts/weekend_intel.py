"""Weekend intelligence aggregator for pre-Monday trading prep.

Pulls:
  1. yfinance market data (NIFTY/BANKNIFTY/VIX/USDINR/Crude/Gold/SP500/Nasdaq)
  2. RSS feeds (Reuters India, Economic Times, Moneycontrol, LiveMint, Business Standard)
  3. Kotak Neo daily derivatives PDF (if available — only Mon-Fri usually)

Outputs data_cache/weekend_intel.json with:
  - as_of (IST timestamp)
  - markets: {ticker: {last, change_1d_pct, change_5d_pct}}
  - key_news: list of {title, link, source, published, sentiment, score, keywords}
  - regime_hint: "risk_on" | "risk_off" | "neutral"
  - monday_outlook: short text summary
  - india_open_gap_signal: "gap_up" | "gap_down" | "flat"

Designed to run on Saturday/Sunday/Monday-pre-open (0 21 * * 0 cron).
All sources are free / no API key. Network errors are non-fatal (partial result).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import feedparser
import requests
import yfinance as yf
from loguru import logger

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))

CACHE_DIR = Path("data_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH = CACHE_DIR / "weekend_intel.json"

# Yfinance tickers — all free, no key
TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "INDIA_VIX": "^INDIAVIX",
    "USDINR": "USDINR=X",
    "WTI_CRUDE": "CL=F",
    "BRENT_CRUDE": "BZ=F",
    "GOLD": "GC=F",
    "BTC": "BTC-USD",
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "US_VIX": "^VIX",
    "DOLLAR_INDEX": "DX-Y.NYB",
}

# RSS feeds (no key, plain HTTP)
RSS_FEEDS = {
    "reuters_india": "http://feeds.reuters.com/reuters/INbusinessNews",
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "moneycontrol": "https://www.moneycontrol.com/rss/latestnews.xml",
    "livemint_markets": "https://www.livemint.com/rss/markets",
    "bs_markets": "https://www.business-standard.com/rss/markets-106.rss",
}

# Keyword → sentiment score for headlines
BULLISH_KW = [
    "rally", "surge", "soar", "jump", "gain", "rise", "high", "record",
    "boost", "recover", "bullish", "upgrade", "beat", "outperform",
    "stimulus", "rate cut", "dovish", "strong", "growth", "expansion",
    "optimistic", "ceasefire", "deal", "agreement", "buy", "buying",
    "fed pauses", "fed holds", "earnings beat", "profit",
]
BEARISH_KW = [
    "fall", "drop", "plunge", "crash", "slump", "tumble", "decline", "low",
    "tension", "war", "attack", "strike", "missile", "conflict", "ceasefire",
    "sanction", "tariff", "inflation", "hawkish", "rate hike", "recession",
    "fear", "panic", "sell", "selling", "selloff", "bearish", "downgrade",
    "weak", "slowdown", "contraction", "unemployment", "default", "crisis",
    "concern", "worry", "risk-off", "geopolitical", "earthquake", "flood",
    "fed hikes", "earnings miss", "loss",
]
EVENT_KW = [
    "rbi", "fed", "fomc", "cpi", "gdp", "pmi", "nfp", "payroll", "ecb", "boj",
    "union budget", "election", "opec", "crude", "oil", "rupee", "dollar",
    "treasury", "yield", "10-year", "2-year", "fii", "dii",
]


def fetch_market_data() -> dict:
    """Pull 5d + 1d change for each ticker via yfinance."""
    markets = {}
    for name, ticker in TICKERS.items():
        try:
            t = yf.Ticker(ticker)
            h = t.history(period="10d", auto_adjust=True)
            if h is None or len(h) < 1:
                logger.warning(f"{name} ({ticker}): no history")
                continue
            close = h["Close"].dropna()
            if len(close) < 1:
                continue
            last = float(close.iloc[-1])
            prev = float(close.iloc[-2]) if len(close) >= 2 else last
            week_ago = float(close.iloc[-5]) if len(close) >= 5 else float(close.iloc[0])
            markets[name] = {
                "ticker": ticker,
                "last": round(last, 4),
                "change_1d_pct": round((last - prev) / prev * 100, 2) if prev else 0.0,
                "change_5d_pct": round((last - week_ago) / week_ago * 100, 2) if week_ago else 0.0,
                "as_of_date": str(close.index[-1].date()),
            }
        except Exception as e:
            logger.warning(f"{name} ({ticker}) failed: {e}")
    return markets


def fetch_rss_news(max_per_feed: int = 8) -> list[dict]:
    """Fetch top headlines from each RSS feed, score sentiment."""
    items = []
    for source, url in RSS_FEEDS.items():
        try:
            d = feedparser.parse(url, agent="Mozilla/5.0")
            for entry in d.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                if not title:
                    continue
                # parse published
                pub = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        pub = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pub = None
                if not pub and hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    try:
                        pub = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pub = None
                items.append({
                    "title": title,
                    "link": entry.get("link", ""),
                    "source": source,
                    "published": pub.isoformat() if pub else None,
                    "summary": entry.get("summary", "")[:200],
                })
        except Exception as e:
            logger.warning(f"RSS {source} failed: {e}")
    return items


def score_headline(text: str) -> dict:
    """Keyword-based sentiment: positive vs negative vs event-only."""
    low = text.lower()
    bull = sum(1 for k in BULLISH_KW if k in low)
    bear = sum(1 for k in BEARISH_KW if k in low)
    event = sum(1 for k in EVENT_KW if k in low)
    score = bull - bear
    if event >= 2 and score == 0:
        sentiment = "event"
    elif score >= 1:
        sentiment = "bullish"
    elif score <= -1:
        sentiment = "bearish"
    else:
        sentiment = "neutral"
    return {"sentiment": sentiment, "score": score, "bull_hits": bull, "bear_hits": bear, "event_hits": event}


def derive_regime_hint(markets: dict, scored_news: list[dict]) -> str:
    """Crude rule-based: 5d US + INR + crude + India VIX + news sentiment."""
    score = 0
    # US equities 5d
    for k in ("SP500", "NASDAQ", "DOW"):
        v = markets.get(k, {}).get("change_5d_pct", 0)
        if v > 0.5:
            score += 1
        elif v < -0.5:
            score -= 1
    # USDINR — rising USD/INR = rupee weakening = bearish for India
    usdinr_5d = markets.get("USDINR", {}).get("change_5d_pct", 0)
    if usdinr_5d > 0.5:
        score -= 1
    elif usdinr_5d < -0.5:
        score += 1
    # Crude — rising oil = bearish for India (import bill)
    for k in ("WTI_CRUDE", "BRENT_CRUDE"):
        v = markets.get(k, {}).get("change_5d_pct", 0)
        if v > 3:
            score -= 1
        elif v < -3:
            score += 1
    # VIX
    vix = markets.get("US_VIX", {}).get("last", 15)
    if vix > 22:
        score -= 2
    elif vix > 18:
        score -= 1
    elif vix < 13:
        score += 1
    # India VIX
    ivix = markets.get("INDIA_VIX", {}).get("last", 15)
    if ivix > 18:
        score -= 1
    # News sentiment
    bull = sum(1 for n in scored_news if n["sentiment"] == "bullish")
    bear = sum(1 for n in scored_news if n["sentiment"] == "bearish")
    score += max(-2, min(2, (bull - bear) // 2))
    if score >= 2:
        return "risk_on"
    if score <= -2:
        return "risk_off"
    return "neutral"


def derive_gap_signal(markets: dict) -> str:
    """Hint at Monday open gap based on global cues (US + SGX proxies)."""
    score = 0
    for k in ("SP500", "NASDAQ", "DOW"):
        v = markets.get(k, {}).get("change_1d_pct", 0)
        if v > 0.5:
            score += 1
        elif v < -0.5:
            score -= 1
    usdinr_1d = markets.get("USDINR", {}).get("change_1d_pct", 0)
    if usdinr_1d > 0.3:
        score -= 1
    elif usdinr_1d < -0.3:
        score += 1
    if score >= 1:
        return "gap_up"
    if score <= -1:
        return "gap_down"
    return "flat"


def build_outlook(markets: dict, scored_news: list[dict], regime: str, gap: str) -> str:
    parts = []
    nifty_chg = markets.get("NIFTY", {}).get("change_5d_pct", 0)
    if nifty_chg:
        parts.append(f"NIFTY 5d: {nifty_chg:+.2f}%")
    sp_chg = markets.get("SP500", {}).get("change_5d_pct", 0)
    if sp_chg:
        parts.append(f"S&P 5d: {sp_chg:+.2f}%")
    usdinr_chg = markets.get("USDINR", {}).get("change_5d_pct", 0)
    if usdinr_chg:
        parts.append(f"USD/INR 5d: {usdinr_chg:+.2f}%")
    crude_chg = markets.get("WTI_CRUDE", {}).get("change_5d_pct", 0)
    if crude_chg:
        parts.append(f"Crude 5d: {crude_chg:+.2f}%")
    us_vix = markets.get("US_VIX", {}).get("last", 0)
    if us_vix:
        parts.append(f"US VIX: {us_vix:.1f}")
    ivix = markets.get("INDIA_VIX", {}).get("last", 0)
    if ivix:
        parts.append(f"India VIX: {ivix:.1f}")
    # Top 3 headlines
    top_news = [n for n in scored_news if n["sentiment"] in ("bullish", "bearish", "event")][:3]
    if top_news:
        parts.append("—")
        for n in top_news:
            parts.append(f"• [{n['sentiment']}] {n['title'][:100]}")
    return "\n".join(parts)


def main() -> dict:
    started = datetime.now(IST)
    logger.info(f"weekend_intel started at {started.isoformat()}")

    markets = fetch_market_data()
    logger.info(f"markets: {len(markets)} tickers fetched")

    news = fetch_rss_news()
    logger.info(f"news: {len(news)} headlines")

    scored_news = []
    for n in news:
        s = score_headline(n["title"] + " " + n.get("summary", ""))
        scored_news.append({**n, **s})
    # Sort: bearish first, then bullish, then event, then neutral
    order = {"bearish": 0, "event": 1, "bullish": 2, "neutral": 3}
    scored_news.sort(key=lambda x: (order.get(x["sentiment"], 4), -abs(x["score"])))

    regime = derive_regime_hint(markets, scored_news)
    gap = derive_gap_signal(markets)
    outlook = build_outlook(markets, scored_news, regime, gap)

    result = {
        "as_of": started.isoformat(),
        "script": "weekend_intel.py",
        "markets": markets,
        "key_news": scored_news[:30],  # cap at 30 headlines
        "regime_hint": regime,
        "india_open_gap_signal": gap,
        "monday_outlook": outlook,
        "news_count": len(news),
        "tickers_fetched": len(markets),
        "rss_feeds_attempted": list(RSS_FEEDS.keys()),
    }
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
    # Print one-liner for cron logs
    print(f"[weekend_intel] markets={len(markets)} news={len(news)} regime={regime} gap={gap}")
    return result


if __name__ == "__main__":
    main()
