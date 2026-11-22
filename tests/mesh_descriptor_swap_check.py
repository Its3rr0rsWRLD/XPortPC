"""Keep the upload and shaders fixed while exchanging two actual D3D12 CBVs."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from mesh_entry_check import PROGRAM, TRIANGLE, binary, enumerate_pcs, fixture
from mesh_entry_aot import lower
from mesh_pixel_pipeline_check import buffer_color_program
from pixel_aot_check import translate_buffer_color


MESH = [
    line.replace("v_add_f32_e32 v3, s31, v3", "v_add_f32_e32 v1, s31, v1")
    for line in PROGRAM
]
GEOMETRY = [4099]


def upload():
    data = bytearray(1024)
    for slot, depth, x_offset, color in (
        (0, 0.25, 0.5, (1, 0, 0, 1)),
        (1, 0.75, 0.0, (0, 1, 0, 1)),
    ):
        base = 512 * slot
        struct.pack_into("<f", data, base + 4, depth)
        struct.pack_into("<f", data, base + 12, x_offset)
        struct.pack_into("<4f", data, base + 64, *color)
    return data


def check(tmp, dxc, renderer, adapter):
    sources = (
        ("mesh", "ms_6_5", lower(enumerate_pcs(MESH), GEOMETRY, (3, 1)), ["-DTRACE_EXPORTS"]),
        ("pixel", "ps_6_0", translate_buffer_color(buffer_color_program()), []),
    )
    for name, profile, source, extra in sources:
        hlsl = tmp / f"{name}.hlsl"
        hlsl.write_text(source, encoding="ascii")
        subprocess.run([dxc, "-T", profile, "-E", "main", *extra, "-Fo",
                        tmp / f"{name}.dxil", hlsl], check=True)

    data = upload()
    normal_vertices = [(x, y, 0.25, w) for x, y, _, w in TRIANGLE]
    swapped_vertices = [(x + 0.5, y, 0.75, w) for x, y, _, w in TRIANGLE]
    normal_pixels = bytes((255, 0, 0, 255)) * 1024
    # The translated triangle's left edge moves from x=0 to x=8 in the 32x32 target.
    swapped_pixels = (bytes((0, 0, 0, 255)) * 8 + bytes((0, 255, 0, 255)) * 24) * 32
    path = tmp / "draw.case"
    command = [renderer, adapter, "--mesh-entry-table", tmp / "mesh.dxil", tmp / "pixel.dxil", path]
    path.write_bytes(fixture(data, normal_vertices, normal_pixels, True))
    result = subprocess.run(command)
    if result.returncode == 77:
        return 77
    result.check_returncode()

    command.append("--swap")
    path.write_bytes(fixture(data, swapped_vertices, swapped_pixels, True))
    subprocess.run(command, check=True)
    for vertices, pixels, mismatches, diagnostic in (
        (swapped_vertices, normal_pixels, 1024, "Draw reference mismatch"),
        (normal_vertices, swapped_pixels, 0, "Mesh export trace mismatch"),
    ):
        path.write_bytes(fixture(data, vertices, pixels, True))
        result = subprocess.run(command, capture_output=True, text=True)
        if (result.returncode != 1 or diagnostic not in result.stderr
                or f"pixels=1024 mismatches={mismatches}" not in result.stdout.splitlines()):
            raise AssertionError(f"Expected {diagnostic}\n{result.stdout}\n{result.stderr}")
        print(f"Negative control: {diagnostic}, pixel mismatches={mismatches}")
    return 0


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        if sys.argv[1] == "binary":
            binary(tmp, *sys.argv[2:], program=MESH, words=GEOMETRY)
        else:
            sys.exit(check(tmp, *sys.argv[1:]))
