#!/usr/bin/env python3
"""
Generate a C header with four hex keys and an inline byte-extractor.

Usage:
  python gen_secret_keys_header.py <DEFAULT_KEY_A> <DEFAULT_KEY_B> <MINIMAL_KEY_A> <MINIMAL_KEY_B> -o <output_path>
"""

import argparse
import os
import sys

def parse_hex(s: str) -> int:
    try:
        s_clean = s.replace("_", "")
        return int(s_clean, 16) if s_clean.lower().startswith("0x") else int(s_clean, 16)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Invalid hex value: {s!r}") from e

def fmt_hex(val: int, min_digits: int) -> str:
    if val < 0:
        raise ValueError("Hex values must be non-negative")
    hex_digits = format(val, "X")
    width = max(len(hex_digits), min_digits)
    if width % 2:
        width += 1
    return "0x" + hex_digits.zfill(width)

def generate_header(dka: int, dkb: int, mka: int, mkb: int) -> str:
    for name, v in [("DEFAULT_KEY_A", dka), ("DEFAULT_KEY_B", dkb),
                    ("MINIMAL_KEY_A", mka), ("MINIMAL_KEY_B", mkb)]:
        if v.bit_length() > 64:
            raise ValueError(f"{name} exceeds 64 bits")

    min_digits = 12  # pretty 48-bit style by default
    dka_s, dkb_s = fmt_hex(dka, min_digits), fmt_hex(dkb, min_digits)
    mka_s, mkb_s = fmt_hex(mka, min_digits), fmt_hex(mkb, min_digits)

    max_bytes = max(1, min(8, max((dka.bit_length() + 7) // 8,
                                  (dkb.bit_length() + 7) // 8,
                                  (mka.bit_length() + 7) // 8,
                                  (mkb.bit_length() + 7) // 8)))
    bits = max_bytes * 8

    return f"""#ifndef SECRET_KEYS_H
#define SECRET_KEYS_H

#include <stdint.h>

#define DEFAULT_KEY_A {dka_s}
#define DEFAULT_KEY_B {dkb_s}

#define MINIMAL_KEY_A {mka_s}
#define MINIMAL_KEY_B {mkb_s}

/* Get the n-th byte from a key (0 = least-significant byte). */
static inline uint8_t
key_nth_byte (uint64_t key, unsigned n)
{{
    return (uint8_t)((key >> (8u * n)) & 0xFFU);
}}

/* Convenience macros for your constants (valid n for these {bits}-bit keys: 0..{max_bytes - 1}). */
#define DEFAULT_KEY_A_BYTE(n) key_nth_byte(DEFAULT_KEY_A, (n))
#define DEFAULT_KEY_B_BYTE(n) key_nth_byte(DEFAULT_KEY_B, (n))
#define MINIMAL_KEY_A_BYTE(n) key_nth_byte(MINIMAL_KEY_A, (n))
#define MINIMAL_KEY_B_BYTE(n) key_nth_byte(MINIMAL_KEY_B, (n))

#endif
"""

def main():
    ap = argparse.ArgumentParser(description="Generate secret_keys.h from four hex values.")
    ap.add_argument("DEFAULT_KEY_A", type=parse_hex)
    ap.add_argument("DEFAULT_KEY_B", type=parse_hex)
    ap.add_argument("MINIMAL_KEY_A", type=parse_hex)
    ap.add_argument("MINIMAL_KEY_B", type=parse_hex)
    ap.add_argument("-o", "--output", required=True, metavar="PATH", help="Write to file path (e.g., src/secret_keys.h)")
    args = ap.parse_args()

    header = generate_header(args.DEFAULT_KEY_A, args.DEFAULT_KEY_B,
                             args.MINIMAL_KEY_A, args.MINIMAL_KEY_B)

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(header)

if __name__ == "__main__":
    main()
