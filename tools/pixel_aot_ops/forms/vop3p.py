"""VOP3P: mixed-precision fused multiply-add (v_fma_mix_f32, v_fma_mixlo_f16, v_fma_mixhi_f16), packed binary16
arithmetic (v_pk_{add,mul,min,max,fma}_f16), packed 16-bit integer arithmetic (v_pk_*_{i16,u16,b16}) and the dot
products (v_dot2_f32_f16, v_dot2_{i32_i16,u32_u16}, v_dot4_{i32_i8,u32_u8}, v_dot8_{i32_i4,u32_u4})."""
import re
import struct

from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import F16_CONSTANT, tracked_word, word_of

# Mixed-precision fused multiply-add: v_fma_mix_f32, v_fma_mixlo_f16, v_fma_mixhi_f16 (VOP3P encoding).
# Sources:
#   AMD RDNA 2 ISA Reference Guide (document 70648, 2020-11-30), section 12.10 VOP3P Instructions, opcodes 32 to 34:
#     "Size and location of S0, S1 and S2 controlled by OPSEL: 0=src[31:0], 1=src[31:0], 2=src[15:0], 3=src[31:16]";
#     "for MAD_MIX, the NEG_HI field acts instead as an absolute-value modifier"; D.f[31:0] = S0.f * S1.f + S2.f for
#     V_FMA_MIX_F32, D.f[15:0] = ... "stored in low 16 bits" for MIXLO and D.f[31:16] = ... for MIXHI.
#     The OPSEL value of a source is {op_sel_hi, op_sel}: op_sel_hi 0 reads the whole binary32 word whatever op_sel
#     says; op_sel_hi 1 reads the binary16 half that op_sel picks (0 low, 1 high).
#   LLVM 15 (llvmorg-15.0.7) llvm/lib/Target/AMDGPU/VOP3PInstructions.td: VOP3P_Mix_Profile ("The inline immediate values
#     are really f16 converted to f32"; mixlo and mixhi tie $vdst to $vdst_in, so the other half of the destination is
#     kept); "Clamp modifier is applied after conversion to f16"; MadFmaMixPats model mixlo and mixhi as
#     fpround(fma(f32, f32, f32)).
# The ISA text does not say whether the narrowed result is rounded once. This lowering rounds the exact a*b+c once, to
# nearest even, to the format of the result; fpround(fma) in binary32 is not that (a result that lands on a binary16 tie
# after the binary32 rounding is then rounded again: a = 0x31e9, b = 0xb56a, c = 0x5a91 (all binary16) is 210.125, the
# correctly rounded result, where fma in binary32 and then narrowing gives 210.0; the draws use cases like it).
#
# The arithmetic is integer, so it needs no float64 capability and does not depend on whether a target fuses a*b+c or
# flushes binary32 denormals. A source is the encoding of a binary32 (a binary16 source is widened exactly first). A
# finite value is m * 2^e with m < 2^24. The product m_a * m_b < 2^48 is exact in two words. Each of the product and the
# addend is shifted left until its top bit is bit 62 of a 64-bit window; the one with the larger top exponent is the big
# operand, and the other is shifted right by the exponent difference with the bits shifted out OR-ed into bit 0 (a
# sticky bit). That is exact unless bits are lost, which needs a difference over 15 (product) or 39 (addend); then the
# result still has its top bit at 61 or 62, the rounding position is 37 or more bits above bit 0, and the sticky bit
# keeps bit 0 of the sum odd, so the sum is never on a rounding boundary or midpoint while the exact value is on neither
# (the exact value lies within one unit of the computed one and the boundaries are even). Equal signs add (the sum is
# below 2^64), unequal signs subtract the smaller magnitude. The result is rounded to p = 24 (binary32, quantum 2^-149)
# or p = 11 (binary16, quantum 2^-24) bits: nearest even, subnormal results gradual, overflow to infinity. The
# encoding is ((q + bias) << mantissa bits) + kept, where kept holds the implicit bit, so a carry out of kept moves into
# the exponent and a subnormal that rounds up becomes the smallest normal.
# Special values: a NaN source gives that NaN, quieted (first of a, b, c; a binary16 result keeps the top ten payload
# bits as narrow16 does); infinity times zero, or opposite infinities, give the default quiet NaN; an exact zero sum is
# +0 unless both the product and the addend are -0 (round to nearest). A NaN payload or sign from hardware is not
# modelled beyond this and the draws do not use NaN. Binary32 denormal inputs and results are not flushed, as in the
# v_fma_f32 branch (v_mad_f32 is the form that flushes). Clamp: NaN and any negative value, -0 included, give +0, a
# value above 1.0 gives 1.0; the draws avoid -0 under clamp because hardware is not documented for it.
FMA_MIX_HELPERS = """uint fm_msb(uint x) {
    uint n = 0u;
    if (x >= 0x10000u) { x >>= 16u; n += 16u; }
    if (x >= 0x100u) { x >>= 8u; n += 8u; }
    if (x >= 0x10u) { x >>= 4u; n += 4u; }
    if (x >= 0x4u) { x >>= 2u; n += 2u; }
    if (x >= 0x2u) { n += 1u; }
    return n;
}
uint fm_msb64(uint2 v) {
    return v.y != 0u ? 32u + fm_msb(v.y) : fm_msb(v.x);
}
uint2 fm_shl(uint2 v, uint n) {
    if (n == 0u) return v;
    if (n < 32u) return uint2(v.x << n, (v.y << n) | (v.x >> (32u - n)));
    return uint2(0u, v.x << (n - 32u));
}
uint2 fm_shr_jam(uint2 v, uint n) {
    if (n == 0u) return v;
    if (n >= 64u) return uint2((v.x | v.y) != 0u ? 1u : 0u, 0u);
    uint2 r;
    bool lost;
    if (n < 32u) {
        lost = (v.x << (32u - n)) != 0u;
        r = uint2((v.x >> n) | (v.y << (32u - n)), v.y >> n);
    } else if (n == 32u) {
        lost = v.x != 0u;
        r = uint2(v.y, 0u);
    } else {
        lost = v.x != 0u || (v.y << (64u - n)) != 0u;
        r = uint2(v.y >> (n - 32u), 0u);
    }
    return uint2(r.x | (lost ? 1u : 0u), r.y);
}
uint2 fm_add(uint2 a, uint2 b) {
    uint low = a.x + b.x;
    return uint2(low, a.y + b.y + (low < a.x ? 1u : 0u));
}
uint2 fm_sub(uint2 a, uint2 b) {
    return uint2(a.x - b.x, a.y - b.y - (a.x < b.x ? 1u : 0u));
}
bool fm_ge(uint2 a, uint2 b) {
    return a.y > b.y || (a.y == b.y && a.x >= b.x);
}
uint2 fm_mul24(uint a, uint b) {
    uint a0 = a & 0xffffu, a1 = a >> 16u, b0 = b & 0xffffu, b1 = b >> 16u;
    uint p00 = a0 * b0, mid = a0 * b1 + a1 * b0, p11 = a1 * b1;
    uint low = p00 + ((mid & 0xffffu) << 16u);
    return uint2(low, p11 + (mid >> 16u) + (low < p00 ? 1u : 0u));
}
uint fm_f16_word(uint h) {
    uint sign = (h & 0x8000u) << 16u;
    uint e = (h >> 10u) & 0x1fu;
    uint m = h & 0x3ffu;
    if (e == 0x1fu) return sign | 0x7f800000u | (m << 13u);
    if (e != 0u) return sign | ((e + 112u) << 23u) | (m << 13u);
    if (m == 0u) return sign;
    uint k = fm_msb(m);
    return sign | ((k + 103u) << 23u) | ((m << (23u - k)) & 0x7fffffu);
}
uint fm_nan(uint word, bool wide) {
    if (wide) return word | 0x00400000u;
    return ((word >> 16u) & 0x8000u) | 0x7e00u | ((word & 0x7fffffu) >> 13u);
}
uint fm_inf(uint sign, bool wide) {
    return wide ? ((sign << 31u) | 0x7f800000u) : ((sign << 15u) | 0x7c00u);
}
uint fm_zero(uint sign, bool wide) {
    return wide ? (sign << 31u) : (sign << 15u);
}
uint fma_mix_round(uint a, uint b, uint c, bool wide) {
    uint ma = a & 0x7fffffffu, mb = b & 0x7fffffffu, mc = c & 0x7fffffffu;
    uint sa = a >> 31u, sb = b >> 31u, sc = c >> 31u;
    uint sp = sa ^ sb;
    if (ma > 0x7f800000u) return fm_nan(a, wide);
    if (mb > 0x7f800000u) return fm_nan(b, wide);
    if (mc > 0x7f800000u) return fm_nan(c, wide);
    bool inf_p = ma == 0x7f800000u || mb == 0x7f800000u;
    if ((ma == 0x7f800000u && mb == 0u) || (mb == 0x7f800000u && ma == 0u)
        || (inf_p && mc == 0x7f800000u && sp != sc)) return fm_nan(0x7fc00000u, wide);
    if (inf_p) return fm_inf(sp, wide);
    if (mc == 0x7f800000u) return fm_inf(sc, wide);
    uint xa = ma >> 23u, xb = mb >> 23u, xc = mc >> 23u;
    uint na = xa == 0u ? ma : ((ma & 0x7fffffu) | 0x800000u);
    uint nb = xb == 0u ? mb : ((mb & 0x7fffffu) | 0x800000u);
    uint nc = xc == 0u ? mc : ((mc & 0x7fffffu) | 0x800000u);
    int ep = int(xa == 0u ? 1u : xa) + int(xb == 0u ? 1u : xb) - 300;
    int ec = int(xc == 0u ? 1u : xc) - 150;
    uint2 mp = fm_mul24(na, nb);
    bool pz = (mp.x | mp.y) == 0u;
    bool cz = nc == 0u;
    if (pz && cz) return fm_zero(sp & sc, wide);
    uint2 p = uint2(0u, 0u), cw = uint2(0u, 0u);
    int tp = 0, tc = 0;
    if (!pz) {
        uint up = 62u - fm_msb64(mp);
        p = fm_shl(mp, up);
        tp = ep - int(up);
    }
    if (!cz) {
        uint uc = 62u - fm_msb(nc);
        cw = fm_shl(uint2(nc, 0u), uc);
        tc = ec - int(uc);
    }
    bool p_big = cz || (!pz && tp >= tc);
    uint2 big = p_big ? p : cw;
    uint2 small = p_big ? cw : p;
    int big_e = p_big ? tp : tc;
    uint big_s = p_big ? sp : sc;
    uint small_s = p_big ? sc : sp;
    uint gap = (pz || cz) ? 0u : uint(p_big ? tp - tc : tc - tp);
    small = fm_shr_jam(small, gap);
    uint2 r;
    uint rs = big_s;
    if (big_s == small_s) {
        r = fm_add(big, small);
    } else if (fm_ge(big, small)) {
        r = fm_sub(big, small);
    } else {
        r = fm_sub(small, big);
        rs = small_s;
    }
    if ((r.x | r.y) == 0u) return 0u;
    int top = int(fm_msb64(r)) + big_e;
    int mant = wide ? 23 : 10;
    int quantum = max(top - mant, wide ? -149 : -24);
    int shift = quantum - big_e;
    uint2 s2;
    if (shift >= 2) s2 = fm_shr_jam(r, uint(shift - 2));
    else s2 = fm_shl(r, uint(2 - shift));
    uint kept = s2.x >> 2u;
    if ((s2.x & 2u) != 0u && ((s2.x & 1u) != 0u || (kept & 1u) != 0u)) kept += 1u;
    int field = quantum + (wide ? 149 : 24);
    uint infinity = wide ? 0x7f800000u : 0x7c00u;
    if (field >= (wide ? 255 : 31)) return fm_inf(rs, wide);
    uint encoding = (uint(field) << uint(mant)) + kept;
    return min(encoding, infinity) | fm_zero(rs, wide);
}
uint fma_mix_sat(uint v, bool wide) {
    uint sign = wide ? 0x80000000u : 0x8000u;
    uint one = wide ? 0x3f800000u : 0x3c00u;
    if ((v & (sign - 1u)) > (wide ? 0x7f800000u : 0x7c00u) || (v & sign) != 0u) return 0u;
    return min(v, one);
}
"""


def need_fma_mix(st):
    """Emit FMA_MIX_HELPERS once (fma_mix_round, fma_mix_sat and fm_f16_word are shared with v_pk_fma_f16). The text is
    placed by place_fma_mix once the program is lowered: inserting it before the preamble while lowering would move
    every line the control-flow walk has recorded a position of (a loop's dry run, an if's join declarations)."""
    st.helpers.add("fma_mix")


def place_fma_mix(st):
    """Insert FMA_MIX_HELPERS just before the preamble, where need_fma_mix used to insert it at first use (the text
    after lowering is the same: nothing else is put before the preamble while lowering)."""
    if "fma_mix" in st.helpers and FMA_MIX_HELPERS not in st.lines:
        st.lines.insert(st.lines.index(st.preamble), FMA_MIX_HELPERS)


def fma_mix_source(token, high, select, scalar, vector, pending, sample_pending):
    """One source of v_fma_mix_*: the binary32 encoding of its value after widening and modifiers, as a uint expression.

    high is op_sel_hi (the source is binary16) and select is op_sel (high half); select is ignored for a binary32
    source. Inline constants are read as binary16 values and widened, as LLVM does (VOP3P_Mix_Profile): 0, +-0.5,
    +-1, +-2 and +-4 are the same value in both formats and are accepted for either; 1/(2*pi) is accepted only for a
    binary16 source, where its value is known; other integer constants are refused. LLVM prints a literal as its low 16
    bits, so a literal source is lowered only as the low binary16 half; a binary32 literal or a high half is not in the
    text and is refused."""
    negate = absolute = False
    body = token
    constant = re.fullmatch(r"-?0\.5|-?1\.0|-?2\.0|-?4\.0|0|0\.15915494", token)
    if not constant:
        if body.startswith("neg(") and body.endswith(")"):
            negate, body = True, body[4:-1]
        elif body.startswith("-"):
            negate, body = True, body[1:]
        if len(body) > 2 and body.startswith("|") and body.endswith("|"):
            absolute, body = True, body[1:-1]
        if body.startswith("-") and not (absolute and re.fullmatch(r"-0\.5|-1\.0|-2\.0|-4\.0", body)):
            # LLVM prints |-2.0| and -|-2.0| for a negative inline constant under abs, and never --x or |-v1|.
            raise ValueError(f"Malformed modifier {token}")
        constant = re.fullmatch(r"-?0\.5|-?1\.0|-?2\.0|-?4\.0|0|0\.15915494", body)
    if constant:
        text = constant.group(0)
        if (select and high) or (text == "0.15915494" and not high):
            raise ValueError(f"Unsupported constant source {token}")
        bits = F16_CONSTANT.get(text, 0)
        if absolute:
            bits &= 0x7fff
        if negate:
            bits ^= 0x8000
        return f"fm_f16_word({bits:#x}u)"
    if re.fullmatch(r"0x[0-9a-f]{1,4}", body):
        if not high or select:
            raise ValueError(f"A literal source is lowered only as the low binary16 half: {token}")
        word = f"{int(body, 16):#x}u"
    elif re.fullmatch(r"[vs]\d+", body):
        word = word_of(body, scalar, vector, pending, sample_pending)
    else:
        raise ValueError(f"Unsupported source {token}")
    if high:
        half = f"(({word} >> 16u) & 0xffffu)" if select else f"({word} & 0xffffu)"
        if absolute:
            half = f"({half} & 0x7fffu)"
        if negate:
            half = f"({half} ^ 0x8000u)"
        return f"fm_f16_word({half})"
    if absolute:
        word = f"({word} & 0x7fffffffu)"
    if negate:
        word = f"({word} ^ 0x80000000u)"
    return word


@form(r"v_fma_(mix_f32|mixlo_f16|mixhi_f16)(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)"
      r"(?: op_sel:\[([01]),([01]),([01])\])?(?: op_sel_hi:\[([01]),([01]),([01])\])?( clamp)?")
def fma_mix(st, i, m):
    # Mixed-precision fused multiply-add (see FMA_MIX_HELPERS). op_sel_hi picks binary16 for a source and op_sel
    # its high half; the printer omits an all-zero op_sel or op_sel_hi. Output modifiers, DPP and SDWA are not in
    # this grammar. A binary16 result replaces only its half of the destination, as v_cvt_f16_f32 does.
    op, dst, *tokens, s0, s1, s2, h0, h1, h2, clamp = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    old = st.vector.get(dst)
    kept = tracked_word(old) if old is not None else None
    if kept is None and st.stage == "compute" and isinstance(old, tuple) and len(old) == 2 and old[0] == "uint":
        kept = old[1]  # the compute stage keeps the half of any integer word (a local id, say)
    if op != "mix_f32" and old is not None and kept is None:
        raise ValueError("Unsupported arithmetic destination")
    need_fma_mix(st)
    selects = [int(x or 0) for x in (s0, s1, s2)]
    highs = [int(x or 0) for x in (h0, h1, h2)]
    a, b, c = (fma_mix_source(t, h, s, st.scalar, st.vector, st.pending, st.sample_pending)
               for t, h, s in zip(tokens, highs, selects))
    wide = op == "mix_f32"
    expression = f"fma_mix_round({a}, {b}, {c}, {'true' if wide else 'false'})"
    if clamp:
        expression = f"fma_mix_sat({expression}, {'true' if wide else 'false'})"
    if op == "mixlo_f16":
        keep = f"({kept} & 0xffff0000u)" if old is not None else "0u"
        expression = f"{keep} | {expression}"
    elif op == "mixhi_f16":
        keep = f"({kept} & 0xffffu)" if old is not None else "0u"
        expression = f"{keep} | ({expression} << 16u)"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = asfloat({expression});")


# Packed VOP3P forms: v_pk_*_f16, v_pk_*_{i16,u16,b16} and the dot products. A packed word holds two 16-bit lanes; lane 0
# (bits 15:0) reads the half of each source that op_sel picks and lane 1 (bits 31:16) the half that op_sel_hi picks
# (defaults: op_sel all 0, op_sel_hi all 1; the printer omits an all-default modifier). neg_lo and neg_hi negate the
# sources of lane 0 and lane 1; on a binary16 half that flips bit 15, as for the other 16-bit forms. Every packed value
# is a uint word, never a float-typed value, and no float16 HLSL type is used.
# Sources:
#   AMD RDNA 2 ISA Reference Guide (document 70648), section 12.10 VOP3P Instructions (the opcodes of the v_pk_ and
#   v_dot families) and LLVM 15 VOP3PInstructions.td (modifier operands and which instructions take clamp or neg).
# An inline float constant is the binary16 value in the low half with the high half zero (the ported draws check this on
# hardware); an integer inline constant -16..64 is its 32-bit sign extension; a literal is the 32-bit word. Modifiers on a
# source operand (-, |x|) are not part of the grammar, nor are output modifiers, DPP and SDWA.
PK_F16 = {"add": 2, "mul": 2, "min": 2, "max": 2, "fma": 3}
PK_INT16 = {
    "add_i16": (2, True), "add_u16": (2, True), "sub_i16": (2, True), "sub_u16": (2, True),
    "min_i16": (2, False), "min_u16": (2, False), "max_i16": (2, False), "max_u16": (2, False),
    "mul_lo_u16": (2, False), "mad_i16": (3, True), "mad_u16": (3, True),
    "lshlrev_b16": (2, False), "lshrrev_b16": (2, False), "ashrrev_i16": (2, False),
}
DOT_OPS = ("v_dot2_f32_f16", "v_dot2_i32_i16", "v_dot2_u32_u16", "v_dot4_i32_i8", "v_dot4_u32_u8", "v_dot8_i32_i4",
           "v_dot8_u32_u4")

# Dot products accumulate in 64 bits and saturate once at the end when clamp is set (RDNA 2 ISA: the 32-bit result
# is clamped to the destination range). Without clamp the low 32 bits wrap.
SALU_HELPERS.update({
    "dot_u64_add": (
        "uint2 dot_u64_add(uint2 acc, uint v) {\n"
        "    uint lo = acc.x + v;\n"
        "    return uint2(lo, acc.y + (lo < acc.x ? 1u : 0u));\n"
        "}"
    ),
    "dot_u64_sat": (
        "uint dot_u64_sat(uint2 s) {\n"
        "    return s.y != 0u ? 0xffffffffu : s.x;\n"
        "}"
    ),
    "dot_i64_add": (
        "uint2 dot_i64_add(uint2 acc, int v) {\n"
        "    uint uv = asuint(v);\n"
        "    uint lo = acc.x + uv;\n"
        "    uint hi = acc.y + (v < 0 ? 0xffffffffu : 0u) + (lo < acc.x ? 1u : 0u);\n"
        "    return uint2(lo, hi);\n"
        "}"
    ),
    "dot_i64_sat": (
        "uint dot_i64_sat(uint2 s) {\n"
        "    if (asint(s.y) > 0 || (s.y == 0u && s.x > 0x7fffffffu)) return 0x7fffffffu;\n"
        "    if (asint(s.y) < -1 || (s.y == 0xffffffffu && s.x < 0x80000000u)) return 0x80000000u;\n"
        "    return s.x;\n"
        "}"
    ),
    "v_dot2_i32_i16": (
        "uint v_dot2_i32_i16(uint a0, uint a1, uint b0, uint b1, uint c, bool sat) {\n"
        "    int p0 = (asint(a0 << 16u) >> 16) * (asint(b0 << 16u) >> 16);\n"
        "    int p1 = (asint(a1 << 16u) >> 16) * (asint(b1 << 16u) >> 16);\n"
        "    uint2 s = dot_i64_add(dot_i64_add(dot_i64_add(uint2(0u, 0u), asint(c)), p0), p1);\n"
        "    return sat ? dot_i64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot2_u32_u16": (
        "uint v_dot2_u32_u16(uint a0, uint a1, uint b0, uint b1, uint c, bool sat) {\n"
        "    uint p0 = (a0 & 0xffffu) * (b0 & 0xffffu);\n"
        "    uint p1 = (a1 & 0xffffu) * (b1 & 0xffffu);\n"
        "    uint2 s = dot_u64_add(dot_u64_add(uint2(c, 0u), p0), p1);\n"
        "    return sat ? dot_u64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot4_i32_i8": (
        "uint v_dot4_i32_i8(uint a, uint b, uint c, bool sat) {\n"
        "    int sum = 0;\n"
        "    for (uint k = 0u; k < 4u; ++k) {\n"
        "        int x = asint(((a >> (k * 8u)) & 0xffu) << 24u) >> 24;\n"
        "        int y = asint(((b >> (k * 8u)) & 0xffu) << 24u) >> 24;\n"
        "        sum += x * y;\n"
        "    }\n"
        "    uint2 s = dot_i64_add(dot_i64_add(uint2(0u, 0u), asint(c)), sum);\n"
        "    return sat ? dot_i64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot4_u32_u8": (
        "uint v_dot4_u32_u8(uint a, uint b, uint c, bool sat) {\n"
        "    uint sum = 0u;\n"
        "    for (uint k = 0u; k < 4u; ++k) {\n"
        "        sum += ((a >> (k * 8u)) & 0xffu) * ((b >> (k * 8u)) & 0xffu);\n"
        "    }\n"
        "    uint2 s = dot_u64_add(uint2(c, 0u), sum);\n"
        "    return sat ? dot_u64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot8_i32_i4": (
        "uint v_dot8_i32_i4(uint a, uint b, uint c, bool sat) {\n"
        "    int sum = 0;\n"
        "    for (uint k = 0u; k < 8u; ++k) {\n"
        "        int x = asint(((a >> (k * 4u)) & 0xfu) << 28u) >> 28;\n"
        "        int y = asint(((b >> (k * 4u)) & 0xfu) << 28u) >> 28;\n"
        "        sum += x * y;\n"
        "    }\n"
        "    uint2 s = dot_i64_add(dot_i64_add(uint2(0u, 0u), asint(c)), sum);\n"
        "    return sat ? dot_i64_sat(s) : s.x;\n"
        "}"
    ),
    "v_dot8_u32_u4": (
        "uint v_dot8_u32_u4(uint a, uint b, uint c, bool sat) {\n"
        "    uint sum = 0u;\n"
        "    for (uint k = 0u; k < 8u; ++k) {\n"
        "        sum += ((a >> (k * 4u)) & 0xfu) * ((b >> (k * 4u)) & 0xfu);\n"
        "    }\n"
        "    uint2 s = dot_u64_add(uint2(c, 0u), sum);\n"
        "    return sat ? dot_u64_sat(s) : s.x;\n"
        "}"
    ),
})


def packed_word(st, token, *, f16):
    """One packed source as a uint word expression (see the grammar above)."""
    if f16 and token in F16_CONSTANT:
        return f"{F16_CONSTANT[token]:#x}u"
    if re.fullmatch(r"-?\d+", token):
        if not -16 <= int(token) <= 64:
            raise ValueError(f"Integer inline constant out of range: {token}")
        return f"{int(token) & 0xffffffff:#x}u"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return f"{int(token, 16):#x}u"
    if m := re.fullmatch(r"([vs])(\d+)", token):
        if int(m.group(2)) > (255 if m.group(1) == "v" else 105):
            raise ValueError(f"Register out of range: {token}")
        return word_of(token, st.scalar, st.vector, st.pending, st.sample_pending)
    raise ValueError(f"Unsupported packed operand {token}")


def parse_packed(rest, arity, names, *, clamp_allowed):
    """Split `src, src[, src] [modifiers]` into the sources, the modifier bit lists and the clamp flag."""
    parts = rest.split(", ")
    if len(parts) != arity:
        raise ValueError("Invalid packed operand count")
    last, _, text = parts[-1].partition(" ")
    tokens = [*parts[:-1], last]
    bits, clamp = {}, False
    for mod in text.split():
        if mod == "clamp":
            if clamp or not clamp_allowed:
                raise ValueError("Invalid clamp modifier")
            clamp = True
        elif m := re.fullmatch(r"(" + "|".join(names) + r"):\[([01](?:,[01])*)\]", mod):
            value = [int(b) for b in m.group(2).split(",")]
            if m.group(1) in bits or len(value) != arity:
                raise ValueError(f"Invalid packed modifier {mod}")
            bits[m.group(1)] = value
        else:
            raise ValueError(f"Unsupported packed modifier {mod}")
    return tokens, bits, clamp


def declare_words(st, i, prefix, tokens, f16):
    names = []
    for k, token in enumerate(tokens):
        st.lines.append(f"    uint {prefix}{i}_{k} = {packed_word(st, token, f16=f16)};")
        names.append(f"{prefix}{i}_{k}")
    return names


def half_of(name, high, negate=False):
    """The binary16 (or 16-bit) half of a word as an unsigned expression; negate flips bit 15."""
    half = f"(({name} >> 16u) & 0xffffu)" if high else f"({name} & 0xffffu)"
    return f"({half} ^ 0x8000u)" if negate else half


@form(r"v_pk_(add|mul|min|max|fma)_f16 (v\d+), (.+)")
def pk_f16(st, i, m):
    # Each lane is computed from binary16 halves. add and mul widen, operate once in binary32 and narrow once (innocuous
    # double rounding, as F16_ALU in valu_f16.py); fma is the exactly rounded fma_mix_round; min and max return the
    # other operand when one is a NaN. clamp saturates to [0, 1] (NaN gives 0).
    op, dst, rest = m.groups()
    arity = PK_F16[op]
    if int(dst[1:]) > 255:
        raise ValueError("Invalid packed operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    tokens, bits, clamp = parse_packed(rest, arity, ("op_sel", "op_sel_hi", "neg_lo", "neg_hi"), clamp_allowed=True)
    words = declare_words(st, i, "pkw", tokens, True)
    if op == "fma":
        need_fma_mix(st)
    lanes = []
    for lane, select, negate, default in ((0, "op_sel", "neg_lo", 0), (1, "op_sel_hi", "neg_hi", 1)):
        halves = []
        for k, word in enumerate(words):
            halves.append(f"pkh{i}_{lane}{k}")
            high = bits.get(select, [default] * arity)[k]
            st.lines.append(f"    uint {halves[-1]} = {half_of(word, high, bits.get(negate, [0] * arity)[k])};")
        if op == "fma":
            value = "fma_mix_round(" + ", ".join(f"fm_f16_word({h})" for h in halves) + ", false)"
            if clamp:
                value = f"fma_mix_sat({value}, false)"
        else:
            a, b = (f"widen16({h})" for h in halves)
            if op in ("min", "max"):
                nan = lambda h: f"(({h} & 0x7fffu) > 0x7c00u)"
                value = f"({nan(halves[0])} ? {b} : ({nan(halves[1])} ? {a} : {op}({a}, {b})))"
            else:
                value = f"({a} {'+' if op == 'add' else '*'} {b})"
            st.lines.append(f"    precise float pkf{i}_{lane} = {value};")
            value = f"narrow16({'saturate(' if clamp else ''}pkf{i}_{lane}{')' if clamp else ''})"
        lanes.append(value)
    st.lines.append(f"    uint valu{i} = {lanes[0]} | ({lanes[1]} << 16u);")
    st.vector[dst] = ("uint", f"valu{i}")


def pk_int_lane(op, w, high, clamp):
    """The 16-bit result (an unsigned expression below 0x10000) of one lane of v_pk_<op>; high[k] picks the half of
    source k."""
    def u16(k):
        return half_of(w[k], high[k])

    def i16(k):
        return f"(asint({w[k]}) >> 16)" if high[k] else f"(asint({w[k]} << 16u) >> 16)"

    def signed(r):
        return f"(asuint({'clamp(' + r + ', -32768, 32767)' if clamp else r}) & 0xffffu)"

    if op in ("add_i16", "sub_i16"):
        return signed(f"({i16(0)} {'+' if op == 'add_i16' else '-'} {i16(1)})")
    if op in ("add_u16", "sub_u16"):
        if op == "add_u16":
            return f"min({u16(0)} + {u16(1)}, 65535u)" if clamp else f"(({u16(0)} + {u16(1)}) & 0xffffu)"
        return f"({u16(0)} < {u16(1)} ? 0u : ({u16(0)} - {u16(1)}))" if clamp else f"(({u16(0)} - {u16(1)}) & 0xffffu)"
    if op in ("min_i16", "max_i16"):
        return f"(asuint({op[:3]}({i16(0)}, {i16(1)})) & 0xffffu)"
    if op in ("min_u16", "max_u16"):
        return f"{op[:3]}({u16(0)}, {u16(1)})"
    if op == "mul_lo_u16":
        return f"(({u16(0)} * {u16(1)}) & 0xffffu)"
    if op == "mad_i16":
        return signed(f"({i16(0)} * {i16(1)} + {i16(2)})")
    if op == "mad_u16":
        r = f"({u16(0)} * {u16(1)} + {u16(2)})"
        return f"min({r}, 65535u)" if clamp else f"({r} & 0xffffu)"
    if op == "lshlrev_b16":
        return f"(({u16(1)} << ({u16(0)} & 15u)) & 0xffffu)"
    if op == "lshrrev_b16":
        return f"({u16(1)} >> ({u16(0)} & 15u))"
    return f"(asuint({i16(1)} >> ({u16(0)} & 15u)) & 0xffffu)"  # ashrrev_i16


@form(r"v_pk_(" + "|".join(PK_INT16) + r") (v\d+), (.+)")
def pk_int16(st, i, m):
    # The shift forms are reversed (src0 is the count, masked to 4 bits). clamp is accepted only where llvm-mc has it
    # (add, sub, mad); it saturates the exact result to the signed or unsigned 16-bit range. No neg modifiers.
    op, dst, rest = m.groups()
    arity, clamp_allowed = PK_INT16[op]
    if int(dst[1:]) > 255:
        raise ValueError("Invalid packed integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    tokens, bits, clamp = parse_packed(rest, arity, ("op_sel", "op_sel_hi"), clamp_allowed=clamp_allowed)
    words = declare_words(st, i, "pki", tokens, False)
    low = pk_int_lane(op, words, bits.get("op_sel", [0] * arity), clamp)
    high = pk_int_lane(op, words, bits.get("op_sel_hi", [1] * arity), clamp)
    st.lines.append(f"    uint valu{i} = {low} | ({high} << 16u);")
    st.vector[dst] = ("uint", f"valu{i}")


@form(r"(" + "|".join(DOT_OPS) + r") (v\d+), (.+)")
def dot(st, i, m):
    # v_dot2_f32_f16 sums two binary32 products of binary16 halves and a binary32 accumulator (neg_lo[2] negates it);
    # the integer forms sum exact products into 64 bits (see the dot_* helpers). op_sel and op_sel_hi pick halves for the
    # dot2 forms only; neg modifiers exist only on the binary16 form; the accumulator lane modifiers must stay default.
    op, dst, rest = m.groups()
    is_f16, is_dot2 = op == "v_dot2_f32_f16", op.startswith("v_dot2_")
    names = (("op_sel", "op_sel_hi") if is_dot2 else ()) + (("neg_lo", "neg_hi") if is_f16 else ())
    if int(dst[1:]) > 255:
        raise ValueError("Invalid dot-product operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    tokens, bits, clamp = parse_packed(rest, 3, names, clamp_allowed=True)
    if (bits.get("op_sel", [0] * 3)[2] or bits.get("op_sel_hi", [1] * 3)[2] != 1 or bits.get("neg_hi", [0] * 3)[2]):
        raise ValueError("Unsupported accumulator lane modifier on dot product")
    if is_f16:
        words = declare_words(st, i, "dotw", tokens[:2], True)
        if tokens[2] in F16_CONSTANT:
            accumulator = f"asfloat({struct.unpack('<I', struct.pack('<f', float(tokens[2])))[0]:#x}u)"
        elif re.fullmatch(r"-?\d+", tokens[2]):
            raise ValueError("An integer inline constant is not a binary32 accumulator")
        else:
            accumulator = f"asfloat({packed_word(st, tokens[2], f16=False)})"
        if bits.get("neg_lo", [0] * 3)[2]:
            accumulator = f"(-{accumulator})"
        terms = []
        for select, negate in (("op_sel", "neg_lo"), ("op_sel_hi", "neg_hi")):
            defaults = [0, 0, 0] if select == "op_sel" else [1, 1, 1]
            halves = [half_of(words[k], bits.get(select, defaults)[k], bits.get(negate, [0] * 3)[k]) for k in range(2)]
            terms.append(f"(widen16({halves[0]}) * widen16({halves[1]}))")
        expression = f"({terms[0]} + {terms[1]} + {accumulator})"
        st.lines.append(f"    precise float alu{i} = {'saturate(' + expression + ')' if clamp else expression};")
        st.vector[dst] = f"alu{i}"
        return
    signed = "_i32_" in op
    st.helpers.update(("dot_i64_add", "dot_i64_sat", op) if signed else ("dot_u64_add", "dot_u64_sat", op))
    sat = "true" if clamp else "false"
    if is_dot2:
        words = declare_words(st, i, "dotw", tokens, False)
        select = lambda name, default: bits.get(name, [default] * 3)
        a = [half_of(words[0], select("op_sel", 0)[0]), half_of(words[0], select("op_sel_hi", 1)[0])]
        b = [half_of(words[1], select("op_sel", 0)[1]), half_of(words[1], select("op_sel_hi", 1)[1])]
        call = f"{op}({a[0]}, {a[1]}, {b[0]}, {b[1]}, {words[2]}, {sat})"
    else:
        call = f"{op}(" + ", ".join(packed_word(st, t, f16=False) for t in tokens) + f", {sat})"
    st.lines.append(f"    uint valu{i} = {call};")
    st.vector[dst] = ("uint", f"valu{i}")


@form(r"v_pk_fmac_f16(?:_e32)? (v\d+), (v\d+), (v\d+)")
def pk_fmac_f16(st, i, m):
    # VOP2 packed fused multiply-accumulate (compute-stage.md, C-4): D.lo = fma(S0.lo, S1.lo, D.lo) and D.hi = fma(S0.hi,
    # S1.hi, D.hi), which is v_pk_fma_f16 D, S0, S1, D with the default op_sel and op_sel_hi. VOP2 has no modifiers;
    # src0 is a VGPR here, since what a packed instruction reads from the high half of a constant src0 is not modelled.
    dst, a, b = m.groups()
    pk_f16(st, i, re.fullmatch(r"v_pk_(fma)_f16 (v\d+), (.+)", f"v_pk_fma_f16 {dst}, {a}, {b}, {dst}"))


@form(r"v_pack_b32_f16(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+)")
def pack_b32_f16(st, i, m):
    # D = S1.f16 << 16 | S0.f16 (compute-stage.md, C-4): the low halves of the two sources, moved as bits (LLVM's
    # isCanonicalized passes the sources' canonicalization through, so the pack itself neither flushes nor quiets).
    # op_sel, neg and abs are not in this grammar; a constant source is read as packed_word reads it.
    dst, *tokens = m.groups()
    if int(dst[1:]) > 255:
        raise ValueError("Invalid pack destination")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    low, high = declare_words(st, i, "pkw", tokens, True)
    st.lines.append(f"    uint valu{i} = ({low} & 0xffffu) | (({high} & 0xffffu) << 16u);")
    st.vector[dst] = ("uint", f"valu{i}")
