"""VOPC: comparisons and class tests that write a lane mask, and v_cndmask_b32, which reads one."""
import re

from ..dispatch import form
from ..registers import (LANE_MASK, f16_bits, f16_encoding, f16_operand, fp_operand, lane_mask, raw_source,
                         vector_u32, word_of)

# N-prefixed predicates include unordered operands. Keep NLG's NaN case explicit in DXIL.
COMPARE = {
    "f": "false", "tru": "true",
    "lt": "{0} < {1}", "eq": "{0} == {1}", "le": "{0} <= {1}", "gt": "{0} > {1}",
    "lg": "({0} < {1} || {0} > {1})", "ge": "{0} >= {1}",
    "o": "({0} == {0} && {1} == {1})", "u": "({0} != {0} || {1} != {1})",
    "nge": "({0} < {1} || isnan({0}) || isnan({1}))", "nlg": "({0} == {1} || isnan({0}) || isnan({1}))",
    "ngt": "({0} <= {1} || isnan({0}) || isnan({1}))", "nle": "({0} > {1} || isnan({0}) || isnan({1}))",
    "neq": "!({0} == {1})", "nlt": "({0} >= {1} || isnan({0}) || isnan({1}))",
}


def _class_bits(st, classes, reader):
    if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
        return f"{int(classes, 0) & 0xffffffff}u"
    if re.fullmatch(r"[vs]\d+", classes):
        return reader(classes, st.scalar, st.vector, st.pending, st.sample_pending)
    raise ValueError("Unsupported class mask")


def class_f32_relation(st, i, value, classes):
    bits = _class_bits(st, classes, word_of)
    # The class test is exact on every encoding, a subnormal included: abs and neg act on the sign bit of the word, never
    # through a float negate or abs, which a device may flush (a negated subnormal then reads as zero).
    modified = re.fullmatch(r"(-?)(?:abs\(([^()|]+)\)|\|([^()|]+)\|)", value) or re.fullmatch(r"(-)()([vs]\d+)", value)
    if modified:
        neg, inner = modified.group(1), modified.group(2) or modified.group(3)
        if inner.startswith("-") and not re.fullmatch(r"-\d+(?:\.\d+)?", inner):
            raise ValueError(f"Malformed modifier {value}")
        word = f"asuint({fp_operand(inner, st.scalar, st.vector, st.pending, st.sample_pending)})"
        if modified.group(2) or "|" in value:
            word = f"({word} & 0x7fffffffu)"
        if neg:
            word = f"({word} ^ 0x80000000u)"
        operand = f"asfloat({word})"
    else:
        operand = fp_operand(value, st.scalar, st.vector, st.pending, st.sample_pending)
    return f"(class32({operand}) & {bits}) != 0u"


def class_f16_relation(st, i, value, classes):
    # The class is read from the binary16 encoding itself (class16). The class mask is a 32-bit integer
    # source, not a binary16 value, so a float constant there is refused.
    bits = _class_bits(st, classes, vector_u32)
    operand = f16_encoding(value, st.scalar, st.vector, st.pending, st.sample_pending)
    return f"(class16({operand}) & {bits}) != 0u"


def f16_relation(st, i, op, tokens):
    # Both sources are widened from their low halves. Widening binary16 to binary32 is exact (including
    # subnormals, infinities and the NaN-ness of the operands), so every comparison of the widened values
    # in binary32 gives the binary16 result, and the f32 predicate table applies unchanged.
    values = [f16_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    st.lines.append(f"    precise float cmpa{i} = {values[0]};")
    st.lines.append(f"    precise float cmpb{i} = {values[1]};")
    return COMPARE[op].format(f"cmpa{i}", f"cmpb{i}")


def f32_relation(st, i, op, tokens):
    values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    return COMPARE[op].format(*values)


# Integer comparisons (V_CMP_{EQ,NE,LT,LE,GT,GE}_{I32,U32}, VOPC and their VOP3 e64 forms): the signed or unsigned
# order of the two words, written per lane to the lane mask like the float comparisons. llvm-mc refuses source
# modifiers and clamp on them. V_CMP_F and V_CMP_T (always false, always true; from R0Y00/Xbox2Windows#306 by
# Alexander) still read and check both sources.
INT_COMPARE = {"f": None, "eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "t": None}


def int_relation(st, i, op, kind, tokens):
    words = [vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    if kind == "i32":
        words = [f"asint({w})" for w in words]
    return {"f": "false", "t": "true"}.get(op) or f"{words[0]} {INT_COMPARE[op]} {words[1]}"


# 16-bit integer comparisons (V_CMP_{EQ,NE,LT,LE,GT,GE}_{I16,U16}, VOPC and VOP3 e64): both sources are the low 16
# bits of their words (a register's low half, an inline constant or a literal's low half; bits 16..31 never take
# part). i16 sign-extends the low half, u16 zero-extends it. There are no F and T forms for 16-bit integers, no
# source modifiers and no clamp.
INT16_COMPARE = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}


def int16_relation(st, i, op, kind, tokens):
    if any("." in t for t in tokens):
        raise ValueError("A float constant is not a 16-bit integer source")
    words = [f16_bits(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    if kind == "i16":
        words = [f"((int({w}) ^ 0x8000) - 0x8000)" for w in words]
    return f"{words[0]} {INT16_COMPARE[op]} {words[1]}"


def write_compare(st, i, dst, relation):
    """VOPC writes this lane's bit of the destination mask: the relation while the lane is active, 0 while it is not
    (docs/design/control-flow.md, CF-2 section 3: D = ex && cmp)."""
    regs = lane_mask(dst)
    if st.pending.intersection(regs):
        raise ValueError("Invalid comparison")
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.lines.append(f"    bool cmp{i} = {relation if st.ex == 'true' else f'{st.ex} && ({relation})'};")
    st.compares[f"cmp{i}"] = (relation, len(st.lines), st.ex)


def compare_exec(st, i, relation):
    """V_CMPX on gfx10 writes EXEC only (no VCC or SGPR destination): EXEC &= the compare, so an inactive lane stays
    inactive and an active one stays active where the relation holds."""
    st.lines.append(f"    bool cmp{i} = {relation};")
    st.exec_and(i, f"cmp{i}")


def _pending_check(st, dst):
    if st.pending.intersection(lane_mask(dst)):
        raise ValueError("Invalid comparison")


@form(rf"v_cmp_class_f32(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def class_f32(st, i, m):
    dst, value, classes = m.groups()
    _pending_check(st, dst)
    write_compare(st, i, dst, class_f32_relation(st, i, value, classes))


@form(rf"v_cmp_class_f16(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def class_f16(st, i, m):
    dst, value, classes = m.groups()
    _pending_check(st, dst)
    write_compare(st, i, dst, class_f16_relation(st, i, value, classes))


@form(rf"v_cmp_({'|'.join(COMPARE)})_f16(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def compare_f16(st, i, m):
    op, dst, *tokens = m.groups()
    _pending_check(st, dst)
    write_compare(st, i, dst, f16_relation(st, i, op, tokens))


@form(rf"v_cmp_({'|'.join(COMPARE)})_f32(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def compare_f32(st, i, m):
    op, dst, *tokens = m.groups()
    _pending_check(st, dst)
    write_compare(st, i, dst, f32_relation(st, i, op, tokens))


@form(rf"v_cmp_({'|'.join(INT_COMPARE)})_(i32|u32)(?:_e32|_e64)? {LANE_MASK}, ([^,\s]+), ([^,\s]+)")
def compare_int(st, i, m):
    op, kind, dst, *tokens = m.groups()
    _pending_check(st, dst)
    write_compare(st, i, dst, int_relation(st, i, op, kind, tokens))


@form(rf"v_cmp_({'|'.join(INT16_COMPARE)})_(i16|u16)(?:_e32|_e64)? {LANE_MASK}, ([^,\s]+), ([^,\s]+)")
def compare_int16(st, i, m):
    op, kind, dst, *tokens = m.groups()
    _pending_check(st, dst)
    write_compare(st, i, dst, int16_relation(st, i, op, kind, tokens))


# V_CMPX (CF-2b): the same relations, into EXEC. gfx10 encodes no destination in either the VOPC or the VOP3 form, so
# a text with a first operand that is a lane mask is not a v_cmpx of this target and does not match.
@form(r"v_cmpx_class_f32(?:_e32|_e64)? ([^,]+), ([^,]+)")
def cmpx_class_f32(st, i, m):
    compare_exec(st, i, class_f32_relation(st, i, *m.groups()))


@form(r"v_cmpx_class_f16(?:_e32|_e64)? ([^,]+), ([^,]+)")
def cmpx_class_f16(st, i, m):
    compare_exec(st, i, class_f16_relation(st, i, *m.groups()))


@form(rf"v_cmpx_({'|'.join(COMPARE)})_f16(?:_e32|_e64)? ([^,]+), ([^,]+)")
def cmpx_f16(st, i, m):
    op, *tokens = m.groups()
    compare_exec(st, i, f16_relation(st, i, op, tokens))


@form(rf"v_cmpx_({'|'.join(COMPARE)})_f32(?:_e32|_e64)? ([^,]+), ([^,]+)")
def cmpx_f32(st, i, m):
    op, *tokens = m.groups()
    compare_exec(st, i, f32_relation(st, i, op, tokens))


@form(rf"v_cmpx_({'|'.join(INT_COMPARE)})_(i32|u32)(?:_e32|_e64)? ([^,\s]+), ([^,\s]+)")
def cmpx_int(st, i, m):
    op, kind, *tokens = m.groups()
    compare_exec(st, i, int_relation(st, i, op, kind, tokens))


@form(rf"v_cmpx_({'|'.join(INT16_COMPARE)})_(i16|u16)(?:_e32|_e64)? ([^,\s]+), ([^,\s]+)")
def cmpx_int16(st, i, m):
    op, kind, *tokens = m.groups()
    compare_exec(st, i, int16_relation(st, i, op, kind, tokens))


@form(rf"v_cndmask_b32(?:_e32|_e64)? (v\d+), ([^,]+), ([^,]+), {LANE_MASK}")
def select(st, i, m):
    dst, unset, chosen, source = m.groups()
    regs = lane_mask(source)
    condition = st.scalar.get(regs[0])
    bits = {getattr(st.scalar.get(r), "bit", None) for r in regs}
    if len(bits) == 1 and None not in bits and not st.pending.intersection(regs):
        # The uniform mask of s_cselect_b64 D, -1, 0 (exec_mask.UniformMask): the same bit for every lane.
        condition = ("condition", bits.pop(), 0, len(regs))
    elif (st.pending.intersection(regs) or not isinstance(condition, tuple)
            or condition[0] != "condition"
            or [st.scalar.get(r) for r in regs] != [(*condition[:2], j, len(regs)) for j in range(len(regs))]):
        raise ValueError("Select mask is not a tracked comparison")
    plain = r"[vs]\d+|-?\d+|0x[0-9a-f]{1,8}|-?\d+\.\d+"
    if (all(re.fullmatch(plain, t) for t in (chosen, unset))
            and any(raw_source(t, st.scalar, st.vector) for t in (chosen, unset))):
        # A select with a raw-word source picks between unsigned words, never between floats.
        words = [vector_u32(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (chosen, unset)]
        st.lines.append(f"    uint selw{i} = {condition[1]} ? {words[0]} : {words[1]};")
        st.vector[dst] = ("uint", f"selw{i}")
    else:
        values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in (chosen, unset)]
        st.vector[dst] = f"alu{i}"
        st.lines.append(f"    precise float alu{i} = {condition[1]} ? {values[0]} : {values[1]};")
