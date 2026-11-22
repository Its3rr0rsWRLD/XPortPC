"""Draw family `cf2_lane`: pixel_aot_check.py draw --family cf2_lane.

CF-2a (docs/design/control-flow.md, CF-2 sections 2 and 3): EXEC is this lane's bit `ex`, whole-quad mode is a flag
(`wqm`), and a VGPR written while the lane may be inactive keeps its old value (`ex ? new : old`). No instruction of
CF-2a can make `ex` anything but true in a program that lowers, so the draws cover what the lane model newly accepts
(VALU, uniform branches, the sample and the export in whole-quad mode, as ACO lays them out; a select on a saved
EXEC), and the controls drive the inner states (a lane that may be inactive, masked writes, EXEC narrowing) through
the forms directly."""
from pixel_aot_ops.dispatch import dispatch
from pixel_aot_ops.lowering import Lowering, masked_writes

from .cf_uniform import CF_IF_ELSE_BODY, CF_LOOP_BODY, CF_PROGRAMS, check_cf_uniform_draws, must_reject_for
from .common import translate, ubyte, with_constants


def aco_shape(body):
    """The common program as ACO emits it: whole-quad mode from the start and never left, so the constant loads,
    the sample, `body` and the export all run in it."""
    return [line for line in with_constants(body)
            if line not in ("s_mov_b64 s[50:51], exec", "s_and_b64 exec, exec, s[50:51]")]


def in_wqm(wave64):
    """VALU and a uniform branch inside the whole-quad region of the common program, before and between the
    interpolation steps; after the sample, a select on the EXEC saved before whole-quad mode (wave64 names)."""
    def build(body):
        program = with_constants(body)
        at = program.index("s_mov_b32 m0, s24") + 1
        program[at:at] = ["v_mov_b32_e32 v20, 0x40400000", "s_mov_b32 s60, 5", "s_cmp_lt_u32 s60, 7",
                          "s_cbranch_scc0 BB0_9", "v_add_f32_e32 v20, 2.0, v20", "BB0_9:"]
        at = program.index("v_interp_p1_f32_e32 v9, v0, attr0.y") + 1
        program[at:at] = ["v_mul_f32_e32 v21, 0.5, v20"]
        return program
    select = "v_cndmask_b32_e64 v14, 0, 1.0, s[50:51]" if wave64 else "v_mov_b32_e32 v14, 1.0"
    body = ["v_mov_b32_e32 v12, v20", "v_mov_b32_e32 v13, v21", select, ubyte(0, 15, "s44", "e32")]
    return body, build


IF_ELSE, LOOP = (next(p for p in CF_PROGRAMS if p[0] is body) for body in (CF_IF_ELSE_BODY, CF_LOOP_BODY))
WQM_SETS = ((0x12, 0, 0, 0), (0xff, 7, 0, 0))
WQM_BUGS = [(0, lambda x, y, z, w: 3.0),  # the uniform branch in whole-quad mode not taken
            (1, lambda x, y, z, w: 1.5),  # the move between the interpolation steps saw the value before the branch
            (2, lambda x, y, z, w: 0.0),  # the saved EXEC read as off for a covered pixel
            (3, lambda x, y, z, w: float((x >> 8) & 0xff))]


def wqm_reference(x, y, z, w):
    return [5.0, 2.5, 1.0, float(x & 0xff)]


def check_cf2_lane_draws(directory, compiler, renderer, backend):
    aco = [(aco_shape(body), reference, sets, bugs) for body, reference, sets, bugs in (IF_ELSE, LOOP)]
    if code := check_cf_uniform_draws(directory, compiler, renderer, backend, aco, "cf2_aco", lambda p: p):
        return code
    for wave64 in (False, True):
        body, build = in_wqm(wave64)
        programs = [(body, wqm_reference, WQM_SETS, WQM_BUGS)]
        if code := check_cf_uniform_draws(directory, compiler, renderer, backend, programs, f"cf2_wqm{int(wave64)}", build):
            return code
    return 0


def lane(ex, **vector):
    """A lowering state in the middle of a program: interpolated, sampled, constants loaded, lane bit `ex`."""
    st = Lowering({"s44": ("uint", "params[3].x")}, {"v0": "bary_i", "v1": "bary_j", "v12": "sample4.x",
                                                     "v13": "sample4.y", **vector}, [], {0: "tex"}, [1, 2, 3, 4], 64, {})
    st.ex = ex
    return st


def step(st, i, line):
    """One instruction as lower() runs it: masked writes apply while ex is not "true"."""
    ex, before = st.ex, dict(st.vector)
    dispatch(st, i, line)
    if ex != "true":
        masked_writes(st, i, ex, before)


def refused(text, st, i, line):
    try:
        step(st, i, line)
    except ValueError as error:
        assert text in str(error), (text, str(error))
        return
    raise AssertionError(f"{line!r} accepted with ex = {st.ex}")


def check_cf2_lane_controls():
    # The lane starts active and outside whole-quad mode; mask is the old view of the state, kept for older forms.
    st = lane("true")
    assert (st.ex, st.wqm, st.mask) == ("true", False, "entry")
    step(st, 1, "s_mov_b64 s[50:51], exec")
    assert st.scalar["s50"] == ("condition", "true", 0, 2) and st.scalar["s51"] == ("condition", "true", 1, 2)
    step(st, 2, "s_wqm_b64 exec, exec")
    assert (st.ex, st.wqm, st.mask) == ("true", True, "quad") and st.lines == []
    refused("Unsupported instruction", st, 3, "s_wqm_b64 exec, exec")
    # An active lane writes without a select, in or out of whole-quad mode.
    step(st, 4, "v_add_f32_e32 v20, v12, v13")
    assert st.vector["v20"] == "alu4" and st.lines == ["    precise float alu4 = (sample4.x + sample4.y);"], st.lines
    # The restore of a mask saved while active keeps ex true, emits nothing and leaves whole-quad mode.
    step(st, 5, "s_and_b64 exec, exec, s[50:51]")
    assert (st.ex, st.wqm, st.mask) == ("true", False, "entry") and len(st.lines) == 1
    refused("Unsupported execution mask", st, 6, "s_and_b64 exec, exec, s[44:45]")
    st.scalar["s51"] = ("condition", "true", 0, 2)
    refused("Unsupported execution mask", st, 6, "s_and_b64 exec, exec, s[50:51]")  # halves of different masks

    # Narrowing EXEC by a compare's mask: ex becomes a bool local, ANDed with the previous bit.
    st = lane("true")
    st.scalar.update({"s60": ("condition", "cmp3", 0, 2), "s61": ("condition", "cmp3", 1, 2),
                      "s62": ("condition", "cmp4", 0, 2), "s63": ("condition", "cmp4", 1, 2)})
    step(st, 5, "s_and_b64 exec, exec, s[60:61]")
    assert st.ex == "ex5" and st.lines == ["    bool ex5 = cmp3;"] and st.mask == "partial"
    step(st, 6, "s_and_b64 exec, exec, s[62:63]")
    assert st.ex == "ex6" and st.lines[-1] == "    bool ex6 = ex5 && cmp4;"
    step(st, 7, "s_mov_b64 s[70:71], exec")
    assert st.scalar["s70"] == ("condition", "ex6", 0, 2)  # a saved mask holds the lane's bit at the save

    # The masked-write helper: a write while the lane may be inactive keeps the old value.
    st = lane("ex9", v20="alu2", v21=("uint", "valu3"), v22=("uint", "params[4].y"), v23="uv.x")
    step(st, 10, "v_mul_f32_e32 v20, v12, v13")
    assert st.lines[-2:] == ["    precise float alu10 = (sample4.x * sample4.y);",
                             "    uint exw10_20 = ex9 ? asuint(alu10) : asuint(alu2);"], st.lines
    assert st.vector["v20"] == ("uint", "exw10_20")
    step(st, 11, "v_add_f32_e32 v24, v20, v13")  # a masked float result is a raw word that float readers accept
    assert st.lines[-1] == "    precise float alu11 = (asfloat(exw10_20) + sample4.y);" and st.vector["v24"] == "alu11"
    step(st, 12, "v_xor_b32_e32 v21, s44, v21")  # an integer result over an integer result
    assert st.lines[-1] == "    uint exv12_21 = ex9 ? valu12 : valu3;" and st.vector["v21"] == ("uint", "exv12_21")
    step(st, 13, "v_mov_b32_e32 v22, s44")  # a raw word over a raw word
    assert st.lines[-1] == "    uint exw13_22 = ex9 ? movw13 : params[4].y;"
    lines = list(st.lines)
    step(st, 14, "s_mov_b32 s45, s44")  # scalar ALU is not masked: no VGPR changes, no select
    assert st.lines == lines and st.scalar["s45"] == st.scalar["s44"]
    refused("Masked write of a register that does not hold a 32-bit word", st, 15, "v_mov_b32_e32 v23, 1.0")
    refused("Masked write of a register that does not hold a 32-bit word", st, 15, "v_mov_b32_e32 v0, 1.0")
    # What cannot be masked yet is refused while the lane may be inactive: SDWA lane-mask writes (VOPC ones are masked
    # since CF-2b, family cf2_exec), interpolation and loads. The pack is not masked but recorded, and the export
    # discards the lane when it is off (CF-2d, family cf2_discard).
    st.wqm = True
    st.scalar.update({"m0": "interp_base", "vcc": ("condition", "cmp1", 0, 1)})
    for text, line in (("Invalid comparison", "v_cmp_lt_f32_sdwa vcc_lo, v12, v13 src0_sel:DWORD src1_sel:DWORD"),
                       ("Unknown interpolation context", "v_interp_p1_f32_e32 v8, v0, attr0.x"),
                       ("Unknown interpolation context", "v_interp_mov_f32_e32 v8, p0, attr1.x"),
                       ("Unsupported instruction", "s_wqm_b64 exec, exec")):
        refused(text, st, 16, line)
    step(st, 16, "v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    assert st.vector["v16"] == ("sample4.x", "sample4.y") and st.pack_ex == {"v16": {16: "ex9"}}, st.pack_ex
    st.vector.update({"v17": ("sample4.z", "sample4.w")})
    step(st, 17, "exp mrt0 v16, v16, v17, v17 done compr vm")
    assert st.lines[-2:] == ["    if (!ex9) discard;", "    return float4(export16(sample4.x), export16(sample4.y), "
                             "export16(sample4.z), export16(sample4.w));"], st.lines[-2:]
    st.exported = False
    for text, line in (("Invalid image operation", "image_load v[12:15], v[8:9], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm"),
                        ("Invalid buffer load", "buffer_load_dword v20, v12, s[28:31], 0 offen"),
                        ("Invalid global load", "global_load_dword v20, v[12:13], off")):
        refused(text, st, 18, line)
    # The select on a mask that is the lane's own bit: wave64 names it as the pair; the wave32 half is refused.
    st = lane("true")
    st.scalar.update({"s50": ("condition", "true", 0, 2), "s51": ("condition", "true", 1, 2)})
    step(st, 20, "v_cndmask_b32_e64 v14, 0, 1.0, s[50:51]")
    assert st.lines[-1] == "    uint selw20 = true ? 1065353216u : 0u;", st.lines
    refused("Select mask is not a tracked comparison", st, 21, "v_cndmask_b32_e64 v14, 0, 1.0, s50")

    # Through lower(): a narrowed EXEC reaches the export, which discards the lanes that are off (CF-2d), and the lane
    # bit differing between the paths of a uniform branch is joined (CF-2e).
    narrowed = with_constants(["v_cmp_lt_f32_e64 s[60:61], v12, v13", "s_and_b64 exec, exec, s[60:61]",
                               "v_mov_b32_e32 v12, 1.0"])
    assert "    if (!ex" in translate(narrowed)  # since CF-2d the export discards the lanes that are off
    program = with_constants([])
    sample = program.index("image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D")
    for mask, accepted in (("s[60:61]", False), ("s[50:51]", True)):  # a compare's mask, or the saved EXEC
        twin = program[:sample] + ["v_cmp_lt_f32_e64 s[60:61], 1.0, 2.0", f"s_and_b64 exec, exec, {mask}"] + program[sample:]
        if accepted:
            assert "bool ex" not in translate(twin)
        else:
            # Since CF-2c the sample is masked (family cf2_skip); since CF-2d the export discards the lanes that are off.
            assert "    if (!ex" in translate(twin)
    split = with_constants(["v_cmp_lt_f32_e64 s[60:61], v12, v13", "s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 BB0_1",
                            "s_and_b64 exec, exec, s[60:61]", "BB0_1:"])
    # Since CF-2e the lane bit is joined (`bool jx_<tag>`) and the export discards the lanes that are off.
    assert "bool jx_" in translate(split)
    # The ACO layout and the whole-quad work the draws render, checked for their HLSL here.
    body = translate(aco_shape(CF_IF_ELSE_BODY)).split("float4 main", 1)[1]
    assert "bool cf" in body and "} else {" in body and "tex.Sample" in body and " ? " not in body, body
    for wave64 in (False, True):
        program = in_wqm(wave64)[1](in_wqm(wave64)[0])
        text = translate(program)
        assert "bool ex" not in text and "exw" not in text and "bool cf" in text, text
    # Interpolation still needs whole-quad mode: before it and after the restore it is refused.
    program = with_constants([])
    must_reject_for("Unknown interpolation context", translate,
                    [line for line in program if line != "s_wqm_b64 exec, exec"])


def controls(directory):
    check_cf2_lane_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers (wave32)."""
    body, build = in_wqm(False)
    return [(aco_shape(CF_IF_ELSE_BODY), translate), (aco_shape(CF_LOOP_BODY), translate), (build(body), translate)]


draw = check_cf2_lane_draws
