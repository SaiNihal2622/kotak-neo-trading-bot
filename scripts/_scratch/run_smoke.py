"""Run phase8_smoke.py and capture output cleanly."""
import subprocess, sys, os
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'
r = subprocess.run([sys.executable, 'scripts/_scratch/phase8_smoke.py'],
                   capture_output=True, text=True,
                   cwd=r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot',
                   env=env)
with open('data_cache/phase8_smoke.log', 'w', encoding='utf-8') as f:
    f.write('STDOUT:\n')
    f.write(r.stdout)
    f.write('\n\nSTDERR:\n')
    f.write(r.stderr)
    f.write(f'\n\nEXIT={r.returncode}\n')
print(f'exit={r.returncode}')
print('STDOUT:')
print(r.stdout)
print('STDERR (last 1500):')
print(r.stderr[-1500:])