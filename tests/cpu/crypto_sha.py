"""Differential check for all 7 SHA-NI instructions."""
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
    "sha1msg1_op", "sha1msg2_op", "sha1nexte_op",
    "sha1rnds4_0_op", "sha1rnds4_1_op", "sha1rnds4_2_op", "sha1rnds4_3_op",
    "sha256msg1_op", "sha256msg2_op", "sha256rnds2_op",
)

CPUID_HELPER = """#include <intrin.h>
extern "C" __declspec(dllexport) uint32_t host_has_sha() {
    int info[4]{};
    __cpuid(info, 0);
    if (info[0] < 7) return 0u;
    __cpuidex(info, 7, 0);
    return (info[1] & (1 << 29)) != 0 ? 1u : 0u;
}
"""


def emit(native_dll: Path, output_cpp: Path) -> None:
    parts = [INTEGER_HEADER, CPUID_HELPER]
    with pefile.PE(str(native_dll), fast_load=True) as pe:
        for name in EXPORTS:
            ranges = function_ranges(pe, export_rva(pe, name))
            body = [ins for lo, hi in ranges for ins in region(pe, lo, hi)]
            code = lower(body, ["rcx = a; rdx = b; r8 = dst; r9 = wk;"], {}, {}, {})
            parts.append(
                f'extern "C" __declspec(dllexport) uint64_t {name}(uint64_t a, uint64_t b, uint64_t dst, uint64_t wk) {{\n{code}\n}}'
            )
    output_cpp.write_text("\n".join(parts) + "\n", encoding="utf-8")


def check_controls() -> None:
    # Unmodeled register xmm4 in sha1msg1 xmm4, xmm0 (0F 38 C9 E0) followed by ret must be rejected.
    # (The AVX shuffle and shift lowerings model XMM0-XMM3, so xmm3 is no longer unmodeled.)
    bad = list(Decoder(64, b"\x0f\x38\xc9\xe0\xc3", ip=0x1000))
    try:
        lower(bad, [], {}, {}, {})
    except ValueError:
        pass
    else:
        raise AssertionError("expected unmodeled xmm4 in sha1msg1 to be rejected")


def check(native_dll: Path, lifted_dll: Path) -> None:
    check_controls()
    lifted = ctypes.CDLL(str(lifted_dll))
    lifted.host_has_sha.restype = ctypes.c_uint32
    if not lifted.host_has_sha():
        print("host lacks SHA-NI; skipping native differential check")
        raise SystemExit(77)
    native = ctypes.CDLL(str(native_dll))

    a_bytes = bytes.fromhex("67452301efcdab8998badcfe10325476")
    b_bytes = bytes.fromhex("c3d2e1f00123456789abcdef76543210")
    wk_bytes = bytes.fromhex("428a2f9871374491b5c0fbcf9b05688c")
    a_buf = (ctypes.c_ubyte * 16)(*a_bytes)
    b_buf = (ctypes.c_ubyte * 16)(*b_bytes)
    wk_buf = (ctypes.c_ubyte * 16)(*wk_bytes)
    out_n = (ctypes.c_ubyte * 16)()
    out_l = (ctypes.c_ubyte * 16)()
    for name in EXPORTS:
        fn_n, fn_l = getattr(native, name), getattr(lifted, name)
        fn_n.argtypes = fn_l.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
        fn_n.restype = fn_l.restype = ctypes.c_uint64
        fn_n(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_n), ctypes.addressof(wk_buf))
        fn_l(ctypes.addressof(a_buf), ctypes.addressof(b_buf), ctypes.addressof(out_l), ctypes.addressof(wk_buf))
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: native={bytes(out_n).hex()} lifted={bytes(out_l).hex()}")
    print(f"{len(EXPORTS)} SHA-NI cases matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:4]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(Path(native), Path(other))
    else:
        raise SystemExit(f"unknown mode {mode}")
