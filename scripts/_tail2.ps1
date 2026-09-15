$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$log = Join-Path $root "Logs\bot_stderr.log"
$f = [System.IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
$size = $f.Length
$start = [Math]::Max(0, $size - 200000)
$f.Position = $start
$reader = New-Object System.IO.StreamReader($f, [System.Text.Encoding]::UTF8, $true, 1024, $true)
$text = $reader.ReadToEnd()
$reader.Close()
$f.Close()
$lines = $text -split "`n" | Where-Object { $_ -match "10:3[0-5]" -and ($_ -match "QUANT-ACTION|REJECT|long_put|OPEN|NIFTY.*24000|consumed") } | Select-Object -First 25
$lines | ForEach-Object { $_.Substring(0, [Math]::Min(220, $_.Length)) }
