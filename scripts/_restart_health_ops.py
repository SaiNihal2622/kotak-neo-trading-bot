import subprocess, time
for svc in ["KotakHealthMonitor","KotakAutoOperator"]:
    subprocess.run(["sc","stop",svc], capture_output=True, text=True)
    time.sleep(4)
    subprocess.run(["sc","start",svc], capture_output=True, text=True)
