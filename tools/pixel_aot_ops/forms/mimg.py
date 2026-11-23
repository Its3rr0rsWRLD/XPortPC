"""MIMG: image_sample, loads, level queries and gathers of a 2D T#."""
from .. import bindings as binding_names
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


def sampler_of(st, state):
    """The HLSL sampler the four SGPRs `state` hold, or None: st.sampler ("samp") for the fixed contract and the compute
    stage, else the sampler of a binding description (st.samplers) whose tracked words they are."""
    values = [st.scalar.get(r) for r in state]
    if st.samplers is None:
        return "samp" if values == list(st.sampler) else None
    return next((name for name, words in st.samplers.items() if values == list(words)), None)


def texture_dimension(st, texture):
    """The dimension a texture is bound with: st.texture_dims (a binding description's dimensions), else 2D."""
    return st.texture_dims.get(texture, "2d")


def instruction_dimension(st, texture):
    """The dimension an image instruction must name for this texture: a cube array is sampled as dim:SQ_RSRC_IMG_CUBE."""
    dim = texture_dimension(st, texture)
    return "cube" if dim == "cube_array" else dim


@form(r"image_sample (v\d+|v\[\d+:\d+\]), (v\[\d+:\d+\]|\[v\d+(?:, v\d+)+\]), s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] "
      r"dmask:0x([0-9a-f]) dim:(SQ_RSRC_IMG_2D|SQ_RSRC_IMG_2D_ARRAY|SQ_RSRC_IMG_CUBE|SQ_RSRC_IMG_3D)( d16)?")
def sample(st, i, m):
    # The dmask selects the channels that are written, in order, to consecutive destination VGPRs: 0x7 is an RGB-only
    # read (R0Y00/Xbox2Windows#303 by Vonsek) that leaves the fourth VGPR of a v[N:N+3] block alone, 0x1 or 0x8 one
    # channel to a single VGPR, and a mask with holes (0x5, 0xa, ...) the set channels packed together, as for the
    # other MIMG reads (load_query_gather). dmask 0 is refused. A d16 read of an odd channel count would leave half a
    # register undefined, so it is refused with the other odd counts (store_results).
    # The coordinate is a range v[N:N+k] or a non-sequential (NSA) list [vA, vB, ...], as RADV writes it: two words
    # for 2D, three for the other dimensions (docs/design/pixel-bindings.md, "Texture dimensions"). The instruction's
    # dim: must be the dimension the texture is bound with.
    dst_token, addr_token, f0, f1, s0, s1, dmask_digit, dim_field, d16 = m.groups()
    d16 = d16 is not None
    dim = binding_names.INSTRUCTION_DIMS[dim_field]
    width = 2 if dim == "2d" else 3
    channels = [c for c in range(4) if int(dmask_digit, 16) >> c & 1]
    if not channels:
        raise ValueError("Invalid image operation")
    if d16 and len(channels) % 2:
        raise ValueError("A d16 image read needs an even number of channels")
    dest = [int(r[1:]) for r in vgprs(dst_token, len(channels) // 2 if d16 else len(channels))]
    if addr_token.startswith("["):
        coords = [int(r[1:]) for r in addr_token[1:-1].split(", ")]
        if any(n > 255 for n in coords):
            raise ValueError("Image address register out of range")
        if len(coords) != width:
            raise ValueError("Image address width mismatch")
    else:
        coords = [int(r[1:]) for r in vgprs(addr_token, width)]
    image, state = registers(f0, f1, 8), registers(s0, s1, 4)
    if any(f"v{n}" in st.sample_dest for n in dest):
        raise ValueError("Write overlaps an outstanding sample")
    descriptor = [st.scalar.get(f"s{n}") for n in image]
    texture = next((name for name in st.bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
    # CF-2c: a sample while the lane may be inactive (a predicated skip region or a narrowed EXEC) runs in uniform HLSL
    # flow, so all four lanes of the quad take part in the derivatives; lower() masks its destination writes.
    samp = sampler_of(st, [f"s{n}" for n in state])
    if (any(f"s{n}" in st.pending for n in (*image, *state))
            or texture is None
            or samp is None):
        raise ValueError("Unsupported image or sampler binding")
    if instruction_dimension(st, texture) != dim:
        raise ValueError(f"Image dimension {dim_field} does not match the texture binding "
                         f"({texture_dimension(st, texture)})")
    if dim == "2d":
        uv = [quad_coordinate(st, st.vector[f"v{n}"]) for n in coords]
        # The implicit level comes from the derivatives of the coordinates, so each must be defined on helper lanes.
        if None in uv:
            raise ValueError("Unsupported texture coordinate")
        st.lines.append(f"    float4 sample{i} = {texture}.Sample({samp}, float2({', '.join(uv)}));")
    else:
        st.lines.append(f"    float4 sample{i} = {texture}.Sample({samp}, {dimensioned_coordinate(st, i, dim, coords, texture)});")
    st.samples += 1
    names = [f"v{n}" for n in dest]
    store_results(st, i, names, [f"sample{i}.{'xyzw'[c]}" for c in channels], d16)
    st.vm_issue(names, "sample")


def dimensioned_coordinate(st, i, dim, coords, texture):
    """The HLSL float3 location of an implicit-level sample of a 2D-array, cube or 3D texture
    (docs/design/pixel-bindings.md, "Texture dimensions"):
    - 3D: (s, t, r), all normalized, read as a Texture3D. All three enter the level, so each must be a helper-lane
      value that is affine in the interpolated coordinate, as for 2D.
    - 2D array: (s, t, slice) with s and t normalized and the slice an unnormalized index. Whether the texture unit
      rounds or truncates a fractional slice is not established (Mesa rounds it to even in the shader, v_rndne, under
      an option), and the S# is not interpreted here, so the slice must be an integer
      value (Lowering.integral): then it reads that slice under either rule, as Direct3D's rounded and clamped array
      index does. A slice beyond the array is clamped to [0, size - 1] on both. s and t enter the level as for 2D.
    - cube: (s, t, face) as the v_cube* sequence produces them: s = sc / |2 ma| + 1.5 and t likewise lie in [1, 2] on
      the face, and face is a v_cubeid result (Lowering.cube_faces). The cube is bound as a Texture2DArray of its six
      faces and sampled at (s - 1, t - 1, face): the program's own face and face coordinates, so the face choice at
      ties, the projection's rounding and the level's derivatives are the console's, not the desktop's TextureCube
      projection of a direction. s - 1 and t - 1 are exact for s, t in [0.5, 2]. s and t are quotients, not affine in
      the interpolated coordinate, so they need only be helper-lane values (Lowering.quad_defined); how the adapter
      takes their derivatives (coarse or fine) is not proven. A coordinate outside [1, 2], which the hardware's
      seamless addressing may read from the next face, reads the clamped edge of the face here (not modelled).
      A cube array's face word is face + 8 * layer (cube_face)."""
    values = [st.vector[f"v{n}"] for n in coords]
    if dim == "3d":
        xyz = [quad_coordinate(st, v) for v in values]
        if None in xyz:
            raise ValueError("Unsupported texture coordinate")
        return f"float3({', '.join(xyz)})"
    if dim == "2d_array":
        xy = [quad_coordinate(st, v) for v in values[:2]]
        if None in xy:
            raise ValueError("Unsupported texture coordinate")
        if _name(values[2]) not in st.integral:
            raise ValueError("An array slice must be an integer value (v_rndne, v_floor, v_ceil, v_trunc, v_cvt_f32 or "
                             "an integral constant): the texture unit's slice rounding is not modelled")
        return f"float3({xy[0]}, {xy[1]}, {coordinate(st, f'v{coords[2]}')})"
    st_values = [quad_coordinate(st, v, defined=True) for v in values[:2]]
    if None in st_values:
        raise ValueError("Unsupported texture coordinate")
    face = cube_face(st, i, texture, f"v{coords[2]}")
    st.lines.append(f"    precise float3 face{i} = float3({st_values[0]} - 1.0f, {st_values[1]} - 1.0f, {face});")
    return f"face{i}"


def cube_face(st, i, texture, register):
    """The Texture2DArray slice of a cube sample's face word (docs/design/pixel-bindings.md, "Cube arrays"): a v_cubeid
    result is the face of the one cube; face + 8 * layer (Lowering.cube_layers: a v_cubeid result plus 8.0 times an
    integral value, as Mesa's ac_prepare_cube_coords writes a cube array's face word) is the face of cube `layer`, which
    the 6 N faces of the array (slices 6 layer .. 6 layer + 5) hold at slice face + 6 * layer. The layer is clamped to
    [0, N - 1] first, as Vulkan clamps a cube array's layer (RADV emits no clamp, so the texture unit applies it), not
    the slice: Direct3D's own clamp of the slice would move a layer past the end to the last face of the last cube.
    The face and layer are integers, so the slice is exact and Direct3D's rounded slice is it."""
    value = st.vector[register]
    name = _name(value)
    if name in st.cube_faces:
        return coordinate(st, register)
    if name in st.cube_layers:
        face, layer = st.cube_layers[name]
        st.lines.append(f"    uint face{i}_w, face{i}_h, face{i}_n;")
        st.lines.append(f"    {texture}.GetDimensions(face{i}_w, face{i}_h, face{i}_n);")
        st.lines.append(f"    precise float face{i}_layer = clamp({layer}, 0.0f, float(face{i}_n / 6u) - 1.0f);")
        return f"{face} + 6.0f * face{i}_layer"
    raise ValueError("A cube face must be a v_cubeid result")


def explicit_coordinate(st, i, dim, coords, texture):
    """The HLSL float3 location of an explicit-level sample (image_sample_lz and _l) of a 2D-array or cube texture: the
    location of dimensioned_coordinate, but its s and t are any value, since no derivative is taken: the same
    integral-slice rule for an array, and for a cube the v_cubeid face with s - 1 and t - 1 of the program's own
    face coordinates."""
    xy = [coordinate(st, f"v{n}") for n in coords[:2]]
    third = coordinate(st, f"v{coords[2]}")
    value = st.vector[f"v{coords[2]}"]
    if dim == "2d_array":
        if _name(value) not in st.integral:
            raise ValueError("An array slice must be an integer value (v_rndne, v_floor, v_ceil, v_trunc, v_cvt_f32 or "
                             "an integral constant): the texture unit's slice rounding is not modelled")
        return f"float3({xy[0]}, {xy[1]}, {third})"
    third = cube_face(st, i, texture, f"v{coords[2]}")
    st.lines.append(f"    precise float3 face{i} = float3({xy[0]} - 1.0f, {xy[1]} - 1.0f, {third});")
    return f"face{i}"


def _name(value):
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
        value = value[1]
    return value if isinstance(value, str) else None


def require_2d(st, texture):
    """The reads below index a Texture2D: a texture bound with another dimension is refused."""
    if texture is not None and texture_dimension(st, texture) != "2d":
        raise ValueError(f"Image dimension SQ_RSRC_IMG_2D does not match the texture binding "
                         f"({texture_dimension(st, texture)})")


def quad_coordinate(st, value, defined=False):
    """The HLSL binary32 expression of a coordinate an implicit-level sample may read, or None: a value defined on the
    helper lanes (Lowering.quad_values), a float name or a raw word, which is a constant (valu_f32.move). defined:
    also any helper-lane value (Lowering.quad_defined), for a cube sample's face coordinates."""
    known = (lambda name: name in st.quad_values or name in st.quad_defined) if defined else \
        (lambda name: name in st.quad_values)
    if isinstance(value, str) and known(value):
        return value
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint" and known(value[1]):
        return f"asfloat({value[1]})"
    return None


@form(r"image_(load|load_mip|get_resinfo|gather4|gather4_lz_o|gather4_lz) (v\d+|v\[\d+:\d+\]), "
      r"(v\d+|v\[\d+:\d+\]|\[v\d+(?:, v\d+)*\]), "
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
    # The compute stage (docs/design/compute-stage.md, C-3) also loads while the lane may be inactive: a load has no
    # side effect and lower() masks its destination writes; the pixel stage keeps refusing it.
    if (st.ex != "true" and st.stage == "pixel") or not dmask:
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
    if addr_token.startswith("["):  # a non-sequential (NSA) address list
        addrs = addr_token[1:-1].split(", ")
        if len(addrs) != addr_width:
            raise ValueError("Image address width mismatch")
    else:
        addrs = vgprs(addr_token, addr_width)
    image = [f"s{n}" for n in registers(f0, f1, 8)]
    descriptor = [st.scalar.get(r) for r in image]
    texture = next((name for name in st.bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
    if texture is None or int(f0) % 4 or int(f1) > 105 or any(r in st.pending for r in image):
        raise ValueError("Unsupported image binding")
    require_2d(st, texture)
    if gather:
        state = [f"s{n}" for n in registers(s0, s1, 4)]
        samp = sampler_of(st, state)
        if any(r in st.pending for r in state) or samp is None or int(s0) % 4:
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
        call = f"{texture}.Gather{('Red', 'Green', 'Blue', 'Alpha')[channels[0]]}({samp}, {position})"
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


@form(r"image_sample_(lz_o|lz|l_o|l|b|d|o) (v\d+|v\[\d+:\d+\]), (v\[\d+:\d+\]|\[v\d+(?:, v\d+)*\]), s\[(\d+):(\d+)\], "
      r"s\[(\d+):(\d+)\] dmask:0x([0-9a-f]) dim:(SQ_RSRC_IMG_2D|SQ_RSRC_IMG_2D_ARRAY|SQ_RSRC_IMG_CUBE)((?: (?:glc|slc|dlc|d16))*)")
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
    # must be the interpolated texture coordinate; the explicit-level forms read any coordinate.
    # image_sample_o (offset: x, y; the implicit level) takes the level from CalculateLevelOfDetail of the coordinate
    # (a helper-lane value, as for image_sample), rounded and clamped to the levels that exist like an explicit lod
    # (image_level), and applies the offset in texels of that level (image_offset_uv); it is lowered for a 2D texture.
    # The 2D-array and cube textures are lowered for lz, l (x, y, slice or face, lod) and b (bias, x, y, slice or
    # face), as an implicit-level image_sample of them is (dimensioned_coordinate for b; explicit_coordinate for the
    # explicit levels, whose coordinates need no helper-lane definition); the other forms on them, and a16, tfe, lwe,
    # are refused. Refused neighbours: _b_o and _d_o (an offset needs the size of the level, and these pick it from
    # derivatives of a bias or gradients the translator cannot add to the level), _cl (clamped implicit level), _c
    # (a depth comparison needs a comparison sampler, and the desktop sampler is a plain point one) and _cd.
    op, dst_token, addr_token, f0, f1, s0, s1, dmask_digit, dim_field, modifiers = m.groups()
    dim = binding_names.INSTRUCTION_DIMS[dim_field]
    if dim != "2d" and op not in ("lz", "l", "b"):
        raise ValueError(f"image_sample_{op} of a {dim} texture is not lowered")
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
    width = {"lz": 2, "b": 3, "l": 3, "lz_o": 3, "l_o": 4, "d": 6, "o": 3}[op] + (dim != "2d")
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
            or any(r in st.pending for r in (*image, *state)) or (samp := sampler_of(st, state)) is None):
        raise ValueError("Unsupported image or sampler binding")
    if instruction_dimension(st, texture) != dim:
        raise ValueError(f"Image dimension {dim_field} does not match the texture binding "
                         f"({texture_dimension(st, texture)})")
    if any(d in st.sample_dest for d in dests) or any(int(d[1:]) > 255 for d in (*dests, *addrs)):
        raise ValueError("Write overlaps an outstanding sample")
    offset = None
    if op.endswith("_o") or op == "o":
        offset, addrs = vector_u32(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending), addrs[1:]
    if dim != "2d":
        coords = [int(r[1:]) for r in (addrs[1:] if op == "b" else addrs[:3])]
        if op == "b":
            bias = fp_operand(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending)
            call = f"{texture}.SampleBias({samp}, {dimensioned_coordinate(st, i, dim, coords, texture)}, {bias})"
        else:
            location = explicit_coordinate(st, i, dim, coords, texture)
            lod = coordinate(st, addrs[3]) if op == "l" else "0.0f"
            call = f"{texture}.SampleLevel({samp}, {location}, {lod})"
    elif op == "o":
        uv = [quad_coordinate(st, st.vector.get(r)) for r in addrs[:2]]
        if None in uv:
            raise ValueError("Unsupported texture coordinate")
        st.helpers.update(("image_offset_uv", "image_level"))
        position = f"float2({uv[0]}, {uv[1]})"
        st.lines.append(f"    float level{i} = image_level({texture}, {texture}.CalculateLevelOfDetail({samp}, {position}));")
        call = f"{texture}.SampleLevel({samp}, image_offset_uv({texture}, {position}, level{i}, {offset}), level{i})"
    elif op == "b":
        uv = [st.vector.get(r) for r in addrs[1:]]
        if any(v not in ("uv.x", "uv.y") for v in uv):
            raise ValueError("Unsupported texture coordinate")
        bias = fp_operand(addrs[0], st.scalar, st.vector, st.pending, st.sample_pending)
        call = f"{texture}.SampleBias({samp}, float2({', '.join(uv)}), {bias})"
    elif op == "d":
        gradient = [coordinate(st, r) for r in addrs[:4]]
        x, y = (coordinate(st, r) for r in addrs[4:])
        call = (f"{texture}.SampleGrad({samp}, float2({x}, {y}), float2({gradient[0]}, {gradient[1]}), "
                f"float2({gradient[2]}, {gradient[3]}))")
    else:
        x, y = (coordinate(st, r) for r in addrs[:2])
        lod = coordinate(st, addrs[2]) if op.startswith("l") and not op.startswith("lz") else "0.0f"
        if offset is None:
            call = f"{texture}.SampleLevel({samp}, float2({x}, {y}), {lod})"
        else:
            # The offset is in texels of the level that is read, so the level is chosen here, once, for both.
            st.helpers.update(("image_offset_uv", "image_level"))
            level = f"image_level({texture}, {lod})" if lod != "0.0f" else "0.0f"
            st.lines.append(f"    float level{i} = {level};")
            call = (f"{texture}.SampleLevel({samp}, image_offset_uv({texture}, float2({x}, {y}), level{i}, {offset}), "
                    f"level{i})")
    st.lines.append(f"    float4 sample{i} = {call};")
    store_results(st, i, dests, [f"sample{i}.{'xyzw'[c]}" for c in channels], d16)
    st.vm_issue(dests, "sample")
