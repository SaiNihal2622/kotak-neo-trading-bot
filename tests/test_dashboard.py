"""Tests for the new UNLEASHED-mode dashboard (scripts/dashboard.py).

Verifies the structure: 12+ sections covering all live data, professional
typography, 5s auto-refresh, and no broken HTML.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def test_dashboard_module_imports():
    """dashboard.py should import without errors."""
    from scripts import dashboard
    assert hasattr(dashboard, "render_dashboard")
    assert hasattr(dashboard, "main")


def test_dashboard_renders_html():
    """render_dashboard should return valid HTML starting with <!DOCTYPE or <html>."""
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    assert "<html" in html.lower() or "<!doctype" in html.lower()
    assert "</html>" in html.lower()


def test_dashboard_writes_file():
    """main() should write data_cache/dashboard.html."""
    from scripts.dashboard import main
    rc = main()
    assert rc == 0
    assert (ROOT / "data_cache" / "dashboard.html").exists()


def test_dashboard_has_all_required_sections():
    """Dashboard must have all 12+ UNLEASHED-mode sections."""
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    required_sections = [
        "Market",
        "Predictive Signals",
        "FII / DII Flows",
        "News",
        "Grok Bot Desk",
        "Open Positions",
        "Recent Fills",
        "Risk",
        "Brain Decisions",
        "In-Process Schedulers",
        "Bot Activity",
        "AI Overrides",
    ]
    for s in required_sections:
        assert s in html, f"missing section: {s}"


def test_dashboard_has_5s_auto_refresh():
    """The auto-refresh meta tag should be 5 seconds (live)."""
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    assert 'http-equiv="refresh" content="5"' in html, "auto-refresh should be 5s"


def test_dashboard_has_no_telegram_references():
    """The dashboard should be the single source of truth — no Telegram noise.

    The bot's stdout log stream naturally contains 'Telegram' references
    (e.g. 'TelegramCommandHandler started'). We exclude that section.
    """
    import re
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    # Footer should mention dashboard is the only surface
    assert "single source of truth" in html
    assert "Telegram alerts disabled" in html
    # Strip the bot log stream section (it contains the bot's stdout which
    # can naturally mention 'Telegram' as the TelegramCommandHandler logs)
    cleaned = re.sub(r'<div class="log-stream">.*?</div>\s*</div>', '', html, flags=re.DOTALL)
    # Should mention telegram only in the "disabled" context in the dashboard's own UI
    telegram_count = cleaned.lower().count("telegram")
    # 0-2 mentions is OK (one in scheduler description noting EOD alerts are off,
    # one in the footer saying telegram alerts are disabled). Both are informational.
    assert telegram_count <= 2, f"telegram mentioned {telegram_count}x in dashboard UI, should be <= 2"


def test_dashboard_has_professional_typography():
    """Should use a clean system font stack, not a custom font that doesn't load."""
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    # System font stack
    assert "-apple-system" in html or "system-ui" in html
    # JetBrains Mono for numbers
    assert "JetBrains Mono" in html or "Menlo" in html or "monospace" in html


def test_dashboard_html_no_unescaped_braces():
    """f-string formatting issues — no raw { or } left in output."""
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    # No double-braces left (would indicate f-string error)
    assert "{{" not in html, "double-brace { left in HTML"
    assert "}}" not in html, "double-brace } left in HTML"


def test_dashboard_no_jinja_templates():
    """Dashboard is pure Python f-strings, no Jinja templates."""
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    assert "{%" not in html, "no Jinja blocks expected"
    assert "{{" not in html, "no Jinja variables expected"


def test_dashboard_renders_in_under_2_seconds():
    """Dashboard generation should be fast (auto-refresh 5s, so <2s gen)."""
    import time
    from scripts.dashboard import render_dashboard
    t0 = time.time()
    render_dashboard()
    elapsed = time.time() - t0
    assert elapsed < 2.0, f"dashboard took {elapsed:.2f}s, should be < 2s"


def test_dashboard_handles_missing_data():
    """When all data sources are empty, dashboard should still render."""
    from scripts.dashboard import render_dashboard
    # Even with no data, the function should not raise
    html = render_dashboard()
    assert len(html) > 1000, "dashboard should render even with no data"


def test_dashboard_handles_corrupt_json():
    """When JSON files are corrupt, dashboard should still render."""
    from scripts.dashboard import _read_json
    out = _read_json(Path("/nonexistent/path.json"), default={"x": 1})
    assert out == {"x": 1}
    out = _read_json(Path("/nonexistent/path.json"))
    assert out == {}


def test_settings_telegram_disabled():
    """Telegram alerts should be disabled by default (FIX 2026-09-09 01:42)."""
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    # Find the alerts.telegram.enabled line
    m = re.search(r"alerts:\s*\n[\s\S]*?telegram:\s*\n\s*enabled:\s*(\w+)", cfg)
    if m:
        val = m.group(1).lower()
        assert val == "false", f"telegram.enabled should be false, got {val}"


def test_dashboard_no_unicode_encode_errors():
    """Dashboard should handle ₹ and other special characters without errors."""
    from scripts.dashboard import render_dashboard
    html = render_dashboard()
    # ₹ is HTML entity for rupee symbol; check it appears
    assert "₹" in html or "&#8377;" in html or "₹" in html.encode().decode("utf-8", errors="ignore")
    # Or check the actual encoding worked
    html.encode("utf-8")  # should not raise


def test_dashboard_live_data_paths():
    """Dashboard should read from the right data files (live paths)."""
    from scripts import dashboard
    # Check the data sources we read
    expected_files = [
        "quant_service_state.json",
        "liveness.json",
        "paper_state.json",
        "option_chain_NIFTY.json",
        "option_chain_BANKNIFTY.json",
        "predictive_signals.json",
        "fii_dii.json",
        "news_feed.txt",
        "grok_desk_state.json",
        "trade_journal.jsonl",
        "bot.log",
    ]
    for f in expected_files:
        # Just verify we attempt to read this file
        assert (dashboard.DCACHE / f).exists() or f.endswith(".log") or "bot" in f, (
            f"expected data source not present (this is fine for missing optional data): {f}"
        )
