"""Stores from pixel shaders through title memory: MUBUF buffer_store_* (dwords, bytes, halves and the typed
buffer_store_format_x..xyzw), MTBUF tbuffer_store_format_x..xyzw and GLOBAL global_store_*.

A store writes memory, which the masked-write rule of lower() cannot undo, so it is lowered only while this lane is
provably active and the wave is not in whole-quad mode (st.ex == "true", not st.wqm; control-flow.md, CF-2a): an
inactive or helper lane must not write. Desktop helper invocations never write UAVs, as console helper lanes outside
EXEC never do. Addresses follow the load rules of hlsl.MEMORY_HELPERS: a dword (or a dword of a dwordx2..x4) that a V#
puts out of range, an offset sum that wraps, an unmodelled V# (swizzle, add-tid) and a title-memory lookup miss write
nothing. A byte or half is written byte by byte, each byte with an atomic and/or pair on its dword, so lanes that
write different bytes of one dword do not overwrite each other's bytes. Typed stores write their single dword only for
the 32_UINT (20) and 32_SINT (21) formats, whose one component is the raw X word; the other components are not stored.
Any other V# format stores nothing (as the typed load reads zero), and tbuffer_store refuses it at translation time.
The d16 typed stores are not lowered."""
import re

from ..dispatch import form
from ..registers import vector_u32, vgprs
from .flat import global_operands
from .mtbuf import EXACT as FORMATS  # typed stores: the two 32-bit integer formats only
from .mubuf import OPERANDS, buffer_operands

STORE_HELPERS = """bool buffer_dword_address(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint dword, out uint2 address) {
    uint stride = (rsrc.y >> 16) & 0x3fffu;
    uint num_records = rsrc.z;
    uint oob_select = (rsrc.w >> 28) & 3u;
    bool unmodelled = (rsrc.y >> 31) != 0u || ((rsrc.w >> 23) & 1u) != 0u;
    uint partial = voffset + inst_offset;
    uint offset = partial + 4u * dword;
    bool wrapped = partial < voffset || offset < partial;
    bool in_range;
    if (oob_select == 0u) in_range = index < num_records && offset < stride;
    else if (oob_select == 1u) in_range = index < num_records;
    else if (oob_select == 2u) in_range = num_records != 0u;
    else in_range = offset < num_records;
    address = add64(add64(uint2(rsrc.x, rsrc.y & 0xffffu), uint2(soffset, 0u)), add64(mul_stride(stride, index), uint2(offset, 0u)));
    return !(unmodelled || wrapped || !in_range);
}
uint2 global_address(uint2 base, uint voffset, uint2 immediate, uint dword) {
    return add64(add64(base, uint2(voffset, 0u)), add64(immediate, uint2(4u * dword, 0u)));
}
void title_store32(uint2 address, uint value) {
    uint slot;
    uint offset;
    if (TitleLookup(title_ranges, title_range_count, address, 4, slot, offset))
        title_memory[NonUniformResourceIndex(slot)].Store(offset, value);
}
void title_store8(uint2 address, uint value) {
    uint slot;
    uint offset;
    if (!TitleLookup(title_ranges, title_range_count, uint2(address.x & ~3u, address.y), 4, slot, offset)) return;
    uint shift = (address.x & 3u) * 8u;
    uint ignored;
    title_memory[NonUniformResourceIndex(slot)].InterlockedAnd(offset, ~(0xffu << shift), ignored);
    title_memory[NonUniformResourceIndex(slot)].InterlockedOr(offset, (value & 0xffu) << shift, ignored);
}
void title_store_sub(uint2 address, uint bytes, uint value) {
    title_store8(address, value);
    if (bytes == 2u) title_store8(add64(address, uint2(1u, 0u)), value >> 8);
}
void buffer_store32(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint dword, uint value) {
    uint2 address;
    if (buffer_dword_address(rsrc, soffset, voffset, inst_offset, index, dword, address)) title_store32(address, value);
}
void buffer_store_sub(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint bytes, uint value) {
    uint2 address;
    if (buffer_address(rsrc, soffset, voffset, inst_offset, index, address)) title_store_sub(address, bytes, value);
}
void buffer_store_format(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint format, uint value) {
    uint2 address;
    if ((format == 20u || format == 21u) && buffer_address(rsrc, soffset, voffset, inst_offset, index, address))
        title_store32(address, value);
}
"""

# Sub-dword stores: name -> (bytes, the data word's half that is stored: 0 low, 16 high).
SUB_STORE = {"byte": (1, 0), "byte_d16_hi": (1, 16), "short": (2, 0), "short_d16_hi": (2, 16)}


def writing(st, *, dword_store=False):
    """Refuse a memory write unless this lane is provably active outside whole-quad mode, and bind memory writable.
    The compute stage (tools/compute_aot.py, docs/design/compute-stage.md) lowers only the whole-dword
    buffer_store_dword..x4 through this module, with the same address and range rules; every other store and atomic is
    refused there until its card. In the compute stage (C-3) a store may also run while the lane may be inactive: it is
    emitted under `if (ex)` (guarded), so only an active lane writes, and HLSL flow around it stays as it was."""
    if st.stage != "pixel" and not dword_store:
        raise ValueError("This store or atomic is lowered in the pixel stage only")
    if (st.ex != "true" and st.stage == "pixel") or st.wqm:
        raise ValueError("A memory write needs this lane provably active outside whole-quad mode (CF-2a)")
    st.uses_memory = True
    st.writes_memory = True
    st.memory_helpers.setdefault("stores", STORE_HELPERS)


def guarded(st, text):
    """A store statement as emitted: under `if (ex)` while this lane may be inactive (compute stage only, see
    writing), as it is otherwise."""
    if st.ex == "true":
        return text
    if st.stage == "pixel":
        raise ValueError("A memory write needs this lane provably active (CF-2a)")
    return f"    if ({st.ex}) {text.strip()}"


def data_words(st, token, count):
    return [vector_u32(d, st.scalar, st.vector, st.pending, st.sample_pending) for d in vgprs(token, count)]


def store_value(word, half):
    return f"(({word}) >> 16)" if half else word


@form(r"buffer_store_dword(x[234])? (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def buffer_store(st, i, m):
    # Whole dwords through a runtime V#, each range-checked on its own as the loads are; glc, slc and dlc are cache
    # policy and accepted, every other modifier is refused by buffer_operands.
    width, data_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    writing(st, dword_store=True)
    words = data_words(st, data_token, int(width[1]) if width else 1)
    if any(r in st.sample_dest for r in vgprs(data_token, len(words))):
        raise ValueError("Store data overlaps an outstanding load")
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers)
    for j, word in enumerate(words):
        st.lines.append(guarded(st, f"    buffer_store32({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {j}u, {word});"))


@form(r"buffer_store_(" + "|".join(sorted(SUB_STORE, key=len, reverse=True)) + r") (v\d+), " + OPERANDS)
def buffer_store_sub(st, i, m):
    # The low byte or half of the data word, or for a d16_hi form of its high half, at any alignment; the range rule
    # applies to the offset of the first byte, as for the sub-dword loads.
    op, data_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    writing(st)
    word, = data_words(st, data_token, 1)
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers)
    size, half = SUB_STORE[op]
    st.lines.append(f"    buffer_store_sub({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {size}u, "
                    f"{store_value(word, half)});")


@form(r"buffer_store_format_(x|xy|xyz|xyzw) (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def buffer_store_format(st, i, m):
    # The format is V# word 3 bits 12 to 18, known only at runtime (see the module notes).
    comps, data_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    writing(st)
    word = data_words(st, data_token, len(comps))[0]
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers)
    st.lines.append(f"    buffer_store_format({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, "
                    f"({rsrc}.w >> 12u) & 0x7fu, {word});")


@form(r"tbuffer_store_format_(x|xy|xyz|xyzw) (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def tbuffer_store_format(st, i, m):
    # The format is the instruction's format: field: 32_UINT and 32_SINT (by name or number) are lowered, any other
    # format and a missing field (the default format) are refused.
    comps, data_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    fmt = [t for t in modifiers.split() if t.startswith("format:")]
    if len(fmt) != 1:
        raise ValueError("A tbuffer store needs exactly one format: field")
    name = fmt[0][len("format:"):]
    if (name := name[1:-1] if name.startswith("[") and name.endswith("]") else name) in FORMATS:
        number = FORMATS[name]
    elif re.fullmatch(r"\d+", name) and int(name) in FORMATS.values():
        number = int(name)
    else:
        raise ValueError(f"tbuffer format {name} is not lowered")
    rest = " ".join(t for t in modifiers.split() if not t.startswith("format:"))
    writing(st)
    word = data_words(st, data_token, len(comps))[0]
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, rest)
    st.lines.append(f"    buffer_store_format({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {number}u, {word});")


GLOBAL_STORE = r"(v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), (off|s\[\d+:\d+\])((?: \S+)*)"


@form(r"global_store_dword(x[234])? " + GLOBAL_STORE)
def global_store(st, i, m):
    # vaddr (a 64-bit pair with saddr off, or a 32-bit offset with an SGPR-pair saddr), vdata, then the signed 12-bit
    # instruction offset, as for the global loads.
    width, addr_token, data_token, saddr_token, modifiers = m.groups()
    writing(st)
    words = data_words(st, data_token, int(width[1]) if width else 1)
    base, voffset, bits = global_operands(st, addr_token, saddr_token, modifiers)
    for j, word in enumerate(words):
        st.lines.append(f"    title_store32(global_address(uint2({base[0]}, {base[1]}), {voffset}, "
                        f"uint2({bits & 0xffffffff}u, {bits >> 32}u), {j}u), {word});")


@form(r"global_store_(" + "|".join(sorted(SUB_STORE, key=len, reverse=True)) + r") " + GLOBAL_STORE)
def global_store_sub(st, i, m):
    op, addr_token, data_token, saddr_token, modifiers = m.groups()
    writing(st)
    if data_token.startswith("v["):
        raise ValueError("A sub-dword store takes one data register")
    word, = data_words(st, data_token, 1)
    base, voffset, bits = global_operands(st, addr_token, saddr_token, modifiers)
    size, half = SUB_STORE[op]
    st.lines.append(f"    title_store_sub(global_address(uint2({base[0]}, {base[1]}), {voffset}, "
                    f"uint2({bits & 0xffffffff}u, {bits >> 32}u), 0u), {size}u, {store_value(word, half)});")
