"""Smoke test for the _http_get fix on 2026-09-22."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest.mock as mock
import urllib.error
from kotak_bot.data.kotak_prod_feed import _http_get


class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, msg):
        super().__init__('http://test', code, msg, {}, None)

    def read(self):
        return b'{"err": "body"}'


class FakeResp:
    status = 200

    def read(self):
        return b'{"ok": true}'


def test_timeout():
    with mock.patch('urllib.request.urlopen',
                    side_effect=urllib.error.URLError('timed out')):
        code, body = _http_get('http://test', {})
        assert code == 0, f'expected 0, got {code}'
        assert body == '', f'expected empty, got {body!r}'
        print(f'  URLError timeout: code={code!r} body={body!r} PASS')


def test_http_503():
    with mock.patch('urllib.request.urlopen',
                    side_effect=FakeHTTPError(503, 'Service Unavailable')):
        code, body = _http_get('http://test', {})
        assert code == 503, f'expected 503, got {code}'
        assert 'err' in body, f'expected err in body, got {body!r}'
        print(f'  HTTPError 503: code={code!r} body={body!r} PASS')


def test_http_401():
    with mock.patch('urllib.request.urlopen',
                    side_effect=FakeHTTPError(401, 'Unauthorized')):
        code, body = _http_get('http://test', {})
        assert code == 401, f'expected 401, got {code}'
        print(f'  HTTPError 401: code={code!r} body={body!r} PASS')


def test_ssl_error():
    with mock.patch('urllib.request.urlopen',
                    side_effect=OSError('ssl cert verify failed')):
        code, body = _http_get('http://test', {})
        assert code == 0, f'expected 0, got {code}'
        assert body == '', f'expected empty, got {body!r}'
        print(f'  OSError SSL: code={code!r} body={body!r} PASS')


def test_success():
    with mock.patch('urllib.request.urlopen', return_value=FakeResp()):
        code, body = _http_get('http://test', {})
        assert code == 200, f'expected 200, got {code}'
        assert 'ok' in body, f'expected ok in body, got {body!r}'
        print(f'  Success: code={code!r} body={body!r} PASS')


def test_connection_refused():
    with mock.patch('urllib.request.urlopen',
                    side_effect=urllib.error.URLError(
                        ConnectionRefusedError('refused'))):
        code, body = _http_get('http://test', {})
        assert code == 0, f'expected 0, got {code}'
        print(f'  ConnectionRefused: code={code!r} body={body!r} PASS')


if __name__ == '__main__':
    print('Testing _http_get URLError catch...')
    test_timeout()
    test_http_503()
    test_http_401()
    test_ssl_error()
    test_success()
    test_connection_refused()
    print('All _http_get tests passed.')
