"""Live market intelligence fetcher.

Pulls current market data + news from public sources and feeds into the
quant brain's context. Used for:
- Pre-market brief (08:30 IST)
- Intraday context refresh (every 1h during market hours)
- EOD review (15:30 IST)

Data sources (no API key needed):
- TradingView widget for current spot
- MoneyControl / LiveMint for NSE technical levels
- Google News RSS for latest market headlines
- NSE India official site for index data

Output: data_cache/research/live_intel.json — read by quant_service
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.parse
from loguru import logger

OUTPUT_PATH = Path("data_cache/research/live_intel.json")


def _http_get(url: str, timeout: int = 10, headers: Optional[dict] = None) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        **(headers or {})
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _fetch_nifty_technicals() -> dict:
    """Fetch NIFTY/BNF technical levels from public sources."""
    out = {"nifty": {}, "banknifty": {}, "ts": datetime.now().isoformat()}
    try:
        # Try MoneyControl markets page for technical levels
        html = _http_get("https://www.moneycontrol.com/stocks/marketstats/futures/", timeout=8)
        # Extract support/resistance
        for m in re.finditer(r'(NIFTY|BANKNIFTY)[^<]*?(\d{4,5}[,\.\d]*)[^<]*?(?:support|resistance|resist)[^<]*?(\d{4,5}[,\.\d]*)', html, re.IGNORECASE)[:8]:
            instr = m.group(1).upper()
            lvl1 = m.group(2).replace(',', '')
            lvl2 = m.group(3).replace(',', '')
            try:
                if instr not in out:
                    out[instr.lower()] = {"supports": [], "resistances": []}
                v1, v2 = float(lvl1), float(lvl2)
                if 10000 < v1 < 50000:
                    out[instr.lower()]["supports"].append(v1)
                if 10000 < v2 < 50000:
                    out[instr.lower()]["resistances"].append(v2)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"nifty_technicals: {e}")
    return out


def _fetch_news_headlines(max_headlines: int = 5) -> list[dict]:
    """Fetch latest NSE/market news."""
    out = []
    try:
        # Google News RSS for "NIFTY" OR "BANKNIFTY" - last 1h
        q = urllib.parse.quote("NIFTY OR BANKNIFTY Indian stock market")
        url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
        xml = _http_get(url, timeout=8)
        # XML returns a callable iterator from re.finditer; convert to list first
        items = list(re.finditer(r'<item>(.*?)</item>', xml, re.DOTALL))[:max_headlines * 2]
        for m in items:
            title_m = re.search(r'<title>(.*?)</title>', m.group(1))
            pub_m = re.search(r'<pubDate>(.*?)</pubDate>', m.group(1))
            if title_m:
                title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                if title and len(title) > 20:
                    out.append({
                        "title": title,
                        "published": pub_m.group(1) if pub_m else "",
                        "source": "google_news",
                    })
            if len(out) >= max_headlines:
                break
    except Exception as e:
        logger.debug(f"news_headlines: {e}")
    return out


def _fetch_google_trend_indicator() -> dict:
    """Light proxy for market sentiment via Google Trends. No API key needed."""
    # Skipped by default (rate limited). Could use SerpAPI or similar.
    return {"available": False, "note": "skipped to avoid rate limits"}


def refresh_live_intel() -> dict:
    """Pull all sources, cache, return summary."""
    technicals = _fetch_nifty_technicals()
    out = {
        "ts": datetime.now().isoformat(),
        "technicals": technicals,
        "news": _fetch_news_headlines(),
        "trend": _fetch_google_trend_indicator(),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    total_levels = 0
    for inst, t in technicals.items():
        if isinstance(t, dict):
            total_levels += len(t.get("supports", [])) + len(t.get("resistances", []))
    logger.info(f"live_intel: refreshed {len(out['news'])} headlines, {total_levels} levels")
    return out


def get_cached_intel(max_age_min: int = 60) -> Optional[dict]:
    """Read cached intel if fresh."""
    if not OUTPUT_PATH.exists():
        return None
    try:
        data = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        age_min = (datetime.now() - datetime.fromisoformat(data["ts"])).total_seconds() / 60
        if age_min > max_age_min:
            return None
        return data
    except Exception:
        return None


def format_intel_for_llm(data: dict) -> str:
    """Format intel for LLM context (compact)."""
    lines = ["=== LIVE INTEL (last 60min) ==="]
    tech = data.get("technicals", {})
    if tech.get("nifty", {}).get("supports"):
        lines.append(f"NIFTY supports: {tech['nifty']['supports'][:3]}")
    if tech.get("nifty", {}).get("resistances"):
        lines.append(f"NIFTY resistances: {tech['nifty']['resistances'][:3]}")
    if tech.get("banknifty", {}).get("supports"):
        lines.append(f"BANKNIFTY supports: {tech['banknifty']['supports'][:3]}")
    if tech.get("banknifty", {}).get("resistances"):
        lines.append(f"BANKNIFTY resistances: {tech['banknifty']['resistances'][:3]}")
    news = data.get("news", [])
    if news:
        lines.append("Top headlines:")
        for n in news[:3]:
            lines.append(f"  - {n['title'][:120]}")
    return "\n".join(lines)


if __name__ == "__main__":
    out = refresh_live_intel()
    print(format_intel_for_llm(out))
