import subprocess, pathlib, sys
ROOT = pathlib.Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
SVC = "KotakOperator"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
SCRIPT = str(ROOT / "scripts" / "kotak_operator.py")

def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, (r.stdout or r.stderr).strip()

# Remove if exists
rc, out = run([NSSM, "remove", SVC, "confirm"])
print("remove:", rc, out[:80])

# Install
rc, out = run([NSSM, "install", SVC, PY, "-u", SCRIPT])
print("install:", rc, out[:80])

# Set app directory
rc, out = run([NSSM, "set", SVC, "AppDirectory", str(ROOT)])
print("appdir:", rc, out[:80])

# Set stdout/stderr logs
rc, out = run([NSSM, "set", SVC, "AppStdout", str(ROOT / "Logs" / "kotak_operator.out.log")])
print("stdout:", rc, out[:80])
rc, out = run([NSSM, "set", SVC, "AppStderr", str(ROOT / "Logs" / "kotak_operator.err.log")])
print("stderr:", rc, out[:80])

# Auto start
rc, out = run([NSSM, "set", SVC, "Start", "SERVICE_AUTO_START"])
print("start:", rc, out[:80])

print("DONE - service registered:", SVC)
