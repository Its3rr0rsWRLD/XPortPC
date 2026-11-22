"""Draw family `dpp`: pixel_aot_check.py draw --family dpp.

Quad-local DPP16 (quad_perm) and DPP8 (dpp8) VOP1 and VOP2 instructions (from R0Y00/Xbox2Windows#408, #414, #419,
#421 and #423 by KomaGuy): binary32 arithmetic, moves and selects (#408), 32-bit integer, bitwise, shift and bit-scan
operations (#414), binary16 operations (#419), conversions (#421), and extra binary32 operations with carry-in adds
(#423). Each fixture derives the quad lane of every pixel from the interpolated coordinate, folds the operations
into the four exported channels, and compares them with a reference for several constant sets. Each draw also
mutates the program (a different permutation, a swapped neighbour operation, a dropped source modifier) and requires
the draw to fail on the mutant, so a swizzle that reads the wrong lane cannot pass. The controls (no GPU) hold the
refusals: every DPP control that is not quad-local, a partial row or bank mask, source modifiers where the encoding
has none, scalar and constant sources, a lane that may be inactive, whole-quad mode, and a source read before its
load completed. DPP results are cross-lane reads of uint words (tools/pixel_aot_ops/quad.py).

needs bounded-m0 tracking in the scalar forms).
"""
import math
import struct
import subprocess

from .common import assembly, half_rtz, must_reject, single, translate, with_constants

# Quad-local DPP16 (quad_perm) and DPP8 (dpp8) fixture covering all 20 supported VOP1/VOP2 DPP forms.
# Derives per-quad lane ID {0, 1, 2, 3} from interpolated uv.x (v8) and uv.y (v9) so every 2x2 quad
# carries 4 distinct values across all 4,096 pixels while exporting uniform exact binary16 results.
DPP_BODY = [
    "v_subrev_f32_dpp v18, v8, v8 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_subrev_f32_dpp v19, v9, v9 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_mul_f32_e32 v18, 0x42800000, v18",
    "v_fma_f32 v20, 0x43000000, v19, v18",
    "v_sub_f32_dpp v21, v20, v20 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_add_f32_dpp v21, |v21|, |v21| quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_sub_f32_dpp v22, v20, v20 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_max_f32_dpp v22, |v22|, v22 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_add_f32_dpp v23, v20, v20 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_dpp v24, v20 dpp8:[1,2,3,0,5,6,7,4]",
    "v_sub_f32_e32 v25, v24, v20",
    "v_add_f32_e32 v26, 4.0, v25",
    "v_cmp_gt_f32_e32 vcc_lo, 0, v25",
    "v_cndmask_b32_dpp v27, v25, v26, vcc_lo quad_perm:[1,2,0,3] row_mask:0xf bank_mask:0xf",
    "v_add_f32_e32 v12, v21, v22",
    "v_add_f32_e32 v12, v12, v23",
    "v_add_f32_e32 v12, v12, v27",
    "v_add_f32_e32 v12, s44, v12",
    "v_mov_b32_e32 v28, s45",
    "v_mov_b32_e32 v29, s46",
    "v_mov_b32_e32 v30, s47",
    "v_mul_f32_dpp v31, v20, v28 quad_perm:[3,3,3,3] row_mask:0xf bank_mask:0xf",
    "v_mul_legacy_f32_dpp v32, v20, v28 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_min_f32_dpp v33, -v31, v30 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_dpp v34, -|v29| quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_e32 v13, v32",
    "v_fmac_f32_dpp v13, v33, v34 dpp8:[1,0,3,2,5,4,7,6]",
    "v_add_f32_e32 v35, s44, v30",
    "v_floor_f32_dpp v36, v35 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_ceil_f32_dpp v37, v35 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_trunc_f32_dpp v38, v35 dpp8:[3,2,1,0,7,6,5,4]",
    "v_fract_f32_dpp v39, v35 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_fma_f32 v14, 2.0, v37, v36",
    "v_fma_f32 v14, 4.0, v38, v14",
    "v_add_f32_e32 v14, v14, v39",
    "v_log_f32_dpp v40, v28 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_exp_f32_dpp v41, v40 dpp8:[2,3,0,1,6,7,4,5]",
    "v_rcp_f32_dpp v42, v41 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_sqrt_f32_dpp v43, v28 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_rsq_f32_dpp v44, v28 dpp8:[3,2,1,0,7,6,5,4]",
    "v_add_f32_e32 v15, v40, v41",
    "v_fma_f32 v15, 0x41800000, v42, v15",
    "v_add_f32_e32 v15, v15, v43",
    "v_fma_f32 v15, 4.0, v44, v15",
    "v_add_f32_e32 v15, 0.5, v15",
    "v_floor_f32_e32 v15, v15",
]

DPP_SETS = (
    # (a: f32, b: power-of-2 f32, h_bits: packed f16 in low half, c: f32)
    (0.25, 4.0, 0x4000, 1.5),
    (-2.25, 16.0, 0xbe00, 0.5),
)


def dpp_reference(a, b, h_bits, c):
    h = struct.unpack("<e", struct.pack("<H", h_bits & 0xffff))[0]
    ch0 = 8.0 + a
    ch1 = 3.0 * b * abs(h)
    x = a + c
    ch2 = math.floor(x) + 2.0 * math.ceil(x) + 4.0 * math.trunc(x) + (x - math.floor(x))
    log_b = math.log2(b)
    ch3 = math.floor(log_b + (2.0 ** log_b) + 16.0 / (2.0 ** log_b) + math.sqrt(b) + 4.0 / math.sqrt(b) + 0.5)
    return (half_rtz(ch0), half_rtz(ch1), half_rtz(ch2), half_rtz(ch3))


def check_dpp_draw(directory, compiler, renderer, backend):
    program = with_constants(DPP_BODY)
    source = directory / "dpp.hlsl"
    shader = directory / "dpp.cso"
    case = directory / "dpp.case"
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    for a, b, h_bits, c in DPP_SETS:
        constants = bytearray(256)
        struct.pack_into("<2fIf", constants, 12, a, b, h_bits, c)
        expected = dpp_reference(a, b, h_bits, c)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
    for set_idx, old, new, label in (
        (0, "v_sub_f32_dpp v21, v20, v20 quad_perm:[1,0,3,2]",
         "v_sub_f32_dpp v21, v20, v20 quad_perm:[2,3,0,1]", "AcrossX vs AcrossY"),
        (0, "v_sub_f32_dpp v22, v20, v20 quad_perm:[2,3,0,1]",
         "v_sub_f32_dpp v22, v20, v20 quad_perm:[1,0,3,2]", "AcrossY vs AcrossX"),
        (0, "dpp8:[1,2,3,0,5,6,7,4]", "dpp8:[3,0,1,2,7,4,5,6]", "cyclic dpp8 rotation"),
        (0, "v_mul_f32_dpp v31, v20, v28 quad_perm:[3,3,3,3]",
         "v_mul_f32_dpp v31, v20, v28 quad_perm:[1,1,1,1]", "lane broadcast"),
        (0, "v_min_f32_dpp v33, -v31, v30", "v_min_f32_dpp v33, v31, v30", "DPP16 neg modifier"),
        (1, "v_floor_f32_dpp v36, v35", "v_ceil_f32_dpp v36, v35", "floor vs ceil DPP"),
    ):
        a, b, h_bits, c = DPP_SETS[set_idx]
        constants = bytearray(256)
        struct.pack_into("<2fIf", constants, 12, a, b, h_bits, c)
        expected = dpp_reference(a, b, h_bits, c)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


# Quad-local DPP16 and DPP8 integer/bitwise/shift/bit-scan fixture covering 23 VOP1/VOP2 DPP forms.
# Derives integer quad lane ID {0, 1, 2, 3} from interpolated uv.x/uv.y (v8/v9), verifies quad
# swizzles across lanes, folds all 23 ops into a 32-bit accumulator, and exports all 4 bytes as
# exact [0, 255] integers.
DPP_INT32_BODY = [
    "v_mov_b32_e32 v17, 0",
    "v_or_b32_dpp v18, v8, v17 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_or_b32_dpp v19, v9, v17 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_or_b32_dpp v20, v8, v17 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_or_b32_dpp v21, v9, v17 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_sub_f32_e32 v18, v20, v18",
    "v_sub_f32_e32 v19, v21, v19",
    "v_mul_f32_e32 v18, 0x42800000, v18",
    "v_mul_f32_e32 v19, 0x43000000, v19",
    "v_add_f32_e32 v20, v18, v19",
    "v_add_f32_e32 v20, 0x4b000000, v20",
    "v_mov_b32_e32 v17, 3",
    "v_and_b32_dpp v20, v20, v17 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_sub_nc_u32_dpp v21, v20, v20 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_mul_i32_i24_dpp v21, v21, v21 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_subrev_nc_u32_dpp v22, v20, v20 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_mul_i32_i24_dpp v22, v22, v22 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v23, v20, v20 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_sub_nc_u32_dpp v24, v20, v20 dpp8:[1,2,3,0,5,6,7,4]",
    "v_and_b32_dpp v24, v24, v17 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_e32 v25, s44",
    "v_mov_b32_e32 v26, s45",
    "v_mov_b32_e32 v27, s46",
    "v_mov_b32_e32 v28, s47",
    "v_min_i32_dpp v29, v25, v26 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_max_i32_dpp v30, v25, v26 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_min_u32_dpp v31, v25, v26 dpp8:[3,2,1,0,7,6,5,4]",
    "v_max_u32_dpp v32, v25, v26 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_mul_u32_u24_dpp v33, v25, v26 dpp8:[1,0,3,2,5,4,7,6]",
    "v_mul_hi_u32_u24_dpp v34, v25, v26 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_mul_hi_i32_i24_dpp v35, v25, v26 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v36, v29, v30 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_xnor_b32_dpp v37, v31, v32 dpp8:[2,3,0,1,6,7,4,5]",
    "v_not_b32_dpp v38, v27 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_lshlrev_b32_dpp v39, v28, v25 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_lshrrev_b32_dpp v40, v28, v26 dpp8:[1,0,3,2,5,4,7,6]",
    "v_ashrrev_i32_dpp v41, v28, v25 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_bfrev_b32_dpp v42, v27 dpp8:[3,2,1,0,7,6,5,4]",
    "v_ffbl_b32_dpp v43, v27 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_ffbh_u32_dpp v44, v27 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_ffbh_i32_dpp v45, v25 dpp8:[2,3,0,1,6,7,4,5]",
    "v_add_nc_u32_dpp v30, v21, v22 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v23 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v24 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v30, v30, v33 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v34 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v30, v30, v35 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v36 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v30, v30, v37 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v38 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v30, v30, v39 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v40 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v30, v30, v41 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v42 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v30, v30, v43 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_nc_u32_dpp v30, v30, v44 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_xor_b32_dpp v30, v30, v45 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_e32 v46, 0xff",
    "v_mov_b32_e32 v47, 8",
    "v_mov_b32_e32 v48, 16",
    "v_mov_b32_e32 v49, 24",
    "v_and_b32_dpp v50, v30, v46 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_lshrrev_b32_dpp v51, v47, v30 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_and_b32_dpp v51, v51, v46 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_lshrrev_b32_dpp v52, v48, v30 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_and_b32_dpp v52, v52, v46 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_lshrrev_b32_dpp v53, v49, v30 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v12, v50",
    "v_mul_f32_e32 v12, 0x4b800000, v12",
    "v_cvt_f32_f16_e32 v13, v51",
    "v_mul_f32_e32 v13, 0x4b800000, v13",
    "v_cvt_f32_f16_e32 v14, v52",
    "v_mul_f32_e32 v14, 0x4b800000, v14",
    "v_cvt_f32_f16_e32 v15, v53",
    "v_mul_f32_e32 v15, 0x4b800000, v15",
]

DPP_INT32_SETS = (
    # Set 1: negative i24/i32 in s44, positive in s45, mixed bits in s46, shift >= 32 (37 -> 5).
    (0xff801234, 0x007f5678, 0x00108040, 37),
    # Set 2: extreme i24 (-2^23 * 2^23-1), zero input for ffbl/ffbh (-1), all-ones sign for ffbh_i32.
    (0xffffffff, 0x007fffff, 0x00000000, 13),
    # Set 3: negative * negative i24 (-2^23 * -2^23 -> +0x4000 high), MSB=1 for ffbh_u32=0.
    (0x00800000, 0x00800000, 0x80000001, 31),
)


def dpp_int32_reference(a, b, c, shift):
    m32 = 0xffffffff

    def i32(x):
        x &= m32
        return x - 0x100000000 if x & 0x80000000 else x

    def i24(x):
        x &= 0xffffff
        return x - 0x1000000 if x & 0x800000 else x

    def ffbl(x):
        x &= m32
        return m32 if x == 0 else (x & -x).bit_length() - 1

    def ffbh_u(x):
        x &= m32
        return m32 if x == 0 else 32 - x.bit_length()

    def ffbh_i(x):
        x &= m32
        m = (~x & m32) if (x & 0x80000000) else x
        return m32 if m == 0 else 32 - m.bit_length()

    s = shift & 31
    v21, v22, v23, v24 = 1, 4, 3, 1
    v29 = min(i32(a), i32(b)) & m32
    v30_max = max(i32(a), i32(b)) & m32
    v31 = min(a & m32, b & m32)
    v32 = max(a & m32, b & m32)
    v33 = ((a & 0xffffff) * (b & 0xffffff)) & m32
    v34 = (((a & 0xffffff) * (b & 0xffffff)) >> 32) & m32
    v35 = ((i24(a) * i24(b)) >> 32) & m32
    v36 = (v29 ^ v30_max) & m32
    v37 = (~(v31 ^ v32)) & m32
    v38 = (~c) & m32
    v39 = ((a & m32) << s) & m32
    v40 = (b & m32) >> s
    v41 = (i32(a) >> s) & m32
    v42 = int(f"{c & m32:032b}"[::-1], 2)
    v43 = ffbl(c)
    v44 = ffbh_u(c)
    v45 = ffbh_i(a)

    acc = (v21 + v22 + v23 + v24) & m32
    acc = (acc ^ v33) & m32
    acc = (acc + v34) & m32
    acc = (acc ^ v35) & m32
    acc = (acc + v36) & m32
    acc = (acc ^ v37) & m32
    acc = (acc + v38) & m32
    acc = (acc ^ v39) & m32
    acc = (acc + v40) & m32
    acc = (acc ^ v41) & m32
    acc = (acc + v42) & m32
    acc = (acc ^ v43) & m32
    acc = (acc + v44) & m32
    acc = (acc ^ v45) & m32
    return tuple(float((acc >> (8 * k)) & 0xff) for k in range(4))


def check_dpp_int32_draw(directory, compiler, renderer, backend):
    program = with_constants(DPP_INT32_BODY)
    source = directory / "dpp_int32.hlsl"
    shader = directory / "dpp_int32.cso"
    case = directory / "dpp_int32.case"
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    for values in DPP_INT32_SETS:
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = dpp_int32_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
    for set_idx, old, new, label in (
        (0, "v_sub_nc_u32_dpp v21, v20, v20 quad_perm:[1,0,3,2]",
         "v_sub_nc_u32_dpp v21, v20, v20 quad_perm:[2,3,0,1]", "AcrossX vs AcrossY"),
        (0, "dpp8:[1,2,3,0,5,6,7,4]", "dpp8:[3,0,1,2,7,4,5,6]", "cyclic dpp8 rotation"),
        (0, "v_ashrrev_i32_dpp v41, v28, v25", "v_lshrrev_b32_dpp v41, v28, v25", "ashrrev vs lshrrev"),
        (0, "v_mul_hi_i32_i24_dpp v35", "v_mul_hi_u32_u24_dpp v35", "mul_hi signed vs unsigned"),
        (0, "v_ffbh_i32_dpp v45, v25", "v_ffbh_u32_dpp v45, v25", "ffbh signed vs unsigned"),
    ):
        values = DPP_INT32_SETS[set_idx]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = dpp_int32_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


def f16_word(value, high=0):
    lo = struct.unpack("<H", struct.pack("<e", value))[0]
    return lo | ((high & 0xffff) << 16)


# Quad-local DPP16 and DPP8 binary16 fixture covering all 23 f16 VOP1/VOP2 DPP forms
# (including v_cvt_f16_f32_dpp, arithmetic, rounding, trig/transcendentals, frexp and ldexp).
DPP_F16_BODY = [
    "v_mov_b32_e32 v18, 0",
    "v_mov_b32_e32 v19, 0",
    "v_mov_b32_e32 v20, 0",
    "v_mov_b32_e32 v21, 0",
    "v_mov_b32_e32 v22, 0",
    "v_mov_b32_e32 v23, 0",
    "v_mov_b32_e32 v24, 0",
    "v_mov_b32_e32 v25, 0",
    "v_mov_b32_e32 v26, 0",
    "v_mov_b32_e32 v48, 6",
    "v_mov_b32_e32 v49, 7",
    "v_cvt_f16_f32_dpp v18, v8 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_cvt_f16_f32_dpp v20, v8 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_sub_f16_dpp v18, v20, v18 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f16_f32_dpp v19, v9 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_cvt_f16_f32_dpp v21, v9 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_subrev_f16_dpp v19, v19, v21 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_ldexp_f16_dpp v18, v18, v48 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_ldexp_f16_dpp v19, v19, v49 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_f16_dpp v20, v18, v19 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_sub_f16_dpp v22, v20, v20 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_mul_f16_dpp v22, |v22|, |v22| quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_sub_f16_dpp v23, v20, v20 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_max_f16_dpp v23, |v23|, v23 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_add_f16_dpp v24, v20, v20 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_sub_f16_dpp v25, v20, v20 dpp8:[1,2,3,0,5,6,7,4]",
    "v_min_f16_dpp v26, v25, v25 quad_perm:[3,3,3,3] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_e32 v27, v24",
    "v_mov_b32_e32 v28, s44",
    "v_add_f16_dpp v27, v27, -v26 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_f16_dpp v27, v27, v28 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v12, v27",
    "v_mov_b32_e32 v29, s45",
    "v_mov_b32_e32 v30, s46",
    "v_mov_b32_e32 v31, s47",
    "v_mov_b32_e32 v32, 0",
    "v_mov_b32_e32 v33, 0",
    "v_mov_b32_e32 v34, 0",
    "v_mov_b32_e32 v35, 0",
    "v_mov_b32_e32 v36, 0",
    "v_floor_f16_dpp v32, v31 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_ceil_f16_dpp v33, v31 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_trunc_f16_dpp v34, v31 dpp8:[3,2,1,0,7,6,5,4]",
    "v_rndne_f16_dpp v35, v31 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_fract_f16_dpp v36, v31 dpp8:[1,0,3,2,5,4,7,6]",
    "v_cvt_f32_f16_e32 v32, v32",
    "v_cvt_f32_f16_e32 v33, v33",
    "v_cvt_f32_f16_e32 v34, v34",
    "v_cvt_f32_f16_e32 v35, v35",
    "v_cvt_f32_f16_e32 v36, v36",
    "v_fma_f32 v13, 2.0, v33, v32",
    "v_fma_f32 v13, 4.0, v34, v13",
    "v_fma_f32 v13, 0x41000000, v35, v13",
    "v_add_f32_e32 v13, v13, v36",
    "v_mov_b32_e32 v37, 0",
    "v_mov_b32_e32 v38, 0",
    "v_mov_b32_e32 v39, 0",
    "v_mov_b32_e32 v40, 0",
    "v_mov_b32_e32 v41, 0",
    "v_mov_b32_e32 v42, 0",
    "v_mov_b32_e32 v43, 0",
    "v_log_f16_dpp v37, v29 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_exp_f16_dpp v38, v37 dpp8:[2,3,0,1,6,7,4,5]",
    "v_rcp_f16_dpp v39, v38 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_sqrt_f16_dpp v40, v29 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_rsq_f16_dpp v41, v29 dpp8:[3,2,1,0,7,6,5,4]",
    "v_sin_f16_dpp v42, v30 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cos_f16_dpp v43, v30 dpp8:[2,3,0,1,6,7,4,5]",
    "v_cvt_f32_f16_e32 v37, v37",
    "v_cvt_f32_f16_e32 v38, v38",
    "v_cvt_f32_f16_e32 v39, v39",
    "v_cvt_f32_f16_e32 v40, v40",
    "v_cvt_f32_f16_e32 v41, v41",
    "v_cvt_f32_f16_e32 v42, v42",
    "v_cvt_f32_f16_e32 v43, v43",
    "v_add_f32_e32 v14, v37, v38",
    "v_fma_f32 v14, 0x41800000, v39, v14",
    "v_add_f32_e32 v14, v14, v40",
    "v_fma_f32 v14, 4.0, v41, v14",
    "v_add_f32_e32 v14, v14, v42",
    "v_fma_f32 v14, 2.0, v43, v14",
    "v_mov_b32_e32 v44, 0",
    "v_mov_b32_e32 v45, 0",
    "v_mov_b32_e32 v46, 0",
    "v_frexp_mant_f16_dpp v44, v31 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_frexp_exp_i16_f16_dpp v45, v31 dpp8:[1,0,3,2,5,4,7,6]",
    "v_ldexp_f16_dpp v46, v44, v45 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v44, v44",
    "v_cvt_f32_f16_e32 v46, v46",
    "v_add_f32_e32 v15, v44, v46",
]

DPP_F16_SETS = (
    # (a_f16, b_pow2_f16, turns_f16, c_f16) — high 16 bits hold junk to verify low-half reads.
    (f16_word(1.5, 0xbeef), f16_word(4.0, 0xcafe), f16_word(0.0, 0x1234), f16_word(2.5, 0x5678)),
    (f16_word(-1.75, 0xdead), f16_word(16.0, 0xface), f16_word(0.25, 0x4321), f16_word(-1.5, 0x8765)),
)


def dpp_f16_reference(a_w, b_w, t_w, c_w):
    def f16(w):
        return struct.unpack("<e", struct.pack("<H", w & 0xffff))[0]

    a, b, t, c = f16(a_w), f16(b_w), f16(t_w), f16(c_w)
    ch0 = 8.0 + a
    ch1 = math.floor(c) + 2.0 * math.ceil(c) + 4.0 * math.trunc(c) + 8.0 * round(c) + (c - math.floor(c))
    log_b = math.log2(b)
    sin_t = 1.0 if t == 0.25 else 0.0
    cos_t = 0.0 if t == 0.25 else 1.0
    ch2 = log_b + (2.0 ** log_b) + 16.0 / (2.0 ** log_b) + math.sqrt(b) + 4.0 / math.sqrt(b) + sin_t + 2.0 * cos_t
    mant, exp = math.frexp(c)
    ch3 = mant + math.ldexp(mant, exp)
    return (half_rtz(ch0), half_rtz(ch1), half_rtz(ch2), half_rtz(ch3))


def check_dpp_f16_draw(directory, compiler, renderer, backend):
    program = with_constants(DPP_F16_BODY)
    source = directory / "dpp_f16.hlsl"
    shader = directory / "dpp_f16.cso"
    case = directory / "dpp_f16.case"
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    for values in DPP_F16_SETS:
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = dpp_f16_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
    for set_idx, old, new, label in (
        (0, "v_sub_f16_dpp v22, v20, v20 quad_perm:[1,0,3,2]",
         "v_sub_f16_dpp v22, v20, v20 quad_perm:[2,3,0,1]", "AcrossX vs AcrossY"),
        (0, "dpp8:[1,2,3,0,5,6,7,4]", "dpp8:[3,0,1,2,7,4,5,6]", "cyclic dpp8 rotation"),
        (0, "v_rndne_f16_dpp v35, v31", "v_ceil_f16_dpp v35, v31", "rndne tie-to-even"),
        (1, "v_sin_f16_dpp v42, v30", "v_cos_f16_dpp v42, v30", "sin vs cos turns"),
        (0, "v_add_f16_dpp v27, v27, -v26", "v_add_f16_dpp v27, v27, v26", "DPP16 neg modifier"),
    ):
        values = DPP_F16_SETS[set_idx]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = dpp_f16_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


# Quad-local DPP16 and DPP8 conversion fixture covering all 19 conversion VOP1/VOP2 DPP forms.
DPP_CVT_BODY = [
    "v_cvt_pkrtz_f16_f32_dpp v18, v8, v8 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v18, v18",
    "v_cvt_pkrtz_f16_f32_dpp v20, v8, v8 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v20, v20",
    "v_sub_f32_e32 v18, v20, v18",
    "v_cvt_pkrtz_f16_f32_dpp v19, v9, v9 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v19, v19",
    "v_cvt_pkrtz_f16_f32_dpp v21, v9, v9 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v21, v21",
    "v_sub_f32_e32 v19, v21, v19",
    "v_mul_f32_e32 v18, 0x42800000, v18",
    "v_fma_f32 v20, 0x43000000, v19, v18",
    "v_cvt_i32_f32_dpp v21, v20 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_i32_dpp v21, v21 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_sub_f32_e32 v21, v21, v20",
    "v_add_f32_e64 v21, |v21|, 0",
    "v_cvt_u32_f32_dpp v22, v20 dpp8:[1,2,3,0,5,6,7,4]",
    "v_cvt_f32_u32_dpp v22, v22 quad_perm:[3,3,3,3] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_e32 v28, s44",
    "v_cvt_flr_i32_f32_dpp v23, v28 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_i32_dpp v23, v23 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_rpi_i32_f32_dpp v24, v28 dpp8:[2,3,0,1,6,7,4,5]",
    "v_cvt_f32_i32_dpp v24, v24 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_f32_e32 v12, v21, v22",
    "v_add_f32_e32 v12, v12, v23",
    "v_fma_f32 v12, 2.0, v24, v12",
    "v_mov_b32_e32 v29, s45",
    "v_cvt_f32_ubyte0_dpp v25, v29 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_ubyte1_dpp v26, v29 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_ubyte2_dpp v27, v29 dpp8:[3,2,1,0,7,6,5,4]",
    "v_cvt_f32_ubyte3_dpp v30, v29 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_cvt_off_f32_i4_dpp v31, v29 dpp8:[1,0,3,2,5,4,7,6]",
    "v_fma_f32 v13, 2.0, v26, v25",
    "v_fma_f32 v13, 4.0, v27, v13",
    "v_fma_f32 v13, 0x41000000, v30, v13",
    "v_fma_f32 v13, 0x41800000, v31, v13",
    "v_mov_b32_e32 v39, s46",
    "v_mov_b32_e32 v40, s47",
    "v_mov_b32_e32 v32, 0",
    "v_mov_b32_e32 v33, 0",
    "v_mov_b32_e32 v34, 0",
    "v_mov_b32_e32 v35, 0",
    "v_mov_b32_e32 v36, 0",
    "v_mov_b32_e32 v37, 0",
    "v_mov_b32_e32 v38, 0",
    "v_cvt_f16_i16_dpp v32, v39 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_i16_f16_dpp v33, -v32 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_cvt_u16_f16_dpp v34, |v32| quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_cvt_f16_u16_dpp v35, v34 dpp8:[2,3,0,1,6,7,4,5]",
    "v_cvt_norm_i16_f16_dpp v36, v40 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_norm_u16_f16_dpp v37, v40 dpp8:[3,2,1,0,7,6,5,4]",
    "v_cvt_f32_f16_e32 v42, v32",
    "v_cvt_f32_f16_e32 v43, v35",
    "v_cvt_f32_ubyte0_dpp v44, v33 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_ubyte1_dpp v45, v36 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_ubyte1_dpp v46, v37 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_add_f32_e32 v14, v42, v43",
    "v_add_f32_e32 v14, v14, v44",
    "v_add_f32_e32 v14, v14, v45",
    "v_add_f32_e32 v14, v14, v46",
    "v_sat_pk_u8_i16_dpp v38, v29 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_ubyte0_dpp v47, v38 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_ubyte1_dpp v48, v38 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_cvt_pkrtz_f16_f32_dpp v41, v28, v20 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v49, v41",
    "v_add_f32_e32 v15, v47, v48",
    "v_add_f32_e32 v15, v15, v49",
]

DPP_CVT_SETS = (
    # (a_f32, packed_bytes_and_i16s, i16_val, f16_norm_val)
    (1.5, 0xfffe007a, 0x0000fffb, 0x3800),     # a=1.5, i16=(122,-2), i16=-5, f16=0.5
    (-1.5, 0x0200ff80, 0x0000000e, 0xb800),    # a=-1.5, i16=(-128,512), i16=14, f16=-0.5
)


def dpp_cvt_reference(a, w_bytes, i16_w, f16_w):
    def sext(v, bits):
        v &= (1 << bits) - 1
        return v - (1 << bits) if v & (1 << (bits - 1)) else v

    flr = math.floor(a)
    rpi = math.floor(a + 0.5)
    ch0 = 1.0 + 0.0 + flr + 2.0 * rpi

    b0, b1, b2, b3 = ((w_bytes >> (8 * k)) & 0xff for k in range(4))
    off = sext(w_bytes, 4) * 0.0625
    ch1 = b0 + 2.0 * b1 + 4.0 * b2 + 8.0 * b3 + 16.0 * off

    s16 = sext(i16_w, 16)
    v32 = float(s16)
    v33_b0 = (-s16) & 0xff
    v35 = float(abs(s16))
    f16_v = struct.unpack("<e", struct.pack("<H", f16_w & 0xffff))[0]
    norm_i16 = int(round(max(-1.0, min(1.0, f16_v)) * 32767.0)) & 0xffff
    norm_u16 = int(round(max(0.0, min(1.0, f16_v)) * 65535.0)) & 0xffff
    ch2 = v32 + v35 + v33_b0 + ((norm_i16 >> 8) & 0xff) + ((norm_u16 >> 8) & 0xff)

    sat_lo = max(0, min(255, sext(w_bytes, 16)))
    sat_hi = max(0, min(255, sext(w_bytes >> 16, 16)))
    ch3 = sat_lo + sat_hi + half_rtz(a)
    return (half_rtz(ch0), half_rtz(ch1), half_rtz(ch2), half_rtz(ch3))


def check_dpp_cvt_draw(directory, compiler, renderer, backend):
    program = with_constants(DPP_CVT_BODY)
    source = directory / "dpp_cvt.hlsl"
    shader = directory / "dpp_cvt.cso"
    case = directory / "dpp_cvt.case"
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    for a, w_bytes, i16_w, f16_w in DPP_CVT_SETS:
        constants = bytearray(256)
        struct.pack_into("<f3I", constants, 12, a, w_bytes, i16_w, f16_w)
        expected = dpp_cvt_reference(a, w_bytes, i16_w, f16_w)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
    for set_idx, old, new, label in (
        (0, "v_cvt_i32_f32_dpp v21, v20 quad_perm:[1,0,3,2]",
         "v_cvt_i32_f32_dpp v21, v20 quad_perm:[2,3,0,1]", "AcrossX vs AcrossY"),
        (0, "dpp8:[1,2,3,0,5,6,7,4]", "dpp8:[3,0,1,2,7,4,5,6]", "cyclic dpp8 rotation"),
        (0, "v_cvt_rpi_i32_f32_dpp v24, v28", "v_cvt_flr_i32_f32_dpp v24, v28", "rpi vs flr"),
        (0, "v_cvt_norm_i16_f16_dpp v36, v40", "v_cvt_norm_u16_f16_dpp v36, v40", "norm i16 vs u16"),
        (0, "v_cvt_i16_f16_dpp v33, -v32", "v_cvt_i16_f16_dpp v33, v32", "DPP16 neg modifier"),
    ):
        a, w_bytes, i16_w, f16_w = DPP_CVT_SETS[set_idx]
        constants = bytearray(256)
        struct.pack_into("<f3I", constants, 12, a, w_bytes, i16_w, f16_w)
        expected = dpp_cvt_reference(a, w_bytes, i16_w, f16_w)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


# Quad-local DPP16/DPP8 extra f32 (rndne, sin, cos, rcp_iflag, frexp_mant, frexp_exp, mac) and
# carry-in/carry-out u32 (add/sub/subrev_co_ci) fixture on gfx1013. Derives 4-lane quad ID {0,1,2,3}
# from uv.x/uv.y (64x64 RT), exercises non-symmetric quad swizzles and carry/borrow boundaries, and
# broadcasts lane 0 at the end of each channel so every pixel in a quad matches the texel reference.
DPP_EXTRA_SETS = (
    (1.5, 0.25, 4.0, 1.0),
    (2.5, -0.25, 8.0, 2.0),
)
DPP_EXTRA_BODY = [
    # Derive qx (v22), qy (v23), and quad lane id (v20 = qx + 2*qy in {0, 1, 2, 3}) from uv.x/uv.y.
    "v_mov_b32_e32 v20, 0",
    "v_mov_b32_e32 v21, 0",
    "v_mov_b32_e32 v22, 0x42800000",
    "v_mac_f32_dpp v20, v8, v22 quad_perm:[0,1,2,3] row_mask:0xf bank_mask:0xf",
    "v_mac_f32_dpp v21, v9, v22 dpp8:[0,1,2,3,4,5,6,7]",
    "v_floor_f32_e32 v22, v20",
    "v_mul_f32_e32 v24, 0.5, v22",
    "v_floor_f32_e32 v24, v24",
    "v_sub_f32_e32 v22, v22, v24",
    "v_sub_f32_e32 v22, v22, v24",
    "v_floor_f32_e32 v23, v21",
    "v_mul_f32_e32 v24, 0.5, v23",
    "v_floor_f32_e32 v24, v24",
    "v_sub_f32_e32 v23, v23, v24",
    "v_sub_f32_e32 v23, v23, v24",
    "v_fma_f32 v20, 2.0, v23, v22",
    # Channel R (v12): v_rndne_f32_dpp (half-integer ties), v_rcp_iflag_f32_dpp (powers of 2), v_mac_f32_dpp.
    "v_add_f32_e32 v21, s44, v20",
    "v_rndne_f32_dpp v24, -v21 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_exp_f32_e32 v25, v20",
    "v_rcp_iflag_f32_dpp v26, |v25| quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_rcp_iflag_f32_dpp v26, v26 dpp8:[1,2,3,0,5,6,7,4]",
    "v_mov_b32_e32 v27, s46",
    "v_mac_f32_dpp v27, -v24, v26 quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_mac_f32_dpp v27, v27, v25 dpp8:[1,2,3,0,5,6,7,4]",
    "v_rndne_f32_dpp v12, v27 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    # Channel G (v13): v_sin_f32_dpp (exact quarter turns) and v_cos_f32_dpp (exact half turns).
    "v_sub_f32_e32 v26, v22, v23",
    "v_mul_f32_e32 v26, s45, v26",
    "v_sin_f32_dpp v27, -v26 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_sin_f32_dpp v28, v26 dpp8:[2,3,0,1,6,7,4,5]",
    "v_mul_f32_e32 v29, 0.5, v22",
    "v_cos_f32_dpp v30, |v29| quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cos_f32_dpp v31, v29 dpp8:[2,3,0,1,6,7,4,5]",
    "v_fma_f32 v31, 2.0, v30, v31",
    "v_fma_f32 v31, 4.0, v28, v31",
    "v_fma_f32 v31, 0x41000000, v27, v31",
    "v_rndne_f32_dpp v13, v31 dpp8:[0,0,0,0,4,4,4,4]",
    # Channel B (v14): v_frexp_mant_f32_dpp & v_frexp_exp_i32_f32_dpp, biasing signed exp via v_add_co_ci_u32_dpp.
    "v_add_f32_e32 v32, 1.0, v20",
    "v_mul_f32_e32 v32, 0x3ec00000, v32",
    "v_mul_f32_e32 v32, s47, v32",
    "v_frexp_mant_f32_dpp v33, -v32 quad_perm:[2,3,0,1] row_mask:0xf bank_mask:0xf",
    "v_frexp_exp_i32_f32_dpp v34, v32 dpp8:[1,0,3,2,5,4,7,6]",
    "v_cmp_f_f32_e32 vcc_lo, v12, v12",
    "v_mov_b32_e32 v35, 0x200",
    "v_add_co_ci_u32_dpp v34, vcc_lo, v34, v35, vcc_lo quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    "v_cvt_f32_f16_e32 v35, v34",
    "v_mul_f32_e32 v35, 0x4b800000, v35",
    "v_fma_f32 v33, 0x41800000, v33, v35",
    "v_rndne_f32_dpp v14, v33 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
    # Channel A (v15): chained v_add_co_ci_u32_dpp / v_sub_co_ci_u32_dpp / v_subrev_co_ci_u32_dpp carry & borrow.
    "v_mov_b32_e32 v36, -2",
    "v_mov_b32_e32 v37, 1",
    "v_add_co_ci_u32_dpp v38, vcc_lo, v36, v37, vcc_lo dpp8:[1,0,3,2,5,4,7,6]",
    "v_mov_b32_e32 v39, 10",
    "v_sub_co_ci_u32_dpp v40, vcc_lo, v38, v39, vcc_lo quad_perm:[1,2,3,0] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_e32 v41, -12",
    "v_subrev_co_ci_u32_dpp v42, vcc_lo, v40, v41, vcc_lo quad_perm:[3,2,1,0] row_mask:0xf bank_mask:0xf",
    "v_mov_b32_e32 v43, 20",
    "v_subrev_co_ci_u32_dpp v44, vcc_lo, v42, v43, vcc_lo dpp8:[0,1,2,3,4,5,6,7]",
    "v_sub_co_ci_u32_dpp v45, vcc_lo, v44, v43, vcc_lo dpp8:[0,1,2,3,4,5,6,7]",
    "v_mov_b32_e32 v46, 0x42c80000",
    "v_mov_b32_e32 v47, 0x43480000",
    "v_cndmask_b32_e32 v46, v46, v47, vcc_lo",
    "v_cvt_f32_f16_e32 v44, v44",
    "v_mul_f32_e32 v44, 0x4b800000, v44",
    "v_add_f32_e32 v46, v46, v44",
    "v_rndne_f32_dpp v15, v46 quad_perm:[0,0,0,0] row_mask:0xf bank_mask:0xf",
]


def dpp_extra_reference(c0, c1, c2, c3):
    """Independent 4-lane quad reference for DPP_EXTRA_BODY."""
    m32 = 0xffffffff
    qx = [0.0, 1.0, 0.0, 1.0]
    qy = [0.0, 0.0, 1.0, 1.0]
    lane = [0.0, 1.0, 2.0, 3.0]
    perm = lambda arr, p: [arr[i] for i in p]
    # R: rndne, rcp_iflag, mac
    v21 = [c0 + l for l in lane]
    v24 = [float(round(-x)) for x in perm(v21, (1, 0, 3, 2))]
    v25 = [2.0 ** l for l in lane]
    v26 = [1.0 / abs(x) for x in perm(v25, (2, 3, 0, 1))]
    v26 = [1.0 / x for x in perm(v26, (1, 2, 3, 0))]
    v27 = [(-a) * b + c2 for a, b in zip(perm(v24, (3, 2, 1, 0)), v26)]
    v27 = [a * b + c for a, b, c in zip(perm(v27, (1, 2, 3, 0)), v25, v27)]
    r = float(round(v27[0]))
    # G: sin, cos (exact quarter/half turns)
    v26 = [c1 * (x - y) for x, y in zip(qx, qy)]
    v27 = [round(math.sin((-x) * 2.0 * math.pi)) for x in perm(v26, (1, 0, 3, 2))]
    v28 = [round(math.sin(x * 2.0 * math.pi)) for x in perm(v26, (2, 3, 0, 1))]
    v29 = [0.5 * x for x in qx]
    v30 = [round(math.cos(abs(x) * 2.0 * math.pi)) for x in perm(v29, (1, 0, 3, 2))]
    v31 = [round(math.cos(x * 2.0 * math.pi)) for x in perm(v29, (2, 3, 0, 1))]
    g = float(8.0 * v27[0] + 4.0 * v28[0] + 2.0 * v30[0] + v31[0])
    # B: frexp_mant, frexp_exp + add_co_ci
    v32 = [c3 * 0.375 * (1.0 + l) for l in lane]
    v33 = [math.frexp(-x)[0] for x in perm(v32, (2, 3, 0, 1))]
    v34 = [math.frexp(x)[1] & m32 for x in perm(v32, (1, 0, 3, 2))]
    vcc = [0, 0, 0, 0]
    add_res, new_vcc = [], []
    for a, ci in zip(perm(v34, (1, 0, 3, 2)), vcc):
        s = a + 512 + ci
        add_res.append(s & m32)
        new_vcc.append(1 if s > m32 else 0)
    v34, vcc = add_res, new_vcc
    b = 16.0 * v33[0] + float(v34[0] & 0x3ff)
    # A: add_co_ci, sub_co_ci, subrev_co_ci chain
    v38, new_vcc = [], []
    for a, ci in zip([0xfffffffe] * 4, vcc):
        s = a + 1 + ci
        v38.append(s & m32)
        new_vcc.append(1 if s > m32 else 0)
    vcc = new_vcc
    v40, new_vcc = [], []
    for a, bi in zip(perm(v38, (1, 2, 3, 0)), vcc):
        d = a - 10 - bi
        v40.append(d & m32)
        new_vcc.append(1 if d < 0 else 0)
    vcc = new_vcc
    v42, new_vcc = [], []
    for a, bi in zip(perm(v40, (3, 2, 1, 0)), vcc):
        d = 0xfffffff4 - a - bi
        v42.append(d & m32)
        new_vcc.append(1 if d < 0 else 0)
    vcc = new_vcc
    v44, new_vcc = [], []
    for a, bi in zip(v42, vcc):
        d = 20 - a - bi
        v44.append(d & m32)
        new_vcc.append(1 if d < 0 else 0)
    vcc = new_vcc
    new_vcc = []
    for a, bi in zip(v44, vcc):
        new_vcc.append(1 if a - 20 - bi < 0 else 0)
    vcc = new_vcc
    a = (200.0 if vcc[0] else 100.0) + float(v44[0] & 0x3ff)
    expected = (r, g, b, a)
    for x in expected:
        assert single(x) == x == half_rtz(x), x
    return expected


def check_dpp_extra_draw(directory, compiler, renderer, backend):
    program = with_constants(DPP_EXTRA_BODY)
    source = directory / "dpp_extra.hlsl"
    shader = directory / "dpp_extra.cso"
    case = directory / "dpp_extra.case"
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    compile_cmd = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run(compile_cmd, check=True)
    for vals in DPP_EXTRA_SETS:
        constants = bytearray(256)
        struct.pack_into("<4f", constants, 12, *vals)
        expected = dpp_extra_reference(*vals)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
    # Mutations checked against Set 1.
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *DPP_EXTRA_SETS[0])
    case.write_bytes(constants + struct.pack("<4f", *dpp_extra_reference(*DPP_EXTRA_SETS[0])) * 64)
    for old, new, label in (
        ("v_rndne_f32_dpp v24, -v21 quad_perm:[1,0,3,2]", "v_rndne_f32_dpp v24, -v21 quad_perm:[2,3,0,1]", "AcrossX vs AcrossY"),
        ("v_rcp_iflag_f32_dpp v26, v26 dpp8:[1,2,3,0,5,6,7,4]", "v_rcp_iflag_f32_dpp v26, v26 dpp8:[2,3,0,1,6,7,4,5]", "cyclic dpp8 rotation"),
        ("v_sin_f32_dpp v27, -v26 quad_perm:[1,0,3,2]", "v_sin_f32_dpp v27, v26 quad_perm:[1,0,3,2]", "DPP16 neg on sin"),
        ("v_sub_co_ci_u32_dpp v45, vcc_lo, v44, v43, vcc_lo", "v_subrev_co_ci_u32_dpp v45, vcc_lo, v44, v43, vcc_lo", "sub vs subrev carry"),
        ("v_frexp_mant_f32_dpp v33, -v32 quad_perm:[2,3,0,1]", "v_frexp_mant_f32_dpp v33, v32 quad_perm:[2,3,0,1]", "DPP16 neg on frexp_mant"),
    ):
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_cmd, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


def controls_408():
    # Quad-local DPP16 and DPP8 controls.
    dpp = with_constants(DPP_BODY)
    source = translate(dpp)
    for expected in ("QuadReadAcrossX(", "QuadReadAcrossY(", "QuadReadAcrossDiagonal(",
                     "QuadReadLaneAt(", "frag_position.x"):
        assert expected in source, expected
    # Accept optional bound_ctrl:[01] and fi:[01] on quad-local DPP16/DPP8.
    assert "QuadReadAcrossX(" in translate(with_constants([
        "v_mov_b32_dpp v12, v13 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:1",
    ]))
    assert "QuadReadAcrossX(" in translate(with_constants([
        "v_mov_b32_dpp v12, v13 dpp8:[1,0,3,2,5,4,7,6] fi:1",
    ]))
    for bad in (
        "v_mov_b32_dpp v22, v18 dpp8:[4,5,6,7,0,1,2,3]",  # cross-quad DPP8
        "v_mov_b32_dpp v22, v18 dpp8:[1,0,3,2,4,5,6,7]",  # mismatched high-quad perm
        "v_mov_b32_dpp v22, v18 row_shr:1 row_mask:0xf bank_mask:0xf",  # non-quad DPP16
        "v_mov_b32_dpp v22, v18 wave_shr:1 row_mask:0xf bank_mask:0xf",
        "v_mov_b32_dpp v22, v18 quad_perm:[1,0,3,2] row_mask:0xe bank_mask:0xf",  # partial row_mask
        "v_mov_b32_dpp v22, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0x7",  # partial bank_mask
        "v_mov_b32_dpp v22, -v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # neg on mov
        "v_add_f32_dpp v22, -v18, v19 dpp8:[1,0,3,2,5,4,7,6]",  # neg on DPP8
        "v_add_f32_dpp v22, s44, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # SGPR in DPP
        "v_add_f32_dpp v22, 1.0, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # inline const in DPP
        "v_cndmask_b32_dpp v22, v18, v19, s52 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # non-vcc
        "v_cndmask_b32_dpp v22, v18, v19, vcc_lo quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # untracked vcc
        "v_fmac_f32_dpp v25, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # unset fmac dst
        "v_add_f32_dpp v256, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_mad_f32_dpp v22, v18, v19, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # VOP3-only, no DPP encoding
    ):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", bad]))
    wait_vm = dpp.index("s_waitcnt vmcnt(0)")
    must_reject(translate, dpp[:wait_vm] + ["v_mov_b32_dpp v12, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp[wait_vm:])
    must_reject(translate, dpp[:wait_vm] + ["v_mov_b32_dpp v22, v12 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp[wait_vm:])
    wqm_idx = dpp.index("s_wqm_b64 exec, exec") + 1
    must_reject(translate, dpp[:wqm_idx] + ["v_mov_b32_dpp v22, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp[wqm_idx:])


def controls_414():
    # Quad-local integer/bitwise/shift/bit-scan DPP16 and DPP8 controls.
    dpp_int = with_constants(DPP_INT32_BODY)
    source = translate(dpp_int)
    for expected in ("uint dpp_ffbh_u32(", "uint dpp_ffbh_i32(", "uint mul_hi_u32(", "uint mul_hi_i32(",
                     "QuadReadAcrossX(", "QuadReadAcrossY(", "QuadReadAcrossDiagonal(", "QuadReadLaneAt("):
        assert expected in source, expected
    assert "uint mul_hi_i32(" not in translate(assembly(False))
    for bad in (
        "v_add_nc_u32_dpp v22, v18, v19 dpp8:[4,5,6,7,0,1,2,3]",  # cross-quad DPP8
        "v_add_nc_u32_dpp v22, v18, v19 dpp8:[1,0,3,2,4,5,6,7]",
        "v_add_nc_u32_dpp v22, v18, v19 row_shr:1 row_mask:0xf bank_mask:0xf",
        "v_add_nc_u32_dpp v22, v18, v19 quad_perm:[1,0,3,2] row_mask:0xe bank_mask:0xf",
        "v_add_nc_u32_dpp v22, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0x7",
        "v_add_nc_u32_dpp v22, -v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_and_b32_dpp v22, |v18|, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_nc_u32_dpp v22, s44, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_nc_u32_dpp v22, 1, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_not_b32_dpp v22, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_nc_u32_dpp v256, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_mad_u32_u24_dpp v22, v18, v19, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    ):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", bad]))
    wait_vm = dpp_int.index("s_waitcnt vmcnt(0)")
    must_reject(translate, dpp_int[:wait_vm] + ["v_not_b32_dpp v12, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_int[wait_vm:])
    must_reject(translate, dpp_int[:wait_vm] + ["v_not_b32_dpp v22, v12 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_int[wait_vm:])
    wqm_idx = dpp_int.index("s_wqm_b64 exec, exec") + 1
    must_reject(translate, dpp_int[:wqm_idx] + ["v_not_b32_dpp v22, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_int[wqm_idx:])


def controls_419():
    # Quad-local f16 DPP16 and DPP8 controls.
    dpp_f16 = with_constants(DPP_F16_BODY)
    source = translate(dpp_f16)
    for expected in ("float dpp_frexp_mant_f16(", "uint dpp_frexp_exp_i16_f16(", "0xffff0000u"):
        assert expected in source, expected
    assert "float dpp_frexp_mant_f16(" not in translate(assembly(False))
    for bad in (
        "v_add_f16_dpp v25, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # uninitialized vdst high-half
        "v_add_f16_dpp v18, v18, v19 dpp8:[4,5,6,7,0,1,2,3]",  # cross-quad DPP8
        "v_add_f16_dpp v18, v18, v19 row_shr:1 row_mask:0xf bank_mask:0xf",
        "v_add_f16_dpp v18, v18, v19 quad_perm:[1,0,3,2] row_mask:0xe bank_mask:0xf",
        "v_add_f16_dpp v18, -v18, v19 dpp8:[1,0,3,2,5,4,7,6]",  # neg on DPP8
        "v_ldexp_f16_dpp v18, v18, -v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # neg on i16 exp
        "v_add_f16_dpp v18, s44, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_f16_dpp v18, 1.0, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_floor_f16_dpp v18, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_f16_dpp v256, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_mad_f16_dpp v18, v18, v19, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        # Fused: narrow16(mad()) would round twice, so every spelling is refused (as valu_f16 refuses v_fmac_f16).
        "v_fmac_f16_dpp v18, v18, v19 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_fmac_f16_dpp v18, v18, v19 dpp8:[1,0,3,2,5,4,7,6]",
        "v_fmac_f16_dpp v18, -v18, |v19| quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    ):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", bad]))
    wait_vm = dpp_f16.index("s_waitcnt vmcnt(0)")
    must_reject(translate, dpp_f16[:wait_vm] + ["v_cvt_f16_f32_dpp v12, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_f16[wait_vm:])
    must_reject(translate, dpp_f16[:wait_vm] + ["v_mov_b32_e32 v22, 0", "v_cvt_f16_f32_dpp v22, v12 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_f16[wait_vm:])
    wqm_idx = dpp_f16.index("s_wqm_b64 exec, exec") + 1
    must_reject(translate, dpp_f16[:wqm_idx] + ["v_cvt_f16_f32_dpp v22, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_f16[wqm_idx:])


def controls_421():
    # Quad-local conversion DPP16 and DPP8 controls.
    dpp_cvt = with_constants(DPP_CVT_BODY)
    source = translate(dpp_cvt)
    for expected in ("uint dpp_pack16_rtz(", "uint dpp_cvt_i32_f32(", "uint dpp_cvt_i16_f16(", "uint dpp_cvt_u16_f16(",
                     "uint dpp_cvt_norm_i16_f16(", "uint dpp_cvt_norm_u16_f16(", "uint dpp_sat_pk_u8_i16("):
        assert expected in source, expected
    assert "uint dpp_cvt_i32_f32(" not in translate(assembly(False))
    for bad in (
        "v_cvt_f16_i16_dpp v25, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # uninitialized 16-bit vdst
        "v_sat_pk_u8_i16_dpp v25, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_cvt_f32_i32_dpp v18, -v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",  # neg on int src
        "v_sat_pk_u8_i16_dpp v18, -v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_cvt_i32_f32_dpp v18, -v18 dpp8:[1,0,3,2,5,4,7,6]",  # neg on DPP8
        "v_cvt_f32_i32_dpp v18, v18 dpp8:[4,5,6,7,0,1,2,3]",  # cross-quad DPP8
        "v_cvt_f32_i32_dpp v18, v18 row_shr:1 row_mask:0xf bank_mask:0xf",
        "v_cvt_f32_i32_dpp v18, v18 quad_perm:[1,0,3,2] row_mask:0xe bank_mask:0xf",
        "v_cvt_f32_i32_dpp v18, s44 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_cvt_pkrtz_f16_f32_dpp v18, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_cvt_f32_i32_dpp v256, v18 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    ):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", bad]))
    wait_vm = dpp_cvt.index("s_waitcnt vmcnt(0)")
    must_reject(translate, dpp_cvt[:wait_vm] + ["v_cvt_i32_f32_dpp v12, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_cvt[wait_vm:])
    must_reject(translate, dpp_cvt[:wait_vm] + ["v_cvt_i32_f32_dpp v22, v12 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_cvt[wait_vm:])
    wqm_idx = dpp_cvt.index("s_wqm_b64 exec, exec") + 1
    must_reject(translate, dpp_cvt[:wqm_idx] + ["v_cvt_i32_f32_dpp v22, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + dpp_cvt[wqm_idx:])


def controls_423():
    # Existing programs without DPP extra ops emit none of the DPP helper functions or quad intrinsics.
    plain_hlsl = translate(assembly(False))
    for sym in ("dpp_frexp_mant_f32(", "dpp_frexp_exp_i32_f32(", "QuadRead"):
        assert sym not in plain_hlsl, sym

    # Quad-local DPP16/DPP8 extra f32, carry-in/carry-out, and dot-accumulate controls.
    extra_prog = with_constants(DPP_EXTRA_BODY)
    extra_hlsl = translate(extra_prog)
    for sym in ("round(", "6.283185307179586f", "dpp_frexp_mant_f32(", "dpp_frexp_exp_i32_f32(",
                "QuadReadAcrossX(", "QuadReadAcrossY(", "QuadReadAcrossDiagonal(",
                "QuadReadLaneAt(", "frag_position.x"):
        assert sym in extra_hlsl, sym
    # DPP16 optional bound_ctrl/fi and DPP8 optional fi, plus wave64 vcc spelling.
    assert "round(" in translate(with_constants([
        "v_rndne_f32_dpp v12, v12 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf bound_ctrl:1 fi:0",
    ]))
    assert "round(" in translate(with_constants([
        "v_rndne_f32_dpp v12, v12 dpp8:[1,0,3,2,5,4,7,6] fi:1",
    ]))
    assert "cmp" in translate(with_constants([
        "v_cmp_f_f32_e32 vcc, v12, v12",
        "v_add_co_ci_u32_dpp v12, vcc, v12, v13, vcc quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    ]))
    # Negative controls: modifiers on DPP8 or integer ops, cross-quad DPP8, row/wave DPP,
    # partial masks, non-VGPR operands, uninitialized accumulator, untracked/mismatched vcc,
    # WQM, and vmcnt hazards.
    for bad in (
        "v_rndne_f32_dpp v12, -v12 dpp8:[1,0,3,2,5,4,7,6]",
        "v_mac_f32_dpp v12, |v12|, v13 dpp8:[1,0,3,2,5,4,7,6]",
        "v_rndne_f32_dpp v12, v12 dpp8:[4,5,6,7,0,1,2,3]",
        "v_rndne_f32_dpp v12, v12 dpp8:[0,1,2,3,4,5,6,6]",
        "v_rndne_f32_dpp v12, v12 row_shl:1 row_mask:0xf bank_mask:0xf",
        "v_rndne_f32_dpp v12, v12 wave_shl:1 row_mask:0xf bank_mask:0xf",
        "v_rndne_f32_dpp v12, v12 quad_perm:[1,0,3,2] row_mask:0xe bank_mask:0xf",
        "v_rndne_f32_dpp v12, v12 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0x7",
        "v_rndne_f32_dpp v12, v12 quad_perm:[1,0,3,2] row_mask:0xf",
        "v_rndne_f32_dpp v12, s44 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_rndne_f32_dpp v12, 1.0 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_mac_f32_dpp v30, v12, v13 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_co_ci_u32_dpp v12, vcc_lo, v12, v13, vcc_lo quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_sub_co_ci_u32_dpp v12, vcc_lo, v12, v13, vcc_lo quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_subrev_co_ci_u32_dpp v12, vcc_lo, v12, v13, vcc_lo quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    ):
        must_reject(translate, with_constants([bad]))
    for bad_co in (
        "v_add_co_ci_u32_dpp v12, vcc_lo, -v12, v13, vcc_lo quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_co_ci_u32_dpp v12, vcc_lo, v12, v13, vcc quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
        "v_add_co_ci_u32_dpp v12, s52, v12, v13, s52 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf",
    ):
        must_reject(translate, with_constants(["v_cmp_f_f32_e32 vcc_lo, v12, v12", bad_co]))
    # WQM and vmcnt hazards.
    base_dpp = assembly(False)
    wqm_at = base_dpp.index("s_wqm_b64 exec, exec") + 1
    must_reject(translate, base_dpp[:wqm_at] + ["v_rndne_f32_dpp v20, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + base_dpp[wqm_at:])
    wait_at = base_dpp.index("s_waitcnt vmcnt(0)")
    must_reject(translate, base_dpp[:wait_at] + ["v_rndne_f32_dpp v20, v12 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + base_dpp[wait_at:])
    must_reject(translate, base_dpp[:wait_at] + ["v_rndne_f32_dpp v12, v8 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"] + base_dpp[wait_at:])


def controls(directory):
    for check in (controls_408, controls_414, controls_419, controls_421, controls_423):
        check()


def draw(directory, compiler, renderer, backend):
    for check in (check_dpp_draw, check_dpp_int32_draw, check_dpp_f16_draw, check_dpp_cvt_draw, check_dpp_extra_draw):
        check(directory, compiler, renderer, backend)


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate)
            for body in (DPP_BODY, DPP_INT32_BODY, DPP_F16_BODY, DPP_CVT_BODY, DPP_EXTRA_BODY)]
