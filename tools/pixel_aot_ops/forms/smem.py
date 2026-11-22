"""SMEM: scalar loads of descriptors (s_load) and constant words (s_buffer_load)."""
import re

from ..dispatch import form
from ..registers import registers, sgpr_name, sgpr_pair


@form(r"s_load_dwordx8 s\[(\d+):(\d+)\], s\[(\d+):(\d+)\], (null|0x[0-9a-f]+)", when=lambda st, m: (0 if m[5] == "null" else int(m[5], 16)) in st.bindings)
def texture_descriptor(st, i, m):
    # Any other offset is a descriptor-table read for the scalar-load branch below, which refuses it unless
    # every word belongs to a tracked descriptor.
    dst = registers(*m.groups()[:2], 8)
    addr = registers(*m.groups()[2:4], 2)
    offset = 0 if m[5] == "null" else int(m[5], 16)
    if any(f"s{n}" in st.pending for n in (*addr, *dst)) or [st.scalar.get(f"s{n}") for n in addr] != ["texture_ptr", 0]:
        raise ValueError("Texture address differs from binding contract")
    for j, n in enumerate(dst):
        st.scalar[f"s{n}"] = (st.bindings[offset], j)
        st.pending.add(f"s{n}")


@form(r"(s_buffer_load|s_load)_dword(x2|x4|x8|x16)? (s\d+|s\[\d+:\d+\]), (s\[\d+:\d+\]), "
      r"(null|0x[0-9a-f]+|s\d+)(?: offset:(0x[0-9a-f]+))?( glc)?( dlc)?")
def scalar_load(st, i, m):
    # SMEM loads of 1, 2, 4, 8 or 16 dwords. s_buffer_load reads constant words through the constant buffer
    # descriptor that s_load_dwordx4 produced; s_load reads descriptor-table words, which are the tracked
    # descriptors: the constant descriptor and the buffer_descriptors V#s. glc and dlc only select cache
    # behaviour, and the constants never change during a draw. An SGPR offset must hold a translation-time
    # constant, because the range checks below need it. The range checks use the dword count, so a wide read
    # past the 64 constant words is refused instead of reading zeros as hardware does.
    op, width, dst_token, base_token, soffset, extra, _glc, _dlc = m.groups()
    count = int(width[1:]) if width else 1
    descriptor = op == "s_load"
    if count == 1:
        dst = [sgpr_name(dst_token)]
    else:
        if not (span := re.fullmatch(r"s\[(\d+):(\d+)\]", dst_token)):
            raise ValueError("Scalar load destination width mismatch")
        first, last = map(int, span.groups())
        # RDNA SGPR tuples: 64-bit pairs are even-aligned, wider ones are 4-aligned; s105 is the last SGPR.
        if (last - first + 1 != count or first % (2 if count == 2 else 4) or last > 105):
            raise ValueError("Invalid scalar load destination registers")
        dst = [f"s{n}" for n in range(first, last + 1)]
    if descriptor:
        base = sgpr_pair(base_token)
    else:
        low, high = map(int, re.fullmatch(r"s\[(\d+):(\d+)\]", base_token).groups())
        if high - low != 3 or low % 4 or high > 105:
            raise ValueError("Invalid scalar buffer registers")
        base = [f"s{n}" for n in range(low, high + 1)]
    expected = ["texture_ptr", 0] if descriptor else [("cbv", n) for n in range(4)]
    if st.constant_descriptor is None or st.pending.intersection(base) or [st.scalar.get(r) for r in base] != expected:
        raise ValueError("Unresolved constant buffer binding")
    if soffset.startswith("s"):
        value = st.scalar.get(sgpr_name(soffset))
        if soffset in st.pending or not isinstance(value, int):
            raise ValueError("Scalar load offset register must hold a known constant")
        offset = value + int(extra or "0x0", 16)
    elif extra is not None:
        raise ValueError("An offset: field needs an SGPR offset")
    else:
        offset = 0 if soffset == "null" else int(soffset, 16)
    if offset % 4 or not 0 <= offset <= 0xffffffff or (soffset[0] != "s" and offset > 0xfffff):
        raise ValueError("Scalar load offset is misaligned or out of range")
    if not descriptor and offset + 4 * count > 256:
        raise ValueError("Constant read exceeds binding")
    words = []
    for j in range(count):
        at = offset + 4 * j
        if not descriptor:
            word = at // 4
            words.append(("uint", f"params[{word // 4}].{'xyzw'[word % 4]}"))
        elif st.constant_descriptor <= at < st.constant_descriptor + 16:
            words.append(("cbv", (at - st.constant_descriptor) // 4))
        else:
            entry = next((start for start in st.vsharp_words if start <= at < start + 16), None)
            if entry is None:
                raise ValueError("Descriptor table word is not a tracked descriptor")
            word = st.vsharp_words[entry] + (at - entry) // 4
            words.append(("uint", f"params[{word // 4}].{'xyzw'[word % 4]}"))
    for n, value in zip(dst, words):
        if n in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        st.scalar[n] = value
        st.pending.add(n)
