"""Compare native and translated signed and flag-conditional operations:
CMOVcc, SETcc, Jcc, NEG, and CWD."""
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

COND_SUFFIXES = ("l", "ge", "le", "g", "s", "ns", "o", "no")
CMOV_EXPORTS = tuple(f"cmov{s}{b}" for s in COND_SUFFIXES for b in (32, 64))
SET_EXPORTS = tuple(f"set{s}_op" for s in COND_SUFFIXES)
BRANCH_EXPORTS = tuple(f"j{s}_branch" for s in COND_SUFFIXES)
NEG_EXPORTS = ("neg32", "neg64")
ALL_EXPORTS = CMOV_EXPORTS + SET_EXPORTS + BRANCH_EXPORTS + NEG_EXPORTS + ("cwd_op",)


def emit(image, output):
    parts = ["#include <intrin.h>\n", INTEGER_HEADER]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in CMOV_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = alt;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word alt) {{\n{code}\n}}\n')
        for name in SET_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b) {{\n{code}\n}}\n')
        for name in BRANCH_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b) {{\n{code}\n}}\n')
        for name in NEG_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word out) {{\n{code}\n}}\n')
        (bounds,) = function_ranges(pe, export_rva(pe, "cwd_op"))
        body = region(pe, *bounds)
        code = lower(body, ["rcx = a;"], {}, {}, {})
        parts.append(f'extern "C" __declspec(dllexport) word cwd_op(word a) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in CMOV_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, U64], U64
    for name in SET_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64], U64
    for name in BRANCH_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64], U64
    for name in NEG_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, ctypes.POINTER(U64)], U64
    lib.cwd_op.argtypes, lib.cwd_op.restype = [U64], U64
    return lib


def to_signed(v, bits):
    sign = 1 << (bits - 1)
    mask = (1 << bits) - 1
    v = v & mask
    return v - (1 << bits) if v >= sign else v


def ref_pred(cc, a, b, bits):
    sa = to_signed(a, bits)
    sb = to_signed(b, bits)
    diff = sa - sb
    sign_bit = 1 << (bits - 1)
    max_val = sign_bit - 1
    min_val = -sign_bit
    overflow = diff < min_val or diff > max_val
    s_flag = bool((a - b) & sign_bit)

    if cc == "l":
        return sa < sb
    elif cc == "ge":
        return sa >= sb
    elif cc == "le":
        return sa <= sb
    elif cc == "g":
        return sa > sb
    elif cc == "s":
        return s_flag
    elif cc == "ns":
        return not s_flag
    elif cc == "o":
        return overflow
    elif cc == "no":
        return not overflow
    raise ValueError(cc)


def ref_neg(a, bits):
    mask = (1 << bits) - 1
    sign_bit = 1 << (bits - 1)
    a_masked = a & mask
    res = (0 - a_masked) & mask
    cf = 1 if a_masked != 0 else 0
    of = 1 if a_masked == sign_bit else 0
    sf = 1 if (res & sign_bit) != 0 else 0
    zf = 1 if res == 0 else 0
    packed_flags = cf | (of << 1) | (sf << 2) | (zf << 3)
    return res, packed_flags


def ref_cwd(a):
    ax = a & 0xffff
    sign = (ax & 0x8000) != 0
    dx = 0xffff if sign else 0
    return (dx << 16) | ax


def check(native_path, lifted_path):
    native, lifted = load_lib(native_path), load_lib(lifted_path)
    both = ((native, "native"), (lifted, "lifted"))
    slot = U64(0)
    alt = 0xabcdef0123456789

    vals = (
        0, 1, 2, 0x7f, 0x80, 0xff, 0x100, 0x7fff, 0x8000, 0xffff,
        0x7fffffff, 0x80000000, 0x80000001, 0xffffffff,
        0xdeadbeef00000000, 0xdeadbeef00000001,
        0x7fffffffffffffff, 0x8000000000000000, 0x8000000000000001, 0xffffffffffffffff,
    )

    cases = 0

    # 1. CMOVcc across 32-bit and 64-bit widths
    for suffix in COND_SUFFIXES:
        for bits, init in ((32, 0x11), (64, 0x1122334455667788)):
            name = f"cmov{suffix}{bits}"
            mask = (1 << bits) - 1
            for a in vals:
                for b in vals:
                    want = (alt & mask) if ref_pred(suffix, a, b, bits) else init
                    for lib, label in both:
                        got = getattr(lib, name)(a, b, alt)
                        if got != want:
                            raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) = {got:#x}, expected {want:#x}")
                    cases += 1

    # 2. SETcc (64-bit comparison, byte destination preserves upper 56 bits)
    for suffix in COND_SUFFIXES:
        name = f"set{suffix}_op"
        for a in vals:
            for b in vals:
                want = 0x123456789abcde00 | (1 if ref_pred(suffix, a, b, 64) else 0)
                for lib, label in both:
                    got = getattr(lib, name)(a, b)
                    if got != want:
                        raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) = {got:#x}, expected {want:#x}")
                cases += 1

    # 3. Jcc branches (64-bit comparison, returns 1 if branch taken, 0 otherwise)
    for suffix in COND_SUFFIXES:
        name = f"j{suffix}_branch"
        for a in vals:
            for b in vals:
                want = 1 if ref_pred(suffix, a, b, 64) else 0
                for lib, label in both:
                    got = getattr(lib, name)(a, b)
                    if got != want:
                        raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) = {got:#x}, expected {want:#x}")
                cases += 1

    # 4. NEG (32-bit and 64-bit with packed CF, OF, SF, ZF flags)
    for name, bits in (("neg32", 32), ("neg64", 64)):
        for a in vals:
            want_res, want_flags = ref_neg(a, bits)
            for lib, label in both:
                slot.value = 0xdeadbeef
                got = getattr(lib, name)(a, ctypes.byref(slot))
                if (got, slot.value) != (want_res, want_flags):
                    raise AssertionError(
                        f"{label} {name}({a:#x}) = ({got:#x}, {slot.value:#x}), expected ({want_res:#x}, {want_flags:#x})"
                    )
            cases += 1

    # 5. CWD (AX sign-extended into DX:AX)
    for a in vals:
        want = ref_cwd(a)
        for lib, label in both:
            got = lib.cwd_op(a)
            if got != want:
                raise AssertionError(f"{label} cwd_op({a:#x}) = {got:#x}, expected {want:#x}")
        cases += 1

    print(f"{cases} signed condition and flag-op cases (CMOVcc, SETcc, Jcc, NEG, CWD) matched native and translated DLLs")


def check_negative_controls():
    # 1. Unconditional volatile read for memory-operand CMOVcc
    # 41 0F 4C 00 = cmovl eax, dword ptr [r8]
    emitted = lower(list(Decoder(64, bytes.fromhex("39 c9 41 0f 4c 00 c3"), ip=0x1000)), [], {}, {}, {})
    if "load_always<uint32_t>(r8 + 0ull)" not in emitted:
        raise AssertionError(f"expected unconditional volatile read for CMOV memory source:\n{emitted}")

    # 2. Rejection of unhandled / malformed operations
    # UD2 should be rejected cleanly with ValueError
    try:
        lower(list(Decoder(64, bytes.fromhex("0f 0b c3"), ip=0x1000)), [], {}, {}, {})
    except ValueError as exc:
        if "unsupported query operation" not in str(exc):
            raise AssertionError(f"unexpected diagnostic: {exc}") from exc
    else:
        raise AssertionError("accepted UD2 instruction")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check_negative_controls()
        check(native, other)
    else:
        raise ValueError(mode)
