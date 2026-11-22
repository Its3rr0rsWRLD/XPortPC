"""SOP2: 64-bit bitwise, shift and bit-mask forms, 32-bit bitfield extract and add/sub with carry, s_cselect_b64 and the
64-bit bitfield extracts. s_bfe_u64/s_bfe_i64 take a 64-bit S0 and a 32-bit control word: the offset is S1[5:0], the
width S1[22:16] and SCC = (D != 0). A width of zero gives zero; a field running past bit 63 gives S0 >> offset (the same
convention as the 32-bit helper). s_cselect_b64 takes S0 when SCC is set and leaves SCC alone."""
from ..dispatch import form
from .exec_mask import UniformMask, is_mask, mask_op
from ..hlsl import SALU_HELPERS
from ..registers import sgpr_name, sgpr_pair, scalar_u32, scalar_u64

SALU_BIT64 = {
    "and": "uint2({0} & {2}, {1} & {3})",
    "or": "uint2({0} | {2}, {1} | {3})",
    "xor": "uint2({0} ^ {2}, {1} ^ {3})",
    "andn2": "uint2({0} & ~{2}, {1} & ~{3})",
    "orn2": "uint2({0} | ~{2}, {1} | ~{3})",
    "nand": "uint2(~({0} & {2}), ~({1} & {3}))",
    "nor": "uint2(~({0} | {2}), ~({1} | {3}))",
    "xnor": "uint2(~({0} ^ {2}), ~({1} ^ {3}))",
}


# A source that is EXEC or a lane mask (a compare's or a saved EXEC) makes the operation a lane-mask operation:
# exec_mask.mask_op, the bool operation on this lane's bits (docs/design/control-flow.md, CF-2 section 3).
@form(rf"s_({'|'.join(SALU_BIT64)})_b64 (s\[\d+:\d+\]), ([^,]+), ([^,]+)",
      when=lambda st, m: is_mask(st, m[3]) or is_mask(st, m[4]))
def lane_mask_b64(st, i, m):
    mask_op(st, i, *m.groups())


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


SALU_HELPERS.update({
    "s_bfe_u64": (
        "uint2 s_bfe_u64(uint2 v, uint ctrl) {\n"
        "    uint off = ctrl & 63u;\n"
        "    uint w = (ctrl >> 16) & 127u;\n"
        "    if (w == 0u) return uint2(0u, 0u);\n"
        "    if (off + w < 64u) return s_lshr_b64(s_lshl_b64(v, 64u - off - w), 64u - w);\n"
        "    return s_lshr_b64(v, off);\n"
        "}"
    ),
    "s_bfe_i64": (
        "uint2 s_bfe_i64(uint2 v, uint ctrl) {\n"
        "    uint off = ctrl & 63u;\n"
        "    uint w = (ctrl >> 16) & 127u;\n"
        "    if (w == 0u) return uint2(0u, 0u);\n"
        "    if (off + w < 64u) return s_ashr_i64(s_lshl_b64(v, 64u - off - w), 64u - w);\n"
        "    return s_ashr_i64(v, off);\n"
        "}"
    ),
})


@form(r"(s_bfe_u64|s_bfe_i64) (s\[\d+:\d+\]), ([^,]+), ([^,]+)")
def bitfield_extract_64(st, i, m):
    op, dst, src0, src1 = m.groups()
    regs = sgpr_pair(dst)
    if st.pending.intersection(regs):
        raise ValueError("Write overlaps an outstanding scalar load")
    a0, a1 = scalar_u64(src0, st.scalar, st.pending)
    ctrl = scalar_u32(src1, st.scalar, st.pending)
    st.helpers.update(("s_lshl_b64", "s_lshr_b64", op) if op == "s_bfe_u64" else ("s_lshl_b64", "s_ashr_i64", op))
    st.lines.append(f"    uint2 salu{i} = {op}(uint2({a0}, {a1}), {ctrl});")
    st.scalar[regs[0]], st.scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
    st.scc = f"((salu{i}.x | salu{i}.y) != 0u)"


@form(r"s_cselect_b64 (s\[\d+:\d+\]), ([^,]+), ([^,]+)")
def select_64(st, i, m):
    dst, src0, src1 = m.groups()
    regs = sgpr_pair(dst)
    if st.pending.intersection(regs):
        raise ValueError("Write overlaps an outstanding scalar load")
    if st.scc is None:
        raise ValueError("Select requires a tracked SCC")
    a0, a1 = scalar_u64(src0, st.scalar, st.pending)
    b0, b1 = scalar_u64(src1, st.scalar, st.pending)
    st.lines.append(f"    uint2 salu{i} = {st.scc} ? uint2({a0}, {a1}) : uint2({b0}, {b1});")
    st.scalar[regs[0]], st.scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
    if src0 in ("-1", "0") and src1 in ("-1", "0"):
        # 0 or all ones: still the same data words, and also a lane mask, the same bit for every lane (CF-2b).
        bit = f"(salu{i}.x != 0u)"
        st.scalar[regs[0]], st.scalar[regs[1]] = (UniformMask(st.scalar[r], bit) for r in regs)
