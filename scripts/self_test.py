"""Self-test for the Kotak Neo bot.

Runs at startup and on demand. Checks every external dependency that could
silently break the bot and reports a clear PASS/FAIL with remediation steps.
Returns a structured report dict so callers can branch on it.

Usage:
    python scripts/self_test.py            # human-readable
    python scripts/self_test.py --json     # machine-readable
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _check(name: str, fn: Callable[[], tuple[bool, str]]) -> dict:
    """Run a check function. Returns {name, ok, detail, ts}."""
    t0 = time.time()
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"exception: {e}"
    return {
        "name": name,
        "ok": bool(ok),
        "detail": str(detail),
        "ms": int((time.time() - t0) * 1000),
        "ts": datetime.utcnow().isoformat() + "Z",
    }


def _check_yfinance() -> tuple[bool, str]:
    import yfinance as yf
    n = yf.Ticker("^NSEI").history(period="1d")
    b = yf.Ticker("^NSEBANK").history(period="1d")
    v = yf.Ticker("^INDIAVIX").history(period="1d")
    if not (len(n) and len(b) and len(v)):
        return False, "yfinance returned empty series for one of ^NSEI/^NSEBANK/^INDIAVIX"
    return True, f"NIFTY={n['Close'].iloc[-1]:.2f} BANKNIFTY={b['Close'].iloc[-1]:.2f} VIX={v['Close'].iloc[-1]:.2f}"


def _check_telegram() -> tuple[bool, str]:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "config" / "credentials.env")
    import httpx
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from credentials.env"
    r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
    if r.status_code != 200:
        return False, f"getMe HTTP {r.status_code}"
    bot_info = r.json().get("result", {})
    return True, f"bot @{bot_info.get('username')} (id={bot_info.get('id')})"


def _check_llm() -> tuple[bool, str]:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "config" / "credentials.env")
    base = os.environ.get("MINIMAX_LLM_BASE_URL", "")
    key = os.environ.get("MINIMAX_LLM_API_KEY", "")
    if not base or not key:
        return False, "MINIMAX_LLM_BASE_URL or MINIMAX_LLM_API_KEY missing"
    import httpx
    r = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "x-api-key": key,
                 "Content-Type": "application/json"},
        json={"model": "MiniMax-M2.7-highspeed",
              "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
        timeout=15,
    )
    if r.status_code != 200:
        return False, f"LLM HTTP {r.status_code}: {r.text[:200]}"
    return True, "MiniMax M2.7-highspeed OK"


def _check_kotak_creds() -> tuple[bool, str]:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "config" / "credentials.env")
    need = ["KOTAK_API_KEY", "KOTAK_MOBILE", "KOTAK_UCC", "KOTAK_MPIN",
            "KOTAK_TOTP_SECRET", "KOTAK_ENV"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        return False, f"missing: {', '.join(missing)}"
    return True, f"all 6 KOTAK_* vars present, env={os.environ.get('KOTAK_ENV')}"


def _check_paper_state() -> tuple[bool, str]:
    p = ROOT / "data_cache" / "paper_state.json"
    if not p.exists():
        return True, "no paper_state.json yet (fresh install)"
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        return True, (f"cash=Rs.{data.get('cash', 0):,.0f}  realized=Rs.{data.get('realized_pnl', 0):,.0f}  "
                      f"orders={len(data.get('orders', {}))}  positions={len(data.get('positions', {}))}")
    except Exception as e:
        return False, f"could not parse: {e}"


def _check_dashboard() -> tuple[bool, str]:
    import httpx
    try:
        r = httpx.get("http://localhost:8501/_stcore/health", timeout=3)
        if r.status_code == 200:
            return True, "streamlit :8501 HTTP 200"
        return False, f"streamlit :8501 HTTP {r.status_code}"
    except Exception as e:
        return False, f"streamlit unreachable: {e}"


def _check_disk_space() -> tuple[bool, str]:
    import shutil
    total, used, free = shutil.disk_usage(ROOT)
    free_gb = free / (1024 ** 3)
    if free_gb < 1.0:
        return False, f"only {free_gb:.1f} GB free"
    return True, f"{free_gb:.1f} GB free"


def _check_bot_process() -> tuple[bool, str]:
    import subprocess
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process python -ErrorAction SilentlyContinue | "
         "Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | "
         "Measure-Object | Select-Object -ExpandProperty Count"],
        capture_output=True, text=True, timeout=10,
    )
    n = int((out.stdout or "0").strip() or "0")
    if n == 0:
        return False, "no bot python process found (start via 'start -m kotak_bot paper')"
    return True, f"{n} bot process(es) alive"


def _check_trades_state() -> tuple[bool, str]:
    p = ROOT / "data_cache" / "trades_state.json"
    if not p.exists():
        return True, "no trades_state.json yet (no open trades)"
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        n = len(data.get("trades", {}))
        n_open = sum(1 for t in data.get("trades", {}).values()
                     if t.get("closed_at") is None)
        return True, f"{n} trades ({n_open} open)"
    except Exception as e:
        return False, f"parse error: {e}"


def run_all() -> dict:
    """Run every check. Return {ok, passed, failed, total, results: [...]}."""
    checks = [
        ("yfinance", _check_yfinance),
        ("telegram", _check_telegram),
        ("llm_judge", _check_llm),
        ("kotak_creds", _check_kotak_creds),
        ("paper_state", _check_paper_state),
        ("trades_state", _check_trades_state),
        ("dashboard", _check_dashboard),
        ("bot_process", _check_bot_process),
        ("disk_space", _check_disk_space),
    ]
    results = [_check(name, fn) for name, fn in checks]
    failed = [r for r in results if not r["ok"]]
    return {
        "ok": len(failed) == 0,
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "total": len(results),
        "results": results,
        "ts": datetime.utcnow().isoformat() + "Z",
    }


def main() -> int:
    as_json = "--json" in sys.argv
    report = run_all()
    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 60)
        print("Kotak Neo Bot — SELF TEST")
        print("=" * 60)
        for r in report["results"]:
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"  [{mark}] {r['name']:14s}  ({r['ms']:4d}ms)  {r['detail']}")
        print("-" * 60)
        if report["ok"]:
            print(f"  ALL GREEN — {report['passed']}/{report['total']} checks passed")
        else:
            print(f"  {report['failed']} FAIL(s) — {report['passed']}/{report['total']} passed")
            print("  Remediation:")
            for r in report["results"]:
                if not r["ok"]:
                    print(f"    - {r['name']}: {r['detail']}")
        print("=" * 60)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
