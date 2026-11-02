"""Debug what python cmdlines the orphan killer sees."""
import subprocess
ps_cmd = (
    "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" "
    "| Select-Object ProcessId,CommandLine "
    "| ConvertTo-Csv -NoTypeInformation"
)
r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=20)
print("RC:", r.returncode)
import csv, io
reader = csv.DictReader(io.StringIO(r.stdout))
for row in reader:
    pid = row.get("ProcessId", "").strip()
    cmd = (row.get("CommandLine") or "").strip()
    print(f"PID {pid}: {cmd[:200]}")
