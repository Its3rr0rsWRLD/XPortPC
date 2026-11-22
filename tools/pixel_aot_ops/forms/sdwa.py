"""SDWA forms: moves, widening, binary32 arithmetic and comparisons with sub-dword selections."""
from ..dispatch import form
from ..registers import LANE_MASK, fp_operand, lane_mask, tracked_word, word_of
from .valu_f32 import ALU
from .vopc import COMPARE

# SDWA selections: (bit offset, width). A source selection is zero-extended, or sign-extended with sext();
# a destination selection writes the low bits of the result into that field. Following the equivalences in
# LLVM's SIPeepholeSDWA, UNUSED_PAD zeroes the other bits and UNUSED_PRESERVE keeps them from the destination.
SDWA_SEL = {"BYTE_0": (0, 8), "BYTE_1": (8, 8), "BYTE_2": (16, 8), "BYTE_3": (24, 8),
            "WORD_0": (0, 16), "WORD_1": (16, 16), "DWORD": (0, 32)}
# Exact arithmetic with SDWA forms on gfx1013 (docs/coverage/gfx1013.tsv).
SDWA_ALU = ("add", "sub", "subrev", "mul", "mul_legacy", "max", "min", "floor", "ceil", "fract", "trunc")


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


@form(r"v_mov_b32_sdwa (v\d+), (sext\()?([vs]\d+|-?\d+(?:\.\d+)?)(\))? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:(BYTE_[0-3]|WORD_[01]|DWORD)")
def move_sdwa(st, i, m):
    dst, sext, src, close, dst_sel, unused, src_sel = m.groups()
    if bool(sext) != bool(close):
        raise ValueError("Invalid register move")
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    word = word_of(src, st.scalar, st.vector, st.pending, st.sample_pending)
    result = sdwa_dest(sdwa_source(word, src_sel, bool(sext)), dst_sel, unused, st.vector.get(dst))
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = asfloat({result});")


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
    if dst_sel != "DWORD":
        expression = f"asfloat({sdwa_dest(f'asuint({expression})', dst_sel, unused, st.vector.get(dst))})"
    st.vector[dst] = f"alu{i}"
    st.lines.append(f"    precise float alu{i} = {expression};")


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
