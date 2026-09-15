#!/usr/bin/env python
"""Test OI capture."""
import sys
sys.path.insert(0, 'scripts')
from oi_change_detector import capture_snapshot
snap = capture_snapshot('NIFTY')
if snap:
    print('NIFTY OI snapshot captured:')
    for strike, data in list(snap.get('strikes', {}).items())[:5]:
        ce_oi = data.get('ce_oi')
        pe_oi = data.get('pe_oi')
        print(f'  {strike}: CE OI={ce_oi} PE OI={pe_oi}')
else:
    print('failed to capture')
