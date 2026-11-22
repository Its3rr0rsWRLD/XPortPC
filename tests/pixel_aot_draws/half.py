"""Draw family `half`: pixel_aot_check.py draw --family half."""
import struct
import subprocess

from .common import half_rtz, half_value, must_reject, translate, with_constants


# v_cvt_f32_f16 widens the binary16 in the low half of S0; the high half holds junk that must be ignored.
# The second channel applies -|x| to -5.0, the third is the largest finite half and the fourth is the
# smallest subnormal half, 2**-24, scaled by 2**24 so a flushed subnormal exports 0 instead of 1.0.
HALF_WORDS = (0xdead3c00, 0x0000c500, 0x00007bff, 0xbeef0001)
HALF_BODY = [
    "v_cvt_f32_f16_e32 v12, s44",
    "v_cvt_f32_f16_e64 v13, -|s45|",
    "v_cvt_f32_f16_e32 v14, s46",
    "v_cvt_f32_f16_e32 v15, s47",
    "v_mul_f32_e32 v15, 0x4b800000, v15",
]


def check_half_draw(directory, compiler, renderer, backend):
    source = directory / "half.hlsl"
    shader = directory / "half.cso"
    case = directory / "half.case"
    source.write_text(translate(with_constants(HALF_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, *HALF_WORDS)
    first, second, third, fourth = map(half_value, HALF_WORDS)
    expected = [first, -abs(second), third, fourth * 2.0 ** 24]
    assert expected == [1.0, -5.0, 65504.0, 1.0] and fourth == 2.0 ** -24
    # Reading the high half, dropping the negation, a wrong exponent and a flushed subnormal.
    wrong = [half_value(HALF_WORDS[0] >> 16), 5.0, 32752.0, 0.0]
    for x in (*expected, *wrong):
        assert half_rtz(x) == x, x
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
    subprocess.run(draw, check=True)
    for k in range(4):
        wrong_values = list(expected)
        wrong_values[k] = wrong[k]
        case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"A wrong half conversion escaped detection in channel {k}")

    # A separate export observes the literal and two scalar results as half encodings.
    body = [
        "v_cvt_f32_f16_e32 v12, 0x3c00",
        "s_ashr_i64 s[72:73], 0xf000, 2",
        "v_cvt_f32_f16_e32 v13, s72",
        "s_bfm_b64 s[72:73], 16, 0",
        "s_and_b64 s[72:73], s[72:73], 0x3c00",
        "v_cvt_f32_f16_e32 v14, s72",
        *HALF_BODY[3:],
    ]
    source.write_text(translate(with_constants(body)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    scalars = [half_value(0x3c00), half_value(0xf000 // 4), half_value((2**16 - 1) & 0x3c00), fourth * 2.0 ** 24]
    assert scalars == [1.0, 1.0, 1.0, 1.0]
    case.write_bytes(constants + struct.pack("<4f", *scalars) * 64)
    subprocess.run(draw, check=True)
    # A literal read as zero, a shift by zero (0xf000, -8192.0, in green) and a zero-width s_bfm_b64 mask.
    for k, value in ((0, 0.0), (1, half_value(0xf000)), (2, 0.0)):
        wrong_values = list(scalars)
        wrong_values[k] = value
        case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"A wrong literal or scalar half escaped detection in channel {k}")


def controls(directory):
    # v_cvt_f32_f16 widens the low half through widen16 and applies modifiers after widening.
    body = translate(with_constants(HALF_BODY)).split("float4 main", 1)[1]
    assert body.count("widen16(params[") == 4 and "(-abs(widen16(" in body, body
    must_reject(translate, with_constants(["v_cvt_f32_f16_e32 v12, 1.0"]))
    must_reject(translate, with_constants(["v_cvt_f32_f16_sdwa v12, s44 src0_sel:WORD_1"]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (with_constants(HALF_BODY), translate),
    ]


draw = check_half_draw
