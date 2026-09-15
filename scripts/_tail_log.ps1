$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$log = Join-Path $root "Logs\bot_stderr.log"
$f = [System.IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
$size = $f.Length
$start = [Math]::Max(0, $size - 100000)
$f.Position = $start
$reader = New-Object System.IO.StreamReader($f, [System.Text.Encoding]::UTF8, $true, 1024, $true)
$text = $reader.ReadToEnd()
$reader.Close()
$f.Close()
$lines = $text -split "`n" | Where-Object { $_ -match "10:3[5-9]|HTTP|8502|http_server|kotak_bot.http" } | Select-Object -First 25
$lines | ForEach-Object { $_.Substring(0, [Math]::Min(200, $_.Length)) }
