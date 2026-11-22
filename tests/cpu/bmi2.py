"""Compare native and translated BMI2 instructions (32-bit and 64-bit)."""
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

OUT2_EXPORTS = ("bzhi32", "bzhi64", "shlx32", "shlx64", "mulx32", "mulx64")
OUT1_EXPORTS = ("rorx32", "rorx64")
PLAIN2_EXPORTS = ("shrx32", "shrx64", "sarx32", "sarx64", "pdep32", "pdep64", "pext32", "pext64", "mulx64_same")


def emit(image, output):
    parts = [
        "#include <intrin.h>\n",
        INTEGER_HEADER,
        'extern "C" __declspec(dllexport) int host_has_bmi2() {\n'
        "    int regs[4]{};\n"
        "    __cpuid(regs, 0);\n"
        "    if (regs[0] < 7) return 0;\n"
        "    __cpuidex(regs, 7, 0);\n"
        "    return (regs[1] & (1 << 8)) != 0;\n"
        "}\n",
    ]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in OUT2_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word out) {{\n{code}\n}}\n')
        for name in OUT1_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word out) {{\n{code}\n}}\n')
        for name in PLAIN2_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in OUT2_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, ctypes.POINTER(U64)], U64
    for name in OUT1_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, ctypes.POINTER(U64)], U64
    for name in PLAIN2_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64], U64
    return lib


def ref_bzhi(a, idx, bits):
    mask = (1 << bits) - 1
    a &= mask
    n = idx & 0xff
    if n >= bits:
        v, cf = a, 2
    else:
        v, cf = a & ((1 << n) - 1), 0
    return v, cf | (1 if v == 0 else 0)


def ref_rorx(a, count, bits):
    mask = (1 << bits) - 1
    a &= mask
    c = count & (bits - 1)
    v = a if c == 0 else ((a >> c) | (a << (bits - c))) & mask
    return v, 2  # preserved CF=1, ZF=0


def ref_shlx(a, count, bits):
    mask = (1 << bits) - 1
    c = count & (bits - 1)
    return ((a & mask) << c) & mask, 2  # preserved CF=1, ZF=0


def ref_shrx(a, count, bits):
    mask = (1 << bits) - 1
    return (a & mask) >> (count & (bits - 1))


def ref_sarx(a, count, bits):
    mask = (1 << bits) - 1
    sign = 1 << (bits - 1)
    a &= mask
    s = a - (1 << bits) if a & sign else a
    return (s >> (count & (bits - 1))) & mask


def ref_pdep(src, mask_val, bits):
    out = 0
    k = 0
    for b in range(bits):
        if (mask_val >> b) & 1:
            if (src >> k) & 1:
                out |= 1 << b
            k += 1
    return out


def ref_pext(src, mask_val, bits):
    out = 0
    k = 0
    for b in range(bits):
        if (mask_val >> b) & 1:
            if (src >> b) & 1:
                out |= 1 << k
            k += 1
    return out


def ref_mulx(a, b, bits):
    mask = (1 << bits) - 1
    prod = (a & mask) * (b & mask)
    return (prod >> bits) & mask, prod & mask


def check(native_path, lifted_path):
    lifted = load_lib(lifted_path)
    lifted.host_has_bmi2.argtypes, lifted.host_has_bmi2.restype = [], ctypes.c_int
    if not lifted.host_has_bmi2():
        print("Host CPU lacks BMI2 (CPUID leaf 7 EBX bit 8); skipping native differential check.")
        sys.exit(77)
    native = load_lib(native_path)
    slot = U64(0)
    values = (
        0, 1, 2, 0x55aa55aa, 0x7fffffff, 0x80000000, 0xffffffff,
        0xdeadbeef00000000, 0xdeadbeef12345678, 0x8000000000000000,
        0x7fffffffffffffff, 0xffffffffffffffff, 0x0123456789abcdef,
    )
    counts = (0, 1, 7, 15, 31, 32, 33, 63, 64, 65, 255, 0x100)
    masks = (0, 1, 0x55555555, 0xaaaaaaaa, 0x0f0f0f0f, 0xffffffff, 0x00ff00ff00ff00ff, 0x8000000000000001, 0xffffffffffffffff)

    cases = 0
    for name, fn, bits, rhs_list in (
        ("bzhi32", ref_bzhi, 32, counts),
        ("bzhi64", ref_bzhi, 64, counts),
        ("shlx32", ref_shlx, 32, counts),
        ("shlx64", ref_shlx, 64, counts),
        ("mulx32", ref_mulx, 32, values),
        ("mulx64", ref_mulx, 64, values),
    ):
        for a in values:
            for b in rhs_list:
                want_v, want_out = fn(a, b, bits)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    slot.value = 0xdeadbeef
                    got_v = getattr(lib, name)(a, b, ctypes.byref(slot))
                    if (got_v, slot.value) != (want_v, want_out):
                        raise AssertionError(
                            f"{label} {name}({a:#x}, {b:#x}) = ({got_v:#x}, {slot.value:#x}), "
                            f"expected ({want_v:#x}, {want_out:#x})"
                        )
                cases += 1

    for name, count, bits in (("rorx32", 13, 32), ("rorx64", 19, 64)):
        for a in values:
            want_v, want_out = ref_rorx(a, count, bits)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                slot.value = 0xdeadbeef
                got_v = getattr(lib, name)(a, ctypes.byref(slot))
                if (got_v, slot.value) != (want_v, want_out):
                    raise AssertionError(
                        f"{label} {name}({a:#x}) = ({got_v:#x}, {slot.value:#x}), "
                        f"expected ({want_v:#x}, {want_out:#x})"
                    )
            cases += 1

    for name, fn, bits, rhs_list in (
        ("shrx32", ref_shrx, 32, counts),
        ("shrx64", ref_shrx, 64, counts),
        ("sarx32", ref_sarx, 32, counts),
        ("sarx64", ref_sarx, 64, counts),
        ("pdep32", ref_pdep, 32, masks),
        ("pdep64", ref_pdep, 64, masks),
        ("pext32", ref_pext, 32, masks),
        ("pext64", ref_pext, 64, masks),
    ):
        for a in values:
            for b in rhs_list:
                want = fn(a, b, bits)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    got = getattr(lib, name)(a, b)
                    if got != want:
                        raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) = {got:#x}, expected {want:#x}")
                cases += 1

    for a in values:
        for b in values:
            want_hi, _ = ref_mulx(a, b, 64)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                got = lib.mulx64_same(a, b)
                if got != want_hi:
                    raise AssertionError(f"{label} mulx64_same({a:#x}, {b:#x}) = {got:#x}, expected {want_hi:#x}")
            cases += 1

    print(f"{cases} BMI2 cases (32/64-bit values, BZHI flags, preserved flags, MULX same-dest) matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
    else:
        raise ValueError(mode)
