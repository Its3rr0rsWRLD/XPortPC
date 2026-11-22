"""Draw family `mad`: pixel_aot_check.py draw --family mad."""
import struct
import subprocess

from .common import half_rtz, must_reject, single, translate, with_constants


# v_mad_f32 and v_mac_f32 round the product before the add and flush binary32 denormals.
# 4097 * 4097 = 2**24 + 2**13 + 1 rounds to 2**24 + 2**13, so the unfused sum is 0 where a fused one is 1.0.
# 2**-127 is a denormal input: flushed, the second sum is 0.5; preserved, it is 1.0.
MAD_INPUTS = (4097.0, -16785408.0, 2.0 ** -127, 2.0 ** 126)
MAD_BODY = [
    "v_mad_f32 v12, s44, s44, s45",
    "v_mov_b32_e32 v13, s47",
    "v_mad_f32 v13, s46, v13, 0.5",
    "v_mov_b32_e32 v15, s44",
    "v_mov_b32_e32 v14, s45",
    "v_mac_f32_e32 v14, s44, v15",
    "v_mad_f32 v15, 0.5, 4.0, 0.5",
]


# v_madak_f32 (S0 * S1 + K) and v_madmk_f32 (S0 * K + S1) are the same legacy mad with a 32-bit literal K. The first
# two channels repeat the rounding and denormal cases of MAD_BODY with the literal taking the addend or the multiplier:
# 4097 * 4097 - (2**24 + 2**13) is 0 unfused and 1.0 fused, and 2**-127 * 2**126 + 0.5 is 0.5 flushed and 1.0 kept.
# The last two are exact and tell the literal from S1: 2 * 3 + 0.5 = 6.5 against 2 * 0.5 + 3 = 4, and
# -2 * 0.5 + 0.75 = -0.25 against -2 * 0.75 + 0.5 = -1.
MADK_INPUTS = (4097.0, 0.0, 2.0 ** -127, 0.0)
MADK_BODY = [
    "v_mov_b32_e32 v18, s44",
    "v_madak_f32 v12, s44, v18, 0xcb801000",
    "v_mov_b32_e32 v19, 0.5",
    "v_madmk_f32 v13, s46, 0x7e800000, v19",
    "v_madmk_f32 v14, 2.0, 0x40400000, v19",
    "v_madak_f32 v15, -2.0, v19, 0x3f400000",
]
MADK_EXPECTED = [0.0, 0.5, 6.5, -0.25]
MADK_WRONG = ([1.0, 0.5, 6.5, -0.25], [0.0, 1.0, 6.5, -0.25], [0.0, 0.5, 4.0, -0.25], [0.0, 0.5, 6.5, -1.0])


def check_madk_draw(directory, compiler, renderer, backend):
    source = directory / "madk.hlsl"
    shader = directory / "madk.cso"
    case = directory / "madk.case"
    source.write_text(translate(with_constants(MADK_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *MADK_INPUTS)
    a, _, tiny, _ = MADK_INPUTS
    addend = struct.unpack("<f", struct.pack("<I", 0xcb801000))[0]
    large = struct.unpack("<f", struct.pack("<I", 0x7e800000))[0]
    assert addend == -16785408.0 and large == 2.0 ** 126
    assert single(single(a * a) + addend) == 0.0 and single(a * a + addend) == 1.0
    assert 0 < tiny < 2.0 ** -126 and single(tiny * large) + 0.5 == 1.0
    assert MADK_EXPECTED == [single(single(a * a) + addend), 0.5, 2 * 3 + 0.5, -2 * 0.5 + 0.75]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, MADK_EXPECTED)) * 64)
    subprocess.run(draw, check=True)
    # A fused or denormal-preserving multiply-add, or the literal swapped with S1, must change the exported color.
    for wrong_values in MADK_WRONG:
        case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, wrong_values)) * 64)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"A wrong literal mad result escaped detection: {wrong_values}")


def check_mad_draw(directory, compiler, renderer, backend):
    source = directory / "mad.hlsl"
    shader = directory / "mad.cso"
    case = directory / "mad.case"
    source.write_text(translate(with_constants(MAD_BODY)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *MAD_INPUTS)
    a, c, tiny, large = MAD_INPUTS
    unfused = single(single(a * a) + c)
    assert unfused == 0.0 and single(a * a + c) == 1.0
    assert single(tiny) == tiny and 0 < tiny < 2.0 ** -126 and single(tiny * large) == 0.5
    expected = [unfused, 0.5, unfused, 2.5]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, expected)) * 64)
    subprocess.run(draw, check=True)
    # A fused multiply-add or a denormal-preserving one exports 1.0; the renderer must tell each case apart.
    for wrong_values in ([1.0, 0.5, unfused, 2.5], [unfused, 1.0, unfused, 2.5], [unfused, 0.5, 1.0, 2.5]):
        case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, wrong_values)) * 64)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"A fused or denormal-preserving result escaped detection: {wrong_values}")


def controls(directory):
    # v_mad_f32 and v_mac_f32 use the unfused, denormal-flushing helper, never the fma lowering.
    body = translate(with_constants(MAD_BODY)).split("float4 main", 1)[1]
    assert body.count("mad32(") == 4 and " mad(" not in body, body
    must_reject(translate, with_constants(["v_mad_f32 v12, s44, s45"]))
    must_reject(translate, with_constants(["v_mac_f32_e32 v14, s44, v15, v14"]))
    # v_madak_f32 and v_madmk_f32 take mad32 too, never the fused lowering of v_fmaak_f32 and v_fmamk_f32, with the
    # literal as the last operand of madak and the second of madmk; a register or inline constant there is refused.
    body = translate(with_constants(MADK_BODY)).split("float4 main", 1)[1]
    assert body.count("mad32(") == 4 and " mad(" not in body, body
    assert "mad32(asfloat(1082392576u), asfloat(1082392576u)" not in body and "asfloat(3414167552u)" in body, body
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_madak_f32 v12, s44, v18, v18"]))
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_madmk_f32 v12, s44, v18, 0x3e800000"]))
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_madak_f32 v12, s44, v18, 0.5"]))
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_madmk_f32 v12, s44, 0x3e800000"]))
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_madak_f32_e64 v12, s44, v18, 0x3e800000"]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (with_constants(MAD_BODY), translate),
        (with_constants(MADK_BODY), translate),
    ]


def draw(directory, compiler, renderer, backend):
    check_mad_draw(directory, compiler, renderer, backend)
    check_madk_draw(directory, compiler, renderer, backend)
