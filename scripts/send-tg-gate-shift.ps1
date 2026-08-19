$envPath = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env"
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
        $name = $matches[1].Trim()
        $val = $matches[2].Trim()
        Set-Variable -Name $name -Value $val -Scope Script
    }
}

$msg = "Kotak Bot 13:40 IST - gate shift detected. " +
       "SCAN skip message transitioned from position cap to intraday cutoff. " +
       "No new entries after 13:30 (intraday mode). " +
       "16 phantom 12AUG/13AUG broker positions still blocking too. " +
       "Bot alive 5h09m, dash UP, no fills today. " +
       "Capital Rs.1,32,749.95 cash / Rs.5,597.55 realized / 172 orders."

$msgFile = New-TemporaryFile
Set-Content -Path $msgFile.FullName -Value $msg -NoNewline

& curl.exe -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" `
    -d "chat_id=$TELEGRAM_CHAT_ID" `
    --data-urlencode "text@$($msgFile.FullName)"

Remove-Item $msgFile.FullName -Force
