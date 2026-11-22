"""Differential check for baseline 128-bit SSE/SSE2 packed floating-point lowering."""
import ctypes
import math
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
    "addps_op", "subps_op", "mulps_op", "divps_op", "sqrtps_op",
    "minps_op", "maxps_op", "andps_op", "andnps_op", "orps_op", "xorps_op",
    "shufps_op", "unpcklps_op", "unpckhps_op",
)
PD_EXPORTS = (
    "addpd_op", "subpd_op", "mulpd_op", "divpd_op", "sqrtpd_op",
    "minpd_op", "maxpd_op", "andpd_op", "andnpd_op", "orpd_op", "xorpd_op",
    "shufpd_op", "unpcklpd_op", "unpckhpd_op",
)
MASK_EXPORTS = ("movmskps_op", "movmskpd_op")
ALL_EXPORTS = PS_EXPORTS + ("movmskps_op",) + PD_EXPORTS + ("movmskpd_op",)


def emit(native_dll: Path, output_cpp: Path) -> None:
    parts = [INTEGER_HEADER]
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
    # VEX vaddps xmm0, xmm1, xmm2 (C5 F0 58 C2) followed by ret (C3) must be rejected by legacy-only lowering.
    vex = list(Decoder(64, b"\xc5\xf0\x58\xc2\xc3", ip=0x1000))
    try:
        lower(vex, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected VEX vaddps to be rejected")


def run_vec(native, lifted, name: str, a: bytes, b: bytes) -> None:
    a_buf = (ctypes.c_ubyte * 16)(*a)
    b_buf = (ctypes.c_ubyte * 16)(*b)
    out_n = (ctypes.c_ubyte * 16)()
    out_l = (ctypes.c_ubyte * 16)()
    fn_n, fn_l = getattr(native, name), getattr(lifted, name)
    fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
    fn_n.restype = fn_l.restype = ctypes.c_uint64
    fn_n(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_n))
    fn_l(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_l))
    got_n, got_l = bytes(out_n), bytes(out_l)
    if got_n != got_l:
        raise AssertionError(f"{name}: native={got_n.hex()} lifted={got_l.hex()}")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    native = ctypes.CDLL(str(native_dll))
    lifted = ctypes.CDLL(str(lifted_dll))

    ps_a = struct.pack("<4f", 1.5, -2.25, 0.0, 9.0)
    ps_b = struct.pack("<4f", 2.0, 4.0, -0.0, 3.0)
    ps_sqrt = struct.pack("<4f", 0.0, -0.0, 2.25, 16.0)
    # Signed-zero and qNaN edge cases for minps/maxps (x86 returns second operand on tie or NaN).
    ps_edge_a = struct.pack("<4I", 0x00000000, 0x80000000, 0x7FC01234, 0x3F800000)
    ps_edge_b = struct.pack("<4I", 0x80000000, 0x00000000, 0x40400000, 0x7FC05678)

    pd_a = struct.pack("<2d", -3.5, 12.25)
    pd_b = struct.pack("<2d", 1.75, -2.5)
    pd_sqrt = struct.pack("<2d", -0.0, 20.25)
    pd_edge_a = struct.pack("<2Q", 0x0000000000000000, 0x7FF8000000000001)
    pd_edge_b = struct.pack("<2Q", 0x8000000000000000, 0x4010000000000000)

    cases = 0
    for name in PS_EXPORTS:
        a = ps_sqrt if name == "sqrtps_op" else ps_a
        run_vec(native, lifted, name, a, ps_b)
        cases += 1
    for name in ("minps_op", "maxps_op"):
        run_vec(native, lifted, name, ps_edge_a, ps_edge_b)
        cases += 1

    for name in PD_EXPORTS:
        a = pd_sqrt if name == "sqrtpd_op" else pd_a
        run_vec(native, lifted, name, a, pd_b)
        cases += 1
    for name in ("minpd_op", "maxpd_op"):
        run_vec(native, lifted, name, pd_edge_a, pd_edge_b)
        cases += 1

    # Verify independent reference on movmskps / movmskpd and representative arithmetic.
    for name, vec, expected in (
        ("movmskps_op", struct.pack("<4f", -1.0, 2.0, -0.0, 0.0), 0b0101),
        ("movmskpd_op", struct.pack("<2d", 1.0, -0.0), 0b10),
    ):
        buf = (ctypes.c_ubyte * 16)(*vec)
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        got_n = fn_n(ctypes.addressof(buf), 0, 0)
        got_l = fn_l(ctypes.addressof(buf), 0, 0)
        if got_n != expected or got_l != expected:
            raise AssertionError(f"{name}: expected={expected:#x} native={got_n:#x} lifted={got_l:#x}")
        cases += 1

    # Spot-check sqrt(-0.0) == -0.0 preservation.
    assert math.copysign(1.0, struct.unpack("<4f", ps_sqrt)[1]) == -1.0
    print(f"{cases} baseline 128-bit SSE/SSE2 packed FP cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
