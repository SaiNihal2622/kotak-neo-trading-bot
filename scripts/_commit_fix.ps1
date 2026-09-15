# Run git commands from the project directory
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
& git add scripts/_chain_health.py scripts/_system_audit.py kotak_bot/broker/paper_client.py tests/test_chain_health.py
& git status --short scripts/ kotak_bot/ tests/
& git commit -m "fix(phantom-fill): reject Rs.1.0 fills + Black-Scholes fallback + chain health check

ROOT CAUSE: The bot's _force_fill_market_like was accepting ANY chain price
without validation. The Sep 11 NIFTY chain had inverted PE prices (PE going
UP as strike goes DOWN), which produced phantom +Rs.3,060 P&L from a single
orphan-auto-close. Sep 15 saw +Rs.88,004 of likely phantom gains from the
same root cause (broken yfinance data + no validation).

This commit fixes 3 layers:

1. scripts/_chain_health.py: NEW module
   - check_chain_health(underlying) detects broken chains
   - validate_fill_price rejects phantom fills: price < sane minimum
   - bs_estimate gives a real Black-Scholes price when chain is bad
   - get_safe_fill_price main API: chain if valid, else BS fallback

2. kotak_bot/broker/paper_client.py: validates every price path before
   accepting. Rs.1.00 fallback now logged as ERROR so it's loud.

3. scripts/_system_audit.py: chain_health subsystem. Shows ERROR status
   when any chain has broken data.

4. tests/test_chain_health.py: 26 tests pass. Covers all paths.

Defense in depth: even with broken yfinance data, the bot now:
  - Logs loudly when chains are bad
  - Falls back to real Black-Scholes prices instead of Rs.1.0
  - Refuses fills at prices < sane minimums per underlying
  - Refuses fills 2x off from the LLM's expected price"
& git log --oneline -3
