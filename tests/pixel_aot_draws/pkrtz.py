"""Draw family `pkrtz`: pixel_aot_check.py draw --family pkrtz."""
import math
import struct
import subprocess

from .common import assembly, byte, f32, half_rtz, must_reject, translate, ubyte, with_constants


# v_cvt_pkrtz_f16_f32_e64 and v_interp_mov_f32. The pack converts each source to binary16 rounding toward zero (a tie goes
# to the smaller magnitude, an overflow to 65504) and the half export returns that value exactly, so the expected values are
# half_rtz of the modified source, with the overflow case that half_rtz cannot take (struct "e" refuses 65520).
# neg and abs act on the binary32 source before the conversion. clamp is refused (see check_pkrtz_controls): the only
# evidence of its effect is LLVM issue 60591 for GFX10.3, which is unverified on gfx1013.
def rtz_ref(x):
    return math.copysign(65504.0, x) if abs(x) >= 65504.0 else half_rtz(x)


def rtn_ref(x):
    try:
        return struct.unpack("<e", struct.pack("<e", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


TIE = 1 + 3 * 2.0 ** -11  # between 1 + 2^-10 and 1 + 2^-9: toward zero gives the smaller, nearest even the larger
PKRTZ_PROGRAMS = (
    # neg and abs on vector sources.
    ([f"v_mov_b32_e32 v{12 + k}, s{44 + k}" for k in range(4)],
     "v_cvt_pkrtz_f16_f32_e64 v16, -v12, |v13|", "v_cvt_pkrtz_f16_f32_e64 v17, -|v14|, v15",
     lambda x, y, z, w: [rtz_ref(-x), rtz_ref(abs(y)), rtz_ref(-abs(z)), rtz_ref(w)],
     ((TIE, -65520.0, -(1.5 + 3 * 2.0 ** -11), 1.5), (-65520.0, -TIE, 3 + 3 * 2.0 ** -10, -0.75)),
     [(0, lambda x, y, z, w: rtz_ref(x)),  # neg dropped
      (1, lambda x, y, z, w: rtz_ref(y)),  # abs dropped
      (2, lambda x, y, z, w: rtz_ref(abs(z))),  # neg dropped
      (2, lambda x, y, z, w: rtz_ref(-z)),  # abs dropped
      (0, lambda x, y, z, w: rtn_ref(-x)),  # nearest even, infinity on overflow
      (1, lambda x, y, z, w: rtn_ref(abs(y)))]),
    # An SGPR source, a vector source with neg, a literal and a negative inline float.
    (["v_mov_b32_e32 v13, s45"],
     "v_cvt_pkrtz_f16_f32_e64 v16, s44, -v13", "v_cvt_pkrtz_f16_f32_e64 v17, 0x3f803000, -2.0",
     lambda x, y, z, w: [rtz_ref(x), rtz_ref(-y), 1 + 2.0 ** -10, -2.0],
     ((TIE, 65520.0, 0.0, 0.0), (-(3 + 3 * 2.0 ** -10), f32(-0.3), 0.0, 0.0)),
     [(0, lambda x, y, z, w: rtn_ref(x)),
      (1, lambda x, y, z, w: rtz_ref(y)),  # neg dropped
      (2, lambda x, y, z, w: 1 + 2.0 ** -9),  # the literal rounded to nearest
      (3, lambda x, y, z, w: 2.0)]),  # neg dropped from the inline constant
    # A vector then an SGPR source with neg and abs, an integer inline constant (a bit pattern, so a binary32 denormal
    # that converts to zero) and an SGPR in the second source.
    (["v_mov_b32_e32 v12, s44"],
     "v_cvt_pkrtz_f16_f32_e64 v16, v12, -|s45|", "v_cvt_pkrtz_f16_f32_e64 v17, 5, s47",
     lambda x, y, z, w: [rtz_ref(x), rtz_ref(-abs(y)), 0.0, rtz_ref(w)],
     ((-TIE, 65520.0, 0.0, 2.5), (3 + 3 * 2.0 ** -10, -f32(0.3), 0.0, -3.0)),
     [(0, lambda x, y, z, w: rtn_ref(x)),
      (1, lambda x, y, z, w: rtz_ref(-y)),  # abs dropped
      (1, lambda x, y, z, w: rtz_ref(abs(y))),  # neg dropped
      (2, lambda x, y, z, w: 5.0)]),  # the integer converted instead of its bits
)


def pack_program(body, first, second):
    program = with_constants(body)
    for old, new in (("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13", first), ("v_cvt_pkrtz_f16_f32_e32 v17, v14, v15", second)):
        program[program.index(old)] = new
    return program


# The harness vertex shader gives attributes 1 and 2 (TEXCOORD1 and 2) these values at vertices 0, 1 and 2, so P0 is the
# first, P10 the second minus the first and P20 the third minus the first, for each of x, y, z, w.
FLAT_VERTICES = {1: ((1, 2, 3, 4), (9, 6, 12, 20), (5, 17, 11, 2)), 2: ((7, 13, 21, 34), (10, 29, 3, 55), (8, 5, 40, 6))}
PARAMETER_INDEX = {"p0": (0, None), "p10": (1, 0), "p20": (2, 0)}


def flat_value(parameter, attr, channel):
    vertices = FLAT_VERTICES[attr]
    first, base = PARAMETER_INDEX[parameter]
    return float(vertices[first]["xyzw".index(channel)] - (vertices[base]["xyzw".index(channel)] if base is not None else 0))


def interp_program(*moves):
    """Read each (spelling, parameter, attribute, channel) move into v20.. in the quad region, then copy to v12.."""
    program = with_constants([f"v_mov_b32_e32 v{12 + k}, v{20 + k}" for k in range(len(moves))])
    pos = program.index("s_and_b64 exec, exec, s[50:51]")
    program[pos:pos] = [f"v_interp_mov_f32_{spelling} v{20 + k}, {parameter}, attr{attr}.{channel}"
                        for k, (spelling, parameter, attr, channel) in enumerate(moves)]
    return program


INTERP_PROGRAMS = (
    (("e32", "p0", 1, "x"), ("e32", "p10", 1, "y"), ("e32", "p20", 1, "z"), ("e64", "p10", 2, "w")),
    (("e32", "p20", 2, "x"), ("e64", "p0", 2, "y"), ("e32", "p10", 1, "w"), ("e64", "p20", 2, "z")),
    (("e32", "p20", 1, "w"), ("e64", "p20", 1, "y"), ("e32", "p0", 2, "w"), ("e32", "p10", 2, "x")),
)
SWAPPED = {"p0": "p10", "p10": "p20", "p20": "p10"}


# The pack as a plain word (ported from R0Y00/Xbox2Windows#528 by Vonsek): S0 is the low half and S1 the high half, each
# rounded toward zero, read back byte by byte through v_cvt_f32_ubyteN. e32 takes S0 from an SGPR or an inline constant, e64
# carries neg and abs on the binary32 sources.
def half_bits(x):
    return struct.unpack("<H", struct.pack("<e", rtz_ref(x)))[0]


WORD_PROGRAMS = (
    (["v_mov_b32_e32 v13, s45", "v_cvt_pkrtz_f16_f32_e32 v20, s44, v13"],
     lambda x, y: half_bits(x) | half_bits(y) << 16),
    (["v_mov_b32_e32 v13, s45", "v_cvt_pkrtz_f16_f32_e32 v20, 1.0, v13"],
     lambda x, y: half_bits(1.0) | half_bits(y) << 16),
    (["v_cvt_pkrtz_f16_f32_e64 v20, -s44, |s45|"], lambda x, y: half_bits(-x) | half_bits(abs(y)) << 16),
)
WORD_SETS = ((TIE, -65520.0), (-(3 + 3 * 2.0 ** -10), f32(0.3)), (0.0, -0.75))
WORD_BYTES = tuple(ubyte(n, 12 + k, "v20", "e32") for k, n in enumerate((0, 1, 2, 3)))


def check_pkrtz_word_draws(directory, compiler, renderer, backend):
    case = directory / "pkrtz_word.case"
    for index, (body, reference) in enumerate(WORD_PROGRAMS):
        source = directory / f"pkrtz_word{index}.hlsl"
        shader = directory / f"pkrtz_word{index}.cso"
        source.write_text(translate(with_constants([*body, *WORD_BYTES])), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for x, y in WORD_SETS:
            x, y = f32(x), f32(y)
            constants = bytearray(256)
            struct.pack_into("<2f", constants, 12, x, y)
            word = reference(x, y)
            expected = [float(byte(word, n)) for n in range(4)]
            case.write_bytes(bytes(constants) + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            # Swapped halves and the nearest-even conversion must each be told apart on some set.
            swapped = word >> 16 | (word & 0xffff) << 16
            if swapped != word:
                wrong = [float(byte(swapped, n)) for n in range(4)]
                case.write_bytes(bytes(constants) + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"Swapped halves escaped detection in pkrtz_word{index}")


def check_pkrtz_word_controls():
    for body, reference in WORD_PROGRAMS:
        source = translate(with_constants([*body, *WORD_BYTES]))
        assert "uint pack16_rtz(float value)" in source and "pack16_rtz(" in source.split("float4 main", 1)[1], source
        for x, y in WORD_SETS:
            assert all(0 <= (reference(f32(x), f32(y)) >> (8 * n) & 255) <= 255 for n in range(4))
    # A program that only exports its pack keeps the export path and carries no helper.
    assert "pack16_rtz" not in translate(pack_program(*PKRTZ_PROGRAMS[0][:3]))
    # An outstanding sample is refused as the S1 of the word form, and clamp and omod stay refused.
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    must_reject(translate, program[:wait] + ["v_cvt_pkrtz_f16_f32_e32 v20, s44, v13"] + program[wait:])
    must_reject(translate, with_constants(["v_cvt_pkrtz_f16_f32_e32 v20, s44, v13 clamp"]))
    must_reject(translate, with_constants(["v_cvt_pkrtz_f16_f32_e32 v20, v13, s44"]))



def check_pkrtz_draws(directory, compiler, renderer, backend):
    check_pkrtz_word_draws(directory, compiler, renderer, backend)
    case = directory / "pkrtz.case"

    def draw_program(name, instructions, shader_model, constants, expected, wrongs):
        source = directory / f"{name}.hlsl"
        shader = directory / f"{name}.cso"
        source.write_text(translate(instructions), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", shader_model, "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for x in (*expected, *(value for _, value in wrongs)):
            assert half_rtz(x) == x, x
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        separated = []
        for channel, value in wrongs:
            separated.append(struct.pack("<f", value) != struct.pack("<f", expected[channel]))
            if not separated[-1]:
                continue
            wrong_values = list(expected)
            wrong_values[channel] = value
            case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong result escaped detection in {name}, channel {channel}: {value}")
        return separated

    for index, (body, first, second, reference, sets, bugs) in enumerate(PKRTZ_PROGRAMS):
        covered = [False] * len(bugs)
        for values in sets:
            values = [f32(v) for v in values]
            constants = bytearray(256)
            struct.pack_into("<4f", constants, 12, *values)
            expected = reference(*values)
            wrongs = [(channel, buggy(*values)) for channel, buggy in bugs]
            separated = draw_program(f"pkrtz{index}", pack_program(body, first, second), "ps_6_0", bytes(constants),
                                     expected, wrongs)
            covered = [a or b for a, b in zip(covered, separated)]
        assert all(covered), (index, covered)
    for index, moves in enumerate(INTERP_PROGRAMS):
        expected = [flat_value(parameter, attr, channel) for _, parameter, attr, channel in moves]
        wrongs = [(k, flat_value(SWAPPED[parameter], attr, channel)) for k, (_, parameter, attr, channel) in enumerate(moves)]
        wrongs += [(k, flat_value(parameter, 3 - attr, channel)) for k, (_, parameter, attr, channel) in enumerate(moves)]
        separated = draw_program(f"interp{index}", interp_program(*moves), "ps_6_1", bytes(256), expected, wrongs)
        assert all(separated), (index, separated)


def check_pkrtz_controls():
    check_pkrtz_word_controls()
    for index, (body, first, second, *_) in enumerate(PKRTZ_PROGRAMS):
        source = translate(pack_program(body, first, second)).split("float4 main", 1)[1]
        assert "nointerpolation" not in source and source.count("export16(") == 4, source
    source = translate(pack_program(*PKRTZ_PROGRAMS[0][:3]))
    assert "= (-asfloat(movw" in source and "= (-abs(asfloat(movw" in source and "= abs(asfloat(movw" in source, source
    # Without a flat attribute the entry point keeps the single interpolated input.
    assert "float4 main(float2 uv : TEXCOORD0) :" in translate(assembly(False))
    source = translate(interp_program(*INTERP_PROGRAMS[0]))
    assert "SV_Position, nointerpolation float4 attr1 : TEXCOORD1, nointerpolation float4 attr2 : TEXCOORD2)" in source, source
    assert "GetAttributeAtVertex(attr1, 2).z - GetAttributeAtVertex(attr1, 0).z" in source, source
    base = PKRTZ_PROGRAMS[2]
    for line in ("v_cvt_pkrtz_f16_f32_e64 v16, v12, v13 mul:2", "v_cvt_pkrtz_f16_f32_e64 v16, v12, v13 div:2",
                 "v_cvt_pkrtz_f16_f32_e64 v16, v12, v13 clamp mul:2",
                 "v_cvt_pkrtz_f16_f32_e64 v16, v12, v13 clamp", "v_cvt_pkrtz_f16_f32_e64 v16, -v12, |s45| clamp", "v_cvt_pkrtz_f16_f32_e64 v16, v12, v13 op_sel:[1,0]",
                 "v_cvt_pkrtz_f16_f32_e64 v16, v12, v30", "v_cvt_pkrtz_f16_f32_e64 v16, s90, v12",
                 "v_cvt_pkrtz_f16_f32_e64 v16, v8, v12", "v_cvt_pkrtz_f16_f32_e64 v16, s20, v12",
                 "v_cvt_pkrtz_f16_f32_e64 v16, vcc_lo, v12", "v_cvt_pkrtz_f16_f32_e64 v16, v12"):
        must_reject(translate, pack_program(base[0], line, base[2]))
    # A source that holds an integer result is not numeric, as for the e32 form.
    must_reject(translate, pack_program([*base[0], "v_and_b32_e32 v12, s44, v12"], base[1], base[2]))
    # An outstanding scalar load and an outstanding sample both refuse the pack.
    program = pack_program(*base[:3])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    must_reject(translate, program[:load] + ["v_cvt_pkrtz_f16_f32_e64 v18, s44, v12"] + program[load:])
    wait = program.index("s_waitcnt vmcnt(0)")
    must_reject(translate, program[:wait] + ["v_cvt_pkrtz_f16_f32_e64 v18, v13, v14"] + program[wait:])
    # v_interp_mov_f32: the context, the attribute range and every modifier.
    moves = (("e32", "p0", 1, "x"),)
    program = interp_program(*moves)
    quad = program.index("v_interp_mov_f32_e32 v20, p0, attr1.x")
    must_reject(translate, [line for line in program if line != "s_mov_b32 m0, s24"])
    must_reject(translate, [line.replace("s_mov_b32 m0, s24", "s_mov_b32 m0, s25") for line in program])
    # At the entry mask the flat read is the same (family interp_attrs; cf2_lane refuses it while the lane may be off).
    assert "precise float alu" in translate(program[:quad] + ["s_and_b64 exec, exec, s[50:51]"] + program[quad:])
    # attr0 is interpolated for the sample too: it is read both ways (family interp_attrs).
    mixed = translate(program[:quad] + ["v_interp_mov_f32_e32 v20, p0, attr0.x"] + program[quad + 1:])
    assert "nointerpolation float4 attr0_v : TEXCOORD0" in mixed and "precise float4 uv = " in mixed, mixed
    for line in ("v_interp_mov_f32_e32 v20, p0, attr32.x",
                 "v_interp_mov_f32_e64 v20, p0, attr1.x clamp", "v_interp_mov_f32_e64 v20, p10, attr1.x mul:2",
                 "v_interp_mov_f32_e32 v20, p0, attr1.x high", "v_interp_mov_f32_e32 v20, v0, attr1.x"):
        must_reject(translate, program[:quad] + [line] + program[quad + 1:])


def controls(directory):
    check_pkrtz_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((pack_program(*program[:3]), translate) for program in PKRTZ_PROGRAMS),
        *((interp_program(*moves), translate) for moves in INTERP_PROGRAMS),
    ]


draw = check_pkrtz_draws
