"""Force-reseed knowledge graph."""
from system.common.knowledge_graph import (
    _save, seed_demo_data, get_stats, get_memory_context_for_prompt,
)
import json
empty = {"version": 1, "entities": [], "relations": []}
_save(empty)
n = seed_demo_data()
print(f"Seeded {n} demo trades")
stats = get_stats()
print(json.dumps(stats, indent=2))
print("\n=== trending_down context ===")
print(get_memory_context_for_prompt("trending_down"))
print("\n=== range_bound context ===")
print(get_memory_context_for_prompt("range_bound"))