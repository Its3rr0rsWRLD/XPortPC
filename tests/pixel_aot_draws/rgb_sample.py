"""Draw family `rgb_sample`: pixel_aot_check.py draw --family rgb_sample.

An RGB-only image_sample (dmask:0x7, three destination VGPRs), ported from R0Y00/Xbox2Windows#303 by Vonsek. The fourth
VGPR of the block keeps its earlier value, so the draw loads 0.5 into it before the sample and exports it as alpha: an
implementation that wrote a fourth channel would draw alpha 1.0 instead.
"""
import re
import struct
import subprocess

from .common import RAMP, assembly, half_rtz, must_reject, translate


def rgb_sample():
    program = assembly(False)
    sample = next(i for i, line in enumerate(program) if line.startswith("image_sample"))
    program[sample] = program[sample].replace("v[12:15]", "v[12:14]").replace("dmask:0xf", "dmask:0x7")
    program.insert(sample, "v_mov_b32_e32 v15, 0.5")
    return program


def check_rgb_sample_draw(directory, compiler, renderer, backend):
    hlsl = directory / "rgb-sample.hlsl"
    shader = directory / "rgb-sample.cso"
    case = directory / "rgb-sample.case"
    hlsl.write_text(translate(rgb_sample()), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, hlsl], check=True)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    for alpha in (0.5, 1.0):
        colors = (struct.pack("<4f", half_rtz(red / 255), half_rtz(green / 255), half_rtz(128 / 255), alpha)
                  for green in RAMP for red in RAMP)
        case.write_bytes(bytes(256) + b"".join(colors))
        if alpha == 0.5:
            subprocess.run(draw, check=True)
        else:
            wrong = subprocess.run(draw, capture_output=True, text=True)
            if wrong.returncode != 1 or "pixel_mismatch x=0 y=0" not in wrong.stderr:
                raise AssertionError("RGB sample with an overwritten alpha register escaped detection")


def controls(directory):
    rgb = rgb_sample()
    body = translate(rgb)
    # Three channels are read from the sample, and alpha is the 0.5 that was loaded before it.
    assert ".z" in body and not re.search(r"sample\d+\.w", body), body
    # The destination width must agree with the dmask (three VGPRs: any three-channel mask, such as 0xb; the other
    # masks are drawn by the sample_shapes family).
    assert re.search(r"sample\d+\.w", translate([line.replace("dmask:0x7", "dmask:0xb") for line in rgb]))
    for old, new in (("v[12:14]", "v[12:15]"), ("dmask:0x7", "dmask:0x3"),
                     ("dmask:0x7", "dmask:0x1"), ("dmask:0x7", "dmask:0x8"), ("dmask:0x7", "dmask:0x6"),
                     ("v[12:14]", "v[12:13]"), ("dmask:0x7", "dmask:0x7 d16")):
        must_reject(translate, [line.replace(old, new) for line in rgb])
    wait = rgb.index("s_waitcnt vmcnt(0)")
    # The sample is still read: without its wait, or with a write over one of its three registers, it is refused;
    # v15 is not a destination, so writing it before the wait is legal.
    must_reject(translate, rgb[:wait] + rgb[wait+1:])
    must_reject(translate, rgb[:wait] + ["v_mov_b32_e32 v14, 1.0"] + rgb[wait:])
    translate(rgb[:wait] + ["v_mov_b32_e32 v15, 1.0"] + rgb[wait:])
    # The fourth channel is not a sample result: reading v15 before the wait is not refused, v14 is.
    translate(rgb[:wait] + ["v_mov_b32_e32 v24, v15"] + rgb[wait:])
    must_reject(translate, rgb[:wait] + ["v_mov_b32_e32 v24, v14"] + rgb[wait:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(rgb_sample(), translate)]


draw = check_rgb_sample_draw
