"""Offline auth/lifecycle fixture; workspace readiness remains test-only."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lib'))
from jvcli import bridge

if __name__ == '__main__':
    with patch.object(bridge.cli, '_workspace_check', return_value=Path.cwd()), patch.object(bridge, 'AUTH_TIMEOUT', .6):
        raise SystemExit(bridge.serve())
