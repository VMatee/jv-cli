#!/usr/bin/env python3
"""Current native Windows gate: shared contracts, private NTFS state, kernel locks.

This is not engine, bridge execution, or installed-package acceptance.
"""
import os
import sys
import unittest

import windows_preflight


def main():
    if os.name != "nt" or sys.platform != "win32":
        raise SystemExit("Run this gate on native Windows")
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        (*windows_preflight.SHARED_TESTS, "test_windows_native", "test_windows_execution"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:
        return 1
    print(f"{result.testsRun} shared/native storage and execution primitive tests passed. "
          "Engine, bridge execution, and installed-package acceptance remain pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
