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
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

def _default_auth_json() -> Path:
    """Best-effort home-based default, computed LAZILY.

    FIX 2026-10-05: this used to be a module-level constant,
    `AUTH_JSON = Path.home() / ...`, which RAISES
    `RuntimeError: Could not determine home directory` under a bare
    LocalSystem environment (no USERPROFILE, no HOMEDRIVE/HOMEPATH, no
    HOME). Because it was evaluated at import time, that exception would
    have propagated out of `import nous_llm_client` and taken the whole
    brain down -- a crash instead of a clean degraded HOLD.

    Never call Path.home() at module scope. Every caller here is on a
    request path where a raised error is recoverable, so a missing home is
    just another candidate that doesn't exist.
    """
    try:
        return Path.home() / 'AppData' / 'Local' / 'hermes' / 'auth.json'
    except (RuntimeError, OSError):
        # No profile at all. Return a path that will not exist; the caller
        # raises a clear "not found at <path>" error naming it.
        return Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'hermes' / 'auth.json'


# Kept for backward compatibility with anything importing this name.
# Resolved through the lazy helper so importing the module is always safe.
AUTH_JSON = _default_auth_json()


def _local_auth_copy() -> Path:
    """Candidate 2: an operator-provided copy inside the project.

    Reading another account's AppData as LocalSystem bypasses the ACL that
    normally protects it. That is accepted for a local dev tool on a
    single-user machine, but if you would rather not have a Windows service
    account reading your profile, drop a gitignored copy of auth.json at
    config/hermes_auth.json and this candidate will find it instead.

    Extracted as a function so tests can redirect it.
    """
    return Path(__file__).resolve().parent.parent.parent / 'config' / 'hermes_auth.json'


def _resolve_auth_json() -> Path:
    """Locate Hermes' auth.json regardless of the user the process runs as.

    FIX 2026-10-05: this bit the brain twice, and both failures were silent
    in the worst way -- the brain degraded to HOLD and looked disciplined.

    NSSM runs the services as LocalSystem (`SERVICE_START_NAME: LocalSystem`,
    confirmed with `sc qc KotakQuantService`). Under that account:

        USERPROFILE  -> unset
        LOCALAPPDATA -> unset
        Path.home()  -> C:\\Windows\\System32\\config\\systemprofile
        (and with no profile env at all, Path.home() raises outright)

    So every profile-derived heuristic fails, and a LocalSystem service
    genuinely CANNOT read the operator's AppData -- that is the point of the
    isolation. Probing other users' profiles is not an option and would be
    the wrong thing to try.

    Therefore: an explicit, operator-configured path is the primary
    mechanism, and it is checked FIRST. On this host it is set in the
    service environment:

        HERMES_AUTH_JSON=C:\\Users\\<you>\\AppData\\Local\\hermes\\auth.json

    Resolution order (first existing file wins):
      1. HERMES_AUTH_JSON          -- explicit, required for LocalSystem
      2. a KOTAK project-local copy at <ROOT>/config/hermes_auth.json
      3. USERPROFILE-derived      -- works for a normal user session
      4. LOCALAPPDATA-derived     -- normal user session
      5. the home-based default   -- last resort; caller raises if missing

    On the credential file's own permissions: reading another account's
    AppData as LocalSystem bypasses the ACL that normally protects it. That
    is a real, if narrow, security consideration -- it is accepted here
    because the file holds a refresh token for a local dev tool on a
    single-user machine, the operator configured it deliberately, and the
    alternative is a trading brain that silently stops working. Prefer
    option 2 (a gitignored copy inside the project) if that trade-off
    matters to you.
    """
    override = os.environ.get('HERMES_AUTH_JSON', '').strip()
    if override:
        p = Path(override)
        if p.is_file():
            return p
        # An EXPLICIT path that does not exist is a configuration error, not a
        # hint. Silently falling through to another candidate here would mean
        # the operator sets a path, it goes stale (profile moved/renamed), and
        # the service quietly keeps using a different credential -- or none.
        # Fail with the path the operator actually asked for.
        raise NousAuthError(
            f"HERMES_AUTH_JSON points at a file that does not exist: {p}. "
            f"Fix the path in config/credentials.env, or delete the "
            f"HERMES_AUTH_JSON line to fall back to auto-detection.")

    # Project-local copy: gitignored, and readable without another profile.
    local_copy = _local_auth_copy()
    if local_copy.is_file():
        return local_copy

    userprofile = os.environ.get('USERPROFILE', '').strip()
    if userprofile:
        cand = Path(userprofile) / 'AppData' / 'Local' / 'hermes' / 'auth.json'
        if cand.is_file():
            return cand

    local = os.environ.get('LOCALAPPDATA', '').strip()
    if local:
        cand = Path(local) / 'hermes' / 'auth.json'
        if cand.is_file():
            return cand

    # Last resort. Avoid Path.home() entirely: it RAISES under a bare
    # LocalSystem environment, and a raise here would look like a crash
    # rather than a missing credential.
    return AUTH_JSON

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
    path = _resolve_auth_json()
    if not path.is_file():
        raise NousAuthError(f"Hermes auth.json not found at {path}")
    try:
        # utf-8-sig: Hermes writes this file with PowerShell-style BOM on
        # some paths, and a plain utf-8 read makes json.loads fail.
        with open(path, 'r', encoding='utf-8-sig') as fh:
            return json.load(fh)
    except Exception as exc:  # pragma: no cover - defensive
        raise NousAuthError(f"could not read {path}: {exc}") from exc


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
    try:
        cred = _token()
    except NousAuthError as auth_err:
        # Return the failure, never raise. This function's contract is
        # {"ok": bool, ...} and its caller (quant_service.call_llm_direct)
        # only knows how to handle a returned error -- an exception here
        # would propagate up through the watch loop instead of degrading to
        # a HOLD. A missing credential is an expected, recoverable state.
        return {'ok': False, 'error': f'auth: {auth_err}'}

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
