"""Draw family `cf_uniform`: pixel_aot_check.py draw --family cf_uniform."""
import struct
import subprocess

from .common import M32, assembly, byte, half_rtz, signed, translate, ubyte, with_constants


# Control flow, CF-1 (docs/design/control-flow.md): labels, uniform branches on SCC, if, if-else and loops with one back
# edge. Every program is spliced into the common sample program by with_constants and its four results are read back
# as bytes (v_cvt_f32_ubyte) or exact small floats. Conditions come from the constant words x, y, z, w = s44..s47, so
# each draw runs both directions of every branch across its constant sets. Each program is (body, reference, sets, bugs)
# like INT_PROGRAMS: the reference computes the four channels from the words independently, and each bug is a wrong
# reference (else taken for then, a loop one iteration short or long, the pre-branch value kept at the join, a word
# changed at the join) that must be reported as a mismatch in at least one set.
def triangular(n):
    return n * (n + 1) // 2


def squares(n):
    return n * (n + 1) * (2 * n + 1) // 6


CF_IF_BODY = [
    "v_mov_b32_e32 v18, 0x10",
    "s_cmp_lt_u32 s44, s45",
    "s_cbranch_scc0 BB0_1",
    "v_mov_b32_e32 v18, 0x21",
    "BB0_1:",
    "v_mov_b32_e32 v19, 0x30",
    "s_cmp_ge_i32 s46, s47",
    "s_cbranch_scc0 BB0_2",
    "v_mov_b32_e32 v19, 0x41",
    "BB0_2:",
    "v_mov_b32_e32 v20, 0x50",
    "s_cmp_eq_u32 s44, s46",
    "s_cbranch_scc1 BB0_3",
    "v_mov_b32_e32 v20, 0x61",
    "BB0_3:",
    "v_mov_b32_e32 v21, 0x70",
    "s_cmp_gt_u32 s47, 7",
    "s_cbranch_scc1 BB0_4",
    "v_mov_b32_e32 v21, 0x81",
    "BB0_4:",
    *[ubyte(0, 12 + n, f"v{18 + n}", "e32") for n in range(4)],
]

CF_IF_ELSE_BODY = [
    "v_mov_b32_e32 v18, 0x77",
    "s_cmp_lg_u32 s44, s45",
    "s_cbranch_scc0 BB0_2",
    "v_mov_b32_e32 v18, 0x11",
    "v_mov_b32_e32 v19, 0x22",
    "s_branch BB0_3",
    "BB0_2:",
    "v_mov_b32_e32 v18, 0x33",
    "v_mov_b32_e32 v19, 0x44",
    "BB0_3:",
    "s_cmp_le_u32 s46, s47",
    "s_cbranch_scc1 BB0_5",
    "v_xor_b32_e32 v20, s46, v19",
    "s_branch BB0_6",
    "BB0_5:",
    "v_and_b32_e32 v20, s47, v18",
    "BB0_6:",
    ubyte(0, 12, "v18", "e32"), ubyte(0, 13, "v19", "e32"), ubyte(0, 14, "v20", "e32"), ubyte(1, 15, "v20", "e32"),
]

CF_NAN_BODY = [
    "v_mov_b32_e32 v22, s44",
    "s_cmp_eq_u32 s45, s46",
    "s_cbranch_scc0 BB0_2",
    "v_xor_b32_e32 v22, 0x80000000, v22",
    "s_branch BB0_3",
    "BB0_2:",
    "v_mov_b32_e32 v22, s47",
    "BB0_3:",
    *[ubyte(n, 12 + n, "v22", "e32") for n in range(4)],
]

CF_LOOP_BODY = [
    "s_mov_b32 s48, 0",
    "v_mov_b32_e32 v12, 0",
    "v_mov_b32_e32 v13, 0",
    "s_cmp_eq_u32 s44, 0",
    "s_cbranch_scc1 BB0_2",
    "BB0_1:",
    "v_add_f32_e32 v12, 1.0, v12",
    "s_add_u32 s48, s48, 1",
    ubyte(0, 21, "s48", "e32"),
    "v_add_f32_e32 v13, v13, v21",
    "s_cmp_lt_u32 s48, s44",
    "s_cbranch_scc1 BB0_1",
    "BB0_2:",
    "s_mov_b32 s49, 0",
    "v_mov_b32_e32 v14, 0",
    "BB0_3:",
    "s_cmp_ge_u32 s49, s44",
    "s_cbranch_scc1 BB0_5",
    "s_add_u32 s49, s49, 1",
    ubyte(0, 22, "s49", "e32"),
    "v_mul_f32_e32 v22, v22, v22",
    "v_add_f32_e32 v14, v14, v22",
    "s_branch BB0_3",
    "BB0_5:",
    ubyte(0, 15, "s48", "e32"),
]

CF_NESTED_BODY = [
    "s_mov_b32 s48, 0",
    "v_mov_b32_e32 v12, 0",
    "v_mov_b32_e32 v13, 0",
    "v_mov_b32_e32 v15, 0",
    "BB0_1:",
    "s_cmp_lt_u32 s48, s45",
    "s_cbranch_scc0 BB0_3",
    "v_add_f32_e32 v12, 1.0, v12",
    "v_mov_b32_e32 v13, 1.0",
    "s_branch BB0_4",
    "BB0_3:",
    "v_add_f32_e32 v12, 0x41200000, v12",
    "v_mov_b32_e32 v13, 2.0",
    "v_add_f32_e32 v15, 1.0, v15",
    "BB0_4:",
    "s_add_u32 s48, s48, 1",
    "s_cmp_lt_u32 s48, s44",
    "s_cbranch_scc1 BB0_1",
    ubyte(0, 14, "s48", "e32"),
]

CF_MASK_BODY = [
    "v_mov_b32_e32 v18, 0x31",
    "v_mov_b32_e32 v19, 0x62",
    "s_cmp_lt_u32 s46, s47",
    "s_cbranch_scc0 BB0_2",
    "v_cmp_class_f32_e64 vcc_lo, s44, 0x60",
    "s_branch BB0_3",
    "BB0_2:",
    "v_cmp_class_f32_e64 vcc_lo, s45, 0x60",
    "BB0_3:",
    "v_cndmask_b32_e32 v20, v18, v19, vcc_lo",
    ubyte(0, 12, "v20", "e32"), ubyte(0, 13, "v18", "e32"), ubyte(0, 14, "v19", "e32"), ubyte(1, 15, "v20", "e32"),
]

CF_SCALAR_BODY = [
    "s_mov_b32 s50, s44",
    "s_sub_u32 s51, s44, s45",
    "s_cbranch_scc0 BB0_1",
    "s_add_u32 s50, s50, 0x100",
    "BB0_1:",
    "s_add_u32 s52, s46, s47",
    "s_cbranch_scc0 BB0_2",
    "s_mov_b32 s53, 0x5a",
    "s_branch BB0_3",
    "BB0_2:",
    "s_mov_b32 s53, 0xa5",
    "BB0_3:",
    ubyte(1, 12, "s50", "e32"), ubyte(0, 13, "s50", "e32"), ubyte(0, 14, "s53", "e32"), ubyte(0, 15, "s52", "e32"),
]


def quieted(word):
    return word | 0x400000


CF_PROGRAMS = (
    (CF_IF_BODY,
     lambda x, y, z, w: [0x21 if x < y else 0x10, 0x41 if signed(z) >= signed(w) else 0x30,
                         0x50 if x == z else 0x61, 0x70 if w > 7 else 0x81],
     ((3, 9, 3, 0xfffffff0), (9, 3, 4, 5), (0xfffffffe, 1, 0x80000000, 0x7fffffff), (7, 7, 8, 8)),
     [(0, lambda x, y, z, w: 0x10 if x < y else 0x21),  # else taken instead of then
      (1, lambda x, y, z, w: 0x41 if z >= w else 0x30),  # unsigned compare for signed
      (2, lambda x, y, z, w: 0x61 if x == z else 0x50),
      (3, lambda x, y, z, w: 0x81 if w > 7 else 0x70)]),
    (CF_IF_ELSE_BODY,
     lambda x, y, z, w: [0x11 if x != y else 0x33, 0x22 if x != y else 0x44,
                         byte((w & (0x11 if x != y else 0x33)) if z <= w else z ^ (0x22 if x != y else 0x44), 0),
                         byte((w & (0x11 if x != y else 0x33)) if z <= w else z ^ (0x22 if x != y else 0x44), 1)],
     ((5, 5, 0x12345, 3), (5, 6, 3, 0x1f1f), (8, 9, 0x2000, 0x2000)),
     [(0, lambda x, y, z, w: 0x77),  # the join keeps the pre-branch value
      (0, lambda x, y, z, w: 0x33 if x != y else 0x11),  # else taken instead of then
      (1, lambda x, y, z, w: 0x44 if x != y else 0x22),
      (2, lambda x, y, z, w: byte(z ^ (0x22 if x != y else 0x44), 0) if z <= w else byte(w & (0x11 if x != y else 0x33), 0)),
      (3, lambda x, y, z, w: byte(z ^ (0x22 if x != y else 0x44), 1) if z <= w else byte(w & (0x11 if x != y else 0x33), 1))]),
    (CF_NAN_BODY,
     lambda x, y, z, w: [byte((x ^ 0x80000000) if y == z else w, n) for n in range(4)],
     ((0xff800001, 1, 1, 0x7fc12345), (0xffc00000, 1, 2, 0xfffffffe), (0x7f800001, 7, 7, 0x00264543),
      (0xfffffffe, 3, 3, 0xff800001), (0x7f800001, 3, 4, 0x7f800001)),
     [(2, lambda x, y, z, w: byte(quieted((x ^ 0x80000000) if y == z else w), 2)),  # NaN quieted at the join
      (3, lambda x, y, z, w: byte(x if y == z else w, 3))]  # sign not flipped
     + [(n, lambda x, y, z, w, n=n: byte(w if y == z else (x ^ 0x80000000), n)) for n in range(4)]  # else taken instead of then
     + [(n, lambda x, y, z, w, n=n: byte(0x7fffffff if ((((x ^ 0x80000000) if y == z else w)) & 0x7fffffff) > 0x7f800000
                                         else ((x ^ 0x80000000) if y == z else w), n)) for n in range(4)]),  # canonical NaN
    (CF_LOOP_BODY,
     lambda n, y, z, w: [float(n), float(triangular(n)), float(squares(n)), float(n)],
     ((0, 0, 0, 0), (1, 0, 0, 0), (5, 0, 0, 0), (3, 0, 0, 0)),
     [(0, lambda n, y, z, w: float(max(n - 1, 0))), (0, lambda n, y, z, w: float(n + 1)),
      (0, lambda n, y, z, w: float(max(n, 1))),  # the guard ignored: a do-while runs once
      (1, lambda n, y, z, w: float(triangular(max(n - 1, 0)))), (1, lambda n, y, z, w: float(triangular(n + 1))),
      (2, lambda n, y, z, w: float(squares(max(n - 1, 0)))), (2, lambda n, y, z, w: float(squares(n + 1))),
      (3, lambda n, y, z, w: 0.0)]),  # the join keeps the value before the branch
    (CF_NESTED_BODY,
     lambda n, k, z, w: [float(sum(1 if i < k else 10 for i in range(max(n, 1)))),
                         1.0 if max(n, 1) - 1 < k else 2.0, float(max(n, 1)),
                         float(sum(1 for i in range(max(n, 1)) if i >= k))],
     ((5, 2, 0, 0), (3, 10, 0, 0), (4, 0, 0, 0), (1, 1, 0, 0)),
     [(0, lambda n, k, z, w: float(sum(10 if i < k else 1 for i in range(max(n, 1))))),  # else taken instead of then
      (0, lambda n, k, z, w: float(sum(1 if i < k else 10 for i in range(max(n, 1) - 1)))),
      (0, lambda n, k, z, w: float(sum(1 if i < k else 10 for i in range(max(n, 1) + 1)))),
      (1, lambda n, k, z, w: 2.0 if max(n, 1) - 1 < k else 1.0),
      (2, lambda n, k, z, w: float(max(n, 1) - 1)),
      (3, lambda n, k, z, w: float(sum(1 for i in range(max(n, 1) + 1) if i >= k)))]),
    (CF_MASK_BODY,
     lambda x, y, z, w: [0x62 if ((x if z < w else y) & 0x7fffffff) == 0 else 0x31, 0x31, 0x62,
                         0],
     ((0, 0x3f800000, 1, 2), (0x3f800000, 0x80000000, 5, 2), (0x3f800000, 0x3f800000, 1, 2), (0, 0x3f800000, 3, 2)),
     [(0, lambda x, y, z, w: 0x62 if (x & 0x7fffffff) == 0 else 0x31),  # the join keeps the first arm
      (0, lambda x, y, z, w: 0x62 if (y & 0x7fffffff) == 0 else 0x31),  # the join keeps the second arm
      (0, lambda x, y, z, w: 0x31 if ((x if z < w else y) & 0x7fffffff) == 0 else 0x62)]),  # inverted
    (CF_SCALAR_BODY,
     lambda x, y, z, w: [byte((x + 0x100) & M32 if x < y else x, 1), byte((x + 0x100) & M32 if x < y else x, 0),
                         0x5a if z + w > M32 else 0xa5, byte((z + w) & M32, 0)],
     ((0x1234, 0x2000, 0xfffffff0, 0x20), (0x7056, 0x2000, 5, 6), (0x1234, 0x1234, 0x80000000, 0x80000000)),
     [(0, lambda x, y, z, w: byte(x, 1)),  # the join keeps the pre-branch value
      (0, lambda x, y, z, w: byte(x if x < y else (x + 0x100) & M32, 1)),  # else taken instead of then
      (2, lambda x, y, z, w: 0xa5 if z + w > M32 else 0x5a),
      (3, lambda x, y, z, w: byte((z + w) & M32, 1))]),
)


def check_cf_uniform_draws(directory, compiler, renderer, backend):
    case = directory / "cf.case"
    for index, (body, reference, sets, bugs) in enumerate(CF_PROGRAMS):
        source = directory / f"cf{index}.hlsl"
        shader = directory / f"cf{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = [float(value) for value in reference(*words)]
            for x in expected:
                assert half_rtz(x) == x, x
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for k, (channel, buggy) in enumerate(bugs):
                value = float(buggy(*words))
                if value == expected[channel]:
                    continue
                separated[k] = True
                assert half_rtz(value) == value, value
                wrong_values = list(expected)
                wrong_values[channel] = value
                case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong control-flow result escaped detection in program {index}, channel {channel}, words {words}")
        assert all(separated), (index, separated)


def cf_program(*lines, constants=True):
    """The common program with `lines` between the sample and the export; constants s44..s47 are loaded."""
    return with_constants(list(lines)) if constants else assembly(False)


def must_reject_for(text, function, *args):
    try:
        function(*args)
    except (ValueError, KeyError) as error:
        assert text in str(error), (text, str(error))
        return
    raise AssertionError(f"{function.__name__} accepted invalid input (expected: {text})")


def check_cf_uniform_controls():
    # The lowering is structured: an if keeps its join variables, a loop is a [loop] while with its break last.
    body = translate(CF_IF_ELSE_BODY and with_constants(CF_IF_ELSE_BODY)).split("float4 main", 1)[1]
    assert "uint jv_v18_" in body and "uint jv_v19_" in body and "} else {" in body, body
    body = translate(with_constants(CF_LOOP_BODY)).split("float4 main", 1)[1]
    assert body.count("[loop] while (true) {") == 2 and "break;" in body and "uint js_s48_" in body, body
    # Label names do not matter.
    renamed = [line.replace("BB0_", "Lbl.") for line in with_constants(CF_NESTED_BODY)]
    assert translate(renamed) == translate(with_constants(CF_NESTED_BODY))
    # A branch to an unknown label.
    must_reject_for("unknown label", translate, with_constants(["s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 NOWHERE"]))
    must_reject_for("unknown label", translate, with_constants(["s_branch NOWHERE"]))
    # A label defined twice.
    must_reject_for("defined twice", translate, with_constants(["L1:", "s_nop 0", "L1:"]))
    # SCC not tracked: no compare, a compare cleared by an exec change, a compare in an earlier block.
    must_reject_for("tracked SCC", translate, with_constants(["s_cbranch_scc1 L1", "L1:"]))
    must_reject_for("tracked SCC", translate, with_constants(["s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 L1", "L1:",
                                                              "s_cbranch_scc0 L2", "L2:"]))
    # A condition of a vector compare is not an SCC.
    must_reject_for("tracked SCC", translate, with_constants(["v_cmp_class_f32_e64 vcc_lo, s44, 3", "s_cbranch_scc1 L1", "L1:"]))
    # Export on only one path: the other path reaches s_endpgm without one.
    one_path = with_constants([])
    export = one_path.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    one_path[export:export] = ["s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 BB0_9"]
    one_path.insert(one_path.index("s_endpgm"), "BB0_9:")
    must_reject_for("export on only one path", translate, one_path)
    # An export in each arm, then the shared s_endpgm, is one export on every path.
    both = with_constants([])
    first = both.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    exporting = both[first:both.index("s_endpgm")]
    both[first:first] = ["s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 BB0_8"]
    both[both.index("s_endpgm"):both.index("s_endpgm")] = [
        "s_branch BB0_9", "BB0_8:", "v_cvt_pkrtz_f16_f32_e32 v16, v13, v12", "v_cvt_pkrtz_f16_f32_e32 v17, v15, v14",
        "exp mrt0 v16, v16, v17, v17 done compr vm", "BB0_9:"]
    body = translate(both).split("float4 main", 1)[1]
    assert body.count("return float4(") == 2 and "} else {" in body, body
    # Descriptor provenance that differs at a join: one arm overwrites a descriptor word.
    program = with_constants([])
    sample = program.index("image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D")
    program[sample:sample] = ["s_cmp_eq_u32 s40, s41", "s_cbranch_scc1 BB0_9", "s_mov_b32 s30, 0", "BB0_9:"]
    must_reject_for("Descriptor state differs", translate, program)
    # A sampler word changed on one path is data, so it joins; the sample then refuses the changed binding.
    program = with_constants([])
    program[sample:sample] = ["s_cmp_eq_u32 s40, s41", "s_cbranch_scc1 BB0_9", "s_mov_b32 s40, 5", "BB0_9:"]
    must_reject_for("Unsupported image or sampler binding", translate, program)
    # An irreducible shape: a jump into the middle of a loop.
    must_reject_for("irreducible", translate, with_constants([
        "s_mov_b32 s48, 0", "s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 BB0_2",
        "BB0_1:", "s_add_u32 s48, s48, 1",
        "BB0_2:", "s_cmp_lt_u32 s48, s46", "s_cbranch_scc1 BB0_1"]))
    # A loop with a second exit, and a loop with no exit at all.
    must_reject_for("leaves its region", translate, with_constants([
        "s_mov_b32 s48, 0",
        "BB0_1:", "s_cmp_eq_u32 s48, s45", "s_cbranch_scc1 BB0_3",
        "s_add_u32 s48, s48, 1", "s_cmp_lt_u32 s48, s44", "s_cbranch_scc1 BB0_1",
        "s_nop 0", "BB0_3:", "s_nop 0"]))
    must_reject_for("A loop must leave", translate, with_constants(["s_mov_b32 s48, 0", "BB0_1:", "s_add_u32 s48, s48, 1", "s_branch BB0_1"]))
    # An unconditional branch that is neither an else jump nor a loop edge.
    must_reject_for("Unconditional branch", translate, with_constants(["s_branch BB0_2", "s_nop 0", "BB0_2:", "s_nop 0"]))
    # A branch in quad execution mode.
    program = with_constants([])
    wqm = program.index("s_wqm_b64 exec, exec")
    program[wqm + 1:wqm + 1] = ["s_mov_b32 s60, 0", "s_cmp_eq_u32 s60, 0", "s_cbranch_scc1 BB0_9", "BB0_9:"]
    must_reject_for("quad", translate, program)
    # A register defined on only one path is unset after the join; a loop-local register is unset after the loop.
    must_reject_for("unset", translate, with_constants([
        "v_mov_b32_e32 v18, 1", "s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 BB0_1", "v_mov_b32_e32 v19, 2", "BB0_1:",
        ubyte(0, 12, "v19", "e32")]))
    must_reject_for("unset", translate, with_constants([
        "s_mov_b32 s48, 0", "BB0_1:", "v_mov_b32_e32 v19, 2", "s_add_u32 s48, s48, 1", "s_cmp_lt_u32 s48, s44",
        "s_cbranch_scc1 BB0_1", ubyte(0, 12, "v19", "e32")]))


def controls(directory):
    check_cf_uniform_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for body, *_ in CF_PROGRAMS),
    ]


draw = check_cf_uniform_draws
