#!/bin/sh
# Entry point for sign_firmware.py that works in three environments:
#   1. CI containers / dev machines where cryptography + intelhex are already
#      importable from system python3 -> runs sign_firmware.py directly.
#   2. Dev machines without those modules -> bootstraps a venv at
#      $(dirname "$0")/.venv/<platform-architecture-python> on first run.
#      Native, Rosetta and Docker builds keep separate binary dependencies.
#   3. CI runners with no Python at all -> caller must install python3 first;
#      this script does not try to install it.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Importing the package alone does not load its native OpenSSL backend.
# Exercise the same signing primitives used by sign_firmware.py.
SIGNING_CHECK='from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from intelhex import IntelHex
key = Ed25519PrivateKey.generate()
key.public_key().verify(key.sign(b"sign-firmware-check"), b"sign-firmware-check")'

if python3 -c "$SIGNING_CHECK" 2>/dev/null; then
    exec python3 "$SCRIPT_DIR/sign_firmware.py" "$@"
fi

ENV_ID=$(python3 -c 'import platform, sys; print("%s-%s-py%d.%d" % (sys.platform, platform.machine(), sys.version_info.major, sys.version_info.minor))')
VENV="$SCRIPT_DIR/.venv/$ENV_ID"
VENV_PY="$VENV/bin/python"
if [ -x "$VENV_PY" ] && "$VENV_PY" -c "$SIGNING_CHECK" 2>/dev/null; then
    exec "$VENV_PY" "$SCRIPT_DIR/sign_firmware.py" "$@"
fi

if [ ! -x "$VENV_PY" ] || ! "$VENV_PY" -c "$SIGNING_CHECK" 2>/dev/null; then
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
    "$VENV_PY" -m pip install --quiet --only-binary=:all: "cryptography>=41" "intelhex>=2.3"
fi

"$VENV_PY" -c "$SIGNING_CHECK"
exec "$VENV_PY" "$SCRIPT_DIR/sign_firmware.py" "$@"
