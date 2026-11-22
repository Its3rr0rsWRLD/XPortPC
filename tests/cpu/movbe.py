"""Compare native and translated MOVBE loads and stores (16-, 32- and 64-bit)."""
import ctypes
from pathlib import Path
import re
import sys

import pefile
from iced_x86 import Code

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from ffx_version_query import INTEGER_HEADER, lower, region

U64 = ctypes.c_uint64
MASK64 = (1 << 64) - 1

# name: (direction, bytes, displacement from the pointer, MOVBE Code the export must contain).
EXPORTS = {
    "load16": ("load", 2, 0, Code.MOVBE_R16_M16),
    "load32": ("load", 4, 0, Code.MOVBE_R32_M32),
    "load64": ("load", 8, 0, Code.MOVBE_R64_M64),
    "load16_r10": ("load", 2, 1, Code.MOVBE_R16_M16),
    "load64_r11": ("load", 8, 3, Code.MOVBE_R64_M64),
    "store16": ("store", 2, 0, Code.MOVBE_M16_R16),
    "store32": ("store", 4, 0, Code.MOVBE_M32_R32),
    "store64": ("store", 8, 0, Code.MOVBE_M64_R64),
    "store64_index": ("store", 8, 3, Code.MOVBE_M64_R64),
    "roundtrip32": ("roundtrip", 4, 0, Code.MOVBE_M32_R32),
}

# Source mutations of the generated C++. Each control DLL must disagree with the reference somewhere.
SWAP = re.compile(r"v = static_cast<(\w+)>\(\(v << 8\) \| \(\(a >> \(8 \* k\)\) & 0xffu\)\);")
CONTROLS = {
    # The bytes are copied in memory order instead of reversed.
    "noswap": (SWAP, lambda m: f"v = static_cast<{m.group(1)}>((v << 8) | ((a >> (8 * (sizeof v - 1 - k))) & 0xffu));"),
    # A 16-bit register destination is zero-extended like a 32-bit one.
    "clear16": (re.compile(r"\(r\w+ & ~65535ull\) \| "), ""),
    # The swap also clears ZF and CF, as a flag-writing instruction would.
    "flags": (SWAP, lambda m: m.group(0) + " zero = false; carry = false;"),
}

PAD = 64  # guard bytes on each side of the data, compared like the data
DATA = bytes((0x11 * k + 0x5a) & 0xff for k in range(48))
OFFSETS = (0, 1, 2, 3, 5, 7, 8, 13, 16)
VALUES = (0, 1, 0x0102030405060708, 0x8000000000000001, 0xffffffffffffffff, 0x00ff00ff00ff00ff,
          0xdeadbeefcafef00d, 0x7f)
PRESETS = (0, 1, 1 << 63, 3 << 62)  # add r8, r8: (ZF, CF) = (1, 0), (0, 0), (1, 1), (0, 1)


def emit(image, output, control="lifted"):
    parts = [
        "#include <intrin.h>\n",
        INTEGER_HEADER,
        'extern "C" __declspec(dllexport) int host_has_movbe() {\n'
        "    int regs[4]{};\n"
        "    __cpuid(regs, 1);\n"
        "    return (regs[2] & (1 << 22)) != 0;\n"
        "}\n",
    ]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name, (*_, code) in EXPORTS.items():
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            if code not in {i.code for i in body}:
                raise AssertionError(f"{name} does not contain {code}")
            lowered = lower(body, ["rcx = a; rdx = b; r8 = c; r9 = state;"], {}, {}, {})
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b, word c, word state) {{\n{lowered}\n}}\n')
    text = "".join(parts)
    if control != "lifted":
        expression, replacement = CONTROLS[control]
        text, count = expression.subn(replacement, text)
        if not count:
            raise AssertionError(f"control {control} changed nothing")
        print(f"control {control}: {count} replacements")
    output.write_text(text, encoding="ascii")


def swapped(raw):
    return int.from_bytes(raw, "big")


def reference(name, offset, value, preset):
    """(RAX, (CF << 1) | ZF, buffer) after the export runs on DATA between its guards."""
    direction, size, disp, _ = EXPORTS[name]
    total = preset + preset
    flags = int(total > MASK64) << 1 | int(total & MASK64 == 0)
    buffer = bytearray(b"\xcc" * PAD + DATA + b"\xcc" * PAD)
    at = PAD + offset + disp
    if direction == "load":
        loaded = swapped(buffer[at:at + size])
        rax = (value & ~0xffff | loaded) if size == 2 else loaded
    elif direction == "store":
        buffer[at:at + size] = (value & ((1 << 8 * size) - 1)).to_bytes(size, "big")
        rax = value
    else:
        rax = swapped(buffer[at:at + size])
        buffer[at + 8:at + 8 + size] = buffer[at:at + size]
    return rax, flags, bytes(buffer)


def cases():
    for name in EXPORTS:
        for offset in OFFSETS:
            for value in VALUES:
                for preset in PRESETS:
                    yield name, (offset, value, preset)


def load_lib(path):
    lib = ctypes.CDLL(str(Path(path).resolve()))
    for name in EXPORTS:
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_void_p, U64, U64, ctypes.POINTER(U64)], U64
    return lib


def mismatches(lib, expected):
    found = []
    state = U64()
    for name, (offset, value, preset), want in expected:
        buffer = (ctypes.c_uint8 * (2 * PAD + len(DATA))).from_buffer_copy(b"\xcc" * PAD + DATA + b"\xcc" * PAD)
        state.value = 0xdeadbeef
        rax = getattr(lib, name)(ctypes.addressof(buffer) + PAD + offset, value, preset, ctypes.byref(state))
        got = (rax, state.value, bytes(buffer))
        if got != want:
            found.append((name, (offset, value, preset), want, got))
    return found


def describe(case):
    name, args, want, got = case
    return (f"{name}(offset={args[0]}, value={args[1]:#x}, preset={args[2]:#x}) = (rax={got[0]:#x}, flags={got[1]}), "
            f"expected (rax={want[0]:#x}, flags={want[1]})" + ("; memory differs" if got[2] != want[2] else ""))


def check(native_path, lifted_path, *control_paths):
    lifted = ctypes.CDLL(str(Path(lifted_path).resolve()))
    lifted.host_has_movbe.argtypes, lifted.host_has_movbe.restype = [], ctypes.c_int
    if not lifted.host_has_movbe():
        print("Host CPU lacks MOVBE (CPUID leaf 1 ECX bit 22); skipping native differential check.")
        sys.exit(77)
    expected = [(name, args, reference(name, *args)) for name, args in cases()]
    for label, path in (("native", native_path), ("lifted", lifted_path)):
        bad = mismatches(load_lib(path), expected)
        if bad:
            raise AssertionError(f"{label}: {len(bad)} mismatches; first {describe(bad[0])}")
    print(f"{len(expected)} cases over {len(EXPORTS)} exports (RAX, ZF/CF, data and guard bytes) matched the "
          "reference in native and translated DLLs")
    for path in control_paths:
        control = Path(path).stem.rsplit("_", 1)[-1]
        bad = mismatches(load_lib(path), expected)
        print(f"control {control}: {len(bad)}/{len(expected)} mismatches")
        if not bad:
            raise AssertionError(f"control {control} matched every case")


if __name__ == "__main__":
    mode, native, other, *rest = sys.argv[1:]
    if mode == "emit":
        emit(Path(native), Path(other), *rest)
    elif mode == "check":
        check(native, other, *rest)
    else:
        raise ValueError(mode)
