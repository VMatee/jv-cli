# Bash: source /path/to/jv-cli/activate.sh
# No profile edits and no global files. A new terminal requires activation again.
if [ -z "${BASH_VERSION:-}" ]; then
  printf '%s\n' 'Use Bash to source activate.sh, or call /path/to/jv-cli/jvcli directly.' >&2
  return 1 2>/dev/null || exit 1
fi
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  printf '%s\n' 'Run: source ./activate.sh (not ./activate.sh)' >&2
  exit 1
fi
_jv_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ -n "${_JVCLI_ACTIVE_ROOT:-}" ] && [ "$_JVCLI_ACTIVE_ROOT" != "$_jv_root" ]; then
  printf '%s\n' 'Another JV CLI folder was activated in this shell. Open a new terminal to avoid a stale PATH.' >&2
  unset _jv_root
  return 1
fi
if [ -z "${_JVCLI_ACTIVE_ROOT:-}" ]; then
  _JVCLI_OLD_PATH=$PATH
  _JVCLI_ACTIVE_ROOT=$_jv_root
  export PATH="$_jv_root:$PATH"
fi
jvcli_deactivate() {
  if [ -n "${_JVCLI_OLD_PATH+x}" ]; then
    export PATH="$_JVCLI_OLD_PATH"
  fi
  unset _JVCLI_OLD_PATH _JVCLI_ACTIVE_ROOT
  unset -f jvcli_deactivate
  hash -r
}
hash -r
printf 'JV CLI active for this terminal: %s\n' "$_jv_root"
printf '%s\n' 'To deactivate: jvcli_deactivate'
unset _jv_root
