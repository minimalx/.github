#!/usr/bin/env bash
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN (github_token) is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${TAG:?TAG (inputs.tag) is required}"

TARGET="${TARGET_COMMITISH:-}"
MAX="${MAX_NOTES_CHARS:-2900}"
FALLBACK="${NOTES_FALLBACK_TEXT:-"(No auto-generated notes; see commits between tags.)"}"

NOTES_RAW="$(
  gh api -X POST \
    "repos/${GITHUB_REPOSITORY}/releases/generate-notes" \
    -f tag_name="$TAG" \
    ${TARGET:+-f target_commitish="$TARGET"} \
    | jq -r '.body'
)"

if [[ -z "$NOTES_RAW" || "$NOTES_RAW" == "null" ]]; then
  NOTES_RAW="$FALLBACK"
fi

if [[ ${#NOTES_RAW} -gt $MAX ]]; then
  NOTES_RAW="${NOTES_RAW:0:$MAX}"$'\n''…(truncated)'
fi

# Save plain text and JSON-escape for Block Kit
printf '%s' "$NOTES_RAW" > notes.txt
NOTES_ESCAPED=$(python3 - <<'PY'
import json,sys
print(json.dumps(sys.stdin.read())[1:-1])
PY
< notes.txt)

# Expose for later steps
echo "notes_escaped=$NOTES_ESCAPED" >> "$GITHUB_OUTPUT"
