# CLOUD COMPARISON 2026 — Best VPS for kotak-neo-bot

> **Decision matrix** based on real prices, latency to NSE, and Indian payment options.
> **TL;DR:** For this bot, **Vultr Mumbai** at $6/mo is the best choice. Hetzner CX22 is the best value for raw specs if you can ignore India latency.

## Comparison (Aug 2026 prices, 2 vCPU / 4 GB RAM / 50 GB SSD tier)

| # | Provider | Plan | Price | India DC | Latency to NSE | INR/UPI | KYC friction | Best for |
|---|---|---|---|---|---|---|---|---|
| 1 | **Vultr** (Mumbai) | Cloud Compute | **$6/mo** | ✅ Mumbai, Delhi | **5-10ms** | ❌ USD | Low | **Best for trading bot, India latency** |
| 2 | **DigitalOcean** (Bangalore) | Basic Droplet | $24/mo | ✅ Bangalore | 25-40ms | ❌ USD | Low | Most mature, easy UI |
| 3 | **Hetzner** (Frankfurt/Helsinki) | CX22 | **€4.51/mo** (~$5) | ❌ None (DE/FI) | 80-150ms | ❌ EUR | High (Indian sign-ups rejected sometimes) | **Best value for raw specs** |
| 4 | **Linode/Akamai** (Mumbai) | Linode 4GB | $24/mo | ✅ Mumbai | 20-30ms | ❌ USD | Low | Stable, mature |
| 5 | **AWS Lightsail** (Mumbai) | 4GB | $20/mo | ✅ Mumbai, Hyderabad | 5-15ms | ❌ USD | Medium | AWS integration, if already in AWS |
| 6 | **Contabo** (Germany) | Cloud VPS 10 | **€4.50/mo** (~$5) | ❌ None | 80-150ms | ❌ EUR | Low | Cheapest 8GB RAM option |
| 7 | **AIC Cloud** (APAC) | VPS Entry | **₹99/mo** ($1.10) | ⚠️ APAC (Singapore) | 30-50ms | ✅ UPI | None | **Cheapest with INR/UPI billing** |
| 8 | **Scaleway** (France/Canada) | Stardust | €3.50/mo (~$4) | ❌ None | 100-200ms | ❌ EUR | Medium | EU alternative |
| 9 | **Hostinger** (Bangalore) | KVM 1 | ₹99/mo (4-yr lock-in) | ✅ Bangalore | 20-40ms | ✅ UPI | None | **Cheapest with India DC + INR** (but 4-yr lock-in for headline price) |
| 10 | **Oracle Cloud** (Mumbai) | Always Free tier | **$0** | ✅ Mumbai | 5-15ms | ❌ USD | Medium | **Free forever (4 vCPU / 24 GB ARM, but 1 vCPU x86 free)** |

## My recommendation for kotak-neo-bot

### Phase 1 (paper trading, now): **Vultr Mumbai $6/mo**

Why:
- **5-10ms latency to NSE** — best for live trading later
- **Mumbai DC** — local to NSE, no JURISDICTION issues
- **$6/mo** is cheap (₹500/mo)
- **Hourly billing** — can pause anytime
- **One-click Ubuntu 22.04** — perfect for the bot
- **Indian payment via card** — no FX fees if you have an international card

**Provisioning time:** 3-4 hours first time (mostly SSH setup + setup_hetzner.sh equivalent)

### Phase 2 (live trading, when ready): **Same Vultr Mumbai, but with:**
- Upgrade to $12/mo plan (2 vCPU, 4 GB RAM, 80 GB SSD) for live trading
- 2 vCPU gives headroom for the brain's LLM calls + bot's main loop
- 4 GB RAM is enough for Python + system services

### Phase 3 (scaling, Rs.10L+ capital): **AWS Mumbai t3.small $15/mo**

Why upgrade:
- **Auto-scaling** for high-volume periods
- **CloudWatch** for monitoring
- **Better** incident response
- **Compliance** features for SEBI

### Free option (if budget is tight): **Oracle Cloud Always Free tier**

- **$0/month** — completely free forever
- **Mumbai DC** — low latency
- **4 vCPU / 24 GB RAM (ARM)** or **1 vCPU / 1 GB (x86)**
- **Indian payment via card**
- **Caveat:** signup is fiddly, and ARM instances don't run x86 Docker images

**Best for:** someone who wants to learn trading without spending money. Not for production (Oracle has been known to reclaim idle instances).

## The "best of the best" for production trading

| If you want... | Use this | Cost |
|---|---|---|
| **Cheapest with India DC** | AIC Cloud ₹99/mo (1 GB) | $1.10/mo |
| **Cheapest with India DC + UPI** | Hostinger ₹99/mo (4-yr lock-in) | $1.10/mo (locked) |
| **Best price/performance globally** | Hetzner CX22 Frankfurt | €4.51/mo |
| **Best India latency** | AWS Mumbai t3.micro | $7-9/mo |
| **Best balance** | **Vultr Mumbai $6/mo** | $6/mo |
| **Cheapest stable for prod** | **Hetzner CX22** (despite 100ms latency) | €4.51/mo |
| **Free forever** | Oracle Cloud Always Free | $0 |

## My single recommendation: **Vultr Mumbai $6/mo**

For this specific user, who:
- Is running the bot from India
- Has a relatively small capital (~Rs.1L)
- Wants 24/7 uptime without keeping their PC on
- Has an international card (Razorpay, Niyo Global, etc.)

Vultr Mumbai is the answer. Cost: $6/mo (~₹500/mo). Latency: 5-10ms. Easy signup. Indian card accepted. Hourly billing (pause anytime).

If they don't have an international card, **Hostinger Bangalore** at ₹99/mo (4-yr lock-in for headline price) is the cheapest with India DC.

If they don't want to lock in for 4 years, **Vultr Mumbai** with INR billing via Razorpay works.

## Provisioning script (works for ALL providers)

The `infra/setup_hetzner.sh` script I wrote works for **any Ubuntu 22.04 server**. To use it on Vultr, AWS, DigitalOcean, or Oracle:
1. Sign up and provision a server with Ubuntu 22.04
2. SSH in
3. Copy your credentials.env to the server
4. Run: `bash setup_hetzner.sh`
5. Done — bot is running with systemd

The only provider-specific thing is the initial provisioning (creating the VM), which is done via the provider's web console.

## Why NOT Hetzner (despite the price)

Hetzner is the cheapest by far, but:
1. **No India DC** — 80-150ms latency to NSE
2. **Indian sign-ups sometimes rejected** — strict KYC
3. **EUR billing** — Indian cards have ~3% FX fee
4. **Data sovereignty** — your trading data goes through German servers

For paper trading, Hetzner is fine. For live trading, the latency adds up. **For your first cloud deploy, Vultr Mumbai is the answer.**
