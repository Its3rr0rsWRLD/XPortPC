"""VOP3P: mixed-precision fused multiply-add (v_fma_mix_f32, v_fma_mixlo_f16, v_fma_mixhi_f16)."""
import re

from ..dispatch import form
from ..hlsl import PREAMBLE
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
    if st.mask != "entry":
        raise ValueError("Invalid arithmetic operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    old = st.vector.get(dst)
    if op != "mix_f32" and old is not None and tracked_word(old) is None:
        raise ValueError("Unsupported arithmetic destination")
    if "fma_mix" not in st.helpers:
        st.helpers.add("fma_mix")
        st.lines.insert(st.lines.index(PREAMBLE), FMA_MIX_HELPERS)
    selects = [int(x or 0) for x in (s0, s1, s2)]
    highs = [int(x or 0) for x in (h0, h1, h2)]
    a, b, c = (fma_mix_source(t, h, s, st.scalar, st.vector, st.pending, st.sample_pending)
               for t, h, s in zip(tokens, highs, selects))
    wide = op == "mix_f32"
    expression = f"fma_mix_round({a}, {b}, {c}, {'true' if wide else 'false'})"
    if clamp:
        expression = f"fma_mix_sat({expression}, {'true' if wide else 'false'})"
    if op == "mixlo_f16":
        keep = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
        expression = f"{keep} | {expression}"
    elif op == "mixhi_f16":
        keep = f"({tracked_word(old)} & 0xffffu)" if old is not None else "0u"
        expression = f"{keep} | ({expression} << 16u)"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = asfloat({expression});")
