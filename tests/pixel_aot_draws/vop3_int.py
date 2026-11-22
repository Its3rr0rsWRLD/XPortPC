"""Draw family `vop3_int`: pixel_aot_check.py draw --family vop3_int.

The VOP3-only integer and bit forms of tools/pixel_aot_ops/forms/valu_vop3int.py: v_bfi_b32, v_alignbit_b32,
v_alignbyte_b32, v_perm_b32, v_sad_u8, v_sad_hi_u8, v_sad_u16, v_sad_u32, v_msad_u8, v_lerp_u8, v_mad_u64_u32, the plain spelling of v_xor3_b32 and the 64-bit
shifts v_lshlrev_b64, v_lshrrev_b64 and v_ashrrev_i64. Semantics are the RDNA 2 ISA guide's, in unsigned words.

Table driven: a row is (name, body, result registers, reads, reference, constant sets, wrong references). The reference
returns the result words (a 64-bit result as low then high word, then the carry where there is one). `reads` names the four
channels: ("b", word, byte) reads one byte of a result word through v_cvt_f32_ubyteN, ("c", word) reads the lane-mask carry
through v_cndmask_b32. Each wrong reference is a plausible bug (wrong operand order, a byte selector off by one, signed for
unsigned, a dropped carry); importing this module asserts that each differs from the reference on some read channel of some
constant set, and the draw check confirms that the renderer reports a mismatch for every such channel. A 64-bit result gets
a row for its low word and one for its high word. Sources are copied into VGPRs first, so that no instruction reads more
than two SGPRs.
"""
import struct
import subprocess

from .arith import copy
from .common import M32, assembly, byte, half_rtz, must_reject, signed, translate, ubyte, with_constants

M64 = (1 << 64) - 1
SETUP = {"x": copy(18, "s44"), "y": copy(23, "s45"), "z": copy(24, "s46"), "w": copy(25, "s47")}
PAIR = [copy(26, "s46"), copy(27, "s47")]
WORD = tuple(("b", 0, n) for n in range(4))
LO = (("b", 0, 0), ("b", 0, 2), ("b", 0, 3), ("c", 2))
HI = (("b", 1, 0), ("b", 1, 1), ("b", 1, 3), ("c", 2))
LO_NC = tuple(("b", 0, n) for n in range(4))
HI_NC = tuple(("b", 1, n) for n in range(4))

# ---- references ---------------------------------------------------------------------------------------------------


def bfi(m, a, b):
    return ((m & a) | (~m & b)) & M32


def alignbit(hi, lo, n):
    return ((hi << 32 | lo) >> n) & M32


def perm(hi, lo, sel_word, *, sign_shift=0, wrap=False, plus=0, twelve=0):
    """v_perm_b32; the keyword arguments build the wrong references (sign bit taken `sign_shift` lower, selectors wrapped
    to four bits, byte index off by `plus`, selector 12 giving `twelve`)."""
    data = hi << 32 | lo
    out = 0
    for n in range(4):
        sel = (sel_word >> 8 * n) & 255
        if wrap:
            sel &= 15
        if sel >= 13:
            value = 0xff
        elif sel == 12:
            value = twelve
        elif sel >= 8:
            value = 0xff if data >> (15 + 16 * (sel - 8) - sign_shift) & 1 else 0
        else:
            value = data >> 8 * ((sel + plus) & 7) & 255
        out |= value << 8 * n
    return out


def sad8(a, b, *, masked=False, signed_bytes=False, count=4):
    total = 0
    for n in range(count):
        p, q = byte(a, n), byte(b, n)
        if masked and q == 0:
            continue
        if signed_bytes:
            p, q = p - ((p >> 7) << 8), q - ((q >> 7) << 8)
        total += abs(p - q)
    return total


def s16(v):
    return (v & 0xffff) - ((v & 0x8000) << 1)


def lerp(a, b, c, round_bit=lambda c, n: c >> 8 * n & 1):
    out = 0
    for n in range(4):
        out |= (((byte(a, n) + byte(b, n) + round_bit(c, n)) >> 1) & 255) << 8 * n
    return out


def shift64(op, value, count):
    n = count & 63
    if op == "lshlrev_b64":
        return (value << n) & M64
    if op == "lshrrev_b64":
        return value >> n
    return ((value - ((value >> 63) << 64)) >> n) & M64


def mad64(a, b, c):
    total = a * b + c
    return total & M64, total >> 64


def words(value):
    return value & M32, value >> 32


# ---- the table ----------------------------------------------------------------------------------------------------

ROWS = []


GROUPS = {}


def add(name, instructions, dst, reads, reference, sets, bugs, setup="xyz", pair=False, group=None):
    body = [*(SETUP[c] for c in setup), *(PAIR if pair else []), *instructions]
    for channel, (kind, word, *rest) in enumerate(reads):
        body.append(ubyte(rest[0], 12 + channel, dst[word], "e32") if kind == "b"
                    else f"v_cndmask_b32_e64 v{12 + channel}, 0, 1.0, s52")
    # The carry row reads vcc_lo for the rows whose instruction names it.
    if any("vcc_lo" in line and line.startswith("v_mad_u64") for line in instructions):
        body = [line.replace("1.0, s52", "1.0, vcc_lo") for line in body]
    differs = {label: any(read(reads, buggy(*s)) != read(reads, reference(*s)) for s in sets) for label, buggy in bugs.items()}
    if group:
        # A 64-bit result has a row per word: a bug that only changes the other word is checked by the other row.
        seen = GROUPS.setdefault(group, {label: False for label in bugs})
        for label, found in differs.items():
            seen[label] |= found
        bugs = {label: buggy for label, buggy in bugs.items() if differs[label]}
    else:
        for label, found in differs.items():
            assert found, (name, label, "never differs")
    ROWS.append((name, body, reads, reference, sets, bugs))


def read(reads, result):
    return [byte(result[word], rest[0]) if kind == "b" else result[word] for kind, word, *rest in reads]


def one(f):
    return lambda x, y, z, w: (f(x, y, z, w),)


def one_word(name, instruction, reference, sets, bugs, setup="xyz"):
    add(name, [instruction], ["v19"], WORD, one(reference), sets, {k: one(f) for k, f in bugs.items()}, setup)


# v_bfi_b32: D = (S0 & S1) | (~S0 & S2).
BFI_SETS = ((0xff00ff00, 0xa5c3e187, 0x3c96b45a, 0), (0x0f0f33cc, 0x12345678, 0x9abcdef0, 0), (0, M32, 0x80000001, 0),
            (M32, 0x13572468, 0xfedcba98, 0))
BFI_BUGS = {"select_swapped": lambda x, y, z, w: bfi(x, z, y),
            "mask_in_wrong_slot": lambda x, y, z, w: bfi(y, x, z),
            "complement_dropped": lambda x, y, z, w: (x & y) | (x & z),
            "operands_rotated": lambda x, y, z, w: bfi(z, x, y)}
one_word("bfi_vgpr", "v_bfi_b32 v19, v18, v23, v24", lambda x, y, z, w: bfi(x, y, z), BFI_SETS, BFI_BUGS)
one_word("bfi_mixed", "v_bfi_b32 v19, 0x00ff00ff, v23, s46", lambda x, y, z, w: bfi(0x00ff00ff, y, z), BFI_SETS,
         {"literal_as_data": lambda x, y, z, w: bfi(y, 0x00ff00ff, z), "select_swapped": lambda x, y, z, w: bfi(0x00ff00ff, z, y),
          "complement_dropped": lambda x, y, z, w: (0x00ff00ff & y) | (0x00ff00ff & z)})

# v_alignbit_b32 and v_alignbyte_b32: {S0, S1} shifted right, S0 the high word; the count is S2[4:0] bits or S2[1:0] bytes.
ALIGN_SETS = ((0xa5c3e187, 0x3c96b45a, 0x00000025, 0), (0x13572468, 0xfedcba98, 0x00000040, 0),
              (0x80000001, 0x7fffffff, 0x0000001f, 0), (0xdeadbeef, 0x01234567, 0x00000000, 0),
              (0x89abcdef, 0x76543210, 0xffffffe3, 0))
add_bit = lambda hi, lo, n: alignbit(hi, lo, n)
one_word("alignbit_vgpr", "v_alignbit_b32 v19, v18, v23, v24", lambda x, y, z, w: alignbit(x, y, z & 31), ALIGN_SETS,
         {"operands_swapped": lambda x, y, z, w: alignbit(y, x, z & 31),
          "count_masked_to_six_bits": lambda x, y, z, w: alignbit(x, y, z & 63) if z & 63 < 64 else 0,
          "high_word_dropped": lambda x, y, z, w: y >> (z & 31),
          "shift_left": lambda x, y, z, w: ((x << 32 | y) << (z & 31) >> 32) & M32,
          "count_off_by_one": lambda x, y, z, w: alignbit(x, y, (z + 1) & 31)})
one_word("alignbit_inline", "v_alignbit_b32 v19, v18, v23, 7", lambda x, y, z, w: alignbit(x, y, 7), ALIGN_SETS,
         {"operands_swapped": lambda x, y, z, w: alignbit(y, x, 7), "count_off_by_one": lambda x, y, z, w: alignbit(x, y, 8),
          "high_word_dropped": lambda x, y, z, w: y >> 7})
one_word("alignbit_sgpr", "v_alignbit_b32 v19, 0x80000001, v23, s46", lambda x, y, z, w: alignbit(0x80000001, y, z & 31),
         ALIGN_SETS, {"operands_swapped": lambda x, y, z, w: alignbit(y, 0x80000001, z & 31),
                      "count_unmasked": lambda x, y, z, w: alignbit(0x80000001, y, min(z, 63)) if z < 64 else 0})
BYTE_SETS = ((0xa5c3e187, 0x3c96b45a, 0, 0), (0x13572468, 0xfedcba98, 1, 0), (0x80000001, 0x7fffffff, 2, 0),
             (0xdeadbeef, 0x01234567, 3, 0), (0x89abcdef, 0x76543210, 5, 0), (0x01020304, 0x05060708, 0xfffffff7, 0))
one_word("alignbyte_vgpr", "v_alignbyte_b32 v19, v18, v23, v24", lambda x, y, z, w: alignbit(x, y, 8 * (z & 3)), BYTE_SETS,
         {"operands_swapped": lambda x, y, z, w: alignbit(y, x, 8 * (z & 3)),
          "byte_count_off_by_one": lambda x, y, z, w: alignbit(x, y, 8 * ((z + 1) & 3)),
          "count_in_bits": lambda x, y, z, w: alignbit(x, y, z & 31),
          "count_masked_to_three_bits": lambda x, y, z, w: alignbit(x, y, 8 * (z & 7)) if z & 7 < 8 else 0,
          "high_word_dropped": lambda x, y, z, w: y >> 8 * (z & 3)})
one_word("alignbyte_inline", "v_alignbyte_b32 v19, v18, 0x11223344, 3", lambda x, y, z, w: alignbit(x, 0x11223344, 24),
         BYTE_SETS, {"operands_swapped": lambda x, y, z, w: alignbit(0x11223344, x, 24),
                     "byte_count_off_by_one": lambda x, y, z, w: alignbit(x, 0x11223344, 16),
                     "count_in_bits": lambda x, y, z, w: alignbit(x, 0x11223344, 3)}, "x")

# v_perm_b32: selector bytes 0-3 pick S1 bytes, 4-7 S0 bytes, 8-11 the sign of bytes 1, 3, 5, 7, 12 zero, 13+ 0xff.
PERM_SETS = ((0x8190a1b2, 0x7f80ff01, 0x03020100, 0), (0x8190a1b2, 0x7f80ff01, 0x07060504, 0),
             (0x8190a1b2, 0x7f80ff01, 0x0b0a0908, 0), (0x8190a1b2, 0x7f80ff01, 0x0f0e0d0c, 0),
             (0x8190a1b2, 0x7f80ff01, 0x0c0d0e80, 0), (0x00ff7f80, 0x80ff00f0, 0x0a09080b, 0),
             (0x00ff7f80, 0x80ff00f0, 0x1c0c0b04, 0), (0x00ff7f80, 0x80ff00f0, 0x00010203, 0),
             (0x7f0080ff, 0x00807fff, 0x04050607, 0), (0x7f0080ff, 0x00807fff, 0x090a0b08, 0))
PERM_BUGS = {"operands_swapped": lambda x, y, z, w: perm(y, x, z),
             "selector_off_by_one": lambda x, y, z, w: perm(x, y, z, plus=1),
             "selector_twelve_is_ff": lambda x, y, z, w: perm(x, y, z, twelve=0xff),
             "selector_wrapped": lambda x, y, z, w: perm(x, y, z, wrap=True),
             "sign_of_byte_not_bit_15": lambda x, y, z, w: perm(x, y, z, sign_shift=8)}
one_word("perm_vgpr", "v_perm_b32 v19, v18, v23, v24", lambda x, y, z, w: perm(x, y, z), PERM_SETS, PERM_BUGS)
one_word("perm_sgpr_selector", "v_perm_b32 v19, v18, v23, s46", lambda x, y, z, w: perm(x, y, z), PERM_SETS, PERM_BUGS, "xy")
one_word("perm_inline", "v_perm_b32 v19, 0x01020304, v23, v24", lambda x, y, z, w: perm(0x01020304, y, z), PERM_SETS,
         {"operands_swapped": lambda x, y, z, w: perm(y, 0x01020304, z),
          "selector_off_by_one": lambda x, y, z, w: perm(0x01020304, y, z, plus=1)}, "yz")

# Sum of absolute differences.
SAD_SETS = ((0xff80017f, 0x00ff8001, 0x12345678, 0), (0xa5c3e187, 0x3c96b45a, 0xfffffff0, 0), (0, M32, 0xffffff00, 0),
            (0x80008000, 0x7fff7fff, 0x00000001, 0), (0x0001ffff, 0xffff0001, 0x80000000, 0), (0x91a2b3c4, 0x00d00080, 7, 0))
one_word("sad_u8", "v_sad_u8 v19, v18, v23, v24", lambda x, y, z, w: (sad8(x, y) + z) & M32, SAD_SETS,
         {"signed_bytes": lambda x, y, z, w: (sad8(x, y, signed_bytes=True) + z) & M32,
          "addend_dropped": lambda x, y, z, w: sad8(x, y) & M32,
          "top_byte_dropped": lambda x, y, z, w: (sad8(x, y, count=3) + z) & M32,
          "addend_in_wrong_slot": lambda x, y, z, w: (sad8(x, z) + y) & M32,
          "sum_shifted": lambda x, y, z, w: ((sad8(x, y) << 16) + z) & M32})
one_word("sad_u8_inline", "v_sad_u8 v19, v18, 0x40ff1002, 9", lambda x, y, z, w: (sad8(x, 0x40ff1002) + 9) & M32,
         SAD_SETS, {"signed_bytes": lambda x, y, z, w: (sad8(x, 0x40ff1002, signed_bytes=True) + 9) & M32,
                    "addend_dropped": lambda x, y, z, w: sad8(x, 0x40ff1002) & M32}, "x")
one_word("sad_hi_u8", "v_sad_hi_u8 v19, v18, v23, v24", lambda x, y, z, w: ((sad8(x, y) << 16) + z) & M32, SAD_SETS,
         {"not_shifted": lambda x, y, z, w: (sad8(x, y) + z) & M32,
          "shifted_by_eight": lambda x, y, z, w: ((sad8(x, y) << 8) + z) & M32,
          "signed_bytes": lambda x, y, z, w: ((sad8(x, y, signed_bytes=True) << 16) + z) & M32,
          "addend_dropped": lambda x, y, z, w: (sad8(x, y) << 16) & M32,
          "top_byte_dropped": lambda x, y, z, w: ((sad8(x, y, count=3) << 16) + z) & M32})
sad16 = lambda a, b: abs((a & 0xffff) - (b & 0xffff)) + abs((a >> 16) - (b >> 16))
one_word("sad_u16", "v_sad_u16 v19, v18, v23, v24", lambda x, y, z, w: (sad16(x, y) + z) & M32, SAD_SETS,
         {"signed_halves": lambda x, y, z, w: (abs(s16(x) - s16(y)) + abs(s16(x >> 16) - s16(y >> 16)) + z) & M32,
          "low_half_only": lambda x, y, z, w: (abs((x & 0xffff) - (y & 0xffff)) + z) & M32,
          "full_word_difference": lambda x, y, z, w: (abs(x - y) + z) & M32,
          "addend_dropped": lambda x, y, z, w: sad16(x, y) & M32,
          "addend_in_wrong_slot": lambda x, y, z, w: (sad16(x, z) + y) & M32})
one_word("sad_u32", "v_sad_u32 v19, v18, v23, v24", lambda x, y, z, w: (abs(x - y) + z) & M32, SAD_SETS,
         {"signed_difference": lambda x, y, z, w: (abs(signed(x) - signed(y)) + z) & M32,
          "no_absolute_value": lambda x, y, z, w: (x - y + z) & M32,
          "reversed_no_absolute_value": lambda x, y, z, w: (y - x + z) & M32,
          "addend_dropped": lambda x, y, z, w: abs(x - y) & M32,
          "addend_in_wrong_slot": lambda x, y, z, w: (abs(x - z) + y) & M32})
MSAD_SETS = ((0xff80017f, 0x00ff8001, 0x12345678, 0), (0xa5c3e187, 0x3c00b4ff, 0xfffffff0, 0), (0x01020304, 0x00000000, 5, 0),
             (0x80008000, 0x7f007f00, 0x00000001, 0), (0x91a2b3c4, 0x00d00080, 7, 0), (0x11223344, 0x00ff0000, 0, 0))
one_word("msad_u8", "v_msad_u8 v19, v18, v23, v24", lambda x, y, z, w: (sad8(x, y, masked=True) + z) & M32, MSAD_SETS,
         {"unmasked": lambda x, y, z, w: (sad8(x, y) + z) & M32,
          "mask_on_first_source": lambda x, y, z, w: (sad8(y, x, masked=True) + z) & M32,
          "signed_bytes": lambda x, y, z, w: (sad8(x, y, masked=True, signed_bytes=True) + z) & M32,
          "addend_dropped": lambda x, y, z, w: sad8(x, y, masked=True) & M32,
          "top_byte_dropped": lambda x, y, z, w: (sad8(x, y, masked=True, count=3) + z) & M32})

# v_lerp_u8: per byte (S0 + S1 + S2[8n]) >> 1.
LERP_SETS = ((0xff01fe80, 0x01ff0181, 0x01010100, 0), (0xffffffff, 0xffffffff, 0x01010101, 0), (0xffffffff, 0xffffffff, 0, 0),
             (0x7f7f7f7f, 0x01010101, 0x00010001, 0), (0xa5c3e187, 0x3c96b45a, 0xfffffffe, 0), (0x01020304, 0x04030201, 0x80808080, 0))
one_word("lerp_u8", "v_lerp_u8 v19, v18, v23, v24", lambda x, y, z, w: lerp(x, y, z), LERP_SETS,
         {"rounding_from_bit_zero_only": lambda x, y, z, w: lerp(x, y, z, lambda c, n: c & 1),
          "no_rounding": lambda x, y, z, w: lerp(x, y, z, lambda c, n: 0),
          "always_rounded": lambda x, y, z, w: lerp(x, y, z, lambda c, n: 1),
          "rounding_from_bit_seven": lambda x, y, z, w: lerp(x, y, z, lambda c, n: c >> (8 * n + 7) & 1),
          "word_add_not_per_byte": lambda x, y, z, w: (((x + y + (z & 0x01010101)) >> 1) & 0x7f7f7f7f)})
one_word("lerp_u8_literal", "v_lerp_u8 v19, v18, 0x10ff80c3, 1", lambda x, y, z, w: lerp(x, 0x10ff80c3, 1), LERP_SETS,
         {"no_rounding": lambda x, y, z, w: lerp(x, 0x10ff80c3, 1, lambda c, n: 0),
          "rounding_on_every_byte": lambda x, y, z, w: lerp(x, 0x10ff80c3, 1, lambda c, n: 1)}, "x")

# v_xor3_b32, already lowered (valu_int) but drawn so far only as v_xor3_b32_e64, which the form list counts as another form.
one_word("xor3", "v_xor3_b32 v19, v18, v23, v24", lambda x, y, z, w: x ^ y ^ z, BFI_SETS,
         {"or_for_xor": lambda x, y, z, w: x | y | z, "third_source_dropped": lambda x, y, z, w: x ^ y,
          "add_for_xor": lambda x, y, z, w: (x + y + z) & M32, "and_for_xor": lambda x, y, z, w: x & y ^ z})

# 64-bit shifts. The count is the first source (S0[5:0]), the value the second (S1, a pair).
SHIFT_SETS = ((0, 0, 0xa5c3e187, 0x3c96b45a), (1, 0, 0xa5c3e187, 0xbc96b45a), (31, 0, 0x80000001, 0x80000001),
              (32, 0, 0xdeadbeef, 0xfeedface), (33, 0, 0xdeadbeef, 0x7eedface), (63, 0, 0x00000001, 0x80000000),
              (0x7f, 0, 0x12345678, 0x9abcdef0), (0x40, 0, 0x12345678, 0x9abcdef0), (0x25, 0, 0xffffffff, 0xffffffff))
SHIFT_BUGS = {
    "lshlrev_b64": {"count_masked_to_five_bits": lambda n, v: shift64("lshlrev_b64", v, n & 31),
                    "right_shift": lambda n, v: shift64("lshrrev_b64", v, n),
                    "low_word_only": lambda n, v: shift64("lshlrev_b64", v & M32, n),
                    "count_masked_to_seven_bits": lambda n, v: (v << (n & 127)) & M64,
                    "operands_swapped": lambda n, v: shift64("lshlrev_b64", n, v & 63)},
    "lshrrev_b64": {"count_masked_to_five_bits": lambda n, v: shift64("lshrrev_b64", v, n & 31),
                    "arithmetic_shift": lambda n, v: shift64("ashrrev_i64", v, n),
                    "left_shift": lambda n, v: shift64("lshlrev_b64", v, n),
                    "high_word_only": lambda n, v: shift64("lshrrev_b64", v & (M32 << 32), n),
                    "operands_swapped": lambda n, v: shift64("lshrrev_b64", n, v & 63)},
    "ashrrev_i64": {"count_masked_to_five_bits": lambda n, v: shift64("ashrrev_i64", v, n & 31),
                    "logical_shift": lambda n, v: shift64("lshrrev_b64", v, n),
                    "sign_from_low_word": lambda n, v: ((v >> (n & 63)) | (M64 << (64 - (n & 63)) if v >> 31 & 1 else 0)) & M64,
                    "high_word_only": lambda n, v: shift64("ashrrev_i64", v & (M32 << 32) | (0xffffffff if v >> 63 else 0), n),
                    "operands_swapped": lambda n, v: shift64("ashrrev_i64", n, v & 63)}}
VALUE = lambda z, w: w << 32 | z
for op, bugs in SHIFT_BUGS.items():
    for variant, instruction, setup, pair, counts in (
            ("vgpr", f"v_{op} v[19:20], v18, v[26:27]", "x", True, None),
            ("sgpr_pair", f"v_{op} v[19:20], v18, s[46:47]", "x", False, None),
            ("inline_count", f"v_{op} v[19:20], 33, v[26:27]", "", True, 33),
            ("count_sixty_four", f"v_{op} v[19:20], 64, v[26:27]", "", True, 64)):
        for half, reads in (("lo", LO_NC), ("hi", HI_NC)):
            def reference(x, y, z, w, op=op, counts=counts):
                return words(shift64(op, VALUE(z, w), x if counts is None else counts))

            add(f"{op}_{variant}_{half}", [instruction], ["v19", "v20"], reads, reference, SHIFT_SETS,
                {k: (lambda x, y, z, w, f=f, counts=counts: words(f(x if counts is None else counts, VALUE(z, w))))
                 for k, f in bugs.items()}, setup, pair, f"{op}_{variant}")

for group, seen in GROUPS.items():
    # A fixed inline count or addend cannot expose every bug (a count of 33 is the same masked to seven bits); each such
    # group still needs at least one.
    assert any(seen.values()) if group.endswith(("inline_count", "count_sixty_four", "inline_addend")) else all(seen.values()), (group, seen)
assert all(row[5] for row in ROWS)

# ---- the draw ------------------------------------------------------------------------------------------------------


def draw_cost(row):
    """Renderer launches one row costs: the plain check per constant set, one per wrong-reference channel that differs, and
    the row's own shader (each launch is a process with the debug layer, so launches are what a family's time is made of)."""
    _, _, reads, reference, sets, bugs = row
    cost = 1
    for constants_words in sets:
        expected = read(reads, reference(*constants_words))
        cost += 1 + sum(value != expected[channel] for buggy in bugs.values()
                        for channel, value in enumerate(read(reads, buggy(*constants_words))))
    return cost


def split_rows(parts):
    """The rows in `parts` consecutive runs of about equal launch cost (a 64-bit pair's rows stay adjacent)."""
    total = sum(draw_cost(row) for row in ROWS)
    runs, current, spent = [[] for _ in range(parts)], 0, 0
    for row in ROWS:
        runs[current].append(row)
        spent += draw_cost(row)
        if current < parts - 1 and spent >= total * (current + 1) / parts:
            current += 1
    return runs


# One CTest test per family and the whole table is ~3100 launches, over the 600 s limit on hardware with the debug layer:
# vop3_int, vop3_int_b, vop3_int_c and vop3_int_d (modules of the same name) each run one run of ROWS, ~770 launches.
PARTS = 4
RUNS = split_rows(PARTS)
assert [row for run in RUNS for row in run] == ROWS and all(RUNS)


def check_vop3_int_draws(directory, compiler, renderer, backend, rows=None):
    case = directory / "vop3_int.case"
    for index, (name, body, reads, reference, sets, bugs) in enumerate(RUNS[0] if rows is None else rows):
        source = directory / f"vop3_int{index}.hlsl"
        shader = directory / f"vop3_int{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = {label: False for label in bugs}
        for constants_words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *constants_words)
            expected = [float(v) for v in read(reads, reference(*constants_words))]
            for x in expected:
                assert half_rtz(x) == x, x
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for label, buggy in bugs.items():
                values = [float(v) for v in read(reads, buggy(*constants_words))]
                for channel, value in enumerate(values):
                    if value == expected[channel]:
                        continue
                    separated[label] = True
                    wrong = list(expected)
                    wrong[channel] = value
                    case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                    result = subprocess.run(draw, capture_output=True, text=True)
                    if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                        raise AssertionError(f"A wrong {name} result ({label}) escaped detection, channel {channel}, words {constants_words}")
        assert all(separated.values()), (name, separated)


def controls(directory):
    names = {row[0] for row in ROWS}
    assert len(names) == len(ROWS)
    for name, body, *_ in ROWS:
        source = translate(with_constants(body))
        main = source.split("float4 main", 1)[1]
        assert "valu" in main, name
    perm_source = translate(with_constants(ROWS[[row[0] for row in ROWS].index("perm_vgpr")][1]))
    assert "uint v_perm_byte(" in perm_source and "uint v_absdiff_u32(" not in perm_source
    sad_source = translate(with_constants(ROWS[[row[0] for row in ROWS].index("sad_u8")][1]))
    assert "uint v_absdiff_u32(" in sad_source and "v_perm_byte" not in sad_source
    # Refused neighbours: the e32 spelling (none exists), source modifiers, clamp, wrong operand shapes, and the forms not lowered.
    prefix = [SETUP["x"], SETUP["y"], SETUP["z"], *PAIR]
    for line in ("v_bfi_b32_e32 v19, v18, v23, v24", "v_bfi_b32 v19, -v18, v23, v24", "v_bfi_b32 v19, v18, |v23|, v24",
                 "v_bfi_b32 v19, v18, v23, v24 clamp", "v_bfi_b32 v19, v18, v23", "v_bfi_b32 v19, v18, v23, v24, v18",
                 "v_alignbit_b32 v19, -v18, v23, v24", "v_alignbit_b32 v19, v18, v23, v24 clamp",
                 "v_alignbit_b32_e32 v19, v18, v23, v24", "v_alignbyte_b32 v19, v18, v23, |v24|",
                 "v_alignbyte_b32 v19, v18, v23, v24 clamp", "v_perm_b32 v19, -v18, v23, v24", "v_perm_b32 v19, v18, v23, v24 clamp",
                 "v_perm_b32_e32 v19, v18, v23, v24", "v_sad_u8 v19, -v18, v23, v24", "v_sad_u8 v19, v18, v23, v24 clamp",
                 "v_sad_hi_u8 v19, v18, |v23|, v24", "v_sad_hi_u8 v19, v18, v23, v24 clamp", "v_sad_u16 v19, v18, v23, v24 clamp",
                 "v_sad_u16 v19, -v18, v23, v24", "v_sad_u32 v19, v18, v23, v24 clamp", "v_sad_u32_e32 v19, v18, v23, v24",
                 "v_msad_u8 v19, v18, v23, v24 clamp", "v_msad_u8 v19, v18, -v23, v24", "v_lerp_u8 v19, v18, v23, v24 clamp",
                 "v_lerp_u8 v19, -v18, v23, v24", "v_lerp_u8_e32 v19, v18, v23, v24",
                 # Not lowered: the float-to-byte rounding is not established.
                 "v_cvt_pk_u8_f32 v19, v18, 1, v24", "v_cvt_pk_u8_f32 v19, v18, v23, v24"):
        must_reject(translate, with_constants([*prefix, line]))
    for line in ("v_lshlrev_b64 v[19:20], -v18, v[26:27]", "v_lshlrev_b64 v[19:20], v18, -v[26:27]",
                 "v_lshrrev_b64 v[19:20], v18, |v[26:27]|", "v_ashrrev_i64 v[19:20], v18, v[26:27] clamp",
                 "v_lshlrev_b64_e32 v[19:20], v18, v[26:27]", "v_lshlrev_b64 v19, v18, v[26:27]",
                 "v_lshlrev_b64 v[19:21], v18, v[26:27]", "v_lshrrev_b64 v[19:20], v18, v26",
                 "v_ashrrev_i64 v[19:20], v18, s46", "v_ashrrev_i64 v[19:20], v[26:27], v[26:27]",
                 "v_lshlrev_b64 v[19:20], v18, 0x80000000", "v_lshrrev_b64 v[19:20], v18, -1", "v_lshrrev_b64 v[19:20], v18, 65",
                 "v_ashrrev_i64 v[19:20], v18, s[45:46]", "v_lshlrev_b64 v[19:20], v18, v[30:31]",
                 "v_lshlrev_b64 v[19:20], v30, v[26:27]", "v_mad_u64_u32 v[19:20], s52, v18, v23, 0x80000000",
                 "v_mad_u64_u32 v[19:20], s52, v18, v23, v24",
                 "v_mad_u64_u32 v[19:20], s52, -v18, v23, v[26:27]", "v_mad_u64_u32 v[19:20], s52, v18, v23, v[26:27] clamp",
                 "v_mad_u64_u32 v19, s52, v18, v23, v[26:27]", "v_mad_u64_u32 v[19:20], v18, v23, v[26:27]",
                 "v_mad_u64_u32 v[19:20], exec_lo, v18, v23, v[26:27]", "v_mad_u64_u32 v[19:20], s52, v18, v30, v[26:27]",
                 "v_mad_u64_u32_e32 v[19:20], s52, v18, v23, v[26:27]"):
        must_reject(translate, with_constants([*prefix, line]))
    program = assembly(False)
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_bfi_b32 v18, v13, 3, 5", "v_perm_b32 v18, v12, v14, 5", "v_sad_u8 v18, v13, 3, 5", "v_lerp_u8 v19, 1, 2, v15",
                  "v_alignbit_b32 v19, v13, 1, 2", "v_lshlrev_b64 v[19:20], v13, 5", "v_lshlrev_b64 v[12:13], 3, 5",
                  "v_mad_u64_u32 v[19:20], s52, v13, 3, 5", "v_mad_u64_u32 v[14:15], s52, 3, 3, 5"):
        must_reject(translate, program[:wait] + [early] + program[wait:])
    program = with_constants([])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("v_bfi_b32 v19, s44, 1, 2", "v_sad_u8 v19, 1, 2, s46", "v_mad_u64_u32 v[19:20], s52, s44, 3, 5",
                  "v_ashrrev_i64 v[19:20], 3, s[46:47]", "v_mad_u64_u32 v[19:20], s44, 1, 3, 5"):
        must_reject(translate, program[:load] + [early] + program[load:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for _, body, *_ in ROWS]


def draw(directory, compiler, renderer, backend):
    return check_vop3_int_draws(directory, compiler, renderer, backend, RUNS[0])
