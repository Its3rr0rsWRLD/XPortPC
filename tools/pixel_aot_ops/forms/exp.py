"""Color export and the v_cvt_pkrtz_f16_f32 packing that feeds it."""
import re

from ..dispatch import form
from ..registers import fp_operand, tracked_word


@form(r"v_cvt_pkrtz_f16_f32_e32 (v\d+), (v\d+), (v\d+)")
def pack_e32(st, i, m):
    dst, lo, hi = m.groups()
    pair = []
    for n, register in enumerate((lo, hi)):
        value = st.vector[register]
        if isinstance(value, tuple) and tracked_word(value) is not None:
            # A raw word is exported as the float with those bits; the export is where it becomes a float.
            st.lines.append(f"    precise float alu{i}_{n} = asfloat({value[1]});")
            value = f"alu{i}_{n}"
        pair.append(value)
    if st.ex != "true" or st.sample_pending or not all(isinstance(v, str) and v.startswith(("sample", "alu")) for v in pair):
        raise ValueError("Unsupported pack operand")
    st.vector[dst] = tuple(pair)


@form(r"v_cvt_pkrtz_f16_f32_e64 (v\d+), ([^, ]+), ([^, ]+?)( clamp)?")
def pack_e64(st, i, m):
    # The VOP3 form of the pack above, with the same operand rules: numeric sources only, entry mask, no pending
    # sample. A source may also be an SGPR holding a numeric word, an inline constant or a literal, and carries
    # neg and abs, which act on the binary32 value before the conversion (the packed halves are not modified).
    # clamp is refused: the only evidence of its effect is LLVM issue 60591, which says the hardware ignores
    # clamp and omod on this instruction on GFX10.3, a single report not measured on gfx1013 and not in the
    # ISA text. omod and op_sel do not match this grammar. https://github.com/llvm/llvm-project/issues/60591
    dst, *tokens, clamp = m.groups()
    if clamp:
        raise ValueError("clamp on v_cvt_pkrtz_f16_f32_e64 is refused: its hardware behaviour is unverified "
                         "(LLVM issue 60591 reports it is ignored on GFX10.3)")
    if st.ex != "true" or st.sample_pending or dst in st.sample_dest:
        raise ValueError("Unsupported pack operand")
    pair = []
    for n, token in enumerate(tokens):
        for register in re.findall(r"[vs]\d+", token):
            if tracked_word((st.vector if register.startswith("v") else st.scalar).get(register)) is None:
                raise ValueError(f"Unsupported pack operand {register}")
        st.lines.append(f"    precise float alu{i}_{n} = {fp_operand(token, st.scalar, st.vector, st.pending, st.sample_pending)};")
        pair.append(f"alu{i}_{n}")
    st.vector[dst] = tuple(pair)


@form(r"exp mrt0,? (v\d+), \1, (v\d+), \2 done compr vm")
def export(st, i, m):
    pairs = [st.vector[v] for v in m.groups()]
    if st.ex != "true" or st.exported or not all(isinstance(p, tuple) and len(p)==2 and
            all(v.startswith(("sample", "alu")) for v in p) for p in pairs):
        raise ValueError("Unsupported export")
    args = [f"export16({v})" for pair in pairs for v in pair]
    st.lines.append(f"    return float4({', '.join(args)});")
    st.exported = True
