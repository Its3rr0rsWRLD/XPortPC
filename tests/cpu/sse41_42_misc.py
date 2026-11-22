"""Differential check for SSSE3/SSE4.1/SSE4.2 integer, insert/extract, ptest, and crc32 lowering."""
import ctypes
import sys
from pathlib import Path

import pefile
from iced_x86 import Decoder

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

ALL_EXPORTS = (
    "pextrb_op", "pextrw_op", "pextrd_op", "pextrq_op",
    "pinsrb_op", "pinsrw_op", "pinsrd_op", "pinsrq_op",
    "pmaddubsw_op", "pmulhrsw_op", "phminposuw_op", "ptest_op",
    "mpsadbw_op", "movntdqa_op", "pcmpgtq_op",
    "crc32_8_op", "crc32_32_op", "crc32_64_op",
)
VEC_EXPORTS = (
    "pinsrb_op", "pinsrw_op", "pinsrd_op", "pinsrq_op",
    "pmaddubsw_op", "pmulhrsw_op", "phminposuw_op",
    "mpsadbw_op", "movntdqa_op", "pcmpgtq_op",
)

CPUID_HELPER = """#include <intrin.h>
extern "C" __declspec(dllexport) uint32_t host_has_sse42() {
    int info[4]{};
    __cpuid(info, 1);
    const int need = (1 << 9) | (1 << 19) | (1 << 20);
    return (info[2] & need) == need ? 1u : 0u;
}
"""


def emit(native_dll: Path, output_cpp: Path) -> None:
    parts = [INTEGER_HEADER, CPUID_HELPER]
    with pefile.PE(str(native_dll), fast_load=True) as pe:
        for name in ALL_EXPORTS:
            ranges = function_ranges(pe, export_rva(pe, name))
            body = [ins for lo, hi in ranges for ins in region(pe, lo, hi)]
            code = lower(body, ["rcx = a; rdx = b; r8 = dst;"], {}, {}, {})
            parts.append(
                f'extern "C" __declspec(dllexport) uint64_t {name}(uint64_t a, uint64_t b, uint64_t dst) {{\n{code}\n}}'
            )
    output_cpp.write_text("\n".join(parts) + "\n", encoding="utf-8")


def check_controls() -> None:
    # 64-bit MMX pmulhrsw mm0, mm1 (0F 38 0B C1) followed by ret must be rejected.
    mmx = list(Decoder(64, b"\x0f\x38\x0b\xc1\xc3", ip=0x1000))
    try:
        lower(mmx, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected 64-bit MMX pmulhrsw to be rejected")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    lifted = ctypes.CDLL(str(lifted_dll))
    lifted.host_has_sse42.restype = ctypes.c_uint32
    if not lifted.host_has_sse42():
        print("host lacks SSSE3/SSE4.1/SSE4.2; skipping native differential check")
        raise SystemExit(77)
    native = ctypes.CDLL(str(native_dll))

    # Allocate 32 bytes and take a 16-byte aligned slice for movntdqa.
    raw_a = (ctypes.c_ubyte * 32)()
    off_a = (16 - (ctypes.addressof(raw_a) & 15)) & 15
    a_bytes = bytes([
        0xff, 0x80, 0x00, 0x80, 0x05, 0x00, 0x05, 0x00,
        0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
    ])
    b_bytes = bytes([
        0x7f, 0x80, 0x00, 0x80, 0xfe, 0x01, 0x02, 0x03,
        0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x7f,
    ])
    for i, v in enumerate(a_bytes):
        raw_a[off_a + i] = v
    a_ptr = ctypes.addressof(raw_a) + off_a
    b_buf = (ctypes.c_ubyte * 16)(*b_bytes)
    b_ptr = ctypes.addressof(b_buf)
    out_n = (ctypes.c_ubyte * 16)()
    out_l = (ctypes.c_ubyte * 16)()

    cases = 0
    for name in VEC_EXPORTS:
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(a_ptr, b_ptr, ctypes.addressof(out_n))
        fn_l(a_ptr, b_ptr, ctypes.addressof(out_l))
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: native={bytes(out_n).hex()} lifted={bytes(out_l).hex()}")
        cases += 1

    for name in ("pextrb_op", "pextrw_op", "pextrd_op", "pextrq_op"):
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        got_n, got_l = fn_n(a_ptr, 0, 0), fn_l(a_ptr, 0, 0)
        if got_n != got_l:
            raise AssertionError(f"{name}: native={got_n:#x} lifted={got_l:#x}")
        cases += 1

    # Test all 4 (ZF, CF) combinations for ptest.
    for x, y, exp_flags in (
        (b"\x00" * 16, b"\x00" * 16, 3),  # ZF=1, CF=1
        (b"\x0f" * 16, b"\xf0" * 16, 1),  # ZF=1, CF=0
        (b"\xff" * 16, b"\x0f" * 16, 2),  # ZF=0, CF=1
        (b"\x0f" * 16, b"\xff" * 16, 0),  # ZF=0, CF=0
    ):
        xb = (ctypes.c_ubyte * 16)(*x)
        yb = (ctypes.c_ubyte * 16)(*y)
        native.ptest_op.argtypes = lifted.ptest_op.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        native.ptest_op.restype = lifted.ptest_op.restype = ctypes.c_uint64
        got_n = native.ptest_op(ctypes.addressof(xb), ctypes.addressof(yb), 0)
        got_l = lifted.ptest_op(ctypes.addressof(xb), ctypes.addressof(yb), 0)
        if got_n != exp_flags or got_l != exp_flags:
            raise AssertionError(f"ptest_op: expected={exp_flags} native={got_n} lifted={got_l}")
        cases += 1

    for name, seed, data in (
        ("crc32_8_op", 0x12345678, 0xAB),
        ("crc32_32_op", 0xDEADBEEF, 0x01234567),
        ("crc32_64_op", 0xFFFFFFFF12345678, 0x0123456789ABCDEF),
    ):
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        got_n, got_l = fn_n(seed, data, 0), fn_l(seed, data, 0)
        if got_n != got_l:
            raise AssertionError(f"{name}: native={got_n:#x} lifted={got_l:#x}")
        cases += 1

    print(f"{cases} SSSE3/SSE4.1/SSE4.2 misc cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
