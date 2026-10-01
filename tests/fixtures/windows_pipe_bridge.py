"""Offline transport-only shared bridge harness, never a production entrypoint."""
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli import bridge


def forbidden_client(*args):
    raise AssertionError("Transport fixture must never authenticate")


if __name__ == "__main__":
    # Workspace containment is a separate unfinished gate. This fixture only
    # exercises shared framing/dispatch/shutdown over actual inherited stdio.
    with patch.object(bridge.cli, '_workspace_check', return_value=Path.cwd()):
        raise SystemExit(bridge.serve(client_factory=forbidden_client))
