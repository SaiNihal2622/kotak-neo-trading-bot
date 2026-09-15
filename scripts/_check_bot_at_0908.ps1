$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$log = Join-Path $root "Logs\bot_stderr.log"
$f = [System.IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
$size = $f.Length
# read last 200KB to capture 09:00-09:15 window
$start = [Math]::Max(0, $size - 200000)
$f.Position = $start
$reader = New-Object System.IO.StreamReader($f, [System.Text.Encoding]::UTF8, $true, 1024, $true)
$text = $reader.ReadToEnd()
$reader.Close()
$f.Close()
# find lines from 09:00 to 09:15 with action/decision/order
$lines = $text -split "`n" | Where-Object { $_ -match "09:0[0-9]|09:1[0-5]|09:08" -and ($_ -match "OPEN|CLOSE|action|order|decision|quant_actions|bear_put|PE.*239|PE.*237") }
$lines | Select-Object -First 25 | ForEach-Object { $_.Substring(0, [Math]::Min(220, $_.Length)) }
