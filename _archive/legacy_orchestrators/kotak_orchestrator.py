"""Kotak Orchestrator — single entry point for the autonomous system.

Starts the brain and healer as managed subprocesses and keeps them alive.
The user (or a scheduled task / Windows service) only needs to start this
one process. Orchestrator handles lifecycle:

  1. Starts `python kotak_healer.py` as a detached child (monitors bot)
  2. Starts `python kotak_brain.py --once` periodically (LLM decisions)
  3. Logs everything to data_cache/orchestrator.log
  4. Persists a tiny state file so an external watchdog can verify it's alive

CLI:
  python kotak_orchestrator.py --once    # run one brain+healer check, exit
  python kotak_orchestrator.py            # loop, supervise forever
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

ORCH_STATE_PATH = ROOT / "data_cache" / "orchestrator_state.json"
ORCH_LOG_PATH = ROOT / "logs" / "orchestrator.log"

ORCH_INTERVAL_SEC = 60        # how often to do an orchestrator-level tick
BRAIN_INTERVAL_SEC = 900      # 15 min — brain evaluates this often
HEALER_TICK_SEC = 60          # healer tick is 60s; we don't need to re-fork
PYTHON_EXE = sys.executable    # use whatever python is running us


def _save_state(state: dict) -> None:
    try:
        ORCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ORCH_STATE_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        tmp.replace(ORCH_STATE_PATH)
    except Exception as e:
        logger.error(f"orch: could not save state: {e}")


def _run_brain_once() -> bool:
    try:
        r = subprocess.run(
            [PYTHON_EXE, str(ROOT / "kotak_brain.py"), "--once"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            logger.info("orch: brain --once succeeded")
            return True
        logger.warning(f"orch: brain --once failed (rc={r.returncode}): {r.stderr[:200]}")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("orch: brain --once timed out")
        return False
    except Exception as e:
        logger.exception(f"orch: brain --once exception: {e}")
        return False


def _run_healer_once() -> bool:
    try:
        r = subprocess.run(
            [PYTHON_EXE, str(ROOT / "kotak_healer.py"), "--once"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            logger.debug("orch: healer --once ok")
            return True
        logger.warning(f"orch: healer --once failed (rc={r.returncode}): {r.stderr[:200]}")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("orch: healer --once timed out")
        return False
    except Exception as e:
        logger.exception(f"orch: healer --once exception: {e}")
        return False


def _start_healer_loop() -> subprocess.Popen | None:
    """Start the healer as a long-running subprocess (it loops internally)."""
    try:
        p = subprocess.Popen(
            [PYTHON_EXE, str(ROOT / "kotak_healer.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        logger.info(f"orch: healer started (pid={p.pid})")
        return p
    except Exception as e:
        logger.exception(f"orch: could not start healer: {e}")
        return None


def tick(state: dict) -> dict:
    """One orchestrator tick."""
    now = time.time()
    state["tick_count"] = int(state.get("tick_count", 0)) + 1
    state["last_tick"] = datetime.utcnow().isoformat() + "Z"

    # Run healer tick
    _run_healer_once()

    # Run brain every BRAIN_INTERVAL_SEC (or always on first tick)
    last_brain = float(state.get("last_brain_at", 0))
    if (now - last_brain) >= BRAIN_INTERVAL_SEC or last_brain == 0:
        if _run_brain_once():
            state["last_brain_at"] = now

    # Make sure healer subprocess is alive (only if we started one in loop mode)
    healer_pid = state.get("healer_pid")
    if healer_pid:
        try:
            import psutil  # noqa
            p = psutil.Process(healer_pid)
            if not p.is_running():
                logger.warning(f"orch: healer pid {healer_pid} died, restarting")
                new = _start_healer_loop()
                state["healer_pid"] = new.pid if new else None
        except Exception:
            # psutil not available — skip subprocess check (healer is independent)
            pass

    _save_state(state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
                        help="Run a single orchestrator tick then exit")
    args = parser.parse_args()

    ORCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.add(str(ORCH_LOG_PATH), rotation="1 day", retention="14 days", level="INFO")
    logger.info(f"orch: starting (once={args.once}) pid={os.getpid()}")

    # PID lock — prevent double-launch
    pidfile = ROOT / "data_cache" / "orchestrator.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    if pidfile.exists():
        try:
            old = int(pidfile.read_text().strip() or "0")
            if old and old != os.getpid():
                import psutil  # type: ignore
                if psutil.pid_exists(old):
                    logger.warning(f"orch: another instance alive pid={old}, exiting")
                    return 0
        except Exception:
            pass
    pidfile.write_text(str(os.getpid()))

    try:
        if args.once:
            tick({})
            return 0

        # loop mode: start healer as long-running subprocess, do periodic brain ticks
        state: dict = {}
        healer = _start_healer_loop()
        if healer:
            state["healer_pid"] = healer.pid

        stop = False
        def _sigint(_sig, _frm):
            nonlocal stop
            stop = True
            logger.info("orch: SIGINT")
        try:
            signal.signal(signal.SIGINT, _sigint)
        except Exception:
            pass

        try:
            while not stop:
                tick(state)
                for _ in range(ORCH_INTERVAL_SEC):
                    if stop:
                        break
                    time.sleep(1)
        finally:
            if healer:
                try:
                    healer.terminate()
                except Exception:
                    pass
        return 0
    finally:
        try:
            if int(pidfile.read_text().strip() or "0") == os.getpid():
                pidfile.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
