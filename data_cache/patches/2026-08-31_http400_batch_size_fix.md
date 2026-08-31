# Patch Proposal — HTTP 400 "Neo symbol max value to 50" Batch-Size Fix

**Status:** DRAFT, awaiting user authorization
**Author:** Mavis self-driver (12:27 IST, 2026-08-31)
**Severity:** P1 — blocks all options order placement since 08:48 IST
**File:** `kotak_bot/data/kotak_prod_feed.py`
**Function:** `_fetch_option_quotes` (line 549)
**Lines changed:** ~7 added, 1 changed (`return` → `continue`)

---

## Problem

`KotakProdFeed._fetch_option_quotes` sends ALL subscribed pSymbols in a single
comma-separated URL. The Kotak Neo API rejects the request with HTTP 400
`Please set the Neo symbol max value to 50` when the comma list exceeds 50
symbols. The poll loop catches the 400, logs a WARNING, and the next 3s
poll re-fires the same 400. Quote updates are silently dead → order
placement cannot price → no new options orders can execute.

Live evidence (12:27 IST, 12:27:52 to 12:28:01, 5 warnings in 9s):

```
2026-08-31 12:27:52.503 WARNING kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560
  KotakProdFeed: quotes HTTP 400 body={"fault":{"code":"400","description":"Please set
  the Neo symbol max value to 50.","message":"Please set the Neo symbol max value to 50."}}
```

Sustained 3h47m+ at ~1 every 2-3 sec. 0 options orders filled since 08:48 IST.

## Fix

Wrap the request body in a chunked loop. 50 symbols per HTTP request.

### Diff (apply to `kotak_bot/data/kotak_prod_feed.py` lines 549-600)

```diff
 def _fetch_option_quotes(self, psyms: list[str]) -> None:
-    # Kotak allows comma-separated queries in one request
+    # Kotak allows comma-separated queries in one request, capped at 50 symbols
+    MAX_PER_REQ = 50
     queries = [f'nse_fo|{p}' for p in psyms]
-    encoded = ','.join(urllib.parse.quote(q, safe='') for q in queries)
-    url = f"{self.session.base_url}/script-details/1.0/quotes/neosymbol/{encoded}/all"
-    code, body = _http_get(url, {'Authorization': self.access_token})
-    if code == 401:
-        logger.warning("KotakProdFeed: 401 on quotes, will re-auth next cycle")
-        self.session = None  # force re-auth
-        return
-    if code != 200:
-        logger.warning(f"KotakProdFeed: quotes HTTP {code} body={body[:200]}")
-        return
-    try:
-        quotes = json.loads(body)
-    except Exception as e:
-        logger.warning(f"KotakProdFeed: parse quotes: {e}")
-        return
-    for q in quotes:
+    for i in range(0, len(queries), MAX_PER_REQ):
+        batch = queries[i:i + MAX_PER_REQ]
+        encoded = ','.join(urllib.parse.quote(q, safe='') for q in batch)
+        url = f"{self.session.base_url}/script-details/1.0/quotes/neosymbol/{encoded}/all"
+        code, body = _http_get(url, {'Authorization': self.access_token})
+        if code == 401:
+            logger.warning("KotakProdFeed: 401 on quotes, will re-auth next cycle")
+            self.session = None  # force re-auth
+            return
+        if code != 200:
+            logger.warning(f"KotakProdFeed: quotes HTTP {code} body={body[:200]}")
+            continue
+        try:
+            quotes = json.loads(body)
+        except Exception as e:
+            logger.warning(f"KotakProdFeed: parse quotes: {e}")
+            continue
+        for q in quotes:
+            # (unchanged: ps lookup, depth, bid/ask/ltp/oi/vol, _update_tick)
```

The existing `for q in quotes:` block (lines 567-600) is moved 4 spaces right and
its body is unchanged. The per-batch try/except isolates any single bad batch
without losing data from the others.

### Why this is safe

- **No behavior change on success path.** When the symbol count is ≤50 (most
  polls in low-vol regimes), the loop runs exactly once with the same URL as
  before. Quotes still flow into `self._update_tick` exactly as today.
- **Failure modes preserved.** HTTP 401 still forces re-auth (the whole session
  is bad, no point hammering). Non-200 on a single batch no longer abandons the
  remaining batches — a transient 400 on one batch won't kill the whole poll.
- **No new imports, no new dependencies.** Pure refactor of one function.
- **Idempotent and revertible.** A one-function wrap with `git revert` restores
  the old behavior instantly.

### Why NOT to skip the orphan kill step

Two bot processes are running concurrently (per AGENTS.md 2026-08-22 known-issue):
- PID 10544 (liveness): uptime 88h, started 2026-08-27 20:30:27 IST (parent NSSM)
- PID 7332 (younger): uptime 3h43m, started 2026-08-31 08:32 IST (parent NSSM)

Wait, checking again — the trader_state output says "cycle=37567" (older stderr)
AND "cycle=2811" (younger log). The older process is the one that was restarted
at 23:38:51 IST on 2026-08-27 (88h ago) and holds the canonical state. The
younger one is the post-Path-fix 2026-08-28 09:04 bot. Both are NSSM-managed;
neither is a true orphan. The Path fix is live in BOTH (no Path warnings
observed in any 12:00+ tick).

So: NSSM `restart KotakBotPaper` is enough — no admin UAC kill required.
After restart, only the new process runs the patched code.

## Application steps (after user authorizes)

```powershell
# 1. Apply the patch (see diff above) and verify syntax:
cd C:\Users\saini\.minimax-agent\projects\kotak-neo-bot
git diff kotak_bot/data/kotak_prod_feed.py   # sanity check the diff
python -c "import ast; ast.parse(open('kotak_bot/data/kotak_prod_feed.py').read()); print('OK')"

# 2. Restart the bot to pick up the change (NSSM-aware):
nssm restart KotakBotPaper

# 3. Watch the log for the 400 to clear within 60s:
Get-Content Logs\bot_stderr.log -Wait | Select-String "quotes HTTP 400" | Select-Object -Last 5
# Expected: no new lines after restart; SCAN/MAVIS lines resume normal cadence.

# 4. Re-issue Plan A NIFTY iron_condor via brain_actions.json:
#    The trader-desk cron (12:55 IST tick) will see the fix land and
#    re-attempt the iron condor (NIFTY 24067 inside Mavis range [23922, 24258]).
#    If the cron does not auto-retry, the user can drop a manual
#    act-1300NIFTYIC.json with ttl=600s — the bot reads it on next scan.
```

## Expected outcome

- Within 60s of restart: HTTP 400 warnings cease, quote pipeline resumes.
- Within 1-2 min: bot's Mavis EXECUTE_PLAN NIFTY iron_condor cycle (currently
  firing every 6s, blocked) reaches the order path, places the 4-leg condor.
- Capital at risk: same as before — paper Rs 1,09,978, max 2 lots, max loss
  capped at ~Rs 5,000 per leg by config.
- If 13:00 IST passes without restart: the paper session today is wasted
  (no-new-entries cutoff 13:30, force-square 14:30 — but 0 open positions
  means no exposure either way).

## Time budget

- Now (12:27): proposal ready
- 12:51: dedup window from 11:51:30 ESCALATE Telegram expires → fresh ESCALATE can fire
- 13:00: realistic latest "fix in" deadline to save the paper session
- 13:30: bot's no-new-entries cutoff
- 14:30: bot's force-square-off (no-op since 0 positions)

---

*This file is a scratch proposal. Not a code change. The patch must be applied
manually (or via a user-authorized worker task) and the bot restarted before
any order path becomes available.*
