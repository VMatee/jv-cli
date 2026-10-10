"""Private disposable state for shared structured-transport tests."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile

from jvcli.safety import private_dir


@contextmanager
def private_state():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='staging-image-tests-', dir=root) as temporary:
        if os.name == 'nt':
            from windows_test_support import trusted_fixture_directory
            trusted_fixture_directory(temporary)
        yield private_dir(Path(temporary) / 'state')
