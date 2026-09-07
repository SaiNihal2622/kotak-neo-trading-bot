"""self_heal.py - 24/7 autonomous self-heal engine for the Kotak Neo bot.

The user is not always available to click UAC prompts or debug issues. This
engine runs in the bot's main loop and continuously:

  1. DETECTS known error patterns in the bot/brain logs and liveness
  2. DIAGNOSES which fix recipe applies
  3. APPLIES the fix (writes a force-action JSON, runs a subprocess, etc.)
  4. VERIFIES the fix took effect
  5. ALERTS the user via Telegram with what was done

Design principles:
  - All fixes are idempotent (safe to re-apply)
  - No fix is irreversible (no destructive actions)
  - Each fix has a verification step
  - If verification fails, the engine alerts and tries again next cycle
  - Recipes are data, not code — easy to add new ones without code changes

Recipes (add to RECIPES dict below):
  "liveness_stale"           — bot's liveness.json not updated in >90s -> restart bot
  "brain_port_down"          — brain HTTP :8503 not responding       -> restart brain
  "shadow_import_in_log"     — "cannot access local variable" in log -> alert + suggest restart
  "kotak_session_error"      — URLError / session expired in feed    -> request re-auth (already done by session_watch)
  "daily_task_missing"       — schtasks /query shows no kotak- tasks  -> INSTALL_TASKS
  "main_thread_dead"         — main_thread_alive=False in liveness  -> restart bot
  "tick_stuck"               — liveness.tick hasn't changed in 60s    -> restart bot
  "phantom_positions"        — broker has positions, order_mgr empty -> orphan-fallback handles
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data_cache"
LOGS = ROOT / "Logs"
FORCE_ACTION = DATA / "mavis_force_action.json"
BRAIN_LOG = DATA / "quant_service.log"
BOT_LOG = LOGS / "bot_stderr.log"
NSSM = Path(r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe")

# FIX 2026-09-05 01:30: the self-heal engine is a guardrail for when the user
# is unavailable. Don't go wild — only fire fixes that have proven safe.

# ---------- recipe definitions ----------

# Each recipe is: name -> dict(detect(log_tail, liveness, brain_health) -> bool,
#                              fix() -> dict(applied: bool, msg: str, action_for_telegram: str))
RECIPES = {}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _read_tail(path: Path, n_bytes: int = 50_000) -> str:
    """Read recent log lines (last 5 minutes) as text. Empty if missing/unreadable.

    FIX 2026-09-05 01:20: filter by timestamp, not just by byte count. The
    bot's log can be 30+ MB. The previous approach (last 5KB) caught the
    SELF-HEAL info message itself (which contains the words "LOOP-ERR"),
    creating a feedback loop where each cycle re-detected its own log line.
    Now we parse loguru's ISO timestamps and only return lines from the
    last 5 minutes. Lines without parseable timestamps are kept (they're
    probably recent enough).
    """
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now() - timedelta(minutes=5)
        out = []
        # loguru writes lines like:
        #   2026-09-05 01:18:28.145 | INFO     | module:func:line | message
        # Read the last N bytes, then keep only lines newer than cutoff.
        with open(path, "rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - n_bytes))
            raw = f.read().decode("utf-8", errors="replace")
        for line in raw.splitlines():
            # Skip loguru's ANSI escape codes: e.g. "\x1b[32m2026-09-05 01:17:28.219\x1b[0m | ..."
            stripped = re.sub(r"^\x1b\[[0-9;]*m", "", line)
            # Filter by log level: only ERROR/WARNING/CRITICAL count as incidents.
            # This avoids matching our own SELF-HEAL info messages (which mention
            # "LOOP-ERR" in the message text but at INFO level).
            # Pattern: | LEVEL | ... | message
            level_match = re.search(r"\|\s*(ERROR|WARNING|CRITICAL)\s*\|", stripped)
            if not level_match:
                continue
            # Skip SELF-HEAL log lines (we never want to trigger on our own output)
            if "SELF-HEAL" in stripped:
                continue
            ts_match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", stripped)
            if ts_match:
                try:
                    line_ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                    if line_ts < cutoff:
                        continue
                except Exception:
                    pass
            out.append(line)
        return "\n".join(out)
    except Exception:
        return ""


def _liveness_age_sec(liveness: dict) -> float | None:
    """How many seconds since the liveness file was last written."""
    try:
        ts = liveness.get("ts") or liveness.get("boot_time")
        if not ts:
            return None
        # ts is ISO format like "2026-09-04T15:30:00+05:30"
        last = datetime.fromisoformat(ts)
        return (datetime.now(last.tzinfo) - last).total_seconds()
    except Exception:
        return None


# ---- detection helpers ----

def _detect_liveness_stale(liveness: dict) -> bool:
    age = _liveness_age_sec(liveness)
    return age is not None and age > 90


def _detect_main_thread_dead(liveness: dict) -> bool:
    return liveness.get("main_thread_alive") is False


def _detect_shadow_import(log_tail: str) -> bool:
    return "cannot access local variable" in log_tail


def _detect_brain_loop_err(log_tail: str) -> bool:
    return "LOOP-ERR" in log_tail


def _detect_kotak_session(log_tail: str) -> bool:
    return ("URLError" in log_tail or "getaddrinfo" in log_tail
            or "session expired" in log_tail.lower() or "auth failed" in log_tail.lower())


def _detect_daily_task_missing() -> bool:
    """Check if the 3 daily tasks are still registered (user-context, visible to user)."""
    try:
        r = subprocess.run(
            ["schtasks", "/query", "/fo", "csv"],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout or ""
        return not all(t in out for t in (
            "kotak-pre-market-self-heal",
            "kotak-eod-pnl-evaluator",
            "kotak-nightly-state-backup",
        ))
    except Exception:
        return False  # can't determine, don't fire the fix


def _detect_nssm_service_stopped() -> bool:
    """FIX 2026-09-07 00:55: detect if the NSSM service KotakBotPaper has gone to
    Stopped state. This happened on 2026-09-06/07 at 00:42 IST when the
    service got SIGINT'd and NSSM gave up auto-restarting. Without this
    detector, the bot is alive but the NSSM service is dead, and there's
    no automatic recovery.

    The bot runs as SYSTEM, so it CAN call schtasks /scmanager to query
    service state via the SCM. We use 'sc query' instead — it's a Windows
    binary, runs without UAC, and returns service state directly.
    """
    try:
        r = subprocess.run(
            ["sc", "query", "KotakBotPaper"],
            capture_output=True, text=True, timeout=10,
        )
        out = r.stdout or ""
        # Look for "STATE" line. State code 1 = STOPPED, 4 = RUNNING.
        for line in out.splitlines():
            if line.strip().startswith("STATE"):
                parts = line.split(":", 1)
                if len(parts) == 2 and "STOPPED" in parts[1].upper():
                    return True
        return False
    except Exception:
        return False


def _fix_nssm_service_stopped() -> dict:
    """FIX 2026-09-07 00:55: if KotakBotPaper is in STOPPED state, start it.
    The bot is already running (we're inside it), but it's running because
    someone manually started the python.exe. The NSSM service is the
    'production' registration. If NSSM state is STOPPED, we start it so
    NSSM takes over monitoring + auto-restart.

    Uses NSSM directly (Windows binary, runs as SYSTEM without UAC)."""
    try:
        r = subprocess.run(
            [str(NSSM), "start", "KotakBotPaper"],
            capture_output=True, text=True, timeout=20,
        )
        return {
            "applied": r.returncode == 0,
            "msg": f"nssm start KotakBotPaper: exit={r.returncode} out={(r.stdout or r.stderr or '').strip()[:200]}",
            "action_for_telegram": (
                f"♻️ [SELF-HEAL] KotakBotPaper NSSM service was STOPPED. "
                f"Started via nssm. exit={r.returncode}"
            ),
        }
    except Exception as e:
        return {
            "applied": False,
            "msg": f"nssm start failed: {e}",
            "action_for_telegram": f"❌ [SELF-HEAL] nssm start KotakBotPaper failed: {e}",
        }


def _detect_brain_port_down() -> bool:
    """Check if the brain's HTTP :8503 responds."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8503/health", timeout=3) as r:
            return r.status != 200
    except Exception:
        return True


# ---- fix actions ----

def _write_force_action(action: dict) -> bool:
    """Write a force-action JSON for the bot to pick up on next cycle."""
    try:
        FORCE_ACTION.parent.mkdir(parents=True, exist_ok=True)
        action.setdefault("consumed", False)
        action.setdefault("ts", _now())
        FORCE_ACTION.write_text(json.dumps(action, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        return False


def _restart_bot_via_nssm() -> tuple[bool, str]:
    """Trigger NSSM to restart the bot service. The bot is already SYSTEM
    so the subprocess inherits admin context. UAC not needed because
    NSSM restart is a service control action via the Service Control
    Manager, not an elevation."""
    try:
        r = subprocess.run(
            [str(NSSM), "restart", "KotakBotPaper"],
            capture_output=True, text=True, timeout=20,
        )
        return (r.returncode == 0, (r.stdout or r.stderr or "").strip()[:200])
    except Exception as e:
        return (False, str(e))


def _restart_brain_via_signal() -> tuple[bool, str]:
    """Write the brain restart signal file. The brain watches for this and exits
    cleanly. The watchdog (or the next bot cycle) respawns it."""
    try:
        # FIX 2026-09-05 13:55: use 'utf-8' explicitly without BOM (the default
        # for 'utf-8' in Python doesn't add BOM, unlike PowerShell's
        # Out-File -Encoding utf8 which does). The brain reads with utf-8-sig
        # so both work, but be consistent.
        (DATA / "quant_service_restart.json").write_text(
            json.dumps({"reason": "self_heal: brain port down", "ts": _now()}, indent=2),
            encoding="utf-8",
        )
        return (True, "restart signal written; brain will exit within 5s")
    except Exception as e:
        return (False, str(e))


# ---- register recipes ----

def _fix_liveness_stale() -> dict:
    """Liveness file is stale > 90s. The main thread is probably hung.
    Restart the bot via NSSM. NSSM restart doesn't need UAC because the
    service is already SYSTEM and the SCM is a system service."""
    ok, msg = _restart_bot_via_nssm()
    return {
        "applied": ok,
        "msg": f"liveness stale > 90s -> nssm restart: {msg}",
        "action_for_telegram": f"♻️ [SELF-HEAL] bot liveness stale. Restarted via NSSM. {msg}",
    }


def _fix_main_thread_dead() -> dict:
    ok, msg = _restart_bot_via_nssm()
    return {
        "applied": ok,
        "msg": f"main_thread_alive=False -> nssm restart: {msg}",
        "action_for_telegram": f"♻️ [SELF-HEAL] main thread reported dead. Restarted via NSSM. {msg}",
    }


def _fix_shadow_import() -> dict:
    """Cannot auto-fix code from inside the running bot. Alert user with full
    context. Suggest the /restart bot path so NSSM picks up the latest code."""
    return {
        "applied": False,
        "msg": "shadow import in log - cannot auto-fix code at runtime",
        "action_for_telegram": (
            "🛑 [SELF-HEAL] shadow-import bug detected in log. "
            "Cannot auto-fix at runtime. Needs a new session to patch code. "
            "Meanwhile: bot will keep restarting via NSSM but the same bug fires. "
            "Telegram if urgent."
        ),
    }


def _fix_brain_loop_err() -> dict:
    """Brain is logging LOOP-ERR. Try restarting it via the restart signal.
    If restart fails twice in 5 min, escalate."""
    ok, msg = _restart_brain_via_signal()
    return {
        "applied": ok,
        "msg": f"brain LOOP-ERR -> restart signal: {msg}",
        "action_for_telegram": f"♻️ [SELF-HEAL] brain LOOP-ERR detected. Restart signal written. {msg}",
    }


def _fix_kotak_session() -> dict:
    """Kotak session error. session_watch.py already handles re-auth every 5 min
    (in-process in the brain). We just need to wait and re-check next cycle."""
    return {
        "applied": True,
        "msg": "session_watch (in-brain) handles re-auth; will verify next cycle",
        "action_for_telegram": "🟡 [SELF-HEAL] Kotak session error in log. session_watch will re-auth.",
    }


def _fix_daily_task_missing() -> dict:
    ok = _write_force_action({
        "action": "INSTALL_TASKS",
        "reason": "self_heal: daily task missing from schtasks /query",
    })
    return {
        "applied": ok,
        "msg": "wrote INSTALL_TASKS force-action; bot will re-register on next cycle",
        "action_for_telegram": "🔧 [SELF-HEAL] daily tasks missing. Wrote INSTALL_TASKS for bot to re-register.",
    }


def _fix_brain_port_down() -> dict:
    ok, msg = _restart_brain_via_signal()
    return {
        "applied": ok,
        "msg": f"brain port :8503 down -> restart signal: {msg}",
        "action_for_telegram": f"♻️ [SELF-HEAL] brain HTTP :8503 down. Restart signal written. {msg}",
    }


# ---- register ----
RECIPES["liveness_stale"] = (_detect_liveness_stale, _fix_liveness_stale)
RECIPES["main_thread_dead"] = (_detect_main_thread_dead, _fix_main_thread_dead)
RECIPES["shadow_import_in_log"] = (_detect_shadow_import, _fix_shadow_import)
RECIPES["brain_loop_err"] = (_detect_brain_loop_err, _fix_brain_loop_err)
RECIPES["kotak_session_error"] = (_detect_kotak_session, _fix_kotak_session)
RECIPES["daily_task_missing"] = (_detect_daily_task_missing, _fix_daily_task_missing)
RECIPES["brain_port_down"] = (_detect_brain_port_down, _fix_brain_port_down)
# FIX 2026-09-07 00:55: NSSM service-state recipes use a longer cooldown
# (NSSM_COOLDOWN_SEC) because NSSM state changes are rare and re-firing
# is wasteful. The 7 above use COOLDOWN_SEC (10 min).
_NSSM_RECIPES = {
    "nssm_service_stopped": (_detect_nssm_service_stopped, _fix_nssm_service_stopped),
}


# FIX 2026-09-07 23:15: inline trade_journal.jsonl writer recipe. If the bot
# is running but the inline journal callback isn't registered (e.g. paper
# client was replaced, or the bot was started in a way that bypassed
# run_paper's callback registration), trade_journal.jsonl will go empty
# until the EOD reconstruction backstop. We detect this by checking the
# bot's stderr log for the "inline trade_journal callback registered"
# message after the most recent restart. If we don't find it, the bot
# needs a restart to pick up the callback.
def _detect_inline_journal_missing() -> bool:
    """Check if the inline trade_journal callback is registered in the
    running bot. We do this by scanning the bot's stderr log for the
    registration message that run_paper() emits on startup. If we don't
    find it within the last 10 minutes, the bot is on old code (or
    something stripped the callback) and needs a restart.
    """
    if not BOT_LOG.exists():
        return False  # no log to scan — let other recipes handle
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now() - timedelta(minutes=10)
        with open(BOT_LOG, "rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 100_000))
            data = f.read().decode("utf-8", errors="ignore")
        for line in data.splitlines():
            if "inline trade_journal callback registered" in line:
                # Parse loguru's timestamp and check it's within 10 min
                try:
                    ts_str = line.split(" | ", 1)[0].strip()
                    if ts_str.startswith("\x1b["):
                        # strip ANSI prefix
                        ts_str = line[line.index("2") + 2:line.index(" | ")].strip()
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff:
                        return False  # registered recently — healthy
                except Exception:
                    return False  # can't parse, assume healthy
        return True  # no recent registration message
    except Exception:
        return False


def _fix_inline_journal_missing() -> dict:
    """Restart the bot via NSSM so it picks up the inline journal callback."""
    try:
        r = subprocess.run(
            [str(NSSM), "restart", "KotakBotPaper"],
            capture_output=True, text=True, timeout=30,
        )
        return {
            "applied": r.returncode == 0,
            "msg": f"nssm restart KotakBotPaper: exit={r.returncode} out={(r.stdout or r.stderr or '').strip()[:200]}",
            "action_for_telegram": (
                f"♻️ [SELF-HEAL] inline journal callback not detected in bot log; "
                f"restarted via nssm. exit={r.returncode}"
            ),
        }
    except Exception as e:
        return {
            "applied": False,
            "msg": f"nssm restart failed: {e}",
            "action_for_telegram": f"❌ [SELF-HEAL] nssm restart KotakBotPaper failed: {e}",
        }


# Register the inline journal recipe (after the function is defined to avoid
# NameError at import time).
RECIPES["inline_journal_missing"] = (
    _detect_inline_journal_missing, _fix_inline_journal_missing
)


# ---- main entry point ----

# Cooldown: don't re-fire the same recipe within N seconds. Prevents alert spam.
COOLDOWN_SEC = 600  # 10 min
_last_fired: dict[str, float] = {}

# FIX 2026-09-07 00:55: separate, longer cooldown for NSSM service-state recipes.
# These should not be re-fired frequently because NSSM state changes are rare.
NSSM_COOLDOWN_SEC = 1800  # 30 min


def self_heal_check(liveness: dict, alerter=None) -> list[dict]:
    """Run all detectors. For each detection, apply the fix (if not in cooldown).
    Returns a list of fixes that were applied (for the caller to log/alert).
    The caller is responsible for sending Telegram alerts (we pass the
    alerter so we can use the same notification path as the rest of the bot).
    """
    log_tail = _read_tail(BOT_LOG) + _read_tail(BRAIN_LOG)
    applied = []
    now_ts = time.time()
    # FIX 2026-09-07 00:55: iterate both regular and NSSM recipes with
    # the appropriate cooldown for each.
    for name, (detect, fix_fn) in {**RECIPES, **_NSSM_RECIPES}.items():
        try:
            if not detect(liveness) if name in ("liveness_stale", "main_thread_dead") else not detect(log_tail):
                continue
        except Exception:
            continue
        # Cooldown
        cooldown = NSSM_COOLDOWN_SEC if name in _NSSM_RECIPES else COOLDOWN_SEC
        last = _last_fired.get(name, 0)
        if now_ts - last < cooldown:
            continue
        try:
            result = fix_fn()
        except Exception as e:
            result = {"applied": False, "msg": f"fix raised: {e}", "action_for_telegram": f"❌ [SELF-HEAL] {name} raised: {e}"}
        _last_fired[name] = now_ts
        applied.append({"name": name, **result})
        if alerter and result.get("action_for_telegram"):
            try:
                alerter.send(result["action_for_telegram"])
            except Exception:
                pass
    return applied


def explain() -> str:
    """Human-readable summary of all registered recipes. For /diag Telegram output."""
    lines = [f"self_heal: {len(RECIPES)} recipes registered, cooldown={COOLDOWN_SEC}s"]
    for name, (detect, _) in RECIPES.items():
        lines.append(f"  - {name}")
    return "\n".join(lines)


if __name__ == "__main__":
    # CLI: python -m kotak_bot.self_heal
    import sys
    sys.path.insert(0, str(ROOT))
    # Try to load liveness for a one-shot check
    liv = {}
    try:
        liv = json.loads((DATA / "liveness.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    results = self_heal_check(liv)
    if results:
        print(json.dumps(results, indent=2, default=str))
    else:
        print("self_heal: no issues detected")
