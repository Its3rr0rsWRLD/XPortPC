# Tessellation, geometry and mesh stages: design

Status: card G-1 (NGG geometry shader to an HLSL vertex and geometry shader pair) is implemented in
`tools/geometry_aot.py` and checked by `tests/geometry_aot_check.py` (CTest `geometry_aot_controls` and
`geometry_aot_<family>_<adapter>`, families `corpus`, `explode`, `strips`). Every other card below is designed only;
the translator refuses those programs with the card's name. `stages_supported` in `site/status.json` is unchanged.

The pixel, vertex ([vertex-stage.md](vertex-stage.md)) and compute ([compute-stage.md](compute-stage.md)) stages map
one console program onto one desktop shader. The stages here do not. On gfx10 the hardware runs two API stages as one
*merged* wave (LS+HS for vertex and tessellation control, ES+GS for vertex or tessellation evaluation and geometry),
hands data between the two halves through LDS, and, with NGG, ends the wave with a fixed epilogue that does the
primitive assembly the desktop input assembler and geometry stage do themselves. The translation has to split each
merged wave back into its API stages and turn the LDS hand-off into HLSL stage inputs and outputs.

References: the AMD "RDNA 2" Instruction Set Architecture reference guide (public), and Mesa (MIT): RADV's argument
layout `src/amd/vulkan/radv_shader_args.c` and the NIR lowerings `src/amd/common/nir/ac_nir_lower_tess_io_to_mem.c`,
`ac_nir_lower_esgs_io_to_mem.c`, `ac_nir_lower_ngg.c`, `ac_nir_lower_ngg_gs.c`, `ac_nir_lower_ngg_mesh.c` and
`ac_nir_lower_taskmesh_io_to_mem.c`. Line references are to the Mesa 26.2.6 release tarball; the corpus was compiled
by RADV 25.2.8 (the Ubuntu package), so a detail read in the source is checked against the dumps before it is used.

## What the corpus shows

`tests/corpus/isa/stages/` holds 22 programs: every tessellation and geometry shader of the two corpus sources
(SaschaWillems/Vulkan, Vulkan-Samples), compiled for gfx1013 with NGG on and with geometry shaders paired to a vertex
shader (`build_corpus.py --pair-geom`; see [tests/corpus/README.md](../../tests/corpus/README.md)).
`python3 -B tools/stage_corpus_report.py` prints the counts below and writes
[docs/coverage/stage-corpus.tsv](../coverage/stage-corpus.tsv).

| Hardware stage (dump header) | NGG | Programs | Translated |
|---|---|---|---|
| Vertex Shader as ES + Geometry Shader (merged ES+GS) | yes | 6 | 3 (G-1) |
| Vertex Shader as LS + Tessellation Control Shader (merged LS+HS) | no | 5 | 0 (T-1) |
| Tessellation Control Shader (HS alone: builder pipelines without a VS) | no | 3 | 0 (T-1) |
| Tessellation Evaluation Shader as ESGS | yes | 8 | 0 (T-2) |
| Mesh / Task Shader | - | 0 | - |

- **ES+GS.** The 6 programs are 4 `shader_object` and `geometryshader` geometry shaders built behind a borrowed vertex
  shader, and the two vertex+geometry pipelines of `deferredshadows` and `gshader_to_mshader`. All six use RADV's NGG
  GS frame (below). The three that translate are triangle-strip outputs with `max_vertices = 3`. The refusals:
  `deferredshadows/shadow` reads the invocation id (GS instancing, `gl_InvocationID` for the layer) and exports the
  layer in `pos1`; `geometryshader/normaldebug` and `gshader_to_mshader` emit line strips with an even
  `max_vertices`, whose epilogue and vertex addressing differ (RADV swizzles the output slots of an even
  `max_vertices`, ac_nir_lower_ngg_gs.c `ngg_gs_out_vertex_addr`).
- **With `nongg`** the same six are legacy GS programs (GSVS ring stores and `MSG_GS_EMIT`/`CUT`/`DONE`), which need a
  separate GS copy shader that the builder does not dump. The `isa-main` corpus build (`nongg`) counts them under
  "other" with the legacy TES "as VS".
- **LS+HS.** The LS half fetches vertices like a vertex shader; with equal input and output patch sizes RADV passes
  VS outputs to the HS in VGPRs (`tcs_inputs_via_temp`, ac_nir_lower_tess_io_to_mem.c) and otherwise through LDS
  (`ds_write`/`ds_read`, up to 17 per program). Every HS writes the tessellation factors with `buffer_store_dwordx4`
  through the TF ring descriptor (`s_load_dwordx4 s[..], s[0:1], 0x50`) from invocation 0 of each patch, and its
  outputs with offset-addressed stores through the off-chip ring (`s[0:1], 0x60`) in the attribute-major layout the
  Mesa comment draws.
- **TES as ESGS.** All 8 run inside the same NGG passthrough frame that card V-2 matches for vertex shaders. The body
  reads control points from the off-chip ring at `rel_patch_id * patch_stride + attribute_offset`, and the tess
  coordinates arrive in v5/v6 (v7 relative patch id, v8 patch id, radv_shader_args.c `declare_tes_input_vgprs`).
- **Mesh and task.** None. RADV exposes VK_EXT_mesh_shader only when `gfx_level >= GFX10_3` and a compute queue exists
  (radv_physical_device.c `radv_taskmesh_enabled`), so gfx1013 (gfx10.1 to RADV) has no mesh shaders, and the null
  winsys refused the extension for `RADV_FORCE_FAMILY=NAVI21` as well (vkCreateDevice returned
  VK_ERROR_EXTENSION_NOT_PRESENT). Mesh programs are designed from the Mesa source alone; no dump checks the design.

## The merged ES+GS wave (NGG)

ac_nir_lower_ngg_gs.c and radv_shader_args.c give the layout, and the six dumps confirm it:

- **Entry.** s2 `gs_tg_info` (vertex count bits 12..20, primitive count 22..30), s3 `merged_wave_info` (ES lanes in
  0..7, GS lanes in 8..15, wave id in 24..27), user SGPRs from s8. VGPRs: v0 vertex offsets 0 and 1 (16 bits each), v1
  offsets 2 and 3, v2 primitive id, v3 invocation id, v4 offsets 4 and 5, then the ES inputs (v5 vertex id, v8
  instance id).
- **ES region**, `exec` from the ES lane count: the vertex body, whose outputs are LDS stores at `lane * es_stride`,
  the lane from `v_mbcnt` over `wave_id * 64`. `es_stride` is an odd number of dwords (20 or 36 bytes in the corpus).
- **GS region**, after `s_barrier`, `exec` from the GS lane count: input vertex k at
  `v_mad_u32_u16 vA, es_stride, v0|v1, 0` (op_sel selects the high half), its words read by `ds_read*`. Each
  `EmitVertex` stores the outputs to slot `lane * max_vertices + k` (`gs_lane_stride = max_vertices * vertex_stride`
  from the `ngg_lds_layout` user SGPR) at byte 4 + field, and one primitive-flag byte after the outputs: bit 0 the
  vertex completes a primitive, bit 1 the primitive is odd (triangle strips), bit 2 the vertex is live. A slot the GS
  does not emit gets flag 0 (`ngg_gs_clear_primflags`). The GS body also tests bit 6 of the `ngg_state` SGPR
  (pipeline-statistics query) for the block after it.
- **Statistics block**: under the query bit, one lane adds the wave's GS invocation count to two GDS counters.
- **Epilogue**: counts the live vertices per wave in LDS, `GS_ALLOC_REQ`, writes each vertex's export index, builds
  each primitive's export from the flag of its last vertex (indices k-2, k-1+odd, k-odd with the provoking vertex
  first, `ngg_gs_process_out_primitive`), and exports each live vertex's words from LDS (`exp pos0`, `exp paramN`).

## Card G-1: NGG ES+GS to a vertex and geometry shader (implemented)

**Split.** `split_frame()` matches the ES head, the GS head, the statistics block and the epilogue instruction by
instruction. A template names registers, numbers and labels; a register binds consistently, to no other name in the
same block, and the pairs of names that share a register in the corpus program must share one in the match (RADV
reuses s0, s1 and s[0:1] across the epilogue; a renaming that merged or split two of them could change what the
frame computes). The epilogue gives the vertex stride, the flag offset and the export map (which LDS field each
`exp` channel reads). What lies between the heads is the ES body and the GS body.

**Idioms.** `_scan()` removes the lines that compute frame values (`s_bfe_u32 s, s3, 0x40018`, the shift by 6, the two
`v_mbcnt`, the ES `v_mul_u32_u24`, the GS `v_mad_u32_u24 ... lds_layout`, the vertex-offset `v_mad_u32_u16`, the
query-bit test) and tags their results. A body line may read a tagged register only as the address of an LDS access;
it may not read s2, s3, m0, the NGG SGPRs, the GS entry VGPRs, or (in the GS) an SGPR the ES half writes: the
GS half's value of such an SGPR depends on whether the ES half ran, which it does not when the wave has no ES lanes.
No SCC writer may stand between the query-bit test and the branch that reads it. The ES half may not write v0, v1
or the NGG SGPRs.

**HLSL.** The ES body is lowered by tools/vertex_aot.py's loop (`run_body`, the same forms and user-SGPR role map,
NGG entry roles) into a vertex shader whose `EsOutput` holds the ES LDS words as `uint4 esN : TEXCOORDN`. The GS
body is lowered by the same loop into a geometry shader with `triangle EsOutput input[3]`: an LDS read of input
vertex k at byte B is `input[k]` word B / 4 (refused when the ES half never writes that word), an output store names
word (B - 4) mod vertex_stride of vertex (B - 4) / vertex_stride. LDS reads complete in issue order, so
`s_waitcnt lgkmcnt(N)` with N > 0 completes all but the newest N of them when no scalar load is outstanding
(refused otherwise). The flags must be constants; each triangle they complete is appended as its own strip in RADV's
order (k-2, k-1+odd, k-odd) followed by `RestartStrip()`, so the vertex order, the winding and the provoking vertex
are the console's, whatever the desktop strip rule is. `[maxvertexcount]` is three per triangle. The outputs are
the epilogue's exports in tools/vertex_aot.py's order (TEXCOORD0, SV_Position, TEXCOORD1..N), so a translated pixel
shader links to them. The frame, the statistics block and the epilogue are dropped: allocation, compaction and
primitive export are what the desktop geometry stage does. The pipeline-statistics counters the block adds to are
the runtime's business (a desktop query counts GS invocations itself).

**Refused, each with its own reason:** another frame, an even `max_vertices`, line and point output, the
provoking-vertex-last export, culling or any other LDS use, `pos1..3` (they need `PA_CL_VS_OUT_CNTL` state, as in
the vertex stage), the primitive id (v2) and the invocation id (v3, GS instancing) until a draw checks them, vertex
offsets 3..5 (adjacency), a non-constant flag (an emit count that depends on data), and control flow in either body.

**Check.** `tests/geometry_aot_check.py draw` translates each family, compiles vs_6_0 and gs_6_0, draws a triangle
list through both (`offscreen_check --check-geometry-case`, tests/vertex_aot_render.cpp with a GS output count in
case header word 20) and compares every stream-output dword of the GS output with `GeometryModel`, a lane-by-lane
model of the merged wave: the ES body per vertex lane writes a 64 KiB LDS array, the GS body per primitive lane with
the console's packed vertex offsets writes slots and flags, and the reference assembles triangles from the flags and
reads the exported fields at the offsets the test itself declares. It runs the bodies the test wrote, idiom lines
included, without the translator's matcher. Families: `corpus` (the committed pass-through program with its derived
role map: push constants, a constant buffer, a vertex V#), `explode` (a four-vertex strip whose second triangle is
odd, a cleared fifth slot, a face normal computed in the GS, constants read in both halves) and `strips` (two strips
separated by a cut, inputs permuted, NaN payloads, infinities and subnormals passed through, partial `lgkmcnt`
waits). Wrong references that must be reported: the D3D strip order for odd triangles, all vertices taken as one
strip, the dead slot drawn, input vertices 1 and 2 exchanged, an ES word read off by one, the base vertex ignored, a
fused multiply-add. `controls` runs 32 refusals and checks every wrong reference changes some dword; `binary`
assembles the three programs with llvm-mc 15 in wave64, disassembles them and requires the same HLSL.

## Card G-2: GS instancing, primitive id, layer and viewport (designed)

`[instance(N)]` and `SV_GSInstanceID` for v3, with N from the GS state (`VGT_GS_INSTANCE_CNT`) that the title's
pipeline gives; `SV_PrimitiveID` for v2 after a draw shows that the console's primitive id and D3D12's count the same
way over instances and strips; `pos1` channels to `SV_RenderTargetArrayIndex` and `SV_ViewportArrayIndex` under
`PA_CL_VS_OUT_CNTL` (`deferredshadows/shadow` needs all three). Even `max_vertices`: match the slot swizzle
(`out_vtx_idx ^ ((out_vtx_idx >> 5) & (2^k - 1))`) in the emit address and the epilogue. Line strips and points:
`LineStream`/`PointStream` with the two- and one-index primitive exports. Data-dependent emit counts (a flag stored
under control flow) wait for the vertex stage's CF cards.

## Card G-3: legacy (GSVS ring) geometry shaders (designed)

Without NGG the GS half writes each emitted vertex to the GSVS ring with `buffer_store_dword*` at dword
`(slot * 4 + component) * max_vertices + vertex` per lane (swizzled by the ring V#), counts emits with
`s_sendmsg MSG_GS_EMIT/CUT`, and a separate GS copy shader (a VS) reads the ring and exports. The ring layout and the
slot-to-export mapping are only in that copy shader and in `VGT_GS_MAX_VERT_OUT`, so the card needs both as inputs,
matches the copy shader as a frame and maps ring stores to output words. The ES-to-GS hand-off is LDS as in G-1
(gfx10 merges ES and GS here too).

## Card T-1: LS+HS to a vertex shader and an HLSL hull shader (designed)

- **LS half** becomes a vertex shader whose outputs are the LDS words it stores (`ds_write` at
  `rel_patch_id * input_patch_stride + vertex * vertex_stride + slot * 16`, ac_nir_lower_tess_io_to_mem.c LDS layout)
  or, when RADV passes them in VGPRs (`tcs_inputs_via_temp`), the VGPRs live at the LS/HS boundary.
- **HS half** becomes the control-point function (`[outputcontrolpoints(N)]`, `SV_OutputControlPointID` from the
  relative invocation id in v1 bits 8..12) reading `InputPatch<EsOutput, M>`; its off-chip ring stores at
  `hs_per_vertex_output_vmem_offset` become output control-point words, and its per-patch stores per-patch
  constants.
- **Tessellation factors.** The TF ring store from invocation 0 becomes the patch-constant function's
  `SV_TessFactor`/`SV_InsideTessFactor`. HLSL computes those in a separate function that reads `InputPatch` and
  `OutputPatch`, so the card accepts factor computations that read only inputs, outputs and constants, and refuses one
  that depends on other cross-invocation LDS state.
- **State.** Domain, partitioning, output topology (`VGT_TF_PARAM`) and the patch sizes come from the pipeline and
  become `[domain]`, `[partitioning]`, `[outputtopology]`. The ring layout needs the patch count and attribute counts
  (`tcs_offchip_layout` user SGPR) at translation time to decompose a store offset into (vertex, attribute).
- **Risk.** The desktop tessellator must produce the same domain points. D3D11 specifies the tessellator exactly; the
  console's partitioning modes have to be checked against it point by point on both adapters before any card claims a
  bit-exact draw. Tests compare per domain point (stream output keyed by `SV_DomainLocation`), not by order.

## Card T-2: TES to an HLSL domain shader (designed)

The TES body sits in V-2's passthrough frame, so the frame matcher is reused with TES entry roles (v5, v6 tess
coordinates; v7 relative patch id; v8 patch id). It becomes a domain shader with `SV_DomainLocation` (u, v; the
shader computes w itself, as the corpus does with `1 - u - v`), `SV_PrimitiveID` and an
`OutputPatch<HsOutput, N>`: an off-chip ring load at `rel_patch_id * patch_stride + offset` maps to output control
point and attribute by the same layout as T-1. The domain shader's outputs are the exports (pos0, paramN). A TES that
feeds a GS runs as the ES half of a G-1 wave and gets the ES outputs instead. T-1 and T-2 land together: one cannot
be drawn without the other.

## Cards M-1 and M-2: mesh and amplification shaders (designed, no corpus)

On RDNA2, RADV runs a mesh shader as an NGG wave with compute-like workgroup semantics (ac_nir_lower_ngg_mesh.c):
`SetMeshOutputs` becomes `GS_ALLOC_REQ` with the vertex and primitive counts, per-vertex and per-primitive outputs go
to LDS (or straight to export when each lane writes only its own), and an epilogue exports primitives and vertices.
That maps naturally onto an HLSL mesh shader (`[outputtopology]`, `[numthreads]`, `SetMeshOutputCounts`,
`out vertices`/`out indices`): the LDS output arrays become the `vertices`, `primitives` and `indices` arrays, the
epilogue is dropped, and workgroup LDS that is not output is `groupshared` as in compute card C-6. Task shaders run
on the compute queue and write their payload and draw entries to rings in memory
(ac_nir_lower_taskmesh_io_to_mem.c); an amplification shader's `DispatchMesh(x, y, z, payload)` replaces both, with
the ring reads in the mesh shader becoming the payload input. Both need ms_6_5/as_6_5 and a device with mesh shader
support (Tier 1), so their draws can skip with 77 on WARP or older hardware. Nothing here is drawn or matched: the
title's own compiler output for a mesh shader is the first input these cards need, and RADV produces none for
gfx1013.

## Reproduction

```bash
python3 -B tools/stage_corpus_report.py --summary docs/coverage/stage-corpus.tsv
python3 -B tests/geometry_aot_check.py controls
L=<llvm15>/bin; python3 -B tests/geometry_aot_check.py binary $L/llvm-mc $L/llvm-objcopy
ctest --preset dev --no-tests=error -R '^geometry_aot_' -V          # Windows, DXC and a D3D12 adapter
# Rebuild the stage corpus (Linux, RADV 25.2.8 null winsys; see docs/coverage/corpus-sources.md):
python3 tools/shader_corpus_build/build_corpus.py sascha <Vulkan>/shaders/glsl <work> <out> --pair-geom
```
