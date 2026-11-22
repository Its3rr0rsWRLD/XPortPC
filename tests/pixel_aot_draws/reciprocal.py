"""Draw family `reciprocal`: v_rcp_f32_e64 and v_rsq_f32_e64 with abs, neg and clamp, read back from exact power-of-two
inputs (from R0Y00/Xbox2Windows#482 by descent81)."""
import struct
import subprocess

from .common import translate, with_constants


RECIPROCAL_BODY = [
    "v_rcp_f32_e64 v12, |s44|",
    "v_rcp_f32_e64 v13, -|s45|",
    "v_rsq_f32_e64 v14, |s46|",
    "v_rsq_f32_e64 v15, |s47| clamp",
]


def binary_fixtures():
    return [(with_constants(RECIPROCAL_BODY), translate)]


def check_reciprocal_draw(directory, compiler, renderer, backend):
    source = directory / "reciprocal.hlsl"
    shader = directory / "reciprocal.cso"
    case = directory / "reciprocal.case"
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, -4.0, 8.0, -16.0, -0.25)
    case.write_bytes(constants + struct.pack("<4f", 0.25, -0.125, 0.25, 1.0) * 64)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    for mutation in (False, True):
        body = RECIPROCAL_BODY.copy()
        if mutation:
            # 1 / abs(-16) is 1/16, while its reciprocal square root is 1/4.
            body[2] = body[2].replace("v_rsq", "v_rcp")
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        if mutation:
            wrong = subprocess.run(draw, capture_output=True, text=True)
            if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
                raise AssertionError("Substituting reciprocal for reciprocal square root escaped detection")
        else:
            result = subprocess.run(draw)
            if result.returncode:
                return result.returncode
    return 0


def controls(directory):
    translate(with_constants(RECIPROCAL_BODY))


draw = check_reciprocal_draw
