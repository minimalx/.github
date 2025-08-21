#!/usr/bin/env python3
import argparse
import subprocess
import fnmatch


def get_changed_files(base_ref, exts, ignore_patterns):
    subprocess.run(['git', 'fetch', 'origin', base_ref], check=True)
    diff = subprocess.check_output([
        'git', 'diff', '--diff-filter=d', '--name-only', f'origin/{base_ref}...HEAD'
    ])
    files = [f for f in diff.decode().split() if any(f.endswith(ext) for ext in exts)]

    # Apply ignore patterns (supports wildcards like *.pb.h or paths like src/generated/*)
    if ignore_patterns:
        files = [
            f for f in files
            if not any(fnmatch.fnmatch(f, pat) for pat in ignore_patterns)
        ]

    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-ref', required=True, help='Base ref for diff')
    parser.add_argument('--changed-exts', default='c,cc,cpp,h,proto',
                        help='Comma-separated extensions')
    parser.add_argument('--ignore-files', default='',
                        help='Comma-separated list of files or glob patterns to ignore')

    args = parser.parse_args()

    exts = ['.' + e.strip() for e in args.changed_exts.split(',')]
    ignore_patterns = [p.strip() for p in args.ignore_files.split(',') if p.strip()]

    files = get_changed_files(args.base_ref, exts, ignore_patterns)
    if not files:
        print("No C/C++/Proto files to check after filtering, skipping formatting check.")
        return

    print("Running clang-format style check:")
    for f in files:
        print(f"Checking: {f}")
        subprocess.run(['clang-format-20', '--dry-run', '--Werror', f], check=True)


if __name__ == '__main__':
    main()
