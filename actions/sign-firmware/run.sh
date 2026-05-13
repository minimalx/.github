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
VENV_PY="$VENV/bin/python"
if [ -x "$VENV_PY" ] && "$VENV_PY" -c "import cryptography, intelhex" 2>/dev/null; then
    exec "$VENV_PY" "$SCRIPT_DIR/sign_firmware.py" "$@"
fi

if [ ! -x "$VENV_PY" ] || ! "$VENV_PY" -c "import cryptography, intelhex" 2>/dev/null; then
    echo "sign-firmware: bootstrapping venv at $VENV (one-time)" >&2
    rm -rf "$VENV"
    if ! python3 -m venv "$VENV"; then
        if [ "$(id -u)" = "0" ] && command -v apt-get >/dev/null 2>&1; then
            echo "sign-firmware: installing python3-venv in container" >&2
            apt-get update
            apt-get install -y python3-venv python3-pip
            rm -rf "$VENV"
            python3 -m venv "$VENV"
        else
            echo "sign-firmware: python3 venv support is unavailable; install python3-venv" >&2
            exit 1
        fi
    fi
    "$VENV_PY" -m pip install --quiet --upgrade pip
    "$VENV_PY" -m pip install --quiet "cryptography>=41" "intelhex>=2.3"
fi

exec "$VENV_PY" "$SCRIPT_DIR/sign_firmware.py" "$@"
