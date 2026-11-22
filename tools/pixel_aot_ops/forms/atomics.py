"""Atomics from pixel shaders through title memory: MUBUF buffer_atomic_* and GLOBAL global_atomic_* on 32-bit words.

Lowered: swap, cmpswap, add, sub, smin, umin, smax, umax, and, or, xor, inc and dec. With glc the pre-operation value is
returned in the first data register, as a load result (usable after vmcnt(0)); without glc no register is written.
Each operation is one D3D atomic: native for swap, cmpswap, add, sub, umin, umax, and, or and xor, and a
compare-exchange loop for smin, smax, inc and dec, which applies the operation to the last value seen and retries until
no other lane changed the word in between. The addressing and range rules are those of the stores (forms/stores.py):
a word out of range or outside title memory is not changed, and a returned value is then zero.

What the draws can check bit-exactly is a final memory value that does not depend on the order in which lanes reach a
word: add, sub, and, or, xor and the four min/max on any word, inc and dec on a word one lane owns (or with one data
value for all lanes), and swap, cmpswap and every returned value only on a word the lane owns. The lowering cannot see
whether two lanes share an address held in a VGPR; a buffer atomic with no VGPR address (`off`) is shared by every
lane, and there swap, cmpswap, inc, dec and glc are refused. Refused everywhere: the float atomics (fcmpswap, fmin,
fmax), whose desktop rounding and NaN rules differ, and the 64-bit _x2 forms, which shader model 6.0 has no atomics for.
Like the stores, an atomic needs this lane provably active outside whole-quad mode (CF-2a)."""
from ..dispatch import form
from ..registers import vector_u32, vgprs
from .flat import global_operands
from .mubuf import OPERANDS, buffer_operands
from .stores import writing

# Operation -> code of title_atomic below.
OPS = {"swap": 0, "cmpswap": 1, "add": 2, "sub": 3, "smin": 4, "umin": 5, "smax": 6, "umax": 7, "and": 8, "or": 9,
       "xor": 10, "inc": 11, "dec": 12}
# Operations whose final value depends on the order of lanes sharing a word unless they share one data value.
ORDERED = {"swap", "cmpswap", "inc", "dec"}
REFUSED = {"fcmpswap", "fmin", "fmax"}

ATOMIC_HELPERS = """uint atomic_value(uint op, uint old, uint data, uint cmp) {
    if (op == 4u) return asint(old) < asint(data) ? old : data;
    if (op == 6u) return asint(old) > asint(data) ? old : data;
    if (op == 11u) return old >= data ? 0u : old + 1u;
    return old == 0u || old > data ? data : old - 1u;
}
uint title_atomic(uint2 address, uint op, uint data, uint cmp) {
    uint slot;
    uint offset;
    if (!TitleLookup(title_ranges, title_range_count, address, 4, slot, offset)) return 0u;
    uint old = 0u;
    if (op == 0u) title_memory[NonUniformResourceIndex(slot)].InterlockedExchange(offset, data, old);
    else if (op == 1u) title_memory[NonUniformResourceIndex(slot)].InterlockedCompareExchange(offset, cmp, data, old);
    else if (op == 2u) title_memory[NonUniformResourceIndex(slot)].InterlockedAdd(offset, data, old);
    else if (op == 3u) title_memory[NonUniformResourceIndex(slot)].InterlockedAdd(offset, 0u - data, old);
    else if (op == 5u) title_memory[NonUniformResourceIndex(slot)].InterlockedMin(offset, data, old);
    else if (op == 7u) title_memory[NonUniformResourceIndex(slot)].InterlockedMax(offset, data, old);
    else if (op == 8u) title_memory[NonUniformResourceIndex(slot)].InterlockedAnd(offset, data, old);
    else if (op == 9u) title_memory[NonUniformResourceIndex(slot)].InterlockedOr(offset, data, old);
    else if (op == 10u) title_memory[NonUniformResourceIndex(slot)].InterlockedXor(offset, data, old);
    else {
        old = title_memory[NonUniformResourceIndex(slot)].Load(offset);
        [loop] for (;;) {
            uint seen;
            title_memory[NonUniformResourceIndex(slot)].InterlockedCompareExchange(offset, old, atomic_value(op, old, data, cmp), seen);
            if (seen == old) break;
            old = seen;
        }
    }
    return old;
}
uint buffer_atomic(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint op, uint data, uint cmp) {
    uint2 address;
    if (!buffer_address(rsrc, soffset, voffset, inst_offset, index, address)) return 0u;
    return title_atomic(address, op, data, cmp);
}
"""


def operation(st, op, wide, data_token, glc, shared):
    """Check one atomic and return (code, data word, compare word, destination register or None)."""
    if op in REFUSED or wide:
        raise ValueError(f"{op}{wide or ''} atomics are not lowered")
    if op not in OPS:
        raise ValueError(f"Unknown atomic {op}")
    if shared and (op in ORDERED or glc):
        raise ValueError("An order-dependent atomic or returned value on an address every lane shares")
    writing(st)
    st.memory_helpers.setdefault("atomics", ATOMIC_HELPERS)
    regs = vgprs(data_token, 2 if op == "cmpswap" else 1)
    words = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in regs]
    if glc and regs[0] in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    return OPS[op], words[0], words[1] if op == "cmpswap" else "0u", regs[0] if glc else None


def returned(st, i, dst, expression):
    if dst is None:
        st.lines.append(f"    {expression};")
        return
    st.lines.append(f"    uint mem{i}_0 = {expression};")
    st.vector[dst] = ("uint", f"mem{i}_0")
    st.vm_issue([dst], "atomic")


@form(r"buffer_atomic_([a-z]+)(_x2)? (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def buffer_atomic(st, i, m):
    op, wide, data_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    glc = "glc" in modifiers.split()
    code, data, cmp, dst = operation(st, op, wide, data_token, glc, addr_token == "off")
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers)
    returned(st, i, dst, f"buffer_atomic({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {code}u, {data}, {cmp})")


@form(r"global_atomic_([a-z]+)(_x2)? (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), "
      r"(off|s\[\d+:\d+\])((?: \S+)*)", when=lambda st, m: "glc" in m[7].split())
def global_atomic_return(st, i, m):
    # With glc the syntax names the returned register first: vdst, vaddr, vdata, saddr.
    op, wide, dst_token, addr_token, data_token, saddr_token, modifiers = m.groups()
    code, data, cmp, dst = operation(st, op, wide, data_token, True, False)
    dst = vgprs(dst_token, 1)[0]
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    base, voffset, bits = global_operands(st, addr_token, saddr_token, modifiers)
    returned(st, i, dst, f"title_atomic(global_address(uint2({base[0]}, {base[1]}), {voffset}, "
                         f"uint2({bits & 0xffffffff}u, {bits >> 32}u), 0u), {code}u, {data}, {cmp})")


@form(r"global_atomic_([a-z]+)(_x2)? (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), (off|s\[\d+:\d+\])((?: \S+)*)",
      when=lambda st, m: "glc" not in m[6].split())
def global_atomic(st, i, m):
    op, wide, addr_token, data_token, saddr_token, modifiers = m.groups()
    code, data, cmp, _ = operation(st, op, wide, data_token, False, False)
    base, voffset, bits = global_operands(st, addr_token, saddr_token, modifiers)
    returned(st, i, None, f"title_atomic(global_address(uint2({base[0]}, {base[1]}), {voffset}, "
                          f"uint2({bits & 0xffffffff}u, {bits >> 32}u), 0u), {code}u, {data}, {cmp})")
