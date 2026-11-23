"""Draw family `image`: pixel_aot_check.py draw --family image."""
import math
import struct
import subprocess

from .common import M32, RAMP, DrawBatch, f32, half_rtz, move, must_reject, translate, ubyte, with_constants


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


def image_gather_body(op, dmask, dest="v[12:15]", modifiers=""):
    return ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45",
            f"image_{op} {dest}, v[18:19], {SRC}, s[40:43] dmask:{dmask:#x} {IMG}{modifiers}", "s_waitcnt vmcnt(0)"]


def image_gather_offset_body(dmask):
    """image_gather4_lz_o: the packed offset word (constant s46) is the first address VGPR, then x and y."""
    return [move(17, "s46"), move(18, "s44"), move(19, "s45"),
            f"image_gather4_lz_o v[12:15], v[17:19], {SRC}, s[40:43] dmask:{dmask:#x} {IMG}", "s_waitcnt vmcnt(0)"]


def pack_offset(x, y):
    """The texel offset word of the offset MIMG forms: signed 6-bit x in bits 5:0 and y in bits 13:8."""
    assert -32 <= x < 32 and -32 <= y < 32
    return (x & 0x3f) | ((y & 0x3f) << 8)


def gather_ref(channel, column, row):
    """A gather result in D3D footprint order for the footprint whose top-left texel is (column, row): texels
    (-,+), (+,+), (+,-), (-,-), with clamp addressing."""
    clamp = lambda v: min(max(v, 0), 7)
    return [texel(clamp(c), clamp(r))[channel] for c, r in ((column, row + 1), (column + 1, row + 1), (column + 1, row), (column, row))]


def d16_unpack(*words):
    """Widen the half-packed words in v20, v21 (as many as given) to v12..v15 by v_cvt_f32_f16, low half first; the
    unused outputs are zeroed."""
    body = []
    for n, word in enumerate(words):
        body += [f"v_cvt_f32_f16_e32 v{12 + 2 * n}, v{word}", f"v_lshrrev_b32_e32 v{22 + n}, 16, v{word}",
                 f"v_cvt_f32_f16_e32 v{13 + 2 * n}, v{22 + n}"]
    for r in range(12 + 2 * len(words), 16):
        body.append(f"v_mov_b32_e32 v{r}, 0")
    return body


def d16_value(byte_value):
    """An unorm byte as a d16 result: binary32 k/255 narrowed to binary16 with round-to-nearest-even. The widened
    value is what the unpack exports (it is a binary16, so the compressed export keeps it)."""
    return struct.unpack("<e", struct.pack("<e", f32(byte_value / 255.0)))[0]


def d16_rtz(byte_value):
    """The same narrowed toward zero, the plausible wrong conversion."""
    return half_rtz(f32(byte_value / 255.0))


d16_exported = lambda *values: [d16_value(v) for v in values]
D16_UNPACK = d16_unpack(20, 21)


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
GATHER_COLUMN, GATHER_ROW = 2, 5  # the footprint's top-left texel at the gather coordinate


def gather_offset_case(name, dmask, offset):
    """image_gather4_lz_o at the gather coordinate moved by offset texels. The wrong references: no offset, the
    offset negated or with its axes swapped, and (at the right edge) wrapping instead of clamping."""
    channel = dmask.bit_length() - 1
    (ox, oy), (sx, sy) = offset, offset[::-1]
    footprint = lambda dx, dy: exported(*gather_ref(channel, GATHER_COLUMN + dx, GATHER_ROW + dy))
    wrong = [footprint(0, 0), footprint(-ox, -oy), footprint(sx, sy)]
    if GATHER_COLUMN + ox + 1 > 7:
        wrap = [texel(c % 8, r)[channel] for c, r in ((GATHER_COLUMN + ox, GATHER_ROW + oy + 1),
                (GATHER_COLUMN + ox + 1, GATHER_ROW + oy + 1), (GATHER_COLUMN + ox + 1, GATHER_ROW + oy),
                (GATHER_COLUMN + ox, GATHER_ROW + oy))]
        wrong.append(exported(*wrap))
    return (name, image_gather_offset_body(dmask), (*GATHER_WORDS[:2], pack_offset(*offset), 0),
            footprint(ox, oy), wrong)


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
    # Offset gathers: red moved by (+1, -2), green by (-3, +1) (its footprint's columns clamp to column 0), and red by
    # (+5, 0) (columns 7 and 8, which clamp to 7).
    gather_offset_case("gather_o_r", 0x1, (1, -2)),
    gather_offset_case("gather_o_g", 0x2, (-3, 1)),
    gather_offset_case("gather_o_edge", 0x1, (5, 0)),
    # d16: two binary16 channels per VGPR, the earlier one in the low half, narrowed from the unorm value to nearest
    # even. The wrong references: the halves swapped, one channel per VGPR (unpacked), and narrowing toward zero.
    ("d16_load", [*image_load_body(("load", "v[20:21]", 0xf, ("s44", "s45"), " unorm d16")), *d16_unpack(20, 21)], (2, 5, 0, 0),
     d16_exported(*texel(2, 5)),
     [d16_exported(texel(2, 5)[1], texel(2, 5)[0], texel(2, 5)[3], texel(2, 5)[2]),
      d16_exported(texel(2, 5)[0], 0, texel(2, 5)[1], 0), [d16_rtz(v) for v in texel(2, 5)]]),
    ("d16_pair", [*image_load_body(("load", "v20", 0xa, ("s44", "s45"), " glc d16")), *d16_unpack(20)], (6, 2, 0, 0),
     d16_exported(*pick(texel(6, 2), 0xa), 0, 0),
     [d16_exported(texel(6, 2)[3], texel(6, 2)[1], 0, 0), d16_exported(*pick(texel(6, 2), 0x5), 0, 0),
      [*[d16_rtz(v) for v in pick(texel(6, 2), 0xa)], 0.0, 0.0]]),
    ("d16_gather", [*image_gather_body("gather4_lz", 0x1, "v[20:21]", " d16"), *d16_unpack(20, 21)], GATHER_WORDS,
     d16_exported(GL, GR, GR, GL), [d16_exported(GR, GL, GL, GR), d16_exported(GL, GR, GL, GR), [d16_rtz(v) for v in (GL, GR, GR, GL)]]),
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


def per_pixel(*channels, convert=None):
    """channels: functions of (u, v) giving one exported byte each; the four exported floats for every pixel."""
    return [(convert or exported)(*(c(u, v) for c in channels)) for u, v in PIXEL_UV]


def mip_off(level, u, v, ox, oy):
    """The texel of a level at (u, v) moved by (ox, oy) texels of that level, clamp addressing. At level 0 the pixel
    centers lie on texel edges of 2x2 blocks, so the offsets used there are even (the move stays in whole blocks)."""
    size = 8 >> level
    clamp = lambda n: min(max(n, 0), size - 1)
    return mip_texel(level, clamp(int(u * size) + ox), clamp(int(v * size) + oy))


def off(level, ox, oy, channel):
    return lambda u, v: mip_off(level, u, v, ox, oy)[channel]


def off_fixed(level, ox, oy, channel, at=None):
    return lambda u, v: mip_off(level, *(at or MIP_COORD), ox, oy)[channel]


def off_scaled(level, ox, oy, channel, at=None):
    """The plausible wrong offset: the offset taken in texels of level 0 (moves the coordinate by ox/8, oy/8)."""
    size = 8 >> level
    clamp = lambda n: min(max(n, 0), size - 1)
    def value(u, v):
        u, v = at or (u, v)
        return mip_texel(level, clamp(math.floor((u + ox / 8) * size)), clamp(math.floor((v + oy / 8) * size)))[channel]
    return value


def at(level, channel):
    return lambda u, v: mip_at(level, u, v)[channel]


def fixed(level, x, y, channel):
    return lambda u, v: mip_at(level, x, y)[channel]


MIP_COORD = (5.5 / 8, 2.5 / 8)  # level-0 block (2, 1); swapped, block (1, 2)
const_texel = lambda level, x, y, channel: (lambda u, v: mip_texel(level, x, y)[channel])


def sample_line(op, dest, address, dmask, modifiers=""):
    return f"image_sample_{op} {dest}, {address}, s[28:35], s[40:43] dmask:{dmask:#x} dim:SQ_RSRC_IMG_2D{modifiers}"

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
    # Explicit levels. lod 2 and 10 (clamped to the last level, 3) and 0 on the texture coordinate, none of which is the
    # implicit level 1. The wrong references: the implicit level, the lod taken as a bias, and an unclamped lod.
    ("l", ["v_mov_b32_e32 v20, s44", "v_mov_b32_e32 v21, s45", "v_mov_b32_e32 v22, s46",
           sample_line("l", "v12", "[v8, v9, v20]", 0x1), sample_line("l", "v13", "[v8, v9, v21]", 0x2),
           sample_line("l", "v[14:15]", "[v8, v9, v22]", 0x5), "s_waitcnt vmcnt(0)"],
     (float_bits(2.0), 0, float_bits(10.0), 0),
     per_pixel(at(2, 0), at(0, 1), at(3, 0), at(3, 2)),
     [per_pixel(at(1, 0), at(1, 1), at(1, 0), at(1, 2)), per_pixel(at(3, 0), at(1, 1), at(3, 0), at(3, 2)),
      per_pixel(at(2, 0), at(0, 1), at(0, 0), at(0, 2)), per_pixel(at(2, 1), at(0, 0), at(3, 1), at(3, 3))]),
    # A constant coordinate, a negative lod (level 0), an NSA list and a range (v[24:26] holds x, y, lod).
    ("l_const", ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46", "v_mov_b32_e32 v21, s47",
                 "v_mov_b32_e32 v24, s44", "v_mov_b32_e32 v25, s45", "v_mov_b32_e32 v26, s47",
                 sample_line("l", "v12", "[v18, v19, v20]", 0x1), sample_line("l", "v13", "[v18, v19, v21]", 0x4),
                 sample_line("l", "v[14:15]", "v[24:26]", 0x3), "s_waitcnt vmcnt(0)"],
     (float_bits(MIP_COORD[0]), float_bits(MIP_COORD[1]), float_bits(-2.0), float_bits(2.0)),
     per_pixel(fixed(0, *MIP_COORD, 0), fixed(2, *MIP_COORD, 2), fixed(2, *MIP_COORD, 0), fixed(2, *MIP_COORD, 1)),
     [per_pixel(fixed(1, *MIP_COORD, 0), fixed(1, *MIP_COORD, 2), fixed(1, *MIP_COORD, 0), fixed(1, *MIP_COORD, 1)),
      per_pixel(fixed(2, *MIP_COORD, 0), fixed(2, *MIP_COORD, 2), fixed(2, *MIP_COORD, 0), fixed(2, *MIP_COORD, 1)),
      per_pixel(fixed(0, *MIP_COORD, 0), fixed(0, *MIP_COORD, 2), fixed(0, *MIP_COORD, 0), fixed(0, *MIP_COORD, 1)),
      per_pixel(fixed(0, *MIP_COORD[::-1], 0), fixed(2, *MIP_COORD[::-1], 2), fixed(2, *MIP_COORD[::-1], 0),
                fixed(2, *MIP_COORD[::-1], 1))]),
    # Offsets at level 0 (the first VGPR is the packed offset word; the pixel-coordinate read moves by an even offset so
    # that it stays in whole 2x2 blocks): (+1, +2) and (-2, +2) on a constant coordinate, (-2, +2) on the texture
    # coordinate, where the offset also clamps at the edges. The wrong references: no offset, every offset negated,
    # every offset with its axes swapped.
    ("lz_o", ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46", "v_mov_b32_e32 v21, s47",
              sample_line("lz_o", "v12", "[v20, v18, v19]", 0x1), sample_line("lz_o", "v13", "[v21, v18, v19]", 0x2),
              sample_line("lz_o", "v[14:15]", "[v21, v8, v9]", 0x5), "s_waitcnt vmcnt(0)"],
     (float_bits(MIP_COORD[0]), float_bits(MIP_COORD[1]), pack_offset(1, 2), pack_offset(-2, 2)),
     per_pixel(off_fixed(0, 1, 2, 0), off_fixed(0, -2, 2, 1), off(0, -2, 2, 0), off(0, -2, 2, 2)),
     [per_pixel(off_fixed(0, 0, 0, 0), off_fixed(0, 0, 0, 1), off(0, 0, 0, 0), off(0, 0, 0, 2)),
      per_pixel(off_fixed(0, -1, -2, 0), off_fixed(0, 2, -2, 1), off(0, 2, -2, 0), off(0, 2, -2, 2)),
      per_pixel(off_fixed(0, 2, 1, 0), off_fixed(0, 2, -2, 1), off(0, 2, -2, 0), off(0, 2, -2, 2))]),
    # Offset and explicit level: (+1, -1) at level 2, (-2, +1) at level 1 and (+2, -2) at level 0 (lod from inline
    # constants and zero), on the texture coordinate. The offset is in texels of the level read: the wrong references take it in
    # level-0 texels, drop it, or read the implicit level.
    ("l_o", ["v_mov_b32_e32 v20, s44", "v_mov_b32_e32 v21, s45", "v_mov_b32_e32 v22, s46", "v_mov_b32_e32 v26, 2.0",
             "v_mov_b32_e32 v27, 1.0", "v_mov_b32_e32 v28, 0",
             sample_line("l_o", "v12", "[v20, v8, v9, v26]", 0x1), sample_line("l_o", "v13", "[v21, v8, v9, v27]", 0x2),
             sample_line("l_o", "v[14:15]", "[v22, v8, v9, v28]", 0x5), "s_waitcnt vmcnt(0)"],
     (pack_offset(1, -1), pack_offset(-2, 1), pack_offset(2, -2), 0),
     per_pixel(off(2, 1, -1, 0), off(1, -2, 1, 1), off(0, 2, -2, 0), off(0, 2, -2, 2)),
     [per_pixel(off_scaled(2, 1, -1, 0), off_scaled(1, -2, 1, 1), off_scaled(0, 2, -2, 0), off_scaled(0, 2, -2, 2)),
      per_pixel(off(2, 0, 0, 0), off(1, 0, 0, 1), off(0, 0, 0, 0), off(0, 0, 0, 2)),
      per_pixel(off(1, 1, -1, 0), off(1, -2, 1, 1), off(1, 2, -2, 0), off(1, 2, -2, 2)),
      per_pixel(off(2, -1, 1, 0), off(1, 2, -1, 1), off(0, -2, 2, 0), off(0, -2, 2, 2)),
      per_pixel(off(2, -1, 1, 0), off(1, 1, -2, 1), off(0, -2, 2, 0), off(0, -2, 2, 2))]),
    # image_sample_o: the implicit level (exactly 1 at 4x4 pixels, read as the quad's derivatives give it) and an offset
    # in texels of that level: (+2, -2), (+3, +1) as a list and (-1, +3) through a range whose first VGPR is the offset.
    # The offsets clamp at the edges of the 4x4 level. The wrong references: no offset, every offset negated, the offsets
    # taken in level-0 texels (half as many level-1 texels), and level 0 read with the offset.
    ("o", ["v_mov_b32_e32 v20, s44", "v_mov_b32_e32 v21, s45", "v_mov_b32_e32 v7, s46",
           sample_line("o", "v12", "[v20, v8, v9]", 0x1), sample_line("o", "v13", "[v21, v8, v9]", 0x2),
           sample_line("o", "v[14:15]", "v[7:9]", 0x5), "s_waitcnt vmcnt(0)"],
     (pack_offset(2, -2), pack_offset(3, 1), pack_offset(-1, 3), 0),
     per_pixel(off(1, 2, -2, 0), off(1, 3, 1, 1), off(1, -1, 3, 0), off(1, -1, 3, 2)),
     [per_pixel(off(1, 0, 0, 0), off(1, 0, 0, 1), off(1, 0, 0, 0), off(1, 0, 0, 2)),
      per_pixel(off(1, -2, 2, 0), off(1, -3, -1, 1), off(1, 1, -3, 0), off(1, 1, -3, 2)),
      per_pixel(off_scaled(1, 2, -2, 0), off_scaled(1, 3, 1, 1), off_scaled(1, -1, 3, 0), off_scaled(1, -1, 3, 2)),
      per_pixel(off(0, 2, -2, 0), off(0, 3, 1, 1), off(0, -1, 3, 0), off(0, -1, 3, 2)),
      per_pixel(off(1, -2, 2, 0), off(1, 1, 3, 1), off(1, 3, -1, 0), off(1, 3, -1, 2))]),
    # Explicit gradients: each of the four gradient VGPRs alone sets the level (0.5 -> 2, 1.0 -> 3, 0.25 -> 1, 1.0 -> 3,
    # in units of the 8-texel base level). The wrong references: the implicit level, the second gradient dropped (levels
    # 0 for the two last samples), the first dropped.
    ("d", ["v_mov_b32_e32 v20, 0.5", "v_mov_b32_e32 v21, 1.0", "v_mov_b32_e32 v22, s44", "v_mov_b32_e32 v26, 0",
           sample_line("d", "v12", "[v20, v26, v26, v26, v8, v9]", 0x1), sample_line("d", "v13", "[v26, v21, v26, v26, v8, v9]", 0x2),
           sample_line("d", "v14", "[v26, v26, v22, v26, v8, v9]", 0x4), sample_line("d", "v15", "[v26, v26, v26, v21, v8, v9]", 0x1),
           "s_waitcnt vmcnt(0)"],
     (float_bits(0.25), 0, 0, 0),
     per_pixel(at(2, 0), at(3, 1), at(1, 2), at(3, 0)),
     [per_pixel(at(1, 0), at(1, 1), at(1, 2), at(1, 0)), per_pixel(at(2, 0), at(3, 1), at(0, 2), at(0, 0)),
      per_pixel(at(0, 0), at(0, 1), at(1, 2), at(3, 0))]),
    # A range of six registers (gradients, then x and y from constants), and zero gradients (the most detailed level).
    ("d_const", ["v_mov_b32_e32 v20, 0", "v_mov_b32_e32 v21, s46", "v_mov_b32_e32 v22, 0", "v_mov_b32_e32 v23, 0",
                 "v_mov_b32_e32 v24, s44", "v_mov_b32_e32 v25, s45", "v_mov_b32_e32 v26, 1.0",
                 sample_line("d", "v[12:13]", "v[20:25]", 0x3), sample_line("d", "v14", "[v20, v20, v26, v20, v24, v25]", 0x4),
                 sample_line("d", "v15", "[v20, v20, v20, v20, v24, v25]", 0x1), "s_waitcnt vmcnt(0)"],
     (float_bits(MIP_COORD[0]), float_bits(MIP_COORD[1]), float_bits(0.25), 0),
     per_pixel(fixed(1, *MIP_COORD, 0), fixed(1, *MIP_COORD, 1), fixed(3, *MIP_COORD, 2), fixed(0, *MIP_COORD, 0)),
     [per_pixel(fixed(1, *MIP_COORD[::-1], 0), fixed(1, *MIP_COORD[::-1], 1), fixed(3, *MIP_COORD[::-1], 2), fixed(0, *MIP_COORD[::-1], 0)),
      per_pixel(fixed(0, *MIP_COORD, 0), fixed(0, *MIP_COORD, 1), fixed(3, *MIP_COORD, 2), fixed(0, *MIP_COORD, 0)),
      per_pixel(fixed(1, *MIP_COORD, 0), fixed(1, *MIP_COORD, 1), fixed(1, *MIP_COORD, 2), fixed(1, *MIP_COORD, 0))]),
    # image_load_mip at levels that exist: x=1, y=0 at level 1, level 2, and (out of range, zero) level 3.
    ("load_mip", ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46",
                  "v_mov_b32_e32 v24, s44", "v_mov_b32_e32 v25, s45", "v_mov_b32_e32 v26, s47",
                  "v_mov_b32_e32 v28, s44", "v_mov_b32_e32 v29, s45", "v_mov_b32_e32 v30, 3",
                  "image_load_mip v[12:13], v[18:20], s[28:35] dmask:0x3 dim:SQ_RSRC_IMG_2D unorm",
                  "image_load_mip v14, v[24:26], s[28:35] dmask:0x4 dim:SQ_RSRC_IMG_2D unorm",
                  "image_load_mip v15, v[28:30], s[28:35] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm", "s_waitcnt vmcnt(0)"],
     (1, 0, 1, 2),
     per_pixel(const_texel(1, 1, 0, 0), const_texel(1, 1, 0, 1), const_texel(2, 1, 0, 2), lambda u, v: 0),
     [per_pixel(const_texel(0, 1, 0, 0), const_texel(0, 1, 0, 1), const_texel(0, 1, 0, 2), lambda u, v: 0),
      per_pixel(const_texel(1, 0, 1, 0), const_texel(1, 0, 1, 1), const_texel(2, 0, 1, 2), lambda u, v: 0),
      per_pixel(const_texel(1, 1, 0, 0), const_texel(1, 1, 0, 1), const_texel(2, 1, 0, 2), const_texel(3, 0, 0, 0)),
      per_pixel(const_texel(2, 1, 0, 0), const_texel(2, 1, 0, 1), const_texel(3, 0, 0, 2), lambda u, v: 0)]),
    # d16 on the mip fixture: an implicit-level sample, a biased one and an explicit-level pair beside a level-0 pair, each
    # unpacked to the four outputs. The wrong references: the halves swapped and the wrong level.
    ("d16_sample", ["image_sample v[20:21], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D d16", "s_waitcnt vmcnt(0)",
                    *D16_UNPACK],
     (0, 0, 0, 0),
     per_pixel(at(1, 0), at(1, 1), at(1, 2), at(1, 3), convert=d16_exported),
     [per_pixel(at(1, 1), at(1, 0), at(1, 3), at(1, 2), convert=d16_exported),
      per_pixel(at(0, 0), at(0, 1), at(0, 2), at(0, 3), convert=d16_exported),
      per_pixel(at(1, 0), at(1, 1), at(1, 2), at(1, 3), convert=lambda *v: [d16_rtz(b) for b in v])]),
    ("d16_levels", ["v_mov_b32_e32 v26, s44",
                    sample_line("b", "v[20:21]", "[v26, v8, v9]", 0xf, " d16"), "s_waitcnt vmcnt(0)", *D16_UNPACK],
     (float_bits(1.0), 0, 0, 0),
     per_pixel(at(2, 0), at(2, 1), at(2, 2), at(2, 3), convert=d16_exported),
     [per_pixel(at(1, 0), at(1, 1), at(1, 2), at(1, 3), convert=d16_exported),
      per_pixel(at(0, 0), at(0, 1), at(0, 2), at(0, 3), convert=d16_exported),
      per_pixel(at(2, 1), at(2, 0), at(2, 3), at(2, 2), convert=d16_exported)]),
    ("d16_pairs", ["v_mov_b32_e32 v26, 2.0",
                   sample_line("l", "v20", "[v8, v9, v26]", 0x6, " d16"), sample_line("lz", "v21", "[v8, v9]", 0x9, " glc d16"),
                   "s_waitcnt vmcnt(0)", *D16_UNPACK],
     (0, 0, 0, 0),
     per_pixel(at(2, 1), at(2, 2), at(0, 0), at(0, 3), convert=d16_exported),
     [per_pixel(at(2, 2), at(2, 1), at(0, 3), at(0, 0), convert=d16_exported),
      per_pixel(at(1, 1), at(1, 2), at(1, 0), at(1, 3), convert=d16_exported),
      per_pixel(at(2, 1), at(2, 2), at(2, 0), at(2, 3), convert=d16_exported)]),
)


PLAIN_SAMPLE = "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D"


def mip_program(body):
    """The common program around a body. A body that starts with an image_sample replaces the program's own sample (a
    program has exactly one implicit-level sample, so a d16 variant of it cannot be added beside it)."""
    if not body[0].startswith("image_sample "):
        return with_constants(body)
    program = with_constants(body[1:])
    program[program.index(PLAIN_SAMPLE)] = body[0]
    return program


def check_mip_draws(directory, compiler, renderer, backend):
    case = directory / "image_mips.case"
    for name, body, words, reference, bugs in MIP_PROGRAMS:
        source = directory / f"image_{name}.hlsl"
        shader = directory / f"image_{name}.cso"
        source.write_text(translate(mip_program(body)), encoding="ascii")
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
        translate(mip_program(body))
    # Refused neighbours: the other sample variants (implicit level from derivatives with a computed coordinate,
    # comparisons, explicit level, offsets, clamps, gradients), unnormalized and 16-bit or partial-result forms,
    # other dimensions, a zero dmask, address and destination widths that disagree with the form, and an unloaded
    # T# or sampler.
    for line in (lz.replace("sample_lz", "sample_c_lz"), bias.replace("sample_b", "sample_b_cl"),
                 bias.replace("sample_b", "sample_c_b"), lz + " unorm", lz + " a16", lz + " tfe", lz + " lwe",
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
    for name, body, words, reference, bugs in IMAGE_PROGRAMS:
        source = directory / f"image_{name}.hlsl"
        shader = directory / f"image_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        for x in reference:
            assert half_rtz(x) == x, x
        with DrawBatch(directory, renderer, backend, shader, "image") as batch:
            batch.add(constants + struct.pack("<4f", *reference) * 64, "pass", f"The image program {name} gives a result other than {reference}")
            for wrong in bugs:
                assert wrong != reference and all(half_rtz(x) == x for x in wrong), (name, wrong)
                batch.add(constants + struct.pack("<4f", *wrong) * 64, "mismatch", f"A wrong image result escaped detection in {name}: {wrong}")


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
                 load[0].replace("0xf", "0x0"), load[0] + " a16", load[0] + " tfe", load[0] + " lwe",
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


def check_offset_level_d16_controls():
    ready = [move(18, "s44"), move(19, "s45"), move(20, "s46"), move(21, "s47"), move(24, "s46"), move(25, "s44"), move(26, "s45")]
    wait = "s_waitcnt vmcnt(0)"
    smp = lambda op, dst, addr, dmask, modifiers="": sample_line(op, dst, addr, dmask, modifiers)
    # Accepted forms lower to the explicit-level, offset, gradient and half-packed calls, with the checked helpers.
    source = translate(with_constants([*ready, smp("l", "v[12:15]", "v[18:20]", 0xf), wait]))
    assert "tex.SampleLevel(samp, float2(" in source and "asfloat(" in source, source
    source = translate(with_constants([*ready, smp("lz_o", "v[12:15]", "v[18:20]", 0xf), wait]))
    assert "image_offset_uv(tex, float2(" in source and "float level" in source and "= 0.0f;" in source, source
    assert "asint(packed << 26u) >> 26" in source and "asint((packed >> 8u) << 26u) >> 26" in source, source
    source = translate(with_constants([*ready, smp("l_o", "v[12:15]", "v[18:21]", 0xf), wait]))
    assert "image_level(tex, " in source and "t.GetDimensions(uint(level)" in source, source
    # The implicit-level offset form: the level of the coordinate's derivatives (a helper-lane coordinate), then the offset.
    source = translate(with_constants([*ready, smp("o", "v[12:15]", "[v20, v8, v9]", 0xf), wait]))
    assert "CalculateLevelOfDetail(samp, float2(uv.x, uv.y))" in source and "image_offset_uv(tex, float2(" in source, source
    must_reject(translate, with_constants([*ready, smp("o", "v[12:15]", "[v20, v18, v19]", 0xf), wait]))  # not the interpolated uv
    must_reject(translate, with_constants([*ready, smp("o", "v[12:15]", "[v8, v9]", 0xf), wait]))
    source = translate(with_constants([*ready, smp("d", "v[12:15]", "[v18, v19, v20, v21, v8, v9]", 0xf), wait]))
    assert "tex.SampleGrad(samp, float2(uv.x, uv.y), float2(" in source, source
    source = translate(with_constants([*ready, smp("lz", "v[20:21]", "v[18:19]", 0xf, " d16"), wait]))
    assert "uint mem_d16_" in source and "narrow16(sample" in source and "<< 16u" in source, source
    source = translate(with_constants([*ready, "image_gather4_lz_o v[12:15], v[24:26], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D", wait]))
    assert "tex.GatherRed(samp, image_offset_uv(tex, float2(" in source, source
    # Refused neighbours. Offset forms whose level comes from derivatives (an offset needs the level's size), depth
    # comparisons (the sampler is not a comparison sampler), clamped and derivative variants, the offset and level
    # gathers other than lz_o (Gather always reads the most detailed level), and the other dimensions.
    d = "dmask:0xf dim:SQ_RSRC_IMG_2D"
    for op, regs, gathers in (("b_o", "v[18:21]", 0), ("d_o", "v[18:24]", 0), ("cl", "v[18:20]", 0),
                              ("b_cl", "v[18:21]", 0), ("c", "v[18:20]", 0), ("c_lz", "v[18:20]", 0), ("c_l", "v[18:21]", 0),
                              ("c_lz_o", "v[18:21]", 0), ("c_l_o", "v[18:22]", 0), ("c_o", "v[18:21]", 0), ("c_b", "v[18:21]", 0),
                              ("c_d", "v[18:24]", 0), ("cd", "v[18:23]", 0), ("d_cl", "v[18:24]", 0), ("d_g16", "v[18:21]", 0),
                              ("cl_o", "v[18:21]", 0)):
        must_reject(translate, with_constants([*ready, f"image_sample_{op} v[12:15], {regs}, s[28:35], s[40:43] {d}", wait]))
    for op, regs in (("", "v[18:19]"), ("_o", "v[18:20]"), ("_l", "v[18:20]"), ("_l_o", "v[18:21]"), ("_c", "v[18:20]"),
                     ("_c_lz", "v[18:20]"), ("_b", "v[18:20]"), ("_cl", "v[18:20]"), ("_c_o", "v[18:21]"),
                     ("_lz_o_x", "v[18:20]")):
        must_reject(translate, with_constants([*ready, f"image_gather4{op} v[12:15], {regs}, s[28:35], s[40:43] dmask:0x1 {IMG}", wait]))
    # Widths that disagree with the form, offset or level operands that were never set, and a d16 read of an odd channel
    # count (the high half of its last VGPR would be undefined), of the wrong number of VGPRs, or of a query.
    for line in (smp("l", "v[12:15]", "v[18:19]", 0xf), smp("l", "v[12:15]", "v[18:21]", 0xf), smp("lz_o", "v[12:15]", "v[18:19]", 0xf),
                 smp("l_o", "v[12:15]", "v[18:20]", 0xf), smp("d", "v[12:15]", "v[18:22]", 0xf),
                 smp("d", "v[12:15]", "[v18, v19, v20, v21, v8]", 0xf), smp("l", "v[12:15]", "v[27:29]", 0xf),
                 smp("l", "v[12:15]", "[v18, v19, v30]", 0xf), smp("lz_o", "v[12:15]", "[v30, v18, v19]", 0xf),
                 smp("d", "v[12:15]", "[v18, v19, v20, v21, v30, v9]", 0xf),
                 smp("lz", "v12", "v[18:19]", 0x1, " d16"), smp("lz", "v[12:13]", "v[18:19]", 0x7, " d16"),
                 smp("lz", "v[12:15]", "v[18:19]", 0xf, " d16"), smp("lz", "v[12:14]", "v[18:19]", 0xf, " d16"),
                 smp("l", "v12", "v[18:20]", 0x3, " d16 d16"), smp("d", "v12", "v[18:23]", 0x1, " d16"),
                 smp("lz_o", "v[12:13]", "v[18:20]", 0xf, " unorm d16"),
                 "image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D d16",
                 "image_sample v[12:13], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D",
                 "image_load v[12:14], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm d16",
                 "image_load v12, v[18:19], s[28:35] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm d16",
                 "image_load v[12:13], v[18:19], s[28:35] dmask:0xf dim:SQ_RSRC_IMG_2D unorm d16 d16",
                 "image_get_resinfo v12, v18, s[28:35] dmask:0x1 dim:SQ_RSRC_IMG_2D d16",
                 "image_gather4_lz v12, v[18:19], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D d16",
                 "image_gather4_lz_o v[12:15], v[24:26], s[28:35], s[40:43] dmask:0x3 dim:SQ_RSRC_IMG_2D",
                 "image_gather4_lz_o v[12:15], v[24:25], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D",
                 "image_gather4_lz_o v[12:15], v[24:26], s[28:35], s[40:43] dmask:0x1 dim:SQ_RSRC_IMG_2D unorm",
                 "image_gather4_lz_o v[12:15], v[24:26], s[28:35], s[44:47] dmask:0x1 dim:SQ_RSRC_IMG_2D"):
        must_reject(translate, with_constants([*ready, line, wait]))
    # An offset or level read from a register under an outstanding sample, a result read before the wait, and a d16 word
    # (a raw integer) read as a sample too early.
    first = smp("lz", "v[12:15]", "v[18:19]", 0xf)
    must_reject(translate, with_constants([*ready, first, smp("lz_o", "v[16:19]", "[v12, v18, v19]", 0xf), wait]))
    must_reject(translate, with_constants([*ready, first, smp("l", "v[16:19]", "[v18, v19, v12]", 0xf), wait]))
    must_reject(translate, with_constants([*ready, smp("lz", "v[20:21]", "v[18:19]", 0xf, " d16"), "v_mov_b32_e32 v12, v20", wait]))
    must_reject(translate, with_constants([*ready, smp("lz", "v[20:21]", "v[18:19]", 0xf, " d16"), "v_cvt_f32_f16_e32 v12, v20", wait]))
    # The references: every program has 16 pixels (or one color) of four channels, and every wrong reference differs.
    for name, body, words, reference, bugs in MIP_PROGRAMS:
        assert len(reference) == 16 and all(len(pixel) == 4 for pixel in reference), name
        assert bugs and all(len(wrong) == 16 and wrong != reference for wrong in bugs), name
    for name, body, words, reference, bugs in IMAGE_PROGRAMS:
        assert len(reference) == 4 and bugs and all(len(wrong) == 4 and wrong != reference for wrong in bugs), name
    # Offsets and levels in the references move to a different texel or level than the unoffset or implicit read.
    for level, ox, oy in ((0, 1, 2), (0, -2, 2), (1, -2, 1), (2, 1, -1)):
        assert any(mip_off(level, u, v, ox, oy) != mip_off(level, u, v, 0, 0) for u, v in PIXEL_UV), (level, ox, oy)
    assert any(mip_at(2, u, v) != mip_at(1, u, v) for u, v in PIXEL_UV)


def controls(directory):
    check_image_controls()
    check_mip_controls()
    check_offset_level_d16_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for _, body, *_ in IMAGE_PROGRAMS),
        *((mip_program(body), translate) for _, body, *_ in MIP_PROGRAMS),
    ]


def draw(directory, compiler, renderer, backend):
    check_image_draws(directory, compiler, renderer, backend)
    check_mip_draws(directory, compiler, renderer, backend)
