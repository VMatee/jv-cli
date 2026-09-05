#!/usr/bin/env python3
"""Install, verify, upgrade, and safely uninstall JV CLI."""
from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from jvcli.cli import ENGINE_VERSION, VERSION
from jvcli.safety import JvError, atomic_write, no_symlink_path, private_dir

OWNED_NAMES = (".state", ".cache", "runtime", ".backups")
EXCLUDED_DIRS = {
    ".git", ".state", ".cache", "runtime", ".backups", "dist", "downloads",
    "__pycache__", ".venv", "node_modules",
}
EXCLUDED_FILES = {"MANIFEST.sha256", ".env", "credentials", "credentials.json"}
PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH"'


def check_tree(root: Path) -> Path:
    root = no_symlink_path(root)
    for name in OWNED_NAMES:
        no_symlink_path(root / name)
    return root


def idle(root: Path) -> None:
    for path in (root / ".state/runs").glob("*/session.lock"):
        path = no_symlink_path(path)
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise JvError("An active JV CLI session was detected. Exit it before updating/uninstalling") from None
        finally:
            os.close(fd)


def _excluded(relative: Path) -> bool:
    if any(part in EXCLUDED_DIRS or part.startswith("staging") for part in relative.parts[:-1]):
        return True
    name = relative.name
    return (name in EXCLUDED_FILES or name.startswith(".env.") or name.endswith((".pyc", ".pyo", ".log", ".tmp"))
            or "credential" in name.lower() or ("session" in name.lower() and "test" not in name.lower()))


def public_files(root: Path) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if not _excluded(relative):
            files.append(relative)
    return sorted(files, key=lambda p: p.as_posix())


def write_manifest(root: Path) -> int:
    entries = []
    for relative in public_files(root):
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        entries.append(f"{digest}  {relative.as_posix()}")
    atomic_write(root / "MANIFEST.sha256", "\n".join(entries) + "\n", 0o644)
    return len(entries)


def manifest(root: Path) -> dict[str, str]:
    root = no_symlink_path(root)
    entries: dict[str, str] = {}
    path = root / "MANIFEST.sha256"
    if not path.is_file() or path.is_symlink():
        raise JvError("Package manifest is missing")
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            checksum, relative = line.split("  ", 1)
        except ValueError:
            raise JvError("Invalid manifest entry") from None
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise JvError("Invalid manifest checksum")
        rel = Path(relative)
        if (not rel.parts or relative in entries or relative != rel.as_posix() or rel.is_absolute()
                or ".." in rel.parts or _excluded(rel)):
            raise JvError("Unsafe manifest path")
        target = no_symlink_path(root / rel)
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
            raise JvError(f"Package integrity check failed: {relative}")
        entries[relative] = checksum
    actual = {item.as_posix() for item in public_files(root)}
    if not entries or actual != set(entries):
        detail = sorted(actual - set(entries)) or sorted(set(entries) - actual) or ["empty manifest"]
        raise JvError(f"Package manifest file set mismatch: {detail[0]}")
    return entries


def check_prerequisites(no_engine: bool = False) -> None:
    errors = []
    if sys.platform != "linux":
        errors.append("Linux is required")
    if platform.machine().lower() not in {"x86_64", "amd64"}:
        errors.append("x86_64/amd64 is required")
    if sys.version_info < (3, 10):
        errors.append("Python 3.10 or later is required (Ubuntu: sudo apt install python3)")
    for command, package in (("curl", "curl"), ("unzip", "unzip"), ("node", "nodejs"), ("npm", "npm")):
        if not shutil.which(command):
            errors.append(f"{command} is required (Ubuntu: sudo apt install {package})")
    if shutil.which("node"):
        try:
            result = subprocess.run(["node", "-p", "process.versions.node"], capture_output=True, text=True, timeout=10)
            if result.returncode or int(result.stdout.strip().split(".")[0]) < 18:
                errors.append("Node.js 18 or later is required")
        except (OSError, ValueError, subprocess.SubprocessError):
            errors.append("Could not verify Node.js version; Node.js 18 or later is required")
    if errors:
        raise JvError("\n".join(errors) + "\nJV CLI never runs apt or sudo automatically.")


def engine_version(engine: Path, env: dict[str, str]) -> str:
    result = subprocess.run([str(engine), "--version"], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=15, env=env)
    match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][\w.-]+)?", result.stdout)
    if result.returncode or not match:
        raise JvError("The engine failed its version check")
    return match.group(0)


def _install_engine(root: Path, no_engine: bool, offline: bool) -> None:
    private_dir(root / ".state")
    cache = private_dir(root / ".cache")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "USER", "LOGNAME", "SHELL")}
    env.update(HOME=str(private_dir(cache / "install-home")), CODEX_HOME=str(private_dir(cache / "engine-check")),
               TMPDIR=str(private_dir(cache / "tmp")), XDG_CACHE_HOME=str(cache),
               NPM_CONFIG_CACHE=str(private_dir(cache / "npm")), NPM_CONFIG_UPDATE_NOTIFIER="false",
               NPM_CONFIG_USERCONFIG=str(cache / "npmrc"), NPM_CONFIG_GLOBALCONFIG=str(cache / "global-npmrc"))
    for name in ("npmrc", "global-npmrc"):
        atomic_write(cache / name, "")
    lock_fd = os.open(root / ".state/install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        idle(root)
        if no_engine:
            return
        engine = root / "runtime/node_modules/.bin/codex"
        version = None
        if engine.is_file() and os.access(engine, os.X_OK):
            try:
                version = engine_version(engine, env)
            except (JvError, subprocess.SubprocessError):
                pass
        if version == ENGINE_VERSION:
            print(f"Pinned engine {ENGINE_VERSION} is already installed; no download needed")
            return
        stage = Path(tempfile.mkdtemp(prefix="engine-stage-", dir=cache))
        backup = cache / ("runtime-backup-" + uuid.uuid4().hex)
        try:
            (stage / "package.json").write_text(json.dumps({"name": "jvcli-local-engine", "private": True,
                                                "dependencies": {"@openai/codex": ENGINE_VERSION}}) + "\n")
            print(f"Installing pinned engine {ENGINE_VERSION} inside {root / 'runtime'}", flush=True)
            command = ["npm", "install", "--prefix", str(stage), "--ignore-scripts", "--no-audit", "--no-fund"]
            if offline:
                command.append("--offline")
            result = subprocess.run(command, env=env, cwd=stage, timeout=600)
            if result.returncode:
                raise JvError("Local engine installation failed. The previous runtime was preserved")
            candidate = stage / "node_modules/.bin/codex"
            if engine_version(candidate, env) != ENGINE_VERSION:
                raise JvError("Downloaded engine version does not match the pin")
            for args in (["exec", "--help"], ["exec", "resume", "--help"]):
                result = subprocess.run([str(candidate), *args], env=env, capture_output=True, text=True, timeout=15)
                if result.returncode or "--json" not in result.stdout:
                    raise JvError("Downloaded engine CLI contract check failed")
            runtime = root / "runtime"
            if runtime.exists():
                os.replace(runtime, backup)
            try:
                os.replace(stage, runtime)
            except BaseException:
                if backup.exists():
                    os.replace(backup, runtime)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    finally:
        os.close(lock_fd)


def _copy_release(source: Path, destination: Path) -> None:
    entries = manifest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if (destination / "lib/jvcli/cli.py").is_file():
            upgrade(source, destination)
            return
        children = list(destination.iterdir())
        if any(child.name != ".state" for child in children):
            raise JvError(f"Refusing to install over an unrecognized directory: {destination}")
    stage = Path(tempfile.mkdtemp(prefix=".jv-cli-install-", dir=destination.parent))
    moved_state = False
    try:
        for name in [*entries, "MANIFEST.sha256"]:
            src, dst = source / name, stage / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        if destination.exists():
            state = destination / ".state"
            if state.exists():
                os.replace(state, stage / ".state")
                moved_state = True
            destination.rmdir()
        try:
            os.replace(stage, destination)
        except BaseException:
            if moved_state:
                destination.mkdir(mode=0o700)
                os.replace(stage / ".state", destination / ".state")
            raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _install_launcher(root: Path, home: Path) -> Path:
    bin_dir = no_symlink_path(home / ".local/bin")
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "jvcli"
    if launcher.exists() and not launcher.is_symlink():
        raise JvError(f"Refusing to replace an existing non-symlink launcher: {launcher}")
    temp = bin_dir / (".jvcli-link-" + uuid.uuid4().hex)
    temp.symlink_to(root / "bin/jvcli")
    os.replace(temp, launcher)
    return launcher


def _path_notice(home: Path, add_path: bool) -> None:
    local_bin = home / ".local/bin"
    path_entries = [Path(p).expanduser() for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if local_bin in path_entries:
        return
    if not add_path:
        print(f'\n{local_bin} is not in PATH. Add it for this shell with:\n  export PATH="$HOME/.local/bin:$PATH"')
        print("Re-run ./install.sh --add-path only if you want JV CLI to add this line to ~/.bashrc.")
        return
    bashrc = no_symlink_path(home / ".bashrc")
    existing = bashrc.read_text(encoding="utf-8") if bashrc.exists() else ""
    if PATH_LINE not in existing.splitlines():
        separator = "" if not existing or existing.endswith("\n") else "\n"
        atomic_write(bashrc, existing + separator + "\n# Added by JV CLI (requested with --add-path)\n" + PATH_LINE + "\n", 0o644)
        print(f"Added JV CLI PATH entry to {bashrc}; open a new shell or source it explicitly.")


def install(source: Path, no_engine: bool = False, offline: bool = False, *, portable: bool = False,
            add_path: bool = False, home: Path | None = None) -> int:
    if os.geteuid() == 0:
        raise JvError("Do not install with sudo or as root. Run ./install.sh as your normal Ubuntu user")
    check_prerequisites(no_engine)
    source = check_tree(source)
    home = no_symlink_path(home or Path.home())
    if portable:
        root = source
    else:
        root = no_symlink_path(home / ".local/share/jv-cli")
        if source != root:
            _copy_release(source, root)
    _install_engine(root, no_engine, offline)
    for path in [root / "jvcli", root / "bin/jvcli", *root.glob("*.sh"), *root.glob("scripts/*.sh")]:
        if path.exists():
            path.chmod(0o755)
    if portable:
        print(f"\nJV CLI {VERSION} portable setup complete.\nRoot: {root}")
        print(f"Run directly: \"{root / 'jvcli'}\" doctor\nOr: source \"{root / 'activate.sh'}\"")
    else:
        launcher = _install_launcher(root, home)
        print(f"\nJV CLI {VERSION} installed for this user.\nRoot: {root}\nLauncher: {launcher}")
        _path_notice(home, add_path)
        print("Run: jvcli doctor\nThen: jvcli login")
    if no_engine:
        print("Engine setup skipped. Coding sessions require the pinned engine before use.")
    return 0


def upgrade(source: Path, destination: Path) -> int:
    source = check_tree(source)
    destination = check_tree(destination)
    if source == destination:
        raise JvError("Extract the new ZIP in a separate folder before upgrading")
    if not (destination / "lib/jvcli/cli.py").is_file():
        raise JvError("Destination is not an existing JV CLI installation")
    entries = manifest(source)
    private_dir(destination / ".state")
    fd = os.open(destination / ".state/install.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        idle(destination)
        backup = private_dir(destination / ".backups" / ("source-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]))
        changed = []
        try:
            for name in [*entries, "MANIFEST.sha256"]:
                src, dst = source / name, no_symlink_path(destination / name)
                old = None
                if dst.exists():
                    if not dst.is_file():
                        raise JvError("A destination source path is not a regular file")
                    old = backup / name
                    old.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, old)
                changed.append((dst, old))
                dst.parent.mkdir(parents=True, exist_ok=True)
                temp = dst.with_name(".jv-upgrade-" + uuid.uuid4().hex)
                try:
                    shutil.copy2(src, temp)
                    os.replace(temp, dst)
                finally:
                    temp.unlink(missing_ok=True)
        except BaseException:
            for dst, old in reversed(changed):
                if old:
                    shutil.copy2(old, dst)
                else:
                    dst.unlink(missing_ok=True)
            raise
        print(f"Upgraded source to {VERSION}. Runtime, account settings, sessions and caches were preserved.\nPrevious source backup: {backup}\nRun: \"{destination / 'install.sh'}\"")
        return 0
    finally:
        os.close(fd)


def uninstall(home: Path | None = None, *, keep_state: bool = False, yes: bool = False) -> int:
    home = no_symlink_path(home or Path.home())
    root = no_symlink_path(home / ".local/share/jv-cli")
    launcher = home / ".local/bin/jvcli"
    if not root.exists():
        raise JvError(f"JV CLI user installation was not found at {root}")
    if not (root / "lib/jvcli/cli.py").is_file() or not (root / "VERSION").is_file():
        raise JvError(f"Refusing to remove an unrecognized directory: {root}")
    if launcher.is_symlink() or launcher.exists():
        if not launcher.is_symlink() or launcher.resolve() != (root / "bin/jvcli").resolve():
            raise JvError(f"Refusing to remove an unexpected launcher: {launcher}")
    idle(root)
    print(f"WARNING: uninstall will remove JV CLI runtime, caches, and source under {root}.")
    print("Your projects are never removed. Local account/session state will be preserved." if keep_state else
          "Local account settings and saved sessions will also be removed.")
    if not yes:
        if not sys.stdin.isatty() or input("Type REMOVE to continue: ").strip() != "REMOVE":
            raise JvError("Uninstall cancelled; use --yes only after reviewing the warning")
    saved_state = None
    if keep_state and (root / ".state").exists():
        saved_state = root.parent / (".jv-cli-state-" + uuid.uuid4().hex)
        os.replace(root / ".state", saved_state)
    if launcher.is_symlink():
        launcher.unlink()
    shutil.rmtree(root)
    if saved_state:
        root.mkdir(mode=0o700)
        os.replace(saved_state, root / ".state")
        print(f"JV CLI removed; state preserved at {root / '.state'}")
    else:
        print("JV CLI user installation removed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    setup = subs.add_parser("install")
    setup.add_argument("--no-engine", action="store_true")
    setup.add_argument("--offline", action="store_true")
    setup.add_argument("--portable", action="store_true")
    setup.add_argument("--add-path", action="store_true")
    up = subs.add_parser("upgrade")
    up.add_argument("destination", type=Path, nargs="?", default=Path.home() / ".local/share/jv-cli")
    remove = subs.add_parser("uninstall")
    remove.add_argument("--keep-state", action="store_true")
    remove.add_argument("--yes", action="store_true")
    subs.add_parser("verify")
    args = parser.parse_args()
    try:
        if args.action == "install":
            if args.portable and args.add_path:
                raise JvError("--add-path is not used in portable mode")
            return install(ROOT, args.no_engine, args.offline, portable=args.portable, add_path=args.add_path)
        if args.action == "upgrade":
            return upgrade(ROOT, args.destination)
        if args.action == "uninstall":
            return uninstall(keep_state=args.keep_state, yes=args.yes)
        count = len(manifest(ROOT))
        print(f"Package integrity verified: {count} source/documentation files")
        return 0
    except (JvError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
