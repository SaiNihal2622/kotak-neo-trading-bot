# PRODUCTION RUNBOOK

> **The "money printing machine" daily operational manual.** This is the single document you read every day to keep the system healthy.

## Quick health check (Telegram)

Type any of these in Telegram:
- `/health` — 1-line summary (bot/brain/cash/session)
- `/diag` — full 12-check pre-market self-heal
- `/live` — live-trading safety gates (only relevant when ready)
- `/bias BULLISH` or `/bias BEARISH` — override brain bias
- `/restart both` — restart bot and brain (no UAC needed after first load)

---

## Daily routine (5 minutes)

### Morning (08:00 - 09:00 IST)

1. **Run pre-market self-heal** (one of these):
   - Telegram: `/diag` — see 12-check report
   - Or run: `python scripts/premarket_self_heal.py`
2. **Check the report**:
   - All 12 checks should pass
   - If anything fails, run `/diag` for details and `/restart both` if needed
3. **Check mavis_trades.json**:
   - action should be `EXECUTE_PLAN` (not `BLOCK`)
   - max_positions should be 4-5
4. **Verify Kotak session**:
   - `/health` shows `Kotak session: expires in Nh` where N > 1
5. **Read 08:15 morning brief** (auto-sent to Telegram)

### During market hours (09:15 - 15:30 IST)

1. **Watch for Telegram alerts**:
   - Open position notifications
   - Order fill confirmations
   - Force-square warnings
   - Self-heal reports
2. **Check confluence signals** (auto-sent when 3+ signals align):
   - Bullish: BIAS_OVERRIDE=BULLISH action triggers
   - Bearish: BIAS_OVERRIDE=BEARISH action triggers
3. **Monitor positions**:
   - `/positions` shows current state
   - Force-square at 14:30 (auto)
   - Hard-kill at 15:15 (auto)

### Evening (15:30 - 18:00 IST)

1. **15:30 EOD reconciler runs** (auto)
2. **15:35 daily post-mortem** (auto, sent to Telegram)
3. **15:45 state backup** (auto)
4. **17:30 post-EOD health check** (auto)
5. **Review today's P&L**:
   - `/pnl` shows today/week/month
6. **Check for issues**:
   - Any error Telegram alerts?
   - Any force-square warnings?
   - Any orphan positions?

### Overnight (18:00 - 06:00 IST)

1. **Brain runs in 24/7 mode** (commits b14304a, bde1778)
2. **Confluence loop runs every 5 min** (writes BIAS_OVERRIDE if applicable)
3. **No trading happens** (intraday mode, allow_overnight=False)
4. **Daily_postmortem + 23:00 nightly improvement runs** (auto)

---

## What to do when things break

### Bot is dead (liveness.json not updating)

1. `/health` — check `Bot: PID=... uptime=...`
2. If PID is gone: `/restart bot`
3. If still dead: open admin PowerShell, run `nssm restart KotakBotPaper`

### Brain is dead (decisions.jsonl not updating)

1. `/health` — check `Brain: LLM=...`
2. If LLM count is 0 or stale: `/restart brain`
3. If still dead: `nssm restart KotakQuantService` from admin PowerShell

### Kotak session expired

- `/health` shows `Kotak session: expires in -Xh` (negative)
- Run `python scripts/_reauth_kotak.py` (TOTP required)
- Or wait for `08:25 daily_maintenance` to re-auth automatically

### Orders silently failing (placed_legs=0)

This is the **shadow-import trap** (Order shadow bug, hit us 4 times). The bot's `Order` import inside `run_paper()` shadows the module-level import. The pre-commit hook should now prevent this.

If you see this:
1. `python scripts/_self_test_orders.py` — verify the bug
2. If self-test fails: `python scripts/lint_no_shadowing.py` — find the offending import
3. Fix the import (move to module level, or use `import X as alias`)
4. `git add -A && git commit -m "fix: shadow import"`
5. `/restart bot` — load the fix

### Force-square didn't fire (orphan positions)

1. Check `order_mgr._trades` is populated (brain-driven OPENs should be there)
2. If empty: there's a pre-fix bug (e.g., line 1283 shadow import)
3. Run `python scripts/_force_square_now.py` — close orphans manually
4. Or wait for the next bot restart (orphan-fallback in `a8dec0a` handles it)

### LLM 503 error

The MiniMax API is having issues. This is a third-party problem, not ours.

- Check `https://agent.minimax.io` in a browser
- Wait 5-10 min, retry
- The bot's HOLD pattern is the right behavior when LLM is unavailable

### Telegram alerts not arriving

1. Check `TELEGRAM_BOT_TOKEN` in `config/credentials.env`
2. Check `TELEGRAM_CHAT_ID` matches your chat
3. Test: `python scripts/_telegram_alert.py "test message"`
4. If broken, regenerate the token via @BotFather

---

## Weekly routine (30 minutes)

### Sunday

1. **Weekly strategy review** (auto, sent to Telegram)
2. **Review the week's P&L**:
   - `/pnl` for week summary
   - `data/performance/weekly.json` for details
3. **Check 24/7 brain mode**:
   - Is the brain making decisions overnight?
   - Are confluence signals firing correctly?
4. **Review the runbook** — update with new learnings

### Performance review

Every Sunday, check:
- Win rate (target: > 55%)
- Sharpe ratio (target: > 1.0)
- Max drawdown (target: < 10%)
- Average win / average loss (target: > 1.5x)

If any of these are off-target, adjust the brain's prompt or the bot's risk caps.

---

## Monthly routine (1 hour)

1. **Run production_audit.py** (12 self-checks)
2. **Update credentials** if needed
3. **Review AGENTS.md** for new patterns / gotchas
4. **Update CHANGELOG.md** with this month's changes
5. **Backup state.db to cloud** (SQLite, easy to backup)
6. **Check for upstream library updates** (`pip list --outdated`)

---

## Quarterly routine (4 hours)

1. **Re-evaluate the strategy**:
   - Is the brain's approach still working?
   - Are there new market regimes we should adapt to?
2. **Migrate to new infrastructure** if needed:
   - WSL2 on local PC
   - Hetzner cloud
   - AWS Mumbai for live trading
3. **Audit the codebase** for technical debt
4. **Review all 9 live-trading gates**:
   - Sharpe, drawdown, win rate, etc.
5. **Re-test self-test order flow**
6. **Update documentation**

---

## Yearly routine (1 day)

1. **KYC re-verification** with Kotak
2. **Tax accounting** — close the year
3. **Major version upgrade**:
   - Update Python, libraries
   - Refactor any accumulated tech debt
4. **Strategic review**:
   - Is the bot still making money?
   - Should we scale up capital?
5. **Update all documentation**

---

## Emergency procedures

### Bot is placing wild trades (uncontrolled)

1. `python scripts/_force_square_now.py` — close all positions
2. `mavis_force_action.json` write `{"action": "PAUSE_BOT", "reason": "wild trades"}`
3. `/restart bot` — load clean state
4. Review what went wrong

### System is down for > 30 min during market hours

1. Check `nssm status KotakBotPaper`
2. If still down: open admin PowerShell, `nssm restart KotakBotPaper`
3. If still down: check Windows Event Viewer for the cause
4. If Windows is unstable: consider WSL2 or Hetzner migration

### Bank / broker incident (Kotak Neo is down)

- Kotak Neo has a 99.9% SLA, but incidents happen
- The bot's safety caps should prevent catastrophic loss
- Wait for Kotak to come back up
- No action needed from you, the bot will resume

### Telegram bot token compromised

1. Generate new token via @BotFather (`/revoke`)
2. Update `TELEGRAM_BOT_TOKEN` in `config/credentials.env`
3. Restart the bot (`/restart both`)
4. Old token is now invalid

---

## Self-test order (what to verify manually)

Run these in order to verify the system is working:

```bash
# 1. Lint (catches Order shadow imports)
python scripts/lint_no_shadowing.py
# Expected: PASSED: no shadow imports found.

# 2. Order flow self-test
python scripts/_self_test_orders.py
# Expected: SELF-TEST PASSED — order flow is healthy

# 3. Pre-market self-heal
python scripts/premarket_self_heal.py
# Expected: SUMMARY: 12 OK, 0 FAIL (or some non-critical warnings)

# 4. Live-trading gates (when ready)
python scripts/live_trading_gates.py
# Expected: 9/9 gates passed (only when actually ready for live)

# 5. Production audit
python scripts/production_audit.py
# Expected: 0 critical issues

# 6. Confluence check
python scripts/_confluence_check.py
# Expected: prints confluence state (or "no confluence")
```

If any of these fail, check the runbook for that specific issue.

---

## Performance targets

| Metric | Target | Stretch |
|---|---|---|
| Win rate | > 55% | > 65% |
| Sharpe ratio | > 1.0 | > 1.5 |
| Max drawdown | < 10% | < 5% |
| Average win / loss | > 1.5x | > 2.0x |
| Daily P&L | > 0 (positive days > negative days) | > 0.5% capital/day |
| System uptime | > 99% | > 99.9% |
| Order execution latency | < 100ms | < 50ms |

If any of these are off-target for 2+ weeks, the strategy or risk management needs adjustment.

---

## Going from paper to live (the 10-gate journey)

| Gate | Current | Required |
|---|---|---|
| 1. KOTAK_LIVE_CONFIRMED=YES set | [FAIL] not set | Manual env edit |
| 2. 30+ days profitable paper | [FAIL] no journal yet | Trade for 30+ days |
| 3. Sharpe > 1.0 | [FAIL] no data | Computed automatically |
| 4. Max drawdown < 10% | [OK] 0% (no trades) | Stay < 10% |
| 5. Win rate > 55% | [FAIL] no journal | Trade 30+ days |
| 6. Avg win > 1.5x avg loss | [FAIL] no journal | Trade 30+ days |
| 7. KYC verified | [OK] session valid | Manual: confirm with Kotak |
| 8. No phantom positions 30d | [OK] 0 phantoms | Stay clean |
| 9. Self-tests pass daily | [FAIL] log not set | Run _self_test_orders.py daily |

After all 9 pass:
1. `/live enable` in Telegram (shows the env-setting steps)
2. Set KOTAK_LIVE_CONFIRMED=YES in env (requires admin)
3. Restart the bot
4. Trade with 1% capital for 7 days
5. If profitable, scale up to 5% capital
6. After 30 more days, scale up to 10% capital
7. After 90 days total, scale to your target allocation

---

## When in doubt

1. Check the logs: `Logs/bot.log` (bot) and `Logs/quant_service.err.log` (brain)
2. Run `/health` and `/diag` from Telegram
3. Read `AGENTS.md` for known patterns / gotchas
4. Read `docs/PRODUCTION_DEPLOYMENT.md` for cloud/local decision
5. If the bot is making decisions that don't match your expectation, **don't panic**. Check `/positions` and `/pnl`. The bot has 9 safety caps (1% per trade, 5% per position, MAX_LOTS_PER_LEG=10, phantom reconcile at startup, force-square at 14:30, hard-kill at 15:15, 13:30 no-new-trades, 1% per-trade, 5% per-position). The risk management is in place.

---

## Versioning

This runbook is for `master` branch. Last updated 2026-09-04 13:45 IST.
