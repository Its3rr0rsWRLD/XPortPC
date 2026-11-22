"""SOPC: 32-bit scalar comparisons that set SCC."""
from ..dispatch import form
from ..registers import scalar_u32, scalar_u64

SCALAR_COMPARE = {"eq": "==", "lg": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}


@form(r"s_cmp_(eq|lg|gt|ge|lt|le)_(u32|i32) ([^,]+), ([^,]+)")
def compare_32(st, i, m):
    # SCC = the comparison of two 32-bit scalar sources, unsigned or signed (RDNA ISA, SOPC).
    relation, kind, src0, src1 = m.groups()
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    if kind == "i32" and relation not in ("eq", "lg"):
        a, b = f"int({a})", f"int({b})"
    st.scc = f"({a} {SCALAR_COMPARE[relation]} {b})"


@form(r"s_cmp_(eq|lg)_u64 ([^,]+), ([^,]+)")
def compare_64(st, i, m):
    # SCC = S0 == S1 or S0 != S1 over the full 64-bit sources.
    relation, src0, src1 = m.groups()
    a0, a1 = scalar_u64(src0, st.scalar, st.pending)
    b0, b1 = scalar_u64(src1, st.scalar, st.pending)
    equal = f"(({a0} == {b0}) && ({a1} == {b1}))"
    st.scc = equal if relation == "eq" else f"(!{equal})"


@form(r"s_bitcmp(0|1)_(b32|b64) ([^,]+), ([^,]+)")
def bit_compare(st, i, m):
    # SCC = (S0[S1[4:0]] == 0) for bitcmp0, == 1 for bitcmp1; the b64 forms index with S1[5:0].
    value, width, src0, src1 = m.groups()
    index = scalar_u32(src1, st.scalar, st.pending)
    if width == "b32":
        word = scalar_u32(src0, st.scalar, st.pending)
        bit = f"(({word} >> ({index} & 31u)) & 1u)"
    else:
        a0, a1 = scalar_u64(src0, st.scalar, st.pending)
        st.helpers.add("s_lshr_b64")
        bit = f"(s_lshr_b64(uint2({a0}, {a1}), {index}).x & 1u)"
    st.scc = f"({bit} == {value}u)"
