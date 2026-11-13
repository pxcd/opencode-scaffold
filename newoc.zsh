# OpenCode scaffold; user-editable template lives beside this helper.
# Capture the directory while sourcing, before newoc changes the working directory.
typeset -g _NEWOC_SOURCE_DIR="${${(%):-%x}:A:h}"
newoc() {
  local newoc_template_dir="${NEWOC_TEMPLATE_DIR:-$_NEWOC_SOURCE_DIR}"
  if [[ "${1-}" == --help || "${1-}" == -h ]]; then
    python3.12 "$newoc_template_dir/newoc.py" "$@"
    return
  fi
  local newoc_destination
  newoc_destination="$(python3.12 "$newoc_template_dir/newoc.py" "$@")" || return
  [[ -n "$newoc_destination" ]] && builtin cd -- "$newoc_destination"
}
