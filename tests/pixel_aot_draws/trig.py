"""Draw family `trig`: pixel_aot_check.py draw --family trig.

v_sin_f32 and v_cos_f32 in both encodings (forms/valu_f32.py), ported from R0Y00/Xbox2Windows#357 by dnn. Both take
revolutions, sin(2 * pi * x). D3D bounds sin and cos only to 0.0008 absolute in [-100 pi, 100 pi], so each result is
quantized to 1/32 steps by exact operations (times 32, plus 0.5, floor, times 1/32) and every reference lies at least 0.1
step from a boundary. Each case covers all four quadrants across its channels and one input of millions of turns, where
multiplying the unreduced input by 2 pi in binary32 moves the quantized result by 20 or more steps.
"""
import math
import struct
import subprocess

from .common import compile_shader, must_reject, translate, with_constants

TRIG_BODY = [
    "v_sin_f32_e32 v12, s44",
    "v_cos_f32_e32 v13, s45",
    "v_sin_f32_e64 v14, -|s46|",
    "v_cos_f32_e64 v15, -s47 clamp",
] + [line for reg in ("v12", "v13", "v14", "v15") for line in (
    f"v_mul_f32_e32 {reg}, 0x42000000, {reg}",
    f"v_add_f32_e32 {reg}, 0.5, {reg}",
    f"v_floor_f32_e32 {reg}, {reg}",
    f"v_mul_f32_e32 {reg}, 0x3d000000, {reg}",
)]
TRIG_CASES = (
    (-4000000.25, 0.125, -0.375, 0.5),
    (-0.125, 4000000.25, 2.75, -0.125),
    (0.25, -1.625, -4000000.5, 0.0),
    (-0.375, 0.375, 0.0625, 2000000.75),
)
REDUCED_ARGUMENT = "(turns(value) * 6.28318548f)"


def trig_reference(case, swap=False):
    """The quantized four channels of TRIG_BODY, from a double-precision reduction of each input."""
    channels = []
    for kind, x, saturate in zip(("sin", "cos", "sin", "cos"), (case[0], case[1], -abs(case[2]), -case[3]),
                                 (False, False, False, True)):
        if swap:
            kind = "cos" if kind == "sin" else "sin"
        value = (math.sin if kind == "sin" else math.cos)(2 * math.pi * math.remainder(x, 1.0))
        if saturate:
            value = min(1.0, max(0.0, value))
        scaled = value * 32 + 0.5
        # Only a drawn reference needs the margin; the swapped values merely have to differ from it.
        assert swap or abs(scaled - round(scaled)) >= 0.1, (case, kind, value)
        channels.append(math.floor(scaled) / 32)
    return channels


def check_trig_draws(directory, compiler, renderer, backend):
    source = directory / "trig.hlsl"
    shader = directory / "trig.cso"
    case = directory / "trig.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    instructions = with_constants(TRIG_BODY)
    hlsl = translate(instructions)

    def write_case(inputs):
        constants = bytearray(256)
        struct.pack_into("<4f", constants, 12, *inputs)
        case.write_bytes(constants + struct.pack("<4f", *trig_reference(inputs)) * 64)

    source.write_text(hlsl, encoding="ascii")
    compile_shader(compiler, source, shader)
    for inputs in TRIG_CASES:
        write_case(inputs)
        subprocess.run(draw, check=True)

    def mismatches(text):
        source.write_text(text, encoding="ascii")
        compile_shader(compiler, source, shader)
        detected = []
        for inputs in TRIG_CASES:
            write_case(inputs)
            wrong = subprocess.run(draw, capture_output=True, text=True)
            if wrong.returncode not in (0, 1) or (wrong.returncode == 1) != ("pixel_mismatch" in wrong.stderr):
                raise AssertionError(f"Unexpected renderer result {wrong.returncode}: {wrong.stderr}")
            detected.append(wrong.returncode == 1)
        return detected

    # Both controls change at least one quantized channel of every case by many steps.
    swapped = [line.replace("v_sin_f32", "v_tmp").replace("v_cos_f32", "v_sin_f32").replace("v_tmp", "v_cos_f32")
               for line in instructions]
    assert all(trig_reference(inputs, swap=True) != trig_reference(inputs) for inputs in TRIG_CASES)
    assert hlsl.count(REDUCED_ARGUMENT) == 2, hlsl
    for name, text in (("calls swapped between sine and cosine", translate(swapped)),
                       ("radians instead of turns", hlsl.replace(REDUCED_ARGUMENT, "(value)"))):
        if not all(mismatches(text)):
            raise AssertionError(f"Sine and cosine with {name} escaped detection")
    # Without the reduction, a binary32 x * 2 pi of the large inputs moves each case by 20 or more steps. Whether the
    # adapter shows it depends on the precision of its own sin and cos argument handling, so the count is reported
    # rather than required; the reduced draws above must match on every adapter.
    unreduced = mismatches(hlsl.replace(REDUCED_ARGUMENT, "(value * 6.28318548f)"))
    print(f"trig_unreduced_mismatches={sum(unreduced)}/{len(unreduced)}")


def controls(directory):
    trig = translate(with_constants(TRIG_BODY))
    assert trig.count("sin32(") == 3 and trig.count("cos32(") == 3, trig  # two calls plus each definition
    assert "saturate(cos32((-asfloat(params" in trig and "sin32((-abs(" in trig and "cos32(asfloat(params" in trig, trig
    assert trig.count(REDUCED_ARGUMENT) == 2 and trig.count("float turns(") == 1, trig
    # A sample destination is not written before its wait; a binary64 spelling, a missing or extra operand, a scalar
    # destination and an output modifier (not drawn) are refused.
    program = with_constants([])
    wait = program.index("s_waitcnt vmcnt(0)")
    must_reject(translate, program[:wait] + ["v_sin_f32_e32 v12, 1.0"] + program[wait:])
    must_reject(translate, program[:wait] + ["v_cos_f32_e64 v13, 1.0"] + program[wait:])
    translate(program[:wait + 1] + ["v_sin_f32_e32 v12, 1.0"] + program[wait + 1:])
    for line in ("v_sin_f32_e64 v12, s44 mul:2",
                 "v_cos_f32_e64 v12, s44 div:2", "v_sin_f32_e32 v12, s44, s45", "v_cos_f32_e32 v12",
                 "v_sin_f64_e32 v[12:13], s[44:45]", "v_sin_f32_e32 s12, s44"):
        must_reject(translate, with_constants([line]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(TRIG_BODY), translate)]


draw = check_trig_draws
