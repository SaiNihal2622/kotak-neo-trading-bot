import subprocess, time
subprocess.run(["sc","stop","KotakBrainBridge"], capture_output=True, text=True)
time.sleep(5)
subprocess.run(["sc","start","KotakBrainBridge"], capture_output=True, text=True)
