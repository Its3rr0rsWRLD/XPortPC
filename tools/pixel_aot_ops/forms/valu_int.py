"""Integer vector forms (VOP1, VOP2, VOP3): bitwise, shifts, add/sub/mul, three-input forms, v_cvt_f32_ubyte."""
from ..dispatch import form
from ..registers import vector_u32

# Integer add, subtract, multiply and three-input forms. Semantics: AMD RDNA 2 ISA guide (instruction pseudocode in
# the VOP2/VOP3 sections): V_ADD_NC_U32 D=S0+S1, V_SUB_NC_U32 D=S0-S1, V_SUBREV_NC_U32 D=S1-S0, V_MUL_U32_U24
# D=S0.u[23:0]*S1.u[23:0], V_MUL_I32_I24 D=S0.i[23:0]*S1.i[23:0], V_MUL_HI_U32_U24 D=(S0.u24*S1.u24)>>32,
# V_MUL_HI_I32_I24 D=(S0.i24*S1.i24)>>32, V_MUL_HI_U32/V_MUL_HI_I32 D=(S0*S1)>>32, V_MUL_LO_U32 D=(S0*S1)[31:0],
# V_MAD_U32_U24 D=S0.u[23:0]*S1.u[23:0]+S2, V_MAD_I32_I24 D=S0.i[23:0]*S1.i[23:0]+S2, V_ADD3_U32 D=S0+S1+S2,
# V_LSHL_ADD_U32 D=(S0<<S1[4:0])+S2, V_ADD_LSHL_U32 D=(S0+S1)<<S2[4:0], V_LSHL_OR_B32 D=(S0<<S1[4:0])|S2,
# V_AND_OR_B32 D=(S0&S1)|S2, V_OR3_B32 D=S0|S1|S2, V_XOR3_B32 D=S0^S1^S2, V_XAD_U32 D=(S0^S1)+S2,
# V_ADD_NC_I32 D=S0+S1, V_SUB_NC_I32 D=S0-S1. Shift counts are the bit slice [4:0], so they are masked to five bits.
# Results wrap. The VOP3 clamp bit saturates the add and subtract forms (LLVM VOP3Instructions.td maps saddsat and
# ssubsat to V_ADD_I32_e64/V_SUB_I32_e64 with clamp); it is accepted only there, never on the multiplies, which
# llvm-mc assembles with clamp but whose saturation point is not established here.
INT_VOP2 = ("add_nc_u32", "sub_nc_u32", "subrev_nc_u32", "mul_u32_u24", "mul_i32_i24", "mul_hi_u32_u24", "mul_hi_i32_i24")
INT_VOP3 = ("add_nc_i32", "sub_nc_i32", "mul_lo_u32", "mul_hi_u32", "mul_hi_i32")
INT_CLAMPED = ("add_nc_u32", "sub_nc_u32", "subrev_nc_u32", "add_nc_i32", "sub_nc_i32")
INT_TERNARY = ("mad_u32_u24", "mad_i32_i24", "add3_u32", "lshl_add_u32", "add_lshl_u32", "lshl_or_b32", "and_or_b32",
               "or3_b32", "xor3_b32", "xad_u32")


def sext24(word):
    return f"asuint(asint({word} << 8u) >> 8)"


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
    if st.mask != "entry" or (clamp and suffix != "_e64"):
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
    if st.mask != "entry":
        raise ValueError("Invalid integer operation")
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
    if st.mask != "entry":
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)
    st.lines.append(f"    uint valu{i} = {'~' if op == 'not' else 'reversebits'}({word});")
    st.vector[dst] = ("uint", f"valu{i}")


@form(r"v_(" + "|".join(INT_VOP2 + INT_VOP3) + r")(_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)( clamp)?")
def binary(st, i, m):
    op, suffix, dst, first, second, clamp = m.groups()
    if st.mask != "entry" or (op in INT_VOP3 and suffix == "_e32") or (clamp and (suffix == "_e32" or op not in INT_CLAMPED)):
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
    if st.mask != "entry":
        raise ValueError("Invalid integer operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b, c = (vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (first, second, third))
    st.lines.append(f"    uint valu{i} = {int_ternary(op, a, b, c)};")
    st.vector[dst] = ("uint", f"valu{i}")
