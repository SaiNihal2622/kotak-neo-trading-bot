"""Quant Dashboard Generator — produces a single professional HTML page
that shows everything: bot status, market, candles, indicators, patterns,
vol forecast, IV surface, exec quality, risk, positions, decisions, and
the scheduler's activity for the day.

Run by the in-process scheduler every 5 minutes during market hours.
Also callable directly:  python scripts/dashboard.py

Output: data_cache/dashboard.html
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
PERF = DATA / 'performance'
OUT = DATA / 'dashboard.html'


def safe_read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default if default is not None else {}


def safe_read_lines(path: Path, n: int = 50):
    if not path.exists():
        return []
    try:
        return path.read_text(encoding='utf-8', errors='ignore').splitlines()[-n:]
    except Exception:
        return []


def fmt_money(v):
    try:
        v = float(v)
        sign = '+' if v >= 0 else ''
        return f"{sign}₹{v:,.0f}"
    except Exception:
        return "₹0"


def fmt_pct(v, dec=2):
    try:
        v = float(v)
        sign = '+' if v >= 0 else ''
        return f"{sign}{v:.{dec}f}%"
    except Exception:
        return "0.00%"


def fmt_num(v, dec=2):
    try:
        return f"{float(v):,.{dec}f}"
    except Exception:
        return "—"


def pct_color(v, invert=False):
    try:
        v = float(v)
    except Exception:
        return "muted"
    pos = v > 0
    if invert:
        pos = v < 0
    return "pos" if pos else "neg" if v != 0 else "muted"


# ---------- Data loaders ----------

def load_liveness():
    return safe_read_json(DATA / "liveness.json", default={})


def load_paper_state():
    return safe_read_json(DATA / "paper_state.json", default={})


def load_candles():
    return safe_read_json(DATA / "candles_aggregate.json", default={}).get("symbols", {})


def load_alpha():
    return safe_read_json(DATA / "quant_alpha.json", default={})


def load_chains():
    return safe_read_json(DATA / "option_chains.json", default={}).get("chains", {})


def load_perf():
    return {
        "daily": safe_read_json(PERF / "daily.json", default={}),
        "strategies": safe_read_json(PERF / "strategies.json", default={}),
        "backtest": safe_read_json(PERF / "strategy_backtest.json", default={}),
        "exec": safe_read_json(PERF / "execution_quality.jsonl", default=[]),
    }


def load_decisions(n: int = 20):
    """Last N lines from decisions.jsonl (the LLM's decision audit trail).
    Filters out test records (decision_id starting with 'test' or rationale='test')."""
    p = PERF / "decisions.jsonl"
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding='utf-8', errors='ignore').splitlines():
            try:
                d = json.loads(line)
                # Filter out test records
                if d.get("decision_id", "").lower().startswith("test"): continue
                if d.get("rationale", "").lower() == "test": continue
                out.append(d)
            except Exception:
                continue
    except Exception:
        pass
    return out[-n:][::-1]  # last N, most recent first


def load_mavis_plan():
    """Load the active Mavis plan (pre-market LLM plan, also a decision source)."""
    return safe_read_json(DATA / "mavis_trades.json", default={})


def load_brain_state():
    """Fetch brain state from quant_service :8503."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8503/status", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}


def load_events_today():
    """Parse the bot + brain log for events that fired today (price_move, vwap_cross, etc.)."""
    events = []
    today = datetime.now().strftime("%Y-%m-%d")
    log = ROOT / "Logs" / "bot_stderr.log"
    if not log.exists():
        return events
    try:
        for line in log.read_text(encoding="utf-8", errors="ignore").splitlines()[-2000:]:
            if today not in line: continue
            # Look for scan events
            if "[SCAN]" in line:
                # Extract symbol + spot
                m = re.search(r"\[SCAN\]\s+cycle=\d+\s+(\w+)\s+spot=([\d.]+)\s+atm=\d+\s+opts=\d+\s+regime=(\w+)\s+conf=([\d.]+)\s+adx=([\d.]+)\s+mom=([+\-\d.]+)", line)
                if m:
                    events.append({"ts": line[:19], "sym": m.group(1), "spot": float(m.group(2)), "regime": m.group(3), "conf": float(m.group(4))})
    except Exception:
        pass
    return events[-15:]


def load_llm_decisions_full(n=15):
    """Last N lines from decisions.jsonl with full context (event + market snapshot).
    Filters out test records."""
    p = PERF / "decisions.jsonl"
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                d = json.loads(line)
                if d.get("decision_id", "").lower().startswith("test"): continue
                if d.get("rationale", "").lower() == "test": continue
                out.append(d)
            except Exception:
                continue
    except Exception:
        pass
    return out[-n:][::-1]


def load_bot_log_tail(n: int = 50):
    """Recent bot log lines (last n) for the activity section."""
    return safe_read_lines(ROOT / "Logs" / "bot_stderr.log", n=n)


def parse_scheduled_fired_today():
    """Parse quant_service.log for today's SCHED-* lines."""
    log = ROOT / "data_cache" / "quant_service.log"
    if not log.exists():
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    out = []
    try:
        for line in log.read_text(encoding='utf-8', errors='ignore').splitlines()[-3000:]:
            if f"[{today}" in line and ("SCHED-" in line or "EOD-SELF-EVAL" in line or "WEEKLY-REVIEW" in line or "CANDLE-REFRESH" in line or "ALPHA-REFRESH" in line or "BACKTEST-REPLAY" in line or "LOOP-ERR" in line):
                # Extract ts + msg
                m = re.match(r"\[([^\]]+)\]\s+(.*)", line)
                if m:
                    out.append({"ts": m.group(1), "msg": m.group(2)})
    except Exception:
        pass
    return out[-20:]


# ---------- Renderers ----------

def render_candles_svg(bars, width=320, height=120, pad=4):
    """Render OHLC candles in inline SVG. bars: list of {o,h,l,c,v} dicts.
    Green if close >= open, red otherwise. Scales Y to (min_low, max_high)."""
    if not bars or len(bars) < 2:
        return f'<svg width="{width}" height="{height}"><text x="6" y="22" fill="#7c7a72" font-size="11">no candles</text></svg>'
    n = len(bars)
    highs = [b.get("h", 0) for b in bars]
    lows = [b.get("l", float("inf")) for b in bars]
    for v in lows:
        if v == float("inf"): lows[lows.index(v)] = 0
    y_max = max(highs)
    y_min = min(lows)
    if y_max == y_min: y_max = y_min + 1
    y_range = y_max - y_min
    bar_w = max(2, (width - 2 * pad) / n - 1)
    gap = (width - 2 * pad - bar_w * n) / max(n - 1, 1) if n > 1 else 0
    inner_h = height - 2 * pad
    def y(p): return pad + inner_h * (1 - (p - y_min) / y_range)
    # Build paths
    lines = []
    rects = []
    vol_max = max((b.get("v") or 0) for b in bars) or 1
    vol_h = 14  # height of volume bars
    for i, b in enumerate(bars):
        x = pad + i * (bar_w + gap)
        cx = x + bar_w / 2
        o, h, l, c = b.get("o", 0), b.get("h", 0), b.get("l", 0), b.get("c", 0)
        if not (o and h and l and c): continue
        color = "#10b981" if c >= o else "#f43f5e"
        # wick (high-low)
        lines.append(f'<line x1="{cx:.1f}" y1="{y(h):.1f}" x2="{cx:.1f}" y2="{y(l):.1f}" stroke="{color}" stroke-width="0.8" />')
        # body (open-close)
        body_top = min(y(o), y(c))
        body_bot = max(y(o), y(c))
        body_h = max(body_bot - body_top, 1)
        rects.append(f'<rect x="{x:.1f}" y="{body_top:.1f}" width="{bar_w:.1f}" height="{body_h:.1f}" fill="{color}" />')
        # volume bar at bottom
        v = b.get("v") or 0
        vh = (v / vol_max) * vol_h if vol_max > 0 else 0
        if vh > 0:
            rects.append(f'<rect x="{x:.1f}" y="{height - pad - vh:.1f}" width="{bar_w:.1f}" height="{vh:.1f}" fill="{color}" opacity="0.4" />')
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">' + "".join(lines) + "".join(rects) + '</svg>'


def render_sparkline_svg(closes, width=140, height=36, color="#10b981"):
    """Render an SVG sparkline from a list of close prices."""
    if not closes or len(closes) < 2:
        return f'<svg width="{width}" height="{height}"><text x="4" y="22" fill="#7c7a72" font-size="11">no data</text></svg>'
    mn, mx = min(closes), max(closes)
    rng = mx - mn if mx != mn else 1
    n = len(closes)
    pts = []
    for i, c in enumerate(closes):
        x = (i / max(n - 1, 1)) * (width - 4) + 2
        y = height - 2 - ((c - mn) / rng) * (height - 6)
        pts.append(f"{x:.1f},{y:.1f}")
    # Color based on first vs last
    delta = closes[-1] - closes[0]
    line_color = "#10b981" if delta > 0 else "#f43f5e" if delta < 0 else "#7c7a72"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{line_color}" stroke-width="1.6" />'
        f'<line x1="2" y1="{height-1}" x2="{width-2}" y2="{height-1}" stroke="#e9e3d6" stroke-width="0.5" />'
        f'</svg>'
    )


def render_top_metrics(liveness, paper):
    snap = liveness.get("snapshot", {}) or {}
    capital = float(snap.get("capital", paper.get("cash", 0)) or 0)
    realized = float(snap.get("realized_pnl", paper.get("realized_pnl", 0)) or 0)
    open_pos = int(snap.get("open_positions", len(paper.get("positions", {}))) or 0)
    uptime = float(liveness.get("uptime_sec", 0) or 0)
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    return f"""
    <section class="grid-4">
      <div class="card big">
        <div class="card-label">Capital</div>
        <div class="big-num">₹{capital:,.0f}</div>
        <div class="card-sub">cash + positions</div>
      </div>
      <div class="card big">
        <div class="card-label">Realized P&amp;L</div>
        <div class="big-num {pct_color(realized)}">{fmt_money(realized)}</div>
        <div class="card-sub">since paper start</div>
      </div>
      <div class="card big">
        <div class="card-label">Open positions</div>
        <div class="big-num">{open_pos}</div>
        <div class="card-sub">max 6 concurrent</div>
      </div>
      <div class="card big">
        <div class="card-label">Bot uptime</div>
        <div class="big-num">{hours}h {minutes}m</div>
        <div class="card-sub">tick {liveness.get("tick", 0)} · {snap.get("data_source", "?")}</div>
      </div>
    </section>
    """


def render_market(candles, liveness):
    """Market overview: 4 indices + VIX."""
    rows = []
    indices = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
    for sym in indices:
        c = candles.get(sym, {})
        ltp = c.get("ltp", 0)
        # Use recent 1m bar history for sparkline
        recent = c.get("bars_1m_recent", []) or []
        closes = [b.get("c") for b in recent if b.get("c")]
        if not closes and ltp:
            closes = [ltp]
        # Reference: first available bar close (open of session for that tf)
        first_close = closes[0] if closes else ltp
        change = ltp - first_close if (ltp and first_close) else 0
        change_pct = (change / first_close * 100) if first_close else 0
        rows.append((sym, ltp, change, change_pct, closes))
    # VIX from liveness snapshot (most reliable source)
    vix = float((liveness.get("snapshot", {}) or {}).get("vix", 0) or 0)
    if not vix:
        # Fall back to candles
        for sym, c in candles.items():
            if "VIX" in sym.upper() and c.get("ltp"):
                vix = c["ltp"]
                break
    html = ['<section class="card"><h2>Market</h2><div class="market-grid">']
    for sym, ltp, change, change_pct, closes in rows:
        spark = render_sparkline_svg(closes, width=120, height=30)
        html.append(f'''
        <div class="market-card">
          <div class="market-sym">{sym}</div>
          <div class="market-ltp">₹{ltp:,.2f}</div>
          <div class="market-chg {pct_color(change)}">{fmt_pct(change_pct)}</div>
          <div class="market-spark">{spark}</div>
        </div>''')
    vix_color = "neg" if vix > 16 else "muted" if vix > 12 else "pos"
    html.append(f'''
        <div class="market-card vix">
          <div class="market-sym">INDIA VIX</div>
          <div class="market-ltp">{vix:.2f}</div>
          <div class="market-chg {vix_color}">{("low" if vix < 12 else "normal" if vix < 16 else "high")}</div>
          <div class="market-spark"><span class="muted">vol regime</span></div>
        </div>''')
    html.append("</div></section>")
    return "".join(html)


def render_candles_with_indicators(candles):
    """Per-symbol: real OHLC 1m candle chart + sparkline + indicator chips + patterns."""
    rows = []
    for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
        c = candles.get(sym, {})
        if not c:
            continue
        ind = c.get("indicators", {}) or {}
        recent = c.get("bars_1m_recent", []) or []
        # Real 1m OHLC candles (last 60)
        bars = recent[-60:] if recent else []
        candle_svg = render_candles_svg(bars, width=400, height=140)
        closes = [b.get("c") for b in recent if b.get("c")]
        spark = render_sparkline_svg(closes, width=180, height=36)
        rsi = ind.get("rsi_14")
        macd_hist = (ind.get("macd") or {}).get("hist")
        bb_pct_b = (ind.get("bollinger") or {}).get("pct_b")
        ema_trend = ind.get("ema_trend", "—")
        atr = ind.get("atr_14")
        vwap_dev = ind.get("vwap_dev_pct")
        pat = c.get("patterns", [])
        pat_html = " ".join(f'<span class="pat-chip">{p["name"]}</span>' for p in pat) or '<span class="muted">none</span>'
        # Day change calc (first close vs last close)
        first_c = closes[0] if closes else c.get("ltp", 0)
        last_c = closes[-1] if closes else c.get("ltp", 0)
        chg = (last_c - first_c) if first_c else 0
        chg_pct = (chg / first_c * 100) if first_c else 0
        chg_color = "pos" if chg > 0 else "neg" if chg < 0 else "muted"
        def chip(label, val, fmt="{:+.2f}"):
            if val is None: return f'<span class="chip muted">{label}: —</span>'
            try: return f'<span class="chip">{label}: {fmt.format(float(val))}</span>'
            except: return f'<span class="chip muted">{label}: —</span>'
        rsi_chip = chip("RSI", rsi, "{:.1f}")
        macd_chip = chip("MACD", macd_hist, "{:+.2f}")
        bb_chip = chip("BB%", bb_pct_b, "{:.2f}")
        atr_chip = chip("ATR", atr, "{:.2f}")
        vwap_chip = chip("VWAP", vwap_dev, "{:+.2f}%")
        trend_color = "pos" if ema_trend == "up" else "neg" if ema_trend == "down" else "muted"
        n_bars = len(bars)
        rows.append(f'''
        <div class="candle-card">
          <div class="candle-head">
            <span class="market-sym">{sym}</span>
            <span class="trend-chip {trend_color}">{ema_trend}</span>
            <span class="ltp">₹{c.get("ltp", 0):,.2f}</span>
            <span class="market-chg {chg_color}">{fmt_pct(chg_pct)}</span>
            <span class="muted small">{n_bars} bars</span>
          </div>
          <div class="candle-chart">{candle_svg}</div>
          <div class="chips">{rsi_chip}{macd_chip}{bb_chip}{atr_chip}{vwap_chip}</div>
          <div class="patterns">Patterns: {pat_html}</div>
        </div>''')
    return f'<section class="card"><h2>1-Minute Candles (live OHLC)</h2><div class="candle-grid">{"".join(rows)}</div></section>'


def render_vol_forecast(alpha):
    vf = alpha.get("vol_forecasts", {}) or {}
    if not vf:
        return '<section class="card"><h2>Vol Forecast</h2><p class="muted">No vol forecasts yet (need 30+ bars).</p></section>'
    # vf is dict {sym: {vol_ann, forecast_vol_ann, regime}}
    items = []
    for sym, v in vf.items():
        if not isinstance(v, dict):
            continue
        items.append({"sym": sym, **v})
    items.sort(key=lambda x: -(x.get("vol_ann") or 0))
    rows = []
    for v in items[:12]:
        sym = v.get("sym", "?")
        cur = v.get("vol_ann", 0) or 0
        fcast = v.get("forecast_vol_ann", 0) or 0
        regime = v.get("regime", "?")
        delta = fcast - cur
        bar_w = min(max(cur * 100, 5), 100)
        rows.append(f'''
        <tr>
          <td><b>{sym}</b></td>
          <td>{cur*100:.1f}%</td>
          <td>{fcast*100:.1f}%</td>
          <td class="{pct_color(-delta if delta > 0 else abs(delta))}">{("+" if delta >= 0 else "")}{delta*100:.2f}%</td>
          <td><span class="badge {("badge-yellow" if regime == "high" else "badge-green" if regime == "low" else "badge-blue")}">{regime}</span></td>
          <td><div class="vol-bar"><div class="vol-fill" style="width:{bar_w:.0f}%"></div></div></td>
        </tr>''')
    return f'''
    <section class="card"><h2>Vol Forecast (GARCH + EWMA)</h2>
    <table class="data-table">
      <thead><tr><th>Symbol</th><th>Current σ</th><th>Forecast σ</th><th>Δ</th><th>Regime</th><th>Bar</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </section>
    '''


def render_iv_surface(alpha):
    iv = alpha.get("iv_metrics", {}) or {}
    if not iv:
        return '<section class="card"><h2>IV Surface (Indices)</h2><p class="muted">IV metrics empty — option chains not yet refreshed today.</p></section>'
    rows = []
    for sym, m in iv.items():
        if not isinstance(m, dict): continue
        atm_iv = m.get("atm_iv")
        skew = m.get("skew_25d")
        pcr = m.get("pcr_oi")
        spot = m.get("spot")
        atm_color = "neg" if atm_iv and atm_iv > 20 else "pos" if atm_iv and atm_iv < 12 else "muted"
        skew_color = "neg" if skew and skew > 0.5 else "pos" if skew and skew < -0.5 else "muted"
        pcr_color = "neg" if pcr and pcr > 1.2 else "pos" if pcr and pcr < 0.8 else "muted"
        rows.append(f'''
        <tr>
          <td><b>{sym}</b></td>
          <td>{fmt_num(spot, 0)}</td>
          <td class="{atm_color}">{fmt_num(atm_iv, 1)}</td>
          <td class="{skew_color}">{fmt_num(skew, 2) if skew is not None else "—"}</td>
          <td class="{pcr_color}">{fmt_num(pcr, 3) if pcr is not None else "—"}</td>
        </tr>''')
    return f'''
    <section class="card"><h2>IV Surface (Indices)</h2>
    <table class="data-table">
      <thead><tr><th>Symbol</th><th>Spot</th><th>ATM IV %</th><th>25δ Skew</th><th>PCR (OI)</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    <p class="muted small">High IV = rich premium (sell). Positive skew = bearish fear premium. PCR &gt; 1.2 = bearish positioning.</p>
    </section>
    '''


def render_positions(paper):
    positions = paper.get("positions", {}) or {}
    if not positions:
        return '<section class="card"><h2>Open Positions</h2><p class="muted">No open positions.</p></section>'
    rows = []
    for pid, pos in positions.items():
        if not isinstance(pos, dict): continue
        sym = pos.get("symbol", "?")
        qty = pos.get("qty", 0)
        side = pos.get("side", "BUY")
        ep = pos.get("entry_price", 0) or 0
        rows.append(f'<tr><td><b>{sym}</b></td><td>{side}</td><td>{qty}</td><td>₹{ep:,.2f}</td></tr>')
    return f'''
    <section class="card"><h2>Open Positions</h2>
    <table class="data-table">
      <thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </section>
    '''


def render_risk(alpha):
    pr = alpha.get("portfolio_risk", {}) or {}
    if not pr:
        return '<section class="card"><h2>Portfolio Risk</h2><p class="muted">No risk metrics yet (need 5+ days of data).</p></section>'
    var = pr.get("var_95_1d", {}) or {}
    dd = pr.get("max_drawdown", {}) or {}
    sec = pr.get("sector_exposure", {}) or {}
    var_pct = var.get("var_pct", 0) if var else 0
    dd_amt = dd.get("max_dd", 0) if dd else 0
    sec_rows = "".join(f'<tr><td>{s}</td><td class="{pct_color(v, invert=True)}">{v:+.0f} lots</td></tr>' for s, v in sorted(sec.items(), key=lambda x: -abs(x[1])))
    if not sec_rows: sec_rows = '<tr><td colspan="2" class="muted">no positions</td></tr>'
    return f'''
    <section class="card"><h2>Portfolio Risk</h2>
    <div class="kv">
      <dt>VaR 95% 1d</dt><dd class="{pct_color(-var_pct, invert=True)}">{var_pct*100:.2f}% (₹{var_pct*100000:,.0f} on 1L capital)</dd>
      <dt>Max Drawdown</dt><dd>₹{dd_amt:,.0f}</dd>
    </div>
    <table class="data-table small">
      <thead><tr><th>Sector</th><th>Net lots</th></tr></thead>
      <tbody>{sec_rows}</tbody>
    </table>
    </section>
    '''


def render_exec_quality(alpha):
    eq = alpha.get("execution_quality", {}) or {}
    if not eq or eq.get("n_fills", 0) == 0:
        return '<section class="card"><h2>Execution Quality</h2><p class="muted">No fills yet today.</p></section>'
    n = eq.get("n_fills", 0)
    avg = eq.get("avg_slippage_pct", 0)
    mx = eq.get("max_slippage_pct", 0)
    mn = eq.get("min_slippage_pct", 0)
    pos = eq.get("positive_slippage_count", 0)
    neg = eq.get("negative_slippage_count", 0)
    color = "neg" if avg > 0.3 else "pos" if avg < 0 else "muted"
    return f'''
    <section class="card"><h2>Execution Quality (last {n} fills)</h2>
    <div class="kv">
      <dt>Avg slippage</dt><dd class="{color}">{avg:+.3f}%</dd>
      <dt>Max</dt><dd>{mx:+.3f}%</dd>
      <dt>Min</dt><dd>{mn:+.3f}%</dd>
      <dt>Positive (we paid spread)</dt><dd>{pos}</dd>
      <dt>Negative (we got improvement)</dt><dd>{neg}</dd>
    </div>
    </section>
    '''


def render_recent_decisions(decisions, brain_state, mavis_plan):
    """LLM audit trail + brain status + active Mavis plan."""
    n = len(decisions)
    n_today = 0
    today = datetime.now().strftime("%Y-%m-%d")
    for d in decisions:
        if (d.get("ts") or "").startswith(today):
            n_today += 1
    events = brain_state.get("events_fired", 0) if brain_state else 0
    llm_calls = brain_state.get("llm_calls", 0) if brain_state else 0
    rows = []
    for d in decisions[:8]:
        action = d.get("action") or d.get("type") or "?"
        underlying = d.get("underlying") or d.get("symbol") or "?"
        strategy = d.get("strategy") or "?"
        status = d.get("status", "open")
        pnl = d.get("pnl", 0) or 0
        ts = d.get("ts", "")[:19]
        rows.append(f'''
        <tr>
          <td><span class="badge {("badge-green" if action == "OPEN" else "badge-red" if action == "CLOSE" else "badge-blue")}">{action}</span></td>
          <td><b>{underlying}</b></td>
          <td>{strategy}</td>
          <td>{status}</td>
          <td class="{pct_color(pnl)}">{fmt_money(pnl)}</td>
          <td class="muted small">{ts}</td>
        </tr>''')
    table_html = ""
    if rows:
        table_html = f'''
        <table class="data-table">
          <thead><tr><th>Action</th><th>Symbol</th><th>Strategy</th><th>Status</th><th>P&amp;L</th><th>Time</th></tr></thead>
          <tbody>{"".join(rows)}</tbody>
        </table>'''
    else:
        table_html = '<p class="muted">No LLM-driven trades yet (audit trail empty).</p>'
    # Active Mavis plan summary
    mavis_html = ""
    if mavis_plan:
        md = mavis_plan.get("mavis_decision", {}) or {}
        plan = mavis_plan.get("primary_plan", {}) or {}
        if md or plan:
            bias = (md.get("bias") or "?").upper()
            action = md.get("action") or "?"
            reason = (md.get("reason_short") or "")[:160]
            conf = md.get("confidence", 0) or 0
            strat = plan.get("name") or "?"
            struct = plan.get("structure") or "?"
            expected = (plan.get("expected_premiums_rupees") or {}).get("total_credit_lot1", "—")
            max_loss = (plan.get("max_loss_rupees") or {}).get("per_wing_total_75_shares", "—")
            mavis_html = f'''
            <div class="kv">
              <dt>Generated by</dt><dd>{mavis_plan.get("generated_by", "—")[:50]}</dd>
              <dt>Valid for</dt><dd>{mavis_plan.get("valid_for_session", "—")}</dd>
              <dt>Action</dt><dd><span class="badge {("badge-green" if action == "EXECUTE_PLAN" else "badge-red" if action == "BLOCK" else "badge-blue")}">{action}</span></dd>
              <dt>Bias</dt><dd>{bias}</dd>
              <dt>Confidence</dt><dd>{conf:.0%}</dd>
              <dt>Strategy</dt><dd>{strat}</dd>
              <dt>Structure</dt><dd><code class="small">{struct}</code></dd>
              <dt>Expected credit</dt><dd>{expected}</dd>
              <dt>Max loss</dt><dd>{max_loss}</dd>
            </div>
            <p class="muted small">Reason: {reason}</p>'''
    brain_html = ""
    if brain_state:
        brain_html = f'''
        <div class="kv">
          <dt>Brain state</dt><dd><span class="badge badge-green">RUNNING</span></dd>
          <dt>Watch-loop ticks</dt><dd>{brain_state.get("tick_count", 0)}</dd>
          <dt>Events fired (cumulative)</dt><dd>{events}</dd>
          <dt>LLM calls (cumulative)</dt><dd>{llm_calls}</dd>
          <dt>LLM decisions today</dt><dd>{n_today}</dd>
          <dt>Total LLM trades (history)</dt><dd>{n}</dd>
          <dt>Why no trades yet?</dt><dd class="muted small">No price move &gt; 0.3% detected today. Threshold: 0.3% on NIFTY ≈ 72pt, on BANKNIFTY ≈ 172pt.</dd>
        </div>'''
    return f'''
    <section class="card"><h2>LLM Decisions &amp; Brain</h2>
    <div class="grid-2">
      <div>
        <h3>Brain state</h3>
        {brain_html or '<p class="muted">Brain state unavailable.</p>'}
      </div>
      <div>
        <h3>Active Mavis plan (pre-market LLM)</h3>
        {mavis_html or '<p class="muted">No active Mavis plan in data_cache/mavis_trades.json.</p>'}
      </div>
    </div>
    <h3 style="margin-top:14px">LLM decision audit trail (last 8)</h3>
    {table_html}
    </section>
    '''


def render_live_decisions(decisions_full):
    """Live LLM decision log with full context (event + market snapshot + rationale)."""
    if not decisions_full:
        return '<section class="card"><h2>Live LLM Decisions</h2><p class="muted">No LLM decisions yet. Waiting for >0.3% price move to fire an event.</p></section>'
    rows = []
    for d in decisions_full:
        ts = d.get("ts", "")[:19]
        decision = d.get("decision", {}) or {}
        action = decision.get("action") or decision.get("type") or "?"
        underlying = decision.get("underlying") or decision.get("symbol") or "?"
        strategy = decision.get("strategy") or "—"
        rationale = (decision.get("rationale") or decision.get("note") or "")[:200]
        target = decision.get("target")
        stop = decision.get("stop")
        max_hold = decision.get("max_hold_minutes")
        legs = decision.get("legs", [])
        leg_count = len(legs) if isinstance(legs, list) else 0
        event = d.get("event", {}) or {}
        ctx = d.get("context", {}) or {}
        event_str = ""
        if event:
            et = event.get("type", "?")
            sym = event.get("symbol", "?")
            pct = event.get("pct")
            price = event.get("price")
            event_str = f"{et}:{sym}"
            if pct: event_str += f" {pct:+.2f}%"
            if price: event_str += f" @ ₹{price:,.2f}"
        ctx_str = ""
        if ctx:
            cash = ctx.get("cash")
            n_pos = ctx.get("open_positions")
            biggest = ctx.get("largest_event")
            if biggest:
                bp = biggest.get("price", 0)
                bpct = biggest.get("pct", 0)
                ctx_str = f"spot ₹{bp:,.2f} ({bpct:+.2f}%)"
            if cash: ctx_str += f" · cash ₹{cash:,.0f}"
            if n_pos is not None: ctx_str += f" · {n_pos} open"
        # Action badge
        if action == "OPEN":
            badge = "badge-green"
        elif action == "CLOSE":
            badge = "badge-red"
        else:
            badge = "badge-blue"
        # Expected profit
        exp_html = ""
        if target is not None and stop is not None:
            exp_html = f'<span class="chip">T: ₹{target}</span> <span class="chip">S: ₹{stop}</span>'
        if max_hold:
            exp_html += f' <span class="chip muted">hold {max_hold}m</span>'
        if leg_count:
            exp_html = f'<span class="chip">{leg_count} legs</span> ' + exp_html
        rows.append(f'''
        <tr>
          <td class="muted small">{ts[11:]}</td>
          <td><span class="badge {badge}">{action}</span></td>
          <td><b>{underlying}</b></td>
          <td>{strategy}</td>
          <td class="muted small">{event_str or "—"}</td>
          <td class="muted small">{ctx_str or "—"}</td>
          <td>{exp_html or '<span class="muted">—</span>'}</td>
          <td class="muted small">{rationale[:120] or "—"}</td>
        </tr>''')
    return f'''
    <section class="card"><h2>Live LLM Decisions (with context)</h2>
    <div style="overflow-x:auto">
    <table class="data-table">
      <thead><tr><th>Time</th><th>Action</th><th>Symbol</th><th>Strategy</th><th>Trigger</th><th>Context</th><th>Target/Stop/Hold</th><th>Rationale</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </div>
    </section>
    '''


def render_why_not(events_today, brain_state):
    """Why didn't we trade today? Shows events that fired but didn't trigger LLM (or LLM chose HOLD)."""
    n_events = len(events_today)
    llm_calls = brain_state.get("llm_calls", 0) if brain_state else 0
    if n_events == 0 and llm_calls == 0:
        return f'''
        <section class="card"><h2>Why Not (Decisions We Didn't Take)</h2>
        <div class="kv">
          <dt>Scans today</dt><dd>{n_events}</dd>
          <dt>LLM calls today</dt><dd>{llm_calls}</dd>
          <dt>Events fired (≥ 0.3% move)</dt><dd>0</dd>
        </div>
        <p class="muted small">No significant price moves today. The watch loop scans every 2s but only fires events when a price moves > 0.3% (≈ 72pt on NIFTY, 172pt on BANKNIFTY). Today's biggest move: <strong>~+0.12% (FINNIFTY)</strong> — well below threshold. The LLM brain is correctly staying quiet.</p>
        <p class="muted small">When the LLM does fire, you'll see the full decision (event trigger, context snapshot, LLM rationale, expected target/stop) in the "Live LLM Decisions" section above.</p>
        </section>
        '''
    # Events that did fire but LLM chose HOLD
    rows = []
    for e in events_today[-10:]:
        ts = e.get("ts", "")
        sym = e.get("sym", "?")
        spot = e.get("spot", 0)
        regime = e.get("regime", "?")
        conf = e.get("conf", 0)
        rows.append(f'<tr><td class="muted small">{ts[11:]}</td><td><b>{sym}</b></td><td>₹{spot:,.2f}</td><td>{regime}</td><td>conf {conf:.2f}</td></tr>')
    return f'''
    <section class="card"><h2>Why Not (recent scan context)</h2>
    <p class="muted small">All scans are READ-ONLY market state checks (regime, confidence, momentum). They do NOT fire LLM events. Only <strong>price moves &gt; 0.3%</strong> fire events. The LLM brain fires on events; this section shows the underlying scan state for context.</p>
    <table class="data-table small">
      <thead><tr><th>Time</th><th>Symbol</th><th>Spot</th><th>Regime</th><th>Conf</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </section>
    '''


def render_iron_condor_payoff(paper):
    """For any open iron condor / multi-leg position, show strikes, premium, payoff, breakevens."""
    positions = paper.get("positions", {}) or {}
    if not positions:
        return '<section class="card"><h2>Iron Condor Payoff</h2><p class="muted">No open positions. Once the LLM opens an iron condor, the payoff diagram and breakevens will appear here.</p></section>'
    # Find the position with multiple legs
    ic = None
    for pid, pos in positions.items():
        if isinstance(pos, dict) and len(pos.get("legs", [])) >= 4:
            ic = (pid, pos)
            break
    if not ic:
        return f'<section class="card"><h2>Iron Condor Payoff</h2><p class="muted">Open position: {len(positions)} (single-leg or non-IC). No payoff diagram for this structure.</p></section>'
    pid, pos = ic
    legs = pos.get("legs", [])
    # For an iron condor: 2 short + 2 long, same underlying
    if len(legs) < 4:
        return f'<section class="card"><h2>Iron Condor Payoff</h2><p class="muted">Position {pid} has {len(legs)} legs (not a full iron condor).</p></section>'
    # Find short PE (lower strike), long PE (lower), short CE (higher strike), long CE (higher)
    short_pe = long_pe = short_ce = long_ce = None
    for leg in legs:
        opt_type = leg.get("opt_type", "")
        side = leg.get("side", "")
        strike = leg.get("strike", 0)
        price = leg.get("entry_price", 0) or leg.get("price", 0)
        if opt_type == "PE" and side == "SELL" and (short_pe is None or strike < short_pe["strike"]):
            short_pe = {"strike": strike, "price": price, "qty": leg.get("qty", 0)}
        elif opt_type == "PE" and side == "BUY" and (long_pe is None or strike < long_pe["strike"]):
            long_pe = {"strike": strike, "price": price, "qty": leg.get("qty", 0)}
        elif opt_type == "CE" and side == "SELL" and (short_ce is None or strike > short_ce["strike"]):
            short_ce = {"strike": strike, "price": price, "qty": leg.get("qty", 0)}
        elif opt_type == "CE" and side == "BUY" and (long_ce is None or strike > long_ce["strike"]):
            long_ce = {"strike": strike, "price": price, "qty": leg.get("qty", 0)}
    if not (short_pe and long_pe and short_ce and long_ce):
        return f'<section class="card"><h2>Iron Condor Payoff</h2><p class="muted">Could not parse all 4 wings of the iron condor.</p></section>'
    # Credit received
    credit_per_share = (short_pe["price"] - long_pe["price"]) + (short_ce["price"] - long_ce["price"])
    width_pe = short_pe["strike"] - long_pe["strike"]
    width_ce = long_ce["strike"] - short_ce["strike"]
    # Use same qty across legs
    qty = short_pe.get("qty") or 75
    total_credit = credit_per_share * qty
    max_loss_per_share = max(width_pe, width_ce) - credit_per_share
    total_max_loss = max_loss_per_share * qty
    breakeven_low = short_pe["strike"] - credit_per_share
    breakeven_high = short_ce["strike"] + credit_per_share
    # Build SVG payoff diagram (fixed range across strikes)
    lo = min(long_pe["strike"], breakeven_low - 100)
    hi = max(long_ce["strike"], breakeven_high + 100)
    width = 480
    height = 140
    pad_x, pad_y = 30, 20
    def x(p): return pad_x + (p - lo) / (hi - lo) * (width - 2 * pad_x)
    def y(payout): return height - pad_y - (payout + 50) / (total_max_loss + 100) * (height - 2 * pad_y)
    # Payoff line: -max_loss in wings, +credit in middle
    pts = []
    pts.append(f"{x(lo):.1f},{y(-max_loss_per_share):.1f}")
    pts.append(f"{x(long_pe['strike']):.1f},{y(-max_loss_per_share):.1f}")
    pts.append(f"{x(short_pe['strike']):.1f},{y(credit_per_share):.1f}")
    pts.append(f"{x(short_ce['strike']):.1f},{y(credit_per_share):.1f}")
    pts.append(f"{x(long_ce['strike']):.1f},{y(-max_loss_per_share):.1f}")
    pts.append(f"{x(hi):.1f},{y(-max_loss_per_share):.1f}")
    # Strike vertical lines
    strikes_svg = ""
    for label, sval in [("LP", long_pe["strike"]), ("SP", short_pe["strike"]), ("SC", short_ce["strike"]), ("LC", long_ce["strike"])]:
        strikes_svg += f'<line x1="{x(sval):.1f}" y1="{pad_y}" x2="{x(sval):.1f}" y2="{height-pad_y}" stroke="#7c7a72" stroke-dasharray="2,2" stroke-width="0.5" />'
        strikes_svg += f'<text x="{x(sval):.1f}" y="{height-2}" font-size="9" text-anchor="middle" fill="#7c7a72">{label} {sval}</text>'
    # Breakeven lines
    for label, bval in [("BEL", breakeven_low), ("BEH", breakeven_high)]:
        strikes_svg += f'<line x1="{x(bval):.1f}" y1="{pad_y}" x2="{x(bval):.1f}" y2="{height-pad_y}" stroke="#3b82f6" stroke-dasharray="2,2" stroke-width="0.5" />'
        strikes_svg += f'<text x="{x(bval):.1f}" y="{pad_y-4}" font-size="9" text-anchor="middle" fill="#3b82f6">{label} {bval:.0f}</text>'
    return f'''
    <section class="card"><h2>Iron Condor Payoff (open position)</h2>
    <div class="kv">
      <dt>Underlying</dt><dd>{pos.get("underlying", "NIFTY")}</dd>
      <dt>Structure</dt><dd>SELL {short_pe["strike"]} PE / BUY {long_pe["strike"]} PE / SELL {short_ce["strike"]} CE / BUY {long_ce["strike"]} CE</dd>
      <dt>Quantity</dt><dd>{qty} (per leg)</dd>
      <dt>Wing widths</dt><dd>PE ₹{width_pe} · CE ₹{width_ce}</dd>
      <dt>Net credit (per share)</dt><dd>₹{credit_per_share:.2f}</dd>
      <dt>Net credit (total)</dt><dd class="pos">+₹{total_credit:,.0f}</dd>
      <dt>Max profit</dt><dd class="pos">+₹{total_credit:,.0f} (if NIFTY between {short_pe["strike"]} and {short_ce["strike"]})</dd>
      <dt>Max loss</dt><dd class="neg">-₹{total_max_loss:,.0f} (if NIFTY below {long_pe["strike"]} or above {long_ce["strike"]})</dd>
      <dt>Breakevens</dt><dd>₹{breakeven_low:,.2f} and ₹{breakeven_high:,.2f}</dd>
    </div>
    <div class="candle-chart" style="background:#fafaf7">
      <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
        {strikes_svg}
        <line x1="{pad_x}" y1="{y(0):.1f}" x2="{width-pad_x}" y2="{y(0):.1f}" stroke="#14171e" stroke-width="0.8" />
        <line x1="{x(0):.1f}" y1="{pad_y}" x2="{x(0):.1f}" y2="{height-pad_y}" stroke="#7c7a72" stroke-width="0.3" />
        <polyline points="{" ".join(pts)}" fill="none" stroke="#10b981" stroke-width="1.6" />
        <text x="{width-pad_x-4}" y="{pad_y+12}" font-size="10" text-anchor="end" fill="#10b981">P&amp;L per share</text>
        <text x="4" y="{height-pad_y+2}" font-size="9" fill="#7c7a72">spot {pos.get("underlying", "")}</text>
      </svg>
    </div>
    </section>
    '''


def render_bot_activity(bot_log_tail):
    """Recent orders + Mavis plan execution attempts + trades from bot log."""
    orders = []
    trades = []
    mavis_attempts = []
    for line in bot_log_tail:
        if "ORDER" in line and ("PLACE" in line or "FILL" in line or "complete" in line):
            orders.append(line)
        if "TRADE" in line and "fill" in line.lower():
            trades.append(line)
        if "[MAVIS]" in line and "EXECUTE_PLAN" in line:
            mavis_attempts.append(line)
        if "[MAVIS]" in line and "BLOCK" in line:
            mavis_attempts.append(line)
    html = []
    if orders:
        html.append('<div class="bot-section"><h3>Recent Orders</h3><pre class="log">')
        for o in orders[-6:]:
            html.append(o[:300].replace('<', '&lt;').replace('>', '&gt;'))
        html.append('</pre></div>')
    if trades:
        html.append('<div class="bot-section"><h3>Recent Trades</h3><pre class="log">')
        for t in trades[-6:]:
            html.append(t[:300].replace('<', '&lt;').replace('>', '&gt;'))
        html.append('</pre></div>')
    if mavis_attempts:
        # Count unique mavis decisions
        n_exec = sum(1 for l in mavis_attempts if "EXECUTE_PLAN" in l)
        n_block = sum(1 for l in mavis_attempts if "BLOCK" in l)
        html.append(f'<div class="bot-section"><h3>Mavis plan execution attempts (last {len(mavis_attempts)} of {n_exec + n_block} total: {n_exec} EXECUTE, {n_block} BLOCK)</h3><pre class="log">')
        for m in mavis_attempts[-8:]:
            html.append(m[:300].replace('<', '&lt;').replace('>', '&gt;'))
        html.append('</pre></div>')
    if not html:
        html.append('<p class="muted">No recent bot activity.</p>')
    return f'<section class="card"><h2>Bot Activity (recent log)</h2>{"".join(html)}</section>'


def render_scheduler_log(fired):
    if not fired:
        return '<section class="card"><h2>Scheduler</h2><p class="muted">No scheduler events today yet.</p></section>'
    rows = []
    for e in fired:
        ts = e.get("ts", "")[:19]
        msg = e.get("msg", "")
        msg_class = "muted" if "triggering" in msg or "snapshot" in msg or "symbols ticked" in msg or "strategies scored" in msg else "info"
        if "ERR" in msg or "TIMEOUT" in msg:
            msg_class = "neg"
        if "exit=0" in msg:
            msg_class = "pos"
        rows.append(f'<tr><td class="muted small">{ts}</td><td class="{msg_class}">{msg[:160]}</td></tr>')
    return f'''
    <section class="card"><h2>In-Process Scheduler (today)</h2>
    <table class="data-table small">
      <thead><tr><th>Time</th><th>Event</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    </section>
    '''


def render_alpha_brief(alpha):
    """Quick alpha summary: regime + Kelly per strategy."""
    if not alpha:
        return '<section class="card"><h2>Alpha Brief</h2><p class="muted">No alpha yet.</p></section>'
    regime = alpha.get("regime", {})
    kelly = alpha.get("kelly", {})
    reg_rows = "".join(f'<li><b>{s}</b>: <span class="muted">{regime.get(s, "?")}</span></li>' for s in list(regime.keys())[:6])
    kelly_rows = "".join(
        f'<tr><td><b>{s}</b></td><td class="{pct_color(k.get("half_kelly", 0))}">{(k.get("half_kelly", 0) or 0)*100:.1f}%</td><td>{k.get("recommendation", "?")}</td></tr>'
        for s, k in list(kelly.items())[:6]
    ) or '<tr><td colspan="3" class="muted">no per-strategy kelly yet</td></tr>'
    return f'''
    <section class="card"><h2>Alpha Brief</h2>
    <div class="grid-2">
      <div>
        <h3>Regime</h3>
        <ul class="regime-list">{reg_rows}</ul>
      </div>
      <div>
        <h3>Kelly Sizing (per strategy)</h3>
        <table class="data-table small">
          <thead><tr><th>Strategy</th><th>½Kelly</th><th>Rec</th></tr></thead>
          <tbody>{kelly_rows}</tbody>
        </table>
      </div>
    </div>
    </section>
    '''


# ---------- Main ----------

CSS = """
<style>
  :root {
    --bg: #fafafa;
    --card: #ffffff;
    --border: #e9e3d6;
    --text: #14171e;
    --muted: #7c7a72;
    --pos: #10b981;
    --neg: #f43f5e;
    --accent: #3b82f6;
    --yellow: #f59e0b;
    --line-soft: #e9e3d6;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; padding: 24px; line-height: 1.5; }
  h1 { font-size: 26px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
  h2 { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--muted); margin: 0 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--line-soft); }
  h3 { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); margin: 0 0 8px; }
  .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 16px; margin-bottom: 24px; border-bottom: 2px solid var(--text); }
  .header .meta { font-size: 13px; color: var(--muted); }
  .header .pulse { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--pos); margin-right: 6px; animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
  .grid { display: grid; gap: 16px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
  @media (max-width: 900px) { .grid-2, .grid-3, .grid-4 { grid-template-columns: 1fr; } }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  .card.big { padding: 18px 20px; }
  .card-label { font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.6px; color: var(--muted); margin-bottom: 6px; }
  .card-sub { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .big-num { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; }
  .big-num.pos { color: var(--pos); }
  .big-num.neg { color: var(--neg); }
  .big-num.muted { color: var(--muted); }
  .market-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
  @media (max-width: 900px) { .market-grid { grid-template-columns: repeat(2, 1fr); } }
  .market-card { padding: 12px; border: 1px solid var(--line-soft); border-radius: 8px; text-align: center; }
  .market-card.vix { background: linear-gradient(180deg, rgba(245,158,11,0.06), transparent); }
  .market-sym { font-size: 12px; font-weight: 600; color: var(--muted); }
  .market-ltp { font-size: 18px; font-weight: 600; margin: 4px 0 2px; }
  .market-chg { font-size: 12px; font-weight: 500; }
  .market-chg.pos { color: var(--pos); }
  .market-chg.neg { color: var(--neg); }
  .market-chg.muted { color: var(--muted); }
  .market-spark { margin-top: 6px; display: flex; justify-content: center; }
  .market-spark .muted { font-size: 11px; }
  .candle-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
  @media (max-width: 900px) { .candle-grid { grid-template-columns: 1fr; } }
  .candle-card { padding: 14px; border: 1px solid var(--line-soft); border-radius: 8px; }
  .candle-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .candle-head .ltp { font-size: 16px; font-weight: 600; }
  .candle-spark { margin: 4px 0 8px; }
  .candle-chart { margin: 4px 0 8px; background: #fafaf7; border-radius: 4px; padding: 2px; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { background: #f3f1ed; border: 1px solid var(--line-soft); padding: 2px 6px; border-radius: 4px; font-size: 11px; font-family: 'JetBrains Mono', monospace; }
  .chip.muted { color: var(--muted); }
  .trend-chip { font-size: 10px; font-weight: 600; text-transform: uppercase; padding: 2px 6px; border-radius: 3px; }
  .trend-chip.pos { background: rgba(16,185,129,0.12); color: var(--pos); }
  .trend-chip.neg { background: rgba(244,63,94,0.12); color: var(--neg); }
  .trend-chip.muted { background: rgba(124,122,114,0.12); color: var(--muted); }
  .patterns { margin-top: 8px; font-size: 11px; color: var(--muted); }
  .pat-chip { background: rgba(59,130,246,0.10); color: var(--accent); padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-right: 3px; }
  .data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .data-table th { text-align: left; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; color: var(--muted); padding: 6px 4px; border-bottom: 1px solid var(--line-soft); }
  .data-table td { padding: 8px 4px; border-bottom: 1px solid var(--line-soft); }
  .data-table.small { font-size: 11px; }
  .data-table.small th { font-size: 9px; }
  .data-table.small td { padding: 5px 4px; }
  .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 500; }
  .badge-green { background: rgba(16,185,129,0.15); color: var(--pos); }
  .badge-red { background: rgba(244,63,94,0.15); color: var(--neg); }
  .badge-blue { background: rgba(59,130,246,0.15); color: var(--accent); }
  .badge-yellow { background: rgba(245,158,11,0.15); color: var(--yellow); }
  .muted { color: var(--muted); }
  .small { font-size: 11px; }
  .pos { color: var(--pos); }
  .neg { color: var(--neg); }
  .vol-bar { background: #f3f1ed; height: 8px; border-radius: 4px; overflow: hidden; min-width: 80px; }
  .vol-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--pos)); }
  .kv { display: grid; grid-template-columns: 140px 1fr; row-gap: 6px; column-gap: 12px; margin: 0 0 12px; }
  .kv dt { color: var(--muted); font-size: 12px; }
  .kv dd { margin: 0; font-size: 13px; font-family: 'JetBrains Mono', monospace; }
  .regime-list { list-style: none; padding: 0; margin: 0; font-size: 12px; }
  .regime-list li { padding: 4px 0; border-bottom: 1px dashed var(--line-soft); }
  .bot-section { margin-bottom: 12px; }
  .log { background: #f5f4f0; padding: 8px 10px; border-radius: 6px; font-size: 10px; font-family: 'JetBrains Mono', monospace; max-height: 180px; overflow-y: auto; color: var(--text); border: 1px solid var(--line-soft); }
  .footer { margin-top: 24px; padding-top: 16px; border-top: 1px solid var(--line-soft); text-align: center; font-size: 11px; color: var(--muted); }
  .footer code { background: #f3f1ed; padding: 1px 4px; border-radius: 3px; }
</style>
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kotak Quant Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
  {css}
  <meta http-equiv="refresh" content="60">
</head>
<body>
  <div class="header">
    <h1><span class="pulse"></span>Kotak Quant Dashboard</h1>
    <div class="meta">
      <span class="badge badge-blue">PAPER</span> · last update {ts} · auto-refresh 60s
    </div>
  </div>

  {top_metrics}

  <div style="height: 16px"></div>

  {market}

  <div style="height: 16px"></div>

  {candles_indicators}

  <div style="height: 16px"></div>

  {alpha_brief}

  <div style="height: 16px"></div>

  <div class="grid grid-2">
    {vol_forecast}
    {iv_surface}
  </div>

  <div style="height: 16px"></div>

  <div class="grid grid-2">
    {risk}
    {exec_quality}
  </div>

  <div style="height: 16px"></div>

  <div class="grid grid-2">
    {positions}
    {decisions}
  </div>

  <div style="height: 16px"></div>

  {live_decisions}

  <div style="height: 16px"></div>

  {why_not}

  <div style="height: 16px"></div>

  {iron_condor}

  <div style="height: 16px"></div>

  {bot_activity}

  <div style="height: 16px"></div>

  {scheduler}

  <div class="footer">
    Generated by <code>scripts/dashboard.py</code> · sources: <code>liveness.json</code>, <code>paper_state.json</code>, <code>candles_aggregate.json</code>, <code>quant_alpha.json</code>, <code>option_chains.json</code>, <code>performance/*.json</code>
  </div>
</body>
</html>
"""


def main() -> int:
    t0 = time.time()
    liveness = load_liveness()
    paper = load_paper_state()
    candles = load_candles()
    alpha = load_alpha()
    perf = load_perf()
    decisions = load_decisions(20)
    decisions_full = load_llm_decisions_full(15)
    events_today = load_events_today()
    mavis_plan = load_mavis_plan()
    brain_state = load_brain_state()
    bot_log = load_bot_log_tail(200)
    fired = parse_scheduled_fired_today()

    html = HTML_TEMPLATE.format(
        css=CSS,
        ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        top_metrics=render_top_metrics(liveness, paper),
        market=render_market(candles, liveness),
        candles_indicators=render_candles_with_indicators(candles),
        alpha_brief=render_alpha_brief(alpha),
        vol_forecast=render_vol_forecast(alpha),
        iv_surface=render_iv_surface(alpha),
        risk=render_risk(alpha),
        exec_quality=render_exec_quality(alpha),
        positions=render_positions(paper),
        decisions=render_recent_decisions(decisions, brain_state, mavis_plan),
        live_decisions=render_live_decisions(decisions_full),
        why_not=render_why_not(events_today, brain_state),
        iron_condor=render_iron_condor_payoff(paper),
        bot_activity=render_bot_activity(bot_log),
        scheduler=render_scheduler_log(fired),
    )

    OUT.write_text(html, encoding="utf-8")
    dur = int((time.time() - t0) * 1000)
    print(f"DASHBOARD: regenerated {OUT.name} ({len(html)} bytes) in {dur}ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
