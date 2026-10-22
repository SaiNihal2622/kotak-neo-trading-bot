import subprocess, time
subprocess.run(["sc","stop","KotakCoreAPI"], capture_output=True, text=True)
time.sleep(5)
subprocess.run(["sc","start","KotakCoreAPI"], capture_output=True, text=True)
