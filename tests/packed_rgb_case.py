"""Verify a packed RGB to linear float PS against independent CPU pixel values."""

import argparse
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory


def linear_half(byte):
    value = byte / 255
    linear = value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    bits, = struct.unpack("<H", struct.pack("<e", linear))
    rounded, = struct.unpack("<e", struct.pack("<H", bits))
    if rounded > linear:
        bits -= 1
    return struct.unpack("<e", struct.pack("<H", bits))[0]


def verify(renderer, adapter, shader, directory):
    case = directory / "input.case"
    for packed in ((0, 10, 11, 90), (227, 128, 32, 0), (227, 128, 32, 240)):
        rgb = tuple(map(linear_half, packed[:3]))
        for wrong in (False, True):
            expected = rgb[2:] + rgb[:2] if wrong else rgb
            case.write_bytes(bytes(packed) + bytes(252) + struct.pack("<4f", *expected, 0) * 64)
            check = subprocess.run([renderer, adapter, "--check-pixel-case", shader, case],
                                   capture_output=True, text=True)
            if wrong:
                passed = check.returncode == 1 and "pixel_mismatch" in check.stderr
            else:
                if check.returncode == 77:
                    print(check.stdout + check.stderr)
                    return 77
                passed = (check.returncode == 0 and "max_absolute_error=0" in check.stdout
                          and "debug_errors=0" in check.stdout)
            if not passed:
                raise RuntimeError(f"{adapter} {packed} wrong_reference={wrong}\n{check.stdout}{check.stderr}")
    print(f"{adapter}: three matched draws, three rejected channel rotations")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("renderer", type=Path)
    parser.add_argument("shader", type=Path, help="Compiled ps_6_0 shader")
    parser.add_argument("adapter", choices=["hardware", "warp"])
    args = parser.parse_args()
    with TemporaryDirectory() as temporary:
        raise SystemExit(verify(args.renderer.resolve(), args.adapter, args.shader.resolve(), Path(temporary)))
