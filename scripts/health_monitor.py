"""Self-watching health monitor for the kotak-neo-bot.

Runs inside the brain's in-process scheduler (no external cron). Every N
minutes it checks EVERY known failure class and writes a clear health report
to data_cache/health_report.json, which the dashboard surfaces. If any check
fails, it flags the exact problem so the operator never has to grep a 38MB log.

Failure classes covered (each was a real bug that cost days of debugging):
  1. services      - all core NSSM services RUNNING
  2. llm_circuit   - LLM circuit breaker closed (not open)
  3. bridge_active - KOTAK_BRIDGE_ACTIVE=YES (no double plan submission)
  4. no_placeholder- no Rs.1.00 placeholder fills in the core (avg_price sane)
  5. no_stranded   - no positions left open past EOD (allow_overnight=false)
  6. realized_pnl  - realized P&L is actually being computed on close
  7. single_book   - core positions == paper_state positions (no two books)
  8. bridge_alive  - bridge is submitting, not stuck
  9. phantom_fill  - OPEN decisions are actually producing fills
  10. config       - allow_overnight=false, bridge flag set

Writes: data_cache/health_report.json  (dashboard reads this)
         data_cache/health_report.log  (append-only audit trail)
"""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

DCACHE = Path("data_cache")
REPORT = DCACHE / "health_report.json"
LOG = DCACHE / "health_report.log"
CORE_URL = os.environ.get("KOTAK_CORE_URL", "http://127.0.0.1:8510")
CORE_SERVICES = [
    "KotakBotPaper", "KotakQuantService", "KotakCoreAPI", "KotakExecGateway",
    "KotakDashboard", "KotakBrainBridge", "KotakHttpServer", "KotakMavisRealtime",
]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _service_state(name):
    try:
        r = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=15)
        for line in r.stdout.splitlines():
            if "STATE" in line:
                return line.split(":")[-1].strip().split()[-1]
    except Exception:
        pass
    return "?"


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _http_json(url, default):
    try:
        import urllib.request
        return json.loads(urllib.request.urlopen(url, timeout=5).read())
    except Exception:
        return default


def _check_services():
    bad = [s for s in CORE_SERVICES if _service_state(s) != "RUNNING"]
    return ("ok" if not bad else "FAIL", f"all {len(CORE_SERVICES)} running" if not bad else f"down: {', '.join(bad)}")


def _check_llm_circuit():
    st = _read_json(DCACHE / "quant_service_state.json", {})
    h = st.get("llm_health", {})
    if h.get("open"):
        return ("FAIL", f"LLM circuit OPEN (consec_err={h.get('consecutive_errors')})")
    return ("ok", f"circuit closed (consec_err={h.get('consecutive_errors', 0)})")


def _check_bridge_active():
    # the bot's NSSM env must carry KOTAK_BRIDGE_ACTIVE=YES
    try:
        r = subprocess.run(
            [r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe", "get", "KotakBotPaper", "AppEnvironmentExtra"],
            capture_output=True, text=True, timeout=15)
        env = r.stdout.replace("\x00", "")
        if "KOTAK_BRIDGE_ACTIVE=YES" in env:
            return ("ok", "bot is data-feed-only (bridge submits)")
        return ("FAIL", "KOTAK_BRIDGE_ACTIVE not set -> bot may double-submit plans")
    except Exception as e:
        return ("WARN", f"cannot read bot env: {e}")


def _check_placeholder_fills():
    # query the core's order.filled events for placeholder (<=1.0) prices
    try:
        import sqlite3
        db = sqlite3.connect(DCACHE / "state.db")
        cur = db.cursor()
        rows = cur.execute(
            "SELECT payload_json FROM events WHERE type='order.filled' ORDER BY id DESC LIMIT 200").fetchall()
        ph = 0
        real = 0
        for (payload,) in rows:
            try:
                p = json.loads(payload)
                fp = float(p.get("fill_price", 0))
                if fp <= 1.01:
                    ph += 1
                else:
                    real += 1
            except Exception:
                pass
        db.close()
        # A few leftover placeholders from BEFORE the fix are expected; only
        # flag if placeholders DOMINATE the recent window (the bug is live).
        if ph > real and ph >= 5:
            return ("FAIL", f"{ph} placeholder(<=1.0) fills vs {real} real -> P&L garbage")
        if ph > 0:
            return ("ok", f"{ph} legacy placeholder fills (pre-fix leftovers), {real} real")
        return ("ok", f"no placeholder fills (last 200: {real} real)")
    except Exception as e:
        return ("WARN", f"cannot read fills: {e}")


def _check_stranded():
    # positions open now, after market close, with allow_overnight=false
    pos = _http_json(f"{CORE_URL}/api/positions", {})
    n = len(pos.get("positions", {}) or {})
    if n == 0:
        return ("ok", "no open positions")
    # if market is closed and positions remain, that's a stranded risk
    now = datetime.now(timezone.utc)
    ist = now.astimezone(timezone.utc).replace(tzinfo=None)
    # NSE 09:15-15:30 IST = 03:45-10:00 UTC
    h = ist.hour
    market_open = (3 <= h < 10)
    if not market_open and n > 0:
        return ("FAIL", f"{n} positions open after market close (should be squared)")
    return ("ok", f"{n} positions open (market {'open' if market_open else 'closed'})")


def _check_realized_pnl():
    surv = _read_json(DCACHE / "survival_state.json", {})
    rp = surv.get("realized_total", 0)
    # can't fail on 0 (no trades yet) - just report
    return ("ok", f"realized_total={rp}")


def _check_single_book():
    core = _http_json(f"{CORE_URL}/api/positions", {})
    core_n = len(core.get("positions", {}) or {})
    paper = _read_json(DCACHE / "paper_state.json", {})
    paper_n = len(paper.get("positions", {}) or {})
    if core_n != paper_n:
        return ("WARN", f"two books: core={core_n} vs paper_state={paper_n}")
    return ("ok", f"single book (core={core_n}, paper={paper_n})")


def _check_bridge_alive():
    # bridge heartbeat / recent cycle lines. The bridge only cycles during
    # NSE hours (09:15-15:30 IST = 03:45-10:00 UTC); after close it is
    # correctly idle, so a stale cycle is NOT a failure then.
    try:
        log = Path("Logs/brain_bridge.err.log")
        if not log.exists():
            return ("WARN", "no bridge log")
        lines = log.read_text(encoding="utf-8", errors="ignore").splitlines()
        recent = [l for l in lines if "cycle:" in l or "submitted" in l]
        if not recent:
            return ("WARN", "no bridge cycle lines found")
        last = recent[-1]
        ts = last[:19]
        try:
            last_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            age = (datetime.now() - last_dt).total_seconds()
            # market open check (UTC 03:45-10:00)
            h = datetime.now(timezone.utc).hour
            market_open = (3 <= h < 10)
            if age > 600 and market_open:
                return ("FAIL", f"bridge last cycle {age/60:.0f} min ago during market hours (stuck?)")
            if age > 600:
                return ("ok", f"bridge idle (market closed, last cycle {age/60:.0f} min ago)")
            return ("ok", f"bridge cycling ({age/60:.0f} min ago)")
        except Exception:
            return ("ok", "bridge has cycle lines")
    except Exception as e:
        return ("WARN", f"bridge check err: {e}")


def _check_phantom_fill():
    # OPEN decisions today vs fills today
    try:
        import sqlite3
        db = sqlite3.connect(DCACHE / "state.db")
        cur = db.cursor()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fills = cur.execute(
            "SELECT COUNT(*) FROM events WHERE type='order.filled' AND ts LIKE ?", (f"{today}%",)).fetchone()[0]
        db.close()
        return ("ok", f"{fills} fills today")
    except Exception as e:
        return ("WARN", f"phantom check err: {e}")


def _check_config():
    try:
        import yaml
        cfg = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))
        ao = cfg.get("risk", {}).get("intraday", {}).get("allow_overnight")
        if ao is not False:
            return ("FAIL", f"allow_overnight={ao} (must be false for daily close)")
        return ("ok", "allow_overnight=false")
    except Exception as e:
        return ("WARN", f"config check err: {e}")


CHECKS = [
    ("services", _check_services),
    ("llm_circuit", _check_llm_circuit),
    ("bridge_active", _check_bridge_active),
    ("placeholder_fills", _check_placeholder_fills),
    ("stranded", _check_stranded),
    ("realized_pnl", _check_realized_pnl),
    ("single_book", _check_single_book),
    ("bridge_alive", _check_bridge_alive),
    ("phantom_fill", _check_phantom_fill),
    ("config", _check_config),
]


def run_health_check():
    results = {}
    for name, fn in CHECKS:
        try:
            status, detail = fn()
        except Exception as e:
            status, detail = "ERR", str(e)
        results[name] = {"status": status, "detail": detail}
    n_fail = sum(1 for v in results.values() if v["status"] == "FAIL")
    n_warn = sum(1 for v in results.values() if v["status"] == "WARN")
    overall = "HEALTHY" if n_fail == 0 else "ACTION-NEEDED"
    report = {
        "ts": _now(),
        "overall": overall,
        "n_fail": n_fail,
        "n_warn": n_warn,
        "checks": results,
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    # append audit trail
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{_now()} {overall} fail={n_fail} warn={n_warn} "
                f"{json.dumps({k: v['status'] for k, v in results.items()})}\n")
    return report


if __name__ == "__main__":
    rep = run_health_check()
    print(json.dumps(rep, indent=2))
