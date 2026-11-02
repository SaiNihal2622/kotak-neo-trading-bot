import subprocess
for cmd in [["sc","stop","KotakMavisRealtime"],["sc","delete","KotakMavisRealtime"]]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(" ".join(cmd), "->", r.returncode, r.stdout.strip()[:80] or r.stderr.strip()[:80])
