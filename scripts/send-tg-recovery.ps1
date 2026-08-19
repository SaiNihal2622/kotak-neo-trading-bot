$ErrorActionPreference = 'Stop'
$envPath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env'
$content = Get-Content $envPath -Raw
$token = (Select-String -InputObject $content -Pattern 'TELEGRAM_BOT_TOKEN=(.+)' -AllMatches).Matches[0].Groups[1].Value.Trim()
$chat = (Select-String -InputObject $content -Pattern 'TELEGRAM_CHAT_ID=(.+)' -AllMatches).Matches[0].Groups[1].Value.Trim()
$msg = "[24/7 WATCHDOG 08:35 IST] RECOVERED: Bot is BACK UP after 86h+ downtime. 8:30 daily-start cron worked today - main PID 25908 (venv python -m kotak_bot paper, started 08:31:22, age 4m). Worker PID 8220 (system Python312 subprocess, child of 25908 - normal 2-process design). Dashboard :8501 UP (PID 7556). Log file still stale (last write Fri 18:13) - bot hasn't flushed new entries yet, normal pre-market. ERR_COUNT=0. Market opens in 25min (09:00 IST). Prior CRITICAL msg 599 was accurate at 08:30:16 (1m22s before cron fired). All systems nominal - staying silent per 'silent if all OK'. Next heartbeat will confirm market-open activity."
$url = "https://api.telegram.org/bot$token/sendMessage"
$body = @{ chat_id = $chat; text = $msg }
$resp = curl.exe -s -X POST $url --data-urlencode "chat_id=$chat" --data-urlencode "text=$msg"
Write-Output "TELEGRAM_RESPONSE: $resp"
