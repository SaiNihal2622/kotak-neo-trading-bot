"""Force-reseed knowledge graph via subprocess."""
import subprocess, sys, os
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'
r = subprocess.run(
    [sys.executable, '-c', '''
import sys
sys.path.insert(0, r"C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot")
from system.common.knowledge_graph import _save, seed_demo_data, get_stats, get_memory_context_for_prompt
import json
empty = {"version": 1, "entities": [], "relations": []}
_save(empty)
n = seed_demo_data()
print(f"Seeded {n} demo trades")
stats = get_stats()
print(json.dumps(stats, indent=2))
print()
print("trending_down context:")
print(get_memory_context_for_prompt("trending_down"))
'''],
    capture_output=True, text=True,
    cwd=r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot',
    env=env,
)
print('exit:', r.returncode)
print(r.stdout)
if r.stderr:
    print('stderr:', r.stderr[-1500:])