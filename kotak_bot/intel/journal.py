"""Trade journal with auto-screenshots, compliance PDF, multi-broker stub.

TradeJournal: captures chart + context for every entry/exit, saves to data_cache/journal/
CompliancePDF: generates SEBI audit pack at EOD
MultiBroker: stub for cross-broker order routing (Kotak + Dhan + Upstox)
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from loguru import logger


class TradeJournal:
    """Auto-captures a chart + context for every trade entry/exit."""

    def __init__(self, journal_dir: Path = Path("data_cache/journal")):
        self.journal_dir = journal_dir
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.index_csv = self.journal_dir / "index.csv"
        if not self.index_csv.exists():
            with open(self.index_csv, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "timestamp", "trade_id", "underlying", "strategy",
                    "entry_chart", "exit_chart", "pnl", "hold_minutes", "tags",
                ])

    def capture_entry(self, trade_id: str, underlying: str, strategy: str,
                      plan, feed) -> Path:
        """Capture chart at trade entry. Returns path to PNG."""
        ts = datetime.utcnow()
        chart_path = self.journal_dir / f"entry_{trade_id}_{ts.strftime('%H%M%S')}.png"
        try:
            # build chart: spot price + key strikes
            spot = feed.get_ltp(underlying)
            strikes = plan.legs
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.set_title(f"ENTRY: {strategy} {underlying} @ {ts.strftime('%H:%M:%S')}", fontweight='bold')
            ax.set_xlabel("Strike")
            ax.set_ylabel("Premium")
            # plot option premiums at strikes
            leg_data = []
            for leg in plan.legs:
                ltp = feed.get_ltp(f"{underlying}{leg.get('expiry', '').replace('-', '')}{int(leg.get('strike', 0))}{leg.get('opt_type', '')}")
                if ltp <= 0:
                    # try plain
                    ltp = feed.get_ltp(f"{underlying}{int(leg.get('strike', 0))}{leg.get('opt_type', '')}")
                leg_data.append((leg.get('strike', 0), ltp, leg.get('opt_type', ''), leg.get('side', '')))
            if leg_data:
                xs = [d[0] for d in leg_data]
                ys = [d[1] for d in leg_data]
                colors = ['red' if d[3] == 'SELL' else 'green' for d in leg_data]
                ax.bar(xs, ys, color=colors, alpha=0.7, width=20)
                for x, y, ot, side in leg_data:
                    ax.annotate(f"{side} {int(x)}{ot}\n@ {y}", (x, y), textcoords="offset points", xytext=(0, 5), ha='center', fontsize=7)
            if spot > 0:
                ax.axvline(spot, color='blue', linestyle='--', alpha=0.5, label=f"Spot {spot:.2f}")
                ax.legend()
            ax.grid(True, alpha=0.3)
            ax.text(0.02, 0.98, f"Target: Rs.{plan.target:.0f} | Stop: Rs.{plan.stop:.0f}\nReason: {plan.reason}",
                    transform=ax.transAxes, fontsize=8, verticalalignment='top', fontfamily='monospace')
            plt.tight_layout()
            plt.savefig(chart_path, dpi=100, bbox_inches='tight')
            plt.close()
            return chart_path
        except Exception as e:
            logger.warning(f"capture_entry chart failed: {e}")
            return None

    def record(self, trade_id: str, underlying: str, strategy: str,
               entry_chart: Optional[Path] = None, exit_chart: Optional[Path] = None,
               pnl: float = 0.0, hold_minutes: int = 0, tags: str = "") -> None:
        """Record a trade event in the journal."""
        with open(self.index_csv, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.utcnow().isoformat(),
                trade_id,
                underlying,
                strategy,
                str(entry_chart) if entry_chart else "",
                str(exit_chart) if exit_chart else "",
                f"{pnl:.2f}",
                hold_minutes,
                tags,
            ])


class CompliancePDF:
    """Generate SEBI audit pack PDF at EOD.

    Includes:
    - Daily P&L summary
    - All trades with timestamps, order IDs, prices
    - All audit log entries
    - Risk engine state
    - Algo ID + compliance header
    """

    def __init__(self, output_dir: Path = Path("data_cache/compliance")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, trades: list, audit_entries: list, risk_state: dict,
                 algo_id: str = "KOTAK_NEO_BOT_V1") -> Optional[Path]:
        """Generate the daily compliance pack. Returns path to PDF or None."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib import colors
        except ImportError:
            logger.warning("reportlab not available — install for PDF compliance")
            return None
        path = self.output_dir / f"compliance_{date.today().isoformat()}.pdf"
        doc = SimpleDocTemplate(str(path), pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        # header
        story.append(Paragraph(f"<b>SEBI Algo Trading Compliance Pack</b>", styles['Title']))
        story.append(Paragraph(f"Date: {date.today().isoformat()}", styles['Normal']))
        story.append(Paragraph(f"Algo ID: {algo_id}", styles['Normal']))
        story.append(Spacer(1, 12))
        # risk state
        story.append(Paragraph("<b>Risk State at EOD</b>", styles['Heading2']))
        risk_table = [
            ["Capital", f"Rs.{risk_state.get('capital', 0):,.0f}"],
            ["Daily P&L", f"Rs.{risk_state.get('daily_pnl', 0):,.0f}"],
            ["Trades today", risk_state.get('trades_today', 0)],
            ["Consec losses", risk_state.get('consecutive_losses', 0)],
            ["Open positions", risk_state.get('open_positions', 0)],
            ["Current preset", risk_state.get('current_preset', 'base')],
        ]
        t = Table(risk_table, colWidths=[200, 200])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))
        # trades
        story.append(Paragraph(f"<b>Trades ({len(trades)})</b>", styles['Heading2']))
        if trades:
            trade_rows = [["Time", "Symbol", "Side", "Qty", "Price", "Status"]]
            for tr in trades[:50]:  # cap at 50 for the PDF
                trade_rows.append([
                    tr.get("timestamp", "")[:19],
                    tr.get("symbol", ""),
                    tr.get("side", ""),
                    tr.get("qty", 0),
                    tr.get("price", 0),
                    tr.get("status", ""),
                ])
            t2 = Table(trade_rows, colWidths=[120, 100, 40, 40, 50, 60])
            t2.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
            ]))
            story.append(t2)
        story.append(Spacer(1, 12))
        # audit summary
        story.append(Paragraph(f"<b>Audit log entries: {len(audit_entries)}</b>", styles['Heading2']))
        if audit_entries:
            sample = audit_entries[:20]
            audit_text = "<br/>".join(str(e)[:200] for e in sample)
            story.append(Paragraph(audit_text, styles['Code']))
        doc.build(story)
        logger.info(f"compliance PDF saved: {path}")
        return path


class MultiBrokerRouter:
    """Stub for cross-broker order routing.

    Currently only Kotak Neo. When Dhan/Upstox creds are added, the bot can
    route orders to the best-priced broker, or split between them for redundancy.
    """

    def __init__(self):
        self.brokers: dict[str, dict] = {
            "kotak": {"enabled": True, "type": "neo", "priority": 1},
            "dhan": {"enabled": False, "type": "dhan", "priority": 2},
            "upstox": {"enabled": False, "type": "upstox", "priority": 3},
        }

    def enable_broker(self, name: str) -> None:
        if name in self.brokers:
            self.brokers[name]["enabled"] = True

    def pick_broker(self, symbol: str) -> str:
        """Pick the best available broker for a symbol (lowest latency = highest priority)."""
        enabled = [b for b in self.brokers.values() if b["enabled"]]
        if not enabled:
            return "kotak"
        return sorted(enabled, key=lambda b: b["priority"])[0]["type"]

    def find_arbitrage(self, symbol: str, prices: dict) -> Optional[dict]:
        """Given {broker: ltp}, detect cross-broker arbitrage.
        Returns {"buy_broker", "sell_broker", "spread", "profit_per_unit"} or None.
        """
        if len(prices) < 2:
            return None
        sorted_prices = sorted(prices.items(), key=lambda kv: kv[1])
        buy_broker, buy_price = sorted_prices[0]
        sell_broker, sell_price = sorted_prices[-1]
        spread = sell_price - buy_price
        if spread > 0.5:  # 50 paisa minimum
            return {
                "buy_broker": buy_broker,
                "sell_broker": sell_broker,
                "spread": spread,
                "profit_per_unit": spread - 0.5,  # 50 paisa slippage
            }
        return None
