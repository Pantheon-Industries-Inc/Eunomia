#!/usr/bin/env bash
# PostToolUse (Edit|Write): auto-format the edited file. Best-effort, NEVER blocks
# (always exits 0). Deterministic enforcement so formatting doesn't rely on the agent
# remembering — ruff format for .py, clang-format for C/C++. Generated files are left
# to the codegen step (and exempt from the C++ format gate).
input="$(cat 2>/dev/null)"
file="$(printf '%s' "$input" | /usr/bin/python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")' 2>/dev/null)"

[ -z "$file" ] && exit 0
[ -f "$file" ] || exit 0

case "$file" in
  */contracts/_generated/*) exit 0 ;;  # generated: codegen owns formatting
  *.py)
    command -v uvx >/dev/null 2>&1 && uvx ruff format "$file" >/dev/null 2>&1
    ;;
  *.c|*.cc|*.cpp|*.cxx|*.h|*.hpp|*.hh)
    command -v clang-format >/dev/null 2>&1 && clang-format -i "$file" >/dev/null 2>&1
    ;;
esac
exit 0
