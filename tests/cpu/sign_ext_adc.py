"""Compare native and translated CBW, CWDE, CDQE, CQO, MOVSX, and ADC instructions."""
import ctypes
from pathlib import Path
import sys

import pefile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64
UNARY_EXPORTS = ("cbw_op", "cwde_op", "cdqe_op", "cqo_op",
                 "movsx_r16_r8", "movsx_r32_r8", "movsx_r64_r8", "movsx_r32_r16", "movsx_r64_r16")
ADC_EXPORTS = ("adc32_op", "adc64_op")


def emit(image, output):
    parts = [INTEGER_HEADER]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in UNARY_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a) {{\n{code}\n}}\n')
        for name in ADC_EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            code = lower(body, ["rcx = a; rdx = b; r8 = cin; r9 = out;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word cin, word out) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in UNARY_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64], U64
    for name in ADC_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, U64, ctypes.POINTER(U64)], U64
    return lib


def sext(val, src_bits, dst_bits):
    s = val & ((1 << src_bits) - 1)
    if s & (1 << (src_bits - 1)):
        s -= 1 << src_bits
    return s & ((1 << dst_bits) - 1)


def check(native_path, lifted_path):
    native, lifted = load_lib(native_path), load_lib(lifted_path)
    slot = U64(0)
    values = (
        0, 1, 0x7f, 0x80, 0xff, 0x7fff, 0x8000, 0xffff,
        0x7fffffff, 0x80000000, 0xffffffff,
        0xdeadbeef0000007f, 0xdeadbeef00000080, 0xdeadbeef00007fff, 0xdeadbeef00008000,
        0x7fffffffffffffff, 0x8000000000000000, 0xffffffffffffffff,
    )
    refs = {
        "cbw_op": lambda a: (a & ~0xffff) | sext(a, 8, 16),
        "cwde_op": lambda a: sext(a, 16, 32),
        "cdqe_op": lambda a: sext(a, 32, 64),
        "cqo_op": lambda a: 0xffffffffffffffff if (a & (1 << 63)) else 0,
        "movsx_r16_r8": lambda a: (0x123456789abcdef & ~0xffff) | sext(a, 8, 16),
        "movsx_r32_r8": lambda a: sext(a, 8, 32),
        "movsx_r64_r8": lambda a: sext(a, 8, 64),
        "movsx_r32_r16": lambda a: sext(a, 16, 32),
        "movsx_r64_r16": lambda a: sext(a, 16, 64),
    }

    cases = 0
    for name, fn in refs.items():
        for a in values:
            want = fn(a)
            for lib, label in ((native, "native"), (lifted, "lifted")):
                got = getattr(lib, name)(a)
                if got != want:
                    raise AssertionError(f"{label} {name}({a:#x}) = {got:#x}, expected {want:#x}")
            cases += 1

    adc_vals = (0, 1, 0x7fffffff, 0x80000000, 0xfffffffe, 0xffffffff,
                0xdeadbeef00000000, 0x7fffffffffffffff, 0x8000000000000000,
                0xfffffffffffffffe, 0xffffffffffffffff)
    for name, bits in (("adc32_op", 32), ("adc64_op", 64)):
        mask = (1 << bits) - 1
        for a in adc_vals:
            for b in adc_vals:
                for cin in (0, 1):
                    total = (a & mask) + (b & mask) + cin
                    want_v = total & mask
                    want_f = (2 if total > mask else 0) | (1 if want_v == 0 else 0)
                    for lib, label in ((native, "native"), (lifted, "lifted")):
                        slot.value = 0xdeadbeef
                        got = getattr(lib, name)(a, b, cin, ctypes.byref(slot))
                        if (got, slot.value) != (want_v, want_f):
                            raise AssertionError(
                                f"{label} {name}({a:#x}, {b:#x}, {cin}) = ({got:#x}, {slot.value:#x}), "
                                f"expected ({want_v:#x}, {want_f:#x})"
                            )
                    cases += 1

    print(f"{cases} sign-extension and ADC cases (CBW, CWDE, CDQE, CQO, MOVSX, ADC) matched native and translated DLLs")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
    else:
        raise ValueError(mode)
