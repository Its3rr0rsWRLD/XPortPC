"""lower(): one pass over a gfx1013 pixel program that tracks every register symbolically and emits HLSL. The forms
in forms/ lower the instructions; this module owns the state they share, the checks around them and the final text."""
import re

from .control_flow import find_loops, program, split_blocks, word_expr
from .dispatch import dispatch
from .hlsl import MEMORY_HELPERS, PREAMBLE, SALU_HELPERS, TITLE_DECLARATIONS, TITLE_LOOKUP, UNSAMPLED_PREAMBLE
from .registers import tracked_word
from . import forms  # noqa: F401  (registers every form)


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
        self.constant_descriptor = constant_descriptor  # byte offset of the constant-buffer V#, or None
        self.vsharp_words = vsharp_words  # byte offset of a buffer V# -> index of its first word in params
        self.uses_memory = False  # emit the title-memory helpers
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
        self.samples = 0  # samples taken on the path so far
        # VGPR -> (issue number, kind) of the outstanding sample or vector memory load that writes it. vmcnt(N) completes
        # all but the newest N of them (from R0Y00/Xbox2Windows#176 by descent81); vmcnt(0) completes all.
        self.sample_dest = {}
        self.integer_export = False  # the uncompressed export returns uint4 bit patterns (lower(integer_export=True))
        self.vm_issued = 0  # vector memory loads and samples issued on the path so far (the vmcnt issue order)
        self.flat_attrs = set()  # attributes read without interpolation
        # attr0 interpolated in all four components at the entry mask (forms/vintrp.py): TEXCOORD0 is declared float4.
        self.attribute_input = False
        self.quad_position = False  # the quad lane of this pixel is needed (quad.quad_read): declare SV_Position
        self.exports = ()  # exports before the done export on this path: (output name, width, mask, HLSL local)
        self.exported = False  # the done export has been emitted
        self.layout = None  # the outputs the done export returns, the same on every path (forms/exp.py)
        self.signature = None  # (return type, declaration) of main when it is not the preamble's float4 SV_Target0
        self.ended = False  # s_endpgm after the export

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
        old = before.get(reg)
        if old is None or value == old:
            continue
        new_word, old_word = word_expr(value), word_expr(old)
        if new_word is None or old_word is None:
            raise ValueError("Masked write of a register that does not hold a 32-bit word")
        # exw: both sides are raw words that the float readers accept (registers.RAW_WORD_PREFIXES); exv: an integer result.
        name = f"{'exw' if tracked_word(value) and tracked_word(old) else 'exv'}{i}_{reg[1:]}"
        st.lines.append(f"    uint {name} = {ex} ? {new_word} : {old_word};")
        st.vector[reg] = ("uint", name)


def lower(instructions, texture_sgpr, interp_sgpr, sampler, constant_descriptor=None, *, second_texture_offset=None,
          buffer_descriptors=None, integer_export=False):
    """Track descriptor provenance, interpolation and packed exports through register writes.

    sampler is the four words of the sampler bound to s0, or None for a program bound without a texture and sampler
    (from R0Y00/Xbox2Windows#480 by Royoo): it then must take no sample, declares neither, and may interpolate attr0
    at the entry mask in all four components (forms/vintrp.py, from R0Y00/Xbox2Windows#484 by Royoo)."""
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
        if st.ex == "true":
            dispatch(st, i, line)
        else:
            ex, before = st.ex, dict(st.vector)
            dispatch(st, i, line)
            masked_writes(st, i, ex, before)
    if not st.ended or st.samples != (0 if empty else len(bindings)):
        raise ValueError("Unexpected sample count or missing color export")
    if st.helpers:
        defs = [body for name, body in SALU_HELPERS.items() if name in st.helpers]
        pos = st.lines.index(st.preamble)
        st.lines[pos:pos] = defs
    if st.uses_memory:
        pos = st.lines.index(st.preamble)
        st.lines[pos:pos] = [TITLE_LOOKUP.read_text(encoding="utf-8"), TITLE_DECLARATIONS, MEMORY_HELPERS]
    if st.flat_attrs or st.quad_position:
        pos = st.lines.index(st.preamble)
        # SV_Position is declared so that the inputs after it sit in the registers the vertex shader gave them.
        inputs = "".join(f", nointerpolation float4 attr{n} : TEXCOORD{n}" for n in sorted(st.flat_attrs))
        note = "// Shader model 6.1 or later: GetAttributeAtVertex.\n" if st.flat_attrs else ""
        st.lines[pos] = (note
                         + st.preamble.replace("float4 main(float2 uv : TEXCOORD0)", f"float4 main(float2 uv : TEXCOORD0, float4 frag_position : SV_Position{inputs})"))
    if st.attribute_input:
        pos = st.lines.index(next(line for line in st.lines if "main(float2 uv : TEXCOORD0" in line))
        st.lines[pos] = st.lines[pos].replace("main(float2 uv : TEXCOORD0", "main(float4 uv : TEXCOORD0", 1)
    if st.signature:
        returns, declaration = st.signature
        pos = st.lines.index(next(line for line in st.lines if "main(" in line and "SV_Target0 {" in line))
        st.lines[pos] = st.lines[pos].replace("float4 main(", f"{returns} main(", 1).replace(") : SV_Target0 {", ") {", 1)
        if declaration:
            st.lines.insert(pos, declaration)
    text = "\n".join([*st.lines, "}",""])
    if integer_export:
        if "return uint4(" not in text:
            raise ValueError("Integer export requires the uncompressed export form")
        text = text.replace("float4 main(", "uint4 main(", 1)
    return text
