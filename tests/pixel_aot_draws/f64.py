"""Draw family `f64`: pixel_aot_check.py draw --family f64 (binary64 VALU, tools/pixel_aot_ops/forms/valu_f64.py)."""
from fractions import Fraction
import math
import os
import struct
import subprocess
import sys

from .common import M32, assembly, must_reject, translate, ubyte, with_constants
from .int import INT_PROGRAMS


# binary64 vector arithmetic and conversions (the _f64 VALU forms). A double is a VGPR pair, low word first. Every
# program copies the constant words into registers with v_or_b32 (so no double passes through a binary32 register),
# computes up to seven results, and exports one 32-bit result word per draw: the words are masked with SGPR constants
# (all ones for the selected word, zero otherwise), ORed together, and read byte by byte with v_cvt_f32_ubyteN, so a
# draw compares one half of one result bit for bit and the same shader serves every (result, half). A NaN result
# compares only its exponent and quiet bit (the sign and payload of a generated NaN differ between adapters); a
# result the ISA leaves open, a signed zero out of clamp, is not compared. The references use Python floats (IEEE
# binary64), fractions.Fraction for the exactly rounded fma and ldexp, and struct for binary32. Each program lists
# wrong references (plausible lowering bugs); a bug is drawn once, on the first draw where it changes the word.
# Doubles are optional in D3D12, so these draws go through --check-pixel-case-f64, which exits 77 when the adapter
# lacks DoublePrecisionFloatShaderOps; the draws are then skipped, not failed.
F64_NAN = "nan"
F64_MINN, F64_TINY, F64_MAX = 2.0 ** -1022, 2.0 ** -1074, sys.float_info.max
F64_QNAN = 0x7ff8000000000000


def f64_bits(x):
    return x if isinstance(x, int) else struct.unpack("<Q", struct.pack("<d", x))[0]


def f64_float(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def f64_result(x):
    return F64_NAN if math.isnan(x) else f64_bits(x)


def f64_flush(x):
    return math.copysign(0.0, x) if x != 0 and abs(x) < F64_MINN else x


def f64_sat(result):
    if result is None or result == F64_NAN:
        return 0 if result == F64_NAN else None
    x = f64_float(result)
    if x == 0:
        return None
    return f64_bits(1.0 if x >= 1 else 0.0 if x < 0 else x)


def f64_fma(x, y, z, fused=True):
    if not fused:
        return f64_result(x * y + z)
    if math.isnan(x) or math.isnan(y) or math.isnan(z):
        return F64_NAN
    if math.isinf(x) or math.isinf(y):
        if x == 0 or y == 0:
            return F64_NAN
        p = math.copysign(math.inf, math.copysign(1, x) * math.copysign(1, y))
        return F64_NAN if math.isinf(z) and z != p else f64_bits(p)
    if math.isinf(z):
        return f64_bits(z)
    product = Fraction(x) * Fraction(y)
    total = product + Fraction(z)
    if total == 0:
        negative = product == 0 and z == 0 and math.copysign(1, x) * math.copysign(1, y) < 0 and math.copysign(1, z) < 0
        return f64_bits(-0.0 if negative else 0.0)
    try:
        return f64_bits(float(total))
    except OverflowError:
        return f64_bits(math.inf if total > 0 else -math.inf)


def f64_extreme(x, y, smaller):
    if math.isnan(x) or math.isnan(y):
        return F64_NAN if math.isnan(x) and math.isnan(y) else f64_bits(y if math.isnan(x) else x)
    if x == 0 and y == 0:
        return None
    return f64_bits(min(x, y) if smaller else max(x, y))


def f64_ldexp(x, e, bug=None):
    if math.isnan(x):
        return F64_NAN
    if math.isinf(x) or x == 0:
        return f64_bits(x)
    if bug == "naive":  # two multiplies by 2^(e/2): the first product can already be subnormal
        half = int(e / 2)
        scale = lambda n: 2.0 ** n if n > -1023 else 5e-324 * 2.0 ** (n + 1074)
        try:
            return f64_result(x * scale(half) * scale(e - half))
        except OverflowError:
            return f64_bits(math.copysign(math.inf, x))
    if bug == "range":  # the scale limited to two steps of 2^1023
        e = max(-2046, min(2046, e))
    if e > 3000:
        return f64_bits(math.copysign(math.inf, x))
    if e < -3000:
        return f64_bits(math.copysign(0.0, x))
    try:
        r = float(Fraction(x) * Fraction(2) ** e)
    except OverflowError:
        r = math.copysign(math.inf, x)
    return f64_bits(math.copysign(0.0, x) if r == 0 else r)


def f64_integral(x, mode, bug=None):
    """mode: trunc, floor, ceil or rndne, with the sign of a zero result kept (unless bug == "zero")."""
    if math.isnan(x):
        return F64_NAN
    if math.isinf(x):
        return f64_bits(x)
    if bug == "away" and mode == "rndne":
        r = math.floor(abs(x) + 0.5) * (1 if x >= 0 else -1)
    elif bug == "trunc" and mode == "floor":
        r = math.trunc(x)
    else:
        r = {"trunc": math.trunc, "floor": math.floor, "ceil": math.ceil, "rndne": round}[mode](x)
    return f64_bits(float(r) if r != 0 else (0.0 if bug == "zero" else math.copysign(0.0, x)))


def f64_fract(x, bug=None):
    if math.isnan(x) or math.isinf(x):
        return F64_NAN
    r = x - float(math.floor(x)) if x != 0 else 0.0
    if bug != "unclamped" and r >= 1.0:
        return 0x3fefffffffffffff
    return f64_bits(r)


def f32_of_f64(x, bug=None):
    """The binary32 word of a double: nearest even through struct (a C cast)."""
    if math.isnan(x):
        return F64_NAN
    try:
        r = struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        r = math.copysign(math.inf, x)
    word = struct.unpack("<I", struct.pack("<f", r))[0]
    if bug == "truncate" and abs(r) > abs(x):
        word -= 1  # the next smaller magnitude; an overflow to infinity becomes the largest finite value
    if bug == "flush" and r != 0 and abs(r) < 2.0 ** -126:
        word &= 0x80000000
    if bug == "saturate" and math.isinf(r) and not math.isinf(x):
        word = (word & 0x80000000) | 0x7f7fffff
    return word


def int_of_f64(x, signed, bug=None):
    lo, hi = (-2 ** 31, 2 ** 31 - 1) if signed else (0, 2 ** 32 - 1)
    if math.isnan(x):
        return (0x80000000 if signed else 0) if bug == "nan" else 0
    t = hi if x == math.inf else lo if x == -math.inf else math.trunc(x) if bug != "nearest" else round(x)
    return (t if bug == "wrap" else min(max(t, lo), hi)) & 0xffffffff


def f64_word_float(word, bug=None):
    x = struct.unpack("<f", struct.pack("<I", word))[0]
    if bug == "flush" and x != 0 and abs(x) < 2.0 ** -126:
        x = math.copysign(0.0, x)
    return x


def signed32(w):
    return w - (1 << 32) if w & 0x80000000 else w


# Each ref(a, b, c, e, bug) returns the results: a binary64 or binary32 bit pattern, F64_NAN, or None (not compared).
def ref_add(a, b, c, e, bug=None):
    x, y = f64_float(a), f64_float(b)
    flush = f64_flush if bug == "flush" else (lambda v: v)
    s = lambda p, q: f64_result(flush(flush(p) + flush(q)))
    total = s(x, y)
    three = f64_float(0x40080000) if bug == "literal" else 3.0  # a literal is the high word, not the low word
    return [total, s(x if bug == "neg" else -x, abs(y)), s(x, 1.0), s(-y if bug == "abs" else -abs(y), three), f64_sat(total)]


def ref_mul(a, b, c, e, bug=None):
    x, y = f64_float(a), f64_float(b)
    flush = f64_flush if bug == "flush" else (lambda v: v)
    m = lambda p, q: f64_result(flush(flush(p) * flush(q)))
    return [m(x, y), m(-abs(x), y), m(x, 0.5), m(y, f64_float(0x40100000) if bug == "literal" else 4.0)]


def ref_fma(a, b, c, e, bug=None):
    x, y, z = f64_float(a), f64_float(b), f64_float(c)
    if bug == "flush":
        x, y, z = f64_flush(x), f64_flush(y), f64_flush(z)
    fused = bug != "unfused"
    return [f64_fma(x, y, z, fused), f64_fma(-x, y, abs(z), fused), f64_fma(x, 2.0, 1.0, fused), f64_fma(x, y, z, False)]


def ref_minmax(a, b, c, e, bug=None):
    x, y = f64_float(a), f64_float(b)
    lo, hi = bug != "swap", bug == "swap"
    r = [f64_extreme(x, y, lo), f64_extreme(x, y, hi), f64_extreme(-x, abs(y), lo)]
    if bug == "nan" and (math.isnan(x) or math.isnan(y)):
        r[0] = r[1] = F64_NAN
    m = f64_extreme(x, 0.5, hi)
    return [*r, f64_sat(m)]


def ref_ldexp(a, b, c, e, bug=None):
    x, n = f64_float(a), signed32(e)
    if bug == "flush":
        x = f64_flush(x)
    return [f64_ldexp(x, n, bug), f64_ldexp(-x, n, bug), f64_ldexp(abs(x), -3, bug), f64_ldexp(x, 0x12345, bug)]


def ref_integral(a, b, c, e, bug=None):
    x = f64_float(a)
    i = lambda mode, v: f64_integral(v, mode, bug)
    return [i("floor", x), i("ceil", x), i("trunc", -x), i("rndne", x), f64_fract(x, bug), f64_sat(i("floor", abs(x))),
            f64_fract(-x, bug), i("trunc", x), i("ceil", -abs(x)), f64_sat(i("rndne", -x))]


def ref_to_f32(a, b, c, e, bug=None):
    x = f64_float(a)
    clamped = None if x == 0 else f32_of_f64(0.0 if math.isnan(x) else min(max(x, 0.0), 1.0), bug)
    return [f32_of_f64(x, bug), f32_of_f64(-abs(x), bug), clamped, f32_of_f64(x, bug)]


def ref_from_f32(a, b, c, e, bug=None):
    x = f64_word_float(e, bug)
    return [f64_result(x), f64_result(-abs(x)), f64_sat(f64_result(x)), f64_bits(1.0)]


def ref_from_int(a, b, c, e, bug=None):
    signed = lambda w: float(signed32(w) if bug != "unsigned" else w)
    unsigned = lambda w: float(w if bug != "signed" else signed32(w))
    return [f64_bits(signed(e)), f64_bits(unsigned(e)), f64_sat(f64_bits(signed(e))), f64_bits(5.0),
            f64_sat(f64_bits(unsigned(e)))]


def ref_to_int(a, b, c, e, bug=None):
    x = f64_float(a)
    return [int_of_f64(x, True, bug), int_of_f64(x, False, bug), int_of_f64(-abs(x), True, bug), int_of_f64(-x, False, bug)]


def ref_odd(a, b, c, e, bug=None):
    # v[41:42] = A, v[43:44] = B, v[45:46] = A + B; v[42:43] is (A high, B low) and v[44:45] is (B high, sum low).
    low = lambda v: v & 0xffffffff
    s = f64_float(a) + f64_float(b)
    x = f64_float((b << 32 & 0xffffffffffffffff) | (a >> 32))
    y = f64_float(((f64_bits(s) & 0xffffffff) << 32) | (b >> 32))
    return [f64_result(s), f64_result(x * y)]


def pair(dst, src):
    return [f"v_or_b32_e64 v{dst}, s{src}, 0", f"v_or_b32_e64 v{dst + 1}, s{src + 1}, 0"]


F64_PRELUDE = [*pair(20, 44), *pair(22, 46), *pair(24, 48), "v_or_b32_e64 v26, s50, 0"]
F64_FIRST_MASK = 8  # constant words 0 to 7 are the inputs A (0, 1), B (2, 3), C (4, 5), E (6)
FSET = lambda *args: (*(f64_bits(v) for v in args), *([0] * (4 - len(args))))

F64_PROGRAMS = (
    ("add", [
        "v_add_f64 v[30:31], v[20:21], v[22:23]",
        "v_add_f64 v[32:33], -v[20:21], |s[46:47]|",
        "v_add_f64 v[34:35], v[20:21], 1.0",
        "v_add_f64 v[36:37], -|v[22:23]|, 0x40080000",
        "v_add_f64 v[38:39], v[20:21], v[22:23] clamp",
    ], [2] * 5, ref_add,
     [FSET(0.1, 0.2), FSET(1.0, 2.0 ** -53), FSET(1 + 2.0 ** -52, 2.0 ** -53), FSET(F64_MINN, -(F64_MINN - F64_TINY)),
      FSET(-0.0, -0.0), FSET(3.5, -3.5), FSET(F64_QNAN, 1.0), FSET(F64_MAX, F64_MAX), FSET(-2.0, 1.0)],
     ["flush", "neg", "abs", "literal"]),
    ("mul", [
        "v_mul_f64 v[30:31], v[20:21], v[22:23]",
        "v_mul_f64 v[32:33], -|v[20:21]|, s[46:47]",
        "v_mul_f64 v[34:35], v[20:21], 0.5",
        "v_mul_f64 v[36:37], v[22:23], 0x40100000",
    ], [2] * 4, ref_mul,
     [FSET(0.1, 3.0), FSET(1.5 * F64_MINN, 0.5), FSET(F64_TINY, 0.5), FSET(3 * F64_TINY, 0.5), FSET(F64_MAX, 2.0),
      FSET(-0.0, 5.0), FSET(math.inf, 0.0), FSET(5 * F64_TINY, 2.0 ** 52), FSET(F64_QNAN, 2.0)],
     ["flush", "literal"]),
    ("fma", [
        "v_fma_f64 v[30:31], v[20:21], v[22:23], v[24:25]",
        "v_fma_f64 v[32:33], -v[20:21], v[22:23], |s[48:49]|",
        "v_fma_f64 v[34:35], v[20:21], 2.0, 1.0",
        "v_mul_f64 v[36:37], v[20:21], v[22:23]",
        "v_add_f64 v[36:37], v[36:37], v[24:25]",
    ], [2] * 4, ref_fma,
     [FSET(1 + 2.0 ** -30, 1 + 2.0 ** -30, -(1 + 2.0 ** -29)), FSET(3.0, 0.1, -0.3), FSET(2.0 ** -600, 1.5 * 2.0 ** -473, 0.0),
      FSET(-0.0, 1.0, -0.0), FSET(1.0, -1.0, 1.0), FSET(F64_QNAN, 1.0, 1.0), FSET(math.inf, 0.0, 1.0),
      FSET(F64_MAX, 2.0, -F64_MAX), FSET(3 * F64_TINY, 0.5, F64_TINY)],
     ["unfused", "flush"]),
    ("minmax", [
        "v_min_f64 v[30:31], v[20:21], v[22:23]",
        "v_max_f64 v[32:33], v[20:21], v[22:23]",
        "v_min_f64 v[34:35], -v[20:21], |v[22:23]|",
        "v_max_f64 v[36:37], v[20:21], 0.5 clamp",
    ], [2] * 4, ref_minmax,
     [FSET(1.5, 2.5), FSET(-3.0, 2.0), FSET(F64_QNAN, 4.0), FSET(F64_TINY, 2 * F64_TINY), FSET(-1e300, -1e-300),
      FSET(math.inf, -math.inf), FSET(0.25, F64_QNAN)],
     ["swap", "nan"]),
    ("ldexp", [
        "v_ldexp_f64 v[30:31], v[20:21], v26",
        "v_ldexp_f64 v[32:33], -v[20:21], s50",
        "v_ldexp_f64 v[34:35], |v[20:21]|, -3",
        "v_ldexp_f64 v[36:37], v[20:21], 0x12345",
    ], [2] * 4, ref_ldexp,
     [(f64_bits(1.0), 0, 0, 5), (f64_bits(1.5), 0, 0, (-1074) & 0xffffffff), (f64_bits(F64_MINN), 0, 0, (-1) & 0xffffffff),
      (f64_bits(F64_MINN * (1 + 2.0 ** -52)), 0, 0, (-1) & 0xffffffff), (f64_bits(F64_TINY), 0, 0, 1074),
      (f64_bits(F64_TINY), 0, 0, 2097), (f64_bits(F64_TINY), 0, 0, 2098), (f64_bits(F64_MAX), 0, 0, 1),
      (f64_bits(1.0), 0, 0, (-1075) & 0xffffffff), (f64_bits(1 + 2.0 ** -52), 0, 0, (-1075) & 0xffffffff),
      (f64_bits(float.fromhex('0x1.6454321186ee9p-1021')), 0, 0, (-5) & 0xffffffff),
      (f64_bits(-3.0), 0, 0, (-2000) & 0xffffffff), (f64_bits(-0.0), 0, 0, 100), (f64_bits(F64_QNAN), 0, 0, 3),
      (f64_bits(0.75), 0, 0, 0x80000000), (f64_bits(0.75), 0, 0, 0x7fffffff)],
     ["naive", "range", "flush"]),
    ("integral", [
        "v_floor_f64_e32 v[30:31], v[20:21]",
        "v_ceil_f64_e32 v[32:33], v[20:21]",
        "v_trunc_f64_e64 v[34:35], -v[20:21]",
        "v_rndne_f64_e32 v[36:37], s[44:45]",
        "v_fract_f64_e32 v[38:39], v[20:21]",
        "v_floor_f64_e64 v[40:41], |v[20:21]| clamp",
        "v_fract_f64_e64 v[42:43], -v[20:21]",
        "v_trunc_f64_e32 v[44:45], v[20:21]",
        "v_ceil_f64_e64 v[46:47], -|v[20:21]|",
        "v_rndne_f64_e64 v[48:49], -v[20:21] clamp",
    ], [2] * 10, ref_integral,
     [FSET(2.5), FSET(3.5), FSET(-2.5), FSET(0.5), FSET(-0.5), FSET(0.7), FSET(2.0 ** 52 - 0.5), FSET(2.0 ** 52 + 1.0),
      FSET(-1e-20), FSET(F64_TINY), FSET(-0.0), FSET(F64_QNAN), FSET(math.inf), FSET(1 + 2.0 ** -52),
      FSET(1 - 2.0 ** -53)],
     ["away", "trunc", "unclamped", "zero"]),
    ("to_f32", [
        "v_cvt_f32_f64_e32 v30, v[20:21]",
        "v_cvt_f32_f64_e64 v31, -|v[20:21]|",
        "v_cvt_f32_f64_e64 v32, v[20:21] clamp",
        "v_cvt_f32_f64_e32 v33, s[44:45]",
    ], [1] * 4, ref_to_f32,
     [FSET(1 + 2.0 ** -24), FSET(1 + 3 * 2.0 ** -24), FSET(1 + 2.0 ** -24 + 2.0 ** -50), FSET(1 + 2.0 ** -24 - 2.0 ** -53),
      FSET(3.4028235677973362e38), FSET(3.4028235677973366e38), FSET(1e39), FSET(2.0 ** -149), FSET(1.5 * 2.0 ** -149),
      FSET(2.0 ** -150), FSET(2.0 ** -150 * (1 + 2.0 ** -52)), FSET(2.0 ** -126 - 2.0 ** -151), FSET(0.1), FSET(-1.5),
      FSET(0.5), FSET(F64_TINY), FSET(F64_QNAN)],
     ["truncate", "saturate", "flush"]),
    ("from_f32", [
        "v_cvt_f64_f32_e32 v[30:31], s50",
        "v_cvt_f64_f32_e64 v[32:33], -|v26|",
        "v_cvt_f64_f32_e64 v[34:35], v26 clamp",
        "v_cvt_f64_f32_e32 v[36:37], 1.0",
    ], [2] * 4, ref_from_f32,
     [(0, 0, 0, w) for w in (0x3dcccccd, 0xc0200000, 0x00000001, 0x007fffff, 0x7f800000, 0xff800000, 0x7fc00000, 0x7f7fffff,
                             0x3fc00000, 0x3f400000)],
     ["flush"]),
    ("from_int", [
        "v_cvt_f64_i32_e32 v[30:31], s50",
        "v_cvt_f64_u32_e32 v[32:33], s50",
        "v_cvt_f64_i32_e64 v[34:35], v26 clamp",
        "v_cvt_f64_u32_e32 v[36:37], 5",
        "v_cvt_f64_u32_e64 v[38:39], v26 clamp",
    ], [2] * 5, ref_from_int,
     [(0, 0, 0, w) for w in (0, 1, 0xffffffff, 0x80000000, 0x7fffffff, 0x80000001, 12345678)],
     ["unsigned", "signed"]),
    ("to_int", [
        "v_cvt_i32_f64_e32 v30, v[20:21]",
        "v_cvt_u32_f64_e32 v31, v[20:21]",
        "v_cvt_i32_f64_e64 v32, -|s[44:45]|",
        "v_cvt_u32_f64_e64 v33, -v[20:21]",
    ], [1] * 4, ref_to_int,
     [FSET(2.9), FSET(-2.9), FSET(2147483647.9), FSET(2147483648.0), FSET(-2147483648.5), FSET(-2147483649.0),
      FSET(4294967295.5), FSET(4294967296.0), FSET(1e300), FSET(-1e300), FSET(math.inf), FSET(-math.inf),
      FSET(F64_QNAN), FSET(-0.5), FSET(F64_TINY)],
     ["wrap", "nan", "nearest"]),
    ("odd", [
        *pair(41, 44), *pair(43, 46),
        "v_add_f64 v[45:46], v[41:42], v[43:44]",
        "v_mul_f64 v[47:48], v[42:43], v[44:45]",
    ], [2, 2], ref_odd, [FSET(1.5, 2.25), FSET(0.1, 0.3), FSET(1 / 3, 2e10 / 3)], []),
)


def with_many_constants(body, count):
    """with_constants for up to 60 words: constant words 3 + n are in s44 + n. The load into s[44:47] comes last
    because that range holds the descriptor the other loads read through."""
    program = assembly(False)
    pos = program.index("s_mov_b32 s40, 1")
    program.insert(pos, "s_load_dwordx4 s[44:47], s[20:21], 0x40")
    pos = program.index("s_waitcnt vmcnt(0)")
    loads = [f"s_buffer_load_dwordx4 s[{44 + 4 * g}:{47 + 4 * g}], s[44:47], {12 + 16 * g:#x}"
             for g in reversed(range((count + 3) // 4))]
    program[pos:pos] = [*loads, "s_waitcnt lgkmcnt(0)"]
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = body
    return program


def f64_registers(widths, name):
    if name == "odd":
        return [45, 47]
    first, registers, total = 30, [], 0
    for width in widths:
        registers.append(first + total)
        total += width
    return registers


def f64_program(name, body, widths):
    registers = f64_registers(widths, name)
    tail, count = [], 0
    for register, width in zip(registers, widths):
        for half in range(width):
            tail.append(f"v_and_b32_e32 v{50 + count}, s{44 + F64_FIRST_MASK + count}, v{register + half}")
            count += 1
    tail.append("v_or_b32_e32 v70, v50, v51" if count > 1 else "v_or_b32_e64 v70, v50, 0")
    tail += [f"v_or_b32_e32 v70, v70, v{50 + n}" for n in range(2, count)]
    tail += [ubyte(n, 12 + n, "v70", "e32") for n in range(4)]
    assert count <= 20, count  # v50 to v69 hold the masked words, v70 their OR
    return with_many_constants([*F64_PRELUDE, *body, *tail], F64_FIRST_MASK + count)


def f64_word(result, width, half):
    """(value, mask) of one word of a reference result; None when it is not compared."""
    if result is None:
        return None
    if result == F64_NAN:
        # A generated NaN is compared by its exponent and quiet bit only.
        return (0x7fc00000, 0x7fc00000) if width == 1 else ((0x7ff80000, 0x7ff80000) if half else None)
    return (result >> (32 * half)) & M32, M32


def f64_wrong_word(result, width, half):
    if result is None:
        return None
    if result == F64_NAN:
        return 0x7fc00000 if width == 1 else (0x7ff80000 if half else 0)
    return (result >> (32 * half)) & M32


def f64_constants(inputs, widths, select):
    a, b, c, e = inputs
    words = [a & M32, a >> 32, b & M32, b >> 32, c & M32, c >> 32, e, 0]
    masks, index = [], 0
    for k, width in enumerate(widths):
        for half in range(width):
            masks.append(select[1] if select[0] == (k, half) else 0)
            index += 1
    constants = bytearray(256)
    struct.pack_into(f"<{len(words) + len(masks)}I", constants, 12, *words, *masks)
    return constants


def f64_case(path, constants, word):
    """Write a renderer case: the constant words, then the four bytes of word as the expected float4 of every texel."""
    path.write_bytes(constants + struct.pack("<4f", *[float((word >> (8 * n)) & 0xff) for n in range(4)]) * 64)
    return path


F64_BATCH = 100  # cases per renderer launch; a Windows command line holds about 32 000 characters


def f64_batch(renderer, backend, shader, cases):
    """One launch for a list of (path, expected status, label) cases; returns 77 when the adapter lacks doubles."""
    command = [renderer, backend, "--check-pixel-batch-f64", shader, *(path for path, _, _ in cases)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 77:
        return 77
    actual = [line for line in result.stdout.splitlines() if line.startswith("case=")]
    expected = [f"case={i} status={status}" for i, (_, status, _) in enumerate(cases)]
    if actual != expected:
        bad = [cases[i][2] for i, (want, got) in enumerate(zip(expected, actual)) if want != got] or ["case list"]
        raise AssertionError(f"f64 batch: unexpected status for {bad[:3]}\n{result.stdout}\n{result.stderr}")
    return 0


def check_f64_draws(directory, compiler, renderer, backend):
    """Draws every binary64 program. Returns 77 (CTest skip), having drawn nothing more, when the adapter lacks doubles.

    Every (inputs, result, half) word is one case, and each program's cases go to the renderer in batches of F64_BATCH
    per launch. For each listed lowering bug the first case where its wrong word differs from the right one is added
    with the status mismatch, so a bug that escaped detection shows as a status of pass.
    """
    for name, body, widths, ref, sets, bugs in F64_PROGRAMS:
        source, shader = directory / f"f64_{name}.hlsl", directory / f"f64_{name}.cso"
        source.write_text(translate(f64_program(name, body, widths)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        # The capability skip, forced: the harness reports it as exit 77 whatever the adapter supports.
        if name == "add":
            draw = [renderer, backend, "--check-pixel-case-f64", shader, f64_case(directory / "f64_forced.case", bytes(256), 0)]
            forced = subprocess.run(draw, capture_output=True, text=True, env={**os.environ, "XBOX2WINDOWS_TEST_NO_DOUBLES": "1"})
            if forced.returncode == 77 and not forced.stdout:  # no adapter at all: a skip, reported by pixel_aot_check.py
                raise subprocess.CalledProcessError(77, draw, forced.stdout, forced.stderr)
            assert forced.returncode == 77 and "forced_off" in forced.stdout, (forced.returncode, forced.stdout, forced.stderr)
        todo = {bug: False for bug in (*bugs, "halves")}
        cases = []
        for inputs in sets:
            results = ref(*inputs, None)
            assert len(results) == len(widths), name
            wrong = {bug: ref(*inputs, bug) for bug in bugs}
            for k, width in enumerate(widths):
                for half in range(width):
                    expected = f64_word(results[k], width, half)
                    if expected is None:
                        continue
                    value, select_mask = expected
                    constants = f64_constants(inputs, widths, ((k, half), select_mask))
                    label = f"{name} result {k} half {half} inputs {inputs}"
                    cases.append((f64_case(directory / f"f64_{name}_{len(cases)}.case", constants, value & select_mask), "pass", label))
                    candidates = {bug: f64_wrong_word(wrong[bug][k], width, half) for bug in bugs}
                    if width == 2:
                        candidates["halves"] = f64_wrong_word(results[k], width, 1 - half)
                        if results[k] == F64_NAN:
                            candidates["halves"] = None
                    for bug, word in candidates.items():
                        if todo[bug] or word is None or word & select_mask == value & select_mask:
                            continue
                        todo[bug] = True
                        cases.append((f64_case(directory / f"f64_{name}_{len(cases)}.case", constants, word & select_mask),
                                      "mismatch", f"{name} lowering bug {bug} (result {k}, half {half}, inputs {inputs})"))
        missing = [bug for bug, drawn in todo.items() if not drawn and not (bug == "halves" and name in ("to_f32", "to_int"))]
        assert not missing, (name, missing)
        for start in range(0, len(cases), F64_BATCH):
            if f64_batch(renderer, backend, shader, cases[start:start + F64_BATCH]) == 77:
                print("pixel_aot f64: skipped, the adapter lacks DoublePrecisionFloatShaderOps")
                return 77
    return 0


def check_f64_models() -> None:
    """The references against hand-computed values, and each listed bug against the sets that must expose it."""
    sets = {name: sets for name, _, _, _, sets, _ in F64_PROGRAMS}
    refs = {name: (ref, bugs) for name, _, _, ref, _, bugs in F64_PROGRAMS}
    one, tiny = f64_bits(1.0), f64_bits(F64_TINY)
    # 0.1 + 0.2 rounds up; 1 + 2^-53 is a tie that stays at 1; (1 + 2^-52) + 2^-53 is a tie that rounds up to even.
    assert ref_add(f64_bits(0.1), f64_bits(0.2), 0, 0)[0] == 0x3fd3333333333334
    assert ref_add(one, f64_bits(2.0 ** -53), 0, 0)[0] == one
    assert ref_add(f64_bits(1 + 2.0 ** -52), f64_bits(2.0 ** -53), 0, 0)[0] == one + 2
    assert ref_add(f64_bits(-0.0), f64_bits(-0.0), 0, 0)[0] == 1 << 63 and ref_add(f64_bits(3.5), f64_bits(-3.5), 0, 0)[0] == 0
    # The fused result keeps 2^-60; the separate multiply and add lose it and give 0.
    x = f64_bits(1 + 2.0 ** -30)
    assert ref_fma(x, x, f64_bits(-(1 + 2.0 ** -29)), 0)[:1] + ref_fma(x, x, f64_bits(-(1 + 2.0 ** -29)), 0)[3:] == [f64_bits(2.0 ** -60), 0]
    assert ref_fma(f64_bits(F64_MAX), f64_bits(2.0), f64_bits(-F64_MAX), 0)[0] == f64_bits(F64_MAX)
    # 3 * 2^-1074 / 2 + 2^-1074 is 2.5 units, a tie that goes to the even 2; the separate form rounds 1.5 up first.
    assert ref_fma(3 * tiny, f64_bits(0.5), tiny, 0)[0] == 2 * tiny and ref_fma(3 * tiny, f64_bits(0.5), tiny, 0)[3] == 3 * tiny
    # ldexp: 1.5 * 2^-1074 ties to the even 2; 2^-1075 ties to 0; the smallest subnormal scaled by 2^2097 is 2^1023.
    assert f64_ldexp(1.5, -1074) == 2 * tiny and f64_ldexp(1.0, -1075) == 0 and f64_ldexp(F64_TINY, 2097) == f64_bits(2.0 ** 1023)
    assert f64_ldexp(F64_TINY, 2098) == 0x7ff0000000000000 and f64_ldexp(F64_MAX, 1) == 0x7ff0000000000000
    # Binary32: the tie 1 + 2^-24 goes to 1, 1 + 3 * 2^-24 to 1 + 2^-22; the overflow tie is infinity.
    assert f32_of_f64(1 + 2.0 ** -24) == 0x3f800000 and f32_of_f64(1 + 3 * 2.0 ** -24) == 0x3f800002
    assert f32_of_f64(3.4028235677973366e38) == 0x7f800000 and f32_of_f64(3.4028235677973362e38) == 0x7f7fffff
    assert f32_of_f64(2.0 ** -150) == 0 and f32_of_f64(1.5 * 2.0 ** -149) == 2
    assert f64_fract(-1e-20) == 0x3fefffffffffffff and f64_integral(2.5, "rndne") == f64_bits(2.0)
    assert f64_integral(-0.5, "ceil") == 1 << 63 and f64_integral(-0.5, "floor") == f64_bits(-1.0)
    assert int_of_f64(2147483648.0, True) == 0x7fffffff and int_of_f64(-2147483649.0, True) == 0x80000000
    assert int_of_f64(-5.0, False) == 0 and int_of_f64(math.nan, True) == 0 and int_of_f64(-2.9, True) == 0xfffffffe
    for name, (ref, bugs) in refs.items():
        for bug in (*bugs, None):
            for inputs in sets[name]:
                results = ref(*inputs, bug)
                assert all(r is None or r == F64_NAN or r < 1 << 64 for r in results), (name, bug, inputs)
        for bug in bugs:
            assert any(ref(*inputs, bug) != ref(*inputs, None) for inputs in sets[name]), (name, bug)


def controls(directory):
    # Binary64 vector arithmetic: the models, the lowering, then refusals.
    check_f64_models()
    source = translate(f64_program(*[(n, b, w) for n, b, w, *_ in F64_PROGRAMS if n == "ldexp"][0]))
    for expected in ("uint2 f64_ldexp(", "uint2 u64_bit(", "f64_ldexp(uint2(", "uint2 dalu"):
        assert expected in source, expected
    assert "f64_sat(" not in source and "f64_round(" not in source and "f64_fma(" not in source
    source = translate(f64_program(*[(n, b, w) for n, b, w, *_ in F64_PROGRAMS if n == "add"][0]))
    # neg and abs act on the sign bit of the high word; a literal is the high word with a zero low word; clamp saturates.
    for expected in ("& 0x7fffffffu) ^ 0x80000000u)", "uint2(0u, 1074266112u)", "f64_sat(f64_add(", "uint2 f64_add(", "precise double r"):
        assert expected in source, expected
    assert "f64_mul(" not in source and "asdouble" in source
    assert "double" not in translate(assembly(False)) and "u64_" not in translate(with_constants(INT_PROGRAMS[0][0]))
    fma_source = translate(f64_program(*[(n, b, w) for n, b, w, *_ in F64_PROGRAMS if n == "fma"][0]))
    assert fma_source.count("= f64_fma(") == 3 and fma_source.count("= f64_mul(") == 1 and fma_source.count("= f64_add(") == 1, fma_source
    # Every refused line follows the same prelude (A, B and C in v[20:25], E in v26), and the prelude with an accepted
    # line in its place translates, so each refusal is the line's own.
    refuse = lambda line: must_reject(translate, with_many_constants([*F64_PRELUDE, line], F64_FIRST_MASK))
    translate(with_many_constants([*F64_PRELUDE, "v_add_f64 v[30:31], v[20:21], v[22:23]"], F64_FIRST_MASK))
    for line in ("v_add_f64 v[30:31], v[20:21], v[22:23] mul:2", "v_add_f64 v[30:31], v[20:21], v[22:23] div:2",
                 "v_mul_f64 v[30:31], v[20:21], v[22:23] clamp mul:2", "v_add_f64_e32 v[30:31], v[20:21], v[22:23]",
                 "v_add_f64 v[30:31], v[20:21], 1", "v_add_f64 v[30:31], v[20:21], -1", "v_add_f64 v[30:31], v[20:21], 3.0",
                 "v_add_f64 v[30:31], v[20:21], 0x123456789", "v_add_f64 v[30:31], v[20:21], vcc", "v_add_f64 v[30:31], v[20:21], v22",
                 "v_add_f64 v[30:31], v[20:21], v[90:91]", "v_add_f64 v[30:31], v[20:21], s[90:91]", "v_add_f64 v[30:31], v[20:21], s[47:48]",
                 "v_add_f64 v[30:31], v[20:22], v[22:23]", "v_add_f64 v[30:32], v[20:21], v[22:23]", "v_add_f64 v30, v[20:21], v[22:23]",
                 "v_add_f64 v[30:31], v[20:21]", "v_fma_f64 v[30:31], v[20:21], v[22:23]", "v_add_f64 v[30:31], --v[20:21], v[22:23]",
                 "v_add_f64 v[30:31], |-v[20:21]|, v[22:23]", "v_add_f64 v[30:31], neg(v[20:21]), v[22:23]",
                 "v_ldexp_f64 v[30:31], v[20:21], -v26", "v_ldexp_f64 v[30:31], v[20:21], |v26|", "v_ldexp_f64 v[30:31], v[20:21], v[22:23]",
                 "v_ldexp_f64 v[30:31], v[20:21], v90", "v_ldexp_f64 v[30:31], v[20:21], s90",
                 "v_floor_f64_e32 v[30:31], -v[20:21]", "v_floor_f64_e64 v[30:31], v[20:21] mul:2", "v_floor_f64_e32 v[30:31], v[20:21] clamp",
                 "v_fract_f64_e64 v[30:31], v[20:21] div:2", "v_trunc_f64 v[30:31], v22", "v_rndne_f64 v[30:31], 1",
                 "v_cvt_i32_f64_e64 v30, v[20:21] clamp", "v_cvt_u32_f64_e64 v30, v[20:21] clamp", "v_cvt_f32_f64_e32 v30, v[20:21] clamp",
                 "v_cvt_f32_f64_e64 v[30:31], v[20:21]", "v_cvt_f32_f64_e64 v30, v[20:21] mul:2", "v_cvt_f32_f64_e64 v30, v26",
                 "v_cvt_f64_f32_e32 v[30:31], v[20:21]", "v_cvt_f64_f32_e64 v[30:31], v26 mul:2", "v_cvt_f64_f32_e32 v[30:31], v90",
                 "v_cvt_f64_i32_e64 v[30:31], -v26", "v_cvt_f64_u32_e32 v[30:31], v[20:21]", "v_cvt_f64_i32_e32 v[30:31], v26 clamp",
                 "v_sqrt_f64_e32 v[30:31], v[20:21]", "v_rcp_f64_e32 v[30:31], v[20:21]", "v_rsq_f64_e32 v[30:31], v[20:21]",
                 "v_frexp_mant_f64_e32 v[30:31], v[20:21]", "v_frexp_exp_i32_f64_e32 v30, v[20:21]", "v_fmac_f64_e32 v[30:31], v[20:21], v[22:23]",
                 "v_cmp_lt_f64_e32 vcc_lo, v[20:21], v[22:23]", "v_mad_f64 v[30:31], v[20:21], v[22:23], v[20:21]",
                 "v_mov_b64_e32 v[30:31], v[20:21]", "v_add_f64 v[30:31], v[20:21], v[22:23] clamp mul:2",
                 # Not bit-exact on any lowering here: approximate on gfx10, and DXIL has no double sqrt.
                 "v_sqrt_f64_e64 v[30:31], v[20:21]", "v_rcp_f64_e64 v[30:31], -v[20:21]",
                 "v_div_scale_f64 v[30:31], vcc_lo, v[20:21], v[22:23], v[20:21]",
                 "v_div_fmas_f64 v[30:31], v[20:21], v[22:23], v[24:25]",
                 "v_div_fixup_f64 v[30:31], v[20:21], v[22:23], v[24:25]", "v_trig_preop_f64 v[30:31], v[20:21], v26",
                 "v_cmp_class_f64_e32 vcc_lo, v[20:21], v26", "v_add_f64 v[30:31], v[20:21], 0.15915494309189532 mul:4",
                 "v_cvt_f64_i32_e64 v[30:31], v26 div:2", "v_cvt_i32_f64_e64 v30, v[20:21] mul:2"):
        refuse(line)
    # An odd-aligned pair is accepted (llvm-mc and gfx10 have no alignment rule for VGPR pairs); the pair is two
    # independent halves, so it can mix the halves of two registers written separately.
    translate(with_constants([*pair(21, 44), *pair(23, 46), "v_add_f64 v[31:32], v[21:22], v[23:24]", "v_mul_f64 v[33:34], v[22:23], v[23:24]"]))
    # An outstanding sample: a pair with one half in the sample destination can be neither read nor written until vmcnt(0).
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    held = ["v_or_b32_e64 v11, 5, 0", "v_or_b32_e64 v16, 5, 0"]
    for line in ("v_add_f64 v[30:31], v[12:13], 1.0", "v_add_f64 v[30:31], v[14:15], 1.0", "v_add_f64 v[30:31], v[11:12], 1.0",
                 "v_add_f64 v[30:31], 1.0, v[15:16]", "v_add_f64 v[11:12], 1.0, 1.0", "v_add_f64 v[15:16], 1.0, 1.0",
                 "v_floor_f64_e32 v[13:14], 1.0", "v_cvt_f64_f32_e32 v[15:16], 1.0", "v_cvt_f32_f64_e32 v13, 1.0",
                 "v_cvt_i32_f64_e32 v12, 1.0", "v_cvt_f64_i32_e32 v[30:31], v12", "v_cvt_f32_f64_e32 v30, v[11:12]",
                 "v_ldexp_f64 v[30:31], 1.0, v13", "v_ldexp_f64 v[30:31], v[11:12], 3"):
        must_reject(translate, program[:wait] + held + [line] + program[wait:])
    translate(program[:wait + 1] + ["v_add_f64 v[30:31], v[12:13], v[14:15]"] + program[wait + 1:])
    # A scalar pair read before its load completes.
    program = with_constants(["v_add_f64 v[30:31], 1.0, 1.0"])
    scalar_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    for line in ("v_add_f64 v[30:31], s[44:45], 1.0", "v_cvt_f32_f64_e32 v30, s[46:47]", "v_ldexp_f64 v[30:31], 1.0, s45",
                 "v_cvt_f64_i32_e32 v[30:31], s44"):
        must_reject(translate, program[:scalar_wait] + [line] + program[scalar_wait:])
        translate(program[:scalar_wait + 1] + [line] + program[scalar_wait + 1:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(f64_program(name, body, widths), translate) for name, body, widths, *_ in F64_PROGRAMS]


draw = check_f64_draws
