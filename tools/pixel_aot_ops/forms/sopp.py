"""SOPP: no-ops, scheduling hints, wait counters and the program end."""
import re

from ..dispatch import form

HINT_LIMITS = {"s_clause": 0x3f, "s_setprio": 3, "s_sleep": 0x7f}


@form(r"(?:s_inst_prefetch|s_nop) (?:0x[0-9a-f]+|\d+)")
def no_op(st, i, m):
    pass


# The VOP1 no-op (from R0Y00/Xbox2Windows#565 by Rachel Amber) takes no operands and changes no state, so it lowers to
# nothing like s_nop. It is a VALU instruction, so it may not sit between the color export and s_endpgm.
@form(r"v_nop")
def vector_no_op(st, i, m):
    pass


# Scheduling hints with no effect on results. Each operand is limited to the width
# of its RDNA 2 field: clause length minus one, wave priority and sleep duration.
@form(r"(s_clause|s_setprio|s_sleep) (0x[0-9a-f]+|\d+)")
def scheduling_hint(st, i, m):
    if int(m[2], 0) > HINT_LIMITS[m[1]]:
        raise ValueError(f"Invalid {m[1]} operand")


@form(r"s_waitcnt lgkmcnt\(0\)")
def wait_lgkmcnt_zero(st, i, m):
    st.pending.clear()


@form(r"s_waitcnt vmcnt\((\d+)\)")
def wait_vmcnt(st, i, m):
    # vmcnt(N): all but the newest N samples and loads have completed (Lowering.vm_wait), so a result whose own load
    # is older than that is readable while a newer one is in flight (R0Y00/Xbox2Windows#176 by descent81). A count
    # above the six-bit gfx10 field is not an instruction.
    st.vm_wait(int(m[1]))


@form(r"s_waitcnt((?: (?:vmcnt|expcnt|lgkmcnt)\(\d+\))+)")
def wait_counters(st, i, m):
    # The counters named by one s_waitcnt, as the disassembler spells them (vmcnt expcnt lgkmcnt). Like the
    # two forms above, only a count of 0 is accepted: a nonzero count leaves loads in flight that lower() does
    # not model. expcnt waits for exports, which lower() emits as the return of main, so any count of its three-bit
    # field orders nothing in the translation (from R0Y00/Xbox2Windows#271 by Rachel Amber).
    fields = re.findall(r"(\w+)\((\d+)\)", m[1])
    if len({name for name, _ in fields}) != len(fields) or any(
            int(count) > 7 if name == "expcnt" else int(count) for name, count in fields):
        raise ValueError("Only zero wait counts without repeats are supported")
    if any(name == "lgkmcnt" for name, _ in fields):
        st.pending.clear()
    if any(name == "vmcnt" for name, _ in fields):
        st.vm_wait(0)


@form(r"s_waitcnt_expcnt (?:(?:null|s\d+), )?(0x[0-7]|[0-7])")
def wait_export_counter(st, i, m):
    # Exports are the return of main, so a wait for them orders nothing and its count, SGPR plus a three-bit
    # immediate, need not be known (from R0Y00/Xbox2Windows#271 by Rachel Amber).
    pass


@form(r"s_waitcnt_(vmcnt|lgkmcnt|vscnt) null, (0x[0-9a-f]+|\d+)")
def wait_split_counter(st, i, m):
    # The split forms wait until the counter is at most SGPR + immediate, and null reads as 0. They clear the
    # same state as the combined forms and accept a count of 0 only.
    op, count = m[1], int(m[2], 0)
    if count > 0xffff:
        raise ValueError("Invalid wait count immediate")
    if op == "vscnt":
        # vscnt counts stores, which orders nothing here: lower() accepts no store instruction.
        pass
    elif count:
        raise ValueError("Only zero wait counts are supported")
    elif op == "lgkmcnt":
        st.pending.clear()
    elif op == "vmcnt":
        st.vm_wait(0)


@form(r"s_waitcnt_depctr (?:0x[0-9a-f]{1,4}|(?:depctr_(?:hold_cnt|sa_sdst|va_vdst|va_sdst|va_ssrc|va_vcc|vm_vsrc)\(\d+\) ?)+)")
def wait_dependencies(st, i, m):
    # Orders VALU, SALU and VMEM register dependencies (the hazards RADV waits out). The translator emits each
    # instruction as a single assignment in program order, so every such dependency already holds.
    pass


@form(r"s_endpgm", when=lambda st, m: st.exported)
def end_program(st, i, m):
    st.ended = True
