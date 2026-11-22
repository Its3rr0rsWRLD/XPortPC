"""Draw family `abs`: pixel_aot_check.py draw --family abs."""
import struct
import subprocess

from .common import RAMP, assembly, half_rtz, must_reject, translate, with_constants


def absolute_value():
    program = assembly(False)
    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = [
        "v_sub_f32_e32 v12, 0.5, v12",
        "v_sub_f32_e64 v12, |v12|, 0",
    ]
    return program


def absolute_case(directory):
    case = bytearray(256)
    for y in RAMP:
        for x in RAMP:
            red = abs(0.5 - x / 255)
            case.extend(struct.pack("<4f", half_rtz(red), half_rtz(y / 255), half_rtz(128 / 255), 1))
    path = directory / "absolute.case"
    path.write_bytes(case)
    return path



def check_abs_draws(directory, compiler, renderer, backend):
    source = directory / "fixture.hlsl"
    shader = directory / "fixture.cso"
    program = absolute_value()
    case = absolute_case(directory)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    subprocess.run(draw, check=True)

    without_abs = [line.replace("|v12|", "v12") for line in program]
    source.write_text(translate(without_abs), encoding="ascii")
    subprocess.run([compiler, "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("The renderer failed to detect the missing absolute value")


def controls(directory):
    program = absolute_value()
    alternate = [line.replace("|v12|", "abs(v12)") for line in program]
    assert translate(program) == translate(alternate)
    check_malformed_modifiers()


def check_malformed_modifiers():
    """LLVM's AMDGPU parser rejects `--x`, `-|-x|` on a register, `||x||` and `abs(-x)` and its printer never produces
    them (each modifier is one bit), so every operand reader must refuse them; fp_operand used to read `--x` as a double
    negate. It does print |-2.0| and -|-2.0| for a negative inline constant under abs, which stay accepted, as do the
    single-modifier neighbours."""
    forms = ("v_cmp_lt_f32_e64 s[60:61], {}, v13", "v_add_f32_e64 v20, {}, v13", "v_max_f32_e64 v20, v13, {}",
             "v_cmp_class_f32_e64 s[60:61], {}, 3", "v_cvt_i32_f32_e64 v20, {}",
             "v_fma_mix_f32 v20, {}, v13, v12 op_sel_hi:[1,0,0]")
    for form in forms:
        for good in ("v12", "-v12", "|v12|", "-|v12|", "s44", "-s44", "-1.0", "|-1.0|", "-|-1.0|"):
            translate(with_constants([form.format(good)]))
        for bad in ("--v12", "--s44", "--1.0", "---v12", "-|-v12|", "-|--1.0|", "||v12||", "|-v12|", "abs(-v12)",
                    "-abs(-v12)"):
            must_reject(translate, with_constants([form.format(bad)]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (absolute_value(), translate),
    ]


draw = check_abs_draws
