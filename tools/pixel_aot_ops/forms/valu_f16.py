"""Binary16 vector forms: widening and narrowing conversions and arithmetic."""
import re

from ..dispatch import form
from ..registers import f16_exponent, f16_operand, fp_operand, tracked_word, word_of

# Binary16 arithmetic on widened operands. Each operation is computed once in binary32 and narrowed once with
# narrow16. That equals rounding the exact result straight to binary16 for add, sub, mul, min, max, floor, ceil,
# trunc, rndne, fract and ldexp: binary32 has p' = 24 significant bits and binary16 has p = 11, and p' >= 2p + 2
# makes the double rounding innocuous for + - * (Figueroa), while the others are exact in binary32. round() is the
# round-half-even of DXIL.
F16_ALU = {
    "add": (2, "({0} + {1})"), "sub": (2, "({0} - {1})"), "subrev": (2, "({1} - {0})"), "mul": (2, "({0} * {1})"),
    "max": (2, "max({0}, {1})"), "min": (2, "min({0}, {1})"),
    "floor": (1, "floor({0})"), "ceil": (1, "ceil({0})"), "trunc": (1, "trunc({0})"), "rndne": (1, "round({0})"),
}


@form(r"v_cvt_f32_f16(?:_e32|_e64)? (v\d+), (-?)(?:\|([vs]\d+|0x[0-9a-f]{1,8}|\d+)\||abs\(([vs]\d+|0x[0-9a-f]{1,8}|\d+)\)|([vs]\d+|0x[0-9a-f]{1,8}|\d+))( clamp)?")
def widen(st, i, m):
    dst, negate, bars, call, plain, clamp = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    source = bars or call or plain
    if re.fullmatch(r"0x[0-9a-f]{1,8}|\d+", source):
        word = f"{int(source, 0) & 0xffffffff}u"
    else:
        word = word_of(source, st.scalar, st.vector, st.pending, st.sample_pending)
    expression = f"widen16({word})"
    if bars or call:
        expression = f"abs({expression})"
    if negate:
        expression = f"(-{expression})"
    if clamp:
        expression = f"saturate({expression})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")


@form(r"v_cvt_f16_f32(?:_e32|_e64)? (v\d+), ([^,\s]+)")
def narrow(st, i, m):
    # GFX10 16-bit results replace only the low half; the high half of the destination is kept
    # (LLVM GCNSubtarget::zeroesHigh16BitsOfDest). A destination with no tracked value contributes zero.
    dst, src = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    old = st.vector.get(dst)
    if old is not None and tracked_word(old) is None:
        raise ValueError("Unsupported conversion destination")
    # fp_operand reads modifiers and inline constants, so -1 stays the bit pattern 0xffffffff.
    value = fp_operand(src, st.scalar, st.vector, st.pending, st.sample_pending)
    high = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = asfloat({high} | narrow16({value}));")


@form(r"v_(add|sub|subrev|mul|max|min|ldexp|floor|ceil|trunc|rndne|fract)_f16(?:_(e32|e64))? (v\d+), (.+?)( clamp)?")
def arithmetic_f16(st, i, m):
    # Binary16 arithmetic. The result replaces only the low half of the destination, as for
    # v_cvt_f16_f32. Min and max take HLSL min/max, the NaN convention of the binary32 forms. Output
    # modifiers, op_sel and any other trailing text fail in the operand grammar. A clamp saturates the
    # binary32 value before narrowing, the same as saturating the binary16 result because 0 and 1 are exact.
    op, form, dst, operands, clamp = m.groups()
    tokens = operands.split(", ")
    if len(tokens) != (1 if op in ("floor", "ceil", "trunc", "rndne", "fract") else 2):
        raise ValueError("Invalid arithmetic operation")
    if clamp and form != "e64":
        raise ValueError("Invalid arithmetic operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    old = st.vector.get(dst)
    if old is not None and tracked_word(old) is None:
        raise ValueError("Unsupported arithmetic destination")
    values = [f16_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens[:1 if op == "ldexp" else len(tokens)]]
    if op == "fract":
        encoding = f"fract16({values[0]})"
        if clamp:
            encoding = f"narrow16(saturate(widen16({encoding})))"
    else:
        if op == "ldexp":
            exponent = f16_exponent(tokens[1], st.scalar, st.vector, st.pending, st.sample_pending)
            expression = f"ldexp16({values[0]}, {exponent})"
        else:
            expression = F16_ALU[op][1].format(*values)
        encoding = f"narrow16({f'saturate({expression})' if clamp else expression})"
    high = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = asfloat({high} | {encoding});")
