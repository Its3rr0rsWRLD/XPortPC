"""Compare native and translated 128-bit baseline SSE2 packed integer ALU instructions."""
import ctypes
from pathlib import Path
import struct
import sys

import pefile
from iced_x86 import Decoder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64
EXPORTS = tuple(f"{op}_op" for op in (
    "paddb", "paddw", "paddd", "paddq", "psubb", "psubw", "psubd", "psubq",
    "pand", "pandn", "por", "pxor", "pcmpeqb", "pcmpeqw", "pcmpeqd", "pcmpgtb", "pcmpgtw", "pcmpgtd",
))


def emit(image, output):
    parts = [INTEGER_HEADER]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = dst;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word dst) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], U64
    return lib


def check(native_path, lifted_path):
    native, lifted = load_lib(native_path), load_lib(lifted_path)
    out_n = (ctypes.c_uint8 * 16)()
    out_l = (ctypes.c_uint8 * 16)()

    a = struct.pack("<16b", -128, -1, 0, 1, 127, -50, 50, 0, -1, 127, -128, 42, -42, 10, -10, 100)
    b = struct.pack("<16b", -128, 1, 0, -1, 1, -50, 51, -1, -1, -128, 127, 42, -41, 11, -10, 100)
    ba, bb = ctypes.create_string_buffer(a, 16), ctypes.create_string_buffer(b, 16)

    cases = 0
    for name in EXPORTS:
        ctypes.memset(out_n, 0xaa, 16)
        ctypes.memset(out_l, 0x55, 16)
        getattr(native, name)(ba, bb, out_n)
        getattr(lifted, name)(ba, bb, out_l)
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: lifted {bytes(out_l).hex()} != native {bytes(out_n).hex()}")
        cases += 1

    print(f"{cases} baseline 128-bit SSE2 packed integer ALU cases matched native and translated DLLs")


def check_rejections():
    # 64-bit MMX paddb mm0, mm1 (0f fc c1) must be rejected (only 128-bit XMM is lowered).
    insns = list(Decoder(64, bytes.fromhex("0f fc c1 c3"), ip=0x1000))
    try:
        lower(insns, [], {}, {}, {})
    except ValueError as exc:
        if not str(exc).startswith("unsupported query operation at 0x1000"):
            raise AssertionError(f"unexpected diagnostic {exc}") from exc
    else:
        raise AssertionError("accepted MMX paddb")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check_rejections()
        check(native, other)
    else:
        raise ValueError(mode)
