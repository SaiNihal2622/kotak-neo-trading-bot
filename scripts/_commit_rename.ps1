Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
& git add -A scripts/ kotak_bot/broker/paper_client.py tests/
& git status --short scripts/ kotak_bot/ tests/ | Select-Object -First 8
& git commit -m "fix(phantom-fill): rename _chain_health to chain_health + fix imports

The underscore prefix broke Python package imports (returns
'No module named scripts._chain_health'). Renamed to
chain_health.py without the leading underscore and updated all
import paths in:
  - scripts/_system_audit.py (audit run)
  - kotak_bot/broker/paper_client.py (force fill validation)
  - tests/test_chain_health_module.py (renamed too)

The earlier commit ac9e515 added files with the underscore-prefixed
name which Python's package loader skips. This commit fixes that."
