"""Tests for the self-refreshing Nous LLM client.

FIX 2026-10-05: this client replaces the static MiniMax key whose silent
death cost 9 trading days of HOLDs.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_nous_llm_client.py -q
"""

import importlib
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / 'system' / 'common'))

import nous_llm_client as nlc  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty credential cache."""
    nlc._CACHE.update({
        'token': None, 'expires_at': 0.0, 'base_url': '',
        'inference_base_url': '', 'refresh_token': '', 'client_id': '',
    })
    yield
    nlc._CACHE.update({
        'token': None, 'expires_at': 0.0, 'base_url': '',
        'inference_base_url': '', 'refresh_token': '', 'client_id': '',
    })


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---------- config discovery ----------

def test_missing_auth_json_raises_actionable_error(tmp_path, monkeypatch):
    # Point the resolver at a nonexistent file via the override env var
    # (patching the AUTH_JSON constant no longer works -- _read_auth_json
    # resolves the path dynamically so it survives running as a service).
    monkeypatch.setenv('HERMES_AUTH_JSON', str(tmp_path / 'nope.json'))
    with pytest.raises(nlc.NousAuthError) as ei:
        nlc._load_provider_config()
    assert 'auth.json' in str(ei.value)


def test_missing_nous_block_raises(monkeypatch, tmp_path):
    p = tmp_path / 'auth.json'
    p.write_text(json.dumps({'providers': {'openai': {}}}), encoding='utf-8')
    monkeypatch.setenv('HERMES_AUTH_JSON', str(p))
    with pytest.raises(nlc.NousAuthError) as ei:
        nlc._load_provider_config()
    assert 'nous' in str(ei.value)


def test_bom_prefixed_auth_json_is_readable(monkeypatch, tmp_path):
    """Hermes writes this file with a BOM on some paths; utf-8 must not break."""
    p = tmp_path / 'auth.json'
    p.write_text(json.dumps({'providers': {'nous': {'client_id': 'x'}}}),
                 encoding='utf-8-sig')
    monkeypatch.setenv('HERMES_AUTH_JSON', str(p))
    assert nlc._load_provider_config()['client_id'] == 'x'


# ---------- caching / refresh ----------

def _fake_cfg():
    return {
        'portal_base_url': 'https://portal.example.com/',
        'inference_base_url': 'https://inference.example.com/v1/',
        'refresh_token': 'rt-original',
        'client_id': 'hermes-cli',
    }


def test_refresh_posts_to_correct_endpoint_with_header(monkeypatch):
    """Regression: the token endpoint is /api/oauth/token and the refresh
    token rides in the x-nous-refresh-token HEADER, not the form body.
    Getting either wrong returns 404/400 and looks like 'bad credentials'.
    """
    seen = {}

    def _urlopen(req, timeout=None):
        seen['url'] = req.full_url
        seen['headers'] = {k.lower(): v for k, v in req.headers.items()}
        seen['body'] = req.data
        return _Resp({'access_token': 'tok-1', 'expires_in': 3600,
                      'refresh_token': 'rt-2',
                      'inference_base_url': 'https://inference.example.com/v1'})

    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)
    monkeypatch.setattr(nlc, '_load_provider_config', _fake_cfg)

    cred = nlc._token()
    assert seen['url'] == 'https://portal.example.com/api/oauth/token'
    assert seen['headers'].get('x-nous-refresh-token') == 'rt-original'
    assert b'rt-original' not in (seen['body'] or b'')
    assert b'client_id=hermes-cli' in (seen['body'] or b'')
    assert cred['token'] == 'tok-1'


def test_token_is_cached_and_not_refreshed_again(monkeypatch):
    calls = {'n': 0}

    def _urlopen(req, timeout=None):
        calls['n'] += 1
        return _Resp({'access_token': f'tok-{calls["n"]}', 'expires_in': 3600})

    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)
    monkeypatch.setattr(nlc, '_load_provider_config', _fake_cfg)

    first = nlc._token()['token']
    for _ in range(5):
        assert nlc._token()['token'] == first
    assert calls['n'] == 1, 'token was refreshed despite being valid'


def test_token_refreshes_before_actual_expiry(monkeypatch):
    """A token that dies mid-request is the 9-day-outage failure mode again."""
    calls = {'n': 0}

    def _urlopen(req, timeout=None):
        calls['n'] += 1
        # expires_in below the margin -> next call must re-refresh.
        return _Resp({'access_token': f'tok-{calls["n"]}',
                      'expires_in': nlc.REFRESH_MARGIN_SEC - 1})

    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)
    monkeypatch.setattr(nlc, '_load_provider_config', _fake_cfg)

    nlc._token()
    nlc._token()
    assert calls['n'] == 2, 'expiring token was reused instead of refreshed'


def test_rotated_refresh_token_is_persisted(monkeypatch):
    """The server may return a NEW refresh token. Losing it breaks the next
    refresh -- this is exactly how the token got rejected earlier."""
    def _urlopen(req, timeout=None):
        return _Resp({'access_token': 'tok-a', 'expires_in': 3600,
                      'refresh_token': 'rt-rotated'})

    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)
    cfg = _fake_cfg()
    monkeypatch.setattr(nlc, '_load_provider_config', lambda: cfg)

    nlc._token()
    assert nlc._CACHE['refresh_token'] == 'rt-rotated'


def test_refresh_http_error_does_not_leak_body(monkeypatch):
    """An error body could echo credential fragments -- never surface it."""
    def _urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 400, 'Bad Request', {},
            __import__('io').BytesIO(b'{"error":"invalid_grant","dt":"eyJSEcreT"}'))

    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)
    monkeypatch.setattr(nlc, '_load_provider_config', _fake_cfg)

    with pytest.raises(nlc.NousAuthError) as ei:
        nlc._token()
    msg = str(ei.value)
    assert '400' in msg
    assert 'eyJ' not in msg, 'credential-shaped string leaked into error message'


# ---------- call_llm ----------

def test_call_llm_returns_contract_and_parses_content(monkeypatch):
    def _urlopen(req, timeout=None):
        assert req.full_url.endswith('/chat/completions')
        assert req.headers.get('Authorization') == 'Bearer tok-1'
        return _Resp({'choices': [{'message': {'content': 'HELLO'}}],
                      'usage': {'total_tokens': 9}, 'id': 'cmpl-1'})

    monkeypatch.setattr(nlc, '_token', lambda: {
        'token': 'tok-1', 'inference_base_url': 'https://inf.example.com/v1'})
    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)

    res = nlc.call_llm('sys', 'hi', model='anthropic/claude-sonnet-5.5', max_tokens=100)
    assert res['ok'] is True
    assert res['text'] == 'HELLO'
    assert res['usage'] == {'total_tokens': 9}
    assert res['id'] == 'cmpl-1'


def test_call_llm_http_error_shape(monkeypatch):
    def _urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, 'Unauthorized', {},
            __import__('io').BytesIO(b'{"error":"auth failed"}'))

    monkeypatch.setattr(nlc, '_token', lambda: {
        'token': 't', 'inference_base_url': 'https://inf.example.com/v1'})
    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)

    res = nlc.call_llm('s', 'u', model='m')
    assert res['ok'] is False
    assert res['error'].startswith('http 401')


def test_call_llm_marks_timeouts_for_the_retry_layer(monkeypatch):
    """quant_service.call_llm_direct retries ONLY on _is_timeout."""
    def _urlopen(req, timeout=None):
        raise TimeoutError('timed out')

    monkeypatch.setattr(nlc, '_token', lambda: {
        'token': 't', 'inference_base_url': 'https://inf.example.com/v1'})
    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)

    res = nlc.call_llm('s', 'u', model='m')
    assert res['ok'] is False
    assert res['_is_timeout'] is True


def test_call_llm_handles_empty_choices(monkeypatch):
    """Malformed/empty responses must degrade, not raise."""
    def _urlopen(req, timeout=None):
        return _Resp({'choices': [], 'usage': {}})

    monkeypatch.setattr(nlc, '_token', lambda: {
        'token': 't', 'inference_base_url': 'https://inf.example.com/v1'})
    monkeypatch.setattr(nlc.urllib.request, 'urlopen', _urlopen)

    res = nlc.call_llm('s', 'u', model='m')
    assert res['ok'] is True
    assert res['text'] == ''


def test_token_fresh_for_is_zero_without_cache():
    assert nlc.token_fresh_for() == 0.0


# ---------- running as a Windows service (the NSSM/LocalSystem trap) ----------

def test_resolves_auth_json_when_home_is_systemprofile(monkeypatch, tmp_path):
    """REGRESSION, and the one that actually broke the brain.

    NSSM runs the services as LocalSystem, where Path.home() is
    C:\\Windows\\System32\\config\\systemprofile. The first version of this
    client used Path.home() directly, so the moment the backend went live
    in production every call failed with

        auth: Hermes auth.json not found at
        C:\\WINDOWS\\system32\\config\\systemprofile\\AppData\\Local\\hermes\\auth.json

    and the brain went straight back to HOLD. USERPROFILE is inherited by
    the service, so it is the reliable anchor -- not HOME.
    """
    fake_home = tmp_path / 'systemprofile'
    fake_home.mkdir()
    real_auth = tmp_path / 'operator' / 'AppData' / 'Local' / 'hermes' / 'auth.json'
    real_auth.parent.mkdir(parents=True)
    real_auth.write_text(json.dumps({'providers': {'nous': {'client_id': 'x'}}}),
                         encoding='utf-8')

    monkeypatch.delenv('HERMES_AUTH_JSON', raising=False)
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'operator'))
    monkeypatch.setenv('LOCALAPPDATA', '')
    monkeypatch.setattr(nlc, 'AUTH_JSON', fake_home / 'AppData' / 'Local' / 'hermes' / 'auth.json')

    assert nlc._resolve_auth_json() == real_auth


def test_explicit_override_wins(monkeypatch, tmp_path):
    """HERMES_AUTH_JSON must beat every heuristic -- it's the escape hatch
    for a service that needs a credential copied to a readable location."""
    override = tmp_path / 'custom' / 'auth.json'
    override.parent.mkdir(parents=True)
    override.write_text('{}', encoding='utf-8')

    monkeypatch.setenv('HERMES_AUTH_JSON', str(override))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'nowhere'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'also-nowhere'))

    assert nlc._resolve_auth_json() == override


def test_missing_everywhere_falls_back_to_home(monkeypatch, tmp_path):
    """No candidate exists -> return the home-based default, and let the
    caller raise the actionable error. Never invent a path."""
    monkeypatch.delenv('HERMES_AUTH_JSON', raising=False)
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'nowhere'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'also-nowhere'))
    monkeypatch.setattr(nlc, 'AUTH_JSON', tmp_path / 'fallback.json')

    assert nlc._resolve_auth_json() == tmp_path / 'fallback.json'


def test_read_auth_json_uses_resolver(monkeypatch, tmp_path):
    """_read_auth_json must go through the resolver, not the module constant."""
    real_auth = tmp_path / 'auth.json'
    real_auth.write_text(json.dumps({'providers': {'nous': {'client_id': 'resolved'}}}),
                         encoding='utf-8')
    monkeypatch.setenv('HERMES_AUTH_JSON', str(real_auth))

    assert nlc._read_auth_json()['providers']['nous']['client_id'] == 'resolved'


def test_missing_auth_json_error_names_the_resolved_path(monkeypatch, tmp_path):
    """The operator needs to be told WHICH path was searched."""
    missing = tmp_path / 'nope.json'
    monkeypatch.setenv('HERMES_AUTH_JSON', str(missing))
    with pytest.raises(nlc.NousAuthError) as ei:
        nlc._read_auth_json()
    assert str(missing) in str(ei.value)
