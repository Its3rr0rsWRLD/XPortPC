"""Draw family `image`: pixel_aot_check.py draw --family image."""
import struct
import subprocess

from .common import M32, RAMP, f32, half_rtz, move, must_reject, translate, ubyte, with_constants


# MIMG loads, level queries and gathers on the 8x8 R8G8B8A8 fixture texture, whose texel (x, y) is (RAMP[x], RAMP[y], 128, 255)
# and which has one mip level. Every coordinate comes from the case constants (or an inline constant) so the draw does not
# depend on the pixel. Outputs are exported directly, as unorm floats, or through v_cvt_f32_ubyte0 for the integer words of
# image_get_resinfo. The texture is square, so width and height are not told apart by the draws; there is one level, so
# a level above 0 is out of range. The wrong references are the plausible lowering bugs: swapped x and y, the first N
# channels instead of the dmask channels, clamped or wrapped coordinates, an ignored mip index, an unzeroed
# out-of-range level, a changed footprint order and the wrong gather component.
IMG = "dim:SQ_RSRC_IMG_2D"
SRC = "s[28:35]"
unorm_export = lambda byte_value: half_rtz(f32(byte_value / 255.0))
float_bits = lambda x: struct.unpack("<I", struct.pack("<f", x))[0]


def texel(x, y):
    """The fixture texel as bytes; any coordinate outside the 8x8 base level reads zero."""
    return (RAMP[x], RAMP[y], 128, 255) if x < 8 and y < 8 else (0, 0, 0, 0)


def pick(values, dmask):
    return [value for c, value in enumerate(values) if dmask >> c & 1]


def image_load_body(*loads):
    """loads: (op, destination, dmask, source sgprs, modifiers). Coordinates move to v18 and up, one group per load."""
    body = []
    first = 18
    for op, dst, dmask, sources, modifiers in loads:
        regs = []
        for source in sources:
            body.append(move(first + len(regs), source))
            regs.append(first + len(regs))
        address = f"v{regs[0]}" if len(regs) == 1 else f"v[{regs[0]}:{regs[-1]}]"
        body.append(f"image_{op} {dst}, {address}, {SRC} dmask:{dmask:#x} {IMG}{modifiers}")
        first += len(regs)
    return [*body, "s_waitcnt vmcnt(0)"]


def image_gather_body(op, dmask):
    return ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45",
            f"image_{op} v[12:15], v[18:19], {SRC}, s[40:43] dmask:{dmask:#x} {IMG}", "s_waitcnt vmcnt(0)"]


def info_body(*queries):
    """queries: (destination base, dmask, level sgpr). Outputs are v12..v15 from the listed result registers."""
    body = []
    for n, (base, dmask, level) in enumerate(queries):
        body.append(move(30 + n, level))
        count = bin(dmask).count("1")
        dst = f"v{base}" if count == 1 else f"v[{base}:{base + count - 1}]"
        body.append(f"image_get_resinfo {dst}, v{30 + n}, {SRC} dmask:{dmask:#x} {IMG}")
    return [*body, "s_waitcnt vmcnt(0)"]


def exported(*values):
    return [unorm_export(v) for v in values]


# (name, body, constant words, reference floats, wrong reference floats)
GATHER_WORDS = (float_bits(3.25 / 8), float_bits(5.75 / 8), 0, 0)
# At (3.25, 5.75) texels the footprint is columns 2 and 3 and rows 5 and 6. The order is lower left, lower right,
# upper right, upper left, so red is [37, 64, 64, 37] and green is [219, 219, 153, 153].
GL, GR, GT, GB = RAMP[2], RAMP[3], RAMP[5], RAMP[6]
IMAGE_PROGRAMS = (
    ("load", image_load_body(("load", "v[12:15]", 0xf, ("s44", "s45"), " unorm")), (2, 5, 0, 0),
     exported(*texel(2, 5)), [exported(*texel(5, 2))]),
    ("pack", image_load_body(("load", "v[12:13]", 0x5, ("s44", "s45"), " unorm glc"),
                             ("load", "v[14:15]", 0xa, ("s46", "s47"), " dlc")), (6, 1, 3, 4),
     exported(*pick(texel(6, 1), 0x5), *pick(texel(3, 4), 0xa)),
     [exported(*texel(6, 1)[:2], *texel(3, 4)[:2]), exported(*pick(texel(6, 1), 0x5), *texel(3, 4)[:2]),
      exported(*texel(6, 1)[:2], *pick(texel(3, 4), 0xa))]),
    ("single", image_load_body(("load", "v12", 0x2, ("s44", "s45"), ""), ("load", "v13", 0x8, ("s46", "s47"), ""),
                               ("load", "v14", 0x4, ("s44", "s45"), " unorm slc"), ("load", "v15", 0x1, ("s46", "s47"), " unorm")),
     (1, 6, 7, 0),
     exported(texel(1, 6)[1], texel(7, 0)[3], texel(1, 6)[2], texel(7, 0)[0]),
     [exported(texel(1, 6)[0], texel(7, 0)[1], texel(1, 6)[2], texel(7, 0)[0])]),
    ("edge", image_load_body(("load", "v[12:13]", 0x3, ("s44", "s45"), " unorm"), ("load", "v[14:15]", 0x3, ("s46", "s47"), " unorm")),
     (7, 7, 8, 2),
     exported(*texel(7, 7)[:2], 0, 0),
     [exported(*texel(7, 7)[:2], *texel(7, 2)[:2]), exported(*texel(7, 7)[:2], *texel(0, 2)[:2])]),
    ("range", image_load_body(("load", "v[12:13]", 0x3, ("s44", "s45"), " unorm"), ("load", "v[14:15]", 0x3, ("s46", "s47"), " unorm")),
     (M32, 1, 3, 8),
     exported(0, 0, 0, 0),
     [exported(*texel(0, 1)[:2], *texel(3, 7)[:2]), exported(*texel(7, 1)[:2], *texel(3, 0)[:2])]),
    ("mip", image_load_body(("load_mip", "v[12:13]", 0x3, ("s44", "s45", "s46"), " unorm"),
                            ("load_mip", "v[14:15]", 0x3, ("s44", "s45", "s47"), " unorm")), (2, 5, 0, 1),
     exported(*texel(2, 5)[:2], 0, 0),
     [exported(*texel(2, 5)[:2], *texel(2, 5)[:2])]),
    ("info0", [*info_body((20, 0xb, "s44"), (23, 0x9, "s45")),
               ubyte(0, 12, "v20", "e32"), ubyte(0, 13, "v21", "e32"), ubyte(0, 14, "v22", "e32"), ubyte(0, 15, "v23", "e64")],
     (0, 1, 0, 0), [8.0, 8.0, 1.0, 0.0], [[8.0, 8.0, 1.0, 4.0], [8.0, 8.0, 0.0, 0.0], [8.0, 8.0, 4.0, 0.0]]),
    ("info1", [*info_body((20, 0xa, "s45"), (22, 0x8, "s44"), (23, 0x1, "s44")),
               ubyte(0, 12, "v20", "e32"), ubyte(0, 13, "v21", "e64"), ubyte(0, 14, "v22", "e32"), ubyte(0, 15, "v23", "e32")],
     (0, 1, 0, 0), [0.0, 1.0, 1.0, 8.0], [[4.0, 1.0, 1.0, 8.0], [0.0, 0.0, 1.0, 8.0], [0.0, 1.0, 4.0, 8.0]]),
    ("gather_r", image_gather_body("gather4_lz", 0x1), GATHER_WORDS,
     exported(GL, GR, GR, GL), [exported(GR, GL, GL, GR), exported(GT, GT, GB, GB), exported(RAMP[2], RAMP[2], RAMP[3], RAMP[3])]),
    ("gather_g", image_gather_body("gather4_lz", 0x2), GATHER_WORDS,
     exported(GB, GB, GT, GT), [exported(GT, GT, GB, GB), exported(GL, GR, GR, GL), exported(GB, GT, GT, GB)]),
    ("gather_a", image_gather_body("gather4_lz", 0x8), GATHER_WORDS,
     exported(255, 255, 255, 255), [exported(128, 128, 128, 128)]),
    ("gather_b", image_gather_body("gather4_lz", 0x4), GATHER_WORDS,
     exported(128, 128, 128, 128), [exported(255, 255, 255, 255)]),
)


# image_sample_lz and image_sample_b on the mip-chain fixture of the renderer's --check-pixel-case-mips: an 8x8 texture
# with all four levels, each with its own blue byte, drawn at 4x4 pixels so that the implicit level is exactly 1 (where the
# program's own image_sample reads). Level 0 is read in 2x2 blocks, so a level-0 read at those pixel centers, which lie on
# level-0 texel edges, has one value. References are per pixel. The wrong references are the plausible lowering bugs: an
# implicit-level sample for lz, an ignored, negated or partly dropped bias, swapped constant coordinates, the first N
# channels instead of the dmask channels, and a level-0 lz read taken from level 1.
MIP_BLUE = (128, 64, 219, 37)


def mip_texel(level, x, y):
    """Texel (x, y) of a level of the mip-chain fixture, as bytes (tests/pixel_aot_render.cpp builds the same)."""
    size = 8 >> level
    assert 0 <= x < size and 0 <= y < size
    if level == 0:
        x, y = x // 2, y // 2
    return (RAMP[(x + 2 * level) % 8], RAMP[(y + 5 * level) % 8], MIP_BLUE[level], 255)


def mip_at(level, u, v):
    """The point-sampled texel of a level at normalized (u, v) in [0, 1), clamp addressing; exact for the coordinates
    used here, which lie on no texel edge of a level other than 0 (where 2x2 blocks make edges inside a block moot)."""
    size = 8 >> level
    return mip_texel(level, min(int(u * size), size - 1), min(int(v * size), size - 1))


PIXEL_UV = [((2 * x + 1) / 8, (2 * y + 1) / 8) for y in range(4) for x in range(4)]  # the 4x4 draw's pixel centers


def per_pixel(*channels):
    """channels: functions of (u, v) giving one exported byte each; the four exported floats for every pixel."""
    return [exported(*(c(u, v) for c in channels)) for u, v in PIXEL_UV]


def at(level, channel):
    return lambda u, v: mip_at(level, u, v)[channel]


def fixed(level, x, y, channel):
    return lambda u, v: mip_at(level, x, y)[channel]


MIP_COORD = (5.5 / 8, 2.5 / 8)  # level-0 block (2, 1); swapped, block (1, 2)
MIP_PROGRAMS = (
    # The texture coordinate read at level 0: an implicit-level sample would read level 1.
    ("lz", ["image_sample_lz v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D", "s_waitcnt vmcnt(0)"],
     (0, 0, 0, 0),
     per_pixel(at(0, 0), at(0, 1), at(0, 2), at(0, 3)),
     [per_pixel(at(1, 0), at(1, 1), at(1, 2), at(1, 3))]),
    # A constant coordinate through an NSA address with two dmask channels, then the texture coordinate as an NSA list
    # with dmask 0x9 and cache modifiers.
    ("lz_nsa", ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45",
                "image_sample_lz v[12:13], [v18, v19], s[28:35], s[40:43] dmask:0x6 dim:SQ_RSRC_IMG_2D",
                "image_sample_lz v[14:15], [v8, v9], s[28:35], s[40:43] dmask:0x9 dim:SQ_RSRC_IMG_2D glc dlc",
                "s_waitcnt vmcnt(0)"],
     (float_bits(MIP_COORD[0]), float_bits(MIP_COORD[1]), 0, 0),
     per_pixel(fixed(0, *MIP_COORD, 1), fixed(0, *MIP_COORD, 2), at(0, 0), at(0, 3)),
     [per_pixel(fixed(0, *MIP_COORD[::-1], 1), fixed(0, *MIP_COORD[::-1], 2), at(0, 0), at(0, 3)),
      per_pixel(fixed(0, *MIP_COORD, 0), fixed(0, *MIP_COORD, 1), at(0, 0), at(0, 1)),
      per_pixel(fixed(0, *MIP_COORD, 1), fixed(0, *MIP_COORD, 2), at(1, 0), at(1, 3))]),
    # Bias +1 (level 2) and -1 (level 0) through NSA lists, and +10 (past the last level, so level 3) through a range
    # whose first VGPR is the bias and whose next two are the texture coordinate.
    ("bias", ["v_mov_b32_e32 v20, s44", "v_mov_b32_e32 v21, s45", "v_mov_b32_e32 v7, s46",
              "image_sample_b v12, [v20, v8, v9], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D",
              "image_sample_b v13, [v21, v8, v9], s[28:35], s[40:43] dmask:0x2 dim:SQ_RSRC_IMG_2D",
              "image_sample_b v[14:15], v[7:9], s[28:35], s[40:43] dmask:0x5 dim:SQ_RSRC_IMG_2D",
              "s_waitcnt vmcnt(0)"],
     (float_bits(1.0), float_bits(-1.0), float_bits(10.0), 0),
     per_pixel(at(2, 0), at(0, 1), at(3, 0), at(3, 2)),
     [per_pixel(at(1, 0), at(1, 1), at(1, 0), at(1, 2)),
      per_pixel(at(0, 0), at(2, 1), at(0, 0), at(0, 2)),
      per_pixel(at(2, 0), at(0, 1), at(3, 0), at(3, 1)),
      per_pixel(at(1, 0), at(0, 1), at(3, 0), at(3, 2))]),
)


def check_mip_draws(directory, compiler, renderer, backend):
    case = directory / "image_mips.case"
    for name, body, words, reference, bugs in MIP_PROGRAMS:
        source = directory / f"image_{name}.hlsl"
        shader = directory / f"image_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case-mips", shader, case]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        case.write_bytes(constants + b"".join(struct.pack("<4f", *pixel) for pixel in reference))
        subprocess.run(draw, check=True)
        for wrong in bugs:
            assert wrong != reference, (name, wrong)
            case.write_bytes(constants + b"".join(struct.pack("<4f", *pixel) for pixel in wrong))
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong mip-level image result escaped detection in {name}: {wrong}")


def check_mip_controls():
    lz = "image_sample_lz v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"
    bias = "image_sample_b v[12:15], [v20, v8, v9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"
    ready = ["v_mov_b32_e32 v20, s44", "v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45"]
    # The level-0 and biased samples lower to SampleLevel(..., 0) and SampleBias with the first address as the bias.
    source = translate(with_constants([lz, "s_waitcnt vmcnt(0)"]))
    assert "tex.SampleLevel(samp, float2(uv.x, uv.y), 0.0f)" in source, source
    source = translate(with_constants([*ready, bias, "s_waitcnt vmcnt(0)"]))
    assert "tex.SampleBias(samp, float2(uv.x, uv.y), asfloat(movw" in source, source
    for _, body, *_ in MIP_PROGRAMS:
        translate(with_constants(body))
    # Refused neighbours: the other sample variants (implicit level from derivatives with a computed coordinate,
    # comparisons, explicit level, offsets, clamps, gradients), unnormalized and 16-bit or partial-result forms,
    # other dimensions, a zero dmask, address and destination widths that disagree with the form, and an unloaded
    # T# or sampler.
    for line in (lz.replace("sample_lz", "sample_l"), lz.replace("sample_lz", "sample_c_lz"),
                 lz.replace("sample_lz", "sample_lz_o"), bias.replace("sample_b", "sample_b_cl"),
                 bias.replace("sample_b", "sample_c_b"), bias.replace("sample_b", "sample_b_o"),
                 lz.replace("sample_lz", "sample_d"), lz + " unorm", lz + " a16", lz + " d16", lz + " tfe", lz + " lwe",
                 lz + " r128", bias + " tfe", lz + " glc glc", lz.replace("IMG_2D", "IMG_2D_ARRAY"),
                 lz.replace("IMG_2D", "IMG_CUBE"), bias.replace("IMG_2D", "IMG_CUBE"), lz.replace("0xf", "0x0"),
                 lz.replace("v[12:15]", "v[12:14]"), lz.replace("v[8:9]", "v[8:10]"), lz.replace("v[8:9]", "[v8, v9, v20]"),
                 bias.replace("[v20, v8, v9]", "[v8, v9]"), bias.replace("[v20, v8, v9]", "v[8:9]"),
                 bias.replace("[v20, v8, v9]", "[v20, v18, v19]"), bias.replace("[v20, v8, v9]", "[v20, v9, v24]"),
                 lz.replace("s[28:35]", "s[36:43]"), lz.replace("s[40:43]", "s[44:47]"),
                 lz.replace("v[8:9]", "[v24, v25]"), "image_sample_lz v[12:15], v[8:9], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D"):
        must_reject(translate, with_constants([*ready, line, "s_waitcnt vmcnt(0)"]))
    # A result read before s_waitcnt vmcnt(0), a coordinate or bias read from a register under an outstanding sample,
    # and a destination that overlaps an outstanding sample.
    must_reject(translate, with_constants([lz, "v_mov_b32_e32 v18, v12", "s_waitcnt vmcnt(0)"]))
    must_reject(translate, with_constants([lz, lz.replace("v[8:9]", "[v12, v13]").replace("v[12:15]", "v[16:19]"),
                                           "s_waitcnt vmcnt(0)"]))
    must_reject(translate, with_constants([lz, bias.replace("v20", "v12").replace("v[12:15]", "v[16:19]"),
                                           "s_waitcnt vmcnt(0)"]))
    must_reject(translate, with_constants([lz, lz.replace("v[12:15]", "v[14:17]"), "s_waitcnt vmcnt(0)"]))


def check_image_draws(directory, compiler, renderer, backend):
    case = directory / "image.case"
    for name, body, words, reference, bugs in IMAGE_PROGRAMS:
        source = directory / f"image_{name}.hlsl"
        shader = directory / f"image_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        for x in reference:
            assert half_rtz(x) == x, x
        case.write_bytes(constants + struct.pack("<4f", *reference) * 64)
        subprocess.run(draw, check=True)
        for wrong in bugs:
            assert wrong != reference and all(half_rtz(x) == x for x in wrong), (name, wrong)
            case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong image result escaped detection in {name}: {wrong}")


def check_image_controls():
    load = ["image_load v[12:15], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm"]
    gather = "image_gather4_lz v[12:15], v[18:19], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D"
    ready = [move(18, "s44"), move(19, "s45")]
    # Direct3D loads, level queries and gathers; the helpers make out-of-range reads zero explicitly.
    source = translate(with_constants([*ready, *load, "s_waitcnt vmcnt(0)"]))
    assert "image_load2d(tex, " in source and "t.Load(int3(int(x), int(y), int(mip)))" in source, source
    assert "if (x >= w || y >= h) return float4(0.0f" in source and "if (mip >= levels)" in source, source
    source = translate(with_constants([*info_body((20, 0xb, "s44")), ubyte(0, 12, "v20", "e32")]))
    assert "image_resinfo2d(tex, " in source and "uint4(w, h, 0u, levels)" in source, source
    source = translate(with_constants([*ready, "image_gather4_lz v[12:15], v[18:19], s[28:35], s[40:43] dmask:0x4 dim:SQ_RSRC_IMG_2D",
                                       "s_waitcnt vmcnt(0)"]))
    assert "tex.GatherBlue(samp, float2(" in source, source
    # The implicit-level gather is refused: its level comes from derivatives, which Gather* does not reproduce.
    must_reject(translate, with_constants([*ready, gather.replace("gather4_lz", "gather4"), "s_waitcnt vmcnt(0)"]))
    # Two dmask bits on a gather, a zero dmask, and unsupported modifiers or dimensions are refused.
    for line in (gather.replace("0x1", "0x3"), gather.replace("0x1", "0x0"), gather.replace("0x1", "0x5"),
                 load[0].replace("0xf", "0x0"), load[0] + " a16", load[0] + " d16", load[0] + " tfe", load[0] + " lwe",
                 load[0].replace("IMG_2D", "IMG_2D_ARRAY"), load[0].replace("IMG_2D", "IMG_3D"), load[0] + " r128",
                 gather + " unorm", gather + " a16", gather.replace("IMG_2D", "IMG_2D_ARRAY"),
                 "image_get_resinfo v[12:14], v18, s[28:35] dmask:0x7 dim:SQ_RSRC_IMG_2D unorm",
                 "image_get_resinfo v12, v18, s[28:35] dmask:0x4 dim:SQ_RSRC_IMG_2D",
                 "image_load v[12:14], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 "image_load v[12:15], v[18:20], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 "image_load_mip v[12:15], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 "image_load v[12:15], v[18:19], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D unorm",
                 gather.replace("s[40:43]", "s[44:47]"), "image_gather4 v[12:15], v[18:19], s[28:35] dmask:0x1 dim:SQ_RSRC_IMG_2D"):
        must_reject(translate, with_constants([*ready, line, "s_waitcnt vmcnt(0)"]))
    # The image descriptor must be a loaded T#, and the coordinates must be set.
    must_reject(translate, with_constants([*ready, load[0].replace("s[28:35]", "s[36:43]"), "s_waitcnt vmcnt(0)"]))
    must_reject(translate, with_constants([*ready, load[0].replace("v[18:19]", "v[24:25]"), "s_waitcnt vmcnt(0)"]))
    # A load result read before s_waitcnt vmcnt(0), an integer word and a destination that overlaps an outstanding load.
    must_reject(translate, with_constants([*ready, *load]))
    must_reject(translate, with_constants([*ready, *load, ubyte(0, 12, "v12", "e32")]))
    must_reject(translate, with_constants([*info_body((20, 0xb, "s44"))[:-1], ubyte(0, 12, "v20", "e32")]))
    must_reject(translate, with_constants([*ready, *load, load[0].replace("v[12:15]", "v[14:17]")]))
    must_reject(translate, with_constants([*ready, gather, ubyte(0, 13, "v13", "e32")]))
    # A gather coordinate read from a register under an outstanding sample is refused as well.
    must_reject(translate, with_constants([*ready, *load, gather.replace("v[18:19]", "v[12:13]")]))


def controls(directory):
    check_image_controls()
    check_mip_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for _, body, *_ in IMAGE_PROGRAMS),
        *((with_constants(body), translate) for _, body, *_ in MIP_PROGRAMS),
    ]


def draw(directory, compiler, renderer, backend):
    check_image_draws(directory, compiler, renderer, backend)
    check_mip_draws(directory, compiler, renderer, backend)
