#!/usr/bin/env bash
set -euo pipefail

: "${HEADER_EMOJI:?HEADER_EMOJI is required}"
: "${BOARD_NAME:?BOARD_NAME is required}"
: "${PACKAGE_NAME:?PACKAGE_NAME is required}"
: "${TAG:?TAG is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_ACTOR:?GITHUB_ACTOR is required}"
: "${NOTES_ESCAPED:?NOTES_ESCAPED is required}"

APP="${APP_NAME:-}"
HEADER="${HEADER_EMOJI} New Release: ${BOARD_NAME}"
if [[ -n "$APP" ]]; then
  HEADER="${HEADER} • ${APP}"
fi
HEADER="${HEADER} ${TAG}"

RELEASE_URL="https://github.com/${GITHUB_REPOSITORY}/releases/tag/${TAG}"

jq -n --arg header "$HEADER" \
      --arg repo   "$GITHUB_REPOSITORY" \
      --arg actor  "$GITHUB_ACTOR" \
      --arg pkg    "$PACKAGE_NAME" \
      --arg tag    "$TAG" \
      --arg url    "$RELEASE_URL" \
      --arg notes  "$NOTES_ESCAPED" \
'{
  blocks: [
    { type: "header", text: { type: "plain_text", text: $header } },
    { type: "section",
      fields: [
        { type: "mrkdwn", text: ("*Repository:*\n" + $repo) },
        { type: "mrkdwn", text: ("*Actor:*\n" + $actor) },
        { type: "mrkdwn", text: ("*Package:*\n" + $pkg) },
        { type: "mrkdwn", text: ("*Tag:*\n" + $tag) }
      ]
    },
    { type: "divider" },
    { type: "section", text: { type: "mrkdwn", text: ("*Release notes:*\n" + $notes) } },
    { type: "actions", elements: [
        { type: "button", text: { type: "plain_text", text: "View Tag" }, url: $url }
    ]}
  ]
}' > payload.json

echo "release_url=$RELEASE_URL" >> "$GITHUB_OUTPUT"
