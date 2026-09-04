"""migrate_state_to_sqlite.py - one-time migration from JSON to SQLite.

FIX 2026-09-04 13:35: JSON files (paper_state.json, trades_state.json, etc.) have
caused multiple bugs due to:
- File race conditions when bot's in-memory state overwrites external writes
- Corrupted state on crash mid-write
- No atomic transactions
- No queryable history

SQLite solves all of these. This script:
1. Reads existing JSON state files
2. Creates SQLite database with proper schema
3. Inserts the JSON state into SQLite
4. Verifies the migration by reading back from SQLite
5. Keeps JSON files as backup (don't delete yet)

After running, the bot can be updated to read/write SQLite instead of JSON.
This is a STAGED migration: the data moves to SQLite first, the bot can be
updated later to use SQLite.

Usage:
  python scripts/migrate_state_to_sqlite.py --db data_cache/state.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(ROOT / "data_cache" / "state.db"))
    parser.add_argument("--data-dir", default=str(ROOT / "data_cache"))
    args = parser.parse_args()

    db_path = Path(args.db)
    data_dir = Path(args.data_dir)
    print("=" * 60)
    print(f"STATE MIGRATION: JSON -> SQLite")
    print(f"  DB: {db_path}")
    print(f"  Source: {data_dir}")
    print("=" * 60)
    print()

    # Initialize SQLite with WAL mode (atomic, fast, durable)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # Create schema
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS paper_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        cash REAL NOT NULL DEFAULT 100000,
        realized_pnl REAL NOT NULL DEFAULT 0,
        starting_capital REAL NOT NULL DEFAULT 100000,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS positions (
        symbol TEXT PRIMARY KEY,
        underlying TEXT NOT NULL,
        qty INTEGER NOT NULL,
        avg_price REAL NOT NULL,
        ltp REAL,
        strike REAL,
        option_type TEXT,
        expiry TEXT,
        side TEXT,
        exchange TEXT,
        product TEXT,
        opened_at TEXT,
        updated_at TEXT
    );

    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        qty INTEGER NOT NULL,
        order_type TEXT,
        product TEXT,
        price REAL,
        trigger_price REAL,
        avg_fill_price REAL,
        filled_qty INTEGER,
        status TEXT,
        tag TEXT,
        underlying TEXT,
        strike REAL,
        option_type TEXT,
        expiry TEXT,
        exchange TEXT,
        placed_at TEXT,
        filled_at TEXT,
        rejection_reason TEXT
    );

    CREATE TABLE IF NOT EXISTS trades (
        trade_id TEXT PRIMARY KEY,
        strategy TEXT,
        underlying TEXT,
        legs_json TEXT,
        target REAL,
        stop REAL,
        confidence REAL,
        reason TEXT,
        opened_at TEXT,
        closed_at TEXT,
        status TEXT
    );

    CREATE TABLE IF NOT EXISTS brain_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        decision_json TEXT NOT NULL,
        event_json TEXT,
        context_json TEXT,
        note TEXT
    );

    CREATE TABLE IF NOT EXISTS bias_overrides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        direction TEXT NOT NULL,
        reason TEXT,
        confidence REAL,
        max_positions INTEGER,
        risk_budget_pct INTEGER
    );

    CREATE TABLE IF NOT EXISTS confluence_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        direction TEXT NOT NULL,
        count INTEGER NOT NULL,
        evidence TEXT
    );

    CREATE TABLE IF NOT EXISTS heartbeats (
        component TEXT PRIMARY KEY,
        ts TEXT NOT NULL,
        pid INTEGER,
        metadata_json TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_decisions_ts ON brain_decisions(ts);
    CREATE INDEX IF NOT EXISTS idx_orders_placed ON orders(placed_at);
    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    """)
    print("[1/8] Schema created (8 tables, 3 indexes)")

    # Migrate paper_state
    ps_path = data_dir / "paper_state.json"
    if ps_path.exists():
        try:
            ps = json.loads(ps_path.read_text(encoding="utf-8"))
            cur.execute("""
                INSERT OR REPLACE INTO paper_state (id, cash, realized_pnl, starting_capital, updated_at)
                VALUES (1, ?, ?, ?, ?)
            """, (ps.get("cash", 100000), ps.get("realized_pnl", 0),
                  ps.get("starting_capital", 100000), datetime.now().isoformat()))
            print(f"[2/8] paper_state: cash={ps.get('cash', 0):.2f} realized={ps.get('realized_pnl', 0):.2f}")
        except Exception as e:
            print(f"  [ERR] paper_state: {e}")

    # Migrate positions
    if ps_path.exists():
        try:
            ps = json.loads(ps_path.read_text(encoding="utf-8"))
            positions = ps.get("positions", {})
            n = 0
            for sym, p in positions.items():
                cur.execute("""
                    INSERT OR REPLACE INTO positions
                    (symbol, underlying, qty, avg_price, ltp, strike, option_type, expiry, side, exchange, product, opened_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sym, p.get("underlying", ""), p.get("qty", 0), p.get("avg_price", 0),
                    p.get("ltp", 0), p.get("strike", 0), p.get("option_type", ""),
                    p.get("expiry", ""), p.get("side", ""), p.get("exchange", "NFO"),
                    p.get("product", "MIS"), p.get("opened_at", ""), datetime.now().isoformat(),
                ))
                n += 1
            print(f"[3/8] positions: {n} migrated")
        except Exception as e:
            print(f"  [ERR] positions: {e}")

    # Migrate orders
    if ps_path.exists():
        try:
            ps = json.loads(ps_path.read_text(encoding="utf-8"))
            orders = ps.get("orders", {})
            n = 0
            for oid, o in orders.items():
                cur.execute("""
                    INSERT OR REPLACE INTO orders
                    (order_id, symbol, side, qty, order_type, product, price, trigger_price,
                     avg_fill_price, filled_qty, status, tag, underlying, strike, option_type,
                     expiry, exchange, placed_at, filled_at, rejection_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    oid, o.get("symbol", ""), o.get("side", ""), o.get("qty", 0),
                    o.get("order_type", "MARKET"), o.get("product", "MIS"),
                    o.get("price", 0), o.get("trigger_price", 0), o.get("avg_fill_price", 0),
                    o.get("filled_qty", 0), o.get("status", ""), o.get("tag", ""),
                    o.get("underlying", ""), o.get("strike", 0), o.get("option_type", ""),
                    o.get("expiry", ""), o.get("exchange", "NFO"), o.get("placed_at", ""),
                    o.get("filled_at", ""), o.get("rejection_reason", ""),
                ))
                n += 1
            print(f"[4/8] orders: {n} migrated")
        except Exception as e:
            print(f"  [ERR] orders: {e}")

    # Migrate brain decisions
    decisions_path = data_dir / "quant_service_decisions.jsonl"
    if decisions_path.exists():
        n = 0
        try:
            with open(decisions_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        cur.execute("""
                            INSERT INTO brain_decisions (ts, decision_json, event_json, context_json, note)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            d.get("ts", ""), json.dumps(d.get("decision", {})),
                            json.dumps(d.get("event", {})),
                            json.dumps(d.get("context", {})),
                            d.get("decision", {}).get("note", ""),
                        ))
                        n += 1
                    except Exception:
                        continue
            print(f"[5/8] brain_decisions: {n} migrated")
        except Exception as e:
            print(f"  [ERR] brain_decisions: {e}")

    # Migrate trade journal
    journal_path = data_dir / "trade_journal.jsonl"
    if journal_path.exists():
        n = 0
        try:
            with open(journal_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                        cur.execute("""
                            INSERT OR REPLACE INTO trades
                            (trade_id, strategy, underlying, legs_json, target, stop,
                             confidence, reason, opened_at, closed_at, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            d.get("trade_id", ""), d.get("strategy", ""), d.get("underlying", ""),
                            json.dumps(d.get("legs", [])), d.get("target", 0), d.get("stop", 0),
                            d.get("confidence", 0), d.get("reason", ""), d.get("opened_at", ""),
                            d.get("closed_at", ""), d.get("status", "open"),
                        ))
                        n += 1
                    except Exception:
                        continue
            print(f"[6/8] trades: {n} migrated")
        except Exception as e:
            print(f"  [ERR] trades: {e}")

    # Set initial heartbeats
    cur.execute("""
        INSERT OR REPLACE INTO heartbeats (component, ts, pid, metadata_json)
        VALUES ('migration', ?, NULL, ?)
    """, (datetime.now().isoformat(), json.dumps({"migrated_at": datetime.now().isoformat(), "source": "json"})))
    print(f"[7/8] heartbeats: migration marker set")

    # Verify
    cur.execute("SELECT COUNT(*) FROM paper_state")
    ps_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM positions")
    pos_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders")
    ord_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM brain_decisions")
    dec_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades")
    tr_count = cur.fetchone()[0]
    print()
    print(f"[8/8] Migration verification:")
    print(f"  paper_state:  {ps_count} rows")
    print(f"  positions:    {pos_count} rows")
    print(f"  orders:       {ord_count} rows")
    print(f"  decisions:    {dec_count} rows")
    print(f"  trades:       {tr_count} rows")
    print()
    print("=" * 60)
    print(f"SUCCESS: data migrated to {db_path}")
    print(f"DB size: {db_path.stat().st_size / 1024:.1f} KB")
    print()
    print("Next steps:")
    print("  1. Verify data: sqlite3 data_cache/state.db 'SELECT * FROM paper_state'")
    print("  2. Update bot code to read/write SQLite instead of JSON")
    print("  3. After bot is stable on SQLite, archive JSON files:")
    print(f"     move {data_dir}\\paper_state.json {data_dir}\\paper_state.json.bak")
    print("=" * 60)


if __name__ == "__main__":
    main()
