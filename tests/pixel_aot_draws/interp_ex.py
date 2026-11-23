"""Draw family `interp_ex`: pixel_aot_check.py draw --family interp_ex.

v_interp_p1_f32 / v_interp_p2_f32 while the lane may be inactive (forms/vintrp.py, lowering.masked_writes): after a
v_cmpx, a discard or inside a skipped region. On the console a lane that is off in EXEC runs neither half and keeps the
register's old value; an active lane gets P0 + I * P10 + J * P20. The pair is one masked write, `ex ? interpolated :
old`, with the old value carried through the half-done p1 value, which is no word. Where the old value is no word either
(the barycentric the last interpolation of an arm overwrites), the inactive lanes keep it as provenance
(control_flow.LaneOnly): the other arm of an if-else still reads the barycentric there, and once both arms have written
the register it is a word on every lane. A lane that discarded has ex false and keeps its old value; a helper lane of
whole-quad mode is a lane with ex true.

The programs are written in the shapes of the corpus shaders this unblocked (occlusionquery mesh and render_octomap
splat: interpolation in a then-arm; radialblur phongpass and shadowmappingomni cubemapdisplay: the barycentrics
overwritten in an if-else; mobile_nerf raster and vertexattributes scene: interpolation after a kill, in whole-quad
mode) and render the 8x8 pixel case of family cf2_skip (one pixel per texel; R = v12 and G = v13 from the texture). At
the centre of pixel (x, y) I = (2x + 1) / 32 and J = (2y + 1) / 32, and the attribute values are the small integers of
tests/pixel_aot_vs.hlsl, so every interpolated value is exact in binary32 and in binary16, which the export packs to.

Each program has a Python reference and wrong references that must each be reported as a pixel_mismatch: the old value
dropped (an inactive lane reads 0), the interpolation ignoring EXEC (every lane interpolated), the half-done p1 value
kept by the inactive lanes, I and J exchanged, and per program the barycentric overwritten by the other arm, the kill
ignored, or the arm decided per quad. The controls refuse the neighbours: EXEC changed between p1 and p2, p2 at
another bit than p1, a read of the barycentric after the arm that overwrote it, and an implicit-level sample of the
masked value."""
from fractions import Fraction
import struct
import subprocess

from pixel_aot_ops.control_flow import LANE_GONE_MESSAGE

from .cf2_discard import CLEAR, kill_bugs, killed, wqm_program, with_null
from .cf2_skip import case_bytes, f32, outputs, pixels, targets_only
from .common import DrawBatch, translate, with_constants
from .interp_attrs import CHANNELS, VERTICES


def interp(attr, channel, p, swapped=False, half=False):
    """The console's interpolated attr.channel at pixel p (binary32 value), or a wrong variant: I and J exchanged, or the
    half-done p1 value P0 + I * P10."""
    p0, p1, p2 = (vertex[CHANNELS.index(channel)] for vertex in VERTICES[attr])
    i, j = Fraction(2 * p.x + 1, 32), Fraction(2 * p.y + 1, 32)
    if swapped:
        i, j = j, i
    value = p0 + i * (p1 - p0) + (0 if half else j * (p2 - p0))
    return float(value)


def with_j(attr, channel, p, j):
    p0, p1, p2 = (vertex[CHANNELS.index(channel)] for vertex in VERTICES[attr])
    return float(p0 + Fraction(2 * p.x + 1, 32) * (p1 - p0) + j * (p2 - p0))


def cond(p):
    return f32(p.k[0]) < p.R  # c = T < R


def per_quad(p):
    """c decided for the whole quad: the then-arm runs only where every lane of the quad takes it."""
    return all(cond(q) for q in p.quad())


# --- interpolation in a then-arm over word registers (occlusionquery mesh, render_octomap splat) -----------------------
THEN = [
    "v_mov_b32_e32 v22, 2.0",
    "v_mov_b32_e32 v23, 0x40400000",
    "v_cmp_lt_f32_e32 vcc_lo, s44, v12",  # c = T < R
    "s_and_saveexec_b64 s[60:61], vcc",
    "s_cbranch_execz BB1_2",
    "BB1_1:",
    "v_interp_p1_f32_e32 v22, v0, attr1.x",
    "v_interp_p1_f32_e32 v23, v0, attr2.y",
    "v_interp_p2_f32_e32 v23, v1, attr2.y",  # the halves pair by register, not by position
    "v_interp_p2_f32_e32 v22, v1, attr1.x",
    "BB1_2:",
    "s_mov_b64 exec, s[60:61]",
    *outputs("v22", "v23", "4.0", "1.0"),
]


def then_values(p, c=None, old=(2.0, 3.0), **variant):
    c = cond(p) if c is None else c
    return [interp(1, "x", p, **variant) if c else old[0], interp(2, "y", p, **variant) if c else old[1], 4.0, 1.0]


THEN_BUGS = [
    lambda p: then_values(p, old=(0.0, 0.0)),  # the old value dropped
    lambda p: then_values(p, c=True),  # the interpolation ignoring EXEC
    lambda p: then_values(p) if cond(p) else [interp(1, "x", p, half=True), interp(2, "y", p, half=True), 4.0, 1.0],
    lambda p: then_values(p, swapped=True),  # I and J exchanged
    lambda p: then_values(p, c=per_quad(p)),  # the arm decided per quad
]

# --- the barycentrics overwritten in an if-else (radialblur phongpass, shadowmappingomni cubemapdisplay) ---------------
IF_ELSE = [
    "v_mov_b32_e32 v22, 2.0",
    "v_mov_b32_e32 v23, 0x40400000",
    "v_cmp_lt_f32_e32 vcc_lo, s44, v12",  # c = T < R
    "s_and_saveexec_b64 s[60:61], vcc",
    "s_cbranch_execz BB2_2",
    "BB2_1:",
    "v_interp_p1_f32_e32 v22, v0, attr3.z",
    "v_interp_p2_f32_e32 v22, v1, attr3.z",
    "v_mov_b32_e32 v1, 1.0",  # J overwritten on the then-lanes only
    "BB2_2:",
    "s_andn2_b64 exec, s[60:61], exec",  # else
    "s_cbranch_execz BB2_4",
    "BB2_3:",
    "v_interp_p1_f32_e32 v0, v0, attr4.w",  # I replaced by the half on the else-lanes
    "v_interp_p2_f32_e32 v0, v1, attr4.w",  # J still the barycentric on the else-lanes
    "v_mov_b32_e32 v23, v0",
    "v_mov_b32_e32 v1, 0x40a00000",
    "BB2_4:",
    "s_mov_b64 exec, s[60:61]",
    *outputs("v22", "v23", "v1", "1.0"),
]


def if_else_values(p, c=None, old=(2.0, 3.0), then_j=False, **variant):
    c = cond(p) if c is None else c
    other = with_j(4, "w", p, 1) if then_j else interp(4, "w", p, **variant)
    return [interp(3, "z", p, **variant) if c else old[0], old[1] if c else other, 1.0 if c else 5.0, 1.0]


IF_ELSE_BUGS = [
    lambda p: if_else_values(p, old=(0.0, 0.0)),  # the old value dropped
    lambda p: [interp(3, "z", p), interp(4, "w", p), 1.0 if cond(p) else 5.0, 1.0],  # interpolation ignoring EXEC
    lambda p: if_else_values(p) if cond(p) else [2.0, interp(4, "w", p, half=True), 5.0, 1.0],  # the half kept
    lambda p: if_else_values(p, swapped=True),  # I and J exchanged
    lambda p: if_else_values(p, then_j=True),  # the then-arm's write of v1 reaching the else-lanes' J
    lambda p: if_else_values(p, c=per_quad(p)),  # the arms decided per quad
]

# --- interpolation after a kill in whole-quad mode, the exact mask restored after it (mobile_nerf raster) -------------
KILL = [
    "v_mov_b32_e32 v23, 0x40400000",
    "v_cmp_gt_f32_e32 vcc_lo, s44, v12",  # killed = T > R
    "s_andn2_b64 exec, exec, vcc",
    "s_andn2_b64 s[50:51], s[50:51], vcc",
    "s_cbranch_scc0 BB3_9",
    "BB3_1:",
    "v_interp_p1_f32_e32 v22, v0, attr5.y",
    "v_interp_p1_f32_e32 v23, v0, attr6.x",
    "v_interp_p2_f32_e32 v22, v1, attr5.y",
    "v_interp_p2_f32_e32 v23, v1, attr6.x",
    "s_mov_b64 exec, s[50:51]",
    *outputs("v22", "v23", "4.0", "1.0"),
]


def kill_live(p):
    return not f32(p.k[0]) > p.R


def kill_values(p, **variant):
    return [interp(5, "y", p, **variant), interp(6, "x", p, **variant), 4.0, 1.0]


KILL_BUGS = kill_bugs(kill_live, kill_values, [
    killed(kill_live, lambda p: kill_values(p, swapped=True)),  # I and J exchanged
    killed(kill_live, lambda p: [interp(5, "y", p, half=True), interp(6, "x", p, half=True), 4.0, 1.0]),
])

# --- a top-level v_cmpx kill, then interpolation over the word it compared (occlusionquery mesh) ---------------------
CMPX = [
    "v_mov_b32_e32 v22, v12",
    "v_cmpx_lt_f32_e32 s44, v22",  # live = T < R
    "s_cbranch_execz BB4_9",
    "BB4_1:",
    "v_interp_p1_f32_e32 v22, v0, attr7.z",
    "v_interp_p2_f32_e32 v22, v1, attr7.z",
    "v_interp_p1_f32_e32 v23, v0, attr0.y",
    "v_interp_p2_f32_e32 v23, v1, attr0.y",
    *outputs("v22", "v23", "4.0", "1.0"),
]


def cmpx_values(p, **variant):
    return [interp(7, "z", p, **variant), interp(0, "y", p, **variant), 4.0, 1.0]


CMPX_BUGS = kill_bugs(cond, cmpx_values, [
    killed(cond, lambda p: cmpx_values(p, swapped=True)),
    killed(lambda p: not cond(p), cmpx_values),  # the kill inverted
])

SETS = ((0.2, 0, 0, 0), (0.5, 0, 0, 0), (-1.0, 0, 0, 0), (2.0, 0, 0, 0))


def programs():
    """(name, program, reference, constant sets, wrong references)."""
    return [(name, targets_only(program), *rest) for name, program, *rest in (
        ("interp_ex_then", with_constants(THEN), then_values, SETS[:3], THEN_BUGS),
        ("interp_ex_if_else", with_constants(IF_ELSE), if_else_values, SETS[:3], IF_ELSE_BUGS),
        ("interp_ex_kill", with_null(wqm_program(KILL), "BB3_9"), killed(kill_live, kill_values), SETS, KILL_BUGS),
        ("interp_ex_cmpx", with_null(with_constants(CMPX), "BB4_9"), killed(cond, cmpx_values), SETS, CMPX_BUGS))]


def check_references():
    """Offline: each wrong reference differs from the reference at some pixel of some set, every program has pixels on
    both sides of its condition, and every value is exact in binary16 (the export's format)."""
    for name, _, reference, sets, bugs in programs():
        for n, wrong in enumerate(bugs):
            assert any(wrong(p) != reference(p) for c in sets for p in pixels(c)), (name, n)
        outcomes = {cond(p) for c in sets for p in pixels(c)}
        assert outcomes == {False, True}, name
        for c in sets:
            for p in pixels(c):
                for v in reference(p):
                    assert struct.unpack("<e", struct.pack("<e", v))[0] == v, (name, v)


def check_interp_ex_draws(directory, compiler, renderer, backend):
    for name, program, reference, sets, bugs in programs():
        source, shader = directory / f"{name}.hlsl", directory / f"{name}.cso"
        source.write_text(translate(program), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        with DrawBatch(directory, renderer, backend, shader, name) as batch:
            for constants in sets:
                batch.add(case_bytes(constants, reference), "pass", f"{name} is wrong for {constants} on {backend}")
            for n, wrong in enumerate(bugs):
                # One set where the wrong reference differs is enough; it must be reported there.
                constants = next(c for c in sets if any(wrong(p) != reference(p) for p in pixels(c)))
                batch.add(case_bytes(constants, wrong), "mismatch", f"{name}: wrong reference {n} escaped detection")
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


def check_interp_ex_controls():
    check_references()
    # The pair is one select over the old value; the half-done value is never a word in the text.
    body = main_body(programs()[0][1])
    assert "= ex" in body and " ? asuint(alu" in body and ": asuint(alu" in body, body
    assert "float alu" in body and "= attr1.x;" in body and "= attr2.y;" in body, body
    # The if-else: the else-arm reads the barycentrics the then-arm overwrote on its own lanes, and after both arms v1 is a
    # word on every lane, exported without a refusal.
    body = main_body(programs()[1][1])
    assert body.count("= attr4.w;") == 1 and body.count("= attr3.z;") == 1, body
    # Neighbours that are refused.
    # EXEC changed between the halves: some lane would hold the half-done value.
    rejected("Unpaired interpolation", with_constants(replace(
        THEN, "v_interp_p2_f32_e32 v22, v1, attr1.x",
        ["v_cmpx_lt_f32_e32 s45, v13", "v_interp_p2_f32_e32 v22, v1, attr1.x"])))
    # p1 inside the arm, p2 after the restore (and the reverse).
    program = [line for line in THEN if line != "v_interp_p2_f32_e32 v22, v1, attr1.x"]
    rejected("Unpaired interpolation", with_constants(replace(
        program, "s_mov_b64 exec, s[60:61]", ["s_mov_b64 exec, s[60:61]", "v_interp_p2_f32_e32 v22, v1, attr1.x"])))
    program = [line for line in THEN if line != "v_interp_p1_f32_e32 v22, v0, attr1.x"]
    rejected("Unpaired interpolation", with_constants(
        replace(program, "v_mov_b32_e32 v22, 2.0", ["v_interp_p1_f32_e32 v22, v0, attr1.x"])))
    # p2 of another channel or attribute under the same bit.
    rejected("Unpaired interpolation", with_constants(replace(
        THEN, "v_interp_p2_f32_e32 v22, v1, attr1.x", ["v_interp_p2_f32_e32 v22, v1, attr1.y"])))
    # The half-done value read inside the arm.
    rejected("Expected a numeric register", with_constants(replace(
        THEN, "v_interp_p2_f32_e32 v23, v1, attr2.y", ["v_add_f32_e32 v24, 1.0, v23", "v_interp_p2_f32_e32 v23, v1, attr2.y"])))
    # The barycentric J read after the then-arm overwrote it on some lanes: on those it is 1.0, on the others J.
    rejected(LANE_GONE_MESSAGE, with_constants(replace(
        IF_ELSE, "s_andn2_b64 exec, s[60:61], exec",
        ["s_mov_b64 exec, s[60:61]", "v_interp_p1_f32_e32 v24, v0, attr1.x", "v_interp_p2_f32_e32 v24, v1, attr1.x",
         "s_andn2_b64 exec, s[60:61], exec"])))
    # v0 after the join: the interpolated value on the else-lanes, still I on the then-lanes, which have no word.
    rejected(LANE_GONE_MESSAGE, with_constants(IF_ELSE[:-4] + outputs("v22", "v0", "v1", "1.0")))
    # A third arm under a bit the first two do not exclude reads J where the then-arm overwrote it.
    rejected(LANE_GONE_MESSAGE, with_constants(replace(
        IF_ELSE, "s_mov_b64 exec, s[60:61]",
        ["s_mov_b64 exec, s[60:61]", "v_cmpx_lt_f32_e32 s45, v13", "v_interp_p1_f32_e32 v24, v0, attr1.x"])))
    # An implicit-level sample of the masked value: it is no helper-lane value.
    sample = "image_sample v[24:27], v[22:23], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"
    rejected("Unsupported texture coordinate", with_constants(replace(
        THEN, "s_mov_b64 exec, s[60:61]", ["s_mov_b64 exec, s[60:61]", sample, "s_waitcnt vmcnt(0)"])))
    # m0 must still address the attributes.
    rejected("Unknown interpolation context", with_constants(replace(
        THEN, "s_and_saveexec_b64 s[60:61], vcc", ["s_and_saveexec_b64 s[60:61], vcc", "s_mov_b32 m0, s44"])))
    # The kill programs discard where the lane is off, as family cf2_discard.
    for name, program, *_ in programs()[2:]:
        assert ") discard;" in main_body(program), name


def controls(directory):
    check_interp_ex_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers (wave32); the kill
    programs without their skip to the dead block and the block, as family cf2_discard."""
    out = []
    for name, program, *_ in programs():
        if program[-2:] == ["exp null off, off, off, off done vm", "s_endpgm"] and program[-3].endswith(":"):
            dead = program[-3][:-1]
            program = [line for line in program[:-3] if not line.endswith(f" {dead}")]
        out.append((program, translate))
    return out


draw = check_interp_ex_draws
