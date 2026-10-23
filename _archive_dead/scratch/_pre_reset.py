"""Find pre-reset entries."""
import json
reset = "2026-09-08T08:25:08"
pre_count = 0
post_count = 0
pre_pnl = 0
post_pnl = 0
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") != "FILL":
                continue
            ts = str(r.get("ts", ""))
            delta = r.get("realized_delta", 0) or 0
            if ts < reset:
                pre_count += 1
                pre_pnl += delta
            else:
                post_count += 1
                post_pnl += delta
        except Exception:
            pass
print(f"PRE-reset fills: {pre_count}, sum realized_delta: Rs.{pre_pnl:,.2f}")
print(f"POST-reset fills: {post_count}, sum realized_delta: Rs.{post_pnl:,.2f}")
print(f"TOTAL: Rs.{pre_pnl + post_pnl:,.2f}")
print(f"paper_state.realized_pnl: Rs.{json.load(open('data_cache/paper_state.json'))['realized_pnl']:,.2f}")
