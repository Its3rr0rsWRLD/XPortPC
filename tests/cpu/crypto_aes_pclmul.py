"""Differential check for legacy and 128-bit VEX AES-NI and PCLMULQDQ lowering."""
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

EXPORTS = (
    "aesenc_op", "aesenclast_op", "aesdec_op", "aesdeclast_op",
    "aesimc_op", "aeskeygenassist_op", "pclmulqdq_00_op", "pclmulqdq_11_op",
    "vaesenc_op", "vaesenclast_op", "vaesdec_op", "vaesdeclast_op",
    "vaesimc_op", "vaeskeygenassist_op", "vpclmulqdq_01_op",
)

CPUID_HELPER = """#include <intrin.h>
extern "C" __declspec(dllexport) uint32_t host_has_aes_pclmul_avx() {
    int info[4]{};
    __cpuid(info, 1);
    const int need = (1 << 1) | (1 << 25) | (1 << 27) | (1 << 28);
    if ((info[2] & need) != need) return 0u;
    return (_xgetbv(0) & 6u) == 6u ? 1u : 0u;
}
"""


def emit(native_dll: Path, output_cpp: Path) -> None:
    parts = [INTEGER_HEADER, CPUID_HELPER]
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
    # 256-bit VAES vaesenc ymm0, ymm1, ymm2 (C4 E2 75 DC C2) followed by ret must be rejected.
    vaes256 = list(Decoder(64, b"\xc4\xe2\x75\xdc\xc2\xc3", ip=0x1000))
    try:
        lower(vaes256, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected 256-bit vaesenc to be rejected")

    # VAESENC xmm0, xmm3, xmm1; RET. XMM3 is outside the tracked profile.
    body = list(Decoder(64, bytes.fromhex("c4 e2 61 dc c1 c3"), ip=0x1000))
    try:
        lower(body, [], {}, {}, {})
    except ValueError as exc:
        if "unsupported crypto source at 0x1000" not in str(exc):
            raise AssertionError(f"unexpected VAESENC rejection: {exc}") from exc
    else:
        raise AssertionError("accepted an untracked VAESENC source")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    lifted = ctypes.CDLL(str(lifted_dll))
    lifted.host_has_aes_pclmul_avx.restype = ctypes.c_uint32
    if not lifted.host_has_aes_pclmul_avx():
        print("host lacks AES-NI/PCLMULQDQ/AVX; skipping native differential check")
        raise SystemExit(77)
    native = ctypes.CDLL(str(native_dll))

    # FIPS-197 Appendix B test vector bytes + mixed bit pattern for PCLMULQDQ.
    a_bytes = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
    b_bytes = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    a_buf = (ctypes.c_ubyte * 16)(*a_bytes)
    b_buf = (ctypes.c_ubyte * 16)(*b_bytes)
    out_n = (ctypes.c_ubyte * 16)()
    out_l = (ctypes.c_ubyte * 16)()
    for name in EXPORTS:
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_n))
        fn_l(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_l))
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: native={bytes(out_n).hex()} lifted={bytes(out_l).hex()}")
    print(f"{len(EXPORTS)} AES-NI and PCLMULQDQ (legacy + 128-bit VEX) cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
