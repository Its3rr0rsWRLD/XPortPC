"""Draw family `quad_lod`: pixel_aot_check.py draw --family quad_lod.

Affine coordinate arithmetic under whole-quad execution (from R0Y00/Xbox2Windows#283 by Vonsek). Before the first
sample, v_add_f32, v_fma_f32 and v_mul_legacy_f32 may compute a coordinate from the interpolated one and ready
constants; such a value is defined on the helper lanes too, so image_sample can take its implicit level from it.
A value written under the entry mask has no helper-lane definition, and a product of two varying values, absolute
value and clamp are outside the affine subset. The draw (offscreen_check --check-pixel-quad-lod) is a partial
triangle on an 8x8 target over a red level 0 and a green level 1: a coordinate scaled by 4 must select level 1 at
every covered pixel, also in quads that straddle the triangle's edge, and leave the clear color outside it.
"""
import subprocess

from .common import assembly, must_reject, translate


def affine_coordinates() -> list[str]:
    program = assembly(False)
    high_address = "s_mov_b32 s21, 0"
    program.remove(high_address)
    restore = program.index("s_and_b64 exec, exec, s[50:51]")
    program[restore:restore] = [
        high_address,
        "s_load_dwordx4 s[44:47], s[20:21], 0x40",
        "s_waitcnt lgkmcnt(0)",
        "s_buffer_load_dwordx4 s[60:63], s[44:47], null",
        "s_waitcnt lgkmcnt(0)",
        "v_add_f32_e32 v8, 0.5, v8",
        "v_mul_legacy_f32_e32 v8, s62, v8",
        "v_fma_f32 v8, 0.5, v8, 0",
    ]
    return program


def check_affine_coordinates() -> None:
    program = affine_coordinates()
    final = "v_fma_f32 v8, 0.5, v8, 0"
    final_index = program.index(final)
    source = translate(program)
    assert f".Sample(samp, float2(alu{final_index}, uv.y))" in source

    # A value written under the entry mask, and a lane mask, have no helper-lane definition.
    exact_input = ["v_mov_b32_e32 v22, 0.5", *program]
    exact_input[final_index + 1] = final.replace("0.5", "v22")
    must_reject(translate, exact_input)
    mask_input = ["v_cmp_eq_f32_e64 s52, 0.5, 0.5", *program]
    mask_input[final_index + 1] = final.replace("0.5", "s52")
    must_reject(translate, mask_input)

    restore = program.index("s_and_b64 exec, exec, s[50:51]")
    exact_overwrite = "v_add_f32_e32 v8, -0.5, v8"
    must_reject(translate, program[:restore + 1] + [exact_overwrite] + program[restore + 1:])
    duplicate = [*program[:final_index], final.replace("v8, 0.5", "v22, 0.5"), *program[final_index:restore],
                 "v_add_f32_e32 v23, 0.0, v9", program[restore], exact_overwrite, *program[restore + 1:]]
    separate_coords = [line.replace("v[8:9]", "v[22:23]") for line in duplicate]
    assert f".Sample(samp, float2(alu{final_index}, alu{restore + 1}))" in translate(separate_coords)
    partial = program.index("v_interp_p2_f32_e32 v8, v1, attr0.x")
    must_reject(translate, program[:partial] + ["v_add_f32_e32 v8, 0.0, v8"] + program[partial:])
    wait = program.index("s_buffer_load_dwordx4 s[60:63], s[44:47], null") + 1
    must_reject(translate, program[:wait] + program[wait + 1:])

    for opcode in ("v_mul_legacy_f32_e32 v8, v9, v8", "v_fma_f32 v8, v9, v8, 0",
                   "v_fma_f32 v8, 0.5, |v8|, 0", "v_fma_f32 v8, 0.5, v8, 0 clamp",
                   "v_mul_f32_e32 v8, 0.5, v8", "v_sub_f32_e32 v8, 0.5, v8"):
        changed = program.copy()
        changed[final_index] = opcode
        must_reject(translate, changed)
    # Only image_sample takes a whole-quad coordinate; the other operations under whole-quad execution stay refused.
    for other in ("v_mov_b32_e32 v8, s62", "v_cvt_f32_ubyte0_e32 v8, s62", "v_and_b32_e32 v8, s62, v8"):
        changed = program.copy()
        changed[final_index] = other
        must_reject(translate, changed)


def check_scalar_helpers_with_vector_arithmetic() -> None:
    entry = assembly(False)
    entry_add = "v_add_f32_e32 v12, 0.0, v12"
    entry.insert(entry.index("s_waitcnt vmcnt(0)") + 1, entry_add)
    quad_add = "v_add_f32_e32 v8, 0.5, v8"
    scalar = "s_bfe_u32 s70, 1, 0x10000"
    for program, vector in ((entry, entry_add), (affine_coordinates(), quad_add)):
        position = program.index(vector)
        for index in (position, position + 1):
            source = translate(program[:index] + [scalar] + program[index:])
            assert "uint s_bfe_u32(" in source and " = s_bfe_u32(" in source


def check_affine_lod_draw(directory, compiler, renderer, backend):
    program = affine_coordinates()
    coordinate = f"float2(alu{program.index('v_fma_f32 v8, 0.5, v8, 0')}, uv.y)"
    source = translate(program)
    assert source.count(coordinate) == 1
    # Wrong reference: values on uncovered lanes replaced with the quad's top-left coordinates before the LOD.
    poor_gradient = (f"(uv.x + uv.y < 0.96875f ? {coordinate} : "
                     "(((floor(uv * 4.0f) * 2.0f + 0.5f) / 8.0f) + float2(0.5f, 0.0f))"
                     " * float2(asfloat(params[0].z) * 0.5f, 1.0f))")
    hlsl = directory / "quad_lod.hlsl"
    shader = directory / "quad_lod.cso"
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, hlsl]
    draw = [renderer, backend, "--check-pixel-quad-lod", shader]
    hlsl.write_text(source, encoding="ascii")
    subprocess.run(compile_shader, check=True)
    subprocess.run(draw, check=True)
    hlsl.write_text(source.replace(coordinate, poor_gradient), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    wrong = subprocess.run(draw, capture_output=True, text=True)
    if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
        raise AssertionError("The draw accepted a missing helper-lane gradient")


def controls(directory):
    check_affine_coordinates()
    check_scalar_helpers_with_vector_arithmetic()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(affine_coordinates(), translate)]


draw = check_affine_lod_draw
