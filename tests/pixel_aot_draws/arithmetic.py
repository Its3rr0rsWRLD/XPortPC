"""Draw family `arithmetic`: pixel_aot_check.py draw --family arithmetic."""
import struct
import subprocess

from .common import assembly, half_rtz, must_reject, translate


def arithmetic():
    """Add, multiply, reversed subtraction and moves on the sample and constant words 8 to 11."""
    program = assembly(False)
    pos = program.index("s_mov_b32 s40, 1")
    program.insert(pos, "s_load_dwordx4 s[44:47], s[20:21], 0x40")
    pos = program.index("s_waitcnt vmcnt(0)")
    program[pos:pos] = [
        "s_buffer_load_dwordx4 s[44:47], s[44:47], 0x20",
        "s_waitcnt lgkmcnt(0)",
    ]
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = [
        "v_mov_b32_e32 v18, v12",
        "v_mul_f32_e32 v18, s44, v18",
        "v_add_f32_e64 v12, v18, s45 clamp",
        "v_mov_b32_e64 v19, s46",
        "v_subrev_f32_e32 v19, v13, v19",
        "v_mul_f32_e64 v19, v19, -2.0",
        "v_subrev_f32_e64 v13, s47, v19 clamp",
        "v_add_f32_e32 v14, -0.5, v14",
        "v_mov_b32_e32 v20, 0x3e800000",
        "v_mul_f32_e32 v20, v20, v18",
        "v_mov_b32_e32 v15, v20",
    ]
    return program


def arithmetic_case(directory, *constants):
    """Expected colors for arithmetic(). Each step must be exact in binary32, so neither the
    rounding of add, subtract and multiply nor fusion can change the result."""
    def exact(value):
        rounded, = struct.unpack("<f", struct.pack("<f", value))
        assert rounded == value, value
        return rounded
    scale, bias, pivot, offset = map(exact, constants)
    case = bytearray(256)
    struct.pack_into("<4f", case, 32, scale, bias, pivot, offset)
    ramp = (0, 16, 37, 64, 101, 153, 219, 254)
    for y in ramp:
        for x in ramp:
            r, g, b = (struct.unpack("<f", struct.pack("<f", c / 255))[0] for c in (x, y, 128))
            scaled = exact(scale * r)
            red = min(1, max(0, exact(scaled + bias)))
            green = min(1, max(0, exact(exact(exact(pivot - g) * -2.0) - offset)))
            color = (red, green, exact(-0.5 + b), exact(0.25 * scaled))
            case.extend(struct.pack("<4f", *map(half_rtz, color)))
    path = directory / "arithmetic.case"
    path.write_bytes(case)
    return path


def check_arithmetic_draws(directory, compiler, renderer, backend):
    source = directory / "fixture.hlsl"
    shader = directory / "fixture.cso"
    program = arithmetic()
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for constants in ((4.0, -.0625, .125, -.015625), (2.0, -.03125, .0625, -.0078125)):
        draw = [renderer, backend, "--check-pixel-case", shader, arithmetic_case(directory, *constants)]
        subprocess.run(draw, check=True)
    swapped = [line.replace("v_subrev_f32", "v_sub_f32") for line in program]
    source.write_text(translate(swapped), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("Swapped subtraction operands escaped detection")


def controls(directory):
    program = arithmetic()
    source = translate(program)
    # Constant words are unsigned: a float use reads asfloat(word), and a move of a raw word stays an unsigned copy.
    for expected in ("= sample16.x;", "= (asfloat(params[2].x) * alu20);", "= saturate((alu21 + asfloat(params[2].y)));",
                     "uint movw23 = params[2].z;", "= (asfloat(movw23) - sample16.y);",
                     "= saturate((alu25 - asfloat(params[2].w)));", "uint movw28 = 1048576000u;", "= alu29;"):
        assert expected in source, expected
    # A move is a bit copy: LLVM prints integer inline constants as integers.
    for operand, expected in (("1", "uint movw28 = 1u;"), ("-4", "uint movw28 = 4294967292u;"),
                              ("-0.5", "float alu28 = (-0.5f);"), ("0.15915494", "float alu28 = 0.15915494f;"),
                              ("s40", "uint movw28 = 1u;")):
        changed = [line.replace("v20, 0x3e800000", f"v20, {operand}") for line in program]
        assert expected in translate(changed), operand
    # The interpolated coordinate is a float value like any other (family interp_attrs).
    assert "uv.x" in translate([line.replace("v18, v12", "v18, v8") for line in program]).split("Sample(", 1)[1]
    for old, new in (("v18, v12", "v18, v0"), ("v18, v12", "v18, v30"),
                     ("v19, s46", "v19, s28"), ("v19, s46", "v19, -s46"), ("v19, s46", "v19, s46 clamp"),
                     ("v18, v12", "v18, v12, v13"), ("v14, -0.5, v14", "v14, v14"),
                     ("v19, v13, v19", "v19, v13, v19, v18")):
        changed = [line.replace(old, new) for line in program]
        assert changed != program
        must_reject(translate, changed)
    first = program.index("v_mov_b32_e32 v18, v12")
    early = program[:first-1] + [program[first], program[first-1]] + program[first+1:]
    assert early[first] == "s_waitcnt vmcnt(0)"
    must_reject(translate, early)  # copies the sample before the wait
    # Until vmcnt(0), the sample may still fill v12 to v15, so a move into one of them has no defined
    # order with it. The same move into a free register, or into v12 after the wait, is accepted.
    wait = program.index("s_waitcnt vmcnt(0)")
    for register in ("v12", "v13", "v14", "v15"):
        must_reject(translate, program[:wait] + [f"v_mov_b32_e32 {register}, 1.0"] + program[wait:])
    must_reject(translate, program[:wait] + ["v_ceil_f32_e32 v12, 1.0"] + program[wait:])
    free = translate(program[:wait] + ["v_mov_b32_e32 v21, 1.0"] + program[wait:])
    assert free.index("tex.Sample") < free.index("= 1.0f;") < free.index("= sample16.x;")
    late = translate(program[:wait+1] + ["v_mov_b32_e32 v12, 1.0"] + program[wait+1:])
    assert "= 1.0f;" in late and "= sample16.x;" not in late
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v17, v14, v15")
    must_reject(translate, program[:pos] + ["v_mov_b32_e32 v20, v16"] + program[pos:])
    # VALU in whole-quad mode is lowered as anywhere else (CF-2a: every lane is active there); a second s_wqm_b64 is not.
    pos = program.index("s_wqm_b64 exec, exec") + 1
    assert "    precise float alu2 = 1.0f;" in translate(program[:pos] + ["v_mov_b32_e32 v20, 1.0"] + program[pos:])
    must_reject(translate, program[:pos] + ["s_wqm_b64 exec, exec"] + program[pos:])
    pos = program.index("v_interp_p1_f32_e32 v9, v0, attr0.y")
    partial = program[:pos] + ["v_interp_p1_f32_e32 v10, v0, attr0.x"] + program[pos:]
    translate(partial)  # an unpaired first phase is allowed, but its partial value is not numeric
    must_reject(translate, [line.replace("v18, v12", "v18, v10") for line in partial])
    pos = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0x20"))
    must_reject(translate, program[:pos] + ["v_mov_b32_e64 v19, s46"] + program[pos:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (arithmetic(), translate),
    ]


draw = check_arithmetic_draws
