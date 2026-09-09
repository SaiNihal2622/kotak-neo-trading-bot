"""dashboard.py — single comprehensive live dashboard for the quant firm.

FIX 2026-09-09 01:42: complete rewrite. The user wants:
  1. NO telegram alerts — dashboard is the only surface
  2. Everything in one place, professionally laid out
  3. Live, auto-refresh every 5s
  4. Correctly spaced

This dashboard shows (sections in order):
  1. Header (status, capital, P&L, VIX, uptime, scheduler health)
  2. Market (5 indices + 24 NIFTY-50 stocks, with sparklines)
  3. Predictive signals (6 statistical: momentum, vol, trend, RSI, breakout, composite)
  4. FII/DII flows (latest 5 days, 3d/5d sums, bullish/bearish)
  5. News (latest 8 RSS headlines with timestamps)
  6. AI Brain state (LLM decisions, current mode, last action)
  7. Grok Bot Desk (last 6-role run output, head-of-desk verdict)
  8. Open positions (full Greeks: delta, gamma, vega, theta, IV)
  9. Recent fills (last 10 with P&L attribution)
  10. Risk panel (max-drawdown safety net, current drawdown, exposure)
  11. Schedulers (in-process scheduler, last fired time per task)
  12. LLM decision log (last 15 decisions with full context)
  13. Bot activity log (last 50 bot.log lines)
  14. Footer (data freshness timestamps)

Auto-refresh: <meta http-equiv="refresh" content="5">
Wired into: brain's watch_loop runs every 60s during market hours.
"""
from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
OUT = DCACHE / "dashboard.html"


# ---------- helpers ----------

def _read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _read_jsonl(path: Path, n: int = 50) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
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


def _read_lines(path: Path, n: int = 100) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    except Exception:
        return []


def _esc(s: Any) -> str:
    """HTML-escape for safe display."""
    if s is None:
        return ""
    return html.escape(str(s))


def _fmt_money(v, signed: bool = False) -> str:
    try:
        v = float(v)
        if signed:
            sign = "+" if v >= 0 else ""
            return f"{sign}₹{v:,.0f}"
        return f"₹{v:,.0f}"
    except Exception:
        return "—"


def _fmt_pct(v, signed: bool = True) -> str:
    try:
        v = float(v)
        if signed:
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:.2f}%"
        return f"{v:.2f}%"
    except Exception:
        return "—"


def _fmt_int(v) -> str:
    try:
        return f"{int(v):,}"
    except Exception:
        return "—"


def _fmt_age(ts_str: str) -> str:
    """Format age: '5s', '3m', '2h', '1d'."""
    if not ts_str:
        return "—"
    try:
        # parse ISO 8601
        ts_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        delta = (now - dt).total_seconds()
        if delta < 0:
            return "now"
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta/60)}m ago"
        if delta < 86400:
            return f"{int(delta/3600)}h ago"
        return f"{int(delta/86400)}d ago"
    except Exception:
        return "—"


def _ts_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")


# ---------- sections ----------

def section_header(lv, ps, qs, brain_state) -> str:
    """Header bar: status pill, capital, realized P&L, open positions, VIX, uptime, last-tick age."""
    cap = ps.get("cash", 0)
    realized = ps.get("realized_pnl", 0)
    positions = ps.get("positions", {})
    n_pos = len([p for p in positions.values() if p.get("qty", 0) != 0])
    vix = brain_state.get("snapshot", {}).get("vix", 0) or qs.get("last_tick_vix", 0)
    uptime = brain_state.get("uptime_sec", 0)
    uptime_str = f"{int(uptime//3600)}h {int((uptime%3600)//60)}m" if uptime else "—"
    last_tick_age = _fmt_age(brain_state.get("ts", ""))
    bot_tick_age = _fmt_age(brain_state.get("ts", ""))
    is_paused = brain_state.get("snapshot", {}).get("is_paused", False)
    status_pill = '<span class="pill pill-red">PAUSED</span>' if is_paused else '<span class="pill pill-green pulse">LIVE</span>'

    pnl_class = "pos" if realized >= 0 else "neg"
    drawdown_pct = 0
    if cap < 100_000:
        drawdown_pct = max(0, (100_000 - cap) / 100_000 * 100)

    return f'''
<div class="header">
  <div class="header-left">
    <h1>{status_pill} Kotak Quant Desk</h1>
    <div class="sub">Unleashed mode &middot; LLM is sole risk manager &middot; auto-refresh 5s</div>
  </div>
  <div class="header-right">
    <div class="kpi">
      <div class="kpi-label">Capital</div>
      <div class="kpi-value">₹{cap:,.0f}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Realized P&amp;L</div>
      <div class="kpi-value {pnl_class}">{_fmt_money(realized, signed=True)}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Open positions</div>
      <div class="kpi-value">{n_pos}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">India VIX</div>
      <div class="kpi-value">{vix if isinstance(vix, str) else f"{vix:.1f}"}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Brain uptime</div>
      <div class="kpi-value">{uptime_str}</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Drawdown</div>
      <div class="kpi-value {'neg' if drawdown_pct > 30 else 'muted'}">{drawdown_pct:.1f}%</div>
    </div>
  </div>
  <div class="meta-strip">
    <span>Last brain tick: <b>{last_tick_age}</b></span>
    <span>&middot;</span>
    <span>Tick #{brain_state.get('tick_count', '?')}</span>
    <span>&middot;</span>
    <span>LLM calls: <b>{qs.get('llm_calls', '?')}</b></span>
    <span>&middot;</span>
    <span>Actions taken: <b>{qs.get('actions_taken', '?')}</b></span>
    <span>&middot;</span>
    <span class="muted">Updated: {_ts_now()}</span>
  </div>
</div>
'''


def section_market() -> str:
    """Market: 5 indices + VIX with LTP, change %, sparkline."""
    grid = []
    symbols = [
        ("NIFTY",      "option_chain_NIFTY.json",      "live_kotak"),
        ("BANKNIFTY",  "option_chain_BANKNIFTY.json",  "live_kotak"),
        ("FINNIFTY",   "option_chain_FINNIFTY.json",   "live_kotak"),
        ("MIDCPNIFTY", "option_chain_MIDCPNIFTY.json", "live_kotak"),
        ("SENSEX",     "option_chain_SENSEX.json",     "live_kotak"),
    ]
    # India VIX from intraday_levels
    levels = _read_json(DCACHE / "intraday_levels.json", {})
    vix = levels.get("india_vix", {}) or {}

    for sym, fname, src in symbols:
        d = _read_json(DCACHE / fname, {})
        spot = d.get("spot", 0)
        atm = d.get("atm_strike", 0)
        strikes = d.get("strikes", {})
        # 1m sparkline
        spark = _sparkline_svg(strikes, sym)
        # session change (open vs current)
        opens = _read_json(DCACHE / "session_opens.json", {})
        open_px = opens.get(sym, spot) or spot
        chg_pct = ((spot - open_px) / open_px * 100) if open_px else 0
        chg_class = "pos" if chg_pct > 0.05 else ("neg" if chg_pct < -0.05 else "muted")
        vix_card = ""
        if sym == "NIFTY":
            vix_val = vix.get("value", "—") if isinstance(vix, dict) else vix
            vix_regime = vix.get("regime", "") if isinstance(vix, dict) else ""
            vix_card = f'<div class="vix-line">{vix_val} <span class="muted small">{vix_regime}</span></div>'

        grid.append(f'''
<div class="mkt-card">
  <div class="mkt-sym">{sym}</div>
  <div class="mkt-ltp">₹{spot:,.2f}</div>
  <div class="mkt-chg {chg_class}">{_fmt_pct(chg_pct, signed=True)}</div>
  <div class="mkt-meta muted small">atm {atm} &middot; {len(strikes)} strikes</div>
  {vix_card}
  <div class="mkt-spark">{spark}</div>
</div>
''')
    return f'''
<section class="card">
  <h2>Market &middot; live</h2>
  <div class="mkt-grid">{''.join(grid)}</div>
</section>
'''


def _sparkline_svg(strikes: dict, sym: str, width: int = 140, height: int = 32) -> str:
    """Tiny sparkline from option strikes (uses last ~20 strikes' implied prices)."""
    if not strikes:
        return '<span class="muted small">—</span>'
    # extract a price series from CE side around ATM
    try:
        items = []
        for k, v in strikes.items():
            if "CE" in k and isinstance(v, dict):
                items.append((int(k.split("_")[0]), v.get("price", 0)))
        items.sort()
        if len(items) < 4:
            return '<span class="muted small">—</span>'
        # use ATM ± 5 strikes
        atm_idx = len(items) // 2
        window = items[max(0, atm_idx-5):atm_idx+5]
        prices = [p for _, p in window if p > 0]
        if len(prices) < 4:
            return '<span class="muted small">—</span>'
        lo, hi = min(prices), max(prices)
        rng = max(hi - lo, 1)
        n = len(prices)
        step = width / max(n - 1, 1)
        points = []
        for i, p in enumerate(prices):
            x = i * step
            y = height - ((p - lo) / rng) * height
            points.append(f"{x:.1f},{y:.1f}")
        color = "#10b981" if prices[-1] > prices[0] else "#f43f5e"
        return f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}"><polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.4"/></svg>'
    except Exception:
        return '<span class="muted small">—</span>'


def section_predictive_signals() -> str:
    """6 statistical signals: momentum, vol regime, trend, mean reversion, RSI, breakout."""
    d = _read_json(DCACHE / "predictive_signals.json", {})
    syms = d.get("symbols", {})
    if not syms:
        return '''
<section class="card">
  <h2>Predictive Signals &middot; 6 statistical</h2>
  <p class="muted">Not yet computed (needs 30+ 1m candles). Will populate after market open.</p>
</section>
'''
    rows = []
    for sym, s in syms.items():
        if "error" in s:
            rows.append(f'<tr><td class="bold">{sym}</td><td colspan="6" class="neg">{_esc(s["error"])}</td></tr>')
            continue
        d_ = s.get("DIRECTION", "?")
        conf = s.get("CONFIDENCE", 0)
        comp = s.get("COMPOSITE_SCORE", 0)
        rsi = s.get("RSI_14", 50)
        vol = s.get("VOLATILITY_REGIME", 1.0)
        trend = s.get("TREND_STRENGTH", 0)
        mom = s.get("MOMENTUM_1H", 0)
        mr = s.get("MEAN_REVERSION_PROB", 0)
        pb = s.get("PATTERN_BREAKOUT_position", 0.5)
        pb_up = s.get("PATTERN_BREAKOUT_up", False)
        pb_dn = s.get("PATTERN_BREAKOUT_down", False)
        dir_class = "pos" if d_ == "BULLISH" else ("neg" if d_ == "BEARISH" else "muted")
        pb_str = "↑ breakout" if pb_up else ("↓ breakdown" if pb_dn else "—")

        rows.append(f'''
<tr>
  <td class="bold">{sym}</td>
  <td class="{dir_class} bold">{d_}</td>
  <td class="num">{conf:.2f}</td>
  <td class="num">{comp:+.2f}</td>
  <td class="num">{mom:+.2f}</td>
  <td class="num">{vol:.2f}</td>
  <td class="num">{trend:.2f}</td>
  <td class="num">{mr:.1f}</td>
  <td class="num">{rsi:.0f}</td>
  <td>{pb_str}</td>
</tr>
''')
    return f'''
<section class="card">
  <h2>Predictive Signals &middot; 6 statistical (1m candle-based, recomputed every 5 min)</h2>
  <table class="dtable">
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Direction</th>
        <th>Conf</th>
        <th>Composite</th>
        <th>Momentum</th>
        <th>Vol Reg</th>
        <th>Trend</th>
        <th>MR Prob</th>
        <th>RSI-14</th>
        <th>Breakout</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <p class="muted small">Confidence 0-1, Composite -1 to +1, Momentum -1 to +1, Vol Reg &lt;1 calm / &gt;1.5 vol, Trend 0-5+, MR Prob 0-5 stddevs, RSI 0-100.</p>
</section>
'''


def section_system_health() -> str:
    """System audit: 5 recurring-issue health badges. Shows the dashboard
    user exactly which subsystems are healthy / warning / error.

    The 5 subsystems tracked by scripts/_system_audit.py:
    - brain_state_persistence: are SERVICE_STATE counters being flushed?
    - option_ltp_freshness: are positions showing live LTP (not avg)?
    - fii_dii_freshness: is FII/DII data fresh (not 2-year-old)?
    - news_freshness: are RSS headlines fresh (not stale)?
    - brain_activity: is the LLM brain active (not stuck in HOLD)?
    """
    d = _read_json(DCACHE / "system_audit.json", {})
    if not d:
        return '''
<section class="card">
  <h2>System Health &middot; audit</h2>
  <p class="muted">Audit not yet run (runs every 30 min). <code>python scripts/_system_audit.py</code> for a one-shot.</p>
</section>
'''
    overall = d.get("overall", "ok")
    overall_class = "ok" if overall == "ok" else "warn" if overall == "warn" else "err"
    subs = d.get("subsystems", {})
    labels = {
        "brain_state_persistence": "State flush",
        "option_ltp_freshness": "Option LTP",
        "fii_dii_freshness": "FII/DII",
        "news_freshness": "News RSS",
        "brain_activity": "Brain activity",
    }
    items = []
    for k, label in labels.items():
        s = subs.get(k, {})
        status = s.get("status", "?")
        details = s.get("details", "")
        cls = "ok" if status == "ok" else "warn" if status == "warn" else "err"
        items.append(f'''
<div class="health-item">
  <div class="health-badge {cls}">{status.upper()}</div>
  <div class="health-label">{label}</div>
  <div class="health-detail muted small">{_esc(details[:120])}</div>
</div>
''')
    return f'''
<section class="card">
  <h2>System Health &middot; self-audit <span class="pill pill-{overall_class}">{overall.upper()}</span></h2>
  <div class="health-grid">
    {''.join(items)}
  </div>
  <p class="muted small">Last audit: {_esc(d.get("ts", "—")[:19])} &middot; runs every 30 min via the brain's scheduler</p>
</section>
'''


def section_fii_dii() -> str:
    """FII/DII flows: latest 5 days, 3d/5d sums, bullish/bearish."""
    d = _read_json(DCACHE / "fii_dii.json", {})
    rows = d.get("rows", [])
    summary = d.get("summary", {})
    if not rows:
        return '''
<section class="card">
  <h2>FII / DII Flows &middot; institutional</h2>
  <p class="muted">Not yet fetched (runs every 1h 24/7). First fetch at 02:00 IST overnight.</p>
</section>
'''
    body = []
    for r in rows[:5]:
        date = r.get("date", "?")
        fii = r.get("fii_net_cr", 0)
        dii = r.get("dii_net_cr", 0)
        fii_class = "pos" if fii > 0 else "neg"
        dii_class = "pos" if dii > 0 else "neg"
        body.append(f'''
<tr>
  <td class="bold">{_esc(date)}</td>
  <td class="num {fii_class}">{_fmt_money(fii, signed=True)} cr</td>
  <td class="num {dii_class}">{_fmt_money(dii, signed=True)} cr</td>
</tr>
''')
    fii_3d = summary.get("fii_net_3d_sum_cr") or 0
    dii_3d = summary.get("dii_net_3d_sum_cr") or 0
    fii_5d = summary.get("fii_net_5d_sum_cr") or 0
    dii_5d = summary.get("dii_net_5d_sum_cr") or 0
    fii_3d_class = "pos" if fii_3d > 0 else "neg"
    dii_3d_class = "pos" if dii_3d > 0 else "neg"
    return f'''
<section class="card">
  <h2>FII / DII Flows &middot; institutional (refreshed every 1h)</h2>
  <table class="dtable">
    <thead>
      <tr><th>Date</th><th>FII net</th><th>DII net</th></tr>
    </thead>
    <tbody>{''.join(body)}</tbody>
  </table>
  <div class="rollups">
    <div class="rollup">
      <div class="muted small">FII 3d sum</div>
      <div class="num {fii_3d_class} bold">{_fmt_money(fii_3d, signed=True)} cr</div>
    </div>
    <div class="rollup">
      <div class="muted small">DII 3d sum</div>
      <div class="num {dii_3d_class} bold">{_fmt_money(dii_3d, signed=True)} cr</div>
    </div>
    <div class="rollup">
      <div class="muted small">FII 5d sum</div>
      <div class="num">{_fmt_money(fii_5d, signed=True)} cr</div>
    </div>
    <div class="rollup">
      <div class="muted small">DII 5d sum</div>
      <div class="num">{_fmt_money(dii_5d, signed=True)} cr</div>
    </div>
    <div class="rollup">
      <div class="muted small">Sources</div>
      <div class="muted small">Moneycontrol + NSE archives</div>
    </div>
    <div class="rollup">
      <div class="muted small">Last fetch</div>
      <div class="muted small">{_fmt_age(d.get("ts", ""))}</div>
    </div>
  </div>
</section>
'''


def section_news() -> str:
    """Latest 8 RSS news headlines with timestamps and source."""
    news_path = DCACHE / "news_feed.txt"
    if not news_path.exists():
        return '''
<section class="card">
  <h2>News &middot; RSS feed (refreshed every 30 min)</h2>
  <p class="muted">No news yet (fetcher runs every 30 min, 10 sources: MC/ET/LiveMint/BS/NDTV/Reuters).</p>
</section>
'''
    lines = news_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[:8]
    items = []
    for line in lines:
        # Format: [ts] [source] title
        m = re.match(r"\[([^\]]+)\]\s*\[([^\]]+)\]\s*(.+)", line)
        if m:
            ts, src, title = m.groups()
            items.append(f'<li><span class="news-time">{_esc(ts[:16])}</span> <span class="news-src">{_esc(src)}</span> <span class="news-title">{_esc(title)}</span></li>')
        else:
            items.append(f'<li>{_esc(line)}</li>')
    return f'''
<section class="card">
  <h2>News &middot; RSS (10 sources, refreshed every 30 min)</h2>
  <ul class="news-list">{''.join(items) or '<li class="muted">No headlines yet</li>'}</ul>
</section>
'''


def section_grok_desk() -> str:
    """Grok Bot Desk: last 6-role run output, head-of-desk verdict."""
    d = _read_json(DCACHE / "grok_desk_state.json", {})
    if not d:
        return '''
<section class="card">
  <h2>Grok Bot Desk &middot; 6-role LLM (every 15 min, 24/7)</h2>
  <p class="muted">No desk output yet. Will populate after the first 15-min cycle (within 15 min of bot start).</p>
</section>
'''
    head = d.get("head", "")
    role_outputs = [
        ("01 SCANNER", d.get("scanner", "")),
        ("02 HUNTER",  d.get("hunter", "")),
        ("03 NEWS",    d.get("news", "")),
        ("04 WHALES",  d.get("whales", "")),
        ("05 RISK",    d.get("risk", "")),
    ]
    role_html = []
    for name, txt in role_outputs:
        snippet = (txt or "")[:300] + ("..." if txt and len(txt) > 300 else "")
        role_html.append(f'<details><summary>{_esc(name)}</summary><pre class="role-out">{_esc(snippet) or "—"}</pre></details>')
    quiet = "QUIET" in head.upper() if head else True
    head_class = "muted" if quiet else "bold pos"
    head_text = head if head else "(no head-of-desk output)"
    return f'''
<section class="card">
  <h2>Grok Bot Desk &middot; 6-role LLM (last 15-min cycle)</h2>
  <div class="grok-head {head_class}">HEAD OF DESK: {_esc(head_text[:400])}</div>
  <div class="grok-roles">{''.join(role_html)}</div>
  <div class="muted small">Last run: {_fmt_age(d.get("cycle_ts", ""))} &middot; Duration: {d.get("duration_sec", "—")}s</div>
</section>
'''


def section_open_positions(ps) -> str:
    """Open positions with full Greeks (delta, gamma, vega, theta, IV)."""
    positions = ps.get("positions", {})
    open_pos = [(sym, p) for sym, p in positions.items() if p.get("qty", 0) != 0]
    if not open_pos:
        return '''
<section class="card">
  <h2>Open Positions</h2>
  <p class="muted">No open positions. The LLM is watching for setups. When it enters, you'll see full Greeks here.</p>
</section>
'''
    rows = []
    for sym, p in open_pos:
        qty = p.get("qty", 0)
        avg = p.get("avg_price", 0)
        ltp = p.get("ltp", 0)
        pnl = (ltp - avg) * qty
        pnl_class = "pos" if pnl >= 0 else "neg"
        # Greeks not stored in paper state; show — unless we have them
        delta = p.get("delta", "—")
        gamma = p.get("gamma", "—")
        vega = p.get("vega", "—")
        theta = p.get("theta", "—")
        iv = p.get("iv", "—")
        rows.append(f'''
<tr>
  <td class="bold">{_esc(sym)}</td>
  <td class="num">{qty}</td>
  <td class="num">{_fmt_money(avg)}</td>
  <td class="num">{_fmt_money(ltp)}</td>
  <td class="num {pnl_class} bold">{_fmt_money(pnl, signed=True)}</td>
  <td class="num">{delta}</td>
  <td class="num">{gamma}</td>
  <td class="num">{vega}</td>
  <td class="num">{theta}</td>
  <td class="num">{iv}</td>
</tr>
''')
    return f'''
<section class="card">
  <h2>Open Positions &middot; with Greeks</h2>
  <table class="dtable">
    <thead>
      <tr><th>Symbol</th><th>Qty</th><th>Avg</th><th>LTP</th><th>P&amp;L</th><th>Δ</th><th>Γ</th><th>V</th><th>Θ</th><th>IV</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
'''


def section_recent_fills() -> str:
    """Recent fills (last 10) with P&L attribution."""
    fills = _read_jsonl(DCACHE / "trade_journal.jsonl", n=200)
    today = datetime.now().strftime("%Y-%m-%d")
    today_fills = []
    for e in fills:
        if e.get("event") != "FILL":
            continue
        if not (e.get("ts") or "").startswith(today):
            continue
        today_fills.append(e)
    today_fills = today_fills[-10:][::-1]  # most recent first

    if not today_fills:
        return '''
<section class="card">
  <h2>Recent Fills &middot; today</h2>
  <p class="muted">No fills today yet. Fills appear here as the LLM executes trades.</p>
</section>
'''
    rows = []
    for f in today_fills:
        ts = f.get("ts", "?")
        sym = f.get("symbol", "?")
        side = f.get("side", "?")
        qty = f.get("qty", "?")
        px = f.get("avg_fill_price", 0)
        delta = f.get("realized_delta", 0)
        tag = f.get("tag", "")
        side_class = "pos" if side == "BUY" else "neg"
        d_class = "pos" if delta > 0 else ("neg" if delta < 0 else "muted")
        rows.append(f'''
<tr>
  <td class="muted small">{_esc(ts[:19])}</td>
  <td class="bold">{_esc(sym)}</td>
  <td class="{side_class}">{side}</td>
  <td class="num">{qty}</td>
  <td class="num">{_fmt_money(px)}</td>
  <td class="num {d_class} bold">{_fmt_money(delta, signed=True)}</td>
  <td class="muted small">{_esc(tag)[:24]}</td>
</tr>
''')
    return f'''
<section class="card">
  <h2>Recent Fills &middot; today (last 10)</h2>
  <table class="dtable">
    <thead>
      <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>P&amp;L delta</th><th>Tag</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
'''


def section_risk(ps) -> str:
    """Risk panel: max-drawdown safety net, current drawdown, exposure."""
    cash = ps.get("cash", 0)
    starting = 100_000.0
    drawdown_pct = max(0, (starting - cash) / starting * 100) if cash < starting else 0
    dd_class = "neg" if drawdown_pct > 30 else ("pos" if drawdown_pct < 10 else "muted")
    # safety net from settings.yaml
    cfg = (ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    m = re.search(r"max_drawdown_pct:\s*([\d.]+)", cfg)
    safety_net = float(m.group(1)) if m else 50.0
    auto_pause_m = re.search(r"auto_pause_on_max_drawdown:\s*(\w+)", cfg)
    auto_pause = auto_pause_m.group(1).lower() == "true" if auto_pause_m else True
    # exposure
    pos = ps.get("positions", {})
    n_pos = len([p for p in pos.values() if p.get("qty", 0) != 0])
    n_long = len([p for p in pos.values() if p.get("qty", 0) > 0])
    n_short = len([p for p in pos.values() if p.get("qty", 0) < 0])
    return f'''
<section class="card">
  <h2>Risk &middot; drawdown + exposure</h2>
  <div class="grid-3">
    <div class="kpi-card">
      <div class="kpi-label">Current drawdown</div>
      <div class="kpi-value {dd_class}">{drawdown_pct:.1f}%</div>
      <div class="muted small">vs starting Rs.100,000</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Auto-pause threshold</div>
      <div class="kpi-value">{safety_net:.0f}%</div>
      <div class="muted small">catastrophic safety net ({"on" if auto_pause else "off"})</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Open positions</div>
      <div class="kpi-value">{n_pos}</div>
      <div class="muted small">{n_long} long &middot; {n_short} short</div>
    </div>
  </div>
</section>
'''


def section_strategy_performance() -> str:
    """Per-strategy P&L attribution. Shows which strategies are profitable."""
    try:
        from scripts.strategy_library import load_performance, STRATEGIES
    except Exception:
        return ""
    perf = load_performance()
    if not perf:
        return ""
    # Sort by total P&L (best first)
    sorted_perf = sorted(perf.values(), key=lambda x: x.total_pnl, reverse=True)
    rows = []
    for s in sorted_perf:
        status = "DISABLED" if s.is_disabled else "ACTIVE"
        status_class = "muted" if s.is_disabled else "pos" if s.total_pnl > 0 else "neg"
        wr_pct = f"{s.win_rate*100:.0f}%" if s.n_trades else "—"
        avg = s.avg_pnl
        avg_class = "pos" if avg > 0 else "neg" if avg < 0 else "muted"
        strat_def = STRATEGIES.get(s.name)
        edge = strat_def.expected_edge[:60] if strat_def else ""
        rows.append(f'''
<tr>
  <td class="bold">{_esc(s.name)}</td>
  <td><span class="pill pill-{status_class}">{status}</span></td>
  <td class="num">{s.n_trades}</td>
  <td class="num">{wr_pct}</td>
  <td class="num {avg_class} bold">{_fmt_money(s.total_pnl, signed=True)}</td>
  <td class="muted small">{_esc(edge)}</td>
</tr>
''')
    return f'''
<section class="card">
  <h2>Strategy Performance &middot; per-strategy P&amp;L attribution</h2>
  <p class="muted small">Disabled strategies auto-killed when win rate drops below 30% over 10+ trades. Backtested edge shown.</p>
  <table class="dtable">
    <thead>
      <tr><th>Strategy</th><th>Status</th><th>Trades</th><th>Win%</th><th>Total P&amp;L</th><th>Edge</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
'''


def section_brain_decisions(qs) -> str:
    """LLM decision log: last 15 decisions with rationale."""
    decisions = []
    dec_path = DCACHE / "quant_service_decisions.jsonl"
    if dec_path.exists():
        try:
            lines = dec_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line in lines[-30:]:
                try:
                    e = json.loads(line)
                    decisions.append(e)
                except Exception:
                    continue
        except Exception:
            pass
    decisions = decisions[::-1][:15]  # most recent first

    if not decisions:
        return '''
<section class="card">
  <h2>Brain Decisions &middot; LLM action log</h2>
  <p class="muted">No decisions yet. The brain's periodic scan will produce one every 15 min during NSE hours. Each shows the trigger, the LLM's reasoning, and the action taken.</p>
</section>
'''
    rows = []
    for d in decisions:
        ts = d.get("ts", "?")[:19]
        decision = d.get("decision", {})
        dtype = decision.get("type", "?")
        underlying = decision.get("underlying", "")
        strategy = decision.get("strategy", "")
        rationale = (decision.get("rationale") or "")[:200]
        trigger = d.get("context", {}).get("trigger", "")
        conv = decision.get("conviction", 0)
        action = d.get("context", {}).get("action_taken", "")
        type_class = "pos" if dtype == "OPEN" else ("neg" if dtype == "CLOSE" else "muted")
        rows.append(f'''
<tr>
  <td class="muted small">{ts}</td>
  <td class="{type_class} bold">{dtype}</td>
  <td>{_esc(underlying)}</td>
  <td class="muted small">{_esc(strategy)}</td>
  <td class="num">{conv}</td>
  <td class="muted small">{_esc(trigger)}</td>
  <td class="muted small" title="{_esc(rationale)}">{_esc(rationale[:80])}…</td>
</tr>
''')
    return f'''
<section class="card">
  <h2>Brain Decisions &middot; LLM action log (last 15)</h2>
  <table class="dtable">
    <thead>
      <tr><th>Time</th><th>Type</th><th>Underlying</th><th>Strategy</th><th>Conv</th><th>Trigger</th><th>Rationale</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
'''


def section_schedulers(qs) -> str:
    """In-process schedulers: which are wired, when each last fired."""
    # We track these by reading the brain's recent log
    log = _read_lines(DCACHE / "quant_service.log", n=200)
    sched_fired = {}
    for line in log:
        m = re.search(r"SCHED-([A-Z\-]+):\s*(triggering|exit=)", line)
        if m:
            label = m.group(1)
            ts_match = re.match(r"\[([^\]]+)\]", line)
            if ts_match:
                sched_fired[label] = ts_match.group(1)
    rows = []
    schedules = [
        ("MORNING-BRIEF",     "08:15",  "scripts/mavis_premarket.py"),
        ("DAILY-MAINT",       "08:25",  "scripts/daily_maintenance.py"),
        ("NEWS-CACHE",        "09:00",  "scripts/news_cache.py + RSS fetch"),
        ("CLOSING-STRADDLE",  "14:50",  "closing straddle scanner"),
        ("EOD-POSTMORTEM",    "15:35",  "EOD report to Telegram (off)"),
        ("PRE-EOD-CHECK",     "15:25",  "pre-close reconciliation"),
        ("POST-EOD-CHECK",    "17:30",  "post-market review"),
        ("EOD-BACKUP",        "15:45",  "state backup"),
        ("WEEKEND-INTEL",     "Sun 21:00", "weekend intel"),
        ("NIGHTLY-IMPROVEMENT", "23:00",  "self-improvement"),
        ("GLOBAL-CHECK",      "5 min 24/7", "US/Asia/Europe pull"),
        ("OVERNIGHT-RESEARCH", "2h 24/7",  "overnight strategy research"),
        ("GROK-DESK",         "15 min 24/7", "6-role LLM desk"),
        ("RSS-NEWS",          "30 min 24/7", "real RSS news fetch"),
        ("FII-DII",           "1h 24/7", "FII/DII flow fetch"),
        ("PREDICTIVE",        "5 min 24/7", "6 statistical signals"),
    ]
    for label, sched, desc in schedules:
        last_fired = sched_fired.get(label, "—")
        rows.append(f'<tr><td class="bold">{label}</td><td class="muted small">{sched}</td><td class="muted small">{_esc(desc)}</td><td class="muted small">{_esc(last_fired)[:19]}</td></tr>')
    return f'''
<section class="card">
  <h2>In-Process Schedulers &middot; 24/7</h2>
  <table class="dtable">
    <thead><tr><th>Task</th><th>When</th><th>What</th><th>Last fired</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
'''


def section_bot_activity() -> str:
    """Recent bot activity log (last 30 lines)."""
    lines = _read_lines(DCACHE / "bot.log", n=30)
    if not lines:
        lines = _read_lines(ROOT / "Logs" / "bot.log", n=30)
    if not lines:
        return '''
<section class="card">
  <h2>Bot Activity &middot; recent log</h2>
  <p class="muted">No log lines yet.</p>
</section>
'''
    formatted = []
    for line in lines:
        # Keep first 220 chars
        line = line[:220]
        formatted.append(f'<div class="log-line">{_esc(line)}</div>')
    return f'''
<section class="card">
  <h2>Bot Activity &middot; recent log (last 30 lines)</h2>
  <div class="log-stream">{"".join(formatted)}</div>
</section>
'''


def section_ai_overrides() -> str:
    """AI override flags: SKIP_DAY, ai_skip_force_square, max-drawdown."""
    skip_day = _read_json(DCACHE / "_skip_day.json", {})
    skip_force = _read_json(DCACHE / "_ai_skip_force_square.json", {})
    items = []
    if skip_day:
        items.append(f'<div class="override-pill">SKIP_DAY active &middot; {_esc(skip_day.get("reason", "")[:80])} &middot; expires {_esc(skip_day.get("expires_at", "")[:19])}</div>')
    if skip_force:
        items.append(f'<div class="override-pill">FORCE-SQUARE OVERRIDE active &middot; {_esc(skip_force.get("reason", "")[:80])} &middot; expires {_esc(skip_force.get("expires_at", "")[:19])}</div>')
    if not items:
        items.append('<div class="muted small">No AI override flags active. LLM is running with default rules.</div>')
    return f'''
<section class="card">
  <h2>AI Overrides &middot; LLM-initiated flags</h2>
  <div class="override-list">{"".join(items)}</div>
</section>
'''


# ---------- main render ----------

def render_dashboard() -> str:
    """Build the full HTML page."""
    # Load all the state we need
    qs = _read_json(DCACHE / "quant_service_state.json", {})
    lv = _read_json(DCACHE / "liveness.json", {})
    ps = _read_json(DCACHE / "paper_state.json", {})

    # build sections
    header = section_header(lv, ps, qs, lv)
    health = section_system_health()
    market = section_market()
    predictive = section_predictive_signals()
    fii_dii = section_fii_dii()
    news = section_news()
    grok = section_grok_desk()
    overrides = section_ai_overrides()
    open_pos = section_open_positions(ps)
    fills = section_recent_fills()
    risk = section_risk(ps)
    sched = section_schedulers(qs)
    strategy_perf = section_strategy_performance()
    decisions = section_brain_decisions(qs)
    bot_log = section_bot_activity()

    css = '''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kotak Quant Desk</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<meta http-equiv="refresh" content="5">
<style>
  :root {
    --bg: #f5f5f0;
    --card: #ffffff;
    --border: #e0dcd0;
    --border-soft: #ebe8df;
    --text: #14171e;
    --muted: #6b6a62;
    --pos: #10b981;
    --neg: #dc2626;
    --accent: #2563eb;
    --yellow: #b45309;
    --pill: #e0e7ff;
  }
  * { box-sizing: border-box; }
  html, body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; line-height: 1.45; font-size: 14px; }
  body { padding: 16px 24px 32px; max-width: 1480px; margin: 0 auto; }
  h1 { font-size: 22px; font-weight: 700; margin: 0; letter-spacing: -0.01em; }
  h2 { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin: 0 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border-soft); }
  h2::before { content: ""; display: inline-block; width: 4px; height: 4px; border-radius: 50%; background: var(--accent); margin-right: 6px; vertical-align: middle; }
  .header { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px 22px; margin-bottom: 18px; }
  .header-top { display: flex; justify-content: space-between; align-items: flex-start; }
  .header-left .sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .header-right { display: grid; grid-template-columns: repeat(6, auto); gap: 24px; align-items: end; }
  .kpi { text-align: right; min-width: 80px; }
  .kpi-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
  .kpi-value { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .kpi-value.pos { color: var(--pos); }
  .kpi-value.neg { color: var(--neg); }
  .kpi-value.muted { color: var(--muted); }
  .meta-strip { display: flex; flex-wrap: wrap; gap: 12px; font-size: 11px; color: var(--muted); margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-soft); }
  .pill { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
  .pill-green { background: rgba(16,185,129,0.12); color: var(--pos); }
  .pill-red { background: rgba(220,38,38,0.12); color: var(--neg); }
  .pulse { animation: pulse 2.5s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
  .kpi-card { padding: 12px; background: var(--bg); border-radius: 6px; }
  .kpi-card .kpi-label { margin-bottom: 4px; }
  .kpi-card .kpi-value { font-size: 20px; }
  .mkt-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; }
  @media (max-width: 1200px) { .mkt-grid { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 700px)  { .mkt-grid { grid-template-columns: repeat(2, 1fr); } }
  .mkt-card { padding: 10px 12px; background: var(--bg); border-radius: 6px; border: 1px solid var(--border-soft); }
  .mkt-sym { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
  .mkt-ltp { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; margin: 4px 0 2px; }
  .mkt-chg { font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .mkt-meta { margin: 4px 0 2px; }
  .mkt-spark { margin-top: 6px; }
  .vix-line { font-size: 12px; margin-top: 4px; }
  .dtable { width: 100%; border-collapse: collapse; font-size: 12px; }
  .dtable th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); padding: 6px 8px; border-bottom: 1px solid var(--border-soft); font-weight: 600; }
  .dtable td { padding: 7px 8px; border-bottom: 1px solid var(--border-soft); }
  .dtable .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', 'Menlo', monospace; }
  .dtable .bold { font-weight: 700; }
  .dtable .pos { color: var(--pos); }
  .dtable .neg { color: var(--neg); }
  .dtable .muted { color: var(--muted); }
  .dtable tr:last-child td { border-bottom: none; }
  .rollups { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border-soft); }
  .rollup .num { font-size: 16px; font-weight: 700; margin-top: 2px; }
  .health-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
  @media (max-width: 1200px) { .health-grid { grid-template-columns: repeat(3, 1fr); } }
  @media (max-width: 700px)  { .health-grid { grid-template-columns: repeat(2, 1fr); } }
  .health-item { padding: 10px 12px; background: var(--bg); border-radius: 6px; border: 1px solid var(--border-soft); }
  .health-badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
  .health-badge.ok { background: rgba(16,185,129,0.18); color: var(--pos); }
  .health-badge.warn { background: rgba(245,158,11,0.18); color: #f59e0b; }
  .health-badge.err { background: rgba(220,38,38,0.18); color: var(--neg); }
  .health-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text); margin-bottom: 4px; }
  .health-detail { line-height: 1.4; }
  .grok-head { padding: 12px 14px; background: var(--bg); border-radius: 6px; margin-bottom: 12px; font-size: 13px; line-height: 1.5; }
  .grok-head.bold { font-weight: 600; }
  .grok-roles details { margin: 6px 0; }
  .grok-roles summary { cursor: pointer; font-weight: 600; padding: 6px 10px; background: var(--bg); border-radius: 4px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .grok-roles summary:hover { background: #e0dcd0; }
  .grok-roles pre.role-out { background: #fafaf5; padding: 10px; margin: 4px 0 0 0; font-size: 11px; line-height: 1.5; max-height: 200px; overflow-y: auto; white-space: pre-wrap; border: 1px solid var(--border-soft); border-radius: 4px; font-family: 'JetBrains Mono', monospace; }
  .news-list { list-style: none; padding: 0; margin: 0; font-size: 12px; }
  .news-list li { padding: 6px 0; border-bottom: 1px dashed var(--border-soft); display: flex; gap: 10px; align-items: baseline; }
  .news-list li:last-child { border-bottom: none; }
  .news-time { font-family: 'JetBrains Mono', monospace; color: var(--muted); font-size: 11px; min-width: 110px; }
  .news-src { display: inline-block; padding: 1px 6px; background: var(--pill); color: var(--accent); border-radius: 3px; font-size: 10px; font-weight: 600; min-width: 80px; text-align: center; }
  .news-title { flex: 1; }
  .override-list { display: flex; flex-direction: column; gap: 6px; }
  .override-pill { padding: 8px 12px; background: rgba(180,83,9,0.08); border-left: 3px solid var(--yellow); border-radius: 0 4px 4px 0; font-size: 12px; }
  .log-stream { background: #fafaf5; padding: 8px 10px; border-radius: 6px; max-height: 280px; overflow-y: auto; font-family: 'JetBrains Mono', 'Menlo', monospace; font-size: 11px; line-height: 1.5; border: 1px solid var(--border-soft); }
  .log-line { padding: 1px 0; white-space: pre-wrap; word-break: break-all; }
  .muted { color: var(--muted); }
  .small { font-size: 11px; }
  details { font-size: 12px; }
  .footer { margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--border-soft); text-align: center; font-size: 11px; color: var(--muted); }
</style>
<meta http-equiv="refresh" content="5">
'''
    body = f'''
{css}
</head>
<body>
{header}
{overrides}
{health}
{market}
{predictive}
{fii_dii}
{news}
{grok}
{open_pos}
{fills}
{risk}
{strategy_perf}
{decisions}
{sched}
{bot_log}
<div class="footer">
  Kotak Quant Desk &middot; UNLEASHED mode &middot; auto-refresh 5s &middot; dashboard is the single source of truth (Telegram alerts disabled)
</div>
</body>
</html>
'''
    return body


def main() -> int:
    html = render_dashboard()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"[dashboard] wrote {len(html):,} bytes to {OUT}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
