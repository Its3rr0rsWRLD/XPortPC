"""Draw family `int`: pixel_aot_check.py draw --family int."""
import struct
import subprocess

from .common import M32, assembly, byte, half_rtz, must_reject, signed, translate, ubyte, with_constants


# 32-bit vector integer values, byte readback, bitwise operations and shifts. Each draw exports four bytes:
# v_cvt_f32_ubyteN turns byte N into the exact float 0..255, which the half export keeps exactly.
# Words that pass through a v_mov_b32 are float-normal (a nonzero, non-255 exponent field), so a round trip
# through binary32 cannot change them. Shift counts are words with bits above the low five set, and the shifted
# values have the top bit set, so a count that is not masked, a logical shift where an arithmetic one is
# required, and operands in the written order all give different bytes. Each program has wrong references
# (channel, function of the words) built from those plausible bugs.
reverse_bits = lambda value: int(f"{value:032b}"[::-1], 2)
arith_shift = lambda value, count: (signed(value) >> count) & M32
exponent = lambda word: (word >> 23) & 0xff


INT_PROGRAMS = (
    # Bitwise operations, e32: an SGPR, a literal and an inline constant against a register, bytes 0 to 3.
    ([
        "v_mov_b32_e32 v18, s45",
        "v_and_b32_e32 v19, s44, v18",
        "v_or_b32_e32 v20, 0x0f0f0f0f, v18",
        "v_xor_b32_e32 v21, s46, v18",
        "v_xnor_b32_e32 v22, 5, v18",
        ubyte(0, 12, "v19", "e32"), ubyte(1, 13, "v20", "e32"), ubyte(2, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(x & y, 0), byte(0x0f0f0f0f | y, 1), byte(z ^ y, 2), byte(~(5 ^ y) & M32, 3)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(3, lambda x, y, z, w: byte(5 ^ y, 3)),  # xor for xnor
      (0, lambda x, y, z, w: byte(x & y, 1)),  # wrong byte
      (1, lambda x, y, z, w: byte(0x0f0f0f0f & y, 1)),  # and for or
      (2, lambda x, y, z, w: byte(~(z ^ y) & M32, 2))]),  # xnor for xor
    # Bitwise operations, e64 and the e64 byte converts.
    ([
        "v_mov_b32_e32 v18, s45",
        "v_and_b32_e64 v19, 63, v18",
        "v_or_b32_e64 v20, s47, v18",
        "v_xor_b32_e64 v21, s46, v18",
        "v_xnor_b32_e64 v22, s44, v18",
        ubyte(0, 12, "v19", "e64"), ubyte(3, 13, "v20", "e64"), ubyte(1, 14, "v21", "e64"), ubyte(2, 15, "v22", "e64"),
    ], lambda x, y, z, w: [byte(63 & y, 0), byte(w | y, 3), byte(z ^ y, 1), byte(~(x ^ y) & M32, 2)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(3, lambda x, y, z, w: byte(x ^ y, 2)),
      (0, lambda x, y, z, w: byte(63 | y, 0)),
      (1, lambda x, y, z, w: byte(w & y, 3)),
      (2, lambda x, y, z, w: byte(z ^ y, 2))]),
    # not and bit reversal, both spellings, a register source for the reversal.
    ([
        "v_not_b32_e32 v18, s44",
        "v_not_b32_e64 v19, s45",
        "v_bfrev_b32_e32 v20, s46",
        "v_bfrev_b32_e64 v21, v19",
        ubyte(3, 12, "v18", "e32"), ubyte(1, 13, "v19", "e32"), ubyte(0, 14, "v20", "e64"), ubyte(2, 15, "v21", "e64"),
    ], lambda x, y, z, w: [byte(~x & M32, 3), byte(~y & M32, 1), byte(reverse_bits(z), 0), byte(reverse_bits(~y & M32), 2)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(0, lambda x, y, z, w: byte(x, 3)),  # no inversion
      (1, lambda x, y, z, w: byte(y, 1)),  # no inversion in the e64 form
      (2, lambda x, y, z, w: byte(z, 3)),  # bytes swapped, bits kept
      (3, lambda x, y, z, w: byte(~y & M32, 2))]),  # reversal dropped
    # Shifts, e32. The count is the first source: an inline constant, then SGPR words with the high bits set.
    ([
        "v_mov_b32_e32 v18, s44",
        "v_lshlrev_b32_e32 v19, 4, v18",
        "v_lshrrev_b32_e32 v20, s45, v18",
        "v_ashrrev_i32_e32 v21, s46, v18",
        "v_lshlrev_b32_e32 v22, s47, v18",
        ubyte(2, 12, "v19", "e32"), ubyte(1, 13, "v20", "e32"), ubyte(3, 14, "v21", "e32"), ubyte(3, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte((x << 4) & M32, 2), byte(x >> (y & 31), 1), byte(arith_shift(x, z & 31), 3),
                           byte((x << (w & 31)) & M32, 3)],
     ((0xa5c3e187, 0x00000025, 0xffffffe3, 0x3c96b45a), (0x83d5f2a9, 0x00000041, 0x7ffffff8, 0x0000003b)),
     [(0, lambda x, y, z, w: byte((4 << (x & 31)) & M32, 2)),  # operands in the written order
      (1, lambda x, y, z, w: byte(x >> y if y < 32 else 0, 1)),  # count not masked
      (2, lambda x, y, z, w: byte(x >> (z & 31), 3)),  # logical for arithmetic
      (3, lambda x, y, z, w: byte((x << w) & M32 if w < 32 else 0, 3))]),  # count not masked
    # Shifts, e64: SGPR count, inline count above 31, a literal count with high bits, a literal shifted value.
    ([
        "v_mov_b32_e32 v18, s44",
        "v_lshlrev_b32_e64 v19, s45, v18",
        "v_lshrrev_b32_e64 v20, 33, v18",
        "v_ashrrev_i32_e64 v21, 0xffff0023, v18",
        "v_ashrrev_i32_e64 v22, s46, 0x8000c3a5",
        ubyte(1, 12, "v19", "e64"), ubyte(3, 13, "v20", "e64"), ubyte(3, 14, "v21", "e64"), ubyte(3, 15, "v22", "e64"),
    ], lambda x, y, z, w: [byte((x << (y & 31)) & M32, 1), byte(x >> 1, 3), byte(arith_shift(x, 3), 3),
                           byte(arith_shift(0x8000c3a5, z & 31), 3)],
     ((0xa5c3e187, 0x00000025, 0xffffffe3, 0), (0x83d5f2a9, 0x00000041, 0x7fffffe5, 0)),
     [(0, lambda x, y, z, w: byte((x << y) & M32 if y < 32 else 0, 1)),  # count not masked
      (1, lambda x, y, z, w: byte(arith_shift(x, 1), 3)),  # arithmetic for logical
      (2, lambda x, y, z, w: byte(x >> 3, 3)),  # logical for arithmetic
      (3, lambda x, y, z, w: byte(0x8000c3a5 >> (z & 31), 3)),  # logical for arithmetic
      (3, lambda x, y, z, w: byte(arith_shift(z, 0x8000c3a5 & 31), 3))]),  # operands in the written order
    # Byte converts straight from an SGPR, a literal and an inline constant, with clamp in the e64 form.
    ([
        ubyte(0, 12, "s44", "e32"),
        ubyte(1, 13, "s45", "e64"),
        ubyte(2, 14, "0xab0000", "e32"),
        ubyte(3, 15, "s47", "e64", clamp=True),
    ], lambda x, y, z, w: [byte(x, 0), byte(y, 1), 0xab, min(byte(w, 3), 1)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x00ffffff)),
     [(0, lambda x, y, z, w: byte(x, 1)),
      (1, lambda x, y, z, w: byte(y, 0)),
      (2, lambda x, y, z, w: 0xab0000 & 0xff),
      (3, lambda x, y, z, w: byte(w, 3))]),  # clamp ignored
    # Byte converts of a numeric register, an inline float and a negative inline integer.
    ([
        "v_mov_b32_e32 v18, s44",
        ubyte(1, 12, "v18", "e32"),
        ubyte(2, 13, "1.0", "e64"),
        ubyte(0, 14, "-2", "e32"),
        ubyte(3, 15, "v18", "e64"),
    ], lambda x, y, z, w: [byte(x, 1), 0x80, 0xfe, byte(x, 3)],
     ((0xa5c3e187, 0, 0, 0), (0x93f1c2d4, 0, 0, 0)),
     [(1, lambda x, y, z, w: byte(0x3f800000, 3)),
      (2, lambda x, y, z, w: 0x02),
      (3, lambda x, y, z, w: byte(x, 2))]),
)


def check_int_draws(directory, compiler, renderer, backend):
    case = directory / "int.case"
    for index, (body, reference, sets, bugs) in enumerate(INT_PROGRAMS):
        source = directory / f"int{index}.hlsl"
        shader = directory / f"int{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for words in sets:
            if "v_mov_b32_e32 v18, s45" in body:
                assert 0 < exponent(words[1]) < 255, hex(words[1])
            if "v_mov_b32_e32 v18, s44" in body:
                assert 0 < exponent(words[0]) < 255, hex(words[0])
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
                    raise AssertionError(f"A wrong integer result escaped detection in program {index}, channel {channel}, words {words}")
        assert all(separated), (index, separated)


def controls(directory):
    # Integer vector values: the lowering, then refusals for modifiers, clamp, unset registers and pending samples.
    source = translate(with_constants(INT_PROGRAMS[3][0])).split("float4 main", 1)[1]
    assert "asint(" in source and "<< (" in source and "& 31u" in source
    for line in ("v_and_b32_e64 v19, -s44, v18", "v_xor_b32_e64 v19, -v18, s44", "v_or_b32_e64 v19, |s44|, v18",
                 "v_not_b32_e64 v19, -s44", "v_lshlrev_b32_e64 v19, -s44, v18",
                 "v_and_b32_e64 v19, s44, v18 clamp", "v_and_b32_e64 v19, s44, v18 mul:2",
                 "v_cvt_f32_ubyte0_e64 v19, -s44", "v_cvt_f32_ubyte0_e64 v19, s44 mul:2",
                 "v_cvt_f32_ubyte0_e32 v19, s44 clamp",
                 "v_and_b32_e32 v19, s44, v30", "v_and_b32_e32 v19, v30, v18", "v_not_b32_e32 v19, v30",
                 "v_bfrev_b32_e32 v19, v30", "v_ashrrev_i32_e32 v19, s44, v30", "v_cvt_f32_ubyte1_e32 v19, v30",
                 "v_and_b32_e32 v19, s90, v18", "v_lshrrev_b32_e32 v19, m0, v18"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", line]))
    plain = with_constants(["v_mov_b32_e32 v18, s45", "v_and_b32_e32 v19, s44, v18", "v_cvt_f32_ubyte0_e32 v12, v19"])
    assert "uint valu" in translate(plain)
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_cvt_f32_ubyte0_e32 v18, v13", "v_and_b32_e32 v18, s44, v13", "v_not_b32_e32 v18, v13",
                  "v_cvt_f32_ubyte0_e32 v13, 5", "v_not_b32_e32 v13, 5"):
        must_reject(translate, program[:wait] + [early] + program[wait:])
    assert "& 255u" in translate(program[:wait + 1] + ["v_cvt_f32_ubyte0_e32 v18, v13"] + program[wait + 1:])
    program = with_constants(["v_mov_b32_e32 v18, s45"])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("v_not_b32_e32 v19, s44", "v_cvt_f32_ubyte0_e32 v19, s44", "v_and_b32_e32 v19, s44, v18"):
        must_reject(translate, program[:load] + [early] + program[load:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for body, *_ in INT_PROGRAMS),
    ]


draw = check_int_draws
