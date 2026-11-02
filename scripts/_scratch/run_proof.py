"""Run proof_harness.py and capture clean output."""
import subprocess, sys, os
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'
r = subprocess.run([sys.executable, 'scripts/proof_harness.py'],
                   capture_output=True, text=True,
                   cwd=r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot',
                   env=env)
with open('data_cache/proof_phase8.log', 'w', encoding='utf-8') as f:
    f.write(r.stdout)
print(f'exit={r.returncode}')
print(r.stdout[-3000:])