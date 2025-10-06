#!/usr/bin/env bash
set -euo pipefail

method="${NOTIFY_METHOD:-}"
if [[ -z "$method" ]]; then
  echo "notify_method is required"; exit 1
fi

case "$method" in
  bot)
    : "${SLACK_CHANNEL_ID:?slack_channel_id is required for notify_method=bot}"
    : "${SLACK_BOT_TOKEN:?slack_bot_token is required for notify_method=bot}"
    ;;
  webhook)
    : "${SLACK_WEBHOOK_URL:?slack_webhook_url is required for notify_method=webhook}"
    ;;
  *)
    echo "notify_method must be 'bot' or 'webhook'"; exit 1
    ;;
esac
