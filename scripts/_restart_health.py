import subprocess, time
subprocess.run(["sc","stop","KotakHealthMonitor"], capture_output=True, text=True)
time.sleep(5)
subprocess.run(["sc","start","KotakHealthMonitor"], capture_output=True, text=True)
