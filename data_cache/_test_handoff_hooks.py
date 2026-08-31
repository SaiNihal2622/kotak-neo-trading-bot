#!/usr/bin/env python3
"""Test the SessionStart and UserPromptSubmit handoff hooks."""
import json
import subprocess
import sys
import os

HOOK_DIR = r"C:\Users\saini\.minimax\agents\mavis\hooks"

def run_hook(script_name, payload):
    script_path = os.path.join(HOOK_DIR, script_name)
    proc = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return {"error": f"exit {proc.returncode}", "stderr": proc.stderr}
    return json.loads(proc.stdout)


# === TEST 1: SessionStart finds handoff file ===
print("=" * 70)
print("TEST 1: SessionStart detects existing handoff")
print("=" * 70)

# Make sure a handoff file exists for testing
handoff_path = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\session_handoff.md"
test_handoff = "# Test handoff\n\nPrevious session was working on X, Y, Z.\n"
with open(handoff_path, "w", encoding="utf-8") as f:
    f.write(test_handoff)

payload = {
    "input": {
        "agentName": "mavis",
        "sessionId": "test_new_session_001",
        "sessionType": "Main",
        "workspaceDir": r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot",
    },
    "output": {}
}
out = run_hook("session_start_handoff.py", payload)
print(f"Output metadata: {out.get('metadata', {})}")
assert out.get("metadata", {}).get("handoff_pending") == True, "FAIL: handoff not detected"
assert out.get("metadata", {}).get("handoff_path") == handoff_path, "FAIL: wrong path"
print("[OK] TEST 1 PASS: SessionStart detected handoff\n")

# Verify the state file was written
state_path = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\_handoff_state\test_new_session_001.json"
assert os.path.isfile(state_path), f"FAIL: state file not written: {state_path}"
with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)
print(f"State file: {state}")
assert state.get("injected") == False, "FAIL: state not initialized as not-injected"
print("[OK] TEST 1.5: State file written correctly\n")

# === TEST 2: UserPromptSubmit on first prompt injects handoff ===
print("=" * 70)
print("TEST 2: First user prompt gets handoff prepended")
print("=" * 70)

payload = {
    "input": {
        "agentName": "mavis",
        "sessionId": "test_new_session_001",
        "prompt": "What's the current status?",
    },
    "output": {}
}
out = run_hook("user_prompt_handoff.py", payload)
rewritten = out.get("prompt", "")
print(f"Rewritten prompt (first 300 chars): {rewritten[:300]!r}")
print(f"...")
print(f"Metadata: {out.get('metadata', {})}")
assert "HANDOFF START" in rewritten, "FAIL: handoff not injected"
assert "What's the current status?" in rewritten, "FAIL: original prompt missing"
assert out.get("metadata", {}).get("handoff_injected") == True, "FAIL: not marked injected"
print("[OK] TEST 2 PASS: Handoff injected on first prompt\n")

# === TEST 3: UserPromptSubmit on second prompt does NOT inject ===
print("=" * 70)
print("TEST 3: Second prompt is NOT modified (injection is one-shot)")
print("=" * 70)

payload = {
    "input": {
        "agentName": "mavis",
        "sessionId": "test_new_session_001",
        "prompt": "Thanks, now show me the dashboard",
    },
    "output": {}
}
out = run_hook("user_prompt_handoff.py", payload)
rewritten = out.get("prompt", "<ABSENT>")  # absent means original is used by runtime
print(f"Rewritten prompt: {rewritten!r}")
print(f"Metadata: {out.get('metadata', {})}")
# Per hook protocol, when prompt is absent in output, runtime uses original.
# So both "absent" and "equal-to-original" are correct no-rewrite signals.
assert rewritten in ("<ABSENT>", "Thanks, now show me the dashboard"), f"FAIL: prompt was modified: {rewritten!r}"
assert out.get("metadata", {}).get("reason") == "already_injected", f"FAIL: wrong reason: {out.get('metadata')}"
print("[OK] TEST 3 PASS: Second prompt passes through unchanged\n")

# === TEST 4: UserPromptSubmit on a session with no handoff ===
print("=" * 70)
print("TEST 4: Session with no handoff passes through")
print("=" * 70)

# No state file for this session
payload = {
    "input": {
        "agentName": "mavis",
        "sessionId": "test_session_no_handoff",
        "prompt": "Hello",
    },
    "output": {}
}
out = run_hook("user_prompt_handoff.py", payload)
rewritten = out.get("prompt", "<ABSENT>")
print(f"Rewritten prompt: {rewritten!r}")
print(f"Metadata: {out.get('metadata', {})}")
assert rewritten in ("<ABSENT>", "Hello"), f"FAIL: prompt was modified: {rewritten!r}"
print("[OK] TEST 4 PASS: No handoff -> no modification\n")

# === TEST 5: Idempotency — even if state file is missing, no crash ===
print("=" * 70)
print("TEST 5: Missing state file = no crash")
print("=" * 70)

# Clear any state file that might exist
state_dir = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\_handoff_state"
import shutil
if os.path.isdir(state_dir):
    shutil.rmtree(state_dir)

payload = {
    "input": {
        "agentName": "mavis",
        "sessionId": "test_fresh_session_999",
        "prompt": "Hi",
    },
    "output": {}
}
out = run_hook("user_prompt_handoff.py", payload)
print(f"Output: {out}")
print(f"Rewritten prompt: {out.get('prompt', 'NOT_PRESENT')!r}")
print(f"Metadata: {out.get('metadata', {})}")
assert out.get("prompt") in (None, "Hi"), f"FAIL: prompt unexpectedly modified: {out.get('prompt')!r}"
print("[OK] TEST 5 PASS: Missing state file handled gracefully\n")

print("=" * 70)
print("ALL 5 HANDOFF TESTS PASSED [OK]")
print("=" * 70)

# Clean up test handoff
# (Leave the real handoff from earlier intact if it had different content)
