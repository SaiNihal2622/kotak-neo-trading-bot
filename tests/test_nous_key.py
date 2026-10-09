"""Tests for static NOUS_API_KEY auth in nous_llm_client.

FIX 2026-10-05: the OAuth path reads Hermes' auth.json for a bearer
access_token. Under an NSSM LocalSystem service that file is missing or
unreadable, so the brain degraded to HOLD with 'Hermes has no Nous access
token'. A static key has no lifecycle and no refresh race -- the right auth
for a headless 24/7 trading service.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_nous_key.py -q
"""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


@pytest.fixture()
def qs_client(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / 'system' / 'common'))
    import nous_llm_client as m
    # Reset cache between tests.
    m._CACHE.update({'token': None, 'expires_at': 0.0, 'base_url': '',
                     'inference_base_url': '', 'refresh_token': '', 'client_id': ''})
    # Deterministically clear all relevant env so no test leaks into another.
    for k in ('NOUS_API_KEY', 'NOUS_INFERENCE_BASE_URL', 'NOUS_USE_OAUTH',
              'HERMES_AUTH_JSON'):
        monkeypatch.delenv(k, raising=False)
        os.environ.pop(k, None)
    return m


# ---------- static key selection ----------

def test_static_key_used_when_env_set(qs_client, monkeypatch):
    monkeypatch.setenv('NOUS_API_KEY', 'sk-nous-testkey123')
    cred = qs_client._static_key()
    assert cred['token'] == 'sk-nous-testkey123'
    assert not cred['refresh_token']


def test_static_key_rejects_when_missing(qs_client):
    with pytest.raises(qs_client.NousAuthError, match='NOUS_API_KEY'):
        qs_client._static_key()


def test_token_uses_static_key_by_default(qs_client, monkeypatch):
    """With NOUS_USE_OAUTH unset and NOUS_API_KEY set, _token() returns the key."""
    monkeypatch.setenv('NOUS_API_KEY', 'sk-nous-static-test')
    cred = qs_client._token()
    assert cred['token'] == 'sk-nous-static-test'


def test_use_oauth_flag_forces_oauth_path(qs_client, monkeypatch):
    monkeypatch.setenv('NOUS_USE_OAUTH', '1')
    monkeypatch.setenv('NOUS_API_KEY', 'sk-nous-ignored')
    monkeypatch.setenv('HERMES_AUTH_JSON', str(qs_client._default_auth_json()))
    with pytest.raises(qs_client.NousAuthError):
        # OAuth path tries to read auth.json -> no nous provider in the
        # temp/default empty file. We just need it to NOT return the static key.
        cred = qs_client._token()
        assert cred['token'] != 'sk-nous-ignored'
        raise qs_client.NousAuthError('token() should not return static key under OAuth')


def test_static_key_inference_base_falls_back_to_default(qs_client, monkeypatch):
    monkeypatch.setattr(qs_client, '_load_provider_config',
                        lambda: {'inference_base_url': ''})
    monkeypatch.setenv('NOUS_API_KEY', 'sk-nous-x')
    cred = qs_client._static_key()
    assert cred['inference_base_url'].endswith('/v1')


def test_static_key_inference_base_honors_override(qs_client, monkeypatch):
    monkeypatch.setenv('NOUS_API_KEY', 'sk-nous-x')
    monkeypatch.setenv('NOUS_INFERENCE_BASE_URL', 'https://my-proxy.example.com/v1')
    cred = qs_client._static_key()
    assert cred['inference_base_url'] == 'https://my-proxy.example.com/v1'


# ---------- live-ish end to end with a stub transport ----------

def test_call_llm_sends_bearer_static_key(qs_client, monkeypatch):
    """The request must carry Authorization: Bearer <static key>."""
    captured = {}

    def _fake_urlopen(req, timeout=None):
        captured['auth'] = req.get_header('Authorization')
        captured['url'] = req.full_url
        class _Resp:
            def read(self): return json.dumps(
                {'choices': [{'message': {'content': 'ok-static'}}]}).encode()
            def __exit__(self, *a): return False
            def __enter__(self): return self
        return _Resp()

    monkeypatch.setattr(qs_client.urllib.request, 'urlopen', _fake_urlopen)
    monkeypatch.setenv('NOUS_API_KEY', 'sk-nous-bearer-test')
    monkeypatch.setenv('NOUS_INFERENCE_BASE_URL', 'https://example.com/v1')
    r = qs_client.call_llm(system='s', user='u', model='m/m', max_tokens=5)
    assert r['ok'] is True
    assert r['text'] == 'ok-static'
    assert captured['auth'] == 'Bearer sk-nous-bearer-test'
    assert '/chat/completions' in captured['url']


def test_call_llm_auth_error_returns_error_not_raise(qs_client):
    """A missing key degrades to a returned error, never an exception."""
    r = qs_client.call_llm(system='s', user='u', model='m/m', max_tokens=5)
    assert r['ok'] is False
    assert 'NOUS_API_KEY' in r['error']
