# Fix import paths from scripts._chain_health to scripts.chain_health
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

# Use sed-equivalent in PowerShell: read each line, replace, write back
$files = @(
    "scripts\_system_audit.py",
    "kotak_bot\broker\paper_client.py",
    "tests\test_chain_health_module.py"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        (Get-Content $f -Raw) -replace 'scripts\._chain_health', 'scripts.chain_health' | Set-Content $f -NoNewline
        Write-Host "Patched $f"
    }
}

# Verify
Select-String -Path "scripts\_system_audit.py" -Pattern "scripts\.chain_health|scripts\._chain_health"
Select-String -Path "kotak_bot\broker\paper_client.py" -Pattern "scripts\.chain_health|scripts\._chain_health" | Select-Object -First 3
