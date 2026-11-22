"""Compare native and translated functions whose entry lies above code they continue in."""
import ctypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_switch_aot import translate
from direct_check import GUARDS, MASK, SENTINELS, input_pairs, observe, register_probe

NAMES = ("square_tail", "inc_square", "pick_tail", "branch_next")
# Whether the export's entry is above the lowest instruction it reaches.
ABOVE = {"square_tail": False, "inc_square": True, "pick_tail": True, "branch_next": False}


def reference(name, x, y):
    """Return value and the two trace words; an untouched word keeps the probe's fill."""
    if name == "branch_next":
        value = (x + y) & MASK
        return value, (value, MASK)
    if name == "pick_tail" and x >= y:
        value = (x - y) & MASK
        return value, (MASK, value)
    if name == "inc_square":
        x = (x + 1) & MASK
    value = (x * x + y) & MASK
    return value, (value, MASK)


def check_layout(original_path):
    """The fixture must really place code below two entries, and the translation must start at each entry."""
    source, functions = translate(original_path, NAMES)
    bodies = source.split('extern "C" __declspec(dllexport) word lifted_')[1:]
    for name, function, body in zip(NAMES, functions, bodies):
        lowest = min(function.instructions)
        if (lowest < function.entry) != ABOVE[name]:
            raise AssertionError(f"{name}: entry {function.entry:#x}, lowest instruction {lowest:#x}")
        first = next(line.strip() for line in body.splitlines()[1:] if not line.strip().startswith("word "))
        starts_with_jump = first == f"goto loc_{function.entry:x};"
        if starts_with_jump != ABOVE[name]:
            raise AssertionError(f"{name}: translation starts with {first!r}")
        print(f"control {name}: entry {function.entry:#x}, lowest instruction {lowest:#x}, "
              f"{'starts with a jump to the entry' if starts_with_jump else 'starts at the entry'}")
    # branch_next must really branch to its own fallthrough, and that target must be labelled.
    branch = next(ins for ins in functions[NAMES.index("branch_next")].instructions.values() if ins.is_jcc_short_or_near)
    if branch.near_branch_target != branch.next_ip:
        raise AssertionError(f"branch_next: the branch at {branch.ip:#x} targets {branch.near_branch_target:#x}")
    if f"loc_{branch.next_ip:x}:" not in bodies[NAMES.index("branch_next")]:
        raise AssertionError("branch_next: the branch target has no label")
    print(f"control branch_next: the branch at {branch.ip:#x} targets its fallthrough, which is labelled")


def check(probe_path, original_path, lifted_path):
    probe = register_probe(probe_path)
    native, lifted = ctypes.CDLL(original_path), ctypes.CDLL(lifted_path)
    inputs = input_pairs()
    taken = {name: set() for name in NAMES}
    for name in NAMES:
        for x, y in inputs:
            value, words = reference(name, x, y)
            want = (value, (GUARDS[0], *words, MASK, GUARDS[1]), SENTINELS)
            for label, function in (("native", getattr(native, name)), ("translated", getattr(lifted, "lifted_" + name))):
                got = observe(probe, function, x, y)
                if got != want:
                    raise AssertionError(f"{label} {name}({x:#x}, {y:#x}) = {got}, expected {want}")
            taken[name].add(words[0] != MASK)
    # pick_tail must have run both its own return and the shared code below its entry.
    if taken["pick_tail"] != {False, True}:
        raise AssertionError(f"pick_tail inputs covered only {taken['pick_tail']}")
    print(f"{len(inputs)} input pairs per export match on return, guarded trace, RBX and RSI "
          f"for {', '.join(NAMES)}")


if __name__ == "__main__":
    check_layout(sys.argv[2])
    check(*sys.argv[1:])
