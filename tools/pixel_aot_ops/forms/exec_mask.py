"""The execution mask: saving EXEC, whole-quad mode, the restore that ends it, and (CF-2b) the straight-line EXEC
algebra: lane-mask moves, SOP2 mask operations that write EXEC or VCC, and the ten *_saveexec_b64 forms. EXEC is this
lane's bit `st.ex` (docs/design/control-flow.md, CF-2 sections 2 and 3); a saved mask is a lane mask like a
compare's, `("condition", bit, j, width)`, and a lane needs only its own bit, so a 64-bit mask is one bool.

A mask operation also writes SCC = (D != 0), a question about the whole wave that one lane cannot answer: it is lane
local and left untracked (`st.scc = None`), so that a select, a carry or a branch on it is refused (CF-2c lowers the
branch idioms on it)."""
import re

from ..dispatch import form
from ..registers import registers


class Saved(tuple):
    """A lane mask saved from EXEC: compares equal to the plain ("condition", bit, j, 2) tuple (so the HLSL and every
    join comparison are unchanged) and remembers whether the wave was in whole-quad mode when it was saved, which a
    restore of it brings back."""

    def __new__(cls, value, wqm):
        self = super().__new__(cls, value)
        self.wqm = wqm
        return self


class UniformMask(tuple):
    """A ("uint", word) half of a 64-bit scalar that holds 0 or all ones (s_cselect_b64 D, -1, 0 and its variants):
    data for every reader as before, and also a lane mask whose bit, the same for every lane, is `bit`."""

    def __new__(cls, value, bit):
        self = super().__new__(cls, value)
        self.bit = bit
        return self


def _pair(token):
    if not (m := re.fullmatch(r"s\[(\d+):(\d+)\]", token)):
        return None
    regs = registers(*m.groups(), 2)
    if regs.start % 2 or regs.stop - 1 > 105:
        raise ValueError(f"Invalid 64-bit scalar register pair: {token}")
    return [f"s{n}" for n in regs]


def mask_bit(st, token):
    """This lane's bit of a 64-bit mask operand as a bool expression, or None when the operand is not a lane mask
    (data, or a register that holds data). Constants 0 and -1 are the uniform masks false and true."""
    if token == "exec":
        return st.ex
    if token == "0":
        return "false"
    if token == "-1":
        return "true"
    if token == "vcc":
        value = st.scalar.get("vcc")
        if "vcc" in st.pending:
            raise ValueError("Lane mask read before load completion")
        return value[1] if isinstance(value, tuple) and value[:1] == ("condition",) and value[2:] == (0, 1) else None
    regs = _pair(token)
    if regs is None:
        return None
    if st.pending.intersection(regs):
        raise ValueError("Lane mask read before load completion")
    values = [st.scalar.get(r) for r in regs]
    if (isinstance(values[0], tuple) and values[0][:1] == ("condition",)
            and values == [("condition", values[0][1], j, 2) for j in range(2)]):
        return values[0][1]
    if isinstance(values[0], tuple) and values[0][:1] == ("condition",) and values[0][2:] == (0, 1):
        # A wave32 compare's mask in the low half (a VOP3 compare names one SGPR there): the lanes of a wave32 wave
        # read their bits from it, and no lane reads the high half.
        return values[0][1]
    if all(isinstance(v, UniformMask) for v in values) and values[0].bit == values[1].bit:
        return values[0].bit
    if values in ([0, 0], [0xffffffff, 0xffffffff]):
        return "true" if values[0] else "false"
    return None


def is_mask(st, token):
    """A source that only a lane mask can be: EXEC or a register pair (or VCC) holding a compare's or a saved mask.
    Constants and uniform data masks alone keep the data form of an operation."""
    if token == "exec":
        return True
    bit = mask_bit(st, token)
    if bit is None or token in ("0", "-1"):
        return False
    regs = _pair(token) or ["vcc"]
    return not isinstance(st.scalar.get(regs[0]), UniformMask) and not isinstance(st.scalar.get(regs[0]), int)


def _neg(a):
    return {"true": "false", "false": "true"}.get(a, f"!{a}")


def _and(a, b):
    if "false" in (a, b):
        return "false"
    if a == "true":
        return b
    if b == "true":
        return a
    return f"({a} && {b})"


def _or(a, b):
    if "true" in (a, b):
        return "true"
    if a == "false":
        return b
    if b == "false":
        return a
    return f"({a} || {b})"


def _xor(a, b):
    if a in ("true", "false"):
        return b if a == "false" else _neg(b)
    if b in ("true", "false"):
        return a if b == "false" else _neg(a)
    return f"({a} != {b})"


# The SOP2 operations on two lane bits, S0 and S1 in the order of the instruction (andn2: S0 & ~S1, orn2: S0 | ~S1).
MASK_OPS = {
    "and": _and, "or": _or, "xor": _xor,
    "andn2": lambda a, b: _and(a, _neg(b)), "orn2": lambda a, b: _or(a, _neg(b)),
    "nand": lambda a, b: _neg(_and(a, b)), "nor": lambda a, b: _neg(_or(a, b)), "xnor": lambda a, b: _neg(_xor(a, b)),
}
# The *_saveexec_b64 forms: the new EXEC from S0 and the old EXEC (RDNA ISA, SOP1): andn2 is S0 & ~EXEC, andn1 is
# ~S0 & EXEC; orn2 is S0 | ~EXEC, orn1 is ~S0 | EXEC.
SAVEEXEC_OPS = {
    **{op: MASK_OPS[op] for op in ("and", "or", "xor", "andn2", "orn2", "nand", "nor", "xnor")},
    "andn1": lambda s, e: _and(_neg(s), e), "orn1": lambda s, e: _or(_neg(s), e),
}


def write_mask(st, i, dst, expression, *, widens=False):
    """Write a lane bit to a mask destination: EXEC (st.ex), VCC or an SGPR pair. A bit that is not a plain name is
    held in a bool local (`ex<i>` for EXEC, `lm<i>` otherwise). `widens`: the bit is folded from a constant source
    (0 or -1) into something other than false or one of the other sources (`s_mov_b64 exec, -1`,
    `s_xor_b64 exec, exec, -1`, `s_or_saveexec_b64 S, -1`); in EXEC that could turn on a lane that was never active,
    which is whole-wave mode: refused."""
    if dst == "exec":
        if widens:
            raise ValueError("EXEC write may enable an inactive lane (whole-wave mode)")
        if not re.fullmatch(r"true|false|ex\d+", expression):
            st.lines.append(f"    bool ex{i} = {expression};")
            expression = f"ex{i}"
        st.ex = expression
        return
    if not re.fullmatch(r"true|false|[A-Za-z_]\w*", expression):
        st.lines.append(f"    bool lm{i} = {expression};")
        expression = f"lm{i}"
    if dst == "vcc":
        if "vcc" in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        st.scalar["vcc"] = ("condition", expression, 0, 1)
        return
    regs = _pair(dst)
    if regs is None:
        raise ValueError(f"Unsupported lane mask destination {dst}")
    if st.pending.intersection(regs):
        raise ValueError("Write overlaps an outstanding scalar load")
    for j, reg in enumerate(regs):
        st.scalar[reg] = ("condition", expression, j, 2)


def widens(op, sources):
    """Whether op folds a constant source into a bit that is neither false nor one of the other sources, checked on
    placeholders so that the answer does not depend on what the other sources hold."""
    if not set(sources) & {"0", "-1"}:
        return False
    bits = [{"0": "false", "-1": "true"}.get(src, f"p{n}") for n, src in enumerate(sources)]
    return op(*bits) not in ("false", *(b for b in bits if b.startswith("p")))


def read_mask(st, token):
    bit = mask_bit(st, token)
    if bit is None:
        raise ValueError("Unsupported execution mask" if token.startswith("s[") or token == "vcc"
                         else f"Unsupported lane mask operand {token}")
    return bit


@form(r"s_mov_b64 s\[(\d+):(\d+)\], exec")
def save_exec(st, i, m):
    regs = registers(*m.groups(), 2)
    for n in regs:
        if f"s{n}" in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        st.scalar[f"s{n}"] = Saved(("condition", st.ex, n-regs.start, 2), st.wqm)


# Whole-quad mode turns on every lane of a quad with an active lane, so it keeps ex true and could only re-enable an
# inactive lane: refused unless the lane is provably active. Entering it twice is refused as before.
@form(r"s_wqm_b64 exec, exec", when=lambda st, m: st.ex == "true" and not st.wqm and st.stage == "pixel")
def whole_quad_mode(st, i, m):
    st.wqm = True
    st.scc = None


@form(r"s_and_b64 exec, exec, s\[(\d+):(\d+)\]")
def restore_exec(st, i, m):
    # EXEC &= a saved mask (the fixture's return from whole-quad mode) or another tracked lane mask. The lane's bit
    # stays true for a mask saved while it was active. Whole-quad mode is left: the result is no wider than the mask.
    pair = [f"s{n}" for n in registers(*m.groups(), 2)]
    mask = st.scalar.get(pair[0])
    if (st.pending.intersection(pair) or not isinstance(mask, tuple) or mask[0] != "condition"
            or [st.scalar.get(r) for r in pair] != [("condition", mask[1], j, 2) for j in range(2)]):
        raise ValueError("Unsupported execution mask")
    st.exec_and(i, mask[1])
    st.wqm = False
    st.scc = None


@form(r"s_mov_b64 (exec|vcc|s\[\d+:\d+\]), (exec|vcc|s\[\d+:\d+\]|-1|0)")
def move_mask(st, i, m):
    # Lane-mask moves. s_mov_b64 S, -1 / 0 into an SGPR pair keeps the data words (0 or all ones), which are also the
    # uniform masks; into VCC they are the masks true and false. s_mov_b64 exec, S restores a mask (the join of an
    # if); a restore of a saved EXEC also restores whole-quad mode as it was at the save. s_mov_b64 exec, -1 is
    # whole-wave mode and refused. SCC is not written.
    dst, src = m.groups()
    if dst == src:
        raise ValueError("Unsupported lane mask move")
    if src in ("-1", "0") and dst.startswith("s["):
        regs = _pair(dst)
        if st.pending.intersection(regs):
            raise ValueError("Write overlaps an outstanding scalar load")
        for reg in regs:
            st.scalar[reg] = 0xffffffff if src == "-1" else 0
        return
    if src.startswith("s[") and dst.startswith("s[") and not is_mask(st, src):
        # A plain 64-bit copy of data.
        regs, sources = _pair(dst), _pair(src)
        if st.pending.intersection(regs) or st.pending.intersection(sources):
            raise ValueError("Unresolved scalar memory dependency")
        values = [st.scalar.get(r) for r in sources]
        if None in values:
            raise ValueError(f"Read of unset scalar register {src}")
        for reg, value in zip(regs, values):
            st.scalar[reg] = value
        return
    bit = read_mask(st, src)
    saved = st.scalar.get(_pair(src)[0]) if src.startswith("s[") else None
    write_mask(st, i, dst, bit, widens=src == "-1")
    if dst == "exec" and isinstance(saved, Saved) and st.ex == "true":
        st.wqm = saved.wqm
    elif dst.startswith("s[") and isinstance(saved, Saved):
        for reg in _pair(dst):
            st.scalar[reg] = Saved(st.scalar[reg], saved.wqm)


@form(rf"s_({'|'.join(MASK_OPS)})_b64 (exec|vcc), ([^,\s]+), ([^,\s]+)")
def mask_op_to_special(st, i, m):
    # A mask operation into EXEC or VCC: the bool operation on this lane's bits of the sources. Into EXEC this is the
    # narrowing (and), the else (andn2 S, exec) and the re-narrow (and M, exec) of a divergent if.
    op, dst, src0, src1 = m.groups()
    a, b = read_mask(st, src0), read_mask(st, src1)
    write_mask(st, i, dst, MASK_OPS[op](a, b), widens=widens(MASK_OPS[op], (src0, src1)))
    st.scc = None  # lane local


def mask_op(st, i, op, dst, src0, src1):
    """A mask operation into an SGPR pair (sop2.py claims the text and calls this when a source is a lane mask)."""
    a, b = read_mask(st, src0), read_mask(st, src1)
    write_mask(st, i, dst, MASK_OPS[op](a, b))
    st.scc = None  # lane local


@form(rf"s_({'|'.join(SAVEEXEC_OPS)})_saveexec_b64 (s\[\d+:\d+\]|vcc), ([^,\s]+)")
def saveexec(st, i, m):
    # D = EXEC; EXEC = op(S0, EXEC); SCC = (EXEC != 0), lane local. S0 is read before D is written, so S0 may be D.
    op, dst, src = m.groups()
    if src == "exec":
        raise ValueError("Unsupported lane mask operand exec")
    bit, old = read_mask(st, src), st.ex
    new = SAVEEXEC_OPS[op](bit, old)
    if dst == "vcc":
        write_mask(st, i, "vcc", old)
    else:
        regs = _pair(dst)
        if st.pending.intersection(regs):
            raise ValueError("Write overlaps an outstanding scalar load")
        for j, reg in enumerate(regs):
            st.scalar[reg] = Saved(("condition", old, j, 2), st.wqm)
    write_mask(st, i, "exec", new, widens=widens(SAVEEXEC_OPS[op], (src, "exec")))
    st.scc = None  # lane local
