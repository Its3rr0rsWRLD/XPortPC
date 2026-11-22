"""Draw family `vop3_e64_table`: pixel_aot_check.py draw --family vop3_e64_table.

Table-driven draws of the VOP3 (e64) spellings of VOP1/VOP2 binary16 ops whose e32 spelling is already drawn
(f16): v_floor_f16, v_trunc_f16, v_min_f16 and v_subrev_f16. The e64 encoding adds source modifiers (neg, abs and
neg of abs, on float sources only) and clamp; the output modifiers (mul, div) are refused, as for the other binary16
forms (valu_f16). Each op gets two programs: one that rotates the four source-modifier kinds over four channels, and
one that puts clamp on every channel, alone and with a modifier. The sources are constant words 3 to 6 (s44 to s47)
with junk in the high halves, so each reference decodes only the low 16 bits.

The reference is independent of the lowering: the low halves are decoded by Python (struct "e"), the modifiers are
applied to the decoded value, the operation is exact in binary16 for these inputs (every value is a multiple of 0.25
below 2^10, so no rounding occurs), and a clamp is min(1, max(0, x)). Each program is drawn with three constant sets,
each against wrong references for every plausible bug (neg dropped, abs dropped, clamp dropped, operands swapped for
subrev, max for min, floor for trunc and the reverse); each bug must change a channel on some set (asserted without a
GPU) and must be reported as a pixel_mismatch. The inputs keep |x| >= 1, so no result is a signed zero.
"""
import math
import re
import struct
import subprocess

from .common import half_value, must_reject, translate, with_constants
from .f16 import f16_values_readback, f16_words


def half_bits(x):
    return struct.unpack("<H", struct.pack("<e", x))[0]


SETS = [f16_words(*(half_bits(x) for x in values)) for values in (
    (-2.5, 1.5, -1.75, 3.5), (2.5, -1.5, 1.75, -3.5), (1.25, -2.25, 1.5, -1.25))]
SOURCE = re.compile(r"(-?)(\|?)s(\d+)\|?")


def source_value(token, words, bug):
    negate, absolute, number = SOURCE.fullmatch(token).groups()
    x = half_value(words[int(number) - 44])
    if absolute and bug != "no_abs":
        x = abs(x)
    return -x if negate and bug != "no_neg" else x


def floor_(x):
    return float(math.floor(x))


def trunc_(x):
    return float(math.trunc(x))


# op -> (number of sources, reference, {bug: wrong reference})
OPS = {
    "floor": (1, lambda a: floor_(a), {"trunc_for_floor": lambda a: trunc_(a)}),
    "trunc": (1, lambda a: trunc_(a), {"floor_for_trunc": lambda a: floor_(a)}),
    "min": (2, lambda a, b: min(a, b), {"max_for_min": lambda a, b: max(a, b)}),
    "subrev": (2, lambda a, b: b - a, {"swapped": lambda a, b: a - b}),
}
# The channels of each program: source operands and the clamp flag, in the order of v12 to v15.
UNARY_PLAIN = (("s44", ""), ("-s44", ""), ("|s45|", ""), ("-|s45|", ""))
UNARY_CLAMP = (("s44", " clamp"), ("-s44", " clamp"), ("|s45|", " clamp"), ("-|s45|", " clamp"))
BINARY_PLAIN = (("s44, s45", ""), ("-s44, |s45|", ""), ("|s44|, -s45", ""), ("-|s44|, -|s45|", ""))
BINARY_CLAMP = (("s44, s45", " clamp"), ("-s44, s46", " clamp"), ("|s44|, -s46", " clamp"), ("-|s47|, s45", " clamp"))


def channel_value(op, operands, clamp, words, bug):
    _, reference, wrongs = OPS[op]
    if bug in wrongs:
        reference = wrongs[bug]
    value = reference(*(source_value(t, words, bug) for t in operands.split(", ")))
    return min(1.0, max(0.0, value)) if clamp and bug != "no_clamp" else value


def programs():
    """(name, instructions, channels) for every op: channels are (op, operands, clamp)."""
    for op, (arity, *_rest) in OPS.items():
        for kind, rows in (("mod", UNARY_PLAIN if arity == 1 else BINARY_PLAIN),
                           ("clamp", UNARY_CLAMP if arity == 1 else BINARY_CLAMP)):
            channels = [(op, operands, clamp) for operands, clamp in rows]
            body = [f"v_{op}_f16_e64 v{12 + n}, {operands}{clamp}" for n, (_, operands, clamp) in enumerate(channels)]
            yield f"{op}_{kind}", [*body, *f16_values_readback()], channels


def model(channels, words, bug=None):
    return [channel_value(op, operands, bool(clamp), words, bug) for op, operands, clamp in channels]


BUGS = ("no_neg", "no_abs", "no_clamp", "trunc_for_floor", "floor_for_trunc", "max_for_min", "swapped")


def applicable(channels, bug):
    text = " ".join(f"{operands}{clamp}" for _, operands, clamp in channels)
    ops = {op for op, *_ in channels}
    return {"no_neg": "-" in text, "no_abs": "|" in text, "no_clamp": "clamp" in text,
            "trunc_for_floor": "floor" in ops and "clamp" not in text, "floor_for_trunc": "trunc" in ops and "clamp" not in text,
            "max_for_min": "min" in ops, "swapped": "subrev" in ops}[bug]


def check_models():
    """Hand-computed channels for one set of each program, then every applicable bug exposed by some set."""
    expected = {  # set 0 = (-2.5, 1.5, -1.75, 3.5)
        "floor_mod": [-3.0, 2.0, 1.0, -2.0], "floor_clamp": [0.0, 1.0, 1.0, 0.0],
        "trunc_mod": [-2.0, 2.0, 1.0, -1.0], "trunc_clamp": [0.0, 1.0, 1.0, 0.0],
        "min_mod": [-2.5, 1.5, -1.5, -2.5], "min_clamp": [0.0, 0.0, 1.0, 0.0],
        "subrev_mod": [4.0, -1.0, -4.0, 1.0],  # S1 - S0 per channel
        "subrev_clamp": [1.0, 0.0, 0.0, 1.0],
    }
    for name, _, channels in programs():
        assert model(channels, SETS[0]) == expected[name], (name, model(channels, SETS[0]))
        for bug in BUGS:
            if applicable(channels, bug):
                assert any(model(channels, words, bug) != model(channels, words) for words in SETS), (name, bug)


def check_draws(directory, compiler, renderer, backend):
    check_models()
    case = directory / "vop3_e64_table.case"
    for name, body, channels in programs():
        source = directory / f"vop3_e64_table_{name}.hlsl"
        shader = directory / f"vop3_e64_table_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for words in SETS:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = model(channels, words)
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for bug in BUGS:
                if not applicable(channels, bug):
                    continue
                wrong = model(channels, words, bug)
                if wrong == expected:
                    continue
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"Lowering bug {bug} escaped detection in {name} for words {words}")


def controls(directory):
    # The e64 spelling lowers through the e32 form: the same expression, with neg and abs acting on bit 15 of the
    # binary16 source before widening and clamp saturating before the narrowing.
    for op in OPS:
        two = OPS[op][0] == 2
        e32 = translate(with_constants([f"v_{op}_f16_e32 v12, s44, v13" if two else f"v_{op}_f16_e32 v12, s44"]))
        e64 = translate(with_constants([f"v_{op}_f16_e64 v12, s44, v13" if two else f"v_{op}_f16_e64 v12, s44"]))
        assert e32 == e64, op
        modified = translate(with_constants([f"v_{op}_f16_e64 v12, -|s44|, v13 clamp" if two else f"v_{op}_f16_e64 v12, -|s44| clamp"]))
        assert "((params[0].w & 0xffffu) & 0x7fffu) ^ 0x8000u" in modified.replace("(((", "((("), (op, modified)
        assert "narrow16(saturate(" in modified, op
        # Output modifiers, op_sel and a wrong operand count are refused; clamp exists only in the e64 encoding.
        operands = "s44, s45" if two else "s44"
        for suffix in (" mul:2", " mul:4", " div:2", " clamp mul:2", " op_sel:[0,0,1]"):
            must_reject(translate, with_constants([f"v_{op}_f16_e64 v12, {operands}{suffix}"]))
        must_reject(translate, with_constants([f"v_{op}_f16_e32 v12, {operands} clamp"]))
        must_reject(translate, with_constants([f"v_{op}_f16_e64 v12, {operands}, s46"]))
        must_reject(translate, with_constants([f"v_{op}_f16_e64 v12, {'s44' if two else 's44, s45'}"]))
        for register in ("v0", "v1", "v8", "v9"):  # interpolation state is not a numeric old value
            must_reject(translate, with_constants([f"v_{op}_f16_e64 {register}, {operands}"]))
    # A source modifier on the integer operand or a double negation is not an operand of the grammar.
    for operation in ("v_min_f16_e64 v12, --s44, s45", "v_floor_f16_e64 v12, |-s44|", "v_trunc_f16_e64 v12, neg(s44)",
                      "v_min_f16_e64 v12, s44, s45 clamp clamp"):
        must_reject(translate, with_constants([operation]))
    # The VOP3 encodings of the interpolation ops carry their own operand form and are not an alias of the e32 forms.
    for operation in ("v_interp_p1_f32_e64 v8, v0, attr0.x", "v_interp_p2_f32_e64 v8, v1, attr0.x"):
        must_reject(translate, [operation])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for _, body, _ in programs()]


draw = check_draws
