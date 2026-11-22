"""Check a PE function and its independently compiled translation through the Windows ABI."""

import ctypes
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import translate

Word = ctypes.c_uint32
MASK = 0xffffffff


def invoke(function, value):
    words = (Word * 3)(0xaced0123, 0xdeadbeef, 0x9876cafe)
    output = ctypes.cast(ctypes.byref(words, ctypes.sizeof(Word)), ctypes.POINTER(Word))
    result = function(value, output)
    return result, tuple(words)


def signed32(value):
    value &= MASK
    return value - 0x100000000 if value & 0x80000000 else value


def simulate(value, *, inverted=False):
    eax = value & MASK
    stages = []
    for threshold, signed, taken_delta, fall_delta in (
        (5, False, -7, 3),
        (15, False, -5, 2),
        (21, False, -1, 4),
        (32, False, -3, 6),
        (300, False, 512, -260),
        (0xfffffff0, False, 19, -41),
        (-12, True, -13, 11),
        (-300, True, 37, -29),
    ):
        lhs = signed32(eax) if signed else eax
        if threshold == 5:
            cond = lhs < 5
        elif threshold == 15:
            cond = lhs == 15
        elif threshold == 21:
            cond = lhs != 21
        elif threshold == 32:
            cond = lhs <= 32
        elif threshold == 300:
            cond = lhs > 300
        elif threshold == 0xfffffff0:
            cond = lhs <= 0xfffffff0
        elif threshold == -12:
            cond = lhs < -12
        else:
            cond = lhs <= -300
        relation = "lt" if lhs < threshold else "eq" if lhs == threshold else "gt"
        stages.append((threshold, relation))
        take = (not cond) if inverted else cond
        eax = (eax + (taken_delta if take else fall_delta)) & MASK
    return ((eax + 1) & MASK, (0xaced0123, eax, 0x9876cafe)), stages


def check(original_path, lifted_path, inverted_path):
    original = ctypes.CDLL(original_path).branch_value
    lifted = ctypes.CDLL(lifted_path).lifted
    inverted = ctypes.CDLL(inverted_path).lifted
    for function in (original, lifted, inverted):
        function.argtypes = [Word, ctypes.POINTER(Word)]
        function.restype = Word

    values = [
        *range(320),
        0x7fffffff,
        0x80000000,
        *range(0xfffffcbe, 0xfffffcca),
        *range(0xfffffdea, 0xfffffdf5),
        *range(0xffffffea, MASK + 1),
    ]
    seen = {threshold: set() for threshold in (5, 15, 21, 32, 300, 0xfffffff0, -12, -300)}
    for value in values:
        reference, stages = simulate(value)
        for threshold, relation in stages:
            seen[threshold].add(relation)
        native = invoke(original, value)
        if native != reference:
            raise AssertionError(f"source fixture mismatch for {value:#x}: {native} != {reference}")
        actual = invoke(lifted, value)
        if actual != native:
            raise AssertionError(f"translation mismatch for {value:#x}: {actual} != {native}")
        inv_ref, _ = simulate(value, inverted=True)
        control = invoke(inverted, value)
        if control == native or control != inv_ref:
            raise AssertionError(f"inverted branch control mismatch for {value:#x}: {control} != {inv_ref}")
    for threshold, relations in seen.items():
        if relations != {"lt", "eq", "gt"}:
            raise AssertionError(f"threshold {threshold:#x} missing relations: {relations}")
    print(f"{len(values)} native/translated matches and {len(values)} inverted-branch differences across "
          "jb/jae, je/jne, jbe/ja, jl/jge, jle/jg, 32-bit immediates and sign-extended imm8")


def check_rejections():
    for body, error in [
        ("90 c3", "unsupported or incomplete instruction at RVA 0x1002"),
        ("83 c0", "unsupported or incomplete instruction at RVA 0x1002"),
        ("3d 01 00 00 00 70 02 89 02 c3", "unsupported or incomplete instruction at RVA 0x1002"),
        ("05 01 00 00", "unsupported or incomplete instruction at RVA 0x1002"),
        ("2d 01 00 00", "unsupported or incomplete instruction at RVA 0x1002"),
        ("eb 01 83 c0 05 c3", "branch into an instruction at RVA 0x1005"),
        ("eb 7f c3", "expected forward in-function branch at RVA 0x1002"),
        ("89 02", "missing terminal return at RVA 0x1004"),
    ]:
        try:
            translate(0x1000, bytes.fromhex("8b c1 " + body))
        except ValueError as exc:
            if str(exc) != error:
                raise AssertionError(str(exc)) from exc
        else:
            raise AssertionError(f"accepted invalid function: {body}")


if __name__ == "__main__":
    check(*sys.argv[1:])
    check_rejections()
