#!/usr/bin/env python3
"""
Kotak Neo Bot — Live Unified Dashboard
Single-screen, real-time, comprehensive view of:
- Bot health (PID, uptime, ticks, errors)
- Market data (NIFTY/BANKNIFTY spots, VIX, regime)
- Account state (cash, realized P&L, total)
- Open positions (per-leg LTP, P&L, days-to-expiry)
- Today's trades (chronological, all 4 legs per strategy)
- Last brain decision (bias, source, rationale)
- Risk metrics (position cap, max risk, regime)
- 0DTE countdown (time to force-square, time to expiry)
- Cron status (next runs for kotak-* jobs)
- Bot log tail (last 10 INFO/ERROR lines)
- Process tree (visible procs related to kotak-neo-bot)

Runs on :8504. Auto-refreshes every 1s. Single file, no deps beyond stdlib.
"""
import json
import os
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen, Request
from urllib.error import URLError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DCACHE = os.path.join(ROOT, "data_cache")
LOGS = os.path.join(ROOT, "logs")
PORT = 8504
IST = timezone(timedelta(hours=5, minutes=30))

# ---- data collectors --------------------------------------------------------

def _read_json(path, default=None):
    try:
        # utf-8-sig handles BOM automatically; falls back to utf-8 if no BOM
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


# ---- TTL cache (singleton) -------------------------------------------------
_TTL = {"bot": 1.5, "procs": 3.0, "log": 1.0, "th_secs": 2.0}
_cache = {}


def _cached(key, fn, ttl):
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def bot_status_8502():
    def _fetch():
        try:
            with urlopen("http://localhost:8502/status", timeout=2) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            return {"error": str(e), "_fetch_failed": True}
    return _cached("bot", _fetch, _TTL["bot"])


def market_thesis():
    """Read thesis/latest.json for spot, regime, expected range, etc."""
    def _fetch():
        j = _read_json(os.path.join(DCACHE, "thesis", "latest.json"), {})
        if not j:
            return {"available": False}
        xmkt = (j.get("data") or {}).get("xmkt") or {}
        return {
            "available": True,
            "regime": j.get("regime"),
            "bias": j.get("bias"),
            "confidence": j.get("confidence"),
            "risk_budget_pct": j.get("risk_budget_pct"),
            "max_positions": j.get("max_positions"),
            "expected_range": j.get("expected_range") or [],
            "preferred_strategies": j.get("preferred_strategies") or [],
            "narrative": j.get("narrative"),
            "ist_time": j.get("ist_time"),
            "nifty_spot": xmkt.get("nifty_spot"),
            "banknifty_spot": xmkt.get("banknifty_spot"),
            "india_vix": xmkt.get("india_vix"),
            "crude_oil": xmkt.get("crude_oil"),
            "usdinr": xmkt.get("usdinr"),
            "dxy": xmkt.get("dxy"),
            "dow_spot": xmkt.get("dow_spot"),
            "global_cues": xmkt.get("global_cues"),
            "macro_next_event": ((j.get("data") or {}).get("macro") or {}).get("next_event"),
        }
    return _cached("thesis", _fetch, _TTL["th_secs"])


def paper_state():
    j = _read_json(os.path.join(DCACHE, "paper_state.json"), {})
    orders = j.get("orders", {}) if isinstance(j.get("orders"), dict) else {}
    positions = j.get("positions", {}) if isinstance(j.get("positions"), dict) else {}
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    today_fills = []
    for oid, o in orders.items():
        fa = o.get("filled_at", "")
        if fa and fa.startswith(today_ist):
            today_fills.append({
                "order_id": oid,
                "symbol": o.get("symbol", ""),
                "side": o.get("side", ""),
                "qty": o.get("filled_qty", 0),
                "price": o.get("avg_fill_price", 0.0),
                "tag": o.get("tag", ""),
                "filled_at": fa,
                "underlying": o.get("underlying", ""),
                "strike": o.get("strike", 0),
                "option_type": o.get("option_type", ""),
            })
    today_fills.sort(key=lambda x: x["filled_at"])
    pos_list = []
    for sym, p in positions.items():
        pnl = p.get("pnl", 0) or 0
        qty = p.get("qty", 0) or 0
        avg = p.get("avg_price", 0) or 0
        ltp = p.get("ltp", 0) or 0
        expiry = p.get("expiry", "")
        pos_list.append({
            "symbol": sym, "qty": qty, "avg": avg, "ltp": ltp,
            "pnl": pnl, "expiry": expiry, "underlying": p.get("underlying", ""),
            "exchange": p.get("exchange", ""),
        })
    return {
        "available": True,
        "cash": j.get("cash", 0),
        "starting_capital": j.get("starting_capital", 0) or j.get("_reset_starting_capital", 100000),
        "realized_pnl": j.get("realized_pnl", 0),
        "unrealized_pnl": sum(max(0, p.get("pnl") or 0) for p in positions.values()) if isinstance(positions, dict) else 0,
        "open_positions_count": len(positions),
        "open_orders_count": len(orders),
        "today_fills": today_fills,
        "today_fills_count": len(today_fills),
        "positions": pos_list,
        "reset_history": j.get("_reset_history", []),
        "ts": datetime.now(IST).isoformat(),
    }


def brain_state():
    ba = _read_json(os.path.join(DCACHE, "brain_actions.json"), {})
    bs = _read_json(os.path.join(DCACHE, "brain_state.json"), {})
    return {
        "available": bool(ba or bs),
        "last_action": ba,
        "last_decision": bs.get("last_decision") if isinstance(bs, dict) else None,
        "brain_state_present": bool(bs),
    }


def thesis_state():
    tl = _read_json(os.path.join(DCACHE, "thesis", "latest.json"), {})
    return {"available": bool(tl), "thesis": tl}


def process_tree():
    def _fetch():
        try:
            out = os.popen(
                'powershell -NoProfile -NonInteractive -Command "Get-CimInstance Win32_Process '
                '| Where-Object { $_.Name -in @(\'python.exe\',\'powershell.exe\',\'streamlit.exe\') } '
                '| Select-Object Name, ProcessId, SessionId, CreationDate, @{N=\'uptime_min\';E={[math]::Round(((Get-Date)-$_.CreationDate).TotalMinutes,1)}}, '
                '@{N=\'cmd\';E={if ($_.CommandLine) { $_.CommandLine.Substring(0, [Math]::Min(100, $_.CommandLine.Length)) } else { \'<HIDDEN>\' }}} '
                '| ConvertTo-Json -Depth 3"'
            ).read()
            procs = json.loads(out) if out.strip().startswith("[") else [json.loads(out)] if out.strip() else []
        except Exception as e:
            return {"available": False, "error": str(e), "kotak_procs": [], "other_procs_count": 0}

        kotak_procs = []
        other_procs = []
        for p in procs:
            rec = {
                "pid": p.get("ProcessId"),
                "name": p.get("Name"),
                "session": p.get("SessionId"),
                "uptime_min": p.get("uptime_min", 0),
                "cmd": p.get("cmd", ""),
            }
            cmd_l = (rec["cmd"] or "").lower()
            if "kotak" in cmd_l or "streamlit" in cmd_l or ("8501" in cmd_l or "8502" in cmd_l or "8504" in cmd_l):
                kotak_procs.append(rec)
            else:
                other_procs.append(rec)
        return {
            "available": True,
            "ts": datetime.now(IST).isoformat(),
            "kotak_procs": kotak_procs[:30],
            "other_procs_count": len(other_procs),
        }
    return _cached("procs", _fetch, _TTL["procs"])


def log_tail(n=10):
    def _fetch():
        p = os.path.join(LOGS, "bot.log")
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-n:]
            return [l.rstrip() for l in lines]
        except Exception as e:
            return [f"<log read error: {e}>"]
    return _cached("log", _fetch, _TTL["log"])


def crons():
    """Read pre-generated crons snapshot (refreshed periodically by user/Mavis)."""
    p = os.path.join(DCACHE, "crons.json")
    data = _read_json(p, {})
    if isinstance(data, list):
        jobs = data
    else:
        jobs = data.get("jobs", [])
    return {"available": bool(jobs), "jobs": jobs, "source": "data_cache/crons.json"}


def market_snapshot():
    """Pull from bot's /status — VIX, data_source, plus scan latest from logs."""
    s = bot_status_8502()
    snap = s.get("liveness", {}).get("snapshot", {})
    return {
        "vix": snap.get("vix"),
        "data_source": snap.get("data_source", "?"),
        "risk_preset": snap.get("risk_preset"),
        "is_paused": snap.get("is_paused", False),
    }


def compute_countdowns():
    now = datetime.now(IST)
    today_915 = now.replace(hour=9, minute=15, second=0, microsecond=0)
    today_1530 = now.replace(hour=15, minute=30, second=0, microsecond=0)
    today_1415 = now.replace(hour=14, minute=15, second=0, microsecond=0)
    today_1515 = now.replace(hour=15, minute=15, second=0, microsecond=0)

    def fmt(dt):
        if dt < now:
            return {"label": "passed", "secs": 0, "target_ist": dt.strftime("%H:%M")}
        secs = int((dt - now).total_seconds())
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return {"label": f"{h}h {m:02d}m {s:02d}s", "secs": secs, "target_ist": dt.strftime("%H:%M")}

    return {
        "now_ist": now.strftime("%H:%M:%S"),
        "now_date": now.strftime("%Y-%m-%d"),
        "force_square_soft_1415": fmt(today_1415),
        "force_square_hard_1515": fmt(today_1515),
        "market_close_1530": fmt(today_1530),
        "market_open_0915": fmt(today_915) if now < today_915 else {"label": "passed", "secs": 0, "target_ist": "09:15"},
    }


def get_live_option_ltps(symbols):
    """FIX 2026-08-26 (item #6): try to get LIVE option LTPs from yfinance for our position symbols.
    Returns dict: {symbol: ltp}. Empty dict if yfinance doesn't have data.
    Cached for 5s.
    """
    if not symbols:
        return {}
    return _cached("live_ltps", lambda: _fetch_live_option_ltps(symbols), 5.0)


def _fetch_live_option_ltps(symbols):
    """Worker: fetch live LTPs for our 8 specific option symbols."""
    if not symbols:
        return {}
    out = {}
    try:
        import yfinance as yf
        # yfinance option chains: ^NSEI, ^NSEBANK
        for und_symbol in ["^NSEI", "^NSEBANK"]:
            try:
                t = yf.Ticker(und_symbol)
                exps = list(t.options or [])
                if not exps:
                    continue
                # Find closest expiry
                closest = exps[0]
                oc = t.option_chain(closest)
                for df in [oc.calls, oc.puts]:
                    for _, row in df.iterrows():
                        # yfinance contractSymbol like "NIFTY26AUG2624450CE"
                        contract = str(row.get("contractSymbol", ""))
                        if contract in symbols:
                            ltp = float(row.get("lastPrice", 0) or 0)
                            if ltp > 0:
                                out[contract] = ltp
            except Exception:
                pass
    except Exception:
        pass
    return out


def aggregate_state():
    # Parallelize: each source already cached, but launch in threads to overlap
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        f_bot = ex.submit(bot_status_8502)
        f_ps = ex.submit(paper_state)
        f_bs = ex.submit(brain_state)
        f_th = ex.submit(thesis_state)
        f_pt = ex.submit(process_tree)
        f_lt = ex.submit(log_tail, 10)
        f_cr = ex.submit(crons)
        f_mk = ex.submit(market_snapshot)
        f_mt = ex.submit(market_thesis)
        f_cd = ex.submit(compute_countdowns)
        s8502 = f_bot.result()
        ps = f_ps.result()
        bs = f_bs.result()
        th = f_th.result()
        pt = f_pt.result()
        lt = f_lt.result()
        cr = f_cr.result()
        mk = f_mk.result()
        mt = f_mt.result()
        cd = f_cd.result()

    snap = s8502.get("liveness", {}).get("snapshot", {})
    uptime_sec = s8502.get("liveness", {}).get("uptime_sec", 0)
    bot_pid = s8502.get("liveness", {}).get("pid")

    return {
        "ts": datetime.now(IST).isoformat(),
        "bot": {
            "alive": s8502.get("liveness", {}).get("available", False),
            "state": snap.get("phase", "?"),
            "pid": bot_pid,
            "uptime_sec": uptime_sec,
            "tick": s8502.get("liveness", {}).get("tick"),
            "last_liveness_age_sec": s8502.get("liveness", {}).get("age_sec"),
            "main_thread_alive": s8502.get("liveness", {}).get("main_thread_alive"),
            "data_source": snap.get("data_source"),
            "vix": snap.get("vix"),
            "trades_today": snap.get("trades_today"),
            "open_positions": snap.get("open_positions"),
            "is_paused": snap.get("is_paused"),
            "risk_preset": snap.get("risk_preset"),
        },
        "market": mk,
        "market_thesis": mt,
        "countdowns": cd,
        "account": {
            "cash": ps.get("cash", 0),
            "starting_capital": ps.get("starting_capital", 100000),
            "realized_pnl": ps.get("realized_pnl", 0),
            "unrealized_pnl": ps.get("unrealized_pnl", 0),
            "total_value": (ps.get("cash", 0) or 0) + (ps.get("unrealized_pnl", 0) or 0),
            "today_pnl_pct": ((ps.get("cash", 0) - ps.get("starting_capital", 100000)) / ps.get("starting_capital", 100000) * 100) if ps.get("starting_capital") else 0,
        },
        "positions": ps.get("positions", []),
        "open_orders_count": ps.get("open_orders_count", 0),
        "today_fills": ps.get("today_fills", []),
        "today_fills_count": ps.get("today_fills_count", 0),
        "brain": bs,
        "thesis": th,
        "processes": pt,
        "log_tail": lt,
        "crons": cr,
        "reset_history": ps.get("reset_history", []),
    }


# ---- HTTP server ------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Kotak Neo Bot — Live Dashboard</title>
<style>
  :root {
    --bg: #0b0f17; --panel: #131927; --panel2: #1a2236; --line: #232b3f;
    --fg: #e7ecf3; --muted: #8893a8; --accent: #4f9cff; --green: #1fbf75;
    --red: #e74c3c; --yellow: #f5b342; --purple: #9b6bff; --cyan: #2dd4d4;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg); color: var(--fg); font-size: 13px; }
  .topbar { display: flex; align-items: center; gap: 18px; padding: 10px 18px;
    background: var(--panel); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
  .topbar .brand { font-weight: 700; font-size: 16px; color: var(--accent); }
  .topbar .pill { padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 600;
    background: var(--panel2); color: var(--muted); }
  .topbar .pill.alive { background: rgba(31,191,117,0.18); color: var(--green); }
  .topbar .pill.dead { background: rgba(231,76,60,0.18); color: var(--red); }
  .topbar .pill.warn { background: rgba(245,179,66,0.18); color: var(--yellow); }
  .topbar .spacer { flex: 1; }
  .topbar .clock { font-family: 'Consolas', monospace; color: var(--cyan); font-size: 14px; }
  .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 12px; padding: 12px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
    padding: 12px 14px; min-height: 60px; }
  .card h3 { margin: 0 0 8px 0; font-size: 11px; text-transform: uppercase;
    color: var(--muted); letter-spacing: 0.5px; font-weight: 700; }
  .card .v { font-size: 22px; font-weight: 700; }
  .card .v.small { font-size: 16px; }
  .card .sub { font-size: 11px; color: var(--muted); margin-top: 4px; }
  .card.col-3 { grid-column: span 3; }
  .card.col-4 { grid-column: span 4; }
  .card.col-5 { grid-column: span 5; }
  .card.col-6 { grid-column: span 6; }
  .card.col-7 { grid-column: span 7; }
  .card.col-8 { grid-column: span 8; }
  .card.col-9 { grid-column: span 9; }
  .card.col-12 { grid-column: span 12; }
  .green { color: var(--green); } .red { color: var(--red); }
  .yellow { color: var(--yellow); } .muted { color: var(--muted); }
  .accent { color: var(--accent); } .purple { color: var(--purple); }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; color: var(--muted); font-size: 10px; text-transform: uppercase;
    padding: 4px 6px; border-bottom: 1px solid var(--line); font-weight: 600; }
  td { padding: 5px 6px; border-bottom: 1px solid rgba(255,255,255,0.04); }
  tr:hover td { background: rgba(255,255,255,0.02); }
  .num { text-align: right; font-family: 'Consolas', monospace; }
  .mono { font-family: 'Consolas', monospace; }
  .log { font-family: 'Consolas', monospace; font-size: 11px; max-height: 240px;
    overflow-y: auto; background: var(--bg); padding: 8px; border-radius: 4px;
    border: 1px solid var(--line); }
  .log-line { white-space: pre-wrap; word-break: break-all; padding: 2px 0; }
  .log-line.err { color: var(--red); }
  .log-line.warn { color: var(--yellow); }
  .scroll { max-height: 320px; overflow-y: auto; }
  .kv { display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; }
  .kv .k { color: var(--muted); }
  .kv .v { font-family: 'Consolas', monospace; }

  /* Pro card style — used by Iron Condor Risk Matrix + P&L Scenarios */
  .pro-card {
    background: linear-gradient(180deg, #131927 0%, #0e1421 100%);
    border: 1px solid #232b3f;
    border-radius: 10px;
    padding: 0;
    overflow: hidden;
    box-shadow: 0 4px 16px rgba(0,0,0,0.18);
  }
  .pro-card-header {
    padding: 12px 16px;
    border-bottom: 1px solid #232b3f;
    background: rgba(255,255,255,0.015);
  }
  .pro-card-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 14px;
    font-weight: 700;
    color: var(--fg);
    letter-spacing: 0.2px;
  }
  .pro-card-title .pro-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 6px;
    font-size: 14px;
    color: #fff;
    box-shadow: 0 2px 6px rgba(0,0,0,0.25);
  }
  .pro-card-sub {
    font-size: 10px;
    color: var(--muted);
    font-weight: 400;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-left: 6px;
  }
  .pro-card-body {
    padding: 14px 16px;
  }

  /* Iron condor risk matrix */
  .ic-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: 6px 0;
    border-bottom: 1px dashed rgba(255,255,255,0.04);
  }
  .ic-row:last-child { border-bottom: 0; }
  .ic-row .ic-k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }
  .ic-row .ic-v { font-family: 'Consolas', monospace; font-size: 13px; font-weight: 600; }
  .ic-strikes {
    font-family: 'Consolas', monospace;
    font-size: 11px;
    color: var(--muted);
    background: rgba(79,156,255,0.06);
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid rgba(79,156,255,0.15);
  }
  .ic-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
  }
  .ic-header-name {
    font-size: 13px;
    font-weight: 700;
    color: var(--accent);
  }
  .ic-header-spot {
    margin-left: auto;
    font-size: 12px;
    color: var(--cyan);
    font-family: 'Consolas', monospace;
  }
  .ic-divider { height: 14px; }

  /* P&L profile SVG container */
  .pnl-chart {
    width: 100%;
    height: 90px;
    margin: 4px 0 8px 0;
    display: block;
  }
  .ic-pnl-num.green { color: var(--green); }
  .ic-pnl-num.red   { color: var(--red); }
  .ic-pnl-num.muted { color: var(--muted); }

  /* P&L scenarios table */
  .pnl-table { width: 100%; font-size: 11px; font-family: 'Consolas', monospace; border-collapse: collapse; }
  .pnl-table th { text-align: left; color: var(--muted); font-weight: 400; padding: 4px 6px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px; }
  .pnl-table td { padding: 4px 6px; }
  .pnl-bar-cell { width: 50%; position: relative; height: 16px; }
  .pnl-bar { position: absolute; top: 4px; height: 8px; border-radius: 2px; }
  .pnl-bar.pos { background: linear-gradient(90deg, #1fbf75, #0d9668); }
  .pnl-bar.neg { background: linear-gradient(90deg, #e74c3c, #c0392b); }
  .pnl-row.current { background: rgba(245,179,66,0.10); }
  .pnl-row.edge    { background: rgba(79,156,255,0.06); }
  .pnl-label-tag {
    display: inline-block;
    padding: 1px 6px;
    border-radius: 3px;
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-left: 4px;
  }
  .pnl-label-tag.current { background: #f5b342; color: #0b0f17; }
  .pnl-label-tag.maxprof { background: #1fbf75; color: #0b0f17; }
  .pnl-label-tag.maxloss { background: #e74c3c; color: #fff; }
  .pnl-zone {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 10px;
    color: var(--muted);
    margin-top: 4px;
    padding-top: 6px;
    border-top: 1px solid rgba(255,255,255,0.04);
  }
  .pnl-zone-swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
  .cd-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .cd-cell { background: var(--bg); border-radius: 4px; padding: 6px; text-align: center; }
  .cd-cell .t { font-size: 14px; font-weight: 700; color: var(--cyan); font-family: 'Consolas', monospace; }
  .cd-cell .l { font-size: 9px; color: var(--muted); text-transform: uppercase; margin-top: 2px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
  .dot.green { background: var(--green); }
  .dot.red { background: var(--red); }
  .dot.yellow { background: var(--yellow); }
  .dot.gray { background: var(--muted); }
  .pulse { animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  .footer { padding: 10px 18px; text-align: center; color: var(--muted);
    font-size: 10px; border-top: 1px solid var(--line); }
</style>
</head>
<body>

<div class="topbar">
  <span class="brand">⚡ KOTAK NEO BOT — LIVE</span>
  <span id="botPill" class="pill">…</span>
  <span id="vixPill" class="pill">VIX …</span>
  <span id="dataPill" class="pill">data …</span>
  <span id="tickPill" class="pill">tick …</span>
  <span class="spacer"></span>
  <span class="clock" id="clock">--:--:--</span>
  <span class="pill">IST</span>
</div>

<div class="grid">

  <!-- COUNTDOWNS -->
  <div class="card col-12">
    <h3>⏱ 0DTE Countdowns</h3>
    <div class="cd-grid" id="cdGrid">
      <div class="cd-cell"><div class="t" id="cd_open">--</div><div class="l">Market open 09:15</div></div>
      <div class="cd-cell"><div class="t" id="cd_soft">--</div><div class="l">Soft force-square 14:15</div></div>
      <div class="cd-cell"><div class="t" id="cd_hard">--</div><div class="l">Hard force-square 15:15</div></div>
      <div class="cd-cell"><div class="t" id="cd_close">--</div><div class="l">Market close 15:30</div></div>
    </div>
  </div>

  <!-- ACCOUNT -->
  <div class="card col-3">
    <h3>💰 Cash</h3>
    <div class="v accent" id="cash">--</div>
    <div class="sub" id="cashSub">--</div>
  </div>
  <div class="card col-3">
    <h3>📈 Realized P&L</h3>
    <div class="v" id="realized">--</div>
    <div class="sub" id="realizedSub">closed trades only</div>
  </div>
  <div class="card col-3">
    <h3>📊 Unrealized P&L</h3>
    <div class="v" id="unrealized">--</div>
    <div class="sub" id="unrealizedSub">open positions MTM</div>
  </div>
  <div class="card col-3">
    <h3>💎 Total Value</h3>
    <div class="v" id="total">--</div>
    <div class="sub" id="totalSub">cash + unrealized</div>
  </div>

  <!-- BOT HEALTH -->
  <div class="card col-4">
    <h3>🤖 Bot Health</h3>
    <div id="botKv"></div>
  </div>
  <div class="card col-4">
    <h3>📊 Market (live)</h3>
    <div id="marketKv"></div>
  </div>
  <div class="card col-4">
    <h3>🧠 Last Brain Decision</h3>
    <div id="brainKv"></div>
  </div>
  <div class="card col-4">
    <h3>🎯 Market Thesis</h3>
    <div id="thesisKv"></div>
  </div>

  <!-- OPEN POSITIONS -->
  <div class="card col-8">
    <h3>📂 Open Positions <span id="posCount" class="muted">(0)</span></h3>
    <div class="scroll"><table id="posTable">
      <thead><tr>
        <th>Symbol</th><th>Underlying</th><th class="num">Qty</th>
        <th class="num">Avg</th><th class="num">LTP</th><th class="num">P&L</th>
        <th>Expiry</th>
      </tr></thead>
      <tbody></tbody>
    </table></div>
  </div>

  <!-- TODAY'S TRADES -->
  <div class="card col-4">
    <h3>📋 Today's Trades <span id="trdCount" class="muted">(0)</span></h3>
    <div class="scroll" id="trdScroll" style="max-height:300px"><table id="trdTable">
      <thead><tr><th>Time</th><th>Sym</th><th>Side</th><th class="num">Qty</th><th class="num">Fill</th></tr></thead>
      <tbody></tbody>
    </table></div>
  </div>

  <!-- THESIS -->
  <div class="card col-6">
    <h3>🎯 Market Thesis</h3>
    <div id="thesisBody" class="muted">—</div>
  </div>

  <!-- CRONS -->
  <div class="card col-6">
    <h3>⏰ Cron Schedule (kotak-*)</h3>
    <div class="scroll" style="max-height:240px"><table id="cronTable">
      <thead><tr><th>Name</th><th>Schedule</th><th>Next IST</th></tr></thead>
      <tbody></tbody>
    </table></div>
  </div>

  <!-- LOG TAIL -->
  <div class="card col-8">
    <h3>📜 bot.log (tail)</h3>
    <div class="log" id="logBox"></div>
  </div>

  <!-- PROCESS TREE -->
  <div class="card col-4">
    <h3>🌳 kotak-neo-bot Processes</h3>
    <div class="scroll" id="procScroll" style="max-height:300px"><table id="procTable">
      <thead><tr><th>PID</th><th>Name</th><th class="num">Sess</th><th class="num">Uptime</th></tr></thead>
      <tbody></tbody>
    </table></div>
  </div>

  <!-- RESET HISTORY -->
  <div class="card col-12">
    <h3>🔄 Reset History (file-level)</h3>
    <div id="resetBody" class="muted">—</div>
  </div>

  <!-- ========== TRADING TERMINAL (full-width section, own padding) ========== -->
  <div style="background: linear-gradient(180deg, #0a1020 0%, #0b0f17 100%); border-top: 3px solid var(--accent); padding: 24px 24px 32px; margin-top: 16px;">

    <!-- SECTION HEADER -->
    <div style="display: flex; align-items: baseline; gap: 16px; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 1px solid var(--line);">
      <div style="font-size: 20px; font-weight: 700; color: var(--accent); letter-spacing: 0.5px;">📊 TRADING TERMINAL</div>
      <div style="font-size: 12px; color: var(--muted);">Real-time NIFTY / BANKNIFTY 5min candles · live option chain · positions terminal · iron-condor risk matrix · P&L scenarios</div>
    </div>

    <!-- ROW 1: CANDLES (full width, side by side, taller) -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">

      <!-- NIFTY CANDLES -->
      <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px;">
        <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 10px;">
          <div style="font-size: 14px; font-weight: 700; color: var(--fg);">📈 NIFTY 5min</div>
          <div style="font-size: 22px; font-weight: 700; color: var(--accent); font-family: 'Consolas', monospace;" id="niftySpotPill">--</div>
          <div style="font-size: 11px; color: var(--muted); margin-left: auto;" id="niftyCandleMeta">—</div>
        </div>
        <div id="niftyCandles" style="background: #050810; border: 1px solid #1a2236; border-radius: 4px; height: 320px; width: 100%;">
          <div style="padding: 8px; color: var(--muted); font-size: 11px;">fetching candles...</div>
        </div>
      </div>

      <!-- BANKNIFTY CANDLES -->
      <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px;">
        <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 10px;">
          <div style="font-size: 14px; font-weight: 700; color: var(--fg);">📈 BANKNIFTY 5min</div>
          <div style="font-size: 22px; font-weight: 700; color: var(--accent); font-family: 'Consolas', monospace;" id="bnfSpotPill">--</div>
          <div style="font-size: 11px; color: var(--muted); margin-left: auto;" id="bnfCandleMeta">—</div>
        </div>
        <div id="bnfCandles" style="background: #050810; border: 1px solid #1a2236; border-radius: 4px; height: 320px; width: 100%;">
          <div style="padding: 8px; color: var(--muted); font-size: 11px;">fetching candles...</div>
        </div>
      </div>
    </div>

    <!-- ROW 2: POSITIONS TERMINAL (full width) -->
    <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
      <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 12px;">
        <div style="font-size: 14px; font-weight: 700; color: var(--fg);">💼 Positions Terminal</div>
        <div style="font-size: 11px; color: var(--muted);" id="termPosCount">(0 legs)</div>
        <div style="font-size: 11px; color: var(--muted); margin-left: auto;">LTP from bot's last MTM tick · bid/ask estimated 0.5% (0DTE) / 1% (1D+) · real exchange bid/ask unavailable (NSE blocked, Kite MCP down)</div>
      </div>
      <div style="overflow-x: auto;"><table id="termPosTable" style="width: 100%; font-size: 12px; border-collapse: collapse;">
        <thead><tr style="background: #0d1421;">
          <th style="text-align:left; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Symbol</th>
          <th style="text-align:left; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Side</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Lots × Qty</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Strike</th>
          <th style="text-align:center; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Type</th>
          <th style="text-align:center; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Expiry</th>
          <th style="text-align:center; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">DTE</th>
          <th style="text-align:center; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">ITM?</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Entry</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">LTP</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Bid est</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Ask est</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">P&L / unit</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">P&L total</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Value if sold now</th>
        </tr></thead>
        <tbody></tbody>
      </table></div>
    </div>

    <!-- ROW 3: RISK MATRIX + SCENARIOS (2 columns) -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">

      <!-- IRON CONDOR RISK MATRIX -->
      <div class="pro-card" id="riskMatrixCard">
        <div class="pro-card-header">
          <div class="pro-card-title">
            <span class="pro-icon" style="background: linear-gradient(135deg,#4f9cff,#2563eb);">▣</span>
            <span>Iron Condor Risk Matrix</span>
            <span class="pro-card-sub">at expiry · live from positions</span>
          </div>
        </div>
        <div id="riskMatrix" class="pro-card-body">—</div>
      </div>

      <!-- SCENARIOS -->
      <div class="pro-card" id="scenariosCard">
        <div class="pro-card-header">
          <div class="pro-card-title">
            <span class="pro-icon" style="background: linear-gradient(135deg,#1fbf75,#0d9668);">◉</span>
            <span>P&amp;L Scenarios</span>
            <span class="pro-card-sub">P&amp;L at various underlying levels</span>
          </div>
        </div>
        <div id="scenariosBody" class="pro-card-body">—</div>
      </div>
    </div>

    <!-- ROW 4: OPTION CHAIN (full width) -->
    <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px;">
      <div style="display: flex; align-items: baseline; gap: 14px; margin-bottom: 12px;">
        <div style="font-size: 14px; font-weight: 700; color: var(--fg);">🔗 NIFTY Option Chain</div>
        <div style="font-size: 11px; color: var(--muted);">26-Aug-2026 (0DTE)</div>
        <div style="font-size: 11px; color: var(--muted); margin-left: auto;" id="ocMeta">—</div>
      </div>
      <div style="overflow-x: auto; max-height: 360px; overflow-y: auto;"><table id="ocTable" style="width: 100%; font-size: 12px; border-collapse: collapse;">
        <thead><tr style="background: #0d1421;">
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">Strike</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">CE LTP</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">CE Bid</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">CE Ask</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">CE OI</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">CE IV</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">PE LTP</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">PE Bid</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">PE Ask</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">PE OI</th>
          <th style="text-align:right; padding: 8px 6px; border-bottom: 2px solid var(--line); color: var(--muted); font-size: 10px; text-transform: uppercase; font-weight: 700;">PE IV</th>
        </tr></thead>
        <tbody></tbody>
      </table></div>
      <div style="font-size: 11px; color: var(--muted); margin-top: 8px;" id="ocNote">—</div>
    </div>

    <!-- ========== 🧠 MAVIS BRAIN (quant trader AI, not template) ========== -->
    <div style="border-top: 3px solid #9b6bff; margin-top: 24px; padding-top: 16px;">
      <div style="background: linear-gradient(90deg, rgba(155,107,255,0.15) 0%, rgba(155,107,255,0.03) 100%); border: 1px solid #9b6bff; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
        <div style="display: flex; align-items: baseline; gap: 14px;">
          <div style="font-size: 20px; font-weight: 700; color: #9b6bff;">🧠 MAVIS BRAIN</div>
          <div style="font-size: 12px; color: var(--muted);">quant trader AI · not template · data-driven decisions</div>
        </div>
      </div>

      <!-- Brain state: regime, trend, key levels -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px;">
        <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px;">
          <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 10px;">📊 Market Regime</div>
          <div id="brainRegime" class="muted">fetching...</div>
        </div>
        <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px;">
          <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 10px;">🎯 Key Levels & Expected Move</div>
          <div id="brainLevels" class="muted">fetching...</div>
        </div>
      </div>

      <!-- Mavis trade plan -->
      <div style="background: linear-gradient(90deg, rgba(31,191,117,0.10) 0%, rgba(31,191,117,0.02) 100%); border: 1px solid #1fbf75; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
        <div style="font-size: 14px; font-weight: 700; color: #1fbf75; margin-bottom: 8px;">💡 Mavis's Trade Plan (data-driven, dynamic)</div>
        <div id="mavisPlan" class="muted">fetching...</div>
      </div>

      <!-- Mavis real-time live presence -->
      <div style="background: linear-gradient(90deg, rgba(155,107,255,0.12) 0%, rgba(155,107,255,0.02) 100%); border: 1px solid #9b6bff; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
        <div style="font-size: 14px; font-weight: 700; color: #9b6bff; margin-bottom: 8px;">🧠 Mavis live (event-driven, real-time)</div>
        <div id="mavisLive" class="muted">fetching...</div>
      </div>

      <!-- Mavis event ticker -->
      <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin-bottom: 16px;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <div style="font-size: 13px; font-weight: 700; color: var(--accent);">📡 Mavis Event Ticker (last 10)</div>
          <div style="font-size: 10px; color: var(--muted);">— auto-refresh 2.5s —</div>
        </div>
        <div id="mavisEvents" class="muted">fetching...</div>
      </div>

      <!-- Intraday decision tree -->
      <div style="background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px;">
        <div style="font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 10px;">🌳 Mavis's Intraday Decision Tree</div>
        <div id="mavisTree" class="muted">fetching...</div>
      </div>
    </div>

  </div>

</div>

<div class="footer">live_dashboard.py · auto-refresh 1s · single-screen unified view · source of truth: paper_state.json + :8502 /status + cron list</div>

<script>
const $ = (id) => document.getElementById(id);
const fmtINR = (n) => "₹" + (n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 });
const fmtINR2 = (n) => "₹" + (n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
const fmtPct = (n) => ((n || 0) >= 0 ? '+' : '') + (n || 0).toFixed(2) + '%';
const fmtUptime = (s) => {
  if (!s && s !== 0) return '--';
  s = Math.floor(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h + 'h ' + (m < 10 ? '0' + m : m) + 'm';
};
const signClass = (n) => (n > 0 ? 'green' : (n < 0 ? 'red' : 'muted'));

async function poll() {
  try {
    const r = await fetch('/api/state', { cache: 'no-store' });
    const s = await r.json();
    render(s);
  } catch (e) {
    $('botPill').className = 'pill dead';
    $('botPill').innerHTML = '<span class="dot red pulse"></span>FETCH ERROR';
  }
  // Mavis real-time (event-driven, fresh data)
  try {
    const mst = await fetch('/api/mavis_state', { cache: 'no-store' });
    const st = await mst.json();
    renderMavisLive(st);
  } catch (e) {}
  try {
    const me = await fetch('/api/mavis_events', { cache: 'no-store' });
    const ev = await me.json();
    renderMavisEvents(ev);
  } catch (e) {}
}

function render(s) {
  // clock
  const cd = s.countdowns || {};
  $('clock').textContent = (cd.now_ist || '--:--:--') + ' IST · ' + (cd.now_date || '');

  // top pills
  const bot = s.bot || {};
  const alive = !!bot.alive && !!bot.main_thread_alive;
  $('botPill').className = 'pill ' + (alive ? 'alive' : 'dead');
  $('botPill').innerHTML = '<span class="dot ' + (alive ? 'green pulse' : 'red') + '"></span>BOT ' + (alive ? 'ALIVE' : 'DOWN') + ' · PID ' + (bot.pid || '?');
  $('vixPill').textContent = 'VIX ' + ((bot.vix || 0).toFixed(2));
  $('vixPill').className = 'pill ' + ((bot.vix || 0) > 18 ? 'dead' : ((bot.vix || 0) > 14 ? 'warn' : 'alive'));
  $('dataPill').textContent = 'data ' + (bot.data_source || '?');
  $('dataPill').className = 'pill ' + (bot.data_source === 'live_kotak' ? 'alive' : 'warn');
  $('tickPill').textContent = 'tick ' + (bot.tick || '?') + ' · uptime ' + fmtUptime(bot.uptime_sec);

  // countdowns
  $('cd_open').textContent = cd.market_open_0915 ? cd.market_open_0915.label : '--';
  $('cd_soft').textContent = cd.force_square_soft_1415 ? cd.force_square_soft_1415.label : '--';
  $('cd_hard').textContent = cd.force_square_hard_1515 ? cd.force_square_hard_1515.label : '--';
  $('cd_close').textContent = cd.market_close_1530 ? cd.market_close_1530.label : '--';

  // account
  const acc = s.account || {};
  $('cash').textContent = fmtINR(acc.cash);
  $('cashSub').innerHTML = 'started ₹' + (acc.starting_capital || 0).toLocaleString('en-IN') + ' · <span class="' + signClass(acc.cash - acc.starting_capital) + '">' + fmtPct(acc.today_pnl_pct) + ' today</span>';
  $('realized').textContent = fmtINR(acc.realized_pnl);
  $('realized').className = 'v ' + signClass(acc.realized_pnl);
  $('unrealized').textContent = fmtINR(acc.unrealized_pnl);
  $('unrealized').className = 'v ' + signClass(acc.unrealized_pnl);
  $('total').textContent = fmtINR(acc.total_value);
  $('total').className = 'v accent';

  // bot health kv
  $('botKv').innerHTML = renderKv({
    'PID': bot.pid || '--', 'State': bot.state || '--',
    'Uptime': fmtUptime(bot.uptime_sec),
    'Tick': bot.tick, 'Last liveness age': (bot.last_liveness_age_sec || 0).toFixed(1) + 's',
    'Main thread alive': bot.main_thread_alive ? 'yes' : 'no',
    'Trades today': bot.trades_today,
    'Open positions': bot.open_positions,
    'Paused': bot.is_paused ? 'YES' : 'no',
    'Risk preset': bot.risk_preset || '--',
  });

  // market kv (live from bot :8502)
  const mk = s.market || {};
  $('marketKv').innerHTML = renderKv({
    'NIFTY spot': (mk.nifty_spot || 'n/a'),
    'BANKNIFTY spot': (mk.banknifty_spot || 'n/a'),
    'VIX (live)': (mk.vix || 0).toFixed(2),
    'PCR': mk.pcr || 'n/a',
    'Max pain (NIFTY)': mk.max_pain_nifty || 'n/a',
    'Max pain (BANKNIFTY)': mk.max_pain_banknifty || 'n/a',
    'FII net OI': mk.fii_net_oi || 'n/a',
    'Data source': mk.data_source || '--',
    'Risk preset': mk.risk_preset || '--',
  });

  // thesis (rich — from thesis/latest.json, updated every 30m)
  const mt = s.market_thesis || {};
  const t = mt;
  if (t && t.available) {
    const regCls = t.regime === 'range' ? 'green' : (t.regime === 'trend' ? 'accent' : 'yellow');
    const biasCls = t.bias === 'bullish' ? 'green' : (t.bias === 'bearish' ? 'red' : 'muted');
    const rng = t.expected_range && t.expected_range.length === 2
      ? t.expected_range[0].toFixed(0) + ' – ' + t.expected_range[1].toFixed(0)
      : 'n/a';
    const prefs = (t.preferred_strategies || []).join(', ') || 'n/a';
    const macroEvt = t.macro_next_event || {};
    const macroLine = macroEvt.name
      ? (macroEvt.name + ' · ' + (macroEvt.datetime_ist || '?') + ' · ' + (macroEvt.minutes_to_event ? Math.round(macroEvt.minutes_to_event/60) + 'h away' : ''))
      : 'none scheduled';
    $('thesisKv').innerHTML =
      '<div class="kv"><span class="k">NIFTY</span><span class="v accent">' + (t.nifty_spot ? t.nifty_spot.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv"><span class="k">BANKNIFTY</span><span class="v accent">' + (t.banknifty_spot ? t.banknifty_spot.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv"><span class="k">VIX</span><span class="v">' + (t.india_vix ? t.india_vix.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv"><span class="k">Regime</span><span class="v ' + regCls + '">' + (t.regime || '--') + '</span></div>' +
      '<div class="kv"><span class="k">Bias</span><span class="v ' + biasCls + '">' + (t.bias || '--') + ' (conf ' + ((t.confidence || 0) * 100).toFixed(0) + '%)</span></div>' +
      '<div class="kv"><span class="k">NIFTY range</span><span class="v">' + rng + '</span></div>' +
      '<div class="kv"><span class="k">Risk budget</span><span class="v">' + (t.risk_budget_pct || '--') + '% · max ' + (t.max_positions || '--') + ' pos</span></div>' +
      '<div class="kv"><span class="k">Strategies</span><span class="v">' + prefs + '</span></div>' +
      '<div class="kv"><span class="k">Crude / USD-INR</span><span class="v">' + (t.crude_oil ? '$' + t.crude_oil.toFixed(2) : '--') + ' · ₹' + (t.usdinr ? t.usdinr.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv"><span class="k">DOW / DXY</span><span class="v">' + (t.dow_spot ? t.dow_spot.toFixed(0) : '--') + ' / ' + (t.dxy ? t.dxy.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv"><span class="k">Global cues</span><span class="v muted" style="font-size:11px">' + (t.global_cues || '--') + '</span></div>' +
      '<div class="kv"><span class="k">Next macro</span><span class="v yellow">' + macroLine + '</span></div>' +
      (t.narrative ? '<div style="margin-top:6px;font-size:11px;color:var(--muted);line-height:1.4">' + t.narrative + '</div>' : '') +
      '<div class="sub">updated ' + (t.ist_time || '--') + ' (refreshes every 30m via thesis cron)</div>';
  } else {
    $('thesisKv').innerHTML = '<span class="muted">no thesis yet — premarket 08:25 cron hasn\'t run today</span>';
  }

  // brain
  const br = s.brain || {};
  const la = br.last_action || {};
  $('brainKv').innerHTML = renderKv({
    'Bias': la.bias || '--',
    'Source': la.source || '--',
    'Max positions': la.max_positions,
    'Actions': (la.actions || []).length,
    'Note': la.note || '--',
    'Updated': la.ist_time || '--',
  });

  // positions
  const posTbody = $('posTable').querySelector('tbody');
  posTbody.innerHTML = (s.positions || []).map(p => {
    const pnlCls = signClass(p.pnl);
    return '<tr><td class="mono">' + (p.symbol || '?') + '</td><td>' + (p.underlying || '') + '</td>'
      + '<td class="num ' + (p.qty < 0 ? 'red' : 'green') + '">' + p.qty + '</td>'
      + '<td class="num">' + (p.avg || 0).toFixed(2) + '</td>'
      + '<td class="num">' + (p.ltp || 0).toFixed(2) + '</td>'
      + '<td class="num ' + pnlCls + '">' + fmtINR(p.pnl) + '</td>'
      + '<td class="mono">' + (p.expiry || '') + '</td></tr>';
  }).join('') || '<tr><td colspan="7" class="muted">no open positions</td></tr>';
  $('posCount').textContent = '(' + (s.positions || []).length + ')';

  // trades
  const trdTbody = $('trdTable').querySelector('tbody');
  trdTbody.innerHTML = (s.today_fills || []).slice().reverse().map(t => {
    const t_short = (t.filled_at || '').split('T')[1] || '';
    return '<tr><td class="mono">' + t_short + '</td><td class="mono">' + (t.symbol || '').replace(/[0-9]/g,'').slice(0, 12) + '</td>'
      + '<td class="' + (t.side === 'BUY' ? 'green' : 'red') + '">' + (t.side || '') + '</td>'
      + '<td class="num">' + t.qty + '</td>'
      + '<td class="num">' + (t.price || 0).toFixed(2) + '</td></tr>';
  }).join('') || '<tr><td colspan="5" class="muted">no fills today</td></tr>';
  $('trdCount').textContent = '(' + (s.today_fills_count || 0) + ')';

  // thesis
  const th = s.thesis || {};
  if (th.available && th.thesis) {
    const t = th.thesis;
    $('thesisBody').innerHTML = '<div class="kv"><span class="k">Regime</span><span class="v accent">' + (t.regime || '--') + '</span></div>'
      + '<div class="kv"><span class="k">Bias</span><span class="v">' + (t.bias || '--') + '</span></div>'
      + '<div class="kv"><span class="k">Confidence</span><span class="v">' + (t.confidence || '--') + '</span></div>'
      + '<div class="kv"><span class="k">Risk budget</span><span class="v">' + (t.risk_budget || '--') + '</span></div>'
      + '<div class="kv"><span class="k">Updated</span><span class="v muted">' + (t.updated_at || t.ts || '--') + '</span></div>'
      + (t.narrative ? '<div style="margin-top:6px;font-size:11px;color:var(--muted)">' + t.narrative + '</div>' : '');
  } else {
    $('thesisBody').innerHTML = '<span class="muted">no thesis yet — pre-market 08:25 cron hasn\'t run</span>';
  }

  // crons
  const crTbody = $('cronTable').querySelector('tbody');
  const crs = (s.crons && s.crons.jobs) || [];
  crTbody.innerHTML = crs.map(c => '<tr><td class="mono">' + c.name + '</td><td class="mono">' + c.schedule + '</td><td class="mono accent">' + c.next_run_ist + '</td></tr>').join('') || '<tr><td colspan="3" class="muted">no kotak- crons</td></tr>';

  // log tail
  $('logBox').innerHTML = (s.log_tail || []).map(l => {
    const cls = (l.indexOf('ERROR') >= 0 || l.indexOf('Traceback') >= 0) ? 'log-line err'
              : (l.indexOf('WARN') >= 0 ? 'log-line warn' : 'log-line');
    return '<div class="' + cls + '">' + escapeHtml(l) + '</div>';
  }).join('');

  // processes
  const procTbody = $('procTable').querySelector('tbody');
  const procs = (s.processes && s.processes.kotak_procs) || [];
  procTbody.innerHTML = procs.map(p => '<tr><td class="mono">' + p.pid + '</td><td>' + p.name + '</td>'
    + '<td class="num">' + p.session + '</td><td class="num">' + (p.uptime_min || 0).toFixed(0) + 'm</td></tr>').join('')
    || '<tr><td colspan="4" class="muted">no kotak procs</td></tr>';

  // reset history
  const rh = s.reset_history || [];
  if (rh.length) {
    $('resetBody').innerHTML = rh.slice(-5).map(r => '<div class="kv"><span class="k">' + r.at + '</span><span class="v">'
      + (r.reason || '?') + ' · capital ₹' + (r.capital || 0).toLocaleString('en-IN') + '</span></div>').join('')
      + (rh.length > 5 ? '<div class="sub">…+' + (rh.length - 5) + ' more</div>' : '');
  } else {
    $('resetBody').innerHTML = '<span class="muted">no resets recorded</span>';
  }

  // ---- TRADING TERMINAL ----
  // Update spot pills from terminal data
  fetch('/api/terminal').then(r => r.json()).then(t => renderTerminal(t))
    .catch(e => { /* keep prev */ });
  // Refresh candles
  fetch('/api/candles?symbol=NIFTY&interval=5m&period=1d').then(r => r.json()).then(d => renderCandles(d, 'nifty'));
  fetch('/api/candles?symbol=BANKNIFTY&interval=5m&period=1d').then(r => r.json()).then(d => renderCandles(d, 'bnf'));
  // Option chain
  fetch('/api/option_chain?symbol=NIFTY&expiry=2026-08-26&spot=' + (s.market_thesis && s.market_thesis.nifty_spot || 24260)).then(r => r.json()).then(d => renderOC(d));

  // Mavis Brain (quant trader AI)
  fetch('/api/quant_brain').then(r => r.json()).then(renderBrain);
  fetch('/api/mavis_trades').then(r => r.json()).then(renderMavisPlan);
  // Mavis real-time (event ticker + current state of mind)
  fetch('/api/mavis_state').then(r => r.json()).then(renderMavisLive);
  fetch('/api/mavis_events').then(r => r.json()).then(renderMavisEvents);
}

function renderMavisLive(st) {
  const el = $('mavisLive');
  if (!el) return;
  if (!st || !st.current || Object.keys(st.current).length === 0) {
    el.innerHTML = '<span class="muted">Mavis monitor not running (start scripts/mavis_realtime.py)</span>';
    return;
  }
  const c = st.current;
  const m = st.mavis_state || {};
  const ts = (c.ts || '').substring(11, 19);
  const lastThought = m.last_thought || 'Standing by';
  const minsToForce = m.mins_to_force_square;
  const mktOpen = m.mkt_open ? '🟢 MARKET OPEN' : '⚪ market closed';
  const forceLine = minsToForce != null ? `<span class="muted"> · </span><span class="yellow">${minsToForce}m to force-square</span>` : '';
  const mtmLine = c.open_positions > 0 ? `<span class="muted"> · MTM </span><span class="${c.mtm_total >= 0 ? 'green' : 'red'}">Rs.${c.mtm_total.toFixed(0)}</span>` : '';
  el.innerHTML =
    `<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px;">` +
    `<span style="color: var(--accent); font-weight: 700;">🧠 Mavis live</span>` +
    `<span class="muted">${ts}</span>` +
    `<span class="muted">·</span><span class="${m.mkt_open ? 'green' : 'muted'}">${mktOpen}</span>` +
    `<span class="muted">·</span><span>NIFTY <b>${(c.nifty || 0).toFixed(2)}</b></span>` +
    `<span class="muted">·</span><span>BNF <b>${(c.banknifty || 0).toFixed(2)}</b></span>` +
    `<span class="muted">·</span><span>VIX <b>${(c.vix || 0).toFixed(2)}</b></span>` +
    `<span class="muted">·</span><span>pos <b>${c.open_positions || 0}</b></span>` +
    mtmLine + forceLine +
    `</div>` +
    `<div style="margin-top: 6px; font-size: 13px; padding: 8px 10px; background: rgba(155,107,255,0.10); border-left: 3px solid #9b6bff; border-radius: 3px;">` +
    `<b style="color: #9b6bff;">Mavis thinks:</b> ${lastThought}` +
    `</div>`;
}

function renderMavisEvents(d) {
  const el = $('mavisEvents');
  if (!el) return;
  if (!d || !d.available || d.events.length === 0) {
    el.innerHTML = '<span class="muted">no events yet — monitor just started, events will appear as NIFTY crosses levels / MTM hits thresholds / VIX spikes</span>';
    return;
  }
  // Show last 10 events, newest first
  const events = d.events.slice().reverse().slice(0, 10);
  let html = `<div style="font-size: 11px; color: var(--muted); margin-bottom: 4px;">${d.total_in_log} total events · showing last ${events.length}</div>`;
  events.forEach(e => {
    const ts = (e.ts || '').substring(11, 19);
    const typeColor =
      e.type === 'nifty_breakdown' || e.type === 'mtm_loss' || e.type === 'vix_above_threshold' ? 'red' :
      e.type === 'nifty_breakout' || e.type === 'mtm_profit' ? 'green' :
      e.type === 'vix_spike' ? 'yellow' : 'muted';
    const ctx = e.context ? JSON.stringify(e.context).substring(0, 80) : '';
    html += `<div style="font-size: 11px; padding: 3px 0; border-bottom: 1px dashed rgba(255,255,255,0.05);">` +
      `<span class="muted">${ts}</span> <span class="${typeColor}">${e.type}</span> <span>${e.level}</span>=<b>${e.value}</b> <span class="muted">${ctx}</span></div>`;
  });
  el.innerHTML = html;
}

function renderBrain(b) {
  if (!b || !b.available) {
    $('brainRegime').innerHTML = '<span class="muted">brain not generated yet — run scripts/quant_brain.py</span>';
    $('brainLevels').innerHTML = '<span class="muted">—</span>';
    return;
  }
  // Regime card
  const n = b.nifty || {};
  const bn = b.banknifty || {};
  const v = b.vix || {};
  const g = b.global_cues || {};
  const sq = b.setup_quality || {};
  const trendCls = n.trend === 'BULL' ? 'green' : (n.trend === 'BEAR' ? 'red' : 'yellow');
  const vixCls = v.regime === 'low' ? 'green' : (v.regime === 'normal' ? 'accent' : (v.regime === 'elevated' ? 'yellow' : 'red'));

  $('brainRegime').innerHTML =
    '<div class="kv"><span class="k">NIFTY spot</span><span class="v accent">' + (n.spot || 0).toFixed(2) + '</span></div>' +
    '<div class="kv"><span class="k">Trend (EMA stack)</span><span class="v ' + trendCls + '"><b>' + (n.trend || '?') + ' ' + (n.trend_strength || '') + '</b></span></div>' +
    '<div class="kv"><span class="k">RSI(14)</span><span class="v">' + (n.rsi || 0).toFixed(1) + ' <span class="muted" style="font-size:10px">(' + (n.rsi_state || '') + ')</span></span></div>' +
    '<div class="kv"><span class="k">ADX(14)</span><span class="v">' + (n.adx || 0).toFixed(1) + ' <span class="muted" style="font-size:10px">(strength)</span></span></div>' +
    '<div class="kv"><span class="k">India VIX</span><span class="v ' + vixCls + '"><b>' + (v.current || 0).toFixed(2) + ' ' + (v.regime || '') + '</b> ' + (v.vs_avg_pct ? ' <span class="muted" style="font-size:10px">(' + v.vs_avg_pct + '% vs avg)</span>' : '') + '</span></div>' +
    '<div class="kv"><span class="k">BANKNIFTY</span><span class="v">' + (bn.spot || 0).toFixed(2) + ' <span class="muted" style="font-size:10px">(' + (bn.trend || '?') + ' ' + (bn.trend_strength || '') + ')</span></span></div>' +
    '<div class="kv"><span class="k">Setup quality</span><span class="v ' + (sq.score >= 60 ? 'green' : (sq.score >= 40 ? 'yellow' : 'red')) + '"><b>' + (sq.score || 0) + '/100</b></span></div>' +
    (sq.notes || []).map(n => '<div style="font-size: 11px; color: var(--muted); margin-top: 3px;">· ' + n + '</div>').join('') +
    '<div style="border-top: 1px solid var(--line); margin-top: 10px; padding-top: 10px; font-size: 11px; color: var(--muted);">' +
      '<b>Global cues:</b><br>' +
      'S&P ' + (g.spx_fut ? g.spx_fut['1d_pct'] + '%' : '?') +
      ' · Nasdaq ' + (g.nasdaq_fut ? g.nasdaq_fut['1d_pct'] + '%' : '?') +
      ' · Crude ' + (g.crude_oil ? g.crude_oil['1d_pct'] + '%' : '?') +
      ' · DXY ' + (g.dxy ? g.dxy['1d_pct'] + '%' : '?') +
      ' · US VIX ' + (g.us_vix ? g.us_vix['spot'] : '?') +
    '</div>';

  // Levels card
  $('brainLevels').innerHTML =
    '<div class="kv"><span class="k">ATR(14) daily</span><span class="v">' + (n.atr_14 || 0).toFixed(0) + ' pts (' + (n.atr_14_pct || 0).toFixed(2) + '%)</span></div>' +
    '<div class="kv"><span class="k">Expected 1d move</span><span class="v yellow"><b>±' + (n.expected_move_1d || 0).toFixed(0) + ' pts</b></span></div>' +
    '<div class="kv"><span class="k">5d range</span><span class="v">' + (n['5d_low'] || 0).toFixed(0) + ' — ' + (n['5d_high'] || 0).toFixed(0) + '</span></div>' +
    '<div class="kv"><span class="k">BB(20,2)</span><span class="v">' + (n.bb_lower || 0).toFixed(0) + ' <span class="muted">/</span> ' + (n.bb_mid || 0).toFixed(0) + ' <span class="muted">/</span> ' + (n.bb_upper || 0).toFixed(0) + '</span></div>' +
    '<div class="kv"><span class="k">Classic Pivot</span><span class="v accent">' + (n.pivot || 0).toFixed(0) + '</span></div>' +
    '<div class="kv"><span class="k">R1 / S1</span><span class="v green">' + (n.r1 || 0).toFixed(0) + '</span> <span class="muted">/</span> <span class="v red">' + (n.s1 || 0).toFixed(0) + '</span></div>' +
    '<div class="kv"><span class="k">EMA 9 / 21 / 50</span><span class="v mono">' + (n.ema9 || 0).toFixed(0) + ' / ' + (n.ema21 || 0).toFixed(0) + ' / ' + (n.ema50 || 0).toFixed(0) + '</span></div>' +
    '<div class="kv"><span class="k">24h change</span><span class="v">' + ((n['24h_change_pct'] || 0) >= 0 ? '+' : '') + (n['24h_change_pct'] || 0).toFixed(2) + '%</span></div>' +
    '<div class="kv"><span class="k">BANKNIFTY ATR</span><span class="v">' + (bn.atr_14 || 0).toFixed(0) + ' pts</span></div>';
}

function renderMavisPlan(d) {
  if (!d || !d.available || !d.trades) {
    $('mavisPlan').innerHTML = '<span class="muted">no Mavis trade plan yet — Mavis writes to data_cache/mavis_trades.json</span>';
    $('mavisTree').innerHTML = '<span class="muted">—</span>';
    return;
  }
  // Render decision banner at the top
  let planHtml = '';
  if (d.decision) {
    const actionColor = d.decision === 'EXECUTE_PLAN' ? 'green' :
                        d.decision === 'BLOCK' ? 'red' : 'yellow';
    const actionBg = d.decision === 'EXECUTE_PLAN' ? 'rgba(31,191,117,0.18)' :
                     d.decision === 'BLOCK' ? 'rgba(231,76,60,0.18)' : 'rgba(245,179,66,0.18)';
    const conf = d.decision_confidence ? Math.round(d.decision_confidence * 100) + '%' : '—';
    const at = d.decision_at || d.generated_at || '';
    const atShort = at.length >= 16 ? at.substring(11, 16) : at;
    planHtml += '<div style="background: ' + actionBg + '; border: 1px solid ' + actionColor + '; border-radius: 6px; padding: 12px; margin-bottom: 12px;">' +
      '<div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">' +
      '<div style="font-size: 22px; font-weight: 700; color: ' + actionColor + ';">' + d.decision + '</div>' +
      '<div style="font-size: 12px;"><span class="muted">bias:</span> <b>' + (d.decision_bias || '—') + '</b></div>' +
      '<div style="font-size: 12px;"><span class="muted">confidence:</span> <b>' + conf + '</b></div>' +
      '<div style="font-size: 12px;"><span class="muted">valid_for:</span> <b>' + (d.valid_for || '—') + '</b></div>' +
      '<div style="font-size: 11px;" class="muted">updated ' + atShort + '</div>' +
      '</div>' +
      (d.decision_reason ? '<div style="font-size: 12px; margin-top: 8px;"><b style="color: ' + actionColor + ';">Why:</b> ' + d.decision_reason + '</div>' : '') +
      '</div>';
  }
  // Render trade plan
  d.trades.forEach((t, i) => {
    const badge = t.type === 'primary' ? '<span class="green" style="background:rgba(31,191,117,0.15); padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 700;">PRIMARY</span>' :
                  t.type === 'alternative' ? '<span class="yellow" style="background:rgba(245,179,66,0.15); padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 700;">ALT</span>' :
                  t.type === 'no_trade' ? '<span class="red" style="background:rgba(231,76,60,0.15); padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: 700;">NO TRADE</span>' : '';
    planHtml += '<div style="background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 10px; margin-bottom: 8px;">' +
      '<div style="display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px;">' +
      '<b style="color: var(--accent);">' + (t.name || 'unnamed') + '</b> ' + badge +
      '</div>' +
      '<div style="font-size: 12px; margin-bottom: 4px;"><b>Logic:</b> ' + (t.logic || '—') + '</div>' +
      '<div style="font-size: 12px; margin-bottom: 4px;"><b>Entry:</b> ' + (t.entry_trigger || '—') + '</div>' +
      '<div style="font-size: 12px; margin-bottom: 4px;"><b>Target:</b> ' + (t.target_premium || t.target || '—') + '</div>' +
      '<div style="font-size: 12px;"><b>Stop:</b> ' + (t.stop_loss || t.stop || '—') + '</div>' +
      '</div>';
  });
  if (d.mavis_analysis) {
    planHtml += '<div style="font-size: 12px; background: rgba(155,107,255,0.08); padding: 10px; border-left: 3px solid #9b6bff; border-radius: 4px; margin-top: 10px;">' +
      '<b style="color: #9b6bff;">Mavis analysis:</b><br>' + d.mavis_analysis +
      '</div>';
  } else if (d.decision_reason) {
    planHtml += '<div style="font-size: 12px; background: rgba(155,107,255,0.08); padding: 10px; border-left: 3px solid #9b6bff; border-radius: 4px; margin-top: 10px;">' +
      '<b style="color: #9b6bff;">Mavis decision rationale:</b><br>' + d.decision_reason +
      '</div>';
  }
  $('mavisPlan').innerHTML = planHtml;

  // Decision tree
  if (d.intraday_decision_tree) {
    const tree = d.intraday_decision_tree;
    let treeHtml = '';
    Object.keys(tree).forEach(phase => {
      const label = phase.replace(/_/g, ' ').replace(/phase (\d) /, 'Phase $1: ');
      treeHtml += '<div style="margin-bottom: 6px; padding: 6px 10px; background: var(--bg); border-radius: 3px; border-left: 2px solid var(--accent);">' +
        '<b style="color: var(--accent); font-size: 11px;">' + label + '</b> ' +
        '<div style="font-size: 12px; margin-top: 2px;">' + tree[phase] + '</div></div>';
    });
    $('mavisTree').innerHTML = treeHtml;
  } else {
    $('mavisTree').innerHTML = '<span class="muted">no decision tree</span>';
  }
}

function renderCandles(d, which) {
  if (!d || d.error || !d.rows || d.rows.length === 0) {
    $(which + 'Candles').innerHTML = '<div style="padding: 8px; color: var(--muted); font-size: 11px;">' + (d && d.error || 'no data') + '</div>';
    return;
  }
  const rows = d.rows;
  const container = $(which + 'Candles');
  const W = container.clientWidth || 600;
  const H = container.clientHeight || 320;
  // Show last 60 candles (~5h on 5m)
  const slice = rows.slice(-60);
  const lo = Math.min(...slice.map(r => r.l));
  const hi = Math.max(...slice.map(r => r.h));
  const pad = (hi - lo) * 0.05 || 1;
  const ymin = lo - pad, ymax = hi + pad;
  const cw = W / slice.length;
  const bodyW = Math.max(cw * 0.7, 2);
  const bodyX = (cw - bodyW) / 2;
  // Vol bars
  const maxV = Math.max(1, ...slice.map(r => r.v || 0));
  const volH = 36;
  const topPad = 18;   // for top y-axis labels
  const botPad = 18;   // for x-axis labels
  const candleH = H - volH - topPad - botPad;
  let svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">';
  // Grid
  for (let g = 0; g < 4; g++) {
    const y = topPad + (candleH * g / 3);
    svg += '<line x1="36" y1="' + y + '" x2="' + W + '" y2="' + y + '" stroke="#1a2236" stroke-width="0.5"/>';
    const v = ymax - (ymax - ymin) * g / 3;
    svg += '<text x="2" y="' + (y + 3) + '" font-size="10" fill="#7a8aa0" font-family="Consolas">' + v.toFixed(0) + '</text>';
  }
  // Candles
  slice.forEach((r, i) => {
    const x = 36 + i * cw;
    const cwAvail = W - 36;
    const xpos = 36 + i * (cwAvail / slice.length);
    const bodyWPx = Math.max((cwAvail / slice.length) * 0.7, 1);
    const bodyX = xpos + (cwAvail / slice.length - bodyWPx) / 2;
    const yO = topPad + candleH - ((r.o - ymin) / (ymax - ymin)) * candleH;
    const yC = topPad + candleH - ((r.c - ymin) / (ymax - ymin)) * candleH;
    const yH = topPad + candleH - ((r.h - ymin) / (ymax - ymin)) * candleH;
    const yL = topPad + candleH - ((r.l - ymin) / (ymax - ymin)) * candleH;
    const up = r.c >= r.o;
    const color = up ? '#1fbf75' : '#e74c3c';
    // Wick
    svg += '<line x1="' + (xpos + cwAvail / slice.length / 2) + '" y1="' + yH + '" x2="' + (xpos + cwAvail / slice.length / 2) + '" y2="' + yL + '" stroke="' + color + '" stroke-width="1"/>';
    // Body
    const top = Math.min(yO, yC);
    const height = Math.max(1, Math.abs(yC - yO));
    svg += '<rect x="' + bodyX + '" y="' + top + '" width="' + bodyWPx + '" height="' + height + '" fill="' + color + '"/>';
    // Vol
    const vH = ((r.v || 0) / maxV) * volH;
    svg += '<rect x="' + bodyX + '" y="' + (H - botPad - vH) + '" width="' + bodyWPx + '" height="' + vH + '" fill="' + color + '" opacity="0.4"/>';
  });
  // Last price line + label
  const last = slice[slice.length - 1];
  const yLast = topPad + candleH - ((last.c - ymin) / (ymax - ymin)) * candleH;
  svg += '<line x1="36" y1="' + yLast + '" x2="' + W + '" y2="' + yLast + '" stroke="#f5b342" stroke-width="1" stroke-dasharray="3,3" opacity="0.8"/>';
  svg += '<rect x="' + (W - 78) + '" y="' + (yLast - 9) + '" width="74" height="14" fill="#f5b342" rx="2"/>';
  svg += '<text x="' + (W - 74) + '" y="' + (yLast + 2) + '" font-size="11" fill="#0b0f17" font-weight="700" font-family="Consolas">' + last.c.toFixed(2) + '</text>';
  // x-axis time labels (4 evenly spaced)
  for (let g = 0; g < 4; g++) {
    const idx = Math.floor(slice.length * g / 3);
    const r = slice[idx];
    if (r) {
      const tStr = r.t.split('T')[1] || '';
      const xpos = 36 + idx * (W - 36) / slice.length;
      svg += '<text x="' + xpos + '" y="' + (H - 4) + '" font-size="9" fill="#7a8aa0" font-family="Consolas">' + tStr + '</text>';
    }
  }
  svg += '</svg>';
  container.innerHTML = svg;
  $(which + 'SpotPill').textContent = (d.latest_close || 0).toFixed(2);
  $(which + 'CandleMeta').innerHTML = '<span>' + slice.length + ' candles · ' + d.source + ' · ' + d.interval + ' · ' + (d.latest_ts || '').split('T')[1] + '</span>';
}

function renderTerminal(t) {
  if (!t) return;
  if (t.nifty_spot) $('niftySpotPill').textContent = '· spot ' + t.nifty_spot.toFixed(2);
  if (t.banknifty_spot) $('bnfSpotPill').textContent = '· spot ' + t.banknifty_spot.toFixed(2);

  // Positions terminal
  const tbody = $('termPosTable').querySelector('tbody');
  const positions = t.positions || [];
  $('termPosCount').textContent = '(' + positions.length + ')';
  tbody.innerHTML = positions.map(p => {
    const sideCls = p.side === 'LONG' ? 'green' : 'red';
    const itm = p.itm === true ? '<span class="green">ITM</span>' : p.itm === false ? '<span class="muted">OTM</span>' : '?';
    const pnlCls = p.total_pnl > 0 ? 'green' : (p.total_pnl < 0 ? 'red' : 'muted');
    const valCls = p.value_if_sold_now > 0 ? 'green' : 'red';
    const ltpCls = p.ltp === p.entry ? 'muted' : (p.ltp > p.entry ? 'green' : 'red');
    return '<tr>'
      + '<td class="mono">' + p.symbol + '</td>'
      + '<td class="' + sideCls + '">' + p.side + '</td>'
      + '<td class="num">' + p.lots + '×' + Math.abs(p.qty) + '</td>'
      + '<td class="num">' + p.strike + '</td>'
      + '<td class="num">' + p.type + '</td>'
      + '<td class="mono">' + p.expiry + '</td>'
      + '<td class="num">' + p.dte_str + '</td>'
      + '<td>' + itm + '</td>'
      + '<td class="num muted">' + p.entry.toFixed(2) + '</td>'
      + '<td class="num ' + ltpCls + '">' + p.ltp.toFixed(2) + '</td>'
      + '<td class="num muted">' + p.est_bid.toFixed(2) + '</td>'
      + '<td class="num muted">' + p.est_ask.toFixed(2) + '</td>'
      + '<td class="num ' + pnlCls + '">' + (p.pnl_per_unit >= 0 ? '+' : '') + p.pnl_per_unit.toFixed(2) + '</td>'
      + '<td class="num ' + pnlCls + '">' + (p.total_pnl >= 0 ? '+' : '') + fmtINR(p.total_pnl) + '</td>'
      + '<td class="num ' + valCls + '"><b>' + fmtINR(p.value_if_sold_now) + '</b></td>'
      + '</tr>';
  }).join('') || '<tr><td colspan="15" class="muted">no positions</td></tr>';

  // Risk matrix — professional layout with P&L profile curve (SVG tent)
  const risk = t.risk || { strategies: [] };
  if (risk.strategies && risk.strategies.length) {
    $('riskMatrix').innerHTML = risk.strategies.map(r => {
      const pnlNow = r.current_pnl;
      const pnlCls = pnlNow > 0 ? 'green' : (pnlNow < 0 ? 'red' : 'muted');
      // P&L profile "tent" SVG
      const sc = (t.scenarios || {})[r.underlying];
      let svg = '';
      if (sc && sc.scenarios && sc.scenarios.length) {
        const W = 320, H = 70, padL = 6, padR = 6, padT = 6, padB = 14;
        const innerW = W - padL - padR, innerH = H - padT - padB;
        const spots = sc.scenarios.map(s => s.spot);
        const minS = Math.min(...spots), maxS = Math.max(...spots);
        const maxAbsPnl = Math.max(...sc.scenarios.map(s => Math.abs(s.pnl)), 1);
        const xOf = s => padL + ((s - minS) / (maxS - minS || 1)) * innerW;
        const yOf = p => padT + (1 - p / maxAbsPnl) * innerH;
        // Build a smooth tent: line with profit zone filled green, loss zone filled red
        const points = sc.scenarios.map(s => xOf(s.spot) + ',' + yOf(s.pnl));
        const polyline = points.join(' ');
        // Profit zone polygon: from zero-line up through curve down
        const zeroY = yOf(0);
        const profitPath = 'M' + xOf(minS) + ',' + zeroY + ' L' + points.join(' L') + ' L' + xOf(maxS) + ',' + zeroY + ' Z';
        svg += '<svg class="pnl-chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">'
          + '<defs><linearGradient id="g' + r.underlying + '" x1="0" y1="0" x2="0" y2="1">'
          + '<stop offset="0%" stop-color="#1fbf75" stop-opacity="0.35"/>'
          + '<stop offset="100%" stop-color="#1fbf75" stop-opacity="0.02"/>'
          + '</linearGradient></defs>'
          + '<line x1="' + padL + '" y1="' + zeroY + '" x2="' + (W - padR) + '" y2="' + zeroY + '" stroke="#3a4258" stroke-width="0.5" stroke-dasharray="2,2"/>'
          + '<path d="' + profitPath + '" fill="url(#g' + r.underlying + ')"/>'
          + '<polyline points="' + polyline + '" fill="none" stroke="#1fbf75" stroke-width="1.5"/>'
          // Current spot marker
          + '<line x1="' + xOf(sc.spot) + '" y1="' + padT + '" x2="' + xOf(sc.spot) + '" y2="' + (H - padB) + '" stroke="#f5b342" stroke-width="1.2" stroke-dasharray="3,2"/>'
          + '<circle cx="' + xOf(sc.spot) + '" cy="' + yOf(pnlNow) + '" r="3" fill="#f5b342" stroke="#0b0f17" stroke-width="1.5"/>'
          + '<text x="' + xOf(sc.spot) + '" y="' + (H - 2) + '" text-anchor="middle" font-size="9" fill="#f5b342" font-family="Consolas">' + sc.spot.toFixed(0) + '</text>'
          + '</svg>';
      }
      return '<div style="margin-bottom: 10px;">'
        + '<div class="ic-header">'
        +   '<span class="ic-header-name">' + r.underlying + ' Iron Condor</span>'
        +   '<span class="ic-strikes">PE ' + r.pe_long_strike + '/' + r.pe_short_strike + ' · CE ' + r.ce_short_strike + '/' + r.ce_long_strike + '</span>'
        +   '<span class="ic-header-spot">spot ' + ((sc && sc.spot) ? sc.spot.toFixed(2) : '—') + '</span>'
        + '</div>'
        + svg
        + '<div class="ic-row"><span class="ic-k">Net premium</span><span class="ic-v" style="color:#4f9cff">₹' + r.net_premium.toFixed(2) + ' / share</span></div>'
        + '<div class="ic-row"><span class="ic-k">Max profit @ expiry</span><span class="ic-v" style="color:#1fbf75">+₹' + r.max_profit.toLocaleString('en-IN') + '</span></div>'
        + '<div class="ic-row"><span class="ic-k">Max loss @ expiry</span><span class="ic-v" style="color:#e74c3c">−₹' + r.max_loss.toLocaleString('en-IN') + '</span></div>'
        + '<div class="ic-row"><span class="ic-k">Breakevens</span><span class="ic-v">' + r.be_low.toFixed(2) + ' — ' + r.be_high.toFixed(2) + '</span></div>'
        + '<div class="ic-row"><span class="ic-k">Current P&amp;L</span><span class="ic-v ' + pnlCls + '">' + (pnlNow >= 0 ? '+' : '−') + '₹' + Math.abs(pnlNow).toLocaleString('en-IN') + '</span></div>'
        + '</div>';
    }).join('');
  } else {
    $('riskMatrix').innerHTML = '<div style="padding: 20px; text-align: center; color: var(--muted);">no iron condor detected in positions</div>';
  }

  // Scenarios — professional table with proper bars, fixed labeling
  const sc = t.scenarios || {};
  const scKeys = Object.keys(sc);
  if (scKeys.length === 0) {
    $('scenariosBody').innerHTML = '<div style="padding: 20px; text-align: center; color: var(--muted);">no scenarios</div>';
  } else {
    const maxAbs = (arr) => Math.max(...arr.map(s => Math.abs(s.pnl)), 1);
    $('scenariosBody').innerHTML = scKeys.map(und => {
      const u = sc[und];
      const maxA = maxAbs(u.scenarios);
      const maxProf = Math.max(...u.scenarios.map(s => s.pnl));
      const maxLoss = Math.min(...u.scenarios.map(s => s.pnl));
      const curIdx = u.scenarios.findIndex(s => Math.abs(s.spot - u.spot) < 50);

      // BUGFIX: only mark EDGE strikes as max profit / max loss (the ones closest
      // to the current spot within their zone), not every row matching the value.
      // We pick: for max profit zone, the row at the center (or the current spot if inside).
      // For max loss zone, the closest row to the spot.
      const profitIdxs = u.scenarios.map((s, i) => s.pnl === maxProf ? i : -1).filter(i => i >= 0);
      const lossIdxs = u.scenarios.map((s, i) => s.pnl === maxLoss ? i : -1).filter(i => i >= 0);
      const profitEdgeIdx = curIdx >= 0 && profitIdxs.includes(curIdx)
        ? curIdx
        : profitIdxs[Math.floor(profitIdxs.length / 2)];  // center of profit zone
      const lossEdgeIdx = lossIdxs.length > 0 ? lossIdxs[lossIdxs.length - 1] : -1;  // closest edge to spot

      return '<div style="margin-bottom: 14px;">'
        + '<div class="ic-header">'
        +   '<span class="ic-header-name">' + und + '</span>'
        +   '<span class="ic-strikes">spot ' + u.spot.toFixed(2) + '</span>'
        + '</div>'
        + '<table class="pnl-table">'
        + '<thead><tr><th>Strike</th><th style="text-align:right">P&amp;L</th><th style="width:50%">At-expiry P&amp;L</th></tr></thead><tbody>'
        + u.scenarios.map((s, i) => {
          const sign = s.pnl >= 0 ? '+' : '−';
          const pnlCls = s.pnl > 0 ? 'ic-pnl-num green' : (s.pnl < 0 ? 'ic-pnl-num red' : 'ic-pnl-num muted');
          const w = Math.max(2, Math.round((Math.abs(s.pnl) / maxA) * 100));
          const rowCls = i === curIdx ? 'pnl-row current' : (i === profitEdgeIdx || i === lossEdgeIdx ? 'pnl-row edge' : '');
          // Bar alignment: positive P&L bars grow right from left, negative grow left from right
          const bar = s.pnl >= 0
            ? '<div class="pnl-bar pos" style="left:0;width:' + w + '%;"></div>'
            : '<div class="pnl-bar neg" style="right:0;width:' + w + '%;"></div>';
          // Tag — only ONE label per zone, not all matching rows
          let tag = '';
          if (i === curIdx) tag = '<span class="pnl-label-tag current">spot</span>';
          else if (i === profitEdgeIdx && i !== curIdx) tag = '<span class="pnl-label-tag maxprof">max profit</span>';
          else if (i === lossEdgeIdx && i !== curIdx) tag = '<span class="pnl-label-tag maxloss">max loss</span>';
          return '<tr class="' + rowCls + '">'
            + '<td>' + s.spot + tag + '</td>'
            + '<td style="text-align:right" class="' + pnlCls + '"><b>' + sign + '₹' + Math.abs(s.pnl).toLocaleString('en-IN') + '</b></td>'
            + '<td class="pnl-bar-cell">' + bar + '</td>'
            + '</tr>';
        }).join('')
        + '</tbody></table>'
        + '<div class="pnl-zone">'
        +   '<span><span class="pnl-zone-swatch" style="background:#1fbf75"></span>Profit zone (max ₹' + maxProf.toLocaleString('en-IN') + ')</span>'
        +   '<span style="margin-left:12px"><span class="pnl-zone-swatch" style="background:#e74c3c"></span>Loss zone (max −₹' + Math.abs(maxLoss).toLocaleString('en-IN') + ')</span>'
        + '</div>'
        + '</div>';
    }).join('');
  }
}

function renderOC(d) {
  if (!d) return;
  const tbody = $('ocTable').querySelector('tbody');
  if (d.error && (!d.calls || !d.calls.length)) {
    $('ocTable').querySelector('tbody').innerHTML = '<tr><td colspan="11" class="muted">' + d.error + '</td></tr>';
    $('ocNote').textContent = 'NSE blocked from this IP, Kite MCP down. Option chain unavailable.';
    return;
  }
  $('ocMeta').textContent = '· spot ' + (d.spot || 0).toFixed(2) + ' · ' + (d.source || '');
  $('ocNote').textContent = d.source || '—';
  // Build strike map
  const map = {};
  (d.calls || []).forEach(c => { map[c.strike] = map[c.strike] || {}; map[c.strike].CE = c; });
  (d.puts || []).forEach(p => { map[p.strike] = map[p.strike] || {}; map[p.strike].PE = p; });
  const strikes = Object.keys(map).map(s => +s).sort((a, b) => a - b);
  // ATM = nearest to spot
  if (d.spot) {
    strikes.sort((a, b) => Math.abs(a - d.spot) - Math.abs(b - d.spot));
  }
  tbody.innerHTML = strikes.slice(0, 21).map(s => {
    const row = map[s] || {};
    const ce = row.CE || {};
    const pe = row.PE || {};
    const isAtm = d.spot && Math.abs(s - d.spot) < 50;
    const atm = isAtm ? 'background: rgba(245,179,66,0.18);' : '';
    return '<tr style="' + atm + '">'
      + '<td class="num"><b>' + s + '</b></td>'
      + '<td class="num">' + (ce.ltp || 0).toFixed(2) + '</td>'
      + '<td class="num muted">' + (ce.bid || 0).toFixed(2) + '</td>'
      + '<td class="num muted">' + (ce.ask || 0).toFixed(2) + '</td>'
      + '<td class="num muted">' + (ce.oi || 0).toLocaleString('en-IN') + '</td>'
      + '<td class="num muted">' + (ce.iv || 0).toFixed(1) + '</td>'
      + '<td class="num">' + (pe.ltp || 0).toFixed(2) + '</td>'
      + '<td class="num muted">' + (pe.bid || 0).toFixed(2) + '</td>'
      + '<td class="num muted">' + (pe.ask || 0).toFixed(2) + '</td>'
      + '<td class="num muted">' + (pe.oi || 0).toLocaleString('en-IN') + '</td>'
      + '<td class="num muted">' + (pe.iv || 0).toFixed(1) + '</td>'
      + '</tr>';
  }).join('') || '<tr><td colspan="11" class="muted">no strikes</td></tr>';
}

function renderKv(obj) {
  return Object.keys(obj).map(k => '<div class="kv"><span class="k">' + k + '</span><span class="v">' + (obj[k] == null ? '--' : obj[k]) + '</span></div>').join('');
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

setInterval(poll, 2500);
poll();
</script>

</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            try:
                state = aggregate_state()
                body = json.dumps(state, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
        elif self.path.startswith("/api/candles") or self.path.startswith("/api/option_chain") or self.path.startswith("/api/terminal") or self.path.startswith("/api/quant_brain") or self.path.startswith("/api/mavis_trades") or self.path.startswith("/api/mavis_events") or self.path.startswith("/api/mavis_state"):
            try:
                body = handle_api(self.path).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err)))
                self.end_headers()
                self.wfile.write(err)
        else:
            self.send_response(404)
            self.end_headers()


def handle_api(path):
    """Dispatch /api/candles, /api/option_chain, /api/terminal, /api/quant_brain, /api/mavis_trades."""
    from urllib.parse import urlparse, parse_qs
    u = urlparse(path)
    qs = parse_qs(u.query)
    if u.path == "/api/candles":
        sym = (qs.get("symbol", ["NIFTY"])[0]).upper()
        interval = qs.get("interval", ["5m"])[0]
        period = qs.get("period", ["1d"])[0]
        return json.dumps(get_candles(sym, interval, period), default=str)
    if u.path == "/api/option_chain":
        sym = (qs.get("symbol", ["NIFTY"])[0]).upper()
        expiry = qs.get("expiry", ["2026-08-26"])[0]
        spot = float(qs.get("spot", ["0"])[0] or 0)
        return json.dumps(get_option_chain(sym, expiry, spot), default=str)
    if u.path == "/api/terminal":
        return json.dumps(get_terminal(), default=str)
    if u.path == "/api/quant_brain":
        return json.dumps(get_quant_brain(), default=str)
    if u.path == "/api/mavis_trades":
        return json.dumps(get_mavis_trades(), default=str)
    if u.path == "/api/mavis_events":
        return json.dumps(get_mavis_events(), default=str)
    if u.path == "/api/mavis_state":
        return json.dumps(get_mavis_realtime_state(), default=str)
    return json.dumps({"error": "unknown api"})


def get_quant_brain():
    """Read the latest quant_brain.json. Cached 30s."""
    def _read():
        p = os.path.join(DCACHE, "quant_brain.json")
        return _read_json(p, {"available": False})
    return _cached("qb", _read, 30.0)


def get_mavis_trades():
    """Read Mavis's actual trade decisions (written by Mavis-the-AI, not by template).

    Transforms v3 schema (mavis_decision + primary_plan + alternatives) into a
    v2-compatible list of 'trades' with type=primary/alternative/no_trade so the
    dashboard's renderMavisPlan() can display them uniformly.
    """
    p = os.path.join(DCACHE, "mavis_trades.json")
    raw = _read_json(p, {})
    if not raw:
        return {"available": False, "trades": []}
    # v2 shape already? pass through with availability flag
    if "trades" in raw and isinstance(raw.get("trades"), list):
        return {"available": True, **raw}
    # v3 shape -> transform
    decision = raw.get("mavis_decision") or {}
    action = str(decision.get("action", "WAIT")).upper()
    bias = str(decision.get("bias", ""))
    confidence = decision.get("confidence", 0)
    reason_short = str(decision.get("reason_short", ""))
    trades = []
    # Primary plan
    pp = raw.get("primary_plan") or {}
    if pp:
        # Build entry_trigger text from conditions
        entry_sig = pp.get("entry_signal", {}) or {}
        conds = entry_sig.get("conditions_all_required", [])
        skips = entry_sig.get("skip_if", [])
        et = "Conditions: " + "; ".join(conds[:4]) if conds else "—"
        if skips:
            et += "  |  SKIP if: " + "; ".join(skips[:3])
        # Target premium
        ep = pp.get("expected_premiums_rupees", {}) or {}
        net_credit = ep.get("net_credit_per_share", "—")
        total_credit = ep.get("total_credit_lot1", "—")
        target = f"{net_credit}/share  ({total_credit})"
        # Stop
        ml = pp.get("max_loss_rupees", {}) or {}
        single = ml.get("realistic_max_loss_single_wing", "—")
        stop = f"single wing: {single}"
        # Window
        win = pp.get("entry_window_ist", "—")
        trades.append({
            "type": "primary",
            "name": pp.get("name", "Primary plan"),
            "logic": pp.get("rationale_data_driven", "—")[:240],
            "instrument": pp.get("structure", "—")[:200],
            "entry_trigger": et,
            "entry_window": win,
            "target_premium": target,
            "stop_loss": stop,
            "exits": pp.get("exit_rules", {}),
            "adjustments": pp.get("adjustments", {}),
        })
    # Alternatives
    alts = raw.get("alternative_plans") or {}
    if isinstance(alts, dict):
        for k, a in alts.items():
            t_type = "no_trade" if a.get("name", "").lower().startswith("no trade") else "alternative"
            trades.append({
                "type": t_type,
                "name": a.get("name", k),
                "logic": a.get("rationale", a.get("trigger", "—"))[:200],
                "instrument": a.get("instrument", "—"),
                "entry_trigger": a.get("trigger", "—"),
                "target_premium": a.get("target", "—"),
                "stop_loss": a.get("stop", "—"),
            })
    # BANKNIFTY decision
    bnf = raw.get("banknifty_decision") or {}
    if bnf.get("action") == "BLOCK":
        trades.append({
            "type": "no_trade",
            "name": "BANKNIFTY blocked",
            "logic": bnf.get("reason", "—")[:240],
            "instrument": "BANKNIFTY",
            "entry_trigger": "BLOCKED by Mavis",
            "target_premium": "—",
            "stop_loss": "—",
        })
    return {
        "available": True,
        "schema_version": raw.get("schema_version", "v?"),
        "generated_at": raw.get("generated_at", ""),
        "valid_for": raw.get("valid_for_session", raw.get("valid_for_date", "")),
        "decision": action,
        "decision_confidence": confidence,
        "decision_bias": bias,
        "decision_reason": reason_short,
        "decision_at": raw.get("last_decision_at", raw.get("generated_at", "")),
        "premarket_check": raw.get("premarket_check"),
        "trades": trades,
        "research": raw.get("research_at_generation", {}),
        "intraday_decision_tree": raw.get("intraday_decision_tree", {}),
        "risk_management": raw.get("risk_management", {}),
        "what_makes_this_different": raw.get("what_makes_this_different_from_template", {}),
        "data_snapshot": raw.get("data_snapshot", {}),
    }


def get_mavis_events(limit: int = 20) -> dict:
    """Read the last N events from mavis_events.jsonl (real-time event stream)."""
    p = os.path.join(DCACHE, "mavis_events.jsonl")
    out = {"available": False, "events": [], "count": 0}
    if not os.path.exists(p):
        return out
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        # Last N
        recent = lines[-limit:] if len(lines) > limit else lines
        events = []
        for ln in recent:
            try:
                events.append(json.loads(ln))
            except Exception:
                pass
        out["available"] = True
        out["events"] = events
        out["count"] = len(events)
        out["total_in_log"] = len(lines)
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


def get_mavis_realtime_state() -> dict:
    """Read mavis_realtime_state.json — current snapshot + Mavis's last thought."""
    p = os.path.join(DCACHE, "mavis_realtime_state.json")
    return _read_json(p, {"available": False, "current": {}, "mavis_state": {}})


def get_candles(symbol, interval, period):
    """yfinance OHLC candles for NIFTY/BANKNIFTY."""
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "NIFTY50": "^NSEI", "NSEBANK": "^NSEBANK"}.get(symbol, symbol)
    try:
        import yfinance as yf
        t = yf.Ticker(yf_sym)
        hist = t.history(period=period, interval=interval)
        if hist is None or len(hist) == 0:
            return {"error": "no data", "symbol": symbol}
        out = []
        for ts, row in hist.iterrows():
            out.append({
                "t": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "o": round(float(row["Open"]), 2),
                "h": round(float(row["High"]), 2),
                "l": round(float(row["Low"]), 2),
                "c": round(float(row["Close"]), 2),
                "v": int(row.get("Volume", 0)) if not pd_isnan(row.get("Volume", 0)) else 0,
            })
        return {
            "symbol": symbol, "interval": interval, "period": period,
            "source": "yfinance",
            "rows": out,
            "latest_close": out[-1]["c"] if out else None,
            "latest_ts": out[-1]["t"] if out else None,
            "ts": datetime.now(IST).isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}


def pd_isnan(v):
    try:
        import math
        return isinstance(v, float) and math.isnan(v)
    except Exception:
        return False


def get_option_chain(symbol, expiry_iso, spot):
    """Try yfinance for option chain; fall back to NSE scrape; else graceful n/a."""
    out = {"symbol": symbol, "expiry": expiry_iso, "spot": spot, "calls": [], "puts": [],
           "source": None, "ts": datetime.now(IST).isoformat()}
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol)
    if not yf_sym:
        out["error"] = "unknown symbol"
        return out

    # yfinance route
    try:
        import yfinance as yf
        t = yf.Ticker(yf_sym)
        exps = list(t.options or [])
        # Find closest expiry to requested
        target = expiry_iso  # YYYY-MM-DD
        chosen = None
        for e in exps:
            ed = e if "-" in e else e  # yf already uses YYYY-MM-DD
            if ed == target:
                chosen = e
                break
        if not chosen and exps:
            chosen = exps[0]
        if chosen:
            oc = t.option_chain(chosen)
            for df, opt_type in [(oc.calls, "CE"), (oc.puts, "PE")]:
                if spot <= 0:
                    spot = float(df["strike"].iloc[len(df)//2]) if len(df) else 0
                for _, r in df.iterrows():
                    strike = float(r["strike"])
                    if spot <= 0 or abs(strike - spot) < 600:
                        out[("calls" if opt_type == "CE" else "puts")].append({
                            "strike": int(strike),
                            "type": opt_type,
                            "ltp": float(r.get("lastPrice", 0) or 0),
                            "bid": float(r.get("bid", 0) or 0),
                            "ask": float(r.get("ask", 0) or 0),
                            "volume": int(r.get("volume", 0) or 0),
                            "oi": int(r.get("openInterest", 0) or 0),
                            "iv": round(float(r.get("impliedVolatility", 0) or 0), 2),
                        })
            out["source"] = f"yfinance:{chosen}"
            out["spot"] = spot
            out["calls"].sort(key=lambda x: x["strike"])
            out["puts"].sort(key=lambda x: x["strike"])
            return out
    except Exception as e:
        out["yfinance_error"] = str(e)[:200]

    out["error"] = "option chain not available (NSE blocked, yfinance has no 0DTE for IN indices)"
    return out


def get_terminal():
    """Full trading terminal view: positions, candles hint, risk matrix, scenario P&L."""
    pf = _read_json(os.path.join(DCACHE, "paper_state.json"), {})
    pos_dict = pf.get("positions", {}) if isinstance(pf.get("positions"), dict) else {}

    # Get spot for NIFTY/BANKNIFTY (from thesis xmkt or paper_state)
    th = _read_json(os.path.join(DCACHE, "thesis", "latest.json"), {})
    xmkt = (th.get("data") or {}).get("xmkt") or {}
    nifty_spot = xmkt.get("nifty_spot")
    banknifty_spot = xmkt.get("banknifty_spot")
    vix = xmkt.get("india_vix")

    # FIX 2026-08-26 (item #6): try to get LIVE option LTPs from yfinance for our positions.
    # This supplements the (often-stale) bot's paper_state.json LTP field.
    live_option_ltps = get_live_option_ltps(list(pos_dict.keys()))

    # Build position rows
    LOT_SIZE = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 25, "MIDCPNIFTY": 50}
    positions = []
    for sym, p in pos_dict.items():
        sym_u = str(sym).upper()
        if "NIFTY" in sym_u and "BANKNIFTY" not in sym_u:
            und, lot = "NIFTY", 75
        elif "BANKNIFTY" in sym_u:
            und, lot = "BANKNIFTY", 30
        else:
            und, lot = "?", 1
        qty = int(p.get("qty", 0) or 0)
        avg = float(p.get("avg_price", 0) or 0)
        ltp = float(p.get("ltp", 0) or 0)
        # Use ltp from paper_state; if ltp=avg exactly, treat as "no live tick yet"
        # Compute P&L: long = (ltp-avg)*qty, short = (avg-ltp)*abs(qty)
        if qty > 0:
            pnl_per_unit = ltp - avg
        else:
            pnl_per_unit = avg - ltp
        total_pnl = pnl_per_unit * abs(qty)
        # ITM/OTM: for CE, ITM if spot > strike; for PE, ITM if spot < strike
        otype = "PE" if "PE" in sym_u else "CE" if "CE" in sym_u else "?"
        # Extract strike
        import re
        m = re.search(r"(\d{4,5})(CE|PE)", sym_u)
        strike = int(m.group(1)) if m else 0
        spot_ref = nifty_spot if und == "NIFTY" else banknifty_spot if und == "BANKNIFTY" else 0
        if otype == "CE" and spot_ref and strike:
            itm = spot_ref > strike
        elif otype == "PE" and spot_ref and strike:
            itm = spot_ref < strike
        else:
            itm = None
        # DTE
        expiry = p.get("expiry", "")
        dte = ""
        if expiry:
            try:
                ed = datetime.strptime(expiry, "%Y-%m-%d").date()
                dte = (ed - datetime.now(IST).date()).days
            except Exception:
                pass
        # Bid/ask estimates: assume 0.5% spread for liquid 0DTE, 1% for illiquid
        if ltp > 0:
            spread_pct = 0.005 if dte == 0 else 0.01
            est_bid = round(ltp * (1 - spread_pct), 2)
            est_ask = round(ltp * (1 + spread_pct), 2)
        else:
            est_bid = est_ask = 0
        # Value if sold now: for our SHORT positions, we BUY to close (pay ask).
        # For LONG positions, we SELL to close (receive bid).
        if qty < 0:  # short
            close_value = -est_ask * abs(qty)  # cost to buy back
        else:  # long
            close_value = est_bid * abs(qty)  # cash received
        # Days-to-expiry hour countdown
        dte_str = f"{dte}D" if isinstance(dte, int) and dte > 0 else ("0D" if dte == 0 else str(dte) if dte else "?")

        positions.append({
            "symbol": sym,
            "underlying": und,
            "side": "SHORT" if qty < 0 else "LONG",
            "qty": qty,
            "lots": round(abs(qty) / lot, 2) if lot else 0,
            "lot_size": lot,
            "strike": strike,
            "type": otype,
            "expiry": expiry,
            "dte": dte,
            "dte_str": dte_str,
            "entry": round(avg, 2),
            "ltp": round(ltp, 2),
            "ltp_source": "live_yfinance" if (live_option_ltps.get(sym) and live_option_ltps[sym] > 0) else "bot_paper_state",
            "spread_pct": spread_pct,
            "est_bid": est_bid,
            "est_ask": est_ask,
            "itm": itm,
            "pnl_per_unit": round(pnl_per_unit, 2),
            "total_pnl": round(total_pnl, 2),
            "value_if_sold_now": round(close_value, 2),
        })

    positions.sort(key=lambda x: (x["underlying"], x["strike"], x["type"]))

    # Risk matrix: per strategy (NIFTY condor, BANKNIFTY condor)
    risk = compute_risk(positions)

    # Scenarios: P&L at various underlying levels (the standard "what if" table)
    scenarios = compute_scenarios(positions, nifty_spot, banknifty_spot)

    return {
        "ts": datetime.now(IST).isoformat(),
        "nifty_spot": nifty_spot,
        "banknifty_spot": banknifty_spot,
        "vix": vix,
        "positions": positions,
        "risk": risk,
        "scenarios": scenarios,
    }


def compute_scenarios(positions, nifty_spot, banknifty_spot):
    """For each underlying, build a 'P&L at various spot prices' table."""
    out = {}
    by_und = {}
    for p in positions:
        by_und.setdefault(p["underlying"], []).append(p)
    for und, legs in by_und.items():
        spot = nifty_spot if und == "NIFTY" else (banknifty_spot if und == "BANKNIFTY" else 0)
        if spot <= 0:
            continue
        # Auto-range: ±2% of spot, 11 steps
        span = int(spot * 0.02 / 50) * 50  # round to 50 for NIFTY, 100 for BANKNIFTY
        if "BANKNIFTY" in und:
            step = 100
        else:
            step = 50
        # Build strikes info
        ce_short = next((p for p in legs if p["type"] == "CE" and p["side"] == "SHORT"), None)
        pe_short = next((p for p in legs if p["type"] == "PE" and p["side"] == "SHORT"), None)
        if not ce_short or not pe_short:
            continue
        range_low = pe_short["strike"] - 2 * step - 100
        range_high = ce_short["strike"] + 2 * step + 100
        if "BANKNIFTY" in und:
            range_low = pe_short["strike"] - 300
            range_high = ce_short["strike"] + 300
        scenarios = []
        for test_spot in range(range_low, range_high + 1, step):
            pnl = 0
            for p in legs:
                if p["type"] == "CE":
                    intrinsic = max(0, test_spot - p["strike"])
                else:
                    intrinsic = max(0, p["strike"] - test_spot)
                if p["side"] == "SHORT":
                    pnl += (p["entry"] - intrinsic) * abs(p["qty"])
                else:
                    pnl += (intrinsic - p["entry"]) * abs(p["qty"])
            scenarios.append({"spot": test_spot, "pnl": round(pnl)})
        out[und] = {"spot": round(spot, 2), "scenarios": scenarios}
    return out


def compute_risk(positions):
    """Compute iron condor P&L matrix at expiry for each underlying."""
    risk = {"strategies": [], "summary": {}}
    by_und = {}
    for p in positions:
        und = p.get("underlying", "?")
        by_und.setdefault(und, []).append(p)
    for und, legs in by_und.items():
        # Group by CE/PE sides
        ce_short = next((p for p in legs if p["type"] == "CE" and p["side"] == "SHORT"), None)
        ce_long = next((p for p in legs if p["type"] == "CE" and p["side"] == "LONG"), None)
        pe_short = next((p for p in legs if p["type"] == "PE" and p["side"] == "SHORT"), None)
        pe_long = next((p for p in legs if p["type"] == "PE" and p["side"] == "LONG"), None)
        if not all([ce_short, ce_long, pe_short, pe_long]):
            continue
        # Premium collected
        net_premium = (ce_short["entry"] - ce_long["entry"]) + (pe_short["entry"] - pe_long["entry"])
        net_premium_per_share = net_premium
        # spread widths (always positive)
        ce_spread = abs(ce_long["strike"] - ce_short["strike"])
        pe_spread = abs(pe_long["strike"] - pe_short["strike"])
        # breakevens
        be_low = pe_short["strike"] - net_premium_per_share
        be_high = ce_short["strike"] + net_premium_per_share
        # Use abs of qty for the short legs (they're stored as negative)
        abs_ce_short = abs(ce_short["qty"])
        abs_pe_short = abs(pe_short["qty"])
        abs_ce_long = abs(ce_long["qty"])
        abs_pe_long = abs(pe_long["qty"])
        # max loss: spread - premium, applied to the LONG-protection qty
        max_loss = (max(ce_spread, pe_spread) - net_premium_per_share) * min(abs_ce_long, abs_pe_long)
        # max profit: full premium kept, applied to the SHORT leg qty
        max_profit = net_premium_per_share * min(abs_ce_short, abs_pe_short)
        # Current value (mid): what we'd receive if we closed now
        # = +bid * long_qty - ask * short_qty
        cur_val = (ce_long["est_bid"] * abs_ce_long) - (ce_short["est_ask"] * abs_ce_short) \
                + (pe_long["est_bid"] * abs_pe_long) - (pe_short["est_ask"] * abs_pe_short)
        # Current value (mid)
        risk["strategies"].append({
            "underlying": und,
            "net_premium": round(net_premium, 2),
            "ce_spread": ce_spread,
            "pe_spread": pe_spread,
            "be_low": round(be_low, 2),
            "be_high": round(be_high, 2),
            "max_profit": round(max_profit, 2),
            "max_loss": round(max_loss, 2),
            "current_value": round(cur_val, 2),
            "current_pnl": round(cur_val + net_premium * min(abs_ce_short, abs_pe_short), 2),
            "ce_short_strike": ce_short["strike"],
            "ce_long_strike": ce_long["strike"],
            "pe_short_strike": pe_short["strike"],
            "pe_long_strike": pe_long["strike"],
        })
    return risk


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[live_dashboard] http://localhost:{PORT}  thread-per-request, 1s poll, single-screen unified view", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
