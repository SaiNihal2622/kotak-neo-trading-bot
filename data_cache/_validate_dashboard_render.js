// End-to-end test of the dashboard JS with mocked DOM and fetch
const fs = require('fs');

// Mock DOM with proxy
const elements = {};
const document = {
  getElementById: (id) => {
    if (!elements[id]) {
      elements[id] = {
        textContent: '',
        innerHTML: '',
        className: '',
        appendChild: () => {},
        querySelector: () => ({
          querySelector: () => ({ innerHTML: '' }),
          innerHTML: ''
        })
      };
    }
    return elements[id];
  }
};

// Mock fetch with rich state
const fetch = async (url) => ({
  json: async () => ({
    countdowns: {
      now_ist: '20:35:00', now_date: '2026-08-30',
      market_open_0915: { label: '6h 30m' },
      force_square_soft_1415: { label: 'passed' },
      force_square_hard_1515: { label: 'passed' },
      market_close_1530: { label: 'passed' },
    },
    bot: { pid: 10544, alive: true, main_thread_alive: true, state: 'running', vix: 10.8, data_source: 'live_kotak', tick: 4343, uptime_sec: 259200, last_liveness_age_sec: 4, trades_today: 0, open_positions: 0, is_paused: false, risk_preset: 'base' },
    account: { cash: 109977, realized_pnl: 9977, unrealized_pnl: 0, total_value: 109977, starting_capital: 100000, today_pnl_pct: 9.97 },
    market_thesis: { available: true, regime: 'range', bias: 'neutral', confidence: 0.3 },
    brain: { last_action: { bias: 'neutral', source: 'mavis' } },
    thesis: { available: true, regime: 'range', bias: 'neutral', confidence: 0.3, nifty_spot: 24119, banknifty_spot: 57427, india_vix: 10.8, narrative: 'RANGE regime', preferred_strategies: ['ic'] },
    processes: { kotak_procs: [{ pid: 10544, name: 'kotak_bot', session: 4 }] },
    crons: { jobs: [{ name: 'kotak-bot-watchdog', schedule: '*/5 * * * *', next_run_ist: '20:50' }] },
    log_tail: ['2026-08-30 20:30:00 | INFO | heartbeat'],
    positions: [],
  })
});

// Load the actual served JS
const js = fs.readFileSync('C:/Users/saini/.minimax-agent/projects/kotak-neo-bot/data_cache/_live_dashboard_actual.js', 'utf-8');
eval(js);

(async () => {
  try {
    await poll();
    console.log('RENDER_OK');
    console.log('clock.textContent:', elements.clock?.textContent);
    console.log('botPill.innerHTML:', elements.botPill?.innerHTML.substring(0, 60));
    console.log('cash.textContent:', elements.cash?.textContent);
    console.log('realized.textContent:', elements.realized?.textContent);
    console.log('botKv.innerHTML length:', elements.botKv?.innerHTML?.length);
    console.log('brainKv.innerHTML length:', elements.brainKv?.innerHTML?.length);
    console.log('marketKv.innerHTML length:', elements.marketKv?.innerHTML?.length);
    console.log('cronTable.querySelector().innerHTML length:', elements.cronTable?.querySelector?.()?.innerHTML?.length);
    console.log('procTable.querySelector().innerHTML length:', elements.procTable?.querySelector?.()?.innerHTML?.length);
  } catch (e) {
    console.log('RENDER_ERROR:', e.message);
    console.log(e.stack);
  }
})();
