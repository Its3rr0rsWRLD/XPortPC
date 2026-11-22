"""Scheduling hints (s_clause, s_setprio, s_sleep, s_nop) and the VALU no-op v_nop: controls only, no draw.

v_nop is from R0Y00/Xbox2Windows#565 by Rachel Amber."""
from .common import assembly, must_reject, translate


HINT_NAMES = ("s_clause", "s_setprio", "s_sleep")


def scheduling_hints():
    # Hints the compiler places between instructions. native_program ends the code at s_endpgm,
    # so s_code_end padding never reaches the translator and is not part of the fixture.
    program = assembly(False)
    program.insert(program.index("s_waitcnt vmcnt(0)"), "s_clause 0x1")
    program.insert(1, "s_setprio 2")
    program.insert(program.index("s_waitcnt vmcnt(0)"), "v_nop")
    program.insert(program.index("s_waitcnt vmcnt(0)"), "s_sleep 1")
    return program


def check_scheduling_hints():
    """Scheduling hints change timing only. Generated names carry the instruction index, so
    each hint must translate exactly like s_nop 0 at the same position."""
    plain = assembly(False)
    hinted = scheduling_hints()
    as_nops = [("s_nop 0" if line.split(" ")[0] in (*HINT_NAMES, "v_nop") else line)
               for line in hinted]
    assert translate(hinted) == translate(as_nops)
    nop = translate(["s_nop 0"] + plain)
    for hint, limit in (("s_clause", 0x3f), ("s_setprio", 3), ("s_sleep", 0x7f)):
        assert translate([f"{hint} {limit}"] + plain) == nop
        assert translate([f"{hint} {hex(limit)}"] + plain) == nop
        must_reject(translate, [f"{hint} {limit + 1}"] + plain)
    assert translate(["v_nop"] + plain) == nop
    must_reject(translate, ["v_nop 0"] + plain)
    # s_code_end stays unknown, and nothing may follow the program end or sit between the color
    # export and s_endpgm.
    must_reject(translate, ["s_code_end"] + plain)
    must_reject(translate, plain + ["s_code_end"])
    must_reject(translate, plain + ["s_nop 0"])
    must_reject(translate, plain[:-1] + ["s_setprio 0", plain[-1]])
    must_reject(translate, plain + ["v_nop"])
    must_reject(translate, plain[:-1] + ["v_nop", plain[-1]])


def controls(directory):
    check_scheduling_hints()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (scheduling_hints(), translate),
    ]
