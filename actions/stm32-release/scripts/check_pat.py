#!/usr/bin/env python3
import os
import sys


def main() -> int:
    pat = os.environ.get("GITHUB_ACTIONS_BOT", "")
    if not pat:
        print(
            (
                "ERROR: GITHUB_ACTIONS_BOT env var (PAT) not set. "
                "Refusing to attempt release."
            ),
            file=sys.stderr,
        )
        return 1

    # Silent success (original step only errored on missing PAT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
