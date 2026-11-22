"""Quad-local DPP16 and DPP8 forms (from R0Y00/Xbox2Windows#408, #414, #419, #421 and #423 by KomaGuy).

A DPP instruction is a VOP1 or VOP2 instruction whose first source is read from another lane of the same quad
(quad_perm for DPP16, dpp8 for DPP8; ../quad.py). The cross-lane read is done on the unsigned 32-bit word of the
source register, then the instruction runs on the swizzled word exactly as its non-DPP encoding would: where the
non-DPP form is lowered in another family module, the DPP form swizzles its first source into a scratch register and
hands that instruction to the same dispatch, so its arithmetic, its helpers and its refusals are those of
the non-DPP form. The forms that exist only here (bit scans, conversions that no other module lowers, frexp, carry-in
adds, the binary16 transcendentals) are lowered below.

Both sources of a DPP instruction are VGPRs. Source modifiers (abs, neg) exist only in DPP16 and only on floating-point
sources; they act after the read. The destination is a VGPR. Refused: a lane that may be inactive (`st.ex`), whole-quad
mode (a helper lane would be read), a write that overlaps an outstanding sample, a source that is not a completed
VGPR, any row or bank pattern that is not quad-local, and every DPP opcode not listed here.

Not ported: v_dot2c_f32_f16_dpp and v_dot4c_i32_i8_dpp (gfx1030 encodings that the gfx1013 binary check cannot
assemble) and the v_movrel*_dpp forms of #428 (they need the bounded-m0 tracking of the scalar forms)."""
import re

from ..dispatch import dispatch, form
from ..hlsl import SALU_HELPERS
from ..quad import dpp_control, quad_read
from ..registers import tracked_word, vector_u32

F32_UNARY = ("log", "exp", "rcp", "sqrt", "rsq", "floor", "ceil", "fract", "trunc", "rndne")
F32_BINARY = ("add", "mul", "max", "min", "sub", "subrev", "mul_legacy", "fmac", "mac")
F16_UNARY = ("floor", "ceil", "trunc", "rndne", "fract")
F16_BINARY = ("add", "sub", "subrev", "mul", "max", "min", "ldexp")
INT_UNARY = ("not_b32", "bfrev_b32")
INT_BINARY = ("and_b32", "or_b32", "xor_b32", "xnor_b32", "lshlrev_b32", "lshrrev_b32", "ashrrev_i32",
              "add_nc_u32", "sub_nc_u32", "subrev_nc_u32", "mul_u32_u24", "mul_hi_u32_u24", "mul_i32_i24",
              "mul_hi_i32_i24", "min_i32", "max_i32", "min_u32", "max_u32")

# Opcode (between v_ and _dpp) -> (number of source operands, whether the sources take abs and neg). The instruction
# is then lowered by the non-DPP form with the same name and the e32 spelling.
DELEGATED = {"mov_b32": (1, False), "cndmask_b32": (3, False), "cvt_f32_f16": (1, True), "cvt_f16_f32": (1, True),
             "cvt_f32_i32": (1, False), "cvt_f32_u32": (1, False), "cvt_i32_f32": (1, True), "cvt_u32_f32": (1, True),
             "rcp_iflag_f32": (1, True)}
DELEGATED.update({f"cvt_f32_ubyte{n}": (1, False) for n in range(4)})
DELEGATED.update({f"{op}_f32": (1, True) for op in F32_UNARY})
DELEGATED.update({f"{op}_f32": (2, True) for op in F32_BINARY})
DELEGATED.update({f"{op}_f16": (1, True) for op in F16_UNARY})
DELEGATED.update({f"{op}_f16": (2, True) for op in F16_BINARY})
DELEGATED.update({op: (1, False) for op in INT_UNARY})
DELEGATED.update({op: (2, False) for op in INT_BINARY})
# The non-DPP form that lowers an alias: v_rcp_iflag_f32 differs from v_rcp_f32 only in not raising an exception.
ALIAS = {"rcp_iflag_f32": "rcp_f32"}

# DPP ops whose result is the low half of the destination: the high half is kept, so the destination must hold a value.
F16_RESULT = {f"{op}_f16" for op in (*F16_UNARY, *F16_BINARY)} | {"cvt_f16_f32"}

SCRATCH = 1000  # scratch register numbers start here, past the last VGPR


def _hlsl(name, body):
    SALU_HELPERS[name] = body


_hlsl("dpp_ffbh_u32", "uint dpp_ffbh_u32(uint x) {\n    return x == 0u ? 0xffffffffu : (31u - firstbithigh(x));\n}")
_hlsl("dpp_ffbh_i32", "uint dpp_ffbh_i32(uint x) {\n    uint m = asint(x) < 0 ? ~x : x;\n"
                      "    return m == 0u ? 0xffffffffu : (31u - firstbithigh(m));\n}")
_hlsl("dpp_cvt_i32_f32", "uint dpp_cvt_i32_f32(float x) {\n    if (isnan(x)) return 0u;\n"
                         "    if (x >= 2147483648.0f) return 0x7fffffffu;\n    if (x <= -2147483648.0f) return 0x80000000u;\n"
                         "    return asuint(int(x));\n}")
_hlsl("dpp_cvt_i16_f16", "uint dpp_cvt_i16_f16(float x) {\n    if (isnan(x)) return 0u;\n"
                         "    if (x >= 32767.0f) return 32767u;\n    if (x <= -32768.0f) return 0x8000u;\n"
                         "    return asuint(int(trunc(x))) & 0xffffu;\n}")
_hlsl("dpp_cvt_u16_f16", "uint dpp_cvt_u16_f16(float x) {\n    if (isnan(x) || x <= 0.0f) return 0u;\n"
                         "    if (x >= 65535.0f) return 65535u;\n    return uint(trunc(x)) & 0xffffu;\n}")
_hlsl("dpp_cvt_norm_i16_f16", "uint dpp_cvt_norm_i16_f16(float x) {\n    if (isnan(x)) return 0u;\n"
                              "    return asuint(int(round(clamp(x, -1.0f, 1.0f) * 32767.0f))) & 0xffffu;\n}")
_hlsl("dpp_cvt_norm_u16_f16", "uint dpp_cvt_norm_u16_f16(float x) {\n    if (isnan(x)) return 0u;\n"
                              "    return uint(round(saturate(x) * 65535.0f)) & 0xffffu;\n}")
_hlsl("dpp_sat_pk_u8_i16", "uint dpp_sat_pk_u8_i16(uint w) {\n    int lo = asint(w << 16) >> 16;\n    int hi = asint(w) >> 16;\n"
                           "    return uint(clamp(lo, 0, 255)) | (uint(clamp(hi, 0, 255)) << 8);\n}")
# Two binary32 values rounded toward zero to binary16 and packed (v_cvt_pkrtz_f16_f32 as a value; the export form keeps
# the pair instead). NaN gives the quiet NaN, a value beyond 65504 gives infinity.
_hlsl("dpp_pack16_rtz", "uint dpp_pack16_rtz(float value) {\n    uint bits = asuint(value);\n"
                        "    uint sign = (bits >> 16) & 0x8000u;\n    uint abs_bits = bits & 0x7fffffffu;\n"
                        "    if (abs_bits > 0x7f800000u) return 0x7e00u;\n"
                        "    if (abs_bits >= 0x47800000u) return sign | 0x7c00u;\n"
                        "    if (abs_bits >= 0x38800000u) return sign | ((abs_bits - 0x38000000u) >> 13);\n"
                        "    if (abs_bits < 0x33800000u) return sign;\n"
                        "    uint sig = 0x00800000u | (abs_bits & 0x007fffffu);\n"
                        "    return sign | (sig >> (126u - (abs_bits >> 23)));\n}")
_hlsl("dpp_frexp_mant_f32", "float dpp_frexp_mant_f32(uint bits) {\n    uint exp = (bits >> 23) & 0xffu;\n"
                            "    uint mant = bits & 0x7fffffu;\n"
                            "    if (exp == 0xffu || (exp == 0u && mant == 0u)) return asfloat(bits);\n"
                            "    uint sign = bits & 0x80000000u;\n"
                            "    if (exp == 0u) {\n        uint shift = 23u - firstbithigh(mant);\n"
                            "        mant = (mant << shift) & 0x7fffffu;\n    }\n"
                            "    return asfloat(sign | 0x3f000000u | mant);\n}")
_hlsl("dpp_frexp_exp_i32_f32", "uint dpp_frexp_exp_i32_f32(uint bits) {\n    uint exp = (bits >> 23) & 0xffu;\n"
                               "    uint mant = bits & 0x7fffffu;\n"
                               "    if (exp == 0xffu || (exp == 0u && mant == 0u)) return 0u;\n"
                               "    if (exp == 0u) return asuint(int(firstbithigh(mant)) - 148);\n"
                               "    return asuint(int(exp) - 126);\n}")
# Binary16 frexp of a widened value: the mantissa is 0.5 <= |m| < 1 with the sign of the input, the exponent a signed
# 16-bit integer. NaN, infinity and zero give the input and zero, as for binary32.
_hlsl("dpp_frexp_mant_f16", "float dpp_frexp_mant_f16(float x) {\n    uint bits = asuint(x);\n    uint ab = bits & 0x7fffffffu;\n"
                            "    if (ab == 0u || ab >= 0x7f800000u) return x;\n"
                            "    return asfloat((bits & 0x807fffffu) | 0x3f000000u);\n}")
_hlsl("dpp_frexp_exp_i16_f16", "uint dpp_frexp_exp_i16_f16(float x) {\n    uint ab = asuint(x) & 0x7fffffffu;\n"
                               "    if (ab == 0u || ab >= 0x7f800000u) return 0u;\n"
                               "    return asuint(int(ab >> 23) - 126) & 0xffffu;\n}")

# Operations lowered here. kind: u32 result word, f32 float result, f16 result in the low half of the destination.
# source: how the first source word is read (bits, f32, f16, i16 = low half as a signed integer); the expression
# templates take the typed first source {0} and, for binary ones, the typed second source {1}.
OWN = {
    "ffbl_b32": ("u32", "bits", "firstbitlow({0})", ()),
    "ffbh_u32": ("u32", "bits", "dpp_ffbh_u32({0})", ("dpp_ffbh_u32",)),
    "ffbh_i32": ("u32", "bits", "dpp_ffbh_i32({0})", ("dpp_ffbh_i32",)),
    "cvt_off_f32_i4": ("f32", "bits", "(float(asint({0} << 28) >> 28) * 0.0625f)", ()),
    "cvt_flr_i32_f32": ("u32", "f32", "dpp_cvt_i32_f32(floor({0}))", ("dpp_cvt_i32_f32",)),
    "cvt_rpi_i32_f32": ("u32", "f32", "dpp_cvt_i32_f32(floor({0} + 0.5f))", ("dpp_cvt_i32_f32",)),
    "cvt_f16_i16": ("f16", "bits", "narrow16(float(asint({0} << 16) >> 16))", ()),
    "cvt_f16_u16": ("f16", "bits", "narrow16(float({0} & 0xffffu))", ()),
    "cvt_i16_f16": ("f16", "f16", "dpp_cvt_i16_f16({0})", ("dpp_cvt_i16_f16",)),
    "cvt_u16_f16": ("f16", "f16", "dpp_cvt_u16_f16({0})", ("dpp_cvt_u16_f16",)),
    "cvt_norm_i16_f16": ("f16", "f16", "dpp_cvt_norm_i16_f16({0})", ("dpp_cvt_norm_i16_f16",)),
    "cvt_norm_u16_f16": ("f16", "f16", "dpp_cvt_norm_u16_f16({0})", ("dpp_cvt_norm_u16_f16",)),
    "sat_pk_u8_i16": ("f16", "bits", "dpp_sat_pk_u8_i16({0})", ("dpp_sat_pk_u8_i16",)),
    "sin_f32": ("f32", "f32", "sin(({0}) * 6.283185307179586f)", ()),
    "cos_f32": ("f32", "f32", "cos(({0}) * 6.283185307179586f)", ()),
    "frexp_mant_f32": ("f32", "bits", "dpp_frexp_mant_f32({0})", ("dpp_frexp_mant_f32",)),
    "frexp_exp_i32_f32": ("u32", "bits", "dpp_frexp_exp_i32_f32({0})", ("dpp_frexp_exp_i32_f32",)),
    "log_f16": ("f16", "f16", "narrow16(log2({0}))", ()),
    "exp_f16": ("f16", "f16", "narrow16(exp2({0}))", ()),
    "rcp_f16": ("f16", "f16", "narrow16(1.0f / {0})", ()),
    "sqrt_f16": ("f16", "f16", "narrow16(sqrt({0}))", ()),
    "rsq_f16": ("f16", "f16", "narrow16(rsqrt({0}))", ()),
    "sin_f16": ("f16", "f16", "narrow16(sin(({0}) * 6.283185307179586f))", ()),
    "cos_f16": ("f16", "f16", "narrow16(cos(({0}) * 6.283185307179586f))", ()),
    "frexp_mant_f16": ("f16", "f16", "narrow16(dpp_frexp_mant_f16({0}))", ("dpp_frexp_mant_f16",)),
    "frexp_exp_i16_f16": ("f16", "f16", "dpp_frexp_exp_i16_f16({0})", ("dpp_frexp_exp_i16_f16",)),
    "fmac_f16": ("f16", "f16", "narrow16(mad({0}, {1}, {2}))", ()),
    "cvt_pkrtz_f16_f32": ("u32", "f32", "(dpp_pack16_rtz({0}) | (dpp_pack16_rtz({1}) << 16))", ("dpp_pack16_rtz",)),
}
# Float sources of these take abs and neg in DPP16 (bit sources and integer ones do not).
MODIFIABLE = {"cvt_flr_i32_f32", "cvt_rpi_i32_f32", "sin_f32", "cos_f32", "frexp_mant_f32", "frexp_exp_i32_f32",
              "log_f16", "exp_f16", "rcp_f16", "sqrt_f16", "rsq_f16", "sin_f16", "cos_f16", "frexp_mant_f16",
              "frexp_exp_i16_f16", "fmac_f16", "cvt_pkrtz_f16_f32", "cvt_i16_f16", "cvt_u16_f16", "cvt_norm_i16_f16", "cvt_norm_u16_f16"}
CARRY = ("add_co_ci_u32", "sub_co_ci_u32", "subrev_co_ci_u32")
BINARY_OWN = {"fmac_f16", "cvt_pkrtz_f16_f32"}  # a second source; v_fmac_f16 also accumulates into the destination

VGPR = r"v\d+"
SOURCE = r"(-?)(?:\|(v\d+)\||abs\((v\d+)\)|(v\d+))"


def _vgpr(token, st, *, mods):
    """Split a DPP source token into (register, negate, absolute). Only a VGPR; modifiers only where allowed."""
    m = re.fullmatch(SOURCE, token)
    if not m:
        raise ValueError(f"DPP source must be a VGPR, got {token}")
    neg, bar, call, plain = m.groups()
    reg = bar or call or plain
    if not 0 <= int(reg[1:]) <= 255:
        raise ValueError(f"VGPR out of range: {reg}")
    if (neg or bar or call) and not mods:
        raise ValueError(f"Source modifiers are not allowed on {token}")
    return reg, bool(neg), bool(bar or call)


def _word(st, reg):
    """The 32-bit word of a completed VGPR. The interpolated coordinate (uv.x, uv.y) is a float value."""
    value = st.vector.get(reg)
    if isinstance(value, str) and value.startswith("uv."):
        return f"asuint({value})"
    return vector_u32(reg, st.scalar, st.vector, st.pending, st.sample_pending)


def _prepare(st, i, dst, operands, count, *, mods):
    """Check the instruction-wide conditions and split the operand text. Returns (tokens, perm, dpp8)."""
    if st.ex != "true" or st.wqm:
        raise ValueError("DPP is lowered only where every lane is active and the wave is not in whole-quad mode")
    if not 0 <= int(dst[1:]) <= 255:
        raise ValueError(f"VGPR out of range: {dst}")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    parts = operands.split(", ")
    last, _, control = parts[-1].partition(" ")
    tokens = [*parts[:-1], last]
    if len(tokens) != count:
        raise ValueError("Invalid DPP operand count")
    perm, dpp8 = dpp_control(control.split())
    return tokens, perm, dpp8


@form(r"v_(\w+)_dpp (v\d+), (.+)")
def dpp(st, i, m):
    op, dst, operands = m.groups()
    if op in DELEGATED:
        count, mods = DELEGATED[op]
        tokens, perm, dpp8 = _prepare(st, i, dst, operands, count, mods=mods)
        if op == "cndmask_b32":
            if tokens[2] not in ("vcc", "vcc_lo"):
                raise ValueError(f"v_cndmask_b32_dpp requires vcc, got {tokens[2]}")
        if op in F16_RESULT and dst not in st.vector:
            raise ValueError("A 16-bit DPP result keeps the high half of a destination that holds no value")
        target = ALIAS.get(op, op)
        reg, neg, absolute = _vgpr(tokens[0], st, mods=mods and not dpp8)
        scratch = f"v{SCRATCH + i}"
        st.vector[scratch] = ("uint", quad_read(st, i, _word(st, reg), perm))
        first = scratch if not absolute else f"|{scratch}|"
        first = f"-{first}" if neg else first
        # The sources after the first are plain VGPRs (with modifiers where the instruction takes them); the select
        # mask of v_cndmask_b32 is the last operand and is read by that form.
        rest = tokens[1:]
        scratches = [scratch]
        for k, token in enumerate(rest[:-1] if op == "cndmask_b32" else rest):
            reg1, neg1, abs1 = _vgpr(token, st, mods=mods and not dpp8)
            if isinstance(st.vector.get(reg1), str) and st.vector[reg1].startswith("uv."):
                # The interpolated coordinate is read by the float forms only after a copy as a word.
                other = f"v{SCRATCH + 256 * (k + 1) + i}"
                st.vector[other] = ("uint", _word(st, reg1))
                scratches.append(other)
                rest[k] = f"{'-' if neg1 else ''}{f'|{other}|' if abs1 else other}"
        dispatch(st, i, f"v_{target}_e32 {dst}, {', '.join([first, *rest])}")
        for name in scratches:
            del st.vector[name]
    elif op in OWN:
        own(st, i, op, dst, operands)
    elif op in CARRY:
        carry(st, i, op, dst, operands)
    else:
        raise ValueError(f"Unsupported DPP instruction v_{op}_dpp")


def _typed(word, source, neg, absolute):
    """The first source word given its type, then abs and neg (on the encoding's sign bit for binary16)."""
    if source == "bits":
        return word
    if source == "f16":
        bits = f"({word} & 0xffffu)"
        if absolute:
            bits = f"({bits} & 0x7fffu)"
        if neg:
            bits = f"({bits} ^ 0x8000u)"
        return f"widen16({bits})"
    value = f"asfloat({word})"
    value = f"abs({value})" if absolute else value
    return f"(-{value})" if neg else value


def own(st, i, op, dst, operands):
    kind, source, template, helpers = OWN[op]
    count = 2 if op in BINARY_OWN else 1
    mods = op in MODIFIABLE
    tokens, perm, dpp8 = _prepare(st, i, dst, operands, count, mods=mods)
    reg, neg, absolute = _vgpr(tokens[0], st, mods=mods and not dpp8)
    args = [_typed(quad_read(st, i, _word(st, reg), perm), source, neg, absolute)]
    if op in BINARY_OWN:
        reg1, neg1, abs1 = _vgpr(tokens[1], st, mods=not dpp8)
        args.append(_typed(_word(st, reg1), source, neg1, abs1))
        if op == "fmac_f16":
            acc = st.vector.get(dst)
            if tracked_word(acc) is None:
                raise ValueError("v_fmac_f16_dpp accumulates into a destination that holds no numeric word")
            args.append(f"widen16({tracked_word(acc)} & 0xffffu)")
    st.helpers.update(helpers)
    expression = template.format(*args)
    if kind == "u32":
        st.lines.append(f"    uint valu{i} = {expression};")
        st.vector[dst] = ("uint", f"valu{i}")
    elif kind == "f32":
        st.lines.append(f"    precise float alu{i} = {expression};")
        st.vector[dst] = f"alu{i}"
    else:
        # A 16-bit result replaces the low half of the destination and keeps the high half (as v_cvt_f16_f32).
        old = st.vector.get(dst)
        if tracked_word(old) is None:
            raise ValueError("A 16-bit DPP result keeps the high half of a destination that holds a numeric word")
        high = f"({tracked_word(old)} & 0xffff0000u)"
        st.vector[dst] = f"alu{i}"
        st.lines.append(f"    precise float alu{i} = asfloat({high} | ({expression} & 0xffffu));")


def carry(st, i, op, dst, operands):
    # v_add_co_ci_u32 D = S0 + S1 + carry-in, v_sub_co_ci_u32 D = S0 - S1 - carry-in, v_subrev_co_ci_u32 the reverse.
    # The carry mask is vcc, tracked as a comparison; the carry out replaces it.
    parts = operands.split(", ")
    if len(parts) != 4 or parts[0] != parts[3].partition(" ")[0] or parts[0] not in ("vcc", "vcc_lo"):
        raise ValueError(f"Unsupported carry mask for {op}")
    tokens, perm, dpp8 = _prepare(st, i, dst, ", ".join(parts[1:]), 3, mods=False)
    condition = st.scalar.get("vcc")
    if ("vcc" in st.pending or not isinstance(condition, tuple) or condition[0] != "condition"
            or condition[2:] != (0, 1)):
        raise ValueError("Carry mask is not a tracked condition")
    a_reg, _, _ = _vgpr(tokens[0], st, mods=False)
    b_reg, _, _ = _vgpr(tokens[1], st, mods=False)
    st.lines.append(f"    uint dpp{i}_a = {quad_read(st, i, _word(st, a_reg), perm)};")
    st.lines.append(f"    uint dpp{i}_b = {_word(st, b_reg)};")
    st.lines.append(f"    uint dpp{i}_c = {condition[1]} ? 1u : 0u;")
    x, y = (f"dpp{i}_a", f"dpp{i}_b") if op != "subrev_co_ci_u32" else (f"dpp{i}_b", f"dpp{i}_a")
    if op == "add_co_ci_u32":
        st.lines.append(f"    uint dpp{i}_t = {x} + {y};")
        st.lines.append(f"    uint dpp{i}_r = dpp{i}_t + dpp{i}_c;")
        st.lines.append(f"    bool cmp{i} = (dpp{i}_t < {x}) || (dpp{i}_r < dpp{i}_t);")
    else:
        st.lines.append(f"    uint dpp{i}_t = {x} - {y};")
        st.lines.append(f"    uint dpp{i}_r = dpp{i}_t - dpp{i}_c;")
        st.lines.append(f"    bool cmp{i} = ({x} < {y}) || (dpp{i}_t < dpp{i}_c);")
    st.scalar["vcc"] = ("condition", f"cmp{i}", 0, 1)
    st.lines.append(f"    uint dppw{i} = dpp{i}_r;")
    st.vector[dst] = ("uint", f"dppw{i}")
