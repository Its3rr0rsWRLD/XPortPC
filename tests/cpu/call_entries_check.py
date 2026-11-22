"""Function-entry rule for direct calls and tail jumps in the jump-table translator.

tests/cpu/call_entries.asm has explicit unwind data: primary runtime functions, one chained
secondary range, an exported interior label, a data export and a forwarded export. A call and a
tail jump to a primary function must translate and match the original through the register probe;
retargeted copies must be refused with their stated reason.
"""

import ctypes
from pathlib import Path
import random
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from direct_check import GUARDS, MASK, SENTINELS, observe, register_probe

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import pefile  # noqa: E402
from cpu_switch_aot import Entries, translate  # noqa: E402

EXPORTS = ("entry_caller", "entry_tail")
UNTOUCHED = (GUARDS[0], MASK, MASK, MASK, GUARDS[1])


def inputs():
    edges = (0, 1, 2, 0x7f, 0xff, 0x7fffffff, 0xffffffff, 1 << 32, 1 << 63, MASK - 1, MASK)
    rng = random.Random(3174)
    return [(x, y) for x in edges for y in edges] + [(rng.getrandbits(64), rng.getrandbits(64)) for _ in range(128)]


def check(probe_path, original_path, lifted_path):
    probe = register_probe(probe_path)
    native, lifted = ctypes.CDLL(str(original_path)), ctypes.CDLL(str(lifted_path))
    for name in EXPORTS:
        original = ctypes.cast(getattr(native, name), ctypes.c_void_p).value
        translated = ctypes.cast(getattr(lifted, "lifted_" + name), ctypes.c_void_p).value
        for x, y in inputs():
            want = ((x + y + 1) & MASK, UNTOUCHED, SENTINELS)
            for label, function in (("source fixture", original), ("translation", translated)):
                got = observe(probe, function, x, y)
                if got != want:
                    raise AssertionError(f"{label} {name}({x:#x}, {y:#x}): {got} != {want}")
    print(f"{len(EXPORTS)} exports x {len(inputs())} inputs: the original and the translation of a call and a tail "
          "jump to a primary runtime function match the reference on return, trace, RBX and RSI")


def layout(pe):
    entries = Entries(pe)
    names = {symbol.name.decode(): symbol.address for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols}
    # Read the chained record from the image itself (UNW_FLAG_CHAININFO), not from the translator.
    directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    records = list(struct.iter_unpack("<III", pe.get_data(directory.VirtualAddress, directory.Size)))
    (chained,) = [(begin, info) for begin, _, info in records if pe.get_data(info, 1)[0] >> 3 & 4]
    count = pe.get_data(chained[1], 4)[2]
    parent = struct.unpack("<III", pe.get_data(chained[1] + 4 + ((count + 1) & ~1) * 2, 12))[0]
    rvas = dict(names, split_tail=chained[0], split_head=parent)
    expected = {"entry_leaf", "split_head", "entry_caller", "entry_tail"}
    if entries.primary != {rvas[name] for name in expected}:
        raise AssertionError(f"primary runtime functions {sorted(map(hex, entries.primary))}")
    kinds = {name: entries.exports[rvas[name]] for name in ("entry_inner", "entry_data", "entry_forward")}
    if kinds != {"entry_inner": "code", "entry_data": "data", "entry_forward": "forward"}:
        raise AssertionError(f"export kinds {kinds}")
    if entries.entries != entries.primary:
        raise AssertionError(f"entries {sorted(map(hex, entries.entries))} != the primary functions")
    print("entries: the four primary runtime functions; not the chained range, the interior, data or forwarded export")
    return rvas


# (export to translate, offset of the branch in it, CALL or JMP rel8, retarget, expected refusal).
CONTROLS = [
    ("entry_caller", 0x04, "call", "entry_inner", "is not a function entry (an exported label inside the function at {entry_leaf:#x})"),
    ("entry_caller", 0x04, "call", "split_tail", "is not a function entry (the start of a chained range of the function at {split_head:#x})"),
    ("entry_caller", 0x04, "call", "entry_data", "is not a function entry (a data export in a non-executable section)"),
    ("entry_caller", 0x04, "call", "entry_forward", "is not a function entry (a forwarded export)"),
    ("entry_tail", 0x00, "jmp8", "entry_inner", "jump target {entry_inner:#x} is not a function entry (an exported label inside the function at {entry_leaf:#x})"),
    ("entry_tail", 0x00, "jmp8", "split_tail", "jump target {split_tail:#x} is not a function entry (the start of a chained range of the function at {split_head:#x})"),
]


def check_rejections(original_path):
    from tempfile import TemporaryDirectory

    data = Path(original_path).read_bytes()
    with pefile.PE(data=data, fast_load=True) as pe:
        rvas = layout(pe)
        offset = pe.get_offset_from_rva
    with TemporaryDirectory() as folder:
        path = Path(folder) / "control.dll"
        for name, delta, kind, target, reason in CONTROLS:
            reason = reason.format(**rvas)
            rva = rvas[name] + delta
            at = offset(rva)
            if kind == "call":
                if data[at] != 0xe8:
                    raise AssertionError(f"no call at {name}+{delta:#x}")
                patch = b"\xe8" + struct.pack("<i", rvas[target] - (rva + 5))
            else:
                if data[at] != 0xeb:
                    raise AssertionError(f"no short jump at {name}+{delta:#x}")
                patch = b"\xeb" + struct.pack("<b", rvas[target] - (rva + 2))
            damaged = bytearray(data)
            damaged[at:at + len(patch)] = patch
            path.write_bytes(damaged)
            try:
                translate(path, [name])
            except ValueError as error:
                if reason not in str(error):
                    raise AssertionError(f"{name} control {reason!r} refused for another reason: {error}") from error
            else:
                raise AssertionError(f"{name} control accepted: {reason}")
            print(f"control {name}+{delta:#x} {kind} {target}: {reason}")
        # The leaf's unwind header patched from version 1 to 3: its record is no longer a verified
        # primary runtime function, for the call and for the tail jump.
        with pefile.PE(data=data, fast_load=True) as pe:
            info = next(info for begin, _, info in Entries(pe).records if begin == rvas["entry_leaf"])
            at = pe.get_offset_from_rva(info)
        if data[at] != 0x01:
            raise AssertionError("unexpected unwind header for entry_leaf")
        damaged = bytearray(data)
        damaged[at] = 0x03
        path.write_bytes(damaged)
        unverified = "is not a function entry (a runtime function whose unwind data is not version 1 or 2"
        for name, site in (("entry_caller", "call target"), ("entry_tail", "jump target")):
            reason = f"{site} {rvas['entry_leaf']:#x} {unverified}"
            try:
                translate(path, [name])
            except ValueError as error:
                if reason not in str(error):
                    raise AssertionError(f"{name} control {reason!r} refused for another reason: {error}") from error
            else:
                raise AssertionError(f"{name} control accepted: {reason}")
            print(f"control {name}, entry_leaf unwind version 3: {reason}")
    print(f"{len(CONTROLS) + 2} entry rejection controls passed")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: call_entries_check.py PROBE ORIGINAL LIFTED")
    check(*sys.argv[1:])
    check_rejections(sys.argv[2])
