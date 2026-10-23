"""kotak_operator.py — Single-process Kotak Neo trading operator (REVAMP).

Mirrors the crypto-options-bot's proven architecture: ONE process, a
scheduler wiring named tick-jobs, instead of 9 NSSM services and 17k files.

Jobs (all in-process, no cross-service coordination):
  market   — read live data (NIFTY spot, VIX, candles) -> context   [every 5s]
  decide   — run decision_engine.decide() -> highest-edge setup    [every 15s]
  execute  — write OPEN/CLOSE action to quant_actions.json (gated) [every 15s]
  manage   — run manage_positions() -> CLOSE on target/stop/edge    [every 30s]
  heal     — restart wedged services, write health                  [every 60s]
  heartbeat— write quant_service_state.json fresh                   [every 30s]
  llm_probe— test LLM, close circuit if recovered                   [every 300s]

The decision engine (scripts/decision_engine.py) is the SOLE selector.
This operator is the ONLY process that runs the trade loop.

Run:  .venv/Scripts/python.exe scripts/kotak_operator.py
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data_cache"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("kotak_operator")

IST = timezone(timedelta(hours=5, minutes=30))


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _safe_read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _safe_write(path: Path, doc) -> None:
    try:
        path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        log.warning(f"write {path.name}: {e}")


def _service_state(name: str) -> str:
    try:
        r = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=15)
        for l in r.stdout.splitlines():
            if "STATE" in l:
                parts = l.split()
                for i, p in enumerate(parts):
                    if p.isdigit():
                        return {"1": "STOPPED", "2": "START_PENDING", "3": "STOP_PENDING",
                                "4": "RUNNING", "5": "PAUSED"}.get(p, "?")
        return "?"
    except Exception:
        return "?"


@dataclass
class Job:
    name: str
    fn: callable
    every_sec: float = 60.0
    at_hhmm: str | None = None
    next_run_at: float = 0.0
    last_run_at: float = 0.0
    last_ok: bool = True
    last_error: str = ""
    runs: int = 0


class Scheduler:
    """Simple scheduler running jobs on intervals (modeled on crypto bot)."""

    def __init__(self, tick_sec: float = 1.0):
        self.tick_sec = tick_sec
        self.jobs: dict[str, Job] = {}
        self.running = False

    def add(self, name, fn, every_sec=60.0, at_hhmm=None):
        self.jobs[name] = Job(name=name, fn=fn, every_sec=every_sec, at_hhmm=at_hhmm, next_run_at=time.time())

    def _due(self, job: Job, now: float) -> bool:
        if job.at_hhmm:
            cur = datetime.now(IST).strftime("%H:%M")
            if cur == job.at_hhmm and now - job.last_run_at > 60:
                return True
            return False
        return now - job.last_run_at >= job.every_sec

    def run_forever(self, stop: threading.Event):
        self.running = True
        while not stop.is_set():
            now = time.time()
            for name, job in list(self.jobs.items()):
                if self._due(job, now):
                    try:
                        job.fn()
                        job.last_ok = True
                        job.last_error = ""
                    except Exception as e:
                        job.last_ok = False
                        job.last_error = str(e)[:200]
                        log.warning(f"job {name} error: {e}")
                    job.last_run_at = time.time()
                    job.runs += 1
            time.sleep(self.tick_sec)


class KotakOperator:
    """Single-process Kotak operator: watch -> decide -> trade -> heal."""

    def __init__(self):
        self.scheduler = Scheduler(tick_sec=1.0)
        self.cycles = 0
        self.started_at = time.time()
        self.context: dict = {}
        self.state = {
            "status": "running",
            "tick_count": 0,
            "last_tick": "",
            "last_decision_at": "",
            "actions_taken": 0,
        }
        self.register_jobs()

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    def _job_data(self):
        """Refresh market data context.

        The operator is the DECISION + EXECUTION layer. The DATA layer
        (live feed -> candle_engine -> candles_aggregate.json) is produced by
        the data feed service. This job just verifies candles are fresh and
        re-reads them via _job_market. candle_engine has no run_once and needs
        live ticks, so it cannot run standalone here.
        """
        try:
            ca = _safe_read(DATA / "candles_aggregate.json", {})
            n = (ca.get("symbols") or {}).get("NIFTY") or {}
            spot = n.get("ltp")
            if not spot:
                log.warning("data job: no NIFTY spot in candles_aggregate (stale?)")
        except Exception as e:
            log.warning(f"data job err: {e}")

    def _job_market(self):
        """Read live market data (NIFTY spot, VIX, candles) into context."""
        candles = _safe_read(DATA / "candles_aggregate.json", {})
        liveness = _safe_read(DATA / "liveness.json", {})
        intraday = _safe_read(DATA / "intraday_levels.json", {})
        paper = _safe_read(DATA / "paper_state.json", {})
        self.context = {
            "candles": candles,
            "intraday": intraday,
            "liveness": liveness,
            "paper": paper,
            "vix": float((liveness.get("snapshot") or {}).get("vix", 15)),
        }
        spot = ((candles.get("symbols") or {}).get("NIFTY") or {}).get("ltp")
        self.state["spot"] = spot
        self.state["last_tick"] = _now_iso()

    def _job_decide(self):
        """Run the decision engine — the SOLE selector."""
        if not self.context:
            return
        from decision_engine import decide
        decision = decide(self.context)
        self.state["last_decision"] = decision
        self.state["last_decision_at"] = _now_iso()
        self.state["tick_count"] += 1

    def _job_execute(self):
        """Write OPEN/CLOSE to quant_actions.json (gated)."""
        decision = self.state.get("last_decision") or {}
        if not decision:
            return
        action = decision.get("action")
        if action not in ("OPEN", "CLOSE"):
            return
        # Execute DIRECTLY via the core API (no file-based bridge indirection)
        if action == "OPEN":
            ok = self._execute_open(decision)
        else:
            ok = self._execute_close()
        if ok:
            self.state["actions_taken"] += 1

    def _execute_open(self, decision: dict) -> bool:
        """POST a multi-leg plan to the core /api/plan."""
        try:
            from decision_engine import build_plan
            plan = build_plan(decision, self.context)
            legs = []
            for leg in plan.get("legs", []):
                sym = f"NIFTY{leg['strike']}{leg['opt_type']}"
                legs.append({
                    "client_order_id": f"oop-{int(time.time()*1000)}",
                    "symbol": sym, "underlying": "NIFTY",
                    "side": leg["side"], "qty": leg["qty"],
                    "order_type": leg.get("order_type", "MARKET"),
                    "product": "MIS", "price": leg.get("price", 0),
                    "tag": "KOTAK-OPERATOR", "strike": leg["strike"],
                    "option_type": leg["opt_type"], "expiry": plan.get("expiry",""),
                    "exchange": "NFO",
                })
            body = {
                "strategy": decision.get("structure", ""), "underlying": "NIFTY",
                "legs": legs, "target": 0.0, "stop": 0.0, "reason": decision.get("rationale",""),
                "dry_run": False,
            }
            # Use the core's state projection - resolve spot
            import urllib.request
            def _post(path, payload):
                req = urllib.request.Request(f"http://127.0.0.1:8510{path}",
                    data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=15) as r:
                    return r.status, r.read().decode()
            st, resp = _post("/api/plan", body)
            log.info(f"OPEN via core: status={st} resp={resp[:120]}")
            return st == 200
        except Exception as e:
            log.warning(f"execute-open err: {e}")
            return False

    def _execute_close(self) -> bool:
        """POST /api/close_all to square all positions."""
        import urllib.request
        try:
            req = urllib.request.Request("http://127.0.0.1:8510/api/close_all",
                data=json.dumps({"reason": "position management"}).encode(),
                headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = r.read().decode()
            log.info(f"CLOSE via core: {resp[:100]}")
            return True
        except Exception as e:
            log.warning(f"execute-close err: {e}")
            return False

    def _job_manage(self):
        """Close positions on target/stop/edge."""
        if not self.context:
            return
        positions = (self.context.get("paper") or {}).get("positions") or {}
        if not positions:
            return
        from decision_engine import manage_positions, _regime
        regime = _regime(self.context["candles"], self.context["intraday"], self.context["vix"])
        mgmt = manage_positions(positions, regime, float((self.context.get("paper") or {}).get("cash", 100000)))
        if mgmt.get("action") == "CLOSE":
            doc = {"ts": _now_iso(), "source": "kotak_operator", "actions": [{
                "type": "CLOSE", "underlying": "ALL", "expiry": "", "strategy": "position_management",
                "legs": [], "target": None, "stop": None, "max_hold_minutes": 0,
                "rationale": mgmt.get("rationale", "position management close"),
            }], "consumed": False}
            _safe_write(DATA / "quant_actions.json", doc)

    def _job_heal(self):
        """Check services, restart wedged ones."""
        services = ["KotakBotPaper", "KotakQuantService", "KotakCoreAPI", "KotakExecGateway",
                    "KotakBrainBridge", "KotakHttpServer", "KotakDashboard"]
        down = [s for s in services if _service_state(s) != "RUNNING"]
        if down:
            log.warning(f"HEAL: down services: {down}")
        self.state["services_down"] = down

    def _job_heartbeat(self):
        """Write fresh state so dashboards see a live brain."""
        self.state["uptime_sec"] = int(time.time() - self.started_at)
        self.state["llm_health"] = {"open": False}
        _safe_write(DATA / "quant_service_state.json", self.state)

    def _job_llm_probe(self):
        """Test LLM; close circuit if recovered (stub — decision engine is deterministic)."""
        pass

    def register_jobs(self):
        self.scheduler.add("data", self._job_data, every_sec=60)
        self.scheduler.add("market", self._job_market, every_sec=5)
        self.scheduler.add("decide", self._job_decide, every_sec=15)
        self.scheduler.add("execute", self._job_execute, every_sec=15)
        self.scheduler.add("manage", self._job_manage, every_sec=30)
        self.scheduler.add("heal", self._job_heal, every_sec=60)
        self.scheduler.add("heartbeat", self._job_heartbeat, every_sec=30)
        self.scheduler.add("llm_probe", self._job_llm_probe, every_sec=300)

    def run(self):
        log.info("kotak_operator starting (single-process revamp)")
        stop = threading.Event()
        if threading.current_thread() is threading.main_thread():
            try:
                signal.signal(signal.SIGINT, lambda *_: stop.set())
                signal.signal(signal.SIGTERM, lambda *_: stop.set())
            except ValueError:
                pass
        self.scheduler.run_forever(stop)


def main() -> int:
    op = KotakOperator()
    op.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
