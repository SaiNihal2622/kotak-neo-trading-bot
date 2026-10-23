"""Check new bot process."""
import psutil
p = psutil.Process(1736)
print(f"PID 1736: status={p.status()}, memory={p.memory_info().rss / 1024 / 1024:.0f}MB")
print(f"Cmdline: {' '.join(p.cmdline())[:300]}")