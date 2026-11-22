"""VOP3-only integer and bit forms: v_bfi_b32, v_alignbit_b32, v_alignbyte_b32, v_perm_b32, the sum-of-absolute-differences
family (v_sad_u8, v_sad_hi_u8, v_sad_u16, v_sad_u32, v_msad_u8), v_lerp_u8, v_mad_u64_u32 and the 64-bit shifts
v_lshlrev_b64, v_lshrrev_b64 and v_ashrrev_i64.

Semantics: AMD RDNA 2 ISA guide, VOP3 pseudocode, in uint words (no value passes through a float type). None takes source
modifiers or clamp (llvm-mc assembles clamp on some, whose saturation is not established here, so clamp is refused
everywhere), and none has an e32 encoding.
- V_BFI_B32 D = (S0 & S1) | (~S0 & S2).
- V_ALIGNBIT_B32 D = ({S0, S1} >> S2[4:0])[31:0]; V_ALIGNBYTE_B32 D = ({S0, S1} >> (8 * S2[1:0]))[31:0]. S0 is the high word.
- V_PERM_B32 D.byte[i] = BYTE_PERMUTE({S0, S1}, S2.byte[i]): selector 0..3 pick bytes of S1, 4..7 bytes of S0, 8..11 give 0xff
  when bit 15, 31, 47 or 63 of {S0, S1} is set and 0 otherwise, 12 gives 0 and 13 or more gives 0xff.
- V_SAD_U8 D = S2 + sum of |S0.byte[i] - S1.byte[i]|; V_SAD_HI_U8 D = (sum << 16) + S2; V_SAD_U16 D = S2 + |S0.lo16 - S1.lo16|
  + |S0.hi16 - S1.hi16|; V_SAD_U32 D = S2 + |S0 - S1| (unsigned difference); V_MSAD_U8 is V_SAD_U8 but a byte whose S1
  (reference) byte is zero adds nothing. All wrap modulo 2^32.
- V_LERP_U8 D.byte[i] = (S0.byte[i] + S1.byte[i] + S2.byte[i][0]) >> 1: the rounding bit is bit 0 of each byte of S2.
- V_MAD_U64_U32 {carry, D.u64} = S0.u32 * S1.u32 + S2.u64 (65-bit sum); the carry goes per lane to the lane mask like
  v_add_co_u32. A 64-bit source is v[N:M], s[N:M] (even) or an inline constant 0..64. The signed v_mad_i64_i32 is not lowered: what
  its carry out holds is not established here. v_cvt_pk_u8_f32 is not lowered: its float-to-byte rounding is not established.
- V_LSHLREV_B64 D = S1.u64 << S0[5:0]; V_LSHRREV_B64 the logical and V_ASHRREV_I64 the arithmetic right shift; the count is a
  32-bit source (S0), the value a 64-bit source (S1).
"""
import re

from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import LANE_MASK, lane_mask, registers, sgpr_pair, vector_u32

SALU_HELPERS["v_perm_byte"] = (
    "uint v_perm_byte(uint hi, uint lo, uint sel) {\n"
    "    sel &= 255u;\n"
    "    if (sel >= 13u) return 0xffu;\n"
    "    if (sel == 12u) return 0u;\n"
    "    if (sel >= 8u) {\n"
    "        uint word = (sel & 2u) != 0u ? hi : lo;\n"
    "        uint bit = (sel & 1u) != 0u ? 31u : 15u;\n"
    "        return ((word >> bit) & 1u) != 0u ? 0xffu : 0u;\n"
    "    }\n"
    "    return ((sel >= 4u ? hi : lo) >> ((sel & 3u) * 8u)) & 0xffu;\n"
    "}"
)
SALU_HELPERS["v_absdiff_u32"] = "uint v_absdiff_u32(uint a, uint b) {\n    return a > b ? a - b : b - a;\n}"


def byte_of(word, n):
    return f"(({word} >> {8 * n}u) & 0xffu)"


def sad_bytes(a, b, masked):
    terms = []
    for n in range(4):
        term = f"v_absdiff_u32({byte_of(a, n)}, {byte_of(b, n)})"
        terms.append(f"({byte_of(b, n)} != 0u ? {term} : 0u)" if masked else term)
    return " + ".join(terms)


def ternary_expression(op, a, b, c):
    if op == "bfi_b32":
        return f"(({a} & {b}) | (~{a} & {c}))"
    if op == "alignbit_b32":
        # (a << 1) << (31 - n) is a << (32 - n) without the undefined shift by 32 when n is 0.
        return f"(({b} >> ({c} & 31u)) | (({a} << 1u) << (31u - ({c} & 31u))))"
    if op == "alignbyte_b32":
        return f"((({c} & 3u) == 0u) ? {b} : ({b} >> (({c} & 3u) * 8u)) | ({a} << (32u - ({c} & 3u) * 8u)))"
    if op == "perm_b32":
        return " | ".join(f"(v_perm_byte({a}, {b}, {byte_of(c, n)}) << {8 * n}u)" for n in range(4))
    if op == "sad_u8":
        return f"({sad_bytes(a, b, False)} + {c})"
    if op == "msad_u8":
        return f"({sad_bytes(a, b, True)} + {c})"
    if op == "sad_hi_u8":
        return f"(({sad_bytes(a, b, False)}) << 16u) + {c}"
    if op == "sad_u16":
        return (f"(v_absdiff_u32({a} & 0xffffu, {b} & 0xffffu) + v_absdiff_u32({a} >> 16u, {b} >> 16u) + {c})")
    if op == "sad_u32":
        return f"(v_absdiff_u32({a}, {b}) + {c})"
    if op == "lerp_u8":
        return " | ".join(f"((({byte_of(a, n)} + {byte_of(b, n)} + (({c} >> {8 * n}u) & 1u)) >> 1u) << {8 * n}u)"
                          for n in range(4))
    raise KeyError(op)


TERNARY_OPS = ("bfi_b32", "alignbit_b32", "alignbyte_b32", "perm_b32", "sad_u8", "sad_hi_u8", "sad_u16", "sad_u32",
               "msad_u8", "lerp_u8")


@form(r"v_(" + "|".join(TERNARY_OPS) + r")(_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)")
def ternary(st, i, m):
    op, _, dst, first, second, third = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b, c = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (first, second, third))
    if op == "perm_b32":
        st.helpers.add("v_perm_byte")
    if op.startswith(("sad", "msad")):
        st.helpers.add("v_absdiff_u32")
    st.lines.append(f"    uint valu{i} = {ternary_expression(op, a, b, c)};")
    st.vector[dst] = ("uint", f"valu{i}")


def pair_operand(token, st):
    """Low and high words of a 64-bit integer source: v[N:M] (any alignment, as in valu_f64), an even s[N:M], or an inline
    constant 0..64. A literal or a negative constant is refused: how it extends to 64 bits is not established here."""
    if pair := re.fullmatch(r"([vs])\[(\d+):(\d+)\]", token):
        names = ([f"v{n}" for n in registers(pair[2], pair[3], 2)] if pair[1] == "v" else sgpr_pair(token))
        lo, hi = (vector_u32(n, st.scalar, st.vector, st.pending, st.sample_pending) for n in names)
        return lo, hi
    if re.fullmatch(r"\d+", token) and int(token) <= 64:
        return f"{int(token)}u", "0u"
    raise ValueError(f"Unsupported 64-bit operand {token}")


def pair_destination(token, st):
    pair = re.fullmatch(r"v\[(\d+):(\d+)\]", token)
    if not pair:
        raise ValueError(f"Expected a 64-bit vector register pair, got {token}")
    names = [f"v{n}" for n in registers(pair[1], pair[2], 2)]
    if st.sample_dest.intersection(names):
        raise ValueError("Write overlaps an outstanding sample")
    return names


@form(r"v_(lshlrev_b64|lshrrev_b64|ashrrev_i64)(?:_e64)? (v\[\d+:\d+\]), ([^,\s]+), ([^,\s]+)")
def shift64(st, i, m):
    op, dst, count_token, value_token = m.groups()
    names = pair_destination(dst, st)
    count = vector_u32(count_token, st.scalar, st.vector, st.pending, st.sample_pending)
    lo, hi = pair_operand(value_token, st)
    st.lines += [f"    uint shn{i} = {count} & 63u;", f"    uint shl{i} = {lo};", f"    uint shh{i} = {hi};",
                 f"    uint shs{i} = shn{i} & 31u;"]
    low, high = f"shl{i}", f"shh{i}"
    n, s = f"shn{i}", f"shs{i}"
    # (x << 1) << (31 - s) is x << (32 - s) and is zero for s = 0, so no shift by 32 is evaluated.
    if op == "lshlrev_b64":
        out_lo = f"({n} >= 32u ? 0u : {low} << {s})"
        out_hi = f"({n} >= 32u ? {low} << {s} : (({high} << {s}) | (({low} >> 1u) >> (31u - {s}))))"
    elif op == "lshrrev_b64":
        out_lo = f"({n} >= 32u ? {high} >> {s} : (({low} >> {s}) | (({high} << 1u) << (31u - {s}))))"
        out_hi = f"({n} >= 32u ? 0u : {high} >> {s})"
    else:
        sign = f"asuint(asint({high}) >> 31)"
        out_lo = (f"({n} >= 32u ? asuint(asint({high}) >> {s}) : (({low} >> {s}) | (({high} << 1u) << (31u - {s}))))")
        out_hi = f"({n} >= 32u ? {sign} : asuint(asint({high}) >> {s}))"
    st.lines += [f"    uint valu{i}l = {out_lo};", f"    uint valu{i}h = {out_hi};"]
    st.vector[names[0]], st.vector[names[1]] = ("uint", f"valu{i}l"), ("uint", f"valu{i}h")


@form(rf"v_mad_u64_u32(?:_e64)? (v\[\d+:\d+\]), {LANE_MASK}, ([^,\s]+), ([^,\s]+), ([^,\s]+)")
def mad_u64(st, i, m):
    dst, carry, first, second, third = m.groups()
    regs = lane_mask(carry)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid integer operation")
    names = pair_destination(dst, st)
    a, b = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (first, second))
    clo, chi = pair_operand(third, st)
    st.helpers.add("mul_hi_u32")
    st.lines += [f"    uint mda{i} = {a};", f"    uint mdb{i} = {b};", f"    uint mdl{i} = {clo};", f"    uint mdh{i} = {chi};",
                 f"    uint mpl{i} = mda{i} * mdb{i};", f"    uint mph{i} = mul_hi_u32(mda{i}, mdb{i});",
                 f"    uint valu{i}l = mpl{i} + mdl{i};", f"    uint mt{i} = mph{i} + mdh{i};",
                 f"    uint valu{i}h = mt{i} + (valu{i}l < mpl{i} ? 1u : 0u);",
                 f"    bool cmp{i} = mt{i} < mph{i} || valu{i}h < mt{i};"]
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.vector[names[0]], st.vector[names[1]] = ("uint", f"valu{i}l"), ("uint", f"valu{i}h")
