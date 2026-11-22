"""Differential check for VEX AVX packed shifts, packs, unpacks, shuffles, blends, movemask, and insert/extract."""
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

VEC_EXPORTS = (
    "vpsllw_imm_op", "vpslld_imm_op", "vpsllq_imm_op", "vpsrlw_reg_op", "vpsrlq_reg_op",
    "vpsraw_imm_op", "vpsrad_reg_op", "vpslldq_op",
    "vpacksswb_op", "vpackssdw_op", "vpackuswb_op", "vpackusdw_op",
    "vpunpcklbw_op", "vpunpcklwd_op", "vpunpckldq_op", "vpunpcklqdq_op",
    "vpunpckhbw_op", "vpunpckhwd_op", "vpunpckhdq_op", "vpunpckhqdq_op",
    "vpshufd_op", "vpshuflw_op", "vpshufhw_op", "vpblendw_op", "vpblendvb_op",
    "vpinsrb_op", "vpinsrw_op", "vpinsrd_op", "vpinsrq_op",
)
SCALAR_EXPORTS = ("vpmovmskb_op", "vpextrb_op", "vpextrw_op", "vpextrd_op", "vpextrq_op")
ALL_EXPORTS = VEC_EXPORTS + SCALAR_EXPORTS

CPUID_HELPER = """#include <intrin.h>
extern "C" __declspec(dllexport) uint32_t host_has_avx() {
    int info[4]{};
    __cpuid(info, 1);
    const int need = (1 << 27) | (1 << 28);
    if ((info[2] & need) != need) return 0u;
    return (_xgetbv(0) & 6u) == 6u ? 1u : 0u;
}
"""


def emit(native_dll: Path, output_cpp: Path) -> None:
    parts = [INTEGER_HEADER, CPUID_HELPER]
    with pefile.PE(str(native_dll), fast_load=True) as pe:
        for name in ALL_EXPORTS:
            ranges = function_ranges(pe, export_rva(pe, name))
            body = [ins for lo, hi in ranges for ins in region(pe, lo, hi)]
            code = lower(body, ["rcx = a; rdx = b; r8 = dst; r9 = mask;"], {}, {}, {})
            parts.append(
                f'extern "C" __declspec(dllexport) uint64_t {name}(uint64_t a, uint64_t b, uint64_t dst, uint64_t mask) {{\n{code}\n}}'
            )
    output_cpp.write_text("\n".join(parts) + "\n", encoding="utf-8")


def check_controls() -> None:
    # EVEX vpshufd xmm0{k1}, xmm1, 0x1B (62 F1 7D 09 70 C1 1B) followed by ret must be rejected.
    evex = list(Decoder(64, b"\x62\xf1\x7d\x09\x70\xc1\x1b\xc3", ip=0x1000))
    try:
        lower(evex, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected EVEX vpshufd to be rejected")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    lifted = ctypes.CDLL(str(lifted_dll))
    lifted.host_has_avx.restype = ctypes.c_uint32
    if not lifted.host_has_avx():
        print("host lacks AVX; skipping native differential check")
        raise SystemExit(77)
    native = ctypes.CDLL(str(native_dll))

    a_bytes = bytes([
        0x00, 0x80, 0x7f, 0x01, 0xff, 0x7f, 0x00, 0xfe,
        0x81, 0x00, 0x12, 0x34, 0xab, 0xcd, 0xef, 0x90,
    ]) + bytes([0xdd] * 16)
    b_bytes = bytes([
        0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x80, 0xff, 0x01, 0x02, 0x7f, 0x80, 0x00, 0x7f,
    ]) + bytes([0xee] * 16)
    m_bytes = bytes([
        0x00, 0x80, 0x7f, 0xff, 0x80, 0x00, 0xff, 0x01,
        0x80, 0x80, 0x00, 0x00, 0x7f, 0x80, 0x01, 0xff,
    ]) + bytes([0x11] * 16)
    a_buf = (ctypes.c_ubyte * 32)(*a_bytes)
    b_buf = (ctypes.c_ubyte * 32)(*b_bytes)
    m_buf = (ctypes.c_ubyte * 32)(*m_bytes)
    out_n = (ctypes.c_ubyte * 32)()
    out_l = (ctypes.c_ubyte * 32)()

    cases = 0
    for name in VEC_EXPORTS:
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_n), ctypes.addressof(m_buf))
        fn_l(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_l), ctypes.addressof(m_buf))
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: native={bytes(out_n).hex()} lifted={bytes(out_l).hex()}")
        cases += 1

    for name in SCALAR_EXPORTS:
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        got_n = fn_n(ctypes.addressof(a_buf), 0, 0, 0)
        got_l = fn_l(ctypes.addressof(a_buf), 0, 0, 0)
        if got_n != got_l:
            raise AssertionError(f"{name}: native={got_n:#x} lifted={got_l:#x}")
        cases += 1

    print(f"{cases} VEX AVX shift/pack/unpack/shuffle/blend/movemask/insert/extract cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
