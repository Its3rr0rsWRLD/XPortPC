"""Packing integer conversions (VOP3): v_cvt_pk_u16_u32 and v_cvt_pk_i16_i32.

D[15:0] is S0 and D[31:16] is S1, each converted to 16 bits with saturation: unsigned to [0, 0xffff], signed to
[-0x8000, 0x7fff] (RDNA 2 ISA guide, V_CVT_PK_U16_U32 = {uint32_to_uint16(S1), uint32_to_uint16(S0)}). ACO masks both
sources to 16 bits before it uses v_cvt_pk_u16_u32 to pack two halves on GFX6/7, which a truncating pack would not
need. The forms take no source modifiers and no clamp (llvm-mc refuses both); the sources are unsigned words.
"""
from ..dispatch import form
from ..registers import vector_u32


@form(r"v_cvt_pk_(u16_u32|i16_i32)(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+)")
def pack_16(st, i, m):
    kind, dst, *tokens = m.groups()
    if st.ex != "true":
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    lo, hi = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens)
    if kind == "u16_u32":
        expression = f"(min({lo}, 0xffffu) | (min({hi}, 0xffffu) << 16u))"
    else:
        clamp = "(asuint(clamp(asint({0}), -32768, 32767)) & 0xffffu)"
        expression = f"({clamp.format(lo)} | ({clamp.format(hi)} << 16u))"
    st.lines.append(f"    uint valu{i} = {expression};")
    st.vector[dst] = ("uint", f"valu{i}")
