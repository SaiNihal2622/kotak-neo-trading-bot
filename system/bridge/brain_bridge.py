"""Brain bridge — connects the legacy LLM brain to the new event-sourced core.

The legacy brain (`scripts/quant_service.py`) writes trade proposals to:
- data_cache/quant_actions.json       (main decision queue)
- data_cache/mavis_trades.json        (mavis's structured plan)
- data_cache/system_enforced_action.json (fallback when LLM is silent)

The legacy bot reads these files, builds a plan, and routes through
/api/plan (Phase 3). The brain bridge does the SAME thing, but as a
standalone daemon — no dependency on the legacy bot.

Phase 5 deployment:
- Legacy bot still runs (data feed + dashboard + telegram + force-action)
- Brain bridge submits plans via /api/plan
- Exec gateway processes ORDER_PROPOSED events, places orders
- Core is the source of truth

The brain bridge is intentionally simple:
- Polls quant_actions.json every 5s
- For each unconsumed action, builds a plan and POSTs to /api/plan
- Marks the action as consumed after submission
- Falls back gracefully if core is unavailable
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests


logger = logging.getLogger(__name__)


IST = timezone(timedelta(hours=5, minutes=30))

# Defaults — overridable via env / args
DEFAULT_CORE_URL = os.environ.get("KOTAK_CORE_URL", "http://127.0.0.1:8510")
DEFAULT_QUANT_ACTIONS = os.environ.get("KOTAK_QUANT_ACTIONS", "data_cache/quant_actions.json")
DEFAULT_MAVIS_TRADES = os.environ.get("KOTAK_MAVIS_TRADES", "data_cache/mavis_trades.json")
DEFAULT_SYS_ENFORCED = os.environ.get("KOTAK_SYS_ENFORCED", "data_cache/system_enforced_action.json")
DEFAULT_INTERVAL = float(os.environ.get("KOTAK_BRIDGE_INTERVAL", "5"))


def _parse_option_symbol(symbol: str) -> tuple[str, str, float, str]:
    """Parse NIFTY01OCT2622950CE → (NIFTY, 2026-10-01, 22950, CE).

    Falls back to safe defaults if the symbol doesn't match the expected
    pattern.
    """
    if not symbol:
        return "", "", 0.0, ""
    # Pattern: <underlying><DDMMMYY><strike><CE|PE>
    # Underlyings we know: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX
    for u in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "NIFTY"):
        if symbol.startswith(u):
            rest = symbol[len(u):]
            # rest = DDMMMYY<strike>CE/PE
            try:
                exp_str = rest[:7]  # DDMMMYY
                strike_str = rest[7:-2]
                opt = rest[-2:]
                strike = float(strike_str) if strike_str else 0.0
                # Convert DDMMMYY to YYYY-MM-DD
                exp_date = datetime.strptime(exp_str, "%d%b%y").date()
                return u, exp_date.isoformat(), strike, opt
            except Exception:
                return u, "", 0.0, ""
    return "", "", 0.0, ""


class BrainBridge:
    """Polls legacy decision files, submits plans via /api/plan."""

    def __init__(
        self,
        core_url: str = DEFAULT_CORE_URL,
        quant_actions_path: str = DEFAULT_QUANT_ACTIONS,
        mavis_trades_path: str = DEFAULT_MAVIS_TRADES,
        sys_enforced_path: str = DEFAULT_SYS_ENFORCED,
        interval: float = DEFAULT_INTERVAL,
        http_session: requests.Session = None,
    ):
        self.core_url = core_url.rstrip("/")
        self.quant_actions_path = Path(quant_actions_path)
        self.mavis_trades_path = Path(mavis_trades_path)
        self.sys_enforced_path = Path(sys_enforced_path)
        self.interval = interval
        # Allow tests to inject a session (or use a fresh one)
        self._http = http_session or requests.Session()
        self._processed_actions: set[str] = set()
        self._processed_keys: set[str] = set()  # composite (ts+symbol+strategy)
        self._last_stats = {"submitted": 0, "rejected": 0, "consumed": 0, "skipped": 0}

    def health(self) -> bool:
        """Check if the core is reachable."""
        try:
            r = self._http.get(f"{self.core_url}/healthz", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _read_json(self, path: Path, default=None):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except Exception as e:
            logger.debug(f"read {path}: {e}")
            return default

    def _write_json(self, path: Path, data: dict) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"write {path}: {e}")

    def _build_plan_legs(self, action: dict) -> list[dict]:
        """Convert a quant_actions.json action into /api/plan legs."""
        underlying = str(action.get("underlying", "NIFTY")).upper()
        raw_legs = action.get("legs", [])
        if not raw_legs:
            # Action may be a simple BUY/SELL — build a single leg
            sym = action.get("symbol", "")
            side = str(action.get("side", "BUY")).upper()
            qty = int(action.get("qty_lots", 1))
            order_type = str(action.get("order_type", "MARKET")).upper()
            price = action.get("price")
            if not sym:
                return []
            return [{
                "symbol": sym,
                "underlying": underlying,
                "side": side,
                "qty": self._lot_qty(underlying) * max(1, qty),
                "order_type": order_type,
                "product": "MIS",
                "price": float(price) if price else 0.0,
                "tag": f"BRAIN-{str(action.get('strategy','?'))[:10]}"[:30],
                "exchange": action.get("exchange", "NFO"),
            }]

        # Multi-leg
        legs = []
        for leg in raw_legs:
            side = str(leg.get("side", "BUY")).upper()
            strike = int(leg.get("strike", 0) or 0)
            opt = str(leg.get("opt_type", "")).upper()
            expiry = str(leg.get("expiry", ""))
            order_type = str(leg.get("order_type", "MARKET")).upper()
            price = leg.get("price")
            qty_lots = int(leg.get("qty", 1) or 1)
            if not strike or not opt:
                # Skip malformed leg
                continue
            # Build option symbol
            try:
                edt = datetime.strptime(expiry, "%Y-%m-%d")
                exp_str = edt.strftime("%d%b%y").upper()
            except Exception:
                exp_str = expiry
            sym = f"{underlying}{exp_str}{int(strike)}{opt}"
            legs.append({
                "symbol": sym,
                "underlying": underlying,
                "side": side,
                "qty": self._lot_qty(underlying) * max(1, qty_lots),
                "order_type": order_type,
                "product": "MIS",
                "price": float(price) if price else 0.0,
                "tag": f"BRAIN-{str(action.get('strategy','?'))[:10]}"[:30],
                "strike": float(strike),
                "option_type": opt,
                "expiry": expiry,
                "exchange": leg.get("exchange", "NFO"),
            })
        return legs

    def _lot_qty(self, underlying: str) -> int:
        return {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65,
                "MIDCPNIFTY": 120, "SENSEX": 10}.get(underlying.upper(), 75)

    def _submit_plan(self, action: dict) -> dict:
        """POST a plan to /api/plan. Returns the core's response."""
        legs = self._build_plan_legs(action)
        if not legs:
            return {"ok": False, "reason": "no_legs"}
        plan = {
            "strategy": str(action.get("strategy", "custom")),
            "underlying": str(action.get("underlying", "NIFTY")).upper(),
            "legs": legs,
            "target": float(action.get("target", 0) or 0),
            "stop": float(action.get("stop", 0) or 0),
            "confidence": float(action.get("confidence", 0) or 0),
            "reason": str(action.get("rationale", ""))[:200],
        }
        try:
            r = self._http.post(f"{self.core_url}/api/plan", json=plan, timeout=10)
            if r.status_code == 200:
                return {"ok": True, **r.json()}
            elif r.status_code == 400:
                err = r.json().get("error", {})
                return {"ok": False, "reason": err.get("reason", "rejected"),
                        "gate": err.get("gate", "?"), "details": err}
            else:
                return {"ok": False, "reason": f"http {r.status_code}",
                        "text": r.text[:200]}
        except Exception as e:
            return {"ok": False, "reason": f"exception: {e}"}

    def process_quant_actions(self) -> int:
        """Read quant_actions.json, submit new actions to /api/plan.

        Returns number of actions submitted.
        """
        if not self.quant_actions_path.exists():
            return 0
        try:
            doc = self._read_json(self.quant_actions_path, default={})
        except Exception as e:
            logger.warning(f"read quant_actions.json: {e}")
            return 0
        actions = doc.get("actions", []) if isinstance(doc, dict) else []
        submitted = 0
        for i, action in enumerate(actions):
            try:
                # Build composite key
                ts = str(action.get("ts", ""))
                sym = str(action.get("symbol") or
                          (action.get("legs", [{}])[0].get("opt_type", "")
                           if action.get("legs") else ""))
                strat = str(action.get("strategy", ""))
                key = f"{ts}|{sym}|{strat}"
                if key in self._processed_keys:
                    continue
                # Submit
                result = self._submit_plan(action)
                self._processed_keys.add(key)
                if result.get("ok"):
                    submitted += 1
                    self._last_stats["submitted"] += 1
                    logger.info(
                        f"[BRIDGE] submitted {strat} {sym} → plan_id={result.get('plan_id', '?')}"
                    )
                else:
                    self._last_stats["rejected"] += 1
                    logger.info(
                        f"[BRIDGE] rejected {strat} {sym}: "
                        f"gate={result.get('gate', '?')} reason={result.get('reason', '?')[:80]}"
                    )
                # Mark consumed in the source file so the legacy bot doesn't
                # try to submit the same action via its own bridge
                if isinstance(doc, dict) and "actions" in doc and i < len(doc["actions"]):
                    doc["actions"][i]["bridge_consumed"] = True
                    doc["actions"][i]["bridge_result"] = result
            except Exception as e:
                logger.warning(f"process action {i}: {e}")
        # Write back consumed markers (best-effort)
        if submitted > 0 or any(
            a.get("bridge_consumed") for a in actions if isinstance(a, dict)
        ):
            try:
                self._write_json(self.quant_actions_path, doc)
            except Exception:
                pass
        return submitted

    def process_system_enforced(self) -> int:
        """Read system_enforced_action.json (LLM-silent fallback)."""
        if not self.sys_enforced_path.exists():
            return 0
        doc = self._read_json(self.sys_enforced_path, default={})
        if not isinstance(doc, dict):
            return 0
        if doc.get("bridge_consumed"):
            return 0
        actions = doc.get("actions", [])
        if not actions:
            return 0
        submitted = 0
        for action in actions:
            try:
                result = self._submit_plan(action)
                if result.get("ok"):
                    submitted += 1
                    self._last_stats["submitted"] += 1
                    logger.info(
                        f"[BRIDGE] system-enforced submitted: "
                        f"{action.get('strategy', '?')} → {result.get('plan_id', '?')}"
                    )
            except Exception as e:
                logger.warning(f"process sys-enforced: {e}")
        if submitted > 0:
            doc["bridge_consumed"] = True
            doc["bridge_submitted"] = submitted
            doc["bridge_consumed_at"] = datetime.now(IST).isoformat()
            self._write_json(self.sys_enforced_path, doc)
        return submitted

    def run_once(self) -> int:
        """Process all sources. Returns total submitted count."""
        if not self.health():
            return 0
        n = self.process_quant_actions()
        n += self.process_system_enforced()
        return n

    def run_forever(self):
        """Poll loop."""
        logger.info(
            f"Brain bridge started: core={self.core_url} "
            f"quant={self.quant_actions_path} "
            f"interval={self.interval}s"
        )
        while True:
            try:
                n = self.run_once()
                if n > 0:
                    logger.info(f"[BRIDGE] cycle: submitted={n}, stats={self._last_stats}")
            except Exception as e:
                logger.warning(f"bridge cycle error: {e}")
            time.sleep(self.interval)


def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [BRAIN-BRIDGE] %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", default=DEFAULT_CORE_URL)
    parser.add_argument("--quant", default=DEFAULT_QUANT_ACTIONS)
    parser.add_argument("--sys-enforced", default=DEFAULT_SYS_ENFORCED)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    args = parser.parse_args()

    bridge = BrainBridge(
        core_url=args.core,
        quant_actions_path=args.quant,
        sys_enforced_path=args.sys_enforced,
        interval=args.interval,
    )
    bridge.run_forever()


if __name__ == "__main__":
    main()