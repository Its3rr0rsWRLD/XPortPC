"""MIMG: image_sample, loads, level queries and gathers of a 2D T#."""
from ..dispatch import form
from ..registers import fp_operand, registers, vector_u32, vgprs


def coordinate(st, register):
    """A texture coordinate or other binary32 address word: the interpolated uv keeps its quad-defined name."""
    value = st.vector.get(register)
    return value if value in ("uv.x", "uv.y") else fp_operand(register, st.scalar, st.vector, st.pending, st.sample_pending)


def store_results(st, i, dests, values, d16):
    """Write the destination VGPRs of an image read. values: one expression per destination channel, in order.
    A binary32 read gives one VGPR per channel. A d16 read packs two channels per VGPR, the earlier in the low half
    (RDNA, no unpacked-D16 mode), each narrowed to binary16 with round-to-nearest-even like v_cvt_f16_f32; the words
    are raw integers named mem_d16_*, so they obey the vmcnt rule. An odd channel count would leave a half whose
    contents this model does not know, so it is refused."""
    if not d16:
        for d, value in zip(dests, values):
            st.vector[d] = value
        return
    if len(values) % 2 or len(dests) != len(values) // 2:
        raise ValueError("A d16 image read needs an even number of channels in half as many VGPRs")
    for k, d in enumerate(dests):
        st.lines.append(f"    uint mem_d16_{i}_{k} = narrow16({values[2 * k]}) | (narrow16({values[2 * k + 1]}) << 16u);")
        st.vector[d] = ("uint", f"mem_d16_{i}_{k}")


@form(r"image_sample v\[(\d+):(\d+)\], v\[(\d+):(\d+)\], s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] dmask:0x([7f]) dim:SQ_RSRC_IMG_2D( d16)?")
def sample(st, i, m):
    # dmask 0x7 is an RGB-only read (R0Y00/Xbox2Windows#303 by Vonsek): three destination VGPRs, and the fourth VGPR
    # of the usual v[N:N+3] block is left alone. A d16 read of three channels would leave half a register undefined,
    # so it is refused with the other odd counts (store_results).
    operands = m.groups()
    rgb = operands[8] == "7"
    d16 = operands[9] is not None
    if rgb and d16:
        raise ValueError("A d16 image read needs an even number of channels")
    dest, coords, image, state = [registers(*operands[k:k+2], width)
                                  for k, width in zip((0,2,4,6), (3 if rgb else 2 if d16 else 4,2,8,4))]
    if any(f"v{n}" in st.sample_dest for n in dest):
        raise ValueError("Write overlaps an outstanding sample")
    descriptor = [st.scalar.get(f"s{n}") for n in image]
    texture = next((name for name in st.bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
    # CF-2c: a sample while the lane may be inactive (a predicated skip region or a narrowed EXEC) runs in uniform HLSL
    # flow, so all four lanes of the quad take part in the derivatives; lower() masks its destination writes.
    if (any(f"s{n}" in st.pending for n in (*image, *state))
            or texture is None
            or [st.scalar.get(f"s{n}") for n in state] != list(st.sampler)):
        raise ValueError("Unsupported image or sampler binding")
    uv = [st.vector[f"v{n}"] for n in coords]
    # The implicit level comes from the derivatives of the coordinates, so each must be defined on helper lanes.
    if any(not isinstance(v, str) or v not in st.quad_values for v in uv):
        raise ValueError("Unsupported texture coordinate")
    st.lines.append(f"    float4 sample{i} = {texture}.Sample(samp, float2({', '.join(uv)}));")
    st.samples += 1
    names = [f"v{n}" for n in dest]
    store_results(st, i, names, [f"sample{i}.{c}" for c in "xyzw"[:3 if rgb else 4]], d16)
    st.vm_issue(names, "sample")


@form(r"image_(load|load_mip|get_resinfo|gather4|gather4_lz_o|gather4_lz) (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), "
      r"s\[(\d+):(\d+)\](?:, s\[(\d+):(\d+)\])? dmask:0x([0-9a-f]) dim:SQ_RSRC_IMG_2D((?: (?:unorm|glc|slc|dlc|d16))*)")
def load_query_gather(st, i, m):
    # MIMG loads, level queries and gathers of a 2D T#, with the descriptor provenance rules of image_sample. Cache
    # modifiers do not change the value; unorm is accepted for loads and queries, where it has no effect on an
    # integer-addressed access. a16, tfe, lwe, r128 and array or other dimensions do not match this grammar. d16
    # (half-packed results, see store_results) is accepted for loads and gathers. Destination and address widths must
    # agree with the dmask and the form, as the assembler requires. image_gather4_lz_o adds a packed texel offset in
    # the first address VGPR (see image_offset_uv); the other offset, level and compare gathers are refused.
    op, dst_token, addr_token, f0, f1, s0, s1, dmask_digit, modifiers = m.groups()
    flags = modifiers.split()
    d16 = "d16" in flags
    if len(set(flags)) != len(flags) or ("unorm" in flags and op.startswith("gather4")) or (d16 and op == "get_resinfo"):
        raise ValueError("Repeated or unsupported image modifier")
    dmask = int(dmask_digit, 16)
    if st.ex != "true" or not dmask:
        raise ValueError("Invalid image operation")
    if op == "gather4":
        raise ValueError("image_gather4 picks its mip level from derivatives, which Gather* cannot reproduce; "
                         "only image_gather4_lz is lowered")
    gather = op.startswith("gather4")
    if gather != (s0 is not None):
        raise ValueError("Sampler operand does not match the image form")
    channels = [c for c in range(4) if dmask >> c & 1]
    if gather and len(channels) != 1:
        raise ValueError("image_gather4 needs exactly one dmask bit")
    if op == "get_resinfo" and 2 in channels:
        raise ValueError("image_get_resinfo depth word of a 2D resource is not defined by Direct3D; refused")
    values_count = 4 if gather else len(channels)
    dests = vgprs(dst_token, values_count // 2 if d16 and values_count % 2 == 0 else values_count)
    addr_width = {"load": 2, "load_mip": 3, "get_resinfo": 1, "gather4": 2, "gather4_lz": 2, "gather4_lz_o": 3}[op]
    addrs = vgprs(addr_token, addr_width)
    image = [f"s{n}" for n in registers(f0, f1, 8)]
    descriptor = [st.scalar.get(r) for r in image]
    texture = next((name for name in st.bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
    if texture is None or int(f0) % 4 or int(f1) > 105 or any(r in st.pending for r in image):
        raise ValueError("Unsupported image binding")
    if gather:
        state = [f"s{n}" for n in registers(s0, s1, 4)]
        if any(r in st.pending for r in state) or [st.scalar.get(r) for r in state] != list(st.sampler) or int(s0) % 4:
            raise ValueError("Unsupported sampler binding")
    if any(d in st.sample_dest for d in dests) or any(int(d[1:]) > 255 for d in (*dests, *addrs)):
        raise ValueError("Write overlaps an outstanding sample")
    if gather:
        # Footprint order is the Direct3D one: x, y, z, w = (-,+), (+,+), (+,-), (-,-) texel offsets, which is
        # VDATA[0..3] = lower left, lower right, upper right, upper left. The coordinate is normalized.
        offset = None
        if op == "gather4_lz_o":
            offset, addrs = vector_u32(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending), addrs[1:]
        coords = [coordinate(st, r) for r in addrs]
        position = f"float2({coords[0]}, {coords[1]})"
        if offset is not None:
            st.helpers.update(("image_offset_uv",))
            position = f"image_offset_uv({texture}, {position}, 0.0f, {offset})"
        call = f"{texture}.Gather{('Red', 'Green', 'Blue', 'Alpha')[channels[0]]}(samp, {position})"
        st.lines.append(f"    float4 sample{i} = {call};")
        results = [f"sample{i}.{c}" for c in "xyzw"]
    elif op == "get_resinfo":
        # D3D resinfo: [width, height, depth or array size, level count]. The depth word of a 2D resource is
        # refused above; a level at or beyond the count returns zero extents and the level count.
        level = vector_u32(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending)
        st.helpers.add("image_resinfo")
        st.lines.append(f"    uint4 mem_info{i} = image_resinfo2d({texture}, {level});")
        results = None
    else:
        x, y = (vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in addrs[:2])
        level = vector_u32(addrs[2], st.scalar, st.vector, st.pending, st.sample_pending) if op == "load_mip" else "0u"
        st.helpers.add("image_load")
        st.lines.append(f"    float4 sample{i} = image_load2d({texture}, {x}, {y}, {level});")
        results = [f"sample{i}.{c}" for c in "xyzw"]
    if results is None:
        for d, c in zip(dests, channels):
            st.vector[d] = ("uint", f"mem_info{i}.{'xyzw'[c]}")
    else:
        store_results(st, i, dests, [results[c] for c in ([0, 1, 2, 3] if gather else channels)], d16)
    st.vm_issue(dests, "sample")


@form(r"image_sample_(lz_o|lz|l_o|l|b|d) (v\d+|v\[\d+:\d+\]), (v\[\d+:\d+\]|\[v\d+(?:, v\d+)*\]), s\[(\d+):(\d+)\], "
      r"s\[(\d+):(\d+)\] dmask:0x([0-9a-f]) dim:SQ_RSRC_IMG_2D((?: (?:glc|slc|dlc|d16))*)")
def sample_level(st, i, m):
    # Samples whose level does not come from the coordinate's derivatives, plus the biased one. The address is a
    # range or a non-sequential (NSA) list, in the hardware order offset, bias, derivatives, coordinates, level:
    #   lz: x, y          SampleLevel(.., 0)                   b: bias, x, y    SampleBias (binary32 bias + implicit level)
    #   l: x, y, lod      SampleLevel(.., lod)                 d: dsdh, dtdh, dsdv, dtdv, x, y     SampleGrad
    #   lz_o: off, x, y   and l_o: off, x, y, lod: the same with a texel offset (image_offset_uv)
    # The mip filter of the desktop sampler is point, so a level is the nearest one, which is exact for an integral
    # lod (or gradients that are powers of two); a fractional lod is rounded by the sampler, not by this translator.
    # The descriptor provenance rules are those of image_sample. Cache modifiers do not change the value; d16 packs
    # two channels per VGPR (store_results). unorm, a16, tfe, lwe, r128 and other dimensions do not match this
    # grammar. The implicit level of image_sample_b comes from derivatives, so, as for image_sample, its coordinates
    # must be the interpolated texture coordinate; the explicit-level forms read any coordinate. Refused neighbours:
    # image_sample_o, _b_o and _d_o (an offset needs the size of the level, and these pick it from derivatives, which
    # this translator cannot see), _cl (clamped implicit level), _c (a depth comparison needs a comparison sampler,
    # and the desktop sampler is a plain point one) and _cd.
    op, dst_token, addr_token, f0, f1, s0, s1, dmask_digit, modifiers = m.groups()
    flags = modifiers.split()
    if len(set(flags)) != len(flags):
        raise ValueError("Repeated image modifier")
    d16 = "d16" in flags
    dmask = int(dmask_digit, 16)
    if not dmask:  # CF-2c: also while the lane may be inactive, as image_sample
        raise ValueError("Invalid image operation")
    channels = [c for c in range(4) if dmask >> c & 1]
    if d16 and len(channels) % 2:
        raise ValueError("A d16 image read needs an even number of channels")
    dests = vgprs(dst_token, len(channels) // 2 if d16 else len(channels))
    width = {"lz": 2, "b": 3, "l": 3, "lz_o": 3, "l_o": 4, "d": 6}[op]
    if addr_token.startswith("["):
        addrs = addr_token[1:-1].split(", ")
        if len(addrs) != width:
            raise ValueError("Image address width mismatch")
    else:
        addrs = vgprs(addr_token, width)
    image = [f"s{n}" for n in registers(f0, f1, 8)]
    state = [f"s{n}" for n in registers(s0, s1, 4)]
    descriptor = [st.scalar.get(r) for r in image]
    texture = next((name for name in st.bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
    if (texture is None or int(f0) % 4 or int(s0) % 4 or int(f1) > 105 or int(s1) > 105
            or any(r in st.pending for r in (*image, *state)) or [st.scalar.get(r) for r in state] != list(st.sampler)):
        raise ValueError("Unsupported image or sampler binding")
    if any(d in st.sample_dest for d in dests) or any(int(d[1:]) > 255 for d in (*dests, *addrs)):
        raise ValueError("Write overlaps an outstanding sample")
    offset = None
    if op.endswith("_o"):
        offset, addrs = vector_u32(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending), addrs[1:]
    if op == "b":
        uv = [st.vector.get(r) for r in addrs[1:]]
        if any(v not in ("uv.x", "uv.y") for v in uv):
            raise ValueError("Unsupported texture coordinate")
        bias = fp_operand(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending)
        call = f"{texture}.SampleBias(samp, float2({', '.join(uv)}), {bias})"
    elif op == "d":
        gradient = [coordinate(st, r) for r in addrs[:4]]
        x, y = (coordinate(st, r) for r in addrs[4:])
        call = (f"{texture}.SampleGrad(samp, float2({x}, {y}), float2({gradient[0]}, {gradient[1]}), "
                f"float2({gradient[2]}, {gradient[3]}))")
    else:
        x, y = (coordinate(st, r) for r in addrs[:2])
        lod = coordinate(st, addrs[2]) if op.startswith("l") and not op.startswith("lz") else "0.0f"
        if offset is None:
            call = f"{texture}.SampleLevel(samp, float2({x}, {y}), {lod})"
        else:
            # The offset is in texels of the level that is read, so the level is chosen here, once, for both.
            st.helpers.update(("image_offset_uv", "image_level"))
            level = f"image_level({texture}, {lod})" if lod != "0.0f" else "0.0f"
            st.lines.append(f"    float level{i} = {level};")
            call = (f"{texture}.SampleLevel(samp, image_offset_uv({texture}, float2({x}, {y}), level{i}, {offset}), "
                    f"level{i})")
    st.lines.append(f"    float4 sample{i} = {call};")
    store_results(st, i, dests, [f"sample{i}.{'xyzw'[c]}" for c in channels], d16)
    st.vm_issue(dests, "sample")
