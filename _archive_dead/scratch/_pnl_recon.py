import json
ps = json.loads(open('data_cache/paper_state.json', encoding='utf-8').read())
total_pnl = 0.0
opens = {}
for oid, o in ps['orders'].items():
    if not o.get('placed_at', '').startswith('2026-09-07'):
        continue
    if o.get('status') != 'complete':
        continue
    sym = o.get('symbol', '')
    side = o.get('side', '')
    px = o.get('avg_fill_price', 0)
    qty = o.get('filled_qty', 0)
    tag = o.get('tag', '')
    key = (sym, side)
    if tag.startswith('QUANT-') or tag.startswith('TEMPLATE-') or tag.startswith('MAVIS-'):
        opens[key] = (qty, px, tag)
    else:
        opp_side = 'SELL' if side == 'BUY' else 'BUY'
        if (sym, opp_side) in opens:
            oqty, o_px, otag = opens[(sym, opp_side)]
            if side == 'SELL':
                pnl = (o_px - px) * qty
            else:
                pnl = (px - o_px) * qty
            total_pnl += pnl
            print(f'{sym} {side}@{px} qty={qty} | open {opp_side}@{o_px} qty={oqty} | pnl={pnl:+.2f}')
            del opens[(sym, opp_side)]
print(f'\nTotal realized P&L from matched pairs: {total_pnl:+.2f}')
print(f'Paper state realized_pnl: {ps["realized_pnl"]:+.2f}')
print(f'Diff: {ps["realized_pnl"] - total_pnl:+.2f}')
