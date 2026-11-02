import subprocess
r=subprocess.run(['sc','start','KotakOperator'],capture_output=True,text=True)
print(r.stdout or r.stderr)
