#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


SUMMARY_HEADING_REGEX = re.compile(r"(?im)^(#{1,6})\s*summary\s*$")


def github_api_get(url: str, token: str) -> list[dict] | dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "stm32-release-action",
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.load(resp)
    except HTTPError as e:
        print(f"GitHub API HTTP error {e.code}: {e.reason}", file=sys.stderr)
    except URLError as e:
        print(f"GitHub API URL error: {e.reason}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"GitHub API unexpected error: {e}", file=sys.stderr)

    return {}


def extract_summary_section(body: str) -> str | None:
    """
    Extract the contents of the 'Summary' Markdown section from a PR body.
    - Looks for a heading like '## Summary', '### Summary', etc.
    - Returns text until the next heading of any level.
    """
    if not body:
        return None

    match = SUMMARY_HEADING_REGEX.search(body)
    if not match:
        return None

    heading_start = match.start()
    heading_end = match.end()
    heading_marks = match.group(1)
    heading_level = len(heading_marks)

    # Content starts at the end of the heading line
    # Move to the next newline to avoid any trailing text on heading line
    newline_pos = body.find("\n", heading_end)
    content_start = len(body) if newline_pos == -1 else newline_pos + 1

    # Find the next heading of same or higher level
    next_heading_regex = re.compile(r"(?m)^#{1,%d}\s+.+$" % heading_level)
    next_match = next_heading_regex.search(body, pos=content_start)

    content_end = next_match.start() if next_match else len(body)
    section = body[content_start:content_end].strip()

    return section or None


def write_github_output(body: str) -> None:
    """
    Write 'body' as a multi-line GitHub Actions output named 'body'.
    """
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print("GITHUB_OUTPUT is not set; cannot export step output.", file=sys.stderr)
        return

    out_file = Path(output_path)
    with out_file.open("a", encoding="utf-8") as f:
        f.write("body<<EOF\n")
        f.write(body)
        if not body.endswith("\n"):
            f.write("\n")
        f.write("EOF\n")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Extract release body from the 'Summary' section of the merged PR."
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="Tag name for fallback release body text.",
    )
    args = parser.parse_args(argv[1:])

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_ACTIONS_BOT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = os.environ.get("GITHUB_SHA")

    if not token or not repo or not sha:
        print(
            "GITHUB_TOKEN (or GITHUB_ACTIONS_BOT), GITHUB_REPOSITORY and "
            "GITHUB_SHA must be set.",
            file=sys.stderr,
        )
        fallback = f"Release for tag {args.tag}"
        write_github_output(fallback)
        return 0

    # Find PR(s) associated with this commit
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/pulls"
    data = github_api_get(url, token)
    if not isinstance(data, list) or not data:
        print(
            f"No pull requests found for commit {sha}; "
            "falling back to generic release body.",
            file=sys.stderr,
        )
        fallback = f"Release for tag {args.tag}"
        write_github_output(fallback)
        return 0

    pr = data[0]
    pr_number = pr.get("number")
    pr_body = pr.get("body") or ""

    summary = extract_summary_section(pr_body)
    if not summary:
        print(
            "Summary section not found in PR body; using full PR body as release notes.",
            file=sys.stderr,
        )
        release_body = pr_body.strip() or f"Release for tag {args.tag} (PR #{pr_number})"
    else:
        release_body = summary

    write_github_output(release_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
