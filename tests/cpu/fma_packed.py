"""Compare native and translated packed FMA3 instructions (all 36 ps/pd forms)."""
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
KINDS = ("madd", "msub", "nmadd", "nmsub", "maddsub", "msubadd")
ORDERS = ("132", "213", "231")
EXPORTS = tuple(f"vf{k}{o}{s}_op" for k in KINDS for o in ORDERS for s in ("ps", "pd"))


def emit(image, output):
    parts = [
        "#include <intrin.h>\n",
        INTEGER_HEADER,
        'extern "C" __declspec(dllexport) int host_has_fma() {\n'
        "    int regs[4]{};\n"
        "    __cpuid(regs, 1);\n"
        "    if ((regs[2] & (1 << 27)) == 0 || (regs[2] & (1 << 12)) == 0) return 0;\n"
        "    return (_xgetbv(0) & 6ull) == 6ull;\n"
        "}\n",
    ]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = c; r9 = dst;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word c, word dst) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], U64
    return lib


def check(native_path, lifted_path):
    lifted = load_lib(lifted_path)
    lifted.host_has_fma.argtypes, lifted.host_has_fma.restype = [], ctypes.c_int
    if not lifted.host_has_fma():
        print("Host CPU/OS lacks FMA3 (CPUID leaf 1 ECX bit 12 / XCR0 YMM); skipping native differential check.")
        sys.exit(77)
    native = load_lib(native_path)
    out_n = (ctypes.c_uint8 * 32)()
    out_l = (ctypes.c_uint8 * 32)()

    qnan32 = struct.unpack("<f", struct.pack("<I", 0x7fc00123))[0]
    snan32 = struct.unpack("<f", struct.pack("<I", 0x7f800123))[0]
    qnan64 = struct.unpack("<d", struct.pack("<Q", 0x7ff8000012345678))[0]
    snan64 = struct.unpack("<d", struct.pack("<Q", 0x7ff0000012345678))[0]

    ps_a = struct.pack("<8f", 1.0 + 2.0**-23, 1.5, -2.25, 0.0, 1e20, snan32, 1.0, 1.0)
    ps_b = struct.pack("<8f", 1.0 - 2.0**-23, -2.25, 4.0, -0.0, 1e20, 4.5, qnan32, 2.0)
    ps_c = struct.pack("<8f", -1.0, 3.75, 0.5, 0.0, -1e38, -0.125, 1.25, qnan32)

    pd_a = struct.pack("<4d", 1.0 + 2.0**-52, snan64, 1.0, 1.0)
    pd_b = struct.pack("<4d", 1.0 - 2.0**-52, -2.25, qnan64, 2.0)
    pd_c = struct.pack("<4d", -1.0, 3.75, -0.125, qnan64)

    cases = 0
    for name in EXPORTS:
        a, b, c = (pd_a, pd_b, pd_c) if name.endswith("pd_op") else (ps_a, ps_b, ps_c)
        buf_a = ctypes.create_string_buffer(a, 32)
        buf_b = ctypes.create_string_buffer(b, 32)
        buf_c = ctypes.create_string_buffer(c, 32)
        ctypes.memset(out_n, 0xaa, 32)
        ctypes.memset(out_l, 0x55, 32)
        getattr(native, name)(buf_a, buf_b, buf_c, out_n)
        getattr(lifted, name)(buf_a, buf_b, buf_c, out_l)
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: lifted {bytes(out_l).hex()} != native {bytes(out_n).hex()}")
        cases += 1

    print(f"{cases} packed FMA3 vector cases across all 36 ps/pd forms matched native and translated DLLs bit-for-bit")


def check_rejections():
    # EVEX broadcast vfmadd132ps ymm0, ymm1, dword ptr [rdx]{1to8} (62 f2 75 38 98 02) must be rejected.
    insns = list(Decoder(64, bytes.fromhex("62 f2 75 38 98 02 c3"), ip=0x1000))
    assert insns[0].is_broadcast
    try:
        lower(insns, [], {}, {}, {})
    except ValueError as exc:
        if not str(exc).startswith("unsupported query operation at 0x1000"):
            raise AssertionError(f"unexpected diagnostic {exc}") from exc
    else:
        raise AssertionError("accepted EVEX broadcast vfmadd132ps")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check_rejections()
        check(native, other)
    else:
        raise ValueError(mode)
