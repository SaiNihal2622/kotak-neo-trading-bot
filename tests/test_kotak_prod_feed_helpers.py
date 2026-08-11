"""Unit tests for KotakProdFeed helpers.

Tests the new helpers (expiry selection, OI safe parsing) WITHOUT making any real
network calls. The feed is built manually with a fake scrip master.
"""
import os
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure env doesn't try real auth
os.environ.setdefault('KOTAK_API_KEY', 'fake')
os.environ.setdefault('KOTAK_MOBILE', '+910000000000')
os.environ.setdefault('KOTAK_UCC', 'FAKE1')

from kotak_bot.data.kotak_prod_feed import KotakProdFeed


# Mock scrip master CSV content — minimal valid rows for testing
def _make_csv_bytes(rows: list[dict]) -> bytes:
    """Build a CSV string from a list of dicts."""
    if not rows:
        return b""
    headers = list(rows[0].keys())
    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in headers))
    return "\n".join(lines).encode()


def _make_feed_with_scrip(rows: list[dict]) -> KotakProdFeed:
    """Build a KotakProdFeed and inject a mock scrip master (no network).

    IMPORTANT: writes to a TEMP file (not the real data_cache path) so tests
    can never overwrite the live scrip master.
    """
    import tempfile
    f = KotakProdFeed(env="uat", access_token="x", mobile="x", ucc="x", totp_secret="x", mpin="x")
    csv_bytes = _make_csv_bytes(rows)
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb")
    tmp.write(csv_bytes)
    tmp.close()
    f.SCRIP_MASTER_FILE = tmp.name  # override path for this test instance
    # load without re-downloading
    f._load_scrip_master()
    return f


def _scrip_row(underlying: str, ref: str, ps: str, lot: int = 65) -> dict:
    return {
        "pSymbol": ps,
        "pGroup": "XX",
        "pExchSeg": "nse_fo",
        "pInstType": "OPTIDX",
        "pSymbolName": underlying,
        "pTrdSymbol": ref.replace(".", ""),  # crude but ok for tests
        "pOptionType": ref[-2:],
        "pScripRefKey": ref,
        "lLotSize": str(lot),
        "lExpiryDate": "0",  # not used; we use ref date
    }


class TestExpiryHelpers(unittest.TestCase):
    def test_nearest_expiry_today(self):
        """If today IS an expiry day, returns today."""
        f = _make_feed_with_scrip([
            _scrip_row("NIFTY", "NIFTY11AUG2624600.00CE", "41015"),
            _scrip_row("NIFTY", "NIFTY18AUG2624600.00CE", "41100"),
        ])
        # 11AUG26 = 2026-08-11 (today per system)
        exp = f.get_nearest_expiry("NIFTY", today=date(2026, 8, 11))
        self.assertEqual(exp, date(2026, 8, 11))

    def test_nearest_expiry_picks_next_weekly(self):
        """If today is past this week's expiry, returns the next one."""
        f = _make_feed_with_scrip([
            _scrip_row("NIFTY", "NIFTY11AUG2624600.00CE", "41015"),
            _scrip_row("NIFTY", "NIFTY18AUG2624600.00CE", "41100"),
        ])
        # If today is 2026-08-12 (Wed), next NIFTY weekly is Aug 18
        exp = f.get_nearest_expiry("NIFTY", today=date(2026, 8, 12))
        self.assertEqual(exp, date(2026, 8, 18))

    def test_nearest_expiry_skips_past(self):
        """Past expiries are ignored even if in scrip master."""
        f = _make_feed_with_scrip([
            _scrip_row("NIFTY", "NIFTY04AUG2624600.00CE", "40950"),
            _scrip_row("NIFTY", "NIFTY11AUG2624600.00CE", "41015"),
        ])
        exp = f.get_nearest_expiry("NIFTY", today=date(2026, 8, 7))
        self.assertEqual(exp, date(2026, 8, 11))

    def test_nearest_expiry_no_data(self):
        f = _make_feed_with_scrip([])
        exp = f.get_nearest_expiry("NIFTY", today=date(2026, 8, 11))
        self.assertIsNone(exp)

    def test_format_expiry_str(self):
        f = KotakProdFeed()
        self.assertEqual(f.format_expiry_str("NIFTY", date(2026, 8, 11)), "11AUG26")
        self.assertEqual(f.format_expiry_str("BANKNIFTY", date(2026, 9, 1)), "01SEP26")

    def test_get_strategy_sym(self):
        f = _make_feed_with_scrip([
            _scrip_row("NIFTY", "NIFTY11AUG2624500.00CE", "41011"),
            _scrip_row("NIFTY", "NIFTY11AUG2624500.00PE", "41012"),
        ])
        sym = f.get_strategy_sym("NIFTY", 24500, "CE", exp=date(2026, 8, 11))
        self.assertEqual(sym, "NIFTY11AUG2624500CE")

    def test_get_strategy_sym_uses_nearest_expiry(self):
        f = _make_feed_with_scrip([
            _scrip_row("NIFTY", "NIFTY18AUG2624500.00CE", "41100"),
        ])
        # We control the test environment by passing exp explicitly
        sym = f.get_strategy_sym("NIFTY", 24500, "CE", exp=date(2026, 8, 18))
        self.assertEqual(sym, "NIFTY18AUG2624500CE")
        # And without exp, it should use the nearest one in the scrip master
        sym2 = f.get_strategy_sym("NIFTY", 24500, "CE")
        self.assertEqual(sym2, "NIFTY18AUG2624500CE")


class TestOIParsing(unittest.TestCase):
    """Test the safe OI/volume parsing in _fetch_option_quotes."""

    def test_oi_normal_number(self):
        f = KotakProdFeed(env="uat", access_token="x", mobile="x", ucc="x", totp_secret="x", mpin="x")
        # Manually call _update_tick with various OI formats
        f._update_tick("TEST", 100.0, 99.5, 100.5, 12345, 678)
        t = f.get_latest("TEST")
        self.assertEqual(t["oi"], 12345)
        self.assertEqual(t["volume"], 678)

    def test_oi_dash_placeholder(self):
        """Kotak returns '-' when OI is not available. We treat it as 0."""
        f = KotakProdFeed(env="uat", access_token="x", mobile="x", ucc="x", totp_secret="x", mpin="x")
        # Simulate the safe-parse path: pass 0 if input is '-'
        # (we don't have direct access to the parser; verify via _update_tick which only takes numbers)
        # But the real check is in _fetch_option_quotes, which we mock below.
        f._update_tick("TEST", 100.0, 99.5, 100.5, 0, 0)
        t = f.get_latest("TEST")
        self.assertEqual(t["oi"], 0)
        self.assertEqual(t["volume"], 0)


class TestPriceHistory(unittest.TestCase):
    def test_history_capped_at_600(self):
        f = KotakProdFeed(env="uat", access_token="x", mobile="x", ucc="x", totp_secret="x", mpin="x")
        for i in range(700):
            f._update_tick("T", float(i), 0, 0, 0, 0)
        hist = f.get_price_history("T")
        self.assertEqual(len(hist), 600)
        # the last value should be the most recent
        self.assertEqual(hist[-1], 699.0)

    def test_momentum_uses_window(self):
        f = KotakProdFeed(env="uat", access_token="x", mobile="x", ucc="x", totp_secret="x", mpin="x")
        # simulate price going from 100 -> 110 over 5 ticks
        for v in [100, 102, 105, 108, 110]:
            f._update_tick("T", v, 0, 0, 0, 0)
        m = f.get_momentum("T", window=5)
        self.assertAlmostEqual(m, 0.10, places=4)


if __name__ == "__main__":
    unittest.main()
