"""dashboard_serve.py — Expose the local Streamlit dashboard to a network.

This script wraps one of four tunnel options. Default is Tailscale Funnel
(recommended for personal use — only you + invited devices can see the
dashboard). The other three are also supported.

Usage:
    # Default: Tailscale Funnel
    python scripts/dashboard_serve.py

    # Other options:
    python scripts/dashboard_serve.py --mode ngrok
    python scripts/dashboard_serve.py --mode cloudflare
    python scripts/dashboard_serve.py --mode tailscale

    # Local-only check:
    python scripts/dashboard_serve.py --mode local

What it does:
- Checks that streamlit is running on :8501 (or starts it).
- For ngrok: launches `ngrok http 8501` and prints the public URL.
- For cloudflare: launches `cloudflared tunnel --url http://localhost:8501`.
- For tailscale: runs `tailscale funnel 8501 on`.
- For local: just opens the browser to http://localhost:8501.

The script does NOT install the tunnel binary — you must do that once.
See docs/DASHBOARD_ACCESS.md for installation steps.
"""
from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def _is_port_open(port: int = 8501) -> bool:
    """Check if anything is listening on the given port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            return True
    except OSError:
        return False


def _ensure_streamlit_running() -> bool:
    """Start Streamlit if it's not already running. Returns True if running."""
    if _is_port_open(8501):
        print("[dashboard_serve] streamlit already on :8501")
        return True
    print("[dashboard_serve] streamlit not running, starting it...")
    # Use NSSM service if available, otherwise spawn directly
    try:
        out = subprocess.run(
            ["nssm", "status", "KotakDashboard"],
            capture_output=True, text=True, timeout=5
        )
        if "SERVICE_RUNNING" in (out.stdout or ""):
            print("[dashboard_serve] starting NSSM service KotakDashboard")
            subprocess.run(["nssm", "start", "KotakDashboard"], check=False)
            time.sleep(4)
            return _is_port_open(8501)
    except FileNotFoundError:
        pass
    print("[dashboard_serve] ERROR: Streamlit not running and NSSM not found.")
    print("[dashboard_serve] Start it manually: nssm start KotakDashboard")
    return False


def _check_binary(name: str) -> bool:
    if shutil.which(name):
        return True
    print(f"[dashboard_serve] ERROR: '{name}' binary not found on PATH.")
    print(f"[dashboard_serve] See docs/DASHBOARD_ACCESS.md for install steps.")
    return False


def serve_local() -> int:
    """Just verify Streamlit is up and print the local URL."""
    if not _ensure_streamlit_running():
        return 1
    print("[dashboard_serve] local URL: http://localhost:8501")
    print("[dashboard_serve] (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        return 0


def serve_ngrok() -> int:
    """Expose via ngrok."""
    if not _ensure_streamlit_running():
        return 1
    if not _check_binary("ngrok"):
        return 1
    print("[dashboard_serve] launching ngrok http 8501...")
    print("[dashboard_serve] (Ctrl+C to stop)")
    try:
        return subprocess.call(["ngrok", "http", "8501"])
    except KeyboardInterrupt:
        return 0


def serve_cloudflare() -> int:
    """Expose via Cloudflare quick tunnel."""
    if not _ensure_streamlit_running():
        return 1
    if not _check_binary("cloudflared"):
        return 1
    print("[dashboard_serve] launching cloudflared quick tunnel...")
    print("[dashboard_serve] (Ctrl+C to stop)")
    try:
        return subprocess.call([
            "cloudflared", "tunnel", "--url", "http://localhost:8501"
        ])
    except KeyboardInterrupt:
        return 0


def serve_tailscale() -> int:
    """Expose via Tailscale Funnel."""
    if not _ensure_streamlit_running():
        return 1
    if not _check_binary("tailscale"):
        return 1
    # Check if tailscale is connected
    try:
        out = subprocess.run(
            ["tailscale", "status"], capture_output=True, text=True, timeout=5
        )
        if out.returncode != 0:
            print("[dashboard_serve] ERROR: tailscale not authenticated.")
            print("[dashboard_serve] Run: tailscale up")
            return 1
    except FileNotFoundError:
        print("[dashboard_serve] tailscale binary not found.")
        return 1
    print("[dashboard_serve] enabling Tailscale Funnel on :8501...")
    subprocess.run(["tailscale", "funnel", "8501", "on"], check=False)
    print("[dashboard_serve] (Ctrl+C to stop)")
    print("[dashboard_serve] view your dashboard at the URL Tailscale printed.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        subprocess.run(["tailscale", "funnel", "8501", "off"], check=False)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Expose local Streamlit dashboard to a network."
    )
    ap.add_argument(
        "--mode",
        choices=["local", "ngrok", "cloudflare", "tailscale"],
        default="tailscale",
        help="Tunnel mode (default: tailscale)",
    )
    args = ap.parse_args()
    handlers = {
        "local": serve_local,
        "ngrok": serve_ngrok,
        "cloudflare": serve_cloudflare,
        "tailscale": serve_tailscale,
    }
    return handlers[args.mode]()


if __name__ == "__main__":
    sys.exit(main())