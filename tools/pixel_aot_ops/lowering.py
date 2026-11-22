"""lower(): one pass over a gfx1013 pixel program that tracks every register symbolically and emits HLSL. The forms
in forms/ lower the instructions; this module owns the state they share, the checks around them and the final text."""
from .control_flow import find_loops, program, split_blocks
from .dispatch import dispatch
from .hlsl import MEMORY_HELPERS, PREAMBLE, SALU_HELPERS, TITLE_DECLARATIONS, TITLE_LOOKUP
from . import forms  # noqa: F401  (registers every form)


class Lowering:
    """The state of one lower() call. Forms read and write it as `st`; the control-flow walk snapshots and restores
    the per-path part (scalar, vector, pending, scc, mask, samples, sample_pending, sample_dest, exported, ended)."""

    def __init__(self, scalar, vector, lines, bindings, sampler, constant_descriptor, vsharp_words):
        self.scalar = scalar  # SGPR name (and "m0", "vcc") -> tracked value, see registers.py
        self.vector = vector  # VGPR name -> tracked value
        self.lines = lines  # the HLSL text so far; the PREAMBLE entry marks where helper definitions go
        self.bindings = bindings  # descriptor-table byte offset of a T# -> HLSL texture name
        self.sampler = sampler  # the four sampler descriptor words bound to s0
        self.constant_descriptor = constant_descriptor  # byte offset of the constant-buffer V#, or None
        self.vsharp_words = vsharp_words  # byte offset of a buffer V# -> index of its first word in params
        self.uses_memory = False  # emit the title-memory helpers
        self.pending = set()  # SGPRs an outstanding scalar load writes (cleared by lgkmcnt(0))
        self.scc = None  # SCC as an HLSL bool expression, or None when it is not tracked
        self.helpers = set()  # names of SALU_HELPERS (hlsl.py) the program uses
        self.mask = "entry"  # the execution mask: "entry" or "quad"
        self.samples = 0  # samples taken on the path so far
        self.sample_pending = False  # a sample or vector memory load is outstanding (cleared by vmcnt(0))
        self.sample_dest = set()  # VGPRs that load writes
        self.flat_attrs = set()  # attributes read without interpolation
        self.exported = False  # the color export has been emitted
        self.ended = False  # s_endpgm after the export


def lower(instructions, texture_sgpr, interp_sgpr, sampler, constant_descriptor=None, *, second_texture_offset=None,
          buffer_descriptors=None):
    """Track descriptor provenance, interpolation and packed exports through register writes."""
    if (texture_sgpr == interp_sgpr or not 0 <= texture_sgpr <= 105 or not 0 <= interp_sgpr <= 105
            or len(sampler) != 4 or any(not 0 <= word <= 0xffffffff for word in sampler)):
        raise ValueError("Invalid scalar inputs or sampler descriptor words")
    scalar = {f"s{texture_sgpr}": "texture_ptr", f"s{interp_sgpr}": "interp_base"}
    vector = {"v0": "bary_i", "v1": "bary_j"}
    lines = [PREAMBLE]
    if constant_descriptor is not None:
        if constant_descriptor < 0 or constant_descriptor % 4:
            raise ValueError("Invalid constant descriptor offset")
        # uint4, not float4: the words are raw data and must never be typed as floats (see docs/experiments.md).
        lines.insert(0, "cbuffer Constants : register(b0) { uint4 params[16]; };")
    bindings = {0: "tex"}
    if second_texture_offset is not None:
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
    st = Lowering(scalar, vector, lines, bindings, sampler, constant_descriptor, vsharp_words)
    blocks, labels = split_blocks(instructions)
    latch_of = find_loops(blocks, labels)
    for i, line in program(st, blocks, labels, latch_of):
        if st.ended:
            raise ValueError("Instruction follows program end")
        if st.exported and line != "s_endpgm":
            raise ValueError("Unexpected instruction after color export")
        dispatch(st, i, line)
    if not st.ended or st.samples != (2 if second_texture_offset is not None else 1):
        raise ValueError("Unexpected sample count or missing color export")
    if st.helpers:
        defs = [body for name, body in SALU_HELPERS.items() if name in st.helpers]
        pos = st.lines.index(PREAMBLE)
        st.lines[pos:pos] = defs
    if st.uses_memory:
        pos = st.lines.index(PREAMBLE)
        st.lines[pos:pos] = [TITLE_LOOKUP.read_text(encoding="utf-8"), TITLE_DECLARATIONS, MEMORY_HELPERS]
    if st.flat_attrs:
        pos = st.lines.index(PREAMBLE)
        # SV_Position is declared so that the inputs after it sit in the registers the vertex shader gave them.
        inputs = "".join(f", nointerpolation float4 attr{n} : TEXCOORD{n}" for n in sorted(st.flat_attrs))
        st.lines[pos] = ("// Shader model 6.1 or later: GetAttributeAtVertex.\n"
                         + PREAMBLE.replace("float4 main(float2 uv : TEXCOORD0)", f"float4 main(float2 uv : TEXCOORD0, float4 frag_position : SV_Position{inputs})"))
    return "\n".join([*st.lines, "}",""])
