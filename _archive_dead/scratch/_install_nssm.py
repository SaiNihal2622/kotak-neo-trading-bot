"""Install KotakCore + KotakBotAdapter as NSSM services."""
import subprocess
from pathlib import Path

ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
NSSM = r"C:\Tools\nssm\nssm-2.24\win32\nssm.exe"


def run(*args):
    print(f"$ {args[0]} {' '.join(args[1:3])[:80]}...")
    r = subprocess.run([str(NSSM)] + list(args), capture_output=True, text=True)
    if r.returncode != 0 and r.stderr:
        print(f"  stderr: {r.stderr.strip()[:200]}")
    return r.returncode == 0


# KotakCore — FastAPI event-sourced trading core
print("=== Installing KotakCore ===")
run("install", "KotakCore", str(PYTHON),
    f"-m system.core.api.server --db {ROOT}\\data_cache\\state.db --port 8510")
run("set", "KotakCore", "AppDirectory", str(ROOT))
run("set", "KotakCore", "DisplayName", "Kotak Trading Core")
run("set", "KotakCore", "Description", "FastAPI event-sourced trading core")
run("set", "KotakCore", "Start", "SERVICE_AUTO_START")
run("set", "KotakCore", "AppStdout", str(ROOT / "Logs" / "core_stdout.log"))
run("set", "KotakCore", "AppStderr", str(ROOT / "Logs" / "core_stderr.log"))
run("set", "KotakCore", "AppRotateFiles", "1")
run("set", "KotakCore", "AppRotateBytes", "10485760")
run("start", "KotakCore")

# KotakBotAdapter — legacy bot JSON → core events bridge
print()
print("=== Installing KotakBotAdapter ===")
run("install", "KotakBotAdapter", str(PYTHON),
    f"-m system.core.migration.bot_adapter --json {ROOT}\\data_cache\\paper_state.json "
    f"--db {ROOT}\\data_cache\\state.db --interval 1")
run("set", "KotakBotAdapter", "AppDirectory", str(ROOT))
run("set", "KotakBotAdapter", "DisplayName", "Kotak Bot JSON Adapter")
run("set", "KotakBotAdapter", "Description", "Bridges legacy bot JSON to core event log (Phase 2)")
run("set", "KotakBotAdapter", "Start", "SERVICE_AUTO_START")
run("set", "KotakBotAdapter", "AppStdout", str(ROOT / "Logs" / "adapter_stdout.log"))
run("set", "KotakBotAdapter", "AppStderr", str(ROOT / "Logs" / "adapter_stderr.log"))
run("set", "KotakBotAdapter", "AppRotateFiles", "1")
run("set", "KotakBotAdapter", "AppRotateBytes", "10485760")
run("start", "KotakBotAdapter")

print()
print("=== Status ===")
for svc in ["KotakCore", "KotakBotAdapter"]:
    r = subprocess.run([NSSM, "status", svc], capture_output=True, text=True)
    print(f"  {svc}: {r.stdout.strip()}")