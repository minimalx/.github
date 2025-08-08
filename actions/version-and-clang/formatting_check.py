#!/usr/bin/env python3
import argparse
import subprocess


def get_changed_files(base_ref, exts):
    subprocess.run(['git', 'fetch', 'origin', base_ref], check=True)
    diff = subprocess.check_output([
        'git', 'diff', '--diff-filter=d', '--name-only', f'origin/{base_ref}...HEAD'
    ])
    files = [f for f in diff.decode().split() if any(f.endswith(ext) for ext in exts)]
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-ref', required=True, help='Base ref for diff')
    parser.add_argument('--changed-exts', default='c,cc,cpp,h,proto', help='Comma-separated extensions')
    args = parser.parse_args()

    exts = ['.' + e.strip() for e in args.changed_exts.split(',')]
    files = get_changed_files(args.base_ref, exts)
    if not files:
        print("No C/C++/Proto files changed, skipping formatting check.")
        return

    print("Running clang-format style check:")
    for f in files:
        print(f"Checking: {f}")
        subprocess.run(['clang-format-20', '--dry-run', '--Werror', f], check=True)

if __name__ == '__main__':
    main()