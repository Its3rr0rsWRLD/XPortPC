"""LDS (docs/design/compute-stage.md, C-6): ds_read*/ds_write*, ds_read2*/ds_write2*, the common LDS atomics without
return, and s_barrier, compute stage only.

Model. LDS is `groupshared uint lds[lds_size / 4]`, lds_size being the program's LDS allocation in bytes (the binding
contract's `lds_size`, from COMPUTE_PGM_RSRC2.LDS_SIZE in a title's shader metadata; at most D3D12's 32 KiB of
groupshared memory). Addresses are byte addresses: ADDR = VGPR + the instruction's offset field (one 16-bit offset
{offset1, offset0}; ds_read2/ds_write2 add OFFSET0 and OFFSET1 times 4 for b32, 8 for b64, and 64 times that for the
st64 forms), as the RDNA 2 ISA guide (section 10.4.3 and the DS opcode table, 12.13) defines them.

Alignment. An access must be naturally aligned (2 bytes for a half, 4 for a dword, 8 for b64, 16 for b96 and b128), and
this must be provable at translation time from the address expression (forms that shift or multiply, constants and
loop variables whose every assignment is aligned): an unaligned LDS access is an alignment fault or not, and returns
which bytes, depending on SH_MEM_CONFIG's alignment mode, which a program cannot see; it is refused.

Range. The ISA guide (section 3.6.1) has an out-of-range LDS access, an address beyond the allocation, discard its
write and read zero; M0 is not used by the indexed LDS forms on RDNA 2 (section 10.4). Each dword is checked: with the
alignment rule and an allocation that is a multiple of 16 bytes, an access is wholly inside or wholly outside, so the
check is the same per dword and per access. An address sum that wraps 32 bits is out of range. An access at a
translation-time constant address outside the allocation is refused (it is a program bug, and the guide's wording at the
boundary, "addr > MIN(lds_size, m0)", is not exact enough to rely on there).

Ordering between threads. A console workgroup that fits one wave runs its lanes in lockstep, and a compiler may drop
barriers there; a desktop workgroup may span several waves, so two accesses of different threads to one LDS address,
one of them a write, must be separated by s_barrier. The walk tracks the accesses since the last barrier on every path
(st.lds_epoch, joined over branches and loops by control_flow.program) and refuses an access that may conflict with one
of them. Two accesses do not conflict when both are reads, both are the same atomic operation, or both are private: the
address is S * (flattened local id) + C with every window of the pair inside one stride S, so different threads touch
disjoint bytes. In a one-thread workgroup nothing conflicts. A read is emitted at the address an active lane computes
(lanes.active_value), so inactive threads read where the active ones do; its result is masked as any VGPR write.

Uniformity. A read at an address that is the same on every thread of the workgroup (the uniformity lattice of
control_flow.uniform_names, checked once the text is complete) returns one word to every thread: such an access is
shared, so no write can be in its epoch, and everything written before the barrier that opened it is visible. Its
name is a root of the lattice (st.lds_reads), so v_readfirstlane_b32 of it is lowered (C-7).

Wait counts. A ds_read result is outstanding until s_waitcnt lgkmcnt(0) (st.pending, as a scalar load's); any
instruction that names the register before that is refused (tools/compute_aot.py).

s_barrier becomes GroupMemoryBarrierWithGroupSync(). HLSL requires it in workgroup-uniform flow: tools/compute_aot.py
checks that every condition of an enclosing if and every break condition of an enclosing loop is in the uniformity
lattice, and that a skipped region (s_cbranch_execz) holding a barrier is in no loop and holds every barrier of the
program (a wave that skips it does not take part, so its later barriers would pair with the others' earlier ones).

Refused: GDS, ds_swizzle_b32, ds_permute_b32 and ds_bpermute_b32 (they read other lanes), ds_append/ds_consume and the
ordered-count and GWS forms, the returning atomics and every other DS form.
"""
import re

from ..dispatch import form
from ..registers import vector_u32, vgprs
from .lanes import active_value
from .mubuf import sub_dword_word
from .stores import guarded

D3D12_GROUPSHARED_LIMIT = 32768


def helpers(size):
    return f"""groupshared uint lds[{size // 4}];
uint lds_address(uint base, uint offset) {{
    uint address = base + offset;
    return address < base ? 0xffffffffu : address;
}}
uint lds_load32(uint address) {{
    return address < {size}u ? lds[address >> 2] : 0u;
}}
void lds_store32(uint address, uint value) {{
    if (address < {size}u) lds[address >> 2] = value;
}}
uint lds_load_sub(uint address, uint bytes) {{
    if (address >= {size}u) return 0u;
    uint word = lds[address >> 2] >> ((address & 3u) * 8u);
    return bytes == 1u ? word & 0xffu : word & 0xffffu;
}}
void lds_store_sub(uint address, uint bytes, uint value) {{
    if (address >= {size}u) return;
    uint shift = (address & 3u) * 8u;
    uint mask = (bytes == 1u ? 0xffu : 0xffffu) << shift;
    uint ignored;
    InterlockedAnd(lds[address >> 2], ~mask, ignored);
    InterlockedOr(lds[address >> 2], (value << shift) & mask, ignored);
}}
void lds_atomic(uint op, uint address, uint value) {{
    if (address >= {size}u) return;
    uint index = address >> 2;
    if (op == 0u) InterlockedAdd(lds[index], value);
    else if (op == 1u) InterlockedAdd(lds[index], 0u - value);
    else if (op == 2u) InterlockedMin(lds[index], value);
    else if (op == 3u) InterlockedMax(lds[index], value);
    else if (op == 4u) InterlockedAnd(lds[index], value);
    else if (op == 5u) InterlockedOr(lds[index], value);
    else if (op == 6u) InterlockedXor(lds[index], value);
    else {{
        uint seen = lds[index];
        [allow_uav_condition] while (true) {{
            bool keep = op == 7u ? asint(seen) <= asint(value) : asint(seen) >= asint(value);
            if (keep) break;
            uint before;
            InterlockedCompareExchange(lds[index], seen, value, before);
            if (before == seen) break;
            seen = before;
        }}
    }}
}}
"""


# Atomics without return: name -> lds_atomic op (7 and 8 are the signed min and max, a compare-exchange loop).
ATOMICS = {"add_u32": 0, "sub_u32": 1, "min_u32": 2, "max_u32": 3, "and_b32": 4, "or_b32": 5, "xor_b32": 6,
           "min_i32": 7, "max_i32": 8}
# Single-address reads and writes: name -> (bytes, dwords); sub-dword reads -> the mubuf sub_dword_word name.
READS = {"b32": (4, 1), "b64": (8, 2), "b96": (12, 3), "b128": (16, 4)}
SUB_READS = {"u8": (1, "ubyte"), "i8": (1, "sbyte"), "u16": (2, "ushort"), "i16": (2, "sshort")}
WRITES = {"b32": (4, 1), "b64": (8, 2), "b96": (12, 3), "b128": (16, 4)}
SUB_WRITES = {"b8": 1, "b16": 2}
ALIGNMENT = {1: 1, 2: 2, 4: 4, 8: 8, 12: 16, 16: 16}


# --- Address analysis on the HLSL text ----------------------------------------------------------------------------
TOKEN = re.compile(r"\s*(?:(0x[0-9a-fA-F]+|\d+)u?(?![\w.])|(\d+\.\d*(?:e[-+]?\d+)?f?)|([A-Za-z_]\w*)|(<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^~!?:()<>\[\],.]))")
BINARY = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6, "<": 7, ">": 7, "<=": 7, ">=": 7,
          "<<": 8, ">>": 8, "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}
ASSIGN = re.compile(r"\s*(?:precise\s+)?(?:(?:float|uint|int|bool)[234]?\s+)?([A-Za-z_]\w*)(\.\w+)?\s*=(?!=)\s*(.*);")
ANY_ASSIGN = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?:\.\w+)?\s*(?:[-+*/%|&^]|<<|>>)?=(?!=)")


def tokens(text):
    out, at = [], 0
    while at < len(text):
        if text[at:].strip() == "":
            break
        m = TOKEN.match(text, at)
        if not m:
            raise ValueError
        at = m.end()
        if m[1]:
            out.append(("num", int(m[1], 0)))
        elif m[2]:
            out.append(("opaque", m[2]))
        elif m[3]:
            out.append(("name", m[3]))
        else:
            out.append(("op", m[4]))
    return out


def parse(text):
    """A tree of the expression: ("num", n), ("name", text), ("bin", op, a, b), ("un", op, a), ("sel", c, a, b),
    ("call", name, args), ("opaque",). Raises ValueError on text it does not read."""
    toks = tokens(text)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else ("end", None)

    def take(kind=None, value=None):
        tok = peek()
        if (kind and tok[0] != kind) or (value is not None and tok[1] != value):
            raise ValueError
        pos[0] += 1
        return tok

    def primary():
        tok = take()
        if tok[0] == "num":
            node = ("num", tok[1] & 0xffffffff)
        elif tok[0] == "opaque":
            node = ("opaque",)
        elif tok[0] == "name":
            name = tok[1]
            if peek() == ("op", "("):
                take()
                args = []
                if peek() != ("op", ")"):
                    args.append(expression(0))
                    while peek() == ("op", ","):
                        take()
                        args.append(expression(0))
                take("op", ")")
                node = ("call", name, args)
            else:
                node = ("name", name)
        elif tok == ("op", "("):
            node = expression(0)
            take("op", ")")
        elif tok[0] == "op" and tok[1] in ("-", "!", "~"):
            node = ("un", tok[1], primary())
        else:
            raise ValueError
        while peek() in (("op", "."), ("op", "[")):
            if take()[1] == ".":
                component = take("name")[1]
                node = ("name", f"{node[1]}.{component}") if node[0] == "name" else ("opaque",)
            else:
                expression(0)
                take("op", "]")
                node = ("opaque",)
        return node

    def expression(level):
        left = primary()
        while True:
            tok = peek()
            if tok[0] == "op" and tok[1] == "?" and level == 0:
                take()
                a = expression(0)
                take("op", ":")
                b = expression(0)
                left = ("sel", left, a, b)
                continue
            if tok[0] != "op" or tok[1] not in BINARY or BINARY[tok[1]] <= level:
                return left
            take()
            left = ("bin", tok[1], left, expression(BINARY[tok[1]]))

    tree = expression(0)
    if pos[0] != len(toks):
        raise ValueError
    return tree


class Addresses:
    """The HLSL text's definitions, read once per access: a name assigned once is its definition; a masked write whose
    lane bit the current EXEC bit implies is its new word (what an active lane holds); any other name is opaque, except
    that the trailing zero bits of a name assigned several times (a join variable) are those every assignment has."""

    def __init__(self, st):
        from ..control_flow import implies
        self.st = st
        self.single, self.multi, counts = {}, {}, {}
        for text in st.lines:
            for m in ANY_ASSIGN.finditer(text):
                counts[m[1]] = counts.get(m[1], 0) + 1
        for text in st.lines:
            if (m := ASSIGN.fullmatch(text)) and not m[2]:
                (self.single if counts.get(m[1]) == 1 else self.multi).setdefault(m[1], []).append(m[3])
        self.masked = {name: new for name, (bit, new) in st.masked.items() if implies(st.lines, st.ex, {bit})}
        self.trees, self.tz_memo, self.affine_memo = {}, {}, {}

    def tree(self, text):
        if text not in self.trees:
            try:
                self.trees[text] = parse(text)
            except ValueError:
                self.trees[text] = ("opaque",)
        return self.trees[text]

    def definition(self, name):
        if name in self.masked:
            return self.tree(self.masked[name])
        if name in self.single:
            return self.tree(self.single[name][0])
        return None

    def const(self, node, depth=0):
        """The 32-bit value of a constant expression, or None."""
        if depth > 64:
            return None
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "name":
            definition = self.definition(node[1])
            return None if definition is None else self.const(definition, depth + 1)
        if kind == "un" and node[1] in ("-", "~"):
            value = self.const(node[2], depth + 1)
            return None if value is None else (-value if node[1] == "-" else ~value) & 0xffffffff
        if kind == "bin" and node[1] in ("+", "-", "*", "&", "|", "^", "<<", ">>"):
            a, b = self.const(node[2], depth + 1), self.const(node[3], depth + 1)
            if a is None or b is None or (node[1] in ("<<", ">>") and b > 31):
                return None
            return {"+": a + b, "-": a - b, "*": a * b, "&": a & b, "|": a | b, "^": a ^ b, "<<": a << b,
                    ">>": a >> b}[node[1]] & 0xffffffff
        return None

    def tz(self, node, depth=0):
        """Known trailing zero bits of a 32-bit value (32 for zero)."""
        if depth > 64:
            return 0
        if (value := self.const(node)) is not None:
            return 32 if value == 0 else (value & -value).bit_length() - 1
        kind = node[0]
        if kind == "num":
            value = node[1]
            return 32 if value == 0 else (value & -value).bit_length() - 1
        if kind == "name":
            name = node[1]
            if name in self.tz_memo:
                return self.tz_memo[name]
            definition = self.definition(name)
            if definition is not None:
                self.tz_memo[name] = 0
                value = self.tz(definition, depth + 1)
            elif name in self.multi:
                # A join variable: optimistic for the cycle through itself, then the least over its assignments,
                # repeated until it no longer drops (it only drops, so this ends).
                value = 32
                while True:
                    self.tz_memo[name] = value
                    lower = min(self.tz(self.tree(rhs), depth + 1) for rhs in self.multi[name])
                    if lower >= value:
                        break
                    value = lower
                    for other in list(self.tz_memo):
                        if other != name and other in self.multi:
                            del self.tz_memo[other]
            else:
                value = 0
            self.tz_memo[name] = value
            return value
        if kind == "bin":
            op, a, b = node[1:]
            shift = self.const(b) if op in ("<<", ">>") else None
            if op == "<<" and shift is not None and shift < 32:
                return min(32, self.tz(a, depth + 1) + shift)
            if op == ">>" and shift is not None and shift < 32:
                t = self.tz(a, depth + 1)
                return 32 if t == 32 else max(0, t - shift)
            if op == "*":
                return min(32, self.tz(a, depth + 1) + self.tz(b, depth + 1))
            if op in ("+", "-", "|", "^"):
                return min(self.tz(a, depth + 1), self.tz(b, depth + 1))
            if op == "&":
                return max(self.tz(a, depth + 1), self.tz(b, depth + 1))
            return 0
        if kind == "sel":
            return min(self.tz(node[2], depth + 1), self.tz(node[3], depth + 1))
        if kind == "call" and node[1] in ("min", "max") and len(node[2]) == 2:
            return min(self.tz(arg, depth + 1) for arg in node[2])
        return 0

    def affine(self, node, depth=0):
        """The value as exact integers {"": constant, "local_id.x": coefficient, ...} over the local ids, or None."""
        if depth > 64:
            return None
        if (value := self.const(node)) is not None:
            return {"": value}
        kind = node[0]
        if kind == "name":
            name = node[1]
            if name in ("local_id.x", "local_id.y", "local_id.z"):
                return {"": 0, name: 1}
            definition = self.definition(name)
            return None if definition is None else self.affine(definition, depth + 1)
        if kind != "bin":
            return None
        op, a, b = node[1:]
        left = self.affine(a, depth + 1)
        if left is None:
            return None
        right = self.affine(b, depth + 1)
        if right is None:
            return None
        if op in ("+", "-"):
            sign = 1 if op == "+" else -1
            return {k: left.get(k, 0) + sign * right.get(k, 0) for k in set(left) | set(right)}
        constant = right if set(right) == {""} else left if set(left) == {""} else None
        other = left if constant is right else right
        if constant is None:
            return None
        if op == "*":
            return {k: v * constant[""] for k, v in other.items()}
        if op == "<<" and constant is right and right[""] < 32:
            return {k: v << right[""] for k, v in left.items()}
        return None


def analyse(st, word):
    """(trailing zero bits, affine form or None) of an address word, as an active lane holds it."""
    addresses = Addresses(st)
    tree = addresses.tree(word)
    return addresses.tz(tree), addresses.affine(tree)


def footprint(st, affine, low, high):
    """("private", stride, low, high) when the bytes [low, high) of the access, relative to the address's constant
    part, sit at stride * (flattened local id): every thread then touches its own bytes. ("shared",) otherwise."""
    if affine is None or any(k not in ("", "local_id.x", "local_id.y", "local_id.z") for k in affine):
        return ("shared",)
    nx, ny, nz = st.numthreads
    stride, step = None, 1
    for axis, n in zip("xyz", (nx, ny, nz)):
        coefficient = affine.get(f"local_id.{axis}", 0)
        if n == 1:
            step *= n
            continue
        if stride is None:
            if coefficient <= 0 or step != 1:
                return ("shared",)
            stride = coefficient
        elif coefficient != stride * step:
            return ("shared",)
        step *= n
    if stride is None:
        return ("shared",)
    base = affine[""]
    if base + low < 0 or base + stride * (nx * ny * nz - 1) + high > 1 << 32:
        return ("shared",)  # the 32-bit address wraps: the HLSL value is not the integer
    return ("private", stride, base + low, base + high)


def conflict(a, b, threads):
    """Whether two accesses of different threads of a `threads`-thread group, with no barrier between, may touch one
    byte with a write. Private accesses of one stride S conflict when S * d + [lo_a, hi_a) meets [lo_b, hi_b) for a
    thread distance d other than 0 that the group has."""
    (kind_a, place_a), (kind_b, place_b) = a, b
    if kind_a == "r" and kind_b == "r":
        return False
    if kind_a == kind_b and kind_a.startswith("a"):
        return False
    if place_a[0] == place_b[0] == "private" and place_a[1] == place_b[1]:
        stride, lo_a, hi_a, lo_b, hi_b = place_a[1], *place_a[2:], *place_b[2:]
        # Overlap for distance d: lo_b - hi_a < stride * d < hi_b - lo_a.
        first = (lo_b - hi_a) // stride + 1
        last = -((lo_a - hi_b) // stride) - 1
        first, last = max(first, 1 - threads), min(last, threads - 1)
        return any(d != 0 for d in range(first, last + 1)) if last - first < 3 else first <= last
    return True


def access(st, i, kind, word, offsets, size):
    """Check one DS instruction's accesses (kind "r", "w" or "a<op>"; byte offsets of its elements of `size` bytes from
    the address word) and record them in the epoch. Returns nothing; raises ValueError to refuse."""
    if st.stage != "compute":
        raise ValueError("LDS (groupshared) access is lowered in the compute stage only (C-6)")
    if not st.lds_size:
        raise ValueError("LDS access in a program without an LDS allocation (contract lds_size)")
    if st.wqm:
        raise ValueError("LDS access in whole-quad mode")
    zeros, affine = analyse(st, word)
    align = ALIGNMENT[size]
    if zeros < align.bit_length() - 1 or any(offset % align for offset in offsets):
        raise ValueError(f"LDS address alignment to {align} bytes is not provable (unaligned LDS access depends on the "
                         "alignment mode)")
    if affine is not None and set(affine) == {""}:
        for offset in offsets:
            if not 0 <= affine[""] + offset <= st.lds_size - size:
                raise ValueError("LDS access outside the allocation at a translation-time address")
    if st.workgroup_threads == 1:
        return
    records = [(kind, footprint(st, affine, offset, offset + size)) for offset in offsets]
    for record in records:
        for other in (*st.lds_epoch, *records):
            if conflict(record, other, st.workgroup_threads):
                raise ValueError(f"Instruction {i}: LDS access may race with another thread's access to the same bytes "
                                 "without s_barrier between (a console wave runs in lockstep, desktop threads do not)")
    st.lds_epoch = st.lds_epoch | frozenset(records)


def prepare(st):
    st.declarations.setdefault("lds", helpers(st.lds_size))


def address_word(st, token):
    return vector_u32(token, st.scalar, st.vector, st.pending, st.sample_pending)


def check_destinations(st, dsts):
    if any(d in st.sample_dest for d in dsts):
        raise ValueError("Write overlaps an outstanding load")


def emit_reads(st, i, dsts, word, offsets, size):
    """Each dword of each element at word + offset, as an active lane computes the address; dsts outstanding."""
    if st.ex != "true":
        word = active_value(st, i, word)
    names = []
    for e, offset in enumerate(offsets):
        for j in range(size // 4):
            name = f"ldw{i}_{len(names)}"
            st.lines.append(f"    uint {name} = lds_load32(lds_address({word}, {offset + 4 * j}u));")
            names.append(name)
    for d, name in zip(dsts, names):
        st.vector[d] = ("uint", name)
        st.lds_reads[name] = word
    st.pending.update(dsts)


OFFSET = r"(?: offset:(\d+))?"


@form(r"ds_read_(b32|b64|b96|b128) (v\d+|v\[\d+:\d+\]), (v\d+)" + OFFSET)
def ds_read(st, i, m):
    op, dst_token, addr, offset = m.groups()
    size, count = READS[op]
    dsts = vgprs(dst_token, count)
    word = address_word(st, addr)
    offset = int(offset or 0)
    if offset > 0xffff:
        raise ValueError("Invalid DS offset")
    access(st, i, "r", word, [offset], size)
    check_destinations(st, dsts)
    prepare(st)
    emit_reads(st, i, dsts, word, [offset], size)


@form(r"ds_read_(u8|i8|u16|i16) (v\d+), (v\d+)" + OFFSET)
def ds_read_sub(st, i, m):
    op, dst, addr, offset = m.groups()
    size, name = SUB_READS[op]
    word = address_word(st, addr)
    offset = int(offset or 0)
    if offset > 0xffff:
        raise ValueError("Invalid DS offset")
    access(st, i, "r", word, [offset], size)
    check_destinations(st, [dst])
    prepare(st)
    if st.ex != "true":
        word = active_value(st, i, word)
    raw = f"lds_load_sub(lds_address({word}, {offset}u), {size}u)"
    st.lines.append(f"    uint ldw{i}_0 = {sub_dword_word(name, raw, None)};")
    st.vector[dst] = ("uint", f"ldw{i}_0")
    st.lds_reads[f"ldw{i}_0"] = word
    st.pending.add(dst)


@form(r"ds_read2(st64)?_(b32|b64) (v\[\d+:\d+\]), (v\d+)(?: offset0:(\d+))?(?: offset1:(\d+))?")
def ds_read2(st, i, m):
    st64, op, dst_token, addr, offset0, offset1 = m.groups()
    size = 4 if op == "b32" else 8
    dsts = vgprs(dst_token, 2 * size // 4)
    step = size * (64 if st64 else 1)
    offsets = [int(offset0 or 0), int(offset1 or 0)]
    if max(offsets) > 0xff:
        raise ValueError("Invalid DS offset")
    offsets = [step * n for n in offsets]
    word = address_word(st, addr)
    access(st, i, "r", word, offsets, size)
    check_destinations(st, dsts)
    prepare(st)
    emit_reads(st, i, dsts, word, offsets, size)


def store_data(st, token, count):
    return [vector_u32(d, st.scalar, st.vector, st.pending, st.sample_pending) for d in vgprs(token, count)]


def emit_store(st, text):
    st.lines.append(guarded(st, f"    {text}"))


@form(r"ds_write_(b32|b64|b96|b128) (v\d+), (v\d+|v\[\d+:\d+\])" + OFFSET)
def ds_write(st, i, m):
    op, addr, data_token, offset = m.groups()
    size, count = WRITES[op]
    word = address_word(st, addr)
    data = store_data(st, data_token, count)
    offset = int(offset or 0)
    if offset > 0xffff:
        raise ValueError("Invalid DS offset")
    access(st, i, "w", word, [offset], size)
    prepare(st)
    for j, value in enumerate(data):
        emit_store(st, f"lds_store32(lds_address({word}, {offset + 4 * j}u), {value});")


@form(r"ds_write_(b8|b16) (v\d+), (v\d+)" + OFFSET)
def ds_write_sub(st, i, m):
    op, addr, data_token, offset = m.groups()
    size = SUB_WRITES[op]
    word = address_word(st, addr)
    value, = store_data(st, data_token, 1)
    offset = int(offset or 0)
    if offset > 0xffff:
        raise ValueError("Invalid DS offset")
    access(st, i, "w", word, [offset], size)
    prepare(st)
    emit_store(st, f"lds_store_sub(lds_address({word}, {offset}u), {size}u, {value});")


@form(r"ds_write2(st64)?_(b32|b64) (v\d+), (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\])(?: offset0:(\d+))?(?: offset1:(\d+))?")
def ds_write2(st, i, m):
    st64, op, addr, data0, data1, offset0, offset1 = m.groups()
    size = 4 if op == "b32" else 8
    step = size * (64 if st64 else 1)
    offsets = [int(offset0 or 0), int(offset1 or 0)]
    if max(offsets) > 0xff:
        raise ValueError("Invalid DS offset")
    offsets = [step * n for n in offsets]
    word = address_word(st, addr)
    data = [store_data(st, token, size // 4) for token in (data0, data1)]
    access(st, i, "w", word, offsets, size)
    prepare(st)
    # Element 0 then element 1, as the ISA's pseudo-code writes them: with equal offsets the second one stays.
    for offset, words in zip(offsets, data):
        for j, value in enumerate(words):
            emit_store(st, f"lds_store32(lds_address({word}, {offset + 4 * j}u), {value});")


@form(r"ds_(" + "|".join(ATOMICS) + r") (v\d+), (v\d+)" + OFFSET)
def ds_atomic(st, i, m):
    op, addr, data_token, offset = m.groups()
    word = address_word(st, addr)
    value, = store_data(st, data_token, 1)
    offset = int(offset or 0)
    if offset > 0xffff:
        raise ValueError("Invalid DS offset")
    access(st, i, f"a{op}", word, [offset], 4)
    prepare(st)
    emit_store(st, f"lds_atomic({ATOMICS[op]}u, lds_address({word}, {offset}u), {value});")


@form(r"s_barrier")
def barrier(st, i, m):
    if st.stage != "compute":
        raise ValueError("s_barrier is lowered in the compute stage only (C-6)")
    st.lines.append("    GroupMemoryBarrierWithGroupSync();")
    st.lds_epoch = frozenset()
