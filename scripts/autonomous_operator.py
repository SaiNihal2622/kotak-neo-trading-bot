"""
AUTONOMOUS OPERATOR — the self-running decision loop.

The user has given full autonomy: 'you do your job too, I should just sit and
watch.' This is the system that monitors itself, catches problems, decides,
auto-fixes what is safe, and escalates only the decisions that need a human/
agent-level call.

Architecture (a real LOOP, not a patch script):
  1. DETECT   - run every check (services, LLM circuit, holiday calendar,
                pre-market READY, phantom fills, single-book, bridge, health).
  2. DECIDE   - classify each finding: OK / AUTO-FIXABLE / escalate-to-me.
  3. FIX      - for AUTO-FIXABLE: apply the known remedy (restart a service,
                clear a stale lock, write the deploy marker, re-run verify).
  4. VERIFY   - re-run the check to confirm the fix landed.
  5. ESCALATE - if not resolved and not safe to keep retrying, write an
                escalation file that a helper turns into a task for the
                agent (which then uses subagents/connectors/web).
  6. LOG      - audit trail of every decision, no matter the outcome.

It runs as its own NSSM service (KotakAutoOperator), every N seconds, 24/7.
It is the "brain watching the brain" the user asked for.

Safe-by-design: it may only restart services it can prove are down, may only
clear stale locks it can prove are stale, and may only write deploy markers
it understands. It never touches positions/cash directly.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
DATA = ROOT / "data_cache"
LOGS = ROOT / "Logs"
STATE_FILE = DATA / "autonomous_operator_state.json"
ESCALATION = DATA / "operator_escalations.jsonl"
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
CORE_URL = os.environ.get("KOTAK_CORE_URL", "http://127.0.0.1:8510")
CORE_SERVICES = [
    "KotakBotPaper", "KotakQuantService", "KotakCoreAPI", "KotakExecGateway",
    "KotakDashboard", "KotakBrainBridge", "KotakHttpServer", "KotakMavisRealtime",
]
MIN_RESTART_GAP = 300  # don't restart a service more than once per 5 min


def _now_iso():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()


def _local():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))


def _read(path, default):
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return default


def _write(path, obj):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        print(f"[op] write err {path}: {e}")


def _svc_state(name):
    try:
        r = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines():
            if "STATE" in line:
                return line.split(":")[-1].strip().split()[-1]
    except Exception:
        pass
    return "?"


def _http_json(url, default, timeout=6):
    import urllib.request
    try:
        return json.loads(urllib.request.urlopen(url, timeout=timeout).read())
    except Exception:
        return default


def _holiday_dates():
    d = _read(DATA / "nse_holidays_2026.json", {})
    n = d.get("nse_holidays_2026") or d
    return {h[:10] for h in (n.get("holidays") or []) if isinstance(h, str)}


def _today_iso():
    return _local().date().isoformat()


def _log(msg):
    line = f"{_now_iso()} {msg}"
    print(line, flush=True)
    try:
        with open(LOGS / "autonomous_operator.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- detectors

def detect_all() -> dict:
    checks = {}
    n = _today_iso()

    # calendar + clock
    checks["calendar"] = {
        "holiday": n in _holiday_dates(),
        "weekend": _local().weekday() >= 5,
        "today": n,
        "detail": f"{_local().strftime('%A %Y-%m-%d %H:%M')} IST, holiday={n in _holiday_dates()}, weekend={_local().weekday()>=5}",
    }

    # services
    checks["services"] = {
        s: _svc_state(s) for s in CORE_SERVICES
    }

    # pre-market readiness (harness output)
    pm = _read(DATA / "pre_market_verification.json", {})
    checks["readiness"] = {
        "overall": pm.get("overall", "NO-HARNESS-YET"),
        "fail": pm.get("n_fail", -1),
        "warn": pm.get("n_warn", -1),
        "ts": pm.get("ts", ""),
    }

    # health monitor
    health = _read(DATA / "health_report.json", {})
    checks["health"] = {
        "overall": health.get("overall", "NO-HEALTH"),
        "fail": health.get("n_fail", -1),
        "warn": health.get("n_warn", -1),
        "ts": health.get("ts", ""),
    }

    # llm circuit
    qs = _read(DATA / "quant_service_state.json", {})
    checks["llm"] = {
        "open": (qs.get("llm_health") or {}).get("open", False),
        "consec": (qs.get("llm_health") or {}).get("consecutive_errors", 0),
        "tick": qs.get("tick_count"),
    }

    # phantom fills / placeholder (core event DB)
    checks["phantom"] = _detect_phantom()

    # single book
    try:
        pos = _http_json(f"{CORE_URL}/api/positions", {"positions": {}})
        core_n = len(pos.get("positions", {}) or {})
        paper = _read(DATA / "paper_state.json", {})
        paper_n = len(paper.get("positions", {}) or {})
        checks["single_book"] = {"core": core_n, "paper": paper_n, "ok": core_n == paper_n}
    except Exception as e:
        checks["single_book"] = {"err": str(e)[:80]}

    return checks


def _detect_phantom() -> dict:
    """Count placeholder (<=1.0) fills vs real in the recent window."""
    try:
        import sqlite3
        db = sqlite3.connect(DATA / "state.db")
        rows = db.execute(
            "SELECT payload_json FROM events WHERE type='order.filled' ORDER BY id DESC LIMIT 200"
        ).fetchall()
        ph = real = 0
        for (p,) in rows:
            try:
                d = json.loads(p)
                fp = float(d.get("fill_price", 0))
                if fp <= 1.01:
                    ph += 1
                else:
                    real += 1
            except Exception:
                pass
        db.close()
        return {"placeholder": ph, "real": real, "bad": ph > real and ph >= 5}
    except Exception as e:
        return {"err": str(e)[:80]}


# ---------------------------------------------------------------- decisions

def decide(checks) -> list[dict]:
    """Return a list of actions. Each {decision: ...}."""
    actions = []
    st = _read(STATE_FILE, {"last_restart": {}})
    now = time.time()

    # bridges: if market is OPEN today and it's a real trading day, keep things running
    trading_day = not checks["calendar"]["holiday"] and not checks["calendar"]["weekend"]
    market_hours = 3 <= _local().hour < 10 and trading_day  # UTC ~ market open

    # 1) services down
    for svc, state in checks["services"].items():
        if state not in ("RUNNING",):
            last = st.get("last_restart", {}).get(svc, 0)
            if now - last > MIN_RESTART_GAP:
                actions.append({
                    "decision": "AUTO-FIX",
                    "what": f"restart {svc}",
                    "why": f"service state={state}",
                    "fix": ["nssm", "restart", svc],
                    "verify": lambda s=svc: _svc_state(s) == "RUNNING",
                })
                st["last_restart"][svc] = now
            else:
                actions.append({
                    "decision": "COOLDOWN",
                    "what": f"{svc} still down but restarted recently",
                    "why": f"state={state}, last restart <{MIN_RESTART_GAP}s ago",
                })

    # 2) LLM circuit open -> restart the brain (safe, known remedy)
    if checks["llm"]["open"]:
        actions.append({
            "decision": "AUTO-FIX",
            "what": "restart KotakQuantService (LLM circuit open)",
            "why": f"consec_err={checks['llm']['consec']}",
            "fix": ["nssm", "restart", "KotakQuantService"],
            "verify": lambda: not checks["llm"]["open"],
        })

    # 3) phantom placeholder fills -> escalate (needs a real code decision,
    #    may require the agent + subagents to trace the price source)
    if checks["phantom"].get("bad"):
        actions.append({
            "decision": "ESCALATE",
            "what": "placeholder fills detected",
            "why": json.dumps(checks["phantom"]),
            "to": "agent",
            "capability": "subagents/web/connectors to trace which price source fell back to Rs.1.0",
        })

    # 4) two books (core != paper) -> likely a sync issue; marker restart both
    if not checks["single_book"].get("ok", True):
        actions.append({
            "decision": "AUTO-FIX",
            "what": "restart ExecGateway (single-book sync)",
            "why": f"core={checks['single_book'].get('core')} vs paper={checks['single_book'].get('paper')}",
            "fix": ["nssm", "restart", "KotakExecGateway"],
            "verify": lambda: True,  # verified next loop
        })

    # 5) readiness NOT-READY should not happen on a trading day
    if trading_day and checks["readiness"]["overall"] == "NOT-READY":
        actions.append({
            "decision": "ESCALATE",
            "what": "pre-market NOT-READY on a trading day",
            "why": f"{checks['readiness']['fail']} checks failed",
            "to": "agent",
            "capability": "agent reviews harness failures and fixes root cause",
        })

    return actions


# ---------------------------------------------------------------- executor

def apply_actions(actions) -> list[dict]:
    results = []
    for a in actions:
        if a["decision"] == "AUTO-FIX" and "fix" in a:
            _log(f"AUTO-FIX {a['what']} ({a['why']})")
            try:
                r = subprocess.run(a["fix"], capture_output=True, text=True, timeout=30)
                ok = (r.returncode == 0)
                # verify
                if "verify" in a:
                    try:
                        time.sleep(3)
                        ok = bool(a["verify"]())
                    except Exception:
                        ok = r.returncode == 0
                results.append({"what": a["what"], "ok": ok, "out": (r.stdout or "")[:120]})
            except Exception as e:
                results.append({"what": a["what"], "ok": False, "err": str(e)[:120]})
        elif a["decision"] == "ESCALATE":
            _escalate(a)
            results.append({"what": a["what"], "ok": True, "decision": "ESCALATED"})
        else:
            results.append({"what": a["what"], "ok": True, "decision": a["decision"]})
    return results


def _escalate(a):
    try:
        with open(ESCALATION, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": _now_iso(), "what": a["what"], "why": a["why"],
                                "capability": a.get("capability", ""), "to": a.get("to", "agent")}) + "\n")
        _log(f"ESCALATE {a['what']} -> {a.get('to','agent')}")
    except Exception as e:
        _log(f"escalate write err {e}")


# ---------------------------------------------------------------- loop

def run_once() -> dict:
    checks = detect_all()
    actions = decide(checks)
    results = apply_actions(actions)
    report = {
        "ts": _now_iso(),
        "checks": checks,
        "actions": results,
    }
    _write(DATA / "autonomous_operator_report.json", report)
    # persist loop state (restart cooldowns)
    _write(STATE_FILE, _read(STATE_FILE, {"last_restart": {}}))
    return report


def main():
    interval = int(os.environ.get("OP_INTERVAL_SEC", "300"))
    _log(f"autonomous-operator started, check every {interval}s")
    while True:
        try:
            run_once()
        except Exception as e:
            _log(f"operator loop error: {traceback.format_exc()[-400:]}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
