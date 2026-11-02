"""Temp harness runner — captures proof_harness output cleanly."""
import subprocess
import sys

result = subprocess.run(
    [sys.executable, 'scripts/proof_harness.py'],
    capture_output=True,
    text=True,
    cwd=r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot',
)
with open('data_cache/proof_baseline.log', 'w', encoding='utf-8') as f:
    f.write('=== STDOUT ===\n')
    f.write(result.stdout)
    f.write('\n=== STDERR ===\n')
    f.write(result.stderr)
    f.write(f'\n=== EXIT {result.returncode} ===\n')
print(f'exit={result.returncode}')
print(result.stdout[-3000:] if result.stdout else '(empty stdout)')
print('STDERR (last 1000):', result.stderr[-1000:] if result.stderr else '(empty stderr)')