"""Draw family `cf2_discard`: pixel_aot_check.py draw --family cf2_discard.

CF-2d (docs/design/control-flow.md, CF-2 sections 3 and 4, card CF-2d): discard. The valid-mask bit of the final
`exp ... done vm` kills a lane that is off in EXEC, so a lane that may be inactive there is lowered as
`if (!ex) discard;` before the return. A branch to the all-lanes-dead block (`exp null off, off, off, off done vm;
s_endpgm`) is not taken: from `s_cbranch_execz` after a top-level `v_cmpx` kill, and from `s_cbranch_scc0` after the
kill of the exact mask (`s_andn2_b64 Sexact, Sexact, M`), in whole-quad mode or inside a divergent if; after it EXEC
may only narrow, so a killed lane stays off. A kill of an outer save inside a skipped region does not poison it (the
lanes the wave skipped for keep their bit). A packed pair exported by a lane must have been packed under a bit the
export's implies. A program whose only export is `exp null` (a depth-only pass) has a void main.

The programs are written in ACO's shapes (swapchain circle, render_octomap splat, dynamicrenderinglocalread,
shadowmappingcascade scene / mobile_nerf raster, shadowmappingcascade depthpass) and render the 8x8 pixel case. A
discarded pixel keeps the clear value (-1, -1, -1, -1). Each program has wrong references that must each be reported
as a pixel_mismatch: the discard ignored, every pixel discarded, the discard decided per quad, and per program the
kill inverted or a dead lane revived by the outer restore."""
import subprocess

from .cf2_skip import f32, outputs, pixels, case_bytes, targets_only
from .common import translate, with_constants

CLEAR = [-1.0] * 4
NULL = ["exp null off, off, off, off done vm", "s_endpgm"]


def with_null(program, label):
    return program + [f"{label}:", *NULL]


def wqm_program(body):
    """The common program without leaving whole-quad mode: the exact mask is saved in s[50:51] before
    s_wqm_b64, the sample runs in whole-quad mode, then `body` (which must leave it) and the export."""
    return [line for line in with_constants(body) if line != "s_and_b64 exec, exec, s[50:51]"]


def per_quad(live, keep_any):
    """The discard decided for the whole quad: dead when any lane is (keep_any False), or kept when any lane lives."""
    def decided(p):
        lanes = [live(q) for q in p.quad()]
        return any(lanes) if keep_any else all(lanes)
    return decided


def kill_bugs(live, values, extra=()):
    """The wrong references every kill program has: the discard ignored, every pixel discarded, the discard
    decided per quad (both ways); and the program's own."""
    return [
        lambda p: values(p),
        lambda p: CLEAR,
        lambda p: values(p) if per_quad(live, False)(p) else CLEAR,
        lambda p: values(p) if per_quad(live, True)(p) else CLEAR,
        *extra,
    ]


def killed(live, values):
    return lambda p: values(p) if live(p) else CLEAR


# --- a top-level v_cmpx kill and a skip to the dead block (swapchain_present_timing circle) -----------------------------
TOP = [
    "v_cmpx_lt_f32_e32 s44, v12",  # live = T < R
    "s_cbranch_execz BB1_9",
    "BB1_1:",
    "v_cmp_lt_f32_e32 vcc_lo, s45, v13",
    "v_cndmask_b32_e64 v22, 0, 1.0, vcc_lo",
    *outputs("2.0", "v22", "4.0", "1.0"),
]


def top_live(p):
    return f32(p.k[0]) < p.R


def top_values(p):
    return [2.0, float(f32(p.k[1]) < p.G), 4.0, 1.0]


TOP_BUGS = kill_bugs(top_live, top_values, [killed(lambda p: not top_live(p), top_values)])  # the kill inverted
TOP_SETS = ((0.2, 0.2, 0, 0), (0.5, 0.05, 0, 0), (-1.0, 0.5, 0, 0), (2.0, 0.5, 0, 0))

# --- two chained kills to one dead block, with work between (render_octomap splat) ------------------------------------
CHAIN = [
    "v_mov_b32_e32 v22, 1.0",
    "v_cmpx_lt_f32_e32 s44, v12",  # a = T1 < R
    "s_cbranch_execz BB2_9",
    "BB2_1:",
    "v_mov_b32_e32 v22, 2.0",
    "v_cmpx_ngt_f32_e32 s45, v13",  # b = !(T2 > G)
    "s_cbranch_execz BB2_9",
    "BB2_2:",
    "v_add_f32_e32 v22, 1.0, v22",
    "v_cmp_lt_f32_e32 vcc_lo, s46, v12",
    "v_cndmask_b32_e64 v23, 0, 1.0, vcc_lo",
    *outputs("v22", "v23", "4.0", "1.0"),
]


def chain_live(p):
    return f32(p.k[0]) < p.R and not f32(p.k[1]) > p.G


def chain_values(p):
    return [3.0, float(f32(p.k[2]) < p.R), 4.0, 1.0]


CHAIN_BUGS = kill_bugs(chain_live, chain_values, [
    killed(lambda p: f32(p.k[0]) < p.R, chain_values),  # the second kill lost
    killed(lambda p: not f32(p.k[1]) > p.G, chain_values),  # the first kill lost
])
CHAIN_SETS = ((0.2, 0.2, 0.5, 0), (0.05, 0.5, 0.3, 0), (2.0, 0.2, 0.5, 0))

# --- leaving whole-quad mode with a kill: s_andn2_b64 exec, Sexact, vcc (dynamicrenderinglocalread, indirectdraw) -----
EXACT = [
    "v_cmp_gt_f32_e32 vcc_lo, s44, v12",  # killed = T > R
    "s_andn2_b64 exec, s[50:51], vcc",
    "s_cbranch_execz BB3_9",
    "BB3_1:",
    "v_cmp_lt_f32_e32 vcc_lo, s45, v13",
    "v_cndmask_b32_e64 v22, 0, 1.0, vcc_lo",
    *outputs("v22", "2.0", "4.0", "1.0"),
]


def exact_live(p):
    return not f32(p.k[0]) > p.R


def exact_values(p):
    return [float(f32(p.k[1]) < p.G), 2.0, 4.0, 1.0]


EXACT_BUGS = kill_bugs(exact_live, exact_values, [killed(lambda p: not exact_live(p), exact_values)])
EXACT_SETS = ((0.2, 0.2, 0, 0), (0.5, 0.05, 0, 0), (2.0, 0.5, 0, 0))

# --- a kill inside whole-quad mode, of EXEC and the exact mask, the scc0 skip to the dead block, more work in whole-quad
# mode, then the exact mask restored (shadowmappingcascade scene, mobile_nerf raster) ----------------------------------
WQM_KILL = [
    "v_cmp_gt_f32_e32 vcc_lo, s44, v12",  # killed = T > R
    "s_andn2_b64 exec, exec, vcc",
    "s_andn2_b64 s[50:51], s[50:51], vcc",
    "s_cbranch_scc0 BB4_9",
    "BB4_1:",
    "v_cmp_lt_f32_e32 vcc_lo, s45, v13",
    "v_cndmask_b32_e64 v22, 0, 1.0, vcc_lo",
    "v_add_f32_e32 v23, 1.0, v22",
    "s_mov_b64 exec, s[50:51]",
    *outputs("v22", "v23", "4.0", "1.0"),
]


def wqm_values(p):
    g = float(f32(p.k[1]) < p.G)
    return [g, g + 1.0, 4.0, 1.0]


WQM_BUGS = kill_bugs(exact_live, wqm_values, [killed(lambda p: not exact_live(p), wqm_values)])

# --- a kill inside a divergent if that also clears the outer save, with the scc0 skip to the dead block ---------------
IN_IF = [
    "v_mov_b32_e32 v22, 1.0",
    "v_mov_b32_e32 v23, 1.0",
    "v_cmp_lt_f32_e32 vcc_lo, s44, v12",  # a = T1 < R
    "s_and_saveexec_b64 s[60:61], vcc",
    "s_cbranch_execz BB5_2",
    "BB5_1:",
    "v_cmp_lt_f32_e32 vcc_lo, s45, v13",  # killed = a && T2 < G
    "s_andn2_b64 exec, exec, vcc",
    "s_andn2_b64 s[60:61], s[60:61], vcc",  # the outer save loses the killed lanes
    "s_cbranch_scc0 BB5_9",
    "BB5_3:",
    "v_mov_b32_e32 v22, 2.0",  # a && !killed
    "BB5_2:",
    "s_mov_b64 exec, s[60:61]",
    "v_add_f32_e32 v23, 1.0, v23",
    *outputs("v22", "v23", "4.0", "1.0"),
]


def in_if_live(p):
    return not (f32(p.k[0]) < p.R and f32(p.k[1]) < p.G)


def in_if_values(p):
    return [2.0 if f32(p.k[0]) < p.R else 1.0, 2.0, 4.0, 1.0]


IN_IF_BUGS = kill_bugs(in_if_live, in_if_values, [
    lambda p: [1.0, 2.0, 4.0, 1.0] if not in_if_live(p) else in_if_values(p),  # a dead lane revived by the restore
])
IN_IF_SETS = ((0.2, 0.2, 0, 0), (0.5, 0.05, 0, 0), (-1.0, 0.3, 0, 0))

# --- a program whose only export is exp null (shadowmappingcascade depthpass): void main, no color written ------------
NULL_ONLY = [
    "v_cmp_gt_f32_e32 vcc_lo, s44, v12",
    "s_andn2_b64 exec, exec, vcc",
]


def null_only_program():
    program = with_constants(NULL_ONLY)
    at = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    return program[:at] + NULL


NULL_BUGS = [lambda p: [0.0, 0.0, 0.0, 0.0] if exact_live(p) else CLEAR]  # a color written by the live lanes


def programs():
    """(name, full program, reference, constant sets, wrong references)."""
    return [(name, targets_only(program), *rest) for name, program, *rest in (
        ("cf2_discard_top", with_null(with_constants(TOP), "BB1_9"), killed(top_live, top_values), TOP_SETS, TOP_BUGS),
        ("cf2_discard_chain", with_null(with_constants(CHAIN), "BB2_9"), killed(chain_live, chain_values),
         CHAIN_SETS, CHAIN_BUGS),
        ("cf2_discard_exact", with_null(wqm_program(EXACT), "BB3_9"), killed(exact_live, exact_values),
         EXACT_SETS, EXACT_BUGS),
        ("cf2_discard_wqm", with_null(wqm_program(WQM_KILL), "BB4_9"), killed(exact_live, wqm_values),
         EXACT_SETS, WQM_BUGS),
        ("cf2_discard_in_if", with_null(with_constants(IN_IF), "BB5_9"), killed(in_if_live, in_if_values),
         IN_IF_SETS, IN_IF_BUGS),
        ("cf2_discard_null", null_only_program(), lambda p: CLEAR, EXACT_SETS, NULL_BUGS))]


def check_references():
    """Offline: every wrong reference differs from the reference in at least one pixel of one constant set, and every
    kill program discards some pixels and keeps others in some set (so neither extreme passes by accident)."""
    for name, _, reference, sets, bugs in programs():
        for n, wrong in enumerate(bugs):
            assert any(wrong(p) != reference(p) for c in sets for p in pixels(c)), (name, n)
        if name != "cf2_discard_null":
            assert any(reference(p) == CLEAR for c in sets for p in pixels(c)), name
            assert any(reference(p) != CLEAR for c in sets for p in pixels(c)), name


def check_cf2_discard_draws(directory, compiler, renderer, backend):
    source, shader, case = directory / "fixture.hlsl", directory / "fixture.cso", directory / "cf2_discard.case"
    for name, program, reference, sets, bugs in programs():
        source.write_text(translate(program), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for constants in sets:
            case.write_bytes(case_bytes(constants, reference))
            subprocess.run(draw, check=True)
        for n, wrong in enumerate(bugs):
            caught = False
            for constants in sets:
                if all(wrong(p) == reference(p) for p in pixels(constants)):
                    continue
                case.write_bytes(case_bytes(constants, wrong))
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode == 1 and "pixel_mismatch" in result.stderr:
                    caught = True
                    break
            if not caught:
                raise AssertionError(f"{name}: wrong reference {n} accepted")
    return 0


# --- controls -----------------------------------------------------------------------------------------------------------
def rejected(text, program):
    try:
        translate(program)
    except ValueError as error:
        assert text in str(error), (text, str(error))
        return
    raise AssertionError(f"program accepted: {program}")


def replace(body, old, new):
    at = body.index(old)
    return body[:at] + new + body[at + 1:]


def main_body(program):
    return translate(program).split(" main(", 1)[1]


def check_cf2_discard_controls():
    check_references()
    for name, program, *_ in programs():
        body = main_body(program)
        # The discard is the last thing before the return, never inside an HLSL branch on the lane bit, and the dead
        # block is not lowered.
        lines = [line.strip() for line in body.splitlines()]
        at = next(n for n, line in enumerate(lines) if line.startswith("return"))
        assert lines[at - 1].startswith("if (!ex") and lines[at - 1].endswith(") discard;"), (name, lines[at - 1])
        assert "exp null" not in body and sum(line.startswith("return") for line in lines) == 1, name
        assert all(line.startswith(("if (!ex", "if (cf", "if (!cf")) for line in lines if line.startswith("if (")), name
    # The null-only program has a void main and writes no color.
    text = translate(programs()[-1][1])
    assert "void main(float2 uv : TEXCOORD0) {" in text and "SV_Target" not in text and "    return;" in text, text
    # ACO's text, with a label on every block, lowers too (its instruction indices, so its names, differ).
    for (body, label, wqm), (_, program, *_) in zip(((TOP, "BB1_9", False), (CHAIN, "BB2_9", False),
                                                     (EXACT, "BB3_9", True), (WQM_KILL, "BB4_9", True),
                                                     (IN_IF, "BB5_9", False)), programs()):
        full = with_null(wqm_program(body) if wqm else with_constants(body), label)
        assert len(full) > len(program) and ") discard;" in translate(full)

    # After a skip to the dead block EXEC may only narrow: a restore of a mask saved before the kill revives the lane.
    rejected("EXEC re-enabled inside a skipped region", with_null(with_constants(
        ["s_mov_b64 s[64:65], exec"] + TOP[:3] + ["s_mov_b64 exec, s[64:65]"] + TOP[3:]), "BB1_9"))
    revived = with_null(wqm_program(replace(WQM_KILL, "s_mov_b64 exec, s[50:51]", ["s_mov_b64 exec, s[52:53]"])),
                        "BB4_9")
    rejected("EXEC re-enabled inside a skipped region", ["s_mov_b64 s[52:53], exec"] + revived)
    # The in-if kill clearing another save than the one the if restores revives the killed lane at the restore.
    rejected("EXEC re-enabled inside a skipped region", with_null(with_constants(["s_mov_b64 s[62:63], exec"] + replace(
        IN_IF, "s_andn2_b64 s[60:61], s[60:61], vcc", ["s_andn2_b64 s[62:63], s[62:63], vcc"])), "BB5_9"))
    # The scc0 skip needs the lane-local SCC of the exact-mask kill right before it, and the lane off when its exact bit
    # is clear. After another SCC write it is an ordinary uniform branch, whose arm is the null export: refused there.
    rejected("Paths of the program export different targets", with_null(wqm_program(replace(
        WQM_KILL, "s_cbranch_scc0 BB4_9", ["s_add_u32 s70, s44, s45", "s_cbranch_scc0 BB4_9"])), "BB4_9"))
    rejected("Kill branch while a lane outside the exact mask may be active", with_null(wqm_program(
        [line for line in WQM_KILL if line != "s_andn2_b64 exec, exec, vcc"]), "BB4_9"))
    # A pair packed while the lane was inactive and exported after EXEC was restored: refused.
    program = with_constants(["s_mov_b64 s[62:63], exec", "v_cmpx_lt_f32_e32 s44, v12"])
    at = program.index("exp mrt0 v16, v16, v17, v17 done compr vm")
    rejected("Export of a pair packed while the exporting lane may have been inactive",
             program[:at] + ["s_mov_b64 exec, s[62:63]"] + program[at:])
    # ... but a pair packed before a kill is the lane's own.
    program = with_constants([])
    at = program.index("exp mrt0 v16, v16, v17, v17 done compr vm")
    assert "    if (!ex" in translate(program[:at] + ["v_cmpx_lt_f32_e32 s44, v12"] + program[at:])
    # Nothing but s_endpgm may follow the null export, as the color export.
    program = with_constants(NULL_ONLY)
    rejected("Unexpected instruction after color export", program[:program.index(
        "exp mrt0 v16, v16, v17, v17 done compr vm")] + NULL[:1] + ["exp mrt0 v16, v16, v17, v17 done compr vm", "s_endpgm"])
    rejected("Unexpected instruction after color export", null_only_program()[:-1] + NULL)
    # The poison of a skipped region still applies to an outer save the region sets rather than clears.
    rejected("Scalar value depends on another lane", with_null(with_constants(replace(
        IN_IF, "v_mov_b32_e32 v22, 2.0", ["v_mov_b32_e32 v22, 2.0", "s_or_b64 s[60:61], s[60:61], vcc"])), "BB5_9"))


def controls(directory):
    check_cf2_discard_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers (wave32). The
    binary check takes one program end, so the kill programs go without their skip to the dead block (the lane is
    discarded at the export all the same) and the dead block itself."""
    out = []
    for name, program, *_ in programs():
        if program[-3:] == [program[-3], *NULL] and program[-3].endswith(":"):
            dead = program[-3][:-1]
            program = [line for line in program[:-3] if not line.endswith(f" {dead}")]
        out.append((program, translate))
    return out


draw = check_cf2_discard_draws
