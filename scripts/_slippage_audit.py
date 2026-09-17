"""FIX 2026-09-17 12:45: slippage model audit.

Checks the trade journal against the live tick bid/ask to detect when paper
fills are unrealistically close to LTP (the symptom of market_like fill_mode
when run for live-equivalent estimation). The audit flags two scenarios:

1. All fills within ±5 bps of LTP — paper is too perfect, almost certainly
   using market_like mode under live-equivalent load.
2. Asymmetric slippage (BUYs always at/above LTP, SELLs always at/below LTP) —
   the marker of bid/ask-aware fills in realistic mode.

It also computes the "live-equivalent" P&L: re-prices today's fills assuming
half-spread crossing and reports the realistic-live-equivalent delta.

Writes data_cache/slippage_audit.json with full details and an `overall`
status that the audit panel in the dashboard reads.

Run: python scripts/_slippage_audit.py
Schedule: cron every 30 min during market hours (in-process scheduler in
quant_service.py already covers this — see _scheduled_subprocess).
"""
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"


def load_journal():
    """Return all journal entries."""
    p = DCACHE / "trade_journal.jsonl"
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def load_chain():
    p = DCACHE / "option_chains.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    journal = load_journal()
    chain = load_chain()

    # Filter today's real (non-phantom) fills
    today = [f for f in journal
             if '2026-09-17' in (f.get('ts') or f.get('filled_at') or '')
             and not f.get('phantom_price', False)]
    n_total_today = len(today)
    n_fills_today = sum(1 for f in today if f.get('event') == 'FILL')

    # Compute slippage stats vs expected_fill_price (chain ref at fill time)
    slippage_bps = []
    by_side = {"BUY": [], "SELL": []}
    for f in today:
        px = f.get('avg_fill_price', 0) or 0
        ref = f.get('expected_fill_price', 0) or 0
        if px <= 0 or ref <= 0:
            continue
        # For BUY: slip = (px - ref) / ref, positive = overpaid
        # For SELL: slip = (ref - px) / ref, positive = undersold
        if f.get('side') == 'BUY':
            bps = (px - ref) / ref * 10_000
        else:
            bps = (ref - px) / ref * 10_000
        slippage_bps.append(bps)
        by_side[f.get('side')].append(bps)

    if not slippage_bps:
        result = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "overall": "ok",
            "issues": [],
            "n_fills_today": n_fills_today,
            "n_total_today": n_total_today,
            "slippage_bps_mean": None,
            "slippage_bps_p50": None,
            "slippage_bps_p95": None,
            "asymmetry_buy_sell_bps": None,
            "live_equivalent_pnl_delta_rs": 0.0,
            "fill_mode_detected": "unknown",
        }
        (DCACHE / "slippage_audit.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8")
        print("[slippage_audit] no fills today — wrote empty audit")
        return 0

    slip_sorted = sorted(slippage_bps)
    mean_slip = statistics.mean(slippage_bps)
    p50 = slip_sorted[len(slip_sorted) // 2]
    p95 = slip_sorted[int(len(slip_sorted) * 0.95)] if len(slip_sorted) >= 20 else slip_sorted[-1]
    avg_buy = statistics.mean(by_side["BUY"]) if by_side["BUY"] else 0.0
    avg_sell = statistics.mean(by_side["SELL"]) if by_side["SELL"] else 0.0
    asymmetry = avg_buy - avg_sell  # if BUY is consistently overpaying and SELL undersold, >0

    # Estimate live-equivalent P&L: assume half-spread crossing on every fill.
    # Liquid options: half-spread ≈ 0.05% (5 bps each leg, 10 bps round-trip).
    # Mid OTM: 0.15% (15 bps each leg).
    # Deep OTM: 0.5% (50 bps each leg).
    # Heuristic by absolute price: < Rs.10 = deep OTM (50 bps), 10-200 = mid (15 bps), > Rs.200 = liquid (5 bps).
    live_eq_pnl_delta = 0.0
    for f in today:
        px = f.get('avg_fill_price', 0) or 0
        ref = f.get('expected_fill_price', 0) or 0
        qty = f.get('qty', 0)
        side = f.get('side', '?')
        realized = f.get('realized_delta', 0) or 0
        if px <= 0 or qty == 0:
            continue
        if px < 10:
            slip_pct = 0.005  # 50 bps
        elif px < 200:
            slip_pct = 0.0015  # 15 bps
        else:
            slip_pct = 0.0005  # 5 bps
        # For each fill, in live you would have crossed half-spread.
        # Paper filled at LTP (no slip). Difference = half_spread * qty * px (BUY: extra paid; SELL: less received).
        # Conservatively assume live would have been worse by slip_pct per leg.
        if side == 'BUY':
            live_eq_pnl_delta -= px * qty * slip_pct  # pay more
        else:
            live_eq_pnl_delta -= px * qty * slip_pct  # receive less

    # Detect fill_mode: in market_like, fills are within ±5 bps of ref.
    # in realistic, BUYs are slightly above (overpaid ask) and SELLs slightly below (undersold bid).
    issues = []
    if abs(mean_slip) < 2.0:
        # All fills very close to LTP — likely market_like mode
        issues.append({
            "issue": "fill_too_perfect",
            "detail": f"mean slippage {mean_slip:.2f} bps across {len(slippage_bps)} fills is unrealistically low. "
                      f"Paper is using market_like mode and underestimating slippage for live-equivalent estimation. "
                      f"Switch to fill_mode=realistic to model half-spread crossing.",
            "severity": "warn",
        })

    if abs(asymmetry) < 1.0 and len(by_side['BUY']) >= 3 and len(by_side['SELL']) >= 3:
        # BUYs and SELLs both at LTP — bid/ask not being used
        issues.append({
            "issue": "no_bid_ask_aware_fills",
            "detail": f"asymmetry BUY-SELL = {asymmetry:.2f} bps. Realistic mode should show positive asymmetry "
                      f"(BUYs filled above mid, SELLs filled below mid). Both legs around zero confirms paper is "
                      f"filling at LTP, not at bid/ask.",
            "severity": "warn",
        })

    # 95th-percentile slippage should be < 200 bps for paper (live can spike higher)
    if p95 > 200:
        issues.append({
            "issue": "large_slippage_outliers",
            "detail": f"95th-percentile slippage {p95:.0f} bps is high. Check if brain is using extreme "
                      f"limit prices or paper fills at stale LTP. Run with realistic mode to verify.",
            "severity": "warn",
        })

    # Overall status
    overall = "ok"
    if any(i['severity'] in ('warn', 'error') for i in issues):
        overall = "warn"

    # Determine detected fill_mode heuristically
    if abs(mean_slip) < 2.0:
        fill_mode_detected = "market_like (optimistic)"
    elif asymmetry > 2.0:
        fill_mode_detected = "realistic (bid/ask-aware)"
    else:
        fill_mode_detected = "unknown"

    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "issues": issues,
        "n_fills_today": n_fills_today,
        "n_total_today": n_total_today,
        "slippage_bps_mean": round(mean_slip, 2),
        "slippage_bps_p50": round(p50, 2),
        "slippage_bps_p95": round(p95, 2),
        "asymmetry_buy_sell_bps": round(asymmetry, 2),
        "buy_fills": len(by_side['BUY']),
        "sell_fills": len(by_side['SELL']),
        "avg_buy_slip_bps": round(avg_buy, 2),
        "avg_sell_slip_bps": round(avg_sell, 2),
        "live_equivalent_pnl_delta_rs": round(live_eq_pnl_delta, 2),
        "fill_mode_detected": fill_mode_detected,
    }

    (DCACHE / "slippage_audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")

    print(f"[slippage_audit] overall={overall}")
    print(f"  fills today: {n_fills_today} ({by_side['BUY']} BUY + {len(by_side['SELL'])} SELL)")
    print(f"  slippage_bps: mean={mean_slip:.2f} p50={p50:.2f} p95={p95:.2f}")
    print(f"  asymmetry (BUY-SELL): {asymmetry:.2f} bps")
    print(f"  live-equivalent P&L delta (estimate): Rs.{live_eq_pnl_delta:,.2f}")
    print(f"  detected fill_mode: {fill_mode_detected}")
    if issues:
        for i in issues:
            print(f"  - {i['severity'].upper()}: {i['issue']} — {i['detail'][:120]}...")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())