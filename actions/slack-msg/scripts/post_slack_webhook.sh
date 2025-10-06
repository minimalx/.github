#!/usr/bin/env bash
set -euo pipefail

: "${SLACK_WEBHOOK_URL:?SLACK_WEBHOOK_URL is required}"

resp="$(curl -sS -X POST "$SLACK_WEBHOOK_URL" \
  -H 'Content-type: application/json' \
  --data-binary @payload.json)"

# Webhooks typically return "ok" (text) or 200 empty – keep for logs.
echo "Webhook response: $resp"
