"""Draw family `vop3p`: pixel_aot_check.py draw --family vop3p.

Packed binary16 arithmetic (v_pk_{add,mul,min,max,fma}_f16), packed 16-bit integer arithmetic (v_pk_*_{i16,u16,b16}) and
the dot products (v_dot2/4/8_*), ported from R0Y00/Xbox2Windows#376, #397 and #391 with their reference values and
wrong-reference mutations. The mixed-precision fma (v_fma_mix_*) is the `fma_mix` family and v_cvt_pkrtz the `pkrtz`
family. The dot products are not in gfx1013's LLVM 15 target, so their binary fixture is assembled for gfx1030.
"""
import math
import struct
import subprocess

from .common import half_rtz, half_value, must_reject, single, translate, with_constants, assembly


def pack_f16_pair(lo, hi):
    lo_bits = lo if isinstance(lo, int) else struct.unpack("<H", struct.pack("<e", lo))[0]
    hi_bits = hi if isinstance(hi, int) else struct.unpack("<H", struct.pack("<e", hi))[0]
    return lo_bits | (hi_bits << 16)


def rne_f16(value):
    if math.isnan(value):
        return math.nan
    try:
        return struct.unpack("<e", struct.pack("<e", value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


# Packed binary16 VOP3P arithmetic: exercises all five v_pk_*_f16 instructions, op_sel/op_sel_hi,
# neg_lo/neg_hi, clamp, NaN minNum semantics, RNE tie-to-even rounding, and gfx1013 zero-extension
# of inline f16 constants (0.5 -> lo=0.5, hi=0.0).
PK_F16_BODY = [
    "v_mov_b32_e32 v19, s45",
    "v_mov_b32_e32 v20, s46",
    "v_mov_b32_e32 v21, s47",
    "v_pk_add_f16 v22, s44, v19 op_sel:[1,0] op_sel_hi:[0,1] neg_lo:[0,1]",
    "v_pk_mul_f16 v23, v22, v20 neg_hi:[1,0]",
    "v_pk_fma_f16 v24, v23, v21, s47 op_sel:[0,1,0] op_sel_hi:[1,0,1]",
    "v_pk_min_f16 v25, v24, 0x40007e00",
    "v_pk_max_f16 v26, v24, 0.5 clamp",
    "v_cvt_f32_f16_e32 v12, v25",
    "v_pk_add_f16 v27, v25, 0 op_sel:[1,0]",
    "v_cvt_f32_f16_e32 v13, v27",
    "v_cvt_f32_f16_e32 v14, v26",
    "v_pk_add_f16 v28, v26, 0 op_sel:[1,0]",
    "v_cvt_f32_f16_e32 v15, v28",
]
PK_F16_SETS = (
    # Set 1: v24=(0.875, 0.25); channel 0 tests minNum(0.875, qNaN)=0.875, channel 3=0.25 proves inline 0.5 hi=0.0.
    (pack_f16_pair(1.5, 2.0), pack_f16_pair(0.5, -1.0), pack_f16_pair(0.5, 1.0), pack_f16_pair(0.5, 0.5)),
    # Set 2: v24=(2.5, -1.0); channel 2 clamps 2.5 -> 1.0 and channel 3 clamps -1.0 -> 0.0.
    (pack_f16_pair(2.0, 3.0), pack_f16_pair(1.0, 0.0), pack_f16_pair(1.0, 2.0), pack_f16_pair(0.5, 1.0)),
    # Set 3: exact halfway ties at 1.0 + 2^-11 (-> even 1.0) and -(1.0 + 2^-10) - 2^-11 (-> even -(1.0 + 2^-9),
    # distinguishing RNE from RTZ f32tof16 in channel 1).
    (pack_f16_pair(0xbc01, 0x3c00), pack_f16_pair(0x9000, 0x9000), pack_f16_pair(4.0, 4.0), pack_f16_pair(0.25, 0.25)),
)


def pk_f16_reference(words):
    def split16(w):
        return half_value(w), half_value(w >> 16)

    def min_num(a, b):
        return b if math.isnan(a) else (a if math.isnan(b) else min(a, b))

    def max_num(a, b):
        return b if math.isnan(a) else (a if math.isnan(b) else max(a, b))

    def sat(x):
        return 0.0 if math.isnan(x) or x <= 0.0 else (1.0 if x >= 1.0 else x)

    s44, s45, s46, s47 = (split16(w) for w in words)
    v22 = (rne_f16(s44[1] + (-s45[0])), rne_f16(s44[0] + s45[1]))
    v23 = (rne_f16(v22[0] * s46[0]), rne_f16((-v22[1]) * s46[1]))
    v24 = (rne_f16(v23[0] * s47[1] + s47[0]), rne_f16(v23[1] * s47[0] + s47[1]))
    v25 = (rne_f16(min_num(v24[0], math.nan)), rne_f16(min_num(v24[1], 2.0)))
    v26 = (rne_f16(sat(max_num(v24[0], 0.5))), rne_f16(sat(max_num(v24[1], 0.0))))
    return [v25[0], v25[1], v26[0], v26[1]]


def check_pk_f16_draw(directory, compiler, renderer, backend):
    source = directory / "pk_f16.hlsl"
    shader = directory / "pk_f16.cso"
    case = directory / "pk_f16.case"
    program = with_constants(PK_F16_BODY)
    source.write_text(translate(program), encoding="ascii")
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    subprocess.run(compile_shader, check=True)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    for words in PK_F16_SETS:
        expected = pk_f16_reference(words)
        assert all(not math.isnan(x) and half_rtz(x) == x for x in expected), expected
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)

    # Negative mutations against Set 1 and Set 2 must produce pixel_mismatch.
    for words, old, new, label in (
        (PK_F16_SETS[0],
         "v_pk_add_f16 v22, s44, v19 op_sel:[1,0] op_sel_hi:[0,1] neg_lo:[0,1]",
         "v_pk_add_f16 v22, s44, v19 op_sel:[1,0] op_sel_hi:[0,1]", "neg_lo"),
        (PK_F16_SETS[0],
         "v_pk_mul_f16 v23, v22, v20 neg_hi:[1,0]",
         "v_pk_mul_f16 v23, v22, v20", "neg_hi"),
        (PK_F16_SETS[0],
         "v_pk_min_f16 v25, v24, 0x40007e00",
         "v_pk_max_f16 v25, v24, 0x40007e00", "min vs max"),
        (PK_F16_SETS[0],
         "v_pk_max_f16 v26, v24, 0.5 clamp",
         "v_pk_max_f16 v26, v24, 0.5 op_sel_hi:[1,0] clamp", "inline hi zero-extension"),
        (PK_F16_SETS[1],
         "v_pk_max_f16 v26, v24, 0.5 clamp",
         "v_pk_max_f16 v26, v24, 0.5", "clamp"),
    ):
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        case.write_bytes(constants + struct.pack("<4f", *pk_f16_reference(words)) * 64)
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


# Packed 16-bit integer VOP3P fixture covering all 14 forms: add/sub/min/max (i16/u16),
# mul_lo_u16, mad (i16/u16), and lshlrev/lshrrev/ashrrev shifts, plus op_sel/op_sel_hi, clamp,
# and inline -1. Exports all four bytes of the packed accumulator as exact [0, 255] integers.
PK_INT16_BODY = [
    "v_mov_b32_e32 v18, s44",
    "v_mov_b32_e32 v19, s45",
    "v_mov_b32_e32 v20, s46",
    "v_mov_b32_e32 v21, s47",
    "v_pk_add_i16 v22, v18, v19 op_sel:[1,0] op_sel_hi:[0,1] clamp",
    "v_pk_add_u16 v23, v18, v19 clamp",
    "v_pk_sub_i16 v24, v18, v19 clamp",
    "v_pk_sub_u16 v25, v18, v19 clamp",
    "v_pk_mad_i16 v26, v18, v19, v20 clamp",
    "v_pk_mad_u16 v27, v18, v19, v20 clamp",
    "v_pk_min_i16 v28, v22, v24",
    "v_pk_max_i16 v29, v28, v26",
    "v_pk_min_u16 v28, v23, v25",
    "v_pk_max_u16 v28, v28, v27",
    "v_pk_mul_lo_u16 v29, v29, v28",
    "v_pk_add_i16 v29, v29, -1",
    "v_pk_lshlrev_b16 v22, v21, v29 op_sel:[0,1] op_sel_hi:[1,0]",
    "v_pk_lshrrev_b16 v23, v21, v28",
    "v_pk_ashrrev_i16 v24, v21, v18",
    "v_pk_add_u16 v30, v22, v23",
    "v_pk_sub_u16 v30, v30, v24",
    "v_pk_add_u16 v30, v30, v25",
    "v_pk_add_u16 v30, v30, v26",
    "v_pk_add_u16 v30, v30, v29",
    "v_pk_lshlrev_b16 v25, 8, v30 op_sel_hi:[0,1]",
    "v_pk_lshrrev_b16 v25, 8, v25 op_sel_hi:[0,1]",
    "v_pk_lshrrev_b16 v26, 8, v30 op_sel_hi:[0,1]",
    "v_pk_add_u16 v27, v25, 0 op_sel:[1,0] op_sel_hi:[0,0]",
    "v_pk_add_u16 v28, v26, 0 op_sel:[1,0] op_sel_hi:[0,0]",
    "v_cvt_f32_f16_e32 v12, v25",
    "v_mul_f32_e32 v12, 0x4b800000, v12",
    "v_cvt_f32_f16_e32 v13, v26",
    "v_mul_f32_e32 v13, 0x4b800000, v13",
    "v_cvt_f32_f16_e32 v14, v27",
    "v_mul_f32_e32 v14, 0x4b800000, v14",
    "v_cvt_f32_f16_e32 v15, v28",
    "v_mul_f32_e32 v15, 0x4b800000, v15",
]

PK_INT16_SETS = (
    # Set 1: mixed signed/unsigned lanes + shift counts >= 16 (testing & 15 masking and ashrrev sign fill).
    (0xf0080015, 0x0010fffe, 0x0007fff9, 0x00130012),
    # Set 2: saturates all 6 clamping ops (signed +/-32767/-32768 and unsigned 0/65535 boundaries).
    (0x70009000, 0x7000a000, 0x4000c000, 0x00020003),
    # Set 3: signed/unsigned extremes (INT16_MIN/MAX, UINT16_MAX) and max 4-bit shift count 15.
    (0x80007fff, 0xffff0001, 0x0002fffd, 0x000f0001),
)


def pk_int16_reference(w18, w19, w20, w21):
    def u16(w, hi):
        return (w >> 16) & 0xffff if hi else w & 0xffff

    def i16(w, hi):
        v = u16(w, hi)
        return v - 0x10000 if v >= 0x8000 else v

    def pack(lo, hi):
        return (lo & 0xffff) | ((hi & 0xffff) << 16)

    def sat_i(v):
        return max(-32768, min(32767, v)) & 0xffff

    def sat_u(v):
        return max(0, min(65535, v)) & 0xffff

    v22 = pack(sat_i(i16(w18, 1) + i16(w19, 0)), sat_i(i16(w18, 0) + i16(w19, 1)))
    v23 = pack(sat_u(u16(w18, 0) + u16(w19, 0)), sat_u(u16(w18, 1) + u16(w19, 1)))
    v24 = pack(sat_i(i16(w18, 0) - i16(w19, 0)), sat_i(i16(w18, 1) - i16(w19, 1)))
    v25 = pack(sat_u(u16(w18, 0) - u16(w19, 0)), sat_u(u16(w18, 1) - u16(w19, 1)))
    v26 = pack(sat_i(i16(w18, 0) * i16(w19, 0) + i16(w20, 0)), sat_i(i16(w18, 1) * i16(w19, 1) + i16(w20, 1)))
    v27 = pack(sat_u(u16(w18, 0) * u16(w19, 0) + u16(w20, 0)), sat_u(u16(w18, 1) * u16(w19, 1) + u16(w20, 1)))
    v28 = pack(min(i16(v22, 0), i16(v24, 0)), min(i16(v22, 1), i16(v24, 1)))
    v29 = pack(max(i16(v28, 0), i16(v26, 0)), max(i16(v28, 1), i16(v26, 1)))
    v28 = pack(min(u16(v23, 0), u16(v25, 0)), min(u16(v23, 1), u16(v25, 1)))
    v28 = pack(max(u16(v28, 0), u16(v27, 0)), max(u16(v28, 1), u16(v27, 1)))
    v29 = pack((u16(v29, 0) * u16(v28, 0)) & 0xffff, (u16(v29, 1) * u16(v28, 1)) & 0xffff)
    v29 = pack((i16(v29, 0) - 1) & 0xffff, (i16(v29, 1) - 1) & 0xffff)
    v22 = pack((u16(v29, 1) << (u16(w21, 0) & 15)) & 0xffff, (u16(v29, 0) << (u16(w21, 1) & 15)) & 0xffff)
    v23 = pack(u16(v28, 0) >> (u16(w21, 0) & 15), u16(v28, 1) >> (u16(w21, 1) & 15))
    v24 = pack((i16(w18, 0) >> (u16(w21, 0) & 15)) & 0xffff, (i16(w18, 1) >> (u16(w21, 1) & 15)) & 0xffff)
    v30 = pack((u16(v22, 0) + u16(v23, 0)) & 0xffff, (u16(v22, 1) + u16(v23, 1)) & 0xffff)
    v30 = pack((u16(v30, 0) - u16(v24, 0)) & 0xffff, (u16(v30, 1) - u16(v24, 1)) & 0xffff)
    v30 = pack((u16(v30, 0) + u16(v25, 0)) & 0xffff, (u16(v30, 1) + u16(v25, 1)) & 0xffff)
    v30 = pack((u16(v30, 0) + u16(v26, 0)) & 0xffff, (u16(v30, 1) + u16(v26, 1)) & 0xffff)
    v30 = pack((u16(v30, 0) + u16(v29, 0)) & 0xffff, (u16(v30, 1) + u16(v29, 1)) & 0xffff)
    return tuple(float((v30 >> (8 * k)) & 0xff) for k in range(4))


def check_pk_int16_draw(directory, compiler, renderer, backend):
    program = with_constants(PK_INT16_BODY)
    source = directory / "pk_int16.hlsl"
    shader = directory / "pk_int16.cso"
    case = directory / "pk_int16.case"
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    for values in PK_INT16_SETS:
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = pk_int16_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
    for set_idx, old, new, label in (
        (0, "v_pk_ashrrev_i16 v24, v21, v18", "v_pk_lshrrev_b16 v24, v21, v18", "ashrrev sign extension"),
        (0, "v_pk_min_i16 v28, v22, v24", "v_pk_min_u16 v28, v22, v24", "signed vs unsigned min"),
        (1, "v_pk_sub_u16 v25, v18, v19 clamp", "v_pk_sub_u16 v25, v18, v19", "sub_u16 clamp"),
        (0, "op_sel:[1,0] op_sel_hi:[0,1] clamp", "op_sel_hi:[1,1] clamp", "op_sel cross-lane swap"),
        (1, "v_pk_mad_i16 v26, v18, v19, v20 clamp", "v_pk_mad_i16 v26, v18, v19, v20", "mad_i16 clamp"),
    ):
        values = PK_INT16_SETS[set_idx]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = pk_int16_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


# VOP3P dot-product fixture covering all 7 RDNA 2 (gfx1030) dot-product forms:
# v_dot2_f32_f16 (op_sel, op_sel_hi, neg_lo, neg_hi, clamp), v_dot2_{i,u}32_{i,u}16,
# v_dot4_{i,u}32_{i,u}8, and v_dot8_{i,u}32_{i,u}4 (wrapping and saturating clamp).
DOT_BODY = [
    "v_mov_b32_e32 v18, s44",
    "v_mov_b32_e32 v19, s45",
    "v_mov_b32_e32 v20, s46",
    "v_mov_b32_e32 v21, s47",
    "v_dot2_f32_f16 v22, v18, 0x40003800, 0.5 op_sel:[1,0,0] op_sel_hi:[0,1,1] neg_lo:[1,0,1] neg_hi:[0,1,0]",
    "v_dot2_f32_f16 v12, v18, 0x3c003800, v22 clamp",
    "v_dot2_i32_i16 v23, v19, v20, v21 op_sel:[0,1,0] op_sel_hi:[1,0,1] clamp",
    "v_dot2_u32_u16 v24, v19, v20, v21 clamp",
    "v_dot4_i32_i8 v25, v19, v20, v21 clamp",
    "v_dot4_u32_u8 v26, v19, v20, v21",
    "v_dot8_i32_i4 v27, v19, v20, v21",
    "v_dot8_u32_u4 v28, v19, v20, v21 clamp",
    "v_dot8_u32_u4 v29, v23, 0x12341234, 0",
    "v_dot8_u32_u4 v29, v24, 0x43214321, v29",
    "v_cvt_f32_f16_e32 v13, v29",
    "v_mul_f32_e32 v13, 0x4b800000, v13",
    "v_dot8_u32_u4 v30, v25, 0x12341234, 0",
    "v_dot8_u32_u4 v30, v26, 0x43214321, v30",
    "v_cvt_f32_f16_e32 v14, v30",
    "v_mul_f32_e32 v14, 0x4b800000, v14",
    "v_dot8_u32_u4 v31, v27, 0x12341234, 0",
    "v_dot8_u32_u4 v31, v28, 0x43214321, v31",
    "v_cvt_f32_f16_e32 v15, v31",
    "v_mul_f32_e32 v15, 0x4b800000, v15",
]

DOT_SETS = (
    # Set 1: mixed signs, interior v_dot2_f32_f16 value, non-overflowing signed & unsigned integer dots.
    (pack_f16_pair(-0.5, 1.0), 0xfffc0005, 0x0003fffe, 0x00000010),
    # Set 2: positive signed saturation (INT32_MAX) and unsigned saturation (UINT32_MAX).
    (pack_f16_pair(2.0, 2.0), 0x7fff7fff, 0x7fff7fff, 0x7ffffff0),
    # Set 3: negative signed saturation (INT32_MIN) and high-end clamp on v_dot2_f32_f16.
    (pack_f16_pair(-2.0, 2.0), 0x8000ffff, 0x7fff7fff, 0x80000010),
    # Set 4: v_dot8_u32_u4 unsigned saturation (UINT32_MAX) vs unwrapped v_dot4_u32_u8 wraparound.
    (pack_f16_pair(0.5, -1.0), 0xffffffff, 0xffffffff, 0xfffffe00),
)


def dot_reference(f16_bits, x, y, acc):
    def sext(val, bits):
        mask = (1 << bits) - 1
        v = val & mask
        return v - (1 << bits) if v & (1 << (bits - 1)) else v

    def sat_i32(v):
        return max(-0x80000000, min(0x7fffffff, v)) & 0xffffffff

    def sat_u32(v):
        return min(0xffffffff, v) & 0xffffffff

    def nibble_dot(a, b):
        return sum(((a >> (4 * k)) & 0xf) * ((b >> (4 * k)) & 0xf) for k in range(8))

    a_lo = struct.unpack("<e", struct.pack("<H", f16_bits & 0xffff))[0]
    a_hi = struct.unpack("<e", struct.pack("<H", (f16_bits >> 16) & 0xffff))[0]
    v22 = single((-a_hi) * 0.5 + a_lo * (-2.0) + (-0.5))
    v12 = min(max(single(a_lo * 0.5 + a_hi * 1.0 + v22), 0.0), 1.0)

    acc_s = sext(acc, 32)
    v23 = sat_i32(sext(x, 16) * sext(y >> 16, 16) + sext(x >> 16, 16) * sext(y, 16) + acc_s)
    v24 = sat_u32((x & 0xffff) * (y & 0xffff) + ((x >> 16) & 0xffff) * ((y >> 16) & 0xffff) + acc)
    v25 = sat_i32(sum(sext(x >> (8 * k), 8) * sext(y >> (8 * k), 8) for k in range(4)) + acc_s)
    v26 = (sum(((x >> (8 * k)) & 0xff) * ((y >> (8 * k)) & 0xff) for k in range(4)) + acc) & 0xffffffff
    v27 = (sum(sext(x >> (4 * k), 4) * sext(y >> (4 * k), 4) for k in range(8)) + acc_s) & 0xffffffff
    v28 = sat_u32(nibble_dot(x, y) + acc)

    c1 = nibble_dot(v23, 0x12341234) + nibble_dot(v24, 0x43214321)
    c2 = nibble_dot(v25, 0x12341234) + nibble_dot(v26, 0x43214321)
    c3 = nibble_dot(v27, 0x12341234) + nibble_dot(v28, 0x43214321)
    assert c1 < 1024 and c2 < 1024 and c3 < 1024, (c1, c2, c3)
    return (half_rtz(v12), float(c1), float(c2), float(c3))


def check_dot_draw(directory, compiler, renderer, backend):
    program = with_constants(DOT_BODY)
    source = directory / "dot.hlsl"
    shader = directory / "dot.cso"
    case = directory / "dot.case"
    compile_shader = [compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source]
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    source.write_text(translate(program), encoding="ascii")
    subprocess.run(compile_shader, check=True)
    for values in DOT_SETS:
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = dot_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
    for set_idx, old, new, label in (
        (0, "neg_lo:[1,0,1]", "neg_lo:[0,0,1]", "dot2_f32_f16 neg_lo"),
        (0, "v_dot2_i32_i16 v23", "v_dot2_u32_u16 v23", "dot2 signed vs unsigned"),
        (1, "v_dot4_i32_i8 v25, v19, v20, v21 clamp", "v_dot4_i32_i8 v25, v19, v20, v21", "dot4_i32_i8 clamp"),
        (0, "v_dot8_i32_i4 v27", "v_dot8_u32_u4 v27", "dot8 signed vs unsigned"),
        (3, "v_dot8_u32_u4 v28, v19, v20, v21 clamp", "v_dot8_u32_u4 v28, v19, v20, v21", "dot8_u32_u4 clamp"),
    ):
        values = DOT_SETS[set_idx]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *values)
        expected = dot_reference(*values)
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run(compile_shader, check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


def check_pk_f16_controls():
    body = with_constants(PK_F16_BODY)
    source = translate(body)
    for expected in ("narrow16(", "widen16(", "saturate(", "fma_mix_round(", "fm_f16_word("):
        assert expected in source, expected
    assert "fma_mix_round(" not in translate(assembly(False))
    assert "float16_t" not in source and "min16float" not in source and "half4" not in source
    # Explicit default modifiers lower identically to omitted defaults.
    explicit = [line.replace("v_pk_min_f16 v25, v24, 0x40007e00",
                             "v_pk_min_f16 v25, v24, 0x40007e00 op_sel:[0,0] op_sel_hi:[1,1] neg_lo:[0,0] neg_hi:[0,0]")
                for line in body]
    assert translate(explicit) == source
    # A packed result is a uint word, not a float-typed value.
    main = source.split("float4 main")[1]
    assert "uint valu" in main and "asfloat(pk" not in main, main
    prefix = ["v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46"]
    for good in ("v_pk_add_f16 v22, s44, v19", "v_pk_fma_f16 v22, s44, v19, v20 clamp", "v_pk_mul_f16 v22, 0.5, -1.0"):
        translate(with_constants([*prefix, good]))
    for bad in (
        "v_pk_fmac_f16 v22, s44, v19",  # VOP2, not a form here
        "v_pk_add_f16 v22, s44, v19, v20",
        "v_pk_fma_f16 v22, s44, v19",
        "v_pk_add_f16 v22, -s44, v19",
        "v_pk_add_f16 v22, |v19|, v20",
        "v_pk_add_f16 v22, v19, 1.5",
        "v_pk_add_f16 v22, v19, 65",
        "v_pk_add_f16 v22, v19, v20 op_sel:[0,1,0]",
        "v_pk_add_f16 v22, v19, v20 neg_lo:[1,0,0]",
        "v_pk_add_f16 v22, v19, v20 op_sel:[2,0]",
        "v_pk_add_f16 v22, v19, v20 op_sel:[0,0] op_sel:[1,0]",
        "v_pk_add_f16 v22, v19, v20 clamp clamp",
        "v_pk_add_f16 v22, v19, v20 mul:2",
        "v_pk_add_f16 v256, v19, v20",
        "v_pk_add_f16 v22, s28, v19",
        "v_pk_add_f16 v22, v19, v30",  # v30 never written
    ):
        must_reject(translate, with_constants([*prefix, bad]))
    wait_vm = body.index("s_waitcnt vmcnt(0)")
    must_reject(translate, body[:wait_vm] + ["v_pk_add_f16 v12, s44, 0.5"] + body[wait_vm:])
    must_reject(translate, body[:wait_vm] + ["v_pk_add_f16 v22, v12, 0.5"] + body[wait_vm:])
    lgkm = body.index("s_waitcnt lgkmcnt(0)", body.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    must_reject(translate, body[:lgkm] + ["v_pk_add_f16 v22, s44, 0.5"] + body[lgkm:])


def check_pk_int16_controls():
    body = with_constants(PK_INT16_BODY)
    source = translate(body)
    assert "clamp(" in source and "0xffffffffu" in source  # inline -1 is the sign-extended word
    main = source.split("float4 main")[1]
    assert "asfloat(pki" not in main and "uint valu" in main, main
    prefix = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46"]
    for bad in (
        "v_pk_min_i16 v22, v18, v19 clamp",  # clamp only on add, sub and mad
        "v_pk_max_u16 v22, v18, v19 clamp",
        "v_pk_mul_lo_u16 v22, v18, v19 clamp",
        "v_pk_lshlrev_b16 v22, v18, v19 clamp",
        "v_pk_lshrrev_b16 v22, v18, v19 clamp",
        "v_pk_ashrrev_i16 v22, v18, v19 clamp",
        "v_pk_add_i16 v22, v18, v19 neg_lo:[1,0]",
        "v_pk_add_i16 v22, v18, v19 neg_hi:[0,1]",
        "v_pk_add_i16 v22, -v18, v19",
        "v_pk_add_i16 v22, |v18|, v19",
        "v_pk_add_i16 v22, 0.5, v19",
        "v_pk_add_i16 v22, 65, v19",
        "v_pk_add_i16 v22, v18, v19 op_sel:[0,1,0]",
        "v_pk_mad_i16 v22, v18, v19",
        "v_pk_add_i16 v22, v18, v19 clamp clamp",
        "v_pk_add_i16 v256, v18, v19",
        "v_pk_add_i16 v22, s28, v19",
        "v_pk_add_i16 v22, v18, v30",  # v30 never written
        "v_pk_sub_i16_e64 v22, v18, v19",
    ):
        must_reject(translate, with_constants([*prefix, bad]))
    wait_vm = body.index("s_waitcnt vmcnt(0)")
    must_reject(translate, body[:wait_vm] + ["v_pk_add_u16 v12, s44, 1"] + body[wait_vm:])
    must_reject(translate, body[:wait_vm] + ["v_pk_add_u16 v22, v12, 1"] + body[wait_vm:])
    lgkm = body.index("s_waitcnt lgkmcnt(0)", body.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    must_reject(translate, body[:lgkm] + ["v_pk_add_u16 v22, s44, 1"] + body[lgkm:])


def check_dot_controls():
    body = with_constants(DOT_BODY)
    source = translate(body)
    for expected in ("uint v_dot2_i32_i16(", "uint v_dot2_u32_u16(", "uint v_dot4_i32_i8(",
                     "uint v_dot4_u32_u8(", "uint v_dot8_i32_i4(", "uint v_dot8_u32_u4("):
        assert expected in source, expected
    assert "uint v_dot2_i32_i16(" not in translate(assembly(False))
    # An inline binary16 constant is its low half with the high half zero; the accumulator is a binary32 value.
    inline = translate(with_constants(["v_dot2_f32_f16 v12, 0.5, 1.0, 2.0"]))
    assert "0x3800u" in inline and "0x3c00u" in inline and "asfloat(0x40000000u)" in inline, inline
    prefix = ["v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46", "v_mov_b32_e32 v21, s47"]
    for bad in (
        "v_dot2_f32_f16 v22, v19, v20, v21 op_sel:[0,0,1]",
        "v_dot2_f32_f16 v22, v19, v20, v21 op_sel_hi:[1,1,0]",
        "v_dot2_f32_f16 v22, v19, v20, v21 neg_hi:[0,0,1]",
        "v_dot2_f32_f16 v22, -v19, v20, v21",
        "v_dot2_f32_f16 v22, |v19|, v20, v21",
        "v_dot2_f32_f16 v22, v19, v20, v21 clamp clamp",
        "v_dot2_f32_f16 v22, v19, v20",
        "v_dot2_f32_f16 v22, v19, v20, 5",  # an integer is not a binary32 accumulator
        "v_dot2_i32_i16 v22, v19, v20, v21 neg_lo:[1,0,0]",
        "v_dot2_i32_i16 v22, 0.5, v20, v21",
        "v_dot4_i32_i8 v22, v19, v20, v21 op_sel:[1,0,0]",
        "v_dot8_u32_u4 v22, v19, v20, v21 op_sel_hi:[0,1,1]",
        "v_dot4_u32_u8 v22, v19, v20, 65",
        "v_dot8_i32_i4 v256, v19, v20, v21",
        "v_dot2_u32_u16 v22, s28, v20, v21",
        "v_dot2c_f32_f16 v22, v19, v20",  # VOP2 neighbours
        "v_dot4c_i32_i8 v22, v19, v20",
        "v_dot4_u32_u8 v22, v19, v20, v30",  # v30 never written
    ):
        must_reject(translate, with_constants([*prefix, bad]))
    wait_vm = body.index("s_waitcnt vmcnt(0)")
    must_reject(translate, body[:wait_vm] + ["v_dot4_u32_u8 v12, s45, s46, 0"] + body[wait_vm:])
    must_reject(translate, body[:wait_vm] + ["v_dot4_u32_u8 v22, v12, s46, 0"] + body[wait_vm:])
    lgkm = body.index("s_waitcnt lgkmcnt(0)", body.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    must_reject(translate, body[:lgkm] + ["v_dot4_u32_u8 v22, s45, 1, 0"] + body[lgkm:])


def check_vop3p_draws(directory, compiler, renderer, backend):
    check_pk_f16_draw(directory, compiler, renderer, backend)
    check_pk_int16_draw(directory, compiler, renderer, backend)
    check_dot_draw(directory, compiler, renderer, backend)


def controls(directory):
    check_pk_f16_controls()
    check_pk_int16_controls()
    check_dot_controls()


def binary_fixtures():
    """(program, translator[, cpu]) entries that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (with_constants(PK_F16_BODY), translate),
        (with_constants(PK_INT16_BODY), translate),
        (with_constants(DOT_BODY), translate, "gfx1030"),
    ]


draw = check_vop3p_draws
