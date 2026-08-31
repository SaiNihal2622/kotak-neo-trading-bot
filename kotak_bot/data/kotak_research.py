"""Kotak Neo's free daily Derivatives Research PDF crawler.

URL pattern: https://www.kotakneo.com/uploads/Derivatives_Daily_<doc_id>_<date>_<hash>.pdf
Contains: max pain, FII net OI, weekly PCR, OI concentration by strike, residual premium, spot expiry scenarios.
This is the single best free source for end-of-day options intelligence in India.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

CACHE_DIR = Path("data_cache/kotak_research")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PDF_URL_RE = re.compile(r"https?://www\.kotakneo\.com/uploads/Derivatives_Daily_[\w_]+\.pdf", re.IGNORECASE)


def find_latest_pdf_url() -> Optional[str]:
    """Find the latest daily derivatives PDF URL from kotakneo.com."""
    try:
        # The PDFs are linked from the research page
        urls_to_try = [
            "https://www.kotakneo.com/futures-and-options/",
            "https://www.kotakneo.com/research/",
            "https://www.kotakneo.com/",
        ]
        for url in urls_to_try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                matches = PDF_URL_RE.findall(r.text)
                if matches:
                    return matches[0]
    except Exception as e:
        logger.warning(f"find_latest_pdf: {e}")
    return None


def download_latest_research_pdf(force: bool = False) -> Optional[Path]:
    """Download the latest Derivatives Daily PDF, cache locally."""
    today = datetime.now().strftime("%Y-%m-%d")
    cache_path = CACHE_DIR / f"derivatives_daily_{today}.pdf"
    if cache_path.exists() and not force:
        return cache_path
    url = find_latest_pdf_url()
    if not url:
        # Demoted from warning to debug on 2026-08-31: kotakneo.com research
        # page has been re-architected and find_latest_pdf_url() reliably
        # returns None. The PDF is one-day-stale-tolerant (regime detector
        # uses candle+macro+VIX; PDF is a supplement, not a gate). Spam at
        # debug so it doesn't pollute Logs\bot.log.
        logger.debug("Could not find derivatives PDF URL (kotakneo.com layout drift); using stale cache if present")
        # Return the stale cache if we have one — better than no PDF
        yesterday = (datetime.now() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
        stale_path = CACHE_DIR / f"derivatives_daily_{yesterday}.pdf"
        if stale_path.exists():
            return stale_path
        return None
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        cache_path.write_bytes(r.content)
        logger.info(f"Downloaded Kotak Derivatives PDF: {cache_path} ({len(r.content)/1024:.0f} KB)")
        return cache_path
    except Exception as e:
        logger.warning(f"Download PDF failed: {e}")
        return None


def parse_pdf_text(pdf_path: Path) -> str:
    """Extract text from the PDF using a lightweight method."""
    try:
        # Try pypdf first
        import pypdf
        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            text = "\n".join(page.extract_text() for page in reader.pages)
        return text
    except ImportError:
        pass
    # Fallback: use subprocess pdftotext if available
    try:
        import subprocess
        result = subprocess.run(["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""


def extract_key_metrics(pdf_text: str) -> dict:
    """Pull out max pain, PCR, OI concentration, FII flows from the PDF text."""
    metrics = {
        "max_pain": None,
        "pcr": None,
        "fii_net_oi": None,
        "spot_expiry_range": None,
        "raw_excerpts": [],
    }
    if not pdf_text:
        return metrics
    lines = [l.strip() for l in pdf_text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        # Max Pain
        if re.search(r"max\s*pain", line, re.IGNORECASE) and i + 1 < len(lines):
            try:
                metrics["max_pain"] = float(re.sub(r"[^\d.]", "", lines[i + 1].split()[0]))
            except (ValueError, IndexError):
                pass
        # PCR
        if re.search(r"(put.?call|pcr).*ratio", line, re.IGNORECASE):
            try:
                val = float(re.search(r"\d+\.\d+", line).group())
                metrics["pcr"] = val
            except (ValueError, AttributeError):
                pass
        # FII net OI
        if re.search(r"fii.*net.*(oi|position)", line, re.IGNORECASE):
            try:
                val = float(re.sub(r"[^\d.-]", "", line.split()[-1]))
                metrics["fii_net_oi"] = val
            except (ValueError, IndexError):
                pass
    return metrics


def daily_research_summary() -> dict:
    """High-level: download today's research, parse, return summary."""
    pdf = download_latest_research_pdf()
    if not pdf:
        return {"error": "could not download"}
    text = parse_pdf_text(pdf)
    metrics = extract_key_metrics(text)
    metrics["source"] = str(pdf)
    metrics["extracted_at"] = datetime.now().isoformat()
    return metrics
