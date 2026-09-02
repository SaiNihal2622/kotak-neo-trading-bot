"""Tests for the live-trading safety guard.

Verifies that:
1. Paper mode works without any env vars
2. Live mode refuses to start without KOTAK_LIVE_CONFIRMED=YES
3. Live mode refuses to start without KOTAK_ENV=prod
4. Live mode only succeeds with BOTH confirmations
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# Set fake env BEFORE importing build_broker
os.environ.setdefault('KOTAK_API_KEY', 'fake')
os.environ.setdefault('KOTAK_MOBILE', '+910000000000')
os.environ.setdefault('KOTAK_UCC', 'FAKE1')

from kotak_bot.__main__ import build_broker


def _paper_config():
    return {
        "mode": "paper",
        "broker": {"type": "paper", "paper_capital": 100_000, "environment": "uat"},
    }


def _live_config():
    return {
        "mode": "live",
        "broker": {"type": "neo", "live_capital": 100_000, "environment": "prod"},
    }


class TestBuildBroker(unittest.TestCase):
    def setUp(self):
        # Clean env between tests
        for k in ("KOTAK_LIVE_CONFIRMED", "KOTAK_ENV"):
            os.environ.pop(k, None)

    def test_paper_mode_works_without_confirmations(self):
        """Paper mode should never require any live-confirmation env vars."""
        cfg = _paper_config()
        broker = build_broker(cfg)
        # Should be a PaperClient, no exception
        self.assertIsInstance(broker, PaperClient)

    def test_live_mode_refuses_without_confirmation(self):
        """Without KOTAK_LIVE_CONFIRMED=YES, live mode must refuse."""
        cfg = _live_config()
        os.environ["KOTAK_ENV"] = "prod"
        with self.assertRaises(RuntimeError) as ctx:
            build_broker(cfg)
        self.assertIn("KOTAK_LIVE_CONFIRMED", str(ctx.exception))

    def test_live_mode_refuses_on_uat_env(self):
        """Even with confirmation, UAT env should be rejected in live mode."""
        cfg = _live_config()
        os.environ["KOTAK_LIVE_CONFIRMED"] = "YES"
        os.environ["KOTAK_ENV"] = "uat"
        with self.assertRaises(RuntimeError) as ctx:
            build_broker(cfg)
        self.assertIn("KOTAK_ENV=prod", str(ctx.exception))

    def test_live_mode_works_with_both_confirmations(self):
        """With both confirmations, build_broker should NOT raise the safety errors.
        It will likely fail at NeoClient init (no real broker), but the safety checks pass."""
        cfg = _live_config()
        os.environ["KOTAK_LIVE_CONFIRMED"] = "YES"
        os.environ["KOTAK_ENV"] = "prod"
        # We can't actually instantiate NeoClient here without real creds / network.
        # Just verify the safety checks pass: it gets to the NeoClient() call and tries to instantiate.
        try:
            with patch("kotak_bot.broker.neo_client.NeoClient") as mock_neo:
                mock_neo.return_value.connect.side_effect = Exception("mock: would connect")
                build_broker(cfg)
        except RuntimeError as e:
            # The two specific safety errors should NOT be the one we get:
            self.assertNotIn("KOTAK_LIVE_CONFIRMED", str(e))
            self.assertNotIn("KOTAK_ENV=prod", str(e))
        except Exception as e:
            # Other exceptions (e.g. network) are expected and fine
            self.assertNotIn("KOTAK_LIVE_CONFIRMED", str(e))
            self.assertNotIn("KOTAK_ENV=prod", str(e))


if __name__ == "__main__":
    unittest.main()
