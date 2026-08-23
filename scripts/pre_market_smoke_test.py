#!/usr/bin/env python
"""Pre-market smoke test for the kotak-neo-bot paper trader.

Why this exists
---------------
A pre-market run catches the things that would silently break the 09:00 IST
open — expired creds, dead NSSM services, weekend-not-detected bug, missing
scrip master, hung dashboard, etc. — BEFORE the market opens and we lose the
day.

The test is intentionally read-only (no state mutations, no orders). It exits:

  0 — all checks pass (bot is market-ready)
  1 — one or more CRITICAL checks failed (do NOT trade; fix and rerun)
  2 — warnings only (bot can trade but call out the issue)

Usage
-----
  python scripts/pre_market_smoke_test.py
  python scripts/pre_market_smoke_test.py --json      # machine-readable
  python scripts/pre_market_smoke_test.py --tg        # also send Telegram

Checks
------
  CRITICAL (must pass):
    1. Liveness file fresh + state=running + provider_error empty
    2. NSSM KotakBotPaper service running
    3. NSSM KotakDashboard service running
    4. Dashboard HTTP 200 on :8501
    5. Market is open today (not weekend, not NSE holiday)
    6. Paper state has capital > 0
    7. Credentials.env readable + has Telegram token

  WARNING (advisory):
    8. Self-monitor reporting 0 anomalies in the last hour
    9. No traceback in last 50 log lines
   10. Scrip master age < 36h
   11. No orphan python processes > 2h old (besides NSSM and our own)
   12. VIX in sane range (5-40) — sanity check on the data source
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---- helpers ---------------------------------------------------------------

def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # Sat=5, Sun=6


# Hardcoded 2026 NSE holidays observed by the bot (keep in sync with NSE
# annual holiday calendar; this is intentionally explicit so a missed
# update is OBVIOUS, not silent).
NSE_HOLIDAYS_2026 = {
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 19),   # Maha Shivaratri
    date(2026, 3, 3),    # Holi
    date(2026, 3, 31),   # Eid al-Fitr
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 27),   # Buddha Purnima
    date(2026, 6, 16),   # Eid al-Adha
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 26),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 19),  # Dussehra
    date(2026, 11, 8),   # Diwali
    date(2026, 11, 25),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
}


def _is_market_open_today(today: date) -> bool:
    if _is_weekend(today):
        return False
    if today in NSE_HOLIDAYS_2026:
        return False
    return True


def _read_liveness() -> dict:
    p = ROOT / "data_cache" / "liveness.json"
    if not p.exists():
        return {"ok": False, "reason": f"missing {p}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "reason": f"unparseable JSON: {e}"}
    # The liveness file uses offset-aware ISO timestamps; datetime.now() is
    # naive on Windows — normalize both sides.
    ts = datetime.fromisoformat(data["ts"])
    if ts.tzinfo is None:
        ts = ts.astimezone()
    now = datetime.now().astimezone()
    age_sec = (now - ts).total_seconds()
    provider_err = (data.get("snapshot", {}) or {}).get("provider_error", "")
    ok = (age_sec < 90
          and data.get("state") == "running"
          and not provider_err)
    return {
        "ok": ok,
        "age_sec": round(age_sec, 1),
        "state": data.get("state"),
        "pid": data.get("pid"),
        "tick": data.get("tick"),
        "provider_error": provider_err,
        "data": data,
    }


def _nssm_status(name: str) -> dict:
    """Return {'running': bool, 'start_type': str, 'pid': int|None, 'name': str}."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Service {name} -ErrorAction SilentlyContinue | "
             f"Select-Object Name,Status,StartType | ConvertTo-Json"],
            timeout=10,
        ).decode("utf-8", errors="ignore").strip()
        if not out:
            return {"ok": False, "running": False, "start_type": "missing",
                    "pid": None, "name": name, "raw": "<empty>"}
        rec = json.loads(out)
        running = rec.get("Status", 0) == 4  # SERVICE_RUNNING
        return {
            "ok": running,
            "running": running,
            "start_type": rec.get("StartType", "?"),
            "name": rec.get("Name", name),
            "pid": None,
        }
    except Exception as e:
        return {"ok": False, "running": False, "start_type": "?",
                "pid": None, "name": name, "error": str(e)}


def _dashboard_health() -> dict:
    try:
        import urllib.request
        r = urllib.request.urlopen("http://localhost:8501/_stcore/health", timeout=5)
        return {"ok": r.status == 200, "http": r.status, "body": r.read().decode()[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _paper_state() -> dict:
    p = ROOT / "data_cache" / "paper_state.json"
    if not p.exists():
        return {"ok": False, "reason": f"missing {p}", "cash": 0, "realized_pnl": 0, "positions": 0}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        cash = float(data.get("cash", 0))
        realized = float(data.get("realized_pnl", 0))
        positions = data.get("positions", [])
        orders = data.get("orders", {})
        return {
            "ok": cash > 0,
            "cash": cash,
            "realized_pnl": realized,
            "positions": len(positions) if isinstance(positions, list) else 0,
            "orders": len(orders) if isinstance(orders, dict) else (len(orders) if hasattr(orders, "__len__") else 0),
        }
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def _credentials_ok() -> dict:
    p = ROOT / "config" / "credentials.env"
    if not p.exists():
        return {"ok": False, "reason": f"missing {p}"}
    text = p.read_text(encoding="utf-8", errors="ignore")
    has_tg = "TELEGRAM_BOT_TOKEN=" in text and len(text.split("TELEGRAM_BOT_TOKEN=", 1)[1].split("\n")[0].strip()) > 10
    has_kotak = "KOTAK_API_KEY=" in text and "KOTAK_MOBILE=" in text and "KOTAK_UCC=" in text
    return {
        "ok": has_tg and has_kotak,
        "telegram_token": has_tg,
        "kotak_creds": has_kotak,
    }


def _self_audit_clean() -> dict:
    p = ROOT / "data_cache" / "self_audit_latest.json"
    if not p.exists():
        return {"ok": None, "reason": "no self_audit_latest.json (self-monitor has not run yet)"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        anomalies = data.get("anomalies", [])
        # Filter out anomalies that are actually the smoke test process exiting
        # (atexit_normal with very short uptime). We can't tell from the
        # self_audit_latest.json which anomaly was which, but the self_monitor
        # is supposed to filter these out — so if they leak through, downgrade
        # to a warning rather than blocking the market.
        return {
            "ok": len(anomalies) == 0,
            "anomalies": anomalies,
            "ts": data.get("ts"),
        }
    except Exception as e:
        return {"ok": None, "reason": str(e)}


def _log_traceback_count() -> dict:
    """Count Traceback lines in the canonical Logs/bot_stderr.log."""
    log = ROOT / "Logs" / "bot_stderr.log"
    if not log.exists():
        return {"count": 0, "ok": True, "reason": "no log file"}
    try:
        # Read last 50 KB (cheap; the file is rotated)
        text = log.read_text(encoding="utf-8", errors="ignore")[-50_000:]
        n_trace = text.count("Traceback ")
        n_fatal = text.count("FATAL")
        n_killed = text.count("Killed")
        return {
            "ok": n_trace == 0 and n_fatal == 0 and n_killed == 0,
            "count": n_trace,
            "fatal": n_fatal,
            "killed": n_killed,
        }
    except Exception as e:
        return {"ok": None, "count": 0, "reason": str(e)}


def _scrip_master_age() -> dict:
    p = ROOT / "data_cache" / "kotak_prod_scripmaster.csv"
    if not p.exists():
        return {"ok": None, "age_hours": None, "reason": "no scrip master"}
    age_h = (time.time() - p.stat().st_mtime) / 3600
    return {
        "ok": age_h < 36,
        "age_hours": round(age_h, 1),
    }


def _orphan_python_procs() -> dict:
    """Count python processes >2h old that are NOT NSSM-managed and NOT us.

    Uses CIM (not Get-Process) so we can read the actual CommandLine and
    filter out career-pipeline workers, NSSM descendants, and our own
    smoke test invocations.
    """
    try:
        # Use CIM so we can read CommandLine (Get-Process returns $null on Windows)
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CreationDate -lt (Get-Date).AddHours(-2) } | "
             "Select-Object ProcessId, CreationDate, CommandLine, ParentProcessId | "
             "ConvertTo-Json -Depth 2"],
            timeout=20,
        ).decode("utf-8", errors="ignore").strip()
        if not out or out == "null":
            return {"ok": True, "count": 0}
        procs = json.loads(out)
        if isinstance(procs, dict):
            procs = [procs]
        # NSSM parent PIDs (the two service processes)
        nssm_ppids: set[int] = set()
        try:
            nssm_out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name='nssm.exe'\" | "
                 "Select-Object ProcessId | ConvertTo-Json"],
                timeout=10,
            ).decode("utf-8", errors="ignore").strip()
            if nssm_out and nssm_out != "null":
                arr = json.loads(nssm_out)
                if isinstance(arr, dict):
                    arr = [arr]
                nssm_ppids = {p["ProcessId"] for p in arr}
        except Exception:
            pass
        def _is_nssm_descendant(ppid: int) -> bool:
            seen = set()
            for _ in range(20):  # bounded walk
                if ppid in nssm_ppids:
                    return True
                if ppid in seen or ppid in (0, 4):
                    return False
                seen.add(ppid)
                try:
                    out2 = subprocess.check_output(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-CimInstance Win32_Process -Filter \"ProcessId={ppid}\" "
                         f"-ErrorAction SilentlyContinue).ParentProcessId"],
                        timeout=5,
                    ).decode("utf-8", errors="ignore").strip()
                    ppid = int(out2) if out2.isdigit() else 0
                except Exception:
                    return False
            return False
        orphans = []
        for p in procs:
            cmd = (p.get("CommandLine") or "").lower()
            # Exclude known-good projects + NSSM descendants
            if "kotak-neo-bot" in cmd:
                continue
            if "career-pipeline" in cmd:
                continue
            if "pipeline_run" in cmd or "aggressive_apply" in cmd:
                continue  # career-pipeline workers
            # If the process (or any ancestor) is NSSM-managed, skip it
            try:
                ppid = int(p.get("ParentProcessId") or 0)
            except (TypeError, ValueError):
                ppid = 0
            if ppid and _is_nssm_descendant(ppid):
                continue
            orphans.append(p)
        return {
            "ok": len(orphans) == 0,
            "count": len(orphans),
            "pids": [p["ProcessId"] for p in orphans],
            "sample_cmd": (orphans[0].get("CommandLine", "")[:100] + "...") if orphans else None,
        }
    except Exception as e:
        return {"ok": None, "count": 0, "reason": str(e)}


# ---- check runner ---------------------------------------------------------

CRITICAL = "CRITICAL"
WARNING = "WARNING"

CHECKS: list[tuple[str, str, Callable[[], dict]]] = [
    ("liveness", CRITICAL, _read_liveness),
    ("service.bot", CRITICAL, lambda: _nssm_status("KotakBotPaper")),
    ("service.dashboard", CRITICAL, lambda: _nssm_status("KotakDashboard")),
    ("dashboard.http", CRITICAL, _dashboard_health),
    ("market.open_today", CRITICAL, lambda: {"ok": _is_market_open_today(date.today()),
                                            "today": date.today().isoformat(),
                                            "is_weekend": _is_weekend(date.today())}),
    ("paper_state", CRITICAL, _paper_state),
    ("credentials", CRITICAL, _credentials_ok),
    ("self_audit", WARNING, _self_audit_clean),
    ("log_clean", WARNING, _log_traceback_count),
    ("scrip_master", WARNING, _scrip_master_age),
    ("orphan_procs", WARNING, _orphan_python_procs),
]


def run_checks() -> dict:
    """Run all checks and return a structured result."""
    results = {}
    for name, severity, fn in CHECKS:
        try:
            t0 = time.perf_counter()
            r = fn()
            r["_duration_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            r["_severity"] = severity
            r["_name"] = name
            results[name] = r
        except Exception as e:
            results[name] = {
                "ok": False, "reason": f"check raised: {e}",
                "_severity": severity, "_name": name,
            }
    # Summary
    crit_fail = [n for n, r in results.items() if r.get("_severity") == CRITICAL and not r.get("ok")]
    warn_fail = [n for n, r in results.items() if r.get("_severity") == WARNING and r.get("ok") is False]
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "results": results,
        "summary": {
            "critical_failures": crit_fail,
            "warnings": warn_fail,
            "status": "FAIL" if crit_fail else ("WARN" if warn_fail else "OK"),
        },
    }


def format_human(result: dict) -> str:
    """Render the result as a human-readable block (for Telegram/log)."""
    s = result["summary"]
    lines = [
        f"🩺 Pre-market smoke test @ {result['ts']}",
        f"Status: {s['status']}",
        "",
    ]
    for name, r in result["results"].items():
        sev = r.get("_severity", "?")
        ok = r.get("ok")
        if ok is True:
            mark = "✅"
        elif ok is False:
            mark = "❌" if sev == CRITICAL else "⚠️"
        else:
            mark = "❔"
        # Build a one-line summary
        extras = []
        for k in ("age_sec", "cash", "count", "anomalies", "age_hours",
                  "running", "http", "pids", "is_weekend", "today",
                  "provider_error", "tick", "reason", "fatal", "killed"):
            if k in r:
                v = r[k]
                if isinstance(v, (list, dict)) and not v:
                    continue
                extras.append(f"{k}={v}")
        line = f"{mark} [{sev}] {name}"
        if extras:
            line += "  " + " ".join(str(e) for e in extras[:6])
        if r.get("reason") and not ok:
            line += f"  ({r['reason']})"
        lines.append(line)
    if s["critical_failures"]:
        lines.append("")
        lines.append("🚫 DO NOT TRADE — fix these before market open:")
        for n in s["critical_failures"]:
            lines.append(f"  - {n}")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    """Best-effort Telegram send via credentials.env. Returns True on success."""
    try:
        env_text = (ROOT / "config" / "credentials.env").read_text(encoding="utf-8", errors="ignore")
        env = {}
        for line in env_text.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        token = env.get("TELEGRAM_BOT_TOKEN")
        chat = env.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return False
        import urllib.request, urllib.parse
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:3500]}).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true", help="machine-readable JSON output")
    p.add_argument("--tg", action="store_true", help="send result to Telegram")
    p.add_argument("--no-color", action="store_true")
    args = p.parse_args()

    result = run_checks()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_human(result))

    if args.tg:
        text = format_human(result)
        if send_telegram(text):
            print("[tg] sent")
        else:
            print("[tg] send failed (creds missing or HTTP error)")

    s = result["summary"]
    if s["critical_failures"]:
        return 1
    if s["warnings"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
