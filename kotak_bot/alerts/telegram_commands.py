"""Telegram command handler.

Responds to user messages with bot status, allows pause/resume, and answers questions.
Runs as a background poller — picks up commands from the user.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv
from loguru import logger

_env_path = Path(__file__).parent.parent.parent / "config" / "credentials.env"
if _env_path.exists():
    load_dotenv(str(_env_path))


class TelegramCommandHandler:
    """Polls Telegram for user commands, dispatches to callbacks, replies."""

    def __init__(self, bot_token: str = ""):
        self.bot_token = bot_token or __import__("os").getenv("TELEGRAM_BOT_TOKEN", "")
        self._env_path = "config/credentials.env"
        self._offset = None
        self._running = False
        self._thread = None
        # command dispatch
        self._commands: dict[str, Callable[[str, dict], str]] = {}
        self._register_default_commands()
        # external state hooks
        self.get_status: Optional[Callable[[], dict]] = None
        self.pause: Optional[Callable[[str], str]] = None
        self.resume: Optional[Callable[[], str]] = None
        self.force_close: Optional[Callable[[], str]] = None
        self.force_trade: Optional[Callable[[str], str]] = None  # arg = symbol (NIFTY/BANKNIFTY)

    def _get_chat_id(self) -> str:
        env_id = __import__("os").getenv("TELEGRAM_CHAT_ID", "")
        if env_id:
            return env_id
        try:
            text = Path(self._env_path).read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith("TELEGRAM_CHAT_ID="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
        return ""

    def _register_default_commands(self) -> None:
        self._commands["/start"] = self._cmd_help
        self._commands["/help"] = self._cmd_help
        self._commands["/status"] = self._cmd_status
        self._commands["/pause"] = self._cmd_pause
        self._commands["/resume"] = self._cmd_resume
        self._commands["/close"] = self._cmd_close
        self._commands["/positions"] = self._cmd_positions
        self._commands["/pnl"] = self._cmd_pnl
        self._commands["/regime"] = self._cmd_regime
        self._commands["/ping"] = self._cmd_ping
        self._commands["/time"] = self._cmd_time
        self._commands["/force_trade"] = self._cmd_force_trade
        self._commands["/force"] = self._cmd_force_trade
        self._commands["/oi"] = self._cmd_oi
        self._commands["/perf"] = self._cmd_perf

    def register(self, command: str, handler: Callable[[str, dict], str]) -> None:
        self._commands[command] = handler

    def start(self) -> None:
        if not self.bot_token:
            logger.warning("TelegramCommandHandler disabled — no TELEGRAM_BOT_TOKEN")
            return
        if self._running:
            return
        self._running = True
        import threading
        self._thread = threading.Thread(target=self._poll_loop, name="tg-cmd", daemon=True)
        self._thread.start()
        logger.info("TelegramCommandHandler started")

    def stop(self) -> None:
        self._running = False

    def _poll_loop(self) -> None:
        # short long-poll (5s) — more responsive to user commands
        while self._running:
            try:
                url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
                if self._offset is not None:
                    url += f"?offset={self._offset + 1}&timeout=5"
                else:
                    url += "?timeout=5"
                with urllib.request.urlopen(url, timeout=15) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if not data.get("ok"):
                    time.sleep(2)
                    continue
                for u in data.get("result", []):
                    self._offset = u.get("update_id", self._offset)
                    msg = u.get("message") or u.get("edited_message") or {}
                    text = msg.get("text", "").strip()
                    chat = msg.get("chat", {})
                    if not text or chat.get("id") != int(self._get_chat_id()):
                        continue
                    logger.info(f"CMD received: {text[:60]}")
                    # dispatch
                    parts = text.split(maxsplit=1)
                    cmd = parts[0].lower().split("@")[0]  # strip @botname
                    arg = parts[1] if len(parts) > 1 else ""
                    handler = self._commands.get(cmd)
                    if not handler:
                        self._reply(chat["id"], f"Unknown command: {cmd}\n\nType /help for the list.")
                        continue
                    try:
                        reply = handler(arg, msg)
                        logger.info(f"CMD reply: {cmd} -> {reply[:60]}")
                    except Exception as e:
                        logger.exception(f"command {cmd} failed: {e}")
                        reply = f"Error running {cmd}: {e}"
                    self._reply(chat["id"], reply)
            except Exception as e:
                logger.debug(f"cmd poll: {e}")
                time.sleep(2)

    def _reply(self, chat_id: int, text: str) -> None:
        import httpx
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=10) as c:
                c.post(url, json={"chat_id": chat_id, "text": text})
        except Exception as e:
            logger.warning(f"reply failed: {e}")

    # ------- default command handlers -------
    def _cmd_help(self, arg: str, msg: dict) -> str:
        return (
            "Kotak Neo Trading Bot — Commands\n"
            "\n"
            "/status   — bot state, P&L, positions count\n"
            "/positions — current open positions\n"
            "/pnl      — today/week/month P&L\n"
            "/regime   — current market regime + ADX + VIX\n"
            "/force [NIFTY|BANKNIFTY] — force a paper trade now (bypass gates)\n"
            "/pause [reason]  — pause new entries (keeps monitoring)\n"
            "/resume  — resume new entries\n"
            "/close    — force-close all open positions now\n"
            "/time     — current IST time + market session\n"
            "/ping     — check if bot is alive\n"
            "\n"
            "You can also just chat — I'll try to help."
        )

    def _cmd_ping(self, arg: str, msg: dict) -> str:
        return f"Pong. Bot is alive. Chat id: {msg['chat']['id']}"

    def _cmd_time(self, arg: str, msg: dict) -> str:
        from kotak_bot.utils.clock import now_ist, market_session
        from datetime import datetime
        n = now_ist()
        return (
            f"IST: {n.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Session: {market_session(n)}\n"
            f"Market hours: 9:00-15:30 IST"
        )

    def _cmd_status(self, arg: str, msg: dict) -> str:
        if self.get_status:
            try:
                s = self.get_status()
                return self._format_status(s)
            except Exception as e:
                return f"Status error: {e}"
        return "Status not wired up yet (handler hook not set)"

    def _cmd_pnl(self, arg: str, msg: dict) -> str:
        if self.get_status:
            try:
                s = self.get_status()
                return (
                    f"P&L Report\n"
                    f"  Today:    Rs.{s.get('daily_pnl', 0):,.0f}\n"
                    f"  This week: Rs.{s.get('weekly_pnl', 0):,.0f}\n"
                    f"  This month: Rs.{s.get('monthly_pnl', 0):,.0f}\n"
                    f"  Trades today: {s.get('trades_today', 0)}\n"
                    f"  Open positions: {s.get('open_positions', 0)}"
                )
            except Exception as e:
                return f"PnL error: {e}"
        return "PnL not available"

    def _cmd_positions(self, arg: str, msg: dict) -> str:
        if self.get_status:
            try:
                s = self.get_status()
                positions = s.get("positions", [])
                if not positions:
                    return "No open positions"
                lines = [f"{p['symbol']:30s}  qty={p['qty']:+d}  avg={p['avg_price']:.2f}  ltp={p['ltp']:.2f}  pnl=Rs.{p['pnl']:,.0f}" for p in positions]
                return "Open positions:\n" + "\n".join(lines)
            except Exception as e:
                return f"Positions error: {e}"
        return "Positions not available"

    def _cmd_regime(self, arg: str, msg: dict) -> str:
        if self.get_status:
            try:
                s = self.get_status()
                return (
                    f"Current regime: {s.get('regime', 'unknown').upper()}\n"
                    f"  ADX: {s.get('adx', 0):.1f}\n"
                    f"  VIX: {s.get('vix', 0):.1f}\n"
                    f"  IV rank: {s.get('iv_rank', 0):.0f}\n"
                    f"  Confidence: {s.get('regime_confidence', 0):.0%}"
                )
            except Exception as e:
                return f"Regime error: {e}"
        return "Regime data not available"

    def _cmd_pause(self, arg: str, msg: dict) -> str:
        reason = arg or "manual_pause_via_telegram"
        if self.pause:
            try:
                return self.pause(reason)
            except Exception as e:
                return f"Pause error: {e}"
        return "Pause hook not wired up"

    def _cmd_resume(self, arg: str, msg: dict) -> str:
        if self.resume:
            try:
                return self.resume()
            except Exception as e:
                return f"Resume error: {e}"
        return "Resume hook not wired up"

    def _cmd_close(self, arg: str, msg: dict) -> str:
        if self.force_close:
            try:
                return self.force_close()
            except Exception as e:
                return f"Close error: {e}"
        return "Force-close hook not wired up"

    def _cmd_force_trade(self, arg: str, msg: dict) -> str:
        """Force a paper trade now (bypasses regime/risk gates for testing end-to-end flow).
        Usage: /force_trade NIFTY   or   /force NIFTY
        """
        if not self.force_trade:
            return "Force-trade hook not wired up"
        sym = (arg or "NIFTY").strip().upper()
        if sym not in ("NIFTY", "BANKNIFTY"):
            return f"Invalid symbol: {sym}. Use NIFTY or BANKNIFTY."
        try:
            return self.force_trade(sym)
        except Exception as e:
            return f"Force-trade error: {e}"

    def _cmd_oi(self, arg: str, msg: dict) -> str:
        """Show OI walls + max pain for the given symbol (default NIFTY)."""
        try:
            sym = (arg or "NIFTY").strip().upper()
            if sym not in ("NIFTY", "BANKNIFTY"):
                return f"Invalid: {sym}"
            from kotak_bot.intel.oi_analytics import oi_walls, max_pain, pcr, gex
            # need access to live_feed — read from cmd handler context if set
            feed = getattr(self, "live_feed", None)
            if not feed:
                return "LiveFeed not wired up to /oi command"
            oi_map = feed.get_oi_map(sym)
            if not oi_map:
                return f"No OI data for {sym} yet (synthetic may not have option ticks)"
            walls = oi_walls(oi_map)
            mp = max_pain(oi_map)
            ratio = pcr(oi_map)
            spot = feed.get_ltp(sym)
            return (
                f"📊 OI Analytics — {sym} @ spot {spot:.2f}\n"
                f"  Resistance (max CE OI): {walls.get('resistance')} (OI: {walls.get('resistance_oi', 0)})\n"
                f"  Support (max PE OI):     {walls.get('support')} (OI: {walls.get('support_oi', 0)})\n"
                f"  Max Pain:                {mp}\n"
                f"  Put-Call Ratio (OI):     {ratio:.2f}\n"
                f"  Interpretation: {'bullish' if ratio > 1.0 else 'bearish' if ratio < 0.7 else 'neutral'}"
            )
        except Exception as e:
            return f"OI command error: {e}"

    def _cmd_perf(self, arg: str, msg: dict) -> str:
        """Show performance attribution for all strategies."""
        try:
            perf_tracker = getattr(self, "perf_tracker", None)
            if not perf_tracker:
                return "Performance tracker not wired up to /perf command"
            return perf_tracker.summary()
        except Exception as e:
            return f"Perf command error: {e}"

    def _format_status(self, s: dict) -> str:
        paused = "PAUSED" if s.get("paused") else "ACTIVE"
        return (
            f"Bot Status: {paused}\n"
            f"  Capital: Rs.{s.get('capital', 0):,.0f}\n"
            f"  Today P&L: Rs.{s.get('daily_pnl', 0):,.0f}\n"
            f"  Week P&L: Rs.{s.get('weekly_pnl', 0):,.0f}\n"
            f"  Trades today: {s.get('trades_today', 0)}\n"
            f"  Open positions: {s.get('open_positions', 0)}\n"
            f"  Consec losses: {s.get('consecutive_losses', 0)}\n"
            f"  Regime: {s.get('regime', 'unknown')}\n"
            f"  Data source: {s.get('data_source', 'synthetic')}\n"
            f"  Broker: {s.get('broker_type', 'paper')}\n"
            f"  Pause reason: {s.get('pause_reason', 'none')}"
        )
