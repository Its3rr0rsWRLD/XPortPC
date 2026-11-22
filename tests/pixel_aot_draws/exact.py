"""Draw family `exact`: pixel_aot_check.py draw --family exact (forms/valu_exact.py).

v_ldexp_f32, the binary16 fused multiply-adds and the 64-bit integer multiply-adds. Each reference is independent of the
lowering: ldexp and fma are formed as exact Fractions and rounded once to nearest even by fma_mix.fmx_encode (itself
checked against struct's rounding), and the integer results are Python integers. The four constant words reach s44 to
s47 and every channel is one byte of a result word read back through v_cvt_f32_ubyte, so the readback is bit exact
(signed zeros, NaN payloads, subnormals, kept halves). Each program lists the plausible lowering bugs it must catch;
check_exact_models asserts that every bug changes a channel on some set, and the draw shows each as a wrong reference
that must report a mismatch: double rounding through binary32, round toward zero instead of to nearest even, a missing
clamp, flushed subnormals, an exponent read as 16 bits, a lost carry and more."""
from fractions import Fraction
import math
import random
import struct
import subprocess

from .common import half_rtz, half_value, must_reject, translate, ubyte, with_constants, assembly
from .fma_mix import fmx_decode, fmx_encode

M32 = 0xffffffff
WORD = [ubyte(n, 12 + n, "v18", "e32") for n in range(4)]


def word_bytes(word):
    return [float((word >> shift) & 0xff) for shift in (0, 8, 16, 24)]


def pair_bytes(first, second):
    return [float(first & 0xff), float((first >> 8) & 0xff), float(second & 0xff), float((second >> 8) & 0xff)]


def pair(first, second):
    return [ubyte(0, 12, first, "e32"), ubyte(1, 13, first, "e32"), ubyte(0, 14, second, "e32"), ubyte(1, 15, second, "e32")]


def f32_bits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def encode_rtz(x, negative, wide):
    """x rounded toward zero (the round-to-zero bug): the nearest-even result, stepped back when it is larger."""
    bits = fmx_encode(x, negative, wide)
    magnitude = bits & ((1 << 31 if wide else 1 << 15) - 1)
    if magnitude in (0x7f800000, 0x7c00):
        return bits - 1  # the largest finite value of that sign
    if magnitude and abs(fmx_decode(bits, wide)) > abs(Fraction(x)):
        return bits - 1
    return bits


# ------------------------------------------------------------------------------------------------------- ldexp
def ldexp_model(x, e, bug=None):
    """v_ldexp_f32 of the binary32 word x and the signed 32-bit word e, as a binary32 word."""
    e = e - (1 << 32) if e & 0x80000000 else e
    if bug == "exp16":
        e = ((e & 0xffff) ^ 0x8000) - 0x8000
    magnitude = x & 0x7fffffff
    if magnitude > 0x7f800000:
        return x | 0x400000
    if magnitude == 0x7f800000 or magnitude == 0:
        return x
    if bug == "ftz_input" and magnitude < 0x800000:
        return x & 0x80000000
    negative = bool(x >> 31)
    if e > 400 or e < -400:  # 2^-149 * 2^400 overflows and 2^128 * 2^-400 underflows: no rounding question
        return (x & 0x80000000) | (0x7f800000 if e > 0 else 0)
    value = fmx_decode(x, True) * Fraction(2) ** e
    bits = (encode_rtz if bug == "rtz" else fmx_encode)(value, negative, True)
    if bug == "flush" and 0 < bits & 0x7fffffff < 0x800000:
        bits &= 0x80000000
    return bits


def model_ldexp(words, bug):
    return word_bytes(ldexp_model(words[0], words[1], bug))


def model_ldexp_mods(words, bug):
    # v18 = ldexp(-|s44|, -3), then v21 = ldexp(-v18, s45): the two low bytes of each.
    first = ldexp_model((words[0] & 0x7fffffff) ^ (0 if bug == "no_neg" else 0x80000000), (-3) & M32, bug)
    second = ldexp_model(first ^ (0 if bug == "no_neg" else 0x80000000), words[1], bug)
    return [float(first & 0xff), float(first >> 24), float(second & 0xff), float(second >> 24)]


# ------------------------------------------------------------------------------------------------- binary16 fma
def fma16(a, b, c, bug=None):
    """The binary16 fma of three binary16 encodings, rounded once to nearest even (no NaN or infinity sources)."""
    x, y, z = (fmx_decode(h & 0xffff, False) for h in (a, b, c))
    if bug == "flush":
        x, y, z = (0 if 0 < (h & 0x7fff) < 0x400 else v for h, v in zip((a, b, c), (x, y, z)))
    product, total = x * y, x * y + z
    negative_zero = ((a ^ b) & 0x8000) != 0 and (c & 0x8000) != 0 and product == 0 and z == 0
    if bug == "unfused":
        product = fmx_decode(fmx_encode(product, False, True), True)
        total = product + z
    if bug in ("double", "unfused"):
        total = fmx_decode(fmx_encode(total, negative_zero, True), True)
    bits = (encode_rtz if bug == "rtz" else fmx_encode)(total, negative_zero, False)
    if bug == "flush" and 0 < bits & 0x7fff < 0x400:
        bits &= 0x8000
    return bits


def clamp16(bits, bug):
    if bug == "no_clamp":
        return bits
    assert bits != 0x8000
    value = fmx_decode(bits, False)
    return 0 if value < 0 else 0x3c00 if value > 1 else bits


def low(word):
    return word & 0xffff


def high(word):
    return (word >> 16) & 0xffff


def model_fma(words, bug):
    # v18 = s47; v_fma_f16 v18, v19 (= s44), s45, s46: the low half replaced, the high half of s47 kept.
    result = fma16(low(words[0]), low(words[1]), low(words[2]), bug)
    keep = 0 if bug == "high_zero" else words[3] & 0xffff0000
    return word_bytes(keep | result)


def model_fma_sel(words, bug):
    # v18 = s47; v_fma_f16 v18, -v19, |s45|, s46 op_sel:[1,0,1,1] clamp: a = -(high half of s44), b = |low half of s45|,
    # c = high half of s46; the result goes to the high half and the low half of s47 is kept.
    a = (low(words[0]) if bug == "sel_ignored" else high(words[0])) ^ (0 if bug == "no_neg" else 0x8000)
    b = low(words[1]) & (0xffff if bug == "no_abs" else 0x7fff)
    c = low(words[2]) if bug == "sel_ignored" else high(words[2])
    result = clamp16(fma16(a, b, c), bug)
    if bug == "wrong_dst":
        return word_bytes((words[3] & 0xffff0000) | result)
    return word_bytes((words[3] & 0xffff) | (result << 16))


def model_fmac(words, bug):
    # v18 = s46, v19 = s45: v_fmac_f16_e32 v18, s44, v19; v20 = s47: v_fmac_f16_e64 v20, -s44, |v19| clamp.
    first = fma16(low(words[0]), low(words[1]), low(words[2]), bug)
    a = low(words[0]) ^ (0 if bug == "no_neg" else 0x8000)
    b = low(words[1]) & (0xffff if bug == "no_abs" else 0x7fff)
    second = clamp16(fma16(a, b, low(words[3]), bug if bug != "no_clamp" else None), bug)
    return pair_bytes(first, second)


FMAK_K = 0x3956  # 683/1024: 1.5 * K = 1 + 2^-11, a binary16 tie


def model_fmak(words, bug):
    # v19 = s45, v20 = s46: v_fmaak_f16 v18, s44, v19, K and v_fmamk_f16 v21, s44, K, v20.
    first = fma16(low(words[0]), low(words[1]), FMAK_K, bug)
    if bug == "k_swapped":  # fmamk read as S0 * S1 + K
        second = fma16(low(words[0]), low(words[2]), FMAK_K)
    else:
        second = fma16(low(words[0]), FMAK_K, low(words[2]), bug)
    return pair_bytes(first, second)


# ------------------------------------------------------------------------------------------- 64-bit integer mad
def mad64(a, b, c_lo, c_hi, signed, bug=None):
    """(low 64 bits, carry) of a * b + c; signed reads a and b as two's-complement 32-bit integers."""
    c = c_lo | (c_hi << 32)
    if signed and bug != "unsigned":
        a, b = (v - (1 << 32) if v & 0x80000000 else v for v in (a, b))
    if bug == "mul24":  # the v_mad_u32_u24 / v_mad_i32_i24 operand width
        a, b = (v & 0xffffff for v in (a, b))
    product = a * b
    if bug == "mul32":
        product &= M32
    if bug == "no_carry_lo":
        lo = ((product & M32) + c_lo) & M32
        hi = (((product >> 32) & M32) + c_hi) & M32
        return lo | (hi << 32), 0
    total = product + c
    return total & ((1 << 64) - 1), (total >> 64) & 1 if not signed else None


def model_mad_lo(signed):
    return lambda words, bug: word_bytes(mad64(*words, signed, bug)[0] & M32)


def model_mad_hi(signed):
    return lambda words, bug: word_bytes(mad64(*words, signed, bug)[0] >> 32)


def model_mad_carry(words, bug):
    value, carry = mad64(*words, False, bug)
    if bug == "carry_zero":
        carry = 0
    # Channel 0 is the carry (v_cndmask_b32 of vcc_lo), channels 1 to 3 the top three bytes of the high word.
    return [float(carry), *word_bytes(value >> 32)[1:]]


MAD_BODY = ["v_mov_b32_e32 v20, s46", "v_mov_b32_e32 v21, s47"]
MAD_SETS = [
    (M32, M32, M32, M32),  # (2^32 - 1)^2 + 2^64 - 1: low 0, high 0xfffffffe, carry 1
    (0x12345678, 0x9abcdef0, 0x0fedcba9, 0x87654321),
    (0x0000ffff, 0x00010001, M32, 0),  # the low add carries into the high word
    (0x80000000, 0x00000002, 0, 0),  # 2^32 unsigned, -2^32 signed
    (0xfffffffe, 0x00000003, 0x00000005, 0),  # -6 + 5 = -1 signed
    (0x7fffffff, 0x80000001, 0xdeadbeef, 0x00c0ffee),
]

MARKER = 0xa5c31d2e
# (name, body, model, constant sets, bugs, hand-computed channels of one set: (index, channels)).
EXACT_PROGRAMS = (
    ("ldexp", ["v_mov_b32_e32 v19, s44", "v_ldexp_f32 v18, v19, s45", *WORD],
     model_ldexp,
     # A normal scaling; a subnormal scaled up to 2.0; 1.0 scaled to the smallest subnormal; 1.5 * 2^-150 = 0.75 ulp
     # rounds up; 2^-150 is a tie that rounds to +0; 1.5 * 2^-149 is a tie that rounds to 2 ulp; a subnormal source
     # scaled into the normal range; 1.99999988 * 2^-127 rounds up into the smallest normal; -1.0 * 2^128 overflows to
     # -inf; the largest finite value doubled overflows; INT_MIN and INT_MAX exponents; -0 stays -0; a negative quiet NaN
     # keeps its sign and payload; infinity with a huge negative exponent; 3 and 5 ulp halved (ties to even); an exponent
     # whose low 16 bits are 3 (0x10003, a 16-bit reading gives 8.0 instead of infinity); 1.0 * 2^-1 normal.
     [(0x3f800000, 3, 0, 0), (0x00000001, 150, 0, 0), (0x3f800000, (-149) & M32, 0, 0),
      (0x3fc00000, (-150) & M32, 0, 0), (0x3f800000, (-150) & M32, 0, 0), (0x3fc00000, (-149) & M32, 0, 0),
      (0x007fffff, 1, 0, 0), (0x3fffffff, (-127) & M32, 0, 0), (0xbf800000, 128, 0, 0), (0x7f7fffff, 1, 0, 0),
      (0x3f800000, 0x80000000, 0, 0), (0x3f800000, 0x7fffffff, 0, 0), (0x80000000, 100, 0, 0),
      (0xffc12345, 5, 0, 0), (0x7f800000, (-1000) & M32, 0, 0), (0x00000003, M32, 0, 0), (0x80000005, M32, 0, 0),
      (0x3f800000, 0x10003, 0, 0), (0x00400000, 0x80000000, 0, 0), (0xc0490fdb, (-140) & M32, 0, 0)],
     ("rtz", "flush", "exp16", "ftz_input"),
     (7, [0x00, 0x00, 0x80, 0x00])),
    ("ldexp_mods", ["v_mov_b32_e32 v19, s44", "v_ldexp_f32_e64 v18, -|v19|, -3", "v_ldexp_f32 v21, -v18, s45",
                    ubyte(0, 12, "v18", "e32"), ubyte(3, 13, "v18", "e32"), ubyte(0, 14, "v21", "e32"),
                    ubyte(3, 15, "v21", "e32")],
     model_ldexp_mods,
     # -|x| * 2^-3, then its negation scaled by s45: the low and the sign/exponent byte of each result.
     [(0xc0490fdb, (-130) & M32, 0, 0), (0x3fffffff, (-125) & M32, 0, 0), (0x00000007, 2, 0, 0)],
     ("no_neg", "rtz"),
     None),
    ("fma", ["v_mov_b32_e32 v18, s47", "v_mov_b32_e32 v19, s44", "v_fma_f16 v18, v19, s45, s46", *WORD],
     model_fma,
     # The double-rounding case (0x31e9 * 0xb56a + 0x5a91 = 0x5a91 once rounded, 0x5a90 through binary32); 1.5 * K is
     # the tie 1 + 2^-11 and the addend +-2^-24 breaks it (binary32 lands on the tie); a subnormal result from normal
     # sources; 65504 + 16 is the overflow tie (infinity); 3 * 5 - 15 is +0; 2^-48 against 2^-24 and -2^-24 (sticky
     # only); 2^-25 alone is a tie that rounds to +0, 2^-25 + 2^-35 rounds to 2^-24; an ordinary result; -0 * 1 + -0.
     [(0x31e9, 0xb56a, 0x5a91, MARKER), (0x3e00, FMAK_K, 0x0001, 0x6d1e0000), (0xbe00, FMAK_K, 0x8001, 0x93f10000),
      (0x0400, 0x3800, 0x0001, MARKER), (0x7bff, 0x3c00, 0x4c00, MARKER), (0x4200, 0x4500, 0xcb80, 0x8000ffff),
      (0x0001, 0x0001, 0x0001, MARKER), (0x0001, 0x0001, 0x8001, MARKER), (0x0001, 0x3800, 0x0000, MARKER),
      (0x0001, 0x3801, 0x0000, MARKER), (0x4248, 0xc0f1, 0x3555, 0x12345678), (0x8000, 0x3c00, 0x8000, MARKER),
      (0x3c01, 0x3c01, 0xbc02, MARKER)],
     ("double", "rtz", "flush", "high_zero", "unfused"),
     (1, [0x01, 0x3c, 0x1e, 0x6d])),
    ("fma_sel", ["v_mov_b32_e32 v18, s47", "v_mov_b32_e32 v19, s44",
                 "v_fma_f16 v18, -v19, |s45|, s46 op_sel:[1,0,1,1] clamp", *WORD],
     model_fma_sel,
     # a is the negated high half of s44, b the absolute low half of s45, c the high half of s46, over junk halves;
     # the clamped result goes to the high half of v18. -(-2) * 1.5 + 0.25 saturates to 1.0; -(2) * 1.5 + 0.5 to +0;
     # an in-range result that rounds at a tie; a subnormal result kept by the clamp.
     [(0xc0003c00, 0xbe00, 0x34003800, MARKER), (0x4000bc00, 0x3e00, 0x38003400, MARKER),
      (0xbe004000, 0xb956, 0x00015555, MARKER), (0x84001234, 0x3800, 0x00014321, MARKER)],
     ("no_clamp", "sel_ignored", "wrong_dst", "no_neg", "no_abs"),
     (0, [0x2e, 0x1d, 0x00, 0x3c])),
    ("fmac", ["v_mov_b32_e32 v18, s46", "v_mov_b32_e32 v19, s45", "v_fmac_f16_e32 v18, s44, v19",
              "v_mov_b32_e32 v20, s47", "v_fmac_f16_e64 v20, -s44, |v19| clamp", *pair("v18", "v20")],
     model_fmac,
     # The accumulator is the low half of the destination. The double-rounding and tie cases, then the clamped form:
     # -(1.5) * |K| + 2.0 = 0.99951171875 kept, -(x) * |y| + 4.0 saturated, -(-1.5) * |K| - 0.5 kept.
     [(0x3e00, FMAK_K, 0x0001, 0x4000), (0x31e9, 0xb56a, 0x5a91, 0x4400), (0xbe00, 0xb956, 0x8001, 0xb800)],
     ("double", "rtz", "no_clamp", "no_neg", "no_abs"),
     (0, [0x01, 0x3c, 0xff, 0x3b])),
    ("fmak", ["v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46", f"v_fmaak_f16 v18, s44, v19, {FMAK_K:#x}",
              f"v_fmamk_f16 v21, s44, {FMAK_K:#x}, v20", *pair("v18", "v21")],
     model_fmak,
     # fmaak is S0 * S1 + K and fmamk S0 * K + S1: fmamk meets the tie 1.5 * K broken by +-2^-24, fmaak adds a tiny
     # product to K; then the double-rounding case through fmamk-order operands.
     [(0x3e00, 0x0001, 0x0001, 0), (0xbe00, 0x8001, 0x8001, 0), (0x31e9, 0x5a91, 0x5a91, 0)],
     ("double", "rtz", "k_swapped"),
     (0, [0x56, 0x39, 0x01, 0x3c])),
    ("mad_u64_lo", [*MAD_BODY, "v_mad_u64_u32 v[18:19], vcc_lo, s44, s45, v[20:21]", *WORD],
     model_mad_lo(False), MAD_SETS, ("mul24",), (0, [0, 0, 0, 0])),
    ("mad_u64_hi", [*MAD_BODY, "v_mad_u64_u32 v[18:19], s10, s44, s45, v[20:21]",
                    "v_mov_b32_e32 v18, v19", *WORD],
     model_mad_hi(False), MAD_SETS, ("no_carry_lo", "mul32"), (0, [0xfe, 0xff, 0xff, 0xff])),
    ("mad_u64_carry", [*MAD_BODY, "v_mad_u64_u32 v[18:19], vcc_lo, s44, s45, v[20:21]",
                       "v_cndmask_b32_e64 v22, 0, 1, vcc_lo", ubyte(0, 12, "v22", "e32"),
                       ubyte(1, 13, "v19", "e32"), ubyte(2, 14, "v19", "e32"), ubyte(3, 15, "v19", "e32")],
     model_mad_carry, MAD_SETS, ("carry_zero", "no_carry_lo"), (0, [1, 0xff, 0xff, 0xff])),
    ("mad_i64_lo", [*MAD_BODY, "v_mad_i64_i32 v[18:19], s10, s44, s45, v[20:21]", *WORD],
     model_mad_lo(True), MAD_SETS, ("mul24",), (4, [0xff, 0xff, 0xff, 0xff])),
    ("mad_i64_hi", [*MAD_BODY, "v_mad_i64_i32 v[18:19], null, s44, s45, v[20:21]", "v_mov_b32_e32 v18, v19", *WORD],
     model_mad_hi(True), MAD_SETS, ("unsigned", "no_carry_lo", "mul32"), (3, [0xff, 0xff, 0xff, 0xff])),
    ("mad_consts", ["v_mad_u64_u32 v[18:19], null, s44, 7, -2", "v_mad_i64_i32 v[20:21], null, s45, -16, 64",
                    *pair("v18", "v21")],
     lambda words, bug: pair_bytes(mad64(words[0], 7, 0xfffffffe, M32, False, bug)[0],
                                   mad64(words[1], (-16) & M32, 64, 0, True, bug)[0] >> 32),
     # S2 integer inline constants are sign-extended to 64 bits; -16 as S1 is the word 0xfffffff0. The channels are
     # the low bytes of the unsigned low word and of the signed high word.
     [(0x00000001, 0x00000003, 0, 0), (0x12345678, 0xfffffffd, 0, 0)],
     ("unsigned",),
     (0, [0x05, 0x00, 0x00, 0x00])),
)


def check_f64_route() -> None:
    """The binary64 argument of valu_exact.py, numerically: for binary16 a, b, c, the product is exact in binary64 and
    rounding the binary64 sum to binary16 equals rounding the exact sum once."""
    rng = random.Random(16)
    finite = [h for h in range(0x10000) if h & 0x7c00 != 0x7c00]
    tiny = [h for h in finite if h & 0x7fff < 0x0400]
    big = [h for h in finite if h & 0x7fff >= 0x7000]
    for _ in range(60000):
        pool = (finite, tiny, big)
        a, b, c = (rng.choice(pool[rng.randrange(3)]) for _ in range(3))
        x, y, z = (half_value(h) for h in (a, b, c))
        route = x * y + z  # one binary64 rounding: x * y is exact
        assert math.isfinite(route)  # |x * y| < 2^32
        assert fmx_encode(Fraction(route), math.copysign(1, route) < 0, False) == fma16(a, b, c), (hex(a), hex(b), hex(c))


def check_exact_models() -> None:
    """The hand-computed channels, each bug against the sets, and the double-rounding cases the draws rely on."""
    assert (fma16(0x31e9, 0xb56a, 0x5a91), fma16(0x31e9, 0xb56a, 0x5a91, "double")) == (0x5a91, 0x5a90)
    assert Fraction(3, 2) * fmx_decode(FMAK_K, False) == 1 + Fraction(1, 2048)
    assert (fma16(0x3e00, FMAK_K, 0x0001), fma16(0x3e00, FMAK_K, 0x0001, "double")) == (0x3c01, 0x3c00)
    assert ldexp_model(0x3f800000, (-150) & M32) == 0 and ldexp_model(0x3fc00000, (-149) & M32) == 2
    assert ldexp_model(0x3fffffff, (-127) & M32) == 0x00800000 and ldexp_model(0xffc12345, 5) == 0xffc12345
    for name, _, model, sets, bugs, hand in EXACT_PROGRAMS:
        if hand is not None:
            index, channels = hand
            assert model(sets[index], None) == [float(v) for v in channels], (name, model(sets[index], None))
        for bug in bugs:
            assert any(model(words, bug) != model(words, None) for words in sets), (name, bug)
        for words in sets:
            for bug in (None, *bugs):
                assert all(0 <= x <= 255 and x == int(x) for x in model(words, bug)), (name, bug, words)
    check_f64_route()


def check_exact_draws(directory, compiler, renderer, backend):
    check_exact_models()
    case = directory / "exact.case"
    for name, body, model, sets, bugs, _ in EXACT_PROGRAMS:
        source = directory / f"exact_{name}.hlsl"
        shader = directory / f"exact_{name}.cso"
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
                    raise AssertionError(f"An exact-form lowering bug ({bug}) escaped detection in {name} for words {words}")


def check_exact_controls() -> None:
    check_exact_models()
    prefix = ["v_mov_b32_e32 v19, s44", "v_mov_b32_e32 v20, s45", "v_mov_b32_e32 v21, s46"]
    accepted = {
        "ldexp_f32_bits(": ("v_ldexp_f32 v18, v19, v20", "v_ldexp_f32_e64 v18, -|s44|, 0x12345", "v_ldexp_f32 v18, 1.0, -16",
                            "v_ldexp_f32 v18, 0.15915494, s45"),
        "fma_mix_round(": ("v_fma_f16 v18, v19, v20, v21", "v_fma_f16 v18, -1.0, |v20|, 0x3c00 op_sel:[0,1,0,1]",
                           "v_fmac_f16_e32 v19, 1.0, v20", "v_fmac_f16_e64 v19, -s44, |v20| clamp",
                           "v_fmaak_f16 v18, s44, v20, 0x1234", "v_fmamk_f16 v18, v19, 0x1234, v20", "v_fma_f16 v18, 2, v19, -16"),
        "mad_64_32(": ("v_mad_u64_u32 v[18:19], vcc_lo, v19, v20, v[20:21]", "v_mad_i64_i32 v[22:23], s10, s44, 64, -1",
                       "v_mad_u64_u32 v[18:19], null, v19, 0x12345678, s[44:45]"),
    }
    for helper, lines in accepted.items():
        for line in lines:
            source = translate(with_constants([*prefix, line]))
            assert helper in source.split("float4 main")[1], line
    # The binary16 result keeps the other half of the destination, and the lowering never routes it through a float.
    main = translate(with_constants([*prefix, "v_fma_f16 v19, v19, v20, v21", "v_fma_f16 v19, v19, v20, v21 op_sel:[0,0,0,1]"]))
    main = main.split("float4 main")[1]
    assert "(movw" in main and "& 0xffff0000u) | xh" in main and "& 0xffffu) | (xh" in main, main
    rejected = (
        # ldexp: clamp, output modifiers, an e32 spelling, modifiers or a float constant on the integer exponent.
        "v_ldexp_f32 v18, v19, v20 clamp", "v_ldexp_f32 v18, v19, v20 mul:2", "v_ldexp_f32 v18, v19, v20 div:2",
        "v_ldexp_f32_e32 v18, v19, v20", "v_ldexp_f32 v18, v19, -v20", "v_ldexp_f32 v18, v19, |v20|",
        "v_ldexp_f32 v18, v19, 1.0", "v_ldexp_f32 v18, v19, 65", "v_ldexp_f32 v18, v19",
        # binary16 fma: output modifiers, op_sel on a constant or literal, a bad op_sel, VOP2 operand rules, the
        # destination of fmac never written, a 32-bit literal, DPP/SDWA spellings this module does not claim.
        "v_fma_f16 v18, v19, v20, v21 mul:2", "v_fma_f16 v18, 1.0, v20, v21 op_sel:[1,0,0,0]",
        "v_fma_f16 v18, v19, 0x3c00, v21 op_sel:[0,1,0,0]", "v_fma_f16 v18, v19, v20, v21 op_sel:[1,0,0]",
        "v_fma_f16 v18, v19, v20", "v_fma_f16 v18, v19, v20, 0x12345", "v_fma_f16 v18, --v19, v20, v21",
        "v_fmac_f16_e32 v19, v20, s44", "v_fmac_f16_e32 v19, -v20, v21", "v_fmac_f16_e32 v19, v20, v21 clamp",
        "v_fmac_f16_e64 v30, v20, v21", "v_fmac_f16_e64 v19, v20, v21 op_sel:[1,0,0,0]",
        "v_fmaak_f16 v18, v19, s44, 0x1234", "v_fmaak_f16 v18, -v19, v20, 0x1234", "v_fmaak_f16 v18, v19, v20, 1.0",
        "v_fmamk_f16 v18, v19, 0x1234, s44", "v_fmamk_f16 v18, v19, v20, 0x1234", "v_fmac_f16_sdwa v19, v20, v21",
        "v_mad_f16 v18, v19, v20, v21",
        # 64-bit mad: clamp, modifiers, a literal or float constant for S2, a lane-mask SDST of the wrong width.
        "v_mad_u64_u32 v[18:19], vcc_lo, v19, v20, v[20:21] clamp", "v_mad_i64_i32 v[18:19], vcc_lo, -v19, v20, v[20:21]",
        "v_mad_u64_u32 v[18:19], vcc_lo, v19, v20, 0x1234", "v_mad_u64_u32 v[18:19], vcc_lo, v19, v20, 1.0",
        "v_mad_u64_u32 v[18:19], vcc_lo, 1.0, v20, v[20:21]", "v_mad_u64_u32 v[18:19], vcc_lo, v19, v20, 65",
        "v_mad_u64_u32 v[18:19], vcc_lo, v19, v20, v[30:31]",
        # Kept refused: the conversions whose rounding is not established (valu_exact.py docstring).
        "v_cvt_norm_i16_f16_e32 v18, v19", "v_cvt_norm_u16_f16_e32 v18, v19", "v_cvt_norm_i16_f16_e64 v18, -v19",
        "v_cvt_norm_u16_f16_e64 v18, v19 clamp", "v_cvt_pknorm_i16_f32 v18, v19, v20", "v_cvt_pknorm_u16_f32 v18, v19, v20",
        "v_cvt_pknorm_i16_f16 v18, v19, v20", "v_cvt_pknorm_u16_f16 v18, v19, v20", "v_cvt_pk_u8_f32 v18, v19, 0, v20",
        "v_cvt_pk_u8_f32 v18, v19, 1, v20",
    )
    for line in rejected:
        must_reject(translate, with_constants([*prefix, line]))
    # The SDST of v_mad_i64_i32 is not established, so reading it is refused; the unsigned carry is readable.
    for carry in ("vcc_lo", "s10"):
        must_reject(translate, with_constants([*prefix, f"v_mad_i64_i32 v[22:23], {carry}, v19, v20, v[20:21]",
                                               f"v_cndmask_b32_e64 v18, 0, 1, {carry}"]))
        translate(with_constants([*prefix, f"v_mad_u64_u32 v[22:23], {carry}, v19, v20, v[20:21]",
                                  f"v_cndmask_b32_e64 v18, 0, 1, {carry}"]))
    # A sample result is not readable, and its register is not writable, before the wait.
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    for line in ("v_ldexp_f32 v18, v12, 1", "v_ldexp_f32 v12, 1.0, 1", "v_fma_f16 v18, v13, 1.0, 1.0",
                 "v_fma_f16 v12, 1.0, 1.0, 1.0", "v_mad_u64_u32 v[18:19], null, v12, 1, 0",
                 "v_mad_u64_u32 v[12:13], null, 1, 1, 0"):
        must_reject(translate, program[:wait] + [line] + program[wait:])


def controls(directory):
    check_exact_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [*((with_constants(body), translate) for _, body, *_ in EXACT_PROGRAMS)]


draw = check_exact_draws
