import json
ps = json.loads(open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json", encoding="utf-8").read())
ts = json.loads(open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json", encoding="utf-8").read())
open_trades = sum(1 for t in ts["trades"].values() if t.get("status") == "open")
closed_trades = sum(1 for t in ts["trades"].values() if t.get("status") == "closed")
cash = ps["cash"]
realized = ps["realized_pnl"]
print(f"paper: cash=Rs.{cash:,.0f} realized=Rs.{realized:,.0f} orders={len(ps['orders'])} positions={len(ps['positions'])}")
print(f"trades: total={len(ts['trades'])} open={open_trades} closed={closed_trades}")
