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
from datetime import datetime, timezone
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

# Re-read auth.json this many seconds before the token actually expires, so
# an in-flight request never races the expiry boundary. NOTE: this is a
# re-READ margin, not a refresh margin -- see _adopt_hermes_token. We never
# call the token endpoint ourselves.
TOKEN_REREAD_MARGIN_SEC = 300

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


def _adopt_hermes_token(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Reuse the access token Hermes already obtained. NEVER refresh.

    FIX 2026-10-05: this function used to call POST /api/oauth/token
    itself. That is a protocol violation, not merely a style problem.

    Nous refresh tokens are SINGLE-USE and the server ROTATES them on every
    refresh. Hermes persists the rotated token back to auth.json. We cannot
    safely do the same -- two writers on one rotating secret is a race, and
    whichever loses gets the session revoked. It did, twice, and Hermes
    detected it:

        Nous Portal detected refresh-token reuse and revoked this session.
        Nous refresh tokens are single-use - only Hermes may call the
        refresh endpoint.

    That revocation kills BOTH the trading brain and every Hermes cron job,
    and recovery needs a browser. So the rule is now structural rather than
    a comment: this module only ever READS.

    The design that follows from that:
      - Hermes owns the lifecycle and rotates on schedule.
      - We poll auth.json and reuse whatever token is currently valid.
      - The brain is on a ~5 s decision loop, so it consumes a fresh Hermes
        token long before the 1 h expiry; our own refresh never needs to
        fire in practice.
      - If the token really is expired, say so and tell the operator to run
        `hermes auth add nous --type oauth`. Silently minting one is exactly
        the failure mode this replaces.

    Consequence to accept: if Hermes itself is not running long enough to
    refresh, the brain stops and says why. That is the correct trade -- a
    loud stop beats a revoked session.
    """
    token = cfg.get('access_token')
    if not token:
        err = cfg.get('last_auth_error') or {}
        detail = err.get('message') if isinstance(err, dict) else None
        raise NousAuthError(
            "Hermes has no Nous access token for this profile. "
            + (f"Last error: {detail} " if detail else "")
            + "Run `hermes auth add nous --type oauth` (needs a browser). "
              "This module deliberately never refreshes the token itself: "
              "Nous refresh tokens are single-use and rotating them outside "
              "Hermes revokes the session.")

    expires_at = _parse_expiry(cfg.get('expires_at'))
    _CACHE.update({
        'token': token,
        'expires_at': expires_at,
        'refresh_token': '',   # never read, never used, never persisted
        'client_id': cfg.get('client_id') or '',
        'inference_base_url': _inference_base(cfg),
        'base_url': '',
    })
    return _CACHE


def _parse_expiry(value: Optional[str]) -> float:
    """ISO-8601 -> epoch seconds. Returns 0.0 when unknown/unparseable."""
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except Exception:
        return 0.0


USE_OAUTH = os.environ.get('NOUS_USE_OAUTH', '').strip().lower() in ('1', 'true', 'yes')

def _static_key() -> Dict[str, Any]:
    """Static API-key auth (NOUS_API_KEY), with no auth.json dependency.

    FIX 2026-10-05: the OAuth path reads Hermes' auth.json for a bearer
    access_token. Under an NSSM LocalSystem service that file is missing /
    unreadable, so the brain degraded to HOLD with
    'Hermes has no Nous access token for this profile'. A static key has
    no lifecycle and no refresh race -- it is exactly what a headless
    24/7 service needs. Set NOUS_API_KEY in config/credentials.env.
    """
    key = os.environ.get('NOUS_API_KEY', '').strip()
    if not key:
        raise NousAuthError(
            "NOUS_API_KEY not set (and NOUS_USE_OAUTH not forced). "
            "Put a working sk-nous-... key in NOUS_API_KEY in "
            "config/credentials.env, or set NOUS_USE_OAUTH=1 to use "
            "Hermes' auth.json OAuth flow instead.")
    base = os.environ.get('NOUS_INFERENCE_BASE_URL', '').strip().rstrip('/')
    if not base:
        # Try to inherit from Hermes' auth.json; fall back to the default.
        try:
            cfg = _load_provider_config()
            base = _inference_base(cfg).rstrip('/')
        except Exception:
            base = 'https://inference-api.nousresearch.com/v1'
    _CACHE.update({
        'token': key,
        'expires_at': time.time() + 3600,  # static key: cache 1h, re-read
        'refresh_token': '',
        'client_id': '',
        'inference_base_url': base,
        'base_url': '',
    })
    return _CACHE


def _token() -> Dict[str, Any]:
    """Return a usable credential, re-reading auth.json when needed.

    There is deliberately no refresh path here -- see
    _adopt_hermes_token for why. "Needs a new token" means "Hermes has
    written a new token to disk, go read it", not "mint one yourself".

    Which path runs is decided live (not at import): NOUS_USE_OAUTH in
    ('1','true','yes') forces the OAuth/auth.json path, anything else
    (the default) uses the static NOUS_API_KEY.
    """
    with _LOCK:
        if os.environ.get('NOUS_USE_OAUTH', '').strip().lower() not in ('1', 'true', 'yes'):
            return _static_key()
        now = time.time()
        # Re-read a little before expiry so a long decision never starts
        # with a token that dies mid-flight. Hermes refreshes on its own
        # schedule, so this normally finds a fresh one already waiting.
        if _CACHE['token'] and now < (_CACHE['expires_at'] - TOKEN_REREAD_MARGIN_SEC):
            return _CACHE
        return _adopt_hermes_token(_load_provider_config())


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
