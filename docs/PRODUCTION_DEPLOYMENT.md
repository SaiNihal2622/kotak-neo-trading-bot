# PRODUCTION DEPLOYMENT — Cloud vs Local Decision

## TL;DR

| Phase | Mode | Where | Why | Cost |
|---|---|---|---|---|
| **Phase 1 (now)** | Paper | **WSL2 on your PC** | Free, low latency, full control, no NSSM/UAC/file-locks. ~2 hours to migrate. | $0/mo |
| **Phase 2 (when ready, +30 days)** | Live (small) | **WSL2 on your PC** | 1-2ms RTT to NSE via Kotak local proxy. Free. | $0/mo |
| **Phase 3 (capital > Rs.5L)** | Live (24/7) | **Hetzner Cloud CX11 (Frankfurt) + DigitalOcean Bangalore backup** | 24/7 uptime, no need to keep PC on, redundant failover. | €3.79/mo + $6/mo = ~$10/mo |

**If you only do ONE thing: install WSL2 and run the bot there. It solves 80% of the issues.**

---

## Detailed decision matrix

### Option A: Keep on Windows (current, status quo)

| | |
|---|---|
| Pros | No setup, already running |
| Cons | NSSM is opaque, UAC needed for restart, file-lock races, Windows-specific bugs (shadow imports via `from X import Y` inside functions), paper_state.json gets corrupted by concurrent writes |
| Reliability | ~95% (you've seen 3+ bugs in 2 days) |
| Cost | $0 |
| Setup time | 0 hours |
| Verdict | **NOT production ready. Continue using ONLY for paper trading while you migrate.** |

### Option B: WSL2 (Ubuntu 22.04 inside Windows)

| | |
|---|---|
| Pros | Linux semantics, systemd available, no UAC, no NSSM, file system is saner, low latency (1-2ms via Windows host's network), can run alongside Windows |
| Cons | WSL2 isn't a real server (PC must be on, no auto-failover), slight CPU overhead, 4GB RAM recommended for WSL2 + Windows |
| Reliability | ~99% (proper systemd, proper file semantics, no NSSM/UAC) |
| Cost | $0 |
| Setup time | 2 hours |
| Verdict | **HIGHLY recommended for paper + small live. Best bang for buck.** |

### Option C: Hetzner Cloud CX11 (Frankfurt or Helsinki)

| | |
|---|---|
| Pros | 24/7 uptime, 99.9% SLA, no PC needed, instant provisioning, EU data privacy laws (good for finance), €3.79/mo is cheap, 80-100ms RTT to NSE is fine for non-HFT |
| Cons | 80-100ms latency to NSE, requires server admin skills (basic), no access to Windows-only tools |
| Reliability | ~99.9% (SLA) |
| Cost | €3.79/mo (~$4.10) |
| Setup time | 3-4 hours |
| Verdict | **Best for live trading 24/7. Recommended for Phase 3.** |

### Option D: DigitalOcean Bangalore

| | |
|---|---|
| Pros | 20-30ms RTT to NSE (better for fast execution), $6/mo, 1-click provisioning, good docs |
| Cons | Higher cost than Hetzner, less reliable (no EU SLA), US-based company |
| Reliability | ~99.5% |
| Cost | $6/mo |
| Setup time | 2-3 hours |
| Verdict | **Good for low-latency live trading. Slightly pricier than Hetzner.** |

### Option E: AWS Mumbai t3.micro

| | |
|---|---|
| Pros | 5-10ms RTT to NSE (lowest of all), full AWS integration, auto-scaling, Mumbai region |
| Cons | $7-9/mo (most expensive), complex billing (can surprise you), overkill for a single bot |
| Reliability | ~99.99% (best SLA) |
| Cost | $7-9/mo (can creep up) |
| Setup time | 1-2 days (lots of AWS services to navigate) |
| Verdict | **Best for low-latency at scale. Overkill for paper trading.** |

### Option F: Local Linux server (used PC + Linux)

| | |
|---|---|
| Pros | Cheapest ($0 + electricity), full control, fastest RTT to NSE (1-2ms), no recurring cloud cost |
| Cons | Need to keep the PC on 24/7, hardware failures kill the bot, no SLA, UPS needed for power cuts, cooling |
| Reliability | ~95% (depends on hardware, network, power) |
| Cost | $0 + ~₹500/mo electricity |
| Setup time | 1 day |
| Verdict | **Cheapest long-term. If you have a stable PC + UPS, this works.** |

### Option G: Raspberry Pi 5 at home

| | |
|---|---|
| Pros | $80 one-time, low power (~5W), quiet, runs Linux natively, 1ms RTT to NSE |
| Cons | Limited RAM (4-8GB), SD card failure risk (use SSD!), single point of failure, no SLA |
| Reliability | ~90% (SD card failures) |
| Cost | $80 one-time + electricity |
| Setup time | 4 hours |
| Verdict | **Fun hobby project. Not for serious money.** |

---

## My recommended path

1. **NOW (this weekend, 2 hours):** Install WSL2, run the bot there, paper trade.
2. **+30 days (when you're profitable for 30+ days):** Move to Hetzner Cloud CX11, run live with 5% of capital.
3. **+90 days (when 5% allocation is profitable):** Add DigitalOcean Bangalore as backup failover, scale to full capital.
4. **+1 year (if consistently profitable):** AWS Mumbai + Kubernetes + dedicated quant team.

The bot is currently at Phase 1 with the wrong infra (Option A, Windows). Move it to WSL2 today.

---

## Live-trading safety gates (MUST be satisfied before flipping KOTAK_LIVE_CONFIRMED=YES)

1. **Paper profitable for 30+ consecutive days**
2. **Sharpe ratio > 1.0** (consistent risk-adjusted returns)
3. **Max drawdown < 10%** (capital preservation)
4. **Win rate > 55%** (statistically significant)
5. **Average win > 1.5x average loss** (positive expected value)
6. **KYC verified on Kotak Neo** (required for live trading)
7. **Tested with 1% capital first for 7 days** (small live trial)
8. **Stop-loss verified to fire within 5 min** (execution correctness)
9. **No phantom positions in 30 days** (no reconciliation bugs)
10. **All self-tests pass daily** (no shadow imports, no UAC, no file races)

After all 10 are satisfied, you can flip the live switch. Until then, the bot refuses to place real orders even if KOTAK_LIVE_CONFIRMED=YES (defense in depth).
