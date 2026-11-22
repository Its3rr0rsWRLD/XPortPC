"""Expose each word of a traced constant read through the depth readback fixture."""
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

from depth_mask_check import VS
from pixel_cb_read import Read, depth_probe, first_descriptor, first_read


def source():
    lines = [
        "s_mov_b32 s42, s9", "s_mov_b32 s43, 0",
        "s_load_dwordx4 s[36:39], s[42:43], null", "s_waitcnt lgkmcnt(0)",
        "s_buffer_load_dwordx4 s[12:15], s[36:39], 0x10", "s_waitcnt lgkmcnt(0)",
    ]
    descriptor = first_descriptor(lines)
    assert descriptor and (descriptor.table, descriptor.offset) == (9, 0)
    read = first_read(lines, descriptor)
    assert read == Read(4, 16)
    assert first_descriptor([lines[0], "s_mov_b32 s43, 1", *lines[2:]]) is None
    for invalid in (lines[:3] + lines[4:], lines[:-1],
                    lines[:4] + ["s_mov_b32 s38, 0"] + lines[4:],
                    lines[:4] + ["s_cbranch_scc0 4"] + lines[4:],
                    lines[:-1] + ["v_mov_b32_e32 v2, s13", lines[-1]]):
        assert first_read(invalid, descriptor) is None
    for index, replacement in [(0, "s_mov_b32 s42, s8"), (2, lines[2].replace("null", "0x20")),
                               (4, lines[4].replace("0x10", "0x20"))]:
        changed = lines.copy()
        changed[index] = replacement
        desc = first_descriptor(changed)
        try:
            depth_probe(desc, first_read(changed, desc))
        except ValueError:
            continue
        raise AssertionError("wrong table, slot or byte offset accepted")
    return depth_probe(descriptor, read)


def verify(dxc, renderer, adapter, tmp, shader):
    vs, ps = tmp / "v.dxil", tmp / "p.dxil"
    for profile, text, binary in (("vs", VS, vs), ("ps", shader, ps)):
        path = tmp / (profile + ".hlsl")
        path.write_text(text)
        subprocess.run([dxc, "-T", profile + "_6_0", "-E", "main", "-Fo", binary, path], check=True)

    def buffer(values):
        # Every word outside [16,32) is a sentinel, including the adjacent vectors.
        data = bytearray(struct.pack("<f", 0.75) * 512)
        struct.pack_into("<4f", data, 16, *values)
        return data

    a = (0.125, 0.25, 0.375, 0.5)
    b = (0.875, 0.0625, 0.625, 0.3125)
    c = (0.4375, 0.1875, 0.8125, 0.5625)
    fixture = tmp / "depth.case"
    for first, second, swap, expected, mismatches in (
        (a, b, False, a, 0), (c, b, False, c, 0), (a, c, False, a, 0),
        (a, b, True, a, 1024), (a, b, True, b, 0),
    ):
        fixture.write_bytes(buffer(first) + buffer(second) + struct.pack("<4f", *expected) * 256)
        mode = "--depth-mask-swapped" if swap else "--depth-mask"
        result = subprocess.run([renderer, adapter, mode, vs, ps, fixture], capture_output=True, text=True, timeout=30)
        if result.returncode == 77 and adapter == "hardware":
            print(result.stdout + result.stderr)
            return 77
        if (result.returncode != int(bool(mismatches)) or f"pixels=1024 mismatches={mismatches}\n" not in result.stdout
                or (mismatches and "Draw reference mismatch" not in result.stderr)):
            raise AssertionError(result.stdout + result.stderr)
        if "debug_errors=0" not in result.stdout and "debug_layer=unavailable" not in result.stdout:
            raise AssertionError(result.stdout + result.stderr)
        print(f"{adapter} {mode} mismatches={mismatches} expected={expected}")
    return 0


if __name__ == "__main__":
    dxc, renderer, adapter = sys.argv[1:4]
    shader = source()
    if len(sys.argv) == 5:
        measured = Path(sys.argv[4]).read_text()
        if measured != shader:
            raise ValueError("archive probe differs from source-built access")
        shader = measured
    with TemporaryDirectory() as directory:
        sys.exit(verify(dxc, renderer, adapter, Path(directory), shader))
