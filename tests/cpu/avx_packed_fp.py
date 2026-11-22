"""Differential check for AVX 256-bit packed floating-point lowering."""
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

PS_EXPORTS = (
    "vaddps_op", "vsubps_op", "vmulps_op", "vdivps_op", "vsqrtps_op",
    "vminps_op", "vmaxps_op", "vandps_op", "vandnps_op", "vorps_op", "vxorps_op",
    "vaddsubps_op", "vhaddps_op", "vhsubps_op",
)
PD_EXPORTS = (
    "vaddpd_op", "vsubpd_op", "vmulpd_op", "vdivpd_op", "vsqrtpd_op",
    "vminpd_op", "vmaxpd_op", "vandpd_op", "vandnpd_op", "vorpd_op", "vxorpd_op",
    "vaddsubpd_op", "vhaddpd_op", "vhsubpd_op",
)
ALL_EXPORTS = PS_EXPORTS + ("vmovmskps_op",) + PD_EXPORTS + ("vmovmskpd_op",)

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
            code = lower(body, ["rcx = a; rdx = b; r8 = dst;"], {}, {}, {})
            parts.append(
                f'extern "C" __declspec(dllexport) uint64_t {name}(uint64_t a, uint64_t b, uint64_t dst) {{\n{code}\n}}'
            )
    output_cpp.write_text("\n".join(parts) + "\n", encoding="utf-8")


def check_controls() -> None:
    # EVEX vaddps ymm0{k1}, ymm1, ymm2 (62 F1 74 29 58 C2) followed by ret must be rejected.
    evex = list(Decoder(64, b"\x62\xf1\x74\x29\x58\xc2\xc3", ip=0x1000))
    try:
        lower(evex, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected EVEX vaddps to be rejected")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    lifted = ctypes.CDLL(str(lifted_dll))
    lifted.host_has_avx.restype = ctypes.c_uint32
    if not lifted.host_has_avx():
        print("host lacks AVX; skipping native differential check")
        raise SystemExit(77)
    native = ctypes.CDLL(str(native_dll))

    ps_a = struct.pack("<8f", 1.5, -2.25, 0.0, 9.0, -4.5, 3.25, -0.0, 16.0)
    ps_b = struct.pack("<8f", 2.0, 4.0, -0.0, 3.0, 1.5, -2.5, 0.0, 8.0)
    ps_sqrt = struct.pack("<8f", 0.0, -0.0, 2.25, 16.0, 9.0, 6.25, 1.0, 25.0)
    pd_a = struct.pack("<4d", -3.5, 12.25, 0.0, -0.0)
    pd_b = struct.pack("<4d", 1.75, -2.5, -0.0, 0.0)
    pd_sqrt = struct.pack("<4d", -0.0, 20.25, 0.0, 49.0)

    out_n = (ctypes.c_ubyte * 32)()
    out_l = (ctypes.c_ubyte * 32)()
    cases = 0
    for name in PS_EXPORTS + PD_EXPORTS:
        is_pd = "pd" in name
        if name == "vsqrtps_op":
            a, b = ps_sqrt, ps_b
        elif name == "vsqrtpd_op":
            a, b = pd_sqrt, pd_b
        elif is_pd:
            a, b = pd_a, pd_b
        else:
            a, b = ps_a, ps_b
        a_buf = (ctypes.c_ubyte * 32)(*a)
        b_buf = (ctypes.c_ubyte * 32)(*b)
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_n))
        fn_l(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_l))
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: native={bytes(out_n).hex()} lifted={bytes(out_l).hex()}")
        cases += 1

    for name, vec, exp in (
        ("vmovmskps_op", ps_a, 0b01010010),
        ("vmovmskpd_op", pd_a, 0b1001),
    ):
        buf = (ctypes.c_ubyte * 32)(*vec)
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        got_n, got_l = fn_n(ctypes.addressof(buf), 0, 0), fn_l(ctypes.addressof(buf), 0, 0)
        if got_n != exp or got_l != exp:
            raise AssertionError(f"{name}: expected={exp:#x} native={got_n:#x} lifted={got_l:#x}")
        cases += 1

    print(f"{cases} AVX 256-bit packed FP cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
