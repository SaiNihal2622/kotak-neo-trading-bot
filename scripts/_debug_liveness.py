"""Quick interactive smoke test for the liveness monitor."""
import time
import json
import tempfile
from pathlib import Path
from kotak_bot.utils.liveness import LivenessMonitor

with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    mon = LivenessMonitor(
        ping_file=str(p / "ping.json"),
        crash_file=str(p / "crash.jsonl"),
        interval_sec=0.2,
    )
    mon.start()
    immediate = json.loads((p / "ping.json").read_text())
    print(f"IMMEDIATE: state={immediate['state']} tick={immediate['tick']}")
    for i in range(8):
        time.sleep(0.15)
        d = json.loads((p / "ping.json").read_text())
        print(f"  +{0.15*(i+1):.2f}s state={d['state']} tick={d['tick']} thread_alive={mon._thread.is_alive()}")
    mon.stop()
    print("Crash events:", (p / "crash.jsonl").read_text())
