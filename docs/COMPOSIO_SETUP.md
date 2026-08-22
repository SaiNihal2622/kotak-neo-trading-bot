# Composio MCP Setup

Composio is a unified API for 100+ SaaS apps (Gmail, Calendar, Slack, GitHub,
Notion, Linear, etc.). It's already declared in `~/.minimax/mcp.json` at
`mcpServers.composio` (lines 45-54) but currently `disabled: true` because the
placeholder API key has not been replaced.

## Why we want it
- Auto-fetch emails and surface hiring-related signals in trader ticks
- Push trade alerts to Slack channels in parallel with Telegram
- Sync weekly trade summaries to Notion / Linear
- Cross-post job-pipeline status updates from the career-pipeline project

## Setup (5 minutes)

### 1. Sign up
- Go to https://dashboard.composio.dev/
- Sign in with Google / GitHub
- Free tier = 100 actions/month (enough for weekly summaries)

### 2. Get your API key
- Open Settings → API Keys
- Copy the key (looks like `comp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx`)

### 3. Replace the placeholder
Edit `C:\Users\saini\.minimax\mcp.json` line 50:
```diff
- "COMPOSIO_API_KEY": "__COMPOSIO_API_KEY__"
+ "COMPOSIO_API_KEY": "comp_YOUR_ACTUAL_KEY_HERE"
```

### 4. Enable the server
Same file, line 53:
```diff
- "disabled": true
+ "disabled": false
```

### 5. Restart Mavis
The MCP server is launched by Mavis at session start. Quit the desktop app
fully and reopen it (or click "Reload MCPs" if available). Verify the server
is connected by running:
```
echo "list tools" | curl -s http://localhost:PORT/mcp
```
in a Mavis session, or just run any tool — if the server is loaded, you'll
see `composio__*` tools in your tool list.

## Connecting apps (after MCP is enabled)
Once Composio MCP is loaded in Mavis, you can connect apps in-session:
1. `composio__list_apps` — see what's available
2. `composio__connect_app` with `app_name="gmail"` — opens OAuth flow
3. After auth, the app's tools become available (e.g. `composio__send_email`)

Each connected app consumes some of the 100 actions/month quota.

## Quick win for kotak-neo-bot
After setup, a single cron can:
1. Each Monday 09:00 — pull a one-liner about NIFTY gap-up/down from Gmail
   search (sent by broker statements) and append to brain_state.json
2. Each Friday 18:00 — push weekly summary to a Slack #trading channel
3. On every CRITICAL Telegram — also log to a Notion database for audit

## What stays manual until you set the key
- All current Telegram alerts work without Composio
- Email notifications are out of scope until Composio is enabled
- Slack/Notion integration is blocked

## Files
- MCP declaration: `C:\Users\saini\.minimax\mcp.json` lines 45-54
- Free tier limit: https://docs.composio.dev/guides/limits
- Apps catalog: https://composio.dev/tools
