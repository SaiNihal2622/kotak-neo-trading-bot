import subprocess, time
subprocess.run(["sc","stop","KotakDashboard"], capture_output=True, text=True)
time.sleep(5)
subprocess.run(["sc","start","KotakDashboard"], capture_output=True, text=True)
