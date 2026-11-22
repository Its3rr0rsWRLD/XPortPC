"""Differential check for SSE3 and SSE4.1 floating-point and data-movement lowering."""
import ctypes
import struct
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
    "addsubps_op", "addsubpd_op", "haddps_op", "haddpd_op", "hsubps_op", "hsubpd_op",
    "movddup_op", "movsldup_op", "movshdup_op", "lddqu_op",
    "blendps_op", "blendpd_op", "blendvps_op", "blendvpd_op",
    "dpps_op", "dppd_op",
    "roundps_nearest_op", "roundps_floor_op", "roundpd_ceil_op", "roundpd_trunc_op",
    "roundss_op", "roundsd_op",
)
ALL_EXPORTS = VEC_EXPORTS + ("extractps_op",)

CPUID_HELPER = """#include <intrin.h>
extern "C" __declspec(dllexport) uint32_t host_has_sse3_sse41() {
    int info[4]{};
    __cpuid(info, 1);
    return ((info[2] & (1 << 0)) != 0 && (info[2] & (1 << 19)) != 0) ? 1u : 0u;
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
    # roundps xmm0, xmm1, 0x04 (MXCSR rounding mode bit 2 set) followed by ret must be rejected.
    mxcsr_round = list(Decoder(64, b"\x66\x0f\x3a\x08\xc1\x04\xc3", ip=0x1000))
    try:
        lower(mxcsr_round, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected roundps with MXCSR rounding mode to be rejected")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    lifted = ctypes.CDLL(str(lifted_dll))
    lifted.host_has_sse3_sse41.restype = ctypes.c_uint32
    if not lifted.host_has_sse3_sse41():
        print("host lacks SSE3/SSE4.1; skipping native differential check")
        raise SystemExit(77)
    native = ctypes.CDLL(str(native_dll))

    ps_a = struct.pack("<4f", 2.5, -2.5, 3.5, -0.25)
    ps_b = struct.pack("<4f", 1.25, 4.5, -1.5, 2.0)
    ps_mask = struct.pack("<4I", 0x00000000, 0x80000000, 0x7FFFFFFF, 0xFFFFFFFF)

    pd_a = struct.pack("<2d", -3.5, 2.5)
    pd_b = struct.pack("<2d", 1.5, -4.25)
    pd_mask = struct.pack("<2Q", 0x8000000000000000, 0x7FFFFFFFFFFFFFFF)

    out_n = (ctypes.c_ubyte * 16)()
    out_l = (ctypes.c_ubyte * 16)()
    cases = 0
    for name in VEC_EXPORTS:
        is_pd = "pd" in name or "ddup" in name or "sd" in name
        a, b, m = (pd_a, pd_b, pd_mask) if is_pd else (ps_a, ps_b, ps_mask)
        a_buf = (ctypes.c_ubyte * 16)(*a)
        b_buf = (ctypes.c_ubyte * 16)(*b)
        m_buf = (ctypes.c_ubyte * 16)(*m)
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_n), ctypes.addressof(m_buf))
        fn_l(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_l), ctypes.addressof(m_buf))
        got_n, got_l = bytes(out_n), bytes(out_l)
        if got_n != got_l:
            raise AssertionError(f"{name}: native={got_n.hex()} lifted={got_l.hex()}")
        cases += 1

    # Check extractps_op (lane 2 of ps_a = 3.5f = 0x40600000).
    a_buf = (ctypes.c_ubyte * 16)(*ps_a)
    fn_n, fn_l = native.extractps_op, lifted.extractps_op
    fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
    fn_n.restype = fn_l.restype = ctypes.c_uint64
    got_n = fn_n(ctypes.addressof(a_buf), 0, 0, 0)
    got_l = fn_l(ctypes.addressof(a_buf), 0, 0, 0)
    expected = struct.unpack("<I", struct.pack("<f", 3.5))[0]
    if got_n != expected or got_l != expected:
        raise AssertionError(f"extractps_op: expected={expected:#x} native={got_n:#x} lifted={got_l:#x}")
    cases += 1
    print(f"{cases} SSE3/SSE4.1 floating-point and data-movement cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
