"""Draw family `salu_rest`: pixel_aot_check.py draw --family salu_rest.

The scalar forms of SOP1, SOP2, SOPC and SOPK that salu32, scalar64 and sopk leave: s_not/brev/bcnt0/bcnt1/ff0/ff1/
flbit/flbit_i32/sext_i8/sext_i16/abs/bitset0/bitset1/cmov (32-bit), the 64-bit sources of bcnt/ff/flbit and
s_bitset0/1_b64, s_bitreplicate_b64_b32, s_nand/nor/xnor_b32 (and their SCC), s_add_i32/s_sub_i32 (signed overflow),
s_addc_u32/s_subb_u32 (SCC in and out), s_min/max_i32/u32, s_mul_i32, s_mul_hi_u32/i32, s_absdiff_i32, s_pack_*,
s_bfe_u64/s_bfe_i64, s_cselect_b64, the signed 32-bit compares, s_cmp_eq/lg_u64, s_bitcmp0/1_b32/b64, s_cmpk_* and
s_cmovk_i32. Forms that read or write EXEC (s_wqm, s_quadmask, the saveexec family) and the control-flow forms
(s_getpc, s_movrel, ...) belong to the control-flow cards and are refused here.

Each channel reads one byte of an SGPR back exactly through v_cvt_f32_ubyteN, or the SCC an instruction left, observed
with s_cselect_b32 between 0xa5 and 0x3c. References are computed independently as Python integers, per the RDNA 2 ISA
pseudocode. The wrong references are the plausible bugs: the wrong SCC (the result tested instead of the operands, a
strict compare for a non-strict one, SCC written by an op that leaves it), signed for unsigned and the reverse, an
unmasked or off-by-one bit index, a 32-bit operation for a 64-bit one, a missing carry or borrow in. controls() checks
without a GPU that every wrong reference differs from the right one on some constant set.
"""
import struct
import subprocess

from .common import M32, DrawBatch, byte, must_reject, signed, translate, with_constants

YES, NO = 0xa5, 0x3c


def scc(flag):
    return YES if flag else NO


def select(register):
    return f"s_cselect_b32 {register}, {YES:#x}, {NO:#x}"


def ch(lines, register, n, reference, *bugs):
    """One channel: setup lines, then either byte n of `register` or (n None) the SCC through s_cselect_b32."""
    return lines, register, n, reference, bugs


def program(sets, *channels):
    body, reference_of, bugs = [], [], []
    for index, (lines, register, n, reference, wrong) in enumerate(channels):
        body += lines
        if n is None:
            body += [select("s90"), f"v_cvt_f32_ubyte0_e32 v{12 + index}, s90"]
        else:
            body += [f"v_cvt_f32_ubyte{n}_e32 v{12 + index}, {register}"]
        reference_of.append((n, reference))
        bugs += [(index, (n, bug)) for bug in wrong]

    def convert(n, value):
        return scc(value) if n is None else byte(value, n)

    def expected(*words):
        return [convert(n, reference(*words)) for n, reference in reference_of]

    return (body, expected, sets,
            [(index, (lambda *words, n=n, bug=bug: convert(n, bug(*words)))) for index, (n, bug) in bugs])


# ---- Python references (independent of the HLSL the translator writes) -------------------------------------------
def rev32(v):
    return int(f"{v:032b}"[::-1], 2)


def pop(v):
    return bin(v).count("1")


def ctz(v, bits=32):
    return (v & -v).bit_length() - 1 if v else M32


def clz(v, bits=32):
    return bits - v.bit_length() if v else M32


def flbit_sign(v, bits=32):
    mask = (1 << bits) - 1
    return clz(~v & mask if v >> (bits - 1) else v, bits)


def sext(v, bits):
    v &= (1 << bits) - 1
    return (v - (1 << bits) if v >> (bits - 1) else v) & M32


def lo(v):
    return v & M32


def hi(v):
    return v >> 32


def pair(a, b):
    return a | (b << 32)


def sx32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def shl_or_unmasked(value, index):
    return (value << index) & M32 if index < 32 else 0


def replicate(x):
    out = 0
    for i in range(32):
        if x >> i & 1:
            out |= 3 << (2 * i)
    return out


def bfe(source, ctrl, signed_field, bits=64):
    off, width = ctrl & 63, (ctrl >> 16) & 127
    if width == 0:
        return 0
    field = (source >> off) & ((1 << width) - 1) if off + width < bits else source >> off
    top = min(width, bits - off)
    if signed_field and field >> (top - 1) & 1:
        field |= ((1 << bits) - 1) ^ ((1 << top) - 1)
    return field & ((1 << bits) - 1)


def add_overflow(a, b):
    r = (a + b) & M32
    return ((a ^ r) & (b ^ r)) >> 31 == 1


def sub_overflow(a, b):
    r = (a - b) & M32
    return ((a ^ b) & (a ^ r)) >> 31 == 1


def carry_of(a, b):
    return a + b > M32


def abs32(v):
    return (-v & M32) if v & 0x80000000 else v


def absdiff(a, b):
    return abs32((a - b) & M32)


def mul_hi_u(a, b):
    return (a * b) >> 32


def mul_hi_i(a, b):
    return ((sx32(a) * sx32(b)) >> 32) & M32


SIGN_FLIP = 0x80000000

SALU_REST_PROGRAMS = (
    # s_not_b32 and s_brev_b32: values, the SCC of s_not_b32, and the SCC that s_brev_b32 leaves.
    program(
        ((0x12345678, 0x80000001, 0xffffffff, 0x00000000), (0x9abcdef0, 0x0f0f1234, 0x00000000, 0xffffffff),
         (0xa5c3e187, 0x0000ff01, 0x00000001, 0xffffffff)),
        ch(["s_not_b32 s0, s44"], "s0", 3, lambda x, y, z, w: ~x & M32, lambda x, y, z, w: x),
        ch(["s_brev_b32 s1, s45"], "s1", 1, lambda x, y, z, w: rev32(y), lambda x, y, z, w: rev32(y) >> 1,
           lambda x, y, z, w: y),
        ch(["s_not_b32 s2, s46"], "s2", None, lambda x, y, z, w: (~z & M32) != 0, lambda x, y, z, w: z != 0),
        ch(["s_not_b32 s3, s47", "s_brev_b32 s4, s46"], "s4", None, lambda x, y, z, w: (~w & M32) != 0,
           lambda x, y, z, w: z != 0)),
    # s_bcnt0/1_i32_b32 values and SCC (set when the count is nonzero).
    program(
        ((0xff0f0001, 0x000000ff, 0xffffffff, 0x00000000), (0x0000000f, 0xffffffff, 0x00000000, 0xffffffff),
         (0x12345678, 0x80000000, 0x7fffffff, 0x00000001)),
        ch(["s_bcnt1_i32_b32 s0, s44"], "s0", 0, lambda x, y, z, w: pop(x), lambda x, y, z, w: 32 - pop(x)),
        ch(["s_bcnt0_i32_b32 s1, s45"], "s1", 0, lambda x, y, z, w: 32 - pop(y), lambda x, y, z, w: pop(y)),
        ch(["s_bcnt0_i32_b32 s2, s46"], "s2", None, lambda x, y, z, w: 32 - pop(z) != 0,
           lambda x, y, z, w: pop(z) != 0),
        ch(["s_bcnt1_i32_b32 s3, s47"], "s3", None, lambda x, y, z, w: pop(w) != 0,
           lambda x, y, z, w: 32 - pop(w) != 0)),
    # s_ff1/ff0/flbit_i32_b32/flbit_i32: the bit index, and -1 when there is no such bit.
    program(
        ((0x00000000, 0xffffffff, 0x00000000, 0x00000000), (0x80000000, 0x0000000f, 0x00010000, 0xfffffffe),
         (0x00000001, 0xffffff7f, 0xffffffff, 0xffffffff), (0x00001000, 0x00000000, 0x00000f00, 0x00000fff)),
        ch(["s_ff1_i32_b32 s0, s44"], "s0", 0, lambda x, y, z, w: ctz(x), lambda x, y, z, w: ctz(x) + 1),
        ch(["s_ff0_i32_b32 s1, s45"], "s1", 0, lambda x, y, z, w: ctz(~y & M32), lambda x, y, z, w: ctz(y)),
        ch(["s_flbit_i32_b32 s2, s46"], "s2", 0, lambda x, y, z, w: clz(z),
           lambda x, y, z, w: (31 - clz(z)) & M32 if z else M32),
        ch(["s_flbit_i32 s3, s47"], "s3", 0, lambda x, y, z, w: flbit_sign(w), lambda x, y, z, w: clz(w))),
    # The find-bit forms, s_sext and s_bitset leave SCC alone (SCC comes from s_not_b32 of the first word).
    program(
        ((0xffffffff, 0x11111111, 0x00000002, 0x80000000), (0x00000000, 0x22222222, 0x00000100, 0x00010000),
         (0x00000000, 0x33333333, 0x80000001, 0x00000000)),
        ch(["s_not_b32 s9, s44", "s_ff1_i32_b32 s0, s46", "s_ff0_i32_b32 s1, s47"], "s0", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: ctz(z) != 0, lambda x, y, z, w: ctz(~w & M32) != 0),
        ch(["s_not_b32 s9, s44", "s_flbit_i32_b32 s2, s46", "s_flbit_i32 s3, s47"], "s2", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: clz(z) != 0, lambda x, y, z, w: flbit_sign(w) != 0),
        ch(["s_mov_b32 s6, s45", "s_not_b32 s9, s44", "s_sext_i32_i8 s4, s46", "s_sext_i32_i16 s5, s47",
            "s_bitset1_b32 s6, s46", "s_bitset0_b32 s6, s47"], "s6", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: sext(z, 8) != 0, lambda x, y, z, w: sext(w, 16) != 0),
        ch(["s_not_b32 s9, s44", "s_brev_b32 s7, s46", "s_mov_b32 s8, s45", "s_cmov_b32 s8, s47"], "s8", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: z != 0)),
    # s_sext_i32_i8 / i16 and s_bitset0/1_b32.
    program(
        ((0x00000080, 0x00008000, 0x00ff00ff, 0x00000018), (0x0000007f, 0x00007fff, 0x00000000, 0x0000003f),
         (0xfffff0f0, 0xffff0f0f, 0xa5a5a5a5, 0x0000001f), (0xffffff7f, 0xffff7fff, 0xffffffff, 0x00000038)),
        ch(["s_sext_i32_i8 s0, s44"], "s0", 1, lambda x, y, z, w: sext(x, 8), lambda x, y, z, w: x & 0xff),
        ch(["s_sext_i32_i16 s1, s45"], "s1", 3, lambda x, y, z, w: sext(y, 16), lambda x, y, z, w: y & 0xffff,
           lambda x, y, z, w: sext(y, 8)),
        ch(["s_mov_b32 s2, s46", "s_bitset1_b32 s2, s47"], "s2", 3, lambda x, y, z, w: z | 1 << (w & 31),
           lambda x, y, z, w: z | 1 << ((w & 31) + 1), lambda x, y, z, w: z | shl_or_unmasked(1, w),
           lambda x, y, z, w: z & ~(1 << (w & 31))),
        ch(["s_mov_b32 s3, s46", "s_bitset0_b32 s3, s47"], "s3", 3, lambda x, y, z, w: z & ~(1 << (w & 31)),
           lambda x, y, z, w: z & ~(1 << ((w & 31) - 1)), lambda x, y, z, w: z | 1 << (w & 31))),
    # 64-bit sources: s_bcnt1/bcnt0_i32_b64 values and SCC; the low half alone would be wrong.
    program(
        ((0xff0f0001, 0x00ff00ff, 0xffffffff, 0x00000000), (0x00000000, 0xffffffff, 0x0000ffff, 0xffff0000),
         (0xffffffff, 0xffffffff, 0x00000000, 0x00000000)),
        ch(["s_bcnt1_i32_b64 s0, s[44:45]"], "s0", 0, lambda x, y, z, w: pop(x) + pop(y), lambda x, y, z, w: pop(x),
           lambda x, y, z, w: 64 - pop(x) - pop(y)),
        ch(["s_bcnt0_i32_b64 s1, s[46:47]"], "s1", 0, lambda x, y, z, w: 64 - pop(z) - pop(w),
           lambda x, y, z, w: 32 - pop(z), lambda x, y, z, w: pop(z) + pop(w)),
        ch(["s_bcnt1_i32_b64 s2, s[44:45]"], "s2", None, lambda x, y, z, w: pop(x) + pop(y) != 0,
           lambda x, y, z, w: pop(x) != 0),
        ch(["s_bcnt0_i32_b64 s3, s[46:47]"], "s3", None, lambda x, y, z, w: 64 - pop(z) - pop(w) != 0,
           lambda x, y, z, w: 32 - pop(z) != 0)),
    # s_ff0/ff1/flbit_i32_b64 and s_flbit_i32_i64 (leading sign bits).
    program(
        ((0x00000000, 0x00000000, 0x00000000, 0x00000000), (0x00000000, 0x00000100, 0xffffffff, 0xffffffff),
         (0x80000000, 0x00000000, 0x00000001, 0x00000000), (0xffffffff, 0x0000000f, 0x00001000, 0xfffffff0),
         (0x00000010, 0x00000001, 0x00000000, 0x80000000)),
        ch(["s_ff1_i32_b64 s0, s[44:45]"], "s0", 0, lambda x, y, z, w: ctz(pair(x, y), 64),
           lambda x, y, z, w: ctz(y) if not x else ctz(x)),
        ch(["s_ff0_i32_b64 s1, s[44:45]"], "s1", 0, lambda x, y, z, w: ctz(~pair(x, y) & (2**64 - 1), 64),
           lambda x, y, z, w: ctz(pair(x, y), 64)),
        ch(["s_flbit_i32_b64 s2, s[46:47]"], "s2", 0, lambda x, y, z, w: clz(pair(z, w), 64),
           lambda x, y, z, w: clz(z)),
        ch(["s_flbit_i32_i64 s3, s[46:47]"], "s3", 0, lambda x, y, z, w: flbit_sign(pair(z, w), 64),
           lambda x, y, z, w: clz(pair(z, w), 64))),
    # The 64-bit find-bit forms leave SCC alone.
    program(
        ((0xffffffff, 0x11111111, 0x00000002, 0x00000001), (0x00000000, 0x22222222, 0x00000100, 0x00010000),
         (0x00000000, 0x33333333, 0x80000001, 0x00000000)),
        ch(["s_not_b32 s9, s44", "s_ff1_i32_b64 s0, s[46:47]", "s_ff0_i32_b64 s1, s[46:47]"], "s0", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: ctz(pair(z, w), 64) != 0),
        ch(["s_not_b32 s9, s44", "s_flbit_i32_b64 s2, s[46:47]", "s_flbit_i32_i64 s3, s[46:47]"], "s2", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: clz(pair(z, w), 64) != 0),
        ch(["s_not_b32 s9, s44", "s_mov_b32 s4, s45", "s_mov_b32 s5, s46", "s_bitset1_b64 s[4:5], s46"], "s4", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: True),  # SCC written as "result nonzero"
        ch(["s_not_b32 s9, s44", "s_bitreplicate_b64_b32 s[6:7], s46"], "s6", None,
           lambda x, y, z, w: (~x & M32) != 0, lambda x, y, z, w: replicate(z) != 0)),
    # s_bitset0/1_b64: a 6-bit index, so bit 32 and up land in the high word; an index with bits above the low six.
    program(
        ((0xa5a5a5a5, 0x5a5a5a5a, 28, 59), (0xa5a5a5a5, 0x5a5a5a58, 33, 26), (0xa5a5a5a5, 0x5a5a5a5a, 0x5c, 0x7b),
         (0xa5a5a5a5, 0x5a5a5a58, 59, 3), (0xa5a5a5a5, 0x5a5a5a58, 2, 27)),
        ch(["s_mov_b32 s0, s44", "s_mov_b32 s1, s45", "s_bitset1_b64 s[0:1], s46"], "s0", 3,
           lambda x, y, z, w: lo(pair(x, y) | 1 << (z & 63)), lambda x, y, z, w: x | 1 << (z & 31),
           lambda x, y, z, w: lo(pair(x, y) | 1 << ((z & 63) + 1)), lambda x, y, z, w: lo(pair(x, y) | 1 << z)),
        ch(["s_mov_b32 s2, s44", "s_mov_b32 s3, s45", "s_bitset1_b64 s[2:3], s46"], "s3", 0,
           lambda x, y, z, w: hi(pair(x, y) | 1 << (z & 63)), lambda x, y, z, w: y | 1 << (z & 31),
           lambda x, y, z, w: hi(pair(x, y) | 1 << ((z & 63) - 1))),
        ch(["s_mov_b32 s4, s44", "s_mov_b32 s5, s45", "s_bitset0_b64 s[4:5], s47"], "s5", 3,
           lambda x, y, z, w: hi(pair(x, y) & ~(1 << (w & 63))), lambda x, y, z, w: y & ~(1 << (w & 31)),
           lambda x, y, z, w: hi(pair(x, y) | 1 << (w & 63))),
        ch(["s_mov_b32 s6, s44", "s_mov_b32 s7, s45", "s_bitset0_b64 s[6:7], s47"], "s6", 3,
           lambda x, y, z, w: lo(pair(x, y) & ~(1 << (w & 63))), lambda x, y, z, w: lo(pair(x, y) & ~(1 << ((w & 63) + 1))),
           lambda x, y, z, w: lo(pair(x, y) | 1 << (w & 63)))),
    # s_bitreplicate_b64_b32: bit i of the source to bits 2i and 2i+1.
    program(
        ((0xa5c3e187, 0, 0, 0), (0x0f0f0f0f, 0, 0, 0), (0x80000001, 0, 0, 0), (0x00010002, 0, 0, 0)),
        ch(["s_bitreplicate_b64_b32 s[0:1], s44"], "s0", 0, lambda x, y, z, w: lo(replicate(x)),
           lambda x, y, z, w: x & 0xff),
        ch([], "s0", 3, lambda x, y, z, w: lo(replicate(x)), lambda x, y, z, w: lo(replicate(x) >> 1)),
        ch([], "s1", 0, lambda x, y, z, w: replicate(x) >> 32, lambda x, y, z, w: lo(replicate(x))),
        ch([], "s1", 3, lambda x, y, z, w: replicate(x) >> 32, lambda x, y, z, w: lo(replicate(x)))),
    # s_abs_i32 value, SCC (0x80000000 stays negative and nonzero) and s_cmov_b32 under a signed compare.
    program(
        ((0xffffff80, 0xfffffe00, 0xffffffff, 0x000000bb), (0x7fffffff, 0x80000000, 0x80000000, 0x000000cc),
         (0x00000005, 0x00000000, 0x00000000, 0x000000dd), (0xffffffff, 0x000000aa, 0x00000001, 0x000000ee)),
        ch(["s_abs_i32 s0, s44"], "s0", 0, lambda x, y, z, w: abs32(x), lambda x, y, z, w: ~x & M32,
           lambda x, y, z, w: x),
        ch(["s_abs_i32 s1, s45"], "s1", 3, lambda x, y, z, w: abs32(y), lambda x, y, z, w: -y & M32 if y < 0x80000000
           else y, lambda x, y, z, w: y),
        ch(["s_abs_i32 s2, s46"], "s2", None, lambda x, y, z, w: abs32(z) != 0, lambda x, y, z, w: sx32(z) > 0),
        ch(["s_mov_b32 s3, s45", "s_cmp_lt_i32 s44, s46", "s_cmov_b32 s3, s47"], "s3", 0,
           lambda x, y, z, w: w if sx32(x) < sx32(z) else y, lambda x, y, z, w: w if x < z else y,
           lambda x, y, z, w: y if sx32(x) < sx32(z) else w)),
    # s_nand/nor/xnor_b32 values.
    program(
        ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
        ch(["s_nand_b32 s0, s44, s45"], "s0", 0, lambda x, y, z, w: ~(x & y) & M32, lambda x, y, z, w: x & y),
        ch(["s_nor_b32 s1, s46, s47"], "s1", 1, lambda x, y, z, w: ~(z | w) & M32, lambda x, y, z, w: ~(z & w) & M32,
           lambda x, y, z, w: z | w),
        ch(["s_xnor_b32 s2, s44, s46"], "s2", 3, lambda x, y, z, w: ~(x ^ z) & M32, lambda x, y, z, w: x ^ z),
        ch(["s_nand_b32 s3, s45, s47"], "s3", 2, lambda x, y, z, w: ~(y & w) & M32, lambda x, y, z, w: ~(y | w) & M32)),
    # Their SCC: set when the result is nonzero (all ones in gives zero out for nand, zero in for nor).
    program(
        ((0xffffffff, 0xffffffff, 0x00000000, 0x00000000), (0x12345678, 0x00000000, 0xffffffff, 0x0000ffff),
         (0xa5a5a5a5, 0xa5a5a5a5, 0x5a5a5a5a, 0x5a5a5a5a), (0xffffffff, 0x00000001, 0x80000000, 0x7fffffff)),
        ch(["s_nand_b32 s0, s44, s45"], "s0", None, lambda x, y, z, w: ~(x & y) & M32 != 0,
           lambda x, y, z, w: (x & y) != 0),
        ch(["s_nor_b32 s1, s46, s47"], "s1", None, lambda x, y, z, w: ~(z | w) & M32 != 0,
           lambda x, y, z, w: (z | w) != 0),
        ch(["s_xnor_b32 s2, s44, s45"], "s2", None, lambda x, y, z, w: ~(x ^ y) & M32 != 0,
           lambda x, y, z, w: (x ^ y) != 0),
        ch(["s_xnor_b32 s3, s46, s47"], "s3", None, lambda x, y, z, w: ~(z ^ w) & M32 != 0,
           lambda x, y, z, w: (z | w) != 0)),
    # s_nand/nor/xnor_b64 (lowered earlier, here with their values and SCC).
    program(
        ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff),
         (0x00000000, 0x00000000, 0x00000000, 0x00000000), (0xf0f0f0f0, 0x0f0f0f0f, 0x0f0f0f0f, 0xf0f0f0f0),
         (0xffffffff, 0x00000000, 0xffffffff, 0x00000000)),
        ch(["s_nand_b64 s[0:1], s[44:45], s[46:47]"], "s1", 3,
           lambda x, y, z, w: ~(y & w) & M32, lambda x, y, z, w: ~(x & z) & M32, lambda x, y, z, w: y & w),
        ch(["s_nor_b64 s[2:3], s[44:45], s[46:47]"], "s2", 0,
           lambda x, y, z, w: ~(x | z) & M32, lambda x, y, z, w: ~(y | w) & M32),
        ch(["s_xnor_b64 s[4:5], s[44:45], s[46:47]"], "s5", 2,
           lambda x, y, z, w: ~(y ^ w) & M32, lambda x, y, z, w: y ^ w),
        ch(["s_nand_b64 s[6:7], s[44:45], s[46:47]"], "s6", None,
           lambda x, y, z, w: (~(x & z) & M32) | (~(y & w) & M32) != 0,
           lambda x, y, z, w: ~(x & z) & M32 != 0)),
    # s_add_i32 / s_sub_i32: the value and the signed overflow (not the carry or borrow).
    program(
        ((0x7fffffff, 0x00000001, 0x7fffffff, 0x00000001), (0x80000000, 0x80000000, 0x80000000, 0x00000001),
         (0xffffffff, 0x00000001, 0xffffffff, 0x00000001), (0x00000001, 0xffffffff, 0x00000001, 0x80000000),
         (0x0000000a, 0x00000003, 0x0000000a, 0x0000000a)),
        ch(["s_add_i32 s0, s44, s45"], "s0", 3, lambda x, y, z, w: (x + y) & M32, lambda x, y, z, w: (x - y) & M32),
        ch(["s_add_i32 s1, s46, s47"], "s1", None, lambda x, y, z, w: add_overflow(z, w),
           lambda x, y, z, w: carry_of(z, w), lambda x, y, z, w: not add_overflow(z, w)),
        ch(["s_sub_i32 s2, s44, s45"], "s2", 3, lambda x, y, z, w: (x - y) & M32, lambda x, y, z, w: (x + y) & M32),
        ch(["s_sub_i32 s3, s46, s47"], "s3", None, lambda x, y, z, w: sub_overflow(z, w), lambda x, y, z, w: z < w,
           lambda x, y, z, w: add_overflow(z, w))),
    # s_addc_u32 / s_subb_u32: SCC in (from s_add_u32 / s_sub_u32 of the first pair) and SCC out.
    program(
        ((0xffffffff, 1, 0xffffffff, 0), (0, 1, 5, 5), (0x80000000, 0x80000000, 0x7ffffffe, 0x7fffffff),
         (5, 1, 0xff, 0x01), (0x00000000, 0x00000000, 0x00000005, 0x00000005)),
        ch(["s_add_u32 s9, s44, s45", "s_addc_u32 s0, s46, s47"], "s0", 0,
           lambda x, y, z, w: (z + w + carry_of(x, y)) & M32, lambda x, y, z, w: (z + w) & M32),
        ch(["s_add_u32 s9, s44, s45", "s_addc_u32 s1, s46, s47"], "s1", None,
           lambda x, y, z, w: z + w + carry_of(x, y) > M32, lambda x, y, z, w: carry_of(z, w)),
        ch(["s_sub_u32 s9, s44, s45", "s_subb_u32 s2, s46, s47"], "s2", 0,
           lambda x, y, z, w: (z - w - (x < y)) & M32, lambda x, y, z, w: (z - w) & M32),
        ch(["s_sub_u32 s9, s44, s45", "s_subb_u32 s3, s46, s47"], "s3", None,
           lambda x, y, z, w: w + (x < y) > z, lambda x, y, z, w: z < w, lambda x, y, z, w: w + (x < y) >= z)),
    # s_min_i32 / s_max_i32 / s_min_u32 / s_max_u32 values.
    program(
        ((0xffffffff, 1, 0xffffffff, 1), (5, 5, 7, 7), (0x7fffffff, 0x80000000, 0x80000000, 0x7fffffff)),
        ch(["s_min_i32 s0, s44, s45"], "s0", 3, lambda x, y, z, w: x if sx32(x) < sx32(y) else y,
           lambda x, y, z, w: min(x, y)),
        ch(["s_max_i32 s1, s46, s47"], "s1", 3, lambda x, y, z, w: z if sx32(z) >= sx32(w) else w,
           lambda x, y, z, w: max(z, w)),
        ch(["s_min_u32 s2, s44, s45"], "s2", 3, lambda x, y, z, w: min(x, y),
           lambda x, y, z, w: x if sx32(x) < sx32(y) else y),
        ch(["s_max_u32 s3, s46, s47"], "s3", 3, lambda x, y, z, w: max(z, w),
           lambda x, y, z, w: z if sx32(z) >= sx32(w) else w)),
    # Their SCC: set when S0 is the selected operand; min is strict, max is not (equal operands).
    program(
        ((0xffffffff, 1, 0xffffffff, 1), (5, 5, 7, 7), (0x7fffffff, 0x80000000, 0x80000000, 0x7fffffff)),
        ch(["s_min_i32 s0, s44, s45"], "s0", None, lambda x, y, z, w: sx32(x) < sx32(y),
           lambda x, y, z, w: x < y, lambda x, y, z, w: sx32(x) <= sx32(y)),
        ch(["s_max_i32 s1, s46, s47"], "s1", None, lambda x, y, z, w: sx32(z) >= sx32(w),
           lambda x, y, z, w: z >= w, lambda x, y, z, w: sx32(z) > sx32(w)),
        ch(["s_min_u32 s2, s44, s45"], "s2", None, lambda x, y, z, w: x < y,
           lambda x, y, z, w: sx32(x) < sx32(y), lambda x, y, z, w: x <= y),
        ch(["s_max_u32 s3, s46, s47"], "s3", None, lambda x, y, z, w: z >= w,
           lambda x, y, z, w: sx32(z) >= sx32(w), lambda x, y, z, w: z > w)),
    # s_mul_i32, s_mul_hi_u32 and s_mul_hi_i32 values.
    program(
        ((0xfffffff0, 0x12345678, 0xfffffffe, 3), (0x89abcdef, 0xffffffff, 0x7fffffff, 0x80000000),
         (0x80000000, 0x00000002, 0x80000000, 0x80000000)),
        ch(["s_mul_i32 s0, s44, s45"], "s0", 2, lambda x, y, z, w: (x * y) & M32, lambda x, y, z, w: mul_hi_u(x, y)),
        ch(["s_mul_hi_u32 s1, s44, s45"], "s1", 3, lambda x, y, z, w: mul_hi_u(x, y),
           lambda x, y, z, w: mul_hi_i(x, y)),
        ch(["s_mul_hi_i32 s2, s46, s47"], "s2", 3, lambda x, y, z, w: mul_hi_i(z, w),
           lambda x, y, z, w: mul_hi_u(z, w)),
        ch(["s_mul_hi_i32 s3, s44, s47"], "s3", 0, lambda x, y, z, w: mul_hi_i(x, w),
           lambda x, y, z, w: mul_hi_u(x, w))),
    # The multiplies leave SCC alone.
    program(
        ((0xffffffff, 0x12345678, 0xfffffffe, 3), (0x00000000, 0xffffffff, 0x7fffffff, 0x80000000)),
        ch(["s_not_b32 s9, s44", "s_mul_i32 s0, s46, s47"], "s0", None, lambda x, y, z, w: (~x & M32) != 0,
           lambda x, y, z, w: (z * w) & M32 != 0),
        ch(["s_not_b32 s9, s44", "s_mul_hi_u32 s1, s46, s47"], "s1", None, lambda x, y, z, w: (~x & M32) != 0,
           lambda x, y, z, w: mul_hi_u(z, w) != 0),
        ch(["s_not_b32 s9, s44", "s_mul_hi_i32 s2, s46, s47"], "s2", None, lambda x, y, z, w: (~x & M32) != 0,
           lambda x, y, z, w: mul_hi_i(z, w) != 0),
        ch(["s_not_b32 s9, s44", "s_pack_ll_b32_b16 s3, s46, s47"], "s3", None, lambda x, y, z, w: (~x & M32) != 0,
           lambda x, y, z, w: (z & 0xffff) | (w << 16) != 0)),
    # s_absdiff_i32: the wraparound case, the SCC, and the equal operands.
    program(
        ((0x00000002, 0x00000005, 0x80000000, 0x00000001), (0xffffffff, 0x00000000, 0x00000007, 0x00000007),
         (0x80000000, 0x00000000, 0x00000000, 0x80000000), (0x00000005, 0x00000002, 0x00000001, 0x80000000)),
        ch(["s_absdiff_i32 s0, s44, s45"], "s0", 0, lambda x, y, z, w: absdiff(x, y),
           lambda x, y, z, w: (x - y) & M32),
        ch(["s_absdiff_i32 s1, s44, s45"], "s1", None, lambda x, y, z, w: absdiff(x, y) != 0,
           lambda x, y, z, w: sx32(x) > sx32(y)),
        ch(["s_absdiff_i32 s2, s46, s47"], "s2", 3, lambda x, y, z, w: absdiff(z, w),
           lambda x, y, z, w: abs(sx32(z) - sx32(w)) & M32),
        ch(["s_absdiff_i32 s3, s46, s47"], "s3", None, lambda x, y, z, w: absdiff(z, w) != 0,
           lambda x, y, z, w: sx32(z) > sx32(w))),
    # s_pack_ll/lh/hh_b32_b16.
    program(
        ((0xaabbccdd, 0x11223344, 0x55667788, 0x99aabbcc), (0x01020304, 0x05060708, 0xa1b2c3d4, 0xe5f60718)),
        ch(["s_pack_ll_b32_b16 s0, s44, s45"], "s0", 3, lambda x, y, z, w: (x & 0xffff) | (y << 16) & M32,
           lambda x, y, z, w: (x & 0xffff) | (y & 0xffff0000)),
        ch(["s_pack_lh_b32_b16 s1, s44, s45"], "s1", 3, lambda x, y, z, w: (x & 0xffff) | (y & 0xffff0000),
           lambda x, y, z, w: (x & 0xffff) | (y << 16) & M32),
        ch(["s_pack_hh_b32_b16 s2, s44, s45"], "s2", 0, lambda x, y, z, w: (x >> 16) | (y & 0xffff0000),
           lambda x, y, z, w: x & 0xffff),
        ch(["s_pack_hh_b32_b16 s3, s46, s47"], "s3", 1, lambda x, y, z, w: (z >> 16) | (w & 0xffff0000),
           lambda x, y, z, w: (z & 0xffff) | (w & 0xffff0000))),
    # s_bfe_u64 / s_bfe_i64 values: a field inside one word, across the words, in the high word, past bit 63, and a
    # control word whose offset has bits above the low six.
    program(
        ((0x89abcdef, 0x91234567, 0x00100008, 0), (0x89abcdef, 0x91234567, 0x00100048, 0),
         (0x89abcdef, 0x91234567, 0x00200010, 0), (0x89abcdef, 0x91234567, 0x00180024, 0),
         (0x89abcdef, 0x11234567, 0x00280028, 0), (0x89abcdef, 0x91234567, 0x00080038, 0),
         (0x89abcdef, 0x91234567, 0x00000010, 0), (0x00000000, 0x00000080, 0x00280000, 0)),
        ch(["s_bfe_u64 s[0:1], s[44:45], s46"], "s0", 1, lambda x, y, z, w: lo(bfe(pair(x, y), z, False)),
           lambda x, y, z, w: lo(bfe(pair(x, y), z, True)), lambda x, y, z, w: bfe(x, z & 0x1f007f, False, 32)),
        ch(["s_bfe_u64 s[2:3], s[44:45], s46"], "s3", 0, lambda x, y, z, w: hi(bfe(pair(x, y), z, False)),
           lambda x, y, z, w: hi(bfe(pair(x, y), z, True)), lambda x, y, z, w: y >> (z & 63) if False else
           hi(bfe(pair(x, y), z + 1, False))),
        ch(["s_bfe_i64 s[4:5], s[44:45], s46"], "s4", 3, lambda x, y, z, w: lo(bfe(pair(x, y), z, True)),
           lambda x, y, z, w: lo(bfe(pair(x, y), z, False)), lambda x, y, z, w: lo(bfe(pair(x, y), z - 0x10000, True))),
        ch(["s_bfe_i64 s[6:7], s[44:45], s46"], "s7", 3, lambda x, y, z, w: hi(bfe(pair(x, y), z, True)),
           lambda x, y, z, w: hi(bfe(pair(x, y), z, False)))),
    # Their SCC: the 64-bit result is nonzero, even when its low word is zero (sign extension of bit 39).
    program(
        ((0x89abcdef, 0x91234567, 0x00100008, 0), (0x00000000, 0x00000080, 0x00280000, 0),
         (0x00000000, 0x00000000, 0x00100008, 0), (0x00000000, 0x00000001, 0x00100000, 0),
         (0x00000012, 0x00000000, 0x00100000, 0)),
        ch(["s_bfe_u64 s[0:1], s[44:45], s46"], "s0", None, lambda x, y, z, w: bfe(pair(x, y), z, False) != 0,
           lambda x, y, z, w: lo(bfe(pair(x, y), z, False)) != 0),
        ch(["s_bfe_i64 s[2:3], s[44:45], s46"], "s2", None, lambda x, y, z, w: bfe(pair(x, y), z, True) != 0,
           lambda x, y, z, w: lo(bfe(pair(x, y), z, True)) != 0),
        ch(["s_bfe_u64 s[4:5], s[44:45], s46"], "s4", None, lambda x, y, z, w: bfe(pair(x, y), z, False) != 0,
           lambda x, y, z, w: hi(bfe(pair(x, y), z, False)) != 0),
        ch(["s_bfe_i64 s[6:7], s[44:45], s46"], "s6", None, lambda x, y, z, w: bfe(pair(x, y), z, True) != 0,
           lambda x, y, z, w: hi(bfe(pair(x, y), z, True)) != 0)),
    # s_cselect_b64: both halves follow SCC; an inline -1 is sign-extended; SCC survives the select.
    program(
        ((0x11223344, 0x55667788, 0x99aabbcc, 0xddeeff00), (0x11223344, 0x11223344, 0x99aabbcc, 0xddeeff00),
         (0xfffffffe, 0x00000001, 0x00000000, 0x80000000), (0, 0, 1, 2)),
        ch(["s_cmp_eq_u32 s44, s45", "s_cselect_b64 s[0:1], s[46:47], s[44:45]"], "s0", 0,
           lambda x, y, z, w: z if x == y else x, lambda x, y, z, w: x if x == y else z),
        ch([], "s1", 3, lambda x, y, z, w: w if x == y else y, lambda x, y, z, w: y if x == y else w),
        ch(["s_cselect_b64 s[2:3], -1, 0"], "s3", 3, lambda x, y, z, w: 0xffffffff if x == y else 0,
           lambda x, y, z, w: 0 if x == y else 0xffffffff),
        ch(["s_cselect_b64 s[4:5], s[44:45], 0"], "s4", None, lambda x, y, z, w: x == y,
           lambda x, y, z, w: x != y, lambda x, y, z, w: x != 0 and x == y)),
    # The signed 32-bit compares (equality, signed order, and the same words ordered as unsigned).
    program(
        ((5, 5, 0xffffffff, 1), (0xffffffff, 1, 0x80000000, 0x7fffffff), (1, 0xffffffff, 0x7fffffff, 0x80000000),
         (0x80000000, 0x80000000, 7, 7)),
        ch(["s_cmp_eq_i32 s44, s45"], "s0", None, lambda x, y, z, w: x == y, lambda x, y, z, w: x != y),
        ch(["s_cmp_gt_i32 s46, s47"], "s1", None, lambda x, y, z, w: sx32(z) > sx32(w), lambda x, y, z, w: z > w,
           lambda x, y, z, w: sx32(z) >= sx32(w)),
        ch(["s_cmp_le_i32 s44, s45"], "s2", None, lambda x, y, z, w: sx32(x) <= sx32(y), lambda x, y, z, w: x <= y,
           lambda x, y, z, w: sx32(x) < sx32(y)),
        ch(["s_cmp_lt_i32 s46, s47"], "s3", None, lambda x, y, z, w: sx32(z) < sx32(w), lambda x, y, z, w: z < w,
           lambda x, y, z, w: sx32(z) <= sx32(w))),
    program(
        ((5, 5, 0xffffffff, 1), (0xffffffff, 1, 0x80000000, 0x7fffffff), (1, 0xffffffff, 0x7fffffff, 0x80000000),
         (0x80000000, 0x80000000, 7, 7)),
        ch(["s_cmp_lg_i32 s44, s45"], "s0", None, lambda x, y, z, w: x != y, lambda x, y, z, w: x == y),
        ch(["s_cmp_ge_i32 s46, s47"], "s1", None, lambda x, y, z, w: sx32(z) >= sx32(w), lambda x, y, z, w: z >= w,
           lambda x, y, z, w: sx32(z) > sx32(w)),
        ch(["s_cmp_lt_i32 s44, s45"], "s2", None, lambda x, y, z, w: sx32(x) < sx32(y), lambda x, y, z, w: x < y),
        ch(["s_cmp_gt_i32 s46, s47"], "s3", None, lambda x, y, z, w: sx32(z) > sx32(w), lambda x, y, z, w: z > w)),
    # s_cmp_eq_u64 / s_cmp_lg_u64: all 64 bits count, and a literal source is zero-extended.
    program(
        ((0x11223344, 0x55667788, 0x11223344, 0x55667788), (0x11223344, 0x55667788, 0x11223344, 0x55667789),
         (0x11223344, 0x55667788, 0x11223345, 0x55667788), (0, 0, 0x99, 0),
         (5, 0, 0x99, 1), (0, 5, 1, 0x99)),
        ch(["s_cmp_eq_u64 s[44:45], s[46:47]"], "s0", None, lambda x, y, z, w: (x, y) == (z, w),
           lambda x, y, z, w: x == z, lambda x, y, z, w: y == w),
        ch(["s_cmp_lg_u64 s[44:45], s[46:47]"], "s1", None, lambda x, y, z, w: (x, y) != (z, w),
           lambda x, y, z, w: x != z, lambda x, y, z, w: y != w),
        ch(["s_cmp_eq_u64 s[44:45], 0"], "s2", None, lambda x, y, z, w: (x, y) == (0, 0),
           lambda x, y, z, w: x == 0, lambda x, y, z, w: y == 0),
        ch(["s_cmp_lg_u64 s[46:47], 0x99"], "s3", None, lambda x, y, z, w: (z, w) != (0x99, 0),
           lambda x, y, z, w: z != 0x99, lambda x, y, z, w: w != 0x99)),
    # s_bitcmp0/1_b32: the index is S1[4:0]; the b64 forms index with S1[5:0].
    program(
        ((0x80000001, 0x1f, 0x80000001, 0x00), (0x80000001, 0x20, 0x00000020, 0x25), (0x00000010, 0x04, 0x00000010, 0x24),
         (0x00000000, 0x01, 0xffffffff, 0x1f)),
        ch(["s_bitcmp0_b32 s44, s45"], "s0", None, lambda x, y, z, w: (x >> (y & 31)) & 1 == 0,
           lambda x, y, z, w: (x >> (y & 31)) & 1 == 1, lambda x, y, z, w: (x >> y) & 1 == 0,
           lambda x, y, z, w: (x >> ((y + 1) & 31)) & 1 == 0),
        ch(["s_bitcmp1_b32 s46, s47"], "s1", None, lambda x, y, z, w: (z >> (w & 31)) & 1 == 1,
           lambda x, y, z, w: (z >> (w & 31)) & 1 == 0, lambda x, y, z, w: (z >> w) & 1 == 1,
           lambda x, y, z, w: (z >> ((w - 1) & 31)) & 1 == 1),
        # Channels 2 and 3 are written too: the export has four channels and the case file carries four references.
        ch(["s_bitcmp1_b32 s44, s45"], "s2", None, lambda x, y, z, w: (x >> (y & 31)) & 1 == 1,
           lambda x, y, z, w: (x >> (y & 31)) & 1 == 0, lambda x, y, z, w: (x >> y) & 1 == 1),
        ch(["s_bitcmp0_b32 s46, s47"], "s3", None, lambda x, y, z, w: (z >> (w & 31)) & 1 == 0,
           lambda x, y, z, w: (z >> (w & 31)) & 1 == 1, lambda x, y, z, w: (z >> w) & 1 == 0)),
    program(
        ((0x80000001, 0x00000001, 0x1f, 0x20), (0x00000000, 0x80000000, 0x3f, 0x1f), (0x00000010, 0x00000100, 0x24, 0x28),
         (0x00000000, 0x00000000, 0x5f, 0x64)),
        ch(["s_bitcmp0_b64 s[44:45], s46"], "s0", None, lambda x, y, z, w: (pair(x, y) >> (z & 63)) & 1 == 0,
           lambda x, y, z, w: (pair(x, y) >> (z & 63)) & 1 == 1, lambda x, y, z, w: (x >> (z & 31)) & 1 == 0,
           lambda x, y, z, w: (pair(x, y) >> ((z + 1) & 63)) & 1 == 0),
        ch(["s_bitcmp1_b64 s[44:45], s47"], "s1", None, lambda x, y, z, w: (pair(x, y) >> (w & 63)) & 1 == 1,
           lambda x, y, z, w: (pair(x, y) >> (w & 63)) & 1 == 0, lambda x, y, z, w: (y >> (w & 31)) & 1 == 1,
           lambda x, y, z, w: (pair(x, y) >> ((w - 1) & 63)) & 1 == 1),
        ch(["s_bitcmp1_b32 s44, s46"], "s2", None, lambda x, y, z, w: (x >> (z & 31)) & 1 == 1,
           lambda x, y, z, w: (pair(x, y) >> (z & 63)) & 1 == 1),
        ch(["s_bitcmp0_b64 s[44:45], s47"], "s3", None, lambda x, y, z, w: (pair(x, y) >> (w & 63)) & 1 == 0,
           lambda x, y, z, w: (x >> (w & 31)) & 1 == 0)),
)


def sopk_program(rows, immediates, kind):
    """Four channels of s_cmpk_<rel>_<kind>: word k of the set against channel k's immediate (RDNA 2 SOPK: the
    immediate is sign-extended for _i32 and zero-extended for _u32)."""
    relations = {"eq": lambda a, b: a == b, "lg": lambda a, b: a != b, "gt": lambda a, b: a > b,
                 "ge": lambda a, b: a >= b, "lt": lambda a, b: a < b, "le": lambda a, b: a <= b}
    channels = []
    for index, (relation, token) in enumerate(immediates):
        imm = int(token, 0)
        extended = sext(imm, 16) if kind == "i32" else imm
        view = sx32 if kind == "i32" else (lambda v: v)
        other_view = (lambda v: v) if kind == "i32" else sx32
        other_extended = imm if kind == "i32" else sext(imm, 16)
        strict = {"gt": "ge", "ge": "gt", "lt": "le", "le": "lt", "eq": "lg", "lg": "eq"}[relation]
        compare = relations[relation]
        channels.append(ch(
            [f"s_cmpk_{relation}_{kind} s{44 + index}, {token}"], f"s{index}", None,
            lambda *w, i=index, c=compare, v=view, e=extended: c(v(w[i]), v(e)),
            lambda *w, i=index, c=compare, v=other_view, e=other_extended: c(v(w[i]), v(e)),  # the other signedness
            lambda *w, i=index, c=relations[strict], v=view, e=extended: c(v(w[i]), v(e))))  # off-by-one relation
    return program(rows, *channels)


def around(token, kind):
    """Words around an immediate: equal after sign extension, equal after zero extension, one below, one above."""
    imm = int(token, 0)
    ext = sext(imm, 16) if kind == "i32" else imm
    return ext, imm, (ext - 1) & M32, (ext + 1) & M32


def sopk_rows(immediates, kind):
    columns = [around(token, kind) for _, token in immediates]
    return tuple(tuple(column[k] for column in columns) for k in range(4)) + (
        (0x80000000, 0x7fffffff, 0xffffffff, 0x00000000), (0x00000000, 0x80000000, 0x7fffffff, 0xffffffff),
        (0xffffffff, 0x00000000, 0x80000000, 0x7fffffff), (0x7fffffff, 0xffffffff, 0x00000000, 0x80000000))


SOPK_COMPARES = (
    (("eq", "0x8000"), ("lg", "0x8000"), ("eq", "0xfffe"), ("lg", "0xffff")),
    (("gt", "0x8000"), ("ge", "0x8000"), ("lt", "0xffff"), ("le", "0x7fff")),
    (("gt", "0xffff"), ("ge", "0x8000"), ("lt", "0x0001"), ("le", "0x8000")),
)
SOPK_PROGRAMS = tuple(
    sopk_program(sopk_rows(group, kind), group, kind)
    for kind, groups in (("i32", SOPK_COMPARES[:2]), ("u32", (SOPK_COMPARES[0], SOPK_COMPARES[2])))
    for group in groups)

# s_cmovk_i32: the sign-extended immediate when SCC is set, D otherwise; SCC survives the move.
SOPK_MOVE_PROGRAMS = (
    program(
        ((5, 5, 0x11223344, 0x55667788), (5, 6, 0x11223344, 0x55667788), (0xffffffff, 0xffffffff, 0, 0xaabbccdd)),
        ch(["s_mov_b32 s0, s46", "s_cmp_eq_u32 s44, s45", "s_cmovk_i32 s0, 0x8000"], "s0", 3,
           lambda x, y, z, w: 0xffff8000 if x == y else z, lambda x, y, z, w: 0x8000 if x == y else z,
           lambda x, y, z, w: z if x == y else 0xffff8000),
        ch(["s_mov_b32 s1, s47", "s_cmp_eq_u32 s44, s45", "s_cmovk_i32 s1, -2"], "s1", 0,
           lambda x, y, z, w: 0xfffffffe if x == y else w, lambda x, y, z, w: w if x == y else 0xfffffffe),
        ch(["s_mov_b32 s2, s46", "s_cmp_lg_u32 s44, s45", "s_cmovk_i32 s2, 0x1234"], "s2", 1,
           lambda x, y, z, w: 0x1234 if x != y else z, lambda x, y, z, w: 0x1234),
        ch(["s_mov_b32 s3, s46", "s_cmp_eq_u32 s44, s45", "s_cmovk_i32 s3, 1"], "s3", None,
           lambda x, y, z, w: x == y, lambda x, y, z, w: x != y)),
)

ALL_PROGRAMS = SALU_REST_PROGRAMS + SOPK_PROGRAMS + SOPK_MOVE_PROGRAMS


def check_draws(directory, compiler, renderer, backend):
    for index, (body, reference, sets, bugs) in enumerate(ALL_PROGRAMS):
        source = directory / f"salu_rest_{index}.hlsl"
        shader = directory / f"salu_rest_{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        batch = DrawBatch(directory, renderer, backend, shader, "salu_rest")
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = [float(v) for v in reference(*words)]
            batch.add(constants + struct.pack("<4f", *expected) * 64, "pass",
                      f"A scalar result differs in program {index}, words {[hex(v) for v in words]}")
            for channel, buggy in bugs:
                value = float(buggy(*words))
                if value == expected[channel]:
                    continue
                wrong = list(expected)
                wrong[channel] = value
                batch.add(constants + struct.pack("<4f", *wrong) * 64, "mismatch",
                          f"A wrong scalar result escaped detection in program {index}, channel "
                          f"{channel}, words {[hex(v) for v in words]}")
        batch.flush()


def separation(programs=ALL_PROGRAMS):
    """(program, channel, bug) triples whose wrong reference equals the right one on every constant set."""
    unseparated = []
    for index, (body, reference, sets, bugs) in enumerate(programs):
        for k, (channel, buggy) in enumerate(bugs):
            if all(float(buggy(*words)) == float(reference(*words)[channel]) for words in sets):
                unseparated.append((index, channel, k))
    return unseparated


def upstream_edge_controls():
    """Translation of the programs R0Y00/Xbox2Windows main added as Windows GPU draws (0a9cc04): s_cmpk_eq_u32 against
    0x8001 with s_cmovk_i32 on a second compare, v_subrev_nc_u32 with two VGPR sources, the v_mad_legacy_f32 and
    v_madak_f32 edge operands and s_bitset1_b32 at a low bit. Only the lowering is checked here; the draws and their
    references need a Windows GPU run."""
    from .f32_modes import uncompressed_export
    four = ["v_mov_b32_e32 v12, s52", "v_mov_b32_e32 v13, s53", "v_mov_b32_e32 v14, s50", "v_mov_b32_e32 v15, s51"]
    for body in (
        ["s_mov_b32 s52, 0", "s_mov_b32 s53, 0", "s_mov_b32 s50, s46", "s_mov_b32 s51, s46",
         "s_cmpk_eq_u32 s45, 0x8001", "s_cselect_b32 s63, 64, 0", "s_or_b32 s53, s53, s63",
         "s_cmpk_eq_i32 s47, 0xffff", "s_cmovk_i32 s50, 0xfffe", "s_cmpk_eq_i32 s47, 1", "s_cmovk_i32 s51, 0x8000",
         *four],
        ["v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v19, s44", "v_subrev_nc_u32_e32 v12, s44, v18",
         "v_subrev_nc_u32_e32 v14, v19, v18", "v_mov_b32_e32 v13, 0", "v_mov_b32_e32 v15, 0"],
        ["v_mov_b32_e32 v19, s47", "v_mad_legacy_f32 v12, s44, s45, 1.0", "v_mad_legacy_f32 v13, s46, 1.0, 1.0",
         "v_madak_f32 v14, s44, v19, 0x3f400000", "v_mad_legacy_f32 v15, 1.0, |v19|, 0.0"],
        ["s_mov_b32 s52, s46", "s_bitset1_b32 s52, 4", "s_mov_b32 s53, 0", "s_mov_b32 s50, 0", "s_mov_b32 s51, 0",
         *four],
    ):
        if any(line.startswith("v_s") or line.startswith("v_mad") for line in body):
            translate(uncompressed_export(body))
        else:
            translate(with_constants(body))


def controls(directory):
    upstream_edge_controls()
    assert not separation(), separation()
    for body, *_ in ALL_PROGRAMS:  # every program translates (and is recorded for the form-coverage count)
        translate(with_constants(body))
    for index, (body, reference, sets, bugs) in enumerate(ALL_PROGRAMS):
        for words in sets:
            assert all(0 <= v <= 255 for v in reference(*words)), (index, words)
            assert all(0 <= v <= M32 for v in words), (index, words)
    text = translate(with_constants(next(p[0] for p in SALU_REST_PROGRAMS if "s_abs_i32 s0, s44" in p[0]))).split("float4 main", 1)[1]
    assert "asfloat(" not in text  # scalar words never take a float type
    # Refusals. Lane-mask and EXEC forms and the control-flow forms stay with CF-2/CF-3.
    for line in (
        "s_wqm_b32 s0, s44", "s_quadmask_b32 s0, s44", "s_quadmask_b64 s[0:1], s[44:45]",
        "s_movrels_b32 s0, s44", "s_movreld_b32 s0, s44", "s_getpc_b64 s[0:1]", "s_setpc_b64 s[44:45]",
        "s_swappc_b64 s[0:1], s[44:45]", "s_rfe_b64 s[44:45]", "s_and_saveexec_b32 s0, s44",
        "s_or_saveexec_b64 s[0:1], s[44:45]", "s_andn1_wrexec_b64 s[0:1], s[44:45]",
        "s_cmp_eq_u64 exec, s[46:47]", "s_cmp_lg_u64 s[44:45], vcc", "s_bitcmp1_b64 exec, s44",
        "s_bitcmp0_b32 exec_lo, s44", "s_bitcmp0_b32 s44, vcc_lo",
        "s_cselect_b64 exec, s[44:45], s[46:47]", "s_cselect_b64 s[0:1], exec, s[46:47]",
        "s_cmov_b32 exec_lo, s44", "s_not_b32 exec_lo, s44", "s_not_b32 s0, exec_lo", "s_brev_b32 vcc_lo, s44",
        "s_bcnt1_i32_b64 s0, exec", "s_bcnt0_i32_b64 s0, vcc", "s_ff1_i32_b64 s0, exec", "s_flbit_i32_b64 s0, vcc",
        "s_bitset1_b64 exec, s44", "s_bitset1_b32 exec_lo, s44", "s_bitset0_b32 s0, exec_lo",
        "s_bitreplicate_b64_b32 exec, s44", "s_bfe_u64 exec, s[44:45], s46", "s_bfe_i64 s[0:1], exec, s46",
        "s_bfe_u64 s[0:1], s[44:45], exec_lo", "s_min_i32 exec_lo, s44, s45", "s_add_i32 s0, exec_lo, s45",
        "s_nand_b32 s0, s44, exec_lo", "s_mul_hi_u32 vcc_lo, s44, s45", "s_pack_ll_b32_b16 s0, exec_lo, s45",
        "s_absdiff_i32 s0, s44, vcc_lo", "s_cmpk_eq_u32 exec_lo, 1", "s_cmpk_eq_i32 s44, exec_lo",
        "s_cmovk_i32 exec_lo, 1",
        # Operands and destinations of the wrong kind.
        "s_not_b32 s[0:1], s44", "s_not_b32 s0, s[44:45]", "s_not_b32 v0, s44", "s_brev_b32 s0, v12",
        "s_bcnt1_i32_b64 s[0:1], s[44:45]", "s_bcnt1_i32_b64 s0, s44", "s_ff1_i32_b64 s0, s[45:46]",
        "s_bitset1_b64 s[0:1], s[44:45]", "s_bitset1_b64 s[1:2], s44", "s_bitset0_b32 s90, s44",
        "s_bitreplicate_b64_b32 s[1:2], s44", "s_bitreplicate_b64_b32 s0, s44", "s_sext_i32_i8 s0, s[44:45]",
        "s_abs_i32 s0, v12", "s_abs_i32 s0", "s_nand_b32 s0, s44", "s_nor_b32 s[0:1], s44, s45",
        "s_add_i32 s0, s44, s[46:47]", "s_sub_i32 s106, s44, s45", "s_min_i32 s0, v12, s45", "s_max_u32 s0, s44, scc",
        "s_mul_i32 s0, s44, -s45", "s_mul_hi_u32 s0, s44, 0x1ffffffff", "s_pack_ll_b32_b16 s0, s44, 0x100000000",
        "s_absdiff_i32 s[0:1], s44, s45", "s_bfe_u64 s0, s[44:45], s46", "s_bfe_u64 s[0:1], s44, s46",
        "s_bfe_u64 s[0:1], s[44:45], s[46:47]", "s_bfe_i64 s[1:2], s[44:45], s46", "s_cselect_b64 s0, s[44:45], 0",
        "s_cselect_b64 s[0:1], s44, s45", "s_cmp_eq_u64 s44, s45", "s_cmp_lg_u64 s[44:45], s46",
        "s_cmp_eq_u64 s[45:46], s[44:45]", "s_bitcmp0_b64 s44, s46", "s_bitcmp1_b32 s[44:45], s46",
        "s_bitcmp1_b32 s44, v12", "s_cmp_lt_i32 s44, v12", "s_cmp_gt_i32 s44",
        # SOPK immediates: 16 bits, zero-extended for _u32 (so no negative), no vector or 64-bit operand.
        "s_cmpk_eq_u32 s44, -1", "s_cmpk_lt_u32 s44, 0x10000", "s_cmpk_gt_i32 s44, 32768x", "s_cmpk_eq_i32 s44, -32769",
        "s_cmpk_ge_i32 s44, 65536", "s_cmpk_le_u32 s44, 65536", "s_cmpk_lg_i32 v12, 1", "s_cmpk_eq_u32 s[44:45], 1",
        "s_cmpk_eq_i32 s90, 1", "s_cmpk_eq_i32 s44", "s_cmpk_eq_i64 s44, 1", "s_cmpk_eq_u32 s44, s45",
        "s_cmovk_i32 s0, 0x10000", "s_cmovk_i32 s0, v12", "s_cmovk_i32 s[0:1], 1", "s_cmovk_i32 s0, s44",
        "s_cmovk_i32 s106, 1",
    ):
        must_reject(translate, with_constants([line]))
    # No tracked SCC: a select, a carry in, a conditional move have no condition to read. Nothing sets SCC before the
    # first instruction of the program, so these are refused; with an SCC written first they are accepted.
    for line in ("s_cselect_b64 s[0:1], s[44:45], s[46:47]", "s_addc_u32 s0, s44, s45", "s_subb_u32 s0, s44, s45",
                 "s_cmov_b32 s44, s45", "s_cmovk_i32 s44, 1"):
        must_reject(translate, with_constants([line]))
    for line in ("s_cselect_b64 s[0:1], s[44:45], s[46:47]", "s_addc_u32 s0, s44, s45", "s_subb_u32 s0, s44, s45",
                 "s_cmov_b32 s44, s45", "s_cmovk_i32 s44, 1"):
        translate(with_constants(["s_cmp_eq_u32 s44, s45", line]))
    # Read-modify-write destinations must hold a numeric word first.
    for line in ("s_bitset1_b32 s90, s44", "s_bitset0_b64 s[90:91], s44", "s_cmovk_i32 s91, 1", "s_cmpk_eq_u32 s91, 1"):
        must_reject(translate, with_constants(["s_cmp_eq_u32 s44, s45", line]))
    # A destination or source whose load has not completed.
    program_ = with_constants([])
    load = program_.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("s_not_b32 s44, s0", "s_brev_b32 s0, s45", "s_bcnt1_i32_b64 s0, s[44:45]", "s_bitset1_b32 s45, s46",
                  "s_bitreplicate_b64_b32 s[44:45], 1", "s_cselect_b64 s[46:47], 1, 2", "s_add_i32 s0, s44, 1",
                  "s_bfe_u64 s[44:45], 1, 2", "s_cmp_eq_u64 s[44:45], 0", "s_bitcmp1_b32 s46, 1", "s_cmpk_eq_u32 s44, 1"):
        must_reject(translate, program_[:load] + ["s_mov_b32 s0, 0", "s_cmp_eq_u32 s0, s0", early] + program_[load:])
    # A scalar result cannot supply a sampler word.
    sample = program_.index("image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D")
    for line in ("s_not_b32 s40, 0", "s_abs_i32 s41, 1", "s_min_i32 s42, 1, 2"):
        must_reject(translate, program_[:sample] + [line] + program_[sample:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for body, *_ in ALL_PROGRAMS]


draw = check_draws
