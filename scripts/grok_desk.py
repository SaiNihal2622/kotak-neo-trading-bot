"""grok_desk.py — 6-role LLM trading desk for Indian NIFTY/BNF options.

DESIGN (2026-09-08): inspired by @MSBIntel's GROK BOT Desk (PDF guide shared
by the user, 4 pages, 6 role prompts). The Grok Bot uses Grok-4-fast (xAI).
We use the same architecture with our existing minimax M2.7-highspeed
provider, which is already configured in the bot's LLMNewsJudge.

The 6 roles, adapted for Indian weekly options:
  01 SCANNER  : NIFTY/BNF option chain unusual activity (volume, OI, IV)
  02 HUNTER   : Setup detection (range break, retest, failed move) on NIFTY/BNF
  03 NEWS     : Filter relevant news (RBI, FII/DII, US, INR, crude, earnings)
  04 WHALES   : Track FII/DII flows, OI build-up, large block deals
  05 RISK     : Apply risk rules (5% per trade, 6 max positions, etc.)
  06 HEAD     : Confluence filter — speak only if 2+ roles agree on
               something material that the human needs to act on.
               Default output: QUIET DAY. Speak rarely.

Each role is a focused LLM call (~300-500 tokens). Total cost per cycle
is roughly 6 calls × 400 tokens = 2,400 tokens. At our current rate
limit (30/min), we can run the desk every 15 minutes as designed.

DATA SOURCES (all already collected by the bot):
  - data_cache/option_chain_NIFTY.json, option_chain_BANKNIFTY.json
  - data_cache/intraday_levels.json (session opens, prior close, PDH/PDL)
  - data_cache/oi_snapshots/ (rolling OI history)
  - data_cache/news_aggregate.json (last LLM-scored headlines)
  - data_cache/last_quant_actions.json (most recent brain decisions)
  - data_cache/paper_state.json (positions, P&L)
  - data_cache/fii_dii.json (if cached) or via macro_cal.refresh()

OUTPUT CHANNELS:
  - data_cache/grok_desk_state.json  : last full desk output
  - data_cache/grok_desk_history.jsonl : append-only log
  - Telegram alert ONLY when head-of-desk speaks (no QUIET DAY spam)

This is a PARALLEL module — it does not replace the existing LLM brain
in scripts/quant_service.py. It runs alongside and provides an
independent second opinion. The head-of-desk alert shows the user a
focused brief, separate from the brain's full reasoning.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from loguru import logger


# ----- paths -----
ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
STATE_PATH = DCACHE / "grok_desk_state.json"
HISTORY_PATH = DCACHE / "grok_desk_history.jsonl"


def _load_credentials_env() -> None:
    """Auto-load credentials.env into os.environ so MINIMAX_LLM_API_KEY is
    available even when the script is run outside the bot's venv (e.g. by
    cron, by the daily_autonomy scheduler, or by tests)."""
    cred = ROOT / "config" / "credentials.env"
    if not cred.exists():
        return
    try:
        for line in cred.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass


_load_credentials_env()


# ----- LLM config (matches the bot's existing minimax config) -----
LLM_BASE_URL = os.environ.get(
    "MINIMAX_LLM_BASE_URL", "https://agent.minimax.io/mavis/api/v1/llm/v1"
)
LLM_API_KEY = os.environ.get("MINIMAX_LLM_API_KEY", "")
LLM_MODEL = "MiniMax-M2.7-highspeed"


# ----- role system prompts (6 roles) -----
# Each role is intentionally short and focused — same philosophy as the
# Grok Bot guide. The system prompt is the "personality", the user message
# is the data + instruction.

SYSTEM_SCANNER = """You are the scanner on a small Indian options trading desk.
Input: NIFTY/BANKNIFTY option chain data (spot, ATM strike, top OI changes, top volume, IV).
Output: the 5 most unusual observations relative to a normal session, one line each.
If nothing is unusual, say NOTHING UNUSUAL.
Never recommend a trade. No adjectives. Facts only."""

SYSTEM_HUNTER = """You are the setup hunter on an Indian options desk.
Input: NIFTY/BANKNIFTY spot, recent price action, support/resistance levels, VIX.
Output: for each, is there a defined setup (range break, retest, failed move)?
State the level that makes it valid and the level that kills it. No setup means say NO SETUP.
You do not predict. You describe structure."""

SYSTEM_NEWS = """You are the news desk on an Indian options desk.
Input: today's headlines, RBI/Fed events, US market moves, INR, crude.
Output: only items that could move NIFTY/BANKNIFTY positions within 4 hours,
each tagged PRIMARY (filing, official release) or SECONDARY (reporting, rumor).
One line of plain-English impact each. Kill everything else. No opinions."""

SYSTEM_WHALES = """You are the flow desk on an Indian options desk.
Input: FII/DII cash flows (in Rs crores), NIFTY/BNF OI build-up today (top 5 strikes),
any large block deals reported.
Output: net institutional flow (FII vs DII, bullish/bearish), top OI build-up strikes,
any cluster of 2+ whales in the same direction inside an hour. Facts only.
If no signal, say QUIET ON FLOW."""

SYSTEM_RISK = """You are the risk desk and you outrank everyone on this Indian options desk.
Input: current positions, proposed ideas from the other desks, and these rules:
  - Max 5% of capital per single trade (cost cap on debit spreads)
  - Max 5% of capital per open position (max loss cap)
  - Max 6 concurrent open strategies
  - No new entries 09:00-09:15 (pre-open buffer)
  - No new entries after 13:30 IST (no_new_trades time)
  - Force-square at 14:30 IST
  - No adding to losing positions
  - No trading within 24h of a red day (>1% loss on capital)
Output: APPROVED or REJECTED with the rule that decided it. You cannot be argued with."""

SYSTEM_HEAD = """You are head of desk on a small Indian options trading desk.
Input: the reports from scanner, hunter, news, whales, and risk.
Decide if ANYTHING requires the human's attention today.
The bar is high: a fresh confluence of at least two desks, risk-approved,
not a repeat of yesterday, and the position would still be openable at 13:30 IST.
If nothing clears the bar, output QUIET DAY and nothing else.
If something clears it, write ONE message under 100 words: what, why now,
what would invalidate it. You are judged on how rarely you speak."""


# ----- role data assembly (read existing bot state) -----
def _load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _opt_chain_summary(symbol: str) -> str:
    """Build a short summary of the option chain for the LLM."""
    d = _load_json(DCACHE / f"option_chain_{symbol}.json")
    if not d:
        return f"{symbol}: option chain not available"
    spot = d.get("spot", 0)
    atm = d.get("atm_strike", 0)
    strikes = d.get("strikes", {})
    # find top OI build-up / unwind
    if not strikes:
        return f"{symbol}: spot={spot:.2f} atm={atm}, no strikes cached"
    # take ATM ± 5 strikes for the summary
    try:
        atm_int = int(atm)
        keys = [k for k in strikes.keys() if abs(int(k.split("_")[0]) - atm_int) <= 250]
    except Exception:
        keys = list(strikes.keys())[:20]
    lines = [f"{symbol}: spot={spot:.2f} atm={atm}"]
    for k in keys[:20]:
        s = strikes[k]
        lines.append(
            f"  {k:12} px={s.get('price', 0):>7.2f}  delta={s.get('delta', 0):>5.2f}  iv={s.get('iv', 0):.2f}"
        )
    return "\n".join(lines)


def _levels_summary() -> str:
    d = _load_json(DCACHE / "intraday_levels.json")
    if not d:
        return "intraday levels not available"
    opens = d.get("session_opens", {})
    pdh_pdl = d.get("pdh_pdl", {})
    lines = ["SESSION LEVELS:"]
    for sym in ("NIFTY", "BANKNIFTY"):
        op = opens.get(sym, 0)
        pd = pdh_pdl.get(sym, {})
        lines.append(f"  {sym}: open={op}  PDH={pd.get('pdh', '?')}  PDL={pd.get('pdl', '?')}")
    return "\n".join(lines)


def _oi_summary() -> str:
    """Get latest OI snapshots for NIFTY/BNF — top build-up / unwind."""
    oi_dir = DCACHE / "oi_snapshots"
    if not oi_dir.exists():
        return "OI snapshots not available"
    # find latest snapshot
    files = sorted(oi_dir.glob("oi_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "no OI snapshot files"
    latest = files[0]
    try:
        d = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return f"failed to parse {latest.name}"
    lines = [f"OI SNAPSHOT ({latest.name}):"]
    for sym in ("NIFTY", "BANKNIFTY"):
        rows = d.get(sym, [])
        if not rows:
            continue
        # sort by abs OI change desc
        rows = sorted(rows, key=lambda r: abs(r.get("change", 0)), reverse=True)
        lines.append(f"  {sym} top 5 OI change:")
        for r in rows[:5]:
            lines.append(
                f"    {r.get('strike', 0):>5} {r.get('opt_type', '?'):>2}  "
                f"OI_change={r.get('change', 0):>+8}  OI_total={r.get('total', 0):>8}  "
                f"price={r.get('price', 0):>7.2f}"
            )
    return "\n".join(lines)


def _news_summary() -> str:
    d = _load_json(DCACHE / "news_aggregate.json")
    if not d:
        return "news not available"
    lines = [f"NEWS (score={d.get('score', 0):.2f}, n={d.get('n', 0)}):"]
    for h in d.get("headlines", [])[:8]:
        if h and not h.startswith("│") and not h.startswith(" "):
            lines.append(f"  - {h[:200]}")
    return "\n".join(lines) if len(lines) > 1 else "no clean headlines"


def _position_summary() -> str:
    d = _load_json(DCACHE / "paper_state.json")
    if not d:
        return "no paper state"
    cash = d.get("cash", 0)
    realized = d.get("realized_pnl", 0)
    positions = d.get("positions", {})
    open_count = len([p for p in positions.values() if p.get("qty", 0) != 0])
    lines = [f"CASH: Rs.{cash:,.2f}  REALIZED_PNL: Rs.{realized:+,.2f}  OPEN_POS: {open_count}"]
    for sym, p in list(positions.items())[:5]:
        if p.get("qty", 0) != 0:
            lines.append(
                f"  {sym}: qty={p.get('qty', 0)}  avg={p.get('avg_price', 0):.2f}  "
                f"ltp={p.get('ltp', 0):.2f}  pnl={p.get('qty', 0) * (p.get('ltp', 0) - p.get('avg_price', 0)):+,.2f}"
            )
    return "\n".join(lines)


# ----- LLM call -----
def _call_minimax(system: str, user: str, max_tokens: int = 400, timeout: int = 30) -> str:
    """Call minimax M2.7-highspeed via Anthropic-compatible Messages API.
    Matches the calling convention in kotak_bot/signals/llm_judge.py.
    """
    if not LLM_API_KEY:
        raise RuntimeError("MINIMAX_LLM_API_KEY not set in env")
    url = f"{LLM_BASE_URL.rstrip('/')}/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": LLM_API_KEY,
        "Authorization": f"Bearer {LLM_API_KEY}",
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": LLM_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=timeout) as c:
        resp = c.post(url, headers=headers, json=body)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    out = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            out += block.get("text", "")
        elif block.get("type") == "thinking" and not out:
            out += block.get("thinking", "")
    if not out:
        raise RuntimeError(f"no text in response: {str(data)[:200]}")
    return out.strip()


# ----- role runners -----
@dataclass
class DeskOutput:
    scanner: str = ""
    hunter: str = ""
    news: str = ""
    whales: str = ""
    risk: str = ""
    head: str = ""
    error: str = ""
    cycle_ts: str = ""
    duration_sec: float = 0.0


def run_scanner() -> str:
    user = (
        "Today's option chain data:\n\n"
        + _opt_chain_summary("NIFTY") + "\n\n"
        + _opt_chain_summary("BANKNIFTY") + "\n\n"
        + "Output 5 most unusual observations, one line each, or NOTHING UNUSUAL."
    )
    return _call_minimax(SYSTEM_SCANNER, user, max_tokens=350)


def run_hunter() -> str:
    user = (
        "Spot and key levels for NIFTY/BANKNIFTY:\n\n"
        + _levels_summary() + "\n\n"
        + _opt_chain_summary("NIFTY")[:600] + "\n\n"
        + "For each underlying: is there a defined setup? State the level that "
        + "makes it valid and the level that kills it. If no setup, say NO SETUP."
    )
    return _call_minimax(SYSTEM_HUNTER, user, max_tokens=400)


def run_news() -> str:
    user = (
        "Today's headlines and news context:\n\n"
        + _news_summary() + "\n\n"
        + "Output only items that could move NIFTY/BANKNIFTY positions within "
        + "4 hours. Tag PRIMARY or SECONDARY. One line each. No opinions."
    )
    return _call_minimax(SYSTEM_NEWS, user, max_tokens=400)


def run_whales() -> str:
    user = (
        "Flow data — OI build-up / unwind + institutional flows:\n\n"
        + _oi_summary() + "\n\n"
        + "Net institutional flow direction (FII vs DII). Top OI build-up strikes. "
        + "Any cluster of 2+ whales in the same direction inside an hour. "
        + "If no signal, say QUIET ON FLOW."
    )
    return _call_minimax(SYSTEM_WHALES, user, max_tokens=400)


def run_risk(scanner: str, hunter: str, news: str, whales: str) -> str:
    user = (
        "Current positions and the proposed ideas from the other desks:\n\n"
        f"POSITIONS:\n{_position_summary()}\n\n"
        f"SCANNER: {scanner}\n\n"
        f"HUNTER: {hunter}\n\n"
        f"NEWS: {news}\n\n"
        f"WHALES: {whales}\n\n"
        "Output: APPROVED or REJECTED with the rule that decided it. "
        "If multiple ideas, list each as APPROVED/REJECTED. No compromise."
    )
    return _call_minimax(SYSTEM_RISK, user, max_tokens=300)


def run_head(scanner: str, hunter: str, news: str, whales: str, risk: str) -> str:
    user = (
        "Reports from all 5 desks:\n\n"
        f"SCANNER: {scanner}\n\n"
        f"HUNTER: {hunter}\n\n"
        f"NEWS: {news}\n\n"
        f"WHALES: {whales}\n\n"
        f"RISK: {risk}\n\n"
        "Decide if anything requires the human's attention today. The bar is "
        "high: fresh confluence of at least 2 desks, risk-approved, not a "
        "repeat of yesterday. If nothing clears the bar, output QUIET DAY. "
        "If something clears it, ONE message under 100 words: what, why now, "
        "what would invalidate it."
    )
    return _call_minimax(SYSTEM_HEAD, user, max_tokens=300)


# ----- main run -----
def run_desk() -> DeskOutput:
    """Run all 6 roles in sequence. Returns DeskOutput."""
    out = DeskOutput(cycle_ts=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    t0 = time.time()
    try:
        out.scanner = run_scanner()
    except Exception as e:
        out.error = f"scanner: {e}"
        logger.warning(f"grok_desk scanner failed: {e}")
    try:
        out.hunter = run_hunter()
    except Exception as e:
        out.error += f"\nhunter: {e}"
        logger.warning(f"grok_desk hunter failed: {e}")
    try:
        out.news = run_news()
    except Exception as e:
        out.error += f"\nnews: {e}"
        logger.warning(f"grok_desk news failed: {e}")
    try:
        out.whales = run_whales()
    except Exception as e:
        out.error += f"\nwhales: {e}"
        logger.warning(f"grok_desk whales failed: {e}")
    try:
        out.risk = run_risk(out.scanner, out.hunter, out.news, out.whales)
    except Exception as e:
        out.error += f"\nrisk: {e}"
        logger.warning(f"grok_desk risk failed: {e}")
    try:
        out.head = run_head(out.scanner, out.hunter, out.news, out.whales, out.risk)
    except Exception as e:
        out.error += f"\nhead: {e}"
        logger.warning(f"grok_desk head failed: {e}")
    out.duration_sec = round(time.time() - t0, 2)
    return out


def save_state(out: DeskOutput) -> None:
    """Save the desk output to state + history files."""
    DCACHE.mkdir(parents=True, exist_ok=True)
    payload = asdict(out)
    STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    # append to history
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": out.cycle_ts, "head": out.head, "duration_sec": out.duration_sec}) + "\n")


def should_alert(head: str) -> bool:
    """Only alert when head-of-desk speaks (i.e., NOT a QUIET DAY)."""
    if not head:
        return False
    h = head.upper()
    if "QUIET DAY" in h:
        return False
    if len(h.strip()) < 5:
        return False
    return True


def send_telegram_alert(out: DeskOutput) -> bool:
    """Send a Telegram alert when head-of-desk speaks."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        cred = ROOT / "config" / "credentials.env"
        if cred.exists():
            for line in cred.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
        from telegram_alerter import get_alerter
        a = get_alerter()
        if not (a and a.enabled):
            return False
        msg = (
            f"🧠 [GROK DESK — head-of-desk]\n\n"
            f"{out.head}\n\n"
            f"— — —\n"
            f"scanner: {out.scanner[:120]}\n"
            f"hunter:  {out.hunter[:120]}\n"
            f"news:    {out.news[:120]}\n"
            f"whales:  {out.whales[:120]}\n"
            f"risk:    {out.risk[:120]}\n"
            f"\n({out.duration_sec}s · {out.cycle_ts})"
        )
        return a.send(msg)
    except Exception as e:
        logger.warning(f"telegram alert failed: {e}")
        return False


def main() -> int:
    out = run_desk()
    save_state(out)
    if should_alert(out.head):
        send_telegram_alert(out)
        print(f"[grok_desk] ALERT sent ({out.duration_sec}s)")
    else:
        print(f"[grok_desk] QUIET DAY ({out.duration_sec}s)")
    if out.error:
        print(f"[grok_desk] errors: {out.error[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
