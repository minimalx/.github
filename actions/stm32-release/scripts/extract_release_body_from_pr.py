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


def github_api_get(url: str, token: str):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json, application/vnd.github.groot-preview+json",
        "User-Agent": "stm32-release-action",
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.load(resp)
    except HTTPError as e:
        print(f"[extract-release-body] GitHub API HTTP error {e.code}: {e.reason} ({url})", file=sys.stderr)
    except URLError as e:
        print(f"[extract-release-body] GitHub API URL error: {e.reason} ({url})", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[extract-release-body] GitHub API unexpected error: {e} ({url})", file=sys.stderr)
    return None


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


def is_coderabbit_title(line: str) -> bool:
    """
    Determine if a line looks like the 'Summary by CodeRabbit' title.

    We:
      - strip leading markdown cruft (#, *, >, spaces),
      - lowercase,
      - check if it starts with 'summary by coderabbit'.
    """
    stripped = re.sub(r"^[#>*\s]+", "", line).strip()
    return stripped.lower().startswith("summary by coderabbit")


def extract_coderabbit_summary_from_comment(body: str) -> str | None:
    """
    Given a single comment/review body, return the useful part of a
    'Summary by CodeRabbit' block.
    """
    if not body:
        return None

    lines = body.splitlines()

    title_idx = None
    for i, line in enumerate(lines):
        if is_coderabbit_title(line):
            title_idx = i
            break

    if title_idx is None:
        return None

    content_lines = lines[title_idx + 1 :]

    # Skip Markdown separators like '---', '___', '***'
    while content_lines and re.fullmatch(r"\s*(---+|___+|\*\s*\*\s*\*)\s*", content_lines[0]):
        content_lines = content_lines[1:]

    content = "\n".join(content_lines).strip()
    return content or None


def find_coderabbit_summary(repo: str, pr_number: int, token: str) -> str | None:
    """
    Look through PR issue comments and reviews for a CodeRabbit summary.
    Uses the latest matching block.
    """
    summaries: list[str] = []

    # 1) Issue comments: /issues/{pr}/comments
    url_comments = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    comments = github_api_get(url_comments, token)
    if isinstance(comments, list):
        print(f"[extract-release-body] Found {len(comments)} issue comments.", file=sys.stderr)
        for c in comments:
            summary = extract_coderabbit_summary_from_comment(c.get("body") or "")
            if summary:
                summaries.append(summary)
    else:
        print("[extract-release-body] No issue comments or API error for issue comments.", file=sys.stderr)

    # 2) PR reviews: /pulls/{pr}/reviews
    url_reviews = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
    reviews = github_api_get(url_reviews, token)
    if isinstance(reviews, list):
        print(f"[extract-release-body] Found {len(reviews)} PR reviews.", file=sys.stderr)
        for r in reviews:
            summary = extract_coderabbit_summary_from_comment(r.get("body") or "")
            if summary:
                summaries.append(summary)
    else:
        print("[extract-release-body] No PR reviews or API error for reviews.", file=sys.stderr)

    if summaries:
        print("[extract-release-body] Found CodeRabbit summary.", file=sys.stderr)
        return summaries[-1]

    print("[extract-release-body] No CodeRabbit summary comment found.", file=sys.stderr)
    return None


def find_pr_for_commit(repo: str, sha: str, token: str) -> dict | None:
    """
    Try to find a PR for the given commit SHA.

    Strategy:
      1. Use /commits/{sha}/pulls
      2. If that fails or is empty, scan recent PRs and match merge_commit_sha/head.sha
    """
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/pulls"
    prs = github_api_get(url, token)
    if isinstance(prs, list) and prs:
        print(f"[extract-release-body] /commits/{sha}/pulls returned {len(prs)} PR(s).", file=sys.stderr)
        return prs[0]
    print(f"[extract-release-body] /commits/{sha}/pulls returned no PRs; trying fallback search.", file=sys.stderr)

    url = f"https://api.github.com/repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=30"
    prs = github_api_get(url, token)
    if not isinstance(prs, list):
        print("[extract-release-body] Fallback PR search failed.", file=sys.stderr)
        return None

    for pr in prs:
        if pr.get("merge_commit_sha") == sha:
            print(f"[extract-release-body] Matched PR #{pr.get('number')} by merge_commit_sha.", file=sys.stderr)
            return pr
        head = pr.get("head") or {}
        if head.get("sha") == sha:
            print(f"[extract-release-body] Matched PR #{pr.get('number')} by head.sha.", file=sys.stderr)
            return pr

    print("[extract-release-body] No PR matched the commit SHA in recent PRs.", file=sys.stderr)
    return None


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
            "or from a 'Summary by CodeRabbit' comment/review."
        )
    )
    parser.add_argument("--tag", required=True, help="Tag name for fallback text.")
    args = parser.parse_args(argv[1:])

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_ACTIONS_BOT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = os.environ.get("GITHUB_SHA")

    print(f"[extract-release-body] repo={repo}, sha={sha}", file=sys.stderr)

    if not token or not repo or not sha:
        print(
            "[extract-release-body] Missing GITHUB_TOKEN / GITHUB_REPOSITORY / GITHUB_SHA; using fallback.",
            file=sys.stderr,
        )
        fallback = f"Release for tag {args.tag}"
        write_github_output(fallback)
        return 0

    pr = find_pr_for_commit(repo, sha, token)
    if not isinstance(pr, dict):
        print(
            "[extract-release-body] No PR found for this commit; using fallback.",
            file=sys.stderr,
        )
        fallback = f"Release for tag {args.tag}"
        write_github_output(fallback)
        return 0

    pr_number = pr.get("number")
    pr_body = pr.get("body") or ""
    print(f"[extract-release-body] Using PR #{pr_number}.", file=sys.stderr)

    # 1) Try '## Summary' in PR body
    summary = extract_summary_section(pr_body)
    if summary:
        print("[extract-release-body] Found 'Summary' section in PR body.", file=sys.stderr)

    # 2) If not found, try CodeRabbit comment/review
    if not summary and pr_number is not None:
        summary = find_coderabbit_summary(repo, pr_number, token)

    # 3) Fallbacks
    if not summary:
        print(
            "[extract-release-body] No explicit summary found; using full PR body or generic fallback.",
            file=sys.stderr,
        )
        release_body = pr_body.strip() or f"Release for tag {args.tag} (PR #{pr_number})"
    else:
        release_body = summary

    write_github_output(release_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
