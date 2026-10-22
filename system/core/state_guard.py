"""
state_guard.py — SYSTEM-LEVEL write-ownership enforcement.

The recurring failure class across this project is MULTIPLE components writing
the SAME shared state file (paper_state.json, quant_actions.json) and
clobbering each other: the bot's empty book overwrote gateway fills, the
pre-market harness POSTed /api/plan and created phantom positions, the bridge
left an unconsumed CLOSE-ALL clogging the queue. Each was patched individually;
this module kills the CLASS by enforcing single-owner writes at the write site.

OWNERSHIP MAP — the single source of truth for who may write what.
  - paper_state.json      -> ExecGateway (the executor). The bot, brain, bridge,
                             probes, and reset scripts must NOT write it.
  - quant_actions.json    -> the brain (quant_service / brain_daemon). The bridge
                             only READS it (and marks consumed). Probes must not.
  - quant_service_state.json -> the brain (quant_service) only.

Any write attempt by a non-owner is REJECTED and logged loudly. This is
fail-closed: a rogue writer cannot corrupt the book, it can only fail loudly
so the auto-operator escalates it.

Usage:
    from system.core.state_guard import guarded_write, OWNERS
    ok, err = guarded_write("paper_state.json", data, owner="ExecGateway")
    if not ok: logger.error(err)   # non-owner -> rejected, nothing written
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# OWNERSHIP MAP
#   key:   canonical filename (basename) of the shared state file
#   value: the single component allowed to write it
# ---------------------------------------------------------------------------
OWNERS: dict[str, str] = {
    "paper_state.json": "ExecGateway",
    "quant_actions.json": "Brain",          # bridge READS + marks consumed only
    "quant_service_state.json": "Brain",
}

# Components that are allowed to write NOTHING shared (probes, harnesses,
# reset scripts, the bot in bridge-active mode). They may only READ.
READ_ONLY_COMPONENTS: set[str] = {
    "Probe", "PreMarketHarness", "E2EProbe", "ResetScript", "BotDataFeed",
}

# ---------------------------------------------------------------------------
# Atomic write with ownership enforcement.
# ---------------------------------------------------------------------------
_lock = threading.Lock()


def guarded_write(
    path: str | Path,
    data: dict | list,
    owner: str,
    *,
    atomic: bool = True,
) -> tuple[bool, str]:
    """Write `data` to `path` ONLY if `owner` is the registered owner.

    Returns (ok, err_or_ok_msg). On non-owner, returns (False, reason) and
    writes NOTHING — fail-closed.
    """
    p = Path(path)
    fname = p.name

    if owner in READ_ONLY_COMPONENTS:
        return False, f"state_guard: {owner} is read-only; cannot write {fname}"

    allowed = OWNERS.get(fname)
    if allowed is None:
        # Not a guarded shared file — allow (it's a private/scratch file).
        return _do_write(p, data, atomic), "ok (unguarded file)"

    if owner != allowed:
        return (
            False,
            f"state_guard: WRITE DENIED — {owner} tried to write {fname}, "
            f"but {allowed} owns it. Rejected (fail-closed).",
        )

    return _do_write(p, data, atomic), f"ok ({owner} owns {fname})"


def _do_write(p: Path, data: dict | list, atomic: bool) -> bool:
    """Write JSON atomically (tmp + rename) to avoid torn reads."""
    p.parent.mkdir(parents=True, exist_ok=True)
    if atomic:
        tmp = p.with_suffix(p.suffix + ".tmp")
        with _lock:
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, p)
    else:
        with _lock:
            p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return True


def assert_owner(fname: str, owner: str) -> None:
    """Raise if `owner` is not the registered owner of `fname` (for tests)."""
    allowed = OWNERS.get(fname)
    if allowed is not None and owner != allowed:
        raise PermissionError(
            f"state_guard: {owner} is not the owner of {fname} ({allowed} is)"
        )
