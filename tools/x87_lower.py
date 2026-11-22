"""Opt-in x87 leaf-function profile for ffx_version_query.lower(x87=True).

The profile accepts:
- FLD and FSTP with an m32, m64 or m80 operand, and FST with an m32 or m64 operand;
- FLD, FST, FSTP and FXCH with ST(i), and FCHS and FABS;
- the constant loads FLD1, FLDZ, FLDPI, FLDL2T, FLDL2E, FLDLG2 and FLDLN2;
- FILD, FISTP and FISTTP with an m16, m32 or m64 integer operand, and FIST with m16 or m32;
- FCOMI, FCOMIP, FUCOMI and FUCOMIP ST(0), ST(i), which set ZF and CF for the integer lowering (PF is
  not modelled, and the integer lowering rejects every instruction that reads it);
- FADD, FSUB, FSUBR, FMUL, FDIV and FDIVR with an m32 or m64 operand, with ST(0), ST(i) and with
  ST(i), ST(0), and their popping forms FADDP, FSUBP, FSUBRP, FMULP, FDIVP and FDIVRP ST(i), ST(0) for
  i from 1 to 7.
A function starts with control word 0x027F, TOP 0, eight empty registers and a clear status word, and
must return with the stack empty. The stack depth before every instruction is fixed at translation
time, so each register maps to a C++ slot and no TOP is needed at run time. Translation rejects any x87
instruction outside the profile (including control-word and status-word access, a popping form with
ST(0) as the destination, and the undocumented FSTP and FXCH alias encodings), a stack overflow or
underflow, a depth that differs where control flow joins, an x87 instruction it cannot reach from the entry through direct edges, and x87 state that is
live at a call, a return, an indirect branch or an external edge. The helpers are in tools/x87_soft.h,
which the generated source must include before the lowered functions (X87_HEADER).
"""
from pathlib import Path

from iced_x86 import Code as C, FlowControl, MemorySize as S, Mnemonic as M, OpKind as K, Register as R

X87_HEADER = Path(__file__).with_name("x87_soft.h").read_text(encoding="ascii")
X87_OPS = frozenset({M.FLD, M.FST, M.FSTP, M.FXCH, M.FCHS, M.FABS, M.FLD1, M.FLDZ, M.FLDPI, M.FLDL2T, M.FLDL2E,
                     M.FLDLG2, M.FLDLN2, M.FILD, M.FIST, M.FISTP, M.FISTTP, M.FCOMI,
                     M.FCOMIP, M.FUCOMI, M.FUCOMIP, M.FADD, M.FADDP, M.FSUB, M.FSUBP, M.FSUBR, M.FSUBRP, M.FMUL, M.FMULP,
                     M.FDIV, M.FDIVP, M.FDIVR, M.FDIVRP})
DECLARATION = "X87Value x87_slot[8]{};"

LOADS = {S.FLOAT32: "x87_from_f32(load<uint32_t>(a))", S.FLOAT64: "x87_from_f64(load<uint64_t>(a))",
         S.FLOAT80: "x87_from_m80(load<uint64_t>(a), load<uint16_t>(a + 8))"}
# An arithmetic memory operand keeps a signaling NaN signaling until the NaN rules have seen it.
OPERANDS = {S.FLOAT32: "x87_operand_f32(load<uint32_t>(a))", S.FLOAT64: "x87_operand_f64(load<uint64_t>(a))"}
# Two-operand register arithmetic: mnemonic -> helper. The P forms pop after writing ST(i).
ARITHMETIC = {M.FADD: "x87_add", M.FADDP: "x87_add", M.FSUB: "x87_sub", M.FSUBP: "x87_sub", M.FSUBR: "x87_subr",
              M.FSUBRP: "x87_subr", M.FMUL: "x87_mul", M.FMULP: "x87_mul", M.FDIV: "x87_div", M.FDIVP: "x87_div",
              M.FDIVR: "x87_divr", M.FDIVRP: "x87_divr"}
# Arithmetic with a memory operand or with ST(0), ST(i) / ST(i), ST(0), which keeps the stack depth.
TWO_FORM = frozenset({M.FADD, M.FSUB, M.FSUBR, M.FMUL, M.FDIV, M.FDIVR})
POPPING = frozenset({M.FADDP, M.FSUBP, M.FSUBRP, M.FMULP, M.FDIVP, M.FDIVRP})
# The constant loads push their value rounded to 64 significand bits under the rounding control, which
# the profile fixes at round to nearest-even; the precision control does not apply to them. Each entry is
# the (significand, sign and exponent) encoding.
CONSTANTS = {M.FLD1: (0x8000000000000000, 0x3FFF), M.FLDZ: (0, 0), M.FLDPI: (0xC90FDAA22168C235, 0x4000),
             M.FLDL2T: (0xD49A784BCD1B8AFE, 0x4000), M.FLDL2E: (0xB8AA3B295C17F0BC, 0x3FFF),
             M.FLDLG2: (0x9A209A84FBCFF799, 0x3FFD), M.FLDLN2: (0xB17217F7D1CF79AC, 0x3FFE)}
# Integer memory operands: (signed type, unsigned type, bits).
INTEGERS = {S.INT16: ("int16_t", "uint16_t", 16), S.INT32: ("int32_t", "uint32_t", 32),
            S.INT64: ("int64_t", "uint64_t", 64)}
# Comparisons into EFLAGS; the P forms pop after comparing.
COMPARES = frozenset({M.FCOMI, M.FCOMIP, M.FUCOMI, M.FUCOMIP})
# Undocumented aliases of FSTP ST(i) (DF D0+i, DF D8+i) and FXCH ST(i) (DD C8+i, DF C8+i). Assemblers do
# not emit them and the fixtures do not measure them, so they stay outside the profile.
ALIASES = frozenset({C.FSTP_STI_DFD0, C.FSTP_STI_DFD8, C.FXCH_ST0_STI_DDC8, C.FXCH_ST0_STI_DFC8})


# Every x87 mnemonic in iced starts with F (including FXSAVE/FXRSTOR, which store the x87 state, and
# FEMMS, which empties it); WAIT reports pending x87 exceptions. All of them touch the modelled state.
X87_STATE_OPS = frozenset(value for name, value in vars(M).items() if name.startswith("F")) | {M.WAIT}


def is_x87(i):
    return i.mnemonic in X87_STATE_OPS


def _effect(i, depth):
    """Stack depth after i, or a ValueError for an instruction or operand outside the profile."""
    op = i.mnemonic
    if i.code in ALIASES:
        raise ValueError(f"unsupported x87 encoding at {i.ip:#x}: {i}")
    if op in (M.FLD, M.FST, M.FSTP) and i.op0_kind == K.REGISTER:  # ST(i) copies
        if depth <= i.op0_register - R.ST0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        if op == M.FLD and depth == 8:
            raise ValueError(f"x87 stack overflow at {i.ip:#x}: {i}")
        return depth + {M.FLD: 1, M.FST: 0, M.FSTP: -1}[op]
    if op == M.FXCH and i.op_count == 2 and i.op0_register == R.ST0:
        if depth <= i.op1_register - R.ST0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth
    if op in COMPARES:
        if i.op_count != 2 or i.op0_register != R.ST0:
            raise ValueError(f"unsupported x87 operand at {i.ip:#x}: {i}")
        if depth <= i.op1_register - R.ST0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth - 1 if op in (M.FCOMIP, M.FUCOMIP) else depth
    if op in (M.FILD, M.FIST, M.FISTP, M.FISTTP):
        if i.op0_kind != K.MEMORY or i.memory_size not in INTEGERS:
            raise ValueError(f"unsupported x87 operand at {i.ip:#x}: {i}")
        if op == M.FILD:
            if depth == 8:
                raise ValueError(f"x87 stack overflow at {i.ip:#x}: {i}")
            return depth + 1
        if depth == 0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth if op == M.FIST else depth - 1
    if op in CONSTANTS:
        if depth == 8:
            raise ValueError(f"x87 stack overflow at {i.ip:#x}: {i}")
        return depth + 1
    if op in (M.FCHS, M.FABS):
        if depth == 0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth
    if op == M.FST:  # FST m32/m64; there is no FST m80
        if i.op0_kind != K.MEMORY or i.memory_size not in OPERANDS:
            raise ValueError(f"unsupported x87 operand at {i.ip:#x}: {i}")
        if depth == 0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth
    if op in (M.FLD, M.FSTP):
        if i.op0_kind != K.MEMORY or i.memory_size not in LOADS:
            raise ValueError(f"unsupported x87 operand at {i.ip:#x}: {i}")
        if op == M.FLD:
            if depth == 8:
                raise ValueError(f"x87 stack overflow at {i.ip:#x}: {i}")
            return depth + 1
        if depth == 0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth - 1
    if op in TWO_FORM and i.op_count == 1:
        if i.op0_kind != K.MEMORY or i.memory_size not in OPERANDS:
            raise ValueError(f"unsupported x87 operand at {i.ip:#x}: {i}")
        if depth == 0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth
    if op in TWO_FORM and i.op_count == 2 and R.ST0 in (i.op0_register, i.op1_register):
        if depth <= max(i.op0_register, i.op1_register) - R.ST0:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth
    if op in POPPING and i.op_count == 2 and i.op1_register == R.ST0 and i.op0_register != R.ST0:
        if depth <= i.op0_register - R.ST0 or depth < 2:
            raise ValueError(f"x87 stack underflow at {i.ip:#x}: {i}")
        return depth - 1
    raise ValueError(f"unsupported x87 operation at {i.ip:#x}: {i}")


def depths(body, exits):
    """The x87 stack depth before each instruction of body, from an empty stack at body[0]."""
    index = {i.ip: i for i in body}
    depth = {body[0].ip: 0}
    work = [body[0].ip]
    while work:
        i = index[work.pop()]
        before = depth[i.ip]
        after = _effect(i, before) if is_x87(i) else before
        flow = i.flow_control
        if flow == FlowControl.RETURN and before:
            raise ValueError(f"x87 stack not empty at return {i.ip:#x}")
        if flow in (FlowControl.CALL, FlowControl.INDIRECT_CALL) and before:
            raise ValueError(f"x87 state live across the call at {i.ip:#x}")
        if flow == FlowControl.INDIRECT_BRANCH and before:
            raise ValueError(f"x87 state live at the indirect branch {i.ip:#x}")
        successors = []
        if flow not in (FlowControl.RETURN, FlowControl.UNCONDITIONAL_BRANCH, FlowControl.INDIRECT_BRANCH):
            successors.append(i.next_ip)
        if flow in (FlowControl.CONDITIONAL_BRANCH, FlowControl.UNCONDITIONAL_BRANCH):
            successors.append(i.near_branch_target)
        for target in successors:
            if target in index:
                if target not in depth:
                    depth[target] = after
                    work.append(target)
                elif depth[target] != after:
                    raise ValueError(f"x87 stack depth {depth[target]} and {after} meet at {target:#x}")
            elif target in exits and after:
                raise ValueError(f"x87 state live at the external edge {i.ip:#x} -> {target:#x}")
    for i in body:
        if i.ip not in depth and is_x87(i):
            raise ValueError(f"unknown x87 stack depth at {i.ip:#x}: {i}")
    return depth


def statement(i, depth, address):
    """C++ for one profile instruction at a known stack depth; address() gives the memory operand."""
    op = i.mnemonic
    _effect(i, depth)
    top = depth - 1  # ST(k) is x87_slot[top - k]
    if op in (M.FLD, M.FST, M.FSTP) and i.op0_kind == K.REGISTER:
        k = i.op0_register - R.ST0
        if op == M.FLD:  # push a copy of ST(k): every encoding is copied as it is
            return f"x87_slot[{depth}] = x87_slot[{top - k}];  // fld st({k})"
        return f"x87_slot[{top - k}] = x87_slot[{top}];  // {'fst' if op == M.FST else 'fstp'} st({k})"
    if op == M.FXCH:
        k = top - (i.op1_register - R.ST0)
        return f"{{ const X87Value t = x87_slot[{top}]; x87_slot[{top}] = x87_slot[{k}]; x87_slot[{k}] = t; }}  // fxch"
    if op in COMPARES:  # ZF and CF: 1 and 0 for equal, 0 and 1 for less, 0 and 0 for greater, 1 and 1 unordered
        k = top - (i.op1_register - R.ST0)
        return (f"{{ const int r = x87_compare(x87_slot[{top}], x87_slot[{k}]); "
                f"zero = r == 1 || r == 3; carry = r == 0 || r == 3; }}")
    if op in (M.FILD, M.FIST, M.FISTP, M.FISTTP):
        signed, unsigned, bits = INTEGERS[i.memory_size]
        if op == M.FILD:
            return (f"{{ const word a = {address()}; "
                    f"x87_slot[{depth}] = x87_from_integer(static_cast<{signed}>(load<{unsigned}>(a))); }}")
        chop = "true" if op == M.FISTTP else "false"
        return (f"{{ const word a = {address()}; "
                f"store<{unsigned}>(a, static_cast<{unsigned}>(x87_to_integer(x87_slot[{top}], {bits}, {chop}))); }}")
    if op in CONSTANTS:
        sig, se = CONSTANTS[op]
        name = next(n for n, v in vars(M).items() if v == op).lower()
        return f"x87_slot[{depth}] = X87Value{{{sig:#018x}ull, {se:#06x}}};  // {name}"
    if op in (M.FCHS, M.FABS):
        return f"x87_slot[{top}] = {'x87_chs' if op == M.FCHS else 'x87_abs'}(x87_slot[{top}]);"
    if op == M.FLD:
        return f"{{ const word a = {address()}; x87_slot[{depth}] = {LOADS[i.memory_size]}; }}"
    if op in (M.FST, M.FSTP):  # FST m32/m64 stores without popping
        v = f"x87_slot[{top}]"
        store = {S.FLOAT32: f"store<uint32_t>(a, x87_to_f32({v}));", S.FLOAT64: f"store<uint64_t>(a, x87_to_f64({v}));",
                 S.FLOAT80: f"store<uint64_t>(a, {v}.sig); store<uint16_t>(a + 8, {v}.se);"}[i.memory_size]
        return f"{{ const word a = {address()}; {store} }}" + ("  // fst m" if op == M.FST else "")
    if i.op_count == 1:  # arithmetic with an m32/m64 operand: ST(0) = ST(0) op operand
        return (f"{{ const word a = {address()}; "
                f"x87_slot[{top}] = {ARITHMETIC[op]}(x87_slot[{top}], {OPERANDS[i.memory_size]}); }}")
    # The destination is the first operand: ST(i) for FMUL ST(i), ST(0) and the P forms, ST(0) otherwise.
    destination, source = (top - (i.op0_register - R.ST0), top - (i.op1_register - R.ST0))
    return f"x87_slot[{destination}] = {ARITHMETIC[op]}(x87_slot[{destination}], x87_slot[{source}]);"
