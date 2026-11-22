"""Remaining float VOP1, VOP2 and VOP3 forms that need no VCC and are exact: conversions to and from 16-bit integers,
v_cvt_off_f32_i4, v_cvt_flr_i32_f32, v_cvt_rpi_i32_f32, v_sat_pk_u8_i16, v_frexp_* (binary32 and binary16), the binary16
three-input selections v_min3_f16, v_max3_f16 and v_med3_f16, and v_mad_legacy_f32 and v_mac_legacy_f32.

The arithmetic of the conversions and frexp is the one the DPP forms already lower (forms/dpp.py OWN: the same
expressions and helpers), here for the plain VOP1 encodings in both spellings. Integer and 16-bit results are uint words:
a 32-bit result is a `valu` word, and a 16-bit result is `f16w`, the low half of the destination replaced and the high
half kept (a destination with no value keeps zero, as for v_cvt_f16_f32). The float source of a 32-bit-source form may
carry neg and abs in the VOP3 spelling (abs and neg act on the sign bit of the word for frexp, on bit 15 for binary16);
integer sources take none. clamp and omod exist only on the three-input binary16 forms and the legacy multiply-adds.

Refused, because they cannot be made exact here (each has a must_reject control in tests/pixel_aot_draws/valu_float_rest.py):
v_fma_f16, v_fmac_f16, v_fmaak_f16, v_fmamk_f16 (a binary16 fused multiply-add needs one rounding of a 22-bit product plus
an addend; the binary32 route rounds twice), v_div_fmas_f32 (reads VCC), v_div_scale_f32 (writes VCC and special-cases
exponent gaps), v_div_fixup_f16 and v_div_fixup_f32 (exponent-gap and NaN rules not established). Also not lowered:
v_ldexp_f32 (the scale 2^n is not representable at the ends of the exponent range and the denormal result rounds twice),
v_cvt_norm_*, v_cvt_pknorm_* (rounding mode of the scaled value not established)."""
import re

from ..dispatch import form
from ..hlsl import SALU_HELPERS
from ..registers import f16_operand, fp_operand, tracked_word, word_of
from .dpp import OWN

OPS = ("cvt_off_f32_i4", "cvt_flr_i32_f32", "cvt_rpi_i32_f32", "cvt_f16_i16", "cvt_f16_u16", "cvt_i16_f16",
       "cvt_u16_f16", "sat_pk_u8_i16", "frexp_mant_f32", "frexp_exp_i32_f32", "frexp_mant_f16", "frexp_exp_i16_f16")
# Sources that take neg and abs in the VOP3 spelling: floats, and the frexp bit sources (sign-bit operations).
MODIFIABLE = {"cvt_flr_i32_f32", "cvt_rpi_i32_f32", "cvt_i16_f16", "cvt_u16_f16", "frexp_mant_f32", "frexp_exp_i32_f32",
              "frexp_mant_f16", "frexp_exp_i16_f16"}
PLAIN = r"[vs]\d+|-?\d+|0x[0-9a-f]{1,8}|-?\d+\.\d+"
MODIFIED = re.compile(r"-[vs]|-?\||-?abs\(")

SALU_HELPERS["mad_legacy32"] = (
    "float mad_legacy32(float a, float b, float c) {\n"
    "    precise float product = (ftz32(a) == 0.0f || ftz32(b) == 0.0f) ? 0.0f : ftz32(ftz32(a) * ftz32(b));\n"
    "    precise float sum = product + ftz32(c);\n"
    "    return ftz32(sum);\n"
    "}"
)


def _merged_16(st, dst, expression, i):
    """A 16-bit result over the kept high half of the destination (zero where it holds no value)."""
    old = st.vector.get(dst)
    if old is not None and tracked_word(old) is None:
        raise ValueError("A 16-bit result keeps the high half of a destination that holds a numeric word")
    high = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
    st.lines.append(f"    uint f16w{i} = {high} | ({expression} & 0xffffu);")
    st.vector[dst] = ("uint", f"f16w{i}")


def _source(st, op, source, token, suffix):
    if suffix == "_e32" and MODIFIED.match(token):
        raise ValueError("Source modifiers need the VOP3 encoding")
    regs = (st.scalar, st.vector, st.pending, st.sample_pending)
    if source == "f32":
        if op not in MODIFIABLE and MODIFIED.match(token):
            raise ValueError("Unsupported source modifier")
        return fp_operand(token, *regs)
    if source == "f16":
        return f16_operand(token, *regs)
    if op in MODIFIABLE and not re.fullmatch(PLAIN, token):  # frexp bit source: sign-bit modifiers
        m = re.fullmatch(r"(-?)(?:\|([^|]+)\||abs\(([^()]+)\)|([^|()]+))", token)
        if not m:
            raise ValueError(f"Unsupported operand {token}")
        negate, bar, call, plain = m.groups()
        body = bar or call or plain
        if not re.fullmatch(r"[vs]\d+", body):
            raise ValueError(f"Unsupported operand {token}")
        word = word_of(body, *regs)
        if bar or call:
            word = f"({word} & 0x7fffffffu)"
        return f"({word} ^ 0x80000000u)" if negate else word
    if not re.fullmatch(PLAIN, token):
        raise ValueError(f"Unsupported operand {token}")
    return word_of(token, *regs)


@form(r"v_(" + "|".join(OPS) + r")(_e32|_e64)? (v\d+), ([^,\s]+)")
def convert(st, i, m):
    op, suffix, dst, token = m.groups()
    kind, source, template, helpers = OWN[op]
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    value = _source(st, op, source, token, suffix)
    st.helpers.update(helpers)
    expression = template.format(value)
    if kind == "u32":
        st.lines.append(f"    uint valu{i} = {expression};")
        st.vector[dst] = ("uint", f"valu{i}")
    elif kind == "f32":
        st.lines.append(f"    precise float alu{i} = {expression};")
        st.vector[dst] = f"alu{i}"
    else:
        _merged_16(st, dst, expression, i)


@form(r"v_(min3|max3|med3)_f16(?:_e64)? (v\d+), ([^,]+), ([^,]+), ([^,]+?)( clamp)?")
def select3_f16(st, i, m):
    # Each result is one of the widened operands (so exact once narrowed), as for the binary32 forms in valu_f32.
    op, dst, *tokens, clamp = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    a, b, c = (f16_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens)
    expression = {"min3": f"min(min({a}, {b}), {c})", "max3": f"max(max({a}, {b}), {c})",
                  "med3": f"med3_f32({a}, {b}, {c})"}[op]
    if op == "med3":
        st.helpers.add("med3_f32")
    if clamp:
        expression = f"saturate({expression})"
    _merged_16(st, dst, f"narrow16({expression})", i)


@form(r"v_(mad|mac)_legacy_f32(_e32|_e64)? (v\d+), (.+?)( clamp)?")
def legacy_mad(st, i, m):
    # D = legacy S0 * S1 + S2 (a zero factor gives zero even against infinity or NaN), unfused and flushing denormals
    # like v_mad_f32 (mad32). v_mad has no e32 encoding; v_mac accumulates into the destination.
    op, suffix, dst, operands, clamp = m.groups()
    tokens = operands.split(", ")
    if op == "mac":
        tokens.append(dst)
    if len(tokens) != 3 or (suffix == "_e32" and (op == "mad" or clamp or any(MODIFIED.match(t) for t in tokens[:2]))):
        raise ValueError("Invalid arithmetic operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    st.helpers.add("mad_legacy32")
    expression = f"mad_legacy32({values[0]}, {values[1]}, {values[2]})"
    if clamp:
        expression = f"saturate({expression})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")
