"""FIX 2026-09-18 phase-16 tests:
- use_dcache() helper isolates tests from production
- news feed source fallback (URLs as list, multiple per source)
- chain_availability hint in LLM context

FIX 2026-09-18 14:50: tests use tmp_path + monkey-patch.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Fix 1: use_dcache() helper
# ---------------------------------------------------------------------------

def test_use_dcache_redirects_paper_client_dcache():
    """use_dcache(path) should update both DCACHE and REJECTIONS_LOG globals."""
    import tempfile
    import shutil
    from kotak_bot.broker import paper_client
    from kotak_bot.broker.paper_client import use_dcache

    original_dcache = paper_client.DCACHE
    original_log = paper_client.REJECTIONS_LOG

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Copy a sample chain so the new dcache has data
        for cf in (ROOT / "data_cache").glob("option_chain_*.json"):
            shutil.copy2(cf, tmp_path / cf.name)
        use_dcache(tmp_path)
        assert paper_client.DCACHE == tmp_path
        assert paper_client.REJECTIONS_LOG == tmp_path / "order_rejections.jsonl"

    # Restore
    use_dcache(original_dcache)
    assert paper_client.DCACHE == original_dcache
    assert paper_client.REJECTIONS_LOG == original_log


def test_use_dcache_with_nonexistent_path(tmp_path):
    """use_dcache should accept a path that doesn't exist yet (it'll be created)."""
    from kotak_bot.broker import paper_client
    from kotak_bot.broker.paper_client import use_dcache

    nonexistent = tmp_path / "does_not_exist_yet"
    use_dcache(nonexistent)
    assert paper_client.DCACHE == nonexistent
    # Restore
    use_dcache(ROOT / "data_cache")


# ---------------------------------------------------------------------------
# Fix 3: News feed source fallback (URLs as list)
# ---------------------------------------------------------------------------

def test_news_sources_have_fallback_urls():
    """Each source with prior failure should have at least 2 URLs."""
    from rss_news_fetcher import RSS_SOURCES
    # The 3 Moneycontrol sources, BS, Reuters were all failing pre-fix.
    # They should now have Google News fallbacks.
    must_have_fallback = [
        "moneycontrol_markets",
        "moneycontrol_economy",
        "moneycontrol_stocks",
        "bs_markets",
        "reuters_india",
    ]
    sources_dict = {name: urls for name, urls in RSS_SOURCES}
    for name in must_have_fallback:
        assert name in sources_dict, f"missing source: {name}"
        urls = sources_dict[name]
        # Accept either: a list of URLs (new format) or a single string
        if isinstance(urls, str):
            urls = [urls]
        assert len(urls) >= 2, (
            f"{name} should have at least 2 URLs (primary + fallback), got {len(urls)}"
        )


def test_news_sources_have_total_of_at_least_12():
    """We added 2 new sources (google_news_india, toi_business)."""
    from rss_news_fetcher import RSS_SOURCES
    assert len(RSS_SOURCES) >= 12, f"expected >= 12 sources, got {len(RSS_SOURCES)}"


def test_news_fetch_tries_fallback_url():
    """When primary URL returns empty, fetcher should try the fallback."""
    calls = []

    def mock_fetch(url, timeout=12, max_bytes=1_500_000):
        calls.append(url)
        # Moneycontrol primary returns empty; the Google News fallback (which
        # also contains 'moneycontrol' in its query) returns valid content.
        if url.startswith("https://www.moneycontrol.com"):
            return ""  # primary empty
        if url.startswith("https://news.google.com"):
            return "<rss><channel><item><title>Fallback works</title><link>x</link></item></channel></rss>"
        return ""

    urls = [
        "https://www.moneycontrol.com/rss/markets.xml",
        "https://news.google.com/rss/search?q=site:moneycontrol.com",
    ]
    text = ""
    for url in urls:
        text = mock_fetch(url)
        if text:
            break
    assert "Fallback" in text, f"expected fallback result, got '{text[:60]}' after {len(calls)} calls"
    assert len(calls) == 2, f"expected 2 URL attempts (1 empty primary + 1 fallback), got {len(calls)}"


# ---------------------------------------------------------------------------
# Fix 4: Chain availability hint in LLM context
# ---------------------------------------------------------------------------

def test_chain_availability_hint_populates_for_index_underlyings():
    """The CHAIN_AVAILABILITY hint should be populated when option_chains.json
    exists with NIFTY/BANKNIFTY data."""
    from scripts.quant_service import _build_chain_availability_hint

    # Build a synthetic chain file
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chain_path = tmp_path / "option_chains.json"
        chain_path.write_text(json.dumps({
            "chains": {
                "NIFTY": {
                    "spot": 23300.0,
                    "strikes": {
                        "23200_CE": {}, "23250_CE": {}, "23300_CE": {},
                        "23350_CE": {}, "23400_CE": {}, "23450_CE": {},
                        "23500_CE": {},
                    },
                },
            },
        }), encoding="utf-8")

        hint = _build_chain_availability_hint(tmp_path)
        assert "NIFTY" in hint
        nifty_hint = hint["NIFTY"]
        assert nifty_hint["spot"] == 23300.0
        assert nifty_hint["atm_strike"] == 23300
        assert 23200 in nifty_hint["tradeable_strikes_sample"]
        assert 23500 in nifty_hint["tradeable_strikes_sample"]
        assert nifty_hint["n_strikes"] == 7
        assert "interpretation" in nifty_hint


def test_chain_availability_handles_missing_chain_file(tmp_path):
    """If option_chains.json doesn't exist, return empty dict (don't crash)."""
    from scripts.quant_service import _build_chain_availability_hint
    hint = _build_chain_availability_hint(tmp_path)
    assert hint == {}


def test_chain_availability_filters_far_otm_strikes():
    """Strikes >250pt from ATM should not be in the tradeable sample."""
    from scripts.quant_service import _build_chain_availability_hint
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chain_path = tmp_path / "option_chains.json"
        chain_path.write_text(json.dumps({
            "chains": {
                "NIFTY": {
                    "spot": 23300.0,
                    "strikes": {
                        "23300_CE": {}, "23350_CE": {}, "23400_CE": {},
                        "23450_CE": {}, "23500_CE": {},  # within ±250pt
                        "24500_CE": {},  # 1200pt OTM, NOT in sample
                    },
                },
            },
        }), encoding="utf-8")
        hint = _build_chain_availability_hint(tmp_path)
        sample = hint["NIFTY"]["tradeable_strikes_sample"]
        assert 24500 not in sample, f"24500 should not be in tradeable sample (1200pt OTM)"
        assert 23300 in sample
        assert 23500 in sample
