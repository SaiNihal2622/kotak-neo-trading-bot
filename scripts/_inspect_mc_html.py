"""Save the Moneycontrol HTML so we can inspect the actual FII/DII table."""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

url = "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=10) as r:
    data = r.read(500_000)
text = data.decode("utf-8", errors="ignore")

# Find the FII/DII table region
idx = text.find("FII")
if idx > 0:
    # Save 3000 chars around the first FII/DII mention
    snippet = text[max(0, idx - 500):idx + 5000]
    out = ROOT / "Logs" / "mc_fii_dii_snippet.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(snippet, encoding="utf-8")
    print(f"Saved FII/DII region ({len(snippet)} chars) to {out}")
    # Print first 1000 chars of the region
    print(snippet[:1500])
else:
    print("FII not found in HTML")
