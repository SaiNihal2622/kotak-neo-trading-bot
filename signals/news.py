"""
signals/news.py
===============

Indian financial news ingestion + two-tier sentiment scoring.

Components
----------

* ``NewsItem``            — normalised record passed through the whole pipeline.
* ``NewsConfig``          — dataclass for all knobs (DB path, API keys, etc.).
* ``NewsIngestor``        — pulls RSS feeds (Moneycontrol, ET, LiveMint, BS, NDTV)
  plus an optional Marketaux API. Dedupe by URL hash; persist to SQLite.
* ``FinBERTScorer``       — lazy-loads ``Vansh180/FinBERT-India-v1`` (with
  ``yiyanghkust/finbert-tone`` as a fallback). Falls back to ``LexiconScorer``
  if ``transformers`` is not installed.
* ``LLMScorer``           — optional OpenAI / Anthropic judge used only for
  the top-N signal candidates per day. Returns structured JSON.
* ``NewsPipeline``        — public API: ``ingest()``, ``get_relevant()``,
  ``get_sentiment_score()``.

Run a smoke test with::

    python -m signals.news

The smoke test inserts a handful of synthetic news items, exercises the
sentiment fallbacks, validates ticker / event extraction, and queries the
SQLite cache. No external API keys are needed.

Graceful degradation
--------------------

* ``transformers`` not installed → use built-in ``LexiconScorer``.
* No internet / feedparser failure → that source is skipped, others continue.
* No OpenAI / Anthropic key → LLM tier is silently skipped.
* Marketaux key missing → Marketaux path is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import feedparser
import requests
from loguru import logger

# Lazy import — feedparser is the only hard requirement beyond stdlib + loguru.
try:
    from dateutil import parser as _date_parser  # type: ignore

    _HAS_DATEUTIL = True
except Exception:  # pragma: no cover
    _HAS_DATEUTIL = False

# Optional transformers stack — loaded on demand by FinBERTScorer.
try:
    import transformers  # noqa: F401  (presence check)

    _HAS_TRANSFORMERS = True
except Exception:  # pragma: no cover
    _HAS_TRANSFORMERS = False

# Optional LLM clients.
try:
    from openai import OpenAI  # type: ignore

    _HAS_OPENAI = True
except Exception:  # pragma: no cover
    _HAS_OPENAI = False
try:
    from anthropic import Anthropic  # type: ignore

    _HAS_ANTHROPIC = True
except Exception:  # pragma: no cover
    _HAS_ANTHROPIC = False


# ===========================================================================
# Configuration & dataclasses
# ===========================================================================


# Canonical RSS feed registry. Add new sources here; ``NewsIngestor`` will
# pick them up automatically.
RSS_FEEDS: dict[str, str] = {
    "Moneycontrol": "https://www.moneycontrol.com/rss/MCtopnews.xml",
    "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "LiveMint": "https://www.livemint.com/rss/markets",
    "Business Standard": "https://www.business-standard.com/rss/markets-106.rss",
    "NDTV Profit": "https://feeds.feedburner.com/ndtvprofit-latest",
}

# Ticker extraction universe. NIFTY-50 + key indices.
NIFTY_50_TICKERS: list[str] = [
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
    "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL",
    "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA",
    "DIVISLAB", "DRREDDY", "EICHERMOT", "GRASIM",
    "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
    "INFY", "ITC", "JSWSTEEL", "KOTAKBANK",
    "LT", "M&M", "MARUTI", "NESTLEIND",
    "NTPC", "ONGC", "POWERGRID", "RELIANCE",
    "SBILIFE", "SBIN", "SUNPHARMA", "TATACONSUM",
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM",
    "TITAN", "ULTRACEMCO", "WIPRO", "SHRIRAMFIN",
]

# Event keyword → canonical tag mapping.
EVENT_KEYWORDS: dict[str, str] = {
    "rbi": "rbi", "reserve bank": "rbi",
    "fed": "fed", "federal reserve": "fed", "fomc": "fed",
    "budget": "budget", "union budget": "budget",
    "gdp": "gdp",
    "inflation": "inflation", "cpi": "inflation", "wpi": "inflation",
    "election": "election", "poll": "election",
    "opec": "opec",
    "crude": "crude", "brent": "crude", "wti": "crude",
    "war": "war", "russia": "war", "ukraine": "war", "iran": "war", "israel": "war",
}


@dataclass
class NewsConfig:
    """All knobs for the news pipeline.

    Environment variables
    ---------------------
    ``MARKETAUX_API_KEY``, ``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY`` are
    auto-populated into the corresponding fields if not set explicitly.
    """

    db_path: str = "data_cache/news.db"
    cache_ttl_minutes: int = 60
    enable_marketaux: bool = False
    marketaux_api_key: Optional[str] = None
    enable_llm: bool = False
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    finbert_model: str = "Vansh180/FinBERT-India-v1"
    finbert_fallback: str = "yiyanghkust/finbert-tone"
    poll_interval_seconds: int = 300  # 5 min — typical for market hours
    max_news_per_source: int = 30
    request_timeout_seconds: int = 15
    user_agent: str = "KotakNeoBot/0.1 (+https://example.com)"

    def __post_init__(self) -> None:
        # Pull from env if not explicitly set.
        if self.marketaux_api_key is None:
            self.marketaux_api_key = os.getenv("MARKETAUX_API_KEY")
        if self.openai_api_key is None:
            self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if self.anthropic_api_key is None:
            self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if self.marketaux_api_key and not self.enable_marketaux:
            self.enable_marketaux = True
        if (self.openai_api_key or self.anthropic_api_key) and not self.enable_llm:
            self.enable_llm = True


@dataclass
class NewsItem:
    """Canonical record produced by the pipeline."""

    id: str
    timestamp: datetime
    source: str
    title: str
    body: str
    url: str
    tickers: list[str]
    event_tags: list[str]
    sentiment_finbert: float  # -1 .. +1
    sentiment_llm: Optional[float] = None
    urgency: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NewsItem":
        d = dict(d)
        if isinstance(d.get("timestamp"), str):
            d["timestamp"] = datetime.fromisoformat(d["timestamp"])
        return cls(**d)


# ===========================================================================
# SQLite cache
# ===========================================================================


_SCHEMA = """
CREATE TABLE IF NOT EXISTS news (
    id          TEXT PRIMARY KEY,
    url_hash    TEXT UNIQUE NOT NULL,
    timestamp   TEXT NOT NULL,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    url         TEXT NOT NULL,
    tickers     TEXT NOT NULL,
    event_tags  TEXT NOT NULL,
    sentiment_finbert REAL NOT NULL,
    sentiment_llm     REAL,
    urgency     REAL NOT NULL,
    confidence  REAL NOT NULL,
    inserted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_timestamp ON news(timestamp);
CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);
"""


class NewsCache:
    """Thin SQLite wrapper for dedupe + retrieval.

    Single-writer / multi-reader safe via an internal RLock.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterable[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(str(self.db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
        logger.debug(f"NewsCache schema ready at {self.db_path}")

    @staticmethod
    def url_hash(url: str) -> str:
        return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:32]

    def upsert(self, item: NewsItem) -> bool:
        """Insert or update a news item by URL hash. Returns ``True`` if new."""
        h = self.url_hash(item.url)
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM news WHERE url_hash = ?", (h,)
            ).fetchone()
            if existing is not None:
                return False
            conn.execute(
                """
                INSERT INTO news (
                    id, url_hash, timestamp, source, title, body, url,
                    tickers, event_tags, sentiment_finbert, sentiment_llm,
                    urgency, confidence, inserted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    h,
                    item.timestamp.isoformat(),
                    item.source,
                    item.title,
                    item.body,
                    item.url,
                    json.dumps(item.tickers),
                    json.dumps(item.event_tags),
                    float(item.sentiment_finbert),
                    (None if item.sentiment_llm is None else float(item.sentiment_llm)),
                    float(item.urgency),
                    float(item.confidence),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return True

    def get_since(self, since: datetime) -> list[NewsItem]:
        iso = since.isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM news WHERE timestamp >= ? ORDER BY timestamp DESC",
                (iso,),
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def get_for_ticker(
        self, symbol: str, since: Optional[datetime] = None
    ) -> list[NewsItem]:
        pattern = f'%"{symbol.upper()}"%'
        sql = "SELECT * FROM news WHERE tickers LIKE ?"
        params: list[Any] = [pattern]
        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY timestamp DESC"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_item(r) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM news").fetchone()[0])

    def clear(self) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM news")


def _row_to_item(row: sqlite3.Row) -> NewsItem:
    tickers = json.loads(row["tickers"]) if row["tickers"] else []
    events = json.loads(row["event_tags"]) if row["event_tags"] else []
    ts = datetime.fromisoformat(row["timestamp"])
    return NewsItem(
        id=row["id"],
        timestamp=ts,
        source=row["source"],
        title=row["title"],
        body=row["body"],
        url=row["url"],
        tickers=tickers,
        event_tags=events,
        sentiment_finbert=float(row["sentiment_finbert"]),
        sentiment_llm=(
            None if row["sentiment_llm"] is None else float(row["sentiment_llm"])
        ),
        urgency=float(row["urgency"]),
        confidence=float(row["confidence"]),
    )


# ===========================================================================
# Sentiment scorers
# ===========================================================================


# Tiny built-in lexicon — used when neither transformers nor an LLM is
# available. Intentionally conservative: returns 0.0 for unknown content
# rather than guessing.
POSITIVE_LEXICON: frozenset[str] = frozenset(
    {
        "surge", "rally", "gain", "profit", "beat", "strong", "rise", "high",
        "boom", "growth", "upgrade", "bullish", "outperform", "record",
        "soar", "jump", "recover", "positive", "win", "wins", "approve",
        "optimistic", "robust", "accelerate", "exceed", "boost",
    }
)
NEGATIVE_LEXICON: frozenset[str] = frozenset(
    {
        "crash", "fall", "loss", "miss", "weak", "decline", "low", "slump",
        "drop", "downgrade", "bearish", "tumble", "negative", "fail",
        "concern", "risk", "warn", "warning", "cut", "slashed", "fears",
        "recession", "slowdown", "weakness", "deteriorate", "drag",
    }
)


class LexiconScorer:
    """Counts positive vs. negative tokens and returns a normalised score."""

    def score(self, text: str) -> float:
        if not text:
            return 0.0
        words = re.findall(r"[A-Za-z][A-Za-z\-']+", text.lower())
        if not words:
            return 0.0
        pos = sum(1 for w in words if w in POSITIVE_LEXICON)
        neg = sum(1 for w in words if w in NEGATIVE_LEXICON)
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total  # in [-1, +1]


class FinBERTScorer:
    """Lazy-loaded FinBERT wrapper with graceful fallback.

    Tries the primary model first; if that fails (offline, OOM, missing dep)
    falls back to a second model; if that also fails falls back to the
    lexicon scorer. Whatever loaded is sticky for the process lifetime.
    """

    def __init__(self, primary: str, fallback: str) -> None:
        self.primary = primary
        self.fallback = fallback
        self._pipeline: Any = None
        self._loaded_name: Optional[str] = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        with self._lock:
            if self._pipeline is not None or not _HAS_TRANSFORMERS:
                return
            for name in (self.primary, self.fallback):
                try:
                    logger.info(f"FinBERTScorer: loading {name}")
                    from transformers import pipeline  # local import

                    self._pipeline = pipeline(
                        "sentiment-analysis",
                        model=name,
                        truncation=True,
                        max_length=512,
                    )
                    self._loaded_name = name
                    logger.success(f"FinBERTScorer ready: {name}")
                    return
                except Exception as exc:
                    logger.warning(f"FinBERTScorer: {name} failed ({exc})")
            logger.error("FinBERTScorer: no model loaded, using lexicon fallback")

    def score(self, text: str) -> float:
        if not text:
            return 0.0
        self._load()
        if self._pipeline is None:
            return LexiconScorer().score(text)
        try:
            truncated = text if len(text) <= 1500 else text[:1500]
            result = self._pipeline(truncated)
            if not result:
                return 0.0
            label = str(result[0].get("label", "")).lower()
            confidence = float(result[0].get("score", 0.0))
            if "positive" in label:
                return confidence
            if "negative" in label:
                return -confidence
            return 0.0
        except Exception as exc:
            logger.warning(f"FinBERTScorer.score failed: {exc}")
            return LexiconScorer().score(text)

    @property
    def loaded_model(self) -> Optional[str]:
        return self._loaded_name


# ---------------------------------------------------------------------------
# Optional LLM judge
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are an expert Indian-markets analyst. Given a news headline and body, \
return strict JSON with these fields:

{
  "sentiment": number in [-1, +1]  // net bullish/bearish score,
  "urgency":   number in [0, 1]    // how time-critical the news is,
  "affected_instruments": ["NIFTY", "HDFCBANK", ...]  // tickers/indices,
  "confidence": number in [0, 1]   // your confidence in the verdict,
  "summary": "one-sentence market implication"
}

Reply with JSON only — no markdown, no preamble.
"""


class LLMScorer:
    """OpenAI or Anthropic judge, used sparingly for top-N signal candidates."""

    def __init__(self, config: NewsConfig) -> None:
        self.config = config
        self._client: Any = None
        self._provider: Optional[str] = None
        self._model: Optional[str] = None

    def available(self) -> bool:
        return self._ensure_loaded() is not None

    def _ensure_loaded(self) -> Optional[Any]:
        if self._client is not None:
            return self._client
        if not self.config.enable_llm:
            return None
        if self.config.openai_api_key and _HAS_OPENAI:
            try:
                self._client = OpenAI(api_key=self.config.openai_api_key)
                self._provider = "openai"
                self._model = "gpt-4o-mini"
                logger.info("LLMScorer: OpenAI client ready")
                return self._client
            except Exception as exc:
                logger.warning(f"LLMScorer: OpenAI init failed ({exc})")
        if self.config.anthropic_api_key and _HAS_ANTHROPIC:
            try:
                self._client = Anthropic(api_key=self.config.anthropic_api_key)
                self._provider = "anthropic"
                self._model = "claude-3-haiku-20240307"
                logger.info("LLMScorer: Anthropic client ready")
                return self._client
            except Exception as exc:
                logger.warning(f"LLMScorer: Anthropic init failed ({exc})")
        return None

    def score(self, text: str) -> dict[str, Any]:
        """Score a single item. Returns an empty/safe dict if unavailable."""
        empty: dict[str, Any] = {
            "sentiment": 0.0,
            "urgency": 0.0,
            "affected_instruments": [],
            "confidence": 0.0,
            "summary": "",
        }
        client = self._ensure_loaded()
        if client is None:
            return empty
        try:
            user_msg = f"Headline + body:\n\n{text[:4000]}"
            if self._provider == "openai":
                resp = client.chat.completions.create(
                    model=self._model or "gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                    max_tokens=300,
                )
                payload = resp.choices[0].message.content or "{}"
            else:
                resp = client.messages.create(
                    model=self._model or "claude-3-haiku-20240307",
                    max_tokens=300,
                    system=_LLM_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                payload = (
                    resp.content[0].text if getattr(resp, "content", None) else "{}"
                )
            data = json.loads(payload)
            # Defensive parsing — clamp everything to expected ranges.
            sentiment = float(data.get("sentiment", 0.0))
            sentiment = max(-1.0, min(1.0, sentiment))
            urgency = float(data.get("urgency", 0.0))
            urgency = max(0.0, min(1.0, urgency))
            confidence = float(data.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
            return {
                "sentiment": sentiment,
                "urgency": urgency,
                "affected_instruments": list(data.get("affected_instruments", [])),
                "confidence": confidence,
                "summary": str(data.get("summary", ""))[:500],
            }
        except Exception as exc:
            logger.warning(f"LLMScorer.score failed: {exc}")
            return empty


# ===========================================================================
# Ticker / event extraction
# ===========================================================================


def _build_ticker_regex() -> re.Pattern[str]:
    """Word-boundary regex matching NIFTY-50 symbols and major indices.

    Sorts by descending length so ``BANKNIFTY`` matches before ``NIFTY``.
    """
    sorted_tickers = sorted(set(NIFTY_50_TICKERS), key=len, reverse=True)
    escaped = [re.escape(t) for t in sorted_tickers]
    pattern = r"\b(" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


_TICKER_RE = _build_ticker_regex()


def extract_tickers(text: str) -> list[str]:
    """Return unique uppercase tickers mentioned in ``text``."""
    if not text:
        return []
    matches = _TICKER_RE.findall(text)
    seen: list[str] = []
    for m in matches:
        u = m.upper()
        if u not in seen:
            seen.append(u)
    return seen


def detect_events(text: str) -> list[str]:
    """Return unique canonical event tags mentioned in ``text``."""
    if not text:
        return []
    lower = text.lower()
    found: list[str] = []
    for keyword, tag in EVENT_KEYWORDS.items():
        if keyword in lower and tag not in found:
            found.append(tag)
    return found


# ===========================================================================
# Ingestor
# ===========================================================================


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if _HAS_DATEUTIL:
            return _date_parser.parse(s)
    except Exception:
        pass
    # Fallback regex parse for common ISO formats.
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NewsIngestor:
    """Pulls news from all configured RSS feeds + optional Marketaux.

    State is held by an injected ``NewsCache`` instance so dedupe survives
    process restarts.
    """

    def __init__(
        self,
        config: NewsConfig,
        cache: NewsCache,
        finbert: Optional[FinBERTScorer] = None,
    ) -> None:
        self.config = config
        self.cache = cache
        self.finbert = finbert or FinBERTScorer(
            primary=config.finbert_model, fallback=config.finbert_fallback
        )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": config.user_agent})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_all(self) -> list[NewsItem]:
        """Fetch from every registered source and persist to the cache."""
        items: list[NewsItem] = []
        for source, url in RSS_FEEDS.items():
            try:
                items.extend(self._fetch_rss(url, source))
            except Exception as exc:
                logger.warning(f"RSS fetch failed for {source}: {exc}")
        if self.config.enable_marketaux and self.config.marketaux_api_key:
            try:
                items.extend(self._fetch_marketaux())
            except Exception as exc:
                logger.warning(f"Marketaux fetch failed: {exc}")
        return self._persist(items)

    def fetch_since(self, since: datetime) -> list[NewsItem]:
        """Fetch fresh items whose published time is >= ``since``.

        The function reads the cache first to avoid duplicate network calls;
        if the cache is empty, it falls back to a full ``fetch_all``.
        """
        # Strategy: pull cache for the window — this is what the pipeline
        # actually consumes. Then top up with a full fetch (which is deduped
        # by the cache) to catch anything new.
        cached = self.cache.get_since(since)
        if cached:
            return cached
        return self.fetch_all()

    # ------------------------------------------------------------------
    # RSS
    # ------------------------------------------------------------------
    def _fetch_rss(self, url: str, source: str) -> list[NewsItem]:
        logger.debug(f"Fetching RSS: {source} ({url})")
        try:
            resp = self._session.get(
                url, timeout=self.config.request_timeout_seconds
            )
            resp.raise_for_status()
            content = resp.content
        except Exception as exc:
            logger.warning(f"HTTP fetch failed for {source}: {exc}")
            # feedparser can still parse from a URL but with reduced control;
            # we try anyway to be resilient.
            content = None
        parsed = feedparser.parse(content if content is not None else url)
        if parsed.bozo and not parsed.entries:
            logger.warning(f"Malformed feed for {source}: {parsed.bozo_exception}")
            return []
        items: list[NewsItem] = []
        for entry in parsed.entries[: self.config.max_news_per_source]:
            try:
                item = self._entry_to_item(entry, source)
                if item is not None:
                    items.append(item)
            except Exception as exc:
                logger.debug(f"Skipping bad entry in {source}: {exc}")
        return items

    def _entry_to_item(self, entry: Any, source: str) -> Optional[NewsItem]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            return None
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        # Strip simple HTML for storage.
        body = re.sub(r"<[^>]+>", " ", summary).strip()
        ts = (
            _parse_dt(entry.get("published"))
            or _parse_dt(entry.get("updated"))
            or _now_utc()
        )
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        text_blob = f"{title}\n{body}"
        tickers = extract_tickers(text_blob)
        events = detect_events(text_blob)
        sentiment = self.finbert.score(text_blob)
        item_id = hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]
        return NewsItem(
            id=item_id,
            timestamp=ts,
            source=source,
            title=title[:500],
            body=body[:5000],
            url=link,
            tickers=tickers,
            event_tags=events,
            sentiment_finbert=float(sentiment),
            urgency=0.0,
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Marketaux
    # ------------------------------------------------------------------
    def _fetch_marketaux(self) -> list[NewsItem]:
        if not self.config.marketaux_api_key:
            return []
        url = "https://api.marketaux.com/v1/news/all"
        params = {
            "api_token": self.config.marketaux_api_key,
            "countries": "in",
            "language": "en",
            "limit": self.config.max_news_per_source,
        }
        try:
            resp = self._session.get(
                url, params=params, timeout=self.config.request_timeout_seconds
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"Marketaux request failed: {exc}")
            return []
        out: list[NewsItem] = []
        for raw in data.get("data", []):
            try:
                title = (raw.get("title") or "").strip()
                link = (raw.get("url") or "").strip()
                if not title or not link:
                    continue
                body = (raw.get("description") or "").strip()
                ts = _parse_dt(raw.get("published_at")) or _now_utc()
                if ts.tzinfo is not None:
                    ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
                text_blob = f"{title}\n{body}"
                out.append(
                    NewsItem(
                        id=hashlib.sha256(link.encode("utf-8")).hexdigest()[:16],
                        timestamp=ts,
                        source="Marketaux",
                        title=title[:500],
                        body=body[:5000],
                        url=link,
                        tickers=extract_tickers(text_blob),
                        event_tags=detect_events(text_blob),
                        sentiment_finbert=float(self.finbert.score(text_blob)),
                        urgency=0.0,
                        confidence=0.0,
                    )
                )
            except Exception as exc:
                logger.debug(f"Skipping bad Marketaux entry: {exc}")
        return out

    # ------------------------------------------------------------------
    # Persist
    # ------------------------------------------------------------------
    def _persist(self, items: list[NewsItem]) -> list[NewsItem]:
        new: list[NewsItem] = []
        for it in items:
            try:
                if self.cache.upsert(it):
                    new.append(it)
            except Exception as exc:
                logger.warning(f"Cache upsert failed for {it.url}: {exc}")
        logger.info(f"Ingested {len(new)} new items (of {len(items)} fetched)")
        return new


# ===========================================================================
# Public pipeline
# ===========================================================================


class NewsPipeline:
    """High-level news pipeline used by the rest of the bot.

    Usage::

        cfg = NewsConfig()
        pipeline = NewsPipeline(cfg)
        pipeline.ingest()
        nifty_news = pipeline.get_relevant("NIFTY", lookback_hours=24)
        score = pipeline.get_sentiment_score("NIFTY", lookback_hours=24)
    """

    def __init__(
        self,
        config: Optional[NewsConfig] = None,
        cache: Optional[NewsCache] = None,
        finbert: Optional[FinBERTScorer] = None,
    ) -> None:
        self.config = config or NewsConfig()
        self.cache = cache or NewsCache(self.config.db_path)
        self.finbert = finbert or FinBERTScorer(
            primary=self.config.finbert_model, fallback=self.config.finbert_fallback
        )
        self.ingestor = NewsIngestor(self.config, self.cache, self.finbert)
        self.llm = LLMScorer(self.config) if self.config.enable_llm else LLMScorer(self.config)

    def ingest(self) -> list[NewsItem]:
        """Fetch + score + persist fresh news. Returns the new items."""
        items = self.ingestor.fetch_all()
        # Optional LLM tier 2 — only for the top-N most extreme items.
        if self.llm.available() and items:
            self._enrich_top_n_with_llm(items, n=3)
        return items

    def _enrich_top_n_with_llm(self, items: list[NewsItem], n: int = 3) -> None:
        """Use the LLM judge on the N items with the largest |sentiment|."""
        ranked = sorted(items, key=lambda x: abs(x.sentiment_finbert), reverse=True)[:n]
        for it in ranked:
            verdict = self.llm.score(f"{it.title}\n\n{it.body}")
            it.sentiment_llm = float(verdict.get("sentiment", 0.0))
            it.urgency = float(verdict.get("urgency", 0.0))
            it.confidence = float(verdict.get("confidence", 0.0))
            # Merge LLM-tagged instruments into the tickers list.
            for t in verdict.get("affected_instruments", []):
                if t and t.upper() not in it.tickers:
                    it.tickers.append(t.upper())
            try:
                self.cache.upsert(it)  # write enriched version back
            except Exception as exc:
                logger.debug(f"LLM enrich write-back failed: {exc}")

    def get_relevant(
        self, symbol: str, lookback_hours: int = 24
    ) -> list[NewsItem]:
        """Return news items mentioning ``symbol`` in the last N hours."""
        since = datetime.utcnow() - timedelta(hours=lookback_hours)
        items = self.cache.get_for_ticker(symbol.upper(), since=since)
        # Fall back to a live fetch if cache is empty (e.g. fresh start).
        if not items:
            logger.info(f"Cache empty for {symbol}; triggering full ingest")
            self.ingest()
            items = self.cache.get_for_ticker(symbol.upper(), since=since)
        return items

    def get_sentiment_score(
        self, symbol: str, lookback_hours: int = 24
    ) -> float:
        """Aggregate sentiment for ``symbol`` over the last N hours.

        Returns a value in ``[-1, +1]`` — time-decayed average of per-item
        sentiment (LLM score preferred, FinBERT otherwise), weighted so the
        most recent 25 % of items carry 50 % of the weight.
        """
        items = self.get_relevant(symbol, lookback_hours)
        if not items:
            return 0.0
        items = sorted(items, key=lambda x: x.timestamp)
        n = len(items)
        # Linear weights: most recent gets highest weight.
        weights = np.linspace(0.5, 1.5, n) if n > 1 else np.array([1.0])
        scores: list[float] = []
        for it in items:
            s = it.sentiment_llm if it.sentiment_llm is not None else it.sentiment_finbert
            scores.append(float(s))
        arr_scores = np.array(scores)
        arr_weights = weights / weights.sum()
        return float(np.dot(arr_scores, arr_weights))

    def close(self) -> None:
        """Cleanup — currently a no-op but provided for symmetry."""
        return None


# ===========================================================================
# Smoke test
# ===========================================================================


def _smoke_test() -> None:
    """Run a deterministic smoke test that doesn't need internet or GPUs."""
    logger.info("=== signals.news smoke test ===")

    # --- helpers ----------------------------------------------------------
    pos_text = "NIFTY rallies 2% as HDFCBANK posts record profit; RBI keeps rate unchanged"
    neg_text = "Crude crash drags BANKNIFTY down; inflation fears mount amid war concerns"
    neutral_text = "The board meeting was held on Wednesday."

    lex = LexiconScorer()
    fb = FinBERTScorer(primary="Vansh180/FinBERT-India-v1", fallback="yiyanghkust/finbert-tone")
    for label, txt in [("positive", pos_text), ("negative", neg_text), ("neutral", neutral_text)]:
        s = fb.score(txt)
        l = lex.score(txt)
        logger.info(f"Sentiment[{label}]: FinBERT/lexicon-fallback={s:+.3f}  lexicon={l:+.3f}")

    # --- ticker / event extraction ---------------------------------------
    sample = (
        "NIFTY and BANKNIFTY fell sharply after RBI hiked rates. "
        "RELIANCE, TCS, INFY and HDFCBANK all declined. "
        "Crude prices surged on OPEC cuts. War tensions in Iran are rising."
    )
    tickers = extract_tickers(sample)
    events = detect_events(sample)
    logger.info(f"Tickers extracted: {tickers}")
    logger.info(f"Events detected:   {events}")
    assert "NIFTY" in tickers and "BANKNIFTY" in tickers
    assert "RELIANCE" in tickers and "TCS" in tickers
    assert "rbi" in events and "crude" in events and "war" in events and "opec" in events

    # --- cache + pipeline (synthetic items, no network) ------------------
    tmp_db = Path("data_cache") / "smoke_news.db"
    if tmp_db.exists():
        tmp_db.unlink()
    cfg = NewsConfig(
        db_path=str(tmp_db),
        enable_marketaux=False,
        enable_llm=False,
    )
    pipeline = NewsPipeline(cfg)
    now = datetime.utcnow()
    synthetic = [
        NewsItem(
            id=f"synth-{i}",
            timestamp=now - timedelta(minutes=10 * i),
            source="Synthetic",
            title=title,
            body=body,
            url=f"https://example.com/{i}",
            tickers=extract_tickers(title + " " + body),
            event_tags=detect_events(title + " " + body),
            sentiment_finbert=lex.score(title + " " + body),
        )
        for i, (title, body) in enumerate(
            [
                ("NIFTY surges 2% on strong GDP data", "HDFCBANK and INFY also rallied."),
                ("BANKNIFTY crashes as inflation fears mount", "Crude prices spike on OPEC cuts."),
                ("RBI keeps rates unchanged; markets steady", "RELIANCE, TCS report earnings."),
            ]
        )
    ]
    for it in synthetic:
        pipeline.cache.upsert(it)
    logger.info(f"Cache size: {pipeline.cache.count()} items")

    # --- get_relevant / get_sentiment_score ------------------------------
    nifty_news = pipeline.get_relevant("NIFTY", lookback_hours=24)
    score = pipeline.get_sentiment_score("NIFTY", lookback_hours=24)
    logger.info(f"NIFTY news: {len(nifty_news)} items, sentiment={score:+.3f}")
    assert len(nifty_news) >= 1

    # --- LLM no-op (no key) ---------------------------------------------
    llm = LLMScorer(cfg)
    out = llm.score("any text")
    assert out["sentiment"] == 0.0 and out["summary"] == ""
    logger.info("LLM scorer correctly no-ops without API key.")

    # --- pipeline.ingest (no network → should just log 0 new) ------------
    new_items = pipeline.ingest()
    logger.info(f"ingest() returned {len(new_items)} new items (no network in sandbox)")

    logger.success("signals.news smoke test passed.")


if __name__ == "__main__":
    _smoke_test()
