#!/usr/bin/env python
"""Test the LLM endpoint the brain uses."""
import os
import httpx
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

url = 'https://agent.minimax.io/mavis/api/v1/llm/v1/messages'
key = os.environ.get('MINIMAX_LLM_API_KEY', '')
print(f'  URL: {url}')
print(f'  key len: {len(key)}')
r = httpx.post(url, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, json={'model': 'claude-sonnet-4-20250514', 'max_tokens': 30, 'messages': [{'role': 'user', 'content': 'reply OK only'}]}, timeout=30)
print(f'  status: {r.status_code}')
try:
    print(f'  text: {r.json().get("content", [{}])[0].get("text", "")[:50]}')
except Exception:
    print(f'  body: {r.text[:200]}')
