"""Draw family `dim_levels`: pixel_aot_check.py draw --family dim_levels.

image_sample_lz, _l and _b of a 2D-array and a cube T# (tools/pixel_aot_ops/forms/mimg.py, sample_level), in the programs
of the `texdims` family (the same prologue, coordinates and v_cube* sequence) bound to a texture with all four levels
(8x8, 4x4, 2x2, 1x1) and a different value in every level, slice or face, texel and channel. The harness binds the
'X2WD' section's mip levels (tests/pixel_aot_render.cpp); the sampler is the harness's point one, clamp addressing,
nearest mip.

The 64x64 target reads an 8x8 level 0 at 8 pixels per texel, so an implicit level is about -3 and clamps to level 0.
That gives the references their levels:
- _l: the level is the explicit lod, rounded to the nearest and clamped to the levels that exist (a lod of 7 reads level
  3, a negative one level 0). Lods at least 0.1 from a half, so that no adapter's rounding can differ.
- _b: the level is -3 + bias, rounded and clamped; biases at x.75 give lod x - 2.25, again 0.25 from a half. The coordinates
  are the interpolated ones (the bias form needs their derivatives).
- _lz: level 0 and the slice or face mapping only; at this scale the implicit level is 0 too, so the form's level is not
  separable here (the 2D draws of the `image` family put it at level 1).
Wrong references: the lod or the bias ignored (level 0), the bias sign flipped (level 0, or the clamp of a negative one),
the bias taken as a lod, the lod truncated instead of rounded, the slice truncated. Each must be reported as a mismatch.
"""
import math
import struct

from .common import DrawBatch, compile_shader, half_rtz
from .texdims import (ARRAY, CUBE, DIMENSIONS_MAGIC, FACE_ROWS, KIND, SIZE, SLICES, cube_constants, cube_lookup,
                      point, refuses, replaced, rndne, translate_array, translate_cube, words)

LEVELS = 4


def texel(level, layer, x, y, channel):
    return (37 * x + 11 * y + 59 * layer + 71 * channel + 113 * level + 5) & 0xff


def color(level, layer, x, y):
    return tuple(half_rtz(texel(level, layer, x, y, c) / 255) for c in range(4))


def texture_section(dimension):
    data = bytearray(struct.pack("<4I", DIMENSIONS_MAGIC, 1, 0, 0))
    data += struct.pack("<8I", 0, KIND[dimension], SIZE, SIZE, SLICES[dimension], LEVELS, 0, 0)
    for layer in range(SLICES[dimension]):
        for level in range(LEVELS):
            size = SIZE >> level
            data += bytes(texel(level, layer, x, y, c) for y in range(size) for x in range(size) for c in range(4))
    return bytes(data)


def case(dimension, constants, rows):
    data = bytearray(words(constants))
    for row in rows:
        data += struct.pack("<4f", *row)
    return bytes(data) + texture_section(dimension)


def nearest(x):
    """The level of a lod: nearest, clamped to the levels that exist."""
    return min(max(math.floor(x + 0.5), 0), LEVELS - 1)


def level_of(kind, value, flaw=None):
    """The level read by an _l (value = lod) or _b (value = bias) sample of this draw, or by the flawed lowering."""
    if kind == "lz":
        return 0
    if kind == "l":
        return {"ignored": 0, "truncated": min(max(math.floor(value), 0), LEVELS - 1)}.get(flaw, nearest(value))
    return {"ignored": 0, "negated": nearest(-3 - value), "as_lod": nearest(value)}.get(flaw, nearest(-3 + value))


def lookups(kind, dimension, args, flaw=None):
    """The 64 reference colours of a case: the (level, layer, x, y) of each 8x8 block of the target."""
    if dimension == "2d_array":
        slice_word, value = args
        layer = {"truncated_slice": math.trunc(slice_word)}.get(flaw, int(rndne(slice_word)))
        layer = min(max(layer, 0), SLICES["2d_array"] - 1)
        level = level_of(kind, value, None if flaw == "truncated_slice" else flaw)
        read = lambda u, v: (level, layer, point(u, SIZE >> level), point(v, SIZE >> level))
    else:
        face_rows, k, value = args
        level = level_of(kind, value, flaw)
        lookup = cube_lookup(face_rows, k)

        def read(u, v):
            face, i, j = lookup(u, v)
            return level, face, i >> level, j >> level
    return read


def colours(kind, dimension, args, flaw=None):
    read = lookups(kind, dimension, args, flaw)
    rows = []
    for by in range(8):
        for bx in range(8):
            found = {read((2 * (8 * bx + i) + 1) / 128, (2 * (8 * by + j) + 1) / 128) for i in range(8) for j in range(8)}
            assert len(found) == 1, (bx, by, found)
            rows.append(color(*found.pop()))
    return rows


# Programs: the texdims ones with the sample replaced. v7 / v17 hold the lod or bias, word 5 / 9 of the constants.
def sample_of(program):
    return next(line for line in program if line.startswith("image_sample"))


def array_program(kind):
    sample = sample_of(ARRAY)
    new = {"lz": ["image_sample_lz v[20:23], [v4, v5, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D_ARRAY"],
           "l": ["v_mov_b32_e32 v7, s25",
                 "image_sample_l v[20:23], [v4, v5, v6, v7], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D_ARRAY"],
           "b": ["v_mov_b32_e32 v7, s25",
                 "image_sample_b v[20:23], [v7, v4, v5, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D_ARRAY"]}[kind]
    at = ARRAY.index(sample)
    return ARRAY[:at] + new + ARRAY[at + 1:]


def cube_program(kind):
    sample = sample_of(CUBE)
    new = {"lz": ["image_sample_lz v[20:23], [v14, v15, v16], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"],
           "l": ["v_mov_b32_e32 v17, s29",
                 "image_sample_l v[20:23], [v14, v15, v16, v17], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"],
           "b": ["v_mov_b32_e32 v17, s29",
                 "image_sample_b v[20:23], [v17, v14, v15, v16], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"]}[kind]
    at = CUBE.index(sample)
    return CUBE[:at] + new + CUBE[at + 1:]


# (slice word, value): rounding of the slice, and lods and biases of every level, clamped and rounded.
ARRAY_CASES = {
    "lz": [(0.0, 0.0), (1.0, 0.0), (3.0, 0.0), (2.7, 0.0), (1.5, 0.0), (9.0, 0.0)],
    "l": [(1.0, 0.0), (2.0, 1.0), (0.0, 2.0), (3.0, 3.0), (1.0, 7.0), (2.0, -1.0), (3.0, 1.6), (0.0, 2.4), (2.7, 1.0)],
    "b": [(1.0, 3.75), (2.0, 4.75), (0.0, 5.75), (3.0, 9.0), (1.0, 2.75), (2.0, -2.0), (3.0, 4.25), (2.7, 3.75)],
}
CUBE_VALUES = {
    "lz": [0.0] * 6,
    "l": [1.0, 2.0, 0.0, 3.0, 1.6, 7.0, 2.4, -1.0, 2.0, 1.0, 3.0, 0.0],
    "b": [3.75, 4.75, 5.75, 9.0, 2.75, 3.75, 4.25, -2.0, 5.75, 3.75, 4.75, 2.75],
}
FLAWS = {"lz": (), "l": ("ignored", "truncated"), "b": ("ignored", "negated", "as_lod")}


def cube_cases(kind):
    out = []
    for n, value in enumerate(CUBE_VALUES[kind]):
        face = n % 6
        k = (1.0, 4.0)[n // 6] if face in (0, 5) else 0.5
        out.append((cube_constants(FACE_ROWS[face], k), (FACE_ROWS[face], k, value)))
    return out


def draw(directory, compiler, renderer, backend):
    for dimension, translate, program_of in (("2d_array", translate_array, array_program),
                                         ("cube", translate_cube, cube_program)):
        for kind in ("lz", "l", "b"):
            name = f"{dimension}_{kind}"
            source, shader = directory / f"dim_levels_{name}.hlsl", directory / f"dim_levels_{name}.cso"
            source.write_text(translate(program_of(kind)), encoding="ascii")
            compile_shader(compiler, source, shader)
            if dimension == "2d_array":
                cases = [([1.0, 0.0, 1.0, 0.0, word, value], (word, value)) for word, value in ARRAY_CASES[kind]]
                flaws = (*FLAWS[kind], "truncated_slice")
            else:
                cases = [([*constants, args[2]], args) for constants, args in cube_cases(kind)]
                flaws = FLAWS[kind]
            with DrawBatch(directory, renderer, backend, shader, name) as batch:
                for constants, args in cases:
                    right = colours(kind, dimension, args)
                    batch.add(case(dimension, constants, right), "pass", f"{name} {args}")
                    for flaw in flaws:
                        wrong = colours(kind, dimension, args, flaw)
                        if wrong != right:
                            batch.add(case(dimension, constants, wrong), "mismatch", f"{name} {args}: {flaw} escaped")


def controls(directory):
    import re
    for kind in ("lz", "l", "b"):
        array, cube = translate_array(array_program(kind)), translate_cube(cube_program(kind))
        assert "Texture2DArray<float4> tex : register(t0);" in array and "Texture2DArray<float4> tex : register(t0);" in cube
        if kind == "b":
            assert re.search(r"tex\.SampleBias\(samp, float3\(alu\d+, alu\d+, alu\d+\), asfloat\(movw\d+\)\)", array), array
            assert re.search(r"tex\.SampleBias\(samp, face\d+, asfloat\(movw\d+\)\)", cube), cube
        elif kind == "l":
            assert re.search(r"tex\.SampleLevel\(samp, float3\(alu\d+, alu\d+, alu\d+\), asfloat\(movw\d+\)\)", array), array
            assert re.search(r"tex\.SampleLevel\(samp, face\d+, asfloat\(movw\d+\)\)", cube), cube
        else:
            assert re.search(r"tex\.SampleLevel\(samp, float3\(alu\d+, alu\d+, alu\d+\), 0\.0f\)", array), array
            assert re.search(r"tex\.SampleLevel\(samp, face\d+, 0\.0f\)", cube), cube
        assert "precise float3 face" in cube
    a_l, c_l, a_b, c_b = (sample_of(p) for p in (array_program("l"), cube_program("l"), array_program("b"), cube_program("b")))
    for program, translate, sample in ((array_program("l"), translate_array, a_l), (cube_program("l"), translate_cube, c_l),
                                       (array_program("b"), translate_array, a_b), (cube_program("b"), translate_cube, c_b)):
        # Forms of the same instruction that are not lowered on these dimensions: offsets, gradients, a16, tfe, lwe,
        # a dmask that disagrees with the destination, an address of the wrong width, and the other dimension.
        base = sample.split(" ", 1)[0]
        for new in (sample.replace(base, base + "_o"), sample.replace(base, "image_sample_d"), sample.replace(base, "image_sample_o"),
                    sample.replace(base, "image_sample_c_l"), sample + " a16", sample + " tfe", sample + " lwe",
                    sample.replace("dmask:0xf", "dmask:0x7"), sample.replace("v[20:23]", "v[20:22]"),
                    sample.replace("SQ_RSRC_IMG_2D_ARRAY", "SQ_RSRC_IMG_CUBE") if "ARRAY" in sample
                    else sample.replace("SQ_RSRC_IMG_CUBE", "SQ_RSRC_IMG_2D_ARRAY")):
            try:
                translate(replaced(program, sample, new))
            except ValueError:
                continue
            raise AssertionError(f"Accepted: {new}")
    for op in ("l", "b"):
        # An address of three words for the four-word forms.
        program = array_program(op)
        sample = sample_of(program)
        short = sample.replace("[v7, v4, v5, v6]" if op == "b" else "[v4, v5, v6, v7]", "[v4, v5, v6]")
        refuses("Image address width mismatch", replaced(program, sample, short), translate_array)
    # The slice and the cube face are checked as for the implicit level (refusals of the explicit_coordinate).
    refuses("An array slice must be an integer value", replaced(array_program("l"), "v_rndne_f32_e32 v6, s24",
                                                                "v_mov_b32_e32 v6, s24"), translate_array)
    refuses("An array slice must be an integer value", replaced(array_program("lz"), "v_rndne_f32_e32 v6, s24",
                                                                "v_fract_f32_e32 v6, s24"), translate_array)
    refuses("A cube face must be a v_cubeid result",
            replaced(cube_program("l"), "v_cubeid_f32 v16, v7, v8, v9", "v_cubema_f32 v16, v7, v8, v9"), translate_cube)
    # The biased forms need the interpolated coordinates (their derivatives), which the explicit ones do not.
    refuses("Unsupported texture coordinate", replaced(array_program("b"), "v_add_f32_e32 v4, s21, v4", "v_rcp_f32_e32 v4, v4"),
            translate_array)
    translate_array(replaced(array_program("l"), "v_add_f32_e32 v4, s21, v4", "v_rcp_f32_e32 v4, v4"))
    # Wrong references differ from the right ones on the draws.
    for kind in ("l", "b"):
        for flaw in FLAWS[kind]:
            assert any(colours(kind, "2d_array", args, flaw) != colours(kind, "2d_array", args) for args in ARRAY_CASES[kind]), (kind, flaw)
            assert any(colours(kind, "cube", args, flaw) != colours(kind, "cube", args) for _, args in cube_cases(kind)), (kind, flaw)
    assert any(colours("lz", "2d_array", args, "truncated_slice") != colours("lz", "2d_array", args) for args in ARRAY_CASES["lz"])


def binary_fixtures():
    return [(array_program(k), translate_array) for k in ("lz", "l", "b")] + \
        [(cube_program(k), translate_cube) for k in ("lz", "l", "b")]
