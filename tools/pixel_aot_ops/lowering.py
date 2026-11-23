"""lower(): one pass over a gfx1013 pixel program that tracks every register symbolically and emits HLSL. The forms
in forms/ lower the instructions; this module owns the state they share, the checks around them and the final text."""
import re

from .control_flow import (JOIN_POISON, JOIN_POISON_MESSAGE, POISON_MESSAGE, find_loops, poisoned_operands, program,
                           split_blocks, word_expr)
from .dispatch import GUARDS, dispatch
from .hlsl import (MEMORY_HELPERS, PREAMBLE, SALU_HELPERS, TITLE_DECLARATIONS, TITLE_LOOKUP, TITLE_RW_DECLARATIONS,
                   UNSAMPLED_PREAMBLE)
from .registers import tracked_word
from . import bindings as binding_names
from .bindings import PixelBindings
from . import forms  # noqa: F401  (registers every form)
from .forms.vop3p import place_fma_mix


# What may come between the done export and s_endpgm: an export-counter wait and the scheduling hints s_nop and
# s_inst_prefetch, none of which changes a result (from R0Y00/Xbox2Windows#271 by Rachel Amber).
AFTER_EXPORT = re.compile(r"s_waitcnt_expcnt (?:(?:null|s\d+), )?(?:0x[0-7]|[0-7])|s_waitcnt expcnt\([0-7]\)"
                          r"|(?:s_inst_prefetch|s_nop) (?:0x[0-9a-f]+|\d+)")


class Lowering:
    """The state of one lower() call. Forms read and write it as `st`; the control-flow walk snapshots and restores
    the per-path part (scalar, vector, pending, scc, ex, wqm, samples, sample_dest, vm_issued, exports, exported,
    ended)."""

    def __init__(self, scalar, vector, lines, bindings, sampler, constant_descriptor, vsharp_words):
        self.scalar = scalar  # SGPR name (and "m0", "vcc") -> tracked value, see registers.py
        self.vector = vector  # VGPR name -> tracked value
        self.lines = lines  # the HLSL text so far; the preamble entry marks where helper definitions go
        self.preamble = PREAMBLE  # that entry: PREAMBLE, or UNSAMPLED_PREAMBLE for a program bound without a sampler
        self.bindings = bindings  # descriptor-table byte offset of a T# -> HLSL texture name
        self.sampler = sampler  # the four sampler descriptor words bound to s0; () when no sampler is bound
        self.sampler_offsets = {}  # descriptor key of a sampler S# loaded from memory -> its word tag (forms/smem.py)
        # Under a binding description (lower(bindings=...), docs/design/pixel-bindings.md) and in the compute stage:
        # every descriptor load is resolved word by word (forms/smem.compute_descriptor_load).
        self.descriptor_words = False
        self.constant_buffers = {}  # descriptor key of a constant-buffer V# -> its word tag "cbv<k>" (bindings.py)
        self.samplers = None  # HLSL sampler name -> its four tracked words; None: the one sampler st.sampler, "samp"
        self.constant_descriptor = constant_descriptor  # byte offset of the constant-buffer V#, or None
        self.vsharp_words = vsharp_words  # byte offset of a buffer V# -> index of its first word in vsharp_array
        self.vsharp_array = "params"  # the uint4 array that holds the buffer V# words (bindings.PixelBindings.buffer_words)
        self.constant_limit = 256  # bytes of b0 a scalar buffer load may read; the vertex stage raises it (vertex_aot.py)
        self.constant_words = 0  # one past the highest b0 word a load has read: sizes params[] when it exceeds 64
        self.uses_memory = False  # emit the title-memory helpers
        self.writes_memory = False  # a store or atomic: title memory is declared writable (hlsl.TITLE_RW_DECLARATIONS)
        self.memory_helpers = {}  # name -> HLSL a form needs after MEMORY_HELPERS (it may call them), in insertion order
        self.storage_images = {}  # descriptor-table byte offset of a storage-image T# -> (slot, format); forms/image_writes.py
        self.declarations = {}  # name -> HLSL declarations and helpers a form needs before the preamble, in insertion order
        self.pending = set()  # SGPRs an outstanding scalar load writes (cleared by lgkmcnt(0))
        self.scc = None  # SCC as an HLSL bool expression, or None when it is not tracked
        self.helpers = set()  # names of SALU_HELPERS (hlsl.py) the program uses
        # This lane's EXEC bit (docs/design/control-flow.md, CF-2 section 2): an HLSL bool expression, "true" when the
        # lane is provably active. Every lane starts active; desktop helper invocations run with ex true throughout.
        self.ex = "true"
        self.wqm = False  # s_wqm_b64 exec, exec has put the wave in whole-quad mode (attribute interpolation needs it)
        # Values defined on the helper lanes of the quad too: the interpolated coordinate and whole-quad affine
        # arithmetic on it (valu_f32.arithmetic). Each name is unique, so the set only grows; True marks a value that
        # depends on the interpolated coordinate. An implicit-LOD sample may read only these.
        self.quad_values = {"uv.x": True, "uv.y": True}
        # Values defined on the helper lanes by any whole-quad VALU operation on quad values (not only affine ones):
        # a cube sample's face coordinates (forms/mimg.py) may read them; see docs/design/pixel-bindings.md.
        self.quad_defined = set()
        # Binary32 values that are integers (or NaN, which no form below produces from these): results of v_rndne,
        # v_floor, v_ceil, v_trunc and v_cvt_f32_{i32,u32}, integral immediates and copies of them. An array slice
        # must be one (forms/mimg.py). cube_faces: v_cubeid results and copies, the face of a cube sample.
        self.integral = set()
        self.cube_faces = set()
        self.texture_dims = {}  # HLSL texture name -> "2d_array", "cube" or "3d" (bindings.PixelBindings); absent: 2D
        self.samples = 0  # samples taken on the path so far
        # VGPR -> (issue number, kind) of the outstanding sample or vector memory load that writes it. vmcnt(N) completes
        # all but the newest N of them (from R0Y00/Xbox2Windows#176 by descent81); vmcnt(0) completes all.
        self.sample_dest = {}
        self.integer_export = False  # the uncompressed export returns uint4 bit patterns (lower(integer_export=True))
        self.vm_issued = 0  # vector memory loads and samples issued on the path so far (the vmcnt issue order)
        self.flat_attrs = set()  # attributes read without interpolation
        self.interp_attrs = set()  # attributes interpolated by v_interp_p1/p2 (forms/vintrp.py)
        # attr0 interpolated in its z or w component (forms/vintrp.py): TEXCOORD0 is declared float4.
        self.attribute_input = False
        self.quad_position = False  # the quad lane of this pixel is needed (quad.quad_read): declare SV_Position
        self.texcoord4 = False  # lower(texcoord_components=4): TEXCOORD0 is declared float4
        self.compressed_mrt0 = False  # the done export is the compressed mrt0 export alone (forms/exp.py)
        self.exports = ()  # exports before the done export on this path: (output name, width, mask, HLSL local)
        self.exported = False  # the done export has been emitted
        self.layout = None  # the outputs the done export returns, the same on every path (forms/exp.py)
        self.signature = None  # (return type, declaration) of main when it is not the preamble's float4 SV_Target0
        self.broke = False  # CF-2e: the path left the loop through s_branch to its exit (ended is set with it)
        self.ended = False  # s_endpgm after the export
        # Stage hooks (docs/design/compute-stage.md): the stage being lowered, and the high word a descriptor-list
        # pointer is completed with (0 for the pixel contract; tools/compute_aot.py sets RADV's 0xffff8000).
        self.stage = "pixel"
        # tbuffer_load_format may name any gfx10 format (the vertex stage, whose typed draws check them all); otherwise
        # only the two the pixel draws check (forms/mtbuf.py).
        self.all_buffer_formats = False
        self.descriptor_high = 0
        # CF-2c: each VOPC compare's relation without the EXEC mask, the line count when it was written and the lane bit
        # it ran under, by the name of its bool (cmp<i>); s_cbranch_vccz/vccnz on a uniform compare branches on it
        # (control_flow.uniform_vcc).
        self.compares = {}
        # CF-2c: HLSL names a VGPR took unmasked because it had no value before (masked_writes); a lane that was
        # inactive holds something else on the console, so they are never wave-uniform.
        self.lane_values = set()
        # C-7 (forms/lanes.py): each masked-write name -> (the lane bit it was written under, the new word), and the
        # names of v_readfirstlane_b32 results the compute stage must prove wave-uniform once the text is complete.
        self.masked = {}
        self.uniform_claims = []
        # CF-2d: (index, bit) of the last mask operation, whose SCC (D != 0) is lane local: this lane's part of it is
        # its bit of D. Only s_cbranch_scc0 to the all-lanes-dead block reads it (control_flow.program).
        self.lane_scc = None
        # CF-2d: the lane bits a v_cvt_pkrtz_f16_f32 ran under while the lane may have been inactive, by destination
        # VGPR and instruction index. The packed pair is not masked (it is no word); the export it feeds must run under
        # a bit that implies each of them, so that a lane that exports holds the new pair.
        self.pack_ex = {}
        # C-6 (forms/lds.py, compute stage): the LDS allocation in bytes (0: none), the workgroup size, the LDS
        # accesses since the last s_barrier on this path (joined by control_flow.program) and the name of each LDS
        # read word with the address it was read at (roots of the uniformity lattice when the address is uniform).
        self.lds_size = 0
        self.numthreads = (1, 1, 1)
        self.lds_epoch = frozenset()
        self.lds_reads = {}

    @property
    def sample_pending(self):
        """The outstanding loads' destination VGPRs: truthy while any load is outstanding. The operand readers in
        registers.py take it as their `sample_pending` argument and refuse a source register that is in it, so a
        register whose own load has completed is readable while a newer load is still in flight."""
        return self.sample_dest

    def vm_issue(self, registers, kind):
        """Record a sample or load of `kind` ("sample", "mubuf", "mtbuf", "flat") that writes `registers`."""
        self.vm_issued += 1
        for register in registers:
            self.sample_dest[register] = (self.vm_issued, kind)

    def vm_wait(self, limit):
        """s_waitcnt vmcnt(limit): only the newest `limit` loads can remain outstanding. Loads of different kinds are
        not known to return in order, so while two kinds are outstanding only a wait for all of them (limit 0) completes
        any. Filtering the current set keeps what earlier, tighter waits already guaranteed."""
        if limit > 63:
            raise ValueError("VM wait count exceeds the gfx10 six-bit field")
        if limit and len({kind for _, kind in self.sample_dest.values()}) > 1:
            return
        self.sample_dest = {reg: entry for reg, entry in self.sample_dest.items() if entry[0] > self.vm_issued - limit}

    @property
    def mask(self):
        """Deprecated, read-only: the execution mask as it was before CF-2a ("entry", "quad"), for forms written
        against it. It is never "entry" in whole-quad mode or while a lane may be inactive, so such a form keeps
        refusing exactly where it refused before. New forms test `ex` (and `wqm`) instead."""
        if self.ex != "true":
            return "partial"
        return "quad" if self.wqm else "entry"

    def exec_and(self, i, bit):
        """EXEC &= a mask whose bit for this lane is `bit` (a bool expression): this lane's ex becomes ex && bit. A
        new ex other than "true" is held in `bool ex<i>`."""
        if bit != "true":
            expression = bit if self.ex == "true" else f"{self.ex} && {bit}"
            self.lines.append(f"    bool ex{i} = {expression};")
            self.ex = f"ex{i}"


def masked_writes(st, i, ex, before):
    """The masked-write rule for instruction i, run while this lane's EXEC bit was `ex` (not "true"): a VGPR the
    instruction wrote keeps its old value when the lane is inactive, `v = ex ? new : old`. A register with no value
    before takes the new one (a refinement of an undefined register). Both values must be 32-bit words."""
    for reg, value in list(st.vector.items()):
        if i in st.pack_ex.get(reg, {}):
            continue
        old = before.get(reg)
        if old is None and value is not None:
            st.lane_values.add(word_expr(value) or str(value))
        if old is None or value == old:
            continue
        new_word, old_word = word_expr(value), word_expr(old)
        if new_word is None or old_word is None:
            raise ValueError("Masked write of a register that does not hold a 32-bit word")
        # exw: both sides are raw words that the float readers accept (registers.RAW_WORD_PREFIXES); exv: an integer result.
        # mem_ex: the destination of an outstanding sample (CF-2c), which, like a memory word, waits for vmcnt(0).
        name = f"{'exw' if tracked_word(value) and tracked_word(old) else 'exv'}{i}_{reg[1:]}"
        if reg in st.sample_dest:
            name = f"mem_ex{i}_{reg[1:]}"
        st.lines.append(f"    uint {name} = {ex} ? {new_word} : {old_word};")
        st.masked[name] = (ex, new_word)
        st.vector[reg] = ("uint", name)


def poison_message(st, regs):
    """The refusal of an instruction that reads registers poisoned at a reconvergence point (control_flow.POISON)."""
    kind = JOIN_POISON_MESSAGE if all(st.scalar.get(r) == JOIN_POISON for r in regs) else POISON_MESSAGE
    return f"{kind}: {', '.join(regs)}"


def described_state(b):
    """The Lowering of a program bound by the binding description b (bindings.PixelBindings,
    docs/design/pixel-bindings.md): entry SGPRs by role, every declared descriptor resolved word by word."""
    if not isinstance(b, PixelBindings):
        raise ValueError("bindings must be a PixelBindings")
    b.check()
    scalar = {}
    for reg, role in b.sgprs.items():
        if role == "interp":
            scalar[reg] = "interp_base"
        elif role.startswith("push:"):
            scalar[reg] = ("uint", binding_names.word(binding_names.constant_array(b.push_constants), int(role[5:])))
        else:
            scalar[reg] = binding_names.pointer_role(role)
    head, sampled = binding_names.declarations(b)
    preamble = PREAMBLE if sampled else UNSAMPLED_PREAMBLE
    st = Lowering(scalar, {"v0": "bary_i", "v1": "bary_j"}, [*head, preamble],
                  {key: binding_names.texture_name(k) for key, k in b.textures.items()}, (), None, dict(b.buffers))
    st.preamble = preamble
    st.texture_dims = {binding_names.texture_name(k): dim for k in b.textures.values()
                       if (dim := b.dimension(k)) != "2d"}
    st.descriptor_words = True
    st.descriptor_high = b.descriptor_high
    st.vsharp_array = b.buffer_words
    st.constant_buffers = {key: binding_names.constant_tag(k) for key, k in b.constant_buffers.items()}
    st.sampler_offsets = {key: binding_names.sampler_tag(k) for k, key in b.samplers.items() if isinstance(key, int)}
    st.samplers = {binding_names.sampler_name(k): tuple((binding_names.sampler_tag(k), j) for j in range(4))
                   if isinstance(key, int) else tuple(key) for k, key in sorted(b.samplers.items())}
    st.storage_images.update(b.storage_images)
    return st


def lower(instructions, texture_sgpr=None, interp_sgpr=None, sampler=None, constant_descriptor=None, *,
          second_texture_offset=None, buffer_descriptors=None, integer_export=False, storage_images=None, bindings=None,
          texcoord_components=2):
    """Track descriptor provenance, interpolation and packed exports through register writes.

    The fixed contract: texture_sgpr holds the descriptor-table pointer (high word 0), with the T# at offset 0 and
    optionally a second at second_texture_offset, constant_descriptor the offset of the constant-buffer V#, interp_sgpr
    the interpolation base, and each texture is sampled once. sampler is the four words of the sampler bound to s0, or
    None for a program bound without a texture and sampler (from R0Y00/Xbox2Windows#480 by Royoo): it then must take no
    sample, declares neither, and may interpolate attr0 at the entry mask in all four components (forms/vintrp.py,
    from R0Y00/Xbox2Windows#484 by Royoo).

    bindings: a bindings.PixelBindings instead of all of those (docs/design/pixel-bindings.md): descriptor sets,
    push constants, any number of textures, samplers and constant buffers at any offset, samplers loaded from memory.

    texcoord_components: 2 or 4, the width of the TEXCOORD0 input main declares (upstream's argument, 2 by default;
    tests/mesh_textured_check.py pairs a float4 PARAM0 with it), whatever the program reads of it."""
    if texcoord_components not in (2, 4):
        raise ValueError("Expected two or four TEXCOORD components")
    if bindings is not None:
        if (texture_sgpr, interp_sgpr, sampler, constant_descriptor, second_texture_offset, buffer_descriptors,
                storage_images) != (None,) * 7 or texcoord_components != 2:
            raise ValueError("A binding description replaces the fixed-contract arguments")
        st = described_state(bindings)
        st.integer_export = integer_export
        return finish(st, instructions)
    if texture_sgpr == interp_sgpr or not 0 <= texture_sgpr <= 105 or not 0 <= interp_sgpr <= 105:
        raise ValueError("Invalid scalar inputs")
    if sampler is not None and (len(sampler) != 4 or any(not 0 <= word <= 0xffffffff for word in sampler)):
        raise ValueError("Invalid sampler descriptor words")
    scalar = {f"s{texture_sgpr}": "texture_ptr", f"s{interp_sgpr}": "interp_base"}
    vector = {"v0": "bary_i", "v1": "bary_j"}
    preamble = PREAMBLE if sampler is not None else UNSAMPLED_PREAMBLE
    lines = [preamble]
    if constant_descriptor is not None:
        if constant_descriptor < 0 or constant_descriptor % 4:
            raise ValueError("Invalid constant descriptor offset")
        # uint4, not float4: the words are raw data and must never be typed as floats (see docs/experiments.md).
        lines.insert(0, "cbuffer Constants : register(b0) { uint4 params[16]; };")
    bindings = {} if sampler is None else {0: "tex"}
    if second_texture_offset is not None:
        if sampler is None:
            raise ValueError("Second texture requires a sampler")
        if second_texture_offset < 32 or second_texture_offset % 32:
            raise ValueError("Second texture descriptor must have a distinct aligned offset")
        bindings[second_texture_offset] = "tex1"
        lines.insert(0, "Texture2D<float4> tex1 : register(t1);")
    if constant_descriptor is not None and any(
            start < constant_descriptor + 16 and constant_descriptor < start + 32 for start in bindings):
        raise ValueError("Texture and constant descriptors overlap")
    # buffer_descriptors maps the byte offset of a descriptor-table entry, as s_load_dwordx4 names it, to the index of the
    # first of four constant-buffer words that hold that buffer resource at runtime.
    vsharp_words = dict(buffer_descriptors or {})
    if vsharp_words and constant_descriptor is None:
        raise ValueError("Buffer descriptors need a constant descriptor")
    for offset, word in vsharp_words.items():
        if offset < 0 or offset % 16 or not 0 <= word <= 60:
            raise ValueError("Invalid buffer descriptor offset or constant word")
        if (any(start < offset + 16 and offset < start + 32 for start in bindings)
                or constant_descriptor < offset + 16 and offset < constant_descriptor + 16):
            raise ValueError("Buffer and texture or constant descriptors overlap")
    st = Lowering(scalar, vector, lines, bindings, () if sampler is None else tuple(sampler), constant_descriptor,
                  vsharp_words)
    st.preamble = preamble
    st.integer_export = integer_export
    st.texcoord4 = texcoord_components == 4
    # storage_images maps the byte offset of a 32-byte image T# in the descriptor table to (slot, format): the harness
    # binds that image's levels at u(8 * slot), space2 (forms/image_writes.py checks the format where it is written).
    slots = [entry[0] if isinstance(entry, tuple) and len(entry) == 2 else None for entry in (storage_images or {}).values()]
    for (offset, entry), slot in zip((storage_images or {}).items(), slots):
        if (slot not in range(4) or not isinstance(offset, int) or offset < 32 or offset % 32 or slots.count(slot) != 1
                or any(start < offset + 32 and offset < start + 32 for start in bindings)
                or any(start < offset + 32 and offset < start + 16 for start in vsharp_words)
                or constant_descriptor is not None and constant_descriptor < offset + 32 and offset < constant_descriptor + 16):
            raise ValueError("Invalid storage image offset or slot, or it overlaps another descriptor")
        st.storage_images[offset] = entry
    return finish(st, instructions, len(bindings))


def finish(st, instructions, samples=None):
    """Lower the program into st and return the HLSL. samples: the sample count the fixed contract requires (one per
    texture), or None under a binding description, which only requires the done export."""
    integer_export = st.integer_export
    # A program whose entire body is s_endpgm exports nothing and reads nothing: an empty void main, the same
    # signature as a program whose only export is exp null (forms/exp.py), without the texture sample that one has.
    empty = [line.strip() for line in instructions] == ["s_endpgm"]
    if empty:
        st.lines.append("    return;")
        st.layout, st.signature, st.exported = (), ("void", None), True
    blocks, labels = split_blocks(instructions)
    latch_of = find_loops(blocks, labels)
    for i, line in program(st, blocks, labels, latch_of):
        if st.ended:
            raise ValueError("Instruction follows program end")
        if st.exported and line != "s_endpgm" and not AFTER_EXPORT.fullmatch(line):
            raise ValueError("Unexpected instruction after color export")
        if st.exports and not line.startswith("exp "):
            raise ValueError("Only exports may follow an export that is not done")
        # CF-2c: an instruction that names a scalar register poisoned by a skipped region must overwrite it, not read it.
        poisoned = poisoned_operands(st.scalar, line)
        try:
            for guard in GUARDS:
                guard(st, i, line)
            if st.ex == "true":
                dispatch(st, i, line)
            else:
                ex, before = st.ex, dict(st.vector)
                dispatch(st, i, line)
                masked_writes(st, i, ex, before)
        except ValueError as error:
            if poisoned:
                raise ValueError(poison_message(st, poisoned)) from error
            raise
        if poisoned and set(poisoned) & set(poisoned_operands(st.scalar, line)):
            raise ValueError(poison_message(st, poisoned))
    if samples is None and not st.ended:
        raise ValueError("Missing color export")
    if not st.ended or samples is not None and st.samples != (0 if empty else samples):
        raise ValueError("Unexpected sample count or missing color export")
    place_fma_mix(st)
    if st.helpers:
        defs = [body for name, body in SALU_HELPERS.items() if name in st.helpers]
        pos = st.lines.index(st.preamble)
        st.lines[pos:pos] = defs
    if st.uses_memory:
        pos = st.lines.index(st.preamble)
        declarations = TITLE_RW_DECLARATIONS if st.writes_memory else TITLE_DECLARATIONS
        st.lines[pos:pos] = [TITLE_LOOKUP.read_text(encoding="utf-8"), declarations, MEMORY_HELPERS,
                             *st.memory_helpers.values()]
    if st.declarations:
        pos = st.lines.index(st.preamble)
        st.lines[pos:pos] = list(st.declarations.values())
    attributes = st.flat_attrs | st.interp_attrs
    mixed = st.flat_attrs & st.interp_attrs
    if attributes - {0} or st.quad_position:
        pos = st.lines.index(st.preamble)
        # SV_Position is declared so that the inputs after it sit in the registers the vertex shader gave them, and
        # TEXCOORD1 up to the last attribute read are all declared (each float4, one register) for the same reason.
        # An attribute is nointerpolation when it is read flat and linear otherwise; one read both ways is the
        # nointerpolation attrN_v (forms/vintrp.py).
        def declaration(n):
            if n in mixed:
                return f", nointerpolation float4 attr{n}_v : TEXCOORD{n}"
            return f", {'nointerpolation ' if n in st.flat_attrs else ''}float4 attr{n} : TEXCOORD{n}"
        inputs = "".join(declaration(n) for n in range(1, max(attributes | {0}) + 1))
        st.lines[pos] = st.preamble.replace("float4 main(float2 uv : TEXCOORD0)", f"float4 main(float2 uv : TEXCOORD0, float4 frag_position : SV_Position{inputs})")
    if st.flat_attrs or mixed:
        pos = st.lines.index(next(line for line in st.lines if "main(float2 uv : TEXCOORD0" in line))
        line = "// Shader model 6.1 or later: GetAttributeAtVertex.\n" + st.lines[pos]
        if 0 in st.flat_attrs:
            # Attribute 0 read flat: TEXCOORD0 is attr0 (or attr0_v), and uv, if it is read, is computed below.
            line = line.replace("main(float2 uv : TEXCOORD0", f"main(nointerpolation float4 attr0{'_v' if 0 in mixed else ''} : TEXCOORD0", 1)
        if mixed:
            line = line.replace(") : SV_Target0 {", ", float3 bary : SV_Barycentrics) : SV_Target0 {", 1)
        st.lines[pos] = line
        prologue = []
        for n in sorted(mixed):
            # P0 + I * P10 + J * P20 of the vertex values, as the console's v_interp_p1 and p2 evaluate it.
            def vertex(k):
                return f"GetAttributeAtVertex(attr{n}_v, {k})"
            local = "uv" if n == 0 else f"attr{n}"
            prologue.append(f"    precise float4 {local} = ({vertex(0)} + bary.y * ({vertex(1)} - {vertex(0)}))"
                            f" + bary.z * ({vertex(2)} - {vertex(0)});")
            st.lines[:] = [text.replace(f"GetAttributeAtVertex(attr{n}, ", f"GetAttributeAtVertex(attr{n}_v, ")
                           for text in st.lines]
        st.lines[pos + 1:pos + 1] = prologue
    if (st.attribute_input or st.texcoord4) and 0 not in st.flat_attrs:
        pos = st.lines.index(next(line for line in st.lines if "main(float2 uv : TEXCOORD0" in line))
        st.lines[pos] = st.lines[pos].replace("main(float2 uv : TEXCOORD0", "main(float4 uv : TEXCOORD0", 1)
    if st.signature:
        returns, declaration = st.signature
        pos = st.lines.index(next(line for line in st.lines if "main(" in line and "SV_Target0 {" in line))
        st.lines[pos] = st.lines[pos].replace("float4 main(", f"{returns} main(", 1).replace(") : SV_Target0 {", ") {", 1)
        if declaration:
            st.lines.insert(pos, declaration)
    if samples == 0 and st.compressed_mrt0 and not attributes and not st.quad_position:
        # The fixed contract without a sampler (lower(sampler=None)) whose compressed mrt0 export reads no input:
        # main takes no TEXCOORD0, as upstream R0Y00/Xbox2Windows#544 lowers it, so the program links with a mesh
        # or vertex stage that outputs SV_Position alone (tests/mesh_cbv_order_check.py).
        pos = st.lines.index(next(line for line in st.lines if re.search(r"main\(float[24] uv : TEXCOORD0\)", line)))
        if not any(re.search(r"\buv\b", line) for line in st.lines[pos + 1:]):
            st.lines[pos] = re.sub(r"main\(float[24] uv : TEXCOORD0\)", "main()", st.lines[pos], count=1)
    text = "\n".join([*st.lines, "}",""])
    if integer_export:
        if "return uint4(" not in text:
            raise ValueError("Integer export requires the uncompressed export form")
        text = text.replace("float4 main(", "uint4 main(", 1)
    return text
