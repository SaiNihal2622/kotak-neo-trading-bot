"""Quick state check."""
import json, sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.common.knowledge_graph import get_stats, get_memory_context_for_prompt

stats = get_stats()
print(f"Entities: {stats['n_entities']} | Relations: {stats['n_relations']}")
print(f"By type: {stats['by_type']}")
print()
print("=== trending_down context ===")
print(get_memory_context_for_prompt('trending_down'))
print()
print("=== range_bound context ===")
print(get_memory_context_for_prompt('range_bound'))

# Check mcp helpers
from system.common.mcp_helpers import plugin_status
print()
print("=== plugin_status (from subprocess) ===")
print(plugin_status())

# Check live_intel
from system.brain.live_intel import fetch_intel
intel = fetch_intel()
print()
print("=== live_intel ===")
print(f"  bias: {intel.get('consensus_bias')}")
print(f"  nearest_support: {intel.get('nearest_support')}")
print(f"  nearest_resistance: {intel.get('nearest_resistance')}")