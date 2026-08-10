"""Telegram alerter + voice + chart capabilities.

Sends text alerts via direct httpx (no event loop).
On fills / EOD / anomalies, optionally synthesizes a short voice MP3 and sends it.
Generates a daily P&L chart as PNG and sends it to Telegram.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# load .env if not already loaded
_env_path = Path(__file__).parent.parent.parent / "config" / "credentials.env"
if _env_path.exists():
    load_dotenv(str(_env_path))

from loguru import logger


class TelegramAlerter:
    def __init__(self, bot_token: str = "", chat_id: str = "", voice_enabled: bool = True):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._initial_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._env_path = "config/credentials.env"
        self.enabled = bool(self.bot_token)
        self.voice_enabled = voice_enabled
        if not self.bot_token:
            logger.warning("TelegramAlerter disabled — set TELEGRAM_BOT_TOKEN")
        elif not self._initial_chat_id:
            logger.info("TelegramAlerter: bot token set, waiting for chat_id")
        # voice scratch dir
        self._voice_dir = Path("data_cache/voice_alerts")
        self._voice_dir.mkdir(parents=True, exist_ok=True)
        self._chart_dir = Path("data_cache/charts")
        self._chart_dir.mkdir(parents=True, exist_ok=True)

    def _get_chat_id(self) -> str:
        env_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if env_id:
            return env_id
        try:
            text = Path(self._env_path).read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith("TELEGRAM_CHAT_ID="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
        return self._initial_chat_id

    def _api_call(self, method: str, **params):
        if not self.enabled:
            return {"ok": False, "error": "alerter_disabled"}
        import httpx
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        try:
            if method == "sendPhoto":
                # multipart for photos
                with httpx.Client(timeout=30) as c:
                    with open(params["photo_path"], "rb") as f:
                        resp = c.post(
                            url,
                            data={"chat_id": params.get("chat_id"), "caption": params.get("caption", "")},
                            files={"photo": (Path(params["photo_path"]).name, f, "image/png")},
                        )
            else:
                with httpx.Client(timeout=20) as client:
                    resp = client.post(url, json=params)
            return resp.json() if resp else {"ok": False}
        except Exception as e:
            logger.warning(f"Telegram API call {method} failed: {e}")
            return {"ok": False, "error": str(e)}

    def send(self, message: str, parse_mode: str = None) -> bool:
        if not self.enabled:
            logger.debug(f"[TG-DRY-RUN] {message}")
            return False
        chat_id = self._get_chat_id()
        if not chat_id:
            return False
        kwargs = {"chat_id": chat_id, "text": message[:4000]}  # Telegram limit
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        resp = self._api_call("sendMessage", **kwargs)
        if resp.get("ok"):
            return True
        logger.warning(f"Telegram send failed: {resp}")
        return False

    def send_voice(self, mp3_path: Path, caption: str = "") -> bool:
        """Send a pre-generated MP3 voice message."""
        if not self.enabled or not mp3_path.exists():
            return False
        chat_id = self._get_chat_id()
        if not chat_id:
            return False
        import httpx
        url = f"https://api.telegram.org/bot{self.bot_token}/sendVoice"
        try:
            with httpx.Client(timeout=30) as c:
                with open(mp3_path, "rb") as f:
                    resp = c.post(url, data={"chat_id": chat_id, "caption": caption[:200]}, files={"voice": (mp3_path.name, f, "audio/mpeg")})
            return resp.json().get("ok", False)
        except Exception as e:
            logger.warning(f"send_voice failed: {e}")
            return False

    def send_photo(self, png_path: Path, caption: str = "") -> bool:
        if not self.enabled or not png_path.exists():
            return False
        chat_id = self._get_chat_id()
        if not chat_id:
            return False
        resp = self._api_call("sendPhoto", chat_id=chat_id, caption=caption[:200], photo_path=str(png_path))
        return resp.get("ok", False)

    # ------- voice synthesis (uses local TTS via PowerShell SAPI on Windows) -------
    def synthesize_voice(self, text: str, label: str = "alert") -> Optional[Path]:
        """Synthesize text to MP3 using Windows SAPI (PowerShell SpeechSynthesizer).
        Returns the MP3 path or None on failure.
        """
        if not self.voice_enabled:
            return None
        try:
            out_mp3 = self._voice_dir / f"{label}_{int(time.time())}.wav"
            # Use PowerShell System.Speech.Synthesis
            ps_cmd = f"""
Add-Type -AssemblyName System.Speech
$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speak.SetOutputToWaveFile('{out_mp3}')
$speak.Speak('{text.replace("'", "''")}')
$speak.Dispose()
"""
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=20,
            )
            if result.returncode == 0 and out_mp3.exists():
                logger.info(f"voice: synthesized {out_mp3.name}")
                return out_mp3
            else:
                logger.debug(f"voice synth skipped: rc={result.returncode}")
                return None
        except Exception as e:
            logger.warning(f"voice synth failed: {e}")
            return None

    def voice_alert(self, text: str, label: str = "alert", also_text: bool = True) -> None:
        """Synthesize voice + send to Telegram. Optionally also send text."""
        if also_text:
            self.send(f"🔊 {text}")
        mp3 = self.synthesize_voice(text, label=label)
        if mp3:
            self.send_voice(mp3, caption=text[:200])

    # ------- chart generation (P&L curve) -------
    def generate_daily_chart(self, trades_csv: Path = Path("logs/trades.csv"),
                             out_path: Optional[Path] = None) -> Optional[Path]:
        """Generate a daily P&L chart using matplotlib (lightweight) and return the PNG path.
        Falls back to None if matplotlib is not installed.
        """
        out_path = out_path or (self._chart_dir / f"pnl_{date.today().isoformat()}.png")
        if not trades_csv.exists():
            logger.warning(f"chart: {trades_csv} not found")
            return None
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available — install for charts")
            return None
        # load today's trades
        today = date.today().isoformat()
        rows = []
        with open(trades_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                ts = r.get("timestamp", "")
                if today in ts or date.today().strftime("%Y-%m-%d") in ts:
                    try:
                        pnl = float(r.get("fill_price", 0)) - float(r.get("price", 0))
                        # rough estimate: BUY pnl = current - cost; SELL pnl = cost - current
                        side = r.get("side", "")
                        if side == "BUY":
                            pnl = -float(r.get("price", 0))  # cost
                        else:
                            pnl = float(r.get("price", 0))  # credit
                        rows.append((ts, pnl, side, r.get("symbol", "")))
                    except Exception:
                        continue
        if not rows:
            return None
        # build chart
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), gridspec_kw={"height_ratios": [2, 1]})
        # cumulative P&L
        cum_pnl = []
        running = 0.0
        times = []
        for i, (ts, pnl, side, sym) in enumerate(rows):
            running += pnl
            cum_pnl.append(running)
            times.append(i)
        ax1.plot(times, cum_pnl, marker='o', color='green' if running >= 0 else 'red', linewidth=2)
        ax1.set_title(f"Daily P&L — {today}\nNet: ₹{running:,.0f} | Trades: {len(rows)}", fontsize=12, fontweight='bold')
        ax1.set_ylabel("Cumulative P&L (₹)")
        ax1.axhline(0, color='gray', linestyle='--', alpha=0.5)
        ax1.grid(True, alpha=0.3)
        # per-trade
        colors = ['green' if side == 'SELL' else 'red' for _, _, side, _ in rows]
        ax2.bar(range(len(rows)), [p for _, p, _, _ in rows], color=colors, alpha=0.7)
        ax2.set_xlabel("Trade #")
        ax2.set_ylabel("Leg P&L (₹)")
        ax2.axhline(0, color='gray', linestyle='--', alpha=0.5)
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_path, dpi=120, bbox_inches='tight')
        plt.close()
        logger.info(f"chart: saved {out_path}")
        return out_path

    # ------- the typed alert methods -------
    def info(self, msg: str) -> None:
        self.send(f"ℹ️ {msg}")

    def warn(self, msg: str) -> None:
        self.send(f"⚠️ {msg}")

    def critical(self, msg: str) -> None:
        self.send(f"🚨 {msg}")

    def trade_opened(self, plan) -> None:
        legs = ", ".join(f"{l['side']} {l.get('strike','')}{l.get('opt_type','')}" for l in plan.legs)
        msg = (
            f"📈 OPENED {plan.strategy.value}\n"
            f"Underlying: {plan.underlying}\n"
            f"Legs: {legs}\n"
            f"Target: Rs.{plan.target:.0f} | Stop: Rs.{plan.stop:.0f}\n"
            f"Reason: {plan.reason}"
        )
        self.send(msg)
        # voice alert
        try:
            short = f"Opened {plan.strategy.value} on {plan.underlying}. {len(plan.legs)} legs. Target {int(plan.target)} rupees, stop {int(plan.stop)}."
            self.voice_alert(short, label=f"open_{plan.underlying}_{int(time.time())}")
        except Exception as e:
            logger.debug(f"voice alert failed: {e}")

    def trade_closed(self, pnl: float, reason: str = "") -> None:
        emoji = "✅" if pnl > 0 else "❌"
        msg = f"{emoji} CLOSED P&L: Rs.{pnl:,.0f}\nReason: {reason}"
        self.send(msg)
        try:
            short = f"Closed trade. {'Profit' if pnl > 0 else 'Loss'} {int(abs(pnl))} rupees."
            self.voice_alert(short, label=f"close_{int(time.time())}")
        except Exception:
            pass

    def daily_report(self, summary: dict) -> None:
        msg = (
            f"📊 Daily Report\n"
            f"P&L: Rs.{summary.get('daily_pnl', 0):,.0f}\n"
            f"Trades: {summary.get('trades_today', 0)}\n"
            f"Open: {summary.get('open_positions', 0)}\n"
            f"Preset: {summary.get('risk_preset', 'base')}\n"
            f"Capital: Rs.{summary.get('capital', 0):,.0f}"
        )
        self.send(msg)
        # send chart
        try:
            chart = self.generate_daily_chart()
            if chart:
                self.send_photo(chart, caption=f"Daily P&L chart — {date.today().isoformat()}")
        except Exception as e:
            logger.warning(f"daily chart failed: {e}")
