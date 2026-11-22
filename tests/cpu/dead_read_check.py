"""Compare faults of native and translated functions whose memory reads produce unused values."""
import ctypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import translate

PAGE = 0x1000
VALUE = 0x1122334455667788
# Export: (memory reads in its machine code, reference result for a readable operand and second argument y).
EXPORTS = {
    "read_dead": (1, lambda y: y),
    "cmp_dead": (1, lambda y: (y + 1) & (1 << 64) - 1),
    "byte_dead": (1, lambda y: y),
    "pair_dead": (2, lambda y: 0),
    "read_live": (1, lambda y: VALUE),
}
# (export, bytes from the operand to the end of the readable page, whether the call must fault). The page
# after it is inaccessible, so these show that each read keeps its own width and that both reads of
# pair_dead are performed.
EDGES = (
    ("byte_dead", 1, False), ("read_dead", 1, True), ("read_dead", 8, False), ("cmp_dead", 4, False),
    ("cmp_dead", 3, True), ("pair_dead", 16, False), ("pair_dead", 8, True), ("read_live", 7, True),
)


def check_source(original_path):
    """Every memory read of the translation is a volatile read; none is an ordinary load."""
    source, functions = translate(original_path, list(EXPORTS))
    bodies = source.split('extern "C" __declspec(dllexport) word lifted_')[1:]
    for (name, (reads, _)), function, body in zip(EXPORTS.items(), functions, bodies):
        decoded = sum(1 for ins in function.instructions.values() if "ptr [" in str(ins) or "[rcx" in str(ins))
        if decoded != reads:
            raise AssertionError(f"{name}: {decoded} memory operands in the fixture, expected {reads}")
        if body.count("load_always<") != reads or "load<" in body or "memcpy" in body:
            raise AssertionError(f"{name}: translation does not read memory {reads} time(s) through load_always")
        print(f"control {name}: {reads} memory read(s), each translated as a volatile read")


def two_pages():
    """A readable page holding VALUE in every word, followed by an inaccessible page."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
    kernel32.VirtualProtect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_void_p]
    base = kernel32.VirtualAlloc(None, 2 * PAGE, 0x3000, 0x04)  # MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
    if not base:
        raise ctypes.WinError(ctypes.get_last_error())
    (ctypes.c_uint64 * (PAGE // 8)).from_address(base)[:] = [VALUE] * (PAGE // 8)
    old = ctypes.c_uint32()
    if not kernel32.VirtualProtect(base + PAGE, PAGE, 0x01, ctypes.byref(old)):  # PAGE_NOACCESS
        raise ctypes.WinError(ctypes.get_last_error())
    return base


def call(function, pointer, y):
    """The return value, or None when the call raised an access violation."""
    try:
        return function(pointer, y, 0)
    except OSError as error:
        if "access violation" not in str(error):
            raise
        return None


def check(original_path, lifted_path):
    native, lifted = ctypes.CDLL(original_path), ctypes.CDLL(lifted_path)
    base = two_pages()
    sides = []
    for label, library, prefix in (("native", native, ""), ("translated", lifted, "lifted_")):
        functions = {}
        for name in EXPORTS:
            function = getattr(library, prefix + name)
            function.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]
            function.restype = ctypes.c_uint64
            functions[name] = function
        sides.append((label, functions))
    for name, (_, reference) in EXPORTS.items():
        for label, functions in sides:
            for y in (0, 5, 0xfedcba9876543210):
                got = call(functions[name], base, y)
                if got != reference(y):
                    raise AssertionError(f"{label} {name}(readable, {y:#x}) = {got}, expected {reference(y):#x}")
            if call(functions[name], 0, 5) is not None:
                raise AssertionError(f"{label} {name} with a null operand did not fault")
        print(f"{name}: native and translated return the reference for a readable operand and fault for a null one")
    for name, room, faults in EDGES:
        for label, functions in sides:
            got = call(functions[name], base + PAGE - room, 5)
            if (got is None) != faults:
                raise AssertionError(f"{label} {name} {room} byte(s) before an inaccessible page: "
                                     f"{'no fault' if faults else 'fault'}")
            if got is not None and got != EXPORTS[name][1](5):
                raise AssertionError(f"{label} {name} {room} byte(s) before an inaccessible page = {got:#x}")
        print(f"control {name}, operand {room} byte(s) before an inaccessible page: "
              f"native and translated {'fault' if faults else 'return'}")
    print("note: an unoptimized build performs these reads with an ordinary load too; "
          "only an optimized build of the translation shows the difference")


if __name__ == "__main__":
    check_source(sys.argv[1])
    check(*sys.argv[1:])
