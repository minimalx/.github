#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def github_api_get(url: str, token: str):
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
        print(f"[extract-release-body] GitHub API HTTP error {e.code}: {e.reason} ({url})", file=sys.stderr)
    except URLError as e:
        print(f"[extract-release-body] GitHub API URL error: {e.reason} ({url})", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[extract-release-body] GitHub API unexpected error: {e} ({url})", file=sys.stderr)
    return None


def find_pr_for_commit(repo: str, sha: str, token: str) -> dict | None:
    """
    Try to find a PR for the given commit SHA.

    Strategy:
      1. Use /commits/{sha}/pulls
      2. If that fails or is empty, scan recent PRs and match merge_commit_sha/head.sha
    """
    # 1) Preferred: commit -> PRs
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/pulls"
    prs = github_api_get(url, token)
    if isinstance(prs, list) and prs:
        print(f"[extract-release-body] /commits/{sha}/pulls returned {len(prs)} PR(s).", file=sys.stderr)
        return prs[0]
    print(f"[extract-release-body] /commits/{sha}/pulls returned no PRs; trying fallback search.", file=sys.stderr)

    # 2) Fallback: look at recent PRs and match by SHA
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
    """
    Write the body as a multi-line GitHub Actions output named 'body'.
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
        description="Use the associated PR body as release notes."
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
    pr_body = (pr.get("body") or "").strip()
    print(f"[extract-release-body] Using PR #{pr_number}.", file=sys.stderr)

    if pr_body:
        release_body = pr_body
        print("[extract-release-body] Using PR body as release notes.", file=sys.stderr)
    else:
        release_body = f"Release for tag {args.tag} (PR #{pr_number})"
        print(
            "[extract-release-body] PR body is empty; using simple fallback text.",
            file=sys.stderr,
        )

    write_github_output(release_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
