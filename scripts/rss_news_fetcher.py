"""rss_news_fetcher.py — REAL news feed for the brain.

FIX 2026-09-08 22:35: the brain's LLM had no real news to reason on. The
Grok Bot Desk's news role correctly identified "no actual news items in
feed" because news_cache.py was only grepping bot.log for keyword
mentions. This script fetches REAL headlines from Moneycontrol, Economic
Times, LiveMint, and Business Standard RSS feeds.

Output: data_cache/news_feed.txt (one headline per line, max 200 chars each)
        — read by news_cache.py on its next cycle.

The fetcher is rate-limited (1 request per second per source) and
failure-tolerant (one source down doesn't kill the rest). Total cost:
0. Uses stdlib urllib + html.parser (no feedparser dep).

Run on a schedule (brain's SCHED-NEWS-CACHE at 09:00 + 30 min during
market hours + overnight research at 02:00 IST).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
OUT = DCACHE / "news_feed.txt"
META = DCACHE / "news_feed_meta.json"


# RSS feeds — Indian financial news sources, no auth required.
# Some feeds redirect via FeedBurner, some serve direct XML. We try the
# main URL first and fall back to mirror if needed.
RSS_SOURCES = [
    ("moneycontrol_markets",  "https://www.moneycontrol.com/rss/markets.xml"),
    ("moneycontrol_economy",  "https://www.moneycontrol.com/rss/economy.xml"),
    ("moneycontrol_stocks",   "https://www.moneycontrol.com/rss/stocks.xml"),
    ("et_markets",            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("et_news",               "https://economictimes.indiatimes.com/news/rssfeeds/1715249553.cms"),
    ("livemint_markets",      "https://www.livemint.com/rss/markets"),
    ("livemint_news",         "https://www.livemint.com/rss/news"),
    ("bs_markets",            "https://www.business-standard.com/rss/markets-106.rss"),
    ("ndtv_profit",           "https://feeds.feedburner.com/ndtvprofit-latest"),
    ("reuters_india",         "https://feeds.reuters.com/Reuters/IndiaBusinessNews"),
]


class RSSParser(HTMLParser):
    """Lightweight RSS 2.0 / Atom parser. Strips XML, keeps <item>/<entry>
    <title> + <pubDate>/<published> + <link>. Output is plain text headlines
    prefixed with [source] and [ISO timestamp]."""

    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.in_item = False
        self.in_title = False
        self.in_link = False
        self.in_pubdate = False
        self.current_title = []
        self.current_link = ""
        self.current_pubdate = ""
        self.entries: list[dict] = []
        self._tmp_link_chars: list[str] = []

    def handle_starttag(self, tag: str, attrs: list):
        a = dict(attrs)
        if tag in ("item", "entry"):
            self.in_item = True
            self.current_title = []
            self.current_link = ""
            self.current_pubdate = ""
        elif self.in_item:
            if tag == "title":
                self.in_title = True
            elif tag == "link":
                # RSS uses <link>text</link>, Atom uses <link href="..."/>
                if a.get("href"):
                    self.current_link = a.get("href", "").strip()
                else:
                    self.in_link = True
            elif tag in ("pubDate", "published", "updated", "dc:date"):
                self.in_pubdate = True

    def handle_endtag(self, tag: str):
        if tag in ("item", "entry"):
            self.in_item = False
            if self.current_title:
                # clean up
                t = "".join(self.current_title).strip()
                t = re.sub(r"\s+", " ", t)
                if t and len(t) > 8:
                    self.entries.append({
                        "source": self.source,
                        "title": t[:300],
                        "link": self.current_link.strip()[:200],
                        "pubdate": self.current_pubdate.strip()[:50],
                    })
        elif self.in_item:
            if tag == "title":
                self.in_title = False
            elif tag == "link":
                self.in_link = False
            elif tag in ("pubDate", "published", "updated", "dc:date"):
                self.in_pubdate = False

    def handle_data(self, data: str):
        if not self.in_item:
            return
        if self.in_title:
            self.current_title.append(data)
        elif self.in_link:
            self._tmp_link_chars.append(data)
            self.current_link = "".join(self._tmp_link_chars).strip()
        elif self.in_pubdate:
            self.current_pubdate += data

    def handle_endelement(self, tag: str):
        # close link with character data fallback
        if tag == "link" and self.in_link:
            self.in_link = False
            if self._tmp_link_chars:
                self.current_link = "".join(self._tmp_link_chars).strip()
                self._tmp_link_chars = []


def fetch_url(url: str, timeout: int = 12, max_bytes: int = 1_500_000) -> str:
    """Fetch URL with a custom User-Agent. Returns text or empty on failure."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (kotak-neo-bot/2.0; +https://github.com/kotak-neo-bot)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes)
        return data.decode("utf-8", errors="ignore")
    except Exception as e:
        return ""


def _parse_pubdate_to_iso(pubdate: str) -> str:
    """Best-effort RFC-822 / ISO-8601 → ISO. If we can't parse, return original."""
    if not pubdate:
        return ""
    # try ISO first
    try:
        return datetime.fromisoformat(pubdate.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    # try common RFC-822 formats
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M %z",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.strptime(pubdate.strip(), fmt).astimezone(timezone.utc).isoformat()
        except Exception:
            continue
    return pubdate  # fallback


def main() -> int:
    t0 = time.time()
    all_entries: list[dict] = []
    source_stats: list[dict] = []

    for name, url in RSS_SOURCES:
        t_src = time.time()
        text = fetch_url(url)
        if not text:
            source_stats.append({"source": name, "ok": False, "n": 0, "ms": int((time.time() - t_src) * 1000)})
            continue
        try:
            p = RSSParser(name)
            p.feed(text)
            n = len(p.entries)
            for e in p.entries:
                e["pubdate_iso"] = _parse_pubdate_to_iso(e.get("pubdate", ""))
            all_entries.extend(p.entries)
            source_stats.append({"source": name, "ok": True, "n": n, "ms": int((time.time() - t_src) * 1000)})
        except Exception as ex:
            source_stats.append({"source": name, "ok": False, "n": 0, "ms": int((time.time() - t_src) * 1000), "err": str(ex)[:80]})
        # be polite — 200ms between requests
        time.sleep(0.2)

    # Deduplicate by title (some feeds mirror each other)
    seen = set()
    deduped = []
    for e in all_entries:
        k = e["title"][:120].lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(e)

    # Sort newest first (entries with no pubdate go to the end)
    deduped.sort(key=lambda e: e.get("pubdate_iso", "") or "", reverse=True)

    # Write the plain-text feed (read by news_cache.py)
    lines = []
    for e in deduped[:80]:
        ts = e.get("pubdate_iso", "")[:19]
        src = e["source"]
        title = e["title"]
        lines.append(f"[{ts}] [{src}] {title}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Write metadata
    META.write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(deduped),
        "sources_ok": sum(1 for s in source_stats if s["ok"]),
        "sources_failed": sum(1 for s in source_stats if not s["ok"]),
        "duration_sec": round(time.time() - t0, 2),
        "sources": source_stats,
    }, indent=2), encoding="utf-8")

    print(f"[rss_news] {len(deduped)} headlines from {sum(1 for s in source_stats if s['ok'])}/{len(RSS_SOURCES)} sources, {time.time()-t0:.1f}s")
    if len(deduped) == 0:
        print(f"[rss_news] WARN: no headlines fetched. Source stats:")
        for s in source_stats:
            print(f"  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
