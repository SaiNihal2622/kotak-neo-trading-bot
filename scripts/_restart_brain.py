import subprocess, time
subprocess.run(["sc","stop","KotakQuantService"], capture_output=True, text=True)
time.sleep(5)
subprocess.run(["sc","start","KotakQuantService"], capture_output=True, text=True)
