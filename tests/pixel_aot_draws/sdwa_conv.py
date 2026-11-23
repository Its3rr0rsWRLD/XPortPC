"""Draw family `sdwa_conv`: pixel_aot_check.py draw --family sdwa_conv.

SDWA forms of the VOP1 conversions and frexp that valu_float_rest lowers: v_frexp_mant_f32, v_frexp_exp_i32_f32,
v_frexp_mant_f16, v_frexp_exp_i16_f16, v_cvt_f16_i16, v_cvt_f16_u16, v_cvt_i16_f16, v_cvt_u16_f16, v_cvt_flr_i32_f32,
v_cvt_rpi_i32_f32, v_cvt_off_f32_i4 and v_sat_pk_u8_i16. Each program is a table row; an independent model below
(Python integers and floats, never the lowering's expressions) gives the result word, and wrong references with one
selector, extension, modifier, unused mode or destination field wrong are derived from the same model. For each row a
few inputs are chosen (greedily, from fixed pools) so that every wrong reference that can differ differs on at least one
of them; the draw runs the right result on every chosen input and each wrong reference once, and the wrong one must
fail. `controls` asserts that coverage and the refusals without a GPU. The result register is read back as four bytes.

Sources: an integer source is the selected field, zero- or sign-extended; a binary16 source is the selected 16 bits with
neg and abs on bit 15; a binary32 source takes DWORD only (neg and abs on the sign bit). A 16-bit result goes to a
BYTE or WORD field (DWORD is refused). Inputs avoid NaN payloads and denormals, whose handling is not what is measured.
"""
import functools
import math
import struct
import subprocess

from .common import DrawBatch, must_reject, translate, with_constants
from .sdwa import M32, S, Z, float_bits, half_bits, half_of, model_field, model_place, signed32
from .sdwa_int import BASE_INT, INIT, OTHER_SEL, candidates, f32_of

signed16 = lambda x: ((x & 0xffff) ^ 0x8000) - 0x8000
INF32 = 0x7f800000


def modified32(word, mod):
    word = word & 0x7fffffff if "abs" in mod else word
    return word ^ 0x80000000 if "neg" in mod else word


def modified16(bits, mod):
    bits = bits & 0x7fff if "abs" in mod else bits
    return bits ^ 0x8000 if "neg" in mod else bits


def saturate_int(x, low, high):
    return low if x <= low else high if x >= high else math.floor(x)


# ---- models ------------------------------------------------------------------------------------------------------
def frexp_mant32(word):
    x = f32_of(word)
    if x == 0 or (word & 0x7fffffff) >= INF32:
        return word
    return float_bits(math.frexp(x)[0])


def frexp_exp32(word):
    x = f32_of(word)
    return 0 if x == 0 or (word & 0x7fffffff) >= INF32 else math.frexp(x)[1] & M32


def frexp_mant16(bits):
    x = half_of(bits)
    return bits if x == 0 or math.isinf(x) else half_bits(math.frexp(x)[0])


def frexp_exp16(bits):
    x = half_of(bits)
    return 0 if x == 0 or math.isinf(x) else math.frexp(x)[1] & 0xffff


def float_to_int(word, half):
    """cvt_flr: floor then saturate; cvt_rpi: floor of x + 0.5 rounded to binary32, then saturate. NaN gives 0."""
    x = f32_of(word)
    if x != x:
        return 0
    if half:
        x = f32_of(float_bits(x + 0.5)) if not math.isinf(x) else x
    return saturate_int(x, -(2 ** 31), 2 ** 31 - 1) & M32


def half_to_int(bits, kind):
    x = half_of(bits)
    if x != x:
        return 0
    if kind == "i16":
        return (-32768 if x <= -32768 else 32767 if x >= 32767 else math.trunc(x)) & 0xffff
    return 0 if x <= 0 else 65535 if x >= 65535 else math.trunc(x)


def sat_pk(word):
    clamp = lambda v: 0 if v < 0 else 255 if v > 255 else v
    return clamp(signed16(word)) | (clamp(signed16(word >> 16)) << 8)


# operation: (source kind, result bits, function of the source value)
OPS = {
    "frexp_mant_f32": ("f32", 32, frexp_mant32),
    "frexp_exp_i32_f32": ("f32", 32, frexp_exp32),
    "cvt_flr_i32_f32": ("f32", 32, lambda w: float_to_int(w, False)),
    "cvt_rpi_i32_f32": ("f32", 32, lambda w: float_to_int(w, True)),
    "frexp_mant_f16": ("f16", 16, frexp_mant16),
    "frexp_exp_i16_f16": ("f16", 16, frexp_exp16),
    "cvt_i16_f16": ("f16", 16, lambda b: half_to_int(b, "i16")),
    "cvt_u16_f16": ("f16", 16, lambda b: half_to_int(b, "u16")),
    "cvt_off_f32_i4": ("int", 32, lambda w: float_bits(float(((w & 15) ^ 8) - 8) * 0.0625)),
    "cvt_f16_i16": ("int", 16, lambda w: half_bits(float(signed16(w)))),
    "cvt_f16_u16": ("int", 16, lambda w: half_bits(float(w & 0xffff))),
    "sat_pk_u8_i16": ("int", 16, sat_pk),
}
# The result of these does not depend on the sign of the source.
SIGN_BLIND = {"frexp_exp_i32_f32", "frexp_exp_i16_f16"}
# Extension wrongs that no input can show: the operation reads too few bits of the field for the extension to reach it.
def extension_vacuous(op, sel):
    return (sel == "DWORD" or op == "cvt_off_f32_i4"
            or (op in ("cvt_f16_i16", "cvt_f16_u16", "sat_pk_u8_i16") and sel.startswith("WORD")))


# (operation, dst_sel, dst_unused, source) with a source spec (selector, sign-extended, modifier).
ROWS = [
    ("frexp_mant_f32", "DWORD", "UNUSED_PAD", Z("DWORD")), ("frexp_mant_f32", "DWORD", "UNUSED_PAD", Z("DWORD", "neg")),
    ("frexp_mant_f32", "DWORD", "UNUSED_PAD", Z("DWORD", "abs")), ("frexp_mant_f32", "DWORD", "UNUSED_PAD", Z("DWORD", "negabs")),
    # A field takes the low bits of the result, which hold no sign: no modifier shows there.
    ("frexp_mant_f32", "WORD_1", "UNUSED_PRESERVE", Z("DWORD")), ("frexp_mant_f32", "BYTE_0", "UNUSED_PAD", Z("DWORD")),
    ("frexp_exp_i32_f32", "DWORD", "UNUSED_PAD", Z("DWORD")), ("frexp_exp_i32_f32", "WORD_1", "UNUSED_PRESERVE", Z("DWORD")),
    ("frexp_exp_i32_f32", "BYTE_1", "UNUSED_PAD", Z("DWORD")),
    ("cvt_flr_i32_f32", "DWORD", "UNUSED_PAD", Z("DWORD")), ("cvt_flr_i32_f32", "DWORD", "UNUSED_PAD", Z("DWORD", "neg")),
    ("cvt_flr_i32_f32", "BYTE_0", "UNUSED_PRESERVE", Z("DWORD", "abs")), ("cvt_flr_i32_f32", "WORD_1", "UNUSED_PAD", Z("DWORD", "negabs")),
    ("cvt_rpi_i32_f32", "DWORD", "UNUSED_PAD", Z("DWORD")), ("cvt_rpi_i32_f32", "DWORD", "UNUSED_PAD", Z("DWORD", "neg")),
    ("cvt_rpi_i32_f32", "BYTE_2", "UNUSED_PRESERVE", Z("DWORD", "abs")), ("cvt_rpi_i32_f32", "WORD_0", "UNUSED_PAD", Z("DWORD", "negabs")),
    ("frexp_mant_f16", "WORD_0", "UNUSED_PAD", Z("WORD_1")), ("frexp_mant_f16", "WORD_1", "UNUSED_PRESERVE", Z("WORD_0", "neg")),
    ("frexp_mant_f16", "WORD_1", "UNUSED_PAD", Z("WORD_1", "negabs")), ("frexp_mant_f16", "BYTE_1", "UNUSED_PRESERVE", Z("WORD_1")), ("frexp_mant_f16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_0", "abs")),
    ("frexp_exp_i16_f16", "WORD_0", "UNUSED_PAD", Z("WORD_1")), ("frexp_exp_i16_f16", "WORD_1", "UNUSED_PRESERVE", Z("WORD_0")),
    ("frexp_exp_i16_f16", "BYTE_2", "UNUSED_PAD", Z("WORD_1")),
    ("cvt_i16_f16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1")), ("cvt_i16_f16", "WORD_1", "UNUSED_PAD", Z("WORD_0", "neg")),
    ("cvt_i16_f16", "BYTE_3", "UNUSED_PRESERVE", Z("WORD_1", "abs")), ("cvt_i16_f16", "BYTE_0", "UNUSED_PAD", Z("WORD_0", "negabs")),
    ("cvt_u16_f16", "WORD_0", "UNUSED_PAD", Z("WORD_1")), ("cvt_u16_f16", "WORD_1", "UNUSED_PRESERVE", Z("WORD_0", "neg")),
    ("cvt_u16_f16", "BYTE_1", "UNUSED_PAD", Z("WORD_1")), ("cvt_u16_f16", "BYTE_0", "UNUSED_PRESERVE", Z("WORD_0", "abs")),
    ("cvt_off_f32_i4", "DWORD", "UNUSED_PAD", S("BYTE_1")), ("cvt_off_f32_i4", "DWORD", "UNUSED_PAD", Z("WORD_1")),
    ("cvt_off_f32_i4", "DWORD", "UNUSED_PAD", S("BYTE_3")), ("cvt_off_f32_i4", "WORD_0", "UNUSED_PRESERVE", Z("DWORD")),
    ("cvt_off_f32_i4", "DWORD", "UNUSED_PAD", Z("DWORD")),
    ("cvt_f16_i16", "WORD_1", "UNUSED_PAD", S("BYTE_1")), ("cvt_f16_i16", "WORD_0", "UNUSED_PRESERVE", S("WORD_1")),
    ("cvt_f16_i16", "WORD_1", "UNUSED_PRESERVE", Z("BYTE_2")), ("cvt_f16_i16", "BYTE_1", "UNUSED_PAD", S("DWORD")),
    ("cvt_f16_i16", "BYTE_0", "UNUSED_PRESERVE", S("BYTE_3")),
    ("cvt_f16_u16", "WORD_1", "UNUSED_PAD", S("BYTE_2")), ("cvt_f16_u16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1")),
    ("cvt_f16_u16", "WORD_0", "UNUSED_PAD", S("BYTE_0")), ("cvt_f16_u16", "BYTE_1", "UNUSED_PRESERVE", Z("DWORD")),
    ("sat_pk_u8_i16", "WORD_0", "UNUSED_PAD", S("BYTE_1")), ("sat_pk_u8_i16", "WORD_1", "UNUSED_PRESERVE", S("DWORD")),
    ("sat_pk_u8_i16", "BYTE_1", "UNUSED_PAD", Z("WORD_0")), ("sat_pk_u8_i16", "WORD_0", "UNUSED_PRESERVE", S("BYTE_3")),
    ("sat_pk_u8_i16", "BYTE_0", "UNUSED_PRESERVE", S("WORD_1")),
]

# ---- inputs ------------------------------------------------------------------------------------------------------
FLOATS = (2.5, -2.5, 100.75, -7.75, 3e9, 5e9, 2147483648.0, -2147483648.0, -3e9, 0.5, -0.5, 6.0, -1.0, 4294967040.0,
          0.0, -0.0, 1.0, 12345.678, 1e-20, -3e38, 1.5, -0.375, 0.1, 7.5, 1e10)
FLOAT_POOL = [float_bits(x) for x in FLOATS] + [INF32, 0xff800000]
# The conversions also see NaN (any NaN converts to 0); frexp passes a NaN payload through and is not given one.
CONVERT_POOL = FLOAT_POOL + [0x7fc00000]
HALVES = (0x3c00, 0x4000, 0xc200, 0x3800, 0x3e00, 0xc100, 0x4400, 0x3400, 0x3d55, 0xc155, 0x4166, 0x3aa3, 0x5640, 0xd640,
          0x7800, 0xf800, 0x7bff, 0xfbff, 0x7c00, 0xfc00, 0x0000, 0x8000, 0x0400, 0x7000, 0x5a3c, 0xe8d0, 0x6c01, 0x3555)
F16_POOL = [(hi << 16) | lo for hi in HALVES for lo in HALVES[::-1]]
INT_POOL = None


def pool_for(op):
    kind = OPS[op][0]
    if kind == "f32":
        return [(w, 0) for w in (CONVERT_POOL if "cvt" in op else FLOAT_POOL)]
    if kind == "f16":
        return [(w, 0) for w in F16_POOL]
    global INT_POOL
    if INT_POOL is None:
        INT_POOL = list(dict.fromkeys(candidates()))
    return INT_POOL


# ---- rows --------------------------------------------------------------------------------------------------------
def row_word(row, a, init=INIT):
    """The result word of a row on the source register word a (and the destination's earlier word)."""
    op, dst_sel, unused, (sel, sext, mod) = row
    kind, _, function = OPS[op]
    if kind == "f32":
        value = modified32(a, mod)
    elif kind == "f16":
        value = modified16(model_field(a, sel, False) & 0xffff, mod)
    else:
        value = model_field(a, sel, sext)
    return model_place(function(value), dst_sel, unused, init)


def row_wrongs(row):
    """{label: wrong row}: one selection, extension, modifier, unused mode or destination field changed."""
    op, dst_sel, unused, (sel, sext, mod) = row
    kind = OPS[op][0]
    wrongs = {}
    if sel != "DWORD":
        wrongs["source selector"] = (op, dst_sel, unused, (OTHER_SEL(sel), sext, mod))
        if kind == "int" and not extension_vacuous(op, sel):
            wrongs["source extension"] = (op, dst_sel, unused, (sel, not sext, mod))
    if mod:
        assert op not in SIGN_BLIND, row
        wrongs["source modifier"] = (op, dst_sel, unused, (sel, sext, {"neg": "", "abs": "negabs", "negabs": "abs"}[mod]))
    if dst_sel != "DWORD":
        wrongs["unused"] = (op, dst_sel, "UNUSED_PRESERVE" if unused == "UNUSED_PAD" else "UNUSED_PAD", row[3])
        wrongs["destination field"] = (op, OTHER_SEL(dst_sel), unused, row[3])
    return wrongs


def row_plan(row):
    """(inputs, wrongs, labels no chosen input shows): the base inputs, then a greedy cover of the wrong references."""
    wrongs = row_wrongs(row)
    pool = pool_for(row[0])
    base = BASE_INT if OPS[row[0]][0] == "int" else pool[:0]
    shows = [{label for label, wrong in wrongs.items() if row_word(wrong, a) != row_word(row, a)} for a, _ in pool]
    chosen = list(base)
    remaining = set(wrongs).difference(*({label for label, wrong in wrongs.items() if row_word(wrong, a) != row_word(row, a)}
                                         for a, _ in base))
    while remaining and len(chosen) < len(base) + 6:
        best = max(range(len(pool)), key=lambda n: (len(shows[n] & remaining), -n))
        if not shows[best] & remaining:
            break
        chosen.append(pool[best])
        remaining -= shows[best]
    if not chosen:
        chosen = [pool[0]]
    return chosen, wrongs, remaining


def row_program(row):
    op, dst_sel, unused, (sel, sext, mod) = row
    reg = "v18"
    token = f"|{reg}|" if "abs" in mod else reg
    token = f"-{token}" if "neg" in mod else f"sext({reg})" if sext else token
    body = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v20, s46",
            f"v_{op}_sdwa v20, {token} dst_sel:{dst_sel} dst_unused:{unused} src0_sel:{sel}"]
    body += [f"v_cvt_f32_ubyte{n}_e32 v{12 + n}, v20" for n in range(4)]
    return with_constants(body)


@functools.cache
def row_plans():
    return [row_plan(row) for row in ROWS]


def draw(directory, compiler, renderer, backend):
    for index, (row, (inputs, wrongs, _)) in enumerate(zip(ROWS, row_plans())):
        source, shader = directory / f"sdwa_conv{index}.hlsl", directory / f"sdwa_conv{index}.cso"
        source.write_text(translate(row_program(row)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        batch = DrawBatch(directory, renderer, backend, shader, "sdwa_conv")
        shown = set()
        for a, _ in inputs:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, a, 0, INIT, 0)
            right = row_word(row, a)
            batch.add(constants + struct.pack("<4f", *[float((right >> 8 * n) & 255) for n in range(4)]) * 64, "pass",
                      f"SDWA conversion row {row} gives a result other than {right:#010x} for input {a:#x}")
            for label, wrong in wrongs.items():
                word = row_word(wrong, a)
                if label in shown or word == right:
                    continue
                batch.add(constants + struct.pack("<4f", *[float((word >> 8 * n) & 255) for n in range(4)]) * 64, "mismatch",
                          f"A wrong SDWA reference ({label}) escaped detection for {row}")
                shown.add(label)
        batch.flush()


def controls(directory):
    # Every operation has rows, and every non-vacuous wrong reference differs from the right result on a chosen input.
    assert {row[0] for row in ROWS} == set(OPS), set(OPS) - {row[0] for row in ROWS}
    for row, (inputs, wrongs, missing) in zip(ROWS, row_plans()):
        assert not missing and inputs, (row, missing)
        body = translate(row_program(row)).split("float4 main", 1)[1]
        # Integer and binary16 results stay uint words: the float variables are the four byte read-backs and a
        # binary32 result of frexp or cvt_off.
        assert body.count("precise float") == 4 + (1 if OPS[row[0]][2] in (frexp_mant32,) or row[0] == "cvt_off_f32_i4" else 0), (row, body)
    # The model against known values, so that a wrong table cannot agree with a wrong lowering.
    assert frexp_mant32(float_bits(-12.0)) == float_bits(-0.75) and frexp_exp32(float_bits(-12.0)) == 4
    assert frexp_mant16(0x4a00) == 0x3a00 and frexp_exp16(0x4a00) == 4 and frexp_exp16(0x0000) == 0
    assert float_to_int(float_bits(-2.5), False) == (-3) & M32 and float_to_int(float_bits(-2.5), True) == (-2) & M32
    assert float_to_int(float_bits(3e9), True) == 0x7fffffff and float_to_int(0x7fc00000, False) == 0
    assert half_to_int(0xc100, "i16") == 0xfffe and half_to_int(0xc100, "u16") == 0 and half_to_int(0x7bff, "i16") == 0x7fff
    assert OPS["cvt_off_f32_i4"][2](0xf9) == float_bits(-0.4375) and OPS["cvt_f16_i16"][2](0xfff0) == half_bits(-16.0)
    assert sat_pk(0x0100ff80) == 0xff00 and sat_pk(0x0050007f) == 0x507f
    # Accepted spellings: a constant source takes DWORD only; modifiers on float sources; sext on integer ones.
    for operation in ("v_frexp_mant_f32_sdwa v20, 8.0 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                      "v_frexp_exp_i32_f32_sdwa v20, -|v18| dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:DWORD",
                      "v_frexp_exp_i16_f16_sdwa v20, -|v18| dst_sel:BYTE_2 dst_unused:UNUSED_PAD src0_sel:WORD_1",
                      "v_cvt_off_f32_i4_sdwa v20, 5 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                      "v_cvt_f16_u16_sdwa v20, sext(v18) dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:BYTE_1",
                      "v_sat_pk_u8_i16_sdwa v20, 300 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:DWORD"):
        translate(with_constants(["v_mov_b32_e32 v18, s44", operation]))
    for operation in (
        # A binary32 source has no field to select, and a constant has no sub-dword selection.
        "v_frexp_mant_f32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
        "v_frexp_exp_i32_f32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:BYTE_0",
        "v_cvt_flr_i32_f32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_cvt_rpi_i32_f32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
        "v_cvt_off_f32_i4_sdwa v20, 5 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:BYTE_1",
        "v_cvt_f16_i16_sdwa v20, 5 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:WORD_1",
        "v_sat_pk_u8_i16_sdwa v20, 5 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:BYTE_0",
        "v_cvt_i16_f16_sdwa v20, 1.0 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:WORD_1",
        "v_frexp_mant_f16_sdwa v20, 1.0 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:WORD_1",
        # A 16-bit result has no whole-dword placement.
        "v_frexp_mant_f16_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_frexp_exp_i16_f16_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_cvt_f16_i16_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_cvt_f16_u16_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_cvt_i16_f16_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_cvt_u16_f16_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_sat_pk_u8_i16_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
        # sext is no float modifier, integer sources take no neg or abs, UNUSED_SEXT and clamp are not lowered,
        # a unary operation takes no second selection.
        "v_cvt_i16_f16_sdwa v20, sext(v18) dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:WORD_1",
        "v_frexp_mant_f32_sdwa v20, sext(v18) dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_flr_i32_f32_sdwa v20, sext(v18) dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_f16_i16_sdwa v20, -v18 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_cvt_off_f32_i4_sdwa v20, |v18| dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:BYTE_0",
        "v_sat_pk_u8_i16_sdwa v20, -v18 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:BYTE_0",
        "v_cvt_flr_i32_f32_sdwa v20, v18 dst_sel:BYTE_1 dst_unused:UNUSED_SEXT src0_sel:DWORD",
        "v_cvt_u16_f16_sdwa v20, v18 dst_sel:BYTE_1 dst_unused:UNUSED_SEXT src0_sel:WORD_0",
        "v_cvt_off_f32_i4_sdwa v20, v18 clamp dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_cvt_rpi_i32_f32_sdwa v20, v18 clamp dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
        "v_frexp_mant_f16_sdwa v20, v18 clamp dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:WORD_0",
        "v_frexp_exp_i32_f32_sdwa v20, v18 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
        "v_cvt_f16_u16_sdwa v20, v18 dst_sel:WORD_0 dst_unused:UNUSED_PAD src0_sel:WORD_0 src1_sel:WORD_0",
        "v_sat_pk_u8_i16_sdwa v20, v18 dst_sel:WORD_0 dst_unused:UNUSED_PAD",
    ):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", operation]))
    # A partial UNUSED_PRESERVE result needs a tracked numeric destination, as for the other SDWA forms.
    for register in ("v0", "v8", "v21"):
        for operation in (f"v_frexp_mant_f32_sdwa {register}, s44 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:DWORD",
                          f"v_cvt_flr_i32_f32_sdwa {register}, s44 dst_sel:BYTE_1 dst_unused:UNUSED_PRESERVE src0_sel:DWORD",
                          f"v_cvt_i16_f16_sdwa {register}, s44 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0",
                          f"v_sat_pk_u8_i16_sdwa {register}, s44 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0"):
            must_reject(translate, with_constants([operation]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(row_program(row), translate) for row in ROWS]
