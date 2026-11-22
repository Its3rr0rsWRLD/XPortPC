"""The execution mask: saving EXEC, whole-quad mode and the restore that ends it (SOP1/SOP2 on exec)."""
from ..dispatch import form
from ..registers import registers


@form(r"s_mov_b64 s\[(\d+):(\d+)\], exec")
def save_exec(st, i, m):
    regs = registers(*m.groups(), 2)
    for n in regs:
        if f"s{n}" in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        st.scalar[f"s{n}"] = (st.mask, n-regs.start)


@form(r"s_wqm_b64 exec, exec", when=lambda st, m: st.mask == "entry")
def whole_quad_mode(st, i, m):
    st.mask = "quad"
    st.scc = None


@form(r"s_and_b64 exec, exec, s\[(\d+):(\d+)\]")
def restore_exec(st, i, m):
    pair = registers(*m.groups(), 2)
    if st.mask != "quad" or [st.scalar.get(f"s{n}") for n in pair] != [("entry",0),("entry",1)]:
        raise ValueError("Unsupported execution mask")
    st.mask = "entry"
    st.scc = None
