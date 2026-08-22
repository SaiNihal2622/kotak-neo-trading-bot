"""strategy_version.py — read the current strategy code version from git.

Outputs a small JSON describing the strategy code state, so each trader
decision can be traced back to the exact code that produced it.

Usage:
    python scripts/strategy_version.py              # prints JSON to stdout
    python scripts/strategy_version.py --record    # appends to data_cache/strategy_versions.jsonl
    python scripts/strategy_version.py --record --commit  # also commits if strategy/ has uncommitted changes
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _git(*args) -> str:
    """Run git in the project dir, return stripped stdout (or '' on error)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT)] + list(args),
            capture_output=True, text=True, timeout=15, check=False,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def get_version() -> dict:
    """Return current strategy code version metadata."""
    sha = _git("rev-parse", "HEAD")
    short = _git("rev-parse", "--short", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    # get latest commit touching kotak_bot/strategy/
    last_strategy_sha = _git("log", "-1", "--format=%H", "--", "kotak_bot/strategy/")
    last_strategy_short = _git("log", "-1", "--format=%h", "--", "kotak_bot/strategy/")
    last_strategy_msg = _git("log", "-1", "--format=%s", "--", "kotak_bot/strategy/")
    # dirty working tree (any uncommitted change in strategy/)
    diff_out = _git("status", "--short", "--", "kotak_bot/strategy/")
    dirty = bool(diff_out)
    # how many commits since the last strategy change?
    n_since = 0
    if last_strategy_sha:
        try:
            n_since = int(_git("rev-list", "--count", f"{last_strategy_sha}..HEAD") or 0)
        except Exception:
            n_since = 0
    return {
        "ts": datetime.now().isoformat(),
        "branch": branch or "unknown",
        "head_sha": sha,
        "head_short": short,
        "strategy_sha": last_strategy_sha,
        "strategy_short": last_strategy_short,
        "strategy_msg": last_strategy_msg,
        "strategy_dirty": dirty,
        "n_commits_since_strategy_change": n_since,
    }


def commit_strategy_changes() -> bool:
    """If kotak_bot/strategy/ has uncommitted changes, commit them.
    Returns True if a commit was made."""
    diff_out = _git("status", "--short", "--", "kotak_bot/strategy/")
    if not diff_out:
        return False
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"chore(strategy): auto-snapshot at {ts}"
    # stage only the strategy folder + its __init__
    add = _git("add", "--", "kotak_bot/strategy/")
    if add is None and _git("status", "--short", "--", "kotak_bot/strategy/") == "":
        return False
    r = subprocess.run(
        ["git", "-C", str(ROOT), "commit", "-m", msg, "--", "kotak_bot/strategy/"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    return r.returncode == 0


def record_to_jsonl(version: dict) -> None:
    """Append to data_cache/strategy_versions.jsonl (one JSON per line)."""
    out = ROOT / "data_cache" / "strategy_versions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(version, default=str) + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--record", action="store_true", help="Append to data_cache/strategy_versions.jsonl")
    p.add_argument("--commit", action="store_true", help="If strategy/ has uncommitted changes, commit them first")
    args = p.parse_args()

    if args.commit:
        committed = commit_strategy_changes()
        if committed:
            print("[strategy_version] committed strategy/ snapshot", file=sys.stderr)

    v = get_version()
    print(json.dumps(v, indent=2, default=str))
    if args.record:
        record_to_jsonl(v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
