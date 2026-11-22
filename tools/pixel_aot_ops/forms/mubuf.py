"""MUBUF: buffer loads of whole dwords through a runtime V#."""
import re

from ..dispatch import form
from ..registers import registers, vector_u32, vgprs


@form(r"buffer_load_dword(x[234])? (v\d+|v\[\d+:\d+\]), (off|v\d+|v\[\d+:\d+\]), (s\[\d+:\d+\]), (s\d+|0|off)((?: \S+)*)")
def buffer_load(st, i, m):
    # MUBUF loads of whole dwords through a runtime V#. glc, slc and dlc select cache behavior and do not change
    # the loaded value; tfe, lds and every other modifier are refused.
    width, dst_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    count = int(width[1]) if width else 1
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
        else:
            raise ValueError(f"Unsupported buffer load modifier {modifier}")
    if st.mask != "entry" or inst_offset > 4095:
        raise ValueError("Invalid buffer load")
    offen, idxen = "offen" in flags, "idxen" in flags
    dsts = vgprs(dst_token, count)
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
    if any(d in st.sample_dest for d in dsts):
        raise ValueError("Write overlaps an outstanding sample")
    st.uses_memory = True
    st.lines.append(f"    uint4 rsrc{i} = uint4({', '.join(words)});")
    for j, d in enumerate(dsts):
        st.lines.append(f"    uint mem{i}_{j} = buffer_load32(rsrc{i}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {j}u);")
        st.vector[d] = ("uint", f"mem{i}_{j}")
    st.sample_dest.update(dsts)
    st.sample_pending = True
