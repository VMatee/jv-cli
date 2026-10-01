#!/usr/bin/env python3
"""Offline imports, syntax and shared tests; NOT Windows native acceptance.

Runs on Linux too. No installer, engine download, login, or real JV job is run.
The explicit subset leaves OS-dependent acceptance visible in the handoff.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

# Entire selected modules/classes run: no per-test silent Windows skip policy.
SHARED_TESTS = (
    "test_platform_contracts",
    "test_protocol_hardening.ProtocolHardening",
    "test_terminal_output",
    "test_rendered_protocol",
)


def main():
    compiled = 0
    for directory in ("lib", "scripts", "tests"):
        for file in sorted((ROOT / directory).rglob("*.py")):
            if "__pycache__" in file.parts:
                continue
            compile(file.read_text(encoding="utf-8"), str(file), "exec")
            compiled += 1
    for file in sorted((ROOT / "lib/jvcli").rglob("*.py")):
        relative = file.relative_to(ROOT / "lib").with_suffix("")
        parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
        name = ".".join(parts)
        if name == "jvcli.platform.posix" and os.name == "nt":
            continue  # This module deliberately implements only the POSIX OS.
        if name == "jvcli.platform._windows_fs" and os.name != "nt":
            continue  # Real Windows API bindings; public backend remains importable.
        importlib.import_module(name)
    importlib.import_module("manage")
    importlib.import_module("build_release")
    importlib.import_module("build_offline_release")
    if os.name == "nt":
        forbidden = {"fcntl", "termios", "tty"} & sys.modules.keys()
        if forbidden:
            raise RuntimeError("Windows imported POSIX-only modules: " + ", ".join(sorted(forbidden)))
    subprocess.run([sys.executable, "-B", str(ROOT / "bin/jvcli"), "--version"],
                   check=True, timeout=10)
    print(f"Compiled {compiled} Python files; shared modules and package helpers import", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(SHARED_TESTS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:
        print("Preflight must pass with zero skipped selected tests", file=sys.stderr)
        return 1
    print(f"{result.testsRun} preparatory/shared tests passed on {sys.platform}. "
          "Native Windows execution/security/package acceptance remains pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
