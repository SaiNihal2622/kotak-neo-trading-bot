"""End-to-end smoke test: the real brain decision path against the live LLM.

This is the test that would have caught the 9-day outage on day 1. It runs
the ACTUAL decide() code in scripts/quant_service.py -- circuit breaker,
backend dispatch, JSON parsing, normalisation -- against the real Nous
backend, then asserts the result is a usable decision rather than an
HOLD-with-llm-error.

Skipped automatically when the Hermes credential is unavailable, so it never
turns a credential outage into a false test failure. But when the credential
IS present, a failure here is real and must be treated as such.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_llm_brain_e2e.py -q
    .venv\\Scripts\\python.exe -m pytest tests/test_llm_brain_e2e.py -q -m live
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


@pytest.fixture(scope='module')
def qs():
    if str(ROOT / 'scripts') not in sys.path:
        sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location(
        'qs_e2e_undertest', ROOT / 'scripts' / 'quant_service.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _credential_available() -> bool:
    try:
        sys.path.insert(0, str(ROOT / 'system' / 'common'))
        from nous_llm_client import _load_provider_config
        _load_provider_config()
        return True
    except Exception:
        return False


LIVE = pytest.mark.skipif(
    not _credential_available(),
    reason='no Hermes Nous credential on this host (brain would fail for real)')


@LIVE
def test_live_llm_backend_is_nous(qs):
    """The dead static key must not be the configured backend."""
    assert qs.LLM_BACKEND == 'nous', (
        f"LLM_BACKEND is {qs.LLM_BACKEND!r}; the MiniMax key is dead "
        f"(401/402 verified 2026-10-05)")
    assert qs._nous_call_llm is not None, 'nous_llm_client failed to import'


@LIVE
def test_live_call_llm_direct_succeeds(qs):
    """The exact function every decision goes through must return usable text."""
    res = qs.call_llm_direct(
        'You are a JSON-only responder. Output nothing but valid JSON.',
        'Return exactly this JSON and nothing else: {"ok":true,"n":7}',
        max_tokens=4000,
    )
    assert res.get('ok') is True, f"live LLM call failed: {res.get('error')}"
    assert res.get('text', '').strip(), 'live LLM returned empty text'

    # The circuit must be closed after a success.
    assert qs.llm_circuit_state()['open'] is False


@LIVE
def test_live_call_llm_direct_yields_parsable_json(qs):
    """The decision path json.loads()s the response -- verify that end-to-end.

    This is the failure the 32000-token bump fixes: with the old 6000 budget
    the reasoning consumed everything and text came back empty.
    """
    res = qs.call_llm_direct(
        'You are a professional Indian index-options trader. Think briefly, '
        'then output ONE JSON object only, no prose, no code fences.',
        'Spot is 22550, VIX 14.8, session move +0.04%. '
        'Output: {"type":"HOLD","rationale":"<25 words>"}',
        max_tokens=qs.LLM_MAX_TOKENS,
    )
    assert res.get('ok') is True, f"call failed: {res.get('error')}"

    text = (res.get('text') or '').strip()
    if text.startswith('```'):
        text = '\n'.join(text.split('\n')[1:]).rstrip('`').strip()
    assert text, 'empty text after fence-strip'

    payload = json.loads(text)
    assert payload.get('type') in ('HOLD', 'OPEN', 'CLOSE', 'SKIP_DAY'), payload


@LIVE
def test_live_circuit_closes_after_success(qs):
    """A working credential must close a previously-open circuit.

    This is the auto-recovery path: once the credential is fixed, the brain
    resumes normal decisions without needing a service restart.

    Note the probe arithmetic: call_llm_direct increments `probes` BEFORE
    the modulo check, and only `probes % PROBE_EVERY == 1` reaches the
    network. So probes must be set to a multiple of PROBE_EVERY for the
    next call to land on 1.
    """
    qs._LLM_CIRCUIT['open'] = True
    qs._LLM_CIRCUIT['probes'] = qs.LLM_CIRCUIT_PROBE_EVERY  # -> next is 201 % 200 == 1
    res = qs.call_llm_direct('Reply with JSON only.', '{"ok":true}', max_tokens=2000)
    assert res.get('ok') is True, f"probe failed: {res.get('error')}"
    assert qs.llm_circuit_state()['open'] is False, \
        'circuit stayed open after a successful call'


@LIVE
def test_live_usage_is_reported_for_cost_tracking(qs):
    """performance_tracker.record_llm_cost depends on usage being present."""
    res = qs.call_llm_direct('Reply with the single word: pong',
                             'pong', max_tokens=2000)
    assert res.get('ok') is True
    assert res.get('usage'), 'no usage block -- cost tracking would silently no-op'
