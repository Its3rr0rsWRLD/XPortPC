"""Vector bit forms: v_bfe_u32 and v_bfe_i32 (VOP3), v_bfm_b32 and v_bcnt_u32_b32 (VOP3), and the bit scans
v_ffbh_u32, v_ffbh_i32 and v_ffbl_b32 (VOP1 and VOP3). (v_bfrev_b32 is in valu_int.)

Semantics: AMD RDNA 2 ISA guide, VOP3 pseudocode. The offset is S1[4:0] and the width S2[4:0]; v_bfe_u32 gives
(S0 >> offset) & ((1 << width) - 1), v_bfe_i32 the same field of an arithmetic shift, sign-extended from bit
width - 1. A width of 0 gives 0. The forms are integer forms: they take no source modifiers and no clamp (llvm-mc
refuses both), and each source is read as the unsigned word it holds (registers.vector_u32).

v_bfm_b32 gives ((1 << S0[4:0]) - 1) << S1[4:0]; v_bcnt_u32_b32 gives popcount(S0) + S1 modulo 2^32. The scans return
the bit position counted from the top (ffbh) or the bottom (ffbl), or 0xffffffff when no bit is found: v_ffbh_u32
looks for the first 1, v_ffbh_i32 for the first bit that differs from the sign bit (so 0 and -1 find none).
Unary forms take both encodings; the two-source forms are VOP3 only (llvm-mc refuses _e32). None takes source
modifiers or clamp.

Ported from R0Y00/Xbox2Windows#436 by Joacoorandom (the expressions and the v_bfe_i32 and v_ffbh_u32 helpers), moved to
the ("uint", expr) register model: no value is routed through a float type.
"""
from ..dispatch import form
from ..registers import inactive
from ..hlsl import SALU_HELPERS
from ..registers import vector_u32

SALU_HELPERS["v_bfe_i32"] = (
    "uint v_bfe_i32(uint src, uint off, uint width) {\n"
    "    off &= 31u; width &= 31u;\n"
    "    if (width == 0u) return 0u;\n"
    "    if (off + width < 32u) return asuint(asint(src << (32u - off - width)) >> (32u - width));\n"
    "    return asuint(asint(src) >> off);\n"
    "}"
)
SALU_HELPERS["v_ffbh_u32"] = (
    "uint v_ffbh_u32(uint src) {\n"
    "    return src == 0u ? 0xffffffffu : 31u - uint(firstbithigh(src));\n"
    "}"
)

BITS_BINARY = {
    "v_bfm_b32": "(((1u << ({0} & 31u)) - 1u) << ({1} & 31u))",
    "v_bcnt_u32_b32": "(countbits({0}) + {1})",
}
BITS_UNARY = {
    "v_ffbh_u32": "v_ffbh_u32({0})",
    "v_ffbh_i32": "v_ffbh_u32((({0} & 0x80000000u) != 0u) ? ~{0} : {0})",
    "v_ffbl_b32": "uint(firstbitlow({0}))",
}


@form(r"v_bfe_(u32|i32)(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)")
def bitfield_extract(st, i, m):
    kind, dst, *tokens = m.groups()
    if inactive(st):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b, c = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens)
    if kind == "u32":
        expression = f"(({a} >> ({b} & 31u)) & ((1u << ({c} & 31u)) - 1u))"
    else:
        st.helpers.add("v_bfe_i32")
        expression = f"v_bfe_i32({a}, {b}, {c})"
    st.lines.append(f"    uint valu{i} = {expression};")
    st.vector[dst] = ("uint", f"valu{i}")


@form(rf"({'|'.join(BITS_BINARY)})(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+)")
def bits_binary(st, i, m):
    op, dst, *tokens = m.groups()
    if inactive(st):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens)
    st.lines.append(f"    uint valu{i} = {BITS_BINARY[op].format(a, b)};")
    st.vector[dst] = ("uint", f"valu{i}")


@form(rf"({'|'.join(BITS_UNARY)})(?:_e32|_e64)? (v\d+), ([^,\s]+)")
def bit_scan(st, i, m):
    op, dst, token = m.groups()
    if inactive(st):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = vector_u32(token, st.scalar, st.vector, st.pending, st.sample_pending)
    if op != "v_ffbl_b32":
        st.helpers.add("v_ffbh_u32")
    st.lines.append(f"    uint valu{i} = {BITS_UNARY[op].format(word)};")
    st.vector[dst] = ("uint", f"valu{i}")
