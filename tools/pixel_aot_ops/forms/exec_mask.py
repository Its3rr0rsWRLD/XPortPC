"""The execution mask: saving EXEC, whole-quad mode and the restore that ends it (SOP1/SOP2 on exec). EXEC is this
lane's bit `st.ex` (docs/design/control-flow.md, CF-2 section 2); a saved mask is a lane mask like a compare's."""
from ..dispatch import form
from ..registers import registers


@form(r"s_mov_b64 s\[(\d+):(\d+)\], exec")
def save_exec(st, i, m):
    regs = registers(*m.groups(), 2)
    for n in regs:
        if f"s{n}" in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        st.scalar[f"s{n}"] = ("condition", st.ex, n-regs.start, 2)


# Whole-quad mode turns on every lane of a quad with an active lane, so it keeps ex true and could only re-enable an
# inactive lane: refused unless the lane is provably active. Entering it twice is refused as before.
@form(r"s_wqm_b64 exec, exec", when=lambda st, m: st.ex == "true" and not st.wqm)
def whole_quad_mode(st, i, m):
    st.wqm = True
    st.scc = None


@form(r"s_and_b64 exec, exec, s\[(\d+):(\d+)\]")
def restore_exec(st, i, m):
    # EXEC &= a saved mask (the fixture's return from whole-quad mode) or another tracked lane mask. The lane's bit
    # stays true for a mask saved while it was active. Whole-quad mode is left: the result is no wider than the mask.
    pair = [f"s{n}" for n in registers(*m.groups(), 2)]
    mask = st.scalar.get(pair[0])
    if (st.pending.intersection(pair) or not isinstance(mask, tuple) or mask[0] != "condition"
            or [st.scalar.get(r) for r in pair] != [("condition", mask[1], j, 2) for j in range(2)]):
        raise ValueError("Unsupported execution mask")
    st.exec_and(i, mask[1])
    st.wqm = False
    st.scc = None
