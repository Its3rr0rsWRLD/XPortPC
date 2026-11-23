"""Integer vector forms (VOP1, VOP2, VOP3): bitwise, shifts, add/sub/mul, three-input forms, min/max/min3/max3/med3, add and
subtract with carry out, v_cvt_f32_ubyte and the conversions between binary32 and 32-bit integers."""
import re

from ..dispatch import form
from ..registers import inactive
from ..registers import LANE_MASK, fp_operand, lane_mask, vector_u32

# Integer add, subtract, multiply and three-input forms. Semantics: AMD RDNA 2 ISA guide (instruction pseudocode in
# the VOP2/VOP3 sections): V_ADD_NC_U32 D=S0+S1, V_SUB_NC_U32 D=S0-S1, V_SUBREV_NC_U32 D=S1-S0, V_MUL_U32_U24
# D=S0.u[23:0]*S1.u[23:0], V_MUL_I32_I24 D=S0.i[23:0]*S1.i[23:0], V_MUL_HI_U32_U24 D=(S0.u24*S1.u24)>>32,
# V_MUL_HI_I32_I24 D=(S0.i24*S1.i24)>>32, V_MUL_HI_U32/V_MUL_HI_I32 D=(S0*S1)>>32, V_MUL_LO_U32 D=(S0*S1)[31:0],
# V_MAD_U32_U24 D=S0.u[23:0]*S1.u[23:0]+S2, V_MAD_I32_I24 D=S0.i[23:0]*S1.i[23:0]+S2, V_MAD_U32_U16 and V_MAD_I32_I16
# D=S0.[15:0]*S1.[15:0]+S2 (unsigned, signed), V_ADD3_U32 D=S0+S1+S2,
# V_LSHL_ADD_U32 D=(S0<<S1[4:0])+S2, V_ADD_LSHL_U32 D=(S0+S1)<<S2[4:0], V_LSHL_OR_B32 D=(S0<<S1[4:0])|S2,
# V_AND_OR_B32 D=(S0&S1)|S2, V_OR3_B32 D=S0|S1|S2, V_XOR3_B32 D=S0^S1^S2, V_XAD_U32 D=(S0^S1)+S2,
# V_ADD_NC_I32 D=S0+S1, V_SUB_NC_I32 D=S0-S1. Shift counts are the bit slice [4:0], so they are masked to five bits.
# Results wrap. The VOP3 clamp bit saturates the add and subtract forms (LLVM VOP3Instructions.td maps saddsat and
# ssubsat to V_ADD_I32_e64/V_SUB_I32_e64 with clamp); it is accepted only there, never on the multiplies, which
# llvm-mc assembles with clamp but whose saturation point is not established here.
INT_VOP2 = ("add_nc_u32", "sub_nc_u32", "subrev_nc_u32", "mul_u32_u24", "mul_i32_i24", "mul_hi_u32_u24", "mul_hi_i32_i24")
INT_VOP3 = ("add_nc_i32", "sub_nc_i32", "mul_lo_u32", "mul_hi_u32", "mul_hi_i32")
INT_CLAMPED = ("add_nc_u32", "sub_nc_u32", "subrev_nc_u32", "add_nc_i32", "sub_nc_i32")
INT_TERNARY = ("mad_u32_u24", "mad_i32_i24", "mad_u32_u16", "mad_i32_i16", "add3_u32", "lshl_add_u32", "add_lshl_u32", "lshl_or_b32", "and_or_b32",
               "or3_b32", "xor3_b32", "xad_u32")


def sext24(word):
    return f"asuint(asint({word} << 8u) >> 8)"


def sext16(word):
    return f"asuint(asint({word} << 16u) >> 16)"


def int_binary(op, a, b, clamp, helpers):
    """HLSL uint expression for a two-source integer form; a and b are the first and second source words."""
    if clamp:
        name = {"add_nc_u32": "v_add_sat_u32", "sub_nc_u32": "v_sub_sat_u32", "subrev_nc_u32": "v_sub_sat_u32",
                "add_nc_i32": "v_add_sat_i32", "sub_nc_i32": "v_sub_sat_i32"}[op]
        helpers.add(name)
        return f"{name}({b}, {a})" if op == "subrev_nc_u32" else f"{name}({a}, {b})"
    if op.startswith("mul_hi"):
        helpers.update(("mul_hi_u32", "mul_hi_i32") if op.endswith("i32") or op.endswith("i24") else ("mul_hi_u32",))
    return {
        "add_nc_u32": f"({a} + {b})", "add_nc_i32": f"({a} + {b})",
        "sub_nc_u32": f"({a} - {b})", "sub_nc_i32": f"({a} - {b})", "subrev_nc_u32": f"({b} - {a})",
        "mul_u32_u24": f"(({a} & 0xffffffu) * ({b} & 0xffffffu))",
        "mul_i32_i24": f"({sext24(a)} * {sext24(b)})",
        "mul_hi_u32_u24": f"mul_hi_u32({a} & 0xffffffu, {b} & 0xffffffu)",
        "mul_hi_i32_i24": f"mul_hi_i32({sext24(a)}, {sext24(b)})",
        "mul_lo_u32": f"({a} * {b})", "mul_hi_u32": f"mul_hi_u32({a}, {b})", "mul_hi_i32": f"mul_hi_i32({a}, {b})",
    }[op]


def int_ternary(op, a, b, c):
    return {
        "mad_u32_u24": f"((({a} & 0xffffffu) * ({b} & 0xffffffu)) + {c})",
        "mad_i32_i24": f"(({sext24(a)} * {sext24(b)}) + {c})",
        # The 16-bit forms read bits [15:0] of the first two sources (ported from R0Y00/Xbox2Windows#532 by Vonsek).
        "mad_u32_u16": f"((({a} & 0xffffu) * ({b} & 0xffffu)) + {c})",
        "mad_i32_i16": f"(({sext16(a)} * {sext16(b)}) + {c})",
        "add3_u32": f"({a} + {b} + {c})",
        "lshl_add_u32": f"(({a} << ({b} & 31u)) + {c})",
        "add_lshl_u32": f"(({a} + {b}) << ({c} & 31u))",
        "lshl_or_b32": f"(({a} << ({b} & 31u)) | {c})",
        "and_or_b32": f"(({a} & {b}) | {c})",
        "or3_b32": f"({a} | {b} | {c})",
        "xor3_b32": f"({a} ^ {b} ^ {c})",
        "xad_u32": f"(({a} ^ {b}) + {c})",
    }[op]


@form(r"v_cvt_f32_ubyte([0-3])(_e32|_e64)? (v\d+), ([^,\s]+)( clamp)?")
def convert_ubyte(st, i, m):
    # D.f32 = float((S0 >> 8N) & 0xff); clamp exists only in the e64 encoding.
    byte, suffix, dst, src, clamp = m.groups()
    if clamp and suffix != "_e64":
        raise ValueError("Invalid conversion")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)
    expression = f"float(({word} >> {8 * int(byte)}u) & 255u)"
    if clamp:
        expression = f"saturate({expression})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")


@form(r"v_(and|or|xor|xnor|lshlrev|lshrrev|ashrrev)_(?:b32|i32)(?:_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)")
def bitwise(st, i, m):
    # Bitwise operations and shifts. The shift forms take the count in the first source and mask it to
    # five bits; the arithmetic shift replicates the sign of the second source.
    op, dst, first, second = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a = vector_u32(first, st.scalar, st.vector, st.pending, st.sample_pending)
    b = vector_u32(second, st.scalar, st.vector, st.pending, st.sample_pending)
    expression = {
        "and": f"({a} & {b})", "or": f"({a} | {b})", "xor": f"({a} ^ {b})", "xnor": f"(~({a} ^ {b}))",
        "lshlrev": f"({b} << ({a} & 31u))", "lshrrev": f"({b} >> ({a} & 31u))",
        "ashrrev": f"asuint(asint({b}) >> ({a} & 31u))",
    }[op]
    st.lines.append(f"    uint valu{i} = {expression};")
    st.vector[dst] = ("uint", f"valu{i}")


@form(r"v_(not|bfrev)_b32(?:_e32|_e64)? (v\d+), ([^,\s]+)")
def not_bfrev(st, i, m):
    op, dst, src = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)
    st.lines.append(f"    uint valu{i} = {'~' if op == 'not' else 'reversebits'}({word});")
    st.vector[dst] = ("uint", f"valu{i}")


@form(r"v_(" + "|".join(INT_VOP2 + INT_VOP3) + r")(_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)( clamp)?")
def binary(st, i, m):
    op, suffix, dst, first, second, clamp = m.groups()
    if (op in INT_VOP3 and suffix == "_e32") or (clamp and (suffix == "_e32" or op not in INT_CLAMPED)):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a = vector_u32(first, st.scalar, st.vector, st.pending, st.sample_pending)
    b = vector_u32(second, st.scalar, st.vector, st.pending, st.sample_pending)
    st.lines.append(f"    uint valu{i} = {int_binary(op, a, b, bool(clamp), st.helpers)};")
    st.vector[dst] = ("uint", f"valu{i}")


@form(r"v_(" + "|".join(INT_TERNARY) + r")(_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)")
def ternary(st, i, m):
    op, _, dst, first, second, third = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b, c = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (first, second, third))
    st.lines.append(f"    uint valu{i} = {int_ternary(op, a, b, c)};")
    st.vector[dst] = ("uint", f"valu{i}")


# Conversions between binary32 and 32-bit integers. Semantics: AMD RDNA 2 ISA guide, VOP1 (V_CVT_F32_I32,
# V_CVT_F32_U32, V_CVT_I32_F32, V_CVT_U32_F32), and LLVM, which selects V_CVT_I32_F32/V_CVT_U32_F32 for
# llvm.fptosi.sat/llvm.fptoui.sat (SIISelLowering: FP_TO_SINT_SAT/FP_TO_UINT_SAT legal for i32):
# - integer to float rounds to nearest, ties to even. The lowering does not rely on the D3D integer-to-float
#   conversion for that: it converts the high and low 16 bits separately, which is exact, and lets the one binary32
#   add round the exact sum, which D3D requires to be correctly rounded.
# - float to integer rounds toward zero, saturates at the limits of the result type (+-2^31 or 0 and 2^32 - 1, with
#   the infinities) and gives 0 for a NaN; -0.0 and every denormal give 0. HLSL leaves an out-of-range or NaN
#   conversion undefined, so the NaN and range tests are made on the bits, in uint, and the value HLSL converts is
#   clamped on the bits first (every lane evaluates both sides of the select), so no undefined cast is ever made.
# Only the e64 form of an integer-to-float conversion has clamp and omod. omod scales the result by 2, 4 or 1/2, then
# clamp saturates it to [0, 1] (the VOP3 output modifiers, in that order). The scaling is exact here: the result is an
# integer value below 2^34 in magnitude, so it neither overflows nor reaches the denormals. The hardware ignores omod
# when the IEEE mode bit is set (LLVM SIFoldOperands::tryFoldOMod); graphics shaders run with it clear (LLVM
# SIModeRegisterDefaults: IEEE only for compute), and a compiler emits omod only where it is honoured.
# Float-to-integer conversions take neg and abs on the source in the e64 form. llvm-mc also assembles clamp and omod
# there; what they do to an integer result is not established here, so they are refused.
OMOD = {" mul:2": "2.0f", " mul:4": "4.0f", " div:2": "0.5f"}


@form(r"v_cvt_f32_(i32|u32)(_e32|_e64)? (v\d+), ([^,\s]+)( clamp)?( mul:2| mul:4| div:2)?")
def convert_to_float(st, i, m):
    kind, suffix, dst, src, clamp, omod = m.groups()
    if inactive(st) or ((clamp or omod) and suffix != "_e64"):
        raise ValueError("Invalid conversion")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)
    st.lines.append(f"    uint cvtw{i} = {word};")
    high = f"asint(cvtw{i}) >> 16" if kind == "i32" else f"cvtw{i} >> 16u"
    expression = f"float({high}) * 65536.0f + float(cvtw{i} & 0xffffu)"
    if omod:
        expression = f"({expression}) * {OMOD[omod]}"
    if clamp:
        expression = f"saturate({expression})"
    if omod != " div:2":  # an integer, also scaled by 2 or 4 or clamped (Lowering.integral)
        st.integral.add(f"alu{i}")
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")


def source_modified(token):
    return bool(re.fullmatch(r"-?(?:\|.*\||abs\(.*\))|-[vs]\d+", token))


@form(r"v_cvt_(i32|u32)_f32(_e32|_e64)? (v\d+), ([^,\s]+)")
def convert_to_int(st, i, m):
    kind, suffix, dst, src = m.groups()
    if inactive(st) or (source_modified(src) and suffix != "_e64"):
        raise ValueError("Invalid conversion")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    value = fp_operand(src, st.scalar, st.vector, st.pending, st.sample_pending)
    st.lines.append(f"    uint cvtb{i} = asuint({value});")
    if kind == "i32":
        # NaN: magnitude above infinity. |x| >= 2^31 (0x4f000000), the infinities included: the limit of the sign.
        st.lines.append(f"    uint cvtm{i} = cvtb{i} & 0x7fffffffu;")
        # The cast reads the word with its magnitude clamped to 0x4effffff (2^31 - 128), so it is always in range.
        st.lines.append(f"    float cvti{i} = asfloat(min(cvtm{i}, 0x4effffffu) | (cvtb{i} & 0x80000000u));")
        expression = (f"cvtm{i} > 0x7f800000u ? 0u : cvtm{i} >= 0x4f000000u ? 0x7fffffffu + (cvtb{i} >> 31u)"
                      f" : asuint(int(cvti{i}))")
    else:
        # Every word from 0x7f800001 up is a positive NaN or has the sign set (negative, -0.0, negative NaN): 0.
        # Positive x >= 2^32 (0x4f800000), +inf included: 2^32 - 1.
        # The cast reads 0 in place of any word from 0x4f800000 up, so it is always of a value in [0, 2^32).
        st.lines.append(f"    float cvti{i} = asfloat(cvtb{i} < 0x4f800000u ? cvtb{i} : 0u);")
        expression = (f"cvtb{i} > 0x7f800000u ? 0u : cvtb{i} >= 0x4f800000u ? 0xffffffffu"
                      f" : uint(cvti{i})")
    st.lines.append(f"    uint valu{i} = {expression};")
    st.vector[dst] = ("uint", f"valu{i}")


# V_MAX_I32, V_MIN_I32, V_MAX_U32, V_MIN_U32 (VOP2) and V_MED3_I32, V_MED3_U32 (VOP3): signed or unsigned order of
# the words. The result is one of the source words, copied. llvm-mc refuses clamp and source modifiers on all of them.
def ordered(kind, words):
    return [f"asint({w})" for w in words] if kind == "i32" else list(words)


@form(r"v_(max|min)_(i32|u32)(_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)")
def min_max(st, i, m):
    op, kind, _, dst, first, second = m.groups()
    if inactive(st):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b = ordered(kind, (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (first, second)))
    expression = f"{op}({a}, {b})"
    st.lines.append(f"    uint valu{i} = {f'asuint({expression})' if kind == 'i32' else expression};")
    st.vector[dst] = ("uint", f"valu{i}")


@form(r"v_med3_(i32|u32)(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)")
def median(st, i, m):
    kind, dst, *tokens = m.groups()
    if inactive(st):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    words = [vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    cast = "int" if kind == "i32" else "uint"
    for name, word in zip("abc", words):
        st.lines.append(f"    {cast} med{name}{i} = {f'asint({word})' if kind == 'i32' else word};")
    expression = f"max(min(meda{i}, medb{i}), min(max(meda{i}, medb{i}), medc{i}))"
    st.lines.append(f"    uint valu{i} = {f'asuint({expression})' if kind == 'i32' else expression};")
    st.vector[dst] = ("uint", f"valu{i}")


# V_MIN3_I32, V_MAX3_I32, V_MIN3_U32 and V_MAX3_U32 (VOP3 only): the smallest or largest of three words in the
# signed or unsigned order, which is one of the source words, copied. From R0Y00/Xbox2Windows#308 by Alexander,
# kept in uint words here.
@form(r"v_(min3|max3)_(i32|u32)(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)")
def min_max3(st, i, m):
    op, kind, dst, *tokens = m.groups()
    if inactive(st):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b, c = ordered(kind, (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens))
    fn = op[:-1]
    expression = f"{fn}({fn}({a}, {b}), {c})"
    st.lines.append(f"    uint valu{i} = {f'asuint({expression})' if kind == 'i32' else expression};")
    st.vector[dst] = ("uint", f"valu{i}")


# V_ADD_CO_U32 D = S0 + S1, V_SUB_CO_U32 D = S0 - S1, V_SUBREV_CO_U32 D = S1 - S0 (VOP3b), modulo 2^32, with the
# carry out of the add, or the borrow of the subtraction, written per lane to the lane mask (VCC or an SGPR), where a
# v_cndmask_b32 reads it like a comparison. clamp is refused: its saturation is not established for these forms.
@form(rf"v_(add|sub|subrev)_co_u32(?:_e64)? (v\d+), {LANE_MASK}, ([^,\s]+), ([^,\s]+)")
def add_sub_carry(st, i, m):
    op, dst, carry, first, second = m.groups()
    regs = lane_mask(carry)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (first, second))
    st.lines.append(f"    uint coa{i} = {a};")
    st.lines.append(f"    uint cob{i} = {b};")
    result, carry_out = {"add": (f"coa{i} + cob{i}", f"valu{i} < coa{i}"),
                         "sub": (f"coa{i} - cob{i}", f"cob{i} > coa{i}"),
                         "subrev": (f"cob{i} - coa{i}", f"coa{i} > cob{i}")}[op]
    st.lines.append(f"    uint valu{i} = {result};")
    st.lines.append(f"    bool cmp{i} = {carry_out};")
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.vector[dst] = ("uint", f"valu{i}")


# V_ADD_CO_CI_U32 D = S0 + S1 + carry-in, V_SUB_CO_CI_U32 D = S0 - S1 - carry-in, V_SUBREV_CO_CI_U32 D = S1 - S0 -
# carry-in, modulo 2^32 (VOP2 with VCC, or VOP3b with lane masks). The carry-in is a tracked comparison, read as
# v_cndmask_b32 reads it, and the carry out (the borrow of the subtractions) replaces the mask written. The carry out
# of an add is set when S0 + S1 wraps, or the sum with the carry-in does: the two cannot both happen.
@form(rf"v_(add|sub|subrev)_co_ci_u32(?:_e32|_e64)? (v\d+), {LANE_MASK}, ([^,\s]+), ([^,\s]+), {LANE_MASK}")
def add_sub_carry_in(st, i, m):
    op, dst, carry, first, second, source = m.groups()
    regs, in_regs = lane_mask(carry), lane_mask(source)
    condition = st.scalar.get(in_regs[0])
    if (st.ex != "true" or st.pending.intersection(regs) or st.pending.intersection(in_regs)
            or not isinstance(condition, tuple) or condition[0] != "condition"
            or [st.scalar.get(r) for r in in_regs] != [(*condition[:2], j, len(in_regs))
                                                       for j in range(len(in_regs))]):
        raise ValueError("Carry-in mask is not a tracked comparison")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (first, second))
    st.lines.append(f"    uint coa{i} = {a};")
    st.lines.append(f"    uint cob{i} = {b};")
    st.lines.append(f"    uint coc{i} = {condition[1]} ? 1u : 0u;")
    if op == "add":
        st.lines.append(f"    uint cot{i} = coa{i} + cob{i};")
        st.lines.append(f"    uint valu{i} = cot{i} + coc{i};")
        st.lines.append(f"    bool cmp{i} = (cot{i} < coa{i}) || (valu{i} < cot{i});")
    else:
        x, y = (f"coa{i}", f"cob{i}") if op == "sub" else (f"cob{i}", f"coa{i}")
        st.lines.append(f"    uint cot{i} = {x} - {y};")
        st.lines.append(f"    uint valu{i} = cot{i} - coc{i};")
        st.lines.append(f"    bool cmp{i} = ({x} < {y}) || (cot{i} < coc{i});")
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.vector[dst] = ("uint", f"valu{i}")
