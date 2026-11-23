"""Draw family `cube_array`: pixel_aot_check.py draw --family cube_array.

image_sample, _b, _l and _lz of a cube-array T# (tools/pixel_aot_ops/forms/mimg.py, cube_face; docs/design/pixel-bindings.md,
"Cube arrays"): the face word is the v_cubeid face plus 8 times an integral layer, as Mesa's ac_prepare_cube_coords
writes it and as the corpus's texturecubemaparray programs compute it (v_cvt_f32_i32 of a push word, then
v_madmk_f32 layer, 0x41000000, face). The programs are the `texdims` cube program (the same prologue, direction and
v_cube* sequence) with the layer added: from v_rndne_f32 of constant word 10 for the implicit-level forms (a GLSL
float layer), from v_cvt_f32_i32 of word 10 for the explicit ones (the corpus's integer push word), once through
v_madmk_f32 and once (lz) through the VOP3 v_fma_f32 with the 8.0 literal. Word 9 is the lod or bias.

The texture is a cube array of three 8x8 cubes with four levels, bound by the harness ('X2WD' kind 4,
tests/pixel_aot_render.cpp) as the Texture2DArray view of its 18 faces, cube n at slices 6 n .. 6 n + 5; every
level, slice, texel and channel differs. The references: the face and face coordinates of the `texdims` cube model,
the layer rounded (v_rndne, ties to even) or converted, clamped to [0, 2] (Vulkan clamps a cube array's layer, and RADV
emits no clamp), slice face + 6 layer; the level as in the `dim_levels` family. Wrong references, each of which must be
reported as a mismatch where it differs: the layer ignored (cube 0), the face word used as the slice (face + 8 layer,
the slice clamped), face and layer mixed up (layer + 6 face), and Direct3D's slice clamp in place of the layer clamp (a
layer past the end reading the last face of the last cube).
"""
import math
import re
import struct

from pixel_aot_ops.bindings import PixelBindings

from .common import DrawBatch, compile_shader, half_rtz, lower
from .texdims import CUBE, DIMENSIONS_MAGIC, FACE_ROWS, SIZE, cube_constants, cube_lookup, refuses, replaced

CUBES = 3
SLICES = 6 * CUBES
LEVELS = 4
KIND = 4  # 'X2WD' cube-array faces


def bindings(dimension="cube_array"):
    return PixelBindings(sgprs={"s2": "descriptors", "s3": "interp"}, textures={0x00: 0}, samplers={0: 0x20},
                         constant_buffers={0x40: 0}, dimensions={0: dimension})


def translate(program, dimension="cube_array"):
    return lower(program, bindings=bindings(dimension))


def texel(level, layer, x, y, channel):
    return (37 * x + 11 * y + 59 * layer + 71 * channel + 113 * level + 5) & 0xff


def color(level, layer, x, y):
    return tuple(half_rtz(texel(level, layer, x, y, c) / 255) for c in range(4))


def texture_section():
    data = bytearray(struct.pack("<4I", DIMENSIONS_MAGIC, 1, 0, 0))
    data += struct.pack("<8I", 0, KIND, SIZE, SIZE, SLICES, LEVELS, 0, 0)
    for layer in range(SLICES):
        for level in range(LEVELS):
            size = SIZE >> level
            data += bytes(texel(level, layer, x, y, c) for y in range(size) for x in range(size) for c in range(4))
    return bytes(data)


def constant_words(direction, value, layer_word):
    """The 256-byte constant buffer: words 0..8 the direction, 9 the lod or bias, 10 the layer word (a binary32 for the
    v_rndne programs, an int32 for the v_cvt_f32_i32 ones)."""
    data = bytearray(256)
    struct.pack_into("<10f", data, 0, *direction, value)
    struct.pack_into("<f" if isinstance(layer_word, float) else "<i", data, 40, layer_word)
    return bytes(data)


def case(constants, rows):
    data = bytearray(constants)
    for row in rows:
        data += struct.pack("<4f", *row)
    return bytes(data) + texture_section()


# The programs: the texdims cube sample replaced by the layer, the face word (v18) and the sample. v19: lod or bias.
SAMPLES = {
    "plain": ["v_rndne_f32_e32 v17, s30", "v_madmk_f32 v18, v17, 0x41000000, v16",
              "image_sample v[20:23], [v14, v15, v18], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"],
    "b": ["v_rndne_f32_e32 v17, s30", "v_madmk_f32 v18, v17, 0x41000000, v16", "v_mov_b32_e32 v19, s29",
          "image_sample_b v[20:23], [v19, v14, v15, v18], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"],
    "l": ["v_cvt_f32_i32_e32 v17, s30", "v_madmk_f32 v18, v17, 0x41000000, v16", "v_mov_b32_e32 v19, s29",
          "image_sample_l v[20:23], [v14, v15, v18, v19], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"],
    "lz": ["v_cvt_f32_i32_e32 v17, s30", "v_fma_f32 v18, v17, 0x41000000, v16",
           "image_sample_lz v[20:23], [v14, v15, v18], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"],
}


def program(kind):
    sample = next(line for line in CUBE if line.startswith("image_sample"))
    at = CUBE.index(sample)
    return CUBE[:at] + SAMPLES[kind] + CUBE[at + 1:]


def nearest(x):
    return min(max(math.floor(x + 0.5), 0), LEVELS - 1)


def level_of(kind, value):
    """The level of this draw: implicit about -3 at 8 pixels per texel (level 0), the lod, or -3 + bias."""
    return {"plain": 0, "lz": 0, "l": nearest(value), "b": nearest(-3 + value)}[kind]


def layer_of(kind, word):
    """The console's integral layer: v_rndne (ties to even) of a float word, or the int32 converted."""
    return float(round(word)) if kind in ("plain", "b") else float(word)


def slice_of(face, layer, flaw=None):
    clamp = lambda x, top: int(min(max(x, 0), top))  # noqa: E731
    if flaw == "layer_ignored":
        return face
    if flaw == "raw_word":
        return clamp(face + 8 * layer, SLICES - 1)
    if flaw == "mixed_up":
        return clamp(layer + 6 * face, SLICES - 1)
    if flaw == "slice_clamped":
        return clamp(face + 6 * layer, SLICES - 1)
    return face + 6 * clamp(layer, CUBES - 1)


FLAWS = ("layer_ignored", "raw_word", "mixed_up", "slice_clamped")


def colours(kind, rows, k, value, word, flaw=None):
    level, layer = level_of(kind, value), layer_of(kind, word)
    lookup = cube_lookup(rows, k)
    out = []
    for by in range(8):
        for bx in range(8):
            found = set()
            for i in range(8):
                for j in range(8):
                    face, x, y = lookup((2 * (8 * bx + i) + 1) / 128, (2 * (8 * by + j) + 1) / 128)
                    found.add((level, slice_of(face, layer, flaw), x >> level, y >> level))
            assert len(found) == 1, (bx, by, found)
            out.append(color(*found.pop()))
    return out


# (face, layer word, lod or bias) per form: every face, every cube, layers past either end, rounding of a float layer.
CASES = {
    "plain": [(0, 0.0, 0.0), (1, 1.0, 0.0), (2, 2.0, 0.0), (3, 1.5, 0.0), (4, 2.5, 0.0), (5, 0.4, 0.0),
              (0, 5.0, 0.0), (2, -1.0, 0.0)],
    "b": [(0, 1.0, 3.75), (1, 2.0, 4.75), (2, 0.0, 5.75), (3, 2.0, 2.75), (4, 1.5, 9.0), (5, 0.0, 4.25), (1, 7.0, 3.75)],
    "l": [(0, 2, 1.0), (1, 0, 2.0), (2, 1, 0.0), (3, 2, 3.0), (4, 1, 1.6), (5, 3, 0.0), (0, -2, 2.4), (2, 9, 1.0)],
    "lz": [(0, 1, 0.0), (1, 2, 0.0), (2, 0, 0.0), (3, 1, 0.0), (4, 2, 0.0), (5, 0, 0.0), (1, 4, 0.0), (3, -1, 0.0)],
}


def cases(kind):
    """(constants, rows, k, value, word) of each case: the direction of the texdims face rows at scale k."""
    out = []
    for face, word, value in CASES[kind]:
        k = 1.0 if face in (0, 5) else 0.5
        rows = FACE_ROWS[face]
        out.append((constant_words(cube_constants(rows, k), value, word), rows, k, value, word))
    return out


def draw(directory, compiler, renderer, backend):
    for kind in SAMPLES:
        source, shader = directory / f"cube_array_{kind}.hlsl", directory / f"cube_array_{kind}.cso"
        source.write_text(translate(program(kind)), encoding="ascii")
        compile_shader(compiler, source, shader)
        with DrawBatch(directory, renderer, backend, shader, f"cube_array_{kind}") as batch:
            for n, (constants, rows, k, value, word) in enumerate(cases(kind)):
                right = colours(kind, rows, k, value, word)
                batch.add(case(constants, right), "pass", f"cube_array {kind} case {n}")
                for flaw in FLAWS:
                    wrong = colours(kind, rows, k, value, word, flaw)
                    if wrong != right:
                        batch.add(case(constants, wrong), "mismatch", f"cube_array {kind} case {n}: {flaw} escaped")


def controls(directory):
    for kind in SAMPLES:
        source = translate(program(kind))
        assert "Texture2DArray<float4> tex : register(t0);" in source
        m = re.search(r"tex\.GetDimensions\(face(\d+)_w, face\1_h, face\1_n\);\n"
                      r"    precise float face\1_layer = clamp\(alu\d+, 0\.0f, float\(face\1_n / 6u\) - 1\.0f\);\n"
                      r"    precise float3 face\1 = float3\((alu\d+|asfloat\(movw\d+\)) - 1\.0f, "
                      r"(alu\d+|asfloat\(movw\d+\)) - 1\.0f, alu\d+ \+ 6\.0f \* face\1_layer\);", source)
        assert m, source
        # "cube" binds the same view: a cube T# may hold an array of cubes.
        assert translate(program(kind), "cube") == source
    # The plain cube (a v_cubeid face) keeps its HLSL on a cube-array binding: layer 0.
    assert "GetDimensions" not in translate(CUBE)
    # Face words that are not face + 8 * integral layer: a fractional layer, another factor, the face as the factor,
    # the layer added to the face, a negated layer, a clamped or scaled mad.
    plain = program("plain")
    for old, new in (("v_rndne_f32_e32 v17, s30", "v_mov_b32_e32 v17, s30"),
                     ("v_rndne_f32_e32 v17, s30", "v_fract_f32_e32 v17, s30"),
                     ("v_madmk_f32 v18, v17, 0x41000000, v16", "v_madmk_f32 v18, v17, 0x40c00000, v16"),
                     ("v_madmk_f32 v18, v17, 0x41000000, v16", "v_madmk_f32 v18, v16, 0x41000000, v17"),
                     ("v_madmk_f32 v18, v17, 0x41000000, v16", "v_add_f32_e32 v18, v17, v16"),
                     ("v_madmk_f32 v18, v17, 0x41000000, v16", "v_mad_f32 v18, -v17, 0x41000000, v16"),
                     ("v_madmk_f32 v18, v17, 0x41000000, v16", "v_mad_f32 v18, v17, 0x41000000, v16 clamp"),
                     ("v_madmk_f32 v18, v17, 0x41000000, v16", "v_mad_f32 v18, v17, 0x41000000, v16 mul:2")):
        refuses("A cube face must be a v_cubeid result", replaced(plain, old, new), translate)
    # The VOP3 forms with the literal in either factor, and a copy of the face word, are accepted.
    for new in ("v_mad_f32 v18, v17, 0x41000000, v16", "v_fma_f32 v18, 0x41000000, v17, v16",
                "v_fmamk_f32 v18, v17, 0x41000000, v16"):
        assert "face" in translate(replaced(plain, "v_madmk_f32 v18, v17, 0x41000000, v16", new))
    copied = [*plain[:plain.index("v_madmk_f32 v18, v17, 0x41000000, v16") + 1], "v_mov_b32_e32 v24, v18",
              *[line.replace("[v14, v15, v18]", "[v14, v15, v24]") for line in
                plain[plain.index("v_madmk_f32 v18, v17, 0x41000000, v16") + 1:]]]
    assert "face" in translate(copied) and "6.0f * face" in translate(copied)
    # A 2D-array binding still refuses the cube instruction.
    refuses("Image dimension SQ_RSRC_IMG_CUBE does not match", plain, lambda p: translate(p, "2d_array"))
    # Every wrong reference differs from the right one on some case of every form where it can.
    for flaw in FLAWS:
        for kind in SAMPLES:
            assert any(colours(kind, r, k, v, w, flaw) != colours(kind, r, k, v, w) for _, r, k, v, w in cases(kind)), \
                (kind, flaw)


def binary_fixtures():
    return [(program(kind), translate) for kind in SAMPLES]
