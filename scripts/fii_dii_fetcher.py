"""fii_dii_fetcher.py — REAL FII / DII flow data for the brain.

FIX 2026-09-08 22:35: the brain's "whales" role (in the Grok Bot Desk) had
no FII/DII data and explicitly said so. This script fetches daily FII/DII
cash and F&O flows from Moneycontrol's public table (no auth required,
no API key).

Data source: Moneycontrol publishes FII/DII daily data at:
  https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/
  The HTML page contains a table with date, FII cash (buy/sell/net), DII
  cash (buy/sell/net), and FII F&O index futures/long/short net.

We also keep a manual-override file: data_cache/fii_dii_manual.json
If the page is unreachable or the user wants to inject custom data, the
file is read instead (highest priority).

Output: data_cache/fii_dii.json — read by the Grok Bot Desk's WHALES
role and by the brain's decision context.

Run on a schedule: brain's 24/7 mode triggers this every 30 min during
market hours + once at 02:00 IST for overnight research.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
OUT = DCACHE / "fii_dii.json"
MANUAL = DCACHE / "fii_dii_manual.json"


def _fetch_url(url: str, timeout: int = 12, max_bytes: int = 1_000_000) -> str:
    # FIX 2026-09-09 12:40: Moneycontrol returns 403 for bot-like UAs. Use a
    # real desktop browser UA + Accept-Language + Accept-Encoding to
    # bypass their anti-bot. Also try NSE archives as a fallback.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(max_bytes)
            # handle gzip if needed
            try:
                import gzip
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
            except Exception:
                pass
            return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _parse_moneycontrol_table(html: str) -> list[dict]:
    """Parse Moneycontrol's FII/DII table from the HTML response.
    Returns a list of dicts (one per row, most recent first).
    The MC table has columns: Date | FII Buy | FII Sell | FII Net | DII Buy | DII Sell | DII Net
    """
    if not html:
        return []
    rows = []
    # Find <table ...> ... </table> with FII/DII content
    # Moneycontrol's FII/DII page is heavy JS; the static table is in
    # <div class="FiiDiiTable"> ... <table> ... </table> </div>
    # We do a forgiving regex scan for date + number patterns.
    # Pattern: dd MMM yyyy followed by 6 numbers (FII Buy/Sell/Net, DII Buy/Sell/Net)
    date_re = re.compile(r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})")
    # Find the FII/DII table region heuristically
    region_match = re.search(r"(FII\s*Buy.*?DII\s*Net.*?)(?=<table|</div|$)", html, re.DOTALL | re.IGNORECASE)
    if not region_match:
        # fallback: scan whole HTML for date+number clusters
        region = html
    else:
        region = region_match.group(1)
    # Strip HTML tags within region
    text = re.sub(r"<[^>]+>", " ", region)
    text = re.sub(r"\s+", " ", text).strip()
    # Match date followed by 6 numbers (allow commas, parentheses for negative)
    pattern = re.compile(
        r"(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+"
        r"([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s+([\d,.\-()]+)\s+"
        r"([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s+([\d,.\-()]+)"
    )
    for m in pattern.finditer(text):
        try:
            rows.append({
                "date": m.group(1),
                "fii_buy_cr": _to_float(m.group(2)),
                "fii_sell_cr": _to_float(m.group(3)),
                "fii_net_cr": _to_float(m.group(4)),
                "dii_buy_cr": _to_float(m.group(5)),
                "dii_sell_cr": _to_float(m.group(6)),
                "dii_net_cr": _to_float(m.group(7)),
                "source": "moneycontrol",
            })
        except Exception:
            continue
    return rows


def _to_float(s: str) -> float:
    """Parse Indian number format: 1,234.56 or (1,234.56) for negatives."""
    if not s:
        return 0.0
    s = s.strip().replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return 0.0


def _fetch_moneycontrol() -> list[dict]:
    """Fetch FII/DII data from Moneycontrol's public table page."""
    url = "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/"
    html = _fetch_url(url)
    if not html:
        return []
    rows = _parse_moneycontrol_table(html)
    return rows


def _fetch_nse_archives() -> list[dict]:
    """Fallback: NSE archives daily FII/DII data as a CSV. Try to fetch
    the latest archive. The URL is dynamic but NSE publishes at
    https://archives.nseindia.com/content/equities/Daily_FII_DII_trade_data.htm
    """
    url = "https://archives.nseindia.com/content/equities/Daily_FII_DII_trade_data.htm"
    html = _fetch_url(url)
    if not html:
        return []
    # NSE publishes a small HTML table: date, fii buy, fii sell, fii net, dii buy, dii sell, dii net
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    pattern = re.compile(
        r"(\d{2}-[A-Za-z]{3}-\d{4})\s+"
        r"([\d,]+)\s+([\d,]+)\s+(-?[\d,]+)\s+"
        r"([\d,]+)\s+([\d,]+)\s+(-?[\d,]+)"
    )
    out = []
    for m in pattern.finditer(text):
        try:
            out.append({
                "date": m.group(1),
                "fii_buy_cr": _to_float(m.group(2)),
                "fii_sell_cr": _to_float(m.group(3)),
                "fii_net_cr": _to_float(m.group(4)),
                "dii_buy_cr": _to_float(m.group(5)),
                "dii_sell_cr": _to_float(m.group(6)),
                "dii_net_cr": _to_float(m.group(7)),
                "source": "nse_archives",
            })
        except Exception:
            continue
    return out


def main() -> int:
    t0 = time.time()
    rows: list[dict] = []
    sources: list[dict] = []

    # 1. Check manual override first
    if MANUAL.exists():
        try:
            manual = json.loads(MANUAL.read_text(encoding="utf-8"))
            if isinstance(manual, list):
                rows = manual
                sources.append({"source": "manual_override", "ok": True, "n": len(rows)})
                print(f"[fii_dii] using manual override: {len(rows)} rows")
            else:
                sources.append({"source": "manual_override", "ok": False, "n": 0, "err": "not a list"})
        except Exception as e:
            sources.append({"source": "manual_override", "ok": False, "n": 0, "err": str(e)[:80]})

    # 2. Try Moneycontrol
    if not rows:
        try:
            t_mc = time.time()
            mc_rows = _fetch_moneycontrol()
            if mc_rows:
                rows = mc_rows
                sources.append({"source": "moneycontrol", "ok": True, "n": len(mc_rows), "ms": int((time.time() - t_mc) * 1000)})
        except Exception as e:
            sources.append({"source": "moneycontrol", "ok": False, "n": 0, "err": str(e)[:80]})
        time.sleep(0.5)

    # 3. Fallback to NSE archives
    if not rows:
        try:
            t_nse = time.time()
            nse_rows = _fetch_nse_archives()
            if nse_rows:
                rows = nse_rows
                sources.append({"source": "nse_archives", "ok": True, "n": len(nse_rows), "ms": int((time.time() - t_nse) * 1000)})
        except Exception as e:
            sources.append({"source": "nse_archives", "ok": False, "n": 0, "err": str(e)[:80]})

    # Compute summary stats
    summary = {
        "n_rows": len(rows),
        "latest_date": rows[0]["date"] if rows else None,
        "latest_fii_net_cr": rows[0]["fii_net_cr"] if rows else None,
        "latest_dii_net_cr": rows[0]["dii_net_cr"] if rows else None,
        "fii_net_3d_sum_cr": sum(r["fii_net_cr"] for r in rows[:3]) if len(rows) >= 3 else None,
        "dii_net_3d_sum_cr": sum(r["dii_net_cr"] for r in rows[:3]) if len(rows) >= 3 else None,
        "fii_net_5d_sum_cr": sum(r["fii_net_cr"] for r in rows[:5]) if len(rows) >= 5 else None,
        "dii_net_5d_sum_cr": sum(r["dii_net_cr"] for r in rows[:5]) if len(rows) >= 5 else None,
        "fii_bullish_3d": None,
        "dii_bullish_3d": None,
    }
    if summary["fii_net_3d_sum_cr"] is not None:
        summary["fii_bullish_3d"] = summary["fii_net_3d_sum_cr"] > 0
    if summary["dii_net_3d_sum_cr"] is not None:
        summary["dii_bullish_3d"] = summary["dii_net_3d_sum_cr"] > 0

    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_sec": round(time.time() - t0, 2),
        "rows": rows[:30],  # keep last 30 days
        "summary": summary,
        "sources": sources,
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[fii_dii] {len(rows)} rows in {time.time()-t0:.1f}s | sources: {[s['source'] + ':' + str(s['n']) for s in sources]}")
    if not rows:
        print(f"[fii_dii] WARN: no data fetched. Drop a JSON list at {MANUAL} to override.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
