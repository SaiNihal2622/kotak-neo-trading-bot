"""Run lint and capture output."""
import subprocess, sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
r = subprocess.run([sys.executable, 'scripts/lint_no_shadowing.py'],
                   capture_output=True, text=True,
                   cwd=r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
print('exit:', r.returncode)
print('stdout:', r.stdout[:3000])
print('stderr:', r.stderr[:1500])