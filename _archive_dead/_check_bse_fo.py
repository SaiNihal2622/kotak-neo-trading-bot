import csv, sys, os, json
from pathlib import Path
sys.path.insert(0, '.')

env_path = Path('config/credentials.env')
for line in env_path.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

import time, datetime
bse_path = Path('data_cache/bse_fo.csv')
with open(bse_path, encoding='utf-8', errors='ignore') as f:
    rows = list(csv.DictReader(f))

# SENSEX row stats
sensex = [r for r in rows if r.get('pSymbolName')=='SENSEX']
print(f'SENSEX rows: {len(sensex)}')
import re
# Parse expiry dates (lExpiryDate has trailing space)
exps = sorted(set(int(r.get('lExpiryDate ') or 0) for r in sensex))
now = int(time.time())
recent = [e for e in exps if e > now]
old = [e for e in exps if e < now]
print(f'SENSEX total expiries: {len(exps)}, future: {len(recent)}, past: {len(old)}')
print(f'Future expiries (sample 5):')
for e in recent[:5]:
    dt = datetime.datetime.fromtimestamp(e)
    print(f'  {e} = {dt}')
# Sample future SENSEX row
future_rows = [r for r in sensex if int(r.get('lExpiryDate ') or 0) > now]
if future_rows:
    s = future_rows[0]
    print(f'Sample SENSEX future: ref={s.get("pScripRefKey")}, pSymbol={s.get("pSymbol")}, lot={s.get("lLotSize")}')
# Parse SENSEX ref like SENSEX08OCT2670600.00CE
sample = future_rows[0].get('pScripRefKey', '')
m = re.match(r'^(SENSEX)(\d{2})([A-Z]{3})(\d{2})(\d+)\.00(CE|PE)$', sample)
print(f'Regex match: {m.groups() if m else None}')
