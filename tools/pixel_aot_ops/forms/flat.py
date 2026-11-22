"""FLAT and GLOBAL: global loads of dwords, bytes and halves; flat loads are refused (a flat address may be LDS or scratch)."""
import re

from ..dispatch import form
from ..registers import sgpr_pair, vector_u32, vgprs
from .mubuf import SUB_DWORD, sub_dword_word


def global_operands(st, addr_token, saddr_token, modifiers):
    """Parse the address, saddr and modifiers of a global load: (base words, voffset, immediate offset as 64 bits)."""
    flags = set()
    immediate = 0
    for modifier in modifiers.split():
        if gm := re.fullmatch(r"offset:(-?\d+)", modifier):
            if "offset" in flags:
                raise ValueError("Repeated global offset")
            flags.add("offset")
            immediate = int(gm[1])
        elif modifier in ("glc", "slc", "dlc") and modifier not in flags:
            flags.add(modifier)
        else:
            raise ValueError(f"Unsupported global load modifier {modifier}")
    if st.ex != "true" or not -2048 <= immediate <= 2047:
        raise ValueError("Invalid global load")
    if saddr_token == "off":
        if not addr_token.startswith("v["):
            raise ValueError("Global load without saddr needs a 64-bit address register pair")
        first, last = map(int, re.findall(r"\d+", addr_token))
        if last != first + 1:
            raise ValueError("Invalid global address register pair")
        base = [vector_u32(f"v{first}", st.scalar, st.vector, st.pending, st.sample_pending),
                vector_u32(f"v{last}", st.scalar, st.vector, st.pending, st.sample_pending)]
        voffset = "0u"
    else:
        if addr_token.startswith("v["):
            raise ValueError("Global load with saddr needs a 32-bit offset register")
        base = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in sgpr_pair(saddr_token)]
        voffset = vector_u32(addr_token, st.scalar, st.vector, st.pending, st.sample_pending)
    return base, voffset, immediate & 0xffffffffffffffff


@form(r"global_load_dword(x[234])? (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), (off|s\[\d+:\d+\])((?: \S+)*)")
def global_load(st, i, m):
    # Global loads of whole dwords: a 64-bit VGPR pair with saddr off, or an SGPR pair plus a 32-bit VGPR offset,
    # then the signed 12-bit instruction offset. Cache modifiers are accepted as above; the rest are refused.
    width, dst_token, addr_token, saddr_token, modifiers = m.groups()
    count = int(width[1]) if width else 1
    dsts = vgprs(dst_token, count)
    base, voffset, bits = global_operands(st, addr_token, saddr_token, modifiers)
    if any(d in st.sample_dest for d in dsts):
        raise ValueError("Write overlaps an outstanding sample")
    st.uses_memory = True
    for j, d in enumerate(dsts):
        st.lines.append(f"    uint mem{i}_{j} = global_load32(uint2({base[0]}, {base[1]}), {voffset}, "
                     f"uint2({bits & 0xffffffff}u, {bits >> 32}u), {j}u);")
        st.vector[d] = ("uint", f"mem{i}_{j}")
    st.vm_issue(dsts, "flat")


@form(r"global_load_(" + "|".join(sorted(SUB_DWORD, key=len, reverse=True)) + r") (v\d+), (v\d+|v\[\d+:\d+\]), "
      r"(off|s\[\d+:\d+\])((?: \S+)*)")
def global_load_sub(st, i, m):
    # One byte or half, extended to the destination word as for the buffer forms (a d16 form keeps the other half).
    op, dst, addr_token, saddr_token, modifiers = m.groups()
    old = vector_u32(dst, st.scalar, st.vector, st.pending, st.sample_pending) if SUB_DWORD[op][2] else None
    base, voffset, bits = global_operands(st, addr_token, saddr_token, modifiers)
    if dst in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    st.uses_memory = True
    raw = (f"global_load_sub(uint2({base[0]}, {base[1]}), {voffset}, uint2({bits & 0xffffffff}u, {bits >> 32}u), "
           f"{SUB_DWORD[op][0]}u)")
    st.lines.append(f"    uint mem{i}_0 = {sub_dword_word(op, raw, old)};")
    st.vector[dst] = ("uint", f"mem{i}_0")
    st.vm_issue([dst], "flat")


@form(r"(?s)flat_load.*")
def flat_load(st, i, m):
    raise ValueError("flat loads are not lowered")
