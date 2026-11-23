"""Draw family `pxblk`: pixel_aot_check.py draw --family pxblk.

Forms whose corpus shaders (tools/corpus_translate.py) were refused for a reason narrower than the form's contract."""
import math
import struct
import subprocess

from .common import DrawBatch, assembly, byte, f32, half_rtz, must_reject, translate, ubyte, with_constants
from .pkrtz import TIE, half_bits, rtn_ref


def pending_window(body):
    """with_constants(), with body placed while the image_sample of the reference program is still outstanding (after
    the scalar loads have landed, before s_waitcnt vmcnt(0)): the shape of a deferred-shading export, whose packs of
    unrelated registers sit between a sample and its wait."""
    program = with_constants([])
    wait = program.index("s_waitcnt vmcnt(0)")
    program[wait:wait] = body
    return program


READBACK = [ubyte(n, 12 + n, "v20", "e32") for n in range(4)]
# The words of constants 3 and 4 (s44, s45): a tie (toward zero differs from nearest even), an overflow, a negative.
WORD_SETS = ((TIE, -65520.0), (-(3 + 3 * 2.0 ** -10), f32(0.3)), (0.0, -0.75))

# (body in the pending window, model(x, y) -> word, {bug: wrong(x, y) -> word})
PACK_E64_PENDING = (
    (["v_mov_b32_e32 v18, s44", "v_cvt_pkrtz_f16_f32_e64 v20, v18, 1.0"],
     lambda x, y: half_bits(x) | half_bits(1.0) << 16,
     {"swapped": lambda x, y: half_bits(1.0) | half_bits(x) << 16,
      "nearest_even": lambda x, y: (struct.unpack("<H", struct.pack("<e", 65504.0 if abs(x) >= 65520 else rtn_ref(x)))[0]
                                    | half_bits(1.0) << 16),
      "second_is_x": lambda x, y: half_bits(x) | half_bits(x) << 16}),
    (["v_cvt_pkrtz_f16_f32_e64 v20, -|s45|, s44"],
     lambda x, y: half_bits(-abs(y)) | half_bits(x) << 16,
     {"neg_dropped": lambda x, y: half_bits(abs(y)) | half_bits(x) << 16,
      "abs_dropped": lambda x, y: half_bits(-y) | half_bits(x) << 16,
      "swapped": lambda x, y: half_bits(x) | half_bits(-abs(y)) << 16}),
)


# (name, body, in the pending window, constants struct format, constant sets, model, {bug: wrong}); a case packs its set
# at byte 12 (constant words 3 to 6, s44 to s47), and the draw reads the word model(*set) back as four bytes of v20.
CASES = [(f"pack_e64_window{index}", body, True, "<2f", WORD_SETS, model, bugs)
         for index, (body, model, bugs) in enumerate(PACK_E64_PENDING)]

# s_mov_b32 m0, <constant word>; s_mov_b32 s48, m0: the copy out of m0 returns the word that was put in, whole.
M0_WORDS = ((0xff800001, 0), (0x00000001, 0), (0x80000000, 0), (0x12345678, 0))
M0_BODY = ["s_mov_b32 m0, s44", "s_mov_b32 s48, m0", "v_mov_b32_e32 v20, s48"]
CASES.append(("copy_from_m0", M0_BODY, False, "<2I", M0_WORDS, lambda a, b: a,
              {"zeroed": lambda a, b: 0, "sign_cleared": lambda a, b: a & 0x7fffffff,
               "swapped_bytes": lambda a, b: int.from_bytes(a.to_bytes(4, "little"), "big")}))


# omod on the exact rounding forms: the result of floor, ceil or trunc scaled by 2, 4 or 0.5, as the binary32 bits of the
# value read back whole. The sets cover a fraction on each side of zero, an integer and a value whose double is infinity;
# none rounds to a negative zero, whose sign a D3D adapter need not keep.
ROUND = {"floor": math.floor, "ceil": math.ceil, "trunc": math.trunc}
FACTORS = {" mul:2": 2.0, " mul:4": 4.0, " div:2": 0.5}
ROUND_SETS = ((2.5, 0.0), (-2.75, 0.0), (0.75, 0.0), (-1.25, 0.0), (7.0, 0.0), (3.0e38, 0.0), (-1.5e30, 0.0))


def bits_of(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def rounded(op, x):
    value = float(ROUND[op](x)) if math.isfinite(x) else x
    return math.copysign(value, x) if value == 0 else value


def scaled_bits(op, x, factor):
    result = rounded(op, x) * factor
    return bits_of(math.copysign(math.inf, result) if abs(result) >= 2.0 ** 128 else result)


for op in ROUND:
    for omod, factor in FACTORS.items():
        others = [o for o in ROUND if o != op]
        bugs = {"omod_dropped": lambda x, y, op=op: bits_of(rounded(op, x)),
                "wrong_factor": lambda x, y, op=op, factor=factor: scaled_bits(op, x, 4.0 if factor == 2.0 else 2.0),
                "other_op_a": lambda x, y, o=others[0], factor=factor: scaled_bits(o, x, factor),
                "other_op_b": lambda x, y, o=others[1], factor=factor: scaled_bits(o, x, factor)}
        CASES.append((f"{op}{omod.replace(' ', '_').replace(':', '')}", [f"v_{op}_f32_e64 v20, s44{omod}"], False, "<2f",
                      ROUND_SETS, lambda x, y, op=op, factor=factor: scaled_bits(op, x, factor), bugs))


# neg(<float inline constant>), LLVM's spelling of the neg modifier on 0.5, 2.0 and the like, as a source of add and mul.
def f32_round(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


NEG_SETS = ((1.75, 0.0), (-3.0, 0.0), (0.5, 0.0), (1e10, 0.0), (-0.125, 0.0))
CASES.append(("neg_inline_add", ["v_add_f32_e64 v20, s44, neg(0.5)"], False, "<2f", NEG_SETS,
              lambda x, y: bits_of(f32_round(x - 0.5)),
              {"sign_dropped": lambda x, y: bits_of(f32_round(x + 0.5)), "constant_dropped": lambda x, y: bits_of(x),
               "negated_result": lambda x, y: bits_of(f32_round(0.5 - x))}))
CASES.append(("neg_inline_mul", ["v_mul_f32_e64 v20, s44, neg(2.0)"], False, "<2f", NEG_SETS,
              lambda x, y: bits_of(f32_round(x * -2.0)),
              {"sign_dropped": lambda x, y: bits_of(f32_round(x * 2.0)), "wrong_constant": lambda x, y: bits_of(f32_round(x * -0.5))}))


def case_program(body, window):
    program = pending_window(body) if window else with_constants(body)
    at = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[at:at] = READBACK
    return program


def check_pxblk_draws(directory, compiler, renderer, backend):
    for name, body, window, fmt, sets, model, bugs in CASES:
        source = directory / f"pxblk_{name}.hlsl"
        shader = directory / f"pxblk_{name}.cso"
        source.write_text(translate(case_program(body, window)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        batch = DrawBatch(directory, renderer, backend, shader, f"pxblk_{name}")
        separated = {bug: False for bug in bugs}
        for values in sets:
            values = [f32(v) for v in values] if fmt.endswith("f") else list(values)
            constants = bytearray(256)
            struct.pack_into(fmt, constants, 12, *values)
            word = model(*values)
            batch.add(bytes(constants) + struct.pack("<4f", *[float(byte(word, n)) for n in range(4)]) * 64, "pass",
                      f"{name} is wrong for {values} on {backend}")
            for bug, wrong in bugs.items():
                if wrong(*values) == word:
                    continue
                separated[bug] = True
                batch.add(bytes(constants) + struct.pack("<4f", *[float(byte(wrong(*values), n)) for n in range(4)]) * 64, "mismatch",
                          f"Wrong reference {bug} escaped detection in {name}")
        batch.flush()
        assert all(separated.values()), (name, separated)


def case_program_window(body):
    return case_program(body, True)


def check_pxblk_controls():
    # neg(<float>) negates the constant; a doubled sign, an integer-looking one in a float operand's position keeps its own
    # rule, and a malformed spelling is refused.
    main = translate(case_program(["v_add_f32_e64 v20, s44, neg(0.5)"], False)).split("float4 main", 1)[1]
    assert "(-0.5f)" in main, main
    for line in ("v_add_f32_e64 v20, s44, neg(-0.5)", "v_add_f32_e64 v20, s44, neg(0.5", "v_add_f32_e64 v20, s44, neg(x)",
                 "v_add_f32_e64 v20, s44, neg()", "v_add_f32_e64 v20, s44, neg(0.5.5)"):
        must_reject(translate, case_program([line], False))
    for name, body, window, *_ in CASES:
        source = translate(case_program(body, window))
        assert ("pack16_rtz(" in source.split("float4 main", 1)[1]) == name.startswith("pack"), source
    # m0 is copied out as the tracked word: the HLSL moves the constant word, and an m0 nothing has set is refused.
    assert "params[" in translate(case_program(M0_BODY, False)).split("float4 main", 1)[1]
    program = assembly(False)
    program[program.index("s_mov_b32 m0, s24")] = "s_mov_b32 s60, m0"
    try:
        translate(program)
    except ValueError as error:
        assert "Read of unset scalar register m0" in str(error), error
    else:
        raise AssertionError("a copy out of an unset m0 was accepted")
    # A source or the destination that is the sample's own register is still refused while the sample is in flight,
    # and so is clamp.
    must_reject(translate, case_program_window(["v_cvt_pkrtz_f16_f32_e64 v20, v13, 1.0"]))
    must_reject(translate, case_program_window(["v_cvt_pkrtz_f16_f32_e64 v13, s44, 1.0"]))
    must_reject(translate, case_program_window(["v_cvt_pkrtz_f16_f32_e64 v20, s44, 1.0 clamp"]))


def check_empty_labelled():
    # RADV prints a label on its one block ("BB0:"): the empty program is the same with it, and only s_endpgm is empty.
    assert translate(["BB0:", "s_endpgm"]) == translate(["s_endpgm"])
    assert translate(["BB0:", "s_endpgm"]).endswith("    return;\n}\n")
    must_reject(translate, ["BB0:", "s_endpgm", "s_endpgm"])
    must_reject(translate, ["BB0:", "s_nop 0", "s_endpgm"])


def controls(directory):
    check_empty_labelled()
    check_pxblk_controls()


draw = check_pxblk_draws
