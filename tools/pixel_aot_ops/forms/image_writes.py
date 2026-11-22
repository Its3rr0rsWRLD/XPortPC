"""MIMG writes from pixel shaders: image_store, image_store_mip and the 32-bit image_atomic_* of a 2D storage image.

Binding. A storage image is a T# that lower(storage_images={offset: (slot, format)}) names: s_load_dwordx8 of that
descriptor-table offset (forms/smem.py) tracks its eight words as ("image<slot>", j), which no sampling form accepts,
and the harness binds its levels as RWTexture2D at u(8 * slot + level), space2 (tests/pixel_aot_render.cpp, the 'X2WI'
part of a case; null views past the last level). The format is the binding's contract, as RGBA8 is for the sampled
texture: r32_uint (RWTexture2D<uint>) and r32g32b32a32_uint (RWTexture2D<uint4>) are lowered, whose texels are the raw
data words. Every other format is refused where the image is written: float formats (a desktop typed store may flush
denormals or quiet NaNs), normalized, packed and narrower integer formats (conversions this lowering does not model).

Stores. image_store writes level 0 and image_store_mip the level in its third address word, at the unsigned texel
coordinate (x, y) of the first two; unorm does not change an integer address, and glc, slc and dlc are cache policy. The
dmask must name every channel of the format (0x1 for r32_uint, 0xf for r32g32b32a32_uint), one data VGPR per channel;
what the hardware writes to channels a narrower dmask leaves out is not established here. With d16 the channels are
packed two per VGPR, the earlier in the low half, and each 16-bit value is zero-extended into its 32-bit unsigned
channel (an integer conversion that keeps the value; the ISA text itself was not read). A coordinate outside the level,
and a level past the last one (a null view), write nothing (the RDNA rule for out-of-range image stores; the draws
exercise coordinates, not levels).

Atomics. swap, cmpswap (data, then compare value, dmask 0x3), add, sub, smin, umin, smax, umax, and, or, xor, inc and
dec on an r32_uint image, dmask 0x1, at level 0; glc returns the pre-operation value in the first data VGPR, as a load
result. The operations are those of forms/atomics.py (same codes and inc/dec rules): native D3D atomics where one
exists, otherwise a compare-exchange loop. A coordinate outside the image changes nothing and returns zero. Refused: the
float atomics (fcmpswap, fmin, fmax), 64-bit atomics (dmask 0x3, or 0xf for cmpswap) and atomics on a four-channel
image, for which D3D has no typed atomics.

Sharing. A store, swap, cmpswap, inc, dec or a returned value is exact only on a texel that one lane owns. The lowering
cannot prove that lanes name distinct texels; it refuses the case it can see, a texel every lane shares: an address
(x, y, and for image_store_mip the level) whose words are all lane-uniform, that is, they do not depend on the
interpolated coordinate, the pixel position or an attribute (lane_varying below; a quad broadcast counts as shared).
Order-independent atomics without glc are accepted on any texel. Like every memory write, each form needs this lane
provably active outside whole-quad mode (CF-2a)."""
import re

from ..dispatch import form
from ..registers import registers, vector_u32, vgprs
from .atomics import OPS, ORDERED, REFUSED, returned
from .stores import guarded

# Storage image format -> (HLSL texel type, channels, dmask). Only formats whose texels are the raw words.
FORMATS = {"r32_uint": ("uint", 1, 0x1), "r32g32b32a32_uint": ("uint4", 4, 0xf)}
# Compute stage only (docs/design/compute-stage.md, C-2): R8G8B8A8_UNORM, the corpus's storage-image format. The data
# words are binary32 (binary16 halves with d16), converted by the typed store: clamp to [0, 1], NaN to 0, times 255,
# rounded to nearest. A value whose scaled form lies near a half (D3D allows 0.6 ULP of tolerance there) and a NaN are
# not checked by the draws. The dmask may name any channels: the data VGPRs hold the named channels in order and a
# channel outside the dmask is written as 0 (ACO drops a constant-zero channel from the dmask of an image store on that
# rule, visit_image_store in Mesa; not measured here).
UNORM_FORMATS = {"r8g8b8a8_unorm": ("unorm float4", 4, 0xf)}

ADDRESS = r"(v\[\d+:\d+\]|\[v\d+(?:, v\d+)*\])"
DATA = r"(v\d+|v\[\d+:\d+\])"

IMAGE_ATOMIC_VALUE = """uint image_atomic_value(uint op, uint old, uint data) {
    if (op == 4u) return asint(old) < asint(data) ? old : data;
    if (op == 6u) return asint(old) > asint(data) ? old : data;
    if (op == 11u) return old >= data ? 0u : old + 1u;
    return old == 0u || old > data ? data : old - 1u;
}
"""


def store_helper(slot, kind):
    return f"""RWTexture2D<{kind}> image{slot}[8] : register(u{8 * slot}, space2);
void image_store{slot}(uint x, uint y, uint mip, {kind} value) {{
    if (mip >= 8u) return;
    uint width;
    uint height;
    image{slot}[NonUniformResourceIndex(mip)].GetDimensions(width, height);
    if (x < width && y < height) image{slot}[NonUniformResourceIndex(mip)][uint2(x, y)] = value;
}}
"""


def atomic_helper(slot):
    texel = f"image{slot}[0][at]"
    native = {0: f"InterlockedExchange({texel}, data, old)", 1: f"InterlockedCompareExchange({texel}, cmp, data, old)",
              2: f"InterlockedAdd({texel}, data, old)", 3: f"InterlockedAdd({texel}, 0u - data, old)",
              5: f"InterlockedMin({texel}, data, old)", 7: f"InterlockedMax({texel}, data, old)",
              8: f"InterlockedAnd({texel}, data, old)", 9: f"InterlockedOr({texel}, data, old)",
              10: f"InterlockedXor({texel}, data, old)"}
    chain = "\n    else ".join(f"if (op == {code}u) {call};" for code, call in native.items())
    return f"""uint image_atomic{slot}(uint x, uint y, uint op, uint data, uint cmp) {{
    uint width;
    uint height;
    image{slot}[0].GetDimensions(width, height);
    if (x >= width || y >= height) return 0u;
    uint2 at = uint2(x, y);
    uint old = 0u;
    {chain}
    else {{
        old = {texel};
        [loop] for (;;) {{
            uint seen;
            InterlockedCompareExchange({texel}, old, image_atomic_value(op, old, data), seen);
            if (seen == old) break;
            old = seen;
        }}
    }}
    return old;
}}
"""


DEFINITION = re.compile(r"^\s*(?:precise\s+)?(?:(?:uint|int|float|bool)[234]?\s+)?([A-Za-z_]\w*)\s*=\s*(.+?);\s*$", re.M)
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
VARYING = re.compile(r"uv|frag_position|attr\d+|local_id")  # local_id: the compute stage's SV_GroupThreadID


def lane_varying(st, expression):
    """Whether an HLSL expression of the program depends on a lane-varying input (the interpolated coordinate, the
    pixel position or an attribute) through the definitions emitted so far. A value read through QuadReadLaneAt is a
    quad broadcast, shared by four lanes, and does not count. Text-based and conservative for the refusal it backs: a
    value it calls varying may still repeat across lanes, which the lowering cannot see."""
    definitions = {}
    for text in st.lines:
        if text != st.preamble:
            for m in DEFINITION.finditer(text):
                definitions.setdefault(m[1], []).append(m[2])
    seen = set()

    def varies(name):
        if VARYING.fullmatch(name):
            return True
        if name in seen or name not in definitions:
            return False
        seen.add(name)
        return any("QuadReadLaneAt" not in body and any(map(varies, IDENTIFIER.findall(body)))
                   for body in definitions[name])

    return "QuadReadLaneAt" not in expression and any(map(varies, IDENTIFIER.findall(expression)))


def writing(st):
    # The compute stage also writes while the lane may be inactive, under `if (ex)` (stores.guarded).
    if (st.ex != "true" and st.stage == "pixel") or st.wqm:
        raise ValueError("An image write needs this lane provably active outside whole-quad mode (CF-2a)")


def image_operands(st, op, f0, f1, addr_token, width):
    """The storage image (slot, format) named by the T# in s[f0:f1], and the address words as uint expressions."""
    image = [f"s{n}" for n in registers(f0, f1, 8)]
    descriptor = [st.scalar.get(r) for r in image]
    entry = next((e for e in st.storage_images.values() if descriptor == [(f"image{e[0]}", j) for j in range(8)]), None)
    if entry is None or int(f0) % 4 or int(f1) > 105 or any(r in st.pending for r in image):
        raise ValueError("Unsupported storage image binding")
    slot, fmt = entry
    if fmt in UNORM_FORMATS and st.stage == "compute" and op == "store":
        return slot, fmt, [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending)
                           for r in address_registers(addr_token, width)]
    if fmt not in FORMATS:
        raise ValueError(f"Storage image format {fmt} is not lowered exactly")
    words = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in address_registers(addr_token, width)]
    return slot, fmt, words


def address_registers(addr_token, width):
    if addr_token.startswith("["):
        addrs = addr_token[1:-1].split(", ")
        if len(addrs) != width:
            raise ValueError("Image address width mismatch")
    else:
        addrs = vgprs(addr_token, width)
    if any(int(r[1:]) > 255 for r in addrs):
        raise ValueError("Image address register out of range")
    return addrs


def shared(st, words):
    return not any(lane_varying(st, w) for w in words)


def flags_of(modifiers, allowed):
    flags = modifiers.split()
    if len(set(flags)) != len(flags) or not set(flags) <= allowed:
        raise ValueError("Repeated or unsupported image modifier")
    return flags


@form(r"image_(store|store_mip) " + DATA + ", " + ADDRESS + r", s\[(\d+):(\d+)\] dmask:0x([0-9a-f]) "
      r"dim:SQ_RSRC_IMG_2D((?: (?:unorm|glc|slc|dlc|d16))*)")
def image_store(st, i, m):
    op, data_token, addr_token, f0, f1, dmask_digit, modifiers = m.groups()
    d16 = "d16" in flags_of(modifiers, {"unorm", "glc", "slc", "dlc", "d16"})
    writing(st)
    slot, fmt, address = image_operands(st, op, f0, f1, addr_token, 3 if op == "store_mip" else 2)
    if fmt in UNORM_FORMATS:
        return unorm_store(st, slot, fmt, address, data_token, int(dmask_digit, 16), d16)
    kind, channels, mask = FORMATS[fmt]
    if int(dmask_digit, 16) != mask:
        raise ValueError(f"An image store to {fmt} needs dmask {mask:#x}")
    if shared(st, address):
        raise ValueError("An image store to a texel every lane shares is order-dependent")
    regs = vgprs(data_token, (channels + 1) // 2 if d16 else channels)
    words = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in regs]
    if d16:
        values = [f"(({words[c // 2]}) & 0xffffu)" if c % 2 == 0 else f"(({words[c // 2]}) >> 16)" for c in range(channels)]
    else:
        values = words
    value = values[0] if channels == 1 else f"uint4({', '.join(values)})"
    st.declarations.setdefault(f"image{slot}", store_helper(slot, kind))
    mip = address[2] if op == "store_mip" else "0u"
    st.lines.append(guarded(st, f"    image_store{slot}({address[0]}, {address[1]}, {mip}, {value});"))


def unorm_store(st, slot, fmt, address, data_token, dmask, d16):
    """image_store to an R8G8B8A8_UNORM image in the compute stage (see UNORM_FORMATS)."""
    kind, channels, _ = UNORM_FORMATS[fmt]
    named = [c for c in range(channels) if dmask >> c & 1]
    if not named:
        raise ValueError("An image store needs a nonzero dmask")
    if shared(st, address):
        raise ValueError("An image store to a texel every lane shares is order-dependent")
    regs = vgprs(data_token, (len(named) + 1) // 2 if d16 else len(named))
    words = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in regs]
    if d16:
        halves = [f"f16tof32({words[k // 2]})" if k % 2 == 0 else f"f16tof32(({words[k // 2]}) >> 16)"
                  for k in range(len(named))]
    else:
        halves = [f"asfloat({w})" for w in words]
    value = ["0.0f"] * channels
    for c, text in zip(named, halves):
        value[c] = text
    st.declarations.setdefault(f"image{slot}", store_helper(slot, kind))
    st.lines.append(guarded(st, f"    image_store{slot}({address[0]}, {address[1]}, 0u, float4({', '.join(value)}));"))


@form(r"image_atomic_([a-z]+) " + DATA + ", " + ADDRESS + r", s\[(\d+):(\d+)\] dmask:0x([0-9a-f]) "
      r"dim:SQ_RSRC_IMG_2D((?: (?:unorm|glc|slc|dlc))*)")
def image_atomic(st, i, m):
    op, data_token, addr_token, f0, f1, dmask_digit, modifiers = m.groups()
    glc = "glc" in flags_of(modifiers, {"unorm", "glc", "slc", "dlc"})
    if op in REFUSED:
        raise ValueError(f"Float image atomic {op} is not lowered")
    if op not in OPS:
        raise ValueError(f"Unknown image atomic {op}")
    if int(dmask_digit, 16) != (0x3 if op == "cmpswap" else 0x1):
        raise ValueError("64-bit image atomics are not lowered")
    writing(st)
    slot, fmt, address = image_operands(st, op, f0, f1, addr_token, 2)
    if fmt != "r32_uint":
        raise ValueError(f"Image atomics on {fmt} are not lowered (D3D atomics need a one-channel 32-bit format)")
    if (op in ORDERED or glc) and shared(st, address):
        raise ValueError("An order-dependent image atomic or returned value on a texel every lane shares")
    regs = vgprs(data_token, 2 if op == "cmpswap" else 1)
    words = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in regs]
    if glc and regs[0] in st.sample_dest:
        raise ValueError("Write overlaps an outstanding sample")
    st.declarations.setdefault(f"image{slot}", store_helper(slot, "uint"))
    st.declarations.setdefault("image_atomic_value", IMAGE_ATOMIC_VALUE)
    st.declarations.setdefault(f"image_atomic{slot}", atomic_helper(slot))
    cmp = words[1] if op == "cmpswap" else "0u"
    returned(st, i, regs[0] if glc else None,
             f"image_atomic{slot}({address[0]}, {address[1]}, {OPS[op]}u, {words[0]}, {cmp})")
