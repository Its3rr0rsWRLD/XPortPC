"""Draw family `vop3_f32`: pixel_aot_check.py draw --family vop3_f32.

VOP3 (e64) encodings of the binary32 VALU forms with source modifiers, clamp and the output modifiers mul:2, mul:4 and
div:2; v_rndne_f32; the three-operand v_min3_f32, v_max3_f32 and v_med3_f32; v_mac_f32_e64.

The approximate forms (rcp, rsq, sqrt, exp, log) keep the rule of their e32 draws (curve_shaping): every input has an
exact result (a power of two, a perfect square, an integer exponent), so the draw measures the modifiers and the
order omod-then-clamp, not the adapter's transcendental precision. min3, max3 and med3 return one of their operands
and rndne an integer, so those references are exact for any input. Each program is drawn with several constant sets,
and each has wrong references built from plausible lowering bugs (a dropped modifier, clamp before omod, round half
away from zero, med3 without its NaN rule); each must report a mismatch on some set.

v_min3_f32, v_max3_f32 and v_med3_f32 were ported from R0Y00/Xbox2Windows#169 by Vonsek and v_rndne_f32 from
R0Y00/Xbox2Windows#274 by Vonsek; med3 now follows the ISA NaN rule, and the draws are new.
"""
import math
import struct
import subprocess

from .common import half_rtz, must_reject, single, translate, with_constants

NAN = float("nan")


def rcp(x):
    return single(1.0 / x)


def rndne(x):
    return float(round(x))  # Python rounds a float half to even


def away(x):
    return float(math.copysign(math.floor(abs(x) + 0.5), x))


def sat(x):
    return 0.0 if math.isnan(x) else min(1.0, max(0.0, x))


def fmin(*values):
    finite = [v for v in values if not math.isnan(v)]
    return min(finite) if finite else NAN


def fmax(*values):
    finite = [v for v in values if not math.isnan(v)]
    return max(finite) if finite else NAN


def med3(a, b, c, nan_rule=True):
    if any(math.isnan(v) for v in (a, b, c)):
        if nan_rule:
            return fmin(a, b, c)
        return fmax(fmin(a, b), fmin(fmax(a, b), c))  # the plain formula: max(min(a, b), min(max(a, b), c))
    return sorted((a, b, c))[1]


# (body, reference(x, y, z, w) -> four channels, constant sets, [(channel, wrong reference), ...])
VOP3_PROGRAMS = (
    # The corpus spellings: rcp of |x|, exp of -x with div:2, log with mul:4, sqrt with mul:2.
    ([
        "v_rcp_f32_e64 v12, |s44|",
        "v_exp_f32_e64 v13, -s45 div:2",
        "v_log_f32_e64 v14, s46 mul:4",
        "v_sqrt_f32_e64 v15, |s47| mul:2",
    ], lambda x, y, z, w: [rcp(abs(x)), 2.0 ** -y * 0.5, math.log2(z) * 4, math.sqrt(abs(w)) * 2],
     ((-0.25, -3.0, 16.0, -9.0), (2.0, 1.0, 8.0, 0.25), (-8.0, 2.0, 2.0, 4.0)),
     [(0, lambda x, y, z, w: rcp(x)),  # abs dropped
      (1, lambda x, y, z, w: 2.0 ** y * 0.5),  # neg dropped
      (1, lambda x, y, z, w: 2.0 ** -y),  # omod dropped
      (2, lambda x, y, z, w: math.log2(z) * 2),  # mul:4 read as mul:2
      (3, lambda x, y, z, w: math.sqrt(abs(w)) * 0.5)]),  # mul:2 read as div:2
    # Clamp with omod (omod applies first), negated rsq, -|x| on rcp and a log result halved. log inputs stay at powers
    # of two of at least 1: the RTX 4070 Ti returned log2(0.125) a little above -3, so a result below zero is not exact there.
    ([
        "v_rsq_f32_e64 v12, -s44 clamp",
        "v_exp_f32_e64 v13, s45 clamp div:2",
        "v_rcp_f32_e64 v14, -|s46| mul:2",
        "v_log_f32_e64 v15, s47 div:2",
    ], lambda x, y, z, w: [sat(1 / math.sqrt(-x)), sat(2.0 ** y * 0.5), -rcp(abs(z)) * 2, math.log2(w) * 0.5],
     ((-0.25, 1.0, -0.5, 4.0), (-4.0, 3.0, 0.25, 16.0), (-16.0, -3.0, -2.0, 2.0)),
     [(0, lambda x, y, z, w: 1 / math.sqrt(-x)),  # clamp dropped
      (1, lambda x, y, z, w: sat(2.0 ** y) * 0.5),  # clamp before omod
      (2, lambda x, y, z, w: rcp(-z) * 2),  # abs dropped
      (3, lambda x, y, z, w: math.log2(w))]),  # omod dropped
    # Round half to even in both encodings, with neg, abs, mul:2 and clamp.
    ([
        "v_rndne_f32_e32 v12, s44",
        "v_rndne_f32_e64 v13, -s45",
        "v_rndne_f32_e64 v14, |s46| mul:2",
        "v_rndne_f32_e64 v15, s47 clamp",
    ], lambda x, y, z, w: [rndne(x), rndne(-y), rndne(abs(z)) * 2, sat(rndne(w))],
     ((2.5, 2.5, -1.5, 0.5), (-3.5, -0.75, -2.5, 1.5), (-2.5, 1.5, 3.5, -1.25), (7.25, -4.5, 0.25, 0.75)),
     [(0, lambda x, y, z, w: away(x)),  # half away from zero
      (0, lambda x, y, z, w: float(math.floor(x + 0.5))),  # half up
      (1, lambda x, y, z, w: rndne(y)),  # neg dropped
      (2, lambda x, y, z, w: rndne(z) * 2),  # abs dropped
      (2, lambda x, y, z, w: away(abs(z)) * 2),
      (3, lambda x, y, z, w: rndne(w))]),  # clamp dropped
    # Three-operand min, max and median with modifiers, clamp, omod, a literal and a NaN operand. GFX10 VOP3 reads at
    # most two SGPRs or literals, so the third operand comes through a VGPR; the NaN keeps its bits in the raw move.
    ([
        "v_mov_b32_e32 v18, s46",
        "v_mov_b32_e32 v19, s45",
        "v_min3_f32 v12, s44, -s45, |v18|",
        "v_max3_f32 v13, s44, v19, 0x3e800000 clamp",
        "v_med3_f32 v14, s44, s45, v18",
        "v_med3_f32 v15, -s47, v19, s44 mul:2",
    ], lambda x, y, z, w: [fmin(x, -y, abs(z)), sat(fmax(x, y, 0.25)), med3(x, y, z), med3(-w, y, x) * 2],
     ((0.75, -0.25, -0.5, 2.0), (-1.0, 0.5, NAN, -3.0), (4.0, 3.0, -8.0, 0.125), (0.125, -2.0, 0.5, -0.0625)),
     [(0, lambda x, y, z, w: fmin(x, -y, z)),  # abs dropped
      (0, lambda x, y, z, w: fmin(x, y, abs(z))),  # neg dropped
      (1, lambda x, y, z, w: fmax(x, y, 0.25)),  # clamp dropped
      (1, lambda x, y, z, w: sat(fmax(x, y))),  # third operand dropped
      (2, lambda x, y, z, w: med3(x, y, z, nan_rule=False)),  # no NaN rule
      (2, lambda x, y, z, w: fmin(x, y, z)),  # min3 for med3
      (3, lambda x, y, z, w: med3(-w, y, x)),  # omod dropped
      (3, lambda x, y, z, w: med3(w, y, x) * 2)]),  # neg dropped
    # v_mac_f32_e64: modified sources, clamp; the accumulator is the destination.
    ([
        "v_mov_b32_e32 v12, s46",
        "v_mac_f32_e64 v12, -s44, |s45|",
        "v_mov_b32_e32 v13, s47",
        "v_mac_f32_e64 v13, s44, s45 clamp",
        "v_mov_b32_e32 v14, 0",
        "v_mov_b32_e32 v15, 0",
    ], lambda x, y, z, w: [-x * abs(y) + z, sat(x * y + w), 0.0, 0.0],
     ((2.5, -1.25, 3.0, -4.0), (0.5, 0.75, -0.25, 0.5)),
     [(0, lambda x, y, z, w: x * abs(y) + z),  # neg dropped
      (0, lambda x, y, z, w: -x * y + z),  # abs dropped
      (1, lambda x, y, z, w: x * y + w)]),  # clamp dropped
)


def check_vop3_f32_draws(directory, compiler, renderer, backend):
    case = directory / "vop3_f32.case"
    for index, (body, reference, sets, bugs) in enumerate(VOP3_PROGRAMS):
        source = directory / f"vop3_f32_{index}.hlsl"
        shader = directory / f"vop3_f32_{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for inputs in sets:
            assert all(math.isnan(v) or single(v) == v for v in inputs), inputs
            constants = bytearray(256)
            struct.pack_into("<4f", constants, 12, *inputs)
            expected = [float(v) for v in reference(*inputs)]
            for value in expected:  # every reference is exact in binary16, so the export cannot round it
                assert not math.isnan(value) and half_rtz(value) == value, (index, inputs, expected)
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for k, (channel, buggy) in enumerate(bugs):
                value = half_rtz(float(buggy(*inputs)))
                if value == expected[channel] or math.isnan(value):
                    continue
                separated[k] = True
                wrong = list(expected)
                wrong[channel] = value
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong VOP3 result escaped detection in program {index}, channel {channel}, "
                                         f"inputs {inputs}")
        assert all(separated), (index, separated)


def controls(directory):
    source = translate(with_constants(VOP3_PROGRAMS[0][0])).split("float4 main", 1)[1]
    for expected in ("(1.0f / abs(asfloat(params[0].w)))", "(exp2((-asfloat(params[1].x))) * 0.5f)", "* 4.0f)", "* 2.0f)"):
        assert expected in source, (expected, source)
    source = translate(with_constants(VOP3_PROGRAMS[1][0])).split("float4 main", 1)[1]
    assert "saturate((exp2(asfloat(params[1].x)) * 0.5f))" in source, source
    source = translate(with_constants(VOP3_PROGRAMS[3][0]))
    assert "float med3_f32(" in source and "isnan(" in source and "min(min(" in source, source
    assert "round(" in translate(with_constants(VOP3_PROGRAMS[2][0]))
    # Refused neighbours: omod on an e32 spelling or on the denormal-flushing mad/mac, an unknown omod, omod
    # before clamp, an e32 spelling of a VOP3-only form, a missing operand and omod on a move.
    for line in ("v_rcp_f32_e32 v12, s44 mul:2", "v_exp_f32_e64 v12, s44 mul:3", "v_exp_f32_e64 v12, s44 div:4",
                 "v_exp_f32_e64 v12, s44 div:2 clamp", "v_mac_f32_e64 v12, s44, s45 mul:2",
                 "v_mad_f32 v12, s44, s45, s46 div:2", "v_min3_f32_e32 v12, s44, s45, s46",
                 "v_med3_f32 v12, s44, s45", "v_max3_f32 v12, s44, s45, s46, s47",
                 "v_mov_b32_e64 v12, s44 mul:2", "v_rndne_f32_e32 v12, s44, s45"):
        must_reject(translate, with_constants([line]))
    # The approximate forms keep their wait rules: a sample source before vmcnt(0) is refused.
    program = with_constants([])
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_rcp_f32_e64 v18, |v12|", "v_med3_f32 v18, v12, v13, v14", "v_rndne_f32_e32 v18, v12"):
        must_reject(translate, program[:wait] + [early] + program[wait:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for body, *_ in VOP3_PROGRAMS]


draw = check_vop3_f32_draws
