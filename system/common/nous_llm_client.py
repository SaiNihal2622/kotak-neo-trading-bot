"""Self-refreshing Nous Portal LLM client for the quant brain.

WHY THIS EXISTS
---------------
The brain's original LLM path used a hardcoded MiniMax key in
config/credentials.env. That key died (401 auth failed) on 2026-09-21 and
the brain degraded to HOLD for 9 trading days with no alert -- 44,675
identical failures in data_cache/quant_service.log.

This module removes the static secret entirely. It reads the SAME
credential Hermes itself uses (AppData/Local/hermes/auth.json), refreshes
the short-lived access token on demand, and caches it until shortly before
expiry. So there is no long-lived key to expire and nothing to rotate.

FIX 2026-10-05 (this file): added after the 9-day silent outage.

Security notes:
- The access token is NEVER written to config/credentials.env, never
  logged, and never included in an error message. Only its length is
  ever surfaced.
- Reading another app's credential store is a deliberate, local-only
  choice made by the operator. It is the same file Hermes reads for its
  own inference calls.

Usage:
    from nous_llm_client import call_llm
    result = call_llm(system="...", user="...", max_tokens=6000)
    # -> {"ok": bool, "text": str, "usage": dict, "error": str}
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

AUTH_JSON = Path.home() / 'AppData' / 'Local' / 'hermes' / 'auth.json'

# Refresh this many seconds before the token actually expires, so an
# in-flight request never races the expiry boundary.
REFRESH_MARGIN_SEC = 300

# A completion can legitimately take a while on a big prompt.
DEFAULT_TIMEOUT_SEC = 90.0

_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {
    'token': None,
    'expires_at': 0.0,          # epoch seconds
    'base_url': '',
    'inference_base_url': '',
    'refresh_token': '',
    'client_id': '',
}


class NousAuthError(RuntimeError):
    """Raised when the Nous credential cannot be obtained or refreshed."""


def _read_auth_json() -> Dict[str, Any]:
    if not AUTH_JSON.exists():
        raise NousAuthError(f"Hermes auth.json not found at {AUTH_JSON}")
    try:
        # utf-8-sig: Hermes writes this file with PowerShell-style BOM on
        # some paths, and a plain utf-8 read makes json.loads fail.
        with open(AUTH_JSON, 'r', encoding='utf-8-sig') as fh:
            return json.load(fh)
    except Exception as exc:  # pragma: no cover - defensive
        raise NousAuthError(f"could not read {AUTH_JSON}: {exc}") from exc


def _load_provider_config() -> Dict[str, Any]:
    data = _read_auth_json()
    providers = data.get('providers') or {}
    nous = providers.get('nous') or {}
    if not nous:
        raise NousAuthError("no 'nous' provider block in Hermes auth.json")
    return nous


def _token_endpoint(cfg: Dict[str, Any]) -> str:
    portal = (cfg.get('portal_base_url') or '').rstrip('/')
    if not portal:
        raise NousAuthError("portal_base_url missing from Hermes auth.json")
    # Verified against hermes_cli/auth_nous.py::_refresh_access_token:
    # the path is /api/oauth/token and the refresh token travels in the
    # x-nous-refresh-token HEADER, not as a form field.
    return f"{portal}/api/oauth/token"


def _inference_base(cfg: Dict[str, Any]) -> str:
    base = (cfg.get('inference_base_url') or '').rstrip('/')
    if not base:
        raise NousAuthError("inference_base_url missing from Hermes auth.json")
    return base


def _refresh(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Exchange the refresh token for a fresh access token."""
    refresh_token = cfg.get('refresh_token') or _CACHE.get('refresh_token')
    client_id = cfg.get('client_id') or _CACHE.get('client_id')
    if not refresh_token or not client_id:
        raise NousAuthError("Hermes auth.json has no refresh_token/client_id; "
                            "run `hermes auth add nous` to re-login")

    body = f"grant_type=refresh_token&client_id={client_id}".encode()
    req = urllib.request.Request(
        _token_endpoint(cfg),
        data=body,
        headers={
            'x-nous-refresh-token': refresh_token,
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        # Never echo the body: it can contain credential fragments.
        raise NousAuthError(f"token refresh failed (HTTP {exc.code})") from exc
    except Exception as exc:
        raise NousAuthError(f"token refresh failed: {exc}") from exc

    token = payload.get('access_token')
    if not token:
        raise NousAuthError("token refresh response had no access_token")

    _CACHE.update({
        'token': token,
        'expires_at': time.time() + float(payload.get('expires_in') or 3600),
        'refresh_token': payload.get('refresh_token') or refresh_token,
        'inference_base_url': (payload.get('inference_base_url')
                               or _inference_base(cfg)).rstrip('/'),
        'base_url': (payload.get('base_url') or '').rstrip('/'),
    })
    return _CACHE


def _token() -> Dict[str, Any]:
    """Return a valid cached credential, refreshing if needed. Thread-safe."""
    with _LOCK:
        now = time.time()
        if _CACHE['token'] and now < (_CACHE['expires_at'] - REFRESH_MARGIN_SEC):
            return _CACHE
        cfg = _load_provider_config()
        # Pick up a rotated refresh_token / base_url from disk too.
        _CACHE['refresh_token'] = cfg.get('refresh_token') or _CACHE['refresh_token']
        _CACHE['client_id'] = cfg.get('client_id') or _CACHE['client_id']
        return _refresh(cfg)


def token_fresh_for() -> float:
    """Seconds until the cached token needs refreshing (0 if none cached)."""
    return max(0.0, _CACHE['expires_at'] - time.time())


def call_llm(system: str, user: str, *, model: str, max_tokens: int = 6000,
             temperature: Optional[float] = None,
             timeout: float = DEFAULT_TIMEOUT_SEC) -> Dict[str, Any]:
    """One chat completion. Mirrors scripts/quant_service.call_llm_direct's
    return contract so it is a drop-in replacement:
        {"ok": bool, "text": str, "usage": dict, "error": str}
    """
    cred = _token()
    url = f"{cred['inference_base_url']}/chat/completions"

    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': user})

    payload: Dict[str, Any] = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': messages,
    }
    if temperature is not None:
        payload['temperature'] = temperature

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Authorization': f"Bearer {cred['token']}",
            'Content-Type': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'error': f'http {exc.code}: {_safe_body(exc)}'}
    except TimeoutError:
        return {'ok': False, 'error': f'timeout after {timeout}s', '_is_timeout': True}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)[:300]}

    text = ''
    for choice in body.get('choices', []) or []:
        msg = choice.get('message') or {}
        if isinstance(msg, dict):
            text += msg.get('content') or ''
    return {
        'ok': True,
        'text': text,
        'usage': body.get('usage') or {},
        'id': body.get('id'),
    }


def _safe_body(exc: urllib.error.HTTPError) -> str:
    """Short, credential-free excerpt of an error body."""
    try:
        raw = exc.read()[:300].decode('utf-8', 'replace')
    except Exception:
        return '<unreadable>'
    # Strip anything JWT-shaped just in case an upstream echoes the header.
    import re
    return re.sub(r'eyJ[A-Za-z0-9_\-]{20,}', '<token-redacted>', raw)
