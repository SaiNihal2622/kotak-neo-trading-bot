"""Debug orphan killer detection."""
import psutil
import os

# Check what python processes exist and what cmdlines we can read
print("=== All python processes visible to user context ===")
for p in psutil.process_iter(['pid', 'name']):
    if 'python' in (p.info.get('name') or '').lower():
        try:
            cmdline = p.cmdline()
            print(f"PID {p.pid}: {p.info['name']} | {len(cmdline)} cmdline args")
            if cmdline:
                print(f"  first 5 args: {cmdline[:5]}")
        except psutil.AccessDenied:
            print(f"PID {p.pid}: {p.info['name']} | ACCESS DENIED")
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            print(f"PID {p.pid}: {p.info['name']} | ERROR: {e}")

print()
print("=== Check PID 4132 (expected canonical) ===")
try:
    p = psutil.Process(4132)
    print(f"  cmdline: {p.cmdline()}")
    print(f"  cmdline joined: {' '.join(p.cmdline())}")
except Exception as e:
    print(f"  error: {e}")
