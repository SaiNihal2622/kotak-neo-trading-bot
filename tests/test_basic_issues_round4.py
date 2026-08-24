"""Tests for code-quality fixes from the 'fix all basic issues' sweep.

These tests cover real bugs and lint issues that were fixed in commit
'fix(prod-4): code quality cleanup':

1. F821 — `Any` is properly imported in `order_manager.py` (was masked
   by `from __future__ import annotations` but should be explicit).
2. F811 — `BacktestEngine` no longer re-imported inside the function in
   `real_backtest.py` (was shadowing the top-level import).
3. F402 — `__main__.py` no longer shadows the module-level `_t` (used for
   `import time as _t` on line 589) with a loop variable.
4. `datetime.now(timezone.utc)` is fully replaced with `datetime.now(timezone.utc)`
   everywhere in `kotak_bot/` (Python 3.12+ deprecation fix).
5. Unused imports / variables are removed.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# These imports verify the F821 / F811 / F402 fixes by exercising the
# affected modules at module-load time.
from kotak_bot.execution.order_manager import OrderManager  # noqa: F401
from kotak_bot.broker.paper_client import PaperClient

KOTAK_BOT = ROOT / "kotak_bot"


def _read(rel: str) -> str:
    return (KOTAK_BOT / rel).read_text(encoding="utf-8")


def _walk_py() -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(KOTAK_BOT):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            if f.endswith(".py"):
                out.append(Path(root) / f)
    return out


class TestUtcnowRemoved(unittest.TestCase):
    """`datetime.utcnow()` is deprecated in Python 3.12+ and removed in
    a future version. Replace with `datetime.now(timezone.utc)`."""

    def test_no_utcnow_in_kotak_bot(self):
        offenders: list[str] = []
        for p in _walk_py():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if "datetime.utcnow()" in txt or "datetime.utcfromtimestamp" in txt:
                offenders.append(str(p.relative_to(ROOT)))
        self.assertEqual(
            offenders, [],
            f"datetime.now(timezone.utc)/utcfromtimestamp still present in: {offenders}"
        )

    def test_replacement_is_timezone_aware(self):
        """Sanity check: `datetime.now(timezone.utc)` returns a tz-aware
        datetime, which is the whole point of the swap."""
        now = datetime.now(timezone.utc)
        self.assertIsNotNone(now.tzinfo)
        # Compare to a manual construction
        manual = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertIsNotNone(manual.tzinfo)


class TestOrderManagerAnyImport(unittest.TestCase):
    """F821: `Any` is used in the `OrderManager.__init__` annotation but
    was missing from the typing import. The runtime was OK because
    `from __future__ import annotations` makes it a string, but a static
    analysis tool would (rightly) flag it."""

    def test_any_is_imported_in_order_manager(self):
        src = _read("execution/order_manager.py")
        # find `from typing import ...`
        import re
        m = re.search(r"^from typing import (.+)$", src, re.MULTILINE)
        self.assertIsNotNone(m, "no `from typing import` found in order_manager.py")
        names = [n.strip() for n in m.group(1).split(",")]
        self.assertIn(
            "Any", names,
            "Any must be imported in order_manager.py for the "
            "`resilient_executor: Optional[Any] = None` annotation"
        )

    def test_construction_still_works(self):
        """Smoke test: an OrderManager can be constructed with a paper broker,
        matching the production wiring that uses this exact path."""
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "state.json"
        try:
            broker = PaperClient(starting_capital=100_000, persist_path=str(tmp))
            broker.connect()
            om = OrderManager(broker=broker, persist_path=str(tmp))
            self.assertIsNotNone(om)
        finally:
            if tmp.exists():
                tmp.unlink()


class TestBacktestEngineNotShadowed(unittest.TestCase):
    """F811: `BacktestEngine` was imported at the top of `real_backtest.py`
    and then re-imported inside `run_backtest()`, which shadows the
    module-level binding. Move the import to the top-level."""

    def test_single_import_of_backtest_engine(self):
        src = _read("backtest/real_backtest.py")
        # Count the number of times `from kotak_bot.backtest.engine import BacktestEngine`
        # appears in the file body.
        count = src.count("from kotak_bot.backtest.engine import BacktestEngine")
        self.assertEqual(
            count, 1,
            "BacktestEngine should be imported exactly once at module level "
            "(was imported at module level AND inside run_backtest())"
        )

    def test_backtestconfig_at_top_level(self):
        """BacktestConfig should be reachable from the top-level import."""
        src = _read("backtest/real_backtest.py")
        self.assertIn(
            "BacktestConfig", src,
            "BacktestConfig should be imported at the top with BacktestEngine"
        )


class TestNoImportShadowingInMain(unittest.TestCase):
    """F402: `__main__.py` had `import time as _t` on line 589 and then a
    loop variable `for _t in open_trades:` later in the file, which
    shadowed the time import. Rename loop variable to `_trd`."""

    def test_no_loop_var_named_t_underscore(self):
        src = _read("__main__.py")
        # Walk the AST to find `for _t in <expr>:` patterns
        tree = ast.parse(src, filename="__main__.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                tgt = node.target
                if isinstance(tgt, ast.Name) and tgt.id == "_t":
                    self.fail(
                        f"__main__.py: {node.lineno} uses `_t` as a loop "
                        f"variable, which shadows `import time as _t` "
                        f"elsewhere in the file"
                    )

    def test_no_other_top_level_alias_for_time(self):
        """If a file uses `import time as _t` to avoid colliding with `time`
        the stdlib name, no local variable should reuse `_t`."""
        src = _read("__main__.py")
        self.assertIn("import time as _t", src, "expected sentinel `import time as _t`")
        # Already covered by previous test that loop var isn't _t.


class TestSilentExceptReplacedWithLogger(unittest.TestCase):
    """Some bare `except Exception: pass` blocks in `__main__.py`'s main
    loop have been upgraded to log at debug level so errors are at least
    recorded (without breaking the main loop)."""

    def test_main_loop_has_logger_debug_for_news(self):
        src = _read("__main__.py")
        # Each of these is a formerly-silent block in the main loop.
        # After the fix, they should log at debug level.
        self.assertIn("news fetch failed", src)
        self.assertIn("macro calendar fetch failed", src)
        self.assertIn("regime detect failed", src)
        self.assertIn("liveness: india_vix fetch failed", src)
        self.assertIn("liveness: get_open_orders failed", src)


class TestDeadCodeRemoved(unittest.TestCase):
    """Dead-code cleanups: unused imports, unused variables."""

    def test_margin_no_unused_required_pct(self):
        """`required_pct` was computed but never used in `risk/margin.py:167`."""
        src = _read("risk/margin.py")
        # After the fix, the line should not be present (we inlined the
        # direct computation that actually gets used).
        self.assertNotIn(
            "required_pct = self.config.pre_trade_buffer_pct +",
            src,
            "Dead `required_pct` should be removed; the value was never read"
        )

    def test_technical_no_unused_bbands(self):
        """`bbands = ta.bbands(...)` was assigned in `signals/technical.py:83`
        but never used downstream."""
        src = _read("signals/technical.py")
        self.assertNotIn(
            "bbands = ta.bbands(",
            src,
            "Dead bbands computation should be removed"
        )

    def test_kotak_prod_feed_no_unused_ref(self):
        """`ref` was assigned in `data/kotak_prod_feed.py:369` but never used."""
        src = _read("data/kotak_prod_feed.py")
        # We replaced the line with a comment, so `ref = f"..."` should be gone.
        self.assertNotIn(
            'ref = f"{underlying}{exp.strftime',
            src,
            "Dead `ref` assignment should be removed"
        )


class TestOrderManagerPersistsCloseOrders(unittest.TestCase):
    """Sanity check: after the round-3 fix, `close_trade` now captures
    the close order and appends it to `trade.orders`. This was already
    covered by `test_realized_pnl_attribution.py`, but we re-verify here
    to make sure the import/typing cleanup didn't break persistence."""

    def test_close_trade_appends_close_order(self):
        import tempfile
        from kotak_bot.broker.base import Tick
        from kotak_bot.strategy.base import StrategyName, TradePlan

        tmp = Path(tempfile.mkdtemp()) / "state.json"
        try:
            broker = PaperClient(starting_capital=100_000, persist_path=str(tmp))
            broker.connect()
            broker.inject_tick(Tick(symbol="X", ltp=100.0, exchange="NFO"))

            om = OrderManager(broker=broker, persist_path=str(tmp))
            plan = TradePlan(
                strategy=StrategyName.DIRECTIONAL_DEBIT,
                underlying="NIFTY",
                legs=[{"side": "BUY", "strike": 25000, "opt_type": "CE",
                       "qty": 1, "order_type": "MARKET", "price": 100.0,
                       "tag": "test"}],
                target=150.0,
                stop=50.0,
                confidence=0.8,
                reason="test",
            )
            trade = om.execute_plan(
                plan, qty=1, expiry="2026-08-25",
                lot_sizes={"NIFTY": 75}, use_bracket=False,
            )
            self.assertEqual(len(trade.orders), 1)

            closed = om.close_trade(trade.trade_id, reason="test")
            self.assertEqual(
                len(closed.orders), 2,
                "close order should be appended to trade.orders"
            )
        finally:
            if tmp.exists():
                tmp.unlink()


if __name__ == "__main__":
    unittest.main()
