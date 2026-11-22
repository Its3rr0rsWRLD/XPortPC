"""Compare native and translated MUL, DIV, IDIV, XADD, and CMPXCHG instructions."""
import ctypes
from pathlib import Path
import sys

import pefile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64
EXPORTS = ("mul32_op", "mul64_op", "div32_op", "div64_op", "idiv32_op", "idiv64_op",
           "xadd32_op", "xadd64_op", "cmpxchg32_op", "cmpxchg64_op", "xadd64_mem")


def emit(image, output):
    parts = [INTEGER_HEADER]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = c; r9 = d;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word c, word d) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in ("mul32_op", "mul64_op", "xadd32_op", "xadd64_op"):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, ctypes.POINTER(U64), ctypes.POINTER(U64)], U64
    for name in ("div32_op", "div64_op", "idiv32_op", "idiv64_op"):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, U64, ctypes.POINTER(U64)], U64
    for name in ("cmpxchg32_op", "cmpxchg64_op"):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, U64, ctypes.POINTER(U64)], U64
    lib.xadd64_mem.argtypes, lib.xadd64_mem.restype = [U64, U64, U64, U64], U64
    return lib


def check(native_path, lifted_path):
    native, lifted = load_lib(native_path), load_lib(lifted_path)
    out1, out2 = U64(0), U64(0)
    pair = (U64 * 2)(0, 0)
    cases = 0

    mul_vals = (0, 1, 2, 0x10000, 0x7fffffff, 0x80000000, 0xffffffff,
                0xdeadbeef00000003, 0x7fffffffffffffff, 0x8000000000000000, 0xffffffffffffffff)
    for name, bits in (("mul32_op", 32), ("mul64_op", 64)):
        mask = (1 << bits) - 1
        for a in mul_vals:
            for b in mul_vals:
                p = (a & mask) * (b & mask)
                want_lo, want_hi = p & mask, (p >> bits) & mask
                want_cf = 1 if want_hi != 0 else 0
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    out1.value = out2.value = 0xdeadbeef
                    got = getattr(lib, name)(a, b, ctypes.byref(out1), ctypes.byref(out2))
                    if (got, out1.value, out2.value) != (want_lo, want_hi, want_cf):
                        raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) mismatch")
                cases += 1

    div32_cases = [
        (0, 0, 1), (100, 0, 7), (0xffffffff, 0, 0xffffffff),
        (0x12345678, 0x00000003, 0x10000000), (0xffffffff, 0xfffffffe, 0xffffffff),
        (0xdeadbeef00000019, 0xcafebabe00000000, 0x1111111100000005),
    ]
    for lo, hi, den in div32_cases:
        num = ((hi & 0xffffffff) << 32) | (lo & 0xffffffff)
        d = den & 0xffffffff
        want_q, want_r = num // d, num % d
        for lib, label in ((native, "native"), (lifted, "lifted")):
            out1.value = 0xdeadbeef
            got = lib.div32_op(lo, hi, den, ctypes.byref(out1))
            if (got, out1.value) != (want_q, want_r):
                raise AssertionError(f"{label} div32_op({lo:#x}, {hi:#x}, {den:#x}) = ({got:#x}, {out1.value:#x})")
        cases += 1

    div64_cases = [
        (0, 0, 1), (100, 0, 7), (0xffffffffffffffff, 0, 0xffffffffffffffff),
        (0x0123456789abcdef, 0x0000000000000005, 0x1000000000000000),
        (0xffffffffffffffff, 0xfffffffffffffffe, 0xffffffffffffffff),
        (0x8000000000000000, 0x7fffffffffffffff, 0x8000000000000000),
    ]
    for lo, hi, den in div64_cases:
        num = (hi << 64) | lo
        want_q, want_r = num // den, num % den
        for lib, label in ((native, "native"), (lifted, "lifted")):
            out1.value = 0xdeadbeef
            got = lib.div64_op(lo, hi, den, ctypes.byref(out1))
            if (got, out1.value) != (want_q, want_r):
                raise AssertionError(f"{label} div64_op({lo:#x}, {hi:#x}, {den:#x}) = ({got:#x}, {out1.value:#x})")
        cases += 1

    for name, bits, idiv_cases in (
        ("idiv32_op", 32, [
            (0, 0, 1), (100, 0, 7), (100, 0, -7), (-100, -1, 7), (-100, -1, -7),
            (-2147483648, -1, 2), (0x7fffffff, 0, -1), (0x12345678, 2, -0x40000000),
        ]),
        ("idiv64_op", 64, [
            (0, 0, 1), (100, 0, 7), (100, 0, -7), (-100, -1, 7), (-100, -1, -7),
            (-(1 << 63), -1, 2), ((1 << 63) - 1, 0, -1), (0x123456789abcdef0, 3, -(1 << 62)),
            (0, -1, -(1 << 63)),
        ]),
    ):
        mask = (1 << bits) - 1
        for s_lo, s_hi, s_den in idiv_cases:
            lo_u, hi_u, den_u = s_lo & mask, s_hi & mask, s_den & mask
            num = (hi_u << bits) | lo_u
            if num & (1 << (2 * bits - 1)):
                num -= 1 << (2 * bits)
            q = (abs(num) // abs(s_den)) * (-1 if (num < 0) != (s_den < 0) else 1)
            r = num - q * s_den
            want_q, want_r = q & mask, r & mask
            for lib, label in ((native, "native"), (lifted, "lifted")):
                out1.value = 0xdeadbeef
                got = getattr(lib, name)(lo_u, hi_u, den_u, ctypes.byref(out1))
                if (got, out1.value) != (want_q, want_r):
                    raise AssertionError(
                        f"{label} {name}({lo_u:#x}, {hi_u:#x}, {den_u:#x}) = ({got:#x}, {out1.value:#x}), "
                        f"expected ({want_q:#x}, {want_r:#x})"
                    )
            cases += 1

    for name, bits in (("xadd32_op", 32), ("xadd64_op", 64)):
        mask = (1 << bits) - 1
        for a in mul_vals[:7]:
            for b in mul_vals[:7]:
                total = (a & mask) + (b & mask)
                want_sum, want_old = total & mask, a & mask
                want_f = (2 if total > mask else 0) | (1 if want_sum == 0 else 0)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    out1.value = out2.value = 0xdeadbeef
                    got = getattr(lib, name)(a, b, ctypes.byref(out1), ctypes.byref(out2))
                    if (got, out1.value, out2.value) != (want_sum, want_old, want_f):
                        raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) mismatch")
                cases += 1

    for name, bits in (("cmpxchg32_op", 32), ("cmpxchg64_op", 64)):
        mask = (1 << bits) - 1
        src = 0x1122334455667788
        for acc in mul_vals[:7]:
            for dst in mul_vals[:7]:
                a_m, d_m = acc & mask, dst & mask
                eq = a_m == d_m
                want_rax = acc if eq else d_m
                want_dst = (src & mask) if eq else dst
                want_f = (2 if a_m < d_m else 0) | (1 if eq else 0)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    pair[0] = pair[1] = 0xdeadbeef
                    got = getattr(lib, name)(acc, dst, src, pair)
                    if (got, pair[0], pair[1]) != (want_rax, want_dst, want_f):
                        raise AssertionError(
                            f"{label} {name}({acc:#x}, {dst:#x}) = ({got:#x}, {pair[0]:#x}, {pair[1]:#x}), "
                            f"expected ({want_rax:#x}, {want_dst:#x}, {want_f:#x})"
                        )
                cases += 1

    # Memory-operand XADD where base == src: xadd qword ptr [rcx], rcx must write to original rcx.
    mem_slot = U64(0)
    addr = ctypes.addressof(mem_slot)
    for initial in (0, 1, 0x123456789abcdef0, 0xffffffffffffffff):
        want_sum = (initial + addr) & 0xffffffffffffffff
        for lib, label in ((native, "native"), (lifted, "lifted")):
            mem_slot.value = initial
            got_old = lib.xadd64_mem(addr, 0, 0, 0)
            if (got_old, mem_slot.value) != (initial, want_sum):
                raise AssertionError(
                    f"{label} xadd64_mem({initial:#x}) = ({got_old:#x}, {mem_slot.value:#x}), "
                    f"expected ({initial:#x}, {want_sum:#x})"
                )
        cases += 1

    # #DE fault checks: zero divisor and quotient overflow must fault on both native and lifted DLLs.
    de_cases = (
        ("div32_op", 7, 0, 0),
        ("div32_op", 0, 1, 1),
        ("div64_op", 7, 0, 0),
        ("div64_op", 0, 1, 1),
        ("idiv32_op", 7, 0, 0),
        ("idiv32_op", 0x80000000, 0xffffffff, 0xffffffff),
        ("idiv64_op", 7, 0, 0),
        ("idiv64_op", 0x8000000000000000, 0xffffffffffffffff, 0xffffffffffffffff),
    )
    for name, lo_u, hi_u, den_u in de_cases:
        exceptions = []
        for lib, label in ((native, "native"), (lifted, "lifted")):
            try:
                getattr(lib, name)(lo_u, hi_u, den_u, ctypes.byref(out1))
            except OSError as error:
                exceptions.append(error.args)
            else:
                raise AssertionError(f"{label} {name}({lo_u:#x}, {hi_u:#x}, {den_u:#x}) failed to raise #DE")
        if exceptions[0] != exceptions[1]:
            raise AssertionError(f"{name}: native and lifted divide errors differ: {exceptions}")
        cases += 1

    print(f"{cases} MUL, DIV, IDIV, XADD, and CMPXCHG cases (including xadd [rcx],rcx and #DE faults) matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
    else:
        raise ValueError(mode)
