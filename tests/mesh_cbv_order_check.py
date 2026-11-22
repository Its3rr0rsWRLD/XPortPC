"""Exchange the two root CBVs without modifying the mesh or pixel inputs."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from mesh_entry_check import TRIANGLE, fixture, source
from pixel_aot_check import buffer_color, translate_buffer_color


def run(directory, dxc, renderer, adapter):
    for stage, profile, text, flags in (
        ("mesh", "ms_6_5", source(), ["-DTRACE_EXPORTS"]),
        ("pixel", "ps_6_0", translate_buffer_color(buffer_color(False)), []),
    ):
        shader = directory / (stage + ".hlsl")
        shader.write_text(text)
        subprocess.run([dxc, "-T", profile, "-E", "main", *flags, "-Fo",
                        directory / (stage + ".dxil"), shader], check=True)

    constants = bytearray(1024)
    # Mesh depth = b0[byte 4] + b1[byte 12]. Pixel RGBA = (b0.w, b0.x, b0.x, b0.w)
    # from the float4 at byte 16. All values and both depth sums are exactly representable.
    for offset, first, last, green in ((0, 0.125, 0.25, 0), (512, 0.375, 0.375, 1)):
        struct.pack_into("<f", constants, offset + 4, first)
        struct.pack_into("<f", constants, offset + 12, last)
        struct.pack_into("<4f", constants, offset + 16, green, 0, 0, 1)

    red = bytes((255, 0, 0, 255)) * 1024
    white = bytes((255, 255, 255, 255)) * 1024
    path = directory / "draw.case"
    command = [renderer, adapter, "--mesh-entry", directory / "mesh.dxil", directory / "pixel.dxil", path]
    for order, depth, pixels, error in (
        ("ab", 0.5, red, None), ("ba", 0.625, white, None),
        ("ba", 0.625, red, "Draw reference mismatch"),
        ("ba", 0.5, white, "Mesh export trace mismatch"),
    ):
        positions = [(x, y, depth, w) for x, y, _, w in TRIANGLE]
        path.write_bytes(fixture(constants, positions, pixels, True))
        result = subprocess.run([*command, order], capture_output=True, text=True)
        print(result.stdout, end="")
        if result.returncode == 77:
            return 77
        expected_mismatches = 1024 if error == "Draw reference mismatch" else 0
        if (result.returncode != int(error is not None)
                or f"pixels=1024 mismatches={expected_mismatches}" not in result.stdout.splitlines()
                or (error and error not in result.stderr)):
            raise AssertionError(f"{order}: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return 0


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        sys.exit(run(Path(temp), *sys.argv[1:]))
