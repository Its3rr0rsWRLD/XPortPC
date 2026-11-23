"""Descriptor bindings of a program, shared by the pixel stage (lower(bindings=PixelBindings(...))) and the compute stage
(tools/compute_aot.py); design: docs/design/pixel-bindings.md.

A descriptor is named by its key: its byte offset in descriptor set 0, or SET_STRIDE * N + its offset in set N. The
entry SGPRs that hold the 32-bit descriptor-set pointers are named by role ("descriptors" for set 0, "descriptors.N"),
and every descriptor the program loads is resolved word by word against the declared ones
(forms/smem.descriptor_load): a T# (32 bytes), an S# (16 bytes), a constant-buffer V# (16 bytes, read by s_buffer_load),
a buffer V# whose words are constant words (16 bytes), a storage-image T# (32 bytes). A word no declared descriptor
covers is refused.

HLSL names and registers of the pixel stage (the harness binds them, tests/pixel_aot_render.cpp):
    texture k   tex (t0), tex1 (t1), tex2..tex7 (t3..t8; t2 is the title ranges)
    sampler k   samp (s0), samp1..samp3 (s1..s3)
    constants k params (b0), params1..params3 (b2..b4; b1 is the title range count), 64 words each unless
                constant_sizes gives slot k a larger window
    inputs      the SPI_PS_INPUT_ENA layout of the input VGPRs (input_vgprs): persp_center as v0, v1 (bary_i, bary_j);
                positions, front face and pixel coordinate from SV_Position and SV_IsFrontFace
"""
from dataclasses import dataclass, field
import re


# SMEM offsets are 20 bits, so the keys of two sets never meet.
SET_STRIDE = 0x100000
# RADV completes a 32-bit descriptor-set pointer with s_movk_i32 s(n+1), 0x8000, which sign-extends to 0xffff8000
# (its address32_hi on gfx10).
RADV_DESCRIPTOR_HIGH = 0xffff8000
TEXTURE_SLOTS, SAMPLER_SLOTS, CONSTANT_SLOTS = 8, 4, 4
# The bytes of a constant slot's window without constant_sizes (16 uint4), and the most one may have: a D3D12 constant
# buffer view is at most 4096 uint4 (D3D12_REQ_CONSTANT_BUFFER_ELEMENT_COUNT).
CONSTANT_WINDOW, MAX_CONSTANT_WINDOW = 256, 4096 * 16

# The pixel input VGPRs (docs/design/pixel-bindings.md, "Input VGPRs"): the inputs of SPI_PS_INPUT_ENA and
# SPI_PS_INPUT_ADDR in bit order (AMD's register layout, Mesa sid.h S_0286CC_*_ENA) and the VGPRs each takes. The
# hardware gives VGPRs to the inputs whose ADDR bit is set, in bit order from v0, and loads those whose ENA bit is set
# too (ENA is a subset of ADDR); ACO sets ADDR equal to ENA. Of the barycentric inputs only persp_center is lowered:
# the desktop interpolates at the pixel centre, which is what v_interp reads from it (bary_i, bary_j).
PS_INPUTS = (("persp_sample", 2), ("persp_center", 2), ("persp_centroid", 2), ("persp_pull_model", 3),
             ("linear_sample", 2), ("linear_center", 2), ("linear_centroid", 2), ("line_stipple", 1),
             ("pos_x", 1), ("pos_y", 1), ("pos_z", 1), ("pos_w", 1), ("front_face", 1), ("ancillary", 1),
             ("sample_coverage", 1), ("pos_fixed_pt", 1))
PS_INPUT_BITS = {name: bit for bit, (name, _) in enumerate(PS_INPUTS)}
PERSP_CENTER = 1 << PS_INPUT_BITS["persp_center"]
# The tracked value of each lowered input VGPR: the barycentrics, and the words main computes from SV_Position and
# SV_IsFrontFace (lowering.INPUT_WORDS) for the others.
LOWERED_INPUTS = {("persp_center", 0): "bary_i", ("persp_center", 1): "bary_j",
                  **{(f"pos_{c}", 0): ("uint", f"psin_{c}") for c in "xyzw"},
                  ("front_face", 0): ("uint", "psin_face"), ("pos_fixed_pt", 0): ("uint", "psin_pixel")}


def input_vgprs(ena, addr=None):
    """{"vN": (input name, component)} of every VGPR the inputs occupy under SPI_PS_INPUT_ENA `ena` and
    SPI_PS_INPUT_ADDR `addr` (None: equal to ena, as ACO sets it), and the set of those whose input is enabled."""
    addr = ena if addr is None else addr
    layout, enabled, at = {}, set(), 0
    for bit, (name, width) in enumerate(PS_INPUTS):
        if addr >> bit & 1:
            for k in range(width):
                layout[f"v{at}"] = (name, k)
                if ena >> bit & 1:
                    enabled.add(f"v{at}")
                at += 1
    return layout, enabled

# Texture dimensions a T# may declare, with the HLSL type each is bound as (docs/design/pixel-bindings.md): a cube is
# bound as a Texture2DArray view of its six faces (slices 0..5 = +X, -X, +Y, -Y, +Z, -Z), sampled at the face
# coordinates the program computes, not at a direction.
DIMENSIONS = {"2d": "Texture2D<float4>", "2d_array": "Texture2DArray<float4>", "cube": "Texture2DArray<float4>",
              "3d": "Texture3D<float4>"}
# The dim: field of a MIMG instruction (gfx10 SQ_RSRC_IMG_*) for each dimension.
INSTRUCTION_DIMS = {"SQ_RSRC_IMG_2D": "2d", "SQ_RSRC_IMG_2D_ARRAY": "2d_array", "SQ_RSRC_IMG_CUBE": "cube",
                    "SQ_RSRC_IMG_3D": "3d"}
# The TYPE field of a gfx10 image T# (word 3, bits 28..31; AMD's SQ_RSRC_IMG_* encoding, Mesa sid.h V_008F1C_*):
# 8 1D, 9 2D, 10 3D, 11 cube, 12 1D array, 13 2D array, 14 2D MSAA, 15 2D MSAA array. Only these four are bound.
TYPE_DIMS = {9: "2d", 10: "3d", 11: "cube", 13: "2d_array"}


def type_dimension(words):
    """The dimension the TYPE field of a T#'s eight words names, or a ValueError for one this stage does not bind."""
    if not (isinstance(words, tuple) and len(words) == 8 and all(isinstance(w, int) and 0 <= w <= 0xffffffff
                                                                 for w in words)):
        raise ValueError("A texture dimension is a name or the eight words of the T#")
    kind = words[3] >> 28
    if kind not in TYPE_DIMS:
        raise ValueError(f"Unsupported T# type {kind} (word 3 bits 28..31)")
    return TYPE_DIMS[kind]


def valid_key(key, size):
    """A descriptor key (set * SET_STRIDE + byte offset) of a descriptor of `size` bytes in one of sets 0 to 7."""
    return isinstance(key, int) and 0 <= key < 8 * SET_STRIDE and key % 16 == 0 and key % SET_STRIDE + size <= SET_STRIDE


def overlap(spans):
    """Whether any two of the (key, size) descriptor spans share a byte."""
    spans = sorted(spans)
    return any(b < a + size for (a, size), (b, _) in zip(spans, spans[1:]))


def pointer_role(role):
    """The tracked value an entry SGPR with this descriptor-set role holds (forms/smem.table_set), or None."""
    if role == "descriptors":
        return "texture_ptr"
    if m := re.fullmatch(r"descriptors\.([1-7])", role):
        return f"texture_ptr.{m[1]}"
    return None


def describe_key(key):
    return f"set {key // SET_STRIDE} +{key % SET_STRIDE:#x}"


def texture_name(k):
    return "tex" if k == 0 else f"tex{k}"


def texture_register(k):
    return k if k < 2 else k + 1


def sampler_name(k):
    return "samp" if k == 0 else f"samp{k}"


def sampler_tag(k):
    """The tracked name of the words of sampler k loaded from memory, ("sampler<k>", j)."""
    return "sampler" if k == 0 else f"sampler{k}"


def constant_array(k):
    return "params" if k == 0 else f"params{k}"


def constant_tag(k):
    """The tracked name of the words of the constant-buffer V# of slot k, ("cbv<k>", j)."""
    return "cbv" if k == 0 else f"cbv{k}"


def constant_array_of_tag(tag):
    """params<k> for the V# tag cbv<k>, or None."""
    m = re.fullmatch(r"cbv([1-3]?)", tag) if isinstance(tag, str) else None
    return None if m is None else constant_array(int(m[1] or 0))


def word(array, n):
    return f"{array}[{n // 4}].{'xyzw'[n % 4]}"


@dataclass(frozen=True)
class PixelBindings:
    """The binding description of a pixel program (docs/design/pixel-bindings.md).

    sgprs: {"sN": role}: "descriptors" (set 0 pointer), "descriptors.N" (N 1..7), "interp" (the interpolation base
        copied into m0) or "push:W" (push-constant word W, 0..63, of the constant slot push_constants).
    textures: {key of a T#: texture slot 0..7}. samplers: {sampler slot 0..3: key of an S# loaded from memory, or the
        four words s_mov puts in the sampler registers (an immutable sampler RADV inlines)}.
    constant_buffers: {key of a constant-buffer V#: constant slot 0..3}. push_constants: the constant slot that holds
        the push words, or None. buffers: {key of a buffer V#: index of its first word in params (slot 0)}.
    storage_images: {key of a storage-image T#: (slot 0..3, format)} (forms/image_writes.py).
    descriptor_high: the high word the program completes a descriptor-set pointer with.
    dimensions: {texture slot: "2d", "2d_array", "cube" or "3d", or the T#'s eight words when they are known, whose
        TYPE field (type_dimension) gives it}; a slot not listed is 2D.
    constant_sizes: {constant slot: bytes of the window the runtime binds for that constant-buffer V#, a multiple of 16
        from 256 to 65536}; a slot not listed binds 256. A read past the window is refused; params<k>[] is declared
        with the uint4 up to the highest word read (16 at least), or the whole window for a run-time offset.
    ps_input_ena, ps_input_addr: SPI_PS_INPUT_ENA and SPI_PS_INPUT_ADDR (input_vgprs; addr None is ena). The default,
        persp_center alone, is the v0, v1 barycentrics every description had before."""
    sgprs: dict
    textures: dict = field(default_factory=dict)
    samplers: dict = field(default_factory=dict)
    constant_buffers: dict = field(default_factory=dict)
    push_constants: int = None
    buffers: dict = field(default_factory=dict)
    storage_images: dict = field(default_factory=dict)
    descriptor_high: int = RADV_DESCRIPTOR_HIGH
    dimensions: dict = field(default_factory=dict)
    constant_sizes: dict = field(default_factory=dict)
    ps_input_ena: int = PERSP_CENTER
    ps_input_addr: int = None

    def dimension(self, slot):
        """The dimension of texture slot `slot`: the declared name, the TYPE field of declared T# words, else 2D."""
        source = self.dimensions.get(slot, "2d")
        return source if isinstance(source, str) else type_dimension(source)

    def check(self):
        """Refuse a description that is malformed or names one binding twice."""
        roles = list(self.sgprs.values())
        for reg, role in self.sgprs.items():
            if not re.fullmatch(r"s(\d+)", reg) or int(reg[1:]) > 105:
                raise ValueError(f"Invalid entry SGPR {reg}")
            push = re.fullmatch(r"push:(\d+)", role) if isinstance(role, str) else None
            if not (pointer_role(role) or role == "interp" or push and int(push[1]) < 64):
                raise ValueError(f"Unknown entry SGPR role {role}")
            if push and self.push_constants is None:
                raise ValueError("A push-constant SGPR needs a push-constant slot")
            if roles.count(role) > 1:
                raise ValueError(f"Entry SGPR role {role} is given twice")
        for slot, source in self.dimensions.items():
            if slot not in self.textures.values() or not (source in DIMENSIONS or not isinstance(source, str) and type_dimension(source)):
                raise ValueError("A texture dimension needs a declared texture slot and a known dimension")
        if not isinstance(self.descriptor_high, int) or not 0 <= self.descriptor_high <= 0xffffffff:
            raise ValueError("Invalid descriptor high word")
        slots = list(self.textures.values())
        if any(not valid_key(k, 32) for k in self.textures) or any(s not in range(TEXTURE_SLOTS) for s in slots) \
                or len(set(slots)) != len(slots):
            raise ValueError("Invalid texture key or slot (0 to 7, each once)")
        for slot, source in self.samplers.items():
            if slot not in range(SAMPLER_SLOTS):
                raise ValueError("Invalid sampler slot (0 to 3)")
            if not (valid_key(source, 16) or isinstance(source, tuple) and len(source) == 4
                    and all(isinstance(w, int) and 0 <= w <= 0xffffffff for w in source)):
                raise ValueError("A sampler is a descriptor key or four constant words")
        inline = [s for s in self.samplers.values() if isinstance(s, tuple)]
        if len(set(inline)) != len(inline):
            raise ValueError("Two inline samplers have the same words")
        cslots = list(self.constant_buffers.values())
        if self.push_constants is not None:
            cslots.append(self.push_constants)
        if any(not valid_key(k, 16) for k in self.constant_buffers) or any(s not in range(CONSTANT_SLOTS) for s in cslots) \
                or len(set(cslots)) != len(cslots):
            raise ValueError("Invalid constant-buffer key or slot (0 to 3, each once)")
        if self.buffers and 0 not in cslots:
            raise ValueError("Buffer descriptors need constant slot 0")
        if any(not valid_key(k, 16) or not isinstance(w, int) or not 0 <= w <= 60 for k, w in self.buffers.items()):
            raise ValueError("Invalid buffer descriptor offset or constant word")
        images = [e[0] if isinstance(e, tuple) and len(e) == 2 else None for e in self.storage_images.values()]
        if any(not valid_key(k, 32) for k in self.storage_images) or any(s not in range(4) for s in images) \
                or len(set(images)) != len(images):
            raise ValueError("Invalid storage image key or slot")
        spans = [*((k, 32) for k in (*self.textures, *self.storage_images)), *((k, 16) for k in self.constant_buffers),
                 *((k, 16) for k in self.buffers), *((k, 16) for k in self.samplers.values() if isinstance(k, int))]
        if len({k for k, _ in spans}) != len(spans) or overlap(spans):
            raise ValueError("Descriptor-table entries overlap")
        for slot, size in self.constant_sizes.items():
            if slot not in self.constant_buffers.values() or not isinstance(size, int) or size % 16 \
                    or not CONSTANT_WINDOW <= size <= MAX_CONSTANT_WINDOW:
                raise ValueError("A constant window needs a constant-buffer slot and 256 to 65536 bytes, a multiple of 16")
        addr = self.ps_input_ena if self.ps_input_addr is None else self.ps_input_addr
        if not all(isinstance(w, int) and 0 <= w < 1 << 16 for w in (self.ps_input_ena, addr)) \
                or self.ps_input_ena & ~addr or not self.ps_input_ena & 0x7f:
            raise ValueError("SPI_PS_INPUT_ENA needs a barycentric input (bits 0 to 6) and its bits set in "
                             "SPI_PS_INPUT_ADDR (16 bits each)")
        if self.push_constants == 0 and self.buffers:
            pushed = {int(r[5:]) for r in roles if r.startswith("push:")}
            if any(w <= u < w + 4 for u in pushed for w in self.buffers.values()):
                raise ValueError("A push-constant word overlaps the words of a buffer V#")

    def names(self):
        """One line per binding, in a fixed order: what each entry SGPR and each declared descriptor is bound to."""
        out = [f"{reg}: {role}" for reg, role in sorted(self.sgprs.items(), key=lambda kv: int(kv[0][1:]))]
        out += [f"{describe_key(k)}: T# {texture_name(s)} (t{texture_register(s)})"
                + ("" if self.dimension(s) == "2d" else f" {self.dimension(s)}") for k, s in sorted(self.textures.items())]
        for s, source in sorted(self.samplers.items()):
            where = describe_key(source) if isinstance(source, int) else "words " + " ".join(f"{w:#x}" for w in source)
            out.append(f"{where}: S# {sampler_name(s)} (s{s})")
        out += [f"{describe_key(k)}: V# {constant_array(s)} (b{0 if s == 0 else s + 1})"
                for k, s in sorted(self.constant_buffers.items())]
        if self.push_constants is not None:
            s = self.push_constants
            out.append(f"push constants: {constant_array(s)} (b{0 if s == 0 else s + 1})")
        out += [f"{describe_key(k)}: buffer V# in params words {w}..{w + 3}" for k, w in sorted(self.buffers.items())]
        out += [f"{describe_key(k)}: storage image {e[0]} ({e[1]})" for k, e in sorted(self.storage_images.items())]
        out += [f"{constant_array(s)}: {size} bytes" for s, size in sorted(self.constant_sizes.items())]
        if self.ps_input_ena != PERSP_CENTER or self.ps_input_addr not in (None, PERSP_CENTER):
            layout, enabled = input_vgprs(self.ps_input_ena, self.ps_input_addr)
            out += [f"{reg}: {name}{f'.{k}' if dict(PS_INPUTS)[name] > 1 else ''}{'' if reg in enabled else ' (unloaded)'}"
                    for reg, (name, k) in layout.items()]
        return out


def declarations(b):
    """The HLSL declarations of a description, top to bottom, and whether texture 0 and sampler 0 are both declared
    (then the pixel PREAMBLE declares them, exactly as for the fixed contract)."""
    textures, samplers = set(b.textures.values()), set(b.samplers)
    # The PREAMBLE declares tex as a Texture2D, so a texture 0 of another dimension is declared here instead.
    sampled = 0 in textures and 0 in samplers and b.dimension(0) == "2d"
    lines = []
    if 0 in textures and not sampled:
        lines.append(f"{DIMENSIONS[b.dimension(0)]} tex : register(t0);")
    lines += [f"{DIMENSIONS[b.dimension(k)]} {texture_name(k)} : register(t{texture_register(k)});"
              for k in sorted(textures - {0})]
    if 0 in samplers and not sampled:
        lines.append("SamplerState samp : register(s0);")
    lines += [f"SamplerState {sampler_name(k)} : register(s{k});" for k in sorted(samplers - {0})]
    cslots = set(b.constant_buffers.values()) | ({b.push_constants} if b.push_constants is not None else set())
    for k in sorted(cslots):
        lines.append("cbuffer Constants : register(b0) { uint4 params[16]; };" if k == 0 else
                     f"cbuffer Constants{k} : register(b{k + 1}) {{ uint4 {constant_array(k)}[16]; }};")
    return lines, sampled
