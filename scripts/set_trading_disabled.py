"""Set KOTAK_BOT_TRADING_DISABLED=YES on KotakBotPaper NSSM env (runs as LocalSystem).

The guard in paper_client._save_state() checks this env var, but it was only
set INSIDE the bridge-active block (may not run before the first _save_state).
Setting it in the NSSM env makes it always active so the bot can never write
paper_state.json (the gateway is the sole writer).
"""
import subprocess
NSSM = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
SVC = "KotakBotPaper"
new_env = "PYTHONIOENCODING=utf-8\nKOTAK_BRIDGE_ACTIVE=YES\nKOTAK_BOT_TRADING_DISABLED=YES"
r = subprocess.run([NSSM, "set", SVC, "AppEnvironmentExtra", new_env], capture_output=True, text=True)
print("set exit:", r.returncode, r.stdout.replace("\x00","").strip(), r.stderr.replace("\x00","").strip())
v = subprocess.run([NSSM, "get", SVC, "AppEnvironmentExtra"], capture_output=True, text=True).stdout
print("verify:", repr(v.replace("\x00","").strip()))
