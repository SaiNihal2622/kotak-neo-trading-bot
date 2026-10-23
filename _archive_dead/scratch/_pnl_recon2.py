"""Reconcile the bot's realized_pnl with my per-leg reconstruction.

If they don't match, find the missing delta.
"""
import json
from collections import defaultdict

ps = json.loads(open('data_cache/paper_state.json', encoding='utf-8').read())
bot_realized = ps['realized_pnl']
print(f"Bot's realized_pnl: {bot_realized:+.2f}\n")

# For each filled order in chronological order, simulate the bot's
# _apply_fill logic and see what realized_pnl builds up to.
positions = {}  # symbol -> (qty, avg_price)
my_realized = 0.0
opens = {}  # (sym, side) -> (qty, px, tag)

orders_sorted = sorted(ps['orders'].items(), key=lambda kv: kv[1].get('placed_at', ''))
for oid, o in orders_sorted:
    if not o.get('placed_at', '').startswith('2026-09-07'):
        continue
    if o.get('status') != 'complete':
        continue
    sym = o.get('symbol', '')
    side = o.get('side', '')
    px = o.get('avg_fill_price', 0)
    qty = o.get('filled_qty', 0)
    tag = o.get('tag', '')

    is_open = tag.startswith('QUANT-') or tag.startswith('TEMPLATE-') or tag.startswith('MAVIS-')

    if is_open:
        # Open: add to position
        pos = positions.get(sym)
        if pos is None:
            positions[sym] = (qty if side == 'BUY' else -qty, px)
        else:
            cqty, cpx = pos
            if side == 'BUY':
                # adding to long or covering short
                if cqty >= 0:
                    new_qty = cqty + qty
                    new_px = (cpx * cqty + px * qty) / new_qty
                    positions[sym] = (new_qty, new_px)
                else:
                    cover = min(-cqty, qty)
                    my_realized += (cpx - px) * cover
                    new_qty = cqty + qty
                    if new_qty == 0:
                        del positions[sym]
                    elif new_qty > 0:
                        positions[sym] = (new_qty, px)
                    else:
                        positions[sym] = (new_qty, cpx)
            else:  # SELL
                if cqty <= 0:
                    new_qty = cqty - qty
                    new_px = (cpx * abs(cqty) + px * qty) / abs(new_qty)
                    positions[sym] = (new_qty, new_px)
                else:
                    close = min(cqty, qty)
                    my_realized += (px - cpx) * close
                    new_qty = cqty - qty
                    if new_qty == 0:
                        del positions[sym]
                    elif new_qty < 0:
                        positions[sym] = (new_qty, px)
                    else:
                        positions[sym] = (new_qty, cpx)
    else:
        # Close
        pos = positions.get(sym)
        if pos is None:
            print(f"  {sym} {side}@{px} qty={qty} [{tag}] — NO POSITION (skipped)")
            continue
        cqty, cpx = pos
        if side == 'BUY':
            short_close = min(abs(cqty), qty) if cqty < 0 else 0
            my_realized += (cpx - px) * short_close
            new_qty = cqty + qty
            if new_qty == 0:
                del positions[sym]
            elif new_qty > 0:
                positions[sym] = (new_qty, px)
            else:
                positions[sym] = (new_qty, cpx)
        else:  # SELL
            close_qty = min(cqty, qty) if cqty > 0 else 0
            my_realized += (px - cpx) * close_qty
            new_qty = cqty - qty
            if new_qty == 0:
                del positions[sym]
            elif new_qty < 0:
                positions[sym] = (new_qty, px)
            else:
                positions[sym] = (new_qty, cpx)
    print(f"  {sym} {side}@{px} qty={qty} [{tag}] | running realized={my_realized:+.2f} | positions={ {k: v for k, v in positions.items()} }")

print(f"\nReconstructed realized_pnl: {my_realized:+.2f}")
print(f"Bot's realized_pnl: {bot_realized:+.2f}")
print(f"Diff: {bot_realized - my_realized:+.2f}")
print(f"Open positions at EOD: {positions}")
