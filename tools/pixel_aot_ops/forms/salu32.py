"""32-bit scalar ALU (SOP2 and SOP1): bitwise operations, shifts, s_bfm_b32, s_lshl<N>_add_u32 and s_cselect_b32, and
the remaining 32-bit unary and arithmetic forms (second half of this file, see its comment).

Semantics: AMD RDNA 2 ISA guide, SOP2/SOP1 pseudocode. A shift count is S1[4:0]. The bitwise operations and shifts set
SCC to D != 0. s_lshl<N>_add_u32 computes (S0 << N) + S1 in 64 bits, keeps the low word and sets SCC when the sum is at
least 2^32: either a bit was shifted out of the word or the 32-bit add carried. s_bfm_b32 builds
((1 << S0[4:0]) - 1) << S1[4:0] and s_cselect_b32 selects S0 when SCC is set; both leave SCC unchanged. Every value is
an unsigned word (registers.scalar_u32), so no float type ever holds these bits.

Ported from R0Y00/Xbox2Windows#257 by Vonsek (the 32-bit scalar ALU table and s_cselect_b32), re-expressed for the
("uint", expr) register model; the s_lshl<N>_add_u32 and s_bfm_b32 forms are new here.
"""
from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import scalar_u32, scalar_u64, sgpr_name, sgpr_pair

SALU_BIT32 = {
    "and_b32": "({0} & {1})", "or_b32": "({0} | {1})", "xor_b32": "({0} ^ {1})",
    "andn2_b32": "({0} & ~{1})", "orn2_b32": "({0} | ~{1})",
    "lshl_b32": "({0} << ({1} & 31u))", "lshr_b32": "({0} >> ({1} & 31u))",
    "ashr_i32": "asuint(asint({0}) >> ({1} & 31u))",
    "nand_b32": "~({0} & {1})", "nor_b32": "~({0} | {1})", "xnor_b32": "~({0} ^ {1})",
}


def destination(st, dst):
    sgpr_name(dst)
    if dst in st.pending:
        raise ValueError("Write overlaps an outstanding scalar load")


@form(rf"s_({'|'.join(SALU_BIT32)}) (s\d+), ([^,\s]+), ([^,\s]+)")
def bitwise_32(st, i, m):
    op, dst, src0, src1 = m.groups()
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i} = {SALU_BIT32[op].format(a, b)};")
    st.scalar[dst] = ("uint", f"salu{i}")
    st.scc = f"(salu{i} != 0u)"


@form(r"s_lshl([1-4])_add_u32 (s\d+), ([^,\s]+), ([^,\s]+)")
def shift_add_32(st, i, m):
    n, dst, src0, src1 = m.groups()
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i}_s = {a} << {n}u;")
    st.lines.append(f"    uint salu{i} = salu{i}_s + {b};")
    st.scalar[dst] = ("uint", f"salu{i}")
    st.scc = f"((({a} >> {32 - int(n)}u) != 0u) || (salu{i} < salu{i}_s))"


@form(r"s_bfm_b32 (s\d+), ([^,\s]+), ([^,\s]+)")
def bitfield_mask_32(st, i, m):
    dst, src0, src1 = m.groups()
    width = scalar_u32(src0, st.scalar, st.pending)
    offset = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i} = ((1u << ({width} & 31u)) - 1u) << ({offset} & 31u);")
    st.scalar[dst] = ("uint", f"salu{i}")


@form(r"s_cselect_b32 (s\d+), ([^,\s]+), ([^,\s]+)")
def select_32(st, i, m):
    dst, src0, src1 = m.groups()
    if st.scc is None:
        raise ValueError("Select requires a tracked SCC")
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i} = {st.scc} ? {a} : {b};")
    st.scalar[dst] = ("uint", f"salu{i}")


# ---- The remaining 32-bit SOP1, SOP2 forms (AMD RDNA 2 ISA guide, SOP1/SOP2 pseudocode) -------------------------------
# SCC: s_not_b32, s_abs_i32, s_bcnt0/1, s_absdiff_i32 and the NAND/NOR/XNOR forms set SCC = (D != 0); s_add_i32 and
# s_sub_i32 set the signed overflow; s_addc_u32 and s_subb_u32 read SCC as carry/borrow in and write the carry/borrow
# out; s_min/max set SCC when S0 is the chosen operand (min: S0 < S1, max: S0 >= S1, signed or unsigned). s_brev, the
# find-first/last-bit forms (-1 when there is no such bit), s_sext, s_bitset, s_bitreplicate, s_mul_i32, s_mul_hi_*,
# s_pack_* and s_cmov leave SCC alone. Every value is an unsigned word. Forms that read or write EXEC (s_wqm,
# s_quadmask, the saveexec family) are left to the control-flow cards.
SALU_HELPERS.update({
    # Leading zeros of a 32-bit / 64-bit word, 0xffffffff when it is zero (s_flbit_i32_b32, _b64).
    "salu_clz32": "uint salu_clz32(uint v) {\n    return v == 0u ? 0xffffffffu : 31u - firstbithigh(v);\n}",
    "salu_clz64": (
        "uint salu_clz64(uint lo, uint hi) {\n"
        "    if (hi != 0u) return 31u - firstbithigh(hi);\n"
        "    if (lo != 0u) return 63u - firstbithigh(lo);\n"
        "    return 0xffffffffu;\n"
        "}"
    ),
    # Lowest set bit, 0xffffffff when there is none (s_ff1; s_ff0 passes the complement).
    "salu_ctz32": "uint salu_ctz32(uint v) {\n    return v == 0u ? 0xffffffffu : firstbitlow(v);\n}",
    "salu_ctz64": (
        "uint salu_ctz64(uint lo, uint hi) {\n"
        "    if (lo != 0u) return firstbitlow(lo);\n"
        "    if (hi != 0u) return 32u + firstbitlow(hi);\n"
        "    return 0xffffffffu;\n"
        "}"
    ),
    # Bit i of a 16-bit value to bits 2i and 2i+1 (s_bitreplicate_b64_b32 does this for each half of the source).
    "salu_replicate16": (
        "uint salu_replicate16(uint x) {\n"
        "    x = (x | (x << 8)) & 0x00ff00ffu;\n"
        "    x = (x | (x << 4)) & 0x0f0f0f0fu;\n"
        "    x = (x | (x << 2)) & 0x33333333u;\n"
        "    x = (x | (x << 1)) & 0x55555555u;\n"
        "    return x | (x << 1);\n"
        "}"
    ),
})

SOP1_32 = {
    "not_b32": ("{0}", "~{0}", True),
    "brev_b32": ("{0}", "reversebits({0})", False),
    "bcnt1_i32_b32": ("{0}", "countbits({0})", True),
    "bcnt0_i32_b32": ("{0}", "countbits(~{0})", True),
    "ff1_i32_b32": ("{0}", "salu_ctz32({0})", False),
    "ff0_i32_b32": ("{0}", "salu_ctz32(~{0})", False),
    "flbit_i32_b32": ("{0}", "salu_clz32({0})", False),
    # Leading bits equal to the sign: count the zeros of the word, or of its complement when it is negative.
    "flbit_i32": ("{0}", "salu_clz32((asint({0}) < 0) ? ~{0} : {0})", False),
    "sext_i32_i8": ("{0}", "asuint(asint({0} << 24u) >> 24)", False),
    "sext_i32_i16": ("{0}", "asuint(asint({0} << 16u) >> 16)", False),
    "abs_i32": ("{0}", "((asint({0}) < 0) ? (0u - {0}) : {0})", True),
}


@form(rf"s_({'|'.join(SOP1_32)}) (s\d+), ([^,\s]+)")
def unary_32(st, i, m):
    op, dst, src = m.groups()
    a = scalar_u32(src, st.scalar, st.pending)
    destination(st, dst)
    st.helpers.update(h for h in ("salu_clz32", "salu_ctz32") if h in SOP1_32[op][1])
    st.lines.append(f"    uint salu{i} = {SOP1_32[op][1].format(a)};")
    st.scalar[dst] = ("uint", f"salu{i}")
    if SOP1_32[op][2]:
        st.scc = f"(salu{i} != 0u)"


@form(r"s_(bcnt0_i32_b64|bcnt1_i32_b64|ff0_i32_b64|ff1_i32_b64|flbit_i32_b64|flbit_i32_i64) (s\d+), ([^,]+)")
def unary_64_to_32(st, i, m):
    # A 64-bit source, a 32-bit result. s_flbit_i32_b64 counts leading zeros; s_flbit_i32_i64 leading sign bits.
    name, dst, src = m.groups()
    name = name[:-4] if name.endswith("_b64") else name
    lo, hi = scalar_u64(src, st.scalar, st.pending)
    destination(st, dst)
    if name in ("bcnt1_i32", "bcnt0_i32"):
        word = lo if name == "bcnt1_i32" else f"~{lo}"
        word_hi = hi if name == "bcnt1_i32" else f"~{hi}"
        expr = f"(countbits({word}) + countbits({word_hi}))"
    elif name in ("ff1_i32", "ff0_i32"):
        st.helpers.add("salu_ctz64")
        expr = f"salu_ctz64({lo}, {hi})" if name == "ff1_i32" else f"salu_ctz64(~{lo}, ~{hi})"
    elif name == "flbit_i32":  # s_flbit_i32_b64
        st.helpers.add("salu_clz64")
        expr = f"salu_clz64({lo}, {hi})"
    else:  # s_flbit_i32_i64
        st.helpers.add("salu_clz64")
        expr = f"((asint({hi}) < 0) ? salu_clz64(~{lo}, ~{hi}) : salu_clz64({lo}, {hi}))"
    st.lines.append(f"    uint salu{i} = {expr};")
    st.scalar[dst] = ("uint", f"salu{i}")
    if name.startswith("bcnt"):
        st.scc = f"(salu{i} != 0u)"


@form(r"s_bitset(0|1)_b32 (s\d+), ([^,\s]+)")
def bitset_32(st, i, m):
    # D = D with bit S0[4:0] cleared or set; the destination is also the source.
    value, dst, src = m.groups()
    bit = scalar_u32(src, st.scalar, st.pending)
    if dst not in st.scalar:
        raise ValueError(f"Read of unset scalar register {dst}")
    old = scalar_u32(dst, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i} = {old} {'| ' if value == '1' else '& ~'}(1u << ({bit} & 31u));")
    st.scalar[dst] = ("uint", f"salu{i}")


@form(r"s_cmov_b32 (s\d+), ([^,\s]+)")
def cmov_32(st, i, m):
    dst, src = m.groups()
    if st.scc is None:
        raise ValueError("Conditional move requires a tracked SCC")
    a = scalar_u32(src, st.scalar, st.pending)
    old = scalar_u32(dst, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i} = {st.scc} ? {a} : {old};")
    st.scalar[dst] = ("uint", f"salu{i}")


@form(r"s_bitreplicate_b64_b32 (s\[\d+:\d+\]), ([^,\s]+)")
def bitreplicate(st, i, m):
    dst, src = m.groups()
    regs = sgpr_pair(dst)
    if st.pending.intersection(regs):
        raise ValueError("Write overlaps an outstanding scalar load")
    a = scalar_u32(src, st.scalar, st.pending)
    st.helpers.add("salu_replicate16")
    st.lines.append(f"    uint2 salu{i} = uint2(salu_replicate16({a} & 0xffffu), salu_replicate16({a} >> 16));")
    st.scalar[regs[0]], st.scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")


@form(r"s_(add|sub)_i32 (s\d+), ([^,\s]+), ([^,\s]+)")
def add_sub_i32(st, i, m):
    op, dst, src0, src1 = m.groups()
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i} = {a} {'+' if op == 'add' else '-'} {b};")
    if op == "add":  # operands of equal sign, result of the other sign
        st.scc = f"((({a} ^ salu{i}) & ({b} ^ salu{i}) & 0x80000000u) != 0u)"
    else:  # operands of different sign, result sign differs from S0
        st.scc = f"((({a} ^ {b}) & ({a} ^ salu{i}) & 0x80000000u) != 0u)"
    st.scalar[dst] = ("uint", f"salu{i}")


@form(r"s_(addc|subb)_u32 (s\d+), ([^,\s]+), ([^,\s]+)")
def carry_32(st, i, m):
    op, dst, src0, src1 = m.groups()
    if st.scc is None:
        raise ValueError("Add or subtract with carry requires a tracked SCC")
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    st.lines.append(f"    uint salu{i}_c = {st.scc} ? 1u : 0u;")
    if op == "addc":
        st.lines.append(f"    uint salu{i}_t = {a} + {b};")
        st.lines.append(f"    uint salu{i} = salu{i}_t + salu{i}_c;")
        st.scc = f"((salu{i}_t < {a}) || (salu{i} < salu{i}_t))"
    else:
        st.lines.append(f"    uint salu{i} = {a} - {b} - salu{i}_c;")
        st.scc = f"(({a} < {b}) || (({a} == {b}) && (salu{i}_c != 0u)))"
    st.scalar[dst] = ("uint", f"salu{i}")


@form(r"s_(min|max)_(i32|u32) (s\d+), ([^,\s]+), ([^,\s]+)")
def min_max_32(st, i, m):
    op, kind, dst, src0, src1 = m.groups()
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    x, y = (f"asint({a})", f"asint({b})") if kind == "i32" else (a, b)
    st.lines.append(f"    bool salu{i}_s0 = {x} {'<' if op == 'min' else '>='} {y};")
    st.lines.append(f"    uint salu{i} = salu{i}_s0 ? {a} : {b};")
    st.scalar[dst] = ("uint", f"salu{i}")
    st.scc = f"salu{i}_s0"


@form(r"s_(mul_i32|mul_hi_u32|mul_hi_i32|absdiff_i32|pack_ll_b32_b16|pack_lh_b32_b16|pack_hh_b32_b16) "
      r"(s\d+), ([^,\s]+), ([^,\s]+)")
def arithmetic_32(st, i, m):
    op, dst, src0, src1 = m.groups()
    a = scalar_u32(src0, st.scalar, st.pending)
    b = scalar_u32(src1, st.scalar, st.pending)
    destination(st, dst)
    scc = False
    if op == "mul_i32":
        expr = f"{a} * {b}"
    elif op == "mul_hi_u32":
        st.helpers.add("mul_hi_u32")
        expr = f"mul_hi_u32({a}, {b})"
    elif op == "mul_hi_i32":
        st.helpers.update(("mul_hi_u32", "mul_hi_i32"))
        expr = f"mul_hi_i32({a}, {b})"
    elif op == "absdiff_i32":
        # |S0 - S1| in 32-bit wraparound arithmetic, so 0x80000000 stays 0x80000000.
        st.lines.append(f"    uint salu{i}_d = {a} - {b};")
        expr, scc = f"((asint(salu{i}_d) < 0) ? (0u - salu{i}_d) : salu{i}_d)", True
    elif op == "pack_ll_b32_b16":
        expr = f"({a} & 0xffffu) | ({b} << 16)"
    elif op == "pack_lh_b32_b16":
        expr = f"({a} & 0xffffu) | ({b} & 0xffff0000u)"
    else:
        expr = f"({a} >> 16) | ({b} & 0xffff0000u)"
    st.lines.append(f"    uint salu{i} = {expr};")
    st.scalar[dst] = ("uint", f"salu{i}")
    if scc:
        st.scc = f"(salu{i} != 0u)"
