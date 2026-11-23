"""Offline lowering of gfx1013 tessellation programs to D3D12 hull and domain shaders (cards T-1 and T-2,
docs/design/stages.md).

On gfx10, RADV runs the API vertex shader and the tessellation control shader as one merged LS+HS wave (or the HS half
alone when the pipeline has no vertex shader of its own), and the tessellation evaluation shader as the ES half of an
NGG wave, inside the same passthrough frame as an NGG vertex shader (card V-2). The halves talk through memory:
- LS to HS: the LS half's VGPRs stay live into the HS half when RADV passes the inputs in registers
  (ac_nir_lower_tess_io_to_mem.c, tcs_inputs_via_temp), or the HS half reads them from LDS at
  rel_patch_id * input_patch_stride + vertex * vertex_stride + 16 + slot * 16 (hs_per_vertex_input_lds_offset, the 16
  bytes are the tess-level group vote, AC_TESS_LEVEL_VOTE_LDS_BYTES), the vertex stride coming from the
  tcs_offchip_layout user SGPR (radv_shader.h TCS_OFFCHIP_LAYOUT_NUM_LS_OUTPUTS, bits 17..22, times 16 plus 4);
- HS to tessellator: invocation 0 of each patch stores the tessellation factors through the TF ring descriptor
  (ring table + 0x50) at rel_patch_id * 4 * factors, in D3D11 order (hs_store_tess_factors_for_tessellator: the three
  or four outer factors, then the inner ones);
- HS to TES: each control point's outputs go to the off-chip ring (ring table + 0x60) attribute-major, at
  slot * attr_stride + (rel_patch_id * N + vertex) * 16 + component * 4, attr_stride = align(patch count * N * 16,
  256) (hs_per_vertex_output_vmem_offset, radv_nir_lower_abi.c load_tcs_mem_attrib_stride); the TES reads them at
  the same offsets with rel_patch_id from v7 (radv_shader_args.c declare_tes_input_vgprs: v5, v6 the tessellation
  coordinates, v7 the relative patch id, v8 the patch id).

The translation splits those back into D3D12 stages:
- the LS half becomes a vertex shader whose LsOutput holds the VGPRs the HS half reads (uint4 lN : TEXCOORDN);
- the HS half becomes a hull shader whose control-point function runs the HS body with SV_OutputControlPointID for
  the invocation id and writes HsControlPoint (uint4 aK : TEXCOORDK, one per ring slot), and whose patch-constant
  function runs the same body as invocation 0 together with the invocation-0 region and returns the factors the TF
  ring store writes as SV_TessFactor and SV_InsideTessFactor;
- the TES body becomes a domain shader that reads OutputPatch<HsControlPoint, N> where it reads the ring, and
  SV_DomainLocation.xy where it reads v5 and v6 (it computes w itself); its exports are tools/vertex_aot.py's outputs.
The frame (exec masks, barriers, the ring-address and lane-index idioms, the NGG allocation, and RADV's tess-level
group vote, whose only effect is to skip the output stores of a workgroup whose patches are all discarded) is
dropped. The vote is replaced by its "not all discarded" value: a discarded patch runs no domain shader on either
side, so the outputs it would skip are never read.

State (pipeline state the title gives, as VGT_TF_PARAM and RADV's tcs_offchip_layout do), a dict:
    {"domain": "tri" | "quad", "partitioning": "integer" | "pow2" | "fractional_odd" | "fractional_even",
     "topology": "triangle_cw" | "triangle_ccw", "input_control_points": M, "output_control_points": N,
     "attr_stride": bytes (a multiple of 256, at least N * 16), "vertex_slots": ring slots per control point,
     "ls_slots": LDS input slots per vertex (an HS that reads its inputs from LDS)}
The partitionings the desktop tessellator does not reproduce bit for bit are refused (REFUSED_PARTITIONINGS, from the
measurement in tests/tess_tessellator.py; docs/design/stages.md records it).

Only what is proved is accepted. Refused, each with its own reason: control flow other than the frame's exec regions,
per-patch outputs and inputs, isolines and point mode, the primitive id, LDS inputs in a merged LS+HS wave, a TCS that
reads its own outputs or another invocation's (LDS output traffic), the factors computed outside invocation 0's region
or from values only some invocations hold, a vote whose bits feed anything else, and any ring or LDS access that is
not one of the patterns above.

Usage:
    python tools/tess_aot.py tes PROGRAM.s --user-sgprs MAP.json --state STATE.json --output DS.hlsl
    python tools/tess_aot.py hs PROGRAM.s --user-sgprs MAP.json --state STATE.json --hs-output HS.hlsl
                             [--vs-output VS.hlsl]
MAP.json is tools/vertex_aot.py's role map, plus {"role": "tcs_offchip_layout"} for that RADV user SGPR.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixel_aot_ops.dispatch import dispatch  # noqa: E402,F401  (registers the forms)
from pixel_aot_ops.hlsl import HELPERS, PREAMBLE  # noqa: E402
from pixel_aot_ops.forms import exec_mask  # noqa: E402
from pixel_aot_ops.forms.vop3p import place_fma_mix  # noqa: E402
from pixel_aot_ops.registers import vector_u32  # noqa: E402
import geometry_aot  # noqa: E402
import vertex_aot  # noqa: E402

M32 = 0xffffffff
DOMAINS = {"tri": (3, 1), "quad": (4, 2)}  # outer, inner factor counts
PARTITIONINGS = ("integer", "pow2", "fractional_odd", "fractional_even")
TOPOLOGIES = ("triangle_cw", "triangle_ccw")
# Partitionings whose domain points or triangles the desktop tessellator does not reproduce bit for bit
# (tests/tess_tessellator.py; docs/design/stages.md, "The tessellator"). Each is refused with its measured reason.
REFUSED_PARTITIONINGS = {
    "fractional_odd": "the desktop tessellator does not reproduce it bit for bit: on the NVIDIA hardware adapter 2 of 84 "
                      "triangle patches and 1 of 87 quad patches have the same domain points but different degenerate "
                      "(zero-area) triangles than the D3D11 reference (WARP matches it exactly); docs/design/stages.md, "
                      "\"The tessellator\"",
}
VOTE_BYTES = 16  # AC_TESS_LEVEL_VOTE_LDS_BYTES: the LDS bytes before the first HS input vertex
TF_RING, OFFCHIP_RING = 0x50, 0x60  # ring-table offsets of the TF ring and the off-chip ring descriptors
MAX_SLOTS = 32  # a D3D12 control point holds at most 32 four-component registers


def check_state(state):
    s = dict(state)
    for key in ("domain", "partitioning", "topology", "output_control_points", "attr_stride", "vertex_slots"):
        if key not in s:
            raise ValueError(f"Tessellation state lacks {key!r}")
    if s["domain"] not in DOMAINS:
        raise ValueError(f"Tessellation domain {s['domain']!r}: only tri and quad are lowered (isolines are not "
                         "measured)")
    if s["partitioning"] not in PARTITIONINGS:
        raise ValueError(f"Unknown partitioning {s['partitioning']!r}")
    if s["partitioning"] in REFUSED_PARTITIONINGS:
        raise ValueError(f"Refused partitioning {s['partitioning']}: {REFUSED_PARTITIONINGS[s['partitioning']]}")
    if s["topology"] not in TOPOLOGIES:
        raise ValueError(f"Output topology {s['topology']!r}: only triangle_cw and triangle_ccw are lowered (point "
                         "mode is not)")
    n = s["output_control_points"]
    if not isinstance(n, int) or not 1 <= n <= 32:
        raise ValueError("output_control_points must be 1..32")
    m = s.setdefault("input_control_points", n)
    if not isinstance(m, int) or not 1 <= m <= 32:
        raise ValueError("input_control_points must be 1..32")
    stride = s["attr_stride"]
    if not isinstance(stride, int) or stride % 256 or stride < 16 * n:
        raise ValueError(f"attr_stride {stride!r} is not a multiple of 256 of at least 16 * output_control_points "
                         "(RADV aligns patch count * N * 16 to 256)")
    if not isinstance(s["vertex_slots"], int) or not 1 <= s["vertex_slots"] <= MAX_SLOTS:
        raise ValueError(f"vertex_slots must be 1..{MAX_SLOTS}")
    ls = s.setdefault("ls_slots", None)
    if ls is not None and (not isinstance(ls, int) or not 1 <= ls <= MAX_SLOTS):
        raise ValueError(f"ls_slots must be 1..{MAX_SLOTS}")
    return s


# --- shared declarations ------------------------------------------------------------------------------------------------

def control_point_struct(state):
    """The ring slots of one output control point, as both the hull and the domain shader declare them."""
    return ["struct HsControlPoint {",
            *(f"    uint4 a{k} : TEXCOORD{k};" for k in range(state["vertex_slots"])), "};"]


def patch_struct(state):
    outer, inner = DOMAINS[state["domain"]]
    inside = "float inside : SV_InsideTessFactor;" if inner == 1 else "float inside[2] : SV_InsideTessFactor;"
    return ["struct HsPatch {", f"    float edges[{outer}] : SV_TessFactor;", f"    {inside}", "};"]


def ls_slot_struct(state):
    """The LDS input slots of one input vertex (an HS without its LS half): what the vertex shader that feeds it
    writes, slot k as TEXCOORDk."""
    return ["struct LsOutput {", *(f"    uint4 s{k} : TEXCOORD{k};" for k in range(state["ls_slots"])), "};"]


def _mubuf(line):
    """(op, data registers, address VGPR, descriptor, soffset, immediate offset) of an offen MUBUF line, or None."""
    m = re.fullmatch(r"buffer_(load|store)_dword(?:x([234]))? (v\d+|v\[\d+:\d+\]), (v\d+), (s\[\d+:\d+\]), (s\d+) "
                     r"offen(?: offset:(\d+))?((?: glc| dlc| slc)*)", line)
    if not m:
        return None
    regs = geometry_aot._registers(m[3])
    if len(regs) != int(m[2] or 1):
        raise ValueError(f"Refused {line!r}: operand width")
    return m[1], regs, m[4], m[5], m[6], int(m[7] or 0)


def _ring_desc(line):
    m = re.fullmatch(r"s_load_dwordx4 (s\[\d+:\d+\]), s\[0:1\], (0x[0-9a-f]+)", line)
    return (m[1], int(m[2], 16)) if m else None


def _decompose(byte, state, line):
    """(slot, vertex part, component) of an off-chip ring byte offset beyond rel_patch_id * N * 16."""
    stride, n = state["attr_stride"], state["output_control_points"]
    slot, rest = divmod(byte, stride)
    if rest >= 16 * n:
        raise ValueError(f"Refused {line!r}: ring byte {byte} is past the {n} control points of a patch (per-patch "
                         "data is not lowered)")
    if slot >= state["vertex_slots"]:
        raise ValueError(f"Refused {line!r}: ring slot {slot} is not below the state's vertex_slots "
                         f"{state['vertex_slots']}")
    vertex, rest = divmod(rest, 16)
    if rest % 4:
        raise ValueError(f"Refused {line!r}: ring byte {byte} is not word aligned")
    return slot, vertex, rest // 4


HARDWARE_SGPRS = {f"s{n}" for n in range(8)}


# --- T-2: the evaluation shader -----------------------------------------------------------------------------------------

TES_REASONS = {
    **{f"v{n}": f"entry VGPR v{n} of an NGG evaluation shader is a GS input of the frame; the TES body may not read it"
       for n in range(5)},
    "v7": "the relative patch id (v7) is read only by the ring address idiom (v_mul_u32_u24 v, N * 16, v7)",
    "v8": "the patch id (v8) is not lowered yet (SV_PrimitiveID needs its own draw check)",
}


def _tes_scan(body, state):
    """Replace the ring idioms of a TES body by pseudo-lines the lowering handles: x2w_ring_load REGS, BYTE (the
    words at that ring byte offset of this patch). Returns the lines."""
    n = state["output_control_points"]
    tags = {}
    out = []
    body_written = set()
    for line in body:
        head, _, rest = line.partition(" ")
        ops = [t.strip() for t in rest.split(",")] if rest else []
        written, read = geometry_aot.operands(line)
        new = None
        if desc := _ring_desc(line):
            regs, offset = desc
            if offset != OFFCHIP_RING:
                raise ValueError(f"Refused {line!r}: the evaluation shader reads only the off-chip ring")
            new = ("ring", regs)
        elif re.fullmatch(r"v_mul_u32_u24(?:_e32)?", head) and len(ops) == 3 and ops[2] == "v7" \
                and geometry_aot._immediate(ops[1]) == 16 * n:
            new = ("addr", 0)
        elif re.fullmatch(r"v_lshlrev_b32(?:_e32)?", head) and len(ops) == 3 and ops[2] == "v7" \
                and geometry_aot._immediate(ops[1]) is not None and 1 << geometry_aot._immediate(ops[1]) == 16 * n:
            new = ("addr", 0)
        elif re.fullmatch(r"v_add_nc_u32(?:_e32)?", head) and len(ops) == 3 and tags.get(ops[2], ("",))[0] == "addr" \
                and geometry_aot._immediate(ops[1]) is not None:
            new = ("addr", tags[ops[2]][1] + geometry_aot._immediate(ops[1]))
        elif (mb := _mubuf(line)) and mb[0] == "load":
            _, regs, address, rsrc, soffset, imm = mb
            if tags.get(address, ("",))[0] != "addr" or tags.get(rsrc, ("",))[0] != "ring" or soffset != "s4":
                raise ValueError(f"Refused {line!r}: an offen buffer load that is not an off-chip ring read "
                                 "(rel_patch_id * N * 16 + offset, the ring descriptor, s4)")
            base = tags[address][1] + imm
            for r in regs:
                tags.pop(r, None)
                body_written.add(r)
            out.append(f"x2w_ring_load {':'.join(regs)}, {base}")
            continue
        if new:
            for r in written:
                tags.pop(r, None)
                body_written.add(r)
            if new[0] == "ring":
                for r in geometry_aot._registers(new[1]):
                    tags[r] = ("ring",)
                tags[new[1]] = ("ring",)
            else:
                tags[written[0]] = new
            continue
        for r in read:
            if r in tags:
                raise ValueError(f"Refused {line!r}: reads {r}, which holds a ring descriptor or ring address")
            if r in HARDWARE_SGPRS and r not in body_written:
                raise ValueError(f"Refused {line!r}: reads the hardware SGPR {r} (s0:1 the ring table, s2 gs_tg_info, "
                                 "s3 merged_wave_info, s4 the off-chip offset) outside the ring idioms")
        for r in written:
            tags.pop(r, None)
            body_written.add(r)
        out.append(line)
    return out


def lower_tes(instructions, user_sgprs, state):
    """Returns (domain shader HLSL, layout): layout as tools/vertex_aot.py's, plus "reads": {(slot, vertex):
    components read}."""
    state = check_state(state)
    program = vertex_aot._clean(instructions)
    if not vertex_aot.is_ngg(program):
        raise ValueError("An evaluation shader outside the NGG passthrough frame (legacy TES as VS) is not lowered")
    program, _ = vertex_aot.match_ngg_frame(program)
    program = [line for line in program if not vertex_aot._is_label(line)]
    lines = _tes_scan(program, state)
    for line in lines:
        if line.startswith("x2w_"):
            continue
        for pattern, reason in vertex_aot.REFUSALS:
            if re.fullmatch(pattern, line):
                raise ValueError(f"Refused {line!r}: {reason}")
    entry_scalar, tables, root, has_constants = vertex_aot._role_map(user_sgprs, "ngg")
    st = geometry_aot._state(entry_scalar, {"v5": ("uint", "tess_u"), "v6": ("uint", "tess_v")}, has_constants)
    exports = {}
    reads = {}
    ended = False

    def special(i, line):
        nonlocal ended
        if line.startswith("x2w_ring_load "):
            regs, base = line[len("x2w_ring_load "):].split(", ")
            for j, register in enumerate(regs.split(":")):
                slot, vertex, comp = _decompose(int(base) + 4 * j, state, line)
                name = f"mem_ring{i}_{j}"
                st.lines.append(f"    uint {name} = cp[{vertex}].a{slot}.{'xyzw'[comp]};")
                st.vector[register] = ("uint", name)
                reads.setdefault((slot, vertex), set()).add(comp)
            st.vm_issue(regs.split(":"), "mubuf")
            return True
        if line.startswith("exp "):
            vertex_aot._export(i, line, st, exports, {})
            return True
        if line == "s_endpgm":
            vertex_aot._check_positions(exports, {})
            ended = True
            return True
        if ended:
            raise ValueError(f"Instruction follows program end: {line}")
        return False

    vertex_aot.run_body(st, lines, tables, "ngg", special, entry_vgprs={}, reasons=TES_REASONS)
    if not ended:
        raise ValueError("Missing s_endpgm")
    geometry_aot._check_state(st)
    layout = vertex_aot._layout(exports, {}, "ngg", False)
    layout["reads"] = {key: sorted(v) for key, v in sorted(reads.items())}
    place_fma_mix(st)
    params = layout["params"]
    members = (["    float4 param0 : TEXCOORD0;"] if 0 in params else []) + ["    float4 pos0 : SV_Position;"] + \
        [f"    float4 param{n} : TEXCOORD{n};" for n in params if n]
    location = "float3" if state["domain"] == "tri" else "float2"
    n = state["output_control_points"]
    entry = "\n".join([HELPERS, *control_point_struct(state), *patch_struct(state), "struct VertexOutput {", *members,
                       "};", f"[domain(\"{state['domain']}\")]",
                       f"VertexOutput main(HsPatch patch, {location} loc : SV_DomainLocation, "
                       f"const OutputPatch<HsControlPoint, {n}> cp) {{",
                       "    uint tess_u = asuint(loc.x);", "    uint tess_v = asuint(loc.y);"])
    st.lines[st.lines.index(PREAMBLE)] = entry
    uses_vsharps = any(len(e) == 2 for _, entries in tables.values() for e in entries.values())
    head = vertex_aot.declarations(st, root, has_constants, uses_vsharps)
    stores = ["    VertexOutput vertex_out;"]
    stores += [f"    vertex_out.{name} = asfloat({variable});" for name, (variable, _, _) in sorted(exports.items())]
    return "\n".join([*head, *st.lines, *stores, "    return vertex_out;", "}", ""]), layout


# --- T-1: the merged LS+HS wave -------------------------------------------------------------------------------------

LS_REASONS = {
    "v0": "the patch id (v0) belongs to the HS half",
    "v1": "the relative ids (v1) belong to the HS half's frame idioms",
    "v3": "the LS vertex's LDS index (v3, vs_rel_patch_id) is read only by an LDS output address, which is not lowered "
          "in a merged wave",
    "v4": "entry VGPR v4 of an LS+HS wave is unused",
}
HS_REASONS = {
    "v0": "the patch id (v0) is not lowered yet (SV_PrimitiveID needs its own draw check)",
    "v1": "v1 (relative patch id and invocation id) is read only by the frame idioms (v_bfe_u32 v, v1, 8, 5 for the "
          "invocation id, the TF and LDS address idioms, v_readfirstlane_b32 of the lane index)",
    "v2": "the HS half may not read the LS vertex id (v2)",
    "v3": "the HS half may not read v3 (vs_rel_patch_id)",
    "v4": "entry VGPR v4 of an LS+HS wave is unused",
    "v5": "the HS half may not read the LS instance id (v5)",
}

# The tess-level group vote (ac_nir_lower_tess_io_to_mem.c hs_tess_level_group_vote): thread 0 of the workgroup
# initializes LDS word 0 to 3, the first active invocation-0 lane of each wave ANDs its patches' "all factors 0" and
# "all factors 1" bits into it, and after a barrier every lane reads it back.
VOTE_INIT = [
    "v_readfirstlane_b32 %a, v1", "s_bfe_u32 %b, %a, 0x50008", "s_bfe_u32 %a, %a, 0x80000", "s_mul_i32 %a, %a, $N",
    "s_add_u32 %a, %a, %b", "s_mov_b64 %one, 1", "s_cmp_lt_u32 %a, 64", "s_cselect_b64 %m, -1, 0",
    "s_and_b64 %m, %m, %one", "s_and_saveexec_b64 %m, %m", "s_cbranch_execz @i", "v_mov_b32_e32 %z, 0",
    "v_mov_b32_e32 %w, 3", "ds_write_b32 %z, %w", "@i:", "s_waitcnt_depctr 0xffe3", "s_mov_b64 exec, %m",
]
VOTE = [
    "s_mov_b64 %k, 7", "s_and_saveexec_b64 %k, %k", "s_ff1_i32_b64 %a, exec", "s_lshl_b64 %b, 1, %a",
    "s_and_saveexec_b64 %b, %b", "s_cbranch_execz @x", "v_mov_b32_e32 %v, %bits", "v_mov_b32_e32 %z, 0",
    "ds_and_b32 %z, %v",
]
VOTE_READ = [
    "@x:", "s_waitcnt_depctr 0xffe3", "s_mov_b64 exec, %m", "s_waitcnt lgkmcnt(0)", "s_barrier",
    "s_and_b64 exec, %one, exec", "v_mov_b32_e32 %r, 0", "ds_read_b32 %r, %r", "s_waitcnt lgkmcnt(0)",
    "v_readfirstlane_b32 %vote, %r",
]
# The output-store lanes: the lane's output vertex in the wave (rel_patch_id * N + invocation id of the first lane,
# rounded down to the wave, plus the lane) and the lanes below the HS lane count rounded up to 8.
TAIL = [
    "v_readfirstlane_b32 %a, v1", "s_bfe_u32 %b, %a, 0x50008", "s_bfe_u32 %a, %a, 0x80000", "s_mul_i32 %a, %a, $N",
    "s_add_u32 %a, %a, %b", "s_and_b32 %a, %a, 0xffffffc0", "s_bfe_u32 s3, s3, 0x80008",
    "v_mbcnt_lo_u32_b32 %o, -1, %a", "s_add_u32 s3, s3, 7", "s_and_b32 s3, s3, -8", "v_mbcnt_hi_u32_b32 %o, -1, %o",
    "s_pack_ll_b32_b16 s3, 0, s3", "s_bfe_u64 %t, -1, s3",
]
TAIL_VOTE = ["s_cmp_lg_i32 %vote, 1", "s_cselect_b64 %q, -1, 0", "s_and_b64 %t, %t, %q"]
TAIL_END = ["s_and_b64 exec, %t, exec", "s_cbranch_execz @end", "v_lshlrev_b32_e32 %o, 4, %o"]

SCC_WRITERS = re.compile(r"s_(?:and|or|xor|andn2|orn2|nand|nor|xnor|not|cmp|cmpk|add|addc|sub|subb|lshl|lshr|ashr|"
                         r"bfe|bitcmp|abs|absdiff|min|max|lshl\d_add|ff1|bcnt|cselect_never)\w*$")


def _scc(line):
    """(writes SCC, reads SCC) of a line."""
    head = line.split()[0]
    reads = head.startswith(("s_cselect", "s_addc", "s_subb", "s_cbranch_scc")) or "src_scc" in line
    writes = bool(SCC_WRITERS.match(head)) and not head.startswith("s_cselect") and head not in (
        "s_and_saveexec_b64x",)
    return writes, reads


def _operands(line):
    """geometry_aot.operands with the destination of a VOPC compare: its SGPR pair or VCC (written), EXEC for v_cmpx."""
    written, read = geometry_aot.operands(line)
    head, _, rest = line.partition(" ")
    if head.startswith("v_cmp_"):
        ops = [t.strip() for t in rest.split(",")]
        written = geometry_aot._registers(ops[0]) if head.endswith("_e64") else ["vcc"]
    elif head.startswith("v_cmpx_"):
        written = ["exec"]
    elif head.startswith("v_cndmask"):
        ops = [t.strip() for t in rest.split(",")]
        read = [r for token in ops[1:] for r in geometry_aot._registers(token)]
    return written, read


def _match(templates, lines, at, seed=None):
    """Match templates at lines[at:] with a fresh binder seeded with {"%name": value}; (position after, binder) or
    (None, None). Registers bind consistently within one template block (RADV reuses them across blocks)."""
    b = geometry_aot.Binder()
    for key, value in (seed or {}).items():
        b.bind(key[0], key[1:], str(value))
    pos = at
    for template in templates:
        if pos >= len(lines) or not b.match(template, lines[pos]):
            return None, None
        pos += 1
    return pos, b


class HsFrame:
    """The merged wave split into regions. entries: (line, region) with region "ls", "hs" or "inv0" (invocation 0 of
    each patch), pseudo-lines for the frame's I/O: x2w_inv V (the invocation id), x2w_ls_in REGS, VERTEX, BYTE (an LDS
    input read), x2w_tf REGS, WORD (the TF ring store), x2w_out REGS, BYTE (an output store)."""

    def __init__(self, program, state, roles):
        self.state = state
        self.layout_sgpr = next((f"s{n}" for n, role in roles.items() if role == ("tcs_offchip_layout",)), None)
        self.entries = []
        self.merged = False
        self.vote = None
        self.vote_register = None
        self.ls_inputs = "temp"
        self._split(program)

    def _split(self, program):
        state, n = self.state, self.state["output_control_points"]
        lines = [line for line in program if line != "s_waitcnt_vscnt null, 0x0" and not line.startswith("s_setprio")]
        if lines and lines[-1] == "s_endpgm":
            lines = lines[:-1]
        else:
            raise ValueError("An LS+HS program ends with s_endpgm")
        tags = {}  # register -> tag
        region = {"all"}
        scc_tag = None
        barrier_at = None  # index into entries after the last s_barrier of the HS half
        written_in = {}  # register -> region name of its last write
        pos = 0
        saw_hs = False
        tail = False

        def name_of(r):
            if "inv0" in r:
                return "inv0"
            if r & {"hs", "tail"}:
                return "hs"
            if "ls" in r:
                return "ls"
            return "all"

        def add(line, where=None):
            self.entries.append((line, where or name_of(region)))

        while pos < len(lines):
            line = lines[pos]
            head, _, rest = line.partition(" ")
            ops = [t.strip() for t in rest.split(",")] if rest else []
            if vertex_aot._is_label(line):
                pos += 1
                continue
            # Templates first.
            if head == "v_readfirstlane_b32" and ops[1:] == ["v1"]:
                end, b = _match(VOTE_INIT, lines, pos)
                if end is not None:
                    if b.get("$", "N") != n or self.vote is not None:
                        raise ValueError("The tess-level vote's lane index does not use the output patch size")
                    if b.get("@", "i") + ":" != lines[end - 3]:
                        raise ValueError("The vote initialization's branch does not land on its label")
                    tags[b.get("%", "m")] = ("saved", frozenset(region))
                    tags[b.get("%", "one")] = ("vote_lane",)
                    self.vote_masks = {"%m": b.get("%", "m"), "%one": b.get("%", "one")}
                    self.vote = "init"
                    pos = end
                    continue
                end, b = _match(TAIL, lines, pos)
                if end is None:
                    raise ValueError(f"Refused {line!r}: v_readfirstlane_b32 of v1 outside the vote and output-store "
                                     "idioms")
                if b.get("$", "N") != n:
                    raise ValueError("The output-store lane index does not use the output patch size")
                seed = {"%t": b.get("%", "t"), "%o": b.get("%", "o")}
                if self.vote == "read":
                    after, _ = _match(TAIL_VOTE, lines, end, {**seed, "%vote": self.vote_register})
                    if after is None:
                        raise ValueError("The output-store mask does not test the tess-level vote")
                    end = after
                elif end < len(lines) and lines[end] == f"s_and_b64 {seed['%t']}, {seed['%t']}, -1":
                    end += 1
                stop, b = _match(TAIL_END, lines, end, seed)
                if stop is None:
                    raise ValueError(f"Output-store frame: expected {TAIL_END!r} at {lines[end:end + 3]!r}")
                if lines[stop:] and b.get("@", "end") + ":" not in lines[stop:]:
                    raise ValueError("The output-store branch names no later label")
                end_label = b.get("@", "end") + ":"
                if end_label in lines[stop:] and lines.index(end_label, stop) != len(lines) - 1:
                    raise ValueError("The output-store branch does not land on the end of the program")
                region = set(region) | {"tail"}
                tags[b.get("%", "o")] = ("out_addr", 0)
                tail = True
                pos = stop
                continue
            if head == "s_mov_b64" and len(ops) == 2 and ops[1] == "7" and self.vote == "init":
                end, b = _match(VOTE, lines, pos)
                if end is None:
                    raise ValueError(f"Tess-level vote: the block at {line!r} is not RADV's vote")
                bits = b.get("%", "bits")
                end, b2 = _match(VOTE_READ, lines, end, {**self.vote_masks, "@x": b.get("@", "x")})
                if end is None:
                    raise ValueError("Tess-level vote: the read-back is not RADV's (or uses other masks than the "
                                     "initialization's)")
                self._drop_vote_bits(bits, barrier_at, lines[end:])
                self.vote = "read"
                self.vote_register = b2.get("%", "vote")
                add(f"s_mov_b32 {self.vote_register}, 0", "hs")
                pos = end
                continue
            written, read = _operands(line)
            writes_scc, reads_scc = _scc(line)
            pos += 1
            # Exec, branches and barriers.
            if head == "s_cbranch_execz":
                if f"{ops[0]}:" not in lines[pos:]:
                    raise ValueError(f"Refused {line!r}: the branch names no later label")
                continue
            if head.startswith(("s_branch", "s_cbranch", "s_setpc", "s_swappc", "s_call")):
                raise ValueError(f"Refused {line!r}: control flow in the tessellation stages other than the frame's "
                                 "exec regions is lowered with the control-flow cards")
            if head == "s_barrier":
                if "hs" not in region:
                    raise ValueError("Refused s_barrier outside the HS half")
                barrier_at = len(self.entries)
                continue
            if head == "s_pack_ll_b32_b16" and ops[1:] == ["0", "s3"]:
                tags[ops[0]] = ("ls_count",)
                continue
            if head == "s_bfe_u64" and ops[0] == "exec" and ops[1] == "-1" and tags.get(ops[2]) == ("ls_count",):
                if self.entries or region != {"all"}:
                    raise ValueError("The LS region does not start the program")
                region = {"ls"}
                self.merged = True
                continue
            if head == "s_lshl_b32" and ops[1:] == ["s3", "8"]:
                tags[ops[0]] = ("hs_count",)
                continue
            if head == "s_bfe_u64" and ops[1] == "-1" and tags.get(ops[2]) == ("hs_count",):
                tags[ops[0]] = ("mask", "hs")
                continue
            if head == "s_and_saveexec_b64":
                tag = tags.get(ops[1])
                if not tag or tag[0] not in ("mask", "saved"):
                    raise ValueError(f"Refused {line!r}: an exec mask that is not one of the frame's")
                tags[ops[0]] = ("saved", frozenset(region))
                region = set(region) | ({tag[1]} if tag[0] == "mask" else set(tag[1]))
                if tag[0] == "mask" and tag[1] == "hs":
                    saw_hs = True
                continue
            if head == "s_mov_b64" and ops[0] == "exec":
                tag = tags.get(ops[1])
                if not tag or tag[0] != "saved":
                    raise ValueError(f"Refused {line!r}: exec restored from a register that holds no saved mask")
                region = set(tag[1])
                continue
            if head == "s_and_b64" and ops[0] == "exec" and "exec" in ops[1:]:
                other = ops[1] if ops[2] == "exec" else ops[2]
                tag = tags.get(other)
                if not tag or tag[0] != "mask":
                    raise ValueError(f"Refused {line!r}: exec narrowed by a mask that is not the frame's")
                region = set(region) | {tag[1]}
                continue
            if head in ("v_cmpx_eq_i32_e32", "v_cmpx_eq_u32_e32") and ops[0] == "0" and tags.get(ops[1]) == ("inv",):
                region = set(region) | {"inv0"}
                tags["exec"] = ("mask", "inv0")
                continue
            if head == "s_mov_b64" and ops == ["vcc", "exec"] and tags.get("exec") == ("mask", "inv0"):
                tags["vcc"] = ("mask", "inv0")
                continue
            if head == "s_waitcnt_depctr":
                continue
            if head == "s_and_b64" and len(ops) == 3 and ops[0] != "exec" and "exec" in ops[1:] \
                    and (ops[1] if ops[2] == "exec" else ops[2]) == ops[0] and tags.get(ops[0]) == ("uniform_cmp",):
                # SCC = (a compare of wave-uniform operands & EXEC) != 0: this invocation's compare, as it is active.
                add(f"x2w_scc_lane {ops[0]}")
                tags.pop(ops[0], None)
                scc_tag = None
                continue
            if "exec" in line.split(None, 1)[-1].replace(",", " ").split():
                if not (self.vote == "init" and barrier_at is not None and head.startswith("s_")
                        and "exec" not in geometry_aot.operands(line)[0]):
                    raise ValueError(f"Refused {line!r}: an exec use that is not one of the frame's")
                deferred = True
            else:
                deferred = False
            if head == "s_setprio":
                continue
            # Idioms that define frame values.
            if desc := _ring_desc(line):
                regs, offset = desc
                if offset not in (TF_RING, OFFCHIP_RING):
                    raise ValueError(f"Refused {line!r}: ring descriptor {offset:#x} is not the TF or off-chip ring")
                for r in geometry_aot._registers(regs):
                    tags.pop(r, None)
                tags[regs] = ("tf_ring",) if offset == TF_RING else ("offchip",)
                continue
            if head == "v_bfe_u32" and ops[1:] == ["v1", "8", "5"]:
                if "hs" not in region:
                    raise ValueError(f"Refused {line!r}: the invocation id read outside the HS half")
                tags[ops[0]] = ("inv",)
                add(f"x2w_inv {ops[0]}")
                written_in[ops[0]] = name_of(region)
                continue
            m = re.fullmatch(r"v_(lshlrev_b32|mul_u32_u24)_sdwa (v\d+), (\S+), v1 dst_sel:DWORD dst_unused:UNUSED_PAD "
                             r"src0_sel:DWORD src1_sel:BYTE_0", line)
            if m:
                factor = (1 << int(m[3])) if m[1] == "lshlrev_b32" and re.fullmatch(r"\d+", m[3]) else \
                    geometry_aot._immediate(m[3])
                outer, inner = DOMAINS[state["domain"]]
                if factor == 4 * (outer + inner):
                    tags[m[2]] = ("tf_addr",)
                elif m[1] == "mul_u32_u24" and tags.get(m[3]) == ("pstride",):
                    tags[m[2]] = ("lds_addr", 0, 0)
                else:
                    raise ValueError(f"Refused {line!r}: a relative-patch-id product that is not the TF address "
                                     f"(rel_patch_id * {4 * (outer + inner)}) or the LDS input patch offset")
                continue
            if self.layout_sgpr and head == "s_bfe_u32" and ops == [ops[0], self.layout_sgpr, "0x60011"]:
                tags.pop(ops[0], None)
                tags[ops[0]] = ("ls_outputs",)
                scc_tag = "ls_outputs"
                continue
            if head == "s_cselect_b32" and ops[1:] == ["4", "0"] and scc_tag == "ls_outputs":
                tags[ops[0]] = ("pad",)
                continue
            if head == "s_lshl4_add_u32" and len(ops) == 3 and tags.get(ops[1]) == ("ls_outputs",) \
                    and tags.get(ops[2]) == ("pad",):
                tags[ops[0]] = ("vstride",)
                scc_tag = None
                continue
            if head == "s_mul_i32" and len(ops) == 3 and {tags.get(ops[1]), tags.get(ops[2])} >= {("vstride",)}:
                k = geometry_aot._immediate(ops[1] if tags.get(ops[2]) == ("vstride",) else ops[2])
                if k != state["input_control_points"]:
                    raise ValueError(f"Refused {line!r}: the LDS input patch stride is not input_control_points "
                                     "vertex strides")
                tags[ops[0]] = ("pstride",)
                continue
            if head == "v_mad_u32_u24" and len(ops) == 4 and tags.get(ops[1]) == ("vstride",) \
                    and tags.get(ops[2]) == ("inv",) and tags.get(ops[3], ("",))[0] == "lds_addr":
                _, vertex, inv = tags[ops[3]]
                tags[ops[0]] = ("lds_addr", vertex, inv + 1)
                continue
            if re.fullmatch(r"v_add_nc_u32(?:_e32)?", head) and len(ops) == 3 and tags.get(ops[1]) == ("vstride",) \
                    and tags.get(ops[2], ("",))[0] == "lds_addr":
                _, vertex, inv = tags[ops[2]]
                tags[ops[0]] = ("lds_addr", vertex + 1, inv)
                continue
            if head == "v_lshl_add_u32" and len(ops) == 4 and tags.get(ops[1]) == ("vstride",) \
                    and geometry_aot._immediate(ops[2]) is not None and tags.get(ops[3], ("",))[0] == "lds_addr":
                _, vertex, inv = tags[ops[3]]
                tags[ops[0]] = ("lds_addr", vertex + (1 << geometry_aot._immediate(ops[2])), inv)
                continue
            if re.fullmatch(r"v_add_nc_u32(?:_e32)?", head) and len(ops) == 3 \
                    and tags.get(ops[2], ("",))[0] == "out_addr" and geometry_aot._immediate(ops[1]) is not None:
                tags[ops[0]] = ("out_addr", tags[ops[2]][1] + geometry_aot._immediate(ops[1]))
                continue
            if head.startswith("ds_read"):
                address = ops[1].split()[0]
                tag = tags.get(address, ("",))
                if tag[0] != "lds_addr":
                    raise ValueError(f"Refused {line!r}: an LDS read that is not an HS input read (outputs and other "
                                     "cross-invocation LDS traffic are not lowered)")
                if self.merged:
                    raise ValueError(f"Refused {line!r}: LDS inputs in a merged LS+HS wave are not lowered (only "
                                     "inputs passed in VGPRs)")
                if tag[2] > 1:
                    raise ValueError(f"Refused {line!r}: the invocation id is added to the input address twice")
                op, regs, offsets, width = geometry_aot._ds_access(re.sub(rf", {re.escape(address)}(?=$| |,)",
                                                                          ", v0", line, count=1))
                if width != 4:
                    raise ValueError(f"Refused {line!r}: a byte LDS read")
                self.ls_inputs = "lds"
                vertex = f"{tag[1]}" + ("+cpid" if tag[2] else "")
                add(f"x2w_ls_in {':'.join(regs)}, {vertex}, {','.join(map(str, offsets))}")
                for r in regs:
                    tags.pop(r, None)
                    written_in[r] = name_of(region)
                continue
            if head.startswith("ds_write") and "ls" in region and "hs" not in region:
                raise ValueError(f"Refused {line!r}: the LS half writes its outputs to LDS; LDS inputs in a merged "
                                 "LS+HS wave are not lowered (only inputs passed in VGPRs)")
            if head.startswith("ds_"):
                raise ValueError(f"Refused {line!r}: an LDS access that is not an HS input read")
            if (mb := _mubuf(line)) and mb[0] == "store":
                _, regs, address, rsrc, soffset, imm = mb
                if tags.get(rsrc) == ("tf_ring",):
                    if tags.get(address) != ("tf_addr",) or soffset != "s4" or "inv0" not in region:
                        raise ValueError(f"Refused {line!r}: a TF ring store that is not invocation 0's store at "
                                         "rel_patch_id * factors * 4 with s4")
                    if imm % 4:
                        raise ValueError(f"Refused {line!r}: unaligned TF ring store")
                    add(f"x2w_tf {':'.join(regs)}, {imm // 4}", "inv0")
                    self._check_reads(regs, "inv0", written_in, tags, line)
                    continue
                if tags.get(rsrc) == ("offchip",):
                    tag = tags.get(address, ("",))
                    if tag[0] != "out_addr" or soffset != "s2" or not tail:
                        raise ValueError(f"Refused {line!r}: an off-chip ring store that is not an output store of "
                                         "the output-store lanes (lane index * 16 + offset, s2)")
                    add(f"x2w_out {':'.join(regs)}, {tag[1] + imm}", "hs")
                    self._check_reads(regs, "hs", written_in, tags, line)
                    continue
                raise ValueError(f"Refused {line!r}: a buffer store through a descriptor that is not a ring")
            # An ordinary line: frame values are not data.
            where = name_of(region)
            if head == "s_waitcnt" and where in ("hs", "inv0"):
                add(line, "wave")  # a wait runs for the wave whatever EXEC is: both HS functions see it
                continue
            if where == "all":
                raise ValueError(f"Refused {line!r}: code outside the LS and HS regions")
            if where == "ls" and saw_hs:
                raise ValueError(f"Refused {line!r}: LS code after the HS half began")
            for r in read:
                tag = tags.get(r) if r != "exec" else None
                if tag and not (tag == ("mask", "inv0") and r == "vcc"):
                    if tag == ("inv",):
                        continue
                    raise ValueError(f"Refused {line!r}: reads {r}, which holds a frame value ({tag[0]})")
                if r in ("s2", "s3", "s4", "m0", "s0", "s1") and r not in written_in:
                    raise ValueError(f"Refused {line!r}: reads the hardware SGPR {r} outside the frame idioms")
                if self.layout_sgpr and r == self.layout_sgpr and r not in written_in:
                    raise ValueError(f"Refused {line!r}: reads the tcs_offchip_layout SGPR as data")
            if reads_scc and scc_tag:
                raise ValueError(f"Refused {line!r}: reads the SCC of a frame idiom")
            if writes_scc:
                scc_tag = None
            self._check_reads(read, where, written_in, tags, line)
            for r in written:
                tags.pop(r, None)
                written_in[r] = where
            if re.fullmatch(r"v_cmp_eq_[iu]32_e32 vcc, 0, (v\d+)", line) and tags.get(ops[2]) == ("inv",):
                tags["vcc"] = ("mask", "inv0")
            if head.startswith("v_cmp_") and head.endswith("_e64") and re.fullmatch(r"s\[\d+:\d+\]", ops[0]) \
                    and not any(t.split()[0].lstrip("-|").startswith("v") for t in ops[1:]):
                tags[ops[0]] = ("uniform_cmp",)
            add(line, "vote?" if deferred else where)
        for line, where in self.entries:
            if where == "vote?":
                raise ValueError(f"Refused {line!r}: an exec use that is not one of the frame's (nor a vote bit)")
        if not tail:
            raise ValueError("The program has no output-store frame (the lanes that store the control points)")
        if self.vote == "init":
            raise ValueError("The tess-level vote is initialized but never read")
        if self.vote == "read":
            self._fold_vote()

    def _fold_vote(self):
        """Fold the vote's constant ("not all discarded", 0) through the compares, selects and masks that read it, so
        that the outputs it would zero pass through: s_cmp on constants, s_cselect of constants, 64-bit masks of all
        zeros or all ones and the v_cndmask_b32 they select with. Any other read of a folded register is refused."""
        const = {}
        masks = {}
        scc = None
        out = []
        for line, where in self.entries:
            head, _, rest = line.partition(" ")
            ops = [t.strip() for t in rest.split(",")] if rest else []
            if line == f"s_mov_b32 {self.vote_register}, 0":
                const[self.vote_register] = 0
                continue
            imm = lambda t: const[t] if t in const else geometry_aot._immediate(t)  # noqa: E731
            if head in ("s_cmp_lg_i32", "s_cmp_eq_i32", "s_cmp_lg_u32", "s_cmp_eq_u32") and \
                    (ops[0] in const or ops[1] in const) and imm(ops[0]) is not None and imm(ops[1]) is not None:
                scc = (imm(ops[0]) != imm(ops[1])) == head.startswith("s_cmp_lg")
                continue
            if head == "s_cselect_b32" and geometry_aot._immediate(ops[1]) is not None and \
                    geometry_aot._immediate(ops[1]) == geometry_aot._immediate(ops[2]):
                const[ops[0]] = geometry_aot._immediate(ops[1])
                masks.pop(ops[0], None)
                out.append((f"s_mov_b32 {ops[0]}, {ops[1]}", where))
                continue
            if head == "s_cselect_b64" and ops[1:] == ["-1", "0"] and scc is not None:
                masks[ops[0]] = scc
                for r in geometry_aot._registers(ops[0]):
                    const.pop(r, None)
                continue
            if head == "s_mov_b64" and ops[1] in masks:
                masks[ops[0]] = masks[ops[1]]
                continue
            if head.startswith("v_cndmask_b32") and len(ops) == 4 and ops[3] in masks:
                out.append((f"v_mov_b32_e32 {ops[0]}, {ops[2] if masks[ops[3]] else ops[1]}", where))
                continue
            written, read = _operands(line)
            for r in read:
                if r in const or any(r in geometry_aot._registers(m) or r == m for m in masks):
                    raise ValueError(f"Refused {line!r}: reads a value derived from the tess-level vote")
            if _scc(line)[0]:
                scc = None
            if _scc(line)[1] and scc is not None:
                raise ValueError(f"Refused {line!r}: reads the SCC of a compare of the tess-level vote")
            for r in written:
                const.pop(r, None)
                for m in [m for m in masks if r in geometry_aot._registers(m) or r == m]:
                    masks.pop(m)
            out.append((line, where))
        self.entries = out

    def _check_reads(self, read, where, written_in, tags, line):
        for r in read:
            if r.startswith("v") and r[1:].isdigit() or r.startswith("s") and r[1:].isdigit():
                came = written_in.get(r)
                if came == "inv0" and where != "inv0":
                    raise ValueError(f"Refused {line!r}: reads {r}, which only invocation 0's region writes")
                if came == "ls" and where != "ls" and r.startswith("s"):
                    raise ValueError(f"Refused {line!r}: reads {r}, an SGPR the LS half writes (the vertex shader's "
                                     "scalar values do not cross to the hull shader)")

    def _drop_vote_bits(self, bits, barrier_at, rest):
        """The lines since the last barrier that compute the vote bits only: removed, if nothing else reads them."""
        if barrier_at is None:
            raise ValueError("Tess-level vote without a barrier before it")
        live = {bits}
        keep = []
        removed_writes = set()
        for line, where in reversed(self.entries[barrier_at:]):
            written, read = _operands(line)
            writes_scc, reads_scc = _scc(line)
            outs = set(written) | ({"scc"} if writes_scc else set())
            if outs & live:
                live = (live - outs) | set(read) | ({"scc"} if reads_scc else set())
                removed_writes |= outs
                continue
            if live & {"scc"} and writes_scc:
                raise ValueError(f"Tess-level vote: {line!r} writes SCC between vote lines")
            keep.append((line, where))
        live.discard("scc")
        self.entries[barrier_at:] = list(reversed(keep))
        # Every value a removed line computes must die before anything else reads it.
        for register in sorted(removed_writes - {"scc"}):
            for line in rest:
                written, read = _operands(line)
                if register in read:
                    raise ValueError(f"Tess-level vote: {register}, which the vote bits compute, is read by {line!r}")
                if register in written:
                    break
        for line, _ in keep:
            if set(_operands(line)[1]) & removed_writes - {"scc"}:
                raise ValueError(f"Tess-level vote: {line!r} reads a value the vote bits compute")


def _ls_live_out(entries):
    """The VGPRs the HS half reads that the LS half wrote last (the inputs RADV passes in registers), in order."""
    written_ls = set()
    out = []
    hs_written = set()
    for line, where in entries:
        if line.startswith("x2w_"):
            head, _, rest = line.partition(" ")
            regs = rest.split(", ")[0].split(":")
            if head in ("x2w_tf", "x2w_out"):
                reads, writes = regs, []
            else:
                reads, writes = [], regs
        else:
            writes, reads = _operands(line)
            if re.fullmatch(r"v_f?mac_\w+", line.split()[0]):
                reads = reads + writes
        if where == "ls":
            written_ls |= {r for r in writes if r.startswith("v")}
            continue
        for r in reads:
            if r.startswith("v") and r in written_ls and r not in hs_written and r not in out:
                out.append(r)
        hs_written |= {r for r in writes if r.startswith("v")}
    return out


def lower_lshs(instructions, user_sgprs, state):
    """Returns (vertex shader HLSL or None for an HS without its LS half, hull shader HLSL, layout)."""
    state = check_state(state)
    program = geometry_aot._strip_labels(vertex_aot._clean(instructions))
    rest, frame_roles = {}, {}
    for number, role in (user_sgprs or {}).items():
        (frame_roles if role == ("tcs_offchip_layout",) else rest)[number] = role
    frame = HsFrame(program, state, user_sgprs or {})
    for line, _ in frame.entries:
        if line.startswith("x2w_"):
            continue
        for pattern, reason in vertex_aot.REFUSALS:
            if re.fullmatch(pattern, line):
                raise ValueError(f"Refused {line!r}: {reason}")
    entry_scalar, tables, root, has_constants = vertex_aot._role_map(rest, "ngg")
    uses_vsharps = any(len(e) == 2 for _, entries in tables.values() for e in entries.values())
    m, n = state["input_control_points"], state["output_control_points"]
    if frame.ls_inputs == "lds":
        if state["ls_slots"] is None:
            raise ValueError("An HS that reads its inputs from LDS needs ls_slots in the state")
        ls_struct = ls_slot_struct(state)
        live = []
    else:
        if frame.merged and m != n:
            raise ValueError("Inputs in VGPRs need equal input and output patch sizes (tcs_inputs_via_temp)")
        live = _ls_live_out(frame.entries)
        ls_struct = ["struct LsOutput {", *(f"    uint4 l{j} : TEXCOORD{j};" for j in range(max(1, -(-len(live) // 4)))),
                     "};"]
        if not frame.merged and live:
            raise ValueError(f"The HS reads {', '.join(live)}, which nothing writes")

    vs_source = None
    if frame.merged:
        st = geometry_aot._state(entry_scalar, {"v2": ("uint", "vid"), "v5": ("uint", "iid")}, has_constants)
        ended = []

        def ls_special(i, line):
            return False

        ls_lines = [line for line, where in frame.entries if where == "ls"]
        uses_instance = vertex_aot.run_body(st, ls_lines, tables, "ngg", ls_special, entry_vgprs={"v5": "iid"},
                                            reasons=LS_REASONS)
        geometry_aot._check_state(st)
        st.vm_wait(0)
        st.pending.clear()
        words = [vector_u32(r, st.scalar, st.vector, st.pending, st.sample_pending) for r in live]
        del ended
        place_fma_mix(st)
        inputs = "uint vid : SV_VertexID" + (", uint iid : SV_InstanceID" if uses_instance else "")
        st.lines[st.lines.index(PREAMBLE)] = "\n".join([HELPERS, *ls_struct, f"LsOutput main({inputs}) {{"])
        stores = ["    LsOutput ls_out;"]
        for j in range(max(1, -(-len(live) // 4))):
            parts = [words[4 * j + c] if 4 * j + c < len(words) else "0u" for c in range(4)]
            stores.append(f"    ls_out.l{j} = uint4({', '.join(parts)});")
        vs_source = "\n".join([*vertex_aot.declarations(st, root, has_constants, uses_vsharps), *st.lines, *stores,
                               "    return ls_out;", "}", ""])

    outer, inner = DOMAINS[state["domain"]]
    functions = {}
    results = {}
    for kind in ("cp", "pcf"):
        g = geometry_aot._state(entry_scalar, {}, has_constants)
        queue = geometry_aot.DsQueue(g)
        g.lines.append("    uint cpid = 0u;" if kind == "pcf" else "    // cpid: SV_OutputControlPointID")
        for j, r in enumerate(live):
            name = f"lsin{j}"
            g.lines.append(f"    uint {name} = ip[cpid].l{j // 4}.{'xyzw'[j % 4]};")
            g.vector[r] = ("uint", name)
        factors, outputs = {}, {}
        keep = ("hs", "inv0", "wave") if kind == "pcf" else ("hs", "wave")
        lines = [line for line, where in frame.entries if where in keep]

        def special(i, line, g=g, queue=queue, factors=factors, outputs=outputs, kind=kind):
            if geometry_aot._wait(g, queue, i, line):
                return True
            if not line.startswith("x2w_"):
                return False
            head, _, rest = line.partition(" ")
            parts = rest.split(", ")
            regs = parts[0].split(":")
            if head == "x2w_inv":
                g.vector[regs[0]] = ("uint", "cpid")
            elif head == "x2w_scc_lane":
                bit = exec_mask.mask_bit(g, rest)
                if bit is None:
                    raise ValueError(f"Refused {line!r}: the compare mask is not a lane mask")
                g.scc = bit
            elif head == "x2w_ls_in":
                vertex, offsets = parts[1], [int(o) for o in parts[2].split(",")]
                base, _, plus = vertex.partition("+")
                index = f"{base}u" + (" + cpid" if plus else "")
                for j, (register, offset) in enumerate(zip(regs, offsets)):
                    if offset < VOTE_BYTES:
                        raise ValueError(f"Refused {line!r}: reads the tess-level vote word as an input")
                    slot, comp = divmod(offset - VOTE_BYTES, 16)
                    if slot >= state["ls_slots"]:
                        raise ValueError(f"Refused LDS input slot {slot}: the state gives {state['ls_slots']} slots")
                    if not plus and int(base) >= m:
                        raise ValueError(f"Refused LDS input vertex {base}: the patch has {m}")
                    name = f"lds{i}_{j}"
                    g.lines.append(f"    uint {name} = ip[{index}].s{slot}.{'xyzw'[comp // 4]};")
                    g.vector[register] = ("uint", name)
                queue.issue(regs)
            elif head == "x2w_tf":
                if kind == "pcf":
                    for j, register in enumerate(regs):
                        word = int(parts[1]) + j
                        if word >= outer + inner or word in factors:
                            raise ValueError(f"Refused TF ring word {word}: out of range or stored twice")
                        factors[word] = vector_u32(register, g.scalar, g.vector, g.pending, g.sample_pending)
            elif head == "x2w_out":
                if kind == "cp":
                    for j, register in enumerate(regs):
                        slot, vertex, comp = _decompose(int(parts[1]) + 4 * j, state, line)
                        if vertex:
                            raise ValueError(f"Refused {line!r}: an output store past the lane's control point")
                        if (slot, comp) in outputs:
                            raise ValueError(f"Refused {line!r}: output slot {slot} component {comp} stored twice")
                        name = f"out{slot}_{comp}"
                        g.lines.append(f"    uint {name} = "
                                       f"{vector_u32(register, g.scalar, g.vector, g.pending, g.sample_pending)};")
                        outputs[(slot, comp)] = name
            else:
                raise AssertionError(line)
            return True

        vertex_aot.run_body(g, lines, tables, "ngg", special, entry_vgprs={}, reasons=HS_REASONS)
        geometry_aot._check_state(g)
        place_fma_mix(g)
        functions[kind] = g
        results[kind] = (factors, outputs)
    factors, _ = results["pcf"]
    _, outputs = results["cp"]
    missing = [w for w in range(outer + inner) if w not in factors]
    if missing:
        raise ValueError(f"Invocation 0 does not store tessellation factor words {missing}")
    if not outputs:
        raise ValueError("The HS stores no control-point output")
    cp, pcf = functions["cp"], functions["pcf"]
    ip = f"InputPatch<LsOutput, {m}> ip"
    pcf.lines[pcf.lines.index(PREAMBLE)] = f"HsPatch patch_constants({ip}) {{"
    pcf_tail = ["    HsPatch patch;"]
    pcf_tail += [f"    patch.edges[{w}] = asfloat({factors[w]});" for w in range(outer)]
    pcf_tail += ([f"    patch.inside = asfloat({factors[outer]});"] if inner == 1 else
                 [f"    patch.inside[{j}] = asfloat({factors[outer + j]});" for j in range(inner)])
    pcf_tail += ["    return patch;", "}", ""]
    cp.lines[cp.lines.index(PREAMBLE)] = "\n".join([
        f"[domain(\"{state['domain']}\")]", f"[partitioning(\"{state['partitioning']}\")]",
        f"[outputtopology(\"{state['topology']}\")]", f"[outputcontrolpoints({n})]",
        "[patchconstantfunc(\"patch_constants\")]",
        f"HsControlPoint main({ip}, uint cpid : SV_OutputControlPointID) {{"])
    cp_tail = ["    HsControlPoint cp_out;"]
    for k in range(state["vertex_slots"]):
        parts = [outputs.get((k, c), "0u") for c in range(4)]
        cp_tail.append(f"    cp_out.a{k} = uint4({', '.join(parts)});")
    cp_tail += ["    return cp_out;", "}", ""]
    head = []
    for g in (cp, pcf):
        for text in vertex_aot.declarations(g, root, has_constants, uses_vsharps):
            if text not in head:
                head.append(text)
    hs_source = "\n".join([*head, HELPERS, *ls_struct, *control_point_struct(state), *patch_struct(state), *pcf.lines,
                           *pcf_tail, *cp.lines, *cp_tail])
    layout = {"merged": frame.merged, "inputs": frame.ls_inputs, "live": live, "vote": frame.vote == "read",
              "outputs": sorted(outputs), "factors": outer + inner}
    return vs_source, hs_source, layout


def parse_role_map(data):
    out, rest = {}, {}
    for key, value in data.items():
        if isinstance(value, dict) and value.get("role") == "tcs_offchip_layout":
            out[int(key)] = ("tcs_offchip_layout",)
        else:
            rest[key] = value
    out.update(vertex_aot.parse_role_map(rest))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=("tes", "hs"))
    parser.add_argument("program", type=Path)
    parser.add_argument("--user-sgprs", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hs-output", type=Path)
    parser.add_argument("--vs-output", type=Path)
    args = parser.parse_args()
    try:
        roles = parse_role_map(json.loads(args.user_sgprs.read_text(encoding="utf-8")))
        state = json.loads(args.state.read_text(encoding="utf-8"))
        program = args.program.read_text(encoding="utf-8").splitlines()
        if args.kind == "tes":
            source, layout = lower_tes(program, roles, state)
            args.output.write_text(source, encoding="ascii")
            print(json.dumps({"params": layout["params"]}))
        else:
            vs, hs, layout = lower_lshs(program, roles, state)
            args.hs_output.write_text(hs, encoding="ascii")
            if vs is not None and args.vs_output:
                args.vs_output.write_text(vs, encoding="ascii")
            print(json.dumps({k: layout[k] for k in ("merged", "inputs", "vote")}))
    except ValueError as error:
        print(f"tess_aot: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
