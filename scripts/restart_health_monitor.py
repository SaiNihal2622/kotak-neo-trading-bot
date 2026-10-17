"""Restart the KotakHealthMonitor NSSM service (runs as LocalSystem)."""
import subprocess
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
SVC = "KotakHealthMonitor"
# stop then start (reliable sequence)
subprocess.run([NSSM, "stop", SVC], capture_output=True, text=True)
import time
time.sleep(2)
r = subprocess.run([NSSM, "start", SVC], capture_output=True, text=True)
print("start exit:", r.returncode, r.stdout.replace("\x00","").strip(), r.stderr.replace("\x00","").strip())
