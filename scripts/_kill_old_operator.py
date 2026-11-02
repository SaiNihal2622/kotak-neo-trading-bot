import subprocess, time
# Kill the old operator process (PID 7884) running pre-cooldown code
for pid in ["7884"]:
    r = subprocess.run(["taskkill","/PID",pid,"/F","/T"],capture_output=True,text=True)
    print(f"kill {pid}:", r.stdout.strip() or r.stderr.strip()[:80])
time.sleep(2)
# verify
r = subprocess.run(["powershell","-Command","Get-CimInstance Win32_Process -Filter \"ProcessId=7884\" | Measure-Object | Select-Object -ExpandProperty Count"],capture_output=True,text=True)
print("PID 7884 alive:", r.stdout.strip())
