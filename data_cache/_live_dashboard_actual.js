
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
  $('realized').className = 'metric-value ' + signClass(acc.realized_pnl);
  $('unrealized').textContent = fmtINR(acc.unrealized_pnl);
  $('unrealized').className = 'metric-value ' + signClass(acc.unrealized_pnl);
  $('total').textContent = fmtINR(acc.total_value);
  $('total').className = 'metric-value accent';

  // bot health kv
  $('botKv').innerHTML = renderKv({
    'PID': {value: bot.pid || '--', color: 'accent'},
    'State': {value: bot.state || '--', color: bot.state === 'running' ? 'green' : (bot.state === 'paused' ? 'yellow' : 'red')},
    'Uptime': {value: fmtUptime(bot.uptime_sec), color: 'cyan'},
    'Tick': {value: bot.tick, color: 'accent'},
    'Last liveness age': {value: (bot.last_liveness_age_sec || 0).toFixed(1) + 's', color: 'muted'},
    'Main thread': {value: bot.main_thread_alive ? 'alive ✓' : 'DEAD ✗', color: bot.main_thread_alive ? 'green' : 'red'},
    'Trades today': {value: bot.trades_today || 0, color: 'muted'},
    'Open positions': {value: bot.open_positions, color: 'accent'},
    'Paused': {value: bot.is_paused ? 'YES' : 'no', color: bot.is_paused ? 'yellow' : 'green'},
    'Risk preset': {value: bot.risk_preset || 'base', color: 'muted'},
  });

  // market kv (live from bot :8502)
  const mk = s.market || {};
  $('marketKv').innerHTML = renderKv({
    'NIFTY spot': {value: mk.nifty_spot || 'n/a', color: 'accent'},
    'BANKNIFTY spot': {value: mk.banknifty_spot || 'n/a', color: 'accent'},
    'VIX (live)': {value: (mk.vix || 0).toFixed(2), color: 'cyan'},
    'PCR': {value: mk.pcr || 'n/a', color: 'muted'},
    'Max pain (NIFTY)': {value: mk.max_pain_nifty || 'n/a', color: 'muted'},
    'Max pain (BANKNIFTY)': {value: mk.max_pain_banknifty || 'n/a', color: 'muted'},
    'FII net OI': {value: mk.fii_net_oi || 'n/a', color: 'muted'},
    'Data source': {value: mk.data_source || '--', color: 'cyan'},
    'Risk preset': {value: mk.risk_preset || 'base', color: 'muted'}
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
    $('brainKv').innerHTML =
      '<div class="kv-row"><span class="kv-k">NIFTY</span><span class="kv-v accent">' + (t.nifty_spot ? t.nifty_spot.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv-row"><span class="kv-k">BANKNIFTY</span><span class="kv-v accent">' + (t.banknifty_spot ? t.banknifty_spot.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv-row"><span class="kv-k">VIX</span><span class="kv-v cyan">' + (t.india_vix ? t.india_vix.toFixed(2) : '--') + '</span></div>' +
      '<div class="kv-row"><span class="kv-k">Regime</span><span class="kv-v ' + regCls + '">' + (t.regime || '--') + '</span></div>' +
      '<div class="kv-row"><span class="kv-k">Bias</span><span class="kv-v ' + biasCls + '">' + (t.bias || '--') + ' (conf ' + ((t.confidence || 0) * 100).toFixed(0) + '%)</span></div>' +
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
    $('brainKv').innerHTML = '<span class="muted">no thesis yet — premarket 08:25 cron hasn\'t run today</span>';
  }

  // brain
  const br = s.brain || {};
  const la = br.last_action || {};
  $('brainKv').innerHTML = renderKv({
    'Bias': {value: la.bias || '--', color: la.bias === 'bullish' ? 'green' : (la.bias === 'bearish' ? 'red' : 'muted')},
    'Source': {value: la.source || '--', color: 'accent'},
    'Max positions': {value: la.max_positions, color: 'cyan'},
    'Actions': {value: (la.actions || []).length, color: (la.actions || []).length > 0 ? 'yellow' : 'muted'},
    'Note': {value: la.note || '--', color: 'muted'},
    'Updated': {value: la.ist_time || '--', color: 'muted'}
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
    const regCls = t.regime === 'range' ? 'green' : (t.regime === 'trend' ? 'accent' : 'yellow');
    const biasCls = t.bias === 'bullish' ? 'green' : (t.bias === 'bearish' ? 'red' : 'muted');
    $('thesisBody').innerHTML =
      '<div class="kv-grid">'
      + '<div class="kv-row"><span class="kv-k">Regime</span><span class="kv-v ' + regCls + '">' + (t.regime || '--') + '</span></div>'
      + '<div class="kv-row"><span class="kv-k">Bias</span><span class="kv-v ' + biasCls + '">' + (t.bias || '--') + '</span></div>'
      + '<div class="kv-row"><span class="kv-k">Confidence</span><span class="kv-v accent">' + (t.confidence != null ? (t.confidence * 100).toFixed(0) + '%' : '--') + '</span></div>'
      + '<div class="kv-row"><span class="kv-k">Risk budget</span><span class="kv-v cyan">' + (t.risk_budget_pct != null ? t.risk_budget_pct + '%' : (t.risk_budget || '--')) + '</span></div>'
      + '<div class="kv-row"><span class="kv-k">Updated</span><span class="kv-v muted">' + (t.updated_at || t.ts || t.ist_time || '--') + '</span></div>'
      + '</div>'
      + (t.narrative ? '<div style="margin-top:10px; padding:8px 10px; background:rgba(155,107,255,0.06); border-left:2px solid var(--purple); border-radius:4px; font-size:11.5px; line-height:1.5; color:var(--fg)">' + t.narrative + '</div>' : '');
  } else {
    $('thesisBody').innerHTML = '<div style="padding:12px; text-align:center; color:var(--muted); font-size:12px">no thesis yet — pre-market 08:25 cron hasn\'t run today</div>';
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

  // reset history (null-safe — element optional)
  const resetEl = $('resetBody');
  if (resetEl) {
    const rh = s.reset_history || [];
    if (rh.length) {
      resetEl.innerHTML = rh.slice(-5).map(r => '<div class="kv"><span class="k">' + r.at + '</span><span class="v">'
        + (r.reason || '?') + ' · capital ₹' + (r.capital || 0).toLocaleString('en-IN') + '</span></div>').join('')
        + (rh.length > 5 ? '<div class="sub">…+' + (rh.length - 5) + ' more</div>' : '');
    } else {
      resetEl.innerHTML = '<span class="muted">no resets recorded</span>';
    }
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
  // obj: {label: value} or {label: {value, color}}
  return Object.keys(obj).map(k => {
    const v = obj[k];
    if (v && typeof v === 'object' && 'value' in v) {
      return '<div class="kv-row"><span class="kv-k">' + k + '</span><span class="kv-v ' + (v.color || '') + '">' + (v.value == null ? '--' : v.value) + '</span></div>';
    }
    return '<div class="kv-row"><span class="kv-k">' + k + '</span><span class="kv-v">' + (v == null ? '--' : v) + '</span></div>';
  }).join('');
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

setInterval(poll, 2500);
poll();

