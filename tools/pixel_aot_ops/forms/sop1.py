"""SOP1 and SOPK: 64-bit unary scalar forms and 32-bit scalar moves."""
from ..dispatch import form
from ..registers import sgpr_pair, scalar_u64


@form(r"s_(cmov|not|brev)_b64 (s\[\d+:\d+\]), ([^,]+)")
def unary_b64(st, i, m):
    op, dst, src = m.groups()
    regs = sgpr_pair(dst)
    if st.pending.intersection(regs):
        raise ValueError("Write overlaps an outstanding scalar load")
    s0, s1 = scalar_u64(src, st.scalar, st.pending)
    if op == "cmov":
        if st.scc is None:
            raise ValueError("Conditional move requires a tracked SCC")
        d0, d1 = scalar_u64(dst, st.scalar, st.pending)
        expr = f"({st.scc} ? uint2({s0}, {s1}) : uint2({d0}, {d1}))"
    elif op == "not":
        expr = f"uint2(~{s0}, ~{s1})"
    else:
        expr = f"uint2(reversebits({s1}), reversebits({s0}))"
    st.lines.append(f"    uint2 salu{i} = {expr};")
    st.scalar[regs[0]], st.scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
    if op == "not":
        st.scc = f"((salu{i}.x | salu{i}.y) != 0u)"


@form(r"(s_mov_b32|s_movk_i32) (s\d+|m0), (s\d+|0x[0-9a-f]+|\d+)")
def move_32(st, i, m):
    op, dst, src = m.groups()
    if src in st.pending or dst in st.pending:
        raise ValueError("Unresolved scalar memory dependency")
    val = st.scalar[src] if src.startswith("s") else int(src, 0)
    if op == "s_movk_i32":
        if not isinstance(val, int) or not 0 <= val <= 0xffff:
            raise ValueError("Invalid movk immediate")
        val = (val if val < 0x8000 else val - 0x10000) & 0xffffffff
    st.scalar[dst] = val
