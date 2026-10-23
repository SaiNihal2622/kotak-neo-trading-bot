import subprocess, time
# Disable the brain service so it stays stopped (NSSM won't auto-restart it)
subprocess.run(["sc","config","KotakQuantService","start=","disabled"], capture_output=True, text=True)
time.sleep(2)
subprocess.run(["sc","stop","KotakQuantService"], capture_output=True, text=True)
time.sleep(5)
# Ensure the operator is running
subprocess.run(["sc","start","KotakOperator"], capture_output=True, text=True)
