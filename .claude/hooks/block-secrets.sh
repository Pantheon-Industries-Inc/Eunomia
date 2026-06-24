#!/usr/bin/env bash
# PreToolUse (Read|Edit|Write|Bash): block access to secret material. Exit 2 BLOCKS the
# tool call (the only reliable hard block per the docs). CONTRACT §2.3 forbids PSKs /
# secrets in the repo or on the card; PSKs live in a gitignored credentials store.
input="$(cat 2>/dev/null)"
target="$(printf '%s' "$input" | /usr/bin/python3 -c 'import json,sys
try:
    ti = json.load(sys.stdin).get("tool_input", {})
    print(ti.get("file_path") or ti.get("path") or ti.get("command") or "")
except Exception:
    print("")' 2>/dev/null)"

case "$target" in
  *.env|*/.env|*.pem|*.key|*.p12|*.pfx|*id_rsa*|*id_ed25519*|*/credentials/*|*/secrets/*)
    echo "BLOCKED by .claude/hooks/block-secrets.sh: secret-like target ($target)" >&2
    exit 2
    ;;
esac
exit 0
