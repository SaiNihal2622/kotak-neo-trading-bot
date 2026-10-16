"""Set KOTAK_BRIDGE_ACTIVE=YES on the KotakBotPaper NSSM service (runs as LocalSystem)."""
import subprocess, sys
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
SVC = "KotakBotPaper"
# read current env
cur = subprocess.run([NSSM, "get", SVC, "AppEnvironmentExtra"], capture_output=True, text=True).stdout
cur = cur.replace("\x00", "").strip()
print("current env:", repr(cur))
# NSSM AppEnvironmentExtra is NEWLINE-separated KEY=VALUE pairs
new_env = "PYTHONIOENCODING=utf-8\nKOTAK_BRIDGE_ACTIVE=YES"
r = subprocess.run([NSSM, "set", SVC, "AppEnvironmentExtra", new_env], capture_output=True, text=True)
print("set exit:", r.returncode, r.stdout.replace("\x00","").strip(), r.stderr.replace("\x00","").strip())
# verify
v = subprocess.run([NSSM, "get", SVC, "AppEnvironmentExtra"], capture_output=True, text=True).stdout
print("verify:", repr(v.replace("\x00","").strip()))
