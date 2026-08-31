"""News-based research fallback for the LLM brain.

When the Kotak Neo derivatives PDF is unavailable (layout drift), this module
scrapes kotakneo.com/news/ for recent derivatives/F&O technical articles and
extracts key levels, FII flows, max-pain-like data.

Output: data_cache/research/news_research.json — read by quant_service
context builder to augment the LLM's market view.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import requests
from loguru import logger

CACHE_PATH = Path("data_cache/research/news_research.json")
KOTAK_NEO_NEWS = "https://www.kotakneo.com/news/derivatives/"
KOTAK_NEO_FNO = "https://www.kotakneo.com/futures-and-options/"


def _scrape_kotak_neo_news() -> list[dict]:
    """Scrape kotakneo.com for recent derivatives/F&O articles."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        out = []
        for url in [KOTAK_NEO_NEWS, KOTAK_NEO_FNO]:
            try:
                r = requests.get(url, timeout=15, headers=headers)
                if r.status_code != 200:
                    continue
                # Extract article links + titles
                # Pattern: <a href="...kotakneo.com/news/...">Title</a>
                article_re = re.compile(r'<a[^>]+href="([^"]*kotakneo\.com/news/[^"]+)"[^>]*>([^<]+)</a>')
                for m in article_re.finditer(r.text)[:8]:
                    title = m.group(2).strip()
                    if title and len(title) > 15:
                        out.append({"title": title, "url": m.group(1), "source": "kotakneo.com"})
            except Exception:
                continue
        # Dedupe by title
        seen = set()
        unique = []
        for a in out:
            if a["title"] not in seen:
                seen.add(a["title"])
                unique.append(a)
        return unique[:10]
    except Exception as e:
        logger.warning(f"scrape_kotak_neo_news: {e}")
        return []


def _scrape_article_text(url: str) -> str:
    """Scrape the body text of a single article."""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return ""
        # Strip HTML
        text = re.sub(r'<script[^>]*>.*?</script>', '', r.text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:3000]
    except Exception:
        return ""


def extract_levels_from_text(text: str) -> dict:
    """Extract technical levels, support/resistance, FII flows from text."""
    out = {"supports": [], "resistances": [], "fii_flow": None, "pcr": None, "max_pain": None}
    # Match support: "support at Rs X,XXX" or "support: X"
    support_re = re.compile(r'(?:support|buying zone)[\s:]+(?:Rs\.?\s*)?(\d{4,6}(?:,\d{3})*(?:\.\d+)?)', re.IGNORECASE)
    resist_re = re.compile(r'(?:resistance|selling zone)[\s:]+(?:Rs\.?\s*)?(\d{4,6}(?:,\d{3})*(?:\.\d+)?)', re.IGNORECASE)
    fii_re = re.compile(r'FII\s*(?:net|flow|position)[^.]*?(\+?-?Rs?\.?\s*[\d,]+)\s*(?:crore|cr|lakh)?', re.IGNORECASE)
    pcr_re = re.compile(r'PCR\s*[:=]?\s*(\d+\.\d+)', re.IGNORECASE)
    max_pain_re = re.compile(r'max\s*(?:pain)?\s*[:=]?\s*(\d{4,6})', re.IGNORECASE)

    for m in support_re.finditer(text):
        try:
            val = float(m.group(1).replace(',', ''))
            if 1000 < val < 100000:
                out["supports"].append(val)
        except Exception:
            pass
    for m in resist_re.finditer(text):
        try:
            val = float(m.group(1).replace(',', ''))
            if 1000 < val < 100000:
                out["resistances"].append(val)
        except Exception:
            pass
    fii_match = fii_re.search(text)
    if fii_match:
        out["fii_flow"] = fii_match.group(1)
    pcr_match = pcr_re.search(text)
    if pcr_match:
        try:
            out["pcr"] = float(pcr_match.group(1))
        except Exception:
            pass
    max_pain_match = max_pain_re.search(text)
    if max_pain_match:
        try:
            out["max_pain"] = float(max_pain_match.group(1))
        except Exception:
            pass
    return out


def refresh_news_research() -> dict:
    """Fetch latest news research, cache, return summary."""
    articles = _scrape_kotak_neo_news()
    summaries = []
    for a in articles[:5]:  # top 5
        body = _scrape_article_text(a["url"])
        if not body:
            continue
        levels = extract_levels_from_text(body)
        summaries.append({
            "title": a["title"],
            "url": a["url"],
            "fetched_at": datetime.now().isoformat(),
            "levels": levels,
            "body_excerpt": body[:500],
        })
    out = {
        "ts": datetime.now().isoformat(),
        "articles": summaries,
        "aggregate_supports": sorted({l for s in summaries for l in s["levels"].get("supports", [])})[:5],
        "aggregate_resistances": sorted({l for s in summaries for l in s["levels"].get("resistances", [])})[:5],
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def get_cached_research() -> Optional[dict]:
    """Read cached research if fresh (< 12h old)."""
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        ts = data.get("ts", "")
        if not ts:
            return None
        age_hours = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
        if age_hours > 12:
            return None
        return data
    except Exception:
        return None


if __name__ == "__main__":
    out = refresh_news_research()
    print(f"Refreshed {len(out['articles'])} articles")
    print(f"Supports: {out['aggregate_supports']}")
    print(f"Resistances: {out['aggregate_resistances']}")
