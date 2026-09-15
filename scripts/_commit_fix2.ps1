# Commit the staged files
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
& git commit -m "fix(phantom-fill): reject Rs.1.0 fills + Black-Scholes fallback + chain health check

ROOT CAUSE: The bot's _force_fill_market_like was accepting ANY chain price
without validation. The Sep 11 NIFTY chain had inverted PE prices (PE going
UP as strike goes DOWN), which produced phantom +Rs.3,060 P&L from a single
orphan-auto-close. Sep 15 saw +Rs.88,004 of likely phantom gains from the
same root cause (broken yfinance data + no validation).

This commit fixes 3 layers:
1. scripts/_chain_health.py: chain health check + price validator + BS fallback
2. kotak_bot/broker/paper_client.py: validates every price path
3. scripts/_system_audit.py: chain_health subsystem
4. tests/test_chain_health.py: 26 tests

Defense in depth: even with broken yfinance data, the bot now logs loudly,
falls back to real Black-Scholes prices instead of Rs.1.0, refuses fills
at prices below sane minimums, and refuses fills 2x off from the LLM's
expected price. Real P&L Sep 8-15 needs retroactive audit since phantom
fills were not validated before. The fix prevents new phantom fills."
