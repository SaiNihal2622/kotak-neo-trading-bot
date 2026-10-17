"""Register the health monitor as its own NSSM service (runs as LocalSystem).

Runs scripts/health_monitor.py in --loop mode (every 15 min), independent of
the brain's in-process scheduler so health checks can't be lost to a stale
brain process. Also removes the brain-scheduler dependency by keeping this as
the single authoritative health cadence.
"""
import subprocess
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
REPO = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
PY = REPO + r"\.venv\Scripts\python.exe"
SVC = "KotakHealthMonitor"

# remove if exists
subprocess.run([NSSM, "stop", SVC], capture_output=True, text=True)
subprocess.run([NSSM, "remove", SVC, "confirm"], capture_output=True, text=True)

# install
r = subprocess.run([NSSM, "install", SVC, PY, "-u", REPO + r"\scripts\health_monitor.py", "--interval=900"],
                   capture_output=True, text=True)
print("install exit:", r.returncode, r.stdout.replace("\x00","").strip())

subprocess.run([NSSM, "set", SVC, "AppDirectory", REPO], capture_output=True, text=True)
subprocess.run([NSSM, "set", SVC, "AppStdout", REPO + r"\Logs\health_monitor_stdout.log"], capture_output=True, text=True)
subprocess.run([NSSM, "set", SVC, "AppStderr", REPO + r"\Logs\health_monitor_stderr.log"], capture_output=True, text=True)
subprocess.run([NSSM, "set", SVC, "AppRotateFiles", "1"], capture_output=True, text=True)
subprocess.run([NSSM, "set", SVC, "AppRotateBytes", "10485760"], capture_output=True, text=True)
# AUTO_START so it comes up on reboot
subprocess.run(["sc", "config", SVC, "start=", "auto"], capture_output=True, text=True)

# start
r = subprocess.run([NSSM, "start", SVC], capture_output=True, text=True)
print("start exit:", r.returncode, r.stdout.replace("\x00","").strip())