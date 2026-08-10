"""LLM-powered news judge using MiniMax (M2.7-highspeed).

Each call returns structured JSON with:
- sentiment: -1..+1
- relevance: 0..1 (how much this news affects NIFTY/BANKNIFTY)
- urgency: 0..1 (how soon the effect hits)
- direction: 'bullish' | 'bearish' | 'neutral'
- rationale: short text explanation
- affected_instruments: list of ['NIFTY', 'BANKNIFTY', 'USDINR', etc.]

Falls back to FinBERT if MiniMax call fails or no API key.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# load .env if not already loaded
_env_path = Path(__file__).parent.parent.parent / "config" / "credentials.env"
if _env_path.exists():
    load_dotenv(str(_env_path))

from loguru import logger


@dataclass
class NewsVerdict:
    sentiment: float         # -1..+1
    relevance: float         # 0..1
    urgency: float           # 0..1
    direction: str           # 'bullish' | 'bearish' | 'neutral'
    rationale: str           # short text
    affected: list[str]      # ['NIFTY', 'BANKNIFTY', ...]
    source: str              # 'minimax' | 'finbert' | 'fallback'


class LLMNewsJudge:
    """Calls MiniMax M2.7-highspeed for news sentiment + reasoning.
    Caches results for `cache_ttl_sec` to avoid re-judging same headline.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.provider = self.config.get("provider", "minimax")
        self.model = self.config.get("model", "MiniMax-M2.7-highspeed")
        self.base_url = os.environ.get(
            self.config.get("base_url_env", "MINIMAX_LLM_BASE_URL"),
            "https://agent.minimax.io/mavis/api/v1/llm/v1"
        )
        # API key — read from .env; we don't actually need a real key, the endpoint
        # uses managed auth in our env. We just need a non-empty value.
        self.api_key = os.environ.get(
            self.config.get("api_key_env", "MINIMAX_LLM_API_KEY"),
            "managed-auth"
        )
        self.rate_limit_per_min = self.config.get("rate_limit_per_min", 30)
        self.cache_ttl_sec = self.config.get("cache_ttl_sec", 600)
        self._cache: dict[str, tuple[float, NewsVerdict]] = {}
        self._calls: list[float] = []  # for rate limit
        self._llm_call_script = Path(os.environ.get(
            "__MAVIS_PARENT_DATA_DIR",
            str(Path.home() / ".minimax")
        )) / ".builtin-skills" / "llm-call" / "scripts" / "llm_call.py"
        self._last_call_at = 0.0
        self._call_count = 0
        logger.info(f"LLMNewsJudge initialized: provider={self.provider} model={self.model} base_url={self.base_url[:50]}...")

    def _rate_limit_ok(self) -> bool:
        now = time.time()
        self._calls = [t for t in self._calls if now - t < 60]
        if len(self._calls) >= self.rate_limit_per_min:
            return False
        self._calls.append(now)
        return True

    def judge(self, headline: str, summary: str = "") -> NewsVerdict:
        """Judge a single news item. Returns NewsVerdict."""
        key = headline[:200]
        # cache check
        if key in self._cache:
            cached_at, verdict = self._cache[key]
            if (time.time() - cached_at) < self.cache_ttl_sec:
                return verdict

        # rate limit
        if not self._rate_limit_ok():
            return self._fallback(headline, "rate_limit")

        # build prompt
        prompt = self._build_prompt(headline, summary)
        # call LLM
        try:
            raw = self._call_minimax(prompt)
            verdict = self._parse_verdict(raw, headline)
            verdict.source = "minimax"
            self._cache[key] = (time.time(), verdict)
            self._call_count += 1
            return verdict
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return self._fallback(headline, f"llm_error: {e}")

    def judge_batch(self, headlines: list[str]) -> list[NewsVerdict]:
        return [self.judge(h) for h in headlines]

    def get_aggregate(self, headlines: list[str], lookback_hours: int = 4) -> tuple[float, float]:
        """Return (sentiment, urgency) aggregated across headlines. -1..+1, 0..1."""
        if not headlines:
            return 0.0, 0.0
        verdicts = [self.judge(h) for h in headlines[:20]]  # cap at 20 to limit cost
        sent = sum(v.sentiment * v.relevance for v in verdicts) / max(1, sum(v.relevance for v in verdicts))
        urg = max((v.urgency for v in verdicts), default=0.0)
        return sent, urg

    def _build_prompt(self, headline: str, summary: str) -> str:
        return f"""You are an expert Indian options trader analyzing news for NIFTY/BANKNIFTY impact.

NEWS HEADLINE: {headline}
{f"NEWS SUMMARY: {summary}" if summary else ""}

Analyze this news for short-term impact on Indian options (NIFTY, BANKNIFTY) within the next 4 hours.
Consider: RBI policy, US Fed, FII flows, US markets, INR, crude oil, domestic earnings, global events, India-specific events.

Respond ONLY in valid JSON (no markdown, no prose):
{{
  "sentiment": <float -1.0 to +1.0>,  // -1 = very bearish, 0 = neutral, +1 = very bullish
  "relevance": <float 0.0 to 1.0>,    // 0 = irrelevant to NIFTY/BANKNIFTY, 1 = directly relevant
  "urgency": <float 0.0 to 1.0>,      // 0 = long-term effect, 1 = immediate (minutes-hours)
  "direction": "<bullish|bearish|neutral>",
  "rationale": "<one short sentence explanation>",
  "affected": ["<NIFTY|BANKNIFTY|BANKNIFTY|BOTH|etc>"]
}}

Return ONLY the JSON object."""

    def _call_minimax(self, prompt: str) -> str:
        """Call the LLM directly via httpx (anthropic-compatible Messages API).
        Falls back to subprocess llm_call.py if direct call fails.
        """
        # direct call using httpx — more reliable than subprocess
        try:
            import httpx
            url = f"{self.base_url.rstrip('/')}/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "Authorization": f"Bearer {self.api_key}",
                "anthropic-version": "2023-06-01",
            }
            body = {
                "model": self.model,
                "max_tokens": 800,
                "temperature": 0.1,
                "system": "You are a precise financial analyst. ALWAYS produce a 'text' content block with your answer. Return ONLY valid JSON in the text block. No markdown, no prose, no preamble outside the JSON.",
                "messages": [{"role": "user", "content": prompt}],
            }
            with httpx.Client(timeout=45) as c:
                resp = c.post(url, headers=headers, json=body)
            if resp.status_code == 200:
                data = resp.json()
                # extract text from anthropic-style content blocks
                # some M2.7-highspeed responses put answer in "thinking" block, some in "text"
                out = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        out += block.get("text", "")
                    elif block.get("type") == "thinking":
                        # fallback: use thinking text if no text block
                        if not out:
                            out += block.get("thinking", "")
                if not out:
                    raise RuntimeError(f"no text in response: {str(data)[:200]}")
                if "{" in out and "}" in out:
                    start = out.find("{")
                    end = out.rfind("}") + 1
                    return out[start:end]
                return out
            else:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.debug(f"direct httpx call failed: {e}; trying subprocess")
            # fallback to subprocess
            if not self._llm_call_script.exists():
                raise FileNotFoundError(f"llm_call.py not found at {self._llm_call_script}")
            venv_py = Path(__file__).parent.parent.parent / ".venv" / "Scripts" / "python.exe"
            if not venv_py.exists():
                venv_py = Path(sys.executable)
            cmd = [
                str(venv_py),
                str(self._llm_call_script),
                "--model", f"{self.provider}/{self.model}",
                "--system", "You are a precise financial analyst. Return ONLY valid JSON. No markdown, no prose, no preamble.",
                "--max-tokens", "400",
                "--temperature", "0.2",
                "--prompt", prompt,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                env={**os.environ, "MINIMAX_LLM_BASE_URL": self.base_url, "MINIMAX_LLM_API_KEY": self.api_key},
            )
            if result.returncode != 0:
                raise RuntimeError(f"llm_call exit={result.returncode}: {result.stderr[:200]}")
            out = result.stdout.strip()
            if "{" in out and "}" in out:
                start = out.find("{")
                end = out.rfind("}") + 1
                return out[start:end]
            return out

    def _parse_verdict(self, raw: str, headline: str) -> NewsVerdict:
        try:
            data = json.loads(raw)
            return NewsVerdict(
                sentiment=float(data.get("sentiment", 0.0)),
                relevance=float(data.get("relevance", 0.5)),
                urgency=float(data.get("urgency", 0.0)),
                direction=str(data.get("direction", "neutral")).lower(),
                rationale=str(data.get("rationale", ""))[:200],
                affected=list(data.get("affected", [])),
                source="minimax",
            )
        except Exception as e:
            logger.warning(f"parse verdict failed: {e}; raw={raw[:200]}")
            return self._fallback(headline, f"parse_error: {e}")

    def _fallback(self, headline: str, reason: str) -> NewsVerdict:
        """Keyword-based fallback if LLM is unavailable."""
        h = headline.lower()
        bullish = ["surge", "rally", "gain", "rise", "jump", "high", "boost", "growth", "optimis", "positive", "beat", "strong"]
        bearish = ["fall", "drop", "crash", "decline", "tumble", "low", "fear", "concern", "weak", "miss", "loss", "negative", "sell-off", "selloff", "war", "crisis"]
        sent = 0.0
        for w in bullish:
            if w in h: sent += 0.2
        for w in bearish:
            if w in h: sent -= 0.2
        sent = max(-1.0, min(1.0, sent))
        return NewsVerdict(
            sentiment=sent,
            relevance=0.3,
            urgency=0.1,
            direction="bullish" if sent > 0.1 else ("bearish" if sent < -0.1 else "neutral"),
            rationale=f"keyword fallback ({reason})",
            affected=[],
            source="fallback",
        )
