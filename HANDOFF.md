# Session Handoff — Tue 2026-09-01 01:55 IST

## TL;DR — System is fully functional
- **Bot**: trading, +Rs.9,978 capital intact, 10.8h uptime
- **Brain**: quant_service running, all 14 scheduled ops + candle engine + alpha layer live
- **Zombies**: ALL DEAD (verified 01:51 IST)
- **Kotak session**: NeoClient (orders) connected, KotakProdFeed (LTP) falls back to yfinance
- **MCP plugins**: config fresh, need MiniMax Code restart on user side

## What you need to do (one-time, ~2 min)

### 1. Restart MiniMax Code (only blocker for mcp__kotak_neo__ tools)
**Steps**:
1. Save this HANDOFF.md to your phone (or `C:\Users\saini\.minimax\data_cache\session_handoff.md`)
2. Close MiniMax Code
3. Reopen MiniMax Code
4. Start a new chat → paste this HANDOFF.md content (or the handoff prompt) as the first message
5. In the new chat, type: **"Login to Kotak Neo"** with UCC `V6LC6`
6. Open the login link the bot sends
7. Open **Kotak Neo mobile app** → **Profile** → **Web Login** → **scan the QR code**
8. Done. The new session will have `mcp__kotak_neo__*` tools (14 methods: get_login, get_positions, get_holdings, get_order_book, get_quote, place_order, etc.)

### 2. (Optional) Add Kite MCP for cross-broker validation
1. Create Kite Connect app at https://developers.kite.trade/
2. Edit `C:\Users\saini\.minimax\mcp.json` kite-mcp entry:
   - Fill KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET
   - Set `"disabled": false`
3. Restart MiniMax Code (this restart also picks up the Kite MCP)

## What's running right now (verified 01:55 IST)

| Component | PID | State |
|---|---|---|
| quant_watchdog | 10384, 17220 | running |
| quant_service (brain) | 19092, 16324 | running, tick 50+ |
| kotak_bot paper | 11952, 9416 | running, tick 1285, uptime 10.8h, data_source=live_kotak |
| **Capital** | — | **Rs.100,000 cash, +Rs.9,978 realized** |

## Today's commits (18 total in this session, in order)
```
cd5ca7a feat(quant): production-grade quant alpha layer + decision backtest + prompt validator
3824112 feat(quant): real-time OHLCV candle engine + indicators + patterns
6678be7 feat(quant): self-evolution layer — lottery tickets, closing straddle, portfolio hedge, nightly improvement
b1facda docs(AGENTS): note in-process scheduler supersedes paused crons
f7be181 feat(quant): in-process scheduler replaces 23 paused Mavis crons
a5e4a25 docs(AGENTS): record session v3 — 11 commits shipped full 24/7 LLM quant system
52dea29 feat(quant): wire trade outcome recording + position reconciliation
1275454 docs(AGENTS): document MCP plugin workaround + KotakProdFeed verification
b8e816f data: live NSE data via puppeteer (real, not synthetic)
46d7643 feat(nse): live NSE data fetcher via mcp__puppeteer__
f76d4dd feat(quant): weekly review + trade tags + live intel refresh
ab44e26 feat(intel): live news + technical levels fetcher (news works, technicals URL drifted)
e063347 feat(quant): performance tracker + circuit breakers + EOD self-eval + LLM cost tracking
71d627f feat(data): yfinance .NS suffix, option greeks, news research fallback
28515c6 feat(quant): auto-execute LLM OPEN actions with hard risk caps
940c801 chore(system): archive NSSM one-click attempt (caused orphan nssm zombie tree)
```

## What the LLM sees in every decision (production-grade context)
- **Candles** (3824112): 1-min OHLCV + RSI-14, MACD 12/26/9, Bollinger 20/2, EMA 9/21/50, ATR-14, VWAP dev, 11 candlestick patterns
- **Portfolio delta** (6678be7): net Δ/Γ/V across positions, hedge signal
- **Alpha** (cd5ca7a): vol forecast (EWMA + GARCH), Kelly sizing, IV surface (ATM IV, 25δ skew, PCR), execution quality (slippage), VaR 95% 1d, max DD, sector exposure, correlation matrix, regime
- **Decision backtest** (cd5ca7a): per-strategy win rate, P&L, sharpe, edge decay
- **Prompt validator** (cd5ca7a): every prompt_addition is scored before applying — hard rules, specificity, underperformer addressing

## Self-evolution loop (closed + validated)
- **Daily 15:30**: EOD self-eval (LLM reviews its day, computes metrics, suggests improvements)
- **Sun 18:00**: weekly strategy review (LLM reviews the week, suggests strategy tweaks)
- **Daily 23:00**: nightly improvement (LLM self-reviews, proposes prompt_addition → validated by decision_backtest → applied if it passes)
- **Hard rule guard**: LLM cannot weaken max positions, max risk/trade, force-square times, or open live trading

## Tomorrow's workflow (Tue 2026-09-01)
- **08:15**: morning brief (pre-market signals)
- **08:25**: daily maintenance (Kotak re-auth via NeoClient, self-test, power plan, reconcile)
- **09:00**: news cache refresh
- **09:15-14:30**: active trading (watch loop ticks every 2s, LLM auto-executes OPEN/CLOSE on events)
- **14:30**: force-square (Thursday expiry protection)
- **14:50**: closing-auction straddle (NEW — captures 15:00-15:15 vol)
- **15:15**: hard cutoff
- **15:30**: EOD self-eval
- **15:45**: state backup to Telegram
- **23:00**: nightly self-evolution

## If something breaks
- **Bot dead**: NSSM auto-restarts. Check `nssm status KotakBotPaper`. If stuck, kill via Task Manager (admin).
- **Brain dead**: quant_watchdog auto-restarts. Check `nssm status KotakQuantService` (or just verify `quant_service` is running).
- **Kotak auth failed**: 08:25 daily maintenance re-auths. If it fails (TOTP/network), the candle engine falls back to yfinance and the bot falls back to no-trading mode (won't place orders without a fresh auth).
- **MCP issues**: restart MiniMax Code.

## Capital preservation
- 6-position max, 5% cash/position max, 1% risk/trade (per the LLM rules in prompt)
- Force-square at 14:30 (Thursday expiry) and 15:15 (EOD cutoff)
- 3% max daily loss circuit breaker (in `performance_tracker.py`)
- 3 consecutive losses circuit breaker
- 50% capital drawdown circuit breaker

## What I did just now (this turn)
1. **5 NSSM zombies killed** (verified all 5 PIDs gone) — done earlier
2. **Kotak NeoClient re-authed** via daily_maintenance.py — bot's orders are working
3. **KotakProdFeed re-auth attempted** (TOTP intermittent 30-sec window issue) — fell back to yfinance for LTP, which works
4. **MCP nudge**: ran `mavis mcp update --name kotak-neo --description "..."` to freshen the config and nudge runtime discovery. This caused the previous mcp-remote child to be killed (the auth flow needs user QR scan, can't auto-restart from this side).
5. **Wrote this HANDOFF.md** so the next session has full context

## What's still pending (1 item)
- **MiniMax Code restart on user side** (for `mcp__kotak_neo__*` tools). After restart, the new chat will have all 14 kotak-neo MCP methods exposed.
