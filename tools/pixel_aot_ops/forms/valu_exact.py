"""Forms whose exact semantics had to be pinned down before they could be lowered bit for bit: v_ldexp_f32, the
binary16 fused multiply-adds (v_fma_f16, v_fmac_f16, v_fmaak_f16, v_fmamk_f16) and the 32 x 32 + 64 integer
multiply-adds (v_mad_u64_u32, v_mad_i64_i32). Every value is a ("uint", expr) word and every helper is integer
arithmetic on bit patterns; nothing here depends on how the adapter rounds, fuses or flushes.

Sources read for each form: AMD "RDNA 2" Instruction Set Architecture Reference Guide (document 70648, 2020-11-30),
chapter 12 (VOP2, VOP3a/VOP3b opcode tables); LLVM 15 (llvmorg-15.0.7) llvm/lib/Target/AMDGPU (VOP2Instructions.td,
VOP3Instructions.td, AMDGPUInstCombineIntrinsic.cpp, SIISelLowering.cpp, GCNSubtarget.h) and llvm/lib/Analysis/
ConstantFolding.cpp; Mesa ACO (src/amd/compiler/aco_instruction_selection.cpp) and NIR (nir_opcodes.py constant
expressions). Where a statement below comes from one of these, it is named.

v_ldexp_f32 (VOP3 only on gfx10; llvm-mc refuses _e32). ISA: D.f = S0.f * 2.0^S1.i, S1 a signed 32-bit integer.
LLVM folds llvm.amdgcn.ldexp (and the generic llvm.ldexp it selects to v_ldexp_f32) with APFloat scalbn under
round-to-nearest-even and returns a NaN source quieted; NIR's ldexp constant expression is C ldexpf, which is
scalbnf (exact scaling, one rounding to nearest even, gradual underflow, overflow to infinity). The lowering
(ldexp_f32_bits) does exactly that on the bit pattern: the significand of a normal or subnormal source is normalised to
24 bits, the exponent field moved by S1 (clamped to +-512 first, which changes no result: any |S1| > 330 saturates),
and a result below the normal range is shifted right with one round-to-nearest-even on the shifted-out bits, so a
subnormal result, a carry into the smallest normal and a total underflow to a signed zero are each rounded once.
Binary32 denormal sources and results are kept, not flushed, as in the v_fma_f32 branch of valu_f32.py. Infinity and
signed zero are returned unchanged for every exponent; a NaN source is returned with bit 22 set (sign and payload
kept), the quieting LLVM folds; the draws use quiet NaNs only, whose quieting is the identity. abs and neg act on bit 31
of S0. S1 takes no modifiers (llvm-mc refuses them) and a float constant there is refused. clamp and the output
modifiers are refused: their effect on an ldexp result is not modelled here.

v_fma_f16, v_fmac_f16 (e32 and e64), v_fmaak_f16 (D = S0 * S1 + K), v_fmamk_f16 (D = S0 * K + S1). ISA: fused
multiply-add of binary16 values, one rounding. The lowering is vop3p.fma_mix_round(fm_f16_word(a), fm_f16_word(b),
fm_f16_word(c), false), the exactly-once-rounded integer FMA already used by v_pk_fma_f16: each binary16 source is
widened exactly, the 22-bit product is exact in two words, the addend is aligned with a sticky bit, and the sum is
rounded once to nearest even at the binary16 quantum (2^-24 for subnormal results), overflowing to infinity. Rounding
through binary32 (fpround(fma) in f32, or narrow16(mad(...))) is not this: a = 0x31e9, b = 0xb56a, c = 0x5a91 gives
0x5a91 (210.125) correctly and 0x5a90 after a binary32 rounding lands on a binary16 tie; the draws use it.
  The binary64 route also works, and this is the argument (checked numerically in the draws' controls): every finite
binary16 value is a multiple of 2^-24 with at most 11 significant bits, so p = a*b is a multiple of 2^-48 with at most
22 significant bits and |p| < 2^32, exact in binary64. Let S = p + c. If round64(S) != S, S spans more than 53 bits
from its top bit T to its lowest set bit. (i) If that lowest bit comes from p, below every bit of c, then p's 22 bits
end 53 places under T, so |p| < 2^(T-31); c then lies in S's binade (or is the power of two just above it), is a
multiple of half the binary16 quantum q there, and |S - c| < q/2, so both S and round64(S) (|round64(S) - c| <
2^(T-30)) round to c. (ii) Otherwise the lowest bit is a bit of c, at or above 2^-24, so T >= 29 and S, and
round64(S), overflow binary16 to the same infinity. So round16(round64(a*b + c)) is the correctly rounded binary16 fma
for every input; the integer lowering is used because doubles are an optional D3D12 capability (valu_f64.py).
  Results replace the low half of the destination and keep the high half (GCNSubtarget::zeroesHigh16BitsOfDest is
false on gfx10), as in valu_f16.py; v_fma_f16 op_sel[3] writes the high half and keeps the low one, and op_sel[0..2]
read the high half of a register source (a constant or literal under op_sel is refused). v_fmac_f16 reads its addend
from the low half of the destination. clamp (e64) is vop3p.fma_mix_sat: NaN and negative values give +0, values above
1.0 give 1.0 (the draws never clamp a -0). NaN sources give the first NaN of a, b, c quieted (top ten payload bits
kept), as fma_mix_round does; the draws use no NaN. Binary16 denormals are kept (the f16/f64 denormal mode is on in
LLVM's default for graphics), as everywhere in valu_f16.py. Output modifiers are refused (llvm-mc refuses them for
v_fma_f16 on gfx10).

v_mad_u64_u32 and v_mad_i64_i32 (VOP3b). ISA: {vcc_out, D.u64} = S0.u32 * S1.u32 + S2.u64 and
{vcc_out, D.i64} = S0.i32 * S1.i32 + S2.i64. D is the low 64 bits of the exact result for both, computed from four
16 x 16 partial products (the signed product is the unsigned one minus S1 << 32 when S0 is negative and S0 << 32 when
S1 is negative, mod 2^64). For the unsigned form the 65-bit concatenation makes vcc_out bit 64 of the exact sum, the
carry out of the 64-bit add (the product is at most (2^32 - 1)^2, so the sum is below 2^65); it is written per lane
to the lane mask like the carry of v_add_co_u32. For the signed form the text does not say whether vcc_out is bit 64
of the 65-bit two's-complement sum (its sign) or a signed overflow flag, LLVM never reads it (the SDST of its
v_mad_i64_i32 selections is dead) and ACO uses only v_mad_u64_u32, so the SDST of v_mad_i64_i32 is left unset: any
later read of it is refused. clamp, source modifiers (llvm-mc refuses them), float constants and a literal for the
64-bit S2 (whether it is zero- or sign-extended is not established) are refused; an integer inline constant for S2 is
its 64-bit sign extension.

Kept refused (no form here), and why:
- v_cvt_norm_i16_f16, v_cvt_norm_u16_f16, v_cvt_pknorm_{i16,u16}_{f32,f16}: the ISA gives only flt16_to_snorm /
  (snorm)S0.f, LLVM has no constant folding for llvm.amdgcn.cvt.pknorm.* and no generic op that selects the
  v_cvt_norm forms, and ACO uses v_cvt_pknorm only for SNORM16/UNORM16 colour export, where D3D11 (a 0.6 ULP
  tolerance on float-to-UNORM/SNORM) and Vulkan allow either answer. The clamp (to [-1, 1] or [0, 1]; NaN to 0) is
  agreed by every source, and the only exact tie, x = +-0.5, rounds the same to even or away, but whether x * 32767
  (or 65535) is rounded to binary32 before the conversion to an integer is not stated: for binary16 sources the exact
  product and the binary32 product round differently for 4 of the 65536 encodings per form (x = 1025/2048 gives
  16399 exactly and 16400 through binary32), and for binary32 sources for many more.
- v_cvt_pk_u8_f32: the ISA's flt32_to_uint8 states no rounding (nearest even, the MODE round mode or truncation) and no
  NaN or out-of-range rule; LLVM has no fold for llvm.amdgcn.cvt.pk.u8.f32 and neither ACO nor NIR emits it.
- v_mad_f16 does not exist on gfx1013 (llvm-mc: instruction not supported on this GPU)."""
import re

from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import F16_CONSTANT, lane_mask, registers, sgpr_pair, tracked_word, vector_u32, word_of
from .valu_f64 import f32_word_operand
from .vop3p import need_fma_mix

SALU_HELPERS.update({
    "ldexp_f32_bits": (
        "uint ldexp_f32_bits(uint x, int e) {\n"
        "    uint sign = x & 0x80000000u;\n"
        "    uint ex = (x >> 23u) & 0xffu;\n"
        "    uint m = x & 0x7fffffu;\n"
        "    if (ex == 0xffu) return m != 0u ? (x | 0x400000u) : x;\n"
        "    if (ex == 0u && m == 0u) return x;\n"
        "    uint sig;\n"
        "    int field;\n"
        "    if (ex == 0u) {\n"
        "        uint top = firstbithigh(m);\n"
        "        sig = m << (23u - top);\n"
        "        field = int(top) - 22;\n"
        "    } else {\n"
        "        sig = m | 0x800000u;\n"
        "        field = int(ex);\n"
        "    }\n"
        "    field += clamp(e, -512, 512);\n"
        "    if (field >= 255) return sign | 0x7f800000u;\n"
        "    if (field >= 1) return sign | (uint(field) << 23u) | (sig & 0x7fffffu);\n"
        "    uint shift = uint(1 - field);\n"
        "    if (shift > 24u) return sign;\n"
        "    uint q = sig >> shift;\n"
        "    uint rem = sig & ((1u << shift) - 1u);\n"
        "    uint mid = 1u << (shift - 1u);\n"
        "    if (rem > mid || (rem == mid && (q & 1u) != 0u)) q += 1u;\n"
        "    return sign | q;\n"
        "}"
    ),
    "mul_u32_wide": (
        "uint2 mul_u32_wide(uint a, uint b) {\n"
        "    uint a0 = a & 0xffffu, a1 = a >> 16u, b0 = b & 0xffffu, b1 = b >> 16u;\n"
        "    uint p00 = a0 * b0, p01 = a0 * b1, p10 = a1 * b0, p11 = a1 * b1;\n"
        "    uint mid = (p00 >> 16u) + (p01 & 0xffffu) + (p10 & 0xffffu);\n"
        "    return uint2((p00 & 0xffffu) | (mid << 16u), p11 + (p01 >> 16u) + (p10 >> 16u) + (mid >> 16u));\n"
        "}"
    ),
    # x, y: the low 64 bits of a * b + c; z: the carry out of the 64-bit add (meaningful for the unsigned form).
    "mad_64_32": (
        "uint3 mad_64_32(uint a, uint b, uint2 c, bool signed_product) {\n"
        "    uint2 p = mul_u32_wide(a, b);\n"
        "    if (signed_product) {\n"
        "        p.y -= (asint(a) < 0 ? b : 0u) + (asint(b) < 0 ? a : 0u);\n"
        "    }\n"
        "    uint lo = p.x + c.x;\n"
        "    uint carry_lo = lo < p.x ? 1u : 0u;\n"
        "    uint hi = p.y + c.y;\n"
        "    uint carry = hi < p.y ? 1u : 0u;\n"
        "    uint hi2 = hi + carry_lo;\n"
        "    carry |= hi2 < hi ? 1u : 0u;\n"
        "    return uint3(lo, hi2, carry);\n"
        "}"
    ),
})
NEEDS = {"mad_64_32": ("mul_u32_wide",)}


def need(st, name):
    st.helpers.add(name)
    for other in NEEDS.get(name, ()):
        need(st, other)


def raw_destination(st, dst):
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")


# ---------------------------------------------------------------------------------------------------------- ldexp
@form(r"v_ldexp_f32(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+)(.*)")
def ldexp_f32(st, i, m):
    dst, src, exponent, rest = m.groups()
    if rest:
        raise ValueError(f"Unsupported v_ldexp_f32 modifier {rest.strip()}: clamp and output modifiers are not modelled")
    raw_destination(st, dst)
    if not re.fullmatch(r"[vs]\d+|-?\d+|0x[0-9a-f]{1,8}", exponent):
        raise ValueError(f"Unsupported v_ldexp_f32 exponent operand {exponent}")
    if re.fullmatch(r"-?\d+", exponent) and not -16 <= int(exponent) <= 64:
        raise ValueError(f"Integer inline constant out of range: {exponent}")
    word = f32_word_operand(src, st)
    e = vector_u32(exponent, st.scalar, st.vector, st.pending, st.sample_pending)
    need(st, "ldexp_f32_bits")
    st.lines.append(f"    uint xw{i} = ldexp_f32_bits({word}, asint({e}));")
    st.vector[dst] = ("uint", f"xw{i}")


# ------------------------------------------------------------------------------------------------- binary16 fma
def f16_source(token, high, st):
    """The binary16 encoding (unsigned expression) of a source after its modifiers; high reads a register's high half."""
    negate = token.startswith("-") and token not in F16_CONSTANT and not re.fullmatch(r"-\d+", token)
    body = token[1:] if negate else token
    absolute = re.fullmatch(r"\|([^|]+)\|", body)
    if absolute:
        body = absolute.group(1)
    if body in F16_CONSTANT:
        if high:
            raise ValueError(f"op_sel on a constant source is not established: {token}")
        bits = f"{F16_CONSTANT[body]:#x}u"
    elif re.fullmatch(r"-?\d+", body):
        if high or negate or absolute or not -16 <= int(body) <= 64:
            raise ValueError(f"Unsupported 16-bit operand {token}")
        bits = f"{int(body) & 0xffff:#x}u"
    elif re.fullmatch(r"0x[0-9a-f]{1,4}", body):
        if high:
            raise ValueError(f"op_sel on a literal source is not established: {token}")
        bits = f"{int(body, 16):#x}u"
    elif re.fullmatch(r"[vs]\d+", body):
        word = word_of(body, st.scalar, st.vector, st.pending, st.sample_pending)
        bits = f"(({word} >> 16u) & 0xffffu)" if high else f"({word} & 0xffffu)"
    else:
        raise ValueError(f"Unsupported 16-bit operand {token}")
    if absolute:
        bits = f"({bits} & 0x7fffu)"
    if negate:
        bits = f"({bits} ^ 0x8000u)"
    return bits


def f16_fma_write(st, i, dst, a, b, c, clamp, high_dst=False):
    old = st.vector.get(dst)
    if old is not None and tracked_word(old) is None:
        raise ValueError("Unsupported arithmetic destination")
    need_fma_mix(st)
    value = f"fma_mix_round(fm_f16_word({a}), fm_f16_word({b}), fm_f16_word({c}), false)"
    if clamp:
        value = f"fma_mix_sat({value}, false)"
    st.lines.append(f"    uint xh{i} = {value};")
    if high_dst:
        keep = f"({tracked_word(old)} & 0xffffu)" if old is not None else "0u"
        st.lines.append(f"    uint xw{i} = {keep} | (xh{i} << 16u);")
    else:
        keep = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
        st.lines.append(f"    uint xw{i} = {keep} | xh{i};")
    st.vector[dst] = ("uint", f"xw{i}")


@form(r"v_fma_f16(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)(?: op_sel:\[([01]),([01]),([01]),([01])\])?( clamp)?")
def fma_f16(st, i, m):
    dst, *tokens = m.groups()[:4]
    selects = [s == "1" for s in m.groups()[4:8]]
    clamp = m.group(9)
    raw_destination(st, dst)
    a, b, c = (f16_source(t, s, st) for t, s in zip(tokens, selects))
    f16_fma_write(st, i, dst, a, b, c, clamp, high_dst=selects[3])


@form(r"v_fmac_f16_(e32|e64) (v\d+), ([^,\s]+), ([^,\s]+)( clamp)?")
def fmac_f16(st, i, m):
    encoding, dst, first, second, clamp = m.groups()
    if encoding == "e32" and (clamp or not re.fullmatch(r"v\d+", second) or "|" in first
                              or (first.startswith("-") and first not in F16_CONSTANT and not re.fullmatch(r"-\d+", first))):
        raise ValueError("Invalid v_fmac_f16_e32 operands")
    raw_destination(st, dst)
    if st.vector.get(dst) is None:
        raise ValueError(f"Read of unset vector register {dst}")
    a, b = (f16_source(t, False, st) for t in (first, second))
    c = f16_source(dst, False, st)
    f16_fma_write(st, i, dst, a, b, c, clamp)


@form(r"v_(fmaak|fmamk)_f16 (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)")
def fmak_f16(st, i, m):
    op, dst, *tokens = m.groups()
    literal = tokens[2] if op == "fmaak" else tokens[1]
    vgpr = tokens[1] if op == "fmaak" else tokens[2]
    if not re.fullmatch(r"0x[0-9a-f]{1,4}", literal) or not re.fullmatch(r"v\d+", vgpr):
        raise ValueError(f"Invalid v_{op}_f16 operands")
    if tokens[0].startswith(("-", "|")) and not (tokens[0] in F16_CONSTANT or re.fullmatch(r"-\d+", tokens[0])):
        raise ValueError(f"v_{op}_f16 takes no source modifiers")
    raw_destination(st, dst)
    # fmaak is S0 * S1 + K and fmamk S0 * K + S1: both are first * second + third in the printed order.
    a, b, c = (f16_source(t, False, st) for t in tokens)
    f16_fma_write(st, i, dst, a, b, c, None)


# -------------------------------------------------------------------------------------------- 64-bit integer mad
def u64_source(token, st):
    """S2 of v_mad_{u64_u32,i64_i32} as a uint2 expression: a VGPR or SGPR pair, or an integer inline constant
    (its 64-bit sign extension)."""
    if pair := re.fullmatch(r"v\[(\d+):(\d+)\]", token):
        names = [f"v{n}" for n in registers(pair[1], pair[2], 2)]
    elif token.startswith("s["):
        names = sgpr_pair(token)
    elif re.fullmatch(r"-?\d+", token) and -16 <= int(token) <= 64:
        bits = int(token) & 0xffffffffffffffff
        return f"uint2({bits & 0xffffffff:#x}u, {bits >> 32:#x}u)"
    else:
        raise ValueError(f"Unsupported 64-bit integer operand {token}")
    lo, hi = (vector_u32(n, st.scalar, st.vector, st.pending, st.sample_pending) for n in names)
    return f"uint2({lo}, {hi})"


def u32_source(token, st):
    if not re.fullmatch(r"[vs]\d+|-?\d+|0x[0-9a-f]{1,8}", token):
        raise ValueError(f"Unsupported integer operand {token}")
    if re.fullmatch(r"-?\d+", token) and not -16 <= int(token) <= 64:
        raise ValueError(f"Integer inline constant out of range: {token}")
    return vector_u32(token, st.scalar, st.vector, st.pending, st.sample_pending)


@form(r"v_mad_(u64_u32|i64_i32)(?:_e64)? (v\[\d+:\d+\]), (vcc(?:_lo)?|s\d+|s\[\d+:\d+\]|null), ([^,\s]+), ([^,\s]+), "
      r"([^,\s]+)(.*)")
def mad_64_32(st, i, m):
    kind, dst, carry, first, second, addend, rest = m.groups()
    if rest:
        raise ValueError(f"Unsupported v_mad_{kind} modifier {rest.strip()}")
    regs = [] if carry == "null" else lane_mask(carry)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid integer operation")
    pair = re.fullmatch(r"v\[(\d+):(\d+)\]", dst)
    names = [f"v{n}" for n in registers(pair[1], pair[2], 2)]
    if st.sample_dest.keys() & set(names):
        raise ValueError("Write overlaps an outstanding sample")
    a, b = (u32_source(t, st) for t in (first, second))
    c = u64_source(addend, st)
    need(st, "mad_64_32")
    st.lines.append(f"    uint3 xm{i} = mad_64_32({a}, {b}, {c}, {'true' if kind == 'i64_i32' else 'false'});")
    st.lines.append(f"    uint xw{i}_lo = xm{i}.x;")
    st.lines.append(f"    uint xw{i}_hi = xm{i}.y;")
    if kind == "u64_u32":
        st.lines.append(f"    bool cmp{i} = xm{i}.z != 0u;")
        for j, reg in enumerate(regs):
            st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    else:
        for reg in regs:  # vcc_out of the signed form is not established (module docstring): reading it is refused
            st.scalar.pop(reg, None)
    st.vector[names[0]], st.vector[names[1]] = ("uint", f"xw{i}_lo"), ("uint", f"xw{i}_hi")
