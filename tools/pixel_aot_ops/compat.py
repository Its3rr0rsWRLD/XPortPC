"""Upstream-shaped views of the instruction tables that the split translator keeps per family.

Upstream's monolithic tools/pixel_aot.py had one table per instruction class, and merged upstream tests and tools read
them as pixel_aot.INTEGER, SCALAR, VOP3P_F16 and VOP3P_INT16 (tests/pso_readiness_check.py, tools/scan_unsupported_
shaders.py). Here the forms live in forms/ and have no such tables, so each view lists the names this translator lowers
with the shape of upstream's entries: name -> (source count, HLSL, ...). Nothing reads the HLSL slots, so they hold None;
lowering never uses these views. tests/pixel_aot_draws/ and tools/corpus_translate.py exercise the forms themselves.
"""
from .forms.vop3p import PK_F16, PK_INT16

# VOP1/VOP2/VOP3 integer forms of upstream's INTEGER table: name (without v_) -> (source count, HLSL). forms/valu_int.py
# lowers the bitwise and shift forms with one pattern, v_not_b32 with another, and the 24-bit multiplies from INT_VOP2.
INTEGER = {name: (arity, None) for name, arity in (
    ("and_b32", 2), ("or_b32", 2), ("xor_b32", 2), ("not_b32", 1), ("bfi_b32", 3),
    ("lshlrev_b32", 2), ("lshrrev_b32", 2), ("ashrrev_i32", 2),
    ("mul_u32_u24", 2), ("mul_i32_i24", 2), ("mul_hi_u32_u24", 2), ("mul_hi_i32_i24", 2))}

# 32-bit scalar ALU forms: name (without s_) -> (source count, HLSL, SCC expression). forms/salu32.py, forms/sop2.py.
SCALAR = {name: (arity, None, None) for name, arity in (
    ("flbit_i32_b32", 1), ("flbit_i32", 1), ("bcnt0_i32_b32", 1), ("bcnt1_i32_b32", 1), ("mul_hi_u32", 2),
    ("mul_hi_i32", 2), ("pack_ll_b32_b16", 2), ("pack_lh_b32_b16", 2), ("pack_hh_b32_b16", 2), ("sext_i32_i8", 1),
    ("sext_i32_i16", 1), ("abs_i32", 1), ("add_u32", 2), ("sub_u32", 2), ("add_i32", 2), ("sub_i32", 2),
    ("mul_i32", 2), ("min_u32", 2), ("max_u32", 2), ("min_i32", 2), ("max_i32", 2), ("and_b32", 2), ("or_b32", 2),
    ("xor_b32", 2), ("andn2_b32", 2), ("orn2_b32", 2), ("not_b32", 1), ("nand_b32", 2), ("nor_b32", 2),
    ("xnor_b32", 2), ("bfm_b32", 2), ("lshl_b32", 2), ("lshr_b32", 2), ("ashr_i32", 2), ("lshl1_add_u32", 2),
    ("lshl2_add_u32", 2), ("lshl3_add_u32", 2), ("lshl4_add_u32", 2))}

# Packed 16-bit forms, from the tables forms/vop3p.py lowers with: v_pk_<name>_f16 and v_pk_<name>.
VOP3P_F16 = {name: (arity, None) for name, arity in PK_F16.items()}
VOP3P_INT16 = dict(PK_INT16)
