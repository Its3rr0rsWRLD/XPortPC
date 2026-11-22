"""Differential checks and rejection controls for recompiled scalar SSE/SSE2 leaf functions."""

import ctypes
from pathlib import Path
import random
import struct
import sys
from tempfile import TemporaryDirectory

import pefile
from iced_x86 import Decoder, Mnemonic as M

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from cpu_leaf_aot import export_rva
from cpu_ranges import function_ranges
from cpu_sse_aot import translate

SIGNATURES = {"blend_ss": "f:ffqf", "blend_sd": "d:ddqd", "convert": "q:fdq", "from_int": "d:qq",
              "classify_ss": "q:ff", "classify_sd": "q:dq", "round_trip": "f:f",
              "zero_xorps": "d:d", "zero_pxor": "d:d", "zero_xorpd": "d:d", "probe_ss": "q:qff"}
GUARD = bytes.fromhex("5a5a1234a5a54321")
FILL = 0xa5
MASK32 = 0xffffffff
# A float argument occupies the low dword of its XMM register. The rest is not part of the value.
JUNK = 0xdeadbeef << 32

SINGLES = [
    0x00000000, 0x80000000, 0x3f800000, 0xbf800000, 0x3f000000, 0x3fc00000, 0x40200000, 0xc0200000,
    0x3e99999a, 0x3f7fffff, 0xbf7fffff, 0x33800000, 0x4b800000, 0x4b800001,
    0x00000001, 0x807fffff, 0x00800000, 0x7f7fffff, 0xff7fffff,          # denormals, smallest normal, largest
    0x7f800000, 0xff800000,                                              # infinities
    0x7fc00000, 0xffc00000, 0x7fc12345, 0xffe54321,                      # quiet NaNs
    0x7f800001, 0xffa00000, 0x7fbfffff,                                  # signalling NaNs
    0x4f000000, 0x4effffff, 0xcf000000, 0xcf000001,                      # around +-2^31
    0x5f000000, 0x5effffff, 0xdf000000, 0xdf000001,                      # around +-2^63
]
DOUBLES = [
    0x0000000000000000, 0x8000000000000000, 0x3ff0000000000000, 0xbff0000000000000, 0x3fe0000000000000,
    0x3ff8000000000000, 0x4004000000000000, 0xc004000000000000, 0x3fb999999999999a, 0x3fefffffffffffff,
    0x0000000000000001, 0x800fffffffffffff, 0x0010000000000000, 0x7fefffffffffffff, 0xffefffffffffffff,
    0x7ff0000000000000, 0xfff0000000000000,
    0x7ff8000000000000, 0xfff8000000000000, 0x7ff8000012345678, 0xfffc0000deadbeef,
    0x7ff0000000000001, 0xfff4000000000000, 0x7ff7ffffffffffff,
    0x41e0000000000000, 0x41dfffffffe00000, 0xc1e0000000000000, 0xc1e0000000100000, 0xc1e0000000200000,
    0x43e0000000000000, 0x43dfffffffffffff, 0xc3e0000000000000, 0xc3e0000000000001,
    0x47efffffefffffff, 0x47effffff0000000, 0xc7effffff0000000,          # rounds to FLT_MAX, to infinity
    0x36a0000000000000, 0x3690000000000000, 0x380fffffffffffff,          # float denormal range and below
    0x3ff0000010000000, 0x3ff0000030000000,                              # ties when narrowed to float
]
INTEGERS = [
    0, 1, 2, 0x7fffffff, 0x80000000, 0xffffffff, 0x100000000, 0x1000001, 0x1000003, 0xfffffffffeffffff,
    (1 << 53) + 1, (1 << 53) + 3, (1 << 63) - 1, 1 << 63, (1 << 64) - 1, 0x7fffff4000000000,
    0x7fffffbfffffffff, 0x7ffffffffffffbff, 0x0123456789abcdef, 0xfedcba9876543210, 0x123456780fffffff,
]
_rng = random.Random(2027)
SINGLES += [_rng.getrandbits(32) for _ in range(12)]
DOUBLES += [_rng.getrandbits(64) for _ in range(12)]
# Random bit patterns rarely land in a convertible range, so add values of moderate size too.
SINGLES += [struct.unpack("<I", struct.pack("<f", _rng.uniform(-3e9, 3e9)))[0] for _ in range(6)]
DOUBLES += [struct.unpack("<Q", struct.pack("<d", _rng.uniform(-3e19, 3e19)))[0] for _ in range(6)]
INTEGERS += [_rng.getrandbits(64) for _ in range(40)]


def is_nan(bits, width):
    exponent, fraction = (0xff, 23) if width == 4 else (0x7ff, 52)
    return bits >> fraction & exponent == exponent and bits & ((1 << fraction) - 1) != 0


def cases():
    """(export, slot values with None at the pointer slot, initial bytes behind the pointer)."""
    found = []
    for i, a in enumerate(SINGLES):
        for j, b in enumerate(SINGLES):
            c = SINGLES[(5 * i + 3 * j) % len(SINGLES)]
            d = SINGLES[(i + 7 * j + 2) % len(SINGLES)]
            found.append(("blend_ss", (a, b, None, d), struct.pack("<II", c, 0x0badf00d)))
            found.append(("classify_ss", (a, b), b""))
    for i, a in enumerate(DOUBLES):
        for j, b in enumerate(DOUBLES):
            c = DOUBLES[(5 * i + 3 * j) % len(DOUBLES)]
            d = DOUBLES[(i + 7 * j + 2) % len(DOUBLES)]
            found.append(("blend_sd", (a, b, None, d), struct.pack("<QQ", c, 0x0badf00d0badf00d)))
            found.append(("classify_sd", (a, None), struct.pack("<Q", b)))
    for i, f in enumerate(SINGLES):
        for step in (0, 1, 5, 11, 17, 23, 29, 31):
            found.append(("convert", (f, DOUBLES[(i + step * (i + 1)) % len(DOUBLES)], None), bytes([FILL]) * 80))
    for name in ("zero_xorps", "zero_pxor", "zero_xorpd"):
        found.extend((name, (value,), b"") for value in DOUBLES)
    found += [("from_int", (n, None), bytes([FILL]) * 32) for n in INTEGERS]
    found += [("round_trip", (f,), b"") for f in SINGLES]
    name, values, payload, _, _ = probe_answer(2.0, 1.0)
    found.append((name, values, payload))
    return found


def run(call, name, values, payload):
    """Call one export. Returns its result bits and the guarded bytes behind the pointer slot."""
    buffer = ctypes.create_string_buffer(GUARD + payload + GUARD, len(payload) + 16)
    kinds = SIGNATURES[name][2:]
    slots = [ctypes.addressof(buffer) + 8 if value is None else value | JUNK if kind == "f" else value
             for kind, value in zip(kinds, values)]
    return call(name, slots), buffer.raw


def library_caller(path, prefix=""):
    """Floating-point slots travel as doubles, so every bit pattern reaches XMM unchanged."""
    library = ctypes.CDLL(str(path))
    functions = {}
    for name, signature in SIGNATURES.items():
        function = getattr(library, prefix + name)
        function.argtypes = [ctypes.c_uint64 if kind == "q" else ctypes.c_double for kind in signature[2:]]
        function.restype = ctypes.c_uint64 if signature[0] == "q" else ctypes.c_double
        functions[name] = function

    def call(name, slots):
        signature = SIGNATURES[name]
        arguments = [slot if kind == "q" else struct.unpack("<d", struct.pack("<Q", slot))[0]
                     for kind, slot in zip(signature[2:], slots)]
        result = functions[name](*arguments)
        if signature[0] == "q":
            return result
        bits = struct.unpack("<Q", struct.pack("<d", result))[0]
        return bits & MASK32 if signature[0] == "f" else bits
    return call


def single(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def double(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def probe_answer(a, b):
    seed = double(2.75)
    integer = struct.pack("<i", -1) + bytes(4)
    operand = 1.5
    inputs = struct.pack("<Q8sf4x", seed, integer, operand)
    low, high = struct.unpack("<fI", struct.pack("<Q", seed))
    memory = inputs + struct.pack("<QfIfIfI", seed, low + operand, high,
                                  float(struct.unpack_from("<i", integer)[0]), high,
                                  operand, 0)
    result = 2 * (a > b) + 3 * (a < b) + (a != a or b != b)
    return "probe_ss", (None, single(a), single(b)), inputs + bytes([FILL]) * 32, result, memory


def known_answers():
    """Results fixed by the instruction set reference, independent of either build."""
    nan32, nan64 = 0xffc00000, 0xfff8000000000000
    min32, min64 = 0x80000000, 1 << 63
    def convert(f, d, *fields):
        memory = struct.pack("<IIQQQIIQIIQQQ", *fields[:9], FILL * 0x01010101, *fields[9:], d & ~MASK32 | f)
        return "convert", (f, d, None), bytes([FILL]) * 80, fields[0] + fields[1] & MASK32, memory

    return [
        # (1.5 + 2.25) * 2 - 0.5 = 7; 1.5 / 7.
        ("blend_ss", (single(1.5), single(2.25), None, single(0.5)), struct.pack("<II", single(2.0), 0),
         single(1.5 / 7.0), struct.pack("<II", single(2.0), single(7.0))),
        # inf + -inf is invalid: the default NaN has its sign set, and then propagates.
        ("blend_ss", (0x7f800000, 0xff800000, None, single(1.0)), struct.pack("<II", single(2.0), 0),
         nan32, struct.pack("<II", single(2.0), nan32)),
        # A signalling NaN in the destination is quieted and wins over the source NaN.
        ("blend_ss", (0x7f800001, 0xffe54321, None, 0x7fc12345), struct.pack("<II", 0xffa00000, 0),
         0x7fc00001, struct.pack("<II", 0xffa00000, 0x7fc00001)),
        # A NaN source propagates when the destination is a number: 0 * NaN.
        ("blend_ss", (0, 0, None, single(1.0)), struct.pack("<II", 0x7f800001, 0),
         0x7fc00001, struct.pack("<II", 0x7f800001, 0x7fc00001)),
        # (0.1 - 1) * 3 + 0.25, divided by 3, with double rounding at every step.
        ("blend_sd", (double(0.1), double(1.0), None, double(0.25)), struct.pack("<QQ", double(3.0), 0),
         double(((0.1 - 1.0) * 3.0 + 0.25) / 3.0), struct.pack("<QQ", double(3.0), double((0.1 - 1.0) * 3.0 + 0.25))),
        # 0 * inf is invalid.
        ("blend_sd", (0, 0, None, double(1.0)), struct.pack("<QQ", 0x7ff0000000000000, 0),
         nan64, struct.pack("<QQ", 0x7ff0000000000000, nan64)),
        # -0 - -0 = +0, +0 * -1 = -0, -0 + -0 = -0, -0 / -1 = +0.
        ("blend_sd", (min64, min64, None, min64), struct.pack("<QQ", double(-1.0), 0),
         0, struct.pack("<QQ", double(-1.0), min64)),
        # Truncation toward zero, then the integer indefinite for NaN and for values out of range.
        convert(single(-2.75), double(2.75), 0xfffffffe, 2, (1 << 64) - 2, 2, double(-2.75), single(2.75),
                single(-2.75), double(2.75), 2, double(2.75), double(2.75) & ~MASK32 | single(2.75)),
        convert(0x7fc00000, 0xfff8000000000000, min32, min32, min64, min64, 0x7ff8000000000000, 0xffc00000,
                0x7fc00000, 0xfff8000000000000, min32, 0xfff8000000000000, 0xfff80000ffc00000),
        # 3e9 fits in 64 bits only; 2^63 fits in neither; -2^31 - 0.5 truncates to -2^31.
        convert(single(3e9), double(-2147483648.5), min32, min32, 3000000000, (1 << 64) - (1 << 31),
                double(3e9), single(-2147483648.5), single(3e9), double(-2147483648.5), min32,
                double(-2147483648.0), double(-2147483648.5) & ~MASK32 | single(-2147483648.5)),
        convert(0x5f000000, 0x43e0000000000000, min32, min32, min64, min64, 0x43e0000000000000, 0x5f000000,
                0x5f000000, 0x43e0000000000000, min32, 0x43e0000000000000, 0x43e000005f000000),
        # 2^24 + 1 is a tie in single precision and rounds to even; the low dword alone is 1.
        ("from_int", (0x100000001000001, None), bytes([FILL]) * 32, double(float(0x100000001000001) + 16777217.0),
         struct.pack("<IIQQQ", single(16777216.0), single(float(1 << 56)), double(16777217.0),
                     double(float(0x100000001000001)), 0x100000001000001)),
        # -1 as a dword and as a qword.
        ("from_int", (0xffffffff, None), bytes([FILL]) * 32, double(4294967294.0),
         struct.pack("<IIQQQ", single(-1.0), single(4294967296.0), double(-1.0), double(4294967295.0), 0xffffffff)),
        ("classify_ss", (single(1.0), single(1.0)), b"", 1, b""),
        ("classify_ss", (0x80000000, 0), b"", 1, b""),
        ("classify_ss", (single(2.0), single(1.0)), b"", 2, b""),
        ("classify_ss", (single(1.0), single(2.0)), b"", 4, b""),
        ("classify_ss", (0x7fc00000, single(1.0)), b"", 8, b""),
        ("classify_ss", (single(1.0), 0x7f800001), b"", 8, b""),
        ("classify_sd", (double(1.0), None), struct.pack("<Q", double(1.0)), 1, struct.pack("<Q", double(1.0))),
        ("classify_sd", (double(2.0), None), struct.pack("<Q", double(1.0)), 2, struct.pack("<Q", double(1.0))),
        ("classify_sd", (double(1.0), None), struct.pack("<Q", double(2.0)), 4, struct.pack("<Q", double(2.0))),
        ("classify_sd", (0x7ff0000000000001, None), struct.pack("<Q", 0), 8, struct.pack("<Q", 0)),
        ("zero_xorps", (double(1.0),), b"", 0, b""),
        ("zero_pxor", (double(-2.0),), b"", 0, b""),
        ("zero_xorpd", (double(3.0),), b"", 0, b""),
        # The conversion pair quiets a signalling NaN and keeps a quiet one and a number unchanged.
        ("round_trip", (0x7f800001,), b"", 0x7fc00001, b""),
        ("round_trip", (0xffa00000,), b"", 0xffe00000, b""),
        ("round_trip", (0x7fc12345,), b"", 0x7fc12345, b""),
        ("round_trip", (single(-2.75),), b"", single(-2.75), b""),
        probe_answer(1.0, 1.0),
        probe_answer(float("nan"), 1.0),
    ]


def check(original, lifted, swapped, swapped_lifted):
    """Each argument is call(name, slots) -> result bits for one build of the fixture."""
    for name, values, payload, result, memory in known_answers():
        for label, call in (("source fixture", original), ("translation", lifted)):
            got, raw = run(call, name, values, payload)
            if got != result or raw != GUARD + memory + GUARD:
                raise AssertionError(f"{label} {name}{values}: {got:#x} {raw.hex()}")
    matched = dict.fromkeys(SIGNATURES, 0)
    changed = dict.fromkeys(SIGNATURES, 0)
    for name, values, payload in cases():
        native = run(original, name, values, payload)
        actual = run(lifted, name, values, payload)
        if actual != native:
            raise AssertionError(f"translation mismatch for {name}{values}: {actual} != {native}")
        if native[1][:8] != GUARD or native[1][-8:] != GUARD:
            raise AssertionError(f"{name}{values} wrote outside its buffer")
        control = run(swapped, name, values, payload)
        actual = run(swapped_lifted, name, values, payload)
        if actual != control:
            raise AssertionError(f"control translation mismatch for {name}{values}: {actual} != {control}")
        matched[name] += 1
        if control != native:
            changed[name] += 1
            # b + a differs from a + b only in which NaN payload survives.
            if name == "blend_ss" and not (is_nan(values[0], 4) and is_nan(values[1], 4)):
                raise AssertionError(f"swapped addition changed {name}{values}")
            # Dropping the conversion pair differs only for a signalling NaN.
            if name == "round_trip" and not (is_nan(values[0], 4) and not values[0] & 0x400000):
                raise AssertionError(f"dropping the conversion pair changed {name}{values}")
    if not all(changed.values()):
        raise AssertionError(f"swapped-operand control matched the original: {changed}")
    print(f"{len(known_answers())} fixed results and {matched} calls match on the result and the guarded "
          f"buffer for the original and the swapped-operand build; swapped operands changed {changed}")


def check_rejections(original_path):
    data = Path(original_path).read_bytes()
    with pefile.PE(data=data, fast_load=True) as pe:
        code = {}
        for name in SIGNATURES:
            entry = export_rva(pe, name)
            (begin, end), = function_ranges(pe, entry)
            code[name] = list(Decoder(64, pe.get_data(begin, end - begin), ip=begin))
        offset = pe.get_offset_from_rva

    def first(name, mnemonic):
        return next(i for i in code[name] if i.mnemonic == mnemonic)

    def patch(start, encoding, *more):
        """Replace whole instructions, starting at one, by an encoding padded with NOPs."""
        length = start.len + sum(i.len for i in more)
        raw = bytes.fromhex(encoding)
        assert len(raw) <= length and all(a.next_ip == b.ip for a, b in zip((start, *more), more))
        return start.ip, raw.ljust(length, b"\x90")

    add, copy, multiply = first("blend_ss", M.ADDSS), first("blend_ss", M.MOVAPS), first("blend_ss", M.MULSS)
    load, subtract = first("blend_ss", M.MOVSS), first("blend_ss", M.SUBSS)
    truncate = next(i for i in code["convert"] if i.mnemonic == M.CVTTSS2SI and i.len == 5)
    compare, parity, below_equal = (first("classify_ss", m) for m in (M.UCOMISS, M.JP, M.JBE))
    assert load.next_ip == multiply.ip and compare.next_ip == parity.ip
    everything = [f"{name}={signature}" for name, signature in SIGNATURES.items()]
    controls = [
        (patch(add, "0f 58 d1"), "unsupported instruction", "packed ADDPS"),
        (patch(add, "f3 0f 51 d1"), "unsupported instruction", "SQRTSS"),
        (patch(add, "c5 ea 58 d1"), "unsupported instruction", "VEX-encoded VADDSS"),
        (patch(add, "f2 0f 58 d1"), "undefined register xmm1[63:32]", "ADDSD on float arguments"),
        (patch(subtract, "0f 57 d3"), "unsupported instruction", "XORPS of two registers"),
        (patch(copy, "0f 28 f0"), "nonvolatile register xmm6", "write to XMM6"),
        (patch(multiply, "f3 0f 59 d5"), "undefined register xmm5", "read of an unwritten register"),
        (patch(load, "f3 0f 10 25 00 00 00 00", multiply), "unsupported memory operand", "RIP-relative load"),
        (patch(truncate, "f3 48 0f 2d d0"), "unsupported instruction", "CVTSS2SI, which rounds by MXCSR"),
        (patch(truncate, "66 48 0f 7e c2"), "unsupported instruction", "MOVQ to an integer register"),
        ((below_equal.ip, b"\x7e"), "unsupported condition after a float compare", "JLE after COMISS"),
        (patch(below_equal, ""), "float compare without a conditional branch", "COMISS without a jump"),
        # CMP EAX, 1 and JB in place of UCOMISS and JP: the JNE that follows no longer has a producer.
        ((compare.ip, bytes.fromhex("83 f8 01 72")), "flags cross a branch", "second jump after CMP"),
    ]
    with TemporaryDirectory() as folder:
        path = Path(folder) / "control.dll"
        for (rva, raw), reason, label in controls:
            damaged = bytearray(data)
            damaged[offset(rva):offset(rva) + len(raw)] = raw
            path.write_bytes(damaged)
            try:
                translate(path, everything)
            except ValueError as exc:
                if reason not in str(exc):
                    raise AssertionError(f"{label}: {exc}") from exc
            else:
                raise AssertionError(f"accepted control: {label}")
    signatures = [
        ("blend_ss=f:qfqf", "undefined register xmm2"),
        ("blend_ss=f:ffq", "undefined register xmm3"),
        ("blend_ss=d:ffqf", "undefined register xmm0[63:32]"),
        ("blend_sd=d:fdqd", "undefined register xmm0[63:32]"),
        ("from_int=d:qf", "undefined register rdx"),
        ("from_int=q:qq", "undefined register rax"),
        ("blend_ss=f:ffqfq", "invalid signature"),
        ("blend_ss=i:ffqf", "invalid signature"),
    ]
    for export, reason in signatures:
        try:
            translate(original_path, [export])
        except ValueError as exc:
            if reason not in str(exc):
                raise AssertionError(f"{export}: {exc}") from exc
        else:
            raise AssertionError(f"accepted signature: {export}")
    print(f"{len(controls)} patched-instruction rejections and {len(signatures)} signature rejections passed")


if __name__ == "__main__":
    original, lifted, swapped, swapped_lifted = sys.argv[1:]
    check(library_caller(original), library_caller(lifted, "lifted_"),
          library_caller(swapped), library_caller(swapped_lifted, "lifted_"))
    check_rejections(original)
