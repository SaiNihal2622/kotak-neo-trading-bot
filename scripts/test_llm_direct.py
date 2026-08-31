"""Test direct LLM API call. Bypasses Mavis cron, just hits the endpoint."""
import os
import sys
import json
import httpx
from pathlib import Path

ENV = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env')
env = {}
for line in ENV.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    env[k.strip()] = v.strip().strip('"').strip("'")

base_url = env.get('MINIMAX_LLM_BASE_URL', '')
api_key = env.get('MINIMAX_LLM_API_KEY', '')

print(f"base_url: {base_url}")
print(f"api_key: {api_key[:30]}...{api_key[-10:]}")
print(f"api_key length: {len(api_key)}")
print()

# Try OpenAI-compatible chat completions endpoint
for ep in ['/chat/completions', '/completions', '/messages', '/v1/chat/completions']:
    url = base_url.rstrip('/') + ep
    try:
        r = httpx.post(
            url,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': 'MiniMax-M3',
                'messages': [{'role': 'user', 'content': 'Reply with just the word OK if you can read this.'}],
                'max_tokens': 50,
            },
            timeout=15.0,
        )
        print(f"POST {ep}: {r.status_code}")
        if r.status_code == 200:
            print(f"  body: {r.text[:500]}")
            break
        else:
            print(f"  body: {r.text[:300]}")
    except Exception as e:
        print(f"  err: {e}")
