"""Compare native and translated 128-bit SSE4.1 pmovsx/pmovzx instructions."""
import ctypes
from pathlib import Path
import struct
import sys

import pefile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64
EXPORTS = tuple(f"pmov{k}{p}_op" for k in ("sx", "zx") for p in ("bw", "bd", "bq", "wd", "wq", "dq")) + ("pmovsxbd_mem",)


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
        for name in EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = src; rdx = dst;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word src, word dst) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_void_p], U64
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

    # Mix negative, positive, zero, and sign-bit boundary bytes/words/dwords.
    src_bytes = bytes([0x80, 0xff, 0x00, 0x7f, 0x81, 0x01, 0xfe, 0x7e,
                       0x00, 0x80, 0xff, 0x7f, 0x12, 0x34, 0x89, 0xab])
    src_buf = ctypes.create_string_buffer(src_bytes, 16)

    cases = 0
    for name in EXPORTS:
        ctypes.memset(out_n, 0xaa, 16)
        ctypes.memset(out_l, 0x55, 16)
        getattr(native, name)(src_buf, out_n)
        getattr(lifted, name)(src_buf, out_l)
        if bytes(out_n) != bytes(out_l):
            raise AssertionError(f"{name}: lifted {bytes(out_l).hex()} != native {bytes(out_n).hex()}")
        cases += 1

    print(f"{cases} SSE4.1 pmovsx/pmovzx cases (including narrow memory source) matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
    else:
        raise ValueError(mode)
