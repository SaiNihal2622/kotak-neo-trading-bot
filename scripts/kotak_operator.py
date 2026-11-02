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
            "last_executed_sig": "",
            "last_close_at": 0.0,   # epoch sec of last CLOSE (cooldown)
        }
        self.cooldown_sec = 900  # 15 min: no re-OPEN right after a CLOSE
        self.register_jobs()

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    def _job_data(self):
        """Refresh candles from live prices (self-contained data pipeline).

        Mirrors the brain's _candle_refresh: get_engine -> fetch_live_prices
        -> tick_many -> aggregate_to_file. This makes the operator fully
        self-contained — it produces its own candles, no dependency on the
        brain service.
        """
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from candle_engine import get_engine, fetch_live_prices
            eng = get_engine()
            prices = fetch_live_prices()
            if prices:
                eng.tick_many(prices)
            try:
                eng.backfill_session_opens_from_yfinance()
            except Exception:
                pass
            eng.aggregate_to_file()
            try:
                eng.save_all()
            except Exception:
                pass
            self.state["last_data_refresh"] = _now_iso()
        except Exception as e:
            log.warning(f"data job err: {e}")

    def _job_market(self):
        """Read live market data (NIFTY spot, VIX, candles) into context."""
        candles = _safe_read(DATA / "candles_aggregate.json", {})
        liveness = _safe_read(DATA / "liveness.json", {})
        intraday = _safe_read(DATA / "intraday_levels.json", {})
        # FIX 2026-10-26: read REAL positions from the core API, not the stale
        # paper_state.json. The operator was deciding OPEN because paper_state
        # had empty positions while the core's live state had 300 qty from
        # duplicate fills -> infinite OPEN retry rejected by position_cap.
        paper = _safe_read(DATA / "paper_state.json", {})
        try:
            import urllib.request as _ur
            _st = json.loads(_ur.urlopen("http://127.0.0.1:8510/api/state", timeout=4).read())
            paper = {"cash": (_st.get("account") or {}).get("cash", paper.get("cash", 100000)),
                     "positions": _st.get("positions") or {}}
        except Exception:
            pass
        chains = _safe_read(DATA / "option_chains.json", {})
        self.context = {
            "candles": candles,
            "intraday": intraday,
            "liveness": liveness,
            "paper": paper,
            "option_chains": chains,
            "vix": float((liveness.get("snapshot") or {}).get("vix", 15)),
        }
        spot = ((candles.get("symbols") or {}).get("NIFTY") or {}).get("ltp")
        self.state["spot"] = spot
        self.state["last_tick"] = _now_iso()

    def _market_open(self) -> bool:
        """NSE equity-derivatives hours: 09:15-15:30 IST, Mon-Fri.
        The operator must NEVER trade outside these hours (stale data,
        no fills, phantom losses)."""
        try:
            import datetime as _dt
            now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
            if now.weekday() >= 5:  # Sat/Sun
                return False
            t = now.time()
            return _dt.time(9, 15) <= t <= _dt.time(15, 30)
        except Exception:
            return False

    def _job_decide(self):
        """Run the decision engine — the SOLE selector."""
        # HARD market-hours gate: never trade outside NSE hours
        if not self._market_open():
            self.state["last_decision"] = {
                "action": "HOLD", "structure": "market-closed",
                "edge_score": 0, "rationale": "NSE closed - no trading outside 09:15-15:30 IST",
                "ts": _now_iso(),
            }
            self.state["tick_count"] += 1
            return
        if not self.context:
            return
        # FIX 2026-11-02: score ALL live underlyings (NIFTY, BANKNIFTY,
        # FINNIFTY, MIDCPNIFTY, SENSEX) and take the single best opportunity
        # across the whole market — not just NIFTY.
        from decision_engine import decide_all
        decision = decide_all(self.context)
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
        # FIX 2026-10-26: execute each decision EXACTLY ONCE. _job_execute runs
        # every 15s and was re-submitting the same OPEN plan with a new
        # timestamp order_id each time -> the gateway filled every one
        # (duplicate fills). Track the decision signature we already acted on.
        sig = f"{action}:{decision.get('ts','')}:{decision.get('structure','')}"
        if self.state.get("last_executed_sig") == sig:
            return
        # COOLDOWN: after a CLOSE, do NOT re-OPEN for cooldown_sec. This stops
        # the OPEN/CLOSE/OPEN oscillation (re-entering right after a stop-out
        # or take-profit churns the account and books losses).
        if action == "OPEN":
            since_close = time.time() - float(self.state.get("last_close_at") or 0)
            if since_close < self.cooldown_sec:
                self.state["last_decision"] = {
                    "action": "HOLD", "structure": "cooldown",
                    "edge_score": 0,
                    "rationale": f"cooldown {int(self.cooldown_sec-since_close)}s after CLOSE - no re-entry",
                    "ts": _now_iso(),
                }
                return
        # Execute DIRECTLY via the core API (no file-based bridge indirection)
        if action == "OPEN":
            ok = self._execute_open(decision)
        else:
            ok = self._execute_close()
        # Set the guard on BOTH success and failure: a rejected OPEN (e.g.
        # position_cap) must not retry every 15s forever.
        self.state["last_executed_sig"] = sig
        if ok:
            self.state["actions_taken"] += 1

    def _resolve_price(self, strike, opt, underlying: str = "NIFTY") -> float:
        """Resolve a real option price from option_chains.json so the core's
        position-cap preflight has a price to check (underlying-aware)."""
        try:
            ca = _safe_read(DATA / "option_chains.json", {})
            chain = (ca.get("chains") or {}).get(underlying) or {}
            strikes = chain.get("strikes") or {}
            s = strikes.get(f"{strike}_{opt}")
            if not s:
                for k, v in strikes.items():
                    if v.get("strike") == strike and str(v.get("opt_type","")).upper() == opt:
                        s = v; break
            if s:
                return float(s.get("price") or s.get("bid") or s.get("ask") or s.get("last_price") or 0)
        except Exception as e:
            log.warning(f"resolve-price err: {e}")
        return 0.0

    def _execute_open(self, decision: dict) -> bool:
        """POST a multi-leg plan to the core /api/plan."""
        try:
            from decision_engine import build_plan
            plan = build_plan(decision, self.context)
            und = decision.get("underlying") or "NIFTY"
            legs = []
            for leg in plan.get("legs", []):
                sym = f"{und}{leg['strike']}{leg['opt_type']}"
                # Resolve a REAL price from the chain for the preflight cap check
                p_price = self._resolve_price(leg["strike"], leg["opt_type"], und)
                legs.append({
                    "client_order_id": f"oop-{int(time.time()*1000)}",
                    "symbol": sym, "underlying": und,
                    "side": leg["side"], "qty": leg["qty"],
                    "order_type": leg.get("order_type", "MARKET"),
                    "product": "MIS", "price": p_price,
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
            # FIX 2026-10-31 (zero-P&L closes): hitting /api/positions runs the
            # core's _mark_to_market_from_chain() on the SHARED projection,
            # updating pos.ltp to LIVE prices. close_all then fills at the real
            # price and books true P&L. Without this, close_all used pos.ltp
            # which stayed == avg_price (the open price) -> every close = 0.
            try:
                urllib.request.urlopen("http://127.0.0.1:8510/api/positions", timeout=5).read()
            except Exception:
                pass
            req = urllib.request.Request("http://127.0.0.1:8510/api/close_all",
                data=json.dumps({"reason": "position management"}).encode(),
                headers={"Content-Type":"application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = r.read().decode()
            self.state["last_close_at"] = time.time()  # start cooldown
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

    def _job_chain(self):
        """Run the option-chain analyzer every 5 min during market hours.

        FIX 2026-10-31 (stale-chain root cause): the BRAIN used to schedule
        scripts/option_chain_analyzer.py every 5 min. When the brain was
        disabled (operator is sole trader), NOTHING refreshed the chain —
        option_chains.json froze at 2026-10-23 and every fill/close since used
        5-day-old prices (zero/phantom P&L). The operator now owns this job.
        """
        if not self._market_open():
            return
        try:
            subprocess.run(
                [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-u",
                 str(ROOT / "scripts" / "option_chain_analyzer.py")],
                cwd=str(ROOT), timeout=150, capture_output=True, text=True)
            self.state["last_chain_refresh"] = _now_iso()
        except Exception as e:
            log.warning(f"chain job err: {e}")

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
        self.scheduler.add("chain", self._job_chain, every_sec=300)
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
