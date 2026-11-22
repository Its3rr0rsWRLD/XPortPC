"""Draw family `arith`: pixel_aot_check.py draw --family arith."""
import struct
import subprocess

from .common import M32, assembly, byte, half_rtz, must_reject, signed, translate, ubyte, with_constants
from .int import INT_PROGRAMS


# Integer add, subtract, multiply and three-input forms. The same shape as INT_PROGRAMS: body, a reference over the
# four constant words, the constant sets, and wrong references (channel, function) that must each be detected.
# Results that need a vector source are copied with v_or_b32 so that no word passes through a float register.
u24 = lambda value: value & 0xffffff
i24 = lambda value: (value & 0xffffff) - (1 << 24) if value & 0x800000 else value & 0xffffff
u16 = lambda value: value & 0xffff
i16 = lambda value: (value & 0xffff) - (1 << 16) if value & 0x8000 else value & 0xffff
hi_u = lambda a, b: (a * b) >> 32
hi_i = lambda a, b: ((signed(a) * signed(b)) >> 32) & M32
sat_u = lambda value: min(max(value, 0), M32)
sat_i = lambda value: (min(max(value, -(1 << 31)), (1 << 31) - 1)) & M32


def copy(dst, src):
    return f"v_or_b32_e64 v{dst}, {src}, 0"


ARITH_PROGRAMS = (
    # VOP2 add and subtract, e32 and e64: wrapping sums, subtraction order, a literal in the e64 form.
    ([
        copy(18, "s44"),
        "v_add_nc_u32_e32 v19, s45, v18",
        "v_sub_nc_u32_e32 v20, s45, v18",
        "v_subrev_nc_u32_e32 v21, s45, v18",
        "v_subrev_nc_u32_e64 v22, s46, 0x7fff0001",
        ubyte(3, 12, "v19", "e32"), ubyte(0, 13, "v20", "e32"), ubyte(2, 14, "v21", "e64"), ubyte(1, 15, "v22", "e64"),
    ], lambda x, y, z, w: [byte((y + x) & M32, 3), byte((y - x) & M32, 0), byte((x - y) & M32, 2),
                           byte((0x7fff0001 - z) & M32, 1)],
     ((0xa5c3e187, 0xc2f0171d, 0x3d1e8f2b, 0), (0x13579bdf, 0x2468ace0, 0xf1e2d3c4, 0)),
     [(0, lambda x, y, z, w: byte(min(x + y, M32), 3)),  # saturating instead of wrapping
      (1, lambda x, y, z, w: byte((x - y) & M32, 0)),  # sub with the operands swapped
      (2, lambda x, y, z, w: byte((y - x) & M32, 2)),  # subrev as sub
      (3, lambda x, y, z, w: byte((z - 0x7fff0001) & M32, 1))]),  # subrev as sub
    # VOP3 clamp on the unsigned add, sub and subrev: saturation at both ends.
    ([
        "v_add_nc_u32_e64 v19, s44, s45 clamp",
        "v_sub_nc_u32_e64 v20, s44, s45 clamp",
        "v_subrev_nc_u32_e64 v21, s44, s45 clamp",
        "v_add_nc_u32_e64 v22, s44, s45",
        ubyte(0, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(2, 14, "v21", "e32"), ubyte(1, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(sat_u(x + y), 0), byte(sat_u(x - y), 3), byte(sat_u(y - x), 2), byte((x + y) & M32, 1)],
     ((0xa5c3e187, 0xc2f0171d, 0, 0), (0x93f1c2d4, 0x5a1b7e69, 0, 0)),
     [(0, lambda x, y, z, w: byte((x + y) & M32, 0)),  # clamp ignored
      (1, lambda x, y, z, w: byte((x - y) & M32, 3)),  # clamp ignored
      (2, lambda x, y, z, w: byte(sat_u(x - y), 2)),  # operands swapped
      (2, lambda x, y, z, w: byte((y - x) & M32, 2)),  # clamp ignored
      (3, lambda x, y, z, w: byte(sat_u(x + y), 1))]),  # clamp applied to the wrapping form
    # VOP3-only signed add and subtract: wrap, and clamp to INT_MAX and INT_MIN.
    ([
        "v_add_nc_i32 v19, s44, s45 clamp",
        "v_add_nc_i32 v20, s44, s45",
        "v_sub_nc_i32 v21, s44, s47 clamp",
        "v_sub_nc_i32_e64 v22, s44, s47",
        ubyte(3, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(sat_i(signed(x) + signed(y)), 3), byte((x + y) & M32, 3),
                           byte(sat_i(signed(x) - signed(w)), 3), byte((x - w) & M32, 3)],
     ((0x7ffffff0, 0x00000100, 0, 0xffffff00), (0x80000010, 0xffffff00, 0, 0x00000100),
      (0x00000010, 0xfffffff0, 0, 0xffffff00)),
     [(0, lambda x, y, z, w: byte(sat_u(x + y), 3)),  # unsigned saturation
      (0, lambda x, y, z, w: byte((x + y) & M32, 3)),  # clamp ignored
      (1, lambda x, y, z, w: byte(sat_i(signed(x) + signed(y)), 3)),  # clamp applied to the wrapping form
      (2, lambda x, y, z, w: byte(sat_u(x - w), 3)),  # unsigned saturation
      (2, lambda x, y, z, w: byte((x - w) & M32, 3)),  # clamp ignored
      (3, lambda x, y, z, w: byte(sat_i(signed(x) - signed(w)), 3))]),  # clamp applied to the wrapping form
    # 24-bit multiplies, low half: operands masked to 24 bits, i24 sign-extended from bit 23.
    ([
        copy(18, "s44"),
        "v_mul_u32_u24_e32 v19, s45, v18",
        "v_mul_i32_i24_e32 v20, s45, v18",
        "v_mul_i32_i24_e64 v21, s46, 0x00fffff1",
        "v_mul_u32_u24_e64 v22, 0x01000003, s47",
        ubyte(3, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((u24(y) * u24(x)) & M32, 3), byte((i24(y) * i24(x)) & M32, 3),
                           byte((i24(z) * -15) & M32, 3), byte((3 * u24(w)) & M32, 3)],
     ((0xa5c3e187, 0x3c1b7e69, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a96b45a, 0x4be3a05c, 0x1c2d3e4f)),
     [(0, lambda x, y, z, w: byte((y * x) & M32, 3)),  # no 24-bit mask
      (1, lambda x, y, z, w: byte((u24(y) * u24(x)) & M32, 3)),  # unsigned for signed
      (2, lambda x, y, z, w: byte((u24(z) * 0xfffff1) & M32, 3)),  # unsigned for signed
      (3, lambda x, y, z, w: byte((0x01000003 * w) & M32, 3))]),  # no 24-bit mask
    # 24-bit multiplies, high half: bits 47:32 of the unsigned product, bits 63:32 of the sign-extended product.
    ([
        copy(18, "s44"),
        "v_mul_hi_u32_u24_e32 v19, s45, v18",
        "v_mul_hi_i32_i24_e32 v20, s45, v18",
        "v_mul_hi_u32_u24_e64 v21, s46, s47",
        "v_mul_hi_i32_i24_e64 v22, s46, s47",
        ubyte(0, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(1, 14, "v21", "e32"), ubyte(0, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(hi_u(u24(y), u24(x)), 0), byte(((i24(y) * i24(x)) >> 32) & M32, 3),
                           byte(hi_u(u24(z), u24(w)), 1), byte(((i24(z) * i24(w)) >> 32) & M32, 0)],
     ((0xa5c3e187, 0x3c1b7e69, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a96b45a, 0x4be3a05c, 0x1c2d3e4f),
      (0x0123456f, 0x7a5c3b2d, 0x7d3e1f2c, 0x1b2c3d4e)),
     [(0, lambda x, y, z, w: byte((u24(y) * u24(x)) & M32, 0)),  # low half
      (0, lambda x, y, z, w: byte(hi_u(y, x), 0)),  # no 24-bit mask
      (1, lambda x, y, z, w: byte(hi_u(u24(y), u24(x)), 3)),  # unsigned for signed
      (1, lambda x, y, z, w: byte((i24(y) * i24(x)) & M32, 3)),  # low half
      (2, lambda x, y, z, w: byte((u24(z) * u24(w)) & M32, 1)),  # low half
      (3, lambda x, y, z, w: byte(hi_u(u24(z), u24(w)), 0)),  # unsigned for signed
      (3, lambda x, y, z, w: byte((i24(z) * i24(w)) & M32, 0))]),  # low half
    # VOP3-only 32-bit multiplies: low word, unsigned high word, signed high word with mixed and equal signs.
    ([
        "v_mul_lo_u32 v19, s44, s45",
        "v_mul_hi_u32 v20, s44, s45",
        "v_mul_hi_i32 v21, s44, s46",
        "v_mul_hi_i32_e64 v22, s46, s47",
        ubyte(2, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(1, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((x * y) & M32, 2), byte(hi_u(x, y), 3), byte(hi_i(x, z), 3), byte(hi_i(z, w), 1)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0xc4e3a05c, 0x8c8d9f10),
      (M32, M32, 0x7fffffff, 0x80000000)),
     [(0, lambda x, y, z, w: byte(hi_u(x, y), 2)),  # high word for low
      (1, lambda x, y, z, w: byte((x * y) & M32, 3)),  # low word for high
      (1, lambda x, y, z, w: byte(hi_i(x, y), 3)),  # signed for unsigned
      (2, lambda x, y, z, w: byte(hi_u(x, z), 3)),  # unsigned for signed
      (3, lambda x, y, z, w: byte(hi_u(z, w), 1)),  # unsigned for signed
      (3, lambda x, y, z, w: byte((z * w) & M32, 1))]),  # low word for high
    # Multiply-add with 24-bit operands: the addend is the third source; literal, inline constants.
    ([
        copy(18, "s46"),
        "v_mad_u32_u24 v19, s44, s45, v18",
        "v_mad_i32_i24 v20, s44, v18, s47",
        "v_mad_u32_u24 v21, 0x01000005, s46, 7",
        "v_mad_i32_i24_e64 v22, v18, -3, s47",
        ubyte(3, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((u24(x) * u24(y) + z) & M32, 3), byte((i24(x) * i24(z) + w) & M32, 3),
                           byte((5 * u24(z) + 7) & M32, 3), byte((i24(z) * -3 + w) & M32, 3)],
     ((0xa5c3e187, 0x3c1b7e69, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a96b45a, 0x4be3a05c, 0x1c2d3e4f)),
     [(0, lambda x, y, z, w: byte((u24(x) * u24(z) + y) & M32, 3)),  # operands in the wrong slots
      (0, lambda x, y, z, w: byte((x * y + z) & M32, 3)),  # no 24-bit mask
      (1, lambda x, y, z, w: byte((u24(x) * u24(z) + w) & M32, 3)),  # unsigned for signed
      (1, lambda x, y, z, w: byte((i24(x) * i24(w) + z) & M32, 3)),  # operands in the wrong slots
      (2, lambda x, y, z, w: byte((0x01000005 * z + 7) & M32, 3)),  # no 24-bit mask
      (3, lambda x, y, z, w: byte((u24(z) * 0xfffffd + w) & M32, 3))]),  # unsigned for signed
    # Multiply-add with 16-bit operands (v_mad_u32_u16, v_mad_i32_i16; ported from R0Y00/Xbox2Windows#532 by Vonsek): only
    # bits [15:0] of the first two sources are read, zero- or sign-extended, and the addend is the third source.
    ([
        copy(18, "s46"),
        "v_mad_u32_u16 v19, s44, s45, v18",
        "v_mad_i32_i16 v20, s44, v18, s47",
        "v_mad_u32_u16 v21, 0x2345, s46, 7",
        "v_mad_i32_i16 v22, v18, -3, s47",
        ubyte(3, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((u16(x) * u16(y) + z) & M32, 3), byte((i16(x) * i16(z) + w) & M32, 3),
                           byte((0x2345 * u16(z) + 7) & M32, 3), byte((i16(z) * -3 + w) & M32, 3)],
     ((0xa5c3e187, 0x3c1b7e69, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a96b45a, 0x4be3a05c, 0x1c2d3e4f),
      (0x0000ffff, 0xffff0003, 0x7fff8000, 0xfffe0001)),
     [(0, lambda x, y, z, w: byte((x * y + z) & M32, 3)),  # no 16-bit mask
      (0, lambda x, y, z, w: byte((u16(x) * u16(z) + y) & M32, 3)),  # operands in the wrong slots
      (1, lambda x, y, z, w: byte((u16(x) * u16(z) + w) & M32, 3)),  # unsigned for signed
      (2, lambda x, y, z, w: byte((0x2345 * z + 7) & M32, 3)),  # no 16-bit mask on the second source
      (3, lambda x, y, z, w: byte((u16(z) * 0xfffd + w) & M32, 3))]),  # unsigned for signed
    # Three-input adds and bitwise forms; the operand order matters for and_or.
    ([
        copy(18, "s46"),
        "v_add3_u32 v19, s44, s45, v18",
        "v_and_or_b32 v20, s44, v18, s45",
        "v_or3_b32 v21, s44, 0x0000f0f0, v18",
        "v_xor3_b32_e64 v22, v18, s45, s47",
        ubyte(2, 12, "v19", "e32"), ubyte(0, 13, "v20", "e32"), ubyte(1, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((x + y + z) & M32, 2), byte((x & z) | y, 0), byte(x | 0xf0f0 | z, 1), byte(z ^ y ^ w, 3)],
     ((0xa5c3e187, 0x3c96b45a, 0xc2f0171d, 0x6d1e8f2b), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(0, lambda x, y, z, w: byte((x + y) & M32, 2)),  # third source dropped
      (1, lambda x, y, z, w: byte((x & y) | z, 0)),  # operands in the wrong slots
      (1, lambda x, y, z, w: byte((x & z) & y, 0)),  # and for or
      (2, lambda x, y, z, w: byte(x | 0xf0f0, 1)),  # third source dropped
      (3, lambda x, y, z, w: byte(z | y | w, 3)),  # or for xor
      (3, lambda x, y, z, w: byte(z ^ y, 3))]),  # third source dropped
    # xad, and the shift-add forms: counts masked to five bits, counts above 31 in an SGPR and as an inline constant.
    ([
        copy(18, "s46"),
        copy(23, "s47"),
        "v_xad_u32 v19, s44, s45, v18",
        "v_lshl_add_u32 v20, s44, s45, v18",
        "v_add_lshl_u32 v21, s44, s45, v23",
        "v_lshl_or_b32 v22, s44, 33, v18",
        ubyte(1, 12, "v19", "e32"), ubyte(2, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(0, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(((x ^ y) + z) & M32, 1), byte(((x << (y & 31)) + z) & M32, 2),
                           byte(((x + y) << (w & 31)) & M32, 3), byte(((x << 1) | z) & M32, 0)],
     ((0xa5c3e187, 0x00000025, 0xc2f0171d, 0x0000003b), (0x83d5f2a9, 0x00000043, 0x13572468, 0x00000041),
      (0x12345678, 0x0000000d, 0x9abcdef0, 0x00000007)),
     [(0, lambda x, y, z, w: byte((((x + y) & M32) ^ z), 1)),  # add then xor
      (0, lambda x, y, z, w: byte(((x ^ y) ^ z), 1)),  # xor for add
      (1, lambda x, y, z, w: byte(((x << y) + z) & M32 if y < 32 else z, 2)),  # count not masked
      (1, lambda x, y, z, w: byte(((y << (x & 31)) + z) & M32, 2)),  # operands in the wrong slots
      (2, lambda x, y, z, w: byte(((x + y) << w) & M32 if w < 32 else 0, 3)),  # count not masked
      (2, lambda x, y, z, w: byte((x + (y << (w & 31))) & M32, 3)),  # shift applied to the wrong operand
      (3, lambda x, y, z, w: byte(z, 0)),  # count not masked
      (3, lambda x, y, z, w: byte(((x << 1) + z) & M32, 0))]),  # add for or
    # e32 spellings with a literal and with inline constants, the 24-bit mask of an all-ones constant.
    ([
        copy(18, "s44"),
        "v_add_nc_u32_e32 v19, 0x7ff00001, v18",
        "v_sub_nc_u32_e32 v20, 7, v18",
        "v_mul_hi_u32_u24_e32 v21, 0x00fedcba, v18",
        "v_mul_u32_u24_e32 v22, -1, v18",
        ubyte(2, 12, "v19", "e32"), ubyte(3, 13, "v20", "e32"), ubyte(0, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((0x7ff00001 + x) & M32, 2), byte((7 - x) & M32, 3), byte(hi_u(0xfedcba, u24(x)), 0),
                           byte((0xffffff * u24(x)) & M32, 3)],
     ((0xa5c3e187, 0, 0, 0), (0x93f1c2d4, 0, 0, 0)),
     [(0, lambda x, y, z, w: byte((0x7ff00001 + x) & M32, 3)),  # wrong byte
      (1, lambda x, y, z, w: byte((x - 7) & M32, 3)),  # operands swapped
      (2, lambda x, y, z, w: byte(hi_u(0xfedcba, x), 0)),  # no 24-bit mask
      (3, lambda x, y, z, w: byte((M32 * x) & M32, 3))]),  # no 24-bit mask on the constant
)


def check_arith_draws(directory, compiler, renderer, backend):
    case = directory / "arith.case"
    for index, (body, reference, sets, bugs) in enumerate(ARITH_PROGRAMS):
        source = directory / f"arith{index}.hlsl"
        shader = directory / f"arith{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = [float(value) for value in reference(*words)]
            for x in expected:
                assert half_rtz(x) == x, x
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for k, (channel, buggy) in enumerate(bugs):
                value = float(buggy(*words))
                if value == expected[channel]:
                    continue
                separated[k] = True
                assert half_rtz(value) == value, value
                wrong_values = list(expected)
                wrong_values[channel] = value
                case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong arithmetic result escaped detection in program {index}, channel {channel}, words {words}")
        assert all(separated), (index, separated)


def controls(directory):
    # Integer add, subtract, multiply and three-input forms: the lowering, then refusals.
    source = translate(with_constants(ARITH_PROGRAMS[5][0])).split("float4 main", 1)[1]
    assert "mul_hi_u32(" in source and "mul_hi_i32(" in source
    assert "uint mul_hi_u32(" in translate(with_constants(ARITH_PROGRAMS[5][0]))
    assert "uint v_add_sat_i32(" in translate(with_constants(ARITH_PROGRAMS[2][0]))
    assert "mul_hi_u32(" not in translate(with_constants(INT_PROGRAMS[0][0]))
    for line in ("v_add_nc_u32_e64 v19, -s44, v18", "v_sub_nc_u32_e64 v19, s44, -v18", "v_subrev_nc_u32_e64 v19, |s44|, v18",
                 "v_mul_u32_u24_e64 v19, -s44, v18", "v_mul_hi_i32_i24_e64 v19, s44, |v18|", "v_add_nc_i32 v19, -s44, v18",
                 "v_mul_lo_u32 v19, |s44|, v18", "v_mad_u32_u24 v19, -s44, v18, 5", "v_add3_u32 v19, -s44, s45, v18",
                 "v_xad_u32 v19, s44, -s45, v18", "v_lshl_or_b32 v19, s44, 3, -v18",
                 "v_add_nc_u32_e64 v19, s44, v18 mul:2", "v_mul_lo_u32 v19, s44, v18 mul:2", "v_add3_u32 v19, s44, s45, v18 mul:2",
                 "v_add_nc_u32_e64 v19, s44, v18 div:2"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    # clamp that llvm-mc rejects, and clamp on forms that llvm-mc assembles but whose saturation is not modelled.
    for line in ("v_add_nc_u32_e32 v19, s44, v18 clamp", "v_add3_u32 v19, s44, s45, v18 clamp",
                 "v_xad_u32 v19, s44, s45, v18 clamp", "v_lshl_add_u32 v19, s44, s45, v18 clamp",
                 "v_and_or_b32 v19, s44, s45, v18 clamp", "v_mul_lo_u32 v19, s44, v18 clamp",
                 "v_mul_hi_u32 v19, s44, v18 clamp", "v_mul_hi_u32_u24_e64 v19, s44, v18 clamp",
                 "v_mul_u32_u24_e64 v19, s44, v18 clamp", "v_mul_i32_i24_e64 v19, s44, v18 clamp",
                 "v_mad_u32_u24 v19, s44, v18, 5 clamp", "v_mad_i32_i24 v19, s44, v18, 5 clamp",
                 "v_mad_u32_u16 v19, s44, v18, 5 clamp", "v_mad_i32_i16 v19, s44, v18, 5 clamp",
                 "v_mul_lo_u32_e32 v19, s44, v18", "v_add_nc_i32_e32 v19, s44, v18"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    for line in ("v_add_nc_u32_e32 v19, s44, v30", "v_sub_nc_u32_e32 v19, v30, v18", "v_mul_i32_i24_e32 v19, s44, v30",
                 "v_mul_hi_u32 v19, s44, v30", "v_add3_u32 v19, s44, v30, v18", "v_xad_u32 v19, s44, v18, v30",
                 "v_add_nc_u32_e32 v19, s90, v18", "v_add3_u32 v19, m0, s44, v18"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    plain = with_constants(["v_mov_b32_e32 v18, s45", "v_add3_u32 v19, s44, 3, v18", "v_cvt_f32_ubyte0_e32 v12, v19"])
    assert "uint valu" in translate(plain)
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_add_nc_u32_e32 v18, s44, v13", "v_mul_u32_u24_e32 v18, s44, v13", "v_mul_hi_i32 v18, s44, v13",
                  "v_add3_u32 v18, s44, 3, v13", "v_xad_u32 v18, v13, 3, 5", "v_add3_u32 v13, s44, 3, 5",
                  "v_add_nc_u32_e64 v14, s44, 5"):
        must_reject(translate, program[:wait] + [early] + program[wait:])
    program = with_constants(["v_mov_b32_e32 v18, s45"])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("v_add_nc_u32_e32 v19, s44, v18", "v_mul_lo_u32 v19, s44, v18", "v_add3_u32 v19, s44, s45, v18"):
        must_reject(translate, program[:load] + [early] + program[load:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for body, *_ in ARITH_PROGRAMS),
    ]


draw = check_arith_draws
