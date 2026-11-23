"""SMEM: scalar loads of descriptors (s_load) and constant words (s_buffer_load)."""
import re

from ..dispatch import form
from ..registers import DescriptorWord, registers, scalar_u32, sgpr_name, sgpr_pair
from .. import bindings


# A descriptor-list pointer (tools/compute_aot.py, lower(bindings=...)): set 0 is "texture_ptr", the pixel stage's name,
# and set N > 0 is "texture_ptr.N"; both are completed with st.descriptor_high. A descriptor of set N is keyed by
# N * SET_STRIDE + its byte offset in the set (bindings.SET_STRIDE).
SET_STRIDE = bindings.SET_STRIDE


def table_set(st, values):
    """The descriptor set whose pointer the two address words hold, or None."""
    if len(values) != 2 or values[1] != st.descriptor_high or not isinstance(values[0], str):
        return None
    if values[0] == "texture_ptr":
        return 0
    if m := re.fullmatch(r"texture_ptr\.([1-7])", values[0]):
        return int(m[1])
    return None


def data_word(st, key, value):
    """Word j of the descriptor at key, (tag, j); a DescriptorWord carrying params[first + j] when the contract gives
    the descriptor's words as data (st.descriptor_data: key -> index of its first word in params)."""
    first = getattr(st, "descriptor_data", {}).get(key)
    if first is None:
        return value
    word = first + value[1]
    return DescriptorWord(value, f"params[{word // 4}].{'xyzw'[word % 4]}")


@form(r"s_load_dword(x2|x4|x8|x16)? (s\d+|s\[\d+:\d+\]), (s\[\d+:\d+\]), (null|0x[0-9a-f]+|s\d+)(?: offset:(0x[0-9a-f]+))?"
      r"( glc)?( dlc)?",
      when=lambda st, m: st.stage == "compute" or st.descriptor_words)
def compute_descriptor_load(st, i, m):
    # The compute stage, and the pixel stage under a binding description (lower(bindings=...),
    # docs/design/pixel-bindings.md), read every descriptor through this form (docs/design/compute-stage.md): each
    # destination word is the word of the declared descriptor that covers it, a T# (st.bindings, sampled or read-only
    # images, 32 bytes), a storage-image T# (st.storage_images, 32 bytes), a sampler S# (st.sampler_offsets: key ->
    # tag, 16 bytes, tracked as (tag, j)), a constant-buffer V# (16 bytes, tracked as ("cbv<k>", j); compute's single
    # one is st.constant_descriptor) or a buffer V# (16 bytes, its words in params). One load may span several
    # descriptors, as s_load_dwordx16 of two adjacent T#s does. A word no declared descriptor covers is refused, as is
    # an offset that is not a translation-time constant.
    width, dst_token, base_token, soffset, extra, _glc, _dlc = m.groups()
    count = int(width[1:]) if width else 1
    if count == 1:
        dst = [sgpr_name(dst_token)]
    else:
        if not (span := re.fullmatch(r"s\[(\d+):(\d+)\]", dst_token)):
            raise ValueError("Scalar load destination width mismatch")
        first, last = map(int, span.groups())
        if last - first + 1 != count or first % (2 if count == 2 else 4) or last > 105:
            raise ValueError("Invalid scalar load destination registers")
        dst = [f"s{n}" for n in range(first, last + 1)]
    base = sgpr_pair(base_token)
    table = table_set(st, [st.scalar.get(r) for r in base])
    if table is None or st.pending.intersection(base):
        raise ValueError("Unresolved descriptor-list pointer")
    if soffset.startswith("s"):
        # An SGPR offset (plus the offset: field) must hold a translation-time constant, as in scalar_load.
        value = st.scalar.get(soffset)
        if soffset in st.pending or not isinstance(value, int):
            raise ValueError("Scalar load offset register must hold a known constant")
        offset = (value + int(extra or "0x0", 16)) & 0xffffffff
    elif extra is not None:
        raise ValueError("An offset: field needs an SGPR offset")
    else:
        offset = 0 if soffset == "null" else int(soffset, 16)
    if offset % 4 or offset > 0xfffff:
        raise ValueError("Scalar load offset is misaligned or out of range")
    constants = dict(st.constant_buffers)
    if st.constant_descriptor is not None:
        constants.setdefault(st.constant_descriptor, "cbv")
    words = []
    for j in range(count):
        at = table * SET_STRIDE + offset + 4 * j
        texture = next((k for k in st.bindings if k <= at < k + 32), None)
        image = next((k for k in st.storage_images if k <= at < k + 32), None)
        sampler = next((k for k in st.sampler_offsets if k <= at < k + 16), None)
        vsharp = next((k for k in st.vsharp_words if k <= at < k + 16), None)
        cbv = next((k for k in constants if k <= at < k + 16), None)
        if texture is not None:
            words.append(data_word(st, texture, (st.bindings[texture], (at - texture) // 4)))
        elif image is not None:
            words.append(data_word(st, image, (f"image{st.storage_images[image][0]}", (at - image) // 4)))
        elif sampler is not None:
            words.append(data_word(st, sampler, (st.sampler_offsets[sampler], (at - sampler) // 4)))
        elif cbv is not None:
            words.append((constants[cbv], (at - cbv) // 4))
        elif vsharp is not None:
            word = st.vsharp_words[vsharp] + (at - vsharp) // 4
            words.append(("uint", f"{st.vsharp_array}[{word // 4}].{'xyzw'[word % 4]}"))
        else:
            raise ValueError("Descriptor table word is not a tracked descriptor")
    for n, value in zip(dst, words):
        if n in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        st.scalar[n] = value
        st.pending.add(n)


@form(r"s_load_dwordx8 s\[(\d+):(\d+)\], s\[(\d+):(\d+)\], (null|0x[0-9a-f]+)",
      when=lambda st, m: (0 if m[5] == "null" else int(m[5], 16)) in st.bindings.keys() | st.storage_images.keys())
def texture_descriptor(st, i, m):
    # Any other offset is a descriptor-table read for the scalar-load branch below, which refuses it unless
    # every word belongs to a tracked descriptor. A storage image (forms/image_writes.py) is tracked as
    # ("image<slot>", j), a name no sampling form looks up.
    dst = registers(*m.groups()[:2], 8)
    addr = registers(*m.groups()[2:4], 2)
    offset = 0 if m[5] == "null" else int(m[5], 16)
    if any(f"s{n}" in st.pending for n in (*addr, *dst)) or [st.scalar.get(f"s{n}") for n in addr] != ["texture_ptr", 0]:
        raise ValueError("Texture address differs from binding contract")
    for j, n in enumerate(dst):
        name = st.bindings[offset] if offset in st.bindings else f"image{st.storage_images[offset][0]}"
        st.scalar[f"s{n}"] = (name, j)
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
    if descriptor and st.descriptor_words:
        # Under a binding description every descriptor load is resolved by compute_descriptor_load, which needs an
        # immediate offset.
        raise ValueError("Descriptor load offset must be an immediate")
    if descriptor:
        base = sgpr_pair(base_token)
    else:
        low, high = map(int, re.fullmatch(r"s\[(\d+):(\d+)\]", base_token).groups())
        if high - low != 3 or low % 4 or high > 105:
            raise ValueError("Invalid scalar buffer registers")
        base = [f"s{n}" for n in range(low, high + 1)]
    values = [st.scalar.get(r) for r in base]
    # s_buffer_load reads through a constant-buffer V#: the four words ("cbv<k>", 0..3) of constant slot k, whose
    # words are params<k> (bindings.constant_array; "cbv" and params for the fixed contract's single one).
    array = None if descriptor or not isinstance(values[0], tuple) else bindings.constant_array_of_tag(values[0][0])
    if descriptor:
        resolved = st.constant_descriptor is not None and values == ["texture_ptr", st.descriptor_high]
    else:
        resolved = array is not None and values == [(values[0][0], n) for n in range(4)]
    if not resolved or st.pending.intersection(base):
        raise ValueError("Unresolved constant buffer binding")
    if not descriptor and soffset.startswith("s") and soffset not in st.pending \
            and st.scalar.get(sgpr_name(soffset)) is not None and not isinstance(st.scalar[soffset], int):
        dynamic_constant_load(st, i, array, dst, soffset, int(extra or "0x0", 16))
        return
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
    if not descriptor and offset + 4 * count > st.constant_limits.get(array, st.constant_limit):
        raise ValueError("Constant read exceeds binding")
    if not descriptor:
        st.constant_words[array] = max(st.constant_words.get(array, 0), (offset + 4 * count) // 4)
    words = []
    for j in range(count):
        at = offset + 4 * j
        if not descriptor:
            words.append(("uint", bindings.word(array, at // 4)))
        elif st.constant_descriptor <= at < st.constant_descriptor + 16:
            words.append(("cbv", (at - st.constant_descriptor) // 4))
        else:
            entry = next((start for start in st.vsharp_words if start <= at < start + 16), None)
            if entry is None:
                raise ValueError("Descriptor table word is not a tracked descriptor")
            word = st.vsharp_words[entry] + (at - entry) // 4
            words.append(("uint", f"{st.vsharp_array}[{word // 4}].{'xyzw'[word % 4]}"))
    for n, value in zip(dst, words):
        if n in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        st.scalar[n] = value
        st.pending.add(n)


def dynamic_constant_load(st, i, array, dst, soffset, extra):
    """s_buffer_load_dword* of constant words at a run-time SGPR offset (docs/design/compute-stage.md, dynamic scalar
    constant loads). The SGPR is a byte offset; the two low bits of the address are ignored (SMEM reads whole dwords),
    and the offset: field must be a multiple of 4. Dword j reads byte E + extra + 4j of the binding, E = S & ~3; a dword
    that does not lie wholly inside the bound constant words (st.constant_limits[array] or st.constant_limit bytes, the
    binding the contract declares) reads 0, as AMD's buffer range check returns for a dword past num_records. The offset is captured in a
    local when the load issues, so a later write of S (a loop counter) does not change the words; the words are
    locals too, and the control-flow walk joins them as any data word."""
    limit = st.constant_limits.get(array, st.constant_limit)
    if extra % 4 or extra > 0xfffff:
        raise ValueError("Scalar load offset is misaligned or out of range")
    source = scalar_u32(soffset, st.scalar, st.pending)
    if array == "params" or array in st.constant_limits:
        # The whole binding is declared, so that every in-range dword is in the array (sized by constant_words).
        st.constant_words[array] = max(st.constant_words.get(array, 0), limit // 4)
    elif limit != 256:
        raise ValueError("A run-time offset into a constant slot other than b0 needs its 64-word binding")
    base = f"smo{i}"
    st.lines.append(f"    uint {base} = ({source}) & 0xfffffffcu;")
    for j, n in enumerate(dst):
        if n in st.pending:
            raise ValueError("Write overlaps an outstanding scalar load")
        reach = extra + 4 * j  # bytes past E of dword j
        name = f"smw{i}_{j}"
        if reach + 4 > limit:
            st.lines.append(f"    uint {name} = 0u;")
        else:
            at = f"min({base} + {reach}u, {limit - 4}u)" if reach else f"min({base}, {limit - 4}u)"
            st.lines.append(f"    uint {name} = {base} <= {limit - 4 - reach}u ? "
                            f"{array}[{at} >> 4][({at} >> 2) & 3u] : 0u;")
        st.scalar[n] = ("uint", name)
        st.pending.add(n)
