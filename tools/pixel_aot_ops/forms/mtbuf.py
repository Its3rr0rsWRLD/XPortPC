"""MTBUF: typed buffer loads whose format is a field of the instruction."""
import re

from ..dispatch import form
from ..registers import vgprs
from .mubuf import OPERANDS, buffer_operands, finish_load

# gfx10 unified buffer formats that are exact: a 32-bit integer component is the raw dword (hlsl.MEMORY_HELPERS).
FORMATS = {"BUF_FMT_32_UINT": 20, "BUF_FMT_32_SINT": 21}


@form(r"tbuffer_load_format_(x|xy|xyz|xyzw) (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def tbuffer_load_format(st, i, m):
    # The format is the `format:` field, not the V#, so it is known at translation time and any format but 32_UINT and
    # 32_SINT (as a name or its number) is refused instead of read as zero; a missing field means the default format,
    # which is refused too. The V# DST_SEL still places the component. The d16 variants are not lowered.
    comps, dst_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    fmt = [t for t in modifiers.split() if t.startswith("format:")]
    if len(fmt) != 1:
        raise ValueError("A tbuffer load needs exactly one format: field")
    name = fmt[0][len("format:"):]
    if (name := name[1:-1] if name.startswith("[") and name.endswith("]") else name) in FORMATS:
        number = FORMATS[name]
    elif re.fullmatch(r"\d+", name) and int(name) in FORMATS.values():
        number = int(name)
    else:
        raise ValueError(f"tbuffer format {name} is not lowered")
    rest = " ".join(t for t in modifiers.split() if not t.startswith("format:"))
    dsts = vgprs(dst_token, len(comps))
    rsrc, soffset, voffset, inst_offset, vindex, _ = buffer_operands(st, i, addr_token, rsrc_token, soffset_token, rest)
    finish_load(st, dsts)
    st.lines.append(f"    uint4 fmt{i} = buffer_load_format({rsrc}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {number}u);")
    for j, d in enumerate(dsts):
        st.lines.append(f"    uint mem{i}_{j} = fmt{i}[{j}];")
        st.vector[d] = ("uint", f"mem{i}_{j}")
    st.vm_issue(dsts, "mtbuf")
