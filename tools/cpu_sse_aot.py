"""Recompile bounded Windows x64 leaf functions that use scalar SSE/SSE2 arithmetic to C++.

Each export is named with its Windows x64 signature, `name=<result>:<slots>`, where every
letter is `f` (float), `d` (double) or `q` (a 64-bit integer or pointer). Slot N arrives in
XMM0-XMM3 when it is floating point and in RCX, RDX, R8 or R9 otherwise; the result leaves in
XMM0 or RAX. Control flow and the integer instructions are those of cpu_switch_aot.

Only the low quadword of an XMM register is modelled. Every supported instruction computes
that quadword from low quadwords alone, so the upper half never reaches a result. The two
dwords of the low quadword are tracked separately as defined or undefined: a float argument
defines the low dword only, and a read of an undefined part is rejected. Integer registers are
tracked as cpu_switch_aot tracks them, by how many low bytes are defined.
"""

import argparse
from pathlib import Path
import re

import pefile
from iced_x86 import ConditionCode as CC, FlowControl, MemorySizeExt, Mnemonic as M, OpKind, Register as R, RegisterExt

from cpu_leaf_aot import export_rva
from cpu_switch_aot import (ALU, CMOVCC, SETCC, Function, Lifter, NAMES, PRELUDE, VOLATILE, flag_producer, full,
                            signed, unsigned)


SLOTS = (R.RCX, R.RDX, R.R8, R.R9)
XMM_SLOTS = (R.XMM0, R.XMM1, R.XMM2, R.XMM3)
XMM = {getattr(R, f"XMM{number}"): f"xmm{number}" for number in range(16)}
VOLATILE_XMM = {getattr(R, f"XMM{number}") for number in range(6)}
TYPES = {4: "float", 8: "double"}
MOVES = {M.MOVSS: 4, M.MOVSD: 8}
COPIES = {M.MOVAPS, M.MOVAPD, M.MOVUPS, M.MOVUPD}
ARITHMETIC = {M.ADDSS: ("+", 4), M.SUBSS: ("-", 4), M.MULSS: ("*", 4), M.DIVSS: ("/", 4),
              M.ADDSD: ("+", 8), M.SUBSD: ("-", 8), M.MULSD: ("*", 8), M.DIVSD: ("/", 8)}
FROM_INTEGER = {M.CVTSI2SS: 4, M.CVTSI2SD: 8}
TRUNCATIONS = {M.CVTTSS2SI: 4, M.CVTTSD2SI: 8}
RESIZES = {M.CVTSS2SD: 4, M.CVTSD2SS: 8}
COMPARES = {M.UCOMISS: 4, M.COMISS: 4, M.UCOMISD: 8, M.COMISD: 8}
ZEROING = {M.XORPS, M.XORPD, M.PXOR}
SCALAR = {*MOVES, *COPIES, *ARITHMETIC, *FROM_INTEGER, *TRUNCATIONS, *RESIZES, *COMPARES, *ZEROING, M.MOVD, M.MOVQ}
# fc holds ZF, PF and CF of the last compare as bits 2, 1 and 0. An unordered compare sets all three.
CONDITIONS = {CC.E: "(fc & 4u) != 0", CC.NE: "(fc & 4u) == 0", CC.B: "(fc & 1u) != 0", CC.AE: "(fc & 1u) == 0",
              CC.BE: "(fc & 5u) != 0", CC.A: "(fc & 5u) == 0", CC.P: "(fc & 2u) != 0", CC.NP: "(fc & 2u) == 0"}


def parts(register, width):
    """Definedness keys of the low dword and, for a double, of bits 32-63."""
    return {(register, 0)} if width == 4 else {(register, 0), (register, 1)}


def whole(keys):
    """Reads or writes of XMM parts, in the width form of cpu_switch_aot: each part is one dword."""
    return dict.fromkeys(keys, 4)


def gpr(reads, register):
    """Record a read of the low bytes of an integer register, as cpu_switch_aot's lower() does."""
    reads[full(register)] = max(reads.get(full(register), 0), RegisterExt.size(register))


def describe(key):
    if isinstance(key, tuple):
        return XMM[key[0]] + ("[63:32]" if key[1] else "")
    return NAMES[key]


def parse_export(text):
    match = re.fullmatch(r"(\w+)=([fdq]):([fdq]{0,4})", text)
    if not match:
        raise ValueError(f"invalid signature {text!r}: expected name=<result>:<slots> of f, d and q")
    return match.groups()


class LeafFunction(Function):
    def constants(self):
        """No register is tracked as a table base, so every indirect jump is rejected."""
        return {}


class ScalarLifter(Lifter):
    def __init__(self, result):
        super().__init__()
        self.result = result
        self.vectors = set()
        self.compare = False
        self.merges = []

    def xmm(self, ins, number):
        register = ins.op_register(number)
        if ins.op_kind(number) != OpKind.REGISTER or register not in XMM:
            raise ValueError(f"unsupported instruction at RVA {ins.ip:#x}: {ins}")
        self.vectors.add(register)
        return register

    def pointer(self, ins, reads):
        address = self.address(ins)
        for register in (ins.memory_base, ins.memory_index):
            if register != R.NONE:
                gpr(reads, register)
        return address

    def source(self, ins, number, width, reads):
        """The bits of a float or double operand, from an XMM register or from memory."""
        if ins.op_kind(number) == OpKind.MEMORY and MemorySizeExt.size(ins.memory_size) == width:
            # A guest read: performed even when its value is unused, since the original faults either way.
            return f"load_always<{unsigned(width)}>({self.pointer(ins, reads)})"
        register = self.xmm(ins, number)
        reads.update(whole(parts(register, width)))
        return XMM[register] if width == 8 else f"static_cast<std::uint32_t>({XMM[register]})"

    def assign(self, register, width, bits):
        name = XMM[register]
        return f"{name} = {bits};" if width == 8 else f"{name} = low({name}, {bits});"

    def statement(self, ins, sets_flags=False, producer=None):
        """Return C++ for one instruction, its reads and its writes, in the form of cpu_switch_aot's
        Lifter.statement(): each maps a full integer register to the low bytes read or the width
        written. XMM parts are keyed (register, half) and always read or written as one dword.

        sets_flags and producer are passed to the integer lifter; float compares and the jumps that
        read them are handled by condition() below."""
        mnemonic = ins.mnemonic
        reads, writes = {}, {}
        self.merges = []
        if mnemonic == M.RET:
            if self.result == "q":
                # The integer lifter leaves the returned width to its own definedness pass; here the
                # whole of RAX is the result.
                text, _, _ = super().statement(ins, sets_flags, producer)
                return text, {R.RAX: 8}, writes
            width = 4 if self.result == "f" else 8
            self.vectors.add(R.XMM0)
            bits = "xmm0" if width == 8 else "static_cast<std::uint32_t>(xmm0)"
            return f"return cast<{TYPES[width]}>({bits});", whole(parts(R.XMM0, width)), writes
        vector = any(ins.op_kind(n) == OpKind.REGISTER and not RegisterExt.is_gpr(ins.op_register(n))
                     for n in range(ins.op_count))
        unsupported = ValueError(f"unsupported instruction at RVA {ins.ip:#x}: {ins}")
        if mnemonic not in SCALAR or ins.op_count != 2 or not all(
                ins.op_kind(n) in (OpKind.REGISTER, OpKind.MEMORY) for n in range(2)):
            if vector:
                raise unsupported
            return super().statement(ins, sets_flags, producer)

        if mnemonic in MOVES or mnemonic in (M.MOVD, M.MOVQ):
            width = MOVES.get(mnemonic, 4 if mnemonic == M.MOVD else 8)
            if ins.op0_kind == OpKind.MEMORY:
                if MemorySizeExt.size(ins.memory_size) != width:
                    raise unsupported
                bits = self.source(ins, 1, width, reads)
                return f"store<{unsigned(width)}>({self.pointer(ins, reads)}, {bits});", reads, writes
            if ins.op0_register not in XMM:
                # MOVD r32, xmm zero-extends like any 32-bit write. MOVQ to or from an integer
                # register is left out: ML64 versions disagree on how to spell it in a fixture.
                if mnemonic != M.MOVD:
                    raise unsupported
                bits = self.source(ins, 1, 4, reads)
                writes[full(ins.op0_register)] = 4
                return self.write(ins, 4, bits), reads, writes
            destination = self.xmm(ins, 0)
            if ins.op1_kind == OpKind.REGISTER and ins.op1_register not in XMM:
                if mnemonic != M.MOVD:
                    raise unsupported
                gpr(reads, ins.op1_register)
                bits = self.operand(ins, 1, 4)
            else:
                bits = self.source(ins, 1, width, reads)
            if mnemonic == M.MOVSS and ins.op1_kind == OpKind.REGISTER:
                writes.update(whole(parts(destination, 4)))
                return self.assign(destination, 4, bits), reads, writes
            # Loads, MOVD, MOVQ and MOVSD between registers define the whole low quadword.
            writes.update(whole(parts(destination, 8)))
            return f"{XMM[destination]} = {bits};", reads, writes
        if mnemonic in TRUNCATIONS:
            width = RegisterExt.size(ins.op0_register) if ins.op0_kind == OpKind.REGISTER else 0
            if width not in (4, 8) or not RegisterExt.is_gpr(ins.op0_register):
                raise unsupported
            source = TRUNCATIONS[mnemonic]
            bits = self.source(ins, 1, source, reads)
            writes[full(ins.op0_register)] = width
            value = f"truncate<{signed(width)}>(cast<{TYPES[source]}>({bits}))"
            return self.write(ins, width, value), reads, writes

        destination = self.xmm(ins, 0)
        name = XMM[destination]
        if mnemonic in COPIES or mnemonic in ZEROING:
            source = self.xmm(ins, 1)
            if mnemonic in ZEROING:
                # Only the zeroing idiom: any other use combines the two registers bit by bit.
                if source != destination:
                    raise unsupported
                writes.update(whole(parts(destination, 8)))
                return f"{name} = 0;", reads, writes
            # A register copy may carry undefined parts, which stay undefined in the copy.
            self.merges = [((destination, half), (source, half)) for half in (0, 1)]
            return f"{name} = {XMM[source]};", reads, writes
        if mnemonic in ARITHMETIC:
            operator, width = ARITHMETIC[mnemonic]
            reads.update(whole(parts(destination, width)))
            a = name if width == 8 else f"static_cast<std::uint32_t>({name})"
            b = self.source(ins, 1, width, reads)
            return self.assign(destination, width, f"arith<{TYPES[width]}>({a}, {b}, '{operator}')"), reads, writes
        if mnemonic in FROM_INTEGER:
            width = FROM_INTEGER[mnemonic]
            if ins.op1_kind == OpKind.REGISTER:
                source = RegisterExt.size(ins.op1_register)
                if source not in (4, 8) or not RegisterExt.is_gpr(ins.op1_register):
                    raise unsupported
                gpr(reads, ins.op1_register)
                integer = self.operand(ins, 1, source)
            else:
                source = MemorySizeExt.size(ins.memory_size)
                integer = f"load_always<{unsigned(source)}>({self.pointer(ins, reads)})"
            writes.update(whole(parts(destination, width)))
            value = f"static_cast<{TYPES[width]}>(static_cast<{signed(source)}>({integer}))"
            return self.assign(destination, width, f"cast<{unsigned(width)}>({value})"), reads, writes
        if mnemonic in RESIZES:
            source = RESIZES[mnemonic]
            width = 12 - source
            bits = self.source(ins, 1, source, reads)
            writes.update(whole(parts(destination, width)))
            value = f"resize<{TYPES[width]}>(cast<{TYPES[source]}>({bits}))"
            return self.assign(destination, width, f"cast<{unsigned(width)}>({value})"), reads, writes
        # lift() has checked that a conditional jump follows.
        width = COMPARES[mnemonic]
        reads.update(whole(parts(destination, width)))
        a = name if width == 8 else f"static_cast<std::uint32_t>({name})"
        b = self.source(ins, 1, width, reads)
        self.compare = True
        return f"fc = compare(cast<{TYPES[width]}>({a}), cast<{TYPES[width]}>({b}));", reads, writes


def condition(function, edges, lifter, jcc):
    """A float compare may feed a run of conditional jumps; integer flags feed the next jump only.

    Returns the C++ condition and the integer instruction whose flags it reads, or None after a float compare."""
    current = jcc
    while True:
        producer = function.ending.get(current.ip)
        if current.ip in edges or producer is None or producer.flow_control not in (
                FlowControl.NEXT, FlowControl.CONDITIONAL_BRANCH):
            raise ValueError(f"flags cross a join before RVA {jcc.ip:#x}")
        if producer.flow_control == FlowControl.NEXT:
            break
        current = producer
    if producer.mnemonic in COMPARES:
        if jcc.condition_code not in CONDITIONS:
            raise ValueError(f"unsupported condition after a float compare at RVA {jcc.ip:#x}")
        return CONDITIONS[jcc.condition_code], None
    if current is not jcc:
        raise ValueError(f"flags cross a branch before RVA {jcc.ip:#x}")
    if producer.mnemonic not in (*ALU, M.CMP, M.TEST, M.INC, M.DEC):
        raise ValueError(f"unsupported flag producer at RVA {producer.ip:#x}")
    return lifter.condition(producer, jcc), producer


def lift(pe, name, result, slots):
    entry = export_rva(pe, name)
    function = LeafFunction(pe, entry)
    edges = function.explore()
    lifter = ScalarLifter(result)
    sets_flags = set()
    order = sorted(function.instructions)
    instructions = function.instructions
    body = {}
    effects = {}
    # Conditional jumps first: they decide which integer instructions record flags (sets_flags).
    # SETcc and CMOVcc find their producer as cpu_switch_aot does, which rejects a float compare.
    producers = {}
    for ip in order:
        ins = instructions[ip]
        if ins.flow_control == FlowControl.CONDITIONAL_BRANCH:
            test, producer = condition(function, edges, lifter, ins)
            body[ip] = f"if ({test}) goto loc_{ins.near_branch_target:x};"
        elif ins.mnemonic in SETCC | CMOVCC:
            producer = producers[ip] = flag_producer(function, edges, ins)
        else:
            continue
        if producer is not None:
            sets_flags.add(producer.ip)
    for ip in order:
        ins = instructions[ip]
        if ins.has_lock_prefix or ins.has_rep_prefix or ins.has_repne_prefix:
            raise ValueError(f"unsupported prefix at RVA {ip:#x}")
        effects[ip] = ({}, {}, [])
        if ins.flow_control == FlowControl.CONDITIONAL_BRANCH:
            pass
        elif ins.flow_control == FlowControl.UNCONDITIONAL_BRANCH:
            body[ip] = f"goto loc_{ins.near_branch_target:x};"
        else:
            if ins.mnemonic != M.RET and ins.is_stack_instruction:
                raise ValueError(f"stack operation in leaf profile at RVA {ip:#x}")
            following = instructions.get(ins.next_ip) if ins.flow_control == FlowControl.NEXT else None
            if ins.mnemonic in COMPARES and (following is None
                                             or following.flow_control != FlowControl.CONDITIONAL_BRANCH):
                raise ValueError(f"float compare without a conditional branch at RVA {ip:#x}")
            body[ip], reads, writes = lifter.statement(ins, ip in sets_flags, producers.get(ip))
            effects[ip] = (reads, writes, lifter.merges)
        reads, writes, merges = effects[ip]
        touched = {*reads, *writes, *(key for pair in merges for key in pair)}
        saved = sorted(describe(key) for key in touched
                       if (key[0] not in VOLATILE_XMM if isinstance(key, tuple) else key not in VOLATILE))
        if saved:
            raise ValueError(f"nonvolatile register {saved[0]} at RVA {ip:#x}")

    # Low bytes defined on every path, per integer register and XMM part (0 or 8 for a part): the
    # arguments at entry, the minimum at every join.
    arguments = set()
    for number, kind in enumerate(slots):
        arguments |= {SLOTS[number]} if kind == "q" else parts(XMM_SLOTS[number], 4 if kind == "f" else 8)
    everything = {*NAMES, *((register, half) for register in XMM for half in (0, 1))}
    defined = {ip: dict.fromkeys(everything, 8) for ip in order}
    defined[entry] = {key: 8 if key in arguments else 0 for key in everything}
    changed = True
    while changed:
        changed = False
        for ip in order:
            _, writes, merges = effects[ip]
            out = dict(defined[ip])
            for key, width in writes.items():
                # A 32- or 64-bit write (and any XMM part write) defines all eight bytes; an 8- or 16-bit
                # write keeps the rest.
                out[key] = 8 if width >= 4 else max(out[key], width)
            for destination, source in merges:
                # A register copy carries the definedness of its source.
                out[destination] = defined[ip][source]
            for successor in function.successors[ip]:
                old = defined[successor]
                merged = {key: min(old[key], out[key]) for key in everything}
                if merged != old:
                    defined[successor] = merged
                    changed = True
    for ip in order:
        missing = sorted(describe(key) for key, width in effects[ip][0].items() if defined[ip][key] < width)
        if missing:
            raise ValueError(f"undefined register {missing[0]} at RVA {ip:#x}")

    labels = set(edges)
    for position, ip in enumerate(order):
        ins = instructions[ip]
        following = order[position + 1] if position + 1 < len(order) else None
        if ins.flow_control in (FlowControl.NEXT, FlowControl.CONDITIONAL_BRANCH) and following != ins.next_ip:
            labels.add(ins.next_ip)
    integers = lifter.used | ({R.RAX} if result == "q" else set())
    parameters = []
    declarations = []
    for number, kind in enumerate(slots):
        if kind == "q":
            parameters.append("word" + (f" {NAMES[SLOTS[number]]}" if SLOTS[number] in integers else ""))
        elif XMM_SLOTS[number] in lifter.vectors:
            width = 4 if kind == "f" else 8
            parameters.append(f"{TYPES[width]} a{number}")
            declarations.append(f"word xmm{number} = cast<{unsigned(width)}>(a{number});")
        else:
            parameters.append(TYPES[4 if kind == "f" else 8])
    passed = {SLOTS[n] if kind == "q" else XMM_SLOTS[n] for n, kind in enumerate(slots)}
    declarations += [f"word {NAMES[r]} = 0;" for r in sorted(integers - passed, key=lambda r: NAMES[r])]
    declarations += [f"word {XMM[r]} = 0;" for r in sorted(lifter.vectors - passed)]
    if lifter.flags:
        declarations.append("word fa = 0, fb = 0;")
    if lifter.compare:
        declarations.append("unsigned fc = 0;")
    text = []
    for position, ip in enumerate(order):
        if ip in labels:
            text.append(f"loc_{ip:x}:")
        if body[ip]:
            text.append("    " + body[ip])
        ins = instructions[ip]
        following = order[position + 1] if position + 1 < len(order) else None
        if ins.flow_control in (FlowControl.NEXT, FlowControl.CONDITIONAL_BRANCH) and following != ins.next_ip:
            text.append(f"    goto loc_{ins.next_ip:x};")
    returned = {"f": "float", "d": "double", "q": "word"}[result]
    signature = f'extern "C" __declspec(dllexport) {returned} lifted_{name}({", ".join(parameters)})'
    source = [signature + " {", *("    " + d for d in declarations), *text, "}"]
    return "\n".join(source), function


FLOAT_PRELUDE = PRELUDE + """#include <limits>
// One host instruction per guest operation: no fused multiply-add.
#if defined(_MSC_VER) && !defined(__clang__)
#pragma fp_contract(off)
#else
#pragma STDC FP_CONTRACT OFF
#endif
template <class To, class From> static To cast(From value) {
    static_assert(sizeof(To) == sizeof(From), "bit cast between sizes");
    To out;
    std::memcpy(&out, &value, sizeof(out));
    return out;
}
// A scalar single result replaces the low dword and keeps bits 32-63 of the destination.
template <class Bits> static word low(word old, Bits value) {
    return (old & ~0xffffffffull) | static_cast<std::uint32_t>(value);
}
// ADD, SUB, MUL and DIV with exceptions masked. A NaN destination operand is returned quieted,
// otherwise a NaN source operand; an invalid operation gives the default NaN, whose sign is set.
// The host compiler may swap the operands of its own addition, so the rule is applied here.
template <class Float, class Bits> static Bits arith(Bits a, Bits b, char op) {
    const Bits quiet = static_cast<Bits>(1) << (std::numeric_limits<Float>::digits - 2);
    const Float x = cast<Float>(a), y = cast<Float>(b);
    if (x != x) return a | quiet;
    if (y != y) return b | quiet;
    const Float r = op == '+' ? x + y : op == '-' ? x - y : op == '*' ? x * y : x / y;
    return r != r ? static_cast<Bits>(~(quiet - 1)) : cast<Bits>(r);
}
// CVTTSS2SI and CVTTSD2SI: a NaN or a value outside the destination range gives the integer
// indefinite, which is the sign bit alone.
template <class Integer, class Float> static Integer truncate(Float value) {
    const Float limit = -static_cast<Float>(std::numeric_limits<Integer>::min());
    return value >= -limit && value < limit ? static_cast<Integer>(value) : std::numeric_limits<Integer>::min();
}
// CVTSS2SD and CVTSD2SS: the volatile input keeps every conversion, so a pair is not folded to an
// identity. Each one quiets a signalling NaN and, with DAZ or FTZ set, flushes denormals, as on hardware.
template <class To, class From> static To resize(From value) {
    volatile From input = value;
    return static_cast<To>(input);
}
// ZF, PF and CF of COMISS, UCOMISS, COMISD and UCOMISD as bits 2, 1 and 0.
template <class Float> static unsigned compare(Float a, Float b) {
    return a != a || b != b ? 7u : a < b ? 1u : a == b ? 4u : 0u;
}
"""


def translate_pe(pe, exports):
    if pe.FILE_HEADER.Machine != 0x8664 or pe.OPTIONAL_HEADER.Magic != 0x20B:
        raise ValueError("expected AMD64 PE32+")
    functions = [lift(pe, *parse_export(text)) for text in exports]
    return FLOAT_PRELUDE + "\n".join(f"\n{source}" for source, _ in functions) + "\n", [f for _, f in functions]


def translate(image, exports):
    with pefile.PE(str(image), fast_load=True) as pe:
        return translate_pe(pe, exports)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("exports", help="comma-separated name=<result>:<slots> signatures")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        source, functions = translate(args.image, args.exports.split(","))
        args.output.write_text(source, encoding="utf-8")
        for function in functions:
            print(f"RVA {function.entry:#x}: {len(function.instructions)} instructions")
    except (ValueError, OSError, pefile.PEFormatError) as error:
        parser.exit(1, f"{error}\n")
