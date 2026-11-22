"""MIMG: image_sample, loads, level queries and gathers of a 2D T#."""
from ..dispatch import form
from ..registers import fp_operand, registers, vector_u32, vgprs


@form(r"image_sample v\[(\d+):(\d+)\], v\[(\d+):(\d+)\], s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] dmask:0xf dim:SQ_RSRC_IMG_2D")
def sample(st, i, m):
    operands = m.groups()
    dest, coords, image, state = [registers(*operands[k:k+2], width)
                                  for k, width in zip((0,2,4,6), (4,2,8,4))]
    descriptor = [st.scalar.get(f"s{n}") for n in image]
    texture = next((name for name in st.bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
    if (st.ex != "true" or any(f"s{n}" in st.pending for n in (*image, *state))
            or texture is None
            or [st.scalar.get(f"s{n}") for n in state] != list(st.sampler)):
        raise ValueError("Unsupported image or sampler binding")
    uv = [st.vector[f"v{n}"] for n in coords]
    if any(v not in ("uv.x", "uv.y") for v in uv):
        raise ValueError("Unsupported texture coordinate")
    st.lines.append(f"    float4 sample{i} = {texture}.Sample(samp, float2({', '.join(uv)}));")
    st.samples += 1
    st.sample_pending = True
    for j, n in enumerate(dest):
        st.vector[f"v{n}"] = f"sample{i}.{'xyzw'[j]}"
        st.sample_dest.add(f"v{n}")


@form(r"image_(load|load_mip|get_resinfo|gather4|gather4_lz) (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), "
      r"s\[(\d+):(\d+)\](?:, s\[(\d+):(\d+)\])? dmask:0x([0-9a-f]) dim:SQ_RSRC_IMG_2D((?: (?:unorm|glc|slc|dlc))*)")
def load_query_gather(st, i, m):
    # MIMG loads, level queries and gathers of a 2D T#, with the descriptor provenance rules of image_sample. Cache
    # modifiers do not change the value; unorm is accepted for loads and queries, where it has no effect on an
    # integer-addressed access. a16, d16, tfe, lwe, r128 and array or other dimensions do not match this
    # grammar. Destination and address widths must agree with the dmask and the form, as the assembler requires.
    op, dst_token, addr_token, f0, f1, s0, s1, dmask_digit, modifiers = m.groups()
    flags = modifiers.split()
    if len(set(flags)) != len(flags) or ("unorm" in flags and op.startswith("gather4")):
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
    dests = vgprs(dst_token, 4 if gather else len(channels))
    addr_width = {"load": 2, "load_mip": 3, "get_resinfo": 1, "gather4": 2, "gather4_lz": 2}[op]
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
        coords = []
        for r in addrs:
            value = st.vector.get(r)
            coords.append(value if value in ("uv.x", "uv.y") else fp_operand(r, st.scalar, st.vector, st.pending, st.sample_pending))
        call = f"{texture}.Gather{('Red', 'Green', 'Blue', 'Alpha')[channels[0]]}(samp, float2({coords[0]}, {coords[1]}))"
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
    st.sample_pending = True
    if results is None:
        for d, c in zip(dests, channels):
            st.vector[d] = ("uint", f"mem_info{i}.{'xyzw'[c]}")
    else:
        for d, c in zip(dests, [0, 1, 2, 3] if gather else channels):
            st.vector[d] = results[c]
    st.sample_dest.update(dests)


@form(r"image_sample_(lz|b) (v\d+|v\[\d+:\d+\]), (v\[\d+:\d+\]|\[v\d+(?:, v\d+)*\]), s\[(\d+):(\d+)\], "
      r"s\[(\d+):(\d+)\] dmask:0x([0-9a-f]) dim:SQ_RSRC_IMG_2D((?: (?:glc|slc|dlc))*)")
def sample_level(st, i, m):
    # image_sample_lz samples at level 0 (SampleLevel with 0); image_sample_b adds the binary32 bias in its first
    # address VGPR to the implicit level (SampleBias). The address is a range or a non-sequential (NSA) list: lz
    # takes x, y; b takes bias, x, y. The descriptor provenance rules are those of image_sample. Cache modifiers do
    # not change the value; unorm, a16, d16, tfe, lwe, r128 and other dimensions do not match this grammar.
    # The implicit level of image_sample_b comes from derivatives, so, as for image_sample, its coordinates must be
    # the interpolated texture coordinate; lz has no derivatives and, like image_gather4_lz, reads any coordinate.
    op, dst_token, addr_token, f0, f1, s0, s1, dmask_digit, modifiers = m.groups()
    flags = modifiers.split()
    if len(set(flags)) != len(flags):
        raise ValueError("Repeated image modifier")
    dmask = int(dmask_digit, 16)
    if st.ex != "true" or not dmask:
        raise ValueError("Invalid image operation")
    channels = [c for c in range(4) if dmask >> c & 1]
    dests = vgprs(dst_token, len(channels))
    width = 2 if op == "lz" else 3
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
    if op == "lz":
        coords = []
        for r in addrs:
            value = st.vector.get(r)
            coords.append(value if value in ("uv.x", "uv.y") else fp_operand(r, st.scalar, st.vector, st.pending, st.sample_pending))
        call = f"{texture}.SampleLevel(samp, float2({coords[0]}, {coords[1]}), 0.0f)"
    else:
        uv = [st.vector.get(r) for r in addrs[1:]]
        if any(v not in ("uv.x", "uv.y") for v in uv):
            raise ValueError("Unsupported texture coordinate")
        bias = fp_operand(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending)
        call = f"{texture}.SampleBias(samp, float2({', '.join(uv)}), {bias})"
    st.lines.append(f"    float4 sample{i} = {call};")
    st.sample_pending = True
    for d, c in zip(dests, channels):
        st.vector[d] = f"sample{i}.{'xyzw'[c]}"
    st.sample_dest.update(dests)
