"""VOPC: comparisons and class tests that write a lane mask, and v_cndmask_b32, which reads one."""
import re

from ..dispatch import form
from ..registers import (LANE_MASK, f16_encoding, f16_operand, fp_operand, lane_mask, raw_source, vector_u32,
                         word_of)

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


@form(rf"v_cmp_class_f32(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def class_f32(st, i, m):
    dst, value, classes = m.groups()
    regs = lane_mask(dst)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid comparison")
    if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
        bits = f"{int(classes, 0) & 0xffffffff}u"
    elif re.fullmatch(r"[vs]\d+", classes):
        bits = word_of(classes, st.scalar, st.vector, st.pending, st.sample_pending)
    else:
        raise ValueError("Unsupported class mask")
    operand = fp_operand(value, st.scalar, st.vector, st.pending, st.sample_pending)
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.lines.append(f"    bool cmp{i} = (class32({operand}) & {bits}) != 0u;")


@form(rf"v_cmp_class_f16(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def class_f16(st, i, m):
    # The class is read from the binary16 encoding itself (class16). The class mask is a 32-bit integer
    # source, not a binary16 value, so a float constant there is refused.
    dst, value, classes = m.groups()
    regs = lane_mask(dst)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid comparison")
    if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
        bits = f"{int(classes, 0) & 0xffffffff}u"
    elif re.fullmatch(r"[vs]\d+", classes):
        bits = vector_u32(classes, st.scalar, st.vector, st.pending, st.sample_pending)
    else:
        raise ValueError("Unsupported class mask")
    operand = f16_encoding(value, st.scalar, st.vector, st.pending, st.sample_pending)
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.lines.append(f"    bool cmp{i} = (class16({operand}) & {bits}) != 0u;")


@form(rf"v_cmp_({'|'.join(COMPARE)})_f16(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def compare_f16(st, i, m):
    # Both sources are widened from their low halves. Widening binary16 to binary32 is exact (including
    # subnormals, infinities and the NaN-ness of the operands), so every comparison of the widened values
    # in binary32 gives the binary16 result, and the f32 predicate table applies unchanged.
    op, dst, *tokens = m.groups()
    regs = lane_mask(dst)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid comparison")
    values = [f16_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.lines.append(f"    precise float cmpa{i} = {values[0]};")
    st.lines.append(f"    precise float cmpb{i} = {values[1]};")
    st.lines.append(f"    bool cmp{i} = {COMPARE[op].format(f'cmpa{i}', f'cmpb{i}')};")


@form(rf"v_cmp_({'|'.join(COMPARE)})_f32(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)")
def compare_f32(st, i, m):
    op, dst, *tokens = m.groups()
    regs = lane_mask(dst)
    if st.ex != "true" or st.pending.intersection(regs):
        raise ValueError("Invalid comparison")
    values = [fp_operand(t, st.scalar, st.vector, st.pending, st.sample_pending) for t in tokens]
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
    st.lines.append(f"    bool cmp{i} = {COMPARE[op].format(*values)};")


@form(rf"v_cndmask_b32(?:_e32|_e64)? (v\d+), ([^,]+), ([^,]+), {LANE_MASK}")
def select(st, i, m):
    dst, unset, chosen, source = m.groups()
    regs = lane_mask(source)
    condition = st.scalar.get(regs[0])
    if (st.pending.intersection(regs) or not isinstance(condition, tuple)
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
