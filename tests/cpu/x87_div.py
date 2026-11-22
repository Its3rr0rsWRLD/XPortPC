"""Compare native and translated FDIV and FDIVR forms of the x87 leaf-function profile: m32 and m64
operands, ST(0), ST(i), ST(i), ST(0), FDIVP and FDIVRP ST(i), ST(0).

Usage:
    python tests/cpu/x87_div.py asm <asm> <def>             regenerate the MASM source and exports
    python tests/cpu/x87_div.py emit <dll> <cpp> [control]   translate (and optionally mutate) the fixture
    python tests/cpu/x87_div.py check <harness> <native> <lifted> [controls...]

The exports, harness and guards follow tests/cpu/x87_add.py, whose exact-rational helpers this check
reuses with the memory-operand and NaN rules of tests/cpu/x87_mul.py; the quotient model below is
independent of tools/x87_soft.h. emit also checks that every decoded x87 instruction is the form the
sequence names, so an assembler that exchanges FDIV and FDIVR register forms fails before the run.
"""
from pathlib import Path
import platform
import random
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import x87_add as base  # noqa: E402  (tests/cpu is the script directory)
from x87_add import INDEFINITE, J, classify, from_binary, m80, m80_bytes, round_format, to_binary  # noqa: E402
from x87_mul import nan_result, operand  # noqa: E402

INPUT, OUTPUT = base.INPUT, base.OUTPUT
SIZE = {"m32": 4, "m64": 8, "m80": 10}

# name: (input kind, sequence). Arithmetic steps are (mnemonic, "mem", kind, offset) for an m32/m64
# operand, (mnemonic, "st0", i) for "op st, st(i)", (mnemonic, "sti", i) for "op st(i), st" and
# (mnemonic, "pop", i) for the popping form "op st(i), st".
P80 = [("fld", "m80", 0), ("fld", "m80", 16)]
SEQUENCES = {
    "div_m80": ("pair80", P80 + [("fdivp", "pop", 1), ("fstp", "m80", 0)]),
    "div_to_m64": ("pair80", P80 + [("fdivp", "pop", 1), ("fstp", "m64", 0)]),
    "div_to_m32": ("pair80", P80 + [("fdivp", "pop", 1), ("fstp", "m32", 0)]),
    "divr_m80": ("pair80", P80 + [("fdivrp", "pop", 1), ("fstp", "m80", 0)]),
    "div_st0_sti": ("pair80", P80 + [("fdiv", "st0", 1), ("fstp", "m80", 0), ("fstp", "m80", 16)]),
    "div_sti_st0": ("pair80", P80 + [("fdiv", "sti", 1), ("fstp", "m80", 0), ("fstp", "m80", 16)]),
    "divr_st0_sti": ("pair80", P80 + [("fdivr", "st0", 1), ("fstp", "m80", 0), ("fstp", "m80", 16)]),
    "divr_sti_st0": ("pair80", P80 + [("fdivr", "sti", 1), ("fstp", "m80", 0), ("fstp", "m80", 16)]),
    "div_self": ("m80", [("fld", "m80", 0), ("fdiv", "st0", 0), ("fstp", "m80", 0)]),
    "div_mem32": ("m80_f32", [("fld", "m80", 0), ("fdiv", "mem", "m32", 16), ("fstp", "m80", 0)]),
    "div_mem64": ("m80_f64", [("fld", "m80", 0), ("fdiv", "mem", "m64", 16), ("fstp", "m80", 0)]),
    "divr_mem32": ("m80_f32", [("fld", "m80", 0), ("fdivr", "mem", "m32", 16), ("fstp", "m80", 0)]),
    "divr_mem64": ("m80_f64", [("fld", "m80", 0), ("fdivr", "mem", "m64", 16), ("fstp", "m80", 0)]),
    "div_f32": ("pair32", [("fld", "m32", 0), ("fdiv", "mem", "m32", 4), ("fstp", "m32", 0)]),
    "div_f64": ("pair64", [("fld", "m64", 0), ("fdiv", "mem", "m64", 8), ("fstp", "m64", 0)]),
    # a / (b / c) through FDIVP ST(1), ST(0) and then FDIVRP ST(1), ST(0) on the reloaded a.
    "div_three": ("triple80", [("fld", "m80", 16), ("fld", "m80", 32), ("fdivp", "pop", 1), ("fld", "m80", 0),
                               ("fdivrp", "pop", 1), ("fstp", "m80", 0)]),
    # b / (a / c) through FDIVP ST(2), ST(0) and then FDIVRP ST(1), ST(0).
    "div_skip": ("triple80", [("fld", "m80", 0), ("fld", "m80", 16), ("fld", "m80", 32), ("fdivp", "pop", 2),
                              ("fdivrp", "pop", 1), ("fstp", "m80", 0)]),
}

# Source mutations of the generated C++ (the helper header is part of it). Each control must mismatch.
CONTROLS = {
    # The quotient rounds to 64 significand bits, as with precision control 64.
    "pc64": (base.ARITH, "x87_arith{64, 16383, 0x7ffe}"),
    # The quotient rounds in the binary64 exponent range, as host double arithmetic would.
    "double": (base.ARITH, "x87_arith{53, 1023, 0x7fe}"),
    # A nonzero remainder is ignored when rounding.
    "nosticky": (re.compile(r"const uint64_t lo = [^;]*;  // div sticky"), "const uint64_t lo = 0;  // div sticky"),
    # A finite nonzero value by zero gives the indefinite instead of infinity.
    "divzero": (re.compile(r"if \(ia \|\| zb\) return"), "if (zb) return x87_indefinite; if (ia) return"),
    # FDIVR divides in the FDIV order.
    "reverse": (re.compile(r"x87_divr\(X87Value a, X87Value b, uint16_t cw\) \{ return x87_div\(b, a, cw\); \}"),
                "x87_divr(X87Value a, X87Value b, uint16_t cw) { return x87_div(a, b, cw); }"),
    # A zero quotient (zero dividend or infinite divisor) is always +0.
    "zerosign": (re.compile(r"if \(ib \|\| za\) return \{0, s\};"), "if (ib || za) return {0, 0};"),
    # m32 and m64 operands are quieted before the NaN rules see them, as a plain load would.
    "memquiet": (re.compile(r"(x87_operand_f(?:32|64)\(uint(?:32|64)_t bits\) \{ return x87_from_binary\([^)]*), false\)"),
                 r"\1, true)"),
}


# ---- MASM generation and decoding ------------------------------------------------------------------

def asm_line(step):
    op, *args = step
    if op in ("fld", "fstp"):
        return base.asm_line(step)
    form = args[0]
    if form == "mem":
        return f"    {op} {base.PTR[args[1]]} ptr [rcx+{args[2]}]"
    if form == "st0":
        return f"    {op} st, st({args[1]})"
    return f"    {op} st({args[1]}), st"


def expected_form(step):
    """(mnemonic, operands) of the instruction iced should decode for a step."""
    op, *args = step
    if op in ("fld", "fstp"):
        return op, args[0]
    if args[0] == "mem":
        return op, args[1]
    i = args[1]
    return op, (f"st0,st{i}" if args[0] == "st0" else f"st{i},st0")


def decoded_form(i):
    from iced_x86 import MemorySize as S, Mnemonic as M, OpKind as K, Register as R

    mnemonic = next(name for name, value in vars(M).items() if value == i.mnemonic).lower()
    if i.op_count == 1 and i.op0_kind == K.MEMORY:
        return mnemonic, {S.FLOAT32: "m32", S.FLOAT64: "m64", S.FLOAT80: "m80"}[i.memory_size]
    return mnemonic, f"st{i.op0_register - R.ST0},st{i.op1_register - R.ST0}"


def write_asm(asm_path, def_path):
    lines = ["; Generated by tests/cpu/x87_div.py asm; edit SEQUENCES there and regenerate.",
             "; Source-owned differential fixture for the FDIV and FDIVR forms of the x87 leaf-function profile.",
             "; Each export reads an input block at RCX, writes an output block at RDX and returns with the x87",
             "; stack empty.", ".code", ""]
    for name, (_, steps) in SEQUENCES.items():
        lines += [f"{name} PROC FRAME", "    .endprolog", *(asm_line(s) for s in steps), "    ret", f"{name} ENDP", ""]
    lines.append("END")
    Path(asm_path).write_text("\n".join(lines) + "\n", encoding="ascii")
    Path(def_path).write_text("EXPORTS\n" + "".join(f"    {name}\n" for name in SEQUENCES), encoding="ascii")


# ---- Translation -----------------------------------------------------------------------------------

def emit(image, output, control="lifted"):
    import pefile
    from cpu_leaf_aot import export_rva
    from cpu_ranges import function_ranges
    from ffx_version_query import INTEGER_HEADER, lower, region
    from x87_lower import X87_HEADER, is_x87

    parts = [INTEGER_HEADER, X87_HEADER]
    with pefile.PE(str(image), fast_load=True) as pe:
        for name, (_, steps) in SEQUENCES.items():
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            body = region(pe, *bounds)
            decoded = [decoded_form(i) for i in body if is_x87(i)]
            if decoded != [expected_form(s) for s in steps]:
                raise AssertionError(f"{name} assembled as {decoded}, expected {[expected_form(s) for s in steps]}")
            code = lower(body, ["rcx = a; rdx = b;"], {}, {}, {}, x87=True)
            parts.append(f'extern "C" __declspec(dllexport) word {name}(word a, word b) {{\n{code}\n}}\n')
    text = "".join(parts)
    if control != "lifted":
        expression, replacement = CONTROLS[control]
        text, count = expression.subn(replacement, text)
        if not count:
            raise AssertionError(f"control {control} changed nothing")
        print(f"control {control}: {count} replacements")
    output.write_text(text, encoding="ascii")


# ---- Independent model -----------------------------------------------------------------------------

def div(a, b):
    """FDIV a / b with control word 0x027F: the exact quotient rounded to 53 bits in the extended range."""
    ca, cb = classify(a), classify(b)
    if "unsupported" in (ca[0], cb[0]):
        return INDEFINITE
    if "nan" in (ca[0], cb[0]):
        return nan_result(a, b)
    sign = ca[1] ^ cb[1]
    if ca[0] == cb[0] and ca[0] in ("inf", "zero"):
        return INDEFINITE
    if ca[0] == "inf" or cb[0] == "zero":
        return J, sign << 15 | 0x7FFF
    if cb[0] == "inf" or ca[0] == "zero":
        return 0, sign << 15
    rounded = round_format(ca[2] / cb[2], 53, 16383, 0x7FFE)
    if rounded is None:
        return J, sign << 15 | 0x7FFF
    m, biased = rounded
    return m << 11, sign << 15 | biased


FUNCTIONS = {"fdiv": div, "fdivp": div, "fdivr": lambda a, b: div(b, a), "fdivrp": lambda a, b: div(b, a)}


def reference(name, data):
    slots, out = [], bytearray(b"\xcc" * OUTPUT)

    def read(kind, offset):
        return int.from_bytes(data[offset:offset + SIZE[kind]], "little")

    for op, *args in SEQUENCES[name][1]:
        if op == "fld":
            raw = read(*args)
            slots.append((raw & (2 ** 64 - 1), raw >> 64) if args[0] == "m80" else from_binary(args[0], raw))
            continue
        if op == "fstp":
            kind, offset = args
            v = slots.pop()
            encoded = v[0] | v[1] << 64 if kind == "m80" else to_binary(kind, v)
            out[offset:offset + SIZE[kind]] = encoded.to_bytes(SIZE[kind], "little")
            continue
        f, form = FUNCTIONS[op], args[0]
        if form == "mem":
            slots[-1] = f(slots[-1], operand(args[1], read(args[1], args[2])))
        elif form == "st0":
            slots[-1] = f(slots[-1], slots[-1 - args[1]])
        else:
            slots[-1 - args[1]] = f(slots[-1 - args[1]], slots[-1])
            if form == "pop":
                slots.pop()
    assert not slots
    return bytes(out)


# ---- Inputs ----------------------------------------------------------------------------------------

def quotient_bits(a_sig, b_sig):
    """The 64-bit significand quotient and remainder that x87_soft.h forms (only to select inputs)."""
    return divmod(a_sig << 64, b_sig) if a_sig < b_sig else divmod(a_sig << 63, b_sig)


def sticky_pairs(rng, count):
    """Significand pairs whose 64-bit quotient ends exactly on a 53-bit tie (low 11 bits 0x400) with a
    nonzero remainder, so only the remainder decides the rounding."""
    rows = []
    while len(rows) < count:
        k = rng.randrange(3, 1 << 12, 2)
        n = k.bit_length() - 1
        b_sig = k << (63 - n)
        target = (rng.getrandbits(52) | 1 << 52) << 11 | 0x400
        for shift in (n + 1, n):
            a_sig = -(-(k * target) // (1 << shift))
            if J <= a_sig < 1 << 64:
                q, rem = quotient_bits(a_sig, b_sig)
                if q & 0x7FF == 0x400 and rem:
                    rows.append((a_sig, b_sig))
    return rows


def pairs80():
    s = base.special_m80()
    rows = [(a, b) for a in s for b in s]
    rng = random.Random(4096)
    for _ in range(100):  # (2^53 + 1) k / k: an exact quotient halfway between 53-bit neighbours
        k = rng.randrange(1, 1 << 10, 2)
        rows.append((m80(((1 << 53) + 1) * k, rng.randint(-80, 80)), m80(k if rng.random() < 0.5 else -k, 0)))
    for a_sig, b_sig in sticky_pairs(rng, 120):
        ea = rng.choice((0x3FFF, 0x3FFF + 30, 0x3FFF - 30, 0x3FFF - 16382 + 60))
        rows.append(((a_sig, ea | rng.choice((0, 0x8000))), (b_sig, 0x3FFF)))
    one = (J, 0x3FFF)
    rows += [
        (m80(1), m80(3)), (m80(-2), m80(3)), (m80(10), m80(4)), (m80(1), m80(10)), ((J | 1 << 10, 0x3FFF), one),
        ((J | 1, 0x3FFF), one), (one, (J | 1, 0x3FFF)), (one, (0xFFFFFFFFFFFFFFFF, 0x3FFF)),
        (m80(1, 800), m80(1, -400)), (m80(3, -800), m80(7, 400)), (m80(1, 1023), m80(1, -2)),  # binary64 range
        (m80(1, -1074), m80(2)), (m80(3, -1074), m80(2)), (m80(1, -1022), m80(1, 53)),
        ((0xFFFFFFFFFFFFF800, 0x7FFE), m80(1, -1)), ((0xFFFFFFFFFFFFF800, 0x7FFE), (0xFFFFFFFFFFFFFFFF, 0x3FFE)),
        (m80(1, 16000), m80(1, -383)), (m80(1, 16000), m80(1, -384)), (m80(1, -16000), m80(1, 382)),  # range edges
        (m80(1, -16000), m80(1, 383)), (m80(1, -16000), m80(1, 446)), (m80(3, -16000), m80(1, 447)),
        ((J - 1, 0), (J, 0x3FFF + 1)), ((J - 1, 0), (J | 1, 0x3FFF)), ((1, 0), (J, 0x3FFF - 62)), ((0x801, 0), one),
        ((J, 1), m80(3)), ((J | 1, 1), (0xFFFFFFFFFFFFFFFF, 0x3FFF)),
        ((J | 5, 0x7FFF), (J | 5, 0xFFFF)), ((J | 5, 0xFFFF), (J | 5, 0x7FFF)),               # NaN ties by sign
    ]
    for _ in range(600):
        a = (J | rng.getrandbits(63), rng.randint(0x3FFF - 200, 0x3FFF + 200) | rng.choice((0, 0x8000)))
        b = (J | rng.getrandbits(63), rng.randint(0x3FFF - 200, 0x3FFF + 200) | rng.choice((0, 0x8000)))
        rows.append((a, b))
    for _ in range(200):  # quotients near the extended underflow and overflow thresholds
        low = rng.random() < 0.5
        ea = rng.randint(1, 0x3FFF - 100) if low else rng.randint(0x3FFF + 100, 0x7FFE)
        target = rng.randint(-80, 5) if low else rng.randint(0x7FFE - 3, 0x7FFE + 3)
        eb = ea - target + 0x3FFF
        if 1 <= eb <= 0x7FFE:
            rows.append(((J | rng.getrandbits(63), ea), (J | rng.getrandbits(63), eb | rng.choice((0, 0x8000)))))
    return rows


def cases():
    f64, f32 = base.f64_bits(), base.f32_bits()
    specials = base.special_m80()
    rng = random.Random(7)

    def random_m80():
        return J | rng.getrandbits(63), rng.randint(0x3FFF - 300, 0x3FFF + 300) | rng.choice((0, 0x8000))

    def m80_block(*values):
        return b"".join(m80_bytes(v) for v in values)

    blocks = {
        "pair80": [m80_block(a, b) for a, b in pairs80()],
        "m80": [m80_bytes(v) for v in base.m80_singles()] + [m80_bytes(random_m80()) for _ in range(200)],
        "m80_f32": [m80_bytes(v) + b.to_bytes(4, "little") for v in specials for b in f32[:17]]
                   + [m80_bytes(random_m80()) + rng.getrandbits(32).to_bytes(4, "little") for _ in range(300)],
        "m80_f64": [m80_bytes(v) + b.to_bytes(8, "little") for v in specials for b in f64[:18]]
                   + [m80_bytes(random_m80()) + rng.getrandbits(64).to_bytes(8, "little") for _ in range(300)],
        "pair32": [a.to_bytes(4, "little") + b.to_bytes(4, "little") for a in f32[:17] for b in f32[:17]]
                  + [rng.getrandbits(32).to_bytes(4, "little") + rng.getrandbits(32).to_bytes(4, "little")
                     for _ in range(300)],
        "pair64": [a.to_bytes(8, "little") + b.to_bytes(8, "little") for a in f64[:18] for b in f64[:18]]
                  + [rng.getrandbits(64).to_bytes(8, "little") + rng.getrandbits(64).to_bytes(8, "little")
                     for _ in range(300)],
        "triple80": [m80_block(*rng.sample(specials, 3)) for _ in range(200)]
                    + [m80_block(random_m80(), random_m80(), random_m80()) for _ in range(300)],
    }
    for name, (kind, _) in SEQUENCES.items():
        for block in blocks[kind]:
            yield name, block.ljust(INPUT, b"\0")


# ---- Check -----------------------------------------------------------------------------------------

def check(harness_path, native_path, lifted_path, *control_paths):
    expected = [(name, data, reference(name, data)) for name, data in cases()]
    for label, path in (("native", native_path), ("lifted", lifted_path)):
        run = base.Runner(harness_path, path)
        bad = 0
        for name, data, want in expected:
            got, state = run(name, data)
            if not base.entry_state_ok(state):
                raise AssertionError(f"{label} {name} left state {state:#014x}; the profile requires control "
                                     "0x027f and an empty stack at TOP 0")
            if got != want:
                if not bad:
                    print(f"{label} first mismatch: {name}(input {data[:48].hex()})\n  got      {got[:16].hex()}\n"
                          f"  expected {want[:16].hex()}")
                bad += 1
        if bad:
            raise AssertionError(f"{label}: {bad}/{len(expected)} mismatches")
    print(f"{len(expected)} cases over {len(SEQUENCES)} exports (output block and guards) matched the reference "
          "in native and translated DLLs; each export returned with control 0x027f and an empty stack")
    print(f"processor: {platform.processor()}")
    first = {}
    for name, data, want in expected:
        first.setdefault(name, (data, want))
    for label, path in (("native", native_path), ("lifted", lifted_path)):
        run = base.Runner(harness_path, path)
        failed = [name for name, (data, want) in first.items() if not base.preserved(run, "x87_call", name, data, want)]
        if failed:
            raise AssertionError(f"x87_call lost a live caller value or control word around {label} {failed}")
    print(f"x87_call kept a live caller ST(0) value and control word around all {len(first)} native and "
          "translated exports")
    for path in control_paths:
        control = Path(path).stem.rsplit("_", 1)[-1]
        run = base.Runner(harness_path, path)
        bad = sum(1 for name, data, want in expected if run(name, data)[0] != want)
        print(f"control {control}: {bad}/{len(expected)} mismatches")
        if not bad:
            raise AssertionError(f"control {control} matched every case")
    check_rejections()


def check_rejections():
    from iced_x86 import Decoder
    from ffx_version_query import lower

    def attempt(hex_bytes):
        body = list(Decoder(64, bytes.fromhex(hex_bytes), ip=0x1000))
        try:
            lower(body, [], {}, {}, {}, x87=True)
        except ValueError as exc:
            return str(exc)
        return None

    fld, fstp = "db 29", "db 3a"  # fld tbyte ptr [rcx]; fstp tbyte ptr [rdx]
    rejected = {
        "fdivp st(0), st": (attempt(f"{fld} {fld} de f8 {fstp} {fstp} c3"), "unsupported x87 operation"),
        "fdivrp st(0), st": (attempt(f"{fld} {fld} de f0 {fstp} {fstp} c3"), "unsupported x87 operation"),
        "fdiv m32 on an empty stack": (attempt(f"d8 31 {fld} {fstp} c3"), "x87 stack underflow"),
        "fdivr st(2), st with two values": (attempt(f"{fld} {fld} dc f2 {fstp} {fstp} c3"), "x87 stack underflow"),
        "fdivrp with one value": (attempt(f"{fld} de f1 {fstp} c3"), "x87 stack underflow"),
        "fldenv": (attempt(f"{fld} d9 21 {fstp} c3"), "unsupported x87 operation"),
        "fdecstp": (attempt(f"{fld} d9 f6 {fstp} c3"), "unsupported x87 operation"),
        "fnsave": (attempt(f"{fld} dd 31 {fstp} c3"), "unsupported x87 operation"),
        "fprem": (attempt(f"{fld} {fld} d9 f8 {fstp} {fstp} c3"), "unsupported x87 operation"),
        "fincstp": (attempt(f"{fld} d9 f7 {fstp} c3"), "unsupported x87 operation"),
    }
    for case, (message, needle) in rejected.items():
        if message is None or needle not in message:
            raise AssertionError(f"{case}: expected a rejection containing {needle!r}, got {message!r}")
    print(f"rejected {len(rejected)} sequences outside the profile: " + "; ".join(rejected))


if __name__ == "__main__":
    mode, first, second, *rest = sys.argv[1:]
    if mode == "asm":
        write_asm(first, second)
    elif mode == "emit":
        emit(Path(first), Path(second), *rest)
    elif mode == "check":
        check(first, second, *rest)
    else:
        raise ValueError(mode)
