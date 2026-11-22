"""Compare native and translated FCMOVB, FCMOVE, FCMOVBE, FCMOVNB, FCMOVNE and FCMOVNBE of the x87
leaf-function profile.

Usage:
    python tests/cpu/x87_fcmov.py asm <asm> <def>             regenerate the MASM source and exports
    python tests/cpu/x87_fcmov.py emit <dll> <cpp> [control]   translate (and optionally mutate) the fixture
    python tests/cpu/x87_fcmov.py check <harness> <native> <lifted> [controls...]

The exports, harness and guards follow tests/cpu/x87_add.py, and the other steps use the format of
tests/cpu/x87_moves.py. emit checks that every decoded x87 instruction is the form its sequence names.
The flags come from an integer CMP of two input dwords or from FCOMI; the model evaluates each condition
itself and copies raw encodings, independent of tools/x87_soft.h. Seven native-only exports (ENTRY) move
on the caller's CF or ZF, directly or through ADC, SBB, RCL or CMC: they run through x87_call_flags under
each caller CF and ZF, and translation must reject each of them.
"""
from pathlib import Path
import platform
import random
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import x87_add as base  # noqa: E402  (tests/cpu is the script directory)
import x87_compare as compare  # noqa: E402
import x87_integers as integers  # noqa: E402
from x87_add import J, Q, from_binary, m80_bytes, to_binary  # noqa: E402
from x87_div import SIZE  # noqa: E402

INPUT, OUTPUT = base.INPUT, base.OUTPUT
FCMOV = ("fcmovb", "fcmove", "fcmovbe", "fcmovnb", "fcmovne", "fcmovnbe")
CONDITION = {"fcmovb": lambda z, c: c, "fcmove": lambda z, c: z, "fcmovbe": lambda z, c: c or z,
             "fcmovnb": lambda z, c: not c, "fcmovne": lambda z, c: not z, "fcmovnbe": lambda z, c: not c and not z}
# Integer inputs at offsets 48 and 52 of the input block; m80 values at 0, 16 and 32.
CMP = ("cmp",)  # mov eax, [rcx+48]; cmp eax, [rcx+52]: ZF = equal, CF = unsigned below
P2 = [("fld", "m80", 16), ("fld", "m80", 0)]  # ST(0) = a (offset 0), ST(1) = b (offset 16)
OUT2 = [("fstp", "m80", 0), ("fstp", "m80", 16)]

# ("fcmov...", i) and ("cmp",) are the new steps; ("fcomi", i) is the step of tests/cpu/x87_compare.py,
# and the others use the x87_moves format.
SEQUENCES = {
    **{f"{op}_cmp": ("pairint", P2 + [CMP, (op, 1)] + OUT2) for op in FCMOV},
    # A third value: the move reads ST(2), and ST(1) must stay as it was.
    "fcmovb_st2": ("tripleint", [("fld", "m80", 32)] + P2 + [CMP, ("fcmovb", 2), ("fstp", "m80", 0),
                                                              ("fstp", "m80", 16), ("fstp", "m80", 32)]),
    # The flags of FCOMI: max(a, b) with FCMOVB, and min(a, b) with FCMOVNBE, as compilers emit them.
    "fcomi_max": ("pair80", P2 + [("fcomi", 1), ("fcmovb", 1)] + OUT2),
    "fcomi_min": ("pair80", P2 + [("fcomi", 1), ("fcmovnbe", 1)] + OUT2),
    # Two moves under the same flags, and a move of ST(0) onto itself.
    "fcmovne_fcmove": ("tripleint", [("fld", "m80", 32)] + P2 + [CMP, ("fcmovne", 1), ("fcmove", 2),
                                                                  ("fstp", "m80", 0), ("fstp", "m80", 16),
                                                                  ("fstp", "m80", 32)]),
    "fcmove_st0": ("pairint", P2 + [CMP, ("fcmove", 0)] + OUT2),
    # Readers of the CF that CMP defines, ahead of the move: ADC and SBB set ZF from it, CMC inverts it, and
    # RCL carries it through EAX to the ZF of TEST.
    "fcmove_adc": ("pairint", P2 + [CMP, ("mov_eax", 0xFFFFFFFF), ("adc_eax0",), ("fcmove", 1)] + OUT2),
    "fcmove_sbb": ("pairint", P2 + [CMP, ("mov_eax", 0), ("sbb_eax0",), ("fcmove", 1)] + OUT2),
    "fcmovb_cmc": ("pairint", P2 + [CMP, ("cmc",), ("fcmovb", 1)] + OUT2),
    "fcmovne_rcl": ("pairint", P2 + [CMP, ("mov_eax", 0), ("rcl_eax1",), ("test_eax",), ("fcmovne", 1)] + OUT2),
    # The deepest operand: ST(7) at depth 8, stored back as m64.
    "fcmovnb_st7": ("m64x8int", [("fld", "m64", 8 * k) for k in range(8)] + [CMP, ("fcmovnb", 7)]
                    + [("fstp", "m64", 8 * k) for k in range(8)]),
}
# Native only: the move depends on the caller's CF or ZF, directly or through an integer instruction that
# reads the caller's CF. The lowered function has no such input, and translation must reject each export.
# The value is the export's undefined flag and the first instruction that reads it.
ENTRY = {
    "fcmovb_entry": ("pair80", P2 + [("fcmovb", 1)] + OUT2),
    "fcmove_entry": ("pair80", P2 + [("fcmove", 1)] + OUT2),
    # ZF of ADC and SBB: FFFFFFFFh + 0 + CF is zero only for CF = 1, and 0 - 0 - CF only for CF = 0.
    "adc_entry": ("pair80", P2 + [("mov_eax", 0xFFFFFFFF), ("adc_eax0",), ("fcmove", 1)] + OUT2),
    "sbb_entry": ("pair80", P2 + [("mov_eax", 0), ("sbb_eax0",), ("fcmove", 1)] + OUT2),
    # The caller's CF in EAX, from ADC or RCL, then a defined ZF from TEST.
    "adc_test_entry": ("pair80", P2 + [("mov_eax", 0), ("adc_eax0",), ("test_eax",), ("fcmovne", 1)] + OUT2),
    "rcl_test_entry": ("pair80", P2 + [("mov_eax", 0), ("rcl_eax1",), ("test_eax",), ("fcmovne", 1)] + OUT2),
    # CMC inverts the caller's CF.
    "cmc_entry": ("pair80", P2 + [("cmc",), ("fcmovb", 1)] + OUT2),
}
ENTRY_READER = {"fcmovb_entry": ("CF", "fcmovb"), "fcmove_entry": ("ZF", "fcmove"), "adc_entry": ("CF", "adc"),
                "sbb_entry": ("CF", "sbb"), "adc_test_entry": ("CF", "adc"), "rcl_test_entry": ("CF", "rcl"),
                "cmc_entry": ("CF", "cmc")}
INTEGER_STEPS = {"cmp", "mov_eax", "adc_eax0", "sbb_eax0", "rcl_eax1", "test_eax", "cmc"}
STEPS = {**SEQUENCES, **ENTRY}

MOVE = r"x87_slot\[(\d)\] = x87_slot\[(\d)\];  // (fcmov\w*) "
CONTROLS = {
    # FCMOVB moves when CF is clear instead of set.
    "invert": (re.compile(r"if \(carry\) (x87_slot\[\d\] = x87_slot\[\d\];  // fcmovb )"), r"if (!carry) \1"),
    # FCMOVBE reads only CF.
    "beonly": (re.compile(r"if \(carry \|\| zero\) (x87_slot)"), r"if (carry) \1"),
    # FCMOVNBE moves when either flag is clear.
    "nbeor": (re.compile(r"if \(!carry && !zero\) (x87_slot)"), r"if (!carry || !zero) \1"),
    # FCMOVNE never moves.
    "neverne": (re.compile(r"if \(!zero\) (x87_slot\[\d\] = x87_slot\[\d\];  // fcmovne )"), r"if (false) \1"),
    # Every conditional move moves.
    "always": (re.compile(r"if \([^)]*\) (" + MOVE + ")"), r"\1"),
    # The copy quiets a signaling NaN.
    "quiet": (re.compile(MOVE),
              r"x87_slot[\1] = x87_is_nan(x87_slot[\2]) ? x87_quiet(x87_slot[\2]) : x87_slot[\2];  // \3 "),
    # CMC is dropped, so fcmovb_cmc moves on the CF of CMP.
    "cmcdrop": (re.compile(r"carry = !carry;"), ";"),
    # ADC and SBB ignore the incoming CF, so the ZF of fcmove_adc and fcmove_sbb no longer follows it.
    "nocarryin": (re.compile(r" [+-] word\(carry\)\)"), ")"),
}


# ---- MASM generation and decoding ------------------------------------------------------------------

def asm_line(step):
    op, *args = step
    if op == "cmp":
        return "    mov eax, dword ptr [rcx+48]\n    cmp eax, dword ptr [rcx+52]"
    if op == "mov_eax":
        return f"    mov eax, 0{args[0]:X}h"
    if op in ("adc_eax0", "sbb_eax0"):
        return f"    {op[:3]} eax, 0"
    if op == "rcl_eax1":
        return "    rcl eax, 1"
    if op == "test_eax":
        return "    test eax, eax"
    if op == "cmc":
        return "    cmc"
    if op in FCMOV:
        return f"    {op} st, st({args[0]})"
    if op == "fcomi":
        return f"    fcomi st, st({args[0]})"
    return integers.asm_line(step)


def expected_form(step):
    op, *args = step
    if op in FCMOV or op == "fcomi":
        return op, f"st0,st{args[0]}"
    return integers.expected_form(step)


def decoded_form(i):
    from iced_x86 import Mnemonic as M, Register as R

    if i.mnemonic in (M.FCMOVB, M.FCMOVE, M.FCMOVBE, M.FCMOVNB, M.FCMOVNE, M.FCMOVNBE, M.FCOMI):
        name = next(n for n, v in vars(M).items() if v == i.mnemonic).lower()
        return name, f"st{i.op0_register - R.ST0},st{i.op1_register - R.ST0}"
    return integers.decoded_form(i)


def write_asm(asm_path, def_path):
    lines = ["; coverage: source cpu_aot_x87_fcmov",
             "; Generated by tests/cpu/x87_fcmov.py asm; edit SEQUENCES there and regenerate.",
             "; Source-owned differential fixture for the ZF/CF forms of FCMOVcc in the x87 leaf-function",
             "; profile. Each export reads an input block at RCX, writes an output block at RDX and returns with",
             "; the x87 stack empty.", ".code", ""]
    for name, (_, steps) in STEPS.items():
        lines += [f"{name} PROC FRAME", "    .endprolog", *(asm_line(s) for s in steps), "    ret", f"{name} ENDP", ""]
    lines.append("END")
    Path(asm_path).write_text("\n".join(lines) + "\n", encoding="ascii")
    Path(def_path).write_text("EXPORTS\n" + "".join(f"    {name}\n" for name in STEPS), encoding="ascii")


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
            wanted = [expected_form(s) for s in steps if s[0] not in INTEGER_STEPS]
            if decoded != wanted:
                raise AssertionError(f"{name} assembled as {decoded}, expected {wanted}")
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

def reference(name, data, moves=True, flags=None):
    """The output block; with moves=False every conditional move is skipped, for the moved-case count.
    flags gives the caller's (ZF, CF) for the ENTRY exports."""
    slots, out = [], bytearray(b"\xcc" * OUTPUT)
    zero, carry = flags if flags is not None else (None, None)
    eax = None

    def read(kind, offset):
        return int.from_bytes(data[offset:offset + SIZE[kind]], "little")

    for op, *args in STEPS[name][1]:
        if op == "cmp":
            a, b = read("m32", 48), read("m32", 52)
            zero, carry = a == b, a < b
        elif op == "mov_eax":
            eax = args[0]
        elif op == "adc_eax0":
            total = eax + carry
            eax, carry = total & 0xFFFFFFFF, total > 0xFFFFFFFF
            zero = eax == 0
        elif op == "sbb_eax0":
            carry, eax = eax < carry, (eax - carry) & 0xFFFFFFFF
            zero = eax == 0
        elif op == "rcl_eax1":  # ZF is unchanged
            eax, carry = (eax << 1 | carry) & 0xFFFFFFFF, bool(eax >> 31)
        elif op == "test_eax":
            zero, carry = eax == 0, False
        elif op == "cmc":
            carry = not carry
        elif op == "fcomi":
            r = compare.compare(slots[-1], slots[-1 - args[0]])  # 0 less, 1 equal, 2 greater, 3 unordered
            zero, carry = r in (1, 3), r in (0, 3)
        elif op in FCMOV:
            if moves and CONDITION[op](zero, carry):
                slots[-1] = slots[-1 - args[0]]
        elif op == "fld":
            raw = read(*args)
            slots.append((raw & (2 ** 64 - 1), raw >> 64) if args[0] == "m80" else from_binary(args[0], raw))
        else:  # ("fstp", kind, offset)
            kind, offset = args
            v = slots.pop()
            encoded = v[0] | v[1] << 64 if kind == "m80" else to_binary(kind, v)
            out[offset:offset + SIZE[kind]] = encoded.to_bytes(SIZE[kind], "little")
    assert not slots
    return bytes(out)


# ---- Inputs ----------------------------------------------------------------------------------------

def flag_words(rng):
    """Dword pairs for the integer CMP: below, equal and above, signed and unsigned orders apart."""
    rows = [(1, 2), (2, 2), (3, 2), (0, 0xFFFFFFFF), (0xFFFFFFFF, 0), (0x80000000, 0x7FFFFFFF), (7, 7)]
    rows += [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(5)]
    return rows


def cases():
    rng = random.Random(101)
    specials = base.special_m80()
    singles = list(base.m80_singles()) + [(J | rng.getrandbits(63), rng.randint(1, 0x7FFE) | rng.choice((0, 0x8000)))
                                          for _ in range(100)]
    words = flag_words(rng)

    def ints(a, b):
        return a.to_bytes(4, "little") + b.to_bytes(4, "little")

    pairs = [(a, b) for a in specials for b in specials]
    pairint = [m80_bytes(a) + m80_bytes(b) + b"\0" * 16 + ints(*w) for a, b in pairs[::7] for w in words[:3]]
    pairint += [m80_bytes(rng.choice(singles)) + m80_bytes(rng.choice(singles)) + b"\0" * 16 + ints(*rng.choice(words))
                for _ in range(300)]
    tripleint = [m80_bytes(rng.choice(specials)) + m80_bytes(rng.choice(specials)) + m80_bytes(rng.choice(specials))
                 + ints(*w) for _ in range(150) for w in words[:3]]
    pair80 = [m80_bytes(a) + m80_bytes(b) for a, b in pairs] + [m80_bytes(rng.choice(singles)) + m80_bytes(rng.choice(singles))
                                                                 for _ in range(500)]
    f64 = base.f64_bits()
    # Eight m64 values fill the 64-byte block, so the CMP dwords at 48 and 52 are the halves of the seventh.
    m64x8int = [b"".join(rng.choice(f64).to_bytes(8, "little") for _ in range(8)) for _ in range(300)]
    blocks = {"pairint": pairint, "tripleint": tripleint, "pair80": pair80, "m64x8int": m64x8int}
    for name, (kind, _) in SEQUENCES.items():
        for block in blocks[kind]:
            yield name, bytes(block).ljust(INPUT, b"\0")


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
                if bad < 3:
                    print(f"{label} mismatch: {name}(input {data.hex()})\n  got      {got[:48].hex()}\n"
                          f"  expected {want[:48].hex()}")
                bad += 1
        if bad:
            raise AssertionError(f"{label}: {bad}/{len(expected)} mismatches")
    moved = sum(1 for name, data, want in expected if want != reference(name, data, moves=False))
    print(f"{len(expected)} cases over {len(SEQUENCES)} exports (output block and guards) matched the reference "
          "in native and translated DLLs; each export returned with control 0x027f and an empty stack")
    print(f"cases in which a conditional move changed the output block: {moved} of {len(expected)}")
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
    check_entry_flags(harness_path, native_path)
    for path in control_paths:
        control = Path(path).stem.rsplit("_", 1)[-1]
        run = base.Runner(harness_path, path)
        bad = sum(1 for name, data, want in expected if run(name, data)[0] != want)
        print(f"control {control}: {bad}/{len(expected)} mismatches")
        if not bad:
            raise AssertionError(f"control {control} matched every case")
    check_rejections()


FLAGS = {(False, False): 0x00, (False, True): 0x01, (True, False): 0x40, (True, True): 0x41}  # AH for SAHF


def check_entry_flags(harness_path, native_path):
    """The ENTRY exports natively under each caller ZF and CF, through x87_call_flags, and their rejection."""
    import ctypes
    import pefile
    from cpu_leaf_aot import export_rva
    from cpu_ranges import function_ranges
    from ffx_version_query import lower, region

    run = base.Runner(harness_path, native_path)
    call = run.harness.x87_call_flags
    call.argtypes, call.restype = [ctypes.c_void_p] * 3 + [ctypes.c_uint64], ctypes.c_uint64
    rng = random.Random(113)
    singles = list(base.m80_singles())
    blocks = []
    while len(blocks) < 40:
        a, b = rng.choice(singles), rng.choice(singles)
        if a != b:
            blocks.append((m80_bytes(a) + m80_bytes(b)).ljust(INPUT, b"\0"))
    runs = 0
    for name in ENTRY:
        function = ctypes.cast(getattr(run.lib, name), ctypes.c_void_p).value
        for data in blocks:
            outputs = set()
            for flags, ah in FLAGS.items():
                guard, source, target = run._buffers(data)
                state = call(function, ctypes.addressof(source) + base.GUARD, ctypes.addressof(target) + base.GUARD, ah)
                got = run._output(name, data, guard, source, target)
                if not base.entry_state_ok(state) or got != reference(name, data, flags=flags):
                    raise AssertionError(f"native {name} with caller ZF, CF = {flags} gave {got[:32].hex()}")
                outputs.add(got)
                runs += 1
            if len(outputs) != 2:
                raise AssertionError(f"native {name} did not depend on the caller's flags")
    with pefile.PE(str(native_path), fast_load=True) as pe:
        for name, (flag, reader) in ENTRY_READER.items():
            (bounds,) = function_ranges(pe, export_rva(pe, name))
            try:
                lower(region(pe, *bounds), ["rcx = a; rdx = b;"], {}, {}, {}, x87=True)
            except ValueError as exc:
                if not str(exc).startswith(reader) or f"reads {flag}, which no instruction defines" not in str(exc):
                    raise
            else:
                raise AssertionError(f"translation accepted {name}, which reads the caller's {flag}")
    print(f"native {', '.join(ENTRY)} followed the caller's CF or ZF (set by SAHF before the call) in all {runs} "
          f"runs over {len(blocks)} value pairs and the four flag pairs; translation rejects each at its first "
          "reader of the flag, which no instruction defines on every path from the entry: "
          + "; ".join(f"{name} at {reader} ({flag})" for name, (flag, reader) in ENTRY_READER.items()))


def check_rejections():
    from iced_x86 import Decoder
    from ffx_version_query import lower

    def attempt(hex_bytes, calls=None):
        body = list(Decoder(64, bytes.fromhex(hex_bytes), ip=0x1000))
        try:
            lower(body, [], {}, calls or {}, {}, x87=True)
        except ValueError as exc:
            return str(exc)
        return None

    fld, fstp, cmp = "db 29", "db 3a", "8b 41 30 3b 41 34"  # fld/fstp tbyte ptr [rcx]/[rdx]; mov/cmp eax
    two, out = f"{fld} {fld}", f"{fstp} {fstp} c3"
    undefined = "which no instruction defines on every path"
    parity = "reads PF, which the integer lowering models only after"
    rejected = {
        # CMP writes PF last, and the integer lowering does not model its PF.
        "fcmovu st, st(1) after cmp": (attempt(f"{two} {cmp} da d9 {out}"), parity),
        "fcmovnu st, st(1) after cmp": (attempt(f"{two} {cmp} db d9 {out}"), parity),
        "fcmovb st, st(1) with one value": (attempt(f"{fld} {cmp} da c1 {fstp} c3"), "x87 stack underflow"),
        "fcmove st, st(2) with two values": (attempt(f"{two} {cmp} da ca {out}"), "x87 stack underflow"),
        "fcmovnbe on an empty stack": (attempt(f"{cmp} db d1 c3"), "x87 stack underflow"),
        # Flags that no instruction writes on some path from the entry.
        "fcmovb before any flag writer": (attempt(f"{two} da c1 {out}"), "reads CF, " + undefined),
        "fcmove after a join with one undefined predecessor": (attempt(f"{two} e3 06 {cmp} da c9 {out}"),
                                                               "reads ZF, " + undefined),
        "fcmovbe after stc, which leaves ZF undefined": (attempt(f"{two} f9 da d1 {out}"), "reads ZF, " + undefined),
        "fcmovnb after a call": (attempt(f"{cmp} e8 00 00 00 00 {two} db c1 {out}", calls={0x1006: ";"}),
                                 "reads CF, " + undefined),
        "fcmove after imul, which leaves ZF undefined": (attempt(f"{two} 0f af c1 da c9 {out}"),
                                                         "reads ZF, " + undefined),
        "fcmovb after shl eax, cl with no earlier writer": (attempt(f"{two} d3 e0 da c1 {out}"),
                                                            "reads CF, " + undefined),
        "fcmovb after shl ax, 16": (attempt(f"{two} 66 c1 e0 10 da c1 {out}"), "reads CF, " + undefined),
        # A reader of CF that no instruction defines, in a function with a move whose own flags are defined.
        "cmc before a cmp and fcmovb": (attempt(f"{two} f5 {cmp} da c1 {out}"), "reads CF, " + undefined),
        # The rule covers every status flag. The integer lowering would also reject SETO, but the flag rule
        # comes first.
        "seto before a cmp and fcmovb": (attempt(f"{two} 0f 90 c0 {cmp} da c1 {out}"), "reads OF, " + undefined),
    }
    for case, (message, needle) in rejected.items():
        if message is None or needle not in message:
            raise AssertionError(f"{case}: expected a rejection containing {needle!r}, got {message!r}")
    print(f"rejected {len(rejected)} sequences outside the profile: " + "; ".join(rejected))
    accepted = {
        "fcmovb after clc": attempt(f"{two} f8 da c1 {out}"),
        "fcmove after a join where both paths write ZF": attempt(f"{two} {cmp} e3 06 {cmp} da c9 {out}"),
        "fcmove after xor eax, eax": attempt(f"{two} 31 c0 da c9 {out}"),
        "fcmovnbe after fcomi": attempt(f"{two} db f1 db d1 {out}"),
        # A reader of CF after an explicit producer: CLC before ADC, STC before SBB, CMP before CMC, and CLC
        # before RCL and TEST.
        "fcmove after clc and adc": attempt(f"{two} b8 ff ff ff ff f8 83 d0 00 da c9 {out}"),
        "fcmove after stc and sbb": attempt(f"{two} 31 c0 f9 83 d8 00 da c9 {out}"),
        "fcmovb after cmp and cmc": attempt(f"{two} {cmp} f5 da c1 {out}"),
        "fcmovne after clc, rcl and test": attempt(f"{two} 31 c0 f8 d1 d0 85 c0 db c9 {out}"),
    }
    for case, message in accepted.items():
        if message is not None:
            raise AssertionError(f"{case}: expected translation, got {message!r}")
    print(f"translated {len(accepted)} sequences whose flags are written on every path: " + "; ".join(accepted))


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
