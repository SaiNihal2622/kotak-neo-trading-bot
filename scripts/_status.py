"""Quick status check — shows brain, bot, P&L, decisions, signals, news."""
import json
from pathlib import Path

ROOT = Path("C:/Users/saini/.minimax-agent/projects/kotak-neo-bot")
DCACHE = ROOT / "data_cache"


def _esc(s):
    return str(s) if s is not None else "—"


def _read_json(p, default=None):
    if not p.exists():
        return default if default is not None else {}
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return default if default is not None else {}


def _read_jsonl(p, n=50):
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        out = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []


print("=" * 70)
print("KOTAK QUANT DESK — LIVE STATUS @ 12:38 IST (3.5h into market)")
print("=" * 70)

# Brain
qs = _read_json(DCACHE / "quant_service_state.json")
print(f"\nBRAIN (KotakQuantService):")
print(f"  status:        {qs.get('status')}")
print(f"  tick_count:    {qs.get('tick_count')}")
print(f"  llm_calls:     {qs.get('llm_calls')}")
print(f"  actions_taken: {qs.get('actions_taken')}")
print(f"  last_tick:     {qs.get('last_tick', '?')[:19]}")
last_dec = qs.get("last_decision_at")
print(f"  last_decision: {_esc(last_dec)[:19] if last_dec else 'never'}")

# Bot
lv = _read_json(DCACHE / "liveness.json")
s = lv.get("snapshot", {})
print(f"\nBOT (KotakBotPaper):")
print(f"  state:         {lv.get('state')}")
print(f"  uptime:        {lv.get('uptime_sec', 0)/3600:.1f}h")
print(f"  tick:          {lv.get('tick')}")
print(f"  capital:       Rs.{s.get('capital', 0):,.0f}")
print(f"  realized_pnl:  Rs.{s.get('realized_pnl', 0):+,.2f}")
print(f"  open_pos:      {s.get('open_positions')}")
print(f"  vix:           {s.get('vix')}")
print(f"  paused:        {s.get('is_paused')}")

# Paper state
ps = _read_json(DCACHE / "paper_state.json")
print(f"\nPAPER STATE:")
print(f"  cash:          Rs.{ps.get('cash', 0):,.0f}")
print(f"  realized_pnl:  Rs.{ps.get('realized_pnl', 0):+,.2f}")
open_pos = [p for p in ps.get("positions", {}).values() if p.get("qty", 0) != 0]
print(f"  open positions: {len(open_pos)}")
for p in open_pos:
    sym = p.get("symbol", "?")
    qty = p.get("qty", 0)
    avg = p.get("avg_price", 0)
    ltp = p.get("ltp", 0)
    pnl = (ltp - avg) * qty
    sign = "+" if pnl >= 0 else ""
    print(f"    {sym}: qty={qty} avg=Rs.{avg:.2f} ltp=Rs.{ltp:.2f} pnl={sign}Rs.{pnl:.2f}")

# Recent LLM decisions
decisions = []
dec_path = DCACHE / "quant_service_decisions.jsonl"
if dec_path.exists():
    for line in dec_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-15:]:
        try:
            decisions.append(json.loads(line))
        except Exception:
            continue
print(f"\nRECENT LLM DECISIONS (last 10):")
for d in decisions[-10:][::-1]:
    ts = _esc(d.get("ts"))[:19]
    decision = d.get("decision", {})
    dtype = decision.get("type", "?")
    underlying = decision.get("underlying", "")
    strategy = decision.get("strategy", "")
    conv = decision.get("conviction", 0)
    rationale = (decision.get("rationale") or "")[:120]
    print(f"  {ts} | {dtype:6} | {underlying:6} | {strategy:18} | conv={conv:3} | {rationale}")

# Today's fills
fills = _read_jsonl(DCACHE / "trade_journal.jsonl", n=200)
today = "2026-09-09"
today_fills = [e for e in fills if e.get("event") == "FILL" and (e.get("ts") or "").startswith(today)]
print(f"\nTODAY'S FILLS ({len(today_fills)}):")
for f in today_fills[-10:][::-1]:
    ts = _esc(f.get("ts"))[:19]
    sym = _esc(f.get("symbol"))
    side = _esc(f.get("side"))
    qty = f.get("qty", "?")
    px = f.get("avg_fill_price", 0)
    delta = f.get("realized_delta", 0)
    sign = "+" if delta > 0 else ""
    print(f"  {ts} | {side:4} {qty:3} {sym:30} @ Rs.{px:>7.2f} | delta={sign}Rs.{delta:.2f}")

# Predictive signals
ps_data = _read_json(DCACHE / "predictive_signals.json")
syms = ps_data.get("symbols", {})
print(f"\nPREDICTIVE SIGNALS (last update: {_esc(ps_data.get('ts'))[:19]}):")
for sym, s in syms.items():
    if "error" in s:
        print(f"  {sym}: ERROR — {s['error']}")
        continue
    d_ = s.get("DIRECTION", "?")
    conf = s.get("CONFIDENCE", 0)
    comp = s.get("COMPOSITE_SCORE", 0)
    rsi = s.get("RSI_14", 50)
    vol = s.get("VOLATILITY_REGIME", 1.0)
    print(f"  {sym:12} | {d_:8} | conf={conf:.2f} | composite={comp:+.2f} | RSI={rsi:.0f} | vol={vol:.2f}")

# FII/DII
fii = _read_json(DCACHE / "fii_dii.json")
rows = fii.get("rows", [])
summary = fii.get("summary", {})
print(f"\nFII/DII FLOWS (last update: {_esc(fii.get('ts'))[:19]}):")
for r in rows[:3]:
    date = r.get("date", "?")
    f_net = r.get("fii_net_cr", 0)
    d_net = r.get("dii_net_cr", 0)
    f_sign = "+" if f_net > 0 else ""
    d_sign = "+" if d_net > 0 else ""
    print(f"  {date:18} | FII: {f_sign}Rs.{f_net:>8.1f} cr | DII: {d_sign}Rs.{d_net:>8.1f} cr")
print(f"  3d sums: FII={_esc((summary.get('fii_net_3d_sum_cr') or 0))} DII={_esc((summary.get('dii_net_3d_sum_cr') or 0))}")

# News
news_path = DCACHE / "news_feed.txt"
print(f"\nNEWS (last fetch: {news_path.stat().st_mtime if news_path.exists() else 'never'}):")
if news_path.exists():
    lines = news_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[:5]
    for line in lines:
        print(f"  {line[:150]}")
else:
    print("  No news yet")

# Grok Bot Desk
grok = _read_json(DCACHE / "grok_desk_state.json")
print(f"\nGROK BOT DESK (last cycle: {_esc(grok.get('cycle_ts'))[:19]}, {grok.get('duration_sec', '?')}s):")
print(f"  Head of desk: {(_esc(grok.get('head'))[:200] or '—')}")
for name, key in [("Scanner", "scanner"), ("Hunter", "hunter"), ("News", "news"),
                   ("Whales", "whales"), ("Risk", "risk")]:
    txt = (grok.get(key, "") or "")[:120]
    print(f"  {name:8}: {txt or '—'}")

# Schedulers
print(f"\nSCHEDULERS (last 8 events from brain log):")
log_lines = []
log = _read_jsonl(DCACHE / "quant_service.log", n=200)
for line in log:
    if "SCHED-" in str(line):
        log_lines.append(str(line)[:200])
for l in log_lines[-8:]:
    print(f"  {l}")

print("\n" + "=" * 70)
print("DASHBOARD: data_cache/dashboard.html (auto-refresh 5s)")
print("=" * 70)
