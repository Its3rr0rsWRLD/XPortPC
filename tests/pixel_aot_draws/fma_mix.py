"""Draw family `fma_mix`: pixel_aot_check.py draw --family fma_mix."""
from fractions import Fraction
import math
import random
import struct
import subprocess

from .common import assembly, half_rtz, half_value, must_reject, translate, ubyte, with_constants


# Mixed-precision fused multiply-add (v_fma_mix_f32, v_fma_mixlo_f16, v_fma_mixhi_f16). The reference is independent of
# the lowering: sources are decoded by struct ("e", "f") into Python floats, which are exact for binary16 and binary32,
# and a*b+c is formed as an exact Fraction and rounded once, to nearest even, by fmx_encode (checked against struct's own
# rounding in check_fma_mix_models). Each draw reads a whole destination word, or two 16-bit results, as bytes through
# v_cvt_f32_ubyte, so the readback is bit exact and shows the kept half of a destination, signed zeros and subnormal
# results. A source operand reaches the instruction from an SGPR (at most two per instruction, the constant bus limit),
# from a vector register copied with v_mov_b32, or as an inline constant or literal. Each program lists the plausible
# lowering bugs to model: unfused (binary32 multiply, then add), double rounding (binary32 fma, then narrowing), wrong
# or ignored half selection, ignored op_sel_hi, ignored neg or abs, kept half zeroed, result written to the other half,
# ignored clamp, flushed binary32 or binary16 subnormals and a flipped zero sign. Each bug must change a channel on some
# set (check_fma_mix_models) and is drawn as a wrong reference that must report a mismatch.
def fmx_source(word, high, select, negate=False, absolute=False, bug=None):
    """A source as a float: the binary16 half that select picks when high (op_sel_hi), else the binary32 word."""
    if bug == "sel_ignored":
        select = 0
    if bug == "wrong_half" and high:
        select ^= 1
    if bug == "hi_ignored":
        high = False
    if bug == "as_half":
        high, select = True, 0
    if bug == "as_half_high":
        high, select = True, 1
    x = half_value(word >> (16 * select)) if high else struct.unpack("<f", struct.pack("<I", word))[0]
    assert math.isfinite(x), hex(word)
    if absolute and bug != "no_abs":
        x = abs(x)
    if negate and bug != "no_neg":
        x = -x
    return x


def fmx_encode(x, negative, wide):
    """The binary32 (wide) or binary16 encoding of the exact Fraction x, rounded to nearest even; a zero takes the
    sign given by negative."""
    sign = (1 << 31 if wide else 1 << 15) if (x < 0 or (x == 0 and negative)) else 0
    if x == 0:
        return sign
    precision, lowest, top = (24, -149, 127) if wide else (11, -24, 15)
    magnitude = abs(Fraction(x))
    e = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if Fraction(2) ** e > magnitude:
        e -= 1
    quantum = max(e - (precision - 1), lowest)
    scaled = magnitude / Fraction(2) ** quantum
    kept = scaled.numerator // scaled.denominator
    rest = scaled - kept
    if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and kept % 2):
        kept += 1
    value = kept * Fraction(2) ** quantum
    if value >= Fraction(2) ** (top + 1):
        return sign | (0x7f800000 if wide else 0x7c00)
    if wide:
        return sign | struct.unpack("<I", struct.pack("<f", float(value)))[0]
    return sign | struct.unpack("<H", struct.pack("<e", float(value)))[0]


def fmx_decode(bits, wide):
    magnitude = bits & ((1 << 31 if wide else 1 << 15) - 1)
    value = struct.unpack("<f", struct.pack("<I", magnitude))[0] if wide else half_value(magnitude)
    assert math.isfinite(value)
    return -Fraction(value) if bits >> (31 if wide else 15) else Fraction(value)


def fmx_fma(a, b, c, wide, bug=None):
    """a*b+c rounded once. A zero result is -0 only when the product and the addend are both -0 (round to nearest);
    an exact cancellation gives +0."""
    product, addend = Fraction(a) * Fraction(b), Fraction(c)
    negative_product = (math.copysign(1, a) < 0) != (math.copysign(1, b) < 0)
    negative_zero = negative_product and math.copysign(1, c) < 0 and product == 0 and addend == 0
    if bug == "unfused":
        rounded = fmx_encode(product, negative_product, True)
        if rounded & 0x7fffffff == 0x7f800000:  # the product overflows binary32: infinity, signed by the product
            return rounded if wide else (rounded >> 16 & 0x8000) | 0x7c00
        product = fmx_decode(rounded, True)
    total = product + addend
    if wide:
        bits = fmx_encode(total, negative_zero, True)
        if bug == "flush" and 0 < bits & 0x7fffffff < 0x800000:
            bits &= 0x80000000
        return bits
    if bug in ("double", "unfused"):
        total = fmx_decode(fmx_encode(total, negative_zero, True), True)
    bits = fmx_encode(total, negative_zero, False)
    if bug == "flush" and 0 < bits & 0x7fff < 0x400:
        bits &= 0x8000
    if bug == "zero_sign" and bits & 0x7fff == 0:
        bits ^= 0x8000
    return bits


def fmx_clamp(bits, wide):
    """Saturate to [0, 1]; the draws never clamp a -0."""
    sign = 1 << 31 if wide else 1 << 15
    assert bits != sign
    value = fmx_decode(bits, wide)
    return 0 if value < 0 else fmx_encode(Fraction(1), False, wide) if value > 1 else bits


def fmx_lo(old, result, bug):
    if bug == "high_zero":
        return result
    if bug == "wrong_dst":
        return (old & 0xffff) | (result << 16)
    return (old & 0xffff0000) | result


def fmx_hi(old, result, bug):
    if bug == "low_zero":
        return result << 16
    if bug == "wrong_dst":
        return (old & 0xffff0000) | result
    return (old & 0xffff) | (result << 16)


def fmx_bytes(word):
    return [float((word >> shift) & 0xff) for shift in (0, 8, 16, 24)]


def fmx_pair_bytes(first, second):
    return [float(first & 0xff), float((first >> 8) & 0xff), float(second & 0xff), float((second >> 8) & 0xff)]


def fmx_word(low, high):
    return (high << 16) | low


FMX_WORD = [ubyte(n, 12 + n, "v18", "e32") for n in range(4)]


def fmx_pair(first, second):
    return [ubyte(0, 12, first, "e32"), ubyte(1, 13, first, "e32"), ubyte(0, 14, second, "e32"), ubyte(1, 15, second, "e32")]


def fmx_f32(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fmx_f16(x):
    return struct.unpack("<H", struct.pack("<e", x))[0]


def fmx_model_lo(words, bug):
    w0, w1, w2, w3 = words
    a, b = fmx_source(w0, True, 0, bug=bug), fmx_source(w1, True, 1, bug=bug)
    return fmx_bytes(fmx_lo(w3, fmx_fma(a, b, fmx_source(w2, False, 0, bug=bug), False, bug), bug))


def fmx_model_hi(words, bug):
    a, b, c = (fmx_source(w, False, 0, bug=bug) for w in words[:3])
    return fmx_bytes(fmx_hi(words[3], fmx_fma(a, b, c, False, bug), bug))


def fmx_model_pair(words, bug):
    w0, w1, w2, w3 = words
    a = fmx_source(w0, False, 0, bug=bug)
    low = fmx_fma(a, fmx_source(w1, False, 0, bug=bug), fmx_source(w3, False, 0, bug=bug), False, bug)
    high = fmx_fma(a, fmx_source(w2, False, 0, bug=bug), fmx_source(w3, False, 0, bug=bug), False, bug)
    return fmx_bytes(fmx_hi(fmx_lo(0, low, bug), high, bug))


def fmx_model_mixed(words, bug):
    w0, w1, w2, _ = words
    a, b, c = fmx_source(w0, True, 0, bug=bug), fmx_source(w1, False, 0, bug=bug), fmx_source(w2, True, 1, bug=bug)
    if bug == "narrow16":
        low = fmx_fma(a, b, c, False)
        return fmx_bytes(fmx_encode(fmx_decode(low, False), low >> 15, True))
    return fmx_bytes(fmx_fma(a, b, c, True, bug))


def fmx_model_wide(words, bug):
    a, b, c = (fmx_source(w, False, 0, bug="as_half_high" if bug == "op_sel_used" else bug) for w in words[:3])
    return fmx_bytes(fmx_fma(a, b, c, True, bug))


def fmx_model_mods(words, bug):
    w0, w1, w2, _ = words
    a = fmx_source(w0, True, 1, True, False, bug)
    b = fmx_source(w1, True, 0, False, True, bug)
    c = fmx_source(w2, True, 1, True, True, bug)
    first = fmx_lo(0, fmx_fma(a, b, c, False, bug), bug)
    a = fmx_source(w0, False, 0, False, True, bug)
    b = fmx_source(w1, True, 1, True, False, bug)
    c = fmx_source(w2, False, 0, False, False, bug)
    return fmx_pair_bytes(first, fmx_lo(0, fmx_fma(a, b, c, False, bug), bug))


def fmx_model_clamp(words, bug):
    a, b, c = (fmx_source(w, True, 0, bug=bug) for w in words[:3])
    sat = (lambda bits, wide: bits) if bug == "no_clamp" else fmx_clamp
    low = fmx_lo(0, sat(fmx_fma(a, b, c, False), False), bug)
    high = fmx_hi(words[3], sat(fmx_fma(a, b, c, False), False), bug)
    wide = sat(fmx_fma(a, b, c, True), True)
    return [float(low & 0xff), float((low >> 8) & 0xff), float(high >> 24), float(wide >> 24)]


def fmx_model_consts1(words, bug):
    w0, w1, w2, _ = words
    a, b, c = fmx_source(w0, False, 0, bug=bug), fmx_source(w1, False, 0, bug=bug), fmx_source(0, True, 0, True, bug=bug)
    first = fmx_lo(0, fmx_fma(a, b, c, False, bug), bug)
    second = fmx_lo(0, fmx_fma(1.0, fmx_source(w2, True, 0, True, bug=bug), 0.5, False, bug), bug)
    return fmx_pair_bytes(first, second)


def fmx_model_consts2(words, bug):
    w0, w1, w2, _ = words
    literal = struct.unpack("<f", struct.pack("<I", 0x3333))[0] if bug == "literal_as_f32" else half_value(0x3333)
    first = fmx_lo(0, fmx_fma(literal, fmx_source(w1, False, 0, bug=bug), fmx_source(w2, False, 0, bug=bug), False, bug), bug)
    a, c = fmx_source(0xc000, True, 0, False, True, bug), fmx_source(0x3c00, True, 0, True, False, bug)
    second = fmx_lo(0, fmx_fma(a, fmx_source(w0, True, 0, bug=bug), c, False, bug), bug)
    return fmx_pair_bytes(first, second)


def fmx_model_round(words, bug):
    a, b, c = (fmx_source(w, False, 0, bug=bug) for w in words[:3])
    return fmx_bytes(fmx_lo(words[3], fmx_fma(a, b, c, False, bug), bug))


MARKER = 0xa5c31d2e
FMX_ONE_12 = fmx_f32(1 + 2.0 ** -12)
FMX_TIE = fmx_f32(1 + 2.0 ** -11)
# (name, body, model, constant sets, bugs, hand-computed channels of one set: (index, channels)). A source of an
# instruction is an SGPR (at most two), a copy of s44 to s46 in v19 to v22, an inline constant or a literal.
FMA_MIX_PROGRAMS = (
    ("lo", ["v_mov_b32_e32 v18, s47", "v_mov_b32_e32 v19, s44",
            "v_fma_mixlo_f16 v18, v19, s45, s46 op_sel:[0,1,0] op_sel_hi:[1,1,0]", *FMX_WORD],
     fmx_model_lo,
     # a is the low half of s44, b the high half of s45 and c the binary32 s46, over junk in the other halves. Double
     # rounding at a tie (the third and fourth sets differ from correct rounding by one unit); a subnormal result
     # from two normal halves; a subnormal source; a result that overflows only if the sum is rounded twice.
     [(fmx_word(0x34c6, 0xc2f1), fmx_word(0x4d2f, 0x3ca1), 0x4222ee78, MARKER),
      (fmx_word(0xbd2c, 0x4a11), fmx_word(0x5555, 0x3246), 0x42e1f1c8, 0x6d1e8f2b),
      (fmx_word(0x0c00, 0x4b00), fmx_word(0x4c00, 0x0c00), 0, 0x93f1c2d4),
      (fmx_word(0x0200, 0x5a00), fmx_word(0x4d00, 0x3400), 0, 0x3c96b45a),
      (fmx_word(0x7bff, 0x1234), fmx_word(0x5678, 0x3c00), 0x417fffff, MARKER)],
     ("double", "wrong_half", "sel_ignored", "hi_ignored", "high_zero", "wrong_dst"),
     (2, [0x01, 0x00, 0xf1, 0x93])),
    ("hi", ["v_mov_b32_e32 v18, s47", "v_mov_b32_e32 v19, s44", "v_fma_mixhi_f16 v18, v19, s45, s46", *FMX_WORD],
     fmx_model_hi,
     # All binary32. 1+2^-12 squared minus 1+2^-11 is 2^-24, which an unfused multiply loses; ties broken by a
     # tiny addend (the binary32 sum would land on the tie), both signs; an ordinary result. The low half is kept.
     [(FMX_ONE_12, FMX_ONE_12, fmx_f32(-(1 + 2.0 ** -11)), 0x1d2ea5c3),
      (FMX_TIE, fmx_f32(1.0), fmx_f32(2.0 ** -40), 0x6d1e8f2b),
      (fmx_f32(-(1 + 2.0 ** -11)), fmx_f32(1.0), fmx_f32(-2.0 ** -40), 0x93f1c2d4),
      (fmx_f32(3.14159274), fmx_f32(-2.71828175), fmx_f32(0.5), 0x5a1b7e69)],
     ("unfused", "double", "low_zero", "wrong_dst", "as_half"),
     (0, [0xc3, 0xa5, 0x01, 0x00])),
    ("pair", ["v_mov_b32_e32 v19, s44", "v_fma_mixlo_f16 v18, v19, s45, s47", "v_fma_mixhi_f16 v18, v19, s46, s47", *FMX_WORD],
     fmx_model_pair,
     # The pattern ACO emits for a pair of results: mixlo then mixhi into one register, binary32 sources. The
     # destination was never written, so the first instruction keeps zero in the high half and the second keeps the
     # low half it just wrote.
     [(fmx_f32(1.5), fmx_f32(2.25), fmx_f32(-0.1), fmx_f32(0.33333334)),
      (FMX_ONE_12, FMX_ONE_12, fmx_f32(1.0), fmx_f32(-(1 + 2.0 ** -11))),
      (FMX_TIE, fmx_f32(1.0), fmx_f32(-1.0), fmx_f32(2.0 ** -40))],
     ("unfused", "double", "wrong_dst", "low_zero"),
     (1, [0x01, 0x00, 0x00, 0x8c])),
    ("mixed", ["v_mov_b32_e32 v19, s45", "v_fma_mix_f32 v18, s44, v19, s46 op_sel:[0,0,1] op_sel_hi:[1,0,1]", *FMX_WORD],
     fmx_model_mixed,
     # The spelling in the corpus: a is the low half of s44, b the binary32 s45 and c the high half of s46. The first
     # set is 2^-30, which an unfused binary32 multiply loses; then an ordinary result with binary32 digits; then a
     # binary32 subnormal result.
     [(fmx_word(0x3c01, 0x4d2f), fmx_f32(1 - 2.0 ** -10 + 2.0 ** -20), fmx_word(0x3555, 0xbc00), MARKER),
      (fmx_word(0x4100, 0xc2f1), fmx_f32(-1.7), fmx_word(0x4d2f, 0x3a00), 0x6d1e8f2b),
      (fmx_word(0x0001, 0x4d2f), fmx_f32(2.0 ** -110), fmx_word(0x3555, 0x0000), MARKER)],
     ("unfused", "sel_ignored", "wrong_half", "hi_ignored", "flush", "narrow16"),
     (0, [0x00, 0x00, 0x80, 0x30])),
    ("wide", ["v_mov_b32_e32 v19, s44", "v_mov_b32_e32 v20, s45", "v_fma_mix_f32 v18, v19, v20, s46 op_sel:[1,1,1]", *FMX_WORD],
     fmx_model_wide,
     # op_sel with op_sel_hi clear does not select a half (RDNA 2 OPSEL 1 = src[31:0]). 2^-24 from a cancelled
     # product; an ordinary result; overflow to infinity; 2^-46 from (1+2^-23)(1-2^-23)-1.
     [(FMX_ONE_12, FMX_ONE_12, fmx_f32(-(1 + 2.0 ** -11)), 0),
      (fmx_f32(3.5), fmx_f32(-2.25), fmx_f32(0.1), 0),
      (fmx_f32(2.0 ** 100), fmx_f32(2.0 ** 100), 0, 0),
      (fmx_f32(1 + 2.0 ** -23), fmx_f32(1 - 2.0 ** -23), fmx_f32(-1.0), 0)],
     ("unfused", "op_sel_used"),
     (0, [0x00, 0x00, 0x80, 0x33])),
    ("mods", ["v_mov_b32_e32 v19, s44", "v_mov_b32_e32 v20, s45",
              "v_fma_mixlo_f16 v18, -v19, |v20|, -|s46| op_sel:[1,0,1] op_sel_hi:[1,1,1]",
              "v_fma_mixlo_f16 v21, |v19|, -v20, s46 op_sel:[0,1,0] op_sel_hi:[0,1,0]", *fmx_pair("v18", "v21")],
     fmx_model_mods,
     # Every source is negated or absolute somewhere, from both halves and from binary32. s44 and s46 are
     # negative binary32 values whose high halves are also moderate binary16 values.
     [(0xc0490fdb, fmx_word(0xb555, 0x4248), 0xbf000000, 0),
      (0x3fa00000, fmx_word(0x3600, 0xc480), 0x40100000, 0),
      (0xbf99999a, fmx_word(0x4900, 0x3c00), 0xc0200000, 0)],
     ("no_neg", "no_abs", "sel_ignored", "wrong_half", "hi_ignored"),
     None),
    ("clamp", ["v_mov_b32_e32 v20, s44", "v_mov_b32_e32 v21, s45", "v_mov_b32_e32 v22, s46", "v_mov_b32_e32 v19, s47",
               "v_fma_mixlo_f16 v18, v20, v21, v22 op_sel_hi:[1,1,1] clamp",
               "v_fma_mixhi_f16 v19, v20, v21, v22 op_sel_hi:[1,1,1] clamp",
               "v_fma_mix_f32 v23, v20, v21, v22 op_sel_hi:[1,1,1] clamp",
               ubyte(0, 12, "v18", "e32"), ubyte(1, 13, "v18", "e32"), ubyte(3, 14, "v19", "e32"), ubyte(3, 15, "v23", "e32")],
     fmx_model_clamp,
     # 3.5 saturates to 1.0, -2.5 to 0, 0.5 is kept and the smallest subnormal is kept. The channels are the two bytes
     # of the low result, the top byte of the high result and the top byte of the binary32 result.
     [(fmx_word(0x4000, 0), fmx_word(0x3e00, 0), fmx_word(0x3800, 0), MARKER),
      (fmx_word(0xc000, 0), fmx_word(0x3e00, 0), fmx_word(0x3800, 0), MARKER),
      (fmx_word(0x3800, 0), fmx_word(0x3a00, 0), fmx_word(0x3000, 0), MARKER),
      (fmx_word(0x0c00, 0), fmx_word(0x0c00, 0), 0, MARKER)],
     ("no_clamp", "wrong_dst"),
     (0, [0x00, 0x3c, 0x3c, 0x3f])),
    ("consts1", ["v_mov_b32_e32 v19, s44", "v_mov_b32_e32 v20, s45",
                 "v_fma_mixlo_f16 v18, v19, v20, neg(0) op_sel_hi:[0,0,1]",
                 "v_fma_mixlo_f16 v21, 1.0, -s46, 0.5 op_sel_hi:[0,1,1]", *fmx_pair("v18", "v21")],
     fmx_model_consts1,
     # neg(0) is -0: -0 + -0 stays -0 and +0 + -0 is +0. Inline 1.0 and 0.5; a negated half.
     [(0, fmx_f32(-1.0), 0x3400, 0), (0, fmx_f32(1.0), 0xc000, 0), (fmx_f32(1.5), fmx_f32(2.5), 0x4200, 0)],
     ("no_neg", "zero_sign"),
     (0, [0x00, 0x80, 0x00, 0x34])),
    ("consts2", ["v_mov_b32_e32 v19, s44", "v_mov_b32_e32 v20, s45",
                 "v_fma_mixlo_f16 v18, 0x3333, v20, s46 op_sel_hi:[1,0,0]",
                 "v_fma_mixlo_f16 v21, |-2.0|, v19, neg(1.0) op_sel_hi:[1,1,1]", *fmx_pair("v18", "v21")],
     fmx_model_consts2,
     # A literal is the low binary16 half (0x3333 = 0.2); |-2.0| and neg(1.0) constants with modifiers.
     [(fmx_word(0x4600, 0x4d2f), fmx_f32(1.5), fmx_f32(-0.25), 0), (fmx_word(0xb800, 0x3555), fmx_f32(-3.0), fmx_f32(0.75), 0)],
     ("literal_as_f32", "no_abs", "no_neg"),
     None),
    ("round", ["v_mov_b32_e32 v18, s47", "v_mov_b32_e32 v19, s44", "v_fma_mixlo_f16 v18, v19, s45, s46", *FMX_WORD],
     fmx_model_round,
     # Binary32 sources, one rounding to binary16: a tie plus a tiny addend, both signs; the same at the smallest
     # subnormal; just below the overflow tie; a subnormal tie that rounds up into the smallest normal; underflow to
     # -0; an exact cancellation, which is +0; an unfused multiply loses the cancelled product.
     [(FMX_TIE, fmx_f32(1.0), fmx_f32(2.0 ** -40), MARKER),
      (fmx_f32(-(1 + 2.0 ** -11)), fmx_f32(1.0), fmx_f32(-2.0 ** -40), MARKER),
      (fmx_f32(2.0 ** -25), fmx_f32(1.0), fmx_f32(2.0 ** -60), 0x6d1e8f2b),
      (fmx_f32(65520.0), fmx_f32(1.0), fmx_f32(-2.0 ** -30), MARKER),
      (fmx_f32(1023.5 * 2.0 ** -24), fmx_f32(1.0), 0, 0x93f1c2d4),
      (fmx_f32(-2.0 ** -30), fmx_f32(2.0 ** -30), 0, MARKER),
      (fmx_f32(3.0), fmx_f32(5.0), fmx_f32(-15.0), 0x8000ffff),
      (FMX_ONE_12, FMX_ONE_12, fmx_f32(-(1 + 2.0 ** -11)), MARKER)],
     ("double", "unfused", "flush", "zero_sign"),
     (0, [0x01, 0x3c, 0xc3, 0xa5])),
)


def check_fma_mix_models() -> None:
    """The reference against struct's rounding, the hand-computed channels, and each bug against the sets."""
    rng = random.Random(7)
    for _ in range(4000):
        x = rng.choice((rng.uniform(-70000, 70000), math.ldexp(rng.uniform(-1, 1), rng.randint(-40, 16)),
                        math.ldexp(rng.getrandbits(52), rng.randint(-90, -30))))
        try:
            half = struct.unpack("<H", struct.pack("<e", x))[0]
        except OverflowError:
            half = 0xfc00 if x < 0 else 0x7c00
        assert fmx_encode(Fraction(x), x < 0, False) == half, x
        try:
            single = struct.unpack("<I", struct.pack("<f", x))[0]
        except OverflowError:
            single = None
        assert single is None or fmx_encode(Fraction(x), x < 0, True) == single, x
    # Fused, double-rounded and unfused results of a case from the search described above (all binary16 sources).
    a, b, c = half_value(0x31e9), half_value(0xb56a), half_value(0x5a91)
    assert (fmx_fma(a, b, c, False), fmx_fma(a, b, c, False, "double")) == (0x5a91, 0x5a90)
    for name, _, model, sets, bugs, hand in FMA_MIX_PROGRAMS:
        if hand is not None:
            index, channels = hand
            assert model(sets[index], None) == [float(v) for v in channels], (name, model(sets[index], None))
        for bug in bugs:
            assert any(model(words, bug) != model(words, None) for words in sets), (name, bug)
        for words in sets:
            for bug in (None, *bugs):
                assert all(0 <= x <= 255 and x == int(x) for x in model(words, bug)), (name, bug, words)


def check_fma_mix_draws(directory, compiler, renderer, backend):
    check_fma_mix_models()
    case = directory / "fma_mix.case"
    for name, body, model, sets, bugs, _ in FMA_MIX_PROGRAMS:
        source = directory / f"fma_mix_{name}.hlsl"
        shader = directory / f"fma_mix_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = model(words, None)
            for x in expected:
                assert half_rtz(x) == x, x
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for bug in bugs:
                wrong = model(words, bug)
                if wrong == expected:
                    continue
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A mixed-precision fma lowering bug ({bug}) escaped detection in {name} for words {words}")


def check_fma_mix_controls() -> None:
    prefix = ["v_mov_b32_e32 v19, s44", "v_mov_b32_e32 v20, s45", "v_mov_b32_e32 v21, s46"]
    accepted = (
        "v_fma_mixlo_f16 v18, v19, v20, v21", "v_fma_mixhi_f16_e64 v18, v19, v20, v21 clamp",
        "v_fma_mix_f32 v18, v19, v20, v21 op_sel:[1,1,1]", "v_fma_mix_f32 v18, -|v19|, v20, neg(0) op_sel_hi:[1,0,1]",
        "v_fma_mixlo_f16 v18, 0x3333, v20, v21 op_sel_hi:[1,0,0]", "v_fma_mixlo_f16 v18, v19, 0.15915494, v21 op_sel_hi:[0,1,0]",
    )
    for line in accepted:
        source = translate(with_constants([*prefix, line]))
        assert "fma_mix_round(" in source and source.count("uint fma_mix_round(") == 1, line
    main = translate(with_constants([*prefix, "v_fma_mixlo_f16 v18, v19, v20, v21", "v_fma_mixhi_f16 v18, v19, v20, v21"])).split("float4 main")[1]
    assert "asfloat(0u | fma_mix_round(" in main, main
    assert "(asuint(alu" in main and " & 0xffffu) | (fma_mix_round(" in main, main
    rejected = (
        # Output modifiers, DPP and SDWA are not part of the form.
        "v_fma_mixlo_f16 v18, v19, v20, v21 mul:2", "v_fma_mixlo_f16 v18, v19, v20, v21 div:2",
        "v_fma_mix_f32 v18, v19, v20, v21 row_shl:1", "v_fma_mixlo_f16_dpp v18, v19, v20, v21 row_shl:1",
        "v_fma_mixhi_f16_sdwa v18, v19, v20, v21 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0",
        "v_fma_mix_f32_e32 v18, v19, v20, v21",
        # LLVM prints only the low 16 bits of a literal: a binary32 literal or a high half is not in the text.
        "v_fma_mixlo_f16 v18, 0x3333, v20, v21", "v_fma_mixlo_f16 v18, 0x3333, v20, v21 op_sel:[1,0,0] op_sel_hi:[1,0,0]",
        # Integer inline constants and an inline constant under a high-half select are not established; 1/(2*pi) is
        # a different number in binary32.
        "v_fma_mixlo_f16 v18, 3, v20, v21 op_sel_hi:[1,0,0]", "v_fma_mixlo_f16 v18, -1, v20, v21 op_sel_hi:[1,0,0]",
        "v_fma_mixlo_f16 v18, 1.0, v20, v21 op_sel:[1,0,0] op_sel_hi:[1,0,0]", "v_fma_mixlo_f16 v18, 0.15915494, v20, v21",
        # Malformed selects and operands.
        "v_fma_mixlo_f16 v18, v19, v20, v21 op_sel:[0,0,0,1]", "v_fma_mixlo_f16 v18, v19, v20, v21 op_sel_hi:[2,0,0]",
        "v_fma_mixlo_f16 v18, v19, v20, v21 clamp op_sel:[0,0,1]", "v_fma_mixlo_f16 v18, v19, v20",
        "v_fma_mixlo_f16 v18, --v19, v20, v21", "v_fma_mixlo_f16 v18, v19, v20, vcc_lo",
        # A source that was never written.
        "v_fma_mixlo_f16 v18, v19, v20, v30", "v_fma_mix_f32 v18, s70, v20, v21",
    )
    for line in rejected:
        must_reject(translate, with_constants([*prefix, line]))
    # A sample result is not readable, and its register is not writable, before the wait.
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    for line in ("v_fma_mix_f32 v18, v12, 1.0, 0", "v_fma_mixlo_f16 v18, 1.0, 1.0, v13 op_sel_hi:[1,1,1]", "v_fma_mixlo_f16 v12, 1.0, 1.0, 0.5 op_sel_hi:[1,1,1]"):
        must_reject(translate, program[:wait] + [line] + program[wait:])


def controls(directory):
    check_fma_mix_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for _, body, *_ in FMA_MIX_PROGRAMS),
    ]


draw = check_fma_mix_draws
