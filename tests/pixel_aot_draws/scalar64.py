"""Draw family `scalar64`: pixel_aot_check.py draw --family scalar64."""
import struct
import subprocess

from .common import assembly, half_rtz, must_reject, translate
from .select import select


SCALAR64_SETS = (
    # (a_lo, a_hi, b_lo, b_hi, sh_lo, sh_hi, bfm_w, bfm_off, bfe_src, bfe_ctrl_a, bfe_ctrl_b, alt)
    (0x89abcdef, 0x91234567, 0x55aa55aa, 0x7fffffff, 5, 37, 12, 28, 0x9a345f50, 0x00080004, 0x00100018, 0x55aa55aa),
    (0x0000a5a5, 0x0f0f0000, 0xffff5a5a, 0xf0f0ffff, 0, 100, 40, 16, 0x9a345f50, 0x00000000, 0x00000000, 0x00000000),
)


def scalar64():
    """Exercise 64-bit SOP1/SOP2 scalar ALU and 32-bit BFE, packing 40 output bits into exact binary16 floats."""
    program = assembly(False)
    pos = program.index("s_mov_b32 s40, 1")
    program.insert(pos, "s_load_dwordx4 s[44:47], s[20:21], 0x40")
    pos = program.index("s_waitcnt vmcnt(0)")
    program[pos:pos] = [
        "s_buffer_load_dwordx4 s[52:55], s[44:47], 0x10",
        "s_buffer_load_dwordx4 s[56:59], s[44:47], 0x20",
        "s_buffer_load_dwordx4 s[60:63], s[44:47], 0x30",
        "s_waitcnt lgkmcnt(0)",
    ]

    body = [
        "s_mov_b32 s64, 0",
        "s_mov_b32 s65, 0",
        "s_mov_b32 s66, 0",
        "s_mov_b32 s67, 0",
        "s_mov_b32 s78, 0",
        "s_mov_b32 s79, 0",
        "s_mov_b32 s82, s63",
        "s_mov_b32 s83, 0",
    ]

    def capture_scc(bit_index):
        body.extend([
            "s_mov_b32 s70, 0",
            "s_mov_b32 s71, 0",
            f"s_bfm_b64 s[74:75], 1, {bit_index}",
            "s_cmov_b64 s[70:71], s[74:75]",
            "s_or_b64 s[66:67], s[66:67], s[70:71]",
        ])

    def mix_acc(pair):
        body.extend([
            "s_lshl_b64 s[68:69], s[64:65], 3",
            "s_lshr_b64 s[64:65], s[64:65], 61",
            "s_or_b64 s[64:65], s[64:65], s[68:69]",
            f"s_xor_b64 s[64:65], s[64:65], {pair}",
        ])

    # Bit 0: s_and_b64 + two consecutive s_cmov_b64 (inline -1 sign-extended and SCC preserved).
    body.extend([
        "s_and_b64 s[72:73], s[52:53], s[54:55]",
        "s_cmov_b64 s[78:79], -1",
    ])
    capture_scc(0)
    mix_acc("s[72:73]")
    mix_acc("s[78:79]")

    # Bit 1: s_or_b64 (full 64-bit union saved in s[84:85] + SCC probe on s[82:83]).
    body.append("s_or_b64 s[84:85], s[52:53], s[54:55]")
    mix_acc("s[84:85]")
    body.append("s_or_b64 s[72:73], s[82:83], 0")
    capture_scc(1)

    # Bit 2: s_xor_b64 (register pair and zero-extended 32-bit hex literal).
    body.append("s_xor_b64 s[72:73], s[52:53], s[54:55]")
    mix_acc("s[72:73]")
    body.append("s_xor_b64 s[72:73], s[82:83], 0x55aa55aa")
    capture_scc(2)
    mix_acc("s[72:73]")

    # Bit 3: s_andn2_b64 (register pair + SCC probe).
    body.append("s_andn2_b64 s[72:73], s[52:53], s[54:55]")
    mix_acc("s[72:73]")
    body.append("s_andn2_b64 s[72:73], s[82:83], 0xf0f0f0f")
    capture_scc(3)

    # Bit 4: s_orn2_b64 (register pair + inline -1 proving 64-bit all-ones inversion).
    body.append("s_orn2_b64 s[72:73], s[52:53], s[54:55]")
    mix_acc("s[72:73]")
    body.append("s_orn2_b64 s[72:73], s[82:83], -1")
    capture_scc(4)

    # Bit 5: s_not_b64 + s_brev_b64 (s_brev_b64 placed before capture_scc to verify SCC preservation).
    body.append("s_not_b64 s[72:73], s[52:53]")
    mix_acc("s[72:73]")
    body.extend([
        "s_not_b64 s[72:73], s[84:85]",
        "s_brev_b64 s[86:87], s[52:53]",
    ])
    capture_scc(5)
    mix_acc("s[86:87]")

    # Bit 6: s_lshl_b64 across small/zero and >=32/wrapped shift counts.
    body.append("s_lshl_b64 s[72:73], s[52:53], s56")
    mix_acc("s[72:73]")
    body.append("s_lshl_b64 s[72:73], s[52:53], s57")
    mix_acc("s[72:73]")
    body.append("s_lshl_b64 s[72:73], s[82:83], s57")
    capture_scc(6)

    # Bit 7: s_lshr_b64 across small/zero and >=32/wrapped shift counts.
    body.append("s_lshr_b64 s[72:73], s[52:53], s56")
    mix_acc("s[72:73]")
    body.append("s_lshr_b64 s[72:73], s[52:53], s57")
    mix_acc("s[72:73]")
    body.append("s_lshr_b64 s[72:73], s[82:83], s56")
    capture_scc(7)

    # Bit 8: s_ashr_i64 (signed) + s_bfm_b64 (preserving SCC, plus w=0 and w=32 boundaries).
    body.append("s_ashr_i64 s[72:73], s[52:53], s56")
    mix_acc("s[72:73]")
    body.append("s_ashr_i64 s[72:73], s[52:53], s57")
    mix_acc("s[72:73]")
    body.extend([
        "s_ashr_i64 s[72:73], s[82:83], s56",
        "s_bfm_b64 s[86:87], s58, s59",
    ])
    capture_scc(8)
    mix_acc("s[86:87]")
    body.append("s_bfm_b64 s[88:89], 0, 5")
    mix_acc("s[88:89]")
    body.append("s_bfm_b64 s[88:89], 32, 16")
    mix_acc("s[88:89]")

    # Bit 9: s_bfe_u32 (SCC observed via s_cmov_b64 into acc) and s_bfe_i32 (SCC observed in bit 9).
    body.extend([
        "s_mov_b32 s78, 0",
        "s_mov_b32 s79, 0",
        "s_bfe_u32 s72, s60, s61",
        "s_cmov_b64 s[78:79], 0x13572468",
        "s_bfe_u32 s73, s60, s62",
    ])
    mix_acc("s[72:73]")
    mix_acc("s[78:79]")
    body.extend([
        "s_bfe_i32 s72, s60, s61",
        "s_bfe_i32 s73, s60, s62",
    ])
    capture_scc(9)
    mix_acc("s[72:73]")

    # s_nand_b64, s_nor_b64 and s_xnor_b64: the register pair, then an SCC probe. Channel 3 exports
    # only SCC bits 0-9, so each probe's SCC reaches acc through s_cmov_b64 of a distinct literal.
    # nand(-1, -1) and nor(alt, -1) are zero, and xnor(alt, -1) = alt is zero only in Set 2.
    for op, probe, marker in (("s_nand_b64", "-1, -1", "0x2468ace0"),
                              ("s_nor_b64", "s[82:83], -1", "0x13579bdf"),
                              ("s_xnor_b64", "s[82:83], -1", "0x0fedcba9")):
        body.append(f"{op} s[72:73], s[52:53], s[54:55]")
        mix_acc("s[72:73]")
        body.extend([
            "s_mov_b32 s78, 0",
            "s_mov_b32 s79, 0",
            f"{op} s[72:73], {probe}",
            f"s_cmov_b64 s[78:79], {marker}",
        ])
        mix_acc("s[72:73]")
        mix_acc("s[78:79]")

    # Fold all 64 bits of acc into bits [29:0] of s64: acc ^ (acc >> 30) ^ (acc >> 60), both shifts of the
    # original acc, so every bit reaches the export. Repeating x ^= x >> 30 instead gives x ^ (x >> 60)
    # and drops bits 30-59. Then export 4 x 10-bit fields as 1 + k/1024.
    body.extend([
        "s_lshr_b64 s[68:69], s[64:65], 30",
        "s_lshr_b64 s[70:71], s[64:65], 60",
        "s_xor_b64 s[64:65], s[64:65], s[68:69]",
        "s_xor_b64 s[64:65], s[64:65], s[70:71]",
    ])
    for channel, (src, ctrl) in enumerate((("s64", "0xa0000"), ("s64", "0xa000a"),
                                           ("s64", "0xa0014"), ("s66", "0xa0000"))):
        body.extend([
            f"s_bfe_u32 s80, {src}, {ctrl}",
            "s_mov_b32 s81, 0",
            "s_lshl_b64 s[80:81], s[80:81], 13",
            "s_or_b64 s[80:81], s[80:81], 0x3f800000",
            f"v_mov_b32_e32 v{12 + channel}, s80",
        ])

    pos = program.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    program[pos:pos] = body
    return program


def scalar64_reference(program, words):
    """Independent Python ISA reference for scalar64() using wide integers."""
    mask32, mask64 = 0xffffffff, 0xffffffffffffffff
    regs = {}
    scc = None
    channels = {}

    def read32(tok):
        if tok.startswith("s"):
            return regs[tok] & mask32
        return int(tok, 0) & mask32

    def read64(tok, signed=False):
        if tok.startswith("s["):
            lo, hi = map(int, tok[2:-1].split(":"))
            return (regs[f"s{lo}"] & mask32) | ((regs[f"s{hi}"] & mask32) << 32)
        if tok.startswith("0x"):
            v = int(tok, 16)
            return v | (0xffffffff00000000 if signed and (v & 0x80000000) else 0)
        return int(tok, 0) & mask64

    def write64(tok, val):
        lo, hi = map(int, tok[2:-1].split(":"))
        val &= mask64
        regs[f"s{lo}"] = val & mask32
        regs[f"s{hi}"] = (val >> 32) & mask32

    for line in program:
        op, _, rest = line.partition(" ")
        ops = [t.strip() for t in rest.split(",")] if rest else []
        if op == "s_buffer_load_dwordx4":
            lo = int(ops[0][2:-1].split(":")[0])
            start = (0 if ops[2] == "null" else int(ops[2], 16)) // 4
            for j in range(4):
                regs[f"s{lo + j}"] = words[start + j]
        elif op == "s_mov_b32" and ops[0].startswith("s") and not ops[1].startswith("s2"):
            regs[ops[0]] = read32(ops[1])
        elif op == "s_and_b64" and ops[0].startswith("s["):
            v = read64(ops[1]) & read64(ops[2])
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_or_b64":
            v = read64(ops[1]) | read64(ops[2])
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_xor_b64":
            v = read64(ops[1]) ^ read64(ops[2])
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_andn2_b64":
            v = read64(ops[1]) & (~read64(ops[2]) & mask64)
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_orn2_b64":
            v = read64(ops[1]) | (~read64(ops[2]) & mask64)
            write64(ops[0], v)
            scc = v != 0
        elif op in ("s_nand_b64", "s_nor_b64", "s_xnor_b64"):
            a, b = read64(ops[1]), read64(ops[2])
            v = ~{"s_nand_b64": a & b, "s_nor_b64": a | b, "s_xnor_b64": a ^ b}[op] & mask64
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_not_b64":
            v = ~read64(ops[1]) & mask64
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_brev_b64":
            x = read64(ops[1])
            v = int(f"{x:064b}"[::-1], 2)
            write64(ops[0], v)
        elif op == "s_cmov_b64":
            assert scc is not None
            if scc:
                write64(ops[0], read64(ops[1]))
        elif op == "s_lshl_b64":
            v = (read64(ops[1]) << (read32(ops[2]) & 63)) & mask64
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_lshr_b64":
            v = read64(ops[1]) >> (read32(ops[2]) & 63)
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_ashr_i64":
            x = read64(ops[1], signed=True)
            if x >= (1 << 63):
                x -= 1 << 64
            v = (x >> (read32(ops[2]) & 63)) & mask64
            write64(ops[0], v)
            scc = v != 0
        elif op == "s_bfm_b64":
            w = read32(ops[1]) & 63
            off = read32(ops[2]) & 63
            v = (((1 << w) - 1) << off) & mask64
            write64(ops[0], v)
        elif op in ("s_bfe_u32", "s_bfe_i32"):
            src = read32(ops[1])
            ctrl = read32(ops[2])
            off = ctrl & 31
            w = (ctrl >> 16) & 127
            if w == 0:
                v = 0
            elif op == "s_bfe_u32":
                v = (src >> off) & ((1 << min(w, 32)) - 1)
            else:
                if off + w < 32:
                    raw = (src >> off) & ((1 << w) - 1)
                    if raw & (1 << (w - 1)):
                        raw -= 1 << w
                else:
                    raw = (src - (1 << 32) if src & 0x80000000 else src) >> off
                v = raw & mask32
            regs[ops[0]] = v
            scc = v != 0
        elif op == "v_mov_b32_e32" and ops[0] in ("v12", "v13", "v14", "v15"):
            bits = regs[ops[1]] & mask32
            val, = struct.unpack("<f", struct.pack("<I", bits))
            assert half_rtz(val) == val, hex(bits)
            channels[ops[0]] = val
    return tuple(channels[f"v{12 + c}"] for c in range(4)), regs["s66"] & 0x3ff


def scalar64_case(directory, values):
    constants = bytearray(256)
    struct.pack_into("<12I", constants, 16, *values)
    words = struct.unpack("<64I", constants)
    color, _ = scalar64_reference(scalar64(), words)
    path = directory / "scalar64.case"
    path.write_bytes(constants + struct.pack("<4f", *color) * 64)
    return path


def check_scalar64_draws(directory, compiler, renderer, backend):
    source = directory / "fixture.hlsl"
    shader = directory / "fixture.cso"
    program = scalar64()
    source.write_text(translate(program), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    for values in SCALAR64_SETS:
        case = scalar64_case(directory, values)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        subprocess.run(draw, check=True)
    # Keep the original two sets for the SCC toggle checks and add a draw-only case.
    _, _, *middle, _, alt = SCALAR64_SETS[0]
    a = 0x11234567 << 32 | 0xffffffff
    b = middle[1] << 32 | middle[0]
    # s_not_b64 of a | b sets only bit 63, so its SCC depends on the high word alone.
    assert ~(a | b) & (2**64 - 1) == 1 << 63
    case = scalar64_case(directory, (0xffffffff, 0x11234567, *middle, 0x00400018, alt))
    subprocess.run([renderer, backend, "--check-pixel-case", shader, case], check=True)
    # Mutations verified against Set 1 (where negative signed values and SCC=1 paths are active).
    set1_case = scalar64_case(directory, SCALAR64_SETS[0])
    draw = [renderer, backend, "--check-pixel-case", shader, set1_case]
    for old, new, label in (
        ("s_ashr_i64 s[72:73], s[52:53], s56", "s_lshr_b64 s[72:73], s[52:53], s56", "signed right shift"),
        ("s_bfe_i32 s72, s60, s61", "s_bfe_u32 s72, s60, s61", "signed bitfield extract"),
        ("s_andn2_b64 s[72:73], s[52:53], s[54:55]", "s_and_b64 s[72:73], s[52:53], s[54:55]", "andn2 inversion"),
        ("s_cmov_b64 s[78:79], -1", "s_cmov_b64 s[78:79], 0", "conditional move"),
        ("s_nand_b64 s[72:73], s[52:53], s[54:55]", "s_and_b64 s[72:73], s[52:53], s[54:55]", "nand inversion"),
        ("s_nor_b64 s[72:73], s[52:53], s[54:55]", "s_or_b64 s[72:73], s[52:53], s[54:55]", "nor inversion"),
        ("s_xnor_b64 s[72:73], s[52:53], s[54:55]", "s_xor_b64 s[72:73], s[52:53], s[54:55]", "xnor inversion"),
        ("s_nor_b64 s[72:73], s[82:83], -1", "s_nor_b64 s[72:73], s[82:83], 0", "nor SCC probe"),
    ):
        mutated = [line.replace(old, new) for line in program]
        assert mutated != program, label
        source.write_text(translate(mutated), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        wrong = subprocess.run(draw, capture_output=True, text=True)
        if wrong.returncode != 1 or "pixel_mismatch" not in wrong.stderr:
            raise AssertionError(f"Mutation of {label} escaped detection")


def controls(directory):
    # 64-bit scalar ALU and 32-bit BFE controls.
    program = scalar64()
    source = translate(program)
    for expected in ("uint2 s_lshl_b64(", "uint2 s_lshr_b64(", "uint2 s_ashr_i64(",
                     "uint2 s_bfm_b64(", "uint s_bfe_u32(", "uint s_bfe_i32(",
                     "reversebits(", " = salu"):
        assert expected in source, expected
    # Existing programs without shifts/bfm/bfe emit none of the scalar helper functions.
    assert "uint2 s_lshl_b64(" not in translate(assembly(False))
    # Verify 32-bit hex literal sign-extension for s_ashr_i64 vs zero-extension for b64 ops.
    ashr_pos = program.index("s_ashr_i64 s[72:73], s[52:53], s56")
    signed_lit = translate(program[:ashr_pos] + ["s_ashr_i64 s[72:73], 0x80000000, 4"] + program[ashr_pos+1:])
    assert "s_ashr_i64(uint2(2147483648u, 4294967295u), 4u)" in signed_lit
    unsigned_lit = translate(program[:ashr_pos] + ["s_and_b64 s[72:73], s[52:53], 0x80000000"] + program[ashr_pos+1:])
    assert "2147483648u" in unsigned_lit and "0u)" in unsigned_lit
    # Verify all 10 SCC observation bits flip between the two constant sets.
    refs = []
    for values in SCALAR64_SETS:
        constants = bytearray(256)
        struct.pack_into("<12I", constants, 16, *values)
        refs.append(scalar64_reference(program, struct.unpack("<64I", constants)))
    assert (refs[0][1] ^ refs[1][1]) == 0x3ff, (bin(refs[0][1]), bin(refs[1][1]))
    # Negative controls: exec save/restore, #257 ops, out-of-scope 64-bit ops, invalid operands and SCC rules.
    body_start = program.index("s_and_b64 s[72:73], s[52:53], s[54:55]")
    for bad in (
        "s_and_saveexec_b64 s[70:71], s[52:53]",
        "s_or_saveexec_b64 s[70:71], s[52:53]",
        "s_andn2_saveexec_b64 s[70:71], s[52:53]",
        "s_or_b64 exec, exec, s[52:53]",
        "s_and_b64 vcc, s[52:53], s[54:55]",
        "s_cmov_b64 exec, s[52:53]",
        "s_not_b64 vcc, s[52:53]",
        "s_and_b64 s[70:71], exec, s[52:53]",
        "s_xor_b64 s[70:71], vcc, s[52:53]",
        "s_cmov_b64 s[70:71], s[52:53]",  # before any SCC write
        "s_and_b64 s[53:54], s[52:53], s[54:55]",  # unaligned pair
        "s_and_b64 s[106:107], s[52:53], s[54:55]",  # out-of-range SGPR pair
        "s_bfe_u32 s106, s60, 0x80004",  # out-of-range SGPR
        "s_bfe_u32 s70, v12, 0x80004",  # VGPR source
        "s_bfe_u32 s70, m0, 0x80004",  # m0 source
        "s_and_b64 s[70:71], s[28:29], s[52:53]",  # texture descriptor source
        "s_and_b64 s[70:71], s[44:45], s[52:53]",  # CBV descriptor source
        "s_and_b64 s[70:71], s[50:51], s[52:53]",  # saved exec source
        "s_and_b64 s[70:71], s[20:21], s[52:53]",  # texture_ptr source
        "s_and_b64 s[70:71], s[90:91], s[52:53]",  # unset source
        "s_cselect_b64 s[70:71], s[52:53], s[54:55]",  # before any SCC write
        # s_bfe_u64/i64, s_cmp_eq_u64, s_bitcmp1_b32/b64 and s_not_b32 are lowered now (draw family salu_rest)
        "s_addc_u32 s70, s56, s57",
    ):
        must_reject(translate, program[:body_start] + [bad] + program[body_start:])
    # s_cmov_b64 rejects unset or non-numeric destination pairs even after SCC is set.
    after_and = body_start + 1
    for bad_dst in ("s[90:91]", "s[44:45]", "s[50:51]", "s[28:29]"):
        must_reject(translate, program[:after_and] + [f"s_cmov_b64 {bad_dst}, s[52:53]"] + program[after_and:])
    # Pending scalar load read and write overlap must be rejected.
    load_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[60:63], s[44:47], 0x30"))
    for early in ("s_and_b64 s[70:71], s[52:53], s[54:55]", "s_not_b64 s[52:53], 0", "s_bfe_u32 s60, 1, 0x80004"):
        must_reject(translate, program[:load_wait] + [early] + program[load_wait:])
    # s_wqm_b64 and exec-restoring s_and_b64 clear tracked SCC.
    wqm_pos = program.index("s_wqm_b64 exec, exec")
    exec_restore_pos = program.index("s_and_b64 exec, exec, s[50:51]")
    prefix = ["s_mov_b32 s90, 0", "s_mov_b32 s91, 0", "s_not_b64 s[92:93], 0"]
    must_reject(translate, program[:wqm_pos] + prefix + [program[wqm_pos], "s_cmov_b64 s[90:91], s[92:93]"] + program[wqm_pos+1:])
    must_reject(translate, program[:exec_restore_pos] + prefix + [program[exec_restore_pos], "s_cmov_b64 s[90:91], s[92:93]"] + program[exec_restore_pos+1:])
    # A scalar result cannot supply a sampler word, texture address high word, or v_cndmask condition.
    sample_pos = program.index("image_sample v[12:15], v[8:9], s[28:35], s[40:43] dmask:0xf dim:SQ_RSRC_IMG_2D")
    must_reject(translate, program[:sample_pos] + ["s_bfe_u32 s40, 1, 0x10000"] + program[sample_pos:])
    sel = select(True)
    cnd_pos = sel.index("v_cndmask_b32_e64 v13, v13, s46, s[52:53]")
    must_reject(translate, sel[:cnd_pos] + ["s_not_b64 s[52:53], 0"] + sel[cnd_pos:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        (scalar64(), translate),
    ]


draw = check_scalar64_draws
