"""Synthetic process ownership fixture. No service access or account state."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

role, marker = sys.argv[1:3]
if role == "grandchild":
    Path(marker).write_text(json.dumps([int(sys.argv[3]), os.getppid(), os.getpid()]))
    time.sleep(60)
elif role == "child":
    subprocess.Popen([sys.executable, "-B", __file__, "grandchild", marker, sys.argv[3]], shell=False)
    time.sleep(60)
else:
    subprocess.Popen([sys.executable, "-B", __file__, "child", marker, str(os.getpid())], shell=False)
    if role == "exit-parent":
        until = time.monotonic() + 10
        while not Path(marker).exists() and time.monotonic() < until:
            time.sleep(.01)
    else:
        time.sleep(60)
