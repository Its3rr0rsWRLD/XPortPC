"""Draw family `sample_shapes`: pixel_aot_check.py draw --family sample_shapes.

image_sample of a 2D T# in the shapes the RADV corpus uses beyond the four-channel and RGB reads
(tools/corpus_translate.py):

- dmask: one channel to a single VGPR (0x1, 0x8, also through a non-sequential [vA, vB] address) and masks with holes
  (0x5, 0xa, and 0x5 d16, two halves of one VGPR), whose set channels go to consecutive VGPRs in channel order. Drawn with --check-pixel-case over the 8x8
  ramp texture, whose texel (x, y) is (ramp[x], ramp[y], 128, 255); each case has a Python reference per pixel and a
  wrong reference for the property it isolates (the channel a single-channel read takes, the packing of a mask with
  holes, the order of an NSA address).
- coordinates the helper-lane rule now proves (lowering.Lowering.quad_values): an immediate written under whole-quad
  execution (a constant coordinate, drawn as a case: it reads texel row 0), a copy of a helper-lane value, the
  arithmetic v_subrev, v_mul, v_mad and v_madmk, and affine arithmetic after an earlier sample. Those are drawn with
  --check-pixel-quad-lod (the quad_lod family's partial triangle: a coordinate scaled by 4 must select the green level
  1 at every covered pixel), with that family's wrong reference, the helper lanes' coordinates replaced by the quad's
  top-left ones.
A flat attribute (v_interp_mov_f32) read under whole-quad execution is a helper-lane value too; it has controls only,
since its value is the harness triangle's provoking vertex.
"""
import re
import struct
import subprocess

from pixel_aot_ops.bindings import PixelBindings

from .common import RAMP, assembly, half_rtz, lower, must_reject, translate
from .image import d16_unpack, d16_value
from .quad_lod import affine_coordinates

SAMPLE = "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"
FILLS = {"v13": 4.0, "v14": 0.5, "v15": 2.0}  # inline constants for the VGPRs a narrow read leaves alone


def texel(x, y):
    return (RAMP[x] / 255, RAMP[y] / 255, 128 / 255, 1.0)


def narrow(sample, written):
    """The reference program with `sample` in place of the four-channel read; VGPRs from v12 on that it does not
    write are loaded with FILLS before it."""
    program = assembly(False)
    at = program.index(SAMPLE)
    program[at] = sample
    program[at:at] = [f"v_mov_b32_e32 {reg}, {value}" for reg, value in FILLS.items() if reg not in written]
    return program


# name -> (sample, VGPRs written, reference export (x, y) -> v12..v15, wrong reference)
def _fill(regs, x, y, values):
    out = dict(FILLS)
    out.update(zip(regs, values))
    return [out.get(f"v{12 + k}", 0.0) for k in range(4)]


CASES = {
    "red": ("image_sample v12, v[8:9], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D", ["v12"],
            lambda x, y: _fill(["v12"], x, y, [texel(x, y)[0]]),
            lambda x, y: _fill(["v12"], x, y, [texel(x, y)[1]])),  # the green channel
    "alpha": ("image_sample v12, v[8:9], s[28:35], s[40:43] dmask:0x8 dim:SQ_RSRC_IMG_2D", ["v12"],
              lambda x, y: _fill(["v12"], x, y, [texel(x, y)[3]]),
              lambda x, y: _fill(["v12"], x, y, [texel(x, y)[0]])),  # the first channel instead of the set one
    "red-blue": ("image_sample v[12:13], v[8:9], s[28:35], s[40:43] dmask:0x5 dim:SQ_RSRC_IMG_2D", ["v12", "v13"],
                 lambda x, y: _fill(["v12", "v13"], x, y, [texel(x, y)[0], texel(x, y)[2]]),
                 lambda x, y: _fill(["v12", "v13"], x, y, texel(x, y)[:2])),  # read as 0x3
    "green-alpha": ("image_sample v[12:13], v[8:9], s[28:35], s[40:43] dmask:0xa dim:SQ_RSRC_IMG_2D", ["v12", "v13"],
                    lambda x, y: _fill(["v12", "v13"], x, y, [texel(x, y)[1], texel(x, y)[3]]),
                    lambda x, y: _fill(["v12", "v13"], x, y, [texel(x, y)[3], texel(x, y)[1]])),  # channels swapped
    # NSA address in the other order: the first address VGPR is the x coordinate.
    "nsa-red": ("image_sample v12, [v9, v8], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D", ["v12"],
                lambda x, y: _fill(["v12"], x, y, [texel(y, x)[0]]),
                lambda x, y: _fill(["v12"], x, y, [texel(x, y)[0]])),  # address read in register order
}


def constant_coordinate():
    """v9 = 0 under whole-quad execution: the sample reads texel row 0 at every pixel."""
    program = assembly(False)
    program.insert(program.index("s_and_b64 exec, exec, s[50:51]"), "v_mov_b32_e32 v9, 0")
    return program


def d16_holes():
    """dmask 0x5 d16: red and blue as two binary16 halves of v20 (red low), widened to v12, v13 by d16_unpack."""
    program = assembly(False)
    program[program.index(SAMPLE)] = "image_sample v20, v[8:9], s[28:35], s[40:43] dmask:0x5 dim:SQ_RSRC_IMG_2D d16"
    wait = program.index("s_waitcnt vmcnt(0)") + 1
    program[wait:wait] = d16_unpack(20)
    return program


def case_programs():
    out = {name: (narrow(sample, written), reference, wrong) for name, (sample, written, reference, wrong) in CASES.items()}
    out["d16-red-blue"] = (d16_holes(), lambda x, y: [d16_value(RAMP[x]), d16_value(128), 0.0, 0.0],
                           lambda x, y: [d16_value(RAMP[x]), d16_value(RAMP[y]), 0.0, 0.0])  # read as 0x3
    out["constant"] = (constant_coordinate(), lambda x, y: list(texel(x, 0)), lambda x, y: list(texel(x, y)))
    return out


def lod_programs():
    """Coordinates of the quad_lod draw computed in the newly proven shapes; each equals ((u + 0.5) * s62 * 0.5, v)."""
    base = affine_coordinates()
    chain = ["v_add_f32_e32 v8, 0.5, v8", "v_mul_legacy_f32_e32 v8, s62, v8", "v_fma_f32 v8, 0.5, v8, 0"]
    at = base.index(chain[0])

    def replaced(lines):
        return base[:at] + lines + base[at + len(chain):]
    copy = replaced(chain + ["v_mov_b32_e32 v22, v8", "v_mov_b32_e32 v23, v9"])
    copy[copy.index(SAMPLE)] = SAMPLE.replace("v[8:9]", "v[22:23]")
    forms = replaced(["v_mov_b32_e32 v24, 0.5", "v_madmk_f32 v8, v8, 0x3f800000, v24", "v_mul_f32_e32 v8, s62, v8",
                      "v_subrev_f32_e32 v8, 0, v8", "v_mad_f32 v8, 0.5, v8, 0"])
    # An earlier sample in whole-quad mode (T# and sampler made ready first): the arithmetic after it still proves.
    after = [line for line in base if line not in ("s_load_dwordx8 s[28:35], s[20:21], null",
                                                   "s_mov_b32 s40, 1", "s_mov_b32 s41, 2", "s_mov_b32 s42, 3",
                                                   "s_mov_b32 s43, 4")]
    first = after.index(chain[0])
    after[first:first] = ["s_load_dwordx8 s[28:35], s[20:21], null", "s_mov_b32 s40, 1", "s_mov_b32 s41, 2",
                          "s_mov_b32 s42, 3", "s_mov_b32 s43, 4", "s_waitcnt lgkmcnt(0)",
                          "image_sample v[26:29], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"]
    return {"copy": copy, "sub-mul-mad": forms, "after-sample": after}


# The fixed contract of translate() as a binding description (docs/design/pixel-bindings.md), which emits the same
# declarations and, unlike the fixed contract, lets a program sample its texture more than once.
CONTRACT = PixelBindings(sgprs={"s20": "descriptors", "s24": "interp"}, textures={0: 0}, samplers={0: (1, 2, 3, 4)},
                         constant_buffers={64: 0}, descriptor_high=0)


def translate_lod(program):
    return lower(program, bindings=CONTRACT)


def final_coordinate(source):
    return re.findall(r"\.Sample\(samp, (float2\([^()]*\))\)", source)[-1]


def check_case_draws(directory, compiler):
    for name, (program, reference, wrong) in case_programs().items():
        hlsl, shader, case = (directory / f"sample-shapes-{name}.{ext}" for ext in ("hlsl", "cso", "case"))
        hlsl.write_text(translate(program), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, hlsl], check=True)
        for expect, function in ((True, reference), (False, wrong)):
            rows = [[half_rtz(v) for v in function(x, y)] for y in range(8) for x in range(8)]
            case.write_bytes(bytes(256) + b"".join(struct.pack("<4f", *row) for row in rows))
            yield name, expect, shader, case


def check_sample_shapes_draw(directory, compiler, renderer, backend):
    for name, expect, shader, case in check_case_draws(directory, compiler):
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        if expect:
            subprocess.run(draw, check=True)
        else:
            wrong = subprocess.run(draw, capture_output=True, text=True)
            if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
                raise AssertionError(f"sample_shapes {name}: the wrong reference was accepted")
    for name, program in lod_programs().items():
        source = translate_lod(program)
        coordinate = final_coordinate(source)
        assert source.count(coordinate) == 1, name
        # Wrong reference (quad_lod's): values on uncovered lanes replaced with the quad's top-left coordinates.
        poor_gradient = (f"(uv.x + uv.y < 0.96875f ? {coordinate} : "
                         "(((floor(uv * 4.0f) * 2.0f + 0.5f) / 8.0f) + float2(0.5f, 0.0f))"
                         " * float2(asfloat(params[0].z) * 0.5f, 1.0f))")
        hlsl, shader = directory / f"sample-shapes-lod-{name}.hlsl", directory / f"sample-shapes-lod-{name}.cso"
        compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, hlsl]
        draw = [renderer, backend, "--check-pixel-quad-lod", shader]
        hlsl.write_text(source, encoding="ascii")
        subprocess.run(compile_shader, check=True)
        subprocess.run(draw, check=True)
        hlsl.write_text(source.replace(coordinate, poor_gradient), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"sample_shapes lod {name}: the draw accepted a missing helper-lane gradient")


def check_controls():
    for name, (program, _, _) in case_programs().items():
        source = translate(program)
        sample = next(line for line in program if line.startswith("image_sample"))
        channels = [c for c in range(4) if int(re.search(r"dmask:0x(\w)", sample)[1], 16) >> c & 1]
        reads = re.findall(r"sample\d+\.([xyzw])", source)
        assert sorted(set(reads)) == sorted("xyzw"[c] for c in channels), (name, reads)
    # The constant coordinate is read through its raw word, the coordinate of an NSA pair in address order.
    assert re.search(r"\.Sample\(samp, float2\(uv\.x, asfloat\(movw\d+\)\)\)", translate(constant_coordinate()))
    assert ".Sample(samp, float2(uv.y, uv.x))" in translate(case_programs()["nsa-red"][0])
    for name, program in lod_programs().items():
        assert "uv" not in final_coordinate(translate_lod(program)).replace("uv.y", ""), name

    red = case_programs()["red"][0]
    sample = next(line for line in red if line.startswith("image_sample"))

    def changed(new):
        return [new if line == sample else line for line in red]
    # Neighbours: dmask 0, a destination width that disagrees with the dmask, a d16 read of an odd channel count, a
    # write over the outstanding destination, the read before its wait, and other dimensions.
    for new in (sample.replace("dmask:0x1", "dmask:0x0"), sample.replace("v12,", "v[12:13],"),
                sample.replace("dmask:0x1", "dmask:0x3"), sample + " d16",
                sample.replace("dmask:0x1", "dmask:0x7") + " d16",
                sample.replace("SQ_RSRC_IMG_2D", "SQ_RSRC_IMG_2D_ARRAY"),
                sample.replace("SQ_RSRC_IMG_2D", "SQ_RSRC_IMG_CUBE"), sample.replace("SQ_RSRC_IMG_2D", "SQ_RSRC_IMG_3D"),
                sample.replace("v[8:9]", "[v8, v9, v10]")):
        must_reject(translate, changed(new))
    # A d16 read of two set channels packs them in one VGPR, also with a hole between them; a d16 read of an odd count
    # is refused (above).
    packed = translate(d16_holes())
    assert re.search(r"narrow16\(sample\d+\.x\) \| \(narrow16\(sample\d+\.z\) << 16u\)", packed), packed
    wait = red.index("s_waitcnt vmcnt(0)")
    must_reject(translate, red[:wait] + red[wait + 1:])
    must_reject(translate, red[:wait] + ["v_mov_b32_e32 v12, 1.0"] + red[wait:])
    translate(red[:wait] + ["v_mov_b32_e32 v13, 1.0"] + red[wait:])  # v13 is not a destination of a one-channel read

    # Coordinates that stay unproven: an immediate written under the entry mask (before s_wqm_b64 or after EXEC is
    # restored), a copy of an SGPR, a copy made while the lane may be inactive, a product of two varying values, a
    # non-affine operation and a multiply-add whose two factors vary.
    constant = constant_coordinate()
    move = constant.index("v_mov_b32_e32 v9, 0")
    entry = constant[:move] + constant[move + 1:]
    must_reject(translate, ["v_mov_b32_e32 v9, 0"] + [line for line in entry if "attr0.y" not in line])
    restore = entry.index("s_and_b64 exec, exec, s[50:51]")
    must_reject(translate, entry[:restore + 1] + ["v_mov_b32_e32 v9, 0"] + entry[restore + 1:])
    must_reject(translate, constant[:move] + ["s_mov_b32 s70, 0", "v_mov_b32_e32 v9, s70"] + constant[move + 1:])
    # A flat attribute read under whole-quad execution is a coordinate; read under the entry mask it is not.
    flat = [line for line in assembly(False) if line != "v_interp_p2_f32_e32 v9, v1, attr0.y"]
    flat[flat.index("v_interp_p1_f32_e32 v9, v0, attr0.y")] = "v_interp_mov_f32_e32 v9, p0, attr0.y"
    assert re.search(r"\.Sample\(samp, float2\(uv\.x, alu\d+\)\)", translate(flat))
    move = flat.index("v_interp_mov_f32_e32 v9, p0, attr0.y")
    restore = flat.index("s_and_b64 exec, exec, s[50:51]")
    must_reject(translate, flat[:move] + flat[move + 1:restore + 1] + [flat[move]] + flat[restore + 1:])
    lod = lod_programs()["sub-mul-mad"]
    for bad in ("v_mul_f32_e32 v8, v9, v8", "v_sub_f32_e64 v8, v8, |v9|", "v_rcp_f32_e32 v8, v8",
                "v_madak_f32 v8, v8, v9, 0x3f000000", "v_mad_f32 v8, v9, v8, 0", "v_mad_f32 v8, 0.5, v8, 0 clamp"):
        program = lod.copy()
        program[program.index("v_mad_f32 v8, 0.5, v8, 0")] = bad
        must_reject(translate_lod, program)


def controls(directory):
    check_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(program, translate) for program, _, _ in case_programs().values()] + \
        [(program, translate_lod) for program in lod_programs().values()]


draw = check_sample_shapes_draw
