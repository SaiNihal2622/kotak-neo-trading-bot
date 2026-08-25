"""News cache writer — periodically queries LLM news judge, writes aggregate JSON.

Decoupled from thesis_engine so the engine stays sub-second and the LLM
call (5-15s) happens on its own cadence.

Cron: every 30 min during market hours, plus once at 08:00 premarket.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

try:
    from dotenv import load_dotenv
    _env = ROOT / "config" / "credentials.env"
    if _env.exists():
        load_dotenv(str(_env))
except Exception:
    pass

from loguru import logger

from kotak_bot.utils.clock import now_ist
from kotak_bot.signals.llm_judge import LLMNewsJudge

CACHE = ROOT / "data_cache" / "news_aggregate.json"


def _gather_headlines() -> list[str]:
    """Best-effort headline collection. Wire real news source here later.

    For now: pull headlines from bot log tail (FII/DII/macro mentions),
    plus any news cache file. In production this should be a real RSS /
    news API pull (MoneyControl, ET, Reuters, Bloomberg headlines).
    """
    heads: list[str] = []

    # Bot log tail (FII/DII mentions are very predictive)
    log = ROOT / "logs" / "bot.log"
    if log.exists():
        try:
            for line in log.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]:
                low = line.lower()
                if any(w in low for w in (
                    "fii", "dii", "rbi", "fed", "fomc", "cpi", "inflation",
                    "gdp", "opec", "crude", "russia", "ukraine", "israel",
                    "iran", "tariff", "earnings", "policy", "war",
                    "election", "geopolitical", "monetary", "nifty",
                    "banknifty", "sensex", "nse",
                )):
                    heads.append(line.strip()[:200])
                if len(heads) >= 30:
                    break
        except Exception:
            pass

    # External news cache (writeable by user / external scripts)
    extra = ROOT / "data_cache" / "news_feed.txt"
    if extra.exists():
        try:
            heads.extend(extra.read_text(encoding="utf-8", errors="ignore").splitlines()[:30])
        except Exception:
            pass

    return heads[:30]


def refresh() -> dict:
    """Query LLM judge, write aggregate, return it."""
    headlines = _gather_headlines()
    if not headlines:
        out = {
            "ts": now_ist().isoformat(timespec="seconds"),
            "score": 0.0,
            "n": 0,
            "headlines": [],
            "source": "empty",
        }
        CACHE.write_text(json.dumps(out, indent=2), encoding="utf-8")
        logger.info("news_cache: no headlines found, writing zero aggregate")
        return out

    try:
        judge = LLMNewsJudge()
        score, n = judge.get_aggregate(headlines, lookback_hours=4)
        out = {
            "ts": now_ist().isoformat(timespec="seconds"),
            "score": float(score),
            "n": int(n),
            "headlines": headlines[:10],
            "source": "llm_judge",
        }
        CACHE.write_text(json.dumps(out, indent=2), encoding="utf-8")
        logger.info(f"news_cache: score={score:+.2f} n={n} headlines_analyzed={len(headlines)}")
        return out
    except Exception as e:
        logger.error(f"news_cache: LLM judge failed: {e}")
        out = {
            "ts": now_ist().isoformat(timespec="seconds"),
            "score": 0.0,
            "n": 0,
            "headlines": headlines[:10],
            "source": "error",
            "error": str(e),
        }
        CACHE.write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out


def main() -> int:
    t0 = time.time()
    out = refresh()
    print(json.dumps(out, indent=2, default=str))
    logger.info(f"news_cache: refresh took {int((time.time()-t0)*1000)}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
