"""Kotak Executor — reads brain_actions.json and submits orders to paper client.

Runs as a long-lived process. Each tick (default 30s):
  1. Loads latest brain_actions.json
  2. For each unexecuted action:
     - OPEN: build multi-leg order, submit via PaperClient
     - CLOSE: submit opposing orders to flatten position
  3. Marks actions as executed (or expired)
  4. Logs to data_cache/executor.log
  5. Persists state to data_cache/executor_state.json

Single file, zero new dependencies. The paper_client handles all fill mechanics
including the FORCE_FILL fallback chain (tick → limit → expected → underlying → Rs.1).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

# Load credentials before importing kotak_bot
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    _env = ROOT / "config" / "credentials.env"
    if _env.exists():
        load_dotenv(str(_env))
except Exception:
    pass

from loguru import logger

# -------- config --------
ACTIONS_PATH = ROOT / "data_cache" / "brain_actions.json"
EXECUTOR_LOG = ROOT / "logs" / "executor.log"
EXECUTOR_STATE = ROOT / "data_cache" / "executor_state.json"
PAPER_STATE = ROOT / "data_cache" / "paper_state.json"

TICK_SEC = 30                    # how often to poll brain_actions.json
ACTION_TTL_SEC = 300             # how long an OPEN action is valid
MAX_FILLS_PER_TICK = 8           # rate-limit order submission


def _now_ist_str() -> str:
    from kotak_bot.utils.clock import now_ist
    return now_ist().strftime("%Y-%m-%d %H:%M:%S")


def _load_actions() -> dict:
    try:
        if not ACTIONS_PATH.exists():
            return {"actions": []}
        with open(ACTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"executor: cannot read actions: {e}")
        return {"actions": []}


def _save_actions(payload: dict) -> None:
    try:
        ACTIONS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"executor: cannot write actions: {e}")


def _save_state(state: dict) -> None:
    try:
        EXECUTOR_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = EXECUTOR_STATE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        tmp.replace(EXECUTOR_STATE)
    except Exception as e:
        logger.warning(f"executor: cannot save state: {e}")


def _load_paper_state() -> dict:
    try:
        if not PAPER_STATE.exists():
            return {}
        with open(PAPER_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"executor: cannot read paper_state: {e}")
        return {}


def _connect_paper():
    """Open a PaperClient in-place. Reuses the same state file the bot writes to."""
    from kotak_bot.broker.paper_client import PaperClient
    pc = PaperClient(
        starting_capital=100_000.0,
        slippage_bps=5.0,
        fill_mode="market_like",
        persist_path=str(PAPER_STATE),
    )
    pc.connect()
    return pc


def _format_symbol(underlying: str, expiry: str, strike: int, option_type: str) -> str:
    """NIFTY10AUG2624600CE convention used by kotak."""
    try:
        d = datetime.strptime(expiry, "%Y-%m-%d")
        suffix = d.strftime("%d%b%y").upper()
    except Exception:
        suffix = expiry.replace("-", "")[2:]
    return f"{underlying}{suffix}{strike}{option_type}"


def _execute_open_action(pc, action: dict) -> bool:
    """Submit all legs of an OPEN action. Returns True if all submitted."""
    from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType

    legs = action.get("legs", [])
    if not legs:
        return False
    underlying = action.get("underlying", "NIFTY")
    expiry = action.get("expiry", "")
    strategy = action.get("strategy", "executor")
    fills = 0
    failures = 0
    for leg in legs:
        try:
            side = OrderSide(leg["side"])
            opt = leg.get("option_type", "CE")
            strike = int(leg.get("strike", 0))
            qty = int(leg.get("qty", 0))
            if qty <= 0 or strike <= 0:
                continue
            symbol = _format_symbol(underlying, expiry, strike, opt)
            order = Order(
                symbol=symbol,
                side=side,
                qty=qty,
                order_type=OrderType.MARKET,
                product=ProductType.MIS,
                price=0.0,
                tag=f"brain_{strategy}_{action.get('id','')[:8]}",
                exchange="NFO",
                strike=float(strike),
                option_type=opt,
                expiry=expiry,
                underlying=underlying,
            )
            res = pc.place_order(order)
            logger.info(
                f"executor: OPEN leg {leg['side']} {qty}x {symbol} -> {res.status.value} "
                f"@ {res.avg_fill_price} (id={res.order_id})"
            )
            if res.status.value == "complete":
                fills += 1
            else:
                failures += 1
        except Exception as e:
            logger.exception(f"executor: OPEN leg failed: {e}")
            failures += 1
    return fills > 0 and failures == 0


def _execute_close_action(pc, action: dict) -> bool:
    """Flatten a single position by submitting opposing order."""
    from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType

    sym = action.get("symbol", "")
    side = OrderSide(action.get("side", "BUY"))
    qty = int(action.get("qty", 0))
    if not sym or qty <= 0:
        return False
    # try to find the existing position to get metadata
    pos_meta = {}
    paper = _load_paper_state()
    pos = paper.get("positions", {}).get(sym, {})
    if pos:
        pos_meta = {
            "strike": pos.get("strike", 0.0),
            "option_type": pos.get("option_type"),
            "expiry": pos.get("expiry"),
            "underlying": pos.get("underlying", "NIFTY"),
        }
    try:
        order = Order(
            symbol=sym,
            side=side,
            qty=qty,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=0.0,
            tag=f"brain_close_{action.get('id','')[:8]}",
            exchange="NFO",
            strike=pos_meta.get("strike", 0.0),
            option_type=pos_meta.get("option_type"),
            expiry=pos_meta.get("expiry"),
            underlying=pos_meta.get("underlying", "NIFTY"),
        )
        res = pc.place_order(order)
        logger.info(
            f"executor: CLOSE {side.value} {qty}x {sym} -> {res.status.value} "
            f"@ {res.avg_fill_price} (id={res.order_id})"
        )
        return res.status.value == "complete"
    except Exception as e:
        logger.exception(f"executor: CLOSE failed: {e}")
        return False


def _expire_old_actions(actions: list[dict]) -> list[dict]:
    """Mark expired unexecuted actions and remove them."""
    now = datetime.utcnow()
    keep = []
    for a in actions:
        ts_str = a.get("_seen_at") or a.get("ts") or ""
        if a.get("executed"):
            keep.append(a)
            continue
        if a.get("status") == "expired":
            keep.append(a)
            continue
        try:
            age = (now - datetime.fromisoformat(ts_str.replace("Z", "+00:00").replace("+00:00", ""))).total_seconds()
        except Exception:
            age = ACTION_TTL_SEC + 1
        ttl = a.get("ttl_sec", ACTION_TTL_SEC)
        if age > ttl:
            a["status"] = "expired"
            a["executed"] = False
            logger.info(f"executor: action {a.get('id','?')} expired after {age:.0f}s (ttl={ttl})")
            keep.append(a)
        else:
            keep.append(a)
    return keep


def _run_tick(pc, executor_state: dict) -> dict:
    """One executor tick."""
    payload = _load_actions()
    actions = payload.get("actions", [])
    if not actions:
        executor_state.update({
            "ts": _now_ist_str(),
            "pending": 0,
            "executed_total": executor_state.get("executed_total", 0),
        })
        return executor_state

    from kotak_bot.utils.clock import market_session
    session = market_session()
    if session in ("closed", "post_market"):
        logger.debug(f"executor: market {session}, skipping fills")
        executor_state.update({"ts": _now_ist_str(), "pending": 0, "note": f"market_{session}"})
        return executor_state

    fills_this_tick = 0
    actions = _expire_old_actions(actions)
    for a in actions:
        if a.get("executed") or a.get("status") == "expired":
            continue
        if fills_this_tick >= MAX_FILLS_PER_TICK:
            break
        ok = False
        try:
            if a.get("type") == "OPEN":
                ok = _execute_open_action(pc, a)
            elif a.get("type") == "CLOSE":
                ok = _execute_close_action(pc, a)
        except Exception as e:
            logger.exception(f"executor: action {a.get('id','?')} threw: {e}")
            ok = False
        if ok:
            a["executed"] = True
            a["executed_at"] = _now_ist_str()
            a["status"] = "executed"
            fills_this_tick += 1
            executor_state["executed_total"] = executor_state.get("executed_total", 0) + 1
        else:
            a.setdefault("attempts", 0)
            a["attempts"] += 1
            if a["attempts"] >= 3:
                a["status"] = "failed"
                a["executed"] = False
                logger.warning(f"executor: action {a.get('id','?')} failed 3x, marking failed")

    payload["actions"] = actions
    _save_actions(payload)
    pending = sum(1 for a in actions if not a.get("executed") and a.get("status") not in ("expired", "failed"))
    executor_state.update({
        "ts": _now_ist_str(),
        "pending": pending,
        "executed_total": executor_state.get("executed_total", 0),
        "fills_this_tick": fills_this_tick,
    })
    if fills_this_tick or pending:
        logger.info(f"executor: tick fills={fills_this_tick} pending={pending} total={executor_state.get('executed_total',0)}")
    return executor_state


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="One tick then exit")
    args = p.parse_args()

    EXECUTOR_LOG.parent.mkdir(parents=True, exist_ok=True)
    logger.add(str(EXECUTOR_LOG), rotation="1 day", retention="14 days", level="INFO")
    logger.info(f"executor: starting (once={args.once}) pid={os.getpid()}")

    # PID lock — prevent double-launch from cron/healer
    pidfile = ROOT / "data_cache" / "executor.pid"
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    if pidfile.exists():
        try:
            old = int(pidfile.read_text().strip() or "0")
            if old and old != os.getpid():
                import psutil  # type: ignore
                if psutil.pid_exists(old):
                    logger.warning(f"executor: another instance alive pid={old}, exiting")
                    return 0
        except Exception:
            pass
    pidfile.write_text(str(os.getpid()))
    try:
        return _run(args)
    finally:
        try:
            if int(pidfile.read_text().strip() or "0") == os.getpid():
                pidfile.unlink(missing_ok=True)
        except Exception:
            pass


def _run(args) -> int:
    # one persistent paper client (in-process simulator, same state file as bot)
    pc = _connect_paper()
    state = {
        "ts": "",
        "pending": 0,
        "executed_total": 0,
        "started_at": _now_ist_str(),
    }
    _save_state(state)

    if args.once:
        state = _run_tick(pc, state)
        _save_state(state)
        logger.info("executor: --once complete")
        return 0

    while True:
        try:
            state = _run_tick(pc, state)
            _save_state(state)
        except KeyboardInterrupt:
            logger.info("executor: stopped by user")
            return 0
        except Exception as e:
            logger.exception(f"executor: tick error: {e}")
        time.sleep(TICK_SEC)


if __name__ == "__main__":
    sys.exit(main())
