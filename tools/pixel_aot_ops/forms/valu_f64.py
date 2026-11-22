"""Binary64 vector forms (VOP1, VOP3): add, mul, fma, min, max, ldexp, the rounding forms and the conversions.

A binary64 value is a VGPR (or SGPR) pair, low word first. Each half is tracked as a ("uint", expr) word, like every
other raw word (registers.py), so the bits of a double never pass through a float-typed HLSL value: a form reads its
operands as uint2(low, high), a helper below rebuilds the double with asdouble(low, high) only around a real double
operation and splits the result again with asuint(r, lo, hi), and the destination halves are ("uint", "daluN.x") and
("uint", "daluN.y"). neg and abs act on bit 31 of the high word, as integer operations.

Which operations use the adapter's double arithmetic. Doubles are optional in D3D12: DoublePrecisionFloatShaderOps
"Specifies whether double types are allowed for shader operations ... The supported operations are equivalent to
Direct3D 11's ExtendedDoublesShaderInstructions", which covers "the fma intrinsic function and other extended doubles
instructions (DDIV and DRCP)" (learn.microsoft.com, D3D12_FEATURE_DATA_D3D12_OPTIONS and
D3D11_FEATURE_DATA_D3D11_OPTIONS). The Direct3D floating-point rules say "Double-precision instructions follow IEEE 754R
behavior requirements" and "Support for generation of denormalized values is required for double-precision data (no
flush-to-zero behavior). Likewise, instructions don't read denormalized data as a signed zero, they honor the denorm
value." (learn.microsoft.com/windows/win32/direct3d11/floating-point-rules, 64-bit section). IEEE 754 makes add,
multiply and fused multiply-add correctly rounded, and gfx10 keeps binary64 denormals by default, so v_add_f64,
v_mul_f64 and v_fma_f64 use HLSL +, * and fma() on doubles, and v_min_f64 and v_max_f64 HLSL min and max (IEEE minNum
and maxNum: a NaN operand gives the other operand, as gfx10 does with IEEE mode off, the graphics default). The
32-bit to binary64 integer conversions are exact for every input, so they are double(asint(w)) and double(w). Nothing
else relies on the adapter's rounding: DXIL has no floor, ceil, trunc or round on doubles (Round_* is half and float
only), and HLSL casts are undefined out of range, so the rounding forms, v_ldexp_f64, v_cvt_f32_f64, v_cvt_f64_f32 and
the conversions to integers are integer operations on the bit pattern (ldexp uses one exact or once-rounded multiply,
see f64_ldexp).

Refused, each with a control (tests/pixel_aot_draws/f64.py): v_sqrt_f64, v_rcp_f64 and v_rsq_f64 (gfx10 computes them
to about 1 ulp, not correctly rounded, and DXIL has no double sqrt at all, so no lowering is bit-exact), the division
sequence v_div_scale_f64, v_div_fmas_f64 and v_div_fixup_f64 (built on v_rcp_f64; DDIV is not the same rounding),
v_frexp_*, v_trig_preop_f64, v_fmac_f64 and v_mad_f64 (not gfx10 forms), v_cmp_*_f64, output modifiers (mul:N, div:N),
integer inline constants other than 0, and clamp on the integer conversions.
"""
import re
import struct

from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import registers, sgpr_pair, vector_u32

F64_HELPERS = {
    "u64_bit": "uint2 u64_bit(uint k) {\n    if (k >= 32u) return uint2(0u, 1u << (k - 32u));\n    return uint2(1u << k, 0u);\n}",
    "u64_low": ("uint2 u64_low(uint k) {\n    if (k >= 32u) return uint2(0xffffffffu, (1u << (k - 32u)) - 1u);\n"
                "    return uint2((1u << k) - 1u, 0u);\n}"),
    "u64_shr": ("uint2 u64_shr(uint2 v, uint s) {\n    if (s == 0u) return v;\n    if (s >= 32u) return uint2(v.y >> (s - 32u), 0u);\n"
                "    return uint2((v.x >> s) | (v.y << (32u - s)), v.y >> s);\n}"),
    "u64_less": "bool u64_less(uint2 a, uint2 b) {\n    return a.y < b.y || (a.y == b.y && a.x < b.x);\n}",
    "u64_add": "uint2 u64_add(uint2 a, uint2 b) {\n    uint lo = a.x + b.x;\n    return uint2(lo, a.y + b.y + (lo < a.x ? 1u : 0u));\n}",
    "f64_add": ("uint2 f64_add(uint2 a, uint2 b) {\n    precise double r = asdouble(a.x, a.y) + asdouble(b.x, b.y);\n"
                "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    "f64_mul": ("uint2 f64_mul(uint2 a, uint2 b) {\n    precise double r = asdouble(a.x, a.y) * asdouble(b.x, b.y);\n"
                "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    "f64_fma": ("uint2 f64_fma(uint2 a, uint2 b, uint2 c) {\n    precise double r = fma(asdouble(a.x, a.y), asdouble(b.x, b.y), asdouble(c.x, c.y));\n"
                "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    "f64_min": ("uint2 f64_min(uint2 a, uint2 b) {\n    precise double r = min(asdouble(a.x, a.y), asdouble(b.x, b.y));\n"
                "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    "f64_max": ("uint2 f64_max(uint2 a, uint2 b) {\n    precise double r = max(asdouble(a.x, a.y), asdouble(b.x, b.y));\n"
                "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    # The VOP3 clamp bit: saturate to [0, 1]; a NaN gives 0 as HLSL max returns the other operand.
    "f64_sat": ("uint2 f64_sat(uint2 v) {\n    precise double r = min(max(asdouble(v.x, v.y), asdouble(0u, 0u)), asdouble(0u, 0x3ff00000u));\n"
                "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    "f64_from_i32": "uint2 f64_from_i32(uint w) {\n    precise double r = double(asint(w));\n    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}",
    "f64_from_u32": "uint2 f64_from_u32(uint w) {\n    precise double r = double(w);\n    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}",
    # v_trunc/floor/ceil/rndne_f64 (mode 0..3) on the bit pattern. For biased exponent ex in [1023, 1074] the low
    # f = 1075 - ex bits of the pattern are the fraction, and adding 2^f to the cleared pattern adds exactly 1 to the
    # magnitude, carrying into the exponent when needed. Below 1.0 the result is 0 or 1.0 with the sign kept; at 2^52 and
    # above, and for infinities and NaNs, the value is returned unchanged. Round to nearest even looks at bit f.
    "f64_round": (
        "uint2 f64_round(uint2 v, uint mode) {\n"
        "    uint ex = (v.y >> 20) & 0x7ffu;\n"
        "    bool neg = (v.y >> 31) != 0u;\n"
        "    if (ex >= 1075u) return v;\n"
        "    if (ex < 1023u) {\n"
        "        bool nonzero = ((v.y & 0x7fffffffu) | v.x) != 0u;\n"
        "        bool up = false;\n"
        "        if (mode == 1u) up = neg && nonzero;\n"
        "        else if (mode == 2u) up = !neg && nonzero;\n"
        "        else if (mode == 3u) up = ex == 1022u && (((v.y & 0xfffffu) | v.x) != 0u);\n"
        "        return uint2(0u, (v.y & 0x80000000u) | (up ? 0x3ff00000u : 0u));\n"
        "    }\n"
        "    uint f = 1075u - ex;\n"
        "    uint2 mask = u64_low(f);\n"
        "    uint2 rest = uint2(v.x & mask.x, v.y & mask.y);\n"
        "    uint2 whole = uint2(v.x & ~mask.x, v.y & ~mask.y);\n"
        "    bool inexact = (rest.x | rest.y) != 0u;\n"
        "    bool bump = false;\n"
        "    if (mode == 1u) bump = neg && inexact;\n"
        "    else if (mode == 2u) bump = !neg && inexact;\n"
        "    else if (mode == 3u) {\n"
        "        uint2 mid = u64_bit(f - 1u);\n"
        "        bool tie = rest.x == mid.x && rest.y == mid.y;\n"
        "        bump = u64_less(mid, rest) || (tie && (u64_shr(v, f).x & 1u) != 0u);\n"
        "    }\n"
        "    if (bump) return u64_add(whole, u64_bit(f));\n"
        "    return whole;\n"
        "}"),
    # v_fract_f64: x - floor(x) in double arithmetic (exact below 1.0 except for a tiny negative x, which rounds to 1.0),
    # clamped to 0x3fefffffffffffff like v_fract_f32; a NaN or infinity gives NaN.
    "f64_fract": (
        "uint2 f64_fract(uint2 v) {\n"
        "    uint2 fl = f64_round(v, 1u);\n"
        "    precise double r = asdouble(v.x, v.y) - asdouble(fl.x, fl.y);\n"
        "    if (r >= asdouble(0u, 0x3ff00000u)) r = asdouble(0xffffffffu, 0x3fefffffu);\n"
        "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    # v_ldexp_f64: x * 2^e with one rounding. A subnormal x is first scaled by 2^54, which is exact and gives a normal
    # number. While the result exponent t = ex + e is in [1, 2046] only the exponent field changes, which is exact;
    # t >= 2047 is infinity. Otherwise the result is subnormal or zero: put the significand at exponent field 1 and
    # multiply once by 2^(t-1), a power of two that is exactly representable for t-1 in [-1074, -1] (normal down to
    # -1022, a denormal bit pattern below). Rounding happens only in that multiply. t-1 below -1074 means the result
    # is under 2^-2095, so using 2^-1074 still gives a zero of the right sign. e is clamped to +-4096, beyond which the
    # result is infinity or zero for every finite x. A multiply by two exact steps of at most 2^1023 cannot do this:
    # the first product can already be subnormal (double rounding), and a subnormal x scaled up needs up to 2^2097.
    "f64_ldexp": (
        "uint2 f64_ldexp(uint2 v, int e) {\n"
        "    uint ex = (v.y >> 20) & 0x7ffu;\n"
        "    uint sign = v.y & 0x80000000u;\n"
        "    if (ex == 0x7ffu) return v;\n"
        "    int expo = clamp(e, -4096, 4096);\n"
        "    if (ex == 0u) {\n"
        "        if (((v.y & 0xfffffu) | v.x) == 0u) return v;\n"
        "        precise double n = asdouble(v.x, v.y) * asdouble(0u, 0x43500000u);\n"
        "        uint lo, hi;\n        asuint(n, lo, hi);\n"
        "        v = uint2(lo, hi);\n"
        "        ex = (v.y >> 20) & 0x7ffu;\n"
        "        expo -= 54;\n"
        "    }\n"
        "    int t = int(ex) + expo;\n"
        "    if (t >= 2047) return uint2(0u, sign | 0x7ff00000u);\n"
        "    if (t >= 1) return uint2(v.x, (v.y & 0x800fffffu) | (uint(t) << 20));\n"
        "    int k = max(t - 1, -1074);\n"
        "    uint2 scale;\n"
        "    if (k >= -1022) scale = uint2(0u, uint(k + 1023) << 20);\n"
        "    else scale = u64_bit(uint(k + 1074));\n"
        "    precise double r = asdouble(v.x, (v.y & 0x800fffffu) | 0x00100000u) * asdouble(scale.x, scale.y);\n"
        "    uint lo, hi;\n    asuint(r, lo, hi);\n    return uint2(lo, hi);\n}"),
    # v_cvt_f32_f64: binary64 to binary32 rounding to nearest even, in integer arithmetic. The 53-bit significand is
    # shifted right by 29 for a normal result and by 926 - ex (30 to 53) for a subnormal one; the carry out of rounding
    # runs into the exponent, giving the next binade or infinity. Binary32 denormal results are kept (the f32 denormal
    # mode is not modeled, as for the other binary32 forms). A NaN keeps its sign and top 22 payload bits and is quieted.
    "f64_to_f32": (
        "uint f64_to_f32(uint2 v) {\n"
        "    uint sign = v.y & 0x80000000u;\n"
        "    uint ex = (v.y >> 20) & 0x7ffu;\n"
        "    uint top = v.y & 0xfffffu;\n"
        "    if (ex == 0x7ffu) {\n"
        "        if ((top | v.x) == 0u) return sign | 0x7f800000u;\n"
        "        return sign | 0x7fc00000u | (top << 3) | (v.x >> 29);\n"
        "    }\n"
        "    if (ex < 873u) return sign;\n"
        "    if (ex >= 1151u) return sign | 0x7f800000u;\n"
        "    uint2 m = uint2(v.x, 0x100000u | top);\n"
        "    uint s = 29u;\n"
        "    uint base = (ex - 897u) << 23;\n"
        "    if (ex < 897u) {\n        s = 926u - ex;\n        base = 0u;\n    }\n"
        "    uint2 q = u64_shr(m, s);\n"
        "    uint2 low = u64_low(s);\n"
        "    uint2 rest = uint2(m.x & low.x, m.y & low.y);\n"
        "    uint2 mid = u64_bit(s - 1u);\n"
        "    bool tie = rest.x == mid.x && rest.y == mid.y;\n"
        "    bool up = u64_less(mid, rest) || (tie && (q.x & 1u) != 0u);\n"
        "    return sign | (base + q.x + (up ? 1u : 0u));\n"
        "}"),
    # v_cvt_f64_f32: exact. A binary32 subnormal is normalized with firstbithigh; a NaN keeps its payload.
    "f32_to_f64": (
        "uint2 f32_to_f64(uint w) {\n"
        "    uint sign = w & 0x80000000u;\n"
        "    uint ex = (w >> 23) & 0xffu;\n"
        "    uint m = w & 0x7fffffu;\n"
        "    if (ex == 0xffu) return uint2(m << 29, sign | 0x7ff00000u | (m >> 3));\n"
        "    if (ex == 0u) {\n"
        "        if (m == 0u) return uint2(0u, sign);\n"
        "        uint sh = 23u - firstbithigh(m);\n"
        "        m = (m << sh) & 0x7fffffu;\n"
        "        return uint2(m << 29, sign | ((897u - sh) << 20) | (m >> 3));\n"
        "    }\n"
        "    return uint2(m << 29, sign | ((ex + 896u) << 20) | (m >> 3));\n"
        "}"),
    # v_cvt_i32_f64 and v_cvt_u32_f64: truncate toward zero, saturate, NaN gives 0. Spelled out because HLSL casts
    # are undefined out of range.
    "f64_to_int": (
        "uint f64_to_int(uint2 v, bool is_signed) {\n"
        "    uint ex = (v.y >> 20) & 0x7ffu;\n"
        "    bool neg = (v.y >> 31) != 0u;\n"
        "    if (ex == 0x7ffu && (((v.y & 0xfffffu) | v.x) != 0u)) return 0u;\n"
        "    if (ex < 1023u) return 0u;\n"
        "    uint shift = ex - 1023u;\n"
        "    if (!is_signed) {\n"
        "        if (neg) return 0u;\n"
        "        if (shift >= 32u) return 0xffffffffu;\n"
        "    } else if (shift >= 32u) {\n"
        "        return neg ? 0x80000000u : 0x7fffffffu;\n"
        "    }\n"
        "    uint mag = u64_shr(uint2(v.x, 0x100000u | (v.y & 0xfffffu)), 52u - shift).x;\n"
        "    if (!is_signed) return mag;\n"
        "    if (neg) return mag >= 0x80000000u ? 0x80000000u : 0u - mag;\n"
        "    return mag > 0x7fffffffu ? 0x7fffffffu : mag;\n"
        "}"),
}
# Helpers each helper calls; f64_need adds them with it. SALU_HELPERS emits in insertion order, so a helper is defined
# after the ones it calls (the u64_ ones come first in F64_HELPERS).
F64_NEEDS = {
    "f64_round": ("u64_bit", "u64_low", "u64_shr", "u64_less", "u64_add"),
    "f64_fract": ("f64_round",),
    "f64_ldexp": ("u64_bit",),
    "f64_to_f32": ("u64_bit", "u64_low", "u64_shr", "u64_less"),
    "f64_to_int": ("u64_shr",),
}
SALU_HELPERS.update(F64_HELPERS)


def f64_need(st, name):
    st.helpers.add(name)
    for need in F64_NEEDS.get(name, ()):
        f64_need(st, need)


# Inline float constants of a 64-bit float operand are binary64 values (the ISA table, as LLVM prints them for gfx10).
# A literal supplies the high word and the low word is zero, which is how llvm-mc prints and encodes 3.0 as 0x40080000.
# Integer inline constants other than 0 are refused: whether they are a sign-extended bit pattern or converted is not
# established here.
F64_CONSTANT = {t: struct.unpack("<Q", struct.pack("<d", float(t)))[0]
                for t in ("0.5", "1.0", "2.0", "4.0", "0.15915494309189532")}


def f64_operand(token, st):
    """Low and high word expressions of a 64-bit float source. neg and abs act on the sign bit of the high word, abs
    first. A register half is read as the unsigned word it holds (vector_u32), never through a float."""
    modified = re.fullmatch(r"(-?)(?:\|([^|]+)\||([^|]+))", token)
    if not modified:
        raise ValueError(f"Unsupported 64-bit operand {token}")
    negate, body = bool(modified[1]), modified[2] or modified[3]
    absolute = modified[2] is not None
    if pair := re.fullmatch(r"([vs])\[(\d+):(\d+)\]", body):
        if pair[1] == "v":
            # gfx10 has no alignment rule for VGPR pairs (llvm-mc -mcpu=gfx1013 assembles v[21:22]); each half is its
            # own tracked word, so an odd pair can also join the halves of two values written separately.
            names = [f"v{n}" for n in registers(pair[2], pair[3], 2)]
        else:
            names = sgpr_pair(body)
        lo, hi = (vector_u32(n, st.scalar, st.vector, st.pending, st.sample_pending) for n in names)
    elif body in F64_CONSTANT:
        lo, hi = f"{F64_CONSTANT[body] & 0xffffffff}u", f"{F64_CONSTANT[body] >> 32}u"
    elif body == "0":
        lo, hi = "0u", "0u"
    elif re.fullmatch(r"0x[0-9a-f]{1,8}", body):
        lo, hi = "0u", f"{int(body, 16)}u"
    else:
        raise ValueError(f"Unsupported 64-bit operand {token}")
    if absolute:
        hi = f"({hi} & 0x7fffffffu)"
    if negate:
        hi = f"({hi} ^ 0x80000000u)"
    return f"uint2({lo}, {hi})"


def f32_word_operand(token, st):
    """A binary32 source word with neg and abs on bit 31; integer and hex constants are bit patterns."""
    if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", token):
        return vector_u32(token, st.scalar, st.vector, st.pending, st.sample_pending)
    modified = re.fullmatch(r"(-?)(?:\|([^|]+)\||([^|]+))", token)
    if not modified:
        raise ValueError(f"Unsupported 32-bit operand {token}")
    word = vector_u32(modified[2] or modified[3], st.scalar, st.vector, st.pending, st.sample_pending)
    if modified[2] is not None:
        word = f"({word} & 0x7fffffffu)"
    if modified[1]:
        word = f"({word} ^ 0x80000000u)"
    return word


def f64_destination(token, st):
    pair = re.fullmatch(r"v\[(\d+):(\d+)\]", token)
    if not pair:
        raise ValueError(f"Expected a 64-bit vector register pair, got {token}")
    names = [f"v{n}" for n in registers(pair[1], pair[2], 2)]
    if any(name in st.sample_dest for name in names):
        raise ValueError("Write overlaps an outstanding sample")
    return names


def f64_write(st, i, dst, expression, clamp):
    names = f64_destination(dst, st)
    if clamp:
        f64_need(st, "f64_sat")
        expression = f"f64_sat({expression})"
    st.lines.append(f"    uint2 dalu{i} = {expression};")
    st.vector[names[0]], st.vector[names[1]] = ("uint", f"dalu{i}.x"), ("uint", f"dalu{i}.y")


@form(r"v_(add|mul|min|max|fma|ldexp)_f64(_e64)? (v\[\d+:\d+\]), (.+?)( clamp)?")
def arithmetic(st, i, m):
    # VOP3-only binary64 arithmetic; the output modifiers and the e32 spelling are not accepted.
    op, _, dst, operands, clamp = m.groups()
    tokens = operands.split(", ")
    if st.ex != "true" or len(tokens) != {"fma": 3}.get(op, 2):
        raise ValueError("Invalid arithmetic operation")
    f64_destination(dst, st)
    if op == "ldexp":
        # The exponent is an integer word; vector_u32 refuses a modifier on it.
        source = f64_operand(tokens[0], st)
        exponent = vector_u32(tokens[1], st.scalar, st.vector, st.pending, st.sample_pending)
        f64_need(st, "f64_ldexp")
        expression = f"f64_ldexp({source}, asint({exponent}))"
    else:
        f64_need(st, f"f64_{op}")
        expression = f"f64_{op}({', '.join(f64_operand(t, st) for t in tokens)})"
    f64_write(st, i, dst, expression, clamp)


@form(r"v_(floor|ceil|trunc|rndne|fract)_f64(_e32|_e64)? (v\[\d+:\d+\]), (.+?)( clamp)?")
def rounding(st, i, m):
    # Rounding to an integral value on the bit pattern; see f64_round.
    op, suffix, dst, source, clamp = m.groups()
    if st.ex != "true" or (suffix == "_e32" and (clamp or source.startswith(("-", "|")))):
        raise ValueError("Invalid arithmetic operation")
    f64_destination(dst, st)
    operand = f64_operand(source, st)
    if op == "fract":
        f64_need(st, "f64_fract")
        expression = f"f64_fract({operand})"
    else:
        f64_need(st, "f64_round")
        expression = f"f64_round({operand}, {['trunc', 'floor', 'ceil', 'rndne'].index(op)}u)"
    f64_write(st, i, dst, expression, clamp)


@form(r"v_cvt_f64_(f32|i32|u32)(_e32|_e64)? (v\[\d+:\d+\]), (.+?)( clamp)?")
def widen(st, i, m):
    kind, suffix, dst, source, clamp = m.groups()
    if st.ex != "true" or (suffix == "_e32" and (clamp or source.startswith(("-", "|")) and kind == "f32")):
        raise ValueError("Invalid conversion")
    f64_destination(dst, st)
    if kind == "f32":
        f64_need(st, "f32_to_f64")
        expression = f"f32_to_f64({f32_word_operand(source, st)})"
    else:
        f64_need(st, f"f64_from_{kind}")
        expression = f"f64_from_{kind}({vector_u32(source, st.scalar, st.vector, st.pending, st.sample_pending)})"
    f64_write(st, i, dst, expression, clamp)


@form(r"v_cvt_(f32|i32|u32)_f64(_e32|_e64)? (v\d+), (.+?)( clamp)?")
def narrow(st, i, m):
    # The result is one word. clamp is accepted only for the float result, applied to the double before rounding,
    # which is the same as clamping the binary32 result because 0 and 1 are exact.
    kind, suffix, dst, source, clamp = m.groups()
    if (st.ex != "true" or (clamp and (kind != "f32" or suffix == "_e32"))
            or (suffix == "_e32" and source.startswith(("-", "|")))):
        raise ValueError("Invalid conversion")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    operand = f64_operand(source, st)
    if clamp:
        f64_need(st, "f64_sat")
        operand = f"f64_sat({operand})"
    if kind == "f32":
        f64_need(st, "f64_to_f32")
        expression = f"f64_to_f32({operand})"
    else:
        f64_need(st, "f64_to_int")
        expression = f"f64_to_int({operand}, {'true' if kind == 'i32' else 'false'})"
    st.lines.append(f"    uint dalu{i} = {expression};")
    st.vector[dst] = ("uint", f"dalu{i}")
