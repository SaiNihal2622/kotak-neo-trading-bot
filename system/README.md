# Kotak Neo Trading Bot — System

Production infrastructure for the paper-trading bot. Designed for **24/7 unattended operation** on the user's laptop.

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                       Windows Host (laptop, 24/7)                        │
│                                                                          │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │ KotakBotPaper    │    │ KotakDashboard   │    │  Healthcheck     │  │
│  │ (NSSM service)   │    │ (NSSM service)   │    │  (cron 5min)     │  │
│  │                  │    │                  │    │                  │  │
│  │  python -m       │    │  streamlit       │    │  healthcheck.ps1 │  │
│  │   kotak_bot      │    │   run dashboard  │    │   → Telegram     │  │
│  │   paper          │    │   .py :8501      │    │     alerts       │  │
│  └────────┬─────────┘    └────────┬─────────┘    └──────────────────┘  │
│           │                       │                                      │
│           ▼                       ▼                                      │
│  ┌────────────────────────────────────────┐    ┌──────────────────────┐  │
│  │  data_cache/                            │    │  Telegram Bot API    │  │
│  │    paper_state.json (cash, P&L, pos)   │    │   - bot token        │  │
│  │    trades_state.json (open positions)   │    │   - chat_id          │  │
│  │    trades.csv (audit log)               │    │   - alerts on        │  │
│  │    signals.csv                          │    │     state change     │  │
│  └────────────────────────────────────────┘    └──────────────────────┘  │
│                                                                          │
└────────────────────────────────────────────────────────────────────────┘
```

## Components

| Service         | Binary                   | Purpose                                     | Restart |
|-----------------|--------------------------|---------------------------------------------|---------|
| `KotakBotPaper` | `python -m kotak_bot paper` | The trading bot (scans, signals, orders)  | 5s      |
| `KotakDashboard`| `streamlit run dashboard.py` | Real-time capital/P&L/positions view    | 5s      |
| healthcheck     | `system/healthcheck.ps1` | Cron 5min, alerts via Telegram on state change | n/a |

## Auto-restart guarantees

Both services are registered via **NSSM** (the Non-Sucking Service Manager), which:
- Auto-starts them on Windows boot (no manual login required)
- Restarts within 5s if the process exits unexpectedly
- Rotates its own log at 50MB
- Survives logouts (uses LocalSystem-style service mode, runs headless)

## Quick start

### One-time install (as Administrator)

```powershell
cd C:\Users\saini\.minimax-agent\projects\kotak-neo-bot
powershell -NoProfile -ExecutionPolicy Bypass -File system\install_service.ps1
```

This will:
1. Register `KotakBotPaper` and `KotakDashboard` as Windows services
2. Configure them for AUTO_START on boot
3. Start them immediately
4. Both will be in the Windows Services MMC (`services.msc`)

### Verify

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File system\status.ps1
```

### Tail logs

```powershell
Get-Content C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\bot_stderr.log -Tail 50 -Wait
```

### Uninstall

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File system\uninstall_service.ps1
```

## Health monitoring

`healthcheck.ps1` runs every 5 minutes (via Windows Task Scheduler). It checks:
- KotakBotPaper process alive?
- Dashboard HTTP 200?
- Log file fresh (modified <2 min ago)?

On state transitions (alive→dead, dead→alive, PID change), it sends a **Telegram alert**.

To install the 5-min healthcheck scheduled task (as Administrator):

```powershell
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -File C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\system\healthcheck.ps1'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
Register-ScheduledTask -TaskName 'KotakBotHealthcheck' -Action $action -Trigger $trigger -RunLevel Highest -Description 'Kotak bot health monitoring with Telegram alerts'
```

## Migration to Vultr

When the laptop is decommissioned in favor of Vultr Mumbai cloud:
1. `git pull` on Vultr instance
2. Same `install_service.ps1` runs there (use systemd unit instead of NSSM)
3. Point dashboard at `0.0.0.0:8501` and put nginx/Caddy in front for TLS
4. The `healthcheck.ps1` works on any platform (just change the Get-Service calls)

## Files

| File | Purpose |
|------|---------|
| `run_bot.ps1` | NSSM entry for the bot |
| `run_dashboard.ps1` | NSSM entry for the dashboard |
| `install_service.ps1` | Register + start both services |
| `uninstall_service.ps1` | Stop + remove both services |
| `status.ps1` | One-shot health snapshot |
| `healthcheck.ps1` | Cron 5min, alerts on transitions |
| `README.md` | This file |
