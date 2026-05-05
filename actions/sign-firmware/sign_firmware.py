#!/usr/bin/env python3
"""
Sign an Intel HEX firmware image with Ed25519.

Layout (fixed):
    sig region: 64 bytes at app_end - 68
    crc region:  4 bytes at app_end -  4   (NOT touched here; computed by a later step)
    sig covers: bytes [app_start, app_end - 68), gaps padded with 0xFF

Key resolution (in order):
    1. FIRMWARE_SIGNING_PRIVATE_KEY env var (PEM contents) -- CI path
    2. --private-key-file FILE -- local explicit path
    3. --allow-dummy-key -- uses tests/dummy_private_key.pem next to this script
       (committed, non-secret, for local pipeline smoke tests only)

Usage:
    python sign_firmware.py \\
        --hex firmware.hex \\
        --app-start 0x08020000 \\
        --app-end   0x08040000 \\
        [--output firmware_signed.hex] \\
        [--private-key-file key.pem | --allow-dummy-key]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from intelhex import IntelHex

SIG_LEN = 64
CRC_LEN = 4
TRAILER_LEN = SIG_LEN + CRC_LEN  # 68 bytes reserved at end of app slot
PAD_BYTE = 0xFF  # erased flash state on STM32


class SigningError(RuntimeError):
    pass


def parse_address(value: str) -> int:
    text = value.strip().replace("_", "")
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid address {value!r}") from exc


def load_private_key(args: argparse.Namespace) -> Ed25519PrivateKey:
    pem = os.environ.get("FIRMWARE_SIGNING_PRIVATE_KEY")
    source = "FIRMWARE_SIGNING_PRIVATE_KEY env"

    if not pem and args.private_key_file:
        pem = Path(args.private_key_file).read_text()
        source = f"file {args.private_key_file}"
    elif not pem and args.allow_dummy_key:
        dummy = Path(__file__).parent / "tests" / "dummy_private_key.pem"
        if not dummy.exists():
            raise SigningError(f"Dummy key not found at {dummy}")
        pem = dummy.read_text()
        source = "DUMMY KEY (--allow-dummy-key)"
        print(
            "WARNING: signing with the committed dummy key. "
            "DO NOT USE IN PRODUCTION.",
            file=sys.stderr,
        )

    if not pem:
        raise SigningError(
            "No private key provided. Set FIRMWARE_SIGNING_PRIVATE_KEY env, "
            "pass --private-key-file, or use --allow-dummy-key for local testing."
        )

    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError(
            f"Expected an Ed25519 private key, got {type(key).__name__}"
        )
    print(f"Using private key from: {source}", file=sys.stderr)
    return key


def extract_payload(ih: IntelHex, app_start: int, sig_offset: int) -> bytes:
    if app_start >= sig_offset:
        raise SigningError(
            f"app_start (0x{app_start:08X}) must be below sig_offset (0x{sig_offset:08X})"
        )
    ih.padding = PAD_BYTE
    return bytes(ih.tobinarray(start=app_start, size=sig_offset - app_start))


def patch_signature(ih: IntelHex, sig_offset: int, signature: bytes) -> None:
    if len(signature) != SIG_LEN:
        raise SigningError(f"Signature must be {SIG_LEN} bytes, got {len(signature)}")
    for i, byte in enumerate(signature):
        ih[sig_offset + i] = byte


def sign_hex(
    *,
    hex_path: Path,
    app_start: int,
    app_end: int,
    private_key: Ed25519PrivateKey,
    output_path: Path | None = None,
) -> Path:
    if app_end - app_start <= TRAILER_LEN:
        raise SigningError(
            f"App slot too small: end-start = {app_end - app_start} bytes, "
            f"need > {TRAILER_LEN}"
        )
    sig_offset = app_end - TRAILER_LEN

    ih = IntelHex(str(hex_path))
    payload = extract_payload(ih, app_start, sig_offset)
    signature = private_key.sign(payload)
    patch_signature(ih, sig_offset, signature)

    out = output_path or hex_path
    ih.write_hex_file(str(out))
    print(
        f"Signed {len(payload)} bytes from 0x{app_start:08X} to 0x{sig_offset:08X}; "
        f"signature written at 0x{sig_offset:08X} in {out}",
        file=sys.stderr,
    )
    return out


def verify_signed_hex(
    *,
    hex_path: Path,
    app_start: int,
    app_end: int,
    public_key: Ed25519PublicKey,
) -> bool:
    sig_offset = app_end - TRAILER_LEN
    ih = IntelHex(str(hex_path))
    payload = extract_payload(ih, app_start, sig_offset)
    signature = bytes(ih.tobinarray(start=sig_offset, size=SIG_LEN))
    try:
        public_key.verify(signature, payload)
        return True
    except InvalidSignature:
        return False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hex", required=True, type=Path, help="Input Intel HEX file")
    parser.add_argument("--app-start", required=True, type=parse_address, help="App slot start address")
    parser.add_argument("--app-end", required=True, type=parse_address, help="App slot end address (exclusive)")
    parser.add_argument("--output", type=Path, default=None, help="Output hex (default: in-place)")
    parser.add_argument("--private-key-file", type=Path, default=None, help="Path to PEM private key")
    parser.add_argument("--allow-dummy-key", action="store_true", help="Use committed dummy key for local testing")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        priv = load_private_key(args)
        sign_hex(
            hex_path=args.hex,
            app_start=args.app_start,
            app_end=args.app_end,
            private_key=priv,
            output_path=args.output,
        )
    except SigningError as exc:
        print(f"sign-firmware: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
