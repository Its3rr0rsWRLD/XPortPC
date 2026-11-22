"""Compare native and translated 128-bit SSE4.1 integer vector instructions."""
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
BIN_EXPORTS = (
    "pminsb_op", "pmaxsb_op", "pminuw_op", "pmaxuw_op",
    "pminsd_op", "pmaxsd_op", "pminud_op", "pmaxud_op",
    "pmulld_op", "pmuldq_op", "pcmpeqq_op", "packusdw_op", "pblendw_op",
)


def emit(image, output):
    parts = [
        "#include <intrin.h>\n",
        INTEGER_HEADER,
        'extern "C" __declspec(dllexport) int host_has_sse41() {\n'
        "    int regs[4]{};\n"
        "    __cpuid(regs, 1);\n"
        "    return (regs[2] & (1 << 19)) != 0;\n"
        "}\n",
    ]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in BIN_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = dst;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word dst) {{\n{code}\n}}\n')
        (bounds,) = function_ranges(pe, export_rva(pe, "pblendvb_op"))
        body = region(pe, *bounds)
        code = lower(body, ["rcx = a; rdx = b; r8 = mask; r9 = dst;"], {}, {}, {})
        parts.append(f'extern "C" __declspec(dllexport) word pblendvb_op(word a, word b, word mask, word dst) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def check_untracked_source():
    # pminsd xmm0, xmm3; ret. The profile only tracks xmm0 through xmm2.
    body = list(Decoder(64, bytes.fromhex("66 0f 38 39 c3 c3"), ip=0x1000))
    try:
        lower(body, [], {}, {}, {})
    except ValueError as exc:
        if "unsupported query operation at 0x1000" not in str(exc):
            raise AssertionError(f"unexpected SSE4.1 rejection: {exc}") from exc
    else:
        raise AssertionError("accepted an untracked XMM source")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in BIN_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], U64
    lib.pblendvb_op.argtypes, lib.pblendvb_op.restype = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], U64
    return lib


def check(native_path, lifted_path):
    lifted = load_lib(lifted_path)
    lifted.host_has_sse41.argtypes, lifted.host_has_sse41.restype = [], ctypes.c_int
    if not lifted.host_has_sse41():
        print("Host CPU lacks SSE4.1 (CPUID leaf 1 ECX bit 19); skipping native differential check.")
        sys.exit(77)
    native = load_lib(native_path)
    out_n = (ctypes.c_uint8 * 16)()
    out_l = (ctypes.c_uint8 * 16)()

    a_b = struct.pack("<16b", -128, -1, 0, 1, 127, -50, 50, -10, 10, 0, -128, 127, -2, 2, -99, 99)
    b_b = struct.pack("<16b", 127, 0, -1, -128, -128, 50, -50, -10, 10, 1, -128, 126, 2, -2, 100, -100)
    a_w = struct.pack("<8H", 0, 1, 0x7fff, 0x8000, 0xffff, 100, 50000, 0x1234)
    b_w = struct.pack("<8H", 0xffff, 0, 0x8000, 0x7fff, 0xfffe, 100, 40000, 0xabcd)
    a_d = struct.pack("<4i", -2147483648, -1, 0, 2147483647)
    b_d = struct.pack("<4i", 2147483647, -2147483648, 65536, -5)
    a_q = struct.pack("<2Q", 0x0123456789abcdef, 0xffffffffffffffff)
    b_q = struct.pack("<2Q", 0x0123456789abcdef, 0xfffffffffffffffe)
    mask = bytes([0x80, 0x00, 0xff, 0x7f, 0x81, 0x01, 0x00, 0x80, 0x90, 0x10, 0xaa, 0x55, 0x00, 0xff, 0x7f, 0x80])

    cases = 0
    for name, a, b in (
        ("pminsb_op", a_b, b_b), ("pmaxsb_op", a_b, b_b),
        ("pminuw_op", a_w, b_w), ("pmaxuw_op", a_w, b_w),
        ("pminsd_op", a_d, b_d), ("pmaxsd_op", a_d, b_d),
        ("pminud_op", a_d, b_d), ("pmaxud_op", a_d, b_d),
        ("pmulld_op", a_d, b_d), ("pmuldq_op", a_d, b_d),
        ("pcmpeqq_op", a_q, b_q), ("packusdw_op", a_d, b_d),
        ("pblendw_op", a_w, b_w),
    ):
        ba, bb = ctypes.create_string_buffer(a, 16), ctypes.create_string_buffer(b, 16)
        ctypes.memset(out_n, 0xaa, 16)
        ctypes.memset(out_l, 0x55, 16)
        getattr(native, name)(ba, bb, out_n)
        getattr(lifted, name)(ba, bb, out_l)
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: lifted {bytes(out_l).hex()} != native {bytes(out_n).hex()}")
        cases += 1

    ba, bb, bm = ctypes.create_string_buffer(a_b, 16), ctypes.create_string_buffer(b_b, 16), ctypes.create_string_buffer(mask, 16)
    ctypes.memset(out_n, 0xaa, 16)
    ctypes.memset(out_l, 0x55, 16)
    native.pblendvb_op(ba, bb, bm, out_n)
    lifted.pblendvb_op(ba, bb, bm, out_l)
    if bytes(out_n) != bytes(out_l):
        raise AssertionError(f"pblendvb_op: lifted {bytes(out_l).hex()} != native {bytes(out_n).hex()}")
    cases += 1

    print(f"{cases} SSE4.1 integer vector cases across 14 instructions matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check_untracked_source()
        check(native, other)
    else:
        raise ValueError(mode)
