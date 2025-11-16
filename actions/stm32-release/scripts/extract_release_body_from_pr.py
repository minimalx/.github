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
CODERABBIT_TITLE_REGEX = re.compile(r"(?im)^summary by coderabbit\b")


def github_api_get(url: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "stm32-release-action",
    }
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.load(resp)


def extract_summary_section(body: str) -> str | None:
    """Extract the contents of a '## Summary' section from Markdown."""
    if not body:
        return None

    match = SUMMARY_HEADING_REGEX.search(body)
    if not match:
        return None

    heading_end = match.end()
    heading_marks = match.group(1)
    heading_level = len(heading_marks)

    newline_pos = body.find("\n", heading_end)
    content_start = len(body) if newline_pos == -1 else newline_pos + 1

    next_heading_regex = re.compile(r"(?m)^#{1,%d}\s+.+$" % heading_level)
    next_match = next_heading_regex.search(body, pos=content_start)

    content_end = next_match.start() if next_match else len(body)
    section = body[content_start:content_end].strip()
    return section or None


def extract_coderabbit_summary_from_comment(body: str) -> str | None:
    """
    Given a single PR comment body, return the useful part of a
    'Summary by CodeRabbit' comment.
    """
    if not body:
        return None

    lines = body.strip().splitlines()

    # Require first non-empty line to look like "Summary by CodeRabbit"
    first_non_empty_idx = next(
        (i for i, line in enumerate(lines) if line.strip()), None
    )
    if first_non_empty_idx is None:
        return None

    if not CODERABBIT_TITLE_REGEX.match(lines[first_non_empty_idx].strip()):
        return None

    # Skip title line and any immediate separators (e.g. '---', '___')
    content_lines = lines[first_non_empty_idx + 1 :]
    while content_lines and re.fullmatch(r"\s*-{3,}\s*|\s*_{3,}\s*", content_lines[0]):
        content_lines = content_lines[1:]

    content = "\n".join(content_lines).strip()
    return content or None


def find_coderabbit_summary(repo: str, pr_number: int, token: str) -> str | None:
    """
    Look through issue comments on the PR for a CodeRabbit summary comment.
    Uses the *latest* matching comment.
    """
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    try:
        comments = github_api_get(url, token)
    except Exception as e:  # noqa: BLE001
        print(f"Error fetching issue comments: {e}", file=sys.stderr)
        return None

    if not isinstance(comments, list):
        return None

    summary_candidates: list[str] = []
    for comment in comments:
        body = comment.get("body") or ""
        summary = extract_coderabbit_summary_from_comment(body)
        if summary:
            summary_candidates.append(summary)

    return summary_candidates[-1] if summary_candidates else None


def write_github_output(body: str) -> None:
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
        description=(
            "Extract release body from the 'Summary' section of the PR body "
            "or from a 'Summary by CodeRabbit' PR comment."
        )
    )
    parser.add_argument("--tag", required=True, help="Tag name for fallback text.")
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

    # 1) Find PR associated with this commit
    try:
        prs = github_api_get(
            f"https://api.github.com/repos/{repo}/commits/{sha}/pulls", token
        )
    except Exception as e:  # noqa: BLE001
        print(f"Error fetching PRs for commit: {e}", file=sys.stderr)
        prs = []

    if not isinstance(prs, list) or not prs:
        print(
            f"No pull requests found for commit {sha}; "
            "falling back to generic release body.",
            file=sys.stderr,
        )
        fallback = f"Release for tag {args.tag}"
        write_github_output(fallback)
        return 0

    pr = prs[0]
    pr_number = pr.get("number")
    pr_body = pr.get("body") or ""

    # 2) Try `## Summary` section in PR body
    summary = extract_summary_section(pr_body)

    # 3) If not present, try CodeRabbit comment
    if not summary and pr_number is not None:
        summary = find_coderabbit_summary(repo, pr_number, token)

    # 4) Fallbacks
    if not summary:
        print(
            "No explicit summary found; using full PR body or generic fallback.",
            file=sys.stderr,
        )
        release_body = pr_body.strip() or f"Release for tag {args.tag} (PR #{pr_number})"
    else:
        release_body = summary

    write_github_output(release_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
