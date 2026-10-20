#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET_COMMITISH:-}"
MAX="${MAX_NOTES_CHARS:-2900}"
FALLBACK="${NOTES_FALLBACK_TEXT:-"(No auto-generated notes; see commits between tags.)"}"
OVERRIDE="${RELEASE_NOTES_TEXT:-}"

if [[ -n "${OVERRIDE//[[:space:]]/}" ]]; then
  NOTES_RAW="$OVERRIDE"
else
  : "${GH_TOKEN:?GH_TOKEN (github_token) is required}"
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  : "${TAG:?TAG (inputs.tag) is required}"

  NOTES_RAW="$(
    gh api -X POST \
      "repos/${GITHUB_REPOSITORY}/releases/generate-notes" \
      -f tag_name="$TAG" \
      ${TARGET:+-f target_commitish="$TARGET"} \
      | jq -r '.body'
  )"
fi

if [[ -z "$NOTES_RAW" || "$NOTES_RAW" == "null" ]]; then
  NOTES_RAW="$FALLBACK"
fi

if [[ ${#NOTES_RAW} -gt $MAX ]]; then
  NOTES_RAW="${NOTES_RAW:0:$MAX}"$'\n''…(truncated)'
fi

# Save as-is for debugging if you want
printf '%s' "$NOTES_RAW" > notes.txt

# Pass the notes through unescaped: build_payload.sh hands them to
# `jq --arg`, which does the JSON escaping. Escaping here as well would
# double-escape them (literal \n and \uXXXX in Slack). The output keeps the
# notes_escaped name because callers read it by that name.
NOTES_ESCAPED="$NOTES_RAW"

# >>> This is the important part: use a delimiter for multiline-safe output <<<
delim="EOF_$(dd if=/dev/urandom bs=16 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')"
{
  echo "notes_escaped<<$delim"
  printf '%s\n' "$NOTES_ESCAPED"
  echo "$delim"
} >> "$GITHUB_OUTPUT"
