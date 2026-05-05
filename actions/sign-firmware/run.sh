#!/bin/sh
# Entry point for sign_firmware.py that works in three environments:
#   1. CI containers / dev machines where cryptography + intelhex are already
#      importable from system python3 -> runs sign_firmware.py directly.
#   2. Dev machines without those modules -> bootstraps a venv at
#      $(dirname "$0")/.venv on first run, installs the deps, then runs from
#      the venv. Subsequent runs reuse the venv.
#   3. CI runners with no Python at all -> caller must install python3 first;
#      this script does not try to install it.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if python3 -c "import cryptography, intelhex" 2>/dev/null; then
    exec python3 "$SCRIPT_DIR/sign_firmware.py" "$@"
fi

VENV="$SCRIPT_DIR/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "sign-firmware: bootstrapping venv at $VENV (one-time)" >&2
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet "cryptography>=41" "intelhex>=2.3"
fi

exec "$VENV/bin/python" "$SCRIPT_DIR/sign_firmware.py" "$@"
