"""Show what dates the Moneycontrol FII/DII page is actually returning."""
import sys
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from scripts.fii_dii_fetcher import _fetch_moneycontrol, _parse_date_safe
from datetime import date

rows = _fetch_moneycontrol()
if rows:
    print(f"Got {len(rows)} rows. ALL dates:")
    for r in rows[:25]:
        d = _parse_date_safe(r.get("date", ""))
        age = (date.today() - d).days if d else "parse-fail"
        fii_net = r.get("fii_net_cr", 0)
        dii_net = r.get("dii_net_cr", 0)
        print(f"  {r.get('date'):15s}  age={age:>6}  FII={fii_net:>8.1f}  DII={dii_net:>8.1f}")
else:
    print("No rows")
