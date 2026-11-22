"""Compare translated indexed geometry and a translated packed MRT0 export in one draw."""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from mesh_entry_check import draw, enumerate_pcs, fixture
from mesh_indexed_check import HEADER, MESH, SMALL, WORDS, inputs, lower
from pixel_aot_check import translate_buffer_color


def pipeline_case(top_y, rgb):
    # Screen vertices (4,28), (28,28), (4,top_y). The tested slopes miss pixel centers.
    points = [*SMALL[:2], (-0.75, 1 - top_y / 16, 0.5, 1)]
    constants = inputs(points)
    # The mesh matrix occupies b0 bytes 0..63. The pixel stage reads the next four words.
    struct.pack_into("<4f", constants, 64, *rgb, 1)
    color = bytes([*(round(v * 255) for v in rgb), 255])
    pixels = bytearray()
    for y in range(32):
        for x in range(32):
            inside = x >= 4 and y < 28 and (28 - top_y) * (x + 0.5 - 4) < 24 * (y + 0.5 - top_y)
            pixels.extend(color if inside else bytes((0, 0, 0, 255)))
    return constants, [points[i] for i in (1, 2, 0)], bytes(pixels)


def buffer_color_program():
    # Use the existing source-built descriptor setup, with RG and BA separately packed for export.
    program = ["s_mov_b32 s30, s9", "s_mov_b32 s31, 0",
               "s_load_dwordx4 s[12:15], s[30:31], null", "s_waitcnt lgkmcnt(0)",
               "s_buffer_load_dwordx4 s[4:7], s[12:15], 0x40", "s_waitcnt lgkmcnt(0)"]
    program.extend(f"v_mov_b32_e32 v{20+i}, s{4+i}" for i in range(4))
    return program + ["v_cvt_pkrtz_f16_f32_e32 v25, v20, v21", "v_cvt_pkrtz_f16_f32_e32 v26, v22, v23",
                      "exp mrt0 v25, v25, v26, v26 done compr vm", "s_endpgm"]


def main(tmp, compiler, renderer, adapter):
    mesh = lower(enumerate_pcs(MESH), WORDS, (3, 1), HEADER)
    program = buffer_color_program()
    cases = [pipeline_case(5, (1, 0.75, 0)), pipeline_case(5, (0, 0.75, 1)), pipeline_case(13, (1, 0.75, 0))]
    result = draw(compiler, renderer, adapter, tmp, mesh, cases, indexed=True,
                  pixel_source=translate_buffer_color(program))
    if result:
        return result
    swapped = [line.replace("v20, v21", "v22, v21").replace("v22, v23", "v20, v23") for line in program]
    source = tmp / "swapped.hlsl"
    source.write_text(translate_buffer_color(swapped))
    shader = tmp / "swapped.dxil"
    subprocess.run([compiler, "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    path = tmp / "swap.case"
    path.write_bytes(fixture(*cases[0], True))
    wrong = subprocess.run([renderer, adapter, "--mesh-indexed", tmp / "mesh.dxil", shader, path],
                           capture_output=True, text=True)
    if (wrong.returncode != 1 or "pixels=1024 mismatches=276" not in wrong.stdout.splitlines()
            or "Draw reference mismatch" not in wrong.stderr):
        raise AssertionError(f"Expected only covered pixels to change\n{wrong.stdout}\n{wrong.stderr}")
    return 0


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        sys.exit(main(Path(directory), *sys.argv[1:]))
