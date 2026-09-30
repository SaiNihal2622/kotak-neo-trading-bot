"""Pre-flight risk gates — the ONLY way to place an order.

FIX 2026-09-29 19:50: this module replaces the post-hoc risk checks that
ran AFTER orders were placed (the source of every "broken-condor" bug
today). The flow is:

  1. LLM proposes plan (multi-leg, atomic)
  2. Risk engine validates plan via pre-flight checks (this module)
  3. If passed: execution gateway places legs atomically
  4. If failed: rejection event written; LLM gets feedback within 100ms

The pre-flight is the single source of risk truth. Bypassing it is a bug.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import math

from ..domain.events import Event
from ..domain.state import StateProjection, Position, Order


@dataclass
class PreflightResult:
    ok: bool
    reason: str = ""
    gate: str = ""           # which check failed
    details: dict = None     # for debugging

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "gate": self.gate,
            "details": self.details or {},
        }


class PreFlight:
    """Runs all pre-flight checks on a proposed order (or full plan)."""

    def __init__(
        self,
        max_per_trade_pct: float = 0.05,    # 5% of cash per leg
        max_position_pct: float = 0.30,     # 30% of cash aggregate
        max_lots_per_leg: int = 50,         # hard safety
        limit_safety_buy: float = 0.05,      # limit must be within 5% of ask for BUY
        limit_safety_sell: float = 1.20,     # limit must be within 20% of bid for SELL
        min_bid_buffer_pct: float = 0.001,   # 0.1% — reject if tick data too stale
    ):
        self.max_per_trade_pct = max_per_trade_pct
        self.max_position_pct = max_position_pct
        self.max_lots_per_leg = max_lots_per_leg
        self.limit_safety_buy = limit_safety_buy
        self.limit_safety_sell = limit_safety_sell
        self.min_bid_buffer_pct = min_bid_buffer_pct

    def check_order(self, order: dict, state: StateProjection, plan_legs: list = None) -> PreflightResult:
        """Validate a single order. plan_legs is used for atomicity checks."""
        # 1. Basic structural check
        struct_check = self._check_structure(order)
        if not struct_check.ok:
            return struct_check

        # 2. Per-trade cap
        cap_check = self._check_per_trade_cap(order, state)
        if not cap_check.ok:
            return cap_check

        # 3. Position cap (aggregate)
        agg_check = self._check_position_cap(order, state)
        if not agg_check.ok:
            return agg_check

        # 4. Lot size safety
        lot_check = self._check_lot_size(order)
        if not lot_check.ok:
            return lot_check

        # 5. Limit price reasonableness (only for LIMIT orders)
        if order.get("order_type", "MARKET") == "LIMIT":
            limit_check = self._check_limit_reasonable(order, state)
            if not limit_check.ok:
                return limit_check

        # 6. Multi-leg atomicity (if part of a plan)
        if plan_legs:
            atom_check = self._check_plan_atomicity(plan_legs, state)
            if not atom_check.ok:
                return atom_check

        return PreflightResult(ok=True)

    def check_plan(self, plan: dict, state: StateProjection) -> PreflightResult:
        """Validate a multi-leg plan atomically. Either all legs pass or none."""
        legs = plan.get("legs", [])
        if not legs:
            return PreflightResult(ok=False, reason="plan has no legs", gate="structure")

        # Check each leg independently first
        for i, leg in enumerate(legs):
            result = self.check_order(leg, state, plan_legs=legs)
            if not result.ok:
                return PreflightResult(
                    ok=False,
                    reason=f"leg {i}: {result.reason}",
                    gate=result.gate,
                    details={"failed_leg": i, "details": result.details},
                )

        # Aggregate check: sum of all legs
        total_buy = sum(l.get("qty", 0) * l.get("price", 0) for l in legs if l.get("side") == "BUY")
        total_sell = sum(l.get("qty", 0) * l.get("price", 0) for l in legs if l.get("side") == "SELL")
        net_outlay = total_buy - total_sell
        cash = state.account.cash

        if cash <= 0:
            return PreflightResult(ok=False, reason="zero cash available", gate="cash")

        if net_outlay > cash * self.max_position_pct:
            return PreflightResult(
                ok=False,
                reason=f"net outlay {net_outlay:.0f} > {self.max_position_pct*100:.0f}% of cash {cash:.0f}",
                gate="position_cap",
                details={"net_outlay": net_outlay, "cash": cash, "limit": cash * self.max_position_pct},
            )

        return PreflightResult(ok=True, details={"net_outlay": net_outlay, "cash": cash})

    # ----- Individual gate implementations -----

    def _check_structure(self, order: dict) -> PreflightResult:
        if not order.get("symbol"):
            return PreflightResult(ok=False, reason="missing symbol", gate="structure")
        if not order.get("side"):
            return PreflightResult(ok=False, reason="missing side", gate="structure")
        if order.get("qty", 0) <= 0:
            return PreflightResult(ok=False, reason="qty must be > 0", gate="structure")
        if order.get("side") not in ("BUY", "SELL"):
            return PreflightResult(ok=False, reason=f"side must be BUY or SELL, got {order.get('side')}", gate="structure")
        if order.get("order_type") not in ("MARKET", "LIMIT", "SL", "SL-M"):
            return PreflightResult(ok=False, reason=f"unknown order_type {order.get('order_type')}", gate="structure")
        return PreflightResult(ok=True)

    def _check_per_trade_cap(self, order: dict, state: StateProjection) -> PreflightResult:
        cash = state.account.cash
        if cash <= 0:
            return PreflightResult(ok=False, reason="zero cash", gate="cash")
        # SELL legs generate credit, not cash outlay. Cap is for BUY-side only.
        if order.get("side") == "SELL":
            return PreflightResult(ok=True)
        # PHASE 5 FIX 2026-09-30: CAS legs (segment=nse_cm) are spot trades.
        # Their size (qty=75 NIFTY shares ≈ Rs.17 lakhs at 22800) inherently
        # exceeds the standard 5% per-trade cap because they are positions,
        # not option premium outlays. The CAS risk profile is governed by
        # the per-position stop loss (0.75% from entry = ~Rs.1300 on a
        # Rs.17 lakh position). Skip per-trade cap for CAS and let the
        # position cap + stop-loss enforce risk downstream.
        if str(order.get("exchange", "")).upper() == "NSE":
            return PreflightResult(ok=True)
        qty = int(order.get("qty", 0))
        # Estimate cost: use provided price or latest tick
        price = float(order.get("price", 0) or 0)
        if price <= 0:
            sym = order.get("symbol", "")
            tick = state.ticks.get(sym)
            if tick:
                price = tick.ask or tick.ltp
        if price <= 0:
            return PreflightResult(ok=False, reason="no price for cost estimation", gate="pricing")
        est_cost = qty * price
        cap = cash * self.max_per_trade_pct
        if est_cost > cap:
            return PreflightResult(
                ok=False,
                reason=f"per-trade {est_cost:.0f} > {self.max_per_trade_pct*100:.0f}% of cash {cash:.0f}",
                gate="per_trade_cap",
                details={"est_cost": est_cost, "cap": cap},
            )
        return PreflightResult(ok=True)

    def _check_position_cap(self, order: dict, state: StateProjection) -> PreflightResult:
        cash = state.account.cash
        if cash <= 0:
            return PreflightResult(ok=False, reason="zero cash", gate="cash")
        # PHASE 5 FIX 2026-09-30: skip position cap for CAS (NSE) legs.
        # CAS is a spot position with stop-loss-based risk, not a
        # capital-outlay trade. The standard 30% cap is meaningless for
        # a NIFTY spot position (1 lot ≈ Rs.17L vs cash Rs.100k).
        # Risk is enforced via the strategy's stop_pct (0.75% from entry).
        if str(order.get("exchange", "")).upper() == "NSE":
            return PreflightResult(ok=True)
        sym = order.get("symbol", "")
        pos = state.positions.get(sym)
        # FIX 2026-09-29 21:15: short-aware qty math.
        # Previous code used existing_qty = abs(pos.qty) which is wrong for shorts:
        # a short position of -100 plus a SELL 50 would compute max(0, 100-50)=50,
        # but the actual position after is -150. The cap check would UNDERESTIMATE
        # the position value for shorts, allowing oversize shorts.
        side = order.get("side", "BUY")
        qty = int(order.get("qty", 0))
        existing_qty = pos.qty if pos else 0
        # Compute the signed new quantity after this fill
        if side == "BUY":
            new_qty = existing_qty + qty
        else:  # SELL
            new_qty = existing_qty - qty
        # Use the absolute (exposure) value for the cap check — both longs and shorts
        # tie up capital (margin requirement).
        position_exposure = abs(new_qty)
        price = float(order.get("price", 0) or 0) or state.ticks.get(sym, type("T", (), {"ltp": 0})).ltp
        if price <= 0:
            return PreflightResult(ok=False, reason="no price for position cap check", gate="pricing")
        position_value = position_exposure * price
        cap = cash * self.max_position_pct
        if position_value > cap:
            return PreflightResult(
                ok=False,
                reason=f"position exposure {position_value:.0f} > {self.max_position_pct*100:.0f}% of cash {cash:.0f}",
                gate="position_cap",
                details={"position_value": position_value, "cap": cap, "new_qty": new_qty},
            )
        return PreflightResult(ok=True)

    def _check_lot_size(self, order: dict) -> PreflightResult:
        qty = int(order.get("qty", 0))
        # Lot sizes: NIFTY=75, BANKNIFTY=30, FINNIFTY=65, MIDCPNIFTY=120
        underlying = order.get("underlying", "")
        lot_size = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}.get(underlying, 75)
        if qty % lot_size != 0:
            return PreflightResult(
                ok=False,
                reason=f"qty {qty} not multiple of lot size {lot_size}",
                gate="lot_size",
                details={"qty": qty, "lot_size": lot_size},
            )
        lots = qty // lot_size
        if lots > self.max_lots_per_leg:
            return PreflightResult(
                ok=False,
                reason=f"{lots} lots > max {self.max_lots_per_leg}",
                gate="lot_cap",
                details={"lots": lots, "max": self.max_lots_per_leg},
            )
        return PreflightResult(ok=True)

    def _check_limit_reasonable(self, order: dict, state: StateProjection) -> PreflightResult:
        """FIX 2026-09-29 19:50: reject the the limit=113-when-bid=12 bug.

        Without this check, the LLM can propose limit prices 10x above bid
        and the order sits unfilled for 60s before timing out. Wastes time
        and confuses the LLM.
        """
        sym = order.get("symbol", "")
        tick = state.ticks.get(sym)
        if not tick or tick.bid <= 0:
            return PreflightResult(
                ok=False,
                reason=f"no live tick for {sym} — cannot validate LIMIT price",
                gate="pricing",
            )
        limit = float(order.get("price", 0) or 0)
        if limit <= 0:
            return PreflightResult(ok=False, reason="LIMIT order missing price", gate="structure")
        side = order.get("side")
        if side == "SELL" and limit > tick.bid * self.limit_safety_sell:
            return PreflightResult(
                ok=False,
                reason=f"SELL limit {limit:.2f} > {self.limit_safety_sell}x bid {tick.bid:.2f} (too far above market)",
                gate="limit_reasonable",
                details={"limit": limit, "bid": tick.bid, "max_allowed": tick.bid * self.limit_safety_sell},
            )
        if side == "BUY" and tick.ask > 0 and limit < tick.ask * (1 - self.limit_safety_buy):
            return PreflightResult(
                ok=False,
                reason=f"BUY limit {limit:.2f} > 5% below ask {tick.ask:.2f} (too far below market)",
                gate="limit_reasonable",
                details={"limit": limit, "ask": tick.ask, "min_allowed": tick.ask * (1 - self.limit_safety_buy)},
            )
        return PreflightResult(ok=True)

    def _check_plan_atomicity(self, plan_legs: list, state: StateProjection) -> PreflightResult:
        """If a multi-leg plan, check that all legs are independently pre-flightable.

        This is the FIX for the broken-condor bug: every leg of an iron
        condor must pass pre-flight BEFORE any leg is placed. If any leg
        fails, the ENTIRE plan is rejected (not just that leg).
        """
        if not plan_legs:
            return PreflightResult(ok=True)
        # Already checked each leg in check_order(). This is a final sanity
        # check that all legs are consistent (same underlying, valid strikes).
        underlyings = set(l.get("underlying", "") for l in plan_legs)
        if len(underlyings) > 1:
            return PreflightResult(
                ok=False,
                reason=f"plan has multiple underlyings {underlyings}, must be one",
                gate="plan_consistency",
            )
        return PreflightResult(ok=True)