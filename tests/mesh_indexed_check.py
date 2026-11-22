"""Read packed 16-bit indices and three different float3s from a bound vertex SRV."""

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from mesh_entry_check import PROGRAM, TRIANGLE, binary, draw, enumerate_pcs, fixture
from mesh_entry_aot import lower

HEADER = 608  # 12-byte stride and byte base 4
WORDS = [4099, (2 << 16) | 1, 0]
MESH = """
s_mov_b32 s10, s17
s_mov_b32 s11, 0
s_load_dwordx4 s[24:27], s[10:11], null
s_mov_b32 s32, s18
s_or_b32 s33, s19, 0x10000
s_mov_b32 s34, -1
s_mov_b32 s35, 0x11014fac
s_buffer_load_dword s6, s[32:35], null
s_waitcnt lgkmcnt(0)
s_buffer_load_dword s15, s[24:27], null
s_lshr_b32 s4, s6, 3
s_and_b32 s4, s4, 60
s_lshr_b32 s5, s6, 7
s_and_b32 s5, s5, 0x1fffffc
s_waitcnt lgkmcnt(0)
""".strip().splitlines()
# Reuse the lane numbering, allocation and primitive export of the source-built triangle.
MESH += PROGRAM[
    PROGRAM.index("v_mbcnt_lo_u32_b32 v0, -1, 0") : PROGRAM.index(
        "v_cmp_eq_u32_e64 s[10:11], 1, v0"
    )
]
MESH += """
v_lshrrev_b32_e32 v12, 1, v0
v_lshl_add_u32 v12, v12, 2, 4
buffer_load_dword v13, v12, s[24:27], 0 offen
v_and_b32_e32 v10, 1, v0
v_cmp_eq_u32_e32 vcc, 1, v10
s_waitcnt vmcnt(0)
v_lshrrev_b32_e32 v14, 16, v13
v_and_b32_e32 v13, 0xffff, v13
v_cndmask_b32_e32 v1, v13, v14, vcc
v_mad_u32_u24 v1, s4, v1, s5
buffer_load_dwordx3 v[1:3], v1, s[32:35], 0 offen
s_waitcnt vmcnt(0)
v_mov_b32_e32 v4, 0x3f800000
exp pos0, v1, v2, v3, v4 done
s_endpgm
""".strip().splitlines()

SMALL = [(-0.75, -0.75, 0.5, 1), (0.75, -0.75, 0.5, 1), (-0.75, 0.6875, 0.5, 1)]


def inputs(points):
    constants = bytearray(1536)
    identity = (1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    struct.pack_into("<16f", constants, 0, *identity)
    struct.pack_into("<16f", constants, 512 + 352, *identity)
    struct.pack_into("<I", constants, 1024, HEADER)
    for i, point in enumerate(points):
        struct.pack_into("<3f", constants, 1028 + 12 * i, *point[:3])
    return constants


def small_raster():
    # Screen-space vertices (4,28), (28,28), (4,5). No sample lies on the hypotenuse.
    colors = bytearray()
    for y in range(32):
        for x in range(32):
            inside = x >= 4 and y < 28 and 23 * (x + 0.5 - 4) < 24 * (y + 0.5 - 5)
            colors.extend((0, 255 if inside else 0, 0, 255))
    return bytes(colors)


def cases(order):
    return [
        (inputs(points), [points[i] for i in order], visible)
        for points, visible in ((TRIANGLE, True), (SMALL, small_raster()))
    ]


def controls():
    program = enumerate_pcs(MESH)
    for old, new in (("0x11014fac", "0x11014fad"), ("s_waitcnt vmcnt(0)", "s_nop 0")):
        try:
            lower(
                [(pc, line.replace(old, new)) for pc, line in program],
                WORDS,
                (3, 1),
                HEADER,
            )
        except ValueError:
            continue
        raise AssertionError("Unknown descriptor or pending load accepted")
    for words in ([4099, 0xFFFF, 0], [4099]):
        try:
            lower(program, words, (3, 1), HEADER)
        except ValueError:
            continue
        raise AssertionError("Out-of-range index accepted")


if __name__ == "__main__":
    controls()
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        if sys.argv[1] == "binary":
            binary(tmp, *sys.argv[2:], program=MESH, words=WORDS, header=HEADER)
        else:
            compiler, renderer, adapter = sys.argv[1:]
            triangle_cases = cases((1, 2, 0))
            result = draw(
                compiler,
                renderer,
                adapter,
                tmp,
                lower(enumerate_pcs(MESH), WORDS, (3, 1), HEADER),
                triangle_cases,
                indexed=True,
            )
            if result:
                sys.exit(result)
            constants, positions, pixels = triangle_cases[1]
            bad = bytearray(fixture(constants, positions, pixels, True))
            bad[1028:1040] = bad[1040:1052]
            path = tmp / "collapsed.case"
            path.write_bytes(bad)
            control = subprocess.run(
                [
                    renderer,
                    adapter,
                    "--mesh-indexed",
                    tmp / "mesh.dxil",
                    tmp / "pixel.dxil",
                    path,
                ],
                capture_output=True,
                text=True,
            )
            if (
                control.returncode != 1
                or "mismatches=276" not in control.stdout
                or "Mesh export trace mismatch" not in control.stderr
            ):
                raise AssertionError(
                    "Collapsing a vertex must change both geometry and the partial raster"
                )
