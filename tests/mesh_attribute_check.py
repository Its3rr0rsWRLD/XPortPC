"""Pass indexed runtime vertex colors through PARAM0 and a translated attr0 pixel program."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from mesh_entry_check import TRIANGLE, binary, draw, enumerate_pcs, fixture
from mesh_indexed_check import HEADER, MESH, WORDS, inputs, lower
from pixel_aot_check import attribute_color, translate_attribute


def program():
    code = MESH.copy()
    fetch = code.index("buffer_load_dwordx3 v[1:3], v1, s[32:35], 0 offen")
    code[fetch:fetch] = ["v_add_nc_u32_e32 v16, 64, v1",
                         "buffer_load_dwordx3 v[5:7], v16, s[32:35], 0 offen"]
    code.insert(-1, "exp param0 v7, v4, v6, v5 done")
    return code


def gradient(swap):
    constants = inputs(TRIANGLE)
    colors = [(0, 0, 0), (2, 0, 0), (0, 2, 0)]
    for i, (r, g, b) in enumerate(colors):
        struct.pack_into("<3f", constants, 1028 + 64 + i * 12, g if swap else r, r if swap else g, b)
    # The full-screen triangle extends to x=64 and y=-32. Vertex amplitudes of two
    # produce exactly representable ramps at the centers of the 32x32 pixels.
    pixels = bytearray()
    for y in range(32):
        for x in range(32):
            r, g = (round(v * 255 / 32) for v in (x + 0.5, 31.5 - y))
            pixels.extend((g if swap else r, r if swap else g, 0, 255))
    return constants, [TRIANGLE[i] for i in (1, 2, 0)], bytes(pixels)


if __name__ == "__main__":
    code = program()
    export = code.index("exp param0 v7, v4, v6, v5 done")
    for replacement in (["exp param0 off, v4, v6, v5 done"], [code[export]] * 2,
                        ["v_cmpx_gt_u32_e32 2, v0", code[export]]):
        try:
            lower(enumerate_pcs(code[:export] + replacement + code[export + 1:]), WORDS, (3, 1), HEADER)
        except ValueError:
            continue
        raise AssertionError("Unsupported or incomplete PARAM0 export was accepted")
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        if sys.argv[1] == "binary":
            binary(tmp, *sys.argv[2:], program=code, words=WORDS, header=HEADER)
        else:
            mesh = lower(enumerate_pcs(code), WORDS, (3, 1), HEADER)
            pixel = translate_attribute(attribute_color(False))
            result = draw(*sys.argv[1:], tmp, mesh, [gradient(False), gradient(True)],
                          indexed=True, pixel_source=pixel)
            if result:
                sys.exit(result)
            constants, positions, _ = gradient(True)
            path = tmp / "stale-palette.case"
            path.write_bytes(fixture(constants, positions, gradient(False)[2], True))
            wrong = subprocess.run([sys.argv[2], sys.argv[3], "--mesh-indexed", tmp / "mesh.dxil",
                                    tmp / "pixel.dxil", path], capture_output=True, text=True)
            # Only the 32 pixels on the equal-channel diagonal keep the same color.
            if (wrong.returncode != 1 or "pixels=1024 mismatches=992" not in wrong.stdout.splitlines()
                    or "Draw reference mismatch" not in wrong.stderr):
                raise AssertionError(f"Expected an isolated palette mismatch\n{wrong.stdout}\n{wrong.stderr}")
