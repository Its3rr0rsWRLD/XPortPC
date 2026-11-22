"""Draw family `sopk`: pixel_aot_check.py draw --family sopk.

SOPK scalar arithmetic: s_addk_i32 and s_mulk_i32 (s_movk_i32 has its own family, `movk`). Each channel reads one
byte of an SGPR back exactly through v_cvt_f32_ubyteN, or the SCC an instruction left, observed with s_cselect_b32
between 0xa5 and 0x3c. The first program is the one of R0Y00/Xbox2Windows#333 by wh1skrzzz (s_mulk_i32 by 3 and
s_addk_i32 by 0xfffe on the float words of the pairs (0.5, 0.25) and (0.125, 1.0), whose references it also keeps), with the
whole result word read back instead of the float it happens to be. The other programs use immediates with bit 15 set
and clear and sets that overflow the signed add, carry the unsigned add without overflowing it, and check that
s_mulk_i32 leaves the SCC of an earlier s_addk_i32. Wrong references: a zero-extended immediate, the carry for the
overflow, an inverted SCC, an SCC taken from the multiply and a wrong multiplier.
"""
import struct
import subprocess

from .common import M32, byte, must_reject, translate, ubyte, with_constants

YES, NO = 0xa5, 0x3c
RED, GREEN = 0x3f000000, 0x3e800000  # float bits of 0.5 and 0.25


def scc(flag):
    return YES if flag else NO


def select(register):
    return f"s_cselect_b32 {register}, {YES:#x}, {NO:#x}"


def sext(imm):
    return (imm - 0x10000 if imm & 0x8000 else imm) & M32


def addk(value, imm):
    """(result, signed overflow) of s_addk_i32."""
    result = (value + sext(imm)) & M32
    return result, ((value ^ result) & (sext(imm) ^ result)) >> 31 == 1


def mulk(value, imm):
    return (value * sext(imm)) & M32


# (body, reference(x, y, z, w) -> four bytes, constant word sets, [(channel, wrong reference), ...])
SOPK_PROGRAMS = (
    # The program of #333: the red word times 3 and the green word plus -2.
    ([
        "s_mov_b32 s50, s44", "s_mulk_i32 s50, 0x3",
        "s_mov_b32 s51, s45", "s_addk_i32 s51, 0xfffe",
        ubyte(0, 12, "s50", "e32"), ubyte(3, 13, "s50", "e32"),
        ubyte(2, 14, "s51", "e32"), ubyte(3, 15, "s51", "e32"),
    ], lambda x, y, z, w: [byte(mulk(x, 3), 0), byte(mulk(x, 3), 3), byte(addk(y, 0xfffe)[0], 2),
                           byte(addk(y, 0xfffe)[0], 3)],
     ((RED, GREEN, 0, 0), (0x3e000000, 0x3f800000, 0, 0), (0x00000000, 0x00000001, 0, 0),
      (0x40000000, 0x00000000, 0, 0), (0x01234567, 0x00020001, 0, 0)),
     [(0, lambda x, y, z, w: byte(mulk(x, 5), 0)),  # wrong multiplier
      (2, lambda x, y, z, w: byte((y + 0xfffe) & M32, 2)),  # immediate zero-extended
      (3, lambda x, y, z, w: byte((y + 2) & M32, 3))]),  # sign flipped
    # Values with bit 15 of the immediate set and clear.
    ([
        "s_mov_b32 s0, s44", "s_addk_i32 s0, 0x8000", ubyte(0, 12, "s0", "e32"), ubyte(3, 13, "s0", "e32"),
        "s_mov_b32 s1, s45", "s_mulk_i32 s1, 0x8000", ubyte(2, 14, "s1", "e32"), ubyte(3, 15, "s1", "e32"),
    ], lambda x, y, z, w: [byte(addk(x, 0x8000)[0], 0), byte(addk(x, 0x8000)[0], 3), byte(mulk(y, 0x8000), 2),
                           byte(mulk(y, 0x8000), 3)],
     ((0x00012345, 0x00000003, 0, 0), (0xffff7fff, 0x80000001, 0, 0), (0x7fffffff, 0x00001234, 0, 0)),
     [(1, lambda x, y, z, w: byte((x + 0x8000) & M32, 3)),  # zero-extended immediate
      (3, lambda x, y, z, w: byte((y * 0x8000) & M32, 3)),
      (2, lambda x, y, z, w: byte(mulk(y, 0x7fff), 2))]),
    # SCC of s_addk_i32 is the signed overflow; s_mulk_i32 leaves it for the select that follows.
    ([
        "s_mov_b32 s0, s44", "s_addk_i32 s0, 0x7fff", select("s1"), ubyte(0, 12, "s1", "e32"),
        "s_mov_b32 s2, s45", "s_addk_i32 s2, 0xfffe", select("s3"), ubyte(0, 13, "s3", "e32"),
        "s_mov_b32 s4, s44", "s_addk_i32 s4, 0x7fff", "s_mulk_i32 s46, 0x3", select("s5"), ubyte(0, 14, "s5", "e32"),
        "s_mulk_i32 s47, 0x8000", ubyte(2, 15, "s47", "e32"),
    ], lambda x, y, z, w: [scc(addk(x, 0x7fff)[1]), scc(addk(y, 0xfffe)[1]), scc(addk(x, 0x7fff)[1]),
                           byte(mulk(w, 0x8000), 2)],
     ((0x7fffffff, 0x80000000, 5, 0x10001), (0x7fff8000, 0x80000001, 7, 0xfffffffe),
      (0x00000001, 0x00000002, 0x12345678, 0x80000000), (0x80000000, 0x7fffffff, 3, 0x0000ffff),
      (0xfffff000, 0x00000002, 1, 3)),
     [(0, lambda x, y, z, w: scc(x + sext(0x7fff) > M32)),  # the unsigned carry for the overflow
      (1, lambda x, y, z, w: scc((y + sext(0xfffe)) & 0x100000000 == 0)),  # carry of the sign-extended add
      (0, lambda x, y, z, w: scc(not addk(x, 0x7fff)[1])),  # inverted
      (2, lambda x, y, z, w: scc(mulk(z, 3) != 0)),  # the multiply sets SCC
      (2, lambda x, y, z, w: scc(False)),  # the multiply clears SCC
      (3, lambda x, y, z, w: byte(mulk(w, 0x8000), 3))]),
)


def check_sopk_draws(directory, compiler, renderer, backend):
    case = directory / "sopk.case"
    for index, (body, reference, sets, bugs) in enumerate(SOPK_PROGRAMS):
        source = directory / f"sopk_{index}.hlsl"
        shader = directory / f"sopk_{index}.cso"
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
                    raise AssertionError(f"A wrong SOPK result escaped detection in program {index}, channel "
                                         f"{channel}, words {[hex(v) for v in words]}")
        assert all(separated), (index, separated)


def controls(directory):
    source = translate(with_constants(SOPK_PROGRAMS[0][0])).split("float4 main", 1)[1]
    assert "* 3u;" in source and "+ 4294967294u;" in source and "asfloat(params" not in source, source
    source = translate(with_constants(SOPK_PROGRAMS[2][0])).split("float4 main", 1)[1]
    assert "& 0x80000000u) != 0u" in source, source
    # The immediate is 16 bits; the destination is a numeric scalar register; no vector or SCC operand, no
    # modifiers; a 64-bit destination; a destination nothing has set; a missing operand.
    for line in ("s_mulk_i32 s50, 0x10000", "s_addk_i32 s51, 0x10001", "s_addk_i32 s50, -32769",
                 "s_addk_i32 s50, 65536", "s_mulk_i32 s50, v45", "s_addk_i32 s50, s45", "s_mulk_i32 v50, 0x3",
                 "s_addk_i32 s[50:51], 1", "s_addk_i32 s50", "s_mulk_i32 s90, 1", "s_addk_i32 s28, 1",
                 "s_cmovk_i32 s44, 1", "s_addk_i32 s44, 1 clamp", "s_mulk_i32 s106, 1"):
        must_reject(translate, with_constants([line]))
    # A destination whose load has not completed.
    program = with_constants([])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    for early in ("s_mulk_i32 s44, 0x3", "s_addk_i32 s45, 1"):
        must_reject(translate, program[:load] + [early] + program[load:])
    # An accepted decimal immediate means the same word as its hex form.
    assert translate(with_constants(["s_addk_i32 s44, -2"])) == translate(with_constants(["s_addk_i32 s44, 0xfffe"]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(with_constants(body), translate) for body, *_ in SOPK_PROGRAMS]


draw = check_sopk_draws
