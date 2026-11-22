"""Compare native and translated 32-bit and 64-bit ROL, ROR, SHLD, and SHRD instructions."""
import ctypes
from pathlib import Path
import sys

import pefile
from iced_x86 import Decoder

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64

ROT_CL = ("rol32_cl", "rol64_cl", "ror32_cl", "ror64_cl", "rol32_cl_zf")
ROT_IMM = ("rol32_imm", "ror64_imm")
SHD_CL = ("shld32_cl", "shld64_cl", "shrd32_cl", "shrd64_cl", "shld32_cl_zf")
SHD_IMM = ("shld32_imm", "shrd64_imm", "shld32_imm32")


def emit(image, output):
    parts = [INTEGER_HEADER]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in (*ROT_CL, *SHD_IMM):
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word out) {{\n{code}\n}}\n')
        for name in ROT_IMM:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word out) {{\n{code}\n}}\n')
        for name in SHD_CL:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = count; r9 = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word count, word out) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in (*ROT_CL, *SHD_IMM):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, ctypes.POINTER(U64)], U64
    for name in ROT_IMM:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, ctypes.POINTER(U64)], U64
    for name in SHD_CL:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, U64, ctypes.POINTER(U64)], U64
    return lib


def ref_rot(left, a, count, bits, seed_flags=2):
    mask = (1 << bits) - 1
    a &= mask
    c = count & (bits - 1)
    if c == 0:
        return a, seed_flags
    if left:
        v = ((a << c) | (a >> (bits - c))) & mask
        cf = (v & 1) << 1
    else:
        v = ((a >> c) | (a << (bits - c))) & mask
        cf = ((v >> (bits - 1)) & 1) << 1
    return v, cf | (seed_flags & 1)


def ref_shd(left, a, b, count, bits, seed_flags=2):
    mask = (1 << bits) - 1
    a &= mask
    b &= mask
    c = count & (bits - 1)
    if c == 0:
        return a, seed_flags
    if left:
        v = ((a << c) | (b >> (bits - c))) & mask
        cf = ((a >> (bits - c)) & 1) << 1
    else:
        v = ((a >> c) | (b << (bits - c))) & mask
        cf = ((a >> (c - 1)) & 1) << 1
    return v, cf | (1 if v == 0 else 0)


def check(native_path, lifted_path):
    native, lifted = load_lib(native_path), load_lib(lifted_path)
    slot = U64(0)
    values = (
        0, 1, 0x80000000, 0x12345678, 0xffffffff,
        0xdeadbeef00000000, 0xdeadbeef80000001, 0x0123456789abcdef,
        0x8000000000000000, 0xffffffffffffffff,
    )
    counts = (0, 1, 7, 15, 31, 32, 33, 63, 64, 65, 255)

    cases = 0
    for name, left, bits in (("rol32_cl", True, 32), ("rol64_cl", True, 64),
                             ("ror32_cl", False, 32), ("ror64_cl", False, 64)):
        for a in values:
            for count in counts:
                want_v, want_f = ref_rot(left, a, count, bits)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    slot.value = 0xdeadbeef
                    got = getattr(lib, name)(a, count, ctypes.byref(slot))
                    if (got, slot.value) != (want_v, want_f):
                        raise AssertionError(
                            f"{label} {name}({a:#x}, {count}) = ({got:#x}, {slot.value:#x}), "
                            f"expected ({want_v:#x}, {want_f:#x})"
                        )
                cases += 1

    for name, left, count, bits in (("rol32_imm", True, 7, 32), ("ror64_imm", False, 19, 64)):
        for a in values:
            want_v, want_f = ref_rot(left, a, count, bits, seed_flags=0)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                slot.value = 0xdeadbeef
                got = getattr(lib, name)(a, ctypes.byref(slot))
                if (got, slot.value) != (want_v, want_f):
                    raise AssertionError(
                        f"{label} {name}({a:#x}) = ({got:#x}, {slot.value:#x}), expected ({want_v:#x}, {want_f:#x})"
                    )
            cases += 1

    for name, left, bits in (("shld32_cl", True, 32), ("shld64_cl", True, 64),
                             ("shrd32_cl", False, 32), ("shrd64_cl", False, 64)):
        for a in values[:6]:
            for b in values[:6]:
                for count in counts:
                    want_v, want_f = ref_shd(left, a, b, count, bits)
                    for lib, label in ((native, "native"), (lifted, "lifted")):
                        slot.value = 0xdeadbeef
                        got = getattr(lib, name)(a, b, count, ctypes.byref(slot))
                        if (got, slot.value) != (want_v, want_f):
                            raise AssertionError(
                                f"{label} {name}({a:#x}, {b:#x}, {count}) = ({got:#x}, {slot.value:#x}), "
                                f"expected ({want_v:#x}, {want_f:#x})"
                            )
                    cases += 1

    for name, left, count, bits in (("shld32_imm", True, 13, 32), ("shrd64_imm", False, 21, 64)):
        for a in values:
            for b in values:
                want_v, want_f = ref_shd(left, a, b, count, bits, seed_flags=0)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    slot.value = 0xdeadbeef
                    got = getattr(lib, name)(a, b, ctypes.byref(slot))
                    if (got, slot.value) != (want_v, want_f):
                        raise AssertionError(
                            f"{label} {name}({a:#x}, {b:#x}) = ({got:#x}, {slot.value:#x}), "
                            f"expected ({want_v:#x}, {want_f:#x})"
                        )
                cases += 1

    for a in values:
        want_v, want_f = ref_shd(True, a, 0x12345678, 32, 32, seed_flags=1)
        for lib, label in ((native, "native"), (lifted, "lifted")):
            slot.value = 0xdeadbeef
            got = lib.shld32_imm32(a, 0x12345678, ctypes.byref(slot))
            if (got, slot.value) != (want_v, want_f):
                raise AssertionError(
                    f"{label} shld32_imm32({a:#x}) = ({got:#x}, {slot.value:#x}), expected ({want_v:#x}, {want_f:#x})"
                )
        cases += 1

    for a in values:
        for count in (0, 32, 64):
            want_v, want_f = ref_rot(True, a, count, 32, seed_flags=1)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                slot.value = 0xdeadbeef
                got = lib.rol32_cl_zf(a, count, ctypes.byref(slot))
                if (got, slot.value) != (want_v, want_f):
                    raise AssertionError(
                        f"{label} rol32_cl_zf({a:#x}, {count}) = ({got:#x}, {slot.value:#x}), expected ({want_v:#x}, {want_f:#x})"
                    )
            cases += 1
            want_v, want_f = ref_shd(True, a, 0x12345678, count, 32, seed_flags=1)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                slot.value = 0xdeadbeef
                got = lib.shld32_cl_zf(a, 0x12345678, count, ctypes.byref(slot))
                if (got, slot.value) != (want_v, want_f):
                    raise AssertionError(
                        f"{label} shld32_cl_zf({a:#x}, {count}) = ({got:#x}, {slot.value:#x}), expected ({want_v:#x}, {want_f:#x})"
                    )
            cases += 1

    print(f"{cases} rotate and double-precision shift cases (ROL, ROR, SHLD, SHRD) matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
    else:
        raise ValueError(mode)
