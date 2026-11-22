"""Draw family `export_wait`: export-counter waits (s_waitcnt_expcnt, s_waitcnt expcnt(N)) before the program and
between the done export and s_endpgm (from R0Y00/Xbox2Windows#271 by Rachel Amber). Exports are the return of main, so
the waits change nothing: the lowering must be the reference program's, and the draw its colors."""
import subprocess

from .common import assembly, must_reject, translate

WAITS = ("s_waitcnt_expcnt null, 0x0", "s_waitcnt_expcnt null, 0x3", "s_waitcnt_expcnt null, 0",
         "s_waitcnt_expcnt s0, 0x0", "s_waitcnt_expcnt 0x3", "s_waitcnt_expcnt 0",
         "s_waitcnt expcnt(0)", "s_waitcnt expcnt(7)")


def program_with(wait):
    return [wait] + assembly(False)[:-1] + [wait, "s_endpgm"]


def controls(directory):
    program = assembly(False)
    for wait in WAITS:
        assert "return float4(" in translate([wait] + program)
        assert translate(program[:-1] + [wait, program[-1]]) == translate(program)
    must_reject(translate, program + ["s_waitcnt_expcnt null, 0"])  # after s_endpgm
    for bad in ("s_waitcnt_expcnt null, 0x8", "s_waitcnt_expcnt null, 8", "s_waitcnt_expcnt 0x8",
                "s_waitcnt_expcnt invalid", "s_waitcnt_expcnt null, invalid", "s_waitcnt expcnt(8)"):
        must_reject(translate, [bad] + program)
    # Only the export-counter wait and the hints may follow the done export.
    for bad in ("s_waitcnt vmcnt(0)", "s_waitcnt_lgkmcnt null, 0", "s_waitcnt vmcnt(0) expcnt(0)",
                "s_mov_b32 s40, 1"):
        must_reject(translate, program[:-1] + [bad, program[-1]])


def binary_fixtures():
    return [(program_with("s_waitcnt_expcnt null, 0"), translate)]


def draw(directory, compiler, renderer, backend):
    source, shader = directory / "export_wait.hlsl", directory / "export_wait.cso"
    for wait in ("s_waitcnt_expcnt null, 0x3", "s_waitcnt expcnt(0)"):
        source.write_text(translate(program_with(wait)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        result = subprocess.run([renderer, backend, "--check-pixel", shader, "rgba"])
        if result.returncode:
            return result.returncode
    return 0
