"""Draw family `cf2_loop`: pixel_aot_check.py draw --family cf2_loop.

CF-2e (docs/design/control-flow.md, CF-2 section 4, card CF-2e): divergent loops. A loop may leave from anywhere in
its body to the block after its latch: the lane-local exit `s_andn2_b64 Sc, Sc, exec; s_cbranch_scc0 EXIT` (the wave
leaves only when no lane continues) is `if (!Sc) break;` per lane, and the loop goes on with `s_mov_b64 exec, Sc`;
a uniform VCC or SCC branch leaves with the wave, and `s_branch EXIT` ends an arm. The lane's EXEC bit is carried around
the loop (`bool jx_<tag>`), so a lane inactive at the loop's entry leaves at the first exit test. In a loop with a
lane-local exit EXEC may only narrow from the header's bit, implicit-derivative operations are refused, the scalars it
changes are poisoned after it, and only scalar work may precede the restore of EXEC after it. Loops nest.

The programs are written in ACO's shapes (the break mask from v_cmpx, the nand + saveexec break of sparse_image, the
uniform VCC exit of parallaxmapping, a nested loop and a loop inside a divergent if) and render the 8x8 pixel case with
a per-pixel trip count from the texture (R = v12, G = v13), so the lanes of a quad leave at different iterations.
Wrong references (each must be reported as a pixel_mismatch): the trip count off by one either way, the break treated
as uniform (every lane runs as long as the last lane of its quad, or of the whole draw), the continue ignored (every
lane leaves at the first test), the break-path value lost, and the lanes inactive at entry running the body."""
import math
import subprocess

from .cf2_skip import f32, outputs, pixels, case_bytes, targets_only
from .common import translate, with_constants


def trips(t, cap=None):
    """The iterations a lane runs: the counter c = 0, 1, ... leaves at the first c >= t (and at the cap)."""
    n = max(0, math.ceil(t))
    return n if cap is None else min(n, cap)


def loop_values(n, broke=True):
    """v20 = n, v21 = 0 + 1 + ... + (n - 1), v23 = n + 0.5 written on the break path (7 at a uniform exit)."""
    return [float(n), float(n * (n - 1) // 2), n + 0.5 if broke else 7.0, 1.0]


# --- the break mask from v_cmpx (ACO's emit_loop_break), the continue with s_mov_b64 exec, Sc -------------------------
BREAK = [
    "v_mul_f32_e32 v24, 0x41000000, v12",  # t = 8R
    "v_mov_b32_e32 v20, 0",  # c
    "v_mov_b32_e32 v21, 0",  # acc
    "v_mov_b32_e32 v23, 0",
    "s_mov_b64 s[60:61], exec",  # the preheader save
    "BB1_1:",
    "s_mov_b64 s[62:63], exec",
    "v_cmpx_ge_f32_e32 v20, v24",  # the lanes that break: c >= t
    "BB1_2:",
    "v_add_f32_e32 v23, 0.5, v20",  # break-path work
    "s_andn2_b64 s[62:63], s[62:63], exec",  # the lanes that continue
    "s_cbranch_scc0 BB1_4",
    "BB1_3:",
    "s_mov_b64 exec, s[62:63]",  # continue with them
    "v_add_f32_e32 v21, v20, v21",
    "v_add_f32_e32 v20, 1.0, v20",
    "s_branch BB1_1",
    "BB1_4:",
    "s_mov_b64 exec, s[60:61]",
    *outputs("v20", "v21", "v23", "1.0"),
]


def break_trips(p):
    return trips(8 * p.R)


def quad_max(count):
    return lambda p: max(count(q) for q in p.quad())


def frame_max(count):
    return lambda p: max(count(q) for q in pixels(p.k))


def loop_bugs(count, values):
    return [
        lambda p: values(p, count(p) + 1),  # one iteration long
        lambda p: values(p, max(count(p) - 1, 0)),  # one iteration short
        lambda p: values(p, quad_max(count)(p)),  # the break treated as uniform: decided per quad
        lambda p: values(p, frame_max(count)(p)),  # ... or for the whole draw
        lambda p: values(p, 0),  # the continue ignored: every lane leaves at the first test
    ]


def break_values(p, n):
    return loop_values(n)


BREAK_BUGS = loop_bugs(break_trips, break_values) + [
    lambda p: loop_values(break_trips(p))[:2] + [0.0, 1.0],  # the break-path value lost
]
BREAK_SETS = ((0, 0, 0, 0),)

# --- the nand + saveexec break of sparse_image, bounded by a uniform counter (SCC from s_cmp) -------------------------
NAND = [
    "v_mul_f32_e32 v24, 0x41000000, v13",  # t = 8G
    "v_mov_b32_e32 v20, 0",
    "v_mov_b32_e32 v21, 0",
    "v_mov_b32_e32 v23, 0",
    "s_mov_b32 s70, 0",  # k, uniform
    "s_mov_b64 s[60:61], exec",
    "BB2_1:",
    "s_cmp_lt_u32 s70, s47",  # k < N
    "s_cselect_b64 s[62:63], -1, 0",
    "v_cmp_lt_f32_e32 vcc_lo, v20, v24",  # c < t
    "s_nand_b64 s[62:63], s[62:63], vcc",  # the lanes that break
    "s_and_saveexec_b64 s[62:63], s[62:63]",
    "BB2_2:",
    "v_add_f32_e32 v23, 0.5, v20",
    "s_andn2_b64 s[62:63], s[62:63], exec",
    "s_cbranch_scc0 BB2_4",
    "BB2_3:",
    "s_mov_b64 exec, s[62:63]",
    "v_add_f32_e32 v21, v20, v21",
    "v_add_f32_e32 v20, 1.0, v20",
    "s_add_u32 s70, s70, 1",
    "s_branch BB2_1",
    "BB2_4:",
    "s_mov_b64 exec, s[60:61]",
    *outputs("v20", "v21", "v23", "1.0"),
]


def nand_trips(p):
    return trips(8 * p.G, p.k[3])


NAND_BUGS = loop_bugs(nand_trips, break_values) + [
    lambda p: loop_values(trips(8 * p.G)),  # the uniform bound ignored
]
NAND_SETS = ((0, 0, 0, 5), (0, 0, 0, 9))

# --- a uniform VCC exit in the header, an arm ending s_branch EXIT (parallaxmapping) ----------------------------------
UVCC = [
    "v_mul_f32_e32 v24, 0x41000000, v12",
    "v_mov_b32_e32 v20, 0",
    "v_mov_b32_e32 v21, 0",
    "v_mov_b32_e32 v23, 0",
    "s_mov_b32 s70, 0",
    "s_mov_b64 s[60:61], exec",
    "BB3_1:",
    "v_cmp_lt_u32_e64 vcc_lo, s70, s47",  # k < N, uniform
    "s_cbranch_vccnz BB3_3",
    "BB3_2:",
    "v_mov_b32_e32 v23, 0x40e00000",  # the uniform exit's work: 7
    "s_branch BB3_5",
    "BB3_3:",
    "s_mov_b64 s[62:63], exec",
    "v_cmpx_ge_f32_e32 v20, v24",
    "v_add_f32_e32 v23, 0.5, v20",
    "s_andn2_b64 s[62:63], s[62:63], exec",
    "s_cbranch_scc0 BB3_5",
    "BB3_4:",
    "s_mov_b64 exec, s[62:63]",
    "v_add_f32_e32 v21, v20, v21",
    "v_add_f32_e32 v20, 1.0, v20",
    "s_add_u32 s70, s70, 1",
    "s_branch BB3_1",
    "BB3_5:",
    "s_mov_b64 exec, s[60:61]",
    *outputs("v20", "v21", "v23", "1.0"),
]


def uvcc_reference(p, n=None):
    full = trips(8 * p.R)
    n = min(full, p.k[3]) if n is None else n
    return loop_values(n, broke=full < p.k[3])  # the lane-local exit comes after the uniform test of k < N


def uvcc_values(p, n):
    return uvcc_reference(p, n)


UVCC_BUGS = loop_bugs(lambda p: min(trips(8 * p.R), p.k[3]), uvcc_values) + [
    lambda p: loop_values(min(trips(8 * p.R), p.k[3])),  # the uniform exit's work lost
]
UVCC_SETS = ((0, 0, 0, 4), (0, 0, 0, 9))

# --- nested loops, each with its own lane-local exit: a = ceil(4R) outer, b = ceil(4G) inner iterations --------------
NESTED = [
    "v_mul_f32_e32 v24, 4.0, v12",
    "v_mul_f32_e32 v25, 4.0, v13",
    "v_mov_b32_e32 v20, 0",  # i
    "v_mov_b32_e32 v21, 0",  # acc
    "s_mov_b64 s[60:61], exec",
    "BB4_1:",
    "s_mov_b64 s[62:63], exec",
    "v_cmpx_ge_f32_e32 v20, v24",
    "s_andn2_b64 s[62:63], s[62:63], exec",
    "s_cbranch_scc0 BB4_6",
    "BB4_2:",
    "s_mov_b64 exec, s[62:63]",
    "v_mov_b32_e32 v22, 0",  # j
    "s_mov_b64 s[64:65], exec",
    "BB4_3:",
    "s_mov_b64 s[66:67], exec",
    "v_cmpx_ge_f32_e32 v22, v25",
    "s_andn2_b64 s[66:67], s[66:67], exec",
    "s_cbranch_scc0 BB4_5",
    "BB4_4:",
    "s_mov_b64 exec, s[66:67]",
    "v_add_f32_e32 v21, 1.0, v21",
    "v_add_f32_e32 v22, 1.0, v22",
    "s_branch BB4_3",
    "BB4_5:",
    "s_mov_b64 exec, s[64:65]",
    "v_add_f32_e32 v20, 1.0, v20",
    "s_branch BB4_1",
    "BB4_6:",
    "s_mov_b64 exec, s[60:61]",
    *outputs("v20", "v21", "1.0", "1.0"),
]


def nested_counts(p):
    return trips(4 * p.R), trips(4 * p.G)


def nested_reference(p):
    a, b = nested_counts(p)
    return [float(a), float(a * b), 1.0, 1.0]


NESTED_BUGS = [
    lambda p: [float(nested_counts(p)[0]), float(nested_counts(p)[0] * (nested_counts(p)[1] + 1)), 1.0, 1.0],
    lambda p: [float(nested_counts(p)[0] + 1), float((nested_counts(p)[0] + 1) * nested_counts(p)[1]), 1.0, 1.0],
    lambda p: [float(nested_counts(p)[0]),  # the inner break treated as uniform (per quad)
               float(nested_counts(p)[0] * max(nested_counts(q)[1] for q in p.quad())), 1.0, 1.0],
    lambda p: [float(max(nested_counts(q)[0] for q in p.quad())),  # the outer break treated as uniform (per quad)
               float(max(nested_counts(q)[0] for q in p.quad()) * nested_counts(p)[1]), 1.0, 1.0],
    lambda p: [float(nested_counts(p)[0]), 0.0, 1.0, 1.0],  # the inner continue ignored
]

# --- a loop inside a divergent if: lanes inactive at its entry keep their values and leave at the first test ---------
IN_IF = [
    "v_mul_f32_e32 v24, 0x41000000, v12",
    "v_mov_b32_e32 v20, 0",
    "v_mov_b32_e32 v21, 0",
    "v_mov_b32_e32 v23, 0x41200000",  # 10
    "v_cmp_lt_f32_e32 vcc_lo, s44, v13",  # a = T < G
    "s_and_saveexec_b64 s[58:59], vcc",
    "s_cbranch_execz BB5_9",
    "BB5_0:",
    "s_mov_b64 s[60:61], exec",
    "BB5_1:",
    "s_mov_b64 s[62:63], exec",
    "v_cmpx_ge_f32_e32 v20, v24",
    "v_add_f32_e32 v23, 0.5, v20",
    "s_andn2_b64 s[62:63], s[62:63], exec",
    "s_cbranch_scc0 BB5_3",
    "BB5_2:",
    "s_mov_b64 exec, s[62:63]",
    "v_add_f32_e32 v21, v20, v21",
    "v_add_f32_e32 v20, 1.0, v20",
    "s_branch BB5_1",
    "BB5_3:",
    "s_mov_b64 exec, s[60:61]",
    "BB5_9:",
    "s_mov_b64 exec, s[58:59]",
    *outputs("v20", "v21", "v23", "1.0"),
]


def in_if_active(p):
    return f32(p.k[0]) < p.G


def in_if_reference(p, n=None):
    if not in_if_active(p):
        return [0.0, 0.0, 10.0, 1.0]
    return loop_values(break_trips(p) if n is None else n)


IN_IF_BUGS = loop_bugs(lambda p: break_trips(p), in_if_reference)[:3] + [
    lambda p: loop_values(break_trips(p)),  # the lanes inactive at entry run the body
    lambda p: loop_values(break_trips(p)) if in_if_active(p) else [0.0, 0.0, 0.5, 1.0],  # ... once
]
IN_IF_SETS = ((0.2, 0, 0, 0), (0.5, 0, 0, 0))


def programs():
    """(name, full program, reference, constant sets, wrong references)."""
    return [(name, targets_only(program), *rest) for name, program, *rest in (
        ("cf2_loop_break", with_constants(BREAK), lambda p: loop_values(break_trips(p)), BREAK_SETS, BREAK_BUGS),
        ("cf2_loop_nand", with_constants(NAND), lambda p: loop_values(nand_trips(p)), NAND_SETS, NAND_BUGS),
        ("cf2_loop_uvcc", with_constants(UVCC), uvcc_reference, UVCC_SETS, UVCC_BUGS),
        ("cf2_loop_nested", with_constants(NESTED), nested_reference, BREAK_SETS, NESTED_BUGS),
        ("cf2_loop_in_if", with_constants(IN_IF), in_if_reference, IN_IF_SETS, IN_IF_BUGS))]


def check_references():
    """Offline: results are exact in binary16 (small integers and halves), and every wrong reference differs from
    the reference in at least one pixel of one constant set."""
    import struct
    for name, _, reference, sets, bugs in programs():
        for constants in sets:
            for p in pixels(constants):
                for value in reference(p):
                    assert value == struct.unpack("<e", struct.pack("<e", value))[0], (name, value)
        for n, wrong in enumerate(bugs):
            assert any(wrong(p) != reference(p) for c in sets for p in pixels(c)), (name, n)


def check_cf2_loop_draws(directory, compiler, renderer, backend):
    source, shader, case = directory / "fixture.hlsl", directory / "fixture.cso", directory / "cf2_loop.case"
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


def check_cf2_loop_controls():
    check_references()
    for name, program, *_ in programs():
        text = translate(program).split(" main(", 1)[1]
        # The lane's EXEC bit is carried around the loop and the lane-local exit is a per-lane break.
        assert "[loop] while (true)" in text and "bool jx_" in text and ") break;" in text, name
        assert "discard" not in text, name
    text = translate(programs()[0][1])
    assert "if (!lm" in text, text
    # ACO's text, with a label on every block, lowers too.
    for body in (BREAK, NAND, UVCC, NESTED, IN_IF):
        assert ") break;" in translate(with_constants(body))

    # Poison: the uniform counter (and the loop's masks) read after a divergent loop.
    rejected("Scalar value depends on another lane", with_constants(NAND + ["v_mov_b32_e32 v12, s70"]))
    rejected("Scalar value depends on another lane", with_constants(NAND + ["s_mov_b64 vcc, s[62:63]",
                                                                          "v_cndmask_b32_e64 v12, 0, 1.0, vcc_lo"]))
    # ... but not after a loop whose exits are all uniform (CF-1).
    translate(with_constants(["s_mov_b32 s70, 0", "BB0_1:", "s_add_u32 s70, s70, 1", "s_cmp_lt_u32 s70, s47",
                              "s_cbranch_scc1 BB0_1", "BB0_2:", "v_mov_b32_e32 v12, s70"]))
    # Vector work before EXEC is restored after a divergent loop.
    rejected("EXEC must be restored after a divergent loop", with_constants(replace(
        BREAK, "s_mov_b64 exec, s[60:61]", ["v_mov_b32_e32 v22, 1.0", "s_mov_b64 exec, s[60:61]"])))
    rejected("EXEC must be restored after a divergent loop", with_constants(replace(
        BREAK, "s_mov_b64 exec, s[60:61]", [])))
    # Narrow-only inside a divergent loop: restoring the preheader's save revives lanes that left.
    rejected("EXEC re-enabled", with_constants(replace(BREAK, "s_mov_b64 exec, s[62:63]", ["s_mov_b64 exec, s[60:61]"])))
    # An implicit-derivative sample inside a divergent loop is refused.
    sample = "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"
    program = with_constants(BREAK)
    at = program.index("v_add_f32_e32 v21, v20, v21")
    rejected("derivative in divergent flow", program[:at] + [sample, "s_waitcnt vmcnt(0)"] + program[at:])
    # A branch from the inner loop to the outer loop's exit.
    rejected("Branch leaves its region", with_constants(replace(NESTED, "s_cbranch_scc0 BB4_5", ["s_cbranch_scc0 BB4_6"])))
    # A lane-local exit inside a skipped region of the loop's body, and a loop with no exit.
    rejected("Loop exit inside a skipped region", with_constants(replace(
        BREAK, "BB1_2:", ["s_cbranch_execz BB1_3", "BB1_2:"])))
    rejected("A loop must leave", with_constants(["v_mov_b32_e32 v20, 0", "v_mov_b32_e32 v24, 1.0", "BB0_1:",
                                                  "s_mov_b64 s[62:63], exec", "v_cmpx_ge_f32_e32 v20, v24",
                                                  "s_mov_b64 exec, s[62:63]", "s_branch BB0_1"]))
    # The lane-local exit needs the mask operation's SCC right before it; after another SCC write it is a uniform
    # exit on that SCC (here the carry of a uniform add).
    text = translate(with_constants(replace(BREAK, "s_cbranch_scc0 BB1_4", ["s_add_u32 s70, s44, s45",
                                                                            "s_cbranch_scc0 BB1_4"])))
    assert "if (!lm" not in text and "if (!cf" in text, text
    # A uniform branch whose paths leave EXEC different (one narrows it): the lane bit is joined, and the export
    # discards the lanes that are off.
    joined = with_constants(["s_cmp_lt_u32 s46, s47", "s_cbranch_scc1 BB0_2", "BB0_1:",
                             "v_cmpx_lt_f32_e32 s44, v12", "BB0_2:", "v_mov_b32_e32 v14, 1.0"])
    text = translate(joined)
    assert "bool jx_" in text and "if (!jx_" in text, text
    # ... but not when one path killed lanes to the all-lanes-dead block.
    rejected("Kill on one path of a uniform branch", with_constants([
        "s_cmp_lt_u32 s46, s47", "s_cbranch_scc1 BB0_2", "BB0_1:", "v_cmpx_lt_f32_e32 s44, v12",
        "s_cbranch_execz BB0_9", "BB0_2:", "v_mov_b32_e32 v14, 1.0"]) + ["BB0_9:", "exp null off, off, off, off done vm",
                                                                         "s_endpgm"])


def controls(directory):
    check_cf2_loop_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers (wave32)."""
    return [(program, translate) for _, program, *_ in programs()]


draw = check_cf2_loop_draws
