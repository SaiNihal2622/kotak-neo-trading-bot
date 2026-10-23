"""Start the core service and test it."""
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'system')
from system.core.api.server import create_app
app = create_app('data_cache/state.db')
print('App created OK')
print('Routes:')
for route in app.routes:
    if hasattr(route, 'path'):
        methods = getattr(route, 'methods', '-')
        print(f'  {methods} {route.path}')
print()
print('Testing state endpoint...')
from fastapi.testclient import TestClient
with TestClient(app) as client:
    r = client.get('/healthz')
    print(f'  /healthz: {r.status_code} {r.json()}')
    r = client.get('/api/state')
    print(f'  /api/state: {r.status_code}')
    r = client.get('/api/metrics')
    print(f'  /api/metrics: {r.status_code}')
    if r.status_code == 200:
        print('  Metrics preview:')
        for line in r.text.split('\n')[:8]:
            print(f'    {line}')