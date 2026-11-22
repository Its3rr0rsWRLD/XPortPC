"""Compare native and translated unsigned/equality CMOVcc and SETcc instructions."""
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
CMOV_EXPORTS = ("cmova32", "cmova64", "cmovae32", "cmovae64", "cmovb32", "cmovb64", "cmove32", "cmove64")
SET_EXPORTS = ("seta_op", "setae_op", "setb_op", "setbe_op", "setne_op")


def emit(image, output):
    parts = [INTEGER_HEADER]
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
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in CMOV_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64, U64], U64
    for name in SET_EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [U64, U64], U64
    return lib


def check(native_path, lifted_path):
    native, lifted = load_lib(native_path), load_lib(lifted_path)
    vals = (0, 1, 0x7fffffff, 0x80000000, 0xffffffff,
            0xdeadbeef00000000, 0xdeadbeef00000001,
            0x7fffffffffffffff, 0x8000000000000000, 0xffffffffffffffff)
    alt = 0xabcdef0123456789

    preds = {
        "a": lambda x, y: x > y,
        "ae": lambda x, y: x >= y,
        "b": lambda x, y: x < y,
        "be": lambda x, y: x <= y,
        "e": lambda x, y: x == y,
        "ne": lambda x, y: x != y,
    }

    cases = 0
    for suffix, pred in (("a", preds["a"]), ("ae", preds["ae"]), ("b", preds["b"]), ("e", preds["e"])):
        for bits, init in ((32, 0x11), (64, 0x1122334455667788)):
            name = f"cmov{suffix}{bits}"
            mask = (1 << bits) - 1
            for a in vals:
                for b in vals:
                    want = (alt & mask) if pred(a & mask, b & mask) else init
                    for lib, label in ((native, "native"), (lifted, "lifted")):
                        got = getattr(lib, name)(a, b, alt)
                        if got != want:
                            raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) = {got:#x}, expected {want:#x}")
                    cases += 1

    for suffix in ("a", "ae", "b", "be", "ne"):
        name = f"set{suffix}_op"
        pred = preds[suffix]
        for a in vals:
            for b in vals:
                want = 0x123456789abcde00 | (1 if pred(a, b) else 0)
                for lib, label in ((native, "native"), (lifted, "lifted")):
                    got = getattr(lib, name)(a, b)
                    if got != want:
                        raise AssertionError(f"{label} {name}({a:#x}, {b:#x}) = {got:#x}, expected {want:#x}")
                cases += 1

    print(f"{cases} CMOVcc and SETcc cases (cmova/ae/b/e, seta/ae/b/be/ne) matched native and translated DLLs")


def check_memory_source_read():
    # x86 reads a CMOVcc memory source unconditionally even when the predicate is false.
    # 41 0F 47 00 = cmova eax, dword ptr [r8]
    emitted = lower(list(Decoder(64, bytes.fromhex("39 c9 41 0f 47 00 c3"), ip=0x1000)), [], {}, {}, {})
    if "load_always<uint32_t>(r8 + 0ull)" not in emitted:
        raise AssertionError(f"expected unconditional volatile read for CMOV memory source:\n{emitted}")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
        check_memory_source_read()
    else:
        raise ValueError(mode)
