"""MTBUF: typed buffer loads whose format is a field of the instruction."""
import re

from ..dispatch import form
from ..registers import vgprs
from .mubuf import OPERANDS, buffer_operands, finish_load

# gfx10 unified buffer formats by LLVM's name (AMDGPU::UfmtGFX10, 1..77; 0 is INVALID). hlsl.buffer_load_format decodes
# every one; the pixel stage accepts only the two whose conversion its draws check (EXACT), the vertex stage all of them
# (tests/vertex_aot_check.py, family typed).
FORMATS = {
    "BUF_FMT_8_UNORM": 1, "BUF_FMT_8_SNORM": 2, "BUF_FMT_8_USCALED": 3, "BUF_FMT_8_SSCALED": 4,
    "BUF_FMT_8_UINT": 5, "BUF_FMT_8_SINT": 6, "BUF_FMT_16_UNORM": 7, "BUF_FMT_16_SNORM": 8,
    "BUF_FMT_16_USCALED": 9, "BUF_FMT_16_SSCALED": 10, "BUF_FMT_16_UINT": 11, "BUF_FMT_16_SINT": 12,
    "BUF_FMT_16_FLOAT": 13, "BUF_FMT_8_8_UNORM": 14, "BUF_FMT_8_8_SNORM": 15, "BUF_FMT_8_8_USCALED": 16,
    "BUF_FMT_8_8_SSCALED": 17, "BUF_FMT_8_8_UINT": 18, "BUF_FMT_8_8_SINT": 19, "BUF_FMT_32_UINT": 20,
    "BUF_FMT_32_SINT": 21, "BUF_FMT_32_FLOAT": 22, "BUF_FMT_16_16_UNORM": 23, "BUF_FMT_16_16_SNORM": 24,
    "BUF_FMT_16_16_USCALED": 25, "BUF_FMT_16_16_SSCALED": 26, "BUF_FMT_16_16_UINT": 27, "BUF_FMT_16_16_SINT": 28,
    "BUF_FMT_16_16_FLOAT": 29, "BUF_FMT_10_11_11_UNORM": 30, "BUF_FMT_10_11_11_SNORM": 31, "BUF_FMT_10_11_11_USCALED": 32,
    "BUF_FMT_10_11_11_SSCALED": 33, "BUF_FMT_10_11_11_UINT": 34, "BUF_FMT_10_11_11_SINT": 35, "BUF_FMT_10_11_11_FLOAT": 36,
    "BUF_FMT_11_11_10_UNORM": 37, "BUF_FMT_11_11_10_SNORM": 38, "BUF_FMT_11_11_10_USCALED": 39, "BUF_FMT_11_11_10_SSCALED": 40,
    "BUF_FMT_11_11_10_UINT": 41, "BUF_FMT_11_11_10_SINT": 42, "BUF_FMT_11_11_10_FLOAT": 43, "BUF_FMT_10_10_10_2_UNORM": 44,
    "BUF_FMT_10_10_10_2_SNORM": 45, "BUF_FMT_10_10_10_2_USCALED": 46, "BUF_FMT_10_10_10_2_SSCALED": 47, "BUF_FMT_10_10_10_2_UINT": 48,
    "BUF_FMT_10_10_10_2_SINT": 49, "BUF_FMT_2_10_10_10_UNORM": 50, "BUF_FMT_2_10_10_10_SNORM": 51, "BUF_FMT_2_10_10_10_USCALED": 52,
    "BUF_FMT_2_10_10_10_SSCALED": 53, "BUF_FMT_2_10_10_10_UINT": 54, "BUF_FMT_2_10_10_10_SINT": 55, "BUF_FMT_8_8_8_8_UNORM": 56,
    "BUF_FMT_8_8_8_8_SNORM": 57, "BUF_FMT_8_8_8_8_USCALED": 58, "BUF_FMT_8_8_8_8_SSCALED": 59, "BUF_FMT_8_8_8_8_UINT": 60,
    "BUF_FMT_8_8_8_8_SINT": 61, "BUF_FMT_32_32_UINT": 62, "BUF_FMT_32_32_SINT": 63, "BUF_FMT_32_32_FLOAT": 64,
    "BUF_FMT_16_16_16_16_UNORM": 65, "BUF_FMT_16_16_16_16_SNORM": 66, "BUF_FMT_16_16_16_16_USCALED": 67, "BUF_FMT_16_16_16_16_SSCALED": 68,
    "BUF_FMT_16_16_16_16_UINT": 69, "BUF_FMT_16_16_16_16_SINT": 70, "BUF_FMT_16_16_16_16_FLOAT": 71, "BUF_FMT_32_32_32_UINT": 72,
    "BUF_FMT_32_32_32_SINT": 73, "BUF_FMT_32_32_32_FLOAT": 74, "BUF_FMT_32_32_32_32_UINT": 75, "BUF_FMT_32_32_32_32_SINT": 76,
    "BUF_FMT_32_32_32_32_FLOAT": 77,
}
EXACT = {"BUF_FMT_32_UINT": 20, "BUF_FMT_32_SINT": 21}


@form(r"tbuffer_load_format_(x|xy|xyz|xyzw) (v\d+|v\[\d+:\d+\]), " + OPERANDS)
def tbuffer_load_format(st, i, m):
    # The format is the `format:` field, not the V#, so it is known at translation time. The pixel stage refuses any
    # format but 32_UINT and 32_SINT (as a name or its number); the vertex stage takes every valid one. A missing field
    # means the default format, which is refused in both. The V# DST_SEL still places the component. The d16 variants are not lowered.
    comps, dst_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
    fmt = [t for t in modifiers.split() if t.startswith("format:")]
    if len(fmt) != 1:
        raise ValueError("A tbuffer load needs exactly one format: field")
    name = fmt[0][len("format:"):]
    known = FORMATS if st.all_buffer_formats else EXACT
    if (name := name[1:-1] if name.startswith("[") and name.endswith("]") else name) in known:
        number = known[name]
    elif re.fullmatch(r"\d+", name) and int(name) in known.values():
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
