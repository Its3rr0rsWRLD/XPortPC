"""Differential check for baseline 128-bit SSE/SSE2 packed conversions, compares, half moves, and scalar sqrt/min/max."""
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

EXPORTS = (
    "cvtdq2ps_op", "cvtdq2pd_op", "cvtps2dq_op", "cvtpd2dq_op",
    "cvttps2dq_op", "cvttpd2dq_op", "cvtps2pd_op", "cvtpd2ps_op",
    "cmpps_lt_op", "cmpps_unord_op", "cmppd_le_op", "cmppd_neq_op",
    "movhlps_op", "movlhps_op", "movlps_hps_op", "movlpd_hpd_op",
    "sqrtss_op", "minss_op", "maxss_op", "sqrtsd_op", "minsd_op", "maxsd_op",
)


def emit(native_dll: Path, output_cpp: Path) -> None:
    parts = [INTEGER_HEADER]
    with pefile.PE(str(native_dll), fast_load=True) as pe:
        for name in EXPORTS:
            ranges = function_ranges(pe, export_rva(pe, name))
            body = [ins for lo, hi in ranges for ins in region(pe, lo, hi)]
            code = lower(body, ["rcx = a; rdx = b; r8 = dst;"], {}, {}, {})
            parts.append(
                f'extern "C" __declspec(dllexport) uint64_t {name}(uint64_t a, uint64_t b, uint64_t dst) {{\n{code}\n}}'
            )
    output_cpp.write_text("\n".join(parts) + "\n", encoding="utf-8")


def check_controls() -> None:
    # VEX vcvtdq2ps xmm4, xmm1 (C5 F8 5B E1) followed by ret must be rejected: the AVX conversion
    # lowering owns VEX forms on XMM0-XMM3, and the legacy-only path must not take an unmodeled one.
    vex = list(Decoder(64, b"\xc5\xf8\x5b\xe1\xc3", ip=0x1000))
    try:
        lower(vex, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected VEX vcvtdq2ps xmm4 to be rejected")


def aligned_buf(data: bytes):
    raw = (ctypes.c_ubyte * 32)()
    off = (16 - (ctypes.addressof(raw) & 15)) & 15
    for i, v in enumerate(data):
        raw[off + i] = v
    return raw, ctypes.addressof(raw) + off, off


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    native = ctypes.CDLL(str(native_dll))
    lifted = ctypes.CDLL(str(lifted_dll))

    i32_vec = struct.pack("<4i", -2147483648, -3, 0, 2147483647)
    # Include ties, negative fraction, out-of-range (>=2^31), and qNaN.
    ps_cvt = struct.pack("<4f", 2.5, -2.5, 2147483648.0, float("nan"))
    pd_cvt = struct.pack("<2d", -3.5, 2147483647.5)
    ps_a = struct.pack("<4f", 1.5, -2.0, float("nan"), 0.0)
    ps_b = struct.pack("<4f", 4.0, -2.0, 1.0, -0.0)
    pd_a = struct.pack("<2d", 2.25, float("nan"))
    pd_b = struct.pack("<2d", 9.0, 2.25)

    for name in EXPORTS:
        if name in ("cvtdq2ps_op", "cvtdq2pd_op"):
            a, b = i32_vec, i32_vec
        elif name in ("cvtps2dq_op", "cvttps2dq_op", "cvtps2pd_op"):
            a, b = ps_cvt, ps_b
        elif name in ("cvtpd2dq_op", "cvttpd2dq_op", "cvtpd2ps_op"):
            a, b = pd_cvt, pd_b
        elif "pd" in name or "sd" in name:
            a, b = pd_a, pd_b
        else:
            a, b = ps_a, ps_b
        ra, pa, _ = aligned_buf(a)
        rb, pb, _ = aligned_buf(b)
        rn, pn, on = aligned_buf(b"\x00" * 16)
        rl, pl, ol = aligned_buf(b"\x00" * 16)
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(pa, pb, pn)
        fn_l(pa, pb, pl)
        got_n = bytes(rn[on:on + 16])
        got_l = bytes(rl[ol:ol + 16])
        if got_n != got_l:
            raise AssertionError(f"{name}: native={got_n.hex()} lifted={got_l.hex()}")
    print(f"{len(EXPORTS)} baseline 128-bit SSE/SSE2 conversion/compare/move/scalar cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
