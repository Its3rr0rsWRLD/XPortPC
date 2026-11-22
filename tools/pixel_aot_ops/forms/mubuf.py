"""MUBUF: buffer loads through a runtime V#: whole dwords, bytes and halves (with sign or zero extension and the d16
forms), and the typed buffer_load_format_x..xyzw for the 32-bit integer formats."""
import re

from ..dispatch import form
from ..registers import registers, vector_u32, vgprs

# Sub-dword loads: name -> (bytes, sign-extend, half written by a d16 form or None).
SUB_DWORD = {
    "ubyte": (1, False, None), "sbyte": (1, True, None), "ushort": (2, False, None), "sshort": (2, True, None),
    "ubyte_d16": (1, False, "lo"), "ubyte_d16_hi": (1, False, "hi"), "sbyte_d16": (1, True, "lo"),
    "sbyte_d16_hi": (1, True, "hi"), "short_d16": (2, False, "lo"), "short_d16_hi": (2, False, "hi"),
}


def sub_dword_word(op, raw, old):
    """The destination word of a sub-dword load of the zero-extended memory value `raw`: extended to 32 bits, or for a d16
    form extended to 16 bits and merged into one half of `old`, which keeps the other half."""
    size, signed, half = SUB_DWORD[op]
    bits = 8 * size
    word = f"asuint(asint({raw} << {32 - bits}u) >> {32 - bits}u)" if signed else raw
    if half is None:
        return word
    if half == "lo":
        return f"(({old}) & 0xffff0000u) | (({word}) & 0xffffu)"
    return f"(({old}) & 0xffffu) | ((({word}) & 0xffffu) << 16)"


def buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers, extra=()):
    """Parse the address, V#, soffset and modifiers shared by every MUBUF/MTBUF load, emit the V# declaration and return
    (rsrc name, soffset, voffset, instruction offset, vindex, modifier flags). `extra` names further accepted modifiers,
    which are returned in the flags for the caller to read."""
    flags = set()
    inst_offset = 0
    for modifier in modifiers.split():
        if bm := re.fullmatch(r"offset:(\d+)", modifier):
            if "offset" in flags:
                raise ValueError("Repeated buffer offset")
            flags.add("offset")
            inst_offset = int(bm[1])
        elif modifier in ("offen", "idxen", "glc", "slc", "dlc") and modifier not in flags:
            flags.add(modifier)
        elif modifier in extra and modifier not in flags:
            flags.add(modifier)
        else:
            raise ValueError(f"Unsupported buffer load modifier {modifier}")
    if st.ex != "true" or inst_offset > 4095:
        raise ValueError("Invalid buffer load")
    offen, idxen = "offen" in flags, "idxen" in flags
    if addr_token == "off":
        voffset = vindex = "0u"
        if offen or idxen:
            raise ValueError("Buffer address register missing")
    elif addr_token.startswith("v["):
        first, last = map(int, re.findall(r"\d+", addr_token))
        if not (offen and idxen) or last != first + 1:
            raise ValueError("Buffer address register pair needs both idxen and offen")
        vindex = vector_u32(f"v{first}", st.scalar, st.vector, st.pending, st.sample_pending)
        voffset = vector_u32(f"v{last}", st.scalar, st.vector, st.pending, st.sample_pending)
    else:
        if offen == idxen:
            raise ValueError("A single buffer address register needs exactly one of idxen and offen")
        word = vector_u32(addr_token, st.scalar, st.vector, st.pending, st.sample_pending)
        voffset, vindex = (word, "0u") if offen else ("0u", word)
    rsrc = [f"s{n}" for n in registers(*re.findall(r"\d+", rsrc_token), 4)]
    if int(rsrc[0][1:]) % 4 or int(rsrc[3][1:]) > 105:
        raise ValueError("Buffer resource registers must be four aligned scalar registers")
    words = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in rsrc]
    soffset = "0u" if soffset_token in ("0", "off") else vector_u32(soffset_token, st.scalar, st.vector, st.pending, st.sample_pending)
    st.lines.append(f"    uint4 rsrc{i} = uint4({', '.join(words)});")
    return f"rsrc{i}", soffset, voffset, inst_offset, vindex, flags


def finish_load(st, dsts):
    if any(d in st.sample_dest for d in dsts):
        raise ValueError("Write overlaps an outstanding sample")
    st.uses_memory = True


OPERANDS = r"(off|v\d+|v\[\d+:\d+\]), (s\[\d+:\d+\]), (s\d+|0|off)((?: \S+)*)"


@form(r"buffer_load_dword(x[234])? (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def buffer_load(st, i, m):
    # MUBUF loads of whole dwords through a runtime V#. glc, slc and dlc select cache behavior and do not change
    # the loaded value; tfe, lds and every other modifier are refused.
    width, dst_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    count = int(width[1]) if width else 1
    dsts = vgprs(dst_token, count)
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers)
    finish_load(st, dsts)
    for j, d in enumerate(dsts):
        st.lines.append(f"    uint mem{i}_{j} = buffer_load32({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {j}u);")
        st.vector[d] = ("uint", f"mem{i}_{j}")
    st.vm_issue(dsts, "mubuf")


@form(r"buffer_load_(" + "|".join(sorted(SUB_DWORD, key=len, reverse=True)) + r") (v\d+), " + OPERANDS)
def buffer_load_sub(st, i, m):
    # One byte or half through a runtime V#, sign- or zero-extended to the destination word. A d16 form writes one half
    # of the destination and keeps the other half of the register's earlier value, which must be set and settled.
    op, dst, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    old = vector_u32(dst, st.scalar, st.vector, st.pending, st.sample_pending) if SUB_DWORD[op][2] else None
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers)
    finish_load(st, [dst])
    raw = f"buffer_load_sub({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {SUB_DWORD[op][0]}u)"
    st.lines.append(f"    uint mem{i}_0 = {sub_dword_word(op, raw, old)};")
    st.vector[dst] = ("uint", f"mem{i}_0")
    st.vm_issue([dst], "mubuf")


@form(r"buffer_load_format_(x|xy|xyz|xyzw) (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def buffer_load_format(st, i, m):
    # Typed loads: the format comes from the V# (word 3 bits 12 to 18) and only the 32_UINT and 32_SINT formats are
    # exact (see hlsl.MEMORY_HELPERS); any other V# format reads zero. The d16 variants are not lowered.
    comps, dst_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    dsts = vgprs(dst_token, len(comps))
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, modifiers)
    finish_load(st, dsts)
    st.lines.append(f"    uint4 fmt{i} = buffer_load_format({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, "
                    f"({rsrc}.w >> 12u) & 0x7fu);")
    for j, d in enumerate(dsts):
        st.lines.append(f"    uint mem{i}_{j} = fmt{i}[{j}];")
        st.vector[d] = ("uint", f"mem{i}_{j}")
    st.vm_issue(dsts, "mubuf")
