"""Check process."""
import psutil
p = psutil.Process(18300)
print(f"PID 18300: status={p.status()}, cpu={p.cpu_percent(interval=1):.1f}%, memory={p.memory_info().rss / 1024 / 1024:.0f}MB")
print(f"Cmdline: {' '.join(p.cmdline())[:200]}")