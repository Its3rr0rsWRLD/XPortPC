"""Draw family `bits_pack`: pixel_aot_check.py draw --family bits_pack.

v_bfe_u32 and v_bfe_i32, v_bfm_b32, v_bcnt_u32_b32, the bit scans v_ffbh_u32, v_ffbh_i32 and v_ffbl_b32 and v_bfrev_b32
(unary forms in both encodings), and the saturating packs v_cvt_pk_u16_u32 and v_cvt_pk_i16_i32. Each channel reads one byte
of a result back exactly through v_cvt_f32_ubyteN. The constant sets give offsets and widths with bits above the low
five, a width of zero (32 masked), fields that run past bit 31, sign bits set and clear in the field, and pack inputs
inside and outside the 16-bit range on both sides. Wrong references: unmasked offset or width, a signed extract
read as unsigned, zero fill past bit 31, truncating packs, a signed clamp done unsigned and swapped halves.

The bit forms were ported from R0Y00/Xbox2Windows#436 by Joacoorandom, whose sixteen (a, b, c) operand sets and
reference semantics the BIT_CASES and bit_reference below keep (all four result bytes are read back, instead of the
half-widening trick); the draws here are new.
"""
import struct
import subprocess

from .common import M32, DrawBatch, byte, must_reject, signed, translate, ubyte, with_constants


def bfe_u(src, off, width):
    off, width = off & 31, width & 31
    return (src >> off) & ((1 << width) - 1)


def bfe_i(src, off, width):
    off, width = off & 31, width & 31
    if not width:
        return 0
    field = (signed(src) >> off) & ((1 << width) - 1)
    return (field - (1 << width) if field >> (width - 1) else field) & M32


def zero_fill_i(src, off, width):
    """v_bfe_i32 that sign-extends from bit width - 1 of a zero-filled shift (wrong when off + width > 32)."""
    off, width = off & 31, width & 31
    if not width:
        return 0
    field = (src >> off) & ((1 << width) - 1)
    return (field - (1 << width) if field >> (width - 1) else field) & M32


def sat_u16(x):
    return min(x, 0xffff)


def sat_i16(x):
    return min(max(signed(x), -0x8000), 0x7fff) & 0xffff


def pack(lo, hi):
    return lo | hi << 16


# Operand sets of #436 (a, b, c); the draw puts them in the first three constant words.
BIT_CASES = (
    (0, 0, 0), (0xffffffff, 0, 0), (0x80000000, 31, 1),
    (0x7fffffff, 28, 31), (0xdeadbeef, 4, 8), (0x89abcdef, 36, 40),
    (0xfedcba98, 63, 31), (0xffffffff, 0xffffffff, 0xffffffff),
    (0x80000001, 1, 31), (0x12345678, 16, 16), (0x01010101, 63, 32),
    (0x7f00ff00, 8, 9), (1, 0xffffffff, 33), (0xfffffffe, 32, 63),
    (0x40000000, 2, 30), (0x00010000, 31, 31),
)


def bit_reference(op, a, b):
    if op == "v_bfm_b32":
        return sum(1 << i for i in range(b % 32, b % 32 + a % 32) if i < 32)
    if op == "v_bcnt_u32_b32":
        return (bin(a).count("1") + b) & M32
    if op == "v_bfrev_b32":
        return sum(((a >> i) & 1) << (31 - i) for i in range(32))
    sought = 0 if op == "v_ffbh_i32" and a >> 31 else 1
    for i in range(32) if op == "v_ffbl_b32" else range(31, -1, -1):
        if (a >> i) & 1 == sought:
            return i if op == "v_ffbl_b32" else 31 - i
    return M32


def lowest(a):
    return next((i for i in range(32) if a >> i & 1), M32)


# (spelling, wrong reference(a, b) -> word): plausible bugs for each operation.
BIT_BUGS = {
    "v_bfm_b32": (lambda a, b: bit_reference("v_bfm_b32", b, a),  # operands swapped
                  lambda a, b: (((1 << a) - 1) << b) & M32 if a < 32 and b < 32 else 0),  # counts not masked
    "v_bcnt_u32_b32": (lambda a, b: bin(a).count("1"),  # accumulator dropped
                       lambda a, b: bin(a).count("1") ^ b),
    "v_bfrev_b32": (lambda a, b: a,  # not reversed
                    lambda a, b: int(f"{a:032b}", 2) >> 1 | (a & 1) << 31),
    "v_ffbh_u32": (lambda a, b: lowest(a),  # counted from the bottom
                   lambda a, b: a.bit_length() - 1 if a else M32,  # position, not distance from the top
                   lambda a, b: 32 - a.bit_length() if a else 0),  # no bit found gives 0
    "v_ffbh_i32": (lambda a, b: bit_reference("v_ffbh_u32", a, b),  # sign ignored
                   lambda a, b: bit_reference("v_ffbh_u32", a ^ M32, b) if a >> 31 else M32),  # 0 and -1 not refused
    "v_ffbl_b32": (lambda a, b: 31 - lowest(a) if a else M32,
                   lambda a, b: lowest(a) if a else 0),  # no bit found gives 0
}


def bit_program_body(op, spelling):
    """The unary forms in the encoding `spelling` (e32 or e64), the two-source forms as VOP3."""
    arity = 2 if op in ("v_bfm_b32", "v_bcnt_u32_b32") else 1
    name = op + (f"_{spelling}" if arity == 1 else "")
    body = ["v_mov_b32_e32 v20, s44", "v_mov_b32_e32 v21, s45", f"{name} v18, " + ", ".join(("v20", "v21")[:arity])]
    return body + [ubyte(n, 12 + n, "v18", "e32") for n in range(4)]


def bit_program_entry(op, spelling):
    def reference(x, y, z, w):
        result = bit_reference(op, x, y)
        return [byte(result, n) for n in range(4)]

    bugs = []
    for buggy in BIT_BUGS[op]:
        differing = [n for n in range(4) for a, b, _ in BIT_CASES
                     if byte(buggy(a, b) & M32, n) != byte(bit_reference(op, a, b), n)]
        assert differing, (op, "a wrong reference never differs")
        for n in sorted(set(differing)):
            bugs.append((n, lambda x, y, z, w, f=buggy, n=n: byte(f(x, y) & M32, n)))
    return (bit_program_body(op, spelling), reference, BIT_CASES_WORDS, bugs)


BIT_CASES_WORDS = tuple((a, b, c, 0) for a, b, c in BIT_CASES)
BIT_ENTRIES = tuple(bit_program_entry(op, spelling) for op in BIT_BUGS
                    for spelling in (("e32", "e64") if op not in ("v_bfm_b32", "v_bcnt_u32_b32") else ("e64",)))

# (body, reference(x, y, z, w) -> four bytes, constant word sets, [(channel, wrong reference), ...])
BITS_PACK_PROGRAMS = (
    ([
        "v_mov_b32_e32 v23, s46",  # GFX10 VOP3 reads at most two SGPRs or literals
        "v_bfe_u32 v19, s44, s45, v23", ubyte(0, 12, "v19", "e32"),
        "v_bfe_u32 v20, s44, 4, 8", ubyte(0, 13, "v20", "e32"),
        "v_bfe_i32 v21, s44, s45, v23", ubyte(3, 14, "v21", "e32"),
        "v_bfe_i32 v22, s47, 28, 8", ubyte(2, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(bfe_u(x, y, z), 0), byte(bfe_u(x, 4, 8), 0), byte(bfe_i(x, y, z), 3),
                           byte(bfe_i(w, 28, 8), 2)],
     ((0x9abcdef1, 0x00000024, 0x0000002c, 0x80000000), (0x12345678, 0xffffffe8, 0x00000028, 0x70000000),
      (0xfedcba98, 0x00000001, 0x00000020, 0x9fffffff)),
     [(0, lambda x, y, z, w: byte((x >> y if y < 32 else 0) & ((1 << z) - 1), 0)),  # offset not masked
      (1, lambda x, y, z, w: byte(bfe_u(x, 8, 4), 0)),  # offset and width swapped
      (2, lambda x, y, z, w: byte(bfe_u(x, y, z), 3)),  # no sign extension
      (2, lambda x, y, z, w: byte(bfe_i(x, y, z if z < 32 else 31), 3)),  # width not masked
      (3, lambda x, y, z, w: byte(zero_fill_i(w, 28, 8), 2))]),  # logical shift before the extension
    ([
        "v_mov_b32_e32 v18, s47",
        "v_mov_b32_e32 v23, s46",
        "v_bfe_u32 v19, v18, 0, 16", ubyte(1, 12, "v19", "e32"),
        "v_bfe_i32 v20, v18, s46, s45", ubyte(0, 13, "v20", "e32"),
        "v_bfe_u32 v21, 0x8000c3a5, s45, v23", ubyte(0, 14, "v21", "e32"),
        "v_bfe_i32 v22, s44, s45, 32", ubyte(0, 15, "v22", "e32"),
    ], lambda x, y, z, w: [byte(bfe_u(w, 0, 16), 1), byte(bfe_i(w, z, y), 0), byte(bfe_u(0x8000c3a5, y, z), 0),
                           byte(bfe_i(x, y, 32), 0)],
     ((0xa5c3e187, 0x00000003, 0x00000027, 0x3c96b45a), (0x93f1c2d4, 0x00000025, 0x0000000c, 0x4be3a05c)),
     [(0, lambda x, y, z, w: byte(bfe_u(w, 16, 0), 1)),
      (1, lambda x, y, z, w: byte(bfe_i(w, y, z), 0)),  # operands in the wrong order
      (2, lambda x, y, z, w: byte(bfe_u(0x8000c3a5, z, y), 0)),
      (3, lambda x, y, z, w: byte(bfe_i(x, y, 31), 0))]),  # width 32 not masked to 0
    ([
        "v_cvt_pk_u16_u32 v19, s44, s45", ubyte(0, 12, "v19", "e32"), ubyte(3, 13, "v19", "e32"),
        "v_cvt_pk_i16_i32 v20, s46, s47", ubyte(1, 14, "v20", "e32"), ubyte(2, 15, "v20", "e32"),
    ], lambda x, y, z, w: [byte(pack(sat_u16(x), sat_u16(y)), 0), byte(pack(sat_u16(x), sat_u16(y)), 3),
                           byte(pack(sat_i16(z), sat_i16(w)), 1), byte(pack(sat_i16(z), sat_i16(w)), 2)],
     ((0x00012345, 0x00001234, 0xffff7000, 0x00009000), (0x0000abcd, 0x00fedcba, 0xffffff80, 0x00001234),
      (0x80000000, 0x0000ffff, 0x00007fff, 0xffff8000), (0x000000ff, 0x00010000, 0x7fffffff, 0x80000000)),
     [(0, lambda x, y, z, w: byte(x & 0xffff, 0)),  # truncating pack
      (1, lambda x, y, z, w: byte(y & 0xffff, 1)),
      (1, lambda x, y, z, w: byte(sat_u16(x), 1)),  # halves swapped
      (2, lambda x, y, z, w: byte(min(z, 0x7fff), 1)),  # signed clamp done unsigned
      (2, lambda x, y, z, w: byte(z & 0xffff, 1)),
      (3, lambda x, y, z, w: byte(sat_u16(w), 0))]),  # unsigned saturation for the signed pack
    ([
        "v_mov_b32_e32 v18, s45",
        "v_cvt_pk_u16_u32 v19, v18, 0", ubyte(1, 12, "v19", "e32"), ubyte(2, 13, "v19", "e32"),
        "v_cvt_pk_i16_i32 v20, -1, v18", ubyte(0, 14, "v20", "e32"), ubyte(3, 15, "v20", "e32"),
    ], lambda x, y, z, w: [byte(sat_u16(y), 1), 0, 0xff, byte(sat_i16(y), 1)],
     ((0, 0x4b8a2c35, 0, 0), (0, 0x3f801234, 0, 0), (0, 0xbf80c3a5, 0, 0), (0, 0x00005a3c, 0, 0)),
     [(0, lambda x, y, z, w: byte(y, 1)),
      (1, lambda x, y, z, w: byte(y, 2)),  # the high half is S1 = 0, not the high half of S0
      (3, lambda x, y, z, w: byte(sat_u16(y), 1)),
      (3, lambda x, y, z, w: byte(y, 1))]),
    *BIT_ENTRIES,
)


def check_bits_pack_draws(directory, compiler, renderer, backend):
    for index, (body, reference, sets, bugs) in enumerate(BITS_PACK_PROGRAMS):
        source = directory / f"bits_pack_{index}.hlsl"
        shader = directory / f"bits_pack_{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        batch = DrawBatch(directory, renderer, backend, shader, "bits_pack")
        separated = [False] * len(bugs)
        for words in sets:
            if "v_mov_b32_e32 v18, s47" in body:
                assert 0 < (words[3] >> 23) & 0xff < 255, hex(words[3])
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = [float(v) for v in reference(*words)]
            batch.add(constants + struct.pack("<4f", *expected) * 64, "pass",
                      f"Program {index} gives a result other than {expected} for words {[hex(v) for v in words]}")
            for k, (channel, buggy) in enumerate(bugs):
                value = float(buggy(*words))
                if value == expected[channel]:
                    continue
                separated[k] = True
                wrong = list(expected)
                wrong[channel] = value
                batch.add(constants + struct.pack("<4f", *wrong) * 64, "mismatch",
                          f"A wrong bitfield or pack result escaped detection in program {index}, "
                          f"channel {channel}, words {[hex(v) for v in words]}")
        batch.flush()
        assert all(separated), (index, separated)


def controls(directory):
    source = translate(with_constants(BITS_PACK_PROGRAMS[0][0]))
    assert "uint v_bfe_i32(" in source and "asfloat(params" not in source.split("float4 main", 1)[1], source
    source = translate(with_constants(BITS_PACK_PROGRAMS[2][0])).split("float4 main", 1)[1]
    assert "min(params[0].w, 0xffffu)" in source and "clamp(asint(params[1].y), -32768, 32767)" in source, source
    # Integer forms take no modifiers and no clamp; a missing operand and unset or pending registers are refused.
    for line in ("v_bfe_u32 v19, -s44, s45, s46", "v_bfe_u32 v19, |s44|, s45, s46", "v_bfe_u32 v19, s44, s45, s46 clamp",
                 "v_bfe_i32 v19, s44, s45", "v_bfe_u32_e32 v19, s44, s45, s46", "v_bfe_u32 v19, v30, s45, s46",
                 "v_cvt_pk_u16_u32 v19, -s44, s45", "v_cvt_pk_i16_i32 v19, s44, s45 clamp",
                 "v_cvt_pk_u16_u32 v19, s44", "v_cvt_pk_u16_u32_e32 v19, s44, s45", "v_cvt_pk_u16_u32 v19, s44, v30",
                 "v_cvt_pk_u16_u32 v19, s44, s45 mul:2"):
        must_reject(translate, with_constants([line]))
    # The new bit forms: two-source forms are VOP3 only, no modifiers or clamp, no SDWA or DPP, no lane-count
    # variants, and no operand that is unset, a vector pending a load or an SCC.
    for line in ("v_bfm_b32_e32 v19, s44, s45", "v_bcnt_u32_b32_e32 v19, s44, s45", "v_bfm_b32 v19, -s44, s45",
                 "v_bcnt_u32_b32 v19, |s44|, s45", "v_bfm_b32 v19, s44, s45 clamp", "v_bcnt_u32_b32 v19, s44",
                 "v_bfm_b32 v19, s44, s45, s46", "v_bcnt_u32_b32 v19, v30, s45", "v_bfm_b32 v19, s44, scc",
                 "v_ffbh_u32 v19, -s44", "v_ffbh_i32 v19, |s44|", "v_ffbl_b32 v19, s44 clamp",
                 "v_ffbh_u32 v19, s44, s45", "v_ffbl_b32_e32 v19, v30", "v_ffbh_i32_sdwa v19, s44",
                 "v_ffbh_u32_dpp v19, v20", "v_ffbl_b32 v19, s44 mul:2", "v_mbcnt_lo_u32_b32 v19, s44, s45",
                 "v_mbcnt_hi_u32_b32 v19, s44, s45"):
        must_reject(translate, with_constants([line]))
    source = translate(with_constants(bit_program_body("v_ffbh_i32", "e32"))).split("float4 main", 1)[1]
    assert "countbits" not in source and "uint v_ffbh_u32(" in translate(
        with_constants(bit_program_body("v_ffbh_i32", "e32"))), source
    source = translate(with_constants(bit_program_body("v_bcnt_u32_b32", "e64"))).split("float4 main", 1)[1]
    assert "countbits(" in source and "asfloat(params" not in source, source
    program = with_constants([])
    wait = program.index("s_waitcnt vmcnt(0)")
    for early in ("v_bfe_u32 v18, v12, 0, 8", "v_cvt_pk_u16_u32 v18, v13, 0", "v_bfe_u32 v13, s44, 0, 8",
                  "v_bcnt_u32_b32 v18, v12, 0", "v_ffbh_u32 v18, v13", "v_ffbl_b32 v13, s44", "v_bfm_b32 v13, 1, 2"):
        must_reject(translate, program[:wait] + [early] + program[wait:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for body, *_ in BITS_PACK_PROGRAMS]


draw = check_bits_pack_draws
