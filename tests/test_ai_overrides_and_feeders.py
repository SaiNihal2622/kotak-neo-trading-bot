"""Tests for the AI-override mechanism + RSS/FII fetchers."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


# ---------- AI override tests ----------

def test_ai_skip_flag_schema():
    """The _ai_skip_force_square.json schema is documented in the bot code.
    Verify the bot's main loop reads the expected fields."""
    # The bot's main loop checks these keys (verified by reading __main__.py):
    #   "expires_at"  : ISO 8601 timestamp; if > now, skip is active
    #   "reason"      : human-readable; logged
    # If the brain writes a file with these keys, the bot will honor it.
    # This is a documentation test — we verify the schema is consistent.
    import re
    from pathlib import Path
    main_py = (Path(__file__).parent.parent / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
    assert "_ai_skip_force_square.json" in main_py, (
        "bot's main loop must reference _ai_skip_force_square.json"
    )
    assert "expires_at" in main_py, "bot must read 'expires_at' key from the skip flag"
    assert "reason" in main_py, "bot must log the 'reason' from the skip flag"


def test_intraday_defaults_allow_overnight_true():
    """After the 22:35 fix, the LLM is allowed to hold overnight by default."""
    from kotak_bot.utils.clock import set_intraday, get_intraday
    set_intraday({})  # reset to defaults
    cfg = get_intraday()
    assert cfg["allow_overnight"] is True, (
        "intraday.allow_overnight should default to True after the 22:35 fix "
        "so the LLM brain can hold overnight if conditions warrant"
    )
    assert cfg["no_new_trades_after"].hour == 14
    assert cfg["no_new_trades_after"].minute == 30
    assert cfg["force_square_off_time"].hour == 15
    assert cfg["force_square_off_time"].minute == 15


def test_set_intraday_with_empty_dict_resets():
    """set_intraday({}) should actually reset to defaults (was a no-op before)."""
    from kotak_bot.utils.clock import set_intraday, get_intraday
    # First pollute state
    set_intraday({"no_new_trades_after": "11:00", "force_square_off_time": "12:00",
                  "allow_overnight": False})
    cfg = get_intraday()
    assert cfg["no_new_trades_after"].hour == 11  # polluted
    # Now reset
    set_intraday({})
    cfg = get_intraday()
    assert cfg["no_new_trades_after"].hour == 14  # default
    assert cfg["force_square_off_time"].hour == 15  # default
    assert cfg["allow_overnight"] is True  # default


# ---------- RSS news fetcher tests ----------

def test_rss_fetcher_outputs_to_expected_path():
    """rss_news_fetcher.py must write to data_cache/news_feed.txt and meta JSON."""
    from scripts import rss_news_fetcher
    # Just verify the module has the right paths
    assert str(rss_news_fetcher.OUT).endswith("news_feed.txt")
    assert str(rss_news_fetcher.META).endswith("news_feed_meta.json")


def test_rss_fetcher_runs_without_crashing():
    """rss_news_fetcher.main() must complete without raising. May return 0
    with 0 headlines if all sources fail (no network), but should not crash."""
    from scripts import rss_news_fetcher
    rc = rss_news_fetcher.main()
    assert rc == 0
    # The file should exist (or be created)
    assert rss_news_fetcher.OUT.exists()


def test_rss_fetcher_output_format():
    """Each line in news_feed.txt should be [ts] [source] title format."""
    from scripts import rss_news_fetcher
    rss_news_fetcher.main()
    if rss_news_fetcher.OUT.exists():
        content = rss_news_fetcher.OUT.read_text(encoding="utf-8")
        if content.strip():
            for line in content.strip().splitlines()[:3]:
                # Format: [2026-09-08T14:30:00] [moneycontrol_economy] Title here
                # We just check it has at least 2 brackets
                assert line.count("[") >= 2, f"line missing brackets: {line}"


# ---------- FII/DII fetcher tests ----------

def test_fii_dii_fetcher_outputs_to_expected_path():
    """fii_dii_fetcher.py must write to data_cache/fii_dii.json."""
    from scripts import fii_dii_fetcher
    assert str(fii_dii_fetcher.OUT).endswith("fii_dii.json")


def test_fii_dii_fetcher_runs_without_crashing():
    """fii_dii_fetcher.main() must complete without raising. May return 0
    with 0 rows if all sources fail, but should not crash."""
    from scripts import fii_dii_fetcher
    rc = fii_dii_fetcher.main()
    assert rc == 0
    assert fii_dii_fetcher.OUT.exists()


def test_fii_dii_fetcher_output_schema():
    """If fii_dii.json has rows, each row must have the expected keys."""
    from scripts import fii_dii_fetcher
    fii_dii_fetcher.main()
    if fii_dii_fetcher.OUT.exists():
        try:
            d = json.loads(fii_dii_fetcher.OUT.read_text(encoding="utf-8"))
        except Exception:
            return  # no data, skip
        # top-level keys
        for k in ("ts", "duration_sec", "rows", "summary", "sources"):
            assert k in d, f"missing top-level key: {k}"
        # summary keys (when populated)
        if d.get("rows"):
            s = d["summary"]
            for k in ("n_rows", "latest_date", "latest_fii_net_cr", "latest_dii_net_cr",
                     "fii_bullish_3d", "dii_bullish_3d"):
                assert k in s, f"missing summary key: {k}"


def test_fii_dii_manual_override_takes_priority():
    """If data_cache/fii_dii_manual.json exists, the fetcher uses it first."""
    from datetime import date, timedelta
    from scripts import fii_dii_fetcher
    manual = fii_dii_fetcher.MANUAL
    backup = None
    if manual.exists():
        backup = manual.read_text(encoding="utf-8")
    # Use a recent date so the date filter (FIX 2026-09-09 14:05) doesn't drop it
    recent_date = (date.today() - timedelta(days=1)).strftime("%d %b %Y")
    try:
        manual.write_text(json.dumps([
            {"date": recent_date, "fii_buy_cr": 100, "fii_sell_cr": 50,
             "fii_net_cr": 50, "dii_buy_cr": 200, "dii_sell_cr": 100,
             "dii_net_cr": 100, "source": "manual_test"},
        ]), encoding="utf-8")
        fii_dii_fetcher.main()
        d = json.loads(fii_dii_fetcher.OUT.read_text(encoding="utf-8"))
        assert d["rows"][0]["source"] == "manual_test", (
            "manual override should take priority over Moneycontrol fetch"
        )
    finally:
        if backup:
            manual.write_text(backup, encoding="utf-8")
        elif manual.exists():
            manual.unlink()


# ---------- Grok Desk wiring tests ----------

def test_grok_desk_whales_reads_fii_dii():
    """The Grok Bot Desk's WHALES role must read from data_cache/fii_dii.json."""
    from scripts import grok_desk
    out = grok_desk._fii_dii_summary()
    # Even with no data, should return a string (not crash)
    assert isinstance(out, str)
    # And if fii_dii.json exists, it should mention either FII or 'not available'
    if (grok_desk.DCACHE / "fii_dii.json").exists():
        d = json.loads((grok_desk.DCACHE / "fii_dii.json").read_text(encoding="utf-8"))
        if d.get("rows"):
            assert "FII" in out or "fii" in out.lower()
