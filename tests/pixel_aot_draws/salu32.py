"""Draw family `salu32`: pixel_aot_check.py draw --family salu32.

32-bit scalar ALU: s_and/or/xor/andn2/orn2_b32, s_lshl/lshr_b32, s_ashr_i32, s_bfm_b32, s_lshl1..4_add_u32 and
s_cselect_b32. Each channel reads one byte back exactly through v_cvt_f32_ubyteN from an SGPR: either a byte of a
result, or the SCC an instruction left, observed with s_cselect_b32 between 0xa5 and 0x3c. The constant sets make
each SCC both set and clear, give shift counts with bits above the low five, shift the top bit of a negative word,
and carry out of s_lshl<N>_add_u32 once through the shift and once through the add. The wrong references are the
plausible bugs: swapped andn2/orn2 operands, unmasked counts, a logical shift for the arithmetic one, an SCC from the
32-bit add alone or from the shift alone, s_bfm_b32 operands swapped, and an SCC that s_bfm_b32 clobbers.
"""
import struct
import subprocess

from .common import M32, byte, must_reject, signed, translate, with_constants

YES, NO = 0xa5, 0x3c


def scc(flag):
    return YES if flag else NO


def readback(channel, n, register):
    return f"v_cvt_f32_ubyte{n}_e32 v{12 + channel}, {register}"


def select(register):
    return f"s_cselect_b32 {register}, {YES:#x}, {NO:#x}"


def shl_add(a, b, n):
    total = (a << n) + b
    return total & M32, total >= 1 << 32


def bfm(width, offset):
    return (((1 << (width & 31)) - 1) << (offset & 31)) & M32


# (body, reference(x, y, z, w) -> four bytes, constant word sets, [(channel, wrong reference), ...])
SALU32_PROGRAMS = (
    # Bitwise results: an SGPR, a literal and an inline constant source.
    ([
        "s_and_b32 s0, s44, s45", readback(0, 0, "s0"),
        "s_or_b32 s1, s44, 0x0f0f0f0f", readback(1, 1, "s1"),
        "s_xor_b32 s2, s46, s45", readback(2, 2, "s2"),
        "s_andn2_b32 s3, s47, s44", readback(3, 3, "s3"),
    ], lambda x, y, z, w: [byte(x & y, 0), byte(x | 0x0f0f0f0f, 1), byte(z ^ y, 2), byte(w & ~x & M32, 3)],
     ((0xa5c3e187, 0x3c96b45a, 0x6d1e8f2b, 0xc2f0171d), (0x93f1c2d4, 0x5a1b7e69, 0x4be3a05c, 0x2c8d9f10)),
     [(0, lambda x, y, z, w: byte(x | y, 0)),
      (1, lambda x, y, z, w: byte(x & 0x0f0f0f0f, 1)),
      (2, lambda x, y, z, w: byte(~(z ^ y) & M32, 2)),
      (3, lambda x, y, z, w: byte(~w & x & M32, 3))]),  # andn2 operands swapped
    # s_orn2_b32 and the SCC of the bitwise forms: set when the result is nonzero.
    ([
        "s_orn2_b32 s0, s44, s45", readback(0, 3, "s0"),
        "s_and_b32 s1, s46, s47", select("s2"), readback(1, 0, "s2"),
        "s_xor_b32 s3, s46, s47", select("s4"), readback(2, 0, "s4"),
        "s_andn2_b32 s5, s46, s47", select("s6"), readback(3, 0, "s6"),
    ], lambda x, y, z, w: [byte(x | ~y & M32, 3), scc(z & w), scc(z ^ w), scc(z & ~w & M32)],
     ((0x12345678, 0x0f000000, 0xf0f00000, 0x0f0f0000), (0x9abcdef0, 0xf0000000, 0x12340000, 0x12340000),
      (0x00000000, 0xffffffff, 0x80000001, 0x00000001)),
     [(0, lambda x, y, z, w: byte(~x & M32 | y, 3)),  # orn2 operands swapped
      (1, lambda x, y, z, w: scc(not z & w)),  # SCC inverted
      (2, lambda x, y, z, w: scc(not z ^ w)),
      (3, lambda x, y, z, w: scc(not z & ~w & M32))]),
    # Shift results: counts with bits above the low five, a shifted-out top bit, a negative word.
    ([
        "s_lshl_b32 s0, s44, s45", readback(0, 3, "s0"),
        "s_lshr_b32 s1, s44, 36", readback(1, 2, "s1"),
        "s_ashr_i32 s2, s44, s46", readback(2, 3, "s2"),
        "s_lshl_b32 s3, s47, 4", readback(3, 1, "s3"),
    ], lambda x, y, z, w: [byte((x << (y & 31)) & M32, 3), byte(x >> 4, 2),
                           byte((signed(x) >> (z & 31)) & M32, 3), byte((w << 4) & M32, 1)],
     ((0xa5c3e187, 0x00000025, 0xffffffe3, 0x3c96b45a), (0x83d5f2a9, 0x00000041, 0x7ffffff8, 0x0000003b)),
     [(0, lambda x, y, z, w: byte((x << y) & M32 if y < 32 else 0, 3)),  # count not masked
      (1, lambda x, y, z, w: 0),  # count 36 not masked
      (2, lambda x, y, z, w: byte(x >> (z & 31), 3)),  # logical for arithmetic
      (3, lambda x, y, z, w: byte(w >> 4, 1))]),  # wrong direction
    # Shift SCC: s_lshl_b32 and s_lshr_b32 to zero and to nonzero, s_ashr_i32 of a negative word.
    ([
        "s_lshl_b32 s0, s44, s45", select("s1"), readback(0, 0, "s1"),
        "s_lshr_b32 s2, s46, s45", select("s3"), readback(1, 0, "s3"),
        "s_ashr_i32 s4, s47, 31", select("s5"), readback(2, 0, "s5"),
        "s_lshr_b32 s6, s44, s45", readback(3, 3, "s6"),
    ], lambda x, y, z, w: [scc((x << (y & 31)) & M32), scc(z >> (y & 31)), scc((signed(w) >> 31) & M32),
                           byte(x >> (y & 31), 3)],
     ((0x80000000, 0x00000021, 0x00000001, 0x80000000), (0x00010000, 0x00000030, 0x00ff0000, 0x7fffffff),
      (0x00000001, 0x00000021, 0x00000001, 0x00000000)),
     [(0, lambda x, y, z, w: scc((x << y) & M32 if y < 32 else 0)),  # count not masked
      (1, lambda x, y, z, w: scc(z >> y if y < 32 else 0)),
      (3, lambda x, y, z, w: byte(x >> y if y < 32 else 0, 3))]),
    # s_bfm_b32 and s_lshl<N>_add_u32 values; the SCC of s_lshl1_add_u32.
    ([
        "s_bfm_b32 s0, s44, s45", readback(0, 1, "s0"),
        "s_lshl2_add_u32 s1, s46, s47", readback(1, 3, "s1"),
        "s_lshl1_add_u32 s2, s46, s47", select("s3"), readback(2, 0, "s3"),
        "s_lshl4_add_u32 s4, s46, s47", readback(3, 0, "s4"),
    ], lambda x, y, z, w: [byte(bfm(x, y), 1), byte(shl_add(z, w, 2)[0], 3), scc(shl_add(z, w, 1)[1]),
                           byte(shl_add(z, w, 4)[0], 0)],
     ((0x0000002c, 0x00000024, 0x9abcdef1, 0x0000ffff), (0x00000007, 0x00000006, 0x7fffffff, 0x00000003),
      (0x00000010, 0x00000004, 0x1234567f, 0xfedcba98)),
     [(0, lambda x, y, z, w: byte(bfm(y, x), 1)),  # operands swapped
      (0, lambda x, y, z, w: byte((((1 << x) - 1) << y) & M32 if x < 32 and y < 32 else 0, 1)),  # unmasked
      (1, lambda x, y, z, w: byte(((z << 1) + w) & M32, 3)),  # wrong shift
      (2, lambda x, y, z, w: scc(((z << 1) & M32) + w >= 1 << 32)),  # SCC from the 32-bit add alone
      (2, lambda x, y, z, w: scc(z >> 31)),  # SCC from the shifted-out bit alone
      (3, lambda x, y, z, w: byte(((z << 4) | w) & M32, 0))]),  # or for add
    # s_lshl3_add_u32 SCC and value; s_bfm_b32 must leave that SCC for the next select.
    ([
        "s_lshl3_add_u32 s0, s44, s45", select("s1"), readback(0, 0, "s1"),
        readback(1, 3, "s0"),
        "s_bfm_b32 s2, s46, s47", select("s3"), readback(2, 0, "s3"),
        readback(3, 2, "s2"),
    ], lambda x, y, z, w: [scc(shl_add(x, y, 3)[1]), byte(shl_add(x, y, 3)[0], 3), scc(shl_add(x, y, 3)[1]),
                           byte(bfm(z, w), 2)],
     ((0x30000000, 0x00000005, 0x00000008, 0x00000010), (0x1fffffff, 0x00000010, 0x00000025, 0x00000008),
      (0x01000000, 0x00000005, 0x00000004, 0x00000014)),
     [(0, lambda x, y, z, w: scc(((x << 3) & M32) + y >= 1 << 32)),  # carry of the 32-bit add alone
      (0, lambda x, y, z, w: scc(x >> 29)),  # shifted-out bits alone
      (1, lambda x, y, z, w: byte(((x << 3) & M32) | y, 3)),
      (2, lambda x, y, z, w: scc(bfm(z, w))),  # s_bfm_b32 sets SCC
      (3, lambda x, y, z, w: byte(bfm(w, z), 2))]),
)


def check_salu32_draws(directory, compiler, renderer, backend):
    case = directory / "salu32.case"
    for index, (body, reference, sets, bugs) in enumerate(SALU32_PROGRAMS):
        source = directory / f"salu32_{index}.hlsl"
        shader = directory / f"salu32_{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        separated = [False] * len(bugs)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = [float(v) for v in reference(*words)]
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for k, (channel, buggy) in enumerate(bugs):
                value = float(buggy(*words))
                if value == expected[channel]:
                    continue
                separated[k] = True
                wrong = list(expected)
                wrong[channel] = value
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A wrong scalar result escaped detection in program {index}, channel "
                                         f"{channel}, words {[hex(v) for v in words]}")
        assert all(separated), (index, separated)


def controls(directory):
    # Every drawn program translates here too, so the forms they use are recorded by the controls run.
    for body, *_ in SALU32_PROGRAMS:
        translate(with_constants(body))
    source = translate(with_constants(SALU32_PROGRAMS[2][0])).split("float4 main", 1)[1]
    assert "asuint(asint(" in source and "& 31u)" in source and "36u & 31u" in source, source
    assert "asfloat(" not in source, source  # scalar words never take a float type
    source = translate(with_constants(SALU32_PROGRAMS[4][0])).split("float4 main", 1)[1]
    assert ">> 31u) != 0u) ||" in source and "<< 4u;" in source and "<< 2u;" in source, source
    # Refusals: no tracked SCC for the select, unset or vector sources, a pending load, a 64-bit destination,
    # a missing operand and an SCC source.
    for line in ("s_lshl_b32 s0, s44, v12", "s_and_b32 s0, s90, s45", "s_or_b32 s[0:1], s44, s45",
                 "s_lshl2_add_u32 s0, s44", "s_xor_b32 s0, s44, scc", "s_bfm_b32 s0, s44, v12",
                 "s_lshl5_add_u32 s0, s44, s45", "s_lshl0_add_u32 s0, s44, s45", "s_and_b32 s0, -s44, s45",
                 "s_and_b32 s0, s28, s45", "s_lshl_b32 s0, s20, 1", "s_or_b32 s106, s44, s45", "s_xor_b32 s0, m0, s45",
                 "s_cselect_b32 s0, exec_lo, s45"):
        must_reject(translate, with_constants([line]))
    must_reject(translate, with_constants([select("s0")]))
    program = with_constants([])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("s_lshl_b32 s0, s44, 1", "s_and_b32 s45, s0, s0", "s_bfm_b32 s46, 1, 2"):
        must_reject(translate, program[:load] + ["s_mov_b32 s0, 0", early] + program[load:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for body, *_ in SALU32_PROGRAMS]


draw = check_salu32_draws
