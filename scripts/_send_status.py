"""Send Day 5 status update to user via Telegram."""
import requests

token = '8859774824:AAGCzAl1qDUnehmxHAHraMbT9S7id_C4lc8'
chat = '8537408638'

msg = """🟢 BOT BACK ONLINE — Day 5 status @ 15:55 IST

THE BAD NEWS:
- Bot died clean-exit at 20:28 Wed Aug 13 (same recurring pattern we've seen 3x/week)
- The 8:30 AM daily-start cron did NOT restart it today (mystery — investigating)
- Bot + dashboard both down for ~19h40m

THE RECOVERY (just did it, 15:54 IST):
- Restarted bot: PID 23264 (venv) + 15068 (SYSTEM child) — alive, heartbeating
- Restarted dashboard: PID 20200 — HTTP 200 on :8501
- Bot is currently executing EOD square-off (just placed 7 close orders)

CURRENT STATE:
- Capital: Rs.1,32,749.95 (+32.7% paper since start)
- Realized P&L: Rs.5,597.55 (unchanged from Day 2)
- Orders: 156 cumulative
- Trades: 7 total, 0 open (just EOD squared off), 7 closed
- Open positions in paper_state: 16 (4 ICs from yesterday, being closed now)
- VIX: 11.42 (calm, 1.0x lots)
- Intraday mode: active

NEW CODE LIVE (since 18:45 last night, picked up by 15:54 restart):
- Phase 1.1: Intraday-only (no overnight, 13:30 no-new, 14:30 force-close)
- Phase 1.2: VIX-aware (skip if VIX > 22)
- Phase 1.3: Order resilience (retry/backoff + cancel-replace + fallback)
- Phase 1.4: Real margin tracking (Kotak limits() + 50/70/90% alerts)
- Phase 2:   Greeks engine (delta/gamma/vega/theta via Black-Scholes)
- Phase 2:   Risk metrics (drawdown, VaR/CVaR, Kelly, POP)
- Liveness monitor + atexit + signal handlers (so next clean-exit death leaves forensic data)
- 233/233 tests passing

NEXT MARKET: Mon Aug 17 09:00 IST (NSE closed weekends)

OPEN ITEMS (will fix over weekend):
1. Why daily-start cron didn't fire today (mystery)
2. The recurring clean-exit death pattern (liveness monitor now in place to catch it)
3. Cloud VM migration (still need user signup)
4. NSSM install (user must run as Admin once)
"""

try:
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat, 'text': msg},
        timeout=10,
    )
    print(f'Sent: {r.status_code} ok={r.json().get("ok")}')
except Exception as e:
    print(f'Failed: {e}')
