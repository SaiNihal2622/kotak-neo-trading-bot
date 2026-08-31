#!/usr/bin/env python3
"""Run the dashboard's render() function in Node.js with a fake state to find
any other JS errors that would prevent the page from populating."""
import subprocess
import json
import tempfile
import os

# Read the live_dashboard.py source and extract the JS
with open(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\live_dashboard.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Find the script tag content
start = src.find('<script>')
end = src.find('</script>')
js = src[start+8:end]

# Wrap in a node-runnable test
test = f"""
// Stub the DOM
const elements = {{}};
const document = {{
    getElementById: (id) => {{
        if (!elements[id]) elements[id] = {{
            textContent: '', innerHTML: '', className: '',
            querySelector: () => ({{ querySelector: () => ({{ innerHTML: '' }}), innerHTML: '' }}),
        }};
        return elements[id];
    }}
}};
const fetch = async (url) => {{
    return {{
        json: async () => ({{
            countdowns: {{
                now_ist: '20:35:00', now_date: '2026-08-30',
                market_open_0915: {{ label: '6h 30m' }},
                force_square_soft_1415: {{ label: 'passed' }},
                force_square_hard_1515: {{ label: 'passed' }},
                market_close_1530: {{ label: 'passed' }},
            }},
            bot: {{ pid: 10544, alive: true, main_thread_alive: true, state: 'running', vix: 10.8, data_source: 'live_kotak', tick: 4343, uptime_sec: 259200, last_liveness_age_sec: 4, trades_today: 0, open_positions: 0, is_paused: false }},
            account: {{ cash: 109977, realized_pnl: 9977, unrealized_pnl: 0, total_value: 109977, starting_capital: 100000, today_pnl_pct: 9.97 }},
            market_thesis: {{ available: true, regime: 'range', bias: 'neutral', confidence: 0.3 }},
            brain: {{ last_action: {{ bias: 'neutral', source: 'mavis' }} }},
            thesis: {{ available: true, regime: 'range', bias: 'neutral', confidence: 0.3, nifty_spot: 24119, banknifty_spot: 57427, india_vix: 10.8, narrative: 'RANGE regime', preferred_strategies: ['ic'] }},
            processes: {{ kotak_procs: [{{ pid: 10544, name: 'kotak_bot', session: 4 }}] }},
            crons: {{ jobs: [{{ name: 'kotak-bot-watchdog', schedule: '*/5 * * * *', next_run_ist: '20:50' }}] }},
            log_tail: ['line 1', 'line 2'],
            positions: [],
        }});
    }}
}};

{js}

// Run render() and check if it succeeds
try {{
    poll().then(() => {{
        console.log('OK: poll() completed without throwing');
        console.log('clock.textContent:', elements['clock'].textContent);
        console.log('botPill.innerHTML:', elements['botPill'].innerHTML.substring(0, 80));
        console.log('cash.textContent:', elements['cash'].textContent);
        console.log('realized.textContent:', elements['realized'].textContent);
        console.log('botKv innerHTML length:', elements['botKv'].innerHTML.length);
        console.log('brainKv innerHTML length:', elements['brainKv'].innerHTML.length);
        console.log('cronTable tbody innerHTML length:', elements['cronTable'].querySelector().innerHTML.length);
    }});
}} catch (e) {{
    console.log('ERROR:', e.message);
    console.log('STACK:', e.stack);
}}
"""

# Run with node
with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
    f.write(test)
    tmpfile = f.name

try:
    proc = subprocess.run(['node', tmpfile], capture_output=True, text=True, timeout=10)
    print("STDOUT:", proc.stdout)
    if proc.stderr:
        print("STDERR:", proc.stderr[:2000])
finally:
    os.unlink(tmpfile)
