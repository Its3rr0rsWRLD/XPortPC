# Vertex stage: design

Status: proposed. Nothing is implemented yet except the corpus measurement (`tools/vertex_corpus_report.py`,
checked by `tests/vertex_corpus_report_check.py`). The translator today accepts only the pixel stage
(`tools/pixel_aot.py`, `stages_supported: ["pixel"]` in `site/status.json`).

## Why vertex next
The corpus (544 MIT/Apache shaders, [corpus-sources.md](../coverage/corpus-sources.md)) has 244 vertex shaders.
167 of them already use only covered instruction forms, and all 167 are straight-line. No other stage is that close:
compute has 1 of 27 and other has 4 of 23. What is missing for these 167 is the vertex-stage contract: where the
inputs come from, what the exports mean, and how a draw is checked. Very few new instruction lowerings are needed.

## What the corpus shows
These figures come from `python3 -B tools/vertex_corpus_report.py --isa <isa-main> --isa <isa-ngg>`, run at d02d2a2
with the covered set in `site/status.json`. `<isa-main>` is the corpus as it was built (RADV 25.2.8,
`RADV_FORCE_FAMILY=GFX1013`, `RADV_DEBUG=shaders,nocache,nongg`). `<isa-ngg>` is the same sources compiled by
`tools/shader_corpus_build/build_corpus.py` without `NONGG`, so NGG stays on. The 244 vertex shaders are the same in
both builds.

### Hardware stage
- The built corpus has **244 legacy hardware VS, 0 NGG**. This comes from the build choice (`nongg`), not from the
  sources.
- With NGG on, **244 of 244 are NGG** (`# Vertex Shader as ESGS`), and **244 of 244 match the passthrough frame**
  described below. 237 export the primitive first and 7 export the vertex first.
- No vertex shader culls. Under `RADV_PERFTEST=nggc`, 281 vertex pipelines (vertex plus pixel, without tessellation
  or geometry) contain no LDS, `v_mbcnt`, `s_bcnt`, readlane, permlane or DPP operation in their ESGS section. On
  gfx1013, RADV 25.2.8 does not emit lane-cooperative culling for these shaders. This is observed only; the reason
  was not checked in Mesa.
- With the frame removed, each NGG body is the legacy program. The forms of the two builds match for 211 of 244
  shaders. The other 33 differ only in `s_clause` or `s_waitcnt_depctr`, which are scheduling hints. Every shader gets
  the same card in both builds.
- LS/ES-merged vertex shaders (vertex plus tessellation or geometry) count under "other" (7 shaders). They are out of
  scope here.

### Inputs
- Vertex fetch is **untyped**: 189 shaders use `buffer_load_dword{,x2,x3,x4} ... idxen`, indexed by the vertex-id
  VGPR plus a base SGPR. 175 use only that kind of fetch, and 44 fetch nothing (full-screen triangles built from the
  vertex id). None uses `buffer_load_format_*` or `tbuffer_*`. The corpus builder declares every attribute as
  float4/int4/uint4, so RADV knows the format and loads raw dwords. A title that fetches 8- or 16-bit formats would
  use typed loads, and this corpus cannot measure that.
- The V#s come from a descriptor list in memory. A 32-bit pointer in a user SGPR is completed with
  `s_movk_i32 s(n+1), 0x8000` (RADV's 32-bit address high word) and read by `s_load_dwordx8` or `x4`, two V#s or one
  at a time. Constants come from `s_buffer_load_dword*` through a constant-buffer V# loaded the same way. This is the
  pixel path's runtime-V# contract, with a different pointer register and high word.
- Entry VGPRs: legacy **v0 = vertex id (244), v3 = instance id (15)**. NGG **v5 = vertex id, v8 = instance id**, and
  v0 is the primitive payload (`exp prim v0`). The index the fetch uses is `v_add_nc_u32 vX, sBase, vVertexId`: the
  hardware id plus a base-vertex user SGPR.
- 63 shaders read user SGPRs as data, not as pointers: push constants that RADV passes inline, and in one fixture
  shape an inline V#. 25 use offset-addressed (`offen`) buffer loads or `global_load` (SSBO, buffer device address).
  11 use `s_getpc_b64` to address constants stored after the code, and 1 samples a texture (`image_sample_lz`).

### Outputs
- `exp pos0 ... done vm` appears in 244 shaders. `exp pos1` appears in 1 (`gl_ClipDistance`, one channel).
- `exp paramN`: 0 to 5 per shader (0: 39, 1: 114, 2: 24, 3: 53, 4: 10, 5: 4). 180 param exports leave channels
  `off`.
- `gl_PointSize` is written in some sources, but RADV drops it for triangle pipelines. No point-size export appears.

### Forms that block the remaining 77
In 57 of the 77, one uncovered form is the only blocker. The remaining 20 have 2 forms (2 shaders), 3 (12), 6 (4) or
9 (2). If covering forms were the only work, the greedy order would be:

| Form(s) covered | Unlocked | Total covered |
|---|---|---|
| `v_cvt_f32_i32` | +25 | 192 |
| `v_cvt_f32_i32_e64` | +14 | 206 |
| `s_getpc_b64` | +5 | 211 |
| `s_cmp_eq_i32` | +4 | 215 |
| `s_lshl_b32` | +3 | 218 |
| `v_sin_f32_e64` | +3 | 221 |
| `image_sample_lz`, `v_cvt_f32_u32`, `v_cvt_i32_f32`, `v_rndne_f32` | +1 each | 225 |
| `v_sin_f32` + `v_cos_f32` | +4 | 229 |
| `v_cmp_eq_i32_e64` + `v_cmp_le_i32` | +5 | 234 |

`v_cvt_f32_i32` alone blocks 34 shaders, most of them full-screen-triangle UVs built from `gl_VertexIndex`. Forms
that vertex shaders use and no pixel shader does: `s_setprio` (all 244, covered), `v_cvt_f32_i32_e64`,
`v_cmp_le_i32`, `v_max_i32`, `v_med3_i32`, `v_add_co_u32`/`v_add_co_ci_u32`, `v_lshlrev_b64`, `v_cmp_ge_u32` and
`v_sin_f32_e64` (uncovered), plus `v_sub_nc_u32`, `v_add_lshl_u32`, `v_ashrrev_i32`, `v_mul_hi_i32`,
`v_lshl_add_u32`, `v_xor_b32` and `global_load_dwordx2/x4` (covered). The report prints the full lists.

## Mapping onto a D3D12 vertex shader

### Model: one HLSL invocation = one console lane = one vertex
A legacy VS wave holds up to 64 vertices, and each lane depends only on its own vertex (no cross-lane operation in any
of the 244). On desktop that is one vertex-shader invocation per lane, with no wave-level state, the same reduction
as the pixel path ([control-flow.md](control-flow.md)).

### NGG passthrough frame: match and drop
RADV wraps an NGG vertex shader in a fixed frame. The report's `ngg_passthrough()` matches it instruction by
instruction:

```
s_barrier
s_and_b32 sT, sW, 0xf000000 ; s_cbranch_scc1 L          ; only wave 0 of the subgroup allocates
s_bfe_u32/s_lshl_b32 12/s_bfe_u32/s_or_b32 m0 ; s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)   ; prims, verts from gs_tg_info
L: two regions, either order:
  prim:   s_lshl_b32 sC, sW, 8         ; s_bfe_u64 exec, -1, sC ; s_cbranch_execz ; exp prim vP, off, off, off done
  vertex: s_pack_ll_b32_b16 sC, 0, sW  ; s_bfe_u64 exec, -1, sC ; s_cbranch_execz ; <vertex body>
s_endpgm
```

In all 244, `sW` (merged_wave_info) is s3, gs_tg_info is s2 and the payload `vP` is v0. The prim region exports
the primitive the hardware assembled, unchanged. On desktop the input assembler and rasterizer build the same
primitive, so the translator **drops the frame and lowers the vertex body as a legacy VS**, with the entry roles
remapped (v5 vertex id, v8 instance id). The match is refused, naming the first difference, when:
- an instruction differs from the frame, a region repeats, or a count does not come from merged_wave_info;
- the prim region contains anything but one `exp prim` of an entry VGPR, or the body writes that VGPR before a
  primitive export that comes last;
- the body reads the entry value of merged_wave_info, gs_tg_info or m0 (it may reuse those registers after writing
  them);
- the body contains a lane-cooperative or frame operation (`ds_*`, `v_mbcnt*`, `s_bcnt*`, readlane, writelane,
  permlane, `s_ff1`, DPP, SDWA, `s_barrier`, `s_sendmsg`, a second `exp prim`).

**Culling is refused.** A culling NGG shader computes positions early, votes across the wave, compacts the surviving
vertices through LDS and exports a computed payload. A lane cannot reproduce that alone. Dropping culling would give
the same render-target output (the desktop rasterizer discards the same back-facing, zero-area and off-screen
primitives, provided its cull state matches). But it would change pipeline statistics and any side effects, and the
culling region would first have to be recognized whole. That belongs in a later card with its own evidence. A
title's compiler may also emit a different frame from RADV's. That frame has to be read from the title's own code
and matched separately; this matcher refuses it.

### Inputs
- **Vertex and instance id.** Declare `uint vid : SV_VertexID` and `uint iid : SV_InstanceID` and put them in the
  entry-VGPR roles above. **Do not depend on how D3D12 folds `BaseVertexLocation`/`StartInstanceLocation` into the
  system values** (not checked here). The runtime issues the desktop draw with base vertex and start instance 0 and
  passes the console's base-vertex and start-instance user-SGPR values as root constants. The program's own
  `v_add_nc_u32 v, sBase, vid` then computes exactly what it computes on the console. Index buffers move to the
  desktop index buffer unchanged, because the console VGPR id is the fetched index.
- **Vertex fetch stays a buffer load through the runtime V#**, not a D3D12 input layout. `buffer_load_dword*` with
  `idxen` lowers to the existing `buffer_load32(rsrc, soffset, voffset, inst_offset, index, dword)` over
  `title_memory`/`TitleLookup`. Stride scaling, `num_records` and `OOB_SELECT` range checks and the 64-bit address
  sum are already implemented and drawn for the pixel stage (docs/experiments.md). An input layout would hand
  out-of-range reads, stride and format conversion to the desktop IA, which is not bit-exact with the console. It
  stays a later optimization, for when a V# is static and its format maps 1:1 onto DXGI. The input-assembler state
  holds no vertex buffers, only the index buffer.
- **Descriptor pointers and user data.** The pixel path's entry contract (`--texture-sgpr`, `buffer_descriptors`
  mapping a descriptor-table byte offset to constant words) becomes a per-shader **user-SGPR map**: for each entry
  SGPR, its role (descriptor-list pointer with the high word it is combined with, constant-buffer pointer, base
  vertex, start instance, inline data word, inline V# word). RADV's map comes from its user-data layout; a title's
  comes from its shader metadata, read the same way the pixel tools read theirs. Inline data words become root
  constants (`uint`, never `float`; see the raw-word finding in docs/experiments.md). `s_load_dwordx8`/`x16` of
  descriptor-table entries (two or four V#s in one load) must be accepted. The pixel lowering handles `x4` for V#s.
- **Typed fetch** (`buffer_load_format_*`, `tbuffer_load_format_*`): the corpus has none. It is lowered as raw dword
  loads plus explicit unpacking chosen by the runtime V#'s format field (gfx10 word 3), with every format and
  out-of-range rule taken from the ISA text and drawn. To see what RADV emits for 8- and 16-bit formats, rebuild the
  corpus with other `vin` formats in `pipe.c`.
- **Embedded constants** (`s_getpc_b64` plus an offset): the data follows `s_endpgm` in the code object. The ISA
  dumps do not print it, and `native_program()` cuts the image at the terminator. The translator needs the bytes
  after the program (bounded and checked) and resolves the getpc base to a constant table at translation time.

### Outputs
- `exp pos0` becomes `SV_Position` (float4). `done` and `vm` have no desktop meaning. pos0 must be exported exactly
  once on every path.
- `exp paramN` becomes `TEXCOORDN` (float4). A channel left `off` is written as 0, and tests treat it as undefined.
  Words are stored through `asfloat(word)`. The draw check in V-1 has to confirm that a NaN payload survives the
  output store bit for bit on both backends. If it does not, raw words that reach an export become `uint`
  `nointerpolation` outputs.
- Output order follows what `pixel_aot.py` declares for its inputs: `TEXCOORD0`, `SV_Position`, then `TEXCOORD1..N`.
  This keeps D3D12 register linkage with translated pixel shaders. Pairing assumes the identity param-to-attribute
  mapping (pixel attr N = TEXCOORD N). A title whose `SPI_PS_INPUT_CNTL` remaps parameters needs that state applied at
  link time.
- `exp pos1..3` (point size, layer, viewport index, clip or cull distances) depends on `PA_CL_VS_OUT_CNTL` and the
  position-export format. Without that register state, refuse. With it, map to `SV_ClipDistance`,
  `SV_CullDistance`, `SV_RenderTargetArrayIndex` and `SV_ViewportArrayIndex`. Point size has no D3D12 equivalent, so
  it is refused unless the draw is not a point list.
- The root signature for vertex draws uses `SHADER_VISIBILITY_ALL` (or a vertex copy) for `title_ranges`,
  `title_memory`, `TitleCount` and the constants, plus root constants for the user-SGPR map.

### Reuse, and the per-family split
The ALU, SMEM, buffer and global-load, waitcnt and control-flow lowerings do not depend on the stage. The vertex
translator (`tools/vertex_aot.py`) should call the per-family modules that the pixel split is producing. It provides
its own entry contract (roles of entry registers) and its own terminator (pos and param exports instead of `exp mrt`)
and does not fork the lowerings. A form covered once then counts for both stages, as `form_coverage.py` already
assumes.

## Testing bit-exactly
The pixel draws read back render-target bytes. A vertex shader's results are positions and parameters per vertex, so
the check captures them before the rasterizer:

1. **Stream output (primary).** Draw a point list of N vertices with the translated VS and no pixel shader, and use
   a `D3D12_STREAM_OUTPUT_DESC` that captures `SV_Position` and every `TEXCOORDn` into a buffer. Read it back and
   compare each vertex's 4 x (1 + params) dwords exactly against a Python reference. Capturing leaves the translated
   shader unchanged (no extra UAV writes), works on WARP, and gives one record per vertex in draw order. Each draw
   varies the vertex count, the base vertex and start instance passed as root constants, the V# words in title
   memory (stride, `num_records` boundaries, `OOB_SELECT`) and the constant sets.
2. **Raster pairing (secondary).** Draw a known triangle mesh with the translated VS and a fixed pass-through pixel
   shader that writes `nointerpolation` parameters (provoking vertex) as `R32G32B32A32_UINT` and `SV_Position.xy`,
   at pixels whose coverage the reference predicts with margins. This checks the signature linkage with
   `pixel_aot.py`'s inputs and that `SV_Position` reaches the rasterizer as clip space.
3. **References.** Each family writes its references in Python integers and exact fractions, as the pixel families
   do. For straight-line V-1 programs, a small gfx10 VALU/SALU interpreter covering the forms in use (unfused
   `v_mad`/`v_mac` with flushing, as the existing helper does) gives references for corpus replays. The corpus ISA
   carries encodings, so selected corpus vertex shaders can be reassembled with llvm-mc 15 and replayed on synthetic
   vertex buffers.
4. **Controls.** Each card has wrong references that must report a mismatch: base vertex ignored, instance id in
   place of the vertex id, stride ignored, the dword at `num_records` read, parameters swapped, an `off` channel
   checked, the NGG frame kept or the payload changed. It also has refusals that must raise: a culling frame, a frame
   register read at entry, an unknown entry VGPR, `pos1` without state, a typed load before its card. The LLVM round
   trip covers the same programs. Results are reported per adapter (RTX 4070 Ti and WARP), as for the pixel stage.

## Cards
Each card's unlock count is the number of corpus vertex shaders whose first translatable card it is
(`tools/vertex_corpus_report.py`, "First card that translates the shader"). Counts are cumulative over the legacy
build. The NGG build gives the same numbers with V-1 shaders moving to V-2.

- **V-1: legacy VS, straight-line, vertex id, raw indexed fetch, pos0 and params (123 shaders, 123 total).** Adds
  the entry contract (vertex id, base vertex, descriptor-list pointer with its high word, constant-buffer pointer),
  `s_load_dwordx8`/`x16` of V#s, the export lowering and signature order, stream-output readback and the draw
  harness, and the NaN-through-export check.
- **V-2: NGG passthrough frame (the same 123 again, in NGG form).** Adds the frame matcher in the translator (the one
  in the report is the reference), the remapped entry roles and the refusals. A title's own frame is matched in its
  own card.
- **V-3: instance id, inline user data, SSBO and global loads, extra position exports (+44, 167 total).** Instance
  id and start instance as root constants, the user-SGPR map with inline data words and inline V#s (37 of the 44 need
  only this), `offen` and `global_load` in the vertex stage (already lowered for the pixel stage), and `pos1..3` with
  `PA_CL_VS_OUT_CNTL` state. Typed fetch also belongs here once a corpus build exercises it.
- **V-4: forms (+60, 227 total).** `v_cvt_f32_i32` (e32/e64) first, then `s_lshl_b32`, `v_sin_f32_e64`,
  `v_cvt_f32_u32`, `v_cvt_i32_f32`, `v_rndne_f32`, `v_sin`/`v_cos_f32`, the i32 and u32 compares, `v_add_co_*`,
  `v_lshlrev_b64`, `v_max_i32`, `v_med3_i32`, `v_madmk_f32` and `v_madak_f32`. These are stage-neutral forms. Landing
  them as pixel form families with the existing draw harness covers them for vertex too. 45 of the 60 need nothing
  structural beyond V-1, and 15 also need V-3.
- **V-5: embedded constants, image sampling, control flow (+17, 244 total).** `s_getpc_b64` constant tables (needs
  the bytes after `s_endpgm`), `image_sample_lz` (explicit LOD, legal in a VS), uniform branches through CF-1 and
  divergent ones through CF-2 in the vertex stage.
- **Later, not planned as a card:** NGG culling (recognize the culling region and prove that dropping it leaves
  render targets unchanged on the test meshes), LS/ES-merged vertex shaders with tessellation and geometry, and an IA
  input layout as an optimization.

## Reproduction
```bash
# Forms only: reads docs/coverage/corpus-shaders.tsv and site/status.json from the checkout.
python3 -B tools/vertex_corpus_report.py
# Structure: one --isa per compile (DIR/vertex/*.s). The NGG compile is build_corpus.py without NONGG=1.
python3 -B tools/vertex_corpus_report.py --isa <isa-main> --isa <isa-ngg> --json out/vertex-corpus.json
python3 -B -I tests/vertex_corpus_report_check.py
```
