"""SOPK scalar arithmetic: s_addk_i32 and s_mulk_i32, the s_cmpk_* comparisons and s_cmovk_i32. (s_movk_i32 is in sop1.)

Semantics: AMD RDNA 2 ISA guide, SOPK pseudocode. The 16-bit immediate is sign-extended and the operation reads and
writes the same SGPR: s_addk_i32 gives D + simm16 modulo 2^32 and sets SCC when the signed 32-bit add overflows,
s_mulk_i32 gives D * simm16 modulo 2^32 and leaves SCC alone. llvm-mc prints the immediate as 0x0 to 0xffff; the
decimal -32768 to 65535 is read the same way. The destination must already hold a numeric word, and every value is an
unsigned word (registers.scalar_u32), so no float type ever holds these bits.

Ported from R0Y00/Xbox2Windows#333 by wh1skrzzz (the two operations and the signed-overflow SCC), moved to the
("uint", expr) register model: a params[] constant is read as the word it is, and a pending load, an unset register
and a vector destination are refused.
"""
from ..dispatch import form
from ..registers import scalar_u32, sgpr_name


def simm16(token):
    value = int(token, 16) if token.startswith("0x") else int(token)
    if not (-0x8000 <= value <= 0xffff if not token.startswith("0x") else 0 <= value <= 0xffff):
        raise ValueError("Invalid sopk immediate")
    return (value - 0x10000 if 0x8000 <= value <= 0xffff else value) & 0xffffffff


@form(r"(s_addk_i32|s_mulk_i32) (s\d+), (-?\d+|0x[0-9a-f]{1,4})")
def sopk_arithmetic(st, i, m):
    op, dst, token = m.groups()
    sgpr_name(dst)
    if dst in st.pending:
        raise ValueError("Write overlaps an outstanding scalar load")
    if dst not in st.scalar:
        raise ValueError(f"Read of unset scalar register {dst}")
    old = scalar_u32(dst, st.scalar, st.pending)
    immediate = simm16(token)
    if op == "s_addk_i32":
        st.lines.append(f"    uint sopk{i}_old = {old};")
        st.lines.append(f"    uint sopk{i} = sopk{i}_old + {immediate}u;")
        st.scc = f"(((sopk{i}_old ^ sopk{i}) & ({immediate}u ^ sopk{i}) & 0x80000000u) != 0u)"
    else:
        st.lines.append(f"    uint sopk{i} = {old} * {immediate}u;")
    st.scalar[dst] = ("uint", f"sopk{i}")


# s_cmpk_<rel>_i32 compares D with the sign-extended simm16, s_cmpk_<rel>_u32 with the zero-extended one (so
# 0..65535 only; a negative decimal is refused). D is only read. s_cmovk_i32 writes the sign-extended simm16 into D when
# SCC is set and keeps D otherwise. Neither the compare nor the move touches anything but SCC and D.
CMPK = {"eq": "==", "lg": "!=", "gt": ">", "ge": ">=", "lt": "<", "le": "<="}


@form(rf"s_cmpk_({'|'.join(CMPK)})_(i32|u32) (s\d+), (-?\d+|0x[0-9a-f]{{1,4}})")
def sopk_compare(st, i, m):
    relation, kind, src, token = m.groups()
    sgpr_name(src)
    if src not in st.scalar:
        raise ValueError(f"Read of unset scalar register {src}")
    value = scalar_u32(src, st.scalar, st.pending)
    if kind == "u32":
        if token.startswith("-"):
            raise ValueError("Invalid sopk immediate")
        left, right = value, f"{simm16(token) & 0xffff}u"
    else:
        left, right = value, f"{simm16(token)}u"
        if relation not in ("eq", "lg"):
            left, right = f"asint({left})", f"asint({right})"
    st.scc = f"({left} {CMPK[relation]} {right})"


@form(r"s_cmovk_i32 (s\d+), (-?\d+|0x[0-9a-f]{1,4})")
def sopk_cmov(st, i, m):
    dst, token = m.groups()
    sgpr_name(dst)
    if dst in st.pending:
        raise ValueError("Write overlaps an outstanding scalar load")
    if st.scc is None:
        raise ValueError("Conditional move requires a tracked SCC")
    old = scalar_u32(dst, st.scalar, st.pending)
    st.lines.append(f"    uint sopk{i} = {st.scc} ? {simm16(token)}u : {old};")
    st.scalar[dst] = ("uint", f"sopk{i}")
