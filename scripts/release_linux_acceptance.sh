#!/bin/bash
set -euo pipefail
version=$(cat VERSION)
(
  cd dist
  sha256sum -c "jv-cli-$version-linux-x86_64.zip.sha256"
  sha256sum -c "jv-cli-$version-linux-x86_64-offline.zip.sha256"
)
directory=$(mktemp -d)
trap 'rm -rf -- "$directory"' EXIT
unzip -q "dist/jv-cli-$version-linux-x86_64.zip" -d "$directory/normal"
"$directory/normal/jv-cli/verify.sh"
mkdir -p "$directory/home" "$directory/no-downloads"
unzip -q "dist/jv-cli-$version-linux-x86_64-offline.zip" -d "$directory/offline"
"$directory/offline/jv-cli/verify.sh"
for command in node npm curl; do
  printf '#!/bin/sh\nexit 97\n' > "$directory/no-downloads/$command"
  chmod +x "$directory/no-downloads/$command"
done
HOME="$directory/home" PATH="$directory/no-downloads:$PATH" "$directory/offline/jv-cli/install-offline.sh"
HOME="$directory/home" PATH="$directory/no-downloads:$PATH" "$directory/home/.local/bin/jvcli" doctor
HOME="$directory/home" PATH="$directory/no-downloads:$PATH" python3 -B "$directory/home/.local/share/jv-cli/scripts/engine_smoke.py"
