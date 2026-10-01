"""Save sequential-thinking thesis to knowledge graph."""
import subprocess, sys, os
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'
script = '''
import sys
sys.path.insert(0, r"C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot")
from system.common.knowledge_graph import remember_lesson, remember_trade_outcome

# Save lessons learned from sequential-thinking
remember_lesson(
    "Fri Oct 2 thesis: market context = continued bearish after Thu expiry sell-off; "
    "pro trader consensus = bearish (HDFC, Bajaj); historical NIFTY SHORT signal "
    "has +2.12 Sharpe and +0.018% EV at 100 prior samples. "
    "WAIT until 09:45 IST for opening volatility to settle. "
    "Strategy selection: trending_down -> nifty_cash_short (60% win hist, "
    "+0.66% avg P&L); range_bound -> nifty_iron_condor. "
    "Position sizing: 1 lot NIFTY cash, target +0.8%, stop -0.6%. "
    "EOD force-square at 15:15-15:25 IST.",
    regime="trending_down",
    source="sequential_thinking_fri_oct_2_thesis"
)

remember_lesson(
    "Sequential-thinking plugin successfully used to walk through 5-step trade thesis: "
    "market context -> strategy selection -> risk management -> entry rules -> "
    "knowledge graph recording. Each step was auditable and reasoned. "
    "Future trade theses should follow this pattern.",
    regime="meta",
    source="phase10_plugin_validation"
)

print("Saved 2 lessons to knowledge graph")
'''
r = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                   cwd=r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot', env=env)
print('exit:', r.returncode)
print(r.stdout)
if r.stderr:
    print('stderr:', r.stderr[-1000:])