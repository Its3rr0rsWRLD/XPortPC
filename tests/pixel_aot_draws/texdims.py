"""Draw family `texdims`: pixel_aot_check.py draw --family texdims.

image_sample of a 2D-array, cube and 3D T# (docs/design/pixel-bindings.md, "Texture dimensions"), in programs shaped
as RADV writes them (a descriptor set in s2 completed with 0x8000, the interpolation base in s3, whole-quad mode to
the end) and bound by a binding description that declares each texture's dimension. The harness binds the textures
of the case's 'X2WD' section (tests/pixel_aot_render.cpp): an 8x8 R8G8B8A8 array of four slices, the six faces of an
8x8 cube as the Texture2DArray view a cube T# is translated to, and an 8x8x4 3D texture.

The point draws vary the coordinate with the interpolated uv, so each of the 64 texels of the target reads its own
texel; the references are Python models of the console's sample: the array slice rounded by the program's v_rndne and
clamped to the array, the cube face and face coordinates of the v_cube* sequence (LLVM's constant folding, the model
of the `cube` family) mapped from [1, 2] to the face, the 3D r coordinate normalized like s and t. The bilinear draws
bind the translated sampler to the harness's bilinear sampler (s4) and sample constant coordinates at texel centres,
where every adapter's filter weights are exactly 1 and 0, so their references are exact too. Every wrong reference
(the slice truncated instead of rounded, a tie rounded up, the cube face swapped with its opposite, a tie between two
major axes broken the other way, r read as a slice index, two 3D axes exchanged, a neighbouring texel for a bilinear
read) changes some texel and must be reported as a mismatch. Each shader's cases go to the renderer in one batch.
"""
import math
import re
import struct

from pixel_aot_ops.bindings import PixelBindings

from .common import DrawBatch, compile_shader, half_rtz, lower
from .cube import cube_reference

DIMENSIONS_MAGIC = 0x44573258  # 'X2WD'
KIND = {"2d_array": 1, "cube": 2, "3d": 3}
SIZE = 8
SLICES = {"2d_array": 4, "cube": 6, "3d": 4}

# Set 0: the T# at 0x00, its S# at 0x20, the constant-buffer V# (b0, the case's constants) at 0x40.
PROLOGUE = [
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx8 s[8:15], s[2:3], null",
    "s_load_dwordx4 s[4:7], s[2:3], 0x20",
    "s_load_dwordx4 s[16:19], s[2:3], 0x40",
    "s_wqm_b64 exec, exec",
    "s_mov_b32 m0, s0",
    "v_interp_p1_f32_e32 v2, v0, attr0.x",
    "v_interp_p1_f32_e32 v3, v0, attr0.y",
    "v_interp_p2_f32_e32 v2, v1, attr0.x",
    "v_interp_p2_f32_e32 v3, v1, attr0.y",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dwordx16 s[20:35], s[16:19], 0x0",
    "s_waitcnt lgkmcnt(0)",
]
EPILOGUE = [
    "s_waitcnt vmcnt(0)",
    "v_cvt_pkrtz_f16_f32_e32 v24, v20, v21",
    "v_cvt_pkrtz_f16_f32_e32 v25, v22, v23",
    "exp mrt0 v24, v24, v25, v25 done compr vm",
    "s_endpgm",
]


def affine(dst, source, scale, offset):
    """dst = source * constant word `scale` + constant word `offset` (words 0..15 are s20..s35): affine in uv."""
    return [f"v_mul_f32_e32 {dst}, s{20 + scale}, {source}", f"v_add_f32_e32 {dst}, s{20 + offset}, {dst}"]


# 2D array: s = uv.x * w0 + w1, t = uv.y * w2 + w3, slice = v_rndne(w4), an NSA address as RADV writes it.
ARRAY = [*PROLOGUE, *affine("v4", "v2", 0, 1), *affine("v5", "v3", 2, 3),
         "v_rndne_f32_e32 v6, s24",
         "image_sample v[20:23], [v4, v5, v6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D_ARRAY", *EPILOGUE]
# Cube: a = 2 uv.x - 1 and b = 2 uv.y - 1; the direction (x, y, z) = (w0 a + w1 b + w2, w3 a + w4 b + w5,
# w6 a + w7 b + w8); then the corpus's sequence: v_cube{ma,sc,tc,id}, 1 / |ma|, s = sc / |ma| + 1.5, t likewise.
CUBE = [*PROLOGUE,
        "v_fma_f32 v5, v2, 2.0, -1.0",
        "v_fma_f32 v6, v3, 2.0, -1.0",
        *(line for k, d in enumerate(("v7", "v8", "v9"))
          for line in (f"v_mul_f32_e32 {d}, s{20 + 3 * k}, v5", f"v_fmac_f32_e32 {d}, s{21 + 3 * k}, v6",
                       f"v_add_f32_e32 {d}, s{22 + 3 * k}, {d}")),
        "v_cubema_f32 v10, v7, v8, v9",
        "v_cubesc_f32 v11, v7, v8, v9",
        "v_cubetc_f32 v12, v7, v8, v9",
        "v_cubeid_f32 v16, v7, v8, v9",
        "v_rcp_f32_e64 v10, |v10|",
        "v_madak_f32 v14, v11, v10, 0x3fc00000",
        "v_madak_f32 v15, v12, v10, 0x3fc00000",
        "image_sample v[20:23], v[14:16], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE", *EPILOGUE]
# 3D: s = uv.x * w0 + w1, t = uv.y * w2 + w3, r = uv.x * w4 + w5, a v[4:6] range; VOLUME_SWAP names the same three
# values in the order (s, r, t) through an NSA address.
VOLUME = [*PROLOGUE, *affine("v4", "v2", 0, 1), *affine("v5", "v3", 2, 3), *affine("v6", "v2", 4, 5),
          "image_sample v[20:23], v[4:6], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_3D", *EPILOGUE]
VOLUME_SWAP = [line.replace("v[4:6], s[8:15]", "[v4, v6, v5], s[8:15]") for line in VOLUME]


def bindings_for(dimension):
    return PixelBindings(sgprs={"s2": "descriptors", "s3": "interp"}, textures={0x00: 0}, samplers={0: 0x20},
                         constant_buffers={0x40: 0}, dimensions={0: dimension})


def translate_dim(dimension):
    return lambda program: lower(program, bindings=bindings_for(dimension))


translate_array, translate_cube, translate_volume = (translate_dim(d) for d in ("2d_array", "cube", "3d"))


def texel(layer, x, y, channel):
    """Byte `channel` of texel (x, y) of slice, face or depth slice `layer`: every layer and channel differs."""
    return (37 * x + 11 * y + 59 * layer + 71 * channel + 5) & 0xff


def color(layer, x, y):
    return tuple(half_rtz(texel(layer, x, y, c) / 255) for c in range(4))


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def words(values):
    """The 256-byte constant buffer: binary32 words 0.. from `values`, zero words after."""
    data = bytearray(256)
    struct.pack_into(f"<{len(values)}f", data, 0, *values)
    return bytes(data)


def texture_section(dimension):
    layers = SLICES[dimension]
    data = bytearray(struct.pack("<4I", DIMENSIONS_MAGIC, 1, 0, 0))
    data += struct.pack("<8I", 0, KIND[dimension], SIZE, SIZE, layers, 0, 0, 0)
    data += bytes(texel(layer, x, y, c) for layer in range(layers) for y in range(SIZE) for x in range(SIZE)
                  for c in range(4))
    return bytes(data)


def case(dimension, constants, rows):
    data = bytearray(words(constants))
    for row in (rows if len(rows) == 64 else rows * 64):
        data += struct.pack("<4f", *row)
    return bytes(data) + texture_section(dimension)


def pixel_uv(px, py):
    """The interpolated coordinate at the centre of pixel (px, py) of the 64 x 64 target (8 pixels per texel)."""
    return (2 * px + 1) / 128, (2 * py + 1) / 128


def per_texel(lookup):
    """The 64 reference rows of a point draw: lookup(u, v) -> (layer, x, y) at each pixel centre must agree for the
    64 pixels of each texel of the target, as the harness compares one reference per 8 x 8 block."""
    rows = []
    for by in range(8):
        for bx in range(8):
            found = {lookup(*pixel_uv(8 * bx + i, 8 * by + j)) for i in range(8) for j in range(8)}
            assert len(found) == 1, (bx, by, found)
            rows.append(color(*found.pop()))
    return rows


def point(coordinate, size):
    """The texel index a point sample of a normalized coordinate reads under clamp addressing."""
    return min(max(math.floor(coordinate * size), 0), size - 1)


def rndne(x):
    return float(round(x))  # Python rounds half to even, as v_rndne_f32


# --- 2D array -------------------------------------------------------------------------------------------------------
def array_reference(slice_word, flaw=None):
    raw = f32(slice_word)
    layer = {"truncated": math.trunc(raw), "half_up": math.floor(raw + 0.5)}.get(flaw, rndne(raw))
    layer = min(max(int(layer), 0), SLICES["2d_array"] - 1)
    return per_texel(lambda u, v: (layer, point(u, SIZE), point(v, SIZE)))


# (slice word, the wrong references it must expose): integral slices, rounding, ties to even, clamping.
ARRAY_SLICES = ((0.0, ()), (1.0, ()), (2.7, ("truncated",)), (1.5, ()), (2.5, ("half_up",)), (-0.6, ()),
                (9.0, ()), (3.49, ()))


# --- Cube -----------------------------------------------------------------------------------------------------------
# For each face, rows (x, y, z) of the direction as coefficients of (a, b, 1) so that sc = k a, tc = k b, ma = +-k:
# then s = a / 2 + 1.5 = uv.x + 1 and t = uv.y + 1 exactly, and texel (i, j) of the face is the texel the 8 x 8
# block (i, j) of the target reads.
FACE_ROWS = {
    0: ((0, 0, 1), (0, -1, 0), (-1, 0, 0)),
    1: ((0, 0, -1), (0, -1, 0), (1, 0, 0)),
    2: ((1, 0, 0), (0, 0, 1), (0, 1, 0)),
    3: ((1, 0, 0), (0, 0, -1), (0, -1, 0)),
    4: ((1, 0, 0), (0, -1, 0), (0, 0, 1)),
    5: ((-1, 0, 0), (0, -1, 0), (0, 0, -1)),
}
# Ties between two major axes (the later of z, y, x wins, cube_reference): x = -k, y = k picks +Y at its s = 1 edge,
# and y = z = k picks +Z at its t = 1 edge (the edges at 0 of the face, so no coordinate reaches 2).
TIE_ROWS = {
    "yx": ((0, 0, -1), (0, 0, 1), (0, 1, 0)),
    "zy": ((1, 0, 0), (0, 0, 1), (0, 0, 1)),
}


def cube_constants(rows, k):
    return [f32(c * k) for row in rows for c in row]


def cube_lookup(rows, k, flaw=None):
    """The console's texel for the direction at (u, v): the v_cube* model, s and t as the program computes them, the
    face coordinates from [1, 2] to the face. Flaws: the face swapped with its opposite, a tie broken the other way."""
    def lookup(u, v):
        a, b = 2 * u - 1, 2 * v - 1
        x, y, z = (f32(row[0] * k * a + row[1] * k * b + row[2] * k) for row in rows)
        if flaw == "tie_other":
            # The tie given to the earlier axis: y over z, x over y (a desktop projection may break it so).
            ax, ay, az = abs(x), abs(y), abs(z)
            if az == ay >= ax:
                face, sc, tc, ma = (3.0, x, -z, y) if y < 0 else (2.0, x, z, y)
            else:
                face, sc, tc, ma = (1.0, z, -y, x) if x < 0 else (0.0, -z, -y, x)
            ma += ma
        else:
            face, sc, tc, ma = cube_reference(x, y, z)
        s, t = f32(sc * f32(1 / abs(ma)) + 1.5), f32(tc * f32(1 / abs(ma)) + 1.5)
        # The drawn directions keep the console's face coordinates in [1, 2), away from the s or t = 2 edge, where
        # seamless addressing may read the next face (not modelled); only a wrong reference may land on that edge.
        assert 1.0 <= s < 2.0 and 1.0 <= t < 2.0 or flaw, (s, t)
        face = int(face) ^ 1 if flaw == "face_swapped" else int(face)
        return face, point(s - 1, SIZE), point(t - 1, SIZE)
    return lookup


def cube_cases():
    """(constants, reference rows, {flaw: wrong rows}) of the cube point draws."""
    out = []
    for face, rows in FACE_ROWS.items():
        for k in ((1.0, 4.0) if face in (0, 5) else (0.5,)):
            out.append((cube_constants(rows, k), per_texel(cube_lookup(rows, k)),
                        {"face_swapped": per_texel(cube_lookup(rows, k, "face_swapped"))}))
    for rows in TIE_ROWS.values():
        out.append((cube_constants(rows, 2.0), per_texel(cube_lookup(rows, 2.0)),
                    {"tie_other": per_texel(cube_lookup(rows, 2.0, "tie_other"))}))
    return out


# --- 3D -------------------------------------------------------------------------------------------------------------
def volume_reference(r, swapped=False, flaw=None):
    """r: the constant r coordinate (word 5, word 4 = 0). swapped: the program reads (s, r, t) (VOLUME_SWAP). Flaws:
    r read as an unnormalized slice index, the program's axis order ignored."""
    depth = SLICES["3d"]

    def lookup(u, v):
        s, t, q = u, v, r
        if swapped and flaw != "axes_ignored":
            t, q = q, t
        layer = min(max(int(rndne(q)), 0), depth - 1) if flaw == "slice_index" else point(q, depth)
        return layer, point(s, SIZE), point(t, SIZE)
    return per_texel(lookup)


VOLUME_DEPTHS = (0.125, 0.375, 0.625, 0.875, 0.99, 1.2, -0.1)


# --- Bilinear at texel centres --------------------------------------------------------------------------------------
def centre(i, size=SIZE):
    return (2 * i + 1) / (2 * size)


def bilinear_cases():
    """(dimension, program, constants, texel, neighbour) of the bilinear draws: constant coordinates at a texel centre,
    where the filter weights are 1 and 0 on every adapter. The neighbour is the wrong reference."""
    out = []
    for layer, (i, j) in ((0, (0, 0)), (3, (5, 2)), (1, (7, 7))):
        out.append(("2d_array", ARRAY, [0.0, centre(i), 0.0, centre(j), float(layer)], (layer, i, j),
                    (layer, i + 1 if i < 7 else i - 1, j)))
    for face, (i, j) in ((0, (3, 4)), (2, (0, 7)), (5, (6, 1))):
        rows = FACE_ROWS[face]
        a, b = 2 * centre(i) - 1, 2 * centre(j) - 1
        direction = [rows[n][0] * a + rows[n][1] * b + rows[n][2] for n in range(3)]
        constants = [0.0, 0.0, direction[0], 0.0, 0.0, direction[1], 0.0, 0.0, direction[2]]
        out.append(("cube", CUBE, constants, (face, i, j), (face, i, j + 1 if j < 7 else j - 1)))
    for layer, (i, j) in ((0, (2, 6)), (2, (4, 4)), (3, (7, 0))):
        out.append(("3d", VOLUME, [0.0, centre(i), 0.0, centre(j), 0.0, centre(layer, SLICES["3d"])],
                    (layer, i, j), (layer - 1 if layer else 1, i, j)))
    return out


def linear(source):
    """The translated HLSL with its sampler bound to the harness's bilinear sampler s4 (tests/pixel_aot_vs.hlsl)."""
    assert source.count("SamplerState samp : register(s0);") == 1
    return source.replace("SamplerState samp : register(s0);", "SamplerState samp : register(s4);")


def draw(directory, compiler, renderer, backend):
    shaders = {}

    def shader(name, text):
        source, compiled = directory / f"texdims_{name}.hlsl", directory / f"texdims_{name}.cso"
        source.write_text(text, encoding="ascii")
        compile_shader(compiler, source, compiled)
        shaders[name] = compiled
        return compiled

    with DrawBatch(directory, renderer, backend, shader("array", translate_array(ARRAY)), "array") as batch:
        for word, flaws in ARRAY_SLICES:
            constants = [1.0, 0.0, 1.0, 0.0, word]
            batch.add(case("2d_array", constants, array_reference(word)), "pass", f"array slice {word}")
            for flaw in flaws:
                wrong = array_reference(word, flaw)
                assert wrong != array_reference(word), (word, flaw)
                batch.add(case("2d_array", constants, wrong), "mismatch", f"array slice {word}: {flaw} escaped")
    with DrawBatch(directory, renderer, backend, shader("cube", translate_cube(CUBE)), "cube") as batch:
        for n, (constants, rows, wrongs) in enumerate(cube_cases()):
            batch.add(case("cube", constants, rows), "pass", f"cube case {n}")
            for flaw, wrong in wrongs.items():
                assert wrong != rows, (n, flaw)
                batch.add(case("cube", constants, wrong), "mismatch", f"cube case {n}: {flaw} escaped")
    for name, program, swapped in (("volume", VOLUME, False), ("volume_swap", VOLUME_SWAP, True)):
        with DrawBatch(directory, renderer, backend, shader(name, translate_volume(program)), name) as batch:
            for r in VOLUME_DEPTHS:
                constants = [1.0, 0.0, 1.0, 0.0, 0.0, r]
                rows = volume_reference(r, swapped)
                batch.add(case("3d", constants, rows), "pass", f"{name} r={r}")
                for flaw in ("slice_index", "axes_ignored") if swapped else ("slice_index",):
                    wrong = volume_reference(r, swapped, flaw)
                    if wrong != rows:
                        batch.add(case("3d", constants, wrong), "mismatch", f"{name} r={r}: {flaw} escaped")
    translators = {"2d_array": translate_array, "cube": translate_cube, "3d": translate_volume}
    for dimension in ("2d_array", "cube", "3d"):
        program = {"2d_array": ARRAY, "cube": CUBE, "3d": VOLUME}[dimension]
        compiled = shader(f"{dimension}_linear", linear(translators[dimension](program)))
        with DrawBatch(directory, renderer, backend, compiled, f"{dimension}_linear") as batch:
            for dim, _, constants, right, neighbour in bilinear_cases():
                if dim != dimension:
                    continue
                batch.add(case(dim, constants, [color(*right)]), "pass", f"{dim} bilinear {right}")
                assert color(*neighbour) != color(*right)
                batch.add(case(dim, constants, [color(*neighbour)]), "mismatch",
                          f"{dim} bilinear {right}: neighbour {neighbour} escaped")


def refuses(reason, program, translator):
    try:
        translator(program)
    except ValueError as error:
        if not str(error).startswith(reason):
            raise AssertionError(f"Expected refusal {reason!r}, got {error!r}") from error
        return
    raise AssertionError(f"Accepted, expected refusal {reason!r}")


def replaced(program, old, new):
    assert old in program, old
    return [new if line == old else line for line in program]


def controls(directory):
    import corpus_translate
    from pixel_aot_ops.bindings import type_dimension

    array, cube, volume = translate_array(ARRAY), translate_cube(CUBE), translate_volume(VOLUME)
    assert "Texture2DArray<float4> tex : register(t0);" in array and "SamplerState samp : register(s0);" in array
    assert re.search(r"tex\.Sample\(samp, float3\(alu\d+, alu\d+, alu\d+\)\)", array), array
    assert "Texture2DArray<float4> tex : register(t0);" in cube
    assert re.search(r"precise float3 face(\d+) = float3\(alu\d+ - 1\.0f, alu\d+ - 1\.0f, alu\d+\);\n"
                     r"    float4 sample\1 = tex\.Sample\(samp, face\1\);", cube), cube
    assert "Texture3D<float4> tex : register(t0);" in volume
    swap = translate_volume(VOLUME_SWAP)
    order = re.search(r"tex\.Sample\(samp, float3\((alu\d+), (alu\d+), (alu\d+)\)\)", volume).groups()
    assert f"float3({order[0]}, {order[2]}, {order[1]})" in swap, swap
    # The T#'s TYPE field (word 3 bits 28..31) gives the same declaration as the name; 1D and MSAA types are refused.
    for kind, name in ((13, "2d_array"), (11, "cube"), (10, "3d"), (9, "2d")):
        assert type_dimension((0, 0, 0, kind << 28, 0, 0, 0, 0)) == name
    words = (0, 0, 0, 11 << 28, 0, 0, 0, 0)
    assert lower(CUBE, bindings=PixelBindings(**{**bindings_for("cube").__dict__, "dimensions": {0: words}})) == cube
    for kind in (8, 12, 14, 15, 0):
        refuses("Unsupported T# type", CUBE, lambda p, k=kind: lower(p, bindings=PixelBindings(
            **{**bindings_for("cube").__dict__, "dimensions": {0: (0, 0, 0, k << 28, 0, 0, 0, 0)}})))
    refuses("A texture dimension", CUBE, lambda p: lower(p, bindings=PixelBindings(
        **{**bindings_for("cube").__dict__, "dimensions": {1: "cube"}})))
    refuses("A texture dimension", CUBE, translate_dim("cube_array"))
    # The corpus derivation reads each T#'s dimension off the instruction that first samples it.
    for program, dimension in ((ARRAY, "2d_array"), (CUBE, "cube"), (VOLUME, "3d")):
        derived = corpus_translate.derive_bindings(program)
        assert derived.dimensions == {0: dimension}, derived
    # The instruction's dim: must be the bound dimension, both ways; the 2D-only reads refuse a texture of another one.
    sample = next(line for line in CUBE if line.startswith("image_sample"))
    refuses("Image dimension SQ_RSRC_IMG_CUBE does not match", CUBE, translate_array)
    refuses("Image dimension SQ_RSRC_IMG_2D_ARRAY does not match", ARRAY, translate_cube)
    refuses("Image dimension SQ_RSRC_IMG_3D does not match", VOLUME, translate_array)
    refuses("Image dimension SQ_RSRC_IMG_2D does not match",
            replaced(CUBE, sample, "image_sample v[20:23], v[14:15], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D"),
            translate_cube)
    for neighbour in ("image_sample_lz v[20:23], v[14:15], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D",
                      "image_load v[20:23], v[14:15], s[8:15] dmask:0xf dim:SQ_RSRC_IMG_2D unorm"):
        refuses("Image dimension SQ_RSRC_IMG_2D does not match", replaced(CUBE, sample, neighbour), translate_cube)
    # The fixed contract binds a 2D texture: the other dimensions stay refused there (also sample_shapes controls).
    # A two-word address for a three-word dimension, and a four-word list.
    refuses("Image address width mismatch", replaced(ARRAY, ARRAY[ARRAY.index(next(
        line for line in ARRAY if line.startswith("image_sample")))],
        "image_sample v[20:23], [v4, v5], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_2D_ARRAY"), translate_array)
    refuses("Image address width mismatch", replaced(CUBE, sample,
            "image_sample v[20:23], [v14, v15, v16, v17], s[8:15], s[4:7] dmask:0xf dim:SQ_RSRC_IMG_CUBE"), translate_cube)
    # A slice that is not an integer value: the texture unit's rounding is not modelled.
    refuses("An array slice must be an integer value", replaced(ARRAY, "v_rndne_f32_e32 v6, s24",
                                                                "v_mov_b32_e32 v6, s24"), translate_array)
    refuses("An array slice must be an integer value", replaced(ARRAY, "v_rndne_f32_e32 v6, s24",
                                                                "v_fract_f32_e32 v6, s24"), translate_array)
    refuses("An array slice must be an integer value", replaced(ARRAY, "v_rndne_f32_e32 v6, s24",
                                                                "v_mov_b32_e32 v6, 0.5"), translate_array)
    for integral in ("v_floor_f32_e32 v6, s24", "v_trunc_f32_e32 v6, s24", "v_ceil_f32_e32 v6, s24",
                     "v_cvt_f32_u32_e32 v6, s24", "v_cvt_f32_i32_e32 v6, s24", "v_mov_b32_e32 v6, 2.0",
                     "v_mov_b32_e32 v6, 0x40400000", "v_mov_b32_e32 v6, 0"):
        translate_array(replaced(ARRAY, "v_rndne_f32_e32 v6, s24", integral))
    refuses("An array slice must be an integer value", replaced(ARRAY, "v_rndne_f32_e32 v6, s24",
                                                                "v_rndne_f32_e64 v6, s24 div:2"), translate_array)
    # A cube face that is not a v_cubeid result, and face coordinates that are not helper-lane values.
    refuses("A cube face must be a v_cubeid result",
            replaced(CUBE, "v_cubeid_f32 v16, v7, v8, v9", "v_cubema_f32 v16, v7, v8, v9"), translate_cube)
    refuses("A cube face must be a v_cubeid result",
            replaced(CUBE, "v_cubeid_f32 v16, v7, v8, v9", "v_rndne_f32_e32 v16, s20"), translate_cube)
    refuses("A cube face must be a v_cubeid result",
            replaced(CUBE, "v_cubeid_f32 v16, v7, v8, v9", "v_cubeid_f32 v16, v7, v8, v9 clamp"), translate_cube)
    # Face coordinates computed under the entry mask (EXEC restored after the interpolation) are not defined on the
    # helper lanes.
    at = CUBE.index("v_cubema_f32 v10, v7, v8, v9")
    unproven = ["s_mov_b64 s[50:51], exec", *CUBE[:at], "s_and_b64 exec, exec, s[50:51]", *CUBE[at:]]
    refuses("Unsupported texture coordinate", unproven, translate_cube)
    refuses("Unsupported texture coordinate", replaced(CUBE, "v_madak_f32 v14, v11, v10, 0x3fc00000",
                                                       "v_mov_b32_e32 v14, s20"), translate_cube)
    # The 2D-array and 3D coordinates enter the level as 2D ones do: they must be affine helper-lane values.
    refuses("Unsupported texture coordinate", replaced(VOLUME, "v_add_f32_e32 v6, s25, v6", "v_rcp_f32_e32 v6, v6"),
            translate_volume)
    refuses("Unsupported texture coordinate", replaced(ARRAY, "v_add_f32_e32 v4, s21, v4", "v_rcp_f32_e32 v4, v4"),
            translate_array)
    # Wrong references differ from the right ones on the inputs drawn.
    assert array_reference(2.7, "truncated") != array_reference(2.7)
    assert all(rows != wrongs[flaw] for _, rows, wrongs in cube_cases() for flaw in wrongs)
    assert volume_reference(0.625, flaw="slice_index") != volume_reference(0.625)
    assert volume_reference(0.375, True, "axes_ignored") != volume_reference(0.375, True)
    assert {face for face in range(6)} == {cube_lookup(rows, 1.0)(0.3, 0.6)[0] for rows in FACE_ROWS.values()}


def binary_fixtures():
    return [(ARRAY, translate_array), (CUBE, translate_cube), (VOLUME, translate_volume),
            (VOLUME_SWAP, translate_volume)]
