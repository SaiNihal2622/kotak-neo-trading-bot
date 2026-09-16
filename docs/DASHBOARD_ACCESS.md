# Dashboard Accessibility — View From Anywhere

The Streamlit dashboard currently runs on `http://localhost:8501` on the local
Windows PC. To view it from your phone, laptop, or any device, you have 4 options
ranked by ease of setup. Pick one.

| Option | Setup time | Cost | Reliability | Mobile-friendly |
|---|---|---|---|---|
| 1. ngrok (Recommended for testing) | 5 min | Free | OK (free tier URLs change every restart) | Yes |
| 2. Cloudflare Tunnel (free, persistent URL) | 10 min | Free | Good (free tier) | Yes |
| 3. Tailscale Funnel (private network, no exposure) | 10 min | Free | Best (only you + invited devices) | Yes |
| 4. Streamlit Community Cloud (no PC needed) | 20 min | Free | Best (always-on) | Yes |

**All 4 work with the existing local dashboard.** No code changes needed.

---

## Option 1: ngrok (5 minutes, free)

Best for: trying it once, sharing a screenshot with a friend.

1. Sign up at https://dashboard.ngrok.com/signup (free).
2. Get your auth token from the dashboard.
3. Install ngrok on Windows: `choco install ngrok` (or download from
   https://ngrok.com/download).
4. Run once: `ngrok config config add-authtoken <YOUR_TOKEN>`.
5. Run while the dashboard is up:
   ```powershell
   ngrok http 8501
   ```
6. ngrok prints a public URL like `https://a1b2c3.ngrok-free.app`. Open it
   from any device.

**Limitation**: free tier URLs change every ngrok restart. Paid plan ($8/mo)
gets a fixed subdomain.

---

## Option 2: Cloudflare Tunnel (10 minutes, free, persistent)

Best for: daily use, persistent URL, no signup pain.

1. Install `cloudflared` on Windows: `winget install Cloudflare.cloudflared`
   (or download from https://github.com/cloudflare/cloudflared/releases).
2. Login once:
   ```powershell
   cloudflared tunnel login
   ```
   Browser opens, pick a domain (or use the free `*.trycloudflare.com`).
3. Create a tunnel:
   ```powershell
   cloudflared tunnel create kotak-dashboard
   ```
4. Create a config file at `C:\Users\saini\.cloudflared\config.yml`:
   ```yaml
   tunnel: kotak-dashboard
   credentials-file: C:\Users\saini\.cloudflared\<TUNNEL_ID>.json
   ingress:
     - hostname: kotak-dashboard.example.com
       service: http://localhost:8501
     - service: http_status:404
   ```
5. Run:
   ```powershell
   cloudflared tunnel route dns kotak-dashboard kotak-dashboard.example.com
   cloudflared tunnel run kotak-dashboard
   ```
6. Visit `https://kotak-dashboard.example.com` from anywhere.

---

## Option 3: Tailscale Funnel (10 minutes, most private)

Best for: only you and your invited devices. No public exposure.

1. Sign up at https://tailscale.com/ (free for personal use).
2. Install Tailscale on Windows: `winget install Tailscale.Tailscale`.
3. Install Tailscale on every device you want to view from (phone, laptop, tablet).
4. Sign into the same Tailscale account on each device.
5. Enable Funnel on the Windows machine:
   ```powershell
   tailscale set --accept-routes
   tailscale funnel 8501 on
   ```
6. Visit the URL Tailscale prints — only devices on your Tailnet can reach it.

**This is what we recommend for personal use.** No public exposure means no
attacker surface, and it's free for personal networks up to 100 devices.

---

## Option 4: Streamlit Community Cloud (20 minutes, no PC needed)

Best for: 24/7 availability even when your PC is off.

This is a bigger lift — you'd need to:

1. Push the project to GitHub (already done if you commit regularly).
2. Sign up at https://share.streamlit.io/ (free).
3. Connect your GitHub repo, point at `dashboard/app.py`.
4. Configure secrets (Kotak credentials) via the Streamlit secrets UI.

**Caveats**:
- The bot's paper_state.json lives on the local PC, not GitHub. Streamlit
  Cloud can't see it. You'd be running a read-only dashboard against a
  mocked/stale state.
- For a real "view anywhere" 24/7 setup, you'd need to migrate the bot
  itself to the cloud (Hetzner/DigitalOcean as documented in
  `PRODUCTION_DEPLOYMENT.md`). That's a 1-day job and the bigger cost.

**Recommended for later, not now.**

---

## What we recommend (right now)

**Option 3 (Tailscale Funnel)** — it's the right balance:
- 5 minutes to set up.
- Free forever.
- Only you (and your invited devices) can see it.
- No public exposure (much safer than ngrok/Cloudflare).
- Works on phone, laptop, tablet — anything with Tailscale.

Once set up, your dashboard URL stays the same. The bot keeps running on the
local PC. You can view from anywhere with Tailscale installed.

---

## Why not just open port 8501 on the router?

Don't. Streamlit has no auth by default. Port-forwarding exposes the bot's
dashboard (and any future state secrets) to the entire internet. All four
options above add at least an auth or VPN gate.

If you absolutely must port-forward, do it through Cloudflare Tunnel (option 2)
with Cloudflare Access enabled — that adds Google/GitHub OAuth in front of
your dashboard.

---

## Testing checklist

After setting up any option above:

1. Dashboard at `localhost:8501` still works (no regression).
2. New public/private URL works from another device.
3. The data shown (positions, P&L, signals) matches what you see locally.
4. Streamlit's auto-reload still works (it watches the file system).

If the dashboard fails to load remotely but works locally:
- Windows Firewall is likely blocking inbound. Allow `python.exe` and
  `streamlit.exe` on port 8501 (TCP).
- For Tailscale Funnel, ensure `--accept-routes` was set.