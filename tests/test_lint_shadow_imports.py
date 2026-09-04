"""Regression test: lint_no_shadowing must catch the 5 documented shadow-import patterns.

The shadow-import bug class has hit us 5 times in production. The 5th
(2026-09-04 15:48) was on `sys`, not `Order` — `import sys` inside run_paper()
made sys local and broke sys.exit(0) in the RESTART_BOT branch.

This test calls the linter as a subprocess and verifies it fails on a tiny
Python file that exhibits the pattern. It does NOT try to enumerate every
case — that is the linter's job — it just ensures the linter does not
silently pass on the canonical pattern.
"""
import os
import subprocess
import sys
import tempfile
import textwrap

LINTER = os.path.join(os.path.dirname(__file__), "..", "scripts", "lint_no_shadowing.py")


def _run_linter_on(src_text: str):
    """Run the linter on a snippet. Returns (returncode, stdout)."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "_lint_test_file.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(src_text))
        cwd = os.getcwd()
        try:
            os.chdir(td)
            r = subprocess.run([sys.executable, LINTER], capture_output=True, text=True, timeout=15)
            return r.returncode, r.stdout, r.stderr
        finally:
            os.chdir(cwd)


def test_linter_catches_sys_shadow():
    """The 5th production incident (Sep 4 2026) was `import sys` inside
    run_paper() — sys.exit(0) earlier in the function became UnboundLocalError.
    """
    src = """
    def run_paper():
        sys.exit(0)
        import sys
        print(sys.path)
    """
    rc, out, _ = _run_linter_on(src)
    assert rc != 0, f"linter passed but should have caught sys shadow:\n{out}"
    assert "sys" in out.lower(), f"linter output missing sys reference:\n{out}"


def test_linter_catches_order_shadow():
    """The 4 prior incidents (Aug 27 - Sep 3) were `from kotak_bot.broker
    import Order, ...` inside run_paper() — Order(...) earlier in the
    function became UnboundLocalError.
    """
    src = """
    def run_paper():
        order = Order("X")
        from kotak_bot.broker import Order
    """
    rc, out, _ = _run_linter_on(src)
    assert rc != 0, f"linter passed but should have caught Order shadow:\n{out}"
    assert "order" in out.lower(), f"linter output missing Order reference:\n{out}"


def test_linter_passes_clean_function():
    """A function that imports a name and uses it AFTER the import should
    NOT be flagged (the import is the first reference, no earlier use to
    become UnboundLocalError).
    """
    src = """
    def helper():
        from kotak_bot.broker import Order
        return Order("X")
    """
    rc, out, _ = _run_linter_on(src)
    assert rc == 0, f"linter failed on clean code:\n{out}"


def test_linter_catches_missing_global():
    """The 6th production incident (Sep 4 23:47) was on
    `last_overnight_research_ts` — `last_overnight_research_ts = _now_unix`
    inside watch_loop() made it local for the whole function, and the
    earlier `if ... > 1800:` check on the same line failed with
    UnboundLocalError. Fix: add `global last_overnight_research_ts` to
    the function. This is a different class from the import-based bugs:
    an assignment shadows a module-level name.
    """
    src = """
    last_x = 0

    def watch_loop():
        if last_x > 100:  # earlier use of module-level name
            return
        last_x = 50  # assignment makes it local — UnboundLocalError on the line above
    """
    rc, out, _ = _run_linter_on(src)
    assert rc != 0, f"linter passed but should have caught missing global:\n{out}"
    assert "last_x" in out, f"linter output missing last_x reference:\n{out}"
    assert "missing_global_declaration" in out, f"linter output missing reason:\n{out}"


def test_linter_passes_global_declared():
    """A function that ASSIGNS to a module-level name WITH 'global X'
    declaration should NOT be flagged (that's the proper pattern).
    """
    src = """
    last_x = 0

    def watch_loop():
        global last_x
        if last_x > 100:  # earlier use is fine because we declared global
            return
        last_x = 50
    """
    rc, out, _ = _run_linter_on(src)
    assert rc == 0, f"linter failed on properly-declared global:\n{out}"


def test_linter_passes_function_local():
    """A function that assigns to a name that's NOT module-level should
    NOT be flagged (function-local variables are fine).
    """
    src = """
    def helper():
        if some_local > 100:  # earlier use of function-local
            return
        some_local = 50
    """
    rc, out, _ = _run_linter_on(src)
    assert rc == 0, f"linter failed on function-local variable:\n{out}"
