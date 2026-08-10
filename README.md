# Kotak Neo Trading Bot

Indian options + intraday trading bot for Kotak Neo (zero brokerage).

## Features
- **Paper trading first** — built-in `PaperClient` simulates fills from live ticks
- **Real broker** — Kotak Neo API v2 (TOTP + MPIN auth, WebSocket, REST orders)
- **Regime-based strategy selector** — trending (directional debit spreads) / range (iron condors, short strangles) / event (straddles) / volatile (pause)
- **Risk engine** — per-trade cap, daily/weekly/monthly loss caps, consecutive-loss kill switch, EOD square-off, data-staleness kill
- **Signals** — pandas-ta indicators (RSI, MACD, ADX, ATR, Supertrend, BBands, EMA, 64 candlestick patterns), regime detector, news + FinBERT-India-v1 sentiment, LLM judge (optional)
- **Backtesting** — vectorbt, walk-forward analysis, parameter sweeps
- **Live dashboard** — Streamlit with P&L, positions, signals, news, risk status
- **Alerts** — Telegram (with markdown), email fallback (Gmail)
- **Full auto mode** — auto-pause, auto-resume, EOD reports

## Project Layout
```
kotak-neo-bot/
├── kotak_bot/              # main package
│   ├── broker/             # NeoClient (real) + PaperClient (sim)
│   ├── data/               # LiveFeed (synthetic/live), HistoricalData, options chain
│   ├── signals/            # TechnicalAnalyzer, RegimeDetector, NewsPipeline (built by agent)
│   ├── strategy/           # DirectionalDebit, IronCondor, ShortStrangle, EventStraddle + selector
│   ├── risk/               # RiskEngine — sizing, kill switches, caps
│   ├── execution/          # OrderManager — multi-leg plans → broker orders
│   ├── alerts/             # Telegram, Email
│   ├── utils/              # clock, logger
│   └── __main__.py         # entry point
├── config/
│   ├── settings.yaml       # all params
│   └── credentials.env.template
├── openalgo_ref/           # marketcalls/openalgo (Kotak Neo plugin reference)
├── neo_api_src/            # Kotak-neo-api-v2 source
├── backtest/engine.py      # vectorbt wrapper (built by background agent)
├── dashboard/app.py        # Streamlit (built by background agent)
├── smoke_test.py           # end-to-end smoke test
├── mcp/kotak_neo_mcp_config.json
└── logs/                   # bot.log, trades.csv, signals.csv
```

## Quick Start

### 1) Paper trading (no creds needed)
```bash
# Create venv (one-time)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run the smoke test
.venv\Scripts\python.exe smoke_test.py

# Run the paper trading loop
.venv\Scripts\python.exe -m kotak_bot paper
```

### 2) Configure for live trading
```bash
# Copy and edit credentials
copy config\credentials.env.template config\credentials.env
# Fill in: KOTAK_API_KEY, KOTAK_MOBILE, KOTAK_UCC, KOTAK_MPIN, KOTAK_TOTP_SECRET
# Optional: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ANTHROPIC_API_KEY
```

To get the TOTP secret:
1. Kotak Neo mobile app → More → Trade API → TOTP setup
2. Scan the QR in Google Authenticator
3. The secret is in the `otpauth://` URL (between `secret=` and `&issuer`)
4. Paste it as `KOTAK_TOTP_SECRET=...` (no spaces)

### 3) Go live
```bash
# First verify with UAT (request from ks.apihelp@kotak.com)
# Then flip to prod
.venv\Scripts\python.exe -m kotak_bot live
```

### 4) Dashboard
```bash
.venv\Scripts\python.exe -m streamlit run dashboard/app.py
# Open http://localhost:8501
```

### 5) Backtest
```bash
.venv\Scripts\python.exe -m backtest.engine
```

## Strategy Logic

### Regime Detection
- **Trending**: ADX ≥ 25, VIX < 18
- **Range**: ADX ≤ 20, VIX < 12, IV rank > 50
- **Volatile**: VIX > 18 OR (IV rank > 70 + low ADX)
- **Default**: range (low confidence)

### Strategy Selection
- **Trending** → Directional Debit Spread (defined risk, 1.5:1 RR)
- **Range** → Iron Condor (4-leg, 0.16 delta short strikes) or Short Strangle (2-leg, 0.20 delta)
- **Event day** (RBI, Fed, Budget, monthly expiry, < 30 min to event) → Long Straddle
- **Volatile** → No new trades, tighten stops on existing

### Risk Caps (defaults, configurable)
- 1% of capital per trade (max ₹3,000)
- 3% daily loss (max ₹9,000) → auto-pause for the day
- 6% weekly loss → auto-pause for the week
- 12% monthly loss → auto-pause for the month
- 4 consecutive losses → auto-pause
- Max 6 trades per day
- EOD square-off at 3:15 PM IST
- No new entries after 2:30 PM IST

## Open-Source References Used
- **marketcalls/openalgo** (`openalgo_ref/`) — best-maintained OSS broker-agnostic framework with native Kotak Neo plugin. Used as the reference for WebSocket protocol, order adapter, and exchange mapping.
- **Kotak-neo-api-v2** (`neo_api_src/`) — official Python SDK.
- **Vansh180/FinBERT-India-v1** (HuggingFace) — Indian-market-tuned FinBERT for sentiment.
- **pandas-ta** — 130+ technical indicators, no C dep on Windows.
- **vectorbt** — Numba-accelerated backtesting.

## MCP Servers
- **Kotak Neo MCP** (official) — `mcp/kotak_neo_mcp_config.json` provides portfolio/positions/order-book access via Claude/Cursor. Bot itself uses the Python SDK directly, not MCP.

## Notes
- All times in IST
- Indian number format: ₹1,00,000 = ₹100,000 (1 lakh)
- 2025 NSE lot sizes: NIFTY = 75, BANKNIFTY = 30 (update in `config/settings.yaml` if NSE revises)
- Paper mode persists to `data_cache/paper_state.json` for crash recovery
- All `*_id` fields are loguru-redacted; secrets are gitignored

## Status
- ✅ Phase 0: scaffold + paper client + risk engine + signals + strategy + execution + alerts — DONE
- ✅ Smoke test: end-to-end paper trading flow — PASSED
- ⏳ Backtest engine + Dashboard + News pipeline — building in background
- ⏳ Live connection — blocked on user creds (KOTAK_API_KEY, TOTP_SECRET, MPIN, etc.)
