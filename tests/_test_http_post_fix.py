"""Smoke test for the _http_post fix on 2026-09-22."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest.mock as mock
import urllib.error
from kotak_bot.data.kotak_prod_feed import _http_get, _http_post


class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, msg):
        super().__init__('http://test', code, msg, {}, None)

    def read(self):
        return b'{"err": "body"}'


class FakeResp:
    status = 200

    def read(self):
        return b'{"ok": true}'


# Test _http_post timeout
with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('timed out')):
    code, body = _http_post('http://test', {}, {})
    assert code == 0, f'POST timeout expected 0, got {code}'
    assert body == {}, f'POST timeout expected empty dict, got {body!r}'
    print('_http_post URLError timeout: PASS')

# Test _http_post 503
with mock.patch('urllib.request.urlopen', side_effect=FakeHTTPError(503, 'Service Unavailable')):
    code, body = _http_post('http://test', {}, {})
    assert code == 503, f'POST 503 expected 503, got {code}'
    print(f'_http_post HTTPError 503: PASS (body={body!r})')

# Test _http_post success
with mock.patch('urllib.request.urlopen', return_value=FakeResp()):
    code, body = _http_post('http://test', {}, {})
    assert code == 200, f'expected 200, got {code}'
    assert body == {'ok': True}, f'expected ok dict, got {body!r}'
    print('_http_post Success: PASS')

# Re-confirm _http_get
with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('timed out')):
    code, body = _http_get('http://test', {})
    assert code == 0, f'GET timeout expected 0, got {code}'
    print('_http_get URLError timeout: PASS')

with mock.patch('urllib.request.urlopen', side_effect=FakeHTTPError(503, 'Service Unavailable')):
    code, body = _http_get('http://test', {})
    assert code == 503, f'GET 503 expected 503, got {code}'
    print('_http_get HTTPError 503: PASS')

with mock.patch('urllib.request.urlopen', return_value=FakeResp()):
    code, body = _http_get('http://test', {})
    assert code == 200, f'expected 200, got {code}'
    print('_http_get Success: PASS')

print('All HTTP helpers fixes verified.')
