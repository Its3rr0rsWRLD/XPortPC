"""Compare native and translated AVX2 broadcasts and variable per-lane vector shifts."""
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
BCAST_EXPORTS = ("bcast_b256", "bcast_w256", "bcast_d256", "bcast_q256", "bcast_d128_reg")
SHIFT_EXPORTS = ("sllvd256", "srlvd256", "sravd256", "sllvq256", "srlvq256")


def emit(image, output):
    parts = [
        "#include <intrin.h>\n",
        INTEGER_HEADER,
        'extern "C" __declspec(dllexport) int host_has_avx2() {\n'
        "    int regs[4]{};\n"
        "    __cpuid(regs, 0);\n"
        "    if (regs[0] < 7) return 0;\n"
        "    __cpuid(regs, 1);\n"
        "    if ((regs[2] & (1 << 27)) == 0) return 0;\n"
        "    if ((_xgetbv(0) & 6ull) != 6ull) return 0;\n"
        "    __cpuidex(regs, 7, 0);\n"
        "    return (regs[1] & (1 << 5)) != 0;\n"
        "}\n",
    ]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in BCAST_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = src; rdx = dst;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word src, word dst) {{\n{code}\n}}\n')
        for name in SHIFT_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = vals; rdx = counts; r8 = dst;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word vals, word counts, word dst) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in BCAST_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_void_p], U64
    for name in SHIFT_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p], U64
    return lib


def check(native_path, lifted_path):
    lifted = load_lib(lifted_path)
    lifted.host_has_avx2.argtypes, lifted.host_has_avx2.restype = [], ctypes.c_int
    if not lifted.host_has_avx2():
        print("Host CPU/OS lacks AVX2 (CPUID leaf 7 EBX bit 5 / XCR0 YMM); skipping native differential check.")
        sys.exit(77)
    native = load_lib(native_path)
    cases = 0

    src_buf = (ctypes.c_uint8 * 32)(*range(0x10, 0x30))
    dst_buf = (ctypes.c_uint8 * 32)()

    for name, elem_size in (("bcast_b256", 1), ("bcast_w256", 2), ("bcast_d256", 4), ("bcast_q256", 8)):
        want = bytes(src_buf[:elem_size]) * (32 // elem_size)
        for lib, label in ((native, "native"), (lifted, "lifted")):
            ctypes.memset(dst_buf, 0xaa, 32)
            getattr(lib, name)(src_buf, dst_buf)
            got = bytes(dst_buf)
            if got != want:
                raise AssertionError(f"{label} {name} = {got.hex()}, expected {want.hex()}")
        cases += 1

    want_128 = bytes(src_buf[:4]) * 4 + b"\x00" * 16
    for lib, label in ((native, "native"), (lifted, "lifted")):
        ctypes.memset(dst_buf, 0xff, 32)
        lib.bcast_d128_reg(src_buf, dst_buf)
        got = bytes(dst_buf)
        if got != want_128:
            raise AssertionError(f"{label} bcast_d128_reg = {got.hex()}, expected {want_128.hex()}")
    cases += 1

    vals32 = (0x00000000, 0x00000001, 0x7fffffff, 0x80000000, 0xffffffff, 0x12345678, 0x87654321, 0x55aa55aa)
    cnts32 = (0, 1, 7, 15, 31, 32, 33, 0xffffffff)
    v32_buf = ctypes.create_string_buffer(struct.pack("<8I", *vals32), 32)
    c32_buf = ctypes.create_string_buffer(struct.pack("<8I", *cnts32), 32)

    for name, fn in (
        ("sllvd256", lambda v, c: 0 if c >= 32 else (v << c) & 0xffffffff),
        ("srlvd256", lambda v, c: 0 if c >= 32 else v >> c),
        ("sravd256", lambda v, c: (((v - 0x100000000 if v & 0x80000000 else v) >> min(c, 31)) & 0xffffffff)),
    ):
        want = struct.pack("<8I", *(fn(v, c) for v, c in zip(vals32, cnts32)))
        for lib, label in ((native, "native"), (lifted, "lifted")):
            ctypes.memset(dst_buf, 0xaa, 32)
            getattr(lib, name)(v32_buf, c32_buf, dst_buf)
            got = bytes(dst_buf)
            if got != want:
                raise AssertionError(f"{label} {name} = {got.hex()}, expected {want.hex()}")
        cases += 1

    vals64 = (0x0123456789abcdef, 0x8000000000000000, 0xffffffffffffffff, 0x0000000000000001)
    cnts64_sets = ((0, 1, 63, 64), (7, 32, 65, 0xffffffffffffffff))
    v64_buf = ctypes.create_string_buffer(struct.pack("<4Q", *vals64), 32)
    for cnts64 in cnts64_sets:
        c64_buf = ctypes.create_string_buffer(struct.pack("<4Q", *cnts64), 32)
        for name, fn in (
            ("sllvq256", lambda v, c: 0 if c >= 64 else (v << c) & 0xffffffffffffffff),
            ("srlvq256", lambda v, c: 0 if c >= 64 else v >> c),
        ):
            want = struct.pack("<4Q", *(fn(v, c) for v, c in zip(vals64, cnts64)))
            for lib, label in ((native, "native"), (lifted, "lifted")):
                ctypes.memset(dst_buf, 0xaa, 32)
                getattr(lib, name)(v64_buf, c64_buf, dst_buf)
                got = bytes(dst_buf)
                if got != want:
                    raise AssertionError(f"{label} {name} = {got.hex()}, expected {want.hex()}")
            cases += 1

    print(f"{cases} AVX2 broadcast and variable-shift vector cases matched native and translated DLLs")


def check_rejections():
    # EVEX scalar-broadcast vpsllvd ymm0, ymm1, dword ptr [rdx]{1to8} (62 f2 75 38 47 02) must be rejected.
    insns = list(Decoder(64, bytes.fromhex("62 f2 75 38 47 02 c3"), ip=0x1000))
    assert insns[0].is_broadcast
    try:
        lower(insns, [], {}, {}, {})
    except ValueError as exc:
        if not str(exc).startswith("unsupported query operation at 0x1000"):
            raise AssertionError(f"unexpected diagnostic {exc}") from exc
    else:
        raise AssertionError("accepted EVEX broadcast vpsllvd")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check_rejections()
        check(native, other)
    else:
        raise ValueError(mode)
