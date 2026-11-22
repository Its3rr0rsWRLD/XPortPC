"""Draw family `fract`: pixel_aot_check.py draw --family fract."""
import math
import struct
import subprocess

from .common import half_rtz, single, translate, with_constants
from .curve_shaping import shaping


# v_fract_f32 clamps x - floor(x) to 0x3f7fffff. For -2**-30 the unclamped difference rounds to 1.0;
# the other inputs are exact and stay below the clamp.
FRACT_INPUTS = (-2.0 ** -30, -0.25, 2.75, -2.0 ** -23)
FRACT_CLAMP = struct.unpack("<f", struct.pack("<I", 0x3f7fffff))[0]


def fract_values():
    # The e64 lanes take |x| and -|x| (from R0Y00/Xbox2Windows#457 by descent81): ignoring either modifier gives 0.75.
    return with_constants([
        "v_fract_f32_e32 v12, s44",
        "v_fract_f32_e64 v13, |s45|",
        "v_fract_f32_e64 v14, -|s46|",
        "v_fract_f32_e32 v15, s47",
    ])


def binary_fixtures():
    return [(fract_values(), translate)]


def check_fract_draw(directory, compiler, renderer, backend):
    source = directory / "fract.hlsl"
    shader = directory / "fract.cso"
    case = directory / "fract.case"
    source.write_text(translate(fract_values()), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *FRACT_INPUTS)
    a, b, c, d = FRACT_INPUTS
    expected = [min(single(x - math.floor(x)), FRACT_CLAMP) for x in (a, abs(b), -abs(c), d)]
    assert expected[0] == FRACT_CLAMP and single(FRACT_INPUTS[0] - math.floor(FRACT_INPUTS[0])) == 1.0
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *map(half_rtz, expected)) * 64)
    subprocess.run(draw, check=True)
    # An unclamped fract exports 1.0 for the first input; the renderer must tell it from the clamp.
    case.write_bytes(constants + struct.pack("<4f", 1.0, *map(half_rtz, expected[1:])) * 64)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("An unclamped fract result escaped detection")


def controls(directory):
    # v_fract_f32 goes through the clamped helper, never through a bare D3D frac.
    body = translate(shaping()).split("float4 main", 1)[1]
    assert "fract32(" in body and "frac(" not in body, body


draw = check_fract_draw
