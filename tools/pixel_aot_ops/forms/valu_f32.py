"""Binary32 vector arithmetic in the VOP1, VOP2 and VOP3 encodings, moves and v_cube*."""
import re

from ..dispatch import form
from ..registers import fp_operand, raw_source, vector_u32

ALU = {
    "log": (1, "log2({0})"), "exp": (1, "exp2({0})"), "rcp": (1, "(1.0f / {0})"),
    "sqrt": (1, "sqrt({0})"), "rsq": (1, "rsqrt({0})"),
    "floor": (1, "floor({0})"), "ceil": (1, "ceil({0})"), "fract": (1, "fract32({0})"),
    "trunc": (1, "trunc({0})"),
    "add": (2, "({0} + {1})"), "mul": (2, "({0} * {1})"),
    "max": (2, "max({0}, {1})"), "min": (2, "min({0}, {1})"), "sub": (2, "({0} - {1})"),
    "subrev": (2, "({1} - {0})"),
    "mul_legacy": (2, "(({0} == 0 || {1} == 0) ? 0.0f : {0} * {1})"),
    "fma": (3, "mad({0}, {1}, {2})"), "fmac": (3, "mad({0}, {1}, {2})"),
    "mad": (3, "mad32({0}, {1}, {2})"), "mac": (3, "mad32({0}, {1}, {2})"),
}


@form(r"v_cube(id|sc|tc|ma)_f32(?:_e64)? (v\d+), ([^,]+), ([^,]+), ([^,]+?)( clamp)?")
def cube(st, i, m):
    # LLVM ConstantFoldAMDGCNCubeIntrinsic: z, then y, then x is the major axis; a face is negative
    # only for a nonzero, non-NaN negative coordinate.
    op, dst, *tokens, clamp = m.groups()
    if st.mask != "entry":
        raise ValueError("Invalid cube operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    x, y, z = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    st.lines.append(f"    precise float3 cube{i} = float3({x}, {y}, {z});")
    c, a = f"cube{i}", f"abs(cube{i})"
    zmajor = f"({a}.z >= {a}.x && {a}.z >= {a}.y)"
    ymajor = f"({a}.y >= {a}.x)"
    expression = {
        "id": f"({zmajor} ? ({c}.z < 0.0f ? 5.0f : 4.0f) : {ymajor} ? ({c}.y < 0.0f ? 3.0f : 2.0f) : ({c}.x < 0.0f ? 1.0f : 0.0f))",
        "sc": f"({zmajor} ? ({c}.z < 0.0f ? -{c}.x : {c}.x) : {ymajor} ? {c}.x : ({c}.x < 0.0f ? {c}.z : -{c}.z))",
        "tc": f"({zmajor} ? -{c}.y : {ymajor} ? ({c}.y < 0.0f ? -{c}.z : {c}.z) : -{c}.y)",
        "ma": f"(({zmajor} ? {c}.z : {ymajor} ? {c}.y : {c}.x) * 2.0f)",
    }[op]
    if clamp:
        expression = f"saturate({expression})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")


@form(r"v_(fmaak|fmamk)_f32 (v\d+), ([^,]+), ([^,]+), ([^,]+)")
def literal_fma(st, i, m):
    op, dst, *tokens = m.groups()
    literal = tokens[2] if op == "fmaak" else tokens[1]
    if st.mask != "entry" or not re.fullmatch(r"0x[0-9a-f]{1,8}", literal):
        raise ValueError("Invalid literal multiply-add")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {ALU['fma'][1].format(*values)};")


@form(r"v_mov_b32(?:_e32|_e64)? (v\d+), (-?\d+(?:\.\d+)?|0x[0-9a-f]{1,8}|[vs]\d+)")
def move(st, i, m):
    # A bit copy of a numeric value; integer inline constants are bit patterns.
    dst, src = m.groups()
    if st.mask != "entry":
        raise ValueError("Invalid register move")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    if raw_source(src, st.scalar, st.vector):
        # A raw word is copied as an unsigned integer. It never takes a float type, so the compiler or the
        # driver has no float semantics (NaN canonicalization, denormal flushing) to apply to it.
        st.lines.append(f"    uint movw{i} = {vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)};")
        st.vector[dst] = ("uint", f"movw{i}")
    else:
        value = fp_operand(src, st.scalar, st.vector, st.pending, st.sample_pending)
        st.vector[dst] = f"alu{i}"
        st.lines.append(f"    precise float alu{i} = {value};")


@form(r"v_(log|exp|rcp|sqrt|rsq|floor|ceil|fract|trunc|add|mul|max|min|sub|subrev|mul_legacy|fma|fmac|mad|mac)_f32(?:_e32|_e64)? (v\d+), (.+?)( clamp)?")
def arithmetic(st, i, m):
    op, dst, operands, clamp = m.groups()
    tokens = operands.split(", ")
    if op in ("fmac", "mac"):
        tokens.append(dst)
    arity, template = ALU[op]
    if st.mask != "entry" or len(tokens) != arity:
        raise ValueError("Invalid arithmetic operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    expression = template.format(*values)
    if clamp:
        expression = f"saturate({expression})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")
