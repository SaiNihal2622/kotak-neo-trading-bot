"""_update_self_test_log.py - record self-test results to data_cache/performance/self_review.json.

FIX 2026-09-04 13:46: live_trading_gates.py checks self_review.json. The self-test
order script (scripts/_self_test_orders.py) doesn't currently write to this log.
This wrapper script runs the self-test and records the result.

Run this daily (or add to daily_maintenance.py at 08:25 IST).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def main():
    log_path = ROOT / "data_cache" / "performance" / "self_review.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Run the self-test
    ret = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "_self_test_orders.py")],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    passed = ret.returncode == 0

    # Read or create the log
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:
            log = {}
    else:
        log = {}

    log["last_test_at"] = datetime.now().isoformat()
    log["last_passed_at"] = datetime.now().isoformat() if passed else log.get("last_passed_at", "")
    log["last_passed"] = passed
    log["tests_total"] = log.get("tests_total", 0) + 1
    log["tests_passed"] = log.get("tests_passed", 0) + (1 if passed else 0)
    log["tests_failed"] = log.get("tests_failed", 0) + (0 if passed else 1)
    log["last_stdout_tail"] = ret.stdout[-500:]
    log["last_stderr_tail"] = ret.stderr[-500:]

    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"self-test {'PASSED' if passed else 'FAILED'} — log updated at {log_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
