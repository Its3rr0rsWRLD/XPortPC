"""Compare native and translated memory-ordering fences, PAUSE and cache hints.

LFENCE, MFENCE, SFENCE, PAUSE, PREFETCHT0, PREFETCHT1, PREFETCHT2, PREFETCHNTA, PREFETCH, PREFETCHW,
CLFLUSH, CLFLUSHOPT and CLWB have no register result, so each export loads and stores around the
instruction and the check compares the return value and the buffer. A host without CLFLUSHOPT, CLWB
or PREFETCH/PREFETCHW raises an illegal instruction in the native DLL; the check then exits with 77
(skip) instead of claiming the forms.
"""
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
EXPORTS = ("fence_order", "pause_spin", "prefetch_sum", "prefetch_write", "flush_store", "flushopt_store", "clwb_store")
MASK = (1 << 64) - 1
ILLEGAL_INSTRUCTION = 0xC000001D
SKIP = 77


def emit(image, output):
    parts = [INTEGER_HEADER]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name in EXPORTS:
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            code = lower(region(pe, *bounds), ["rcx = p; rdx = v; r8 = q;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word p, word v, word q) {{\n{code}\n}}\n')
    output.write_text("".join(parts), encoding="ascii")


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, U64, ctypes.c_void_p], U64
    return lib


def rejections():
    """Negative controls: a segment-relative prefetch and the invalid LOCK LFENCE must still be refused."""
    for label, code in (("prefetcht0 fs:[rcx]", "640f1809c3"), ("lock lfence (invalid encoding)", "f00faee8c3")):
        body = [i for i in Decoder(64, bytes.fromhex(code))][:-1]
        try:
            lower(body, [], {}, {}, {})
        except ValueError as error:
            print(f"rejected {label}: {error}")
            continue
        raise AssertionError(f"lower() accepted {label}")
    return 2


def check(native_path, lifted_path):
    rejected = rejections()
    native, lifted = load_lib(native_path), load_lib(lifted_path)
    buffer = (U64 * 64)()
    base = ctypes.addressof(buffer)
    values = (0, 1, 0x7f, 0x8000000000000000, 0xffffffffffffffff, 0xdeadbeefcafef00d, 0x0123456789abcdef)
    cases = 0

    def run(name, v, q, seed, want_return, want_slots):
        nonlocal cases
        for lib, label in ((native, "native"), (lifted, "lifted")):
            for k in range(64):
                buffer[k] = (seed * 0x9e3779b97f4a7c15 + k * 0x100000001b3) & MASK
            try:
                got = getattr(lib, name)(base, v, q)
            except OSError as error:
                if label == "native" and (error.winerror or 0) & 0xFFFFFFFF == ILLEGAL_INSTRUCTION:
                    print(f"skip: this host raises an illegal instruction in {name}")
                    sys.exit(SKIP)
                raise
            if got != want_return(buffer_before):
                raise AssertionError(f"{label} {name}(v={v:#x}, q={q:#x}) returned {got:#x}, "
                                     f"expected {want_return(buffer_before):#x}")
            for slot, want in want_slots(buffer_before).items():
                if buffer[slot] != want:
                    raise AssertionError(f"{label} {name}(v={v:#x}) left p[{slot}] = {buffer[slot]:#x}, expected {want:#x}")
        cases += 1

    for seed, v in enumerate(values):
        buffer_before = [(seed * 0x9e3779b97f4a7c15 + k * 0x100000001b3) & MASK for k in range(64)]
        run("fence_order", v, 0, seed, lambda b: (v + b[1]) & MASK,
            lambda b: {0: v, 1: b[1], 2: (v + b[1]) & MASK})
        for q in (0, base, 0x1000):
            run("prefetch_sum", v, q, seed, lambda b: (b[0] + b[8] + b[16] + b[24]) & MASK,
                lambda b: {k: b[k] for k in (0, 8, 16, 24)})
            run("prefetch_write", v, q, seed, lambda b: (b[0] + v) & MASK, lambda b: {0: b[0], 1: v})
        run("flush_store", v, 0, seed, lambda b: v, lambda b: {0: v})
        run("flushopt_store", v, 0, seed, lambda b: v ^ b[9], lambda b: {8: v, 9: b[9]})
        run("clwb_store", v, 0, seed, lambda b: (v - b[17]) & MASK, lambda b: {16: v, 17: b[17]})
    for seed, n in enumerate((0, 1, 2, 7, 100, 1000)):
        buffer_before = [(seed * 0x9e3779b97f4a7c15 + k * 0x100000001b3) & MASK for k in range(64)]
        run("pause_spin", n, 0, seed, lambda b: 3 * n, lambda b: {})

    print(f"{cases} cases of LFENCE, MFENCE, SFENCE, PAUSE, PREFETCHT0/T1/T2/NTA, PREFETCH, PREFETCHW, CLFLUSH, "
          f"CLFLUSHOPT and CLWB matched native and translated DLLs; {rejected} negative controls rejected")


if __name__ == "__main__":
    mode, native, other = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other))
    elif mode == "check":
        check(native, other)
    else:
        raise ValueError(mode)
