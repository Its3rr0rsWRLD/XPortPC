"""SOPP: no-ops, scheduling hints, wait counters and the program end."""
import re

from ..dispatch import form

HINT_LIMITS = {"s_clause": 0x3f, "s_setprio": 3, "s_sleep": 0x7f}


@form(r"(?:s_inst_prefetch|s_nop) (?:0x[0-9a-f]+|\d+)")
def no_op(st, i, m):
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


@form(r"s_waitcnt vmcnt\(0\)")
def wait_vmcnt_zero(st, i, m):
    st.sample_pending = False
    st.sample_dest.clear()


@form(r"s_waitcnt((?: (?:vmcnt|expcnt|lgkmcnt)\(\d+\))+)")
def wait_counters(st, i, m):
    # The counters named by one s_waitcnt, as the disassembler spells them (vmcnt expcnt lgkmcnt). Like the
    # two forms above, only a count of 0 is accepted: a nonzero count leaves loads in flight that lower() does
    # not model. expcnt(0) waits for exports, and the only export is the last instruction.
    fields = re.findall(r"(\w+)\((\d+)\)", m[1])
    if len({name for name, _ in fields}) != len(fields) or any(int(count) for _, count in fields):
        raise ValueError("Only zero wait counts without repeats are supported")
    if any(name == "lgkmcnt" for name, _ in fields):
        st.pending.clear()
    if any(name == "vmcnt" for name, _ in fields):
        st.sample_pending = False
        st.sample_dest.clear()


@form(r"s_waitcnt_(vmcnt|expcnt|lgkmcnt|vscnt) null, (0x[0-9a-f]+|\d+)")
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
        st.sample_pending = False
        st.sample_dest.clear()
    # expcnt(0) waits for exports; the only export is the last instruction.


@form(r"s_waitcnt_depctr (?:0x[0-9a-f]{1,4}|(?:depctr_(?:hold_cnt|sa_sdst|va_vdst|va_sdst|va_ssrc|va_vcc|vm_vsrc)\(\d+\) ?)+)")
def wait_dependencies(st, i, m):
    # Orders VALU, SALU and VMEM register dependencies (the hazards RADV waits out). The translator emits each
    # instruction as a single assignment in program order, so every such dependency already holds.
    pass


@form(r"s_endpgm", when=lambda st, m: st.exported)
def end_program(st, i, m):
    st.ended = True
