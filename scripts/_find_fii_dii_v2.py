"""Try NSE with proper session + GitHub mirrors."""
import sys
import re
import urllib.request
import http.cookiejar
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

# 1. Try NSE with proper session (cookie jar)
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

# First, hit the homepage to get cookies
nse_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

try:
    req = urllib.request.Request("https://www.nseindia.com/", headers=nse_headers)
    opener.open(req, timeout=10)
    print("Got NSE homepage cookies")
except Exception as e:
    print(f"NSE homepage error: {e}")

# 2. Now try the API
try:
    api_headers = {
        **nse_headers,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/market-data/fii-dii-trading-activity",
        "X-Requested-With": "XMLHttpRequest",
    }
    req = urllib.request.Request(
        "https://www.nseindia.com/api/fiidiiTradeReact?month=&year=",
        headers=api_headers,
    )
    with opener.open(req, timeout=10) as r:
        data = r.read(500_000)
    text = data.decode("utf-8", errors="ignore")
    print(f"\nNSE FII/DII API: {len(text)} chars")
    print(f"Sample: {text[:1500]!r}")
except Exception as e:
    print(f"NSE API error: {e}")

# 3. Try GitHub mirrors
github_urls = [
    "https://raw.githubusercontent.com/sahilgupta/social-media-data/main/fii-dii-data.csv",
    "https://raw.githubusercontent.com/sahilgupta/social-media-data/main/fii-dii/data.csv",
    "https://raw.githubusercontent.com/sahilgupta/social-media-data/main/fii-dii-data.json",
    "https://raw.githubusercontent.com/sahilgupta/social-media-data/main/data/fii-dii.csv",
    "https://raw.githubusercontent.com/sahilgupta/social-media-data/main/data/fii-dii.json",
    "https://raw.githubusercontent.com/sahilgupta/social-media-data/main/FII-DII-Activity.csv",
    "https://raw.githubusercontent.com/sahilgupta/social-media-data/main/datasets/fii-dii.csv",
]
for url in github_urls:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read(50_000)
        text = data.decode("utf-8", errors="ignore")
        print(f"\n{url}: {len(text)} chars")
        print(f"Sample: {text[:500]!r}")
    except Exception as e:
        print(f"  {url}: {e}")

# 4. Try a search for known mirrors
known_mirrors = [
    "https://gist.githubusercontent.com/sahilgupta/",
    "https://raw.githubusercontent.com/datasets/",
    "https://raw.githubusercontent.com/code4kunal/",
]
for url in known_mirrors:
    print(f"\n  (skipping {url} - too generic)")

# 5. Try mcp__puppeteer__ (which we have)
print("\n\n=== Need to use puppeteer for Moneycontrol JS rendering ===")
print("Use mcp__puppeteer__puppeteer_navigate to load the page and extract data.")
