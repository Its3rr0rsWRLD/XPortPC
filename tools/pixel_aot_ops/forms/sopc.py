"""SOPC: 32-bit scalar comparisons that set SCC."""
from ..dispatch import form
from ..registers import scalar_u32

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
