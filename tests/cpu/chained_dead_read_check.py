"""Compare the faults of functions that read guest memory with those of their chained-range translation,
built by the project's build and with /O2: each MOV load happens once, whether or not its value is used.

Usage: chained_dead_read_check.py guarded_call.dll original.dll export=translation.dll ...
"""
import ctypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_chained_aot import translate
from direct_check import GUARDS, MASK, Word

PAGE = 0x1000
VALUE = 0xfedcba9876543210
ACCESS_VIOLATION = 0xC0000005
# Export: memory operands that its machine code reads, and the bytes from the operand address the reads
# end at (the last one read).
READS = {"read_dead": (1, 8), "disp_dead": (1, 16), "pair_dead": (2, 16), "read_skip": (1, 8), "read_live": (1, 8)}


def reference(name, y):
    """RAX for a readable operand that holds VALUE in every word."""
    return VALUE if name == "read_live" else y


def check_source(original_path):
    """Each MOV load is read once through the volatile load."""
    for name, (reads, _) in READS.items():
        source, *_ = translate(Path(original_path), name)
        body = source.split("try_lifted(", 1)[1]
        loads = body.count("load_always<word>(")
        if loads != reads or "read_word(" in body:
            raise AssertionError(f"{name}: {reads} memory operand(s), {loads} volatile read(s) in the translation")
        print(f"control {name}: {reads} memory operand(s), each read once through the volatile load")


def two_pages(kernel32):
    """A writable page holding VALUE in every word, followed by an inaccessible page."""
    base = kernel32.VirtualAlloc(None, 2 * PAGE, 0x3000, 0x04)  # MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    if not base:
        raise ctypes.WinError(ctypes.get_last_error())
    old = ctypes.c_uint32()
    if not kernel32.VirtualProtect(base + PAGE, PAGE, 0x01, ctypes.byref(old)):  # PAGE_NOACCESS
        raise ctypes.WinError(ctypes.get_last_error())
    return base


def check(guard_path, original_path, *pairs):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
    kernel32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_void_p]
    guarded = ctypes.CDLL(guard_path).guarded_call
    guarded.argtypes = [ctypes.c_void_p, Word, Word, ctypes.POINTER(Word), ctypes.POINTER(Word)]
    guarded.restype = ctypes.c_uint32
    base = two_pages(kernel32)
    words = (Word * (PAGE // 8)).from_address(base)
    native = ctypes.CDLL(original_path)
    translations = {}
    for pair in pairs:
        name, path = pair.split("=", 1)
        translations.setdefault(name, []).append(ctypes.CDLL(path).try_lifted)
    if set(translations) != set(READS) or any(len(found) != 2 for found in translations.values()):
        raise AssertionError(f"expected the build and the /O2 build of {sorted(READS)}, got {pairs}")

    def run(function, pointer, y, lifted):
        """A fresh page and fresh words, then (exception code or 0, RAX or None, the page's words). The
        original ignores R8; the translation stores RAX through it and returns 1 when it completes."""
        words[:] = [VALUE] * len(words)
        out = (Word * 3)(GUARDS[0], MASK, GUARDS[1])
        result = Word(MASK)
        code = guarded(ctypes.cast(function, ctypes.c_void_p), pointer, y,
                       ctypes.cast(ctypes.byref(out, ctypes.sizeof(Word)), ctypes.POINTER(Word)), ctypes.byref(result))
        if (out[0], out[2]) != GUARDS:
            raise AssertionError("a call wrote outside its output word")
        if code:
            if lifted and out[1] != MASK:
                raise AssertionError("a faulting translation stored a result")
            return code, None, tuple(words)
        if lifted:
            if result.value != 1:
                raise AssertionError(f"translation returned status {result.value}")
            return 0, out[1], tuple(words)
        return 0, result.value, tuple(words)

    clean = (VALUE,) * (PAGE // 8)

    def compare(name, pointer, y, case, faults):
        """The original must return the reference or raise an access violation; both translations must give
        what the original gives."""
        original = run(getattr(native, name), pointer, y, False)
        wanted = (ACCESS_VIOLATION, None, clean) if faults else (0, reference(name, y), clean)
        if original != wanted:
            raise AssertionError(f"original {name}, {case}: code {original[0]:#x}, {original[1]}")
        for label, function in zip(("translation", "/O2 translation"), translations[name]):
            got = run(function, pointer, y, True)
            if got != original:
                raise AssertionError(f"{label} {name}, {case}: code {got[0]:#x}, {got[1]}; "
                                     f"original code {original[0]:#x}, {original[1]}")
        outcome = f"raise {original[0]:#010x}" if original[0] else f"return {original[1]:#x}"
        print(f"{name}, {case}: the original and both translations {outcome}")

    for name, (_, end) in READS.items():
        compare(name, base, 5, "readable operand", False)
        compare(name, 0, 5, "null operand", True)
        # The last read ends exactly at the inaccessible page, then one byte into it.
        compare(name, base + PAGE - end, 5, "reads end at an inaccessible page", False)
        compare(name, base + PAGE - end + 1, 5, "last read crosses into an inaccessible page", True)
    # pair_dead's first read succeeds and its second is entirely in the inaccessible page.
    compare("pair_dead", base + PAGE - 8, 5, "second operand in an inaccessible page", True)
    # The same inaccessible addresses on the path that skips the read: a normal return.
    for pointer, where in ((0, "null operand"), (base + PAGE, "operand in the inaccessible page")):
        compare("read_skip", pointer, 0, f"{where}, read skipped (y = 0)", False)
        compare("read_skip", pointer, 7, f"{where}, read performed (y = 7)", True)


if __name__ == "__main__":
    check_source(sys.argv[2])
    check(*sys.argv[1:])
