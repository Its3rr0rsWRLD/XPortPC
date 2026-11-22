"""Draw family `int_compare`: pixel_aot_check.py draw --family int_compare.

Integer order: v_max_i32, v_min_i32, v_max_u32, v_min_u32 (e32 and e64), v_med3_i32 and v_med3_u32, v_min3 and
v_max3 (_i32, _u32; from R0Y00/Xbox2Windows#308 by Alexander); the integer
comparisons v_cmp_{eq,ne,lt,le,gt,ge}_{i32,u32} (e32 into VCC, e64 into an SGPR or VCC) read through v_cndmask_b32;
v_add_co_u32, v_sub_co_u32 and v_subrev_co_u32 with their carry out; and the scalar comparisons s_cmp_eq_i32,
s_cmp_lt_i32 and s_cmp_lg_i32 read through uniform branches. Words are constant words 3 to 6 (x, y, z, w = s44..s47),
with v18 a v_mov_b32 copy of y. The words are chosen so that signed and unsigned order disagree (the sign bit set on
one side), equal words occur, and sums and differences wrap. Every program reads its results back exactly (bytes
through v_cvt_f32_ubyteN, conditions as 0 or 1) and has wrong references (the other signedness, operands swapped,
a negated condition, a dropped carry, the median of the wrong order) that must each be reported as a pixel_mismatch
for at least one set of words.
"""
import struct
import subprocess

from .common import M32, byte, must_reject, signed, translate, ubyte, with_constants
from .int_convert import readback, run_word_programs

RELATIONS = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "lt": lambda a, b: a < b,
             "le": lambda a, b: a <= b, "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b}
NEGATED = {"eq": "ne", "ne": "eq", "lt": "ge", "ge": "lt", "le": "gt", "gt": "le"}


def order(kind, value):
    return signed(value) if kind == "i32" else value


def other(kind):
    return "u32" if kind == "i32" else "i32"


def pick(op, kind, a, b):
    """v_max/v_min: the source word that is larger or smaller in the signed or unsigned order."""
    return (max if op == "max" else min)((a, b), key=lambda v: order(kind, v))


def median(kind, a, b, c):
    return sorted((a, b, c), key=lambda v: order(kind, v))[1]


def word_of(token, words):
    """The source word of a test operand: x..w, v18 (= y), or an inline integer or a literal."""
    names = {"s44": 0, "s45": 1, "s46": 2, "s47": 3, "v18": 1}
    return words[names[token]] if token in names else int(token, 0) & M32


# Order sets: signed and unsigned order disagree (one word with the sign bit set), equal words, extremes. x and y
# differ in every byte, and y differs from the constants of the third min/max program in the byte its channel reads.
ORDER_SETS = ((0x80123456, 0x7e654321, 0x00000034, 0xffffff56),
              (0x7e654321, 0x80123456, 0xffffff56, 0x00000034),
              (0x12345678, 0x12345678, 0x9abcdef0, 0x00000001),
              (0xfedcba98, 0x01234567, 0x80000000, 0x7fffffff),
              (0x05050505, 0xfbfbfbfb, 0x00000005, 0x80000001),
              (0xffffffff, 0x01010101, 0x00000000, 0xfffffffe),
              (0x01020304, 0x8a0b0c0d, 0x7f6e5d4c, 0x00000002),
              (0x00000000, 0x80808080, 0x7fffffff, 0x7f0000ff))


def minmax_program(lines):
    """Four min/max lines writing v19..v22; channel n is byte n of the nth result, and every set has the two
    sources differ in that byte where they differ at all, so the byte names the chosen word."""
    ops = []
    for line in lines:
        mnemonic, operands = line.split(" ", 1)
        op, kind = mnemonic.split("_")[1:3]
        ops.append((op, kind, [t.strip() for t in operands.split(",")[1:]]))
    body = ["v_mov_b32_e32 v18, s45", *lines, *(ubyte(n, 12 + n, f"v{19 + n}", "e32") for n in range(4))]

    def reference(*words, swap_kind=None, swap_op=None):
        out = []
        for n, (op, kind, (a, b)) in enumerate(ops):
            kind = other(kind) if n == swap_kind else kind
            op = ("min" if op == "max" else "max") if n == swap_op else op
            out.append(byte(pick(op, kind, word_of(a, words), word_of(b, words)), n))
        return out
    bugs = {**{f"signedness_{n}": (lambda n: lambda *w: reference(*w, swap_kind=n))(n) for n in range(4)},
            **{f"min_for_max_{n}": (lambda n: lambda *w: reference(*w, swap_op=n))(n) for n in range(4)}}
    return (body, reference, ORDER_SETS, bugs)


MINMAX_PROGRAMS = (
    minmax_program(["v_max_i32_e32 v19, s44, v18", "v_min_i32_e64 v20, s44, v18", "v_max_u32_e64 v21, v18, s44",
                    "v_min_u32_e32 v22, s44, v18"]),
    minmax_program(["v_min_i32_e32 v19, s44, v18", "v_max_i32_e64 v20, v18, s44", "v_min_u32_e64 v21, s44, v18",
                    "v_max_u32_e32 v22, s44, v18"]),
    # Inline constants and literals against the register: -1 and 64, a negative and a positive literal.
    minmax_program(["v_max_i32_e32 v19, -1, v18", "v_min_u32_e32 v20, 64, v18", "v_min_i32_e64 v21, v18, 0x800000ff",
                    "v_max_u32_e64 v22, 0x7f0000ff, v18"]),
)


def median_bugs(kind, tokens):
    return {"other_signedness": lambda w: median(other(kind), *(word_of(t, w) for t in tokens)),
            "min_max_only": lambda w: max(sorted((word_of(t, w) for t in tokens[:2]),
                                                  key=lambda v: order(kind, v))[0], word_of(tokens[2], w),
                                           key=lambda v: order(kind, v)),
            "first_source": lambda w: word_of(tokens[0], w)}


def median_program(line):
    kind = line.split()[0].split("_")[2]
    tokens = [t.strip() for t in line.split(" ", 1)[1].split(",")[1:]]
    model = lambda w: median(kind, *(word_of(t, w) for t in tokens))
    return (line, ["v_mov_b32_e32 v18, s45", line, *readback("v19")], model, ORDER_SETS, median_bugs(kind, tokens))


# Whole-word medians: the signed and unsigned order of register words, and the corpus's sign clamp to [-1, 1].
MEDIAN_PROGRAMS = (
    median_program("v_med3_i32 v19, s44, v18, s46"),
    median_program("v_med3_u32 v19, s44, v18, s46"),
    median_program("v_med3_i32 v19, -1, v18, 1"),
    median_program("v_med3_u32 v19, s47, 0x7f0000ff, v18"),
)


def extreme_program(line):
    """v_min3/v_max3 of three words, read back as the whole result word."""
    op, kind = line.split()[0].split("_")[1:3]
    tokens = [t.strip() for t in line.split(" ", 1)[1].split(",")[1:]]
    pick3 = min if op == "min3" else max
    model = lambda w: pick3((word_of(t, w) for t in tokens), key=lambda v: order(kind, v))
    bugs = {"other_signedness": lambda w: pick3((word_of(t, w) for t in tokens), key=lambda v: order(other(kind), v)),
            "third_source_ignored": lambda w: pick3((word_of(t, w) for t in tokens[:2]), key=lambda v: order(kind, v)),
            "min_for_max": lambda w: (max if pick3 is min else min)((word_of(t, w) for t in tokens),
                                                                    key=lambda v: order(kind, v))}
    return (line, ["v_mov_b32_e32 v18, s45", line, *readback("v19")], model, ORDER_SETS, bugs)


EXTREME_PROGRAMS = (
    extreme_program("v_min3_i32 v19, s44, v18, s46"),
    extreme_program("v_max3_i32 v19, s46, s44, v18"),
    extreme_program("v_min3_u32 v19, v18, s47, s44"),
    extreme_program("v_max3_u32 v19, s44, 64, s47"),
)

COMPARE_SETS = ((5, 5, 0, 0), (5, 6, 0, 0), (6, 5, 0, 0), (0xffffffff, 1, 0, 0), (1, 0xffffffff, 0, 0),
                (0x80000000, 0x7fffffff, 0, 0), (0x7fffffff, 0x80000000, 0, 0), (0x80000000, 0x80000000, 0, 0))


def compare_program(compares):
    """Four compares (op, kind, encoding, mask): x against y, e32 as `s44, v18`, e64 as `v18, s44` (y against x),
    each read through v_cndmask_b32 into 0.0 or 1.0 in v12..v15."""
    body = ["v_mov_b32_e32 v18, s45"]
    for n, (op, kind, encoding, mask) in enumerate(compares):
        sources = "s44, v18" if encoding == "e32" else "v18, s44"
        body += [f"v_cmp_{op}_{kind}_{encoding} {mask}, {sources}",
                 f"v_cndmask_b32_e64 v{12 + n}, 0, 1.0, {mask}"]

    def reference(x, y, z, w, swap_kind=None, swap_operands=None, negate=None):
        out = []
        for n, (op, kind, encoding, _) in enumerate(compares):
            a, b = (x, y) if encoding == "e32" else (y, x)
            if n == swap_operands:
                a, b = b, a
            kind = other(kind) if n == swap_kind else kind
            op = NEGATED[op] if n == negate else op
            out.append(int(RELATIONS[op](order(kind, a), order(kind, b))))
        return out
    bugs = {}
    for n, (op, _, _, _) in enumerate(compares):
        bugs[f"negated_{n}"] = (lambda n: lambda *w: reference(*w, negate=n))(n)
        if op not in ("eq", "ne"):
            bugs[f"signedness_{n}"] = (lambda n: lambda *w: reference(*w, swap_kind=n))(n)
            bugs[f"operands_swapped_{n}"] = (lambda n: lambda *w: reference(*w, swap_operands=n))(n)
    return (body, reference, COMPARE_SETS, bugs)


COMPARE_PROGRAMS = tuple(
    compare_program([(op, kind, encoding, mask) for op, mask in zip(ops, masks)])
    for kind in ("i32", "u32")
    for encoding, masks in (("e32", ("vcc_lo",) * 4), ("e64", ("s52", "vcc_lo", "s53", "s54")))
    for ops in (("eq", "ne", "lt", "le"), ("gt", "ge", "lt", "ne"))
)
# The comparisons with a constant source: an inline -1 and a literal, both encodings.
COMPARE_CONSTANTS = (
    ["v_mov_b32_e32 v18, s45",
     "v_cmp_gt_i32_e32 vcc_lo, -1, v18", "v_cndmask_b32_e64 v12, 0, 1.0, vcc_lo",
     "v_cmp_lt_u32_e32 vcc_lo, 0x80000000, v18", "v_cndmask_b32_e64 v13, 0, 1.0, vcc_lo",
     "v_cmp_le_i32_e64 s52, v18, 0x7fffffff", "v_cndmask_b32_e64 v14, 0, 1.0, s52",
     "v_cmp_ge_u32_e64 s53, v18, 1", "v_cndmask_b32_e64 v15, 0, 1.0, s53"],
    lambda x, y, z, w: [int(-1 > signed(y)), int(0x80000000 < y), int(signed(y) <= 0x7fffffff), int(y >= 1)],
    COMPARE_SETS,
    {"constant_unsigned": lambda x, y, z, w: [int(M32 > y), int(0x80000000 < y), int(signed(y) <= 0x7fffffff), int(y >= 1)],
     "literal_signed": lambda x, y, z, w: [int(-1 > signed(y)), int(-(1 << 31) < signed(y)), int(signed(y) <= 0x7fffffff), int(y >= 1)],
     "negated_le": lambda x, y, z, w: [int(-1 > signed(y)), int(0x80000000 < y), int(signed(y) > 0x7fffffff), int(y >= 1)],
     "signed_ge": lambda x, y, z, w: [int(-1 > signed(y)), int(0x80000000 < y), int(signed(y) <= 0x7fffffff), int(signed(y) >= 1)]},
)

CARRY_SETS = ((0xffffffff, 0x00000001, 0, 0), (0x80000000, 0x80000000, 0, 0), (0x00000005, 0x00000007, 0, 0),
              (0x00000007, 0x00000005, 0, 0), (0x12345678, 0xedcba988, 0, 0), (0, 0, 0, 0),
              (0xfffffffe, 0xfffffffe, 0, 0), (0x7fffffff, 0x00000001, 0, 0), (0x89abcdef, 0x76543211, 0, 0))


def add(a, b):
    return (a + b) & M32, int(a + b > M32)


def sub(a, b):
    return (a - b) & M32, int(b > a)


CARRY_PROGRAMS = (
    # Sum bytes 0..2 and the carry into an SGPR.
    (["v_mov_b32_e32 v18, s45", "v_add_co_u32 v19, s52, s44, v18", *(ubyte(n, 12 + n, "v19", "e32") for n in range(3)),
      "v_cndmask_b32_e64 v15, 0, 1.0, s52"],
     lambda x, y, z, w: [*(byte(add(x, y)[0], n) for n in range(3)), add(x, y)[1]],
     CARRY_SETS,
     {"carry_dropped": lambda x, y, z, w: [*(byte(add(x, y)[0], n) for n in range(3)), 0],
      "signed_overflow": lambda x, y, z, w: [*(byte(add(x, y)[0], n) for n in range(3)),
                                             int(not -(1 << 31) <= signed(x) + signed(y) < (1 << 31))],
      "sum_saturated": lambda x, y, z, w: [*(byte(min(x + y, M32), n) for n in range(3)), add(x, y)[1]]}),
    # The difference's bytes 1..3 and the borrow into VCC, and the reversed difference with an inline constant.
    (["v_mov_b32_e32 v18, s45", "v_sub_co_u32 v19, vcc_lo, s44, v18",
      *(ubyte(n, 11 + n, "v19", "e32") for n in range(1, 4)), "v_cndmask_b32_e64 v15, 0, 1.0, vcc_lo"],
     lambda x, y, z, w: [*(byte(sub(x, y)[0], n) for n in range(1, 4)), sub(x, y)[1]],
     CARRY_SETS,
     {"operands_swapped": lambda x, y, z, w: [*(byte(sub(y, x)[0], n) for n in range(1, 4)), sub(y, x)[1]],
      "borrow_inverted": lambda x, y, z, w: [*(byte(sub(x, y)[0], n) for n in range(1, 4)), 1 - sub(x, y)[1]],
      "borrow_signed": lambda x, y, z, w: [*(byte(sub(x, y)[0], n) for n in range(1, 4)), int(signed(y) > signed(x))]}),
    (["v_mov_b32_e32 v18, s45", "v_subrev_co_u32 v19, s52, s44, v18", "v_subrev_co_u32 v20, vcc_lo, 7, v18",
      ubyte(0, 12, "v19", "e32"), ubyte(3, 13, "v19", "e32"), "v_cndmask_b32_e64 v14, 0, 1.0, s52",
      "v_cndmask_b32_e64 v15, 0, 1.0, vcc_lo"],
     lambda x, y, z, w: [byte(sub(y, x)[0], 0), byte(sub(y, x)[0], 3), sub(y, x)[1], sub(y, 7)[1]],
     CARRY_SETS,
     {"not_reversed": lambda x, y, z, w: [byte(sub(x, y)[0], 0), byte(sub(x, y)[0], 3), sub(x, y)[1], sub(7, y)[1]],
      "borrow_of_forward": lambda x, y, z, w: [byte(sub(y, x)[0], 0), byte(sub(y, x)[0], 3), sub(x, y)[1], sub(y, 7)[1]]}),
)

# Scalar signed comparisons through uniform branches: SCC set by s_cmp_eq_i32, s_cmp_lt_i32 and s_cmp_lg_i32 (with a
# literal and an inline constant) chooses which of two words each channel takes.
SCALAR_COMPARE_BODY = [
    "v_mov_b32_e32 v18, 0x10",
    "s_cmp_eq_i32 s44, s45",
    "s_cbranch_scc0 BB0_1",
    "v_mov_b32_e32 v18, 0x21",
    "BB0_1:",
    "v_mov_b32_e32 v19, 0x30",
    "s_cmp_lt_i32 s44, s45",
    "s_cbranch_scc0 BB0_2",
    "v_mov_b32_e32 v19, 0x41",
    "BB0_2:",
    "v_mov_b32_e32 v20, 0x50",
    "s_cmp_lg_i32 s46, s47",
    "s_cbranch_scc1 BB0_3",
    "v_mov_b32_e32 v20, 0x61",
    "BB0_3:",
    "v_mov_b32_e32 v21, 0x70",
    "s_cmp_lt_i32 s47, -1",
    "s_cbranch_scc1 BB0_4",
    "v_mov_b32_e32 v21, 0x81",
    "BB0_4:",
    "s_cmp_eq_i32 s46, 0x80000000",
    "s_cbranch_scc0 BB0_5",
    "v_xor_b32_e32 v21, 0xff, v21",
    "BB0_5:",
    "s_cmp_lg_i32 s44, 0",
    "s_cbranch_scc0 BB0_6",
    "v_xor_b32_e32 v20, 0xf, v20",
    "BB0_6:",
    *(ubyte(0, 12 + n, f"v{18 + n}", "e32") for n in range(4)),
]


def scalar_compare(x, y, z, w, lt_unsigned=False, eq_inverted=False, lg_as_eq=False):
    lt = (lambda a, b: a < b) if lt_unsigned else (lambda a, b: signed(a) < signed(b))
    lg = (lambda a, b: a == b) if lg_as_eq else (lambda a, b: a != b)
    eq = (lambda a, b: a != b) if eq_inverted else (lambda a, b: a == b)
    third = 0x50 if lg(z, w) else 0x61
    fourth = 0x70 if lt(w, M32) else 0x81
    return [0x21 if eq(x, y) else 0x10, 0x41 if lt(x, y) else 0x30,
            third ^ 0xf if lg(x, 0) else third, fourth ^ 0xff if eq(z, 0x80000000) else fourth]


SCALAR_COMPARE_SETS = ((5, 5, 7, 7, ), (0xffffffff, 1, 0x80000000, 0xffffffff), (1, 0xffffffff, 3, 0x80000000),
                       (0, 0x80000000, 0x80000000, 0x80000000), (0x7fffffff, 0x80000000, 1, 0))
SCALAR_COMPARE_PROGRAM = (SCALAR_COMPARE_BODY, scalar_compare, SCALAR_COMPARE_SETS,
                          {"lt_unsigned": lambda *w: scalar_compare(*w, lt_unsigned=True),
                           "eq_inverted": lambda *w: scalar_compare(*w, eq_inverted=True),
                           "lg_as_eq": lambda *w: scalar_compare(*w, lg_as_eq=True)})

CHANNEL_PROGRAMS = (*MINMAX_PROGRAMS, *COMPARE_PROGRAMS, COMPARE_CONSTANTS, *CARRY_PROGRAMS, SCALAR_COMPARE_PROGRAM)


def words_constants(words):
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, *words)
    return constants


def run_channel_programs(directory, compiler, renderer, backend):
    """Each program is (body, reference(x, y, z, w) -> four exact channel values, sets, {bug: wrong(...)}). Every set
    is drawn against the reference; every bug is drawn, and must be reported as a pixel_mismatch, for the first set
    where it differs."""
    case = directory / "intcmp.case"
    for index, (body, reference, sets, bugs) in enumerate(CHANNEL_PROGRAMS):
        source = directory / f"intcmp{index}.hlsl"
        shader = directory / f"intcmp{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        pending = dict(bugs)
        for words in sets:
            constants = words_constants(words)
            expected = reference(*words)
            case.write_bytes(constants + struct.pack("<4f", *map(float, expected)) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode == 77:  # no adapter: a skip, reported by pixel_aot_check.py
                raise subprocess.CalledProcessError(77, draw, result.stdout, result.stderr)
            if result.returncode:
                raise AssertionError(f"int_compare program {index}, words {[hex(w) for w in words]}: expected "
                                     f"{expected} on {backend}: {result.stdout}{result.stderr}")
            for bug, wrong in list(pending.items()):
                bad = wrong(*words)
                if bad == expected:
                    continue
                del pending[bug]
                case.write_bytes(constants + struct.pack("<4f", *map(float, bad)) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"Wrong reference {bug} escaped detection in int_compare program {index}")
        assert not pending, (index, sorted(pending))


def check_int_compare_draws(directory, compiler, renderer, backend):
    run_channel_programs(directory, compiler, renderer, backend)
    run_word_programs(directory, compiler, renderer, backend, "med", MEDIAN_PROGRAMS, constants_of=words_constants)
    run_word_programs(directory, compiler, renderer, backend, "ext", EXTREME_PROGRAMS, constants_of=words_constants)


def check_references():
    for index, (_, reference, sets, bugs) in enumerate(CHANNEL_PROGRAMS):
        for bug, wrong in bugs.items():
            assert any(wrong(*w) != reference(*w) for w in sets), (index, bug)
    for name, _, model, sets, bugs in (*MEDIAN_PROGRAMS, *EXTREME_PROGRAMS):
        for bug, wrong in bugs.items():
            assert any(wrong(w) != model(w) for w in sets), (name, bug)
    # Each min/max channel's byte names the chosen source: the two sources differ in that byte when they differ.
    for body, *_ in MINMAX_PROGRAMS:
        for n, line in enumerate(body[1:5]):
            a, b = (t.strip() for t in line.split(" ", 1)[1].split(",")[1:])
            for words in ORDER_SETS:
                wa, wb = word_of(a, words), word_of(b, words)
                assert wa == wb or byte(wa, n) != byte(wb, n), (line, [hex(v) for v in words])
    assert median("i32", 0xfffffffe, M32, 1) == M32 and median("u32", 0xfffffffe, M32, 1) == 0xfffffffe


def controls(directory):
    check_references()
    main = translate(with_constants(MINMAX_PROGRAMS[0][0])).split("float4 main", 1)[1]
    assert "asuint(max(asint(params[0].w), asint(movw20)))" in main and "uint valu23 = max(movw20, params[0].w);" in main, main
    assert "asfloat(" not in main.split("float alu24", 1)[0], main
    main = translate(with_constants(MEDIAN_PROGRAMS[2][1])).split("float4 main", 1)[1]
    assert "int meda21 = asint(4294967295u);" in main and "max(min(meda21, medb21), min(max(meda21, medb21), medc21))" in main, main
    main = translate(with_constants(EXTREME_PROGRAMS[0][1])).split("float4 main", 1)[1]
    assert "uint valu21 = asuint(min(min(asint(params[0].w), asint(movw20)), asint(params[1].y)));" in main, main
    main = translate(with_constants(EXTREME_PROGRAMS[3][1])).split("float4 main", 1)[1]
    assert "uint valu21 = max(max(params[0].w, 64u), params[1].z);" in main, main
    main = translate(with_constants(COMPARE_PROGRAMS[0][0])).split("float4 main", 1)[1]
    assert "bool cmp21 = asint(params[0].w) == asint(movw20);" in main and "selw22 = cmp21 ?" in main, main
    main = translate(with_constants(COMPARE_PROGRAMS[6][0])).split("float4 main", 1)[1]
    assert "bool cmp21 = movw20 == params[0].w;" in main and "bool cmp25 = movw20 < params[0].w;" in main, main
    main = translate(with_constants(CARRY_PROGRAMS[0][0])).split("float4 main", 1)[1]
    assert "uint valu21 = coa21 + cob21;" in main and "bool cmp21 = valu21 < coa21;" in main, main
    main = translate(with_constants(SCALAR_COMPARE_BODY)).split("float4 main", 1)[1]
    assert "(int(params[0].w) < int(params[1].x))" in main and "(params[1].y != params[1].z)" in main, main
    # Refused: modifiers and clamp (llvm-mc refuses them too, except clamp on the carry forms), v_cmpx (CF-2), the
    # compares and carry forms this card does not lower, lane masks that are EXEC or outstanding, unset sources,
    # outstanding samples, and the SDWA and DPP encodings.
    for line in ("v_max_i32_e64 v19, v18, s44 clamp", "v_min_u32_e64 v19, -v18, s44", "v_max_u32_e64 v19, |v18|, s44",
                 "v_med3_i32 v19, v18, s44, s45 clamp", "v_med3_u32 v19, -v18, s44, s45",
                 "v_cmp_eq_i32_e64 s52, v18, s44 clamp", "v_cmp_lt_u32_e64 s52, -v18, s44", "v_cmp_gt_i32_e64 s52, |v18|, s44",
                 "v_cmpx_eq_i32_e32 vcc_lo, s44, v18", "v_cmpx_lt_u32_e64 s52, v18, s44", "v_cmpx_ne_u32_e64 exec_lo, v18, s44",
                 "v_cmp_eq_i32_e64 exec_lo, v18, s44",
                 "v_cmp_lt_u64_e64 s52, v[18:19], s[44:45]",
                 "v_cmp_eq_i32_sdwa vcc_lo, s44, v18 src0_sel:DWORD src1_sel:DWORD",
                 "v_max_i32_sdwa v19, s44, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
                 "v_min_u32_dpp v19, v18, v18 row_shl:1 row_mask:0xf bank_mask:0xf",
                 "v_add_co_u32 v19, s52, s44, v18 clamp", "v_sub_co_u32 v19, vcc_lo, s44, v18 clamp",
                 "v_add_co_ci_u32_e32 v19, vcc_lo, s44, v18, vcc_lo", "v_sub_co_ci_u32_e64 v19, s52, s44, v18, s53",
                 "v_subrev_co_ci_u32_e32 v19, vcc_lo, s44, v18, vcc_lo", "v_add_co_u32 v19, exec_lo, s44, v18",
                 "v_med3_i16 v19, s44, v18, s45", "v_max3_i32_e32 v19, s44, v18, s45", "v_min3_u32 v19, -s44, v18, s45",
                 "v_max3_u32 v19, s44, |v18|, s45", "v_min3_i32 v19, s44, v18, s45 clamp", "v_max3_i32 v19, v30, s44, s45",
                 "v_max_i16_e32 v19, s44, v18",
                 "v_max_i32_e32 v19, s44, v30", "v_min_u32_e32 v19, v30, v18", "v_med3_i32 v19, v30, s44, s45",
                 "v_cmp_eq_u32_e32 vcc_lo, s44, v30", "v_add_co_u32 v19, s52, v30, v18", "v_max_i32_e32 v19, s90, v18",
                 # A literal wider than 32 bits (a refusal from R0Y00/Xbox2Windows#308 by Alexander).
                 "v_min_i32_e64 v19, 0x100000000, v18", "v_cmp_eq_u32_e32 vcc_lo, 0x100000000, v18",
                 "v_add_co_u32 v19, s52, 0x100000000, v18"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    program = with_constants([])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    wait = program.index("s_waitcnt vmcnt(0)")
    for at, early in ((load, "v_max_i32_e64 v19, s44, 0"), (load, "v_cmp_eq_u32_e64 s52, s44, 0"),
                      (load, "v_cmp_eq_u32_e64 s44, 0, 1"), (load, "v_add_co_u32 v19, s45, 0, 1"),
                      (load, "v_med3_u32 v19, s46, 0, 1"),
                      (wait, "v_max_u32_e32 v19, 0, v13"), (wait, "v_cmp_lt_i32_e32 vcc_lo, 0, v12"),
                      (wait, "v_add_co_u32 v19, s52, 0, v14"), (wait, "v_med3_i32 v19, 0, 1, v15"),
                      (wait, "v_min_i32_e32 v13, 0, 1"), (wait, "v_sub_co_u32 v12, s52, 0, 1")):
        must_reject(translate, program[:at] + [early] + program[at:])
    # A carry is a lane mask like a comparison: s_cbranch on it, or a select that reads half of it, is refused.
    must_reject(translate, with_constants(["v_add_co_u32 v19, s52, s44, s45", "s_cbranch_scc1 L1", "L1:"]))
    must_reject(translate, with_constants(["v_cmp_lt_u32_e64 s52, s44, s45", "v_cndmask_b32_e64 v12, 0, 1.0, s[52:53]"]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [*((with_constants(body), translate) for body, *_ in CHANNEL_PROGRAMS),
            *((with_constants(body), translate) for _, body, *_ in (*MEDIAN_PROGRAMS, *EXTREME_PROGRAMS))]


draw = check_int_compare_draws
