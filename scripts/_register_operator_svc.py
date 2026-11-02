import subprocess, pathlib
ROOT = pathlib.Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
SVC = "KotakOperator"
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
SCRIPT = str(ROOT / "scripts" / "kotak_operator.py")

def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, (r.stdout or r.stderr).strip()

run([NSSM, "remove", SVC, "confirm"])
rc, out = run([NSSM, "install", SVC, PY, "-u", SCRIPT])
print("install:", rc, out[:60])
run([NSSM, "set", SVC, "AppDirectory", str(ROOT)])
run([NSSM, "set", SVC, "AppStdout", str(ROOT / "Logs" / "kotak_operator.out.log")])
run([NSSM, "set", SVC, "AppStderr", str(ROOT / "Logs" / "kotak_operator.err.log")])
run([NSSM, "set", SVC, "Start", "SERVICE_AUTO_START"])
rc, out = run([NSSM, "get", SVC, "Application"])
print("verify:", rc, out[:60])
print("DONE")
