Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
# Reset to clear staged scratch files
& git reset HEAD 2>&1 | Out-Null

# Stage ONLY the relevant files
& git add scripts/_system_audit.py scripts/chain_health.py scripts/_chain_health.py kotak_bot/broker/paper_client.py tests/test_chain_health_module.py tests/test_chain_health.py 2>&1 | Out-Null

# Verify what we'll commit
& git status --short scripts/ kotak_bot/broker/ tests/ 2>&1 | Select-Object -First 10

& git commit -m "fix(phantom-fill): rename _chain_health to chain_health + fix imports

The underscore prefix broke Python package imports. Renamed and
updated all imports in audit and bot code."
