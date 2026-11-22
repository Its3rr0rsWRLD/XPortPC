"""Draw family `sdwa_int`: pixel_aot_check.py draw --family sdwa_int.

SDWA integer comparisons, min/max, bit scans and conversions between binary32 and 32-bit integers. Each program is
a table row; an independent integer model (below, with the selection model of the `sdwa` family) gives the result, and
wrong references with one selection, extension, modifier, signedness or destination wrong are derived from the same
model. For every row, a small set of inputs is chosen (greedily, from fixed special words and a fixed pseudo-random
sequence) so that each non-vacuous wrong reference differs from the right result on at least one of them; the draw
runs the right result on every chosen input and each wrong reference once, where it differs, and the wrong one must
fail. `controls` asserts that coverage without a GPU."""
import functools
import struct
import subprocess

from .common import DrawBatch, must_reject, translate, with_constants
from .sdwa import M32, S, Z, float_bits, model_field, model_place, signed32

# A source spec is (selector, sign-extended, modifier), as in the `sdwa` family; modifiers are for binary32 sources.
OTHER_SEL = lambda sel: f"WORD_{1 - int(sel[-1])}" if sel.startswith("WORD") else f"BYTE_{(int(sel[-1]) + 1) % 4}"
f32_of = lambda word: struct.unpack("<f", struct.pack("<I", word))[0]
FLOAT_WORDS = [float_bits(x) for x in (2.5, -2.5, 100.75, -7.75, 3e9, 5e9, 2147483648.0, -2147483648.0, -3e9,
                                       0.5, -0.5, 6.0, -1.0, 4294967040.0)] + [0x7f800000, 0xff800000, 0x7fc00000, 0x80000000, 0x00000001]
SPECIAL_WORDS = (0, M32, 0x80808080, 0x7f7f7f7f, 0x00ff00ff, 0xff00ff00, 0x0000ffff, 0xffff0000, 0x00800000, 0x01000003, 0xfeffffff)
INIT = 0x3f80c0de
BYTE_ALPHABET = (0x00, 0x01, 0x7f, 0x80, 0xff, 0xfe, 0x81)


def candidates(float_source=False, seed=0x2545f491):
    """Fixed data as (a, b) pairs: special words, then pseudo-random dwords."""
    pool = [(w, SPECIAL_WORDS[(n * 5 + 3) % len(SPECIAL_WORDS)]) for n, w in enumerate(FLOAT_WORDS if float_source else SPECIAL_WORDS)]
    state = seed
    for _ in range(0 if float_source else 400):
        state = (state * 1664525 + 1013904223) & M32
        a = state
        state = (state * 1664525 + 1013904223) & M32
        pool.append((a, state))
    # Words whose bytes come from a small alphabet, so that fields of the two sources are often equal.
    for _ in range(0 if float_source else 3000):
        words = []
        for _ in range(2):
            word = 0
            for _ in range(4):
                state = (state * 1664525 + 1013904223) & M32
                word = (word << 8) | BYTE_ALPHABET[(state >> 16) % len(BYTE_ALPHABET)]
            words.append(word)
        pool.append(tuple(words))
    return pool


# Inputs every row of a kind is drawn on: binary32 values (negative and large ones, infinity and NaN) for the float
# sources; for the integer conversions, words that need a round to nearest even.
BASE_FLOAT = [(float_bits(-2.5), 0), (float_bits(3e9), 0), (float_bits(5e9), 0), (0xff800000, 0), (0x7fc00000, 0)]
BASE_INT = [(0x01000003, 0xfeffffff), (0xfeffffff, 0x01000003)]


def choose_inputs(labels_of, wanted, pool, base=(), limit=6):
    """The base inputs, then a greedy set cover from the pool: inputs that between them show every wanted label.
    labels_of(input) is the set of labels whose wrong reference differs there."""
    chosen = list(base)
    remaining = set(wanted).difference(*(labels_of(item) for item in chosen))
    while remaining and len(chosen) < limit + len(base):
        best = max(pool, key=lambda item: (len(labels_of(item) & remaining), -pool.index(item)))
        gained = labels_of(best) & remaining
        if not gained:
            break
        chosen.append(best)
        remaining -= gained
    return chosen, remaining


# ---- comparisons -------------------------------------------------------------------------------------------------
# Each program is four channels (kind, op, source0, source1); channel k is v_cmp, then a select of 1.0 or 0 into
# v12+k. Channel 1 writes an SGPR lane mask and is read by the e64 select; the others use VCC.
RELATIONS = {"eq": lambda x, y: x == y, "ne": lambda x, y: x != y, "lt": lambda x, y: x < y, "le": lambda x, y: x <= y,
             "gt": lambda x, y: x > y, "ge": lambda x, y: x >= y, "f": lambda x, y: False, "t": lambda x, y: True}
CMP_PROGRAMS = [
    [("i32", "eq", Z("WORD_1"), S("BYTE_0")), ("i32", "ne", S("BYTE_2"), Z("DWORD")),
     ("i32", "lt", S("WORD_0"), S("WORD_1")), ("i32", "le", S("BYTE_3"), Z("BYTE_1"))],
    [("i32", "gt", Z("DWORD"), S("BYTE_2")), ("i32", "ge", Z("WORD_1"), S("WORD_0")),
     ("i32", "f", Z("WORD_0"), Z("DWORD")), ("i32", "t", S("BYTE_1"), Z("BYTE_0"))],
    [("u32", "eq", S("WORD_1"), S("BYTE_3")), ("u32", "ne", S("BYTE_1"), S("WORD_0")),
     ("u32", "lt", S("BYTE_2"), Z("WORD_1")), ("u32", "le", Z("DWORD"), S("BYTE_0"))],
    [("u32", "gt", S("WORD_0"), Z("DWORD")), ("u32", "ge", Z("BYTE_2"), S("BYTE_3")),
     ("u32", "f", Z("DWORD"), Z("DWORD")), ("u32", "t", Z("WORD_1"), S("WORD_0"))],
    [("i16", "eq", Z("WORD_1"), S("BYTE_0")), ("i16", "ne", S("BYTE_2"), Z("DWORD")),
     ("i16", "lt", S("BYTE_1"), Z("WORD_0")), ("i16", "le", Z("WORD_1"), S("BYTE_3"))],
    [("i16", "gt", Z("DWORD"), S("BYTE_2")), ("i16", "ge", S("WORD_0"), Z("WORD_1")),
     ("i16", "lt", S("BYTE_0"), S("BYTE_1")), ("i16", "le", S("BYTE_3"), Z("BYTE_2"))],
    [("u16", "eq", S("BYTE_3"), Z("WORD_0")), ("u16", "ne", Z("WORD_1"), S("BYTE_1")),
     ("u16", "lt", S("BYTE_2"), Z("DWORD")), ("u16", "le", Z("BYTE_0"), S("BYTE_3"))],
    [("u16", "gt", S("BYTE_1"), Z("WORD_1")), ("u16", "ge", Z("WORD_0"), S("BYTE_2")),
     ("u16", "lt", S("BYTE_3"), S("BYTE_0")), ("u16", "le", Z("DWORD"), Z("BYTE_1"))],
]


def cmp_truth(channel, a, b, kind=None, s0=None, s1=None):
    """One channel of a program on the words a and b, with an optional wrong kind or selection."""
    kind0, op, spec0, spec1 = channel
    kind, spec0, spec1 = kind or kind0, s0 or spec0, s1 or spec1
    width = 16 if kind.endswith("16") else 32
    values = []
    for word, spec in ((a, spec0), (b, spec1)):
        value = model_field(word, spec[0], spec[1]) & ((1 << width) - 1)
        values.append(value - (1 << width) if kind[0] == "i" and value >> (width - 1) else value)
    return float(RELATIONS[op](*values))


def cmp_wrongs(channel):
    """{label: truth function} of the wrong references of one channel that are not vacuous."""
    kind, op, s0, s1 = channel
    if op in ("f", "t"):
        return {"inverted": lambda a, b: 1.0 - cmp_truth(channel, a, b)}
    wrongs = {}
    for index, spec in enumerate((s0, s1)):
        if spec[0] == "DWORD":
            continue
        place = "s0" if index == 0 else "s1"
        wrongs[f"selector{index}"] = (lambda place, spec: lambda a, b: cmp_truth(channel, a, b, **{place: (OTHER_SEL(spec[0]), spec[1], "")}))(place, spec)
        # A 16-bit compare of a WORD field sees the same 16 bits whatever the extension.
        if not (kind.endswith("16") and spec[0].startswith("WORD")):
            wrongs[f"extension{index}"] = (lambda place, spec: lambda a, b: cmp_truth(channel, a, b, **{place: (spec[0], not spec[1], "")}))(place, spec)
    if op in ("lt", "le", "gt", "ge"):
        wrongs["signedness"] = lambda a, b: cmp_truth(channel, a, b, kind=("u" if kind[0] == "i" else "i") + kind[1:])
    return wrongs


def cmp_program(channels):
    body = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_sub_f32_e64 v21, s47, 0"]
    for k, (kind, op, (sel0, ext0, _), (sel1, ext1, _)) in enumerate(channels):
        mask = "s52" if k == 1 else "vcc_lo"
        first, second = (f"sext(v18)" if ext0 else "v18"), (f"sext(v19)" if ext1 else "v19")
        body.append(f"v_cmp_{op}_{kind}_sdwa {mask}, {first}, {second} src0_sel:{sel0} src1_sel:{sel1}")
        body.append(f"v_cndmask_b32_e64 v{12 + k}, 0, v21, s52" if k == 1 else f"v_cndmask_b32_e32 v{12 + k}, 0, v21, vcc_lo")
    return with_constants(body)


def cmp_plan(channels):
    """(inputs, {label: (channel, truth function)}, labels that no input shows)."""
    wrongs = {(k, label): fn for k, channel in enumerate(channels) for label, fn in cmp_wrongs(channel).items()}
    pool = candidates()

    def shows(item):
        a, b = item
        return {(k, label) for (k, label), fn in wrongs.items() if fn(a, b) != cmp_truth(channels[k], a, b)}

    inputs, missing = choose_inputs(shows, wrongs, pool)
    return inputs, wrongs, missing


@functools.cache
def cmp_plans():
    return [cmp_plan(channels) for channels in CMP_PROGRAMS]


def check_cmp_draws(directory, compiler, renderer, backend):
    for index, (channels, (inputs, wrongs, _)) in enumerate(zip(CMP_PROGRAMS, cmp_plans())):
        source, shader = directory / f"sdwa_int_cmp{index}.hlsl", directory / f"sdwa_int_cmp{index}.cso"
        source.write_text(translate(cmp_program(channels)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        batch = DrawBatch(directory, renderer, backend, shader, "sdwa_int_cmp")
        shown = set()
        for a, b in inputs:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, a, b, 0, 0x3f800000)
            right = [cmp_truth(channel, a, b) for channel in channels]
            batch.add(constants + struct.pack("<4f", *right) * 64, "pass",
                      f"SDWA comparison program {index} gives a result other than {right} for inputs {a:#x}, {b:#x}")
            for (k, label), fn in wrongs.items():
                if (k, label) in shown or fn(a, b) == right[k]:
                    continue
                values = list(right)
                values[k] = fn(a, b)
                batch.add(constants + struct.pack("<4f", *values) * 64, "mismatch",
                          f"A wrong SDWA comparison reference ({label}, channel {k}) escaped detection in program {index}")
                shown.add((k, label))
        batch.flush()


# ---- word results ------------------------------------------------------------------------------------------------
# A row is (operation, dst_sel, dst_unused, source0, source1); the 32-bit result register is read back as four bytes
# (v_cvt_f32_ubyte0..3), so a draw compares every bit of the result including the bits a destination keeps or pads.
def ffbh(x):
    return M32 if x == 0 else 32 - x.bit_length()


def to_int(word, kind):
    """Binary32 to a 32-bit integer: toward zero, saturating, NaN to 0."""
    x = f32_of(word)
    if x != x:
        return 0
    if kind == "i32":
        return 0x7fffffff if x >= 2.0 ** 31 else 0x80000000 if x <= -(2.0 ** 31) else int(x) & M32
    return M32 if x >= 2.0 ** 32 else 0 if x <= 0 else int(x)


def modified(word, mod):
    word = word & 0x7fffffff if "abs" in mod else word
    return word ^ 0x80000000 if "neg" in mod else word


# operation: (sources, float source, function of the source words)
OPS = {
    "max_i32": (2, False, lambda x, y: max(signed32(x), signed32(y)) & M32),
    "min_i32": (2, False, lambda x, y: min(signed32(x), signed32(y)) & M32),
    "max_u32": (2, False, max), "min_u32": (2, False, min),
    "ffbh_u32": (1, False, ffbh),
    "ffbh_i32": (1, False, lambda x: M32 if x in (0, M32) else ffbh(~x & M32 if x >> 31 else x)),
    "ffbl_b32": (1, False, lambda x: M32 if x == 0 else (x & -x).bit_length() - 1),
    "cvt_f32_i32": (1, False, lambda x: float_bits(float(signed32(x)))),
    "cvt_f32_u32": (1, False, lambda x: float_bits(float(x))),
    "cvt_i32_f32": (1, True, lambda x: to_int(x, "i32")),
    "cvt_u32_f32": (1, True, lambda x: to_int(x, "u32")),
}
ROWS = [
    ("max_i32", "DWORD", "UNUSED_PAD", S("WORD_1"), S("BYTE_2")), ("max_i32", "WORD_0", "UNUSED_PRESERVE", Z("BYTE_3"), S("BYTE_1")),
    ("min_i32", "DWORD", "UNUSED_PAD", S("BYTE_2"), S("WORD_0")), ("min_i32", "BYTE_2", "UNUSED_PRESERVE", Z("WORD_1"), Z("BYTE_0")),
    ("max_u32", "DWORD", "UNUSED_PAD", S("WORD_1"), Z("BYTE_1")), ("max_u32", "WORD_1", "UNUSED_PAD", Z("BYTE_2"), S("BYTE_3")),
    ("min_u32", "DWORD", "UNUSED_PAD", Z("WORD_0"), S("BYTE_3")), ("min_u32", "BYTE_3", "UNUSED_PRESERVE", S("BYTE_0"), Z("WORD_1")),
    ("ffbh_u32", "DWORD", "UNUSED_PAD", Z("BYTE_2"), None), ("ffbh_u32", "DWORD", "UNUSED_PAD", S("WORD_1"), None),
    ("ffbh_u32", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1"), None), ("ffbh_u32", "BYTE_1", "UNUSED_PAD", S("BYTE_3"), None),
    ("ffbh_i32", "DWORD", "UNUSED_PAD", S("BYTE_1"), None), ("ffbh_i32", "DWORD", "UNUSED_PAD", Z("WORD_0"), None),
    ("ffbh_i32", "BYTE_1", "UNUSED_PRESERVE", S("BYTE_3"), None), ("ffbh_i32", "WORD_1", "UNUSED_PAD", S("WORD_1"), None),
    ("ffbl_b32", "DWORD", "UNUSED_PAD", Z("BYTE_1"), None), ("ffbl_b32", "DWORD", "UNUSED_PAD", S("BYTE_3"), None),
    ("ffbl_b32", "BYTE_3", "UNUSED_PRESERVE", Z("WORD_1"), None), ("ffbl_b32", "WORD_0", "UNUSED_PAD", S("WORD_0"), None),
    ("cvt_f32_i32", "DWORD", "UNUSED_PAD", S("BYTE_2"), None), ("cvt_f32_i32", "DWORD", "UNUSED_PAD", Z("WORD_1"), None),
    ("cvt_f32_i32", "DWORD", "UNUSED_PAD", S("WORD_0"), None), ("cvt_f32_i32", "DWORD", "UNUSED_PAD", Z("DWORD"), None),
    # A result field takes the low bits of the binary32 result, which are zero unless the integer has more significant
    # bits than its field: only 16-bit and whole-dword sources show a field placement.
    ("cvt_f32_i32", "WORD_0", "UNUSED_PRESERVE", S("WORD_1"), None), ("cvt_f32_i32", "BYTE_1", "UNUSED_PRESERVE", Z("DWORD"), None),
    ("cvt_f32_u32", "DWORD", "UNUSED_PAD", S("BYTE_3"), None), ("cvt_f32_u32", "DWORD", "UNUSED_PAD", Z("WORD_0"), None),
    ("cvt_f32_u32", "DWORD", "UNUSED_PAD", Z("DWORD"), None), ("cvt_f32_u32", "WORD_0", "UNUSED_PRESERVE", S("WORD_1"), None),
    ("cvt_f32_u32", "BYTE_2", "UNUSED_PAD", Z("DWORD"), None),
    ("cvt_i32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, "neg"), None), ("cvt_i32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, "abs"), None),
    ("cvt_i32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, "negabs"), None), ("cvt_i32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, ""), None),
    ("cvt_i32_f32", "WORD_1", "UNUSED_PRESERVE", ("DWORD", False, "neg"), None), ("cvt_i32_f32", "BYTE_0", "UNUSED_PAD", ("DWORD", False, ""), None),
    ("cvt_u32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, "neg"), None), ("cvt_u32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, "abs"), None),
    ("cvt_u32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, "negabs"), None), ("cvt_u32_f32", "DWORD", "UNUSED_PAD", ("DWORD", False, ""), None),
    ("cvt_u32_f32", "BYTE_1", "UNUSED_PRESERVE", ("DWORD", False, "abs"), None), ("cvt_u32_f32", "WORD_0", "UNUSED_PAD", ("DWORD", False, ""), None),
]


def row_word(row, a, b, init=INIT):
    """The result word of a row on the words a and b (and the destination's earlier word)."""
    op, dst_sel, unused, s0, s1 = row
    count, floating, function = OPS[op]
    values = [modified(a, s0[2]) if floating else model_field(a, s0[0], s0[1])]
    if count == 2:
        values.append(model_field(b, s1[0], s1[1]))
    return model_place(function(*values), dst_sel, unused, init)


def row_wrongs(row):
    """{label: wrong row}: one selection, extension, modifier or destination field changed; vacuous ones left out."""
    op, dst_sel, unused, s0, s1 = row
    wrongs = {}
    for index, spec in enumerate((s0, s1)):
        if spec is None:
            continue
        with_spec = lambda new: (op, dst_sel, unused, *(new if i == index else s for i, s in enumerate((s0, s1))))
        if spec[0] != "DWORD":
            wrongs[f"source{index} selector"] = with_spec((OTHER_SEL(spec[0]), spec[1], spec[2]))
            # Extending the lowest set bit's field leaves it where it was: v_ffbl sees no extension.
            if op != "ffbl_b32":
                wrongs[f"source{index} extension"] = with_spec((spec[0], not spec[1], spec[2]))
        if spec[2]:
            wrongs[f"source{index} modifier"] = with_spec((spec[0], spec[1], {"neg": "", "abs": "negabs", "negabs": "abs"}[spec[2]]))
    if dst_sel != "DWORD":
        wrongs["unused"] = (op, dst_sel, "UNUSED_PRESERVE" if unused == "UNUSED_PAD" else "UNUSED_PAD", s0, s1)
        wrongs["destination field"] = (op, OTHER_SEL(dst_sel), unused, s0, s1)
    return wrongs


def row_plan(row):
    wrongs = row_wrongs(row)
    floating = OPS[row[0]][1]

    def shows(item):
        a, b = item
        return {label for label, wrong in wrongs.items() if row_word(wrong, a, b) != row_word(row, a, b)}

    inputs, missing = choose_inputs(shows, wrongs, candidates(floating), BASE_FLOAT if floating else BASE_INT)
    return inputs, wrongs, missing


def row_program(row):
    op, dst_sel, unused, s0, s1 = row

    def token(reg, src):
        sel, sext, mod = src
        text = f"|{reg}|" if "abs" in mod else reg
        return f"-{text}" if "neg" in mod else f"sext({reg})" if sext else text

    body = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46"]
    sels = f" src0_sel:{s0[0]}" + (f" src1_sel:{s1[0]}" if s1 else "")
    operands = token("v18", s0) + (f", {token('v19', s1)}" if s1 else "")
    body.append(f"v_{op}_sdwa v20, {operands} dst_sel:{dst_sel} dst_unused:{unused}{sels}")
    body += [f"v_cvt_f32_ubyte{n}_e32 v{12 + n}, v20" for n in range(4)]
    return with_constants(body)


@functools.cache
def row_plans():
    return [row_plan(row) for row in ROWS]


def check_word_draws(directory, compiler, renderer, backend):
    for index, (row, (inputs, wrongs, _)) in enumerate(zip(ROWS, row_plans())):
        source, shader = directory / f"sdwa_int_word{index}.hlsl", directory / f"sdwa_int_word{index}.cso"
        source.write_text(translate(row_program(row)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        batch = DrawBatch(directory, renderer, backend, shader, "sdwa_int_word")
        shown = set()
        for a, b in inputs:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, a, b, INIT, 0)
            right = row_word(row, a, b)
            batch.add(constants + struct.pack("<4f", *[float((right >> 8 * n) & 255) for n in range(4)]) * 64, "pass",
                      f"SDWA word row {row} gives a result other than {right:#010x} for inputs {a:#x}, {b:#x}")
            for label, wrong in wrongs.items():
                word = row_word(wrong, a, b)
                if label in shown or word == right:
                    continue
                batch.add(constants + struct.pack("<4f", *[float((word >> 8 * n) & 255) for n in range(4)]) * 64, "mismatch",
                          f"A wrong SDWA reference ({label}) escaped detection for {row}")
                shown.add(label)
        batch.flush()


def draw(directory, compiler, renderer, backend):
    check_cmp_draws(directory, compiler, renderer, backend)
    check_word_draws(directory, compiler, renderer, backend)


def controls(directory):
    # Every non-vacuous wrong reference differs from the right result on a chosen input.
    for channels, (inputs, wrongs, missing) in zip(CMP_PROGRAMS, cmp_plans()):
        assert not missing and inputs, (channels, missing)
    for row, (inputs, wrongs, missing) in zip(ROWS, row_plans()):
        assert not missing and inputs, (row, missing)
        body = translate(row_program(row)).split("float4 main", 1)[1]
        # Integer results stay uint words; the float variables are the four byte read-backs and a float result.
        floats = 4 + (1 if row[0].startswith("cvt_f32_") else 0)
        assert body.count("precise float") == floats, (row, body)
    for channels in CMP_PROGRAMS:
        body = translate(cmp_program(channels)).split("float4 main", 1)[1]
        assert body.count("bool cmp") == 4 and "precise float cmp" not in body, body
    # 16-bit comparisons take the low 16 bits of the extended source; 32-bit ones the whole word.
    assert "0xffffu" in translate(cmp_program(CMP_PROGRAMS[4])) and "asint(" in translate(cmp_program(CMP_PROGRAMS[0]))
    # Constants take DWORD only and must be integers; accepted ones compare like registers.
    constant = "v_cmp_lt_i32_sdwa vcc_lo, 5, v18 src0_sel:DWORD src1_sel:WORD_1"
    translate(with_constants(["v_mov_b32_e32 v18, s44", constant]))
    translate(with_constants(["v_cmp_ge_u16_sdwa vcc_lo, -1, 7 src0_sel:DWORD src1_sel:DWORD"]))
    translate(with_constants(["v_ffbl_b32_sdwa v20, 3 dst_sel:BYTE_1 dst_unused:UNUSED_PAD src0_sel:DWORD"]))
    for operation in (
        "v_cmp_lt_i32_sdwa vcc_lo, 5, v18 src0_sel:BYTE_1 src1_sel:DWORD",
        "v_cmp_lt_i32_sdwa vcc_lo, 1.0, v18 src0_sel:DWORD src1_sel:DWORD",
        "v_cmp_lt_i16_sdwa vcc_lo, 0.5, v18 src0_sel:DWORD src1_sel:DWORD",
        "v_cmp_lt_i32_sdwa vcc_lo, v18, v19 src0_sel:WORD_2 src1_sel:DWORD",
        "v_cmp_lt_i32_sdwa vcc_lo, v18, v19 src0_sel:DWORD",
        "v_cmp_lt_i32_sdwa vcc_lo, v18, v19 src0_sel:DWORD src1_sel:DWORD clamp",
        "v_cmp_lt_i32_sdwa vcc_lo, -v18, v19 src0_sel:DWORD src1_sel:DWORD",
        # No F and T forms exist for 16-bit integers, and a comparison that writes EXEC is not lowered.
        "v_cmp_f_i16_sdwa vcc_lo, v18, v19 src0_sel:DWORD src1_sel:DWORD",
        "v_cmp_t_u16_sdwa vcc_lo, v18, v19 src0_sel:DWORD src1_sel:DWORD",
        "v_cmpx_lt_i32_sdwa vcc_lo, v18, v19 src0_sel:DWORD src1_sel:DWORD",
        "v_cmpx_eq_u16_sdwa vcc_lo, v18, v19 src0_sel:DWORD src1_sel:DWORD",
        "v_max_i32_sdwa v20, 5, v19 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:BYTE_1 src1_sel:DWORD",
        "v_max_i32_sdwa v20, 1.0, v19 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
        "v_max_i32_sdwa v20, v18, v19 dst_sel:BYTE_1 dst_unused:UNUSED_SEXT src0_sel:DWORD src1_sel:DWORD",
        "v_min_u32_sdwa v20, v18, v19 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_min_u32_sdwa v20, v18, v19 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD clamp",
        "v_ffbh_u32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
        "v_ffbh_i32_sdwa v20, -v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_f32_i32_sdwa v20, v18 clamp dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_f32_u32_sdwa v20, 1.0 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_f32_u32_sdwa v20, v18 dst_sel:BYTE_1 dst_unused:UNUSED_SEXT src0_sel:DWORD",
        "v_cvt_f32_u32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
        # A binary32 source has no field to select; clamp and omod of an integer result are not established.
        "v_cvt_i32_f32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
        "v_cvt_u32_f32_sdwa v20, v18 clamp dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_u32_f32_sdwa v20, sext(v18) dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_i32_f32_sdwa v20, v18 dst_sel:BYTE_1 dst_unused:UNUSED_SEXT src0_sel:DWORD",
    ):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", operation]))
    # A partial UNUSED_PRESERVE result needs a tracked numeric destination, as for the other SDWA forms.
    for register in ("v0", "v8", "v21"):
        for operation in (f"v_max_u32_sdwa {register}, s44, v19 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0 src1_sel:DWORD",
                          f"v_ffbl_b32_sdwa {register}, s44 dst_sel:BYTE_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0",
                          f"v_cvt_f32_i32_sdwa {register}, s44 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0",
                          f"v_cvt_u32_f32_sdwa {register}, s44 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:DWORD"):
            must_reject(translate, with_constants([operation]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [*((cmp_program(channels), translate) for channels in CMP_PROGRAMS),
            *((row_program(row), translate) for row in ROWS)]
