"""SDWA forms: moves, widening, integer, binary16 and binary32 arithmetic, conversions and comparisons with
sub-dword selections."""
import re

from ..dispatch import form
from ..registers import (LANE_MASK, f16_encoding, fp_operand, lane_mask, tracked_word, vector_u32, word_of)
from .valu_f16 import F16_ALU
from .valu_int import INT_VOP2, int_binary
from .valu_f32 import ALU
from .vopc import COMPARE

# SDWA selections: (bit offset, width). A source selection is zero-extended, or sign-extended with sext();
# a destination selection writes the low bits of the result into that field. Following the equivalences in
# LLVM's SIPeepholeSDWA, UNUSED_PAD zeroes the other bits and UNUSED_PRESERVE keeps them from the destination.
SDWA_SEL = {"BYTE_0": (0, 8), "BYTE_1": (8, 8), "BYTE_2": (16, 8), "BYTE_3": (24, 8),
            "WORD_0": (0, 16), "WORD_1": (16, 16), "DWORD": (0, 32)}
# Exact arithmetic with SDWA forms on gfx1013 (docs/coverage/gfx1013.tsv).
SDWA_ALU = ("add", "sub", "subrev", "mul", "mul_legacy", "max", "min", "floor", "ceil", "fract", "trunc",
            "log", "exp", "rcp", "sqrt", "rsq")


def sdwa_source(word, sel, sext):
    offset, width = SDWA_SEL[sel]
    if width == 32:
        return word
    if sext:
        return f"asuint(asint({word} << {32 - offset - width}u) >> {32 - width}u)"
    return f"(({word} >> {offset}u) & {(1 << width) - 1:#x}u)"


def sdwa_dest(result, sel, unused, old):
    offset, width = SDWA_SEL[sel]
    if width == 32:
        return result
    if unused == "UNUSED_SEXT":
        raise ValueError("UNUSED_SEXT is not lowered")
    field = f"(({result} & {(1 << width) - 1:#x}u) << {offset}u)"
    if unused == "UNUSED_PAD":
        return field
    # The kept bits must come from a tracked numeric value; hardware would keep whatever an untracked register holds.
    kept = tracked_word(old)
    if kept is None:
        raise ValueError("UNUSED_PRESERVE needs a tracked numeric destination")
    keep = ~(((1 << width) - 1) << offset) & 0xffffffff
    return f"(({kept} & {keep:#x}u) | {field})"


def place_float(st, i, dst, expression, dst_sel, unused):
    """Write a binary32 result: a whole dword stays a float; a field is placed in the integer word of the result."""
    if dst_sel == "DWORD":
        st.vector[dst] = f"alu{i}"
        st.lines.append(f"    precise float alu{i} = {expression};")
        return
    st.lines.append(f"    precise float alu{i} = {expression};")
    placed = sdwa_dest(f"asuint(alu{i})", dst_sel, unused, st.vector.get(dst))
    st.lines.append(f"    uint movw{i} = {placed};")
    st.vector[dst] = ("uint", f"movw{i}")


@form(r"v_mov_b32_sdwa (v\d+), (sext\()?([vs]\d+|-?\d+(?:\.\d+)?)(\))? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:(BYTE_[0-3]|WORD_[01]|DWORD)")
def move_sdwa(st, i, m):
    dst, sext, src, close, dst_sel, unused, src_sel = m.groups()
    if bool(sext) != bool(close):
        raise ValueError("Invalid register move")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = word_of(src, st.scalar, st.vector, st.pending, st.sample_pending)
    result = sdwa_dest(sdwa_source(word, src_sel, bool(sext)), dst_sel, unused, st.vector.get(dst))
    st.lines.append(f"    uint movw{i} = {result};")
    st.vector[dst] = ("uint", f"movw{i}")


@form(r"v_cvt_f32_f16_sdwa (v\d+), (-?)(?:\|([vs]\d+)\||([vs]\d+))( clamp)? dst_sel:DWORD dst_unused:UNUSED_(?:PAD|PRESERVE) src0_sel:(WORD_[01])")
def widen_sdwa(st, i, m):
    # The SDWA form widens the selected half; modifiers apply after widening, as in the e64 form.
    dst, negate, bars, plain, clamp, src_sel = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = word_of(bars or plain, st.scalar, st.vector, st.pending, st.sample_pending)
    expression = f"widen16({sdwa_source(word, src_sel, False)})"
    if bars:
        expression = f"abs({expression})"
    if negate:
        expression = f"(-{expression})"
    if clamp:
        expression = f"saturate({expression})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")


@form(rf"v_({'|'.join(SDWA_ALU)})_f32_sdwa (v\d+), (.+?)( clamp)? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:DWORD( src1_sel:DWORD)?")
def arithmetic_sdwa(st, i, m):
    # SDWA forms of exact arithmetic take whole-dword sources, so the binary32 denormal mode never applies
    # to a zero-extended field; the result is placed like an SDWA move.
    op, dst, operands, clamp, dst_sel, unused, src1_sel = m.groups()
    tokens = operands.split(", ")
    arity, template = ALU[op]
    if len(tokens) != arity or bool(src1_sel) != (arity == 2):
        raise ValueError("Invalid arithmetic operation")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    expression = template.format(*[fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens])
    if clamp:
        expression = f"saturate({expression})"
    place_float(st, i, dst, expression, dst_sel, unused)


@form(rf"v_cmp_({'|'.join(COMPARE)})_f32_sdwa {LANE_MASK}, ([^,]+), ([^,]+) src0_sel:DWORD src1_sel:DWORD")
def compare_sdwa(st, i, m):
    # With whole-dword selections the SDWA comparison is the e32/e64 one; byte and word selections
    # would compare zero-extended fields as binary32 and are refused.
    op, dst, *tokens = m.groups()
    regs = lane_mask(dst)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid comparison")
    values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.lines.append(f"    bool cmp{i} = {COMPARE[op].format(*values)};")


# More SDWA forms, for the operations whose e32 form is lowered elsewhere (valu_int, valu_f16, valu_f32, vopc).
# The selectors are the only new semantics:
# - a source selection extracts a field of the register word, zero-extended or, written sext(), sign-extended, before
#   the operation; abs and neg of a binary16 source act on bit 15 of the selected 16 bits;
# - an inline constant or literal source has no field and takes only DWORD;
# - integer results are placed by sdwa_dest and stay uint words (movw), never float-typed HLSL;
# - a binary16 result is 16 bits: BYTE_n and WORD_n select where its low bits go, while DWORD (what the other 16 bits
#   would hold) is not established and is refused; binary32 sources of arithmetic take DWORD only, as above.
SEL = "BYTE_[0-3]|WORD_[01]|DWORD"
DST_FIELDS = rf" dst_sel:({SEL}) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE)"
SRC0 = rf" src0_sel:({SEL})"
SRC1 = rf" src1_sel:({SEL})"
SDWA_BITWISE = {
    "and_b32": "({a} & {b})", "or_b32": "({a} | {b})", "xor_b32": "({a} ^ {b})", "xnor_b32": "(~({a} ^ {b}))",
    "lshlrev_b32": "({b} << ({a} & 31u))", "lshrrev_b32": "({b} >> ({a} & 31u))",
    "ashrrev_i32": "asuint(asint({b}) >> ({a} & 31u))",
}
SDWA_F16 = ("add", "subrev", "mul", "min", "floor", "fract", "trunc", "ldexp")


def source_parts(token, sel, allow_sext=True):
    """(register, sext) of a field source, or (token, False) for a constant, which only has a whole-dword selection."""
    if match := re.fullmatch(r"sext\(([vs]\d+)\)", token):
        if not allow_sext:
            raise ValueError("sext is not valid on a floating-point source")
        return match.group(1), True
    if re.fullmatch(r"[vs]\d+", token):
        return token, False
    if sel != "DWORD":
        raise ValueError("A constant source has no sub-dword selection")
    if not re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", token):
        raise ValueError(f"An integer source takes an integer constant, not {token}")
    return token, False


def int_source(st, token, sel):
    """The selected field of an integer source as a uint word."""
    register, sext = source_parts(token, sel)
    word = vector_u32(register, st.scalar, st.vector, st.pending, st.sample_pending)
    return sdwa_source(word, sel, sext)


def f16_source(st, token, sel):
    """The binary16 encoding (16 bits) of a selected source, after abs and neg."""
    body = re.fullmatch(r"(-?)(?:\|([vs]\d+)\||([vs]\d+))", token)
    if body is None:
        if sel != "DWORD":
            raise ValueError("A constant source has no sub-dword selection")
        return f16_encoding(token, st.scalar, st.vector, st.pending, st.sample_pending)
    negate, bars, plain = body.groups()
    word = word_of(bars or plain, st.scalar, st.vector, st.pending, st.sample_pending)
    bits = f"({sdwa_source(word, sel, False)} & 0xffffu)"
    if bars:
        bits = f"({bits} & 0x7fffu)"
    if negate:
        bits = f"({bits} ^ 0x8000u)"
    return bits


def place_word(st, i, dst, expression, dst_sel, unused):
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    st.lines.append(f"    uint movw{i} = {sdwa_dest(expression, dst_sel, unused, st.vector.get(dst))};")
    st.vector[dst] = ("uint", f"movw{i}")


@form(rf"v_({'|'.join(INT_VOP2)}|{'|'.join(SDWA_BITWISE)})_sdwa (v\d+), ([^,\s]+), ([^,\s]+){DST_FIELDS}{SRC0}{SRC1}")
def integer_sdwa(st, i, m):
    op, dst, first, second, dst_sel, unused, sel0, sel1 = m.groups()
    a = int_source(st, first, sel0)
    b = int_source(st, second, sel1)
    expression = SDWA_BITWISE[op].format(a=a, b=b) if op in SDWA_BITWISE else int_binary(op, a, b, False, st.helpers)
    place_word(st, i, dst, expression, dst_sel, unused)


@form(rf"v_(not_b32|bfrev_b32)_sdwa (v\d+), ([^,\s]+){DST_FIELDS}{SRC0}")
def integer_unary_sdwa(st, i, m):
    op, dst, src, dst_sel, unused, sel = m.groups()
    word = int_source(st, src, sel)
    place_word(st, i, dst, f"{'~' if op == 'not_b32' else 'reversebits'}({word})", dst_sel, unused)


@form(rf"v_cvt_f32_ubyte([0-3])_sdwa (v\d+), ([^,\s]+){DST_FIELDS}{SRC0}")
def ubyte_sdwa(st, i, m):
    byte, dst, src, dst_sel, unused, sel = m.groups()
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    place_float(st, i, dst, f"float(({int_source(st, src, sel)} >> {8 * int(byte)}u) & 255u)", dst_sel, unused)


def f16_result(st, op, tokens, sels, clamp):
    """The binary16 encoding of an arithmetic result on selected sources (the e32/e64 lowering of valu_f16)."""
    values = [f"widen16({f16_source(st, t, sel)})" for t, sel in zip(tokens[:1 if op == "ldexp" else len(tokens)], sels)]
    if op == "fract":
        encoding = f"fract16({values[0]})"
        return f"narrow16(saturate(widen16({encoding})))" if clamp else encoding
    if op == "ldexp":
        exponent = int_source(st, tokens[1], sels[1])
        expression = f"ldexp16({values[0]}, ((int({exponent} & 0xffffu) ^ 0x8000) - 0x8000))"
    else:
        expression = F16_ALU[op][1].format(*values)
    return f"narrow16({f'saturate({expression})' if clamp else expression})"


@form(rf"v_({'|'.join(SDWA_F16)})_f16_sdwa (v\d+), (.+?)( clamp)?{DST_FIELDS}{SRC0}(?:{SRC1})?")
def arithmetic_f16_sdwa(st, i, m):
    op, dst, operands, clamp, dst_sel, unused, sel0, sel1 = m.groups()
    tokens = operands.split(", ")
    unary = op in ("floor", "fract", "trunc")
    if len(tokens) != (1 if unary else 2) or bool(sel1) == unary or dst_sel == "DWORD":
        raise ValueError("Invalid binary16 SDWA operation")
    encoding = f16_result(st, op, tokens, (sel0, sel1), bool(clamp))
    place_word(st, i, dst, encoding, dst_sel, unused)


@form(rf"v_cvt_f16_f32_sdwa (v\d+), ([^,\s]+){DST_FIELDS} src0_sel:DWORD")
def narrow_sdwa(st, i, m):
    dst, src, dst_sel, unused = m.groups()
    if dst_sel == "DWORD":
        raise ValueError("A 16-bit result has no whole-dword placement")
    value = fp_operand(src, st.scalar, st.vector, st.pending, st.sample_pending)
    place_word(st, i, dst, f"narrow16({value})", dst_sel, unused)


@form(r"v_cvt_pkrtz_f16_f32_sdwa (v\d+), ([^,\s]+), ([^,\s]+) dst_sel:DWORD dst_unused:UNUSED_(?:PAD|PRESERVE) src0_sel:DWORD src1_sel:DWORD")
def pack_sdwa(st, i, m):
    # The whole-dword form is the e64 pack: the packed halves are never selected or modified.
    dst, *tokens = m.groups()
    if st.ex != "true" or st.sample_pending or dst in st.sample_dest:
        raise ValueError("Unsupported pack operand")
    pair = []
    for n, token in enumerate(tokens):
        for register in re.findall(r"[vs]\d+", token):
            if tracked_word((st.vector if register.startswith("v") else st.scalar).get(register)) is None:
                raise ValueError(f"Unsupported pack operand {register}")
        st.lines.append(f"    precise float alu{i}_{n} = {fp_operand(token, st.scalar, st.vector, st.pending, st.sample_pending)};")
        pair.append(f"alu{i}_{n}")
    st.vector[dst] = tuple(pair)


def set_condition(st, i, dst):
    regs = lane_mask(dst)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid comparison")
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))


@form(rf"v_cmp_({'|'.join(COMPARE)})_f16_sdwa {LANE_MASK}, ([^,]+), ([^,]+) src0_sel:({SEL}) src1_sel:({SEL})")
def compare_f16_sdwa(st, i, m):
    # The selected 16 bits of each source are widened (exactly) and compared as in the e32 form.
    op, dst, first, second, sel0, sel1 = m.groups()
    values = [f"widen16({f16_source(st, t, sel)})" for t, sel in ((first, sel0), (second, sel1))]
    set_condition(st, i, dst)
    st.lines.append(f"    precise float cmpa{i} = {values[0]};")
    st.lines.append(f"    precise float cmpb{i} = {values[1]};")
    st.lines.append(f"    bool cmp{i} = {COMPARE[op].format(f'cmpa{i}', f'cmpb{i}')};")


@form(rf"v_cmp_class_f(16|32)_sdwa {LANE_MASK}, ([^,]+), ([^,]+) src0_sel:({SEL}) src1_sel:({SEL})")
def class_sdwa(st, i, m):
    # The class mask is an integer source with its own selection. A binary32 value has no field to select (as for the
    # arithmetic above); a binary16 value is its selected 16 bits.
    width, dst, value, classes, sel0, sel1 = m.groups()
    if width == "32":
        if sel0 != "DWORD":
            raise ValueError("A binary32 class source takes DWORD only")
        test = f"class32({fp_operand(value, st.scalar, st.vector, st.pending, st.sample_pending)})"
    else:
        test = f"class16({f16_source(st, value, sel0)})"
    mask = int_source(st, classes, sel1)
    set_condition(st, i, dst)
    st.lines.append(f"    bool cmp{i} = ({test} & {mask}) != 0u;")
