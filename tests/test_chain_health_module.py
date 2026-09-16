"""Tests for the chain health check and phantom fill validator (FIX 2026-09-11)."""
import math
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch
import sys

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestValidateFillPrice:
    """Reject phantom fill prices (Rs.1.0 default, 10x off, etc.)."""

    def test_valid_nifty_price(self):
        from scripts.chain_health import validate_fill_price
        r = validate_fill_price("NIFTY17SEP2623250PE", 102.22)
        assert r["ok"] is True

    def test_reject_rs1_nifty_phantom(self):
        from scripts.chain_health import validate_fill_price
        r = validate_fill_price("NIFTY17SEP2623250PE", 1.0)
        assert r["ok"] is False
        assert "phantom" in r["reason"].lower() or "minimum" in r["reason"].lower()

    def test_reject_sub_minimum_price(self):
        from scripts.chain_health import validate_fill_price
        r = validate_fill_price("NIFTY17SEP2623250PE", 3.0)
        assert r["ok"] is False  # below Rs.5 for NIFTY

    def test_reject_sub_minimum_banknifty(self):
        from scripts.chain_health import validate_fill_price
        r = validate_fill_price("BANKNIFTY10SEP2657200CE", 15.0)
        assert r["ok"] is False  # below Rs.20 for BANKNIFTY

    def test_reject_extreme_high(self):
        from scripts.chain_health import validate_fill_price
        r = validate_fill_price("NIFTY17SEP2623250PE", 10000.0)
        assert r["ok"] is False  # above Rs.3000 for NIFTY

    def test_reject_2x_off_from_expected(self):
        from scripts.chain_health import validate_fill_price
        # expected Rs.100, chain shows Rs.500 (5x off)
        r = validate_fill_price("NIFTY17SEP2623250PE", 500.0, expected_price=100.0)
        assert r["ok"] is False
        assert "differs" in r["reason"].lower()

    def test_accept_within_2x_of_expected(self):
        from scripts.chain_health import validate_fill_price
        # expected Rs.100, chain shows Rs.150 (1.5x)
        r = validate_fill_price("NIFTY17SEP2623250PE", 150.0, expected_price=100.0)
        assert r["ok"] is True

    def test_unparseable_symbol(self):
        from scripts.chain_health import validate_fill_price
        r = validate_fill_price("GARBAGE123", 100.0)
        assert r["ok"] is False

    def test_zero_price(self):
        from scripts.chain_health import validate_fill_price
        r = validate_fill_price("NIFTY17SEP2623250PE", 0.0)
        assert r["ok"] is False


class TestBSEstimate:
    """Black-Scholes estimate for option prices."""

    def test_atm_call(self):
        from scripts.chain_health import bs_estimate
        # NIFTY ATM, 5 DTE, IV 15%
        p = bs_estimate(23500, 23500, "CE", days_to_expiry=5, iv=0.15)
        assert p is not None
        # ATM 5DTE IV15%: ~Rs.150-200
        assert 100 < p < 300

    def test_atm_put(self):
        from scripts.chain_health import bs_estimate
        p = bs_estimate(23500, 23500, "PE", days_to_expiry=5, iv=0.15)
        assert p is not None
        # ATM put-call parity: should be ~ATM call + strike*exp(-rT) - spot
        # For ATM with r=6.5%, T=5/365: ~Rs.150
        assert 100 < p < 300

    def test_deep_itm_call(self):
        from scripts.chain_health import bs_estimate
        # Spot 24000, strike 23000 (1000pt ITM call)
        p = bs_estimate(24000, 23000, "CE", days_to_expiry=5, iv=0.15)
        assert p is not None
        # Intrinsic = 1000, plus time value
        assert p > 1000

    def test_deep_otm_call(self):
        from scripts.chain_health import bs_estimate
        # Spot 23000, strike 24000 (1000pt OTM call)
        p = bs_estimate(23000, 24000, "CE", days_to_expiry=5, iv=0.15)
        assert p is not None
        assert p < 50  # very small

    def test_zero_dte(self):
        from scripts.chain_health import bs_estimate
        # 0DTE: should still give a price
        p = bs_estimate(23500, 23500, "CE", days_to_expiry=0.5, iv=0.20)
        assert p is not None
        assert 10 < p < 200

    def test_invalid_inputs(self):
        from scripts.chain_health import bs_estimate
        assert bs_estimate(0, 23500, "CE", 5, 0.15) is None
        assert bs_estimate(23500, 0, "CE", 5, 0.15) is None
        assert bs_estimate(23500, 23500, "CE", 0, 0.15) is None
        assert bs_estimate(23500, 23500, "XX", 5, 0.15) is None


class TestGetSafeFillPrice:
    """Main API: combine validation + BS fallback."""

    def test_chain_valid_returns_chain_price(self):
        from scripts.chain_health import get_safe_fill_price
        r = get_safe_fill_price("NIFTY17SEP2623250PE", 102.22)
        assert r["source"] == "chain"
        assert r["price"] == 102.22

    def test_chain_phantom_falls_back_to_bs(self):
        from scripts.chain_health import get_safe_fill_price
        # chain shows Rs.1.0 (phantom) — should fall back to BS
        r = get_safe_fill_price("NIFTY17SEP2623250PE", 1.0, spot=23477.0)
        assert r["source"] in ("bs", "rejected")
        if r["source"] == "bs":
            assert r["price"] > 5.0  # BS gives realistic price
            assert r["price"] < 3000.0

    def test_no_chain_no_spot_rejected(self):
        from scripts.chain_health import get_safe_fill_price
        r = get_safe_fill_price("NIFTY17SEP2623250PE", 0, spot=None)
        assert r["source"] == "rejected"


class TestParseSymbol:
    """Parse NSE option symbol format."""

    def test_nifty_weekly(self):
        from scripts.chain_health import parse_symbol
        p = parse_symbol("NIFTY17SEP2623600PE")
        assert p is not None
        assert p["underlying"] == "NIFTY"
        assert p["strike"] == 23600
        assert p["opt_type"] == "PE"
        assert p["day"] == 17
        assert p["month"] == "SEP"
        assert p["year"] == 26

    def test_banknifty_monthly(self):
        from scripts.chain_health import parse_symbol
        p = parse_symbol("BANKNIFTY28OCT2657200CE")
        assert p is not None
        assert p["underlying"] == "BANKNIFTY"
        assert p["strike"] == 57200
        assert p["opt_type"] == "CE"

    def test_garbage_returns_none(self):
        from scripts.chain_health import parse_symbol
        assert parse_symbol("GARBAGE") is None
        assert parse_symbol("") is None
        assert parse_symbol("NIFTY17SEP26") is None  # missing strike + opt

    def test_lowercase_works(self):
        from scripts.chain_health import parse_symbol
        p = parse_symbol("nifty17sep2623600pe")
        assert p is not None
        assert p["underlying"] == "NIFTY"


class TestChainHealth:
    """Detect broken option chains (the Sep 11 root cause)."""

    def setup_method(self):
        """Write a known-bad NIFTY chain to a temp dir."""
        from scripts.chain_health import reset_cache
        reset_cache()

    def test_healthy_chain(self, tmp_path, monkeypatch):
        """A chain with correct monotonicity is healthy: PE prices INCREASE
        as strike increases (more intrinsic / closer-to-ATM for puts), and
        CE prices DECREASE as strike increases (more OTM = less intrinsic)."""
        monkeypatch.setattr("scripts.chain_health.DCACHE", tmp_path)
        # Healthy chain: spot 23500, strikes 23300-23700 (all near ATM)
        strikes = {}
        for s in [23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]:
            # Correct: PE price goes UP as strike goes UP (intrinsic + time value)
            strikes[f"{s}_PE"] = {"strike": s, "opt_type": "PE", "price": 100 + (s - 23300) * 0.5}
            # Correct: CE price goes DOWN as strike goes UP (less intrinsic)
            strikes[f"{s}_CE"] = {"strike": s, "opt_type": "CE", "price": 100 - (s - 23300) * 0.5}
        chain = {"spot": 23500, "strikes": strikes}
        (tmp_path / "option_chain_NIFTY.json").write_text(json.dumps(chain), encoding="utf-8")
        from scripts.chain_health import check_chain_health
        h = check_chain_health("NIFTY", use_cache=False)
        assert h["healthy"] is True, f"Chain should be healthy: {h}"

    def test_inverted_pe_detected(self, tmp_path, monkeypatch):
        """A chain with PE prices DECREASING as strike INCREASES is broken.

        For puts, lower strike = more intrinsic value (more ITM) = HIGHER price.
        A chain where ITM puts (low strike) cost LESS than OTM puts (high strike)
        is the inverted-PE corruption we saw from yfinance on Sep 11 — the
        opposite of what a correct put curve looks like.
        """
        monkeypatch.setattr("scripts.chain_health.DCACHE", tmp_path)
        # Broken chain: PE prices go DOWN as strike goes UP (ITM < OTM is wrong).
        # Spot 23500, strikes 23300-23700.
        strikes = {}
        for s in [23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]:
            # Bug: lower strike (more ITM) = LOWER price (opposite of reality)
            strikes[f"{s}_PE"] = {"strike": s, "opt_type": "PE", "price": 100 - (s - 23300) * 0.5}
        chain = {"spot": 23500, "strikes": strikes}
        (tmp_path / "option_chain_NIFTY.json").write_text(json.dumps(chain), encoding="utf-8")
        from scripts.chain_health import check_chain_health
        h = check_chain_health("NIFTY", use_cache=False)
        assert h["healthy"] is False, f"inverted chain should be flagged unhealthy: {h}"
        assert any("inverted" in i.lower() for i in h["issues"]), (
            f"expected an issue mentioning 'inverted', got: {h['issues']}"
        )

    def test_healthy_chain_with_correct_pe_curve(self, tmp_path, monkeypatch):
        """Sanity: a CORRECT put curve (price goes UP as strike goes UP, because
        higher strike = more ITM = more intrinsic for puts above spot) should
        NOT be flagged as inverted. The pre-fix check was backwards and would
        have flagged this normal behavior."""
        monkeypatch.setattr("scripts.chain_health.DCACHE", tmp_path)
        strikes = {}
        for s in [23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]:
            # Correct: higher strike = higher PE price
            strikes[f"{s}_PE"] = {"strike": s, "opt_type": "PE", "price": 100 + (s - 23300) * 0.5}
        chain = {"spot": 23500, "strikes": strikes}
        (tmp_path / "option_chain_NIFTY.json").write_text(json.dumps(chain), encoding="utf-8")
        from scripts.chain_health import check_chain_health
        h = check_chain_health("NIFTY", use_cache=False)
        # No inversion issue (other issues like spot-range might still flag)
        inv_issues = [i for i in h["issues"] if "inverted" in i.lower()]
        assert inv_issues == [], f"correct put curve flagged as inverted: {inv_issues}"

    def test_bad_spot_detected(self, tmp_path, monkeypatch):
        """FINNIFTY spot=5071 (real is 25,200) should be flagged."""
        monkeypatch.setattr("scripts.chain_health.DCACHE", tmp_path)
        strikes = {}
        for s in [5050, 5100, 5150, 5200, 5250]:
            strikes[f"{s}_PE"] = {"strike": s, "opt_type": "PE", "price": 50}
        chain = {"spot": 5071, "strikes": strikes}
        (tmp_path / "option_chain_FINNIFTY.json").write_text(json.dumps(chain), encoding="utf-8")
        from scripts.chain_health import check_chain_health
        h = check_chain_health("FINNIFTY", use_cache=False)
        assert h["healthy"] is False
        assert any("spot" in i.lower() and "range" in i.lower() for i in h["issues"])

    def test_missing_chain(self, tmp_path, monkeypatch):
        """No chain file = unhealthy."""
        monkeypatch.setattr("scripts.chain_health.DCACHE", tmp_path)
        from scripts.chain_health import check_chain_health
        h = check_chain_health("MISSING", use_cache=False)
        assert h["healthy"] is False
        assert "missing" in h["issues"][0].lower()

    def test_all_zero_prices_detected(self, tmp_path, monkeypatch):
        """Chain with all zero prices = unhealthy."""
        monkeypatch.setattr("scripts.chain_health.DCACHE", tmp_path)
        strikes = {f"{s}_PE": {"strike": s, "opt_type": "PE", "price": 0}
                   for s in [23300, 23400, 23500]}
        chain = {"spot": 23500, "strikes": strikes}
        (tmp_path / "option_chain_NIFTY.json").write_text(json.dumps(chain), encoding="utf-8")
        from scripts.chain_health import check_chain_health
        h = check_chain_health("NIFTY", use_cache=False)
        assert h["healthy"] is False
        assert any("zero" in i.lower() for i in h["issues"])
