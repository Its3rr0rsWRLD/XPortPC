"""Draw family `rcp_iflag`: pixel_aot_check.py draw --family rcp_iflag.

v_rcp_iflag_f32 in both encodings, ported from R0Y00/Xbox2Windows#350 by denn0x. It is v_rcp_f32 without the
integer-divide exception flag, which has no desktop counterpart, so it lowers to the same precise divide. The draw keeps
the transcendental rule of its neighbours (curve_shaping, vop3_f32): every input is a power of two, whose reciprocal is
exact, so the draw measures the modifiers and not the adapter's reciprocal precision. A zero input gives an infinity of
its sign and clamp turns +inf into 1.
"""
import math
import struct
import subprocess

from .common import must_reject, translate, with_constants


def reciprocal_iflag():
    return with_constants([
        "v_rcp_iflag_f32_e32 v12, s44",
        "v_rcp_iflag_f32_e64 v13, -|s45|",
        "v_rcp_iflag_f32_e64 v14, |s46|",
        "v_rcp_iflag_f32_e64 v15, |s47| clamp",
    ])


def check_reciprocal_iflag_draws(directory, compiler, renderer, backend):
    instructions = reciprocal_iflag()
    source = directory / "rcp_iflag.hlsl"
    shader = directory / "rcp_iflag.cso"
    case = directory / "rcp_iflag.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    source.write_text(translate(instructions), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    inf = math.inf
    # Powers of two have exact reciprocals, so no rounding difference can hide a fault.
    # A zero operand gives an infinity of its sign, and clamp turns +inf into 1.
    for (a, b, c, d), expected in (((2.0, 4.0, -0.125, 0.5), (0.5, -0.25, 8.0, 1.0)),
                                   ((-0.25, 0.5, 16.0, 4.0), (-4.0, -2.0, 0.0625, 0.25)),
                                   ((0.0, 0.0, -0.0, 0.0), (inf, -inf, inf, 1.0))):
        constants = bytearray(256)
        struct.pack_into("<4f", constants, 12, a, b, c, d)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)

    wrong = [line.replace("v_rcp_iflag_f32", "v_sqrt_f32") for line in instructions]
    source.write_text(translate(wrong), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    result = subprocess.run(draw, capture_output=True, text=True)
    if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
        raise AssertionError("Replacing the reciprocal with a square root escaped detection")


def controls(directory):
    body = translate(reciprocal_iflag()).split("float4 main", 1)[1]
    assert body.count("(1.0f / ") == 4 and "(-abs(asfloat(params[1].x)))" in body and "saturate((1.0f / abs(" in body, body
    # The same refusals as v_rcp_f32: omod is not drawn for it, an e32 spelling takes no modifiers, an operand is
    # missing or extra, a binary16 or binary64 spelling is another instruction, and a sample is read before its wait.
    for line in ("v_rcp_iflag_f32_e32 v12, s44 mul:2", "v_rcp_iflag_f32_e64 v12, s44 mul:2",
                 "v_rcp_iflag_f32_e64 v12, s44 div:2", "v_rcp_iflag_f32_e32 v12, s44, s45",
                 "v_rcp_iflag_f32_e32 v12", "v_rcp_iflag_f16_e32 v12, s44", "v_rcp_iflag_f64_e32 v[12:13], s[44:45]",
                 "v_rcp_iflag_f32_e32 s12, s44"):
        must_reject(translate, with_constants([line]))
    program = with_constants([])
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_rcp_iflag_f32_e32 v18, v12", "v_rcp_iflag_f32_e64 v18, |v12|"):
        must_reject(translate, program[:wait] + [early] + program[wait:])
        translate(program[:wait + 1] + [early] + program[wait + 1:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(reciprocal_iflag(), translate)]


draw = check_reciprocal_iflag_draws
