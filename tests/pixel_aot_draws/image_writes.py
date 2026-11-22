"""Draw family `image_writes`: pixel_aot_check.py draw --family image_writes.

image_store, image_store_mip and image_atomic_* from pixel shaders (tools/pixel_aot_ops/forms/image_writes.py). A case
carries storage images in the 'X2WI' part of its memory section (tests/pixel_aot_render.cpp): the harness binds each
image's levels as RWTexture2D UAVs at u(8 * slot + level), space2, through the T# the program loads from the descriptor
table, and after the single draw compares every texel word of every level with the Python reference below
(image_mismatch, exit 1). The draw, key and data words are those of the `stores` family (tests/pixel_aot_draws/
stores.py): 64x64 pixels, pixel (x, y) has key k = 64 * y + x and data d0..d3. Every write goes to a texel only its pixel
names, or outside the image, so the final images are exact; a "flaw" is a plausible wrong rule, each of which must
change the expected images and fail the draw.

Program 0 (stores). Slot 0, r32_uint 64x128: d0 at (x, y), the d16 store of d1 at (x, y + 64) and d3 at (x + 64, y),
which is outside the image. Slot 1, r32g32b32a32_uint 64x128: d0..d3 at (x, y) and the d16 store of d2, d3 (four
halves) at (x, y + 64). Slots 2 (r32_uint) and 3 (r32g32b32a32_uint), 64x64 with four levels: image_store_mip at level
m = y >> 4 and texel (x >> m | (x & (2^m - 1)) << 16, the same for y), so the pixels whose low m bits are zero own the
texel (x >> m, y >> m) of level m and the others write outside it; slot 2 takes d2 and slot 3 the d16 halves of d0, d1
(through an NSA address). Program 1 (atomics). Slot 0, r32_uint 256x256: pixel (x, y) owns the 4x4 block at (4x, 4y);
texel j of it (x + j % 4, y + j // 4) is the target of operation j of the atomics family's order with glc and its data
(d1 + K[j]; cmpswap compares with d0 ^ CMP_K), and texels 13 to 15 take xor, or and add without glc. The returned
values are stored at the same texels of slot 1. The initial texels are set per key so that cmpswap matches on even keys,
inc meets its wrap and dec its zero and above-data cases, as in the atomics family."""
import struct
import subprocess

import pixel_memory_check as titlemem

from .atomics import CMP_K, K, ORDER, apply, data_operand, operand, setup
from .common import M32, lower, must_reject
from .stores import C1, C2, COLOR, KEYS, VSHARP_OFFSETS, data, noise, program, refused_for

IMAGE_MAGIC = 0x49573258
OFFSETS = (0xc0, 0xe0, 0x100, 0x120)  # descriptor-table byte offsets of the storage-image T#s of slots 0 to 3
CONSTANTS = [0, 0, 0, C1, C2] + [0] * 59
R32, RGBA32 = "r32_uint", "r32g32b32a32_uint"
CHANNELS = {R32: 1, RGBA32: 4}


def translate_with(formats):
    """lower() with the storage images of slots 0.. bound at OFFSETS in the given formats."""
    images = {OFFSETS[slot]: (slot, fmt) for slot, fmt in enumerate(formats)}
    return lambda instructions: lower(instructions, 20, 24, [1, 2, 3, 4], constant_descriptor=64,
                                      buffer_descriptors=VSHARP_OFFSETS, storage_images=images)


def descriptors(count):
    return [*(f"s_load_dwordx8 s[{64 + 8 * n}:{71 + 8 * n}], s[20:21], {OFFSETS[n]:#x}" for n in range(count)),
            "s_waitcnt lgkmcnt(0)"]


def image(slot):
    return f"s[{64 + 8 * slot}:{71 + 8 * slot}]"


DIM = "dim:SQ_RSRC_IMG_2D"


class Image:
    """One storage image: every level as a list of texels, each a list of channel words."""

    def __init__(self, slot, fmt, width, height, levels):
        self.slot, self.channels, self.width, self.height = slot, CHANNELS[fmt], width, height
        self.levels = []
        base = 0
        for level in range(levels):
            w, h = max(1, width >> level), max(1, height >> level)
            self.levels.append([[noise(word + c, 17 + slot) for c in range(self.channels)]
                                for word in range(base, base + w * h * self.channels, self.channels)])
            base += w * h * self.channels

    def extent(self, level):
        return max(1, self.width >> level), max(1, self.height >> level)

    def store(self, level, x, y, words, wrap=False):
        if level >= len(self.levels):
            return
        w, h = self.extent(level)
        if wrap:
            x, y = x % w, y % h
        if x < w and y < h:
            self.levels[level][y * w + x] = [word & M32 for word in words]

    def load(self, x, y):
        return self.levels[0][y * self.width + x][0]

    def blob(self):
        return b"".join(struct.pack(f"<{self.channels}I", *texel) for level in self.levels for texel in level)


def section(initial, final):
    out = struct.pack("<3I", IMAGE_MAGIC, len(final), 0)
    for start, end in zip(initial, final):
        out += struct.pack("<5I", end.slot, end.channels, end.width, end.height, len(end.levels))
        out += start.blob() + end.blob()
    return titlemem.section([], [], trailing=out)


def halves(word, flaws):
    """The two 16-bit channels of a d16 data word, low half first, widened into 32-bit unsigned channels."""
    lo, hi = word & 0xffff, word >> 16
    if "d16_order" in flaws:
        lo, hi = hi, lo
    if "d16_sext" in flaws:
        lo, hi = (v | 0xffff0000 if v & 0x8000 else v for v in (lo, hi))
    if "d16_wide" in flaws:
        lo = hi = word
    return [lo, hi]


def mip_address(x, y):
    m = y >> 4
    low = (1 << m) - 1
    return (x >> m) | (x & low) << 16, (y >> m) | (y & low) << 16, m


STORE_FORMATS = (R32, RGBA32, R32, RGBA32)
STORE_BODY = [
    *descriptors(4),
    "v_mov_b32_e32 v26, v20", "v_add_nc_u32_e32 v27, 64, v21", "v_add_nc_u32_e32 v28, 64, v20", "v_mov_b32_e32 v29, v21",
    f"image_store v30, v[20:21], {image(0)} dmask:0x1 {DIM} unorm",
    f"image_store v31, v[26:27], {image(0)} dmask:0x1 {DIM} d16",
    f"image_store v33, v[28:29], {image(0)} dmask:0x1 {DIM}",
    f"image_store v[30:33], v[20:21], {image(1)} dmask:0xf {DIM} glc",
    f"image_store v[32:33], v[26:27], {image(1)} dmask:0xf {DIM} unorm slc d16",
    "v_lshrrev_b32_e32 v36, 4, v21", "v_lshlrev_b32_e64 v37, v36, 1", "v_subrev_nc_u32_e32 v37, 1, v37",
    "v_lshrrev_b32_e32 v38, v36, v20", "v_and_b32_e32 v41, v37, v20", "v_lshl_or_b32 v38, v41, 16, v38",
    "v_lshrrev_b32_e32 v39, v36, v21", "v_and_b32_e32 v41, v37, v21", "v_lshl_or_b32 v39, v41, 16, v39",
    "v_mov_b32_e32 v40, v36",
    f"image_store_mip v32, v[38:40], {image(2)} dmask:0x1 {DIM}",
    f"image_store_mip v[30:31], [v38, v39, v36], {image(3)} dmask:0xf {DIM} d16",
]


def store_images():
    return [Image(0, R32, 64, 128, 1), Image(1, RGBA32, 64, 128, 1), Image(2, R32, 64, 64, 4), Image(3, RGBA32, 64, 64, 4)]


def store_reference(flaws=()):
    images = store_images()
    wrap = "wrapped" in flaws
    for k in range(KEYS):
        x, y = k % 64, k // 64
        d = data(k)
        images[0].store(0, x, y, [d[0]], wrap)
        images[0].store(0, x, y + 64, halves(d[1], flaws)[:1], wrap)
        images[0].store(0, x + 64, y, [d[3]], wrap)
        images[1].store(0, x, y, list(reversed(d)) if "rgba_reversed" in flaws else list(d), wrap)
        images[1].store(0, x, y + 64, halves(d[2], flaws) + halves(d[3], flaws), wrap)
        mx, my, m = mip_address(x, y)
        level = 0 if "mip_ignored" in flaws else 3 - m if "mip_reversed" in flaws else m
        images[2].store(level, mx, my, [d[2]], wrap)
        images[3].store(level, mx, my, halves(d[0], flaws) + halves(d[1], flaws), wrap)
    return images


ATOMIC_FORMATS = (R32, R32)
COORDS = [f"v[{100 + 2 * j}:{101 + 2 * j}]" for j in range(16)]
ATOMIC_BODY = [
    *setup(),
    *descriptors(2),
    "v_lshlrev_b32_e32 v90, 2, v20", "v_lshlrev_b32_e32 v91, 2, v21",
    *(line for j in range(16) for line in (f"v_add_nc_u32_e32 v{100 + 2 * j}, {j % 4}, v90",
                                            f"v_add_nc_u32_e32 v{101 + 2 * j}, {j // 4}, v91")),
    *(f"image_atomic_{op} {data_operand(j)}, {COORDS[j]}, {image(0)} dmask:{'0x3' if op == 'cmpswap' else '0x1'} {DIM}"
      f"{' unorm' if j % 2 else ''} glc" for j, op in enumerate(ORDER)),
    f"image_atomic_xor v31, {COORDS[13]}, {image(0)} dmask:0x1 {DIM}",
    f"image_atomic_or v34, {COORDS[14]}, {image(0)} dmask:0x1 {DIM} slc",
    f"image_atomic_add v32, {COORDS[15]}, {image(0)} dmask:0x1 {DIM}",
    "s_waitcnt vmcnt(0)",
    *(f"image_store {operand(j)}, {COORDS[j]}, {image(1)} dmask:0x1 {DIM}" for j in range(len(ORDER))),
]


def atomic_operands(k):
    d0, d1, d2, _ = data(k)
    return d0, d1, d2, [(d1 + K[j]) & M32 for j in range(len(ORDER))], d0 ^ CMP_K


def atomic_images():
    images = [Image(0, R32, 256, 256, 1), Image(1, R32, 256, 256, 1)]
    for k in range(KEYS):
        x, y = 4 * (k % 64), 4 * (k // 64)
        _, _, _, values, cmp = atomic_operands(k)
        for j, op in enumerate(ORDER):
            value = values[j]
            if op == "cmpswap" and k % 2 == 0:
                start = cmp
            elif op == "inc":
                start = (value, (value - 1) & M32, value >> 3)[k % 3]
            elif op == "dec":
                start = (0, (value + 1 + (k & 0xff)) & M32 if value < M32 - 0x100 else 0, value)[k % 3]
            else:
                continue
            images[0].store(0, x + j % 4, y + j // 4, [start])
    return images


def atomic_reference(flaws=()):
    images = atomic_images()
    for k in range(KEYS):
        x, y = 4 * (k % 64), 4 * (k // 64)
        d0, d1, d2, values, cmp = atomic_operands(k)

        def atomic(op, j, value, compare=0):
            tx, ty = x + j % 4, y + j // 4
            old = images[0].load(tx, ty)
            new = apply(op, old, value, compare, flaws)
            images[0].store(0, tx, ty, [new])
            return new if "post" in flaws else old

        returns = [atomic(op, j, values[j], cmp) for j, op in enumerate(ORDER)]
        atomic("xor", 13, d1)
        atomic("or", 14, 1 << (k & 31))
        atomic("add", 15, d2)
        for j, value in enumerate(returns):
            images[1].store(0, x + j % 4, y + j // 4, [value])
    return images


# (formats, body, reference, flaws): every flaw must change the expected images and be rejected by the draw.
PROGRAMS = (
    (STORE_FORMATS, STORE_BODY, store_reference,
     ["wrapped", "d16_order", "d16_sext", "d16_wide", "rgba_reversed", "mip_ignored", "mip_reversed"]),
    (ATOMIC_FORMATS, ATOMIC_BODY, atomic_reference,
     ["post", "unsigned", "inc_gt", "dec_nozero", "cmp_swapped", "sub_rev"]),
)


def blobs(images):
    return [image.blob() for image in images]


def separated():
    for index, (_, _, reference, flaws) in enumerate(PROGRAMS):
        right = blobs(reference())
        for flaw in flaws:
            assert blobs(reference({flaw})) != right, (index, flaw)


def image_controls():
    for formats, body, _, _ in PROGRAMS:
        source = translate_with(formats)(program(*body))
        assert "RWTexture2D<uint> image0[8] : register(u0, space2);" in source, source
        assert "RWByteAddressBuffer" not in source and "title_memory" not in source
    assert "RWTexture2D<uint4> image3[8] : register(u24, space2);" in translate_with(STORE_FORMATS)(program(*STORE_BODY))
    separated()
    # The initial images already differ from the right final ones wherever a pixel writes.
    assert blobs(store_images()) != blobs(store_reference()) and blobs(atomic_images()) != blobs(atomic_reference())
    both = translate_with((R32, RGBA32))
    ready = descriptors(2)
    store = f"image_store v30, v[20:21], {image(0)} dmask:0x1 {DIM}"
    store4 = f"image_store v[30:33], v[20:21], {image(1)} dmask:0xf {DIM}"
    mip = f"image_store_mip v30, v[20:22], {image(0)} dmask:0x1 {DIM}"
    swap = f"image_atomic_swap v31, v[20:21], {image(0)} dmask:0x1 {DIM}"
    add_glc = f"image_atomic_add v31, v[20:21], {image(0)} dmask:0x1 {DIM} glc"
    for line in (store, store4, mip, swap, add_glc):
        both(program(*ready, line, "s_waitcnt vmcnt(0)"))
    # CF-2a: no image write while this lane may be inactive, nor in whole-quad mode, where helper lanes would write.
    narrowed = ["v_cmp_lt_f32_e64 s[80:81], v12, v13", "s_and_b64 exec, exec, s[80:81]"]
    for line in (store, store4, mip, swap, f"image_atomic_add v31, v[20:21], {image(0)} dmask:0x1 {DIM}"):
        refused_for("CF-2a", both, program(*ready, *narrowed, line))
    quad = ["s_mov_b32 s21, 0", "s_load_dwordx8 s[64:71], s[20:21], 0xc0", "s_waitcnt lgkmcnt(0)", "v_mov_b32_e32 v26, 0",
            "v_mov_b32_e32 v27, 0", f"image_atomic_add v26, v[26:27], {image(0)} dmask:0x1 {DIM}"]
    for after in (False, True):
        wqm = program()
        pos = wqm.index("s_and_b64 exec, exec, s[50:51]") + after
        wqm[pos:pos] = quad
        both(wqm) if after else refused_for("CF-2a", both, wqm)
    # A texel every lane shares: a store, the order-dependent atomics and any returned value are refused there, the
    # order-independent atomics without glc are not; one lane-varying coordinate (a row of texels) is not shared.
    uniform = ["v_mov_b32_e32 v26, 5", "v_mov_b32_e32 v27, s44", "v_mov_b32_e32 v28, 1"]
    for line in (f"image_store v30, v[26:27], {image(0)} dmask:0x1 {DIM}",
                 f"image_store v[30:33], v[26:27], {image(1)} dmask:0xf {DIM}",
                 f"image_store_mip v30, v[26:28], {image(0)} dmask:0x1 {DIM}",
                 *(f"image_atomic_{op} {reg}, v[26:27], {image(0)} dmask:{mask} {DIM}"
                   for op, reg, mask in (("swap", "v31", "0x1"), ("cmpswap", "v[64:65]", "0x3"), ("inc", "v31", "0x1"),
                                         ("dec", "v31", "0x1"))),
                 f"image_atomic_add v31, v[26:27], {image(0)} dmask:0x1 {DIM} glc"):
        refused_for("shares", both, program(*ready, *uniform, "v_mov_b32_e32 v64, v30", "v_mov_b32_e32 v65, v31", line,
                                            "s_waitcnt vmcnt(0)"))
    for op in ("add", "sub", "smin", "umin", "smax", "umax", "and", "or", "xor"):
        both(program(*ready, *uniform, f"image_atomic_{op} v31, v[26:27], {image(0)} dmask:0x1 {DIM}"))
    both(program(*ready, *uniform, "v_mov_b32_e32 v26, v20", f"image_store v30, v[26:27], {image(0)} dmask:0x1 {DIM}"))
    both(program(*ready, *uniform, "v_mov_b32_e32 v28, v21", f"image_store_mip v30, v[26:28], {image(0)} dmask:0x1 {DIM}"))
    # A quad broadcast is shared by the four lanes of a quad.
    refused_for("shares", both, program(*ready, "v_mov_b32_dpp v26, v20 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
                                        "v_mov_b32_dpp v27, v21 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
                                        f"image_store v30, v[26:27], {image(0)} dmask:0x1 {DIM}"))
    both(program(*ready, "v_mov_b32_dpp v26, v20 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
                 "v_mov_b32_dpp v27, v21 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
                 f"image_store v30, v[26:27], {image(0)} dmask:0x1 {DIM}"))
    # Float atomics, 64-bit atomics and atomics on a four-channel image.
    for op, reg, mask in (("fmin", "v31", "0x1"), ("fmax", "v31", "0x1"), ("fcmpswap", "v[64:65]", "0x3")):
        refused_for("not lowered", both, program(*ready, f"image_atomic_{op} {reg}, v[20:21], {image(0)} dmask:{mask} {DIM} glc"))
    refused_for("64-bit", both, program(*ready, f"image_atomic_add v[50:51], v[20:21], {image(0)} dmask:0x3 {DIM}"))
    refused_for("64-bit", both, program(*ready, f"image_atomic_cmpswap v[64:67], v[20:21], {image(0)} dmask:0xf {DIM}"))
    refused_for("one-channel", both, program(*ready, f"image_atomic_add v31, v[20:21], {image(1)} dmask:0x1 {DIM}"))
    # Formats whose texels are not the raw words.
    for fmt in ("r32_float", "r32g32b32a32_float", "r8g8b8a8_unorm", "r16_uint", "r32_sint", "r10g10b10a2_uint"):
        refused_for("not lowered exactly", translate_with((fmt,)), program(*descriptors(1), store))
        refused_for("not lowered exactly", translate_with((fmt,)),
                    program(*descriptors(1), f"image_atomic_add v31, v[20:21], {image(0)} dmask:0x1 {DIM}"))
    # The dmask must name every channel of the format.
    for line in (f"image_store v[30:33], v[20:21], {image(0)} dmask:0xf {DIM}",
                 f"image_store v30, v[20:21], {image(1)} dmask:0x1 {DIM}",
                 f"image_store v[30:32], v[20:21], {image(1)} dmask:0x7 {DIM}",
                 f"image_store v[30:31], v[20:21], {image(1)} dmask:0x7 {DIM} d16"):
        refused_for("dmask", both, program(*ready, line))
    for bad in (f"image_store v[30:31], v[20:21], {image(1)} dmask:0xf {DIM}",  # data width
                f"image_store v[30:33], v[20:21], {image(1)} dmask:0xf {DIM} d16",
                f"image_store v30, v20, {image(0)} dmask:0x1 {DIM}",
                f"image_store v30, v[20:22], {image(0)} dmask:0x1 {DIM}",
                f"image_store_mip v30, v[20:21], {image(0)} dmask:0x1 {DIM}",
                f"image_store v30, v[20:21], {image(0)} dmask:0x1 {DIM} tfe",
                f"image_store v30, v[20:21], {image(0)} dmask:0x1 {DIM} lwe",
                f"image_store v30, v[20:21], {image(0)} dmask:0x1 {DIM} glc glc",
                f"image_store v30, v[20:21], {image(0)} dmask:0x1 dim:SQ_RSRC_IMG_2D_ARRAY",
                f"image_store_pck v30, v[20:21], {image(0)} dmask:0x1 {DIM}",
                f"image_store_mip_pck v30, v[20:22], {image(0)} dmask:0x1 {DIM}",
                f"image_atomic_add v31, v[20:21], {image(0)} dmask:0x1 {DIM} d16",
                f"image_atomic_cmpswap v31, v[20:21], {image(0)} dmask:0x3 {DIM}",
                f"image_atomic_cmpswap v[64:65], v[20:21], {image(0)} dmask:0x1 {DIM}",
                f"image_atomic_csub v31, v[20:21], {image(0)} dmask:0x1 {DIM}",
                f"image_store v30, v[20:21], s[65:72] dmask:0x1 {DIM}",
                # A storage image is not a sampled texture, and the sampled texture is not a storage image.
                f"image_load v[40:43], v[20:21], {image(1)} dmask:0xf {DIM} unorm",
                "s_load_dwordx8 s[96:103], s[20:21], null\ns_waitcnt lgkmcnt(0)\n"
                f"image_store v30, v[20:21], s[96:103] dmask:0x1 {DIM}"):
        must_reject(both, program(*ready, *bad.split("\n")))
    must_reject(both, program(f"image_store v30, v[20:21], {image(0)} dmask:0x1 {DIM}"))  # T# load still pending/absent
    must_reject(both, program("s_load_dwordx8 s[64:71], s[20:21], 0xc0", store))  # before lgkmcnt(0)
    must_reject(translate_with((R32,)), program(*descriptors(2), store))  # no image at 0xe0
    # Data and returned values follow the load rules: not readable before vmcnt(0).
    must_reject(both, program(*ready, "buffer_load_dword v30, v22, s[52:55], 0 idxen", store))
    both(program(*ready, "buffer_load_dword v30, v22, s[52:55], 0 idxen", "s_waitcnt vmcnt(0)", store))
    must_reject(both, program(*ready, add_glc, "v_mov_b32_e32 v26, v31"))
    both(program(*ready, add_glc, "s_waitcnt vmcnt(0)", "v_mov_b32_e32 v26, v31"))
    # The binding contract: slots 0 to 3 at distinct, aligned offsets clear of every other descriptor.
    for images in ({0xc0: (4, R32)}, {0xc0: (0, R32), 0xe0: (0, R32)}, {0xd0: (0, R32)}, {0: (0, R32)},
                   {0x40: (0, R32)}, {0x80: (0, R32)}, {0xa0: (0, R32)}, {0xc0: 0}):
        must_reject(lambda p: lower(p, 20, 24, [1, 2, 3, 4], constant_descriptor=64, buffer_descriptors=VSHARP_OFFSETS,
                                    storage_images=images), program(*ready, store))


def controls(directory):
    image_controls()


def binary_fixtures():
    return [(program(*body), translate_with(formats)) for formats, body, _, _ in PROGRAMS]


def draw(directory, compiler, renderer, backend):
    case = directory / "image_writes.case"
    for index, (formats, body, reference, flaws) in enumerate(PROGRAMS):
        source, shader = directory / f"image_writes{index}.hlsl", directory / f"image_writes{index}.cso"
        source.write_text(translate_with(formats)(program(*body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        initial = store_images() if index == 0 else atomic_images()
        run = [renderer, backend, "--check-pixel-case", shader, case]
        case.write_bytes(titlemem.case_file(CONSTANTS, COLOR, section(initial, reference())))
        subprocess.run(run, check=True)
        for flaw in flaws:
            case.write_bytes(titlemem.case_file(CONSTANTS, COLOR, section(initial, reference({flaw}))))
            result = subprocess.run(run, capture_output=True, text=True)
            if result.returncode != 1 or "image_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong image_writes reference escaped detection in program {index}: {flaw}")
