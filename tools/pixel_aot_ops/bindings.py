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
    constants k params (b0), params1..params3 (b2..b4; b1 is the title range count), 64 words each
"""
from dataclasses import dataclass, field
import re


# SMEM offsets are 20 bits, so the keys of two sets never meet.
SET_STRIDE = 0x100000
# RADV completes a 32-bit descriptor-set pointer with s_movk_i32 s(n+1), 0x8000, which sign-extends to 0xffff8000
# (its address32_hi on gfx10).
RADV_DESCRIPTOR_HIGH = 0xffff8000
TEXTURE_SLOTS, SAMPLER_SLOTS, CONSTANT_SLOTS = 8, 4, 4


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
    buffer_words: where the buffer V# words are: "params" (constant slot 0's words 0..63, the harness contract) or
        "vsharp_words" (a descriptor-words buffer of its own, b5 in the converter's registers, words 0..127; the
        graphics shim's contract, tools/pso_translate.py), which needs no constant slot 0.
    storage_images: {key of a storage-image T#: (slot 0..3, format)} (forms/image_writes.py).
    descriptor_high: the high word the program completes a descriptor-set pointer with."""
    sgprs: dict
    textures: dict = field(default_factory=dict)
    samplers: dict = field(default_factory=dict)
    constant_buffers: dict = field(default_factory=dict)
    push_constants: int = None
    buffers: dict = field(default_factory=dict)
    storage_images: dict = field(default_factory=dict)
    descriptor_high: int = RADV_DESCRIPTOR_HIGH
    buffer_words: str = "params"

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
        if self.buffer_words not in ("params", "vsharp_words"):
            raise ValueError("Invalid buffer descriptor words array")
        own = self.buffer_words == "vsharp_words"
        if self.buffers and 0 not in cslots and not own:
            raise ValueError("Buffer descriptors need constant slot 0")
        if any(not valid_key(k, 16) or not isinstance(w, int) or not 0 <= w <= (124 if own else 60)
               for k, w in self.buffers.items()):
            raise ValueError("Invalid buffer descriptor offset or constant word")
        if own:
            words = sorted(self.buffers.values())
            if any(b < a + 4 for a, b in zip(words, words[1:])):
                raise ValueError("Invalid buffer descriptor offset or constant word")
        images = [e[0] if isinstance(e, tuple) and len(e) == 2 else None for e in self.storage_images.values()]
        if any(not valid_key(k, 32) for k in self.storage_images) or any(s not in range(4) for s in images) \
                or len(set(images)) != len(images):
            raise ValueError("Invalid storage image key or slot")
        spans = [*((k, 32) for k in (*self.textures, *self.storage_images)), *((k, 16) for k in self.constant_buffers),
                 *((k, 16) for k in self.buffers), *((k, 16) for k in self.samplers.values() if isinstance(k, int))]
        if len({k for k, _ in spans}) != len(spans) or overlap(spans):
            raise ValueError("Descriptor-table entries overlap")
        if self.push_constants == 0 and self.buffers and not own:
            pushed = {int(r[5:]) for r in roles if r.startswith("push:")}
            if any(w <= u < w + 4 for u in pushed for w in self.buffers.values()):
                raise ValueError("A push-constant word overlaps the words of a buffer V#")

    def names(self):
        """One line per binding, in a fixed order: what each entry SGPR and each declared descriptor is bound to."""
        out = [f"{reg}: {role}" for reg, role in sorted(self.sgprs.items(), key=lambda kv: int(kv[0][1:]))]
        out += [f"{describe_key(k)}: T# {texture_name(s)} (t{texture_register(s)})" for k, s in sorted(self.textures.items())]
        for s, source in sorted(self.samplers.items()):
            where = describe_key(source) if isinstance(source, int) else "words " + " ".join(f"{w:#x}" for w in source)
            out.append(f"{where}: S# {sampler_name(s)} (s{s})")
        out += [f"{describe_key(k)}: V# {constant_array(s)} (b{0 if s == 0 else s + 1})"
                for k, s in sorted(self.constant_buffers.items())]
        if self.push_constants is not None:
            s = self.push_constants
            out.append(f"push constants: {constant_array(s)} (b{0 if s == 0 else s + 1})")
        out += [f"{describe_key(k)}: buffer V# in {self.buffer_words} words {w}..{w + 3}"
                for k, w in sorted(self.buffers.items())]
        out += [f"{describe_key(k)}: storage image {e[0]} ({e[1]})" for k, e in sorted(self.storage_images.items())]
        return out


def declarations(b):
    """The HLSL declarations of a description, top to bottom, and whether texture 0 and sampler 0 are both declared
    (then the pixel PREAMBLE declares them, exactly as for the fixed contract)."""
    textures, samplers = set(b.textures.values()), set(b.samplers)
    sampled = 0 in textures and 0 in samplers
    lines = []
    if 0 in textures and not sampled:
        lines.append("Texture2D<float4> tex : register(t0);")
    lines += [f"Texture2D<float4> {texture_name(k)} : register(t{texture_register(k)});" for k in sorted(textures - {0})]
    if 0 in samplers and not sampled:
        lines.append("SamplerState samp : register(s0);")
    lines += [f"SamplerState {sampler_name(k)} : register(s{k});" for k in sorted(samplers - {0})]
    cslots = set(b.constant_buffers.values()) | ({b.push_constants} if b.push_constants is not None else set())
    for k in sorted(cslots):
        lines.append("cbuffer Constants : register(b0) { uint4 params[16]; };" if k == 0 else
                     f"cbuffer Constants{k} : register(b{k + 1}) {{ uint4 {constant_array(k)}[16]; }};")
    if b.buffers and b.buffer_words == "vsharp_words":
        lines.append("cbuffer Descriptors : register(b5) { uint4 vsharp_words[32]; };")
    return lines, sampled
