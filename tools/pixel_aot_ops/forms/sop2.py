"""SOP2: 64-bit bitwise, shift and bit-mask forms, 32-bit bitfield extract and add/sub with carry."""
from ..dispatch import form
from ..registers import sgpr_name, sgpr_pair, scalar_u32, scalar_u64

SALU_BIT64 = {
    "and": "uint2({0} & {2}, {1} & {3})",
    "or": "uint2({0} | {2}, {1} | {3})",
    "xor": "uint2({0} ^ {2}, {1} ^ {3})",
    "andn2": "uint2({0} & ~{2}, {1} & ~{3})",
    "orn2": "uint2({0} | ~{2}, {1} | ~{3})",
}


@form(rf"s_({'|'.join(SALU_BIT64)})_b64 (s\[\d+:\d+\]), ([^,]+), ([^,]+)")
def bitwise_b64(st, i, m):
    op, dst, src0, src1 = m.groups()
    regs = sgpr_pair(dst)
    if st.pending.intersection(regs):
        raise ValueError("Write overlaps an outstanding scalar load")
    a0, a1 = scalar_u64(src0, st.scalar, st.pending)
    b0, b1 = scalar_u64(src1, st.scalar, st.pending)
    st.lines.append(f"    uint2 salu{i} = {SALU_BIT64[op].format(a0, a1, b0, b1)};")
    st.scalar[regs[0]], st.scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
    st.scc = f"((salu{i}.x | salu{i}.y) != 0u)"


@form(r"(s_lshl_b64|s_lshr_b64|s_ashr_i64|s_bfm_b64) (s\[\d+:\d+\]), ([^,]+), ([^,]+)")
def shift_b64(st, i, m):
    op, dst, src0, src1 = m.groups()
    regs = sgpr_pair(dst)
    if st.pending.intersection(regs):
        raise ValueError("Write overlaps an outstanding scalar load")
    shift = scalar_u32(src1, st.scalar, st.pending)
    if op == "s_bfm_b64":
        width = scalar_u32(src0, st.scalar, st.pending)
        st.helpers.update(("s_lshl_b64", "s_bfm_b64"))
        expr = f"s_bfm_b64({width}, {shift})"
    else:
        a0, a1 = scalar_u64(src0, st.scalar, st.pending, signed=(op == "s_ashr_i64"))
        st.helpers.add(op)
        expr = f"{op}(uint2({a0}, {a1}), {shift})"
    st.lines.append(f"    uint2 salu{i} = {expr};")
    st.scalar[regs[0]], st.scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
    if op != "s_bfm_b64":
        st.scc = f"((salu{i}.x | salu{i}.y) != 0u)"


@form(r"(s_bfe_u32|s_bfe_i32) (s\d+), ([^,]+), ([^,]+)")
def bitfield_extract(st, i, m):
    op, dst, src0, src1 = m.groups()
    sgpr_name(dst)
    if dst in st.pending:
        raise ValueError("Write overlaps an outstanding scalar load")
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    st.helpers.add(op)
    st.lines.append(f"    uint salu{i} = {op}({a}, {b});")
    st.scalar[dst] = ("uint", f"salu{i}")
    st.scc = f"(salu{i} != 0u)"


@form(r"s_(add|sub)_u32 (s\d+), ([^,]+), ([^,]+)")
def add_sub_u32(st, i, m):
    # D = S0 + S1 or S0 - S1 modulo 2^32; SCC is the carry out, or the borrow for sub (RDNA ISA, SOP2).
    # Only the unsigned forms are lowered: a loop counter needs no more.
    op, dst, src0, src1 = m.groups()
    sgpr_name(dst)
    if dst in st.pending:
        raise ValueError("Write overlaps an outstanding scalar load")
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    st.lines.append(f"    uint salu{i} = {a} {'+' if op == 'add' else '-'} {b};")
    st.scc = f"(salu{i} < {a})" if op == "add" else f"({a} < {b})"
    st.scalar[dst] = ("uint", f"salu{i}")
