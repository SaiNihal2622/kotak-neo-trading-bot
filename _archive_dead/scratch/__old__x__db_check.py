"""Inspect existing SQLite state.db."""
import sqlite3
db = sqlite3.connect('data_cache/state.db')
cur = db.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables in state.db:')
for r in cur.fetchall():
    print(' ', r[0])
print()
# Show schema of each
for tbl in [r[0] for r in cur.fetchall()]:
    print(f'\nSchema for {tbl}:')
    for row in db.execute(f"PRAGMA table_info({tbl})").fetchall():
        print(f'  {row}')