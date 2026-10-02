#!/usr/bin/env python3
"""Current native Windows gate: shared contracts and native platform primitives.

This is not engine, bridge execution, or installed-package acceptance.
"""
import os
import sys
import unittest

import windows_preflight


class NativeResult(unittest.TextTestResult):
    def _annotation(self, test, err):
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # Expose the failing test and exception through the public Checks API
            # when downloading hosted job logs requires separate authentication.
            message = f"{test.id()}: {err[0].__name__}: {err[1]}"
            message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::error::{message}", flush=True)

    def addError(self, test, err):
        super().addError(test, err)
        self._annotation(test, err)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._annotation(test, err)


def main():
    if os.name != "nt" or sys.platform != "win32":
        raise SystemExit("Run this gate on native Windows")
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        (*windows_preflight.SHARED_TESTS, "test_windows_native", "test_windows_execution",
         "test_windows_pipes", "test_windows_auth", "test_windows_grammar", "test_windows_journal", "test_execution_policy", "test_windows_packaging"))
    result = unittest.TextTestRunner(verbosity=2, resultclass=NativeResult).run(suite)
    if not result.wasSuccessful() or result.skipped:
        return 1
    print(f"{result.testsRun} shared/native storage, execution and pipe primitive tests passed. "
          "Engine, bridge execution, and installed-package acceptance remain pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
