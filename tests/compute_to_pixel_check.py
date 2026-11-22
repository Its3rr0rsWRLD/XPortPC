"""Translate a compute producer and a pixel consumer that share one GPU buffer."""
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

from pixel_aot_check import buffer_color, compile_shader, translate_buffer_color, write_case
from compute_store_aot import lower


def producer(red, green):
    words = struct.unpack("<4I", struct.pack("<4f", green, 0.0, 0.0, red))
    code = ["s_mov_b32 s9, 0", "s_load_dwordx4 s[12:15], s[8:9], null"]
    code.extend(f"v_mov_b32_e32 v{20 + i}, {word:#x}" for i, word in enumerate(words))
    code += ["s_waitcnt lgkmcnt(0)",
             "buffer_store_dwordx4 v[20:23], off, s[12:15], 0 offset:16",
             "s_endpgm"]
    return lower(code, 1, table_reg=8, descriptor_offset=0)


def check(dxc, renderer, backend):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        pixel_source, pixel = root / "pixel.hlsl", root / "pixel.cso"
        pixel_source.write_text(translate_buffer_color(buffer_color(False)), encoding="ascii")
        compile_shader(dxc, pixel_source, pixel)
        palette = ((0.25, 0.75), (0.5, 0.125))
        command = [renderer, backend, "--compute-to-pixel"]
        shaders = []
        references = []
        for i, (red, green) in enumerate(palette):
            source, shader, reference = (root / f"palette-{i}.{ext}" for ext in ("hlsl", "cso", "case"))
            source.write_text(producer(red, green), encoding="ascii")
            subprocess.run([dxc, "-T", "cs_6_0", "-E", "main", "-Fo", shader, source], check=True)
            # The reference's host constants are deliberately different from either GPU result.
            write_case(reference, bytes(256), (red, green, green, red))
            result = subprocess.run([*command, shader, pixel, reference], check=False)
            if result.returncode:
                return result.returncode
            shaders.append(shader)
            references.append(reference)
        stale = subprocess.run([*command, shaders[1], pixel, references[1], shaders[0]],
                               capture_output=True, text=True)
        expected = ("pixel_mismatch x=0 y=0", "channel=0 expected=0.5 actual=0.25",
                    "channel=1 expected=0.125 actual=0.75")
        if stale.returncode != 1 or any(item not in stale.stderr for item in expected):
            raise AssertionError(f"Stale GPU buffer escaped detection\n{stale.stdout}\n{stale.stderr}")
        print("Two GPU-produced palettes matched. Stale GPU buffer rejected at (0,0).")
    return 0


if __name__ == "__main__":
    sys.exit(check(*sys.argv[1:]))
