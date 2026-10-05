"""Tests for the LLM health circuit breaker.

FIX 2026-10-05: added after the brain silently failed auth for 9 trading
days (44,675 identical 401 lines, zero alerts). The regression these tests
lock down is the SILENCE, not the 401 itself.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_llm_circuit.py -q
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
QS_PATH = ROOT / 'scripts' / 'quant_service.py'


@pytest.fixture(scope='module')
def qs():
    """Import quant_service as a module without running its main()."""
    if str(ROOT / 'scripts') not in sys.path:
        sys.path.insert(0, str(ROOT / 'scripts'))
    spec = importlib.util.spec_from_file_location('qs_circuit_undertest', QS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _reset(qs, tmp_path, monkeypatch):
    """Each test starts with a closed circuit, writes to a throwaway log, and
    NEVER touches the network.

    Three separate hazards this fixture blocks:
    1. `log()` appends to the real data_cache/quant_service.log, so test runs
       would inject fake LLM-CIRCUIT-OPEN/CLOSED lines into the operator's
       forensic record of the 9-day outage.
    2. Since the backend moved to the Nous client (FIX 2026-10-05),
       stubbing `httpx.post` no longer intercepts anything -- these tests
       would make REAL paid LLM calls and assert on their output.
    3. A live call mutates the shared circuit, so tests would leak state
       into each other.
    """
    qs._LLM_CIRCUIT.update({
        'open': False, 'reason': '', 'opened_at': None, 'last_ok_at': None,
        'last_err_at': None, 'consecutive_errors': 0, 'total_errors': 0,
        'alerted': False, 'probes': 0,
    })
    orig_log_path = qs.LOG
    qs.LOG = tmp_path / 'quant_service_test.log'

    # Hard-block every network egress path.
    def _no_network(*a, **k):
        raise AssertionError(
            'test attempted a live network call -- these tests must be offline')
    monkeypatch.setattr(qs.httpx, 'post', _no_network, raising=False)
    monkeypatch.setattr(qs, '_nous_call_llm', _no_network, raising=False)

    yield
    qs.LOG = orig_log_path


# ---------- error classification ----------

@pytest.mark.parametrize('err,expected', [
    ('http 401: {"code":401,"message":"auth failed"}', 'auth'),
    ('http 402: insufficient balance', 'auth'),
    ('http 403: forbidden', 'auth'),
    ('{"type":"error","error":{"type":"authentication_error"}}', 'auth'),
    ('invalid_api_key', 'auth'),
    ('timeout after 30.0s', 'transient'),
    ('[Errno 11001] getaddrinfo failed', 'transient'),
    ('http 529: {"type":"error"}', 'transient'),
    ('The read operation timed out', 'transient'),
    ('', 'transient'),
])
def test_classify_llm_error(qs, err, expected):
    assert qs._classify_llm_error(err) == expected


# ---------- opening / closing ----------

def test_single_auth_error_opens_circuit_immediately(qs):
    """One 401 is conclusive -- no need to wait for a threshold."""
    qs._llm_record_error('http 401: {"code":401,"message":"auth failed"}')
    assert qs._LLM_CIRCUIT['open'] is True
    assert 'auth' in qs._LLM_CIRCUIT['reason']


def test_transient_errors_need_threshold_before_opening(qs):
    """Timeouts are retried; only a sustained run trips the circuit."""
    for _ in range(qs.LLM_CIRCUIT_ERROR_THRESHOLD - 1):
        qs._llm_record_error('timeout after 30.0s')
        assert qs._LLM_CIRCUIT['open'] is False
    qs._llm_record_error('timeout after 30.0s')
    assert qs._LLM_CIRCUIT['open'] is True


def test_success_closes_circuit(qs):
    qs._llm_record_error('http 401: auth failed')
    assert qs._LLM_CIRCUIT['open'] is True
    qs._llm_record_ok()
    assert qs._LLM_CIRCUIT['open'] is False
    assert qs._LLM_CIRCUIT['reason'] == ''
    assert qs._LLM_CIRCUIT['consecutive_errors'] == 0
    assert qs._LLM_CIRCUIT['last_ok_at'] is not None


def test_success_resets_consecutive_counter(qs):
    qs._llm_record_error('timeout after 30.0s')
    qs._llm_record_error('timeout after 30.0s')
    qs._llm_record_ok()
    qs._llm_record_error('timeout after 30.0s')
    # 1, not 3 -- a success in between breaks the run.
    assert qs._LLM_CIRCUIT['consecutive_errors'] == 1


def test_circuit_does_not_reopen_or_realert_while_already_open(qs):
    qs._llm_record_error('http 401: auth failed')
    first_reason = qs._LLM_CIRCUIT['reason']
    qs._llm_record_error('http 401: auth failed')
    assert qs._LLM_CIRCUIT['reason'] == first_reason


def test_alert_is_one_shot(qs):
    """A 9-day outage must not mean 44k Telegram messages."""
    qs._llm_record_error('http 401: auth failed')
    assert qs._LLM_CIRCUIT['alerted'] is True
    # Simulate a fresh outage after recovery -- the alert re-arms.
    qs._llm_record_ok()
    assert qs._LLM_CIRCUIT['alerted'] is False


def test_total_errors_accumulates_across_outages(qs):
    qs._llm_record_error('http 401: auth failed')
    qs._llm_record_ok()
    qs._llm_record_error('http 401: auth failed')
    assert qs._LLM_CIRCUIT['total_errors'] == 2


def test_llm_circuit_state_returns_copy(qs):
    """Callers must not be able to mutate internal circuit state."""
    snap = qs.llm_circuit_state()
    snap['open'] = 'tampered'
    assert qs._LLM_CIRCUIT['open'] is False


# ---------- the anti-storm behaviour (the actual regression) ----------

def test_open_circuit_short_circuits_most_calls(qs, monkeypatch):
    """While open, calls must NOT reach the network -- that was the bug.

    The 401 storm was 44,675 doomed HTTP requests. With the circuit latched,
    199 of every 200 calls must return locally without a POST.

    Note: the stub returns a 401 rather than raising, because `_post` catches
    bare Exception and would swallow the raise -- which is exactly why a
    request storm is invisible from inside the caller.
    """
    qs._llm_record_error('http 401: auth failed')

    calls = {'n': 0}

    def _counting_backend(system, user, model, max_tokens, timeout):
        calls['n'] += 1
        return {'ok': False, 'error': 'http 401: {"code":401,"message":"auth failed"}'}

    monkeypatch.setattr(qs, '_nous_call_llm', _counting_backend)

    # Probe #1 is allowed through (probes was incremented when the circuit
    # opened, so probes % PROBE_EVERY == 1 here).
    res = qs.call_llm_direct('sys', 'user')
    assert res['ok'] is False
    assert calls['n'] == 1

    # The next LLM_CIRCUIT_PROBE_EVERY - 1 calls must not touch the network.
    for _ in range(qs.LLM_CIRCUIT_PROBE_EVERY - 1):
        res = qs.call_llm_direct('sys', 'user')
        assert res['ok'] is False
        assert res.get('_circuit_open') is True
    assert calls['n'] == 1, 'circuit did not suppress the request storm'

    # And exactly one more call gets through -- the periodic probe that lets
    # a fixed credential recover without a service restart.
    res = qs.call_llm_direct('sys', 'user')
    assert res['ok'] is False
    assert calls['n'] == 2


def test_circuit_open_error_message_is_actionable(qs):
    qs._llm_record_error('http 401: {"code":401,"message":"auth failed"}')
    qs._LLM_CIRCUIT['probes'] = qs.LLM_CIRCUIT_PROBE_EVERY - 1
    res = qs.call_llm_direct('sys', 'user', max_tokens=10)
    assert res['ok'] is False
    assert 'llm-circuit-open' in res['error']
    assert '401' in res['error'], 'error must name the real cause'


def test_healthy_circuit_does_not_short_circuit(qs, monkeypatch):
    """Regression guard: the breaker must not block a WORKING LLM."""
    monkeypatch.setattr(
        qs, '_nous_call_llm',
        lambda **kw: {'ok': True, 'text': 'hello there', 'usage': {'total_tokens': 5}})
    res = qs.call_llm_direct('sys', 'hello', max_tokens=10)
    assert res['ok'] is True
    assert 'hello' in res['text']
    assert qs.llm_circuit_state()['open'] is False
    assert qs.llm_circuit_state()['consecutive_errors'] == 0
