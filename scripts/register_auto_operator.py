"""Register the Autonomous Operator as a live NSSM service (runs as LocalSystem)."""
import subprocess
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
REPO = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
PY = REPO + r"\.venv\Scripts\python.exe"
SVC = "KotakAutoOperator"

subprocess.run([NSSM, "stop", SVC], capture_output=True, text=True)
subprocess.run([NSSM, "remove", SVC, "confirm"], capture_output=True, text=True)

r = subprocess.run([NSSM, "install", SVC, PY, "-u", REPO + r"\scripts\autonomous_operator.py"],
                   capture_output=True, text=True)
print("install exit:", r.returncode)
subprocess.run([NSSM, "set", SVC, "AppDirectory", REPO], capture_output=True, text=True)
subprocess.run([NSSM, "set", SVC, "AppStdout", REPO + r"\Logs\auto_operator_stdout.log"], capture_output=True, text=True)
subprocess.run([NSSM, "set", SVC, "AppStderr", REPO + r"\Logs\auto_operator_stderr.log"], capture_output=True, text=True)
subprocess.run([NSSM, "set", SVC, "AppEnvironmentExtra",
                "PYTHONIOENCODING=utf-8\nOP_INTERVAL_SEC=300\nKOTAK_CORE_URL=http://127.0.0.1:8510"], capture_output=True, text=True)
subprocess.run(["sc", "config", SVC, "start=", "auto"], capture_output=True, text=True)
r = subprocess.run([NSSM, "start", SVC], capture_output=True, text=True)
print("start exit:", r.returncode, r.stdout.replace("\x00","").strip())
