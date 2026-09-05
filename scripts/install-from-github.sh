#!/bin/sh
set -eu

REPOSITORY=VMatee/jv-cli

verify_only() {
    [ "$#" -eq 2 ] || { echo "Usage: $0 --verify-only ARCHIVE CHECKSUM" >&2; exit 2; }
    archive=$1
    checksum=$2
    [ -f "$archive" ] && [ -f "$checksum" ] || { echo 'Archive or checksum file is missing.' >&2; exit 1; }
    expected=$(awk 'NR == 1 { print $1 }' "$checksum")
    printf '%s\n' "$expected" | grep -Eq '^[0-9a-f]{64}$' ||
        { echo 'Invalid checksum file.' >&2; exit 1; }
    actual=$(sha256sum "$archive" | awk '{print $1}')
    [ "$actual" = "$expected" ] || { echo 'Checksum verification failed; nothing was extracted or executed.' >&2; exit 1; }
    echo 'Checksum verified.'
}

if [ "${1:-}" = "--verify-only" ]; then
    shift
    verify_only "$@"
    exit
fi
[ "$#" -eq 0 ] || { echo "Usage: $0" >&2; exit 2; }
[ "$(uname -s)" = Linux ] || { echo 'JV CLI release installation currently supports Linux only.' >&2; exit 1; }
case "$(uname -m)" in x86_64|amd64) ;; *) echo 'JV CLI release installation currently supports x86_64/amd64 only.' >&2; exit 1;; esac
for command in python3 curl unzip sha256sum; do
    command -v "$command" >/dev/null 2>&1 || {
        echo "Missing prerequisite: $command. Ubuntu: sudo apt install python3 curl unzip coreutils" >&2
        exit 1
    }
done
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' ||
    { echo 'Python 3.10 or later is required.' >&2; exit 1; }

temporary=$(mktemp -d "${TMPDIR:-/tmp}/jv-cli-bootstrap.XXXXXX")
cleanup() { rm -rf -- "$temporary"; }
trap cleanup EXIT HUP INT TERM
api="https://api.github.com/repos/$REPOSITORY/releases/latest"
metadata="$temporary/release.json"
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location "$api" -o "$metadata"
tag=$(python3 -B -c 'import json,re,sys; value=json.load(open(sys.argv[1], encoding="utf-8")).get("tag_name",""); print(value) if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z.-]+)?",value) else sys.exit(1)' "$metadata") ||
    { echo 'Latest GitHub release has an invalid or missing version tag.' >&2; exit 1; }
version=${tag#v}
archive_name="jv-cli-$version-linux-x86_64.zip"
checksum_name="$archive_name.sha256"
base="https://github.com/$REPOSITORY/releases/download/$tag"
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location "$base/$archive_name" -o "$temporary/$archive_name"
curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location "$base/$checksum_name" -o "$temporary/$checksum_name"
verify_only "$temporary/$archive_name" "$temporary/$checksum_name"
mkdir "$temporary/extracted"
unzip -q "$temporary/$archive_name" -d "$temporary/extracted"
[ -f "$temporary/extracted/jv-cli/install.sh" ] || { echo 'Release archive layout is invalid.' >&2; exit 1; }
(cd "$temporary/extracted/jv-cli" && ./verify.sh && ./install.sh)
