#!/usr/bin/env python3
import argparse
from datetime import datetime

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True, help='Semantic version string')
    parser.add_argument('--actor', required=True, help='GitHub actor')
    args = parser.parse_args()

    version = args.version
    major, minor, patch = version.split('.', 2)
    patch = patch.split('-', 1)[0]
    date = datetime.utcnow().strftime('%Y-%m-%d')

    content = f"""#ifndef VERSION_H
#define VERSION_H

#define VERSION_MAJOR   {major}
#define VERSION_MINOR   {minor}
#define VERSION_PATCH   {patch}

static const char VERSION_STR[]      = \"v{version}\";
static const char VERSION_DATE_STR[] = \"{date}\";
static const char VERSION_AUTHOR[]   = \"{args.actor}\";

#endif // VERSION_H
"""

    with open('version.h', 'w') as f:
        f.write(content)

    print(content)

if __name__ == '__main__':
    main()