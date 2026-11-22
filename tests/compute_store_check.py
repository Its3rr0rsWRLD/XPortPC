"""Check the single-store compute profile with original synthetic kernels."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from pixel_aot_check import envelope, must_reject
import compute_store_aot as aot
from pixel_aot import _read_named_container, disassemble
from resource_inventory import parts

SENTINEL = 0xc5c5c5c5
INDEXED = [
    "s_mov_b32 s12, s7", "s_mov_b32 s13, 0",
    "s_load_dwordx4 s[20:23], s[12:13], 0x30",
    "v_lshl_add_u32 v8, s11, 5, v0",
    "v_mov_b32_e32 v15, 19", "v_mov_b32_e32 v16, -5",
    "s_waitcnt lgkmcnt(0)", "buffer_store_dwordx2 v[15:16], v8, s[20:23], 0 idxen offset:4",
    "s_endpgm",
]
FIXED = [
    "s_mov_b32 s9, 0", "s_load_dwordx4 s[12:15], s[8:9], null",
    "v_mov_b32_e32 v20, 11", "v_mov_b32_e32 v21, 23", "v_mov_b32_e32 v22, -2",
    "s_waitcnt lgkmcnt(0)", "buffer_store_dwordx3 v[20:22], off, s[12:15], 0 offset:20",
    "s_endpgm",
]
INDEX_BINDING = dict(table_reg=7, group_reg=11, descriptor_offset=48, stride=12)
FIXED_BINDING = dict(table_reg=8, descriptor_offset=0)
CASES = [(INDEXED, 32, INDEX_BINDING), (FIXED, 1, FIXED_BINDING)]


def controls():
    for change in (dict(table_reg=6), dict(group_reg=10), dict(descriptor_offset=32), dict(stride=8)):
        must_reject(lambda: aot.lower(INDEXED, 32, **(INDEX_BINDING | change)))
    for old, new in (("lgkmcnt(0)", "lgkmcnt(1)"), ("s11, 5", "s11, 4"),
                     ("s[20:23], 0 idxen", "s[24:27], 0 idxen"), ("s13, 0", "s13, 1")):
        must_reject(lambda: aot.lower([s.replace(old, new) for s in INDEXED], 32, **INDEX_BINDING))
    must_reject(lambda: aot.lower(INDEXED[:6] + INDEXED[7:], 32, **INDEX_BINDING))
    must_reject(lambda: aot.lower(INDEXED[:7] + ["s_mov_b32 s21, 0"] + INDEXED[7:], 32, **INDEX_BINDING))
    must_reject(lambda: aot.lower(FIXED, 32, **FIXED_BINDING))
    must_reject(lambda: aot.lower(["s_endpgm"], 1, **FIXED_BINDING))
    must_reject(aot.group_width, bytes(52))


def binary(directory, assembler, objcopy, library):
    for lines, width, binding in CASES:
        src, obj, raw = [directory / x for x in ("test.s", "test.o", "test.bin")]
        src.write_text("\n".join(lines) + "\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj", src, "-o", obj], check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, raw], check=True)
        code = raw.read_bytes()
        padded = code + bytes.fromhex("00009fbf") * (4 - (len(code) // 4 + 10) % 4)
        payload = envelope(padded, directory_end=(40 + len(padded), 288 + len(padded)), compute_width=width)
        blob = _read_named_container(payload, 1 + len(b"fixture") + 1)
        sections = parts(blob)
        assert aot.group_width(sections[b"PSV0"]) == width
        assert aot.container_code(sections[b"DXIL"], stage=5) == code
        must_reject(lambda: aot.container_code(sections[b"DXIL"], stage=0))
        assert aot.lower(disassemble(code, library), width, **binding) == aot.lower(lines, width, **binding)
        container, output = directory / "input.dxbc", directory / "cli.hlsl"
        container.write_bytes(blob)
        options = [item for key, value in binding.items() for item in ("--" + key.replace("_", "-"), str(value))]
        subprocess.run([sys.executable, "-B", str(Path(aot.__file__)), container, "--output", output,
                        "--llvm", library, *options], check=True)
        assert output.read_text() == aot.lower(lines, width, **binding)


def draw(directory, compiler, renderer, backend):
    for lines, width, binding in CASES:
        src, cso, case = [directory / x for x in ("store.hlsl", "store.cso", "store.case")]
        src.write_text(aot.lower(lines, width, **binding), encoding="ascii")
        subprocess.run([compiler, "-T", "cs_6_0", "-E", "main", "-Fo", cso, src], check=True)
        cmd = [renderer, backend, "--compute-store-case", cso, case]
        for groups in ((1, 3) if width == 32 else (1,)):
            words = [SENTINEL] * 320
            if width == 1:
                words[5:8] = [11, 23, 0xfffffffe]
            else:
                for i in range(groups * 32):
                    words[3*i+1:3*i+3] = [19, 0xfffffffb]
            case.write_bytes(struct.pack("<321I", groups, *words))
            result = subprocess.run(cmd)
            if result.returncode:
                return result.returncode
        words[0] ^= 1
        case.write_bytes(struct.pack("<321I", groups, *words))
        bad = subprocess.run(cmd, capture_output=True, text=True)
        if bad.returncode != 1 or "word=0 expected=" not in bad.stderr:
            raise AssertionError("A wrong untouched word escaped detection")
        words[0] ^= 1
        words[5 if width == 1 else 1] ^= 1
        case.write_bytes(struct.pack("<321I", groups, *words))
        bad = subprocess.run(cmd, capture_output=True, text=True)
        if bad.returncode != 1 or "Compute readback differs" not in bad.stderr:
            raise AssertionError("A wrong stored word escaped detection")
    return 0


if __name__ == "__main__":
    controls()
    mode, *args = sys.argv[1:]
    with tempfile.TemporaryDirectory() as tmp:
        sys.exit({"binary": binary, "draw": draw}[mode](Path(tmp), *args))
