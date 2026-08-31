#!/usr/bin/env python3
"""Test the new sanitizer against a simulated 3.6MB memory tool result."""
import json
import subprocess
import sys
import os

HOOK_SCRIPT = r"C:\Users\saini\.minimax\agents\mavis\hooks\sanitize_tool_result.py"

def run_sanitizer(tool_name, tool_args, tool_result, session_id="test_ses_abc"):
    payload = {
        "input": {
            "agentName": "mavis",
            "sessionId": session_id,
            "toolName": tool_name,
            "toolArgs": tool_args,
            "toolCallId": "call_test_001",
            "workspaceDir": r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot",
        },
        "output": {
            "toolArgs": tool_args,
            "toolResult": tool_result,
            "metadata": {}
        }
    }
    proc = subprocess.run(
        [sys.executable, HOOK_SCRIPT],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return {"error": f"non-zero exit: {proc.returncode}", "stderr": proc.stderr}
    return json.loads(proc.stdout)


# === TEST 1: 3.6MB memory tool result (the actual killer) ===
print("=" * 70)
print("TEST 1: memory tool returning 3.6MB (the documented killer)")
print("=" * 70)

# Build a 3.6MB result that mirrors the dead session's actual content
big_text = ("### Heartbeat — Tue 10:10 IST, MKT OPEN, bot alive, MAIN feed HEALTHY\n"
            "Type: status\n"
            "- Some content line that takes up space in the message.\n") * 50000  # ~3.6MB
big_text = big_text[:3_700_000]  # trim to exactly 3.6MB
big_result = json.dumps({
    "content": [{"type": "text", "text": big_text}],
    "details": {"kind": "memory", "ok": True, "target": "main"}
})
print(f"Input toolResult size: {len(big_result)/1024/1024:.2f}MB ({len(big_result)} chars)")

out = run_sanitizer("memory", {"target": "main", "operation": "read"}, big_result)
sanitized = out.get("toolResult", "")
print(f"Output toolResult size: {len(sanitized)/1024:.1f}KB ({len(sanitized)} chars)")
print(f"Metadata: {out.get('metadata', {})}")
assert len(sanitized) < 100_000, f"FAIL: sanitizer output still {len(sanitized)} chars (should be <100KB)"
assert out.get("metadata", {}).get("sanitized") == "memory_saved_tail", f"FAIL: wrong sanitizer branch: {out.get('metadata')}"
# Verify the full content was saved to disk
saved_path = json.loads(sanitized).get("details", {}).get("saved_to", "")
print(f"Saved to: {saved_path}")
assert os.path.isfile(saved_path), f"FAIL: saved file doesn't exist: {saved_path}"
print(f"Saved file size: {os.path.getsize(saved_path)/1024:.1f}KB")
# Spot-check that head + tail are in the result
sanitized_text = json.loads(sanitized)["content"][0]["text"]
assert "HEAD" in sanitized_text and "TAIL" in sanitized_text, "FAIL: HEAD/TAIL markers missing"
print("[OK] TEST 1 PASS: 3.6MB memory result -> <100KB with head+tail summary\n")

# === TEST 2: mavis session messages with limit=200 (uncapped) ===
print("=" * 70)
print("TEST 2: mavis session messages with limit=200 (was 900KB before fix)")
print("=" * 70)
big_msgs = json.dumps({
    "ok": True,
    "command": "session messages",
    "response": {"messages": [{"msg_id": f"m{i}", "data_json": "x" * 10000} for i in range(100)]}
})
print(f"Input toolResult size: {len(big_msgs)/1024:.1f}KB")
out = run_sanitizer("mavis", {"command": "session messages", "args": {"session_id": "x", "limit": 200}}, big_msgs)
sanitized = out.get("toolResult", "")
new_args = out.get("toolArgs", {})
print(f"Output toolResult size: {len(sanitized)/1024:.1f}KB")
print(f"New toolArgs: {new_args}")
print(f"Metadata: {out.get('metadata', {})}")
# The catch-all should cap it to 50KB
assert len(sanitized) < 60_000, f"FAIL: catch-all did not cap mavis result ({len(sanitized)})"
# The limit should also be capped to 20
if new_args and new_args.get("args", {}).get("limit") is not None:
    assert new_args["args"]["limit"] <= 20, f"FAIL: limit not capped to 20: {new_args}"
    print("[OK] TEST 2 PASS: mavis session messages capped to 50KB AND limit->20\n")
else:
    print("[OK] TEST 2 PASS: mavis session messages capped to 50KB\n")

# === TEST 3: bash with 80KB output (already handled, regression check) ===
print("=" * 70)
print("TEST 3: bash with 80KB output (regression check)")
print("=" * 70)
big_bash = "line\n" * 12000  # ~60KB
big_bash = big_bash * 2  # 120KB
print(f"Input toolResult size: {len(big_bash)/1024:.1f}KB")
out = run_sanitizer("bash", {"command": "echo test"}, big_bash)
sanitized = out.get("toolResult", "")
print(f"Output toolResult size: {len(sanitized)/1024:.1f}KB")
print(f"Metadata: {out.get('metadata', {})}")
assert len(sanitized) < 60_000, f"FAIL: bash not capped: {len(sanitized)}"
print("[OK] TEST 3 PASS: bash output still capped\n")

# === TEST 4: small result untouched (no false positives) ===
print("=" * 70)
print("TEST 4: small result (5KB) should pass through unchanged")
print("=" * 70)
small = json.dumps({"content": [{"type": "text", "text": "hello world"}]})
out = run_sanitizer("mavis", {"command": "agent list"}, small)
sanitized = out.get("toolResult", "")
print(f"Input size: {len(small)} chars, output size: {len(sanitized)} chars")
print(f"Metadata: {out.get('metadata', {})}")
assert sanitized == small, f"FAIL: small result was modified: {sanitized[:100]!r}"
assert not out.get("metadata", {}).get("sanitized"), f"FAIL: small result was flagged: {out.get('metadata')}"
print("[OK] TEST 4 PASS: small results pass through untouched\n")

# === TEST 5: previously broken case — a 4MB tool result for an unknown tool ===
print("=" * 70)
print("TEST 5: 4MB result from an unknown tool (the catch-all)")
print("=" * 70)
unknown_result = "x" * 4_000_000
out = run_sanitizer("some_exotic_mcp_tool", {"foo": "bar"}, unknown_result)
sanitized = out.get("toolResult", "")
print(f"Input: 4.00MB, output: {len(sanitized)/1024:.1f}KB")
print(f"Metadata: {out.get('metadata', {})}")
assert len(sanitized) < 60_000, f"FAIL: catch-all failed: {len(sanitized)}"
assert "catchall" in out.get("metadata", {}).get("sanitized", ""), f"FAIL: not catchall branch: {out.get('metadata')}"
print("[OK] TEST 5 PASS: catch-all capped the unknown tool's 4MB result\n")

print("=" * 70)
print("ALL 5 TESTS PASSED [OK]")
print("=" * 70)
