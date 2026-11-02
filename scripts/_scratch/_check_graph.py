"""Diagnostic: dump trade entities + recall results."""
import json
with open("data_cache/knowledge_graph.json", encoding="utf-8") as f:
    d = json.load(f)
print("top-level keys:", list(d.keys()))
print("n_entities:", len(d.get("entities", [])))
print("n_relations:", len(d.get("relations", [])))
trades = [e for e in d["entities"] if e["entityType"] == "Trade"]
print(f"n_trades={len(trades)}")
print()
print("=== first 3 trade entities ===")
for t in trades[:3]:
    print(json.dumps(t, indent=2, ensure_ascii=False)[:600])
    print("---")
print()
print("=== relations involving Regime_trending_down ===")
for r in d["relations"]:
    if "trending_down" in r.get("to", "") or "trending_down" in r.get("from", ""):
        print(json.dumps(r, ensure_ascii=False))
