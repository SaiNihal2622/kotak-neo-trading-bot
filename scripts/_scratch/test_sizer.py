"""Test sizer rounds to whole lots."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.brain.adaptive_sizer import compute_position_size

s1 = compute_position_size(win_rate=0.70, avg_win_pct=1.5, avg_loss_pct=1.0,
                            realized_vol_pct=10.0, cash=100_000.0)
print(f"Test 1 (70%/1.5/1.0): lots={s1['lots']} qty={s1['qty']} (expect 1 lot, 75 shares)")

s2 = compute_position_size(win_rate=0.60, avg_win_pct=1.5, avg_loss_pct=1.0,
                            realized_vol_pct=10.0, cash=100_000.0)
print(f"Test 2 (60%/1.5/1.0): lots={s2['lots']} qty={s2['qty']} (expect 1 lot, 75 shares)")

s3 = compute_position_size(win_rate=0.80, avg_win_pct=2.0, avg_loss_pct=0.5,
                            realized_vol_pct=10.0, cash=100_000.0, max_lots=5)
print(f"Test 3 (80%/2/0.5, big edge): lots={s3['lots']} qty={s3['qty']} (expect 1 lot, 75)")

s4 = compute_position_size(win_rate=0.40, avg_win_pct=1.0, avg_loss_pct=1.0,
                            realized_vol_pct=10.0, cash=100_000.0)
print(f"Test 4 (no edge): lots={s4['lots']} qty={s4['qty']} (expect 0)")