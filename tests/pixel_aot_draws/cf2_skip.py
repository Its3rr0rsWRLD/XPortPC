"""Draw family `cf2_skip`: pixel_aot_check.py draw --family cf2_skip.

CF-2c (docs/design/control-flow.md, CF-2 sections 4 and 5, card CF-2c): skip branches and uniform VCC branches.
`s_cbranch_execz` / `s_cbranch_execnz` over a region are lowered in predicate mode: the branch is dropped and the
region runs as straight-line code with its VGPR writes masked by the lane's EXEC bit, so HLSL flow stays uniform and
an implicit-LOD sample in the region keeps its quad. Inside a skipped region EXEC may only narrow (a restore of a mask
saved outside it is refused), and a scalar the region leaves different is poisoned. `s_cbranch_vccz` / `vccnz` are
CF-1 uniform branches on the unmasked compare, accepted only when the compare reads wave-uniform operands (the
uniformity lattice) and ran while the wave had an active lane. A skip to the all-lanes-dead block is not taken.

The programs are written in ACO's layout (linear if/else with skips, labels BB<n>_<m>) and render the 8x8 pixel case
(texel (x, y) = (RAMP[x], RAMP[y], 128, 255), one pixel per texel), so the per-lane conditions come from the texture
(R = v12, G = v13) or the interpolated coordinate and differ between pixels, also inside a quad. Results are small
integers, exact in binary16. Each program has a per-pixel Python reference and wrong references that must each be
reported as a pixel_mismatch: the skip taken as if uniform (decided per quad), the skipped region not predicated
(its writes reaching inactive lanes), an execnz region run for the active lanes, and the VCC branch polarity
flipped."""
import struct
import subprocess

from .common import RAMP, translate, with_constants


def f32(w):
    return struct.unpack("<f", struct.pack("<I", w & 0xffffffff))[0]


def word(value):
    return struct.unpack("<I", struct.pack("<f", value))[0] if isinstance(value, float) else value & 0xffffffff


class Pixel:
    def __init__(self, x, y, constants):
        self.x, self.y = x, y
        self.R, self.G = RAMP[x] / 255, RAMP[y] / 255
        self.u = (x + 0.5) / 8  # the interpolated coordinate at the pixel center
        self.k = constants  # the words s44..s47

    def quad(self):
        return [Pixel(self.x & ~1 | dx, self.y & ~1 | dy, self.k) for dy in (0, 1) for dx in (0, 1)]


def outputs(*registers):
    return [f"v_mov_b32_e32 v{12 + n}, {r}" for n, r in enumerate(registers)]


# --- if/else with both skips (ACO's begin_divergent_if_then / _else / end_divergent_if), and an execnz region ---------
IF_ELSE = [
    "v_mov_b32_e32 v22, 1.0",
    "v_mov_b32_e32 v23, 2.0",
    "v_mov_b32_e32 v27, 1.0",
    "v_cmp_lt_f32_e32 vcc_lo, s44, v12",  # c = T < R
    "s_and_saveexec_b64 s[60:61], vcc",
    "s_cbranch_execz BB1_2",  # skip then
    "BB1_1:",
    "v_mov_b32_e32 v22, 4.0",
    "v_add_f32_e32 v23, 1.0, v23",
    "BB1_2:",
    "s_andn2_b64 exec, s[60:61], exec",  # else
    "s_cbranch_execz BB1_4",  # skip else
    "BB1_3:",
    "v_mov_b32_e32 v22, 0x41000000",
    "BB1_4:",
    "s_mov_b64 exec, s[60:61]",  # join
    "v_add_f32_e32 v26, v22, v23",
    "s_mov_b64 s[64:65], exec",
    "v_cmpx_lt_f32_e32 s45, v13",  # e = T2 < G
    "s_cbranch_execnz BB1_6",  # taken whenever a lane is active: the region runs only with EXEC = 0
    "BB1_5:",
    "v_mov_b32_e32 v27, 4.0",
    "BB1_6:",
    "s_mov_b64 exec, s[64:65]",
    *outputs("v22", "v23", "v26", "v27"),
]


def if_else_reference(p):
    c = f32(p.k[0]) < p.R
    return [4.0 if c else 8.0, 3.0 if c else 2.0, 7.0 if c else 10.0, 1.0]


def if_else_quad(p):
    """The skips decided per quad: the then-arm skipped where any lane of the quad is off, the else-arm where any
    lane of the quad took the then-arm."""
    cs = [f32(q.k[0]) < q.R for q in p.quad()]
    c = f32(p.k[0]) < p.R
    v22 = (4.0 if all(cs) else 1.0) if c else (8.0 if not any(cs) else 1.0)
    return v22


IF_ELSE_BUGS = [
    (0, if_else_quad),  # skip branches taken as if uniform (per quad)
    (1, lambda p: 3.0),  # the then region not predicated: its add reaches the else lanes
    (3, lambda p: 4.0 if f32(p.k[1]) < p.G else 1.0),  # the execnz region run for the active lanes
    (3, lambda p: 4.0),  # the execnz region not predicated
]
IF_ELSE_SETS = ((0.2, 0.3, 0, 0), (0.5, 0.05, 0, 0), (-1.0, 2.0, 0, 0))

# --- an if nested in a skipped then-arm, with its own save and skip, and a uniform vccnz inside the region -----------
NESTED = [
    "v_mov_b32_e32 v22, 0",
    "v_mov_b32_e32 v23, 0",
    "v_mov_b32_e32 v26, 0",
    "v_cmp_lt_f32_e32 vcc_lo, s44, v12",  # a = T1 < R
    "s_and_saveexec_b64 s[60:61], vcc",
    "s_cbranch_execz BB2_6",
    "BB2_1:",
    "v_add_f32_e32 v22, 1.0, v22",
    "v_cmp_lt_f32_e64 vcc_lo, s46, s47",  # u = s46 < s47: uniform, at the region's entry EXEC
    "s_cbranch_vccnz BB2_3",
    "BB2_2:",
    "v_add_f32_e32 v26, 4.0, v26",  # !u, masked by a
    "BB2_3:",
    "v_cmp_lt_f32_e32 vcc_lo, s45, v13",  # a && b, b = T2 < G
    "s_and_saveexec_b64 s[62:63], vcc",
    "s_cbranch_execz BB2_5",
    "BB2_4:",
    "v_add_f32_e32 v23, 2.0, v23",
    "BB2_5:",
    "s_mov_b64 exec, s[62:63]",  # restores the mask saved inside the region
    "v_add_f32_e32 v22, 2.0, v22",
    "BB2_6:",
    "s_mov_b64 exec, s[60:61]",
    *outputs("v22", "v23", "v26", "1.0"),
]


def nested_inputs(p):
    return f32(p.k[0]) < p.R, f32(p.k[1]) < p.G, f32(p.k[2]) < f32(p.k[3])


def nested_reference(p):
    a, b, u = nested_inputs(p)
    return [3.0 if a else 0.0, 2.0 if a and b else 0.0, 4.0 if a and not u else 0.0, 1.0]


NESTED_BUGS = [
    (0, lambda p: 3.0),  # the outer region not predicated
    (1, lambda p: 2.0 if nested_inputs(p)[1] else 0.0),  # the inner region predicated by b alone
    (2, lambda p: 4.0 if nested_inputs(p)[0] and nested_inputs(p)[2] else 0.0),  # vccnz polarity flipped
    (1, lambda p: 2.0 if all(nested_inputs(q)[0] and nested_inputs(q)[1] for q in p.quad())
                  else 0.0),  # the inner skip taken as if uniform (per quad)
]
NESTED_SETS = ((0.2, 0.3, 1.0, 2.0), (0.5, 0.1, 2.0, 1.0))

# --- s_cbranch_vccz / vccnz on compares of constants, SGPRs and a uniform VGPR -----------------------------------------
UVCC = [
    "v_mov_b32_e32 v22, 1.0",
    "v_mov_b32_e32 v23, 1.0",
    "v_cmp_lt_f32_e64 vcc_lo, s44, s45",  # u1 = s44 < s45
    "s_cbranch_vccz BB4_2",
    "BB4_1:",
    "v_mov_b32_e32 v22, 2.0",
    "BB4_2:",
    "v_mov_b32_e32 v24, s46",
    "v_add_f32_e32 v24, 0.5, v24",  # a uniform VGPR
    "v_cmp_gt_f32_e32 vcc_lo, 1.0, v24",  # u2 = 1 > s46 + 0.5
    "s_cbranch_vccnz BB4_4",
    "BB4_3:",
    "v_mov_b32_e32 v23, 4.0",
    "BB4_4:",
    "v_cmp_ngt_f32_e64 vcc_lo, 1.0, s45",  # an else-if chain on h = s45 (post_process_color_cycle's shape)
    "s_cbranch_vccz BB4_8",  # 1 > h
    "BB4_5:",
    "v_cmp_ngt_f32_e64 vcc_lo, 2.0, s45",
    "s_cbranch_vccz BB4_7",  # 2 > h
    "BB4_6:",
    "v_mov_b32_e32 v28, 4.0",
    "s_branch BB4_9",  # both inner arms jump to the outer join
    "BB4_7:",
    "v_mov_b32_e32 v28, 2.0",
    "s_branch BB4_9",
    "BB4_8:",
    "v_mov_b32_e32 v28, 1.0",
    "BB4_9:",
    "v_cmp_lt_f32_e32 vcc_lo, s47, v12",  # a per-lane compare, used as data only
    "v_cndmask_b32_e64 v26, 0, 1.0, vcc_lo",
    *outputs("v22", "v23", "v26", "v28"),
]


def uvcc_inputs(p):
    return f32(p.k[0]) < f32(p.k[1]), 1.0 > f32(p.k[2]) + 0.5


def uvcc_reference(p):
    u1, u2 = uvcc_inputs(p)
    h = f32(p.k[1])
    return [2.0 if u1 else 1.0, 1.0 if u2 else 4.0, float(f32(p.k[3]) < p.R), 4.0 if h >= 2 else 2.0 if h >= 1 else 1.0]


UVCC_BUGS = [
    (0, lambda p: 1.0 if uvcc_inputs(p)[0] else 2.0),  # vccz polarity flipped
    (1, lambda p: 4.0 if uvcc_inputs(p)[1] else 1.0),  # vccnz polarity flipped
    (3, lambda p: {4.0: 2.0, 2.0: 4.0}.get(uvcc_reference(p)[3], 1.0)),  # the inner vccz of the chain flipped
]
UVCC_SETS = ((1.0, 2.0, 0.25, 0.3), (2.0, 1.0, 3.0, 0.5), (0.0, 0.5, 0.25, 0.3))

# --- a uniform loop with a vccnz back edge on a float counter, containing a divergent if with a skip -------------------
LOOP = [
    "v_mov_b32_e32 v24, 0",  # c = 0.0
    "v_mov_b32_e32 v25, 0",  # acc
    "v_mov_b32_e32 v26, 0",  # count
    "BB5_1:",
    "v_add_f32_e32 v25, v24, v25",  # acc += c
    "v_add_f32_e32 v24, 1.0, v24",  # c += 1
    "v_mul_f32_e32 v27, 0x3e000000, v24",  # t = c / 8, uniform
    "v_cmp_lt_f32_e32 vcc_lo, v27, v12",  # t < R
    "s_and_saveexec_b64 s[60:61], vcc",
    "s_cbranch_execz BB5_3",
    "BB5_2:",
    "v_add_f32_e32 v26, 1.0, v26",
    "BB5_3:",
    "s_mov_b64 exec, s[60:61]",
    "v_cmp_gt_f32_e32 vcc_lo, s47, v24",  # N > c
    "s_cbranch_vccnz BB5_1",
    "BB5_4:",
    *outputs("v24", "v25", "v26", "1.0"),
]


def loop_reference(p, n_bias=0, predicated=True):
    n = int(f32(p.k[3])) + n_bias
    count = sum(1 for c in range(1, n + 1) if not predicated or c / 8 < p.R)
    return [float(n), float(sum(range(n))), float(count), 1.0]


LOOP_BUGS = [
    (2, lambda p: loop_reference(p, -1)[2]),  # one iteration short
    (1, lambda p: loop_reference(p, 1)[1]),  # one iteration long
    (2, lambda p: loop_reference(p, predicated=False)[2]),  # the region not predicated
]
LOOP_SETS = ((0, 0, 0, 3.0), (0, 0, 0, 7.0))

# --- an implicit-LOD sample inside a skipped region (the shadowmapping shape): a full program ----------------------------
SAMPLE = [
    "s_mov_b64 s[50:51], exec",
    "s_wqm_b64 exec, exec",
    "s_mov_b32 m0, s24",
    "v_interp_p1_f32_e32 v8, v0, attr0.x",
    "v_interp_p1_f32_e32 v9, v0, attr0.y",
    "v_interp_p2_f32_e32 v9, v1, attr0.y",
    "v_interp_p2_f32_e32 v8, v1, attr0.x",
    "s_mov_b32 s21, 0",
    "s_load_dwordx8 s[28:35], s[20:21], null",
    "s_load_dwordx4 s[44:47], s[20:21], 0x40",
    "s_mov_b32 s40, 1",
    "s_mov_b32 s41, 2",
    "s_mov_b32 s42, 3",
    "s_mov_b32 s43, 4",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc",
    "s_waitcnt lgkmcnt(0)",
    "v_add_f32_e32 v10, 0, v8",  # u, defined on the helper lanes too
    "v_mov_b32_e32 v12, 0",
    "v_mov_b32_e32 v13, 0",
    "v_mov_b32_e32 v14, 0",
    "v_mov_b32_e32 v15, 0",
    "v_cmp_lt_f32_e32 vcc_lo, s44, v10",  # c = T < u
    "s_and_saveexec_b64 s[60:61], vcc",
    "s_cbranch_execz BB7_2",
    "BB7_1:",
    "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
    "s_waitcnt vmcnt(0)",
    "BB7_2:",
    "s_mov_b64 exec, s[60:61]",
    "s_and_b64 exec, exec, s[50:51]",
    *(line for n in range(12, 16) for line in (f"v_mul_f32_e32 v{n}, 0x437f0000, v{n}", f"v_rndne_f32_e32 v{n}, v{n}")),
    "v_cvt_pkrtz_f16_f32_e32 v16, v12, v13",
    "v_cvt_pkrtz_f16_f32_e32 v17, v14, v15",
    "exp mrt0 v16, v16, v17, v17 done compr vm",
    "s_endpgm",
]


def texel(p):
    return [float(RAMP[p.x]), float(RAMP[p.y]), 128.0, 255.0]


def sample_reference(p):
    return texel(p) if f32(p.k[0]) < p.u else [0.0] * 4


SAMPLE_BUGS = [
    (0, lambda p: float(RAMP[p.x])),  # the region not predicated
    (0, lambda p: float(RAMP[p.x]) if all(f32(q.k[0]) < q.u for q in p.quad()) else 0.0),  # skip per quad
]
SAMPLE_SETS = ((0.4, 0, 0, 0), (0.6, 0, 0, 0), (-1.0, 0, 0, 0))


def targets_only(program):
    """The program without the labels no branch names: the disassembler prints only branch targets, so the binary
    fixtures lower the same instruction indices (ACO's fall-through block labels are kept in the text above)."""
    named = {line.split()[-1] for line in program if line.startswith(("s_branch ", "s_cbranch_"))}
    return [line for line in program if not line.endswith(":") or line[:-1] in named]


def programs():
    """(name, full program, reference, constant sets, wrong references)."""
    return [(name, targets_only(program), *rest) for name, program, *rest in (
        ("cf2_skip_if_else", with_constants(IF_ELSE), if_else_reference, IF_ELSE_SETS, IF_ELSE_BUGS),
        ("cf2_skip_nested", with_constants(NESTED), nested_reference, NESTED_SETS, NESTED_BUGS),
        ("cf2_uvcc", with_constants(UVCC), uvcc_reference, UVCC_SETS, UVCC_BUGS),
        ("cf2_uvcc_loop", with_constants(LOOP), loop_reference, LOOP_SETS, LOOP_BUGS),
        ("cf2_sample", SAMPLE, sample_reference, SAMPLE_SETS, SAMPLE_BUGS))]


def pixels(constants):
    words = tuple(word(c) for c in constants)
    return [Pixel(x, y, words) for y in range(8) for x in range(8)]


def case_bytes(constants, reference):
    case = bytearray(256)
    struct.pack_into("<4I", case, 12, *(word(c) for c in constants))
    for p in pixels(constants):
        case.extend(struct.pack("<4f", *reference(p)))
    return bytes(case)


def with_bug(reference, channel, wrong):
    def buggy(p):
        values = list(reference(p))
        values[channel] = wrong(p)
        return values
    return buggy


def check_references():
    """Offline: every result is exact in binary16, and every wrong reference differs from the reference in at least
    one pixel of one constant set (so its draw must report a mismatch)."""
    for name, _, reference, sets, bugs in programs():
        for constants in sets:
            for p in pixels(constants):
                for value in reference(p):
                    assert value == struct.unpack("<e", struct.pack("<e", value))[0], (name, value)
        for n, (channel, wrong) in enumerate(bugs):
            buggy = with_bug(reference, channel, wrong)
            assert any(buggy(p) != reference(p) for c in sets for p in pixels(c)), (name, n)


def check_cf2_skip_draws(directory, compiler, renderer, backend):
    source, shader, case = directory / "fixture.hlsl", directory / "fixture.cso", directory / "cf2_skip.case"
    for name, program, reference, sets, bugs in programs():
        source.write_text(translate(program), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for constants in sets:
            case.write_bytes(case_bytes(constants, reference))
            subprocess.run(draw, check=True)
        for n, (channel, wrong) in enumerate(bugs):
            buggy = with_bug(reference, channel, wrong)
            caught = False
            for constants in sets:
                if all(buggy(p) == reference(p) for p in pixels(constants)):
                    continue
                case.write_bytes(case_bytes(constants, buggy))
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


def check_cf2_skip_controls():
    check_references()
    for name, program, *_ in programs():
        text = translate(program).split("float4 main", 1)[1]
        # Predicate mode: no HLSL branch on the lane bit; the only ifs are the uniform VCC branches (bool cf<i>).
        assert "s_cbranch_exec" not in text and all(line.strip().startswith(("if (cf", "if (!cf"))
                                                    for line in text.splitlines() if line.strip().startswith("if (")), name
    # ACO's text, with a label on every block, lowers to the same HLSL.
    for body, program in ((IF_ELSE, 0), (NESTED, 1), (UVCC, 2), (LOOP, 3), (SAMPLE, 4)):
        full = body if body is SAMPLE else with_constants(body)
        assert any(line.endswith(":") for line in full) and len(full) > len(programs()[program][1])
        translate(full)
    # The implicit-LOD sample of the skipped region is in uniform flow: no if or loop before it, and its result is
    # masked (and waits for vmcnt like a memory word).
    text = translate(SAMPLE).split("float4 main", 1)[1]
    head = text.split(".Sample(", 1)[0]
    assert "if (" not in head and "while" not in head and "mem_ex" in text, text
    # The uniform VCC branches branch on the unmasked compare; the loop is a CF-1 loop with a vccnz back edge.
    text = translate(with_constants(NESTED))
    assert "bool cf" in text and "(asfloat(params[1].y) < asfloat(params[1].z))" in text.split("bool cf", 1)[1].split(";")[0], text
    assert "[loop] while (true)" in translate(with_constants(LOOP))

    # Narrow-only: a skipped region that restores a mask saved outside it re-enables lanes the wave never ran.
    rejected("EXEC re-enabled inside a skipped region", with_constants(replace(
        IF_ELSE, "s_cbranch_execz BB1_2", ["s_cbranch_execz BB1_4"])))
    rejected("EXEC re-enabled inside a skipped region", with_constants(replace(
        NESTED, "s_mov_b64 exec, s[62:63]", ["s_mov_b64 exec, s[60:61]"])))
    rejected("EXEC re-enabled inside a skipped region", with_constants([
        "s_mov_b64 s[64:65], exec", "v_cmpx_lt_f32_e32 s44, v12", "s_cbranch_execz BB0_2", "BB0_1:",
        "s_mov_b64 exec, s[64:65]", "v_mov_b32_e32 v12, 1.0", "BB0_2:",
        "s_mov_b64 exec, s[64:65]"]))
    # Poison: a scalar written in a skipped region and read after it.
    poisoned = replace(NESTED, "s_mov_b64 exec, s[60:61]", ["s_mov_b64 exec, s[60:61]", "s_mov_b64 vcc, s[62:63]",
                                                           "v_cndmask_b32_e64 v26, 0, 1.0, vcc_lo"])
    rejected("Scalar value depends on another lane", with_constants(poisoned))
    rejected("Scalar value depends on another lane", with_constants([
        "s_mov_b32 s70, 1", "v_cmp_lt_f32_e32 vcc_lo, s44, v12", "s_and_saveexec_b64 s[60:61], vcc",
        "s_cbranch_execz BB0_2", "BB0_1:", "s_mov_b32 s70, 2", "BB0_2:", "s_mov_b64 exec, s[60:61]",
        "v_mov_b32_e32 v12, s70"]))
    # ... unless both paths leave it equal, or the lane is provably active (the wave cannot skip).
    translate(with_constants(["s_mov_b32 s70, 1", "v_cmp_lt_f32_e32 vcc_lo, s44, v12",
                              "s_and_saveexec_b64 s[60:61], vcc", "s_cbranch_execz BB0_2", "BB0_1:",
                              "s_mov_b32 s70, 1", "BB0_2:", "s_mov_b64 exec, s[60:61]", "v_mov_b32_e32 v12, s70"]))
    translate(with_constants(["s_mov_b32 s70, 1", "s_cbranch_execz BB0_2", "BB0_1:", "s_mov_b32 s70, 2", "BB0_2:",
                              "v_mov_b32_e32 v12, s70"]))
    # A uniform join of a lane mask with data: the register is unreadable after it (CF-1 refused the join itself).
    mixed = ["v_cmp_lt_f32_e32 vcc_lo, s44, v12", "s_mov_b64 s[70:71], vcc", "s_cmp_eq_u32 s46, s47",
             "s_cbranch_scc1 BB0_2", "s_mov_b32 s70, 7", "BB0_2:"]
    translate(with_constants(mixed))
    rejected("Descriptor state differs at a join", with_constants(mixed + ["v_mov_b32_e32 v12, s70"]))
    rejected("Descriptor state differs at a join", with_constants(mixed + ["s_mov_b64 vcc, s[70:71]",
                                                                            "v_cndmask_b32_e64 v12, 0, 1.0, vcc_lo"]))
    # A scalar written in a skipped region inside a uniform loop is poisoned from the next iteration on.
    looped = replace(LOOP, "v_add_f32_e32 v26, 1.0, v26", ["v_add_f32_e32 v26, 1.0, v26", "s_mov_b32 s70, 3"])
    translate(with_constants(["s_mov_b32 s70, 1"] + looped))
    rejected("Scalar value depends on another lane", with_constants(
        ["s_mov_b32 s70, 1"] + replace(looped, "v_add_f32_e32 v25, v24, v25", ["v_add_f32_e32 v25, s70, v25"])))
    # Uniform VCC: a per-lane compare, a mask operation, a compare made while the wave may have had no active lane
    # (EXEC narrowed since the region began), and a compare whose operand changed before the branch are refused.
    rejected("not wave-uniform", with_constants(replace(UVCC, "v_cmp_lt_f32_e64 vcc_lo, s44, s45",
                                                        ["v_cmp_lt_f32_e64 vcc_lo, s44, v12"])))
    rejected("not wave-uniform", with_constants(replace(UVCC, "v_add_f32_e32 v24, 0.5, v24",
                                                        ["v_add_f32_e32 v24, v12, v24"])))
    rejected("needs VCC from a compare", with_constants(replace(UVCC, "v_cmp_lt_f32_e64 vcc_lo, s44, s45",
                                                                ["v_cmp_lt_f32_e64 vcc_lo, s44, s45",
                                                                 "s_andn2_b64 vcc, exec, vcc"])))
    rejected("no active lane", with_constants(replace(NESTED, "v_cmp_lt_f32_e64 vcc_lo, s46, s47",
                                                      ["v_cmpx_lt_f32_e32 s45, v13", "v_cmp_lt_f32_e64 vcc_lo, s46, s47"])))
    rejected("no active lane", with_constants(["s_mov_b64 s[64:65], exec", "v_cmpx_lt_f32_e32 s44, v12",
                                               "v_cmp_lt_f32_e64 vcc_lo, s46, s47", "s_mov_b64 exec, s[64:65]",
                                               "s_cbranch_vccz BB0_2", "BB0_1:", "v_mov_b32_e32 v12, 1.0", "BB0_2:"]))
    # A masked VGPR is not uniform, even with uniform inputs.
    rejected("not wave-uniform", with_constants(["s_mov_b64 s[64:65], exec", "v_cmpx_lt_f32_e32 s44, v12",
                                                 "v_mov_b32_e32 v24, s46", "s_mov_b64 exec, s[64:65]",
                                                 "v_cmp_gt_f32_e32 vcc_lo, 1.0, v24", "s_cbranch_vccz BB0_2",
                                                 "BB0_1:", "v_mov_b32_e32 v12, 1.0", "BB0_2:"]))
    # Skips must jump forward over a region of the enclosing structure; an export may not be inside one.
    rejected("skip branch on EXEC must jump forward", with_constants([
        "BB0_1:", "v_mov_b32_e32 v12, 1.0", "s_cbranch_execnz BB0_1"]))
    rejected("Color export or program end inside a skipped region", replace(
        with_constants([]), "exp mrt0 v16, v16, v17, v17 done compr vm",
        ["s_cbranch_execz BB0_2", "BB0_1:", "exp mrt0 v16, v16, v17, v17 done compr vm", "BB0_2:"]))
    # The all-lanes-dead block: a skip to it is not taken. After it EXEC may only narrow, so a killed lane cannot
    # come back, and the export discards it (CF-2d).
    null = ["exp null off, off, off, off done vm", "s_endpgm"]
    accepted = with_constants(["s_cbranch_execz BB0_9", "v_mov_b32_e32 v12, 1.0"]) + ["BB0_9:", *null]
    assert "exp null" not in translate(accepted)
    killed = with_constants(["s_mov_b64 s[64:65], exec", "v_cmpx_lt_f32_e32 s44, v12", "s_cbranch_execz BB0_9",
                             "s_mov_b64 exec, s[64:65]"]) + ["BB0_9:", *null]
    rejected("EXEC re-enabled inside a skipped region", killed)
    nested_kill = with_constants(["v_cmp_lt_f32_e32 vcc_lo, s44, v12", "s_and_saveexec_b64 s[60:61], vcc",
                                  "s_cbranch_execz BB0_2", "v_cmpx_lt_f32_e32 s45, v13", "s_cbranch_execz BB0_9",
                                  "BB0_2:", "s_mov_b64 exec, s[60:61]"]) + ["BB0_9:", *null]
    rejected("EXEC re-enabled inside a skipped region", nested_kill)
    # Since CF-2d the killed lane is discarded at the export (family cf2_discard).
    assert "    if (!ex" in translate(with_constants(["v_cmpx_lt_f32_e32 s44, v12", "s_cbranch_execz BB0_9"])
                                    + ["BB0_9:", *null])
    # A skip to a block that is not the dead block is an ordinary skip, so its region must end inside the program.
    rejected("Branch leaves its region", with_constants(["s_cmp_eq_u32 s44, s45",
                                                         "s_cbranch_scc1 BB0_2", "s_cbranch_execz BB0_3", "BB0_2:",
                                                         "v_mov_b32_e32 v12, 1.0", "BB0_3:"]))


def controls(directory):
    check_cf2_skip_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers (wave32)."""
    return [(program, translate) for _, program, *_ in programs()]


draw = check_cf2_skip_draws
