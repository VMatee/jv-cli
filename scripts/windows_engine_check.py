#!/usr/bin/env python3
"""Native pinned-engine discovery/version gate; no model, auth or tool execution."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import cli
from jvcli.platform import windows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Native Windows required")
    with tempfile.TemporaryDirectory(prefix="staging-engine-check-", dir=ROOT) as temp:
        state = Path(temp) / "state"
        with patch.object(cli, "STATE_DIR", state):
            engine = windows.find_engine(ROOT / "runtime", args.engine)
            assert cli._version_of_engine(engine) == cli.ENGINE_VERSION
    print("2 pinned-engine checks passed: native package/AMD64 layout and owned isolated --version.")
    print("No model requests. Sandbox, tool isolation, bridge and package acceptance remain pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
