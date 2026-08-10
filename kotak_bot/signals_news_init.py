"""News pipeline init helper.
Lazily imports and constructs the NewsPipeline. Returns None if not available.
Uses MiniMax M2.7-highspeed as LLM judge if configured.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger


def get_news_pipeline(cfg: dict):
    """Initialize news pipeline if available. Returns NewsPipeline or None."""
    try:
        from signals.news import NewsPipeline
        news_cfg = cfg.get("data", {}).get("news", {})
        if not news_cfg.get("sources"):
            return None
        return NewsPipeline(config=news_cfg)
    except Exception:
        return None


def get_llm_judge(cfg: dict):
    """Initialize the LLM news judge (MiniMax by default). Returns LLMNewsJudge or None."""
    try:
        from kotak_bot.signals.llm_judge import LLMNewsJudge
        llm_cfg = cfg.get("data", {}).get("news", {}).get("llm_judge", {})
        if not llm_cfg.get("enabled", True):
            logger.info("LLM judge disabled in config")
            return None
        return LLMNewsJudge(config=llm_cfg)
    except Exception as e:
        logger.warning(f"LLM judge init failed: {e}")
        return None
