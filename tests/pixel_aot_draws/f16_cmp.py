"""Draw family `f16_cmp`: pixel_aot_check.py draw --family f16_cmp."""
import math
import struct
import subprocess

from .common import M32, DrawBatch, f16_const, half_value, must_reject, translate, with_constants
from .predicate import PREDICATES


# Binary16 comparisons and class tests (v_cmp_<p>_f16, v_cmp_class_f16). Each draw exports the four lane-mask results
# through v_cndmask_b32 (0 or 1.0), as the binary32 predicate draws do; words reach vector registers through
# v_or_b32, so no pattern passes through a float register. Inputs are binary16 words under junk high halves.
# The reference is independent: the binary16 values are decoded by struct "e" and compared as Python floats, whose
# relations (less, equal, greater, unordered) are looked up in the gfx10 truth-table number of each predicate. The class
# reference decodes the encoding with float functions. Each program lists the plausible lowering bugs to model; each
# must change a channel on some set and is drawn as a wrong reference that must report a mismatch.
def relation_ref(a, b):
    return 3 if math.isnan(a) or math.isnan(b) else 0 if a < b else 1 if a == b else 2


def f32_word(word):
    return struct.unpack("<f", struct.pack("<I", word & M32))[0]


def cmp_in(word, bug):
    """A source word as the lowering must read it: the low half as binary16. high_half reads the whole word as
    binary32; flush reads binary16 subnormals as zero."""
    if bug == "high_half":
        return f32_word(word)
    x = half_value(word)
    if bug == "flush" and x != 0 and abs(x) < 2.0 ** -14:
        return math.copysign(0.0, x)
    return x


def cmp_model(first, x_mod, y_mod):
    def model(words, bug):
        x, y = cmp_in(words[0], bug), cmp_in(words[1], bug)
        if bug != "no_mod":
            x, y = x_mod(x), y_mod(y)
        out = []
        for op in range(first, first + 4):
            relation = relation_ref(x, y)
            # nan_ordered: an unordered operand is treated as ordered, so no predicate fires on it.
            out.append(0.0 if bug == "nan_ordered" and relation == 3 else float((op >> relation) & 1))
        return out
    return model


identity = lambda value: value
negate = lambda value: -value


def cmp_words(x, y, z=0, w=0, hx=0xdead, hy=0xbeef):
    return ((hx << 16) | x, (hy << 16) | y, z, w)


# (S0, S1) low halves, kept to what the three-minute hardware test budget allows. Each set stands for a class of cases:
# ordinary values, -0 against +0, a quiet NaN first, a signaling NaN second, infinities of opposite sign, a subnormal
# against zero (equal if subnormals are flushed), equal binary16 values under a NaN high half (a whole-register read
# is unordered) and a larger value under a large high half (a whole-register read reverses the relation).
F16_CMP_SETS = (
    cmp_words(0xbc00, 0x3c00), cmp_words(0x8000, 0x0000), cmp_words(0x7e00, 0x3c00), cmp_words(0x3c00, 0x7d00),
    cmp_words(0x7c00, 0xfc00), cmp_words(0x0001, 0x0000), cmp_words(0x3c00, 0x3c00, hx=0x7fc0, hy=0x0000),
    cmp_words(0x4000, 0x3c00, hx=0x0000, hy=0x7f00),
)
F16_CMP_BUGS = ("nan_ordered", "high_half", "flush")


def cmp_group(first, spelling):
    body = ["v_or_b32_e64 v18, s45, 0", "v_mov_b32_e32 v19, 1.0"]
    for channel, op in enumerate(PREDICATES[first:first + 4]):
        if spelling == "e32":
            body.extend([f"v_cmp_{op}_f16_e32 vcc_lo, s44, v18", f"v_cndmask_b32_e32 v{12 + channel}, 0, v19, vcc_lo"])
        else:
            body.extend([f"v_cmp_{op}_f16_e64 s0, -s44, -v18", f"v_cndmask_b32_e64 v{12 + channel}, 0, v19, s0"])
    return body


F16_CMP_MODS_BODY = [
    "v_or_b32_e64 v18, s45, 0", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_lt_f16_e64 s0, |s44|, v18", "v_cndmask_b32_e64 v12, 0, v19, s0",
    "v_cmp_eq_f16_e64 s0, -s44, |v18|", "v_cndmask_b32_e64 v13, 0, v19, s0",
    "v_cmp_nge_f16_e64 s0, |s44|, -v18", "v_cndmask_b32_e64 v14, 0, v19, s0",
    "v_cmp_u_f16_e64 s0, -|s44|, v18", "v_cndmask_b32_e64 v15, 0, v19, s0",
]


def f16_cmp_mods_model(words, bug):
    x, y = cmp_in(words[0], bug), cmp_in(words[1], bug)
    mods = bug != "no_mod"
    relations = [relation_ref(abs(x) if mods else x, y), relation_ref(-x if mods else x, abs(y) if mods else y),
                 relation_ref(abs(x) if mods else x, -y if mods else y), relation_ref(-abs(x) if mods else x, y)]
    truth = [PREDICATES.index(op) for op in ("lt", "eq", "nge", "u")]
    out = [float((truth[c] >> relations[c]) & 1) for c in range(4)]
    return [0.0 if bug == "nan_ordered" and relations[c] == 3 else out[c] for c in range(4)]


# Inline binary16 constants as the first source: 0.5, -0.5 and 1.0 are the binary16 values 0x3800, 0xb800 and 0x3c00;
# read as the low half of their binary32 encodings they would all be +0. Channels: 0.5 < Y, 0.5 == Z, -0.5 > Y, not(1.0 < Y).
F16_CMP_CONST_BODY = [
    "v_or_b32_e64 v18, s45, 0", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_lt_f16_e32 vcc_lo, 0.5, v18", "v_cndmask_b32_e32 v12, 0, v19, vcc_lo",
    "v_cmp_eq_f16_e64 s0, 0.5, s46", "v_cndmask_b32_e64 v13, 0, v19, s0",
    "v_cmp_gt_f16_e64 s0, -0.5, v18", "v_cndmask_b32_e64 v14, 0, v19, s0",
    "v_cmp_nlt_f16_e32 vcc_lo, 1.0, v18", "v_cndmask_b32_e32 v15, 0, v19, vcc_lo",
]


def f16_cmp_const_model(words, bug):
    const = lambda token: f16_const(token, "const_bits" if bug == "const_bits" else None)
    y, z = cmp_in(words[1], bug), cmp_in(words[2], bug)
    # nan_ordered: not(1.0 < Y) is evaluated as 1.0 >= Y, which is false for a NaN.
    nlt = const("1.0") >= y if bug == "nan_ordered" else not const("1.0") < y
    return [float(const("0.5") < y), float(const("0.5") == z), float(const("-0.5") > y), float(nlt)]


F16_CMP_CONST_SETS = (
    cmp_words(0, 0x3800, 0x3800), cmp_words(0, 0x0000, 0x0000), cmp_words(0, 0x3c00, 0x3800),
    cmp_words(0, 0xb800, 0x0000), cmp_words(0, 0x7e00, 0x3800), cmp_words(0, 0xbc00, 0xb800),
)

F16_CMP_PROGRAMS = tuple(
    (f"{spelling}_{first // 4}", cmp_group(first, spelling),
     cmp_model(first, identity if spelling == "e32" else negate, identity if spelling == "e32" else negate),
     F16_CMP_SETS, tuple(bug for bug in F16_CMP_BUGS if bug != "nan_ordered" or first >= 8)  # f..o never fire on NaN
     + (() if spelling == "e32" else ("no_mod",)))
    for spelling in ("e32", "e64") for first in range(0, 16, 4)
) + (
    ("mods", F16_CMP_MODS_BODY, f16_cmp_mods_model, F16_CMP_SETS, F16_CMP_BUGS + ("no_mod",)),
    ("const", F16_CMP_CONST_BODY, f16_cmp_const_model, F16_CMP_CONST_SETS, ("const_bits", "high_half", "nan_ordered")),
)
# Hand-computed channels of the bug-free models: program, set index, channels. e32_0 is f, lt, eq, le; e32_1 is gt,
# lg, ge, o; e32_2 is u, nge, nlg, ngt; e32_3 is nle, neq, nlt, tru. The e64 programs compare -S0 with -S1.
F16_CMP_EXPECTED = (
    ("e32_0", 0, [0, 1, 0, 1]),    # -1 against 1
    ("e32_0", 1, [0, 0, 1, 1]),    # -0 against +0 is equal
    ("e32_0", 2, [0, 0, 0, 0]),    # quiet NaN: no ordered predicate holds
    ("e32_1", 2, [0, 0, 0, 0]),
    ("e32_2", 3, [1, 1, 1, 1]),    # a signaling NaN is unordered
    ("e32_3", 3, [1, 1, 1, 1]),
    ("e32_3", 6, [0, 0, 1, 1]),    # equal halves under a NaN high half are equal
    ("e64_1", 0, [1, 1, 1, 1]),    # -(-1) against -(1): greater
    ("e64_3", 6, [0, 0, 1, 1]),
    ("const", 0, [0, 1, 0, 1]),    # 0.5 < 0.5 false, 0.5 == 0.5 true, -0.5 > 0.5 false, not (1.0 < 0.5) true
    ("const", 1, [0, 0, 0, 1]),    # Y = Z = 0
)


# v_cmp_class_f16: the class of the binary16 in the low half of S0 against a 32-bit mask (bit order as class32).
# Channels: S0 against the SGPR mask S1 (e64), against the vector mask S2 (e32), -|S0| against the literal 0x8c
# (-inf, -normal, +subnormal; e64), and the inline constant 0.5 (+normal) against the SGPR mask S3 (e64).
F16_CLASS_BODY = [
    "v_or_b32_e64 v18, s46, 0", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_class_f16_e64 s0, s44, s45", "v_cndmask_b32_e64 v12, 0, v19, s0",
    "v_cmp_class_f16_e32 vcc_lo, s44, v18", "v_cndmask_b32_e32 v13, 0, v19, vcc_lo",
    "v_cmp_class_f16_e64 s0, -|s44|, 0x8c", "v_cndmask_b32_e64 v14, 0, v19, s0",
    "v_cmp_class_f16_e64 s0, 0.5, s47", "v_cndmask_b32_e64 v15, 0, v19, s0",
]


def class16_ref(word):
    low = word & 0xffff
    x = half_value(low)
    sign = low >> 15
    if math.isnan(x):
        return 0x2 if low & 0x200 else 0x1
    if math.isinf(x):
        return 0x4 if sign else 0x200
    if x == 0:
        return 0x20 if sign else 0x40
    if abs(x) < 2.0 ** -14:
        return 0x10 if sign else 0x80
    return 0x8 if sign else 0x100


def class32_ref(word):
    sign, exponent, mantissa = word >> 31, (word >> 23) & 0xff, word & 0x7fffff
    if exponent == 0xff and mantissa:
        return 0x2 if mantissa & 0x400000 else 0x1
    if exponent == 0xff:
        return 0x4 if sign else 0x200
    if exponent == 0:
        return (0x20 if sign else 0x40) if mantissa == 0 else (0x10 if sign else 0x80)
    return 0x8 if sign else 0x100


def f16_class_model(words, bug):
    x, m0, m1, m3 = words

    def classify(word):
        if bug == "high_half":
            return class32_ref(word)
        c = class16_ref(word)
        if bug == "swap_nan" and c in (1, 2):
            return 3 - c  # signaling and quiet NaN exchanged
        if bug == "sub_zero" and c in (0x10, 0x80):
            return c << 1 if c == 0x10 else c >> 1  # a subnormal classed as the zero of its sign
        return c

    if bug == "no_mod":
        channel2 = classify(x)
    elif bug == "high_half":
        channel2 = classify(0x80000000 | (x & 0x7fffffff))
    else:
        channel2 = classify(0x8000 | (x & 0x7fff))
    half = 0 if bug == "const_bits" else 0x3800  # the low half of the binary32 encoding of 0.5 is 0
    return [float(classify(x) & m0 != 0), float(classify(x) & m1 != 0), float(channel2 & 0x8c != 0),
            float(class16_ref(half) & m3 != 0)]


# One input per class and per edge of the encoding, each under a different high half (a binary32 NaN, an infinity,
# zero, all ones), with the mask of its own class in S1 and the complement in S2, and the other way round.
F16_CLASS_WORDS = ((0x7d00, 0x7f80), (0xfc01, 0xdead), (0x7e00, 0x0000), (0xfe00, 0xffff), (0xfc00, 0x7fc0),
                   (0x7c00, 0x0000), (0xbc00, 0x7f80), (0x3c00, 0xffff), (0x8001, 0x0000), (0x0001, 0x7fc0),
                   (0x83ff, 0xbeef), (0x03ff, 0x0000), (0x8000, 0x7f80), (0x0000, 0xffff), (0x0400, 0xff80),
                   (0x7bff, 0x1234), (0xfbff, 0x0000), (0x8400, 0x7fc0))
F16_CLASS_SETS = tuple(
    ((high << 16) | low, *masks, 0x100 if index % 2 == 0 else 0x40)
    for index, (low, high) in enumerate(F16_CLASS_WORDS)
    for masks in (((class16_ref(low), 0x3ff ^ class16_ref(low)) if index % 2 == 0 else (0x3ff ^ class16_ref(low), class16_ref(low))),)
)
F16_CLASS_BUGS = ("swap_nan", "sub_zero", "high_half", "no_mod", "const_bits")
# Hand-computed channels: (S0, S1, S2, S3) and the four results.
F16_CLASS_EXPECTED = (
    ((0x7f807d00, 0x1, 0x3fe, 0x100), [1, 0, 0, 1]),   # a signaling NaN is class bit 0; -|x| is no listed class; 0.5 is +normal
    ((0x7f807d00, 0x2, 0x3fd, 0x40), [0, 1, 0, 0]),    # not bit 1; 0.5 is not +0
    ((0x00000001, 0x80, 0x37f, 0x100), [1, 0, 0, 1]),  # +subnormal is class bit 7; -|x| is -subnormal, outside 0x8c
    ((0xffff8000, 0x20, 0x3df, 0x40), [1, 0, 0, 0]),   # -0 is class bit 5, not +0
    ((0x7bfffc00, 0x4, 0x3fb, 0x100), [1, 0, 1, 1]),  # -inf is bit 2 and in 0x8c after -|x|
)


F16_CMP_PROGRAM_BY_NAME = {name: (model, sets) for name, _, model, sets, _ in F16_CMP_PROGRAMS}
F16_CLASS_PROGRAMS = (("class", F16_CLASS_BODY, f16_class_model, F16_CLASS_SETS, F16_CLASS_BUGS),)


def check_f16_cmp_models():
    """The models against hand-computed channels, and each listed bug against the sets that must expose it."""
    for name, index, expected in F16_CMP_EXPECTED:
        model, sets = F16_CMP_PROGRAM_BY_NAME[name]
        assert model(sets[index], None) == [float(v) for v in expected], (name, index, model(sets[index], None))
    for words, expected in F16_CLASS_EXPECTED:
        assert f16_class_model(words, None) == [float(v) for v in expected], words
    for name, _, model, sets, bugs in (*F16_CMP_PROGRAMS, *F16_CLASS_PROGRAMS):
        for bug in bugs:
            assert any(model(words, bug) != model(words, None) for words in sets), (name, bug)



def check_f16_cmp_draws(directory, compiler, renderer, backend):
    check_f16_cmp_models()
    for name, body, model, sets, bugs in (*F16_CMP_PROGRAMS, *F16_CLASS_PROGRAMS):
        source = directory / f"f16cmp_{name}.hlsl"
        shader = directory / f"f16cmp_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        batch = DrawBatch(directory, renderer, backend, shader, "f16cmp")
        drawn = dict.fromkeys(bugs, 0)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = model(words, None)
            batch.add(constants + struct.pack("<4f", *expected) * 64, "pass",
                      f"Binary16 comparison draw {name} on {backend}, words {[hex(w) for w in words]}")
            for bug in bugs:
                wrong = model(words, bug)
                # One exposing set per bug establishes that the renderer notices it.
                if wrong == expected or drawn[bug] == 1:
                    continue
                drawn[bug] += 1
                batch.add(constants + struct.pack("<4f", *wrong) * 64, "mismatch",
                          f"A binary16 comparison bug ({bug}) escaped detection in {name} for words {words}")
        batch.flush()
        assert all(count > 0 for count in drawn.values()), (name, drawn)


def check_f16_cmp_controls():
    # Both sources are widened from their low halves and compared in binary32 (exact for binary16); the class is
    # read from the 16-bit encoding after the modifiers, and the mask stays a 32-bit integer.
    body = translate(with_constants(["v_mov_b32_e32 v18, s45", "v_cmp_nge_f16_e32 vcc_lo, s44, v18",
                                     "v_cmp_lt_f16_e64 s0, -0.5, |v18|"])).split("float4 main", 1)[1]
    for expected in ("precise float cmpa", "widen16((params[0].w & 0xffffu))", "widen16(0xb800u)", "isnan(cmpa"):
        assert expected in body, expected
    body = translate(with_constants(["v_mov_b32_e32 v18, s46", "v_cmp_class_f16_e32 vcc_lo, s44, v18",
                                     "v_cmp_class_f16_e64 s0, -|s44|, 0x8c", "v_cmp_class_f16_e64 s1, 0.5, s47"])).split("float4 main", 1)[1]
    for expected in ("class16((((params[0].w & 0xffffu) & 0x7fffu) ^ 0x8000u)) & 140u) != 0u",
                     "class16(0x3800u) & params[", "class16((params[0].w & 0xffffu)) & movw"):
        assert expected in body, expected
    assert translate(with_constants(["v_cmp_class_f16 vcc_lo, s44, 3"])) == translate(with_constants(["v_cmp_class_f16_e32 vcc_lo, s44, 3"]))
    for operation in ("v_cmp_lt_f16_e64 s0, s44, v13 op_sel:[1,0]", "v_cmp_lt_f16_e64 s0, s44, v13 op_sel:[0,1]",
                      "v_cmp_class_f16_e64 s0, s44, 3 op_sel:[1,0]",
                      "v_cmp_lt_f16_sdwa vcc_lo, 1.5, v13 src0_sel:WORD_1 src1_sel:WORD_0",
                      "v_cmp_class_f16_sdwa vcc_lo, s44, 1.0 src0_sel:WORD_0 src1_sel:DWORD",
                      "v_cmp_lt_f16_dpp vcc_lo, v13, v14 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
                      "v_cmp_class_f16_e64 s0, s44, 1.0", "v_cmp_class_f16_e64 s0, s44, 0.5",
                      "v_cmp_class_f16_e64 s0, s44, -s45", "v_cmp_class_f16_e64 s0, s44, |s45|",
                      "v_cmp_class_f16_e64 s0, s44, 0x123456789",
                      "v_cmp_lt_f16_e32 vcc_lo, 1.5, v13", "v_cmp_lt_f16_e32 vcc_lo, 65, v13",
                      "v_cmp_lt_f16_e32 vcc_lo, 0x12345, v13", "v_cmp_lt_f16_e64 s0, --s44, v13",
                      "v_cmp_lt_f16_e32 vcc_lo, s44", "v_cmp_class_f16_e64 s0, s44", "v_cmp_lt_f16_e32 vcc_lo, s44, v13, v14",
                      "v_cmp_lt_f16_e64 s0, s44, v13 clamp", "v_cmp_lt_f16_e64 s0, s44, v13 mul:2",
                      "v_cmp_lt_f16_e32 vcc_lo, s44, v30", "v_cmp_class_f16_e32 vcc_lo, s44, v30",
                      "v_cmp_class_f16_e32 vcc_lo, v30, s44"):
        must_reject(translate, with_constants([operation]))
    # (v_cmpx_lt_f16_e32 / v_cmpx_class_f16_e32 before the export are kills since CF-2d, family cf2_discard.)
    # A source cannot be read before the sample or the scalar load it depends on arrives.
    program = with_constants(["v_cmp_lt_f16_e32 vcc_lo, s44, v13"])
    translate(program)
    wait = program.index("s_waitcnt vmcnt(0)")
    for operation in ("v_cmp_lt_f16_e32 vcc_lo, s44, v13", "v_cmp_lt_f16_e32 vcc_lo, 0.5, v12",
                      "v_cmp_class_f16_e64 s0, v12, 3", "v_cmp_class_f16_e32 vcc_lo, 0x3c00, v13"):
        must_reject(translate, program[:wait] + [operation] + program[wait:])
    scalar_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    for operation in ("v_cmp_lt_f16_e64 s0, s44, s47", "v_cmp_class_f16_e64 s0, s46, s47", "v_cmp_class_f16_e64 s0, 0.5, s47",
                      "v_cmp_class_f16_e64 s0, s47, 3"):
        must_reject(translate, program[:scalar_wait] + [operation] + program[scalar_wait:])
        translate(program[:scalar_wait + 1] + [operation] + program[scalar_wait + 1:])


def controls(directory):
    check_f16_cmp_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for _, body, *_ in (*F16_CMP_PROGRAMS, *F16_CLASS_PROGRAMS)),
    ]


draw = check_f16_cmp_draws
