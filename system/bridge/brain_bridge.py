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
import math
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
        # PHASE 6 FIX 2026-09-30: delegate to system.common.atomic_io
        # for the BOM-safe utf-8-sig read. Behavior unchanged from caller
        # perspective (returns default on any read error).
        from ..common.atomic_io import read_json
        return read_json(path, default)

    def _write_json(self, path: Path, data: dict) -> None:
        # PHASE 6 FIX 2026-09-30: atomic write via system.common.atomic_io.
        # Kills the intermittent [Errno 22] Invalid argument we saw when
        # brain daemon + bridge hit the same file at the same instant on
        # Windows. Uses os.replace() (Windows MoveFileEx REPLACE_EXISTING)
        # so readers never see a half-written file.
        from ..common.atomic_io import write_json_atomic
        ok = write_json_atomic(path, data)
        if not ok:
            # FIX 2026-10-16: transient race when brain daemon + bridge hit the
            # same file at the same instant. Retry with a tiny backoff; also add
            # a unique nonce so a concurrent reader/writer of the same content
            # doesn't clobber the rename under contention.
            import time as _tw
            for _attempt in range(3):
                _tw.sleep(0.05 * (_attempt + 1))
                _ok2 = write_json_atomic(path, data)
                if _ok2:
                    ok = True
                    break
        if not ok:
            logger.warning(f"write {path}: atomic write failed after retries")

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
            # PHASE 5 FIX 2026-09-30: detect CAS legs (segment="nse_cm") —
            # for CAS, qty is already in shares (e.g., 75 = 1 lot of NIFTY),
            # so we must NOT multiply by lot size again. The strategy_library
            # writes CAS legs with `qty=75` (shares) not `qty=1` (lots).
            _is_cash_leg = str(leg.get("segment", "")).lower() == "nse_cm"
            price = leg.get("price")
            qty_lots = int(leg.get("qty", 1) or 1)
            if _is_cash_leg:
                # CAS: qty is already in shares, no multiplier
                if qty_lots < 1:
                    continue
                # FIX 2026-10-12: brain sizer can emit qty not a multiple of the
                # lot size (e.g. 38 for NIFTY lot 75) -> preflight lot_size gate
                # rejects -> OPEN silently never fills. Round UP to nearest lot.
                _lot = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}.get(underlying, 75)
                _l_qty = int(math.ceil(qty_lots / _lot) * _lot)
                sym = underlying  # NIFTY spot, no strike suffix
                legs.append({
                    "symbol": sym,
                    "underlying": underlying,
                    "side": side,
                    "qty": _l_qty,
                    "order_type": order_type,
                    "product": "MIS",
                    "price": float(price) if price else 0.0,
                    "tag": f"BRAIN-{str(action.get('strategy','?'))[:10]}"[:30],
                    "strike": 0.0,
                    "option_type": "",
                    "expiry": "",
                    "exchange": leg.get("exchange", "NSE"),
                })
                continue
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
            # FIX 2026-10-14: use the LIVE chain price for the limit, not the
            # LLM's guess. The LLM proposes limits ~50% below the real ask,
            # which the preflight limit_reasonable gate rejects -> OPEN never
            # fills. ask for BUY, bid for SELL. Fall back to the LLM price only
            # if the chain has no data for this symbol.
            _live = self._chain_price(sym, side)
            _final_price = _live if _live is not None else (float(price) if price else 0.0)
            legs.append({
                "symbol": sym,
                "underlying": underlying,
                "side": side,
                "qty": self._lot_qty(underlying) * max(1, qty_lots),
                "order_type": order_type,
                "product": "MIS",
                "price": _final_price,
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

    def _chain_price(self, sym: str, side: str):
        """FIX 2026-10-14: override the LLM's guessed limit with the LIVE
        option-chain price (ask for BUY, bid for SELL). The LLM frequently
        proposes a limit ~50% below the real ask (e.g. 34 vs 67), which the
        preflight limit_reasonable gate correctly rejects -> the OPEN never
        fills. The chain file (data_cache/option_chain_<UND>.json) has real
        bid/ask per strike. Returns a float price, or None if no chain data.
        """
        try:
            import json as _j
            from pathlib import Path as _P
            und = sym
            for _u in ("BANKNIFTY", "NIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"):
                if sym.startswith(_u):
                    und = _u
                    break
            chain_path = _P("data_cache") / f"option_chain_{und}.json"
            if not chain_path.exists():
                return None
            data = _j.loads(chain_path.read_text(encoding="utf-8-sig"))
            # FIX 2026-10-21: NIFTY CASH/spot leg (symbol==underlying) is not an
            # option - use the chain's real spot price. Without this, a NIFTY
            # cash order got price=0 -> preflight pricing gate rejected it.
            if sym.upper() == und or sym.upper() == f"{und}SPOT":
                _spot = float(data.get("spot", 0) or 0)
                return _spot if _spot > 1.0 else None
            strikes = data.get("strikes", {})
            entry = strikes.get(sym)
            if not entry:
                import re as _re
                _m = _re.search(r"(\d{4,5})(CE|PE)$", sym)
                if _m:
                    entry = strikes.get(f"{_m.group(1)}_{_m.group(2)}")
            if not entry:
                return None
            bid = float(entry.get("bid") or 0)
            ask = float(entry.get("ask") or 0)
            if side == "BUY":
                return ask if ask > 0 else (bid if bid > 0 else None)
            return bid if bid > 0 else (ask if ask > 0 else None)
        except Exception:
            return None

    def _cap_leg_notional(self, legs: list, capital: float = 100000.0,
                          max_pct: float = 0.05) -> list:
        """FIX 2026-10-14: hard-cap each leg's notional (qty x price) to a % of
        capital. The sizer/LLM can emit an oversized leg (e.g. Rs.396k on a
        Rs.100k account) which the preflight per_trade_cap gate rejects -> the
        OPEN never fills. Reduce qty to the nearest lot multiple that fits.
        """
        if not legs or capital <= 0:
            return legs
        cap = capital * max_pct
        out = []
        for leg in legs:
            qty = int(leg.get("qty", 0) or 0)
            price = float(leg.get("price", 0) or 0)
            if qty <= 0 or price <= 0:
                out.append(leg)
                continue
            notional = qty * price
            if notional <= cap:
                out.append(leg)
                continue
            # reduce qty to fit the cap, rounded down to a lot multiple
            lot = self._lot_qty(str(leg.get("underlying", "NIFTY")))
            max_qty = int(cap / price)
            max_qty = max(0, (max_qty // lot) * lot)
            if max_qty < lot:
                # even 1 lot exceeds the cap -> drop the leg (safer than oversizing)
                continue
            leg = dict(leg)
            leg["qty"] = max_qty
            out.append(leg)
        return out

    def _submit_close_all(self, action: dict) -> dict:
        """PHASE 6 FIX: post a CLOSE_ALL to /api/close_all.

        Returns {ok, closed} where closed is the count of positions closed.
        """
        try:
            r = self._http.post(
                f"{self.core_url}/api/close_all",
                json={"reason": str(action.get("rationale", "force_square"))[:200]},
                timeout=15,
            )
            if r.status_code == 200:
                return {"ok": True, **r.json()}
            return {"ok": False, "reason": f"http {r.status_code}", "text": r.text[:200]}
        except Exception as e:
            return {"ok": False, "reason": f"exception: {e}"}

    def _submit_plan(self, action: dict) -> dict:
        """POST a plan to /api/plan. Returns the core's response."""
        legs = self._build_plan_legs(action)
        if not legs:
            return {"ok": False, "reason": "no_legs"}
        # FIX 2026-10-14: hard-cap leg notional so the preflight per_trade_cap
        # gate doesn't reject an oversized leg (e.g. Rs.396k on Rs.100k).
        try:
            from pathlib import Path as _P
            _pp_path = _P("data_cache") / "paper_state.json"
            _pp = self._read_json(_pp_path, default={}) if _pp_path.exists() else {}
            _cap_cash = float((_pp or {}).get("cash") or 100000.0)
            legs = self._cap_leg_notional(legs, capital=_cap_cash)
        except Exception:
            pass
        if not legs:
            return {"ok": False, "reason": "no_legs_after_cap"}
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
                # PHASE 6 FIX 2026-09-30: handle CLOSE_ALL specially.
                # It calls /api/close_all instead of /api/plan.
                action_kind = str(action.get("action", "")).upper()
                # FIX 2026-10-21 (recurring 'custom/no_legs' blocker): the brain
                # emits an end-of-day force-square as type=CLOSE, strategy=custom,
                # underlying=ALL, 0-legs. That NEVER matched action_kind=CLOSE_ALL,
                # fell through to /api/plan submission, got rejected as 'no_legs',
                # and (being rejected) was never marked consumed -> it blocked the
                # queue every cycle all day. Recognize the type=CLOSE underlying=ALL
                # shape as a close-all too.
                if action_kind != "CLOSE_ALL":
                    if str(action.get("type", "")).upper() in ("CLOSE", "CLOSE_ALL") and \
                       str(action.get("underlying", "")).upper() in ("ALL", "ALL_POSITIONS"):
                        action_kind = "CLOSE_ALL"
                if action_kind == "CLOSE_ALL":
                    if action.get("bridge_consumed"):
                        continue
                    result = self._submit_close_all(action)
                    if isinstance(doc, dict) and "actions" in doc and i < len(doc["actions"]):
                        doc["actions"][i]["bridge_consumed"] = True
                        doc["actions"][i]["bridge_result"] = result
                    if result.get("ok"):
                        submitted += 1
                        self._last_stats["submitted"] += 1
                        logger.warning(f"[BRIDGE] CLOSE_ALL executed: closed {result.get('closed', 0)} positions")
                    continue

                # PHASE 6 FIX 2026-09-30 (swing mode): SWING_CLOSE = close swing
                # position. Currently reuses close_all; in future could filter by
                # underlying. For now swing holds at most one position at a time
                # (the strategy itself, not other underlyings), so /api/close_all
                # is fine.
                if action_kind == "SWING_CLOSE":
                    if action.get("bridge_consumed"):
                        continue
                    result = self._submit_close_all(action)
                    if isinstance(doc, dict) and "actions" in doc and i < len(doc["actions"]):
                        doc["actions"][i]["bridge_consumed"] = True
                        doc["actions"][i]["bridge_result"] = result
                    if result.get("ok"):
                        submitted += 1
                        self._last_stats["submitted"] += 1
                        logger.warning(f"[BRIDGE] SWING_CLOSE executed: {action.get('exit_reason', 'manual')}")
                    continue

                # PHASE 5 FIX 2026-09-29: use a more robust dedup key.
                # The legacy brain may write actions with empty ts (older
                # bots didn't always populate it). Combined with the same
                # sym+strat, this caused collisions across cycles. Use
                # action dict's full fingerprint instead of ts-based key.
                import hashlib
                import json as _json
                # Serialize the legs (the actual content) for fingerprint
                payload = {
                    "strategy": str(action.get("strategy", "")),
                    "underlying": str(action.get("underlying", "")),
                    "legs": action.get("legs", []),
                    "rationale": str(action.get("rationale", ""))[:100],
                }
                fp = hashlib.md5(_json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
                sym = str(action.get("symbol") or
                          (action.get("legs", [{}])[0].get("opt_type", "")
                           if action.get("legs") else ""))
                strat = str(action.get("strategy", ""))
                key = f"{strat}|{sym}|{fp}"
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
        # PHASE 6 FIX 2026-09-30: per-service heartbeat. Catches a stuck
        # bridge (alive process but stuck on /api/plan POST forever).
        from ..common.heartbeat import HeartbeatWriter
        hb = HeartbeatWriter("brain_bridge", interval_sec=10)
        hb.update(core_reachable=False, submitted=0, rejected=0)
        hb.start()

        logger.info(
            f"Brain bridge started: core={self.core_url} "
            f"quant={self.quant_actions_path} "
            f"interval={self.interval}s"
        )
        while True:
            try:
                n = self.run_once()
                hb.update(
                    core_reachable=True,
                    submitted=self._last_stats.get("submitted", 0),
                    rejected=self._last_stats.get("rejected", 0),
                )
                if n > 0:
                    logger.info(f"[BRIDGE] cycle: submitted={n}, stats={self._last_stats}")
            except Exception as e:
                logger.warning(f"bridge cycle error: {e}")
                hb.update(last_error=str(e)[:200])
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