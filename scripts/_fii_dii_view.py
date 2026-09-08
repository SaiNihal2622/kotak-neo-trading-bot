"""View FII/DII data."""
import json
d = json.load(open("data_cache/fii_dii.json"))
print("Latest 3 rows:")
for r in d["rows"][:3]:
    date = r["date"]
    fii = r["fii_net_cr"]
    dii = r["dii_net_cr"]
    print(f"  {date}: FII net={fii:>+8.1f} cr | DII net={dii:>+8.1f} cr")
print()
print("Summary:")
for k, v in d["summary"].items():
    print(f"  {k}: {v}")
