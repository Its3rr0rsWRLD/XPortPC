"""Verify the D3D12 screen-space pixel center of each covered sample."""
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory


def check(dxc, renderer, backend):
    source = Path(__file__).with_name("pixel_position.hlsl")
    left, top, width, height = 2, 1, 5, 3
    colors = bytearray()
    for y in range(8):
        for x in range(8):
            inside = left <= x < left + width and top <= y < top + height
            rgba = (x + 0.5, y + 0.5, 0.25, 1.0) if inside else (-1.0,) * 4
            colors += struct.pack("<4f", *rgba)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = root / "position.case"
        reference.write_bytes(bytes(256) + colors + struct.pack("<B4I", 2, left, top, width, height))
        shaders = []
        for name, defines in (("position", []), ("swapped", ["-D", "SWAP_XY=1"])):
            shader = root / f"{name}.cso"
            subprocess.run([dxc, "-E", "main", "-T", "ps_6_0", *defines, "-Fo", shader, source], check=True)
            shaders.append(shader)
        command = [renderer, backend, "--check-pixel-case"]
        positive = subprocess.run([*command, shaders[0], reference], check=False)
        if positive.returncode:
            return positive.returncode
        negative = subprocess.run([*command, shaders[1], reference], capture_output=True, text=True)
        expected = ("pixel_mismatch x=2 y=1", "channel=0 expected=2.5 actual=1.5",
                    "channel=1 expected=1.5 actual=2.5")
        if negative.returncode != 1 or any(line not in negative.stderr for line in expected):
            raise AssertionError(f"Swapped X/Y did not fail at the first covered pixel\n{negative.stdout}\n{negative.stderr}")
        print("15 covered pixel centers and 49 clear pixels matched. Swapped X/Y failed at (2,1).")
    return 0


if __name__ == "__main__":
    sys.exit(check(*sys.argv[1:]))
