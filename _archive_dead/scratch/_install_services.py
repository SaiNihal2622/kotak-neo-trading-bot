"""Install KotakCore + KotakBotAdapter as Windows services via sc.exe."""
import subprocess
from pathlib import Path

ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
SC = r"C:\Windows\System32\sc.exe"


def run(label, *args):
    print(f"$ {label}: {args[1] if len(args) > 1 else ''}")
    r = subprocess.run([str(SC)] + list(args), capture_output=True, text=True, timeout=10)
    out = (r.stdout + r.stderr).strip()
    if out:
        print(f"  -> {out[:200]}")
    return r.returncode == 0


# Use sc.exe to create the services
core_cmd = [str(PYTHON), "-m", "system.core.api.server",
           f"--db", str(ROOT / "data_cache" / "state.db"),
           "--port", "8510"]

adapter_cmd = [str(PYTHON), "-m", "system.core.migration.bot_adapter",
               "--json", str(ROOT / "data_cache" / "paper_state.json"),
               "--db", str(ROOT / "data_cache" / "state.db"),
               "--interval", "1"]


# First, remove if they exist
for name in ["KotakCore", "KotakBotAdapter"]:
    subprocess.run([SC, "stop", name], capture_output=True, timeout=5)
    subprocess.run([SC, "delete", name], capture_output=True, timeout=5)

# Create KotakCore
print("\n=== Creating KotakCore ===")
run("create",
    "KotakCore", "binPath=", " ".join(f'"{c}"' if " " in c else c for c in core_cmd),
    "start=", "auto",
    "DisplayName=", "Kotak Trading Core",
)

# Create KotakBotAdapter
print("\n=== Creating KotakBotAdapter ===")
run("create",
    "KotakBotAdapter", "binPath=", " ".join(f'"{c}"' if " " in c else c for c in adapter_cmd),
    "start=", "auto",
    "DisplayName=", "Kotak Bot JSON Adapter",
)

print("\n=== Final status ===")
for name in ["KotakCore", "KotakBotAdapter"]:
    r = subprocess.run([SC, "query", name], capture_output=True, text=True, timeout=5)
    print(f"\n{name}:")
    for line in r.stdout.strip().split("\n"):
        print(f"  {line}")