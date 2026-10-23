"""Check news feed results."""
import json
m = json.load(open("data_cache/news_feed_meta.json"))
print(f"sources_ok: {m['sources_ok']} / 12")
print(f"total headlines: {m['total']}")
print("per-source:")
for s in m["sources"]:
    src = s["source"]
    ok = s["ok"]
    n = s["n"]
    print(f"  {src:25s} ok={ok} n={n}")
