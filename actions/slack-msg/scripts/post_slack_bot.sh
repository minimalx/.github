#!/usr/bin/env bash
set -euo pipefail

: "${SLACK_BOT_TOKEN:?SLACK_BOT_TOKEN is required}"
: "${SLACK_CHANNEL_ID:?SLACK_CHANNEL_ID is required}"

resp="$(curl -sS -X POST 'https://slack.com/api/chat.postMessage' \
  -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
  -H 'Content-type: application/json; charset=utf-8' \
  --data-binary @- <<JSON
{
  "channel": "${SLACK_CHANNEL_ID}",
  "unfurl_links": false,
  "unfurl_media": false,
  $(jq -c '. | to_entries | map(select(.key=="blocks")) | from_entries' < payload.json)
}
JSON
)"

ok=$(printf '%s' "$resp" | jq -r '.ok')
if [[ "$ok" != "true" ]]; then
  echo "Slack API error: $resp"
  exit 1
fi

ts=$(printf '%s' "$resp" | jq -r '.ts')
echo "slack_ts=$ts" >> "$GITHUB_OUTPUT"
