import urllib.request, json
for port, path in [(8501, '/_stcore/health'), (8502, '/health'), (8503, '/status'), (8504, '/')]:
    try:
        r = urllib.request.urlopen(f'http://localhost:{port}{path}', timeout=3)
        body = r.read().decode()
        if 'json' in r.headers.get('Content-Type', ''):
            print(f'  port {port} HTTP {r.status} ({path[:30]:30s}): {len(body)}B')
        else:
            print(f'  port {port} HTTP {r.status} ({path[:30]:30s}): {body[:60]}')
    except Exception as e:
        print(f'  port {port} ({path[:30]:30s}): ERR {e}')
