"""Binary32 vector arithmetic in the VOP1, VOP2 and VOP3 encodings, moves and v_cube*."""
import math
import re
import struct

from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import fp_operand, raw_source, vector_u32

ALU = {
    "log": (1, "log2({0})"), "exp": (1, "exp2({0})"), "rcp": (1, "(1.0f / {0})"),
    # The same reciprocal: v_rcp_iflag_f32 differs only in not raising the integer-divide exception flag, which has no
    # desktop equivalent (from R0Y00/Xbox2Windows#350 by denn0x). It stays a plain precise divide like v_rcp_f32, so the
    # transcendental rule of the e32 draws holds: its draws use only inputs whose reciprocal is exact.
    "rcp_iflag": (1, "(1.0f / {0})"),
    "sqrt": (1, "sqrt({0})"), "rsq": (1, "rsqrt({0})"),
    "floor": (1, "floor({0})"), "ceil": (1, "ceil({0})"), "fract": (1, "fract32({0})"),
    "trunc": (1, "trunc({0})"), "rndne": (1, "round({0})"),  # HLSL round is DXIL Round_ne: ties to even
    # v_sin_f32 and v_cos_f32 take revolutions (from R0Y00/Xbox2Windows#357 by dnn): see sin32 below.
    "sin": (1, "sin32({0})"), "cos": (1, "cos32({0})"),
    "add": (2, "({0} + {1})"), "mul": (2, "({0} * {1})"),
    "max": (2, "max({0}, {1})"), "min": (2, "min({0}, {1})"), "sub": (2, "({0} - {1})"),
    "subrev": (2, "({1} - {0})"),
    "mul_legacy": (2, "(({0} == 0 || {1} == 0) ? 0.0f : {0} * {1})"),
    "fma": (3, "mad({0}, {1}, {2})"), "fmac": (3, "mad({0}, {1}, {2})"),
    "mad": (3, "mad32({0}, {1}, {2})"), "mac": (3, "mad32({0}, {1}, {2})"),
    # Each result is one of the operands, so no rounding occurs. HLSL min and max return the other operand of a NaN,
    # as v_min_f32 and v_max_f32 already lower. v_med3_f32 is min3 when any operand is NaN (RDNA ISA, V_MED3_F32).
    "min3": (3, "min(min({0}, {1}), {2})"), "max3": (3, "max(max({0}, {1}), {2})"),
    "med3": (3, "med3_f32({0}, {1}, {2})"),
}
# Forms that exist only in the VOP3 encoding: an _e32 spelling of them is not an instruction.
VOP3_ONLY = ("fma", "mad", "min3", "max3", "med3")
# VOP3 output modifiers (omod) scale the result by 2, 4 or 0.5 after the operation and before clamp (ISA order).
#
# Mode. The ISA says omod is ignored while binary32 denormals are enabled. The hardware mode these lowerings model is
# the graphics default, IEEE bit clear and binary32 denormals flushed (LLVM SIModeRegisterDefaults; the same mode that
# makes v_mad_f32, v_mac_f32 and the transcendentals flush, see mad32 in hlsl.py), and a compiler emits omod only
# where it is honoured (SIFoldOperands::tryFoldOMod). So omod is applied, and a scaled result that is subnormal is
# flushed to a zero of its sign, as every flush-mode result is. A program that ran with denormals enabled would have
# omod ignored; this translator does not model that mode.
# Exactness. The scale is a power of two, so the multiply is exact except at the two edges, and both are handled
# without any rounding step: a result that scales past the largest finite binary32 becomes infinity (the IEEE
# overflow of the multiply, which the hardware gives too), and one that scales below the smallest normal number is
# zeroed by ftz32, an operation on the bits that cannot change a normal value. The operation's own result is not
# flushed before the scale (add, sub, mul, fma and min/max leave their results as the operation gives them), so a
# subnormal result of the operation itself is where the scale and the flush could be ordered either way; the draws
# keep every operation result a normal number.
# omod is accepted on the e64 spellings of arithmetic, min/max, the multiply-adds and the forms the transcendental
# draws measure; the rounding forms floor, ceil, fract and trunc and rcp_iflag still refuse it.
OMOD = {" mul:2": "2.0f", " mul:4": "4.0f", " div:2": "0.5f"}
OMOD_FORMS = ("log", "exp", "rcp", "sqrt", "rsq", "sin", "cos", "rndne", "min3", "max3", "med3",
              "add", "sub", "subrev", "mul", "mul_legacy", "min", "max", "fma", "fmac", "mad", "mac")

# v_sin_f32 and v_cos_f32 compute sin(2 * pi * x) and cos(2 * pi * x). Removing the nearest integer is exact in binary32
# and keeps the radian argument within [-pi, pi], where D3D bounds the sin and cos error; x * 2 * pi on the unreduced input
# would round away the fraction of a large argument. Inputs of at most half a turn pass unchanged, so -0 keeps its sign.
# An infinity reduces to NaN. D3D bounds the result only to 0.0008 absolute, so the draws (trig) quantize it.
SALU_HELPERS["turns"] = (
    "float turns(float value) {\n"
    "    return abs(value) > 0.5f ? value - round(value) : value;\n"
    "}"
)
SALU_HELPERS["sin32"] = "float sin32(float value) {\n    return sin(turns(value) * 6.28318548f);\n}"
SALU_HELPERS["cos32"] = "float cos32(float value) {\n    return cos(turns(value) * 6.28318548f);\n}"

SALU_HELPERS["med3_f32"] = (
    "float med3_f32(float a, float b, float c) {\n"
    "    if (isnan(a) || isnan(b) || isnan(c)) return min(min(a, b), c);\n"
    "    precise float high = max(max(a, b), c);\n"
    "    if (high == a) return max(b, c);\n"
    "    if (high == b) return max(a, c);\n"
    "    return max(a, b);\n"
    "}"
)


def _value_name(value):
    """The HLSL name a tracked VGPR value carries: a float name, or the name of a raw word ("uint", name)."""
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
        value = value[1]
    return value if isinstance(value, str) else None


def helper_defined(st, tokens):
    """Whether, under whole-quad execution with every lane active, every VGPR the operand tokens read holds a value
    defined on the helper lanes (Lowering.quad_values or Lowering.quad_defined): then the result of any VALU operation
    on them is defined there too, as on the hardware (the desktop's helper invocations run the same code). Scalar and
    immediate operands are the same on every lane. Unlike quad_values, the result need not be affine in the
    interpolated coordinate, so its derivatives depend on how the adapter takes them (coarse or fine): only a cube
    sample reads such a value (forms/mimg.py, docs/design/pixel-bindings.md)."""
    if not (st.wqm and st.ex == "true"):
        return False
    for token in tokens:
        m = re.fullmatch(r"-?(?:\|(v\d+)\||abs\((v\d+)\)|(v\d+))", token)
        if m:
            name = _value_name(st.vector.get(next(g for g in m.groups() if g)))
            if name is None or (name not in st.quad_values and name not in st.quad_defined):
                return False
    return True


def immediate_value(token):
    """The binary32 value of an immediate operand (an inline float constant, an integer inline constant or a literal
    word, both read as bit patterns), or None for a register or modified operand."""
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    if re.fullmatch(r"0x[0-9a-f]{1,8}|-?\d+", token):
        return struct.unpack("<f", struct.pack("<I", int(token, 0) & 0xffffffff))[0]
    return None


def integral_immediate(token):
    value = immediate_value(token)
    return value is not None and math.isfinite(value) and value == int(value)


@form(r"v_cube(id|sc|tc|ma)_f32(?:_e64)? (v\d+), ([^,]+), ([^,]+), ([^,]+?)( clamp)?")
def cube(st, i, m):
    # LLVM ConstantFoldAMDGCNCubeIntrinsic: z, then y, then x is the major axis; a face is negative
    # only for a nonzero, non-NaN negative coordinate.
    op, dst, *tokens, clamp = m.groups()
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
    if helper_defined(st, tokens):
        st.quad_defined.add(f"alu{i}")
    if op == "id" and not clamp:
        st.cube_faces.add(f"alu{i}")
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")


@form(r"v_(fmaak|fmamk|madak|madmk)_f32 (v\d+), ([^,]+), ([^,]+), ([^,]+)")
def literal_fma(st, i, m):
    # *ak: S0 * S1 + K; *mk: S0 * K + S1, with K a 32-bit literal. v_fma*k is fused; v_mad*k is the legacy unfused,
    # denormal-flushing multiply-add of v_mad_f32 (mad32), so it takes the same lowering as v_mad_f32 and v_mac_f32.
    op, dst, *tokens = m.groups()
    literal = tokens[2] if op.endswith("ak") else tokens[1]
    if not re.fullmatch(r"0x[0-9a-f]{1,8}", literal):
        raise ValueError("Invalid literal multiply-add")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    # A multiply-add with at most one varying factor, as for v_fma_f32 and v_mad_f32 (arithmetic, QUAD_AFFINE): under
    # whole-quad execution its result is a helper-lane value when every VGPR it reads is one.
    sources = [st.vector.get(t.lstrip("-")) if t.lstrip("-").startswith("v") else None for t in tokens]
    if (st.wqm and st.ex == "true" and not any("|" in t or "abs(" in t for t in tokens)
            and all(v in st.quad_values for t, v in zip(tokens, sources) if t.lstrip("-").startswith("v"))):
        varying = [st.quad_values.get(v, False) for v in sources]
        if not all(varying[:2]):  # S0 * K or S0 * S1
            st.quad_values[f"alu{i}"] = any(varying)
    if f"alu{i}" not in st.quad_values and helper_defined(st, tokens):
        st.quad_defined.add(f"alu{i}")
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {ALU[op[:3]][1].format(*values)};")


@form(r"v_mov_b32(?:_e32|_e64)? (v\d+), (-?\d+(?:\.\d+)?|0x[0-9a-f]{1,8}|[vs]\d+)")
def move(st, i, m):
    # A bit copy of a numeric value; integer inline constants are bit patterns.
    dst, src = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    # Under whole-quad execution with every lane active, a copy of a helper-lane value (Lowering.quad_values) or of an
    # immediate (the same on every lane) is defined on the helper lanes too, so an implicit-level sample may read it.
    # An SGPR copy and a copy written under the entry mask or while the lane may be inactive do not join the set.
    quad = st.wqm and st.ex == "true"
    source_name = _value_name(st.vector.get(src)) if src.startswith("v") else None
    name = f"movw{i}" if raw_source(src, st.scalar, st.vector) else f"alu{i}"
    if integral_immediate(src) or source_name in st.integral:
        st.integral.add(name)
    if source_name in st.cube_faces:
        st.cube_faces.add(name)
    if quad and source_name in st.quad_defined:
        st.quad_defined.add(name)
    if raw_source(src, st.scalar, st.vector):
        # A raw word is copied as an unsigned integer. It never takes a float type, so the compiler or the
        # driver has no float semantics (NaN canonicalization, denormal flushing) to apply to it.
        st.lines.append(f"    uint movw{i} = {vector_u32(src, st.scalar, st.vector, st.pending, st.sample_pending)};")
        st.vector[dst] = ("uint", f"movw{i}")
        if quad and not src.startswith(("v", "s")):
            st.quad_values[f"movw{i}"] = False
    else:
        value = fp_operand(src, st.scalar, st.vector, st.pending, st.sample_pending)
        if quad and not src.startswith(("v", "s")):
            st.quad_values[f"alu{i}"] = False
        elif quad and src.startswith("v") and (source := st.vector.get(src)) in st.quad_values:
            st.quad_values[f"alu{i}"] = st.quad_values[source]
        st.vector[dst] = f"alu{i}"
        st.lines.append(f"    precise float alu{i} = {value};")


# The VALU operations whose whole-quad result joins Lowering.quad_values (arithmetic): sums and differences of quad
# values, and products and multiply-adds with at most one varying factor.
QUAD_AFFINE = ("add", "sub", "subrev", "fma", "fmac", "mad", "mac", "mul", "mul_legacy")


@form(r"v_(log|exp|rcp_iflag|rcp|sqrt|rsq|sin|cos|floor|ceil|fract|trunc|rndne|add|mul|max|min|sub|subrev|mul_legacy|fma|fmac|mad|mac"
      r"|min3|max3|med3)_f32(_e32|_e64)? (v\d+), (.+?)( clamp)?( mul:2| mul:4| div:2)?")
def arithmetic(st, i, m):
    op, suffix, dst, operands, clamp, omod = m.groups()
    tokens = operands.split(", ")
    if op in ("fmac", "mac"):
        tokens.append(dst)
    arity, template = ALU[op]
    if len(tokens) != arity or (suffix == "_e32" and (op in VOP3_ONLY or omod)):
        raise ValueError("Invalid arithmetic operation")
    if omod and op not in OMOD_FORMS:
        raise ValueError("Unsupported output modifier")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    # CF-2a: whole-quad execution does not restrict VALU, every lane is active. What an implicit-LOD sample may read is
    # the set of values defined on the helper lanes (Lowering.quad_values): affine coordinate arithmetic (QUAD_AFFINE
    # of such values and ready constants, with at most one varying factor in a product, no absolute value and no
    # clamp) extends it (from R0Y00/Xbox2Windows#283 by Vonsek, there before the first sample of a one-texture program
    # only; its operands are never sample results and the textures bound do not change what the helper lanes compute,
    # so neither restriction is needed); anything else is lowered but does not join it.
    quad = (st.wqm and st.ex == "true" and op in QUAD_AFFINE and not clamp
            and not any("|" in t or "abs(" in t for t in tokens))
    provenance = st.quad_values if quad else None
    try:
        values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending, quad_values=provenance)
                  for t in tokens]
    except ValueError as error:
        if not quad or "helper-lane" not in str(error):
            raise
        quad, values = False, [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    if quad:
        varying = [st.quad_values.get(st.vector.get(t.lstrip("-"), ""), False) for t in tokens]
        if op not in ("add", "sub", "subrev") and all(varying[:2]):
            quad = False
    if quad:
        st.quad_values[f"alu{i}"] = any(varying)
    elif helper_defined(st, tokens):
        st.quad_defined.add(f"alu{i}")
    if op in ("rndne", "floor", "ceil", "trunc") and not omod:
        st.integral.add(f"alu{i}")
    expression = template.format(*values)
    if op == "med3":
        st.helpers.add("med3_f32")
    if op in ("sin", "cos"):
        st.helpers.update(("turns", f"{op}32"))
    if omod:
        expression = f"ftz32(({expression} * {OMOD[omod]}))"
    if clamp:
        expression = f"saturate({expression})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")
