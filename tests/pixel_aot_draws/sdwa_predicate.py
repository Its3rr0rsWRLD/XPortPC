"""Draw family `sdwa_predicate`: pixel_aot_check.py draw --family sdwa_predicate."""
import math
import struct
import subprocess

from .common import must_reject, translate, with_constants
from .predicate import PREDICATES, predicate_group
from .sdwa import H, MODIFIED, S, SELECTORS, Z, half_of, model_field


# The SDWA comparisons with whole-dword selections repeat the 16-predicate draws, including NaN on either side.
# For each group a reference that inverts the unordered (NaN) result must report a mismatch.
def check_sdwa_predicate_draws(directory, compiler, renderer, backend):
    source = directory / "sdwa_predicates.hlsl"
    shader = directory / "sdwa_predicates.cso"
    case = directory / "sdwa_predicates.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    inputs = ((-1, 1, 0), (-0.0, 0.0, 1), (1, -1, 2), (math.nan, 1, 3), (1, math.nan, 3))
    for first in range(0, 16, 4):
        source.write_text(translate(predicate_group(first, sdwa=True)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        for left, right, relation in inputs:
            constants = bytearray(256)
            struct.pack_into("<4f", constants, 12, left, right, 0, 1)
            expected = [float((op >> relation) & 1) for op in range(first, first + 4)]
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
        wrong = [1.0 - value for value in expected]
        case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"An inverted unordered SDWA comparison escaped detection, first={first}")


# Binary16 comparisons and class tests with selected sources. Each channel is one test of a program: v18 and v19
# hold the words a and b, v22 the binary32 word f. A channel's source specs are (selector, sext, modifier) as in the
# `sdwa` family. The reference reads the selected bits as a half, applies abs/neg to bit 15 and relates the two
# values (less, equal, greater, unordered); the class tests use the ISA class bits. For every channel and input,
# the references with the other selector (or the other extension of the class mask, or no modifier) are wrong
# references: wherever one differs from the right value the draw must fail.
F16_CHANNELS = (
    (Z("WORD_0"), Z("WORD_1")), (Z("WORD_1"), Z("WORD_0")),
    (Z("WORD_1", "negabs"), Z("WORD_1")), (Z("WORD_0"), Z("WORD_0", "neg")),
)
COMPARE_INPUTS = (
    (H(0x3c00, 0xbc00), H(0x4000, 0x3c00)), (H(0x3800, 0x8000), H(0x3800, 0x0000)), (H(0x7e00, 0x4000), H(0x3c00, 0x7e00)),
    (H(0xc200, 0x4400), H(0xc200, 0x3c00)), (H(0x3c00, 0x3c00), H(0x4000, 0xbc00)),
    (H(0x7e00, 0x4000), H(0x3c00, 0x4400)), (H(0x4000, 0x7e00), H(0x4400, 0x3c00)),
)
CLASS_CHANNELS = (
    ("f16", Z("WORD_1"), S("BYTE_2")), ("f16", Z("WORD_0"), Z("BYTE_2")),
    ("f32", ("DWORD", False, ""), Z("WORD_1")), ("f32", ("DWORD", False, ""), S("BYTE_0")),
)
# a: binary16 halves (high, low); b: the class mask word; f: a binary32 value.
CLASS_INPUTS = (
    (H(0x3c00, 0x3c00), 0x03800080, 0x3f800000), (H(0x0001, 0xfc00), 0x0000ff04, 0x00000001),
    (H(0x7c00, 0x8000), H(0x0200, 0x0400), 0xff800000), (H(0x7e00, 0xc200), H(0x0082, 0x0002), 0x7fc00000),
    (H(0x0000, 0x4400), H(0x0040, 0x00a0), 0x80000000), (H(0x3c00, 0x0200), 0x00800040, 0xc0000000),
)


def half_relation(x, y):
    return 3 if x != x or y != y else 0 if x < y else 1 if x == y else 2


def half_class(bits):
    sign, exponent, mantissa = bits >> 15, (bits >> 10) & 31, bits & 0x3ff
    if exponent == 31:
        return 1 << ((1 if mantissa & 0x200 else 0) if mantissa else 2 + (0 if sign else 7))
    if exponent == 0:
        return 1 << ((4 if sign else 7) if mantissa else (5 if sign else 6))
    return 1 << (3 if sign else 8)


def float_class(bits):
    sign, exponent, mantissa = bits >> 31, (bits >> 23) & 255, bits & 0x7fffff
    if exponent == 255:
        return 1 << ((1 if mantissa & 0x400000 else 0) if mantissa else 2 + (0 if sign else 7))
    if exponent == 0:
        return 1 << ((4 if sign else 7) if mantissa else (5 if sign else 6))
    return 1 << (3 if sign else 8)


def half_source(word, src):
    return MODIFIED[src[2]](model_field(word, src[0], src[1]) & 0xffff)


COMPARE_WRONGS = ("source0 selector", "source1 selector", "modifiers")


def compare_value(op, a, b, channel, wrong=None):
    """The truth of one compare channel, with one kind of wrong selection if asked."""
    sources = list(F16_CHANNELS[channel])
    for index, kind in enumerate(COMPARE_WRONGS[:2]):
        if wrong == kind:
            sel, sext, mod = sources[index]
            sources[index] = (f"WORD_{1 - int(sel[-1])}", sext, mod)
    if wrong == "modifiers":
        sources = [(sel, sext, "") for sel, sext, _ in sources]
    values = [half_of(half_source(word, src)) for word, src in zip((a, b), sources)]
    return float((PREDICATES.index(op) >> half_relation(*values)) & 1)


def f16_compare_program(first):
    body = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_sub_f32_e64 v21, s47, 0"]
    for channel, ((sel0, _, mod0), (sel1, _, mod1)) in enumerate(F16_CHANNELS):
        token = lambda reg, mod: {"": reg, "neg": f"-{reg}", "abs": f"|{reg}|", "negabs": f"-|{reg}|"}[mod]
        body += [f"v_cmp_{PREDICATES[first + channel]}_f16_sdwa vcc_lo, {token('v18', mod0)}, {token('v19', mod1)} src0_sel:{sel0} src1_sel:{sel1}",
                 f"v_cndmask_b32_e32 v{12 + channel}, 0, v21, vcc_lo"]
    return with_constants(body)


def class_value(channel, a, b, f, wrong=None):
    kind, x, mask = CLASS_CHANNELS[channel]
    if wrong == "mask selector":
        mask = (f"WORD_{1 - int(mask[0][-1])}" if mask[0].startswith("WORD") else f"BYTE_{(int(mask[0][-1]) + 1) % 4}", mask[1], mask[2])
    elif wrong == "mask extension":
        mask = (mask[0], not mask[1], mask[2])
    elif wrong == "source selector":
        x = (f"WORD_{1 - int(x[0][-1])}", x[1], x[2]) if kind == "f16" else x
    bits = model_field(b, mask[0], mask[1])
    classes = half_class(half_source(a, x)) if kind == "f16" else float_class(f)
    return float(bool(classes & bits))


CLASS_WRONGS = ("mask selector", "mask extension", "source selector")


def class_program():
    body = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v22, s46", "v_sub_f32_e64 v21, s47, 0"]
    for channel, (kind, (sel0, _, _), (sel1, sext, _)) in enumerate(CLASS_CHANNELS):
        mask = f"sext(v19)" if sext else "v19"
        body += [f"v_cmp_class_{kind}_sdwa vcc_lo, {'v18' if kind == 'f16' else 'v22'}, {mask} src0_sel:{sel0} src1_sel:{sel1}",
                 f"v_cndmask_b32_e32 v{12 + channel}, 0, v21, vcc_lo"]
    return with_constants(body)


def check_f16_sdwa_draws(directory, compiler, renderer, backend):
    case = directory / "sdwa_f16.case"
    shader = directory / "sdwa_f16.cso"
    source = directory / "sdwa_f16.hlsl"
    draw = [renderer, backend, "--check-pixel-case", shader, case]

    def run(program, words, expected, wrong_label=None):
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words, 0x3f800000)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        if wrong_label is None:
            subprocess.run(draw, check=True)
            return
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"A wrong SDWA reference ({wrong_label}) escaped detection for {words}")

    for first in range(0, 16, 4):
        source.write_text(translate(f16_compare_program(first)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        ops = PREDICATES[first:first + 4]
        for a, b in COMPARE_INPUTS:
            right = [compare_value(op, a, b, k) for k, op in enumerate(ops)]
            run(None, (a, b, 0), right)
            for wrong in COMPARE_WRONGS:
                values = [compare_value(op, a, b, k, wrong) for k, op in enumerate(ops)]
                if values != right:
                    run(None, (a, b, 0), values, f"{wrong}, group {first}")
    source.write_text(translate(class_program()), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for a, b, f in CLASS_INPUTS:
        right = [class_value(k, a, b, f) for k in range(4)]
        run(None, (a, b, f), right)
        for wrong in CLASS_WRONGS:
            values = [class_value(k, a, b, f, wrong) for k in range(4)]
            if values != right:
                run(None, (a, b, f), values, f"class {wrong}")


def check_selection_coverage():
    """Each channel of each program has, among the inputs, a wrong reference that differs from the right one."""
    for first in range(0, 16, 4):
        for channel in range(4):
            op = PREDICATES[first + channel]
            for wrong in COMPARE_WRONGS:
                shown = any(compare_value(op, a, b, channel, wrong) != compare_value(op, a, b, channel) for a, b in COMPARE_INPUTS)
                needed = wrong != "modifiers" or any(src[2] for src in F16_CHANNELS[channel])
                # f and tru ignore their operands; o and u only see whether one is a NaN, which a sign does not change.
                assert shown or not needed or op in ("f", "tru") or (op in ("o", "u") and wrong == "modifiers"), (op, channel, wrong)
    for channel, (kind, x, mask) in enumerate(CLASS_CHANNELS):
        for wrong in CLASS_WRONGS:
            if (wrong == "source selector" and kind == "f32") or (wrong == "mask extension" and mask[0].startswith("WORD")):
                continue
            assert any(class_value(channel, a, b, f, wrong) != class_value(channel, a, b, f) for a, b, f in CLASS_INPUTS), (channel, wrong)


def controls(directory):
    check_selection_coverage()
    # Selected binary16 sources keep uint words and widen once; a binary32 class source is the whole word.
    for first in range(0, 16, 4):
        body = translate(f16_compare_program(first)).split("float4 main", 1)[1]
        assert body.count("widen16(") == 8 and body.count("class") == 0, body
    body = translate(class_program()).split("float4 main", 1)[1]
    assert body.count("class16(") == 2 and body.count("class32(") == 2, body
    # A constant takes no sub-dword selection and a float constant is no class mask.
    must_reject(translate, with_constants(["v_cmp_lt_f16_sdwa vcc_lo, 1.0, s44 src0_sel:WORD_1 src1_sel:DWORD"]))
    must_reject(translate, with_constants(["v_cmp_class_f16_sdwa vcc_lo, s44, 0.5 src0_sel:WORD_1 src1_sel:DWORD"]))
    must_reject(translate, with_constants(["v_cmp_class_f32_sdwa vcc_lo, s44, 3 src0_sel:BYTE_1 src1_sel:DWORD"]))
    # Whole-dword SDWA comparisons lower exactly as the e32 forms; byte and word selections are refused.
    for first in range(0, 16, 4):
        assert translate(predicate_group(first, sdwa=True)) == translate(predicate_group(first)), first
    must_reject(translate, with_constants(["v_sub_f32_e64 v18, s45, 0",
        "v_cmp_lt_f32_sdwa vcc_lo, s44, v18 src0_sel:WORD_1 src1_sel:DWORD"]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((predicate_group(first, sdwa=True), translate) for first in range(0, 16, 4)),
        *((f16_compare_program(first), translate) for first in range(0, 16, 4)),
        (class_program(), translate),
    ]


def draw(directory, compiler, renderer, backend):
    check_sdwa_predicate_draws(directory, compiler, renderer, backend)
    check_f16_sdwa_draws(directory, compiler, renderer, backend)
