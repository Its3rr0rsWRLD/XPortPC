"""Compare the faults of functions that read guest memory with those of their translation, built by the
project's build and with /O2: each read happens once, at its own width, whether or not its value is used."""
import ctypes
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import translate
from direct_check import GUARDS, MASK, Word

PAGE = 0x1000
VALUE = 0xfedcba9876543210
ACCESS_VIOLATION = 0xC0000005
# Export: memory operands that its machine code reads.
READS = {"read_dead": 1, "cmp_dead": 1, "byte_dead": 1, "pair_dead": 2, "read_live": 1, "read_skip": 1,
         "sum_zero": 1, "add_in_place": 1}
# Exports whose one read gives both a result and flags: the translation must use the captured value twice.
SHARED = ("sum_zero", "add_in_place")
# (export, bytes from the operand to the end of the readable page, whether the call must fault). The next
# page is inaccessible, so these show that each read keeps its own width, that both reads of pair_dead
# are performed, and that a read-modify-write faults before it writes.
EDGES = (
    ("byte_dead", 1, False), ("read_dead", 1, True), ("read_dead", 8, False), ("cmp_dead", 4, False),
    ("cmp_dead", 3, True), ("pair_dead", 16, False), ("pair_dead", 8, True), ("read_live", 7, True),
    ("sum_zero", 8, False), ("sum_zero", 7, True), ("add_in_place", 8, False), ("add_in_place", 4, True),
)


def reference(name, y, value=VALUE):
    """RAX, the three trace words and the 64-bit word at the operand afterwards, for a readable operand."""
    trace, stored = [1, 2, MASK], value
    if name == "cmp_dead":
        rax = (y + 1) & MASK
    elif name == "pair_dead":
        rax = 0
    elif name == "read_live":
        rax = value
    elif name == "read_skip":
        rax, trace = y, [1, 2 if y else MASK, 3]
    elif name == "sum_zero":
        rax = (y + value) & MASK
        trace[2] = int(rax == 0)
    elif name == "add_in_place":
        stored = (y + value) & MASK
        rax = int(stored == 0)
    else:
        rax = y
    return rax, tuple(trace), stored


def check_source(original_path):
    """Each memory operand is read once, through the volatile load, and a shared read is reused."""
    source, functions = translate(original_path, list(READS))
    bodies = source.split('extern "C" __declspec(dllexport) word lifted_')[1:]
    for (name, reads), function, body in zip(READS.items(), functions, bodies):
        decoded = sum(1 for ins in function.instructions.values() if "[rcx" in str(ins))
        loads = body.count("load_always<")
        if decoded != reads or loads != reads or "load<" in body:
            raise AssertionError(f"{name}: {decoded} memory operand(s), {loads} volatile read(s) in the translation")
        line = f"control {name}: {reads} memory operand(s), each read once through the volatile load"
        if name in SHARED:
            statement = next(text for text in body.splitlines() if "load_always<" in text)
            uses = len(re.findall(r"\bmem\b", statement)) - 1
            if uses < 2:
                raise AssertionError(f"{name}: the captured value is used {uses} time(s): {statement.strip()}")
            line += f"; its value is captured once and used {uses} times, for the flags and for the result"
        print(line)


def two_pages(kernel32):
    """A writable page holding VALUE in every word, followed by an inaccessible page."""
    base = kernel32.VirtualAlloc(None, 2 * PAGE, 0x3000, 0x04)  # MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    if not base:
        raise ctypes.WinError(ctypes.get_last_error())
    old = ctypes.c_uint32()
    if not kernel32.VirtualProtect(base + PAGE, PAGE, 0x01, ctypes.byref(old)):  # PAGE_NOACCESS
        raise ctypes.WinError(ctypes.get_last_error())
    return base


def check(guard_path, original_path, lifted_path, optimized_path):
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
    sides = [("original", lambda name: getattr(native, name))]
    for label, path in (("translation", lifted_path), ("/O2 translation", optimized_path)):
        library = ctypes.CDLL(path)
        sides.append((label, lambda name, library=library: getattr(library, "lifted_" + name)))

    def run(function, pointer, y):
        """A fresh page and fresh trace words, then (exception code or 0, RAX or None, trace, the page's words)."""
        words[:] = [VALUE] * len(words)
        trace = (Word * 5)(GUARDS[0], MASK, MASK, MASK, GUARDS[1])
        result = Word(0)
        code = guarded(ctypes.cast(function, ctypes.c_void_p), pointer, y,
                       ctypes.cast(ctypes.byref(trace, ctypes.sizeof(Word)), ctypes.POINTER(Word)), ctypes.byref(result))
        return code, (None if code else result.value), tuple(trace)[1:4], tuple(words)

    def compare(name, pointer, y, case, wanted):
        """The original must give wanted (None: an access violation after the first marker only); both
        translations must give what the original gives."""
        original = run(sides[0][1](name), pointer, y)
        clean = (VALUE,) * len(words)
        if wanted is None:
            wanted = (ACCESS_VIOLATION, None, (1, MASK, MASK), clean)
        if original != wanted:
            raise AssertionError(f"original {name}, {case}: code {original[0]:#x}, {original[1]}, trace {original[2]}")
        for label, function in sides[1:]:
            got = run(function(name), pointer, y)
            if got != original:
                raise AssertionError(f"{label} {name}, {case}: code {got[0]:#x}, {got[1]}, trace {got[2]}; "
                                     f"original code {original[0]:#x}, {original[1]}, trace {original[2]}")
        outcome = (f"raise {original[0]:#010x} after the first marker and before the second" if original[0]
                   else f"return {original[1]:#x} with trace {tuple(hex(word) for word in original[2])}")
        print(f"{name}, {case}: the original and both translations {outcome}")

    def expected(name, y, index=0):
        rax, trace, stored = reference(name, y)
        page = [VALUE] * len(words)
        page[index] = stored
        return 0, rax, trace, tuple(page)

    for name in READS:
        # The second y makes y + VALUE wrap to zero, so sum_zero and add_in_place take both flag values.
        for y in (5, (1 << 64) - VALUE):
            compare(name, base, y, f"readable operand, y = {y:#x}", expected(name, y))
        compare(name, 0, 5, "null operand", None)
    for name, room, faults in EDGES:
        pointer = base + PAGE - room
        wanted = None if faults else expected(name, 5, (PAGE - room) // 8)
        compare(name, pointer, 5, f"operand {room} byte(s) before an inaccessible page", wanted)
    # The same inaccessible addresses on the path that skips the read: a normal return, markers 1 and 3.
    for pointer, where in ((0, "null operand"), (base + PAGE, "operand in the inaccessible page")):
        compare("read_skip", pointer, 0, f"{where}, read skipped (y = 0)", (0, 0, (1, MASK, 3), (VALUE,) * len(words)))
        compare("read_skip", pointer, 7, f"{where}, read performed (y = 7)", None)


if __name__ == "__main__":
    check_source(sys.argv[2])
    check(*sys.argv[1:])
