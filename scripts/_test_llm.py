#!/usr/bin/env python
"""Test if LLM endpoint is reachable."""
import os
import requests
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

api_key = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('MINIMAX_API_KEY') or os.environ.get('LLM_API_KEY') or ''
print(f'  API key present: {bool(api_key)} (len={len(api_key)})')

url = 'https://agent.minimax.io/mavis/api/v1/llm/v1/messages'
headers = {
    'x-api-key': api_key,
    'anthropic-version': '2023-06-01',
    'content-type': 'application/json',
}
data = {
    'model': 'claude-sonnet-4-20250514',
    'max_tokens': 50,
    'messages': [{'role': 'user', 'content': 'hi'}]
}
print(f'  calling {url}...')
try:
    r = requests.post(url, headers=headers, json=data, timeout=10)
    print(f'  status: {r.status_code}')
    print(f'  response (first 300): {r.text[:300]}')
except Exception as e:
    print(f'  err: {e}')
