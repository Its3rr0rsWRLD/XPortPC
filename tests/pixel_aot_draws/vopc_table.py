"""Draw family `vopc_table`: pixel_aot_check.py draw --family vopc_table.

Table-driven VOPC draws, one per data type: v_cmp_<p>_{f32,f16,i32,u32,i16,u16} and v_cmp_class_f32, each in its e32
encoding (into VCC) and its e64 encoding (into VCC, an SGPR or an SGPR pair), every predicate of the type. The
operands are constant words 3 and 4 (S0 = s44, S1 = v18, a v_mov_b32 copy of s45), so each is a raw word and no bit
pattern passes through a float register. Each channel exports one lane-mask result through v_cndmask_b32 (0 or 1.0).
The e64 programs rotate source modifiers (float types: neg, abs, neg of abs) and destinations across channels and groups.

The references are independent of the lowering: the words are decoded by Python (struct "f" and "e", sign extension of
the low 16 bits) and the relation (less, equal, greater, unordered) is looked up in the predicate's truth-table
number. Every program names the plausible lowering bugs that each draw is also run against as a wrong reference;
each must change some channel on some input set (checked without a GPU) and must be reported as a pixel_mismatch.
f32 sets avoid a subnormal against zero or against another subnormal, because the f32 relation there depends on the
flush mode of the device; a subnormal is only set against a normal or an infinity, where both modes agree. binary16
subnormals widen to normal binary32 values, so the f16 sets compare them exactly.
"""
import math
import struct
import subprocess

from .common import M32, half_value, must_reject, translate, with_constants
from .f16_cmp import class16_ref, class32_ref, cmp_words, relation_ref
from .predicate import INT_PREDICATES, PREDICATES

DESTS = ("s0", "vcc_lo", "s52", "s54")  # one SGPR each: llvm-mc assembles wave32, where a pair is refused
MODS = (("{}", "{}", lambda v: v, lambda v: v),
        ("-{}", "-{}", lambda v: -v, lambda v: -v),
        ("|{}|", "-{}", abs, lambda v: -v),
        ("-|{}|", "|{}|", lambda v: -abs(v), abs))
FLOAT_NUMBER = {op: number for number, op in enumerate(PREDICATES)}
INT_NUMBER = {op: number for number, op in enumerate(INT_PREDICATES)}
INT16_OPS = (("eq", "ne", "lt", "le"), ("gt", "ge", "ne", "lt"))


def f32_of(word):
    return struct.unpack("<f", struct.pack("<I", word & M32))[0]


def sign_extend(word, bits):
    word &= (1 << bits) - 1
    return word - (1 << bits) if word >> (bits - 1) else word


def decode(kind, word, bug):
    """A source word as the instruction must read it."""
    if kind == "f32":
        return f32_of(word)
    if kind == "f16":
        if bug == "high_half":
            return f32_of(word)
        x = half_value(word)
        return math.copysign(0.0, x) if bug == "flush" and x != 0 and abs(x) < 2.0 ** -14 else x
    if kind in ("i32", "u32"):
        if bug == "signedness":
            kind = "u32" if kind == "i32" else "i32"
        return sign_extend(word, 32) if kind == "i32" else word & M32
    if bug == "signedness":
        kind = "u16" if kind == "i16" else "i16"
    if bug == "whole_word":
        return sign_extend(word, 32) if kind == "i16" else word & M32
    return sign_extend(word, 16) if kind == "i16" else word & 0xffff


def relation(a, b):
    return relation_ref(a, b) if isinstance(a, float) or isinstance(b, float) else 0 if a < b else 1 if a == b else 2


def number_of(kind, op):
    return FLOAT_NUMBER[op] if kind in ("f32", "f16") else INT_NUMBER[op]


def channel_result(kind, op, rel, bug):
    number = number_of(kind, op)
    if bug == "swap_lt_gt":
        rel = {0: 2, 2: 0}.get(rel, rel)
    if bug == "nan_ordered" and rel == 3:
        return 0.0  # an unordered operand treated as ordered: no predicate fires
    if bug == "ordered_as_unordered":
        number ^= 8  # the ordered compare answers as its unordered counterpart, and the other way round
    if bug == "negated":
        number = ~number & (0xf if kind in ("f32", "f16") else 0x7)
    return float((number >> rel) & 1)


def compare_program(kind, encoding, group):
    """Body, per-channel (op, modifier index) and the instruction text of one group of four predicates."""
    ops = (PREDICATES[group * 4:group * 4 + 4] if kind in ("f32", "f16") else
           INT_PREDICATES[group * 4:group * 4 + 4] if kind in ("i32", "u32") else INT16_OPS[group])
    float_kind = kind in ("f32", "f16")
    body = ["v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v19, 1.0"]
    channels = []
    for channel, op in enumerate(ops):
        mod = (channel + group) % 4 if float_kind and encoding == "e64" else 0
        if encoding == "e32":
            body += [f"v_cmp_{op}_{kind}_e32 vcc_lo, s44, v18", f"v_cndmask_b32_e32 v{12 + channel}, 0, v19, vcc_lo"]
        else:
            dest = DESTS[(channel + group) % 4]
            body += [f"v_cmp_{op}_{kind}_e64 {dest}, {MODS[mod][0].format('s44')}, {MODS[mod][1].format('v18')}",
                     f"v_cndmask_b32_e64 v{12 + channel}, 0, v19, {dest}"]
        channels.append((op, mod))
    return body, channels


def compare_model(kind, channels):
    def model(words, bug):
        a, b = decode(kind, words[0], bug), decode(kind, words[1], bug)
        out = []
        for op, mod in channels:
            x, y = (MODS[mod][2](a), MODS[mod][3](b)) if bug != "no_mod" else (a, b)
            out.append(channel_result(kind, op, relation(x, y), bug))
        return out
    return model


# S0, S1 words. Float sets: ordinary, -0 against +0, NaNs (quiet, signaling, with payload and sign) on either side,
# infinities of both signs, equal values, a subnormal against a normal and against an infinity.
F32_SETS = tuple((x, y, 0, 0) for x, y in (
    (0xbf800000, 0x3f800000), (0x80000000, 0x00000000), (0x7fc00000, 0x3f800000), (0x3f800000, 0x7fa00001),
    (0x7f800000, 0xff800000), (0xff800000, 0xff800000), (0x3fc00000, 0x3fc00000), (0x007fffff, 0x00800000),
    (0x80000001, 0x00800000), (0x00000001, 0xff800000), (0xffffffff, 0xffffffff), (0xff800000, 0x80000001),
    (0x7f800000, 0x7f7fffff), (0xc0000000, 0xbf800000)))
F16_SETS = (cmp_words(0xbc00, 0x3c00), cmp_words(0x8000, 0x0000), cmp_words(0x7e00, 0x3c00), cmp_words(0x3c00, 0x7d00),
            cmp_words(0x7c00, 0xfc00), cmp_words(0xfc00, 0xfc00), cmp_words(0x0001, 0x0000),
            cmp_words(0x8001, 0x0001), cmp_words(0x03ff, 0x0400), cmp_words(0x7c00, 0x7bff),
            cmp_words(0xfe01, 0xfe01), cmp_words(0x3c00, 0x3c00, hx=0x7fc0, hy=0x0000),
            cmp_words(0x4000, 0x3c00, hx=0x0000, hy=0x7f00), cmp_words(0x0000, 0x8000, hx=0xffff, hy=0x0000))
INT32_SETS = tuple((x, y, 0, 0) for x, y in (
    (0x80000000, 0x00000000), (0x00000000, 0x80000000), (0xffffffff, 0x00000001), (0x00000001, 0xffffffff),
    (0x00000005, 0x00000005), (0x7fffffff, 0x80000000), (0x80000000, 0x80000000), (0x12345678, 0x12345679),
    (0x00000000, 0x00000000), (0xfffffffe, 0xffffffff), (0x80000001, 0x7fffffff)))
# 16-bit: signed and unsigned order disagree, equal low halves under different high halves (a whole-word read is
# not equal), and a larger low half under a smaller high half (a whole-word read reverses the relation).
INT16_SETS = tuple((hx << 16 | x, hy << 16 | y, 0, 0) for x, y, hx, hy in (
    (0x8000, 0x0000, 0x0000, 0x0000), (0x0000, 0x8000, 0x0000, 0x0000), (0xffff, 0x0001, 0x7fff, 0x0000),
    (0x1234, 0x1234, 0xdead, 0xbeef), (0x7fff, 0x8000, 0x0000, 0xffff), (0x0001, 0x0002, 0xffff, 0x0000),
    (0xffff, 0xfffe, 0x0000, 0x0000), (0x8000, 0x8000, 0x0000, 0xffff), (0x0000, 0x0000, 0x8000, 0x0001),
    (0x0002, 0x0001, 0x0000, 0xffff)))

# Hand-computed channels of the bug-free models: (kind, encoding, group, set index, channels). They pin the models
# to the ISA: the f32 e32 group 0 is f, lt, eq, le; e64 group g rotates the modifiers and the destinations.
EXPECTED = (
    ("f32", "e32", 0, 0, [0, 1, 0, 1]),     # -1 against 1: less
    ("f32", "e32", 0, 1, [0, 0, 1, 1]),     # -0 against +0: equal
    ("f32", "e32", 0, 2, [0, 0, 0, 0]),     # a quiet NaN: no ordered predicate holds
    ("f32", "e32", 2, 3, [1, 1, 1, 1]),     # u, nge, nlg, ngt with a signaling NaN: all hold
    ("f32", "e32", 1, 4, [1, 1, 1, 1]),     # +inf against -inf is greater: gt, lg, ge, o
    ("f32", "e32", 3, 7, [0, 1, 0, 1]),     # a subnormal is less than the least normal: nle, neq, nlt, tru
    ("f16", "e32", 0, 6, [0, 0, 0, 0]),     # 0x0001 against 0 is greater: f, lt, eq, le
    ("f16", "e32", 1, 6, [1, 1, 1, 1]),     # gt, lg, ge, o
    ("i32", "e32", 0, 0, [0, 1, 0, 1]),     # 0x80000000 against 0 is less when signed: f, lt, eq, le
    ("u32", "e32", 0, 0, [0, 0, 0, 0]),     # and greater when unsigned
    ("i16", "e32", 0, 0, [0, 1, 1, 1]),     # low halves 0x8000 (-32768) against 0: eq, ne, lt, le
    ("u16", "e32", 0, 0, [0, 1, 0, 0]),     # 0x8000 against 0 unsigned: greater
)


def models():
    """(name, body, model, sets, bugs) for every compare program."""
    sets = {"f32": F32_SETS, "f16": F16_SETS, "i32": INT32_SETS, "u32": INT32_SETS, "i16": INT16_SETS, "u16": INT16_SETS}
    out = []
    for kind in sets:
        groups = 4 if kind in ("f32", "f16") else 2
        for encoding in ("e32", "e64"):
            for group in range(groups):
                body, channels = compare_program(kind, encoding, group)
                bugs = ["swap_lt_gt"]
                if kind in ("f32", "f16"):
                    bugs += ["ordered_as_unordered"]
                    if any(number_of(kind, op) >= 8 for op, _ in channels):
                        bugs += ["nan_ordered"]
                    if encoding == "e64":
                        bugs += ["no_mod"]
                    if kind == "f16":
                        bugs += ["high_half", "flush"]
                else:
                    bugs += ["negated", "signedness"]
                    if kind in ("i16", "u16"):
                        bugs += ["whole_word"]
                out.append((f"{kind}_{encoding}_{group}", body, compare_model(kind, channels), sets[kind], tuple(bugs)))
    return out


# v_cmp_class_f32: the class of S0 (after its modifiers) is in the mask S1, bit n as LLVM's SIInstrFlags::ClassFlags
# (signaling NaN 0x1, quiet NaN 0x2, -inf 0x4, -normal 0x8, -subnormal 0x10, -0 0x20, +0 0x40, +subnormal 0x80,
# +normal 0x100, +inf 0x200). Channels: S0 against the SGPR mask S1 (e64, SGPR dest), against the vector mask S2 (e32),
# -S0 against the literal 0x44 (-inf, +0; e64, VCC dest) and |S0| against the inline mask 3 (NaNs; e64, SGPR dest).
CLASS_BODY = [
    "v_mov_b32_e32 v18, s46", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_class_f32_e64 s0, s44, s45", "v_cndmask_b32_e64 v12, 0, v19, s0",
    "v_cmp_class_f32_e32 vcc_lo, s44, v18", "v_cndmask_b32_e32 v13, 0, v19, vcc_lo",
    "v_cmp_class_f32_e64 vcc_lo, -s44, 0x44", "v_cndmask_b32_e64 v14, 0, v19, vcc_lo",
    "v_cmp_class_f32_e64 s54, |s44|, 3", "v_cndmask_b32_e64 v15, 0, v19, s54",
]
CLASS_WORDS = (0x7fa00001, 0xffc00000, 0xff800000, 0x7f800000, 0xbf800000, 0x3f800000, 0x80000001, 0x007fffff,
               0x80000000, 0x00000000, 0x00800000, 0x807fffff, 0x7f7fffff, 0xff7fffff, 0x7fffffff, 0xffa00000)


def class_model(words, bug):
    x, m0, m1, _ = words
    classify = class16_ref if bug == "f16_class" else class32_ref  # f16_class reads the low half as binary16
    neg, absolute = (x, x) if bug == "no_mod" else (x ^ 0x80000000, x & 0x7fffffff)
    return [float(classify(x) & m0 != 0), float(classify(x) & m1 != 0), float(classify(neg) & 0x44 != 0),
            float(classify(absolute) & 3 != 0)]


# One word per class and per edge of the encoding, with the mask of its own class in S1 and the complement in S2, and the
# other way round on alternate words.
CLASS_SETS = tuple(
    (word, *((class32_ref(word), 0x3ff ^ class32_ref(word)) if index % 2 == 0
             else (0x3ff ^ class32_ref(word), class32_ref(word))), 0)
    for index, word in enumerate(CLASS_WORDS))
CLASS_BUGS = ("no_mod", "f16_class")


def check_models():
    """The models against hand-computed channels, and each listed bug against the sets that must expose it."""
    programs = {name: (model, sets) for name, _, model, sets, _ in models()}
    for kind, encoding, group, index, expected in EXPECTED:
        model, sets = programs[f"{kind}_{encoding}_{group}"]
        assert model(sets[index], None) == [float(v) for v in expected], (kind, encoding, group, index,
                                                                           model(sets[index], None))
    for name, _, model, sets, bugs in (*models(), ("class", CLASS_BODY, class_model, CLASS_SETS, CLASS_BUGS)):
        for bug in bugs:
            assert any(model(words, bug) != model(words, None) for words in sets), (name, bug)


def drawn_programs():
    return [*models(), ("class", CLASS_BODY, class_model, CLASS_SETS, CLASS_BUGS), *const16_programs()]


# 16-bit integers against inline constants and a literal: -1 as the inline integer is 0xffff in the low half, and a
# literal supplies its low half. Channels: i16 -1 < S1, u16 64 > S1, i16 literal 0x8000 >= S1, u16 literal 0x1234 == S1.
CONST16_BODY = [
    "v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v19, 1.0",
    "v_cmp_lt_i16_e32 vcc_lo, -1, v18", "v_cndmask_b32_e32 v12, 0, v19, vcc_lo",
    "v_cmp_gt_u16_e64 s0, 64, v18", "v_cndmask_b32_e64 v13, 0, v19, s0",
    "v_cmp_ge_i16_e32 vcc_lo, 0x8000, v18", "v_cndmask_b32_e32 v14, 0, v19, vcc_lo",
    "v_cmp_eq_u16_e64 s52, 0x1234, v18", "v_cndmask_b32_e64 v15, 0, v19, s52",
]
CONST16_SETS = tuple((hy << 16 | y, hy << 16 | y, 0, 0) for y, hy in (
    (0xffff, 0x0000), (0x0000, 0xdead), (0x8000, 0x7fff), (0x1234, 0xffff), (0x0040, 0x0000), (0x0041, 0x8000),
    (0x7fff, 0x0001), (0xfffe, 0x0000)))


def const16_model(words, bug):
    w = words[1]
    if bug == "whole_word":
        return [float(-1 < sign_extend(w, 32)), float(64 > w), float(-0x8000 >= sign_extend(w, 32)), float(0x1234 == w)]
    signed = (lambda v: sign_extend(v, 16)) if bug != "signedness" else (lambda v: v & 0xffff)
    unsigned = (lambda v: v & 0xffff) if bug != "signedness" else (lambda v: sign_extend(v, 16))
    # signedness: the i16 channels read their operands as u16 (so the inline -1 is 0xffff) and the u16 ones as i16.
    return [float((-1 if bug != "signedness" else 0xffff) < signed(w)), float(64 > unsigned(w)),
            float((-0x8000 if bug != "signedness" else 0x8000) >= signed(w)), float(0x1234 == unsigned(w))]


def const16_programs():
    return [("const16", CONST16_BODY, const16_model, CONST16_SETS, ("signedness", "whole_word"))]


def check_vopc_table_draws(directory, compiler, renderer, backend):
    check_models()
    case = directory / "vopc_table.case"
    for name, body, model, sets, bugs in drawn_programs():
        source = directory / f"vopc_table_{name}.hlsl"
        shader = directory / f"vopc_table_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        drawn = dict.fromkeys(bugs, 0)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = model(words, None)
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            try:
                subprocess.run(draw, check=True)
            except subprocess.CalledProcessError as error:
                error.add_note(f"VOPC table draw {name} on {backend}, words {[hex(w) for w in words]}")
                raise
            for bug in bugs:
                wrong = model(words, bug)
                # One exposing set per bug establishes that the renderer notices it.
                if wrong == expected or drawn[bug] == 1:
                    continue
                drawn[bug] += 1
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A comparison bug ({bug}) escaped detection in {name} for words {words}")
        assert all(count > 0 for count in drawn.values()), (name, drawn)


def check_vopc_table_controls():
    check_models()
    sources = {name: translate(with_constants(body)) for name, body, *_ in drawn_programs()}
    # 16-bit integers read the low halves: i16 sign-extends, u16 zero-extends; constants supply their low half.
    body = sources["i16_e64_0"].split("float4 main", 1)[1]
    assert "((int((params[0].w & 0xffffu)) ^ 0x8000) - 0x8000)" in body, body
    body = sources["u16_e32_0"].split("float4 main", 1)[1]
    assert "(params[0].w & 0xffffu) == (movw20 & 0xffffu)" in body, body
    body = sources["const16"].split("float4 main", 1)[1]
    for expected in ("((int(0xffffu) ^ 0x8000) - 0x8000)", "0x40u", "0x8000u", "0x1234u"):
        assert expected in body, expected
    body = sources["u16_e32_0"].split("float4 main", 1)[1]
    assert "0x8000) -" not in body and "asint(" not in body, body
    # f32 and f16 e64 sources keep their modifiers; f16 modifiers act on bit 15 of the low half.
    body = sources["f32_e64_1"].split("float4 main", 1)[1]
    assert "(-" in body and "abs(" in body, body
    body = sources["f16_e64_1"].split("float4 main", 1)[1]
    assert "^ 0x8000u" in body and "& 0x7fffu" in body, body
    body = sources["class"].split("float4 main", 1)[1]
    # abs and neg act on the sign bit of the word, so a subnormal survives (a float negate may flush it).
    assert "^ 0x80000000u" in body and "& 0x7fffffffu" in body and "class32((-" not in body and "class32(abs(" not in body, body
    # Wave64 spelling: an SGPR pair or VCC as the destination lowers exactly like the single register of wave32.
    for name, body, *_ in drawn_programs():
        if any(f"_e64 {d}," in line for line in body for d in ("s52", "s54")):
            wide = [line.replace(" s52,", " s[52:53],").replace(" s54,", " s[54:55],")
                    if "v_cmp" in line else line.replace("v19, s52", "v19, s[52:53]").replace("v19, s54", "v19, s[54:55]")
                    for line in body]
            assert wide != body
            assert translate(with_constants(wide)) == sources[name], name
    # One instruction at a time, as the neighbours of the covered forms: all must be refused.
    for operation in (
        "v_cmp_lt_i16_e64 s0, -s44, v18", "v_cmp_lt_i16_e64 s0, |s44|, v18", "v_cmp_lt_u16_e64 s0, s44, -v18",
        "v_cmp_lt_i16_e64 s0, s44, v18 clamp", "v_cmp_lt_i16_e64 s0, s44, v18 op_sel:[1,0]",
        "v_cmp_lt_u16_e32 vcc_lo, 0.5, v18", "v_cmp_lt_i16_e32 vcc_lo, 65, v18", "v_cmp_lt_i16_e32 vcc_lo, -17, v18",
        "v_cmp_lt_i16_e32 vcc_lo, 0x12345, v18", "v_cmp_lt_i16_e32 vcc_lo, s44", "v_cmp_lt_i16_e32 vcc_lo, s44, v18, v19",
        "v_cmp_lt_i16_e32 vcc_lo, s44, v30", "v_cmp_lt_u16_e32 vcc_lo, v30, s44",
        "v_cmp_f_i16_e32 vcc_lo, s44, v18", "v_cmp_t_u16_e32 vcc_lo, s44, v18", "v_cmp_f_u16_e64 s0, s44, v18",
        "v_cmp_lt_i16_dpp vcc_lo, v18, v19 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
        "v_cmpx_lt_u16_e64 s0, s44, v18",  # (v_cmpx_lt_i16_e32 before the export is a kill since CF-2d)
        "v_cmp_lt_i16_e64 s0, s44, v13 mul:2", "v_cmp_lt_u16_e64 s0, s44, v18 div:2",
        # Neighbours of the f32, f16, class and 32-bit integer forms.
        "v_cmp_lt_f32_e64 s0, s44, v18 clamp",
        "v_cmp_lt_f32_e64 s0, s44, v18 op_sel:[1,0]", "v_cmp_lt_f32_e64 s0, s44, v30",
        "v_cmp_lt_f16_e64 s0, s44, v18 clamp", "v_cmp_lt_f16_e64 s0, --s44, v18",
        "v_cmp_class_f32_e64 s0, s44, -s45", "v_cmp_class_f32_e64 s0, s44, |s45|", "v_cmp_class_f32_e64 s0, s44",
        "v_cmp_class_f32_e64 s0, s44, 0x1ffffffff", "v_cmp_class_f32_e64 s0, s44, 1.0",
        "v_cmp_class_f32_e64 s0, s44, v30", "v_cmp_class_f32_e64 s0, v30, 3",
        "v_cmp_lt_i32_e64 s0, s44, v18 clamp", "v_cmp_lt_u32_e32 vcc_lo, s44, v18, v19",
        "v_cmp_lt_i32_e32 vcc_lo, 0x100000000, v18", "v_cmp_lt_u32_e64 s0, s44, v30",
        "v_cmp_lt_f32_e64 s0, s44, v18 mul:2",
    ):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", operation]))
    # A source is not readable before the sample or the scalar load it depends on arrives, for every type.
    program = with_constants(["v_mov_b32_e32 v18, s45", "v_cmp_lt_f32_e32 vcc_lo, s44, v18"])
    wait = program.index("s_waitcnt vmcnt(0)")
    scalar_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    for operation in ("v_cmp_lt_i16_e32 vcc_lo, s44, v12", "v_cmp_lt_u16_e64 s0, v12, 3",
                      "v_cmp_lt_f32_e64 s0, -|v12|, 1.0", "v_cmp_class_f32_e32 vcc_lo, v12, v13",
                      "v_cmp_lt_u32_e32 vcc_lo, 1, v12"):
        must_reject(translate, program[:wait] + [operation] + program[wait:])
    for operation in ("v_cmp_lt_i16_e64 s0, s44, 0", "v_cmp_ne_u16_e32 vcc_lo, 0, s45",
                      "v_cmp_class_f32_e64 s0, 1.0, s47", "v_cmp_lt_f32_e64 s0, |s44|, 1.0"):
        must_reject(translate, program[:scalar_wait] + [operation] + program[scalar_wait:])
        translate(program[:scalar_wait + 1] + [operation] + program[scalar_wait + 1:])


def controls(directory):
    check_vopc_table_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for name, body, *_ in drawn_programs()]


draw = check_vopc_table_draws
