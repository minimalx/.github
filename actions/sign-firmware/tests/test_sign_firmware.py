"""Tests for sign_firmware.py.

Run from the action directory:
    python -m pytest tests/
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from intelhex import IntelHex

ACTION_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACTION_DIR))

import sign_firmware as sf  # noqa: E402

DUMMY_PRIV = ACTION_DIR / "tests" / "dummy_private_key.pem"
DUMMY_PUB = ACTION_DIR / "tests" / "dummy_public_key.pem"

APP_START = 0x08020000
APP_END = 0x08040000  # 128 KiB slot
SIG_OFFSET = APP_END - sf.TRAILER_LEN


def _make_synthetic_hex(tmp_path: Path, size: int = 0x1000) -> Path:
    """Build a small hex with a recognizable byte pattern at app_start."""
    ih = IntelHex()
    for i in range(size):
        ih[APP_START + i] = (i * 7 + 13) & 0xFF
    path = tmp_path / "fw.hex"
    ih.write_hex_file(str(path))
    return path


def _load_dummy_public_key():
    return serialization.load_pem_public_key(DUMMY_PUB.read_bytes())


def _load_dummy_private_key():
    return serialization.load_pem_private_key(DUMMY_PRIV.read_bytes(), password=None)


def test_sign_and_verify_roundtrip(tmp_path):
    hex_path = _make_synthetic_hex(tmp_path)
    sf.sign_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        private_key=_load_dummy_private_key(),
    )
    assert sf.verify_signed_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        public_key=_load_dummy_public_key(),
    )


def test_signature_is_deterministic(tmp_path):
    """Ed25519 is deterministic: same key + same message -> same signature."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    a = _make_synthetic_hex(dir_a)
    b = _make_synthetic_hex(dir_b)

    priv = _load_dummy_private_key()
    sf.sign_hex(hex_path=a, app_start=APP_START, app_end=APP_END, private_key=priv)
    sf.sign_hex(hex_path=b, app_start=APP_START, app_end=APP_END, private_key=priv)

    sig_a = bytes(IntelHex(str(a)).tobinarray(start=SIG_OFFSET, size=sf.SIG_LEN))
    sig_b = bytes(IntelHex(str(b)).tobinarray(start=SIG_OFFSET, size=sf.SIG_LEN))
    assert sig_a == sig_b


def test_tampered_payload_fails_verification(tmp_path):
    hex_path = _make_synthetic_hex(tmp_path)
    sf.sign_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        private_key=_load_dummy_private_key(),
    )

    ih = IntelHex(str(hex_path))
    ih[APP_START + 100] ^= 0x01
    ih.write_hex_file(str(hex_path))

    assert not sf.verify_signed_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        public_key=_load_dummy_public_key(),
    )


def test_tampered_signature_fails_verification(tmp_path):
    hex_path = _make_synthetic_hex(tmp_path)
    sf.sign_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        private_key=_load_dummy_private_key(),
    )

    ih = IntelHex(str(hex_path))
    ih[SIG_OFFSET + 10] ^= 0xFF
    ih.write_hex_file(str(hex_path))

    assert not sf.verify_signed_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        public_key=_load_dummy_public_key(),
    )


def test_crc_region_left_untouched(tmp_path):
    """Bytes [app_end - 4, app_end) must not be modified by signing."""
    hex_path = _make_synthetic_hex(tmp_path)
    ih = IntelHex(str(hex_path))
    crc_marker = b"\xDE\xAD\xBE\xEF"
    for i, b in enumerate(crc_marker):
        ih[APP_END - sf.CRC_LEN + i] = b
    ih.write_hex_file(str(hex_path))

    sf.sign_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        private_key=_load_dummy_private_key(),
    )

    ih = IntelHex(str(hex_path))
    written = bytes(ih.tobinarray(start=APP_END - sf.CRC_LEN, size=sf.CRC_LEN))
    assert written == crc_marker


def test_payload_padded_with_0xff_for_gaps(tmp_path):
    """Sparse hex regions must be treated as 0xFF (erased flash) when signing."""
    ih = IntelHex()
    ih[APP_START] = 0xAA
    ih[APP_START + 0x800] = 0xBB  # leaves a gap
    hex_path = tmp_path / "sparse.hex"
    ih.write_hex_file(str(hex_path))

    sf.sign_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        private_key=_load_dummy_private_key(),
    )

    assert sf.verify_signed_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        public_key=_load_dummy_public_key(),
    )


def test_cli_with_dummy_key_flag(tmp_path):
    hex_path = _make_synthetic_hex(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(ACTION_DIR / "sign_firmware.py"),
            "--hex", str(hex_path),
            "--app-start", hex(APP_START),
            "--app-end", hex(APP_END),
            "--allow-dummy-key",
        ],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "FIRMWARE_SIGNING_PRIVATE_KEY"},
    )
    assert result.returncode == 0, result.stderr
    assert "DUMMY KEY" in result.stderr
    assert sf.verify_signed_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        public_key=_load_dummy_public_key(),
    )


def test_cli_fails_without_any_key(tmp_path):
    hex_path = _make_synthetic_hex(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(ACTION_DIR / "sign_firmware.py"),
            "--hex", str(hex_path),
            "--app-start", hex(APP_START),
            "--app-end", hex(APP_END),
        ],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "FIRMWARE_SIGNING_PRIVATE_KEY"},
    )
    assert result.returncode != 0
    assert "No private key" in result.stderr


def test_cli_with_env_var(tmp_path):
    hex_path = _make_synthetic_hex(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "FIRMWARE_SIGNING_PRIVATE_KEY"}
    env["FIRMWARE_SIGNING_PRIVATE_KEY"] = DUMMY_PRIV.read_text()
    result = subprocess.run(
        [
            sys.executable,
            str(ACTION_DIR / "sign_firmware.py"),
            "--hex", str(hex_path),
            "--app-start", hex(APP_START),
            "--app-end", hex(APP_END),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert sf.verify_signed_hex(
        hex_path=hex_path,
        app_start=APP_START,
        app_end=APP_END,
        public_key=_load_dummy_public_key(),
    )


def test_app_slot_too_small_rejected(tmp_path):
    hex_path = _make_synthetic_hex(tmp_path, size=16)
    with pytest.raises(sf.SigningError, match="too small"):
        sf.sign_hex(
            hex_path=hex_path,
            app_start=APP_START,
            app_end=APP_START + 32,
            private_key=_load_dummy_private_key(),
        )
