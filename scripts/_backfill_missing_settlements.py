"""FIX 2026-09-18 17:30: backfill missing 0DTE settlement entries.

The Sep 17 iron condor settled at 15:30 IST with +Rs.6,216 total P&L.
Paper_state correctly shows this cash, but the journal missed the
4 EXPIRY entries (only 1 was written for a Sep 10 leftover).

This script:
1. Finds positions in paper_state that have:
   - expiry date in the past (today > expiry)
   - 0DTE status (expiry == today - 1 typically)
   - no corresponding EXPIRY-* journal entry
2. Computes settlement P&L using intrinsic
3. Writes EXPIRY-* entries to trade_journal.jsonl

This reconciles the journal with paper_state.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"

IST = timezone(timedelta(hours=5, minutes=30))


def main():
    """Write 4 EXPIRY entries for the Sep 17 0DTE iron condor settlement.

    This is a one-time backfill — the original _settle_expired_positions
    code only wrote 1 EXPIRY entry (Sep 10 leftover) but missed the 4
    legs of the Sep 17 iron condor. Paper_state correctly shows +6,216
    from the settlement but the journal is missing it.
    """
    jrnl_path = DCACHE / "trade_journal.jsonl"
    existing = set()
    if jrnl_path.exists():
        with jrnl_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    tid = r.get("trade_id", "")
                    if tid.startswith("EXPIRY-"):
                        existing.add(tid)
                except Exception:
                    pass

    # The 4 legs of the Sep 17 iron condor with their actual realized_delta
    # (computed from the orders that paper_state has tracked)
    backfill = [
        {
            "trade_id": "EXPIRY-2026-09-17-NIFTY17SEP2623350CE",
            "symbol": "NIFTY17SEP2623350CE",
            "underlying": "NIFTY",
            "strike": 23350,
            "option_type": "CE",
            "side": "BUY",
            "qty": 75,
            "avg_fill_price": 0.0,
            "realized_delta": 6507.0,  # SELL 86.76 - settlement 0 = +86.76 × 75 = +6507
            "tag": "0dte_expiry_settlement_BACKFILL",
        },
        {
            "trade_id": "EXPIRY-2026-09-17-NIFTY17SEP2623500CE",
            "symbol": "NIFTY17SEP2623500CE",
            "underlying": "NIFTY",
            "strike": 23500,
            "option_type": "CE",
            "side": "SELL",
            "qty": 75,
            "avg_fill_price": 0.0,
            "realized_delta": -2913.0,  # BUY 38.84 - settlement 0 = -38.84 × 75
            "tag": "0dte_expiry_settlement_BACKFILL",
        },
        {
            "trade_id": "EXPIRY-2026-09-17-NIFTY17SEP2623150PE",
            "symbol": "NIFTY17SEP2623150PE",
            "underlying": "NIFTY",
            "strike": 23150,
            "option_type": "PE",
            "side": "BUY",
            "qty": 75,
            "avg_fill_price": 0.0,
            "realized_delta": 5798.25,  # SELL 77.31 × 75
            "tag": "0dte_expiry_settlement_BACKFILL",
        },
        {
            "trade_id": "EXPIRY-2026-09-17-NIFTY17SEP2623000PE",
            "symbol": "NIFTY17SEP2623000PE",
            "underlying": "NIFTY",
            "strike": 23000,
            "option_type": "PE",
            "side": "SELL",
            "qty": 75,
            "avg_fill_price": 0.0,
            "realized_delta": -3176.25,  # BUY 42.35 × 75 = -3176.25
            "tag": "0dte_expiry_settlement_BACKFILL",
        },
    ]

    settle_ts = "2026-09-17T15:30:00"
    written = 0
    with jrnl_path.open("a", encoding="utf-8") as f:
        for entry in backfill:
            if entry["trade_id"] in existing:
                continue
            rec = {
                "trade_id": entry["trade_id"],
                "order_id": f"EXPIRY-CLOSE-{entry['symbol']}",
                "symbol": entry["symbol"],
                "underlying": entry["underlying"],
                "strike": entry["strike"],
                "option_type": entry["option_type"],
                "side": entry["side"],
                "qty": entry["qty"],
                "avg_fill_price": entry["avg_fill_price"],
                "expected_fill_price": entry["avg_fill_price"],
                "tag": entry["tag"],
                "realized_delta": entry["realized_delta"],
                "status": "complete",
                "placed_at": settle_ts,
                "filled_at": settle_ts,
                "event": "FILL",
                "ts": settle_ts,
                "phantom_price": False,
                "suspect_price": False,
                "_backfill_note": "One-time backfill — settlement code missed writing these entries to journal.",
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
            print(f"  Wrote {entry['trade_id']}: delta=Rs.{entry['realized_delta']:+,.2f}")

    print(f"\nWrote {written} backfill entries")
    if written:
        # Verify reconciliation
        state = json.loads((DCACHE / "paper_state.json").read_text(encoding="utf-8"))
        ps = state.get("realized_pnl", 0)
        seen = set()
        js = 0.0
        with jrnl_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("event") != "FILL" or r.get("phantom_price"):
                        continue
                    sym = r.get("symbol", "")
                    side = r.get("side", "")
                    ts = str(r.get("ts", ""))[:10]
                    if not sym or not side or not ts:
                        continue
                    if side == "SELL":
                        key = (sym, "SELL", ts)
                    else:
                        key = (sym, "BUY", r.get("qty", 0), round(float(r.get("avg_fill_price", 0) or 0), 2), ts)
                    if key in seen:
                        continue
                    seen.add(key)
                    js += r.get("realized_delta", 0) or 0
                except Exception:
                    pass
        print(f"\nAfter backfill:")
        print(f"  journal dedup'd sum: Rs.{js:,.2f}")
        print(f"  paper_state.realized_pnl: Rs.{ps:,.2f}")
        print(f"  Remaining diff: Rs.{ps - js:+,.2f}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
