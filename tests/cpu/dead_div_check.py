"""Compare the divide errors of functions that never use their quotient or remainder with their translation,
built unoptimized and with /O2."""
import ctypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import translate
from direct_check import GUARDS, MASK, SENTINELS, Word, observe, register_probe

NAMES = ("div32_dead", "idiv32_dead", "udiv128_dead", "idiv64_dead", "div_skip")
# STATUS_INTEGER_DIVIDE_BY_ZERO and STATUS_INTEGER_OVERFLOW: the codes Windows gives a divide error.
DIVIDE_CODES = (0xC0000094, 0xC0000095)
MIN32, MIN64 = 1 << 31, 1 << 63
# Export: (x, y, case). "valid" inputs divide normally; the others must raise a divide error in the original.
CASES = {
    "div32_dead": [(100, 7, "valid"), (MASK >> 1, MASK, "valid"), (5, 0, "zero divisor"),
                   (7 << 32, 1 << 32, "zero divisor"), (1 << 32, 1, "quotient overflow"),
                   (MASK, 1, "quotient overflow")],
    "idiv32_dead": [(100, 7, "valid"), (MIN32, 1, "valid"), (MIN32 + 1, MASK, "valid"), (9, 0, "zero divisor"),
                    (MIN32, 0xffffffff, "quotient overflow"), (MIN32, MASK, "quotient overflow")],
    "udiv128_dead": [(5, 6, "valid"), (MASK - 1, MASK, "valid"), (5, 0, "zero divisor"),
                     (5, 5, "quotient overflow"), (MASK, 1, "quotient overflow")],
    "idiv64_dead": [(100, 7, "valid"), (MIN64, 1, "valid"), (MIN64 + 1, MASK, "valid"), (9, 0, "zero divisor"),
                    (MIN64, MASK, "quotient overflow")],
    "div_skip": [(100, 7, "valid"), (MASK, 1, "valid"), (5, 0, "skipped"), (MASK, 0, "skipped")],
}


def expected_trace(case):
    """The three trace words: 1 before the divide, 2 after it, and div_skip's 3 after the join."""
    return {"valid": (1, 2), "skipped": (1, MASK)}.get(case, (1, MASK))


def check_source(original_path):
    """Each divide of the translation stores its quotient to a volatile local."""
    source, functions = translate(original_path, list(NAMES))
    bodies = source.split('extern "C" __declspec(dllexport) word lifted_')[1:]
    for name, function, body in zip(NAMES, functions, bodies):
        divides = sum(1 for ins in function.instructions.values() if str(ins).startswith(("div ", "idiv ")))
        kept = body.count("volatile") and body.count(" performed = quotient;")
        if divides != 1 or kept != 1:
            raise AssertionError(f"{name}: {divides} divide(s), {kept} kept through a volatile store")
        print(f"control {name}: one divide, whose quotient the translation stores to a volatile local")


def guarded(library_path):
    function = ctypes.CDLL(library_path).guarded_call
    function.argtypes = [ctypes.c_void_p, Word, Word, ctypes.POINTER(Word), ctypes.POINTER(Word)]
    function.restype = ctypes.c_uint32

    def call(target, x, y):
        """(exception code or 0, return value or None, the guarded trace) of target(x, y, trace)."""
        trace = (Word * 5)(GUARDS[0], MASK, MASK, MASK, GUARDS[1])
        output = ctypes.cast(ctypes.byref(trace, ctypes.sizeof(Word)), ctypes.POINTER(Word))
        result = Word(0)
        code = function(ctypes.cast(target, ctypes.c_void_p), x, y, output, ctypes.byref(result))
        return code, (None if code else result.value), tuple(trace)
    return call


def check(probe_path, guard_path, original_path, lifted_path, optimized_path):
    probe, call = register_probe(probe_path), guarded(guard_path)
    native = ctypes.CDLL(original_path)
    builds = (("Debug", ctypes.CDLL(lifted_path)), ("/O2", ctypes.CDLL(optimized_path)))
    faults = 0
    for name in NAMES:
        for x, y, case in CASES[name]:
            code, result, trace = call(getattr(native, name), x, y)
            third = 3 if name == "div_skip" else MASK
            wanted = (GUARDS[0], *expected_trace(case), third, GUARDS[1])
            if case in ("valid", "skipped"):
                if (code, result, trace) != (0, (y + 1) & MASK, wanted):
                    raise AssertionError(f"original {name}({x:#x}, {y:#x}), {case}: code {code:#x}, {result}, {trace}")
            elif code not in DIVIDE_CODES or trace != (GUARDS[0], 1, MASK, MASK, GUARDS[1]):
                raise AssertionError(f"original {name}({x:#x}, {y:#x}), {case}: code {code:#x}, trace {trace}")
            for label, library in builds:
                function = getattr(library, "lifted_" + name)
                got = call(function, x, y)
                if got != (code, result, trace):
                    raise AssertionError(f"{label} translation {name}({x:#x}, {y:#x}), {case}: "
                                         f"code {got[0]:#x}, {got[1]}, {got[2]}; original code {code:#x}, "
                                         f"{result}, {trace}")
                if not code:
                    observed = observe(probe, function, x, y)
                    if observed != (result, trace, SENTINELS):
                        raise AssertionError(f"{label} translation {name}({x:#x}, {y:#x}) through the probe: {observed}")
            if code:
                faults += 1
                print(f"fault {name}({x:#x}, {y:#x}), {case}: the original and both translations raise "
                      f"{code:#010x} after the first trace word and before the second")
            else:
                print(f"{name}({x:#x}, {y:#x}), {case}: the original and both translations return {result:#x} "
                      f"with the same trace, and the translations keep RBX and RSI")
    print(f"{sum(map(len, CASES.values()))} inputs, {faults} of them faulting: the Debug and /O2 translations "
          "match the original's exception code, return value and trace")


if __name__ == "__main__":
    check_source(sys.argv[3])
    check(*sys.argv[1:])
