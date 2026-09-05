#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
command -v python3 >/dev/null 2>&1 || { echo 'Python 3.10 or later is required.' >&2; exit 1; }
exec python3 -B "$ROOT/scripts/build_release.py"
