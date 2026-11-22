# Compute stage: design

Status: C-1 is implemented (`tools/compute_aot.py`, checked by `tests/compute_aot_check.py` and
`tests/compute_aot_render.cpp`); C-2 to C-8 are proposed. The structure follows [vertex-stage.md](vertex-stage.md):
the instruction lowerings stay in `tools/pixel_aot_ops/forms/` and are shared, and the compute stage adds only its entry
contract, its terminator, its refusals and its test harness.

## What the corpus shows
The corpus has 27 compute shaders (10 from Sascha Willems' Vulkan samples, 17 from Khronos Vulkan-Samples; licenses in
[corpus-sources.md](../coverage/corpus-sources.md)). The figures below come from
`python3 -B tools/compute_aot.py survey --isa <isa-main>`, run on the RADV 25.2.8 build of the corpus
(`RADV_FORCE_FAMILY=GFX1013`) with the covered set in `site/status.json` at 077d510. The workgroup sizes come from
the SPIR-V (`spirv-dis`, `OpExecutionMode LocalSize`, or the default of a `LocalSizeId` specialization constant), since
the ISA dump does not print them.

### Entry registers
- **Local ids are unpacked: v0 = x, v1 = y, v2 = z.** 21 shaders read v0 (15 of them also v1); none reads v2 (no
  corpus workgroup has a z size above 1). 6 read no VGPR at entry: their workgroups have one thread (headless,
  binary_demo and the four Vulkan-Samples n-body shaders, whose `LocalSizeId` defaults to 1), so the workgroup id is the
  invocation index. The packed form (x, y, z in bits 0, 10 and 20 of v0) is gfx90a and gfx11; gfx1013 does not use it.
  RADV enables only the components the shader reads (COMPUTE_PGM_RSRC2.TIDIG_COMP_CNT), so an unread VGPR is undefined.
- **Workgroup ids are SGPRs after the user data**, one for each dimension the shader uses: s3 (x only: 10 shaders),
  s3/s4 (6), s4/s5 (3), s5/s6 (2), s7/s8 (4), s8/s9 (1); binary_demo reads none. Before them come the user SGPRs from s2:
  the 32-bit descriptor-set pointer (24 shaders), completed with `s_movk_i32 s(n+1), 0x8000`, which sign-extends to
  RADV's high word 0xffff8000; inline push constants (threshold, the 16-bit arithmetic shaders, update_vbo,
  device_fault, game_of_life_mutate); and a 64-bit pointer to the NumWorkgroups words where `gl_NumWorkGroups` is
  read (cull at s3:s4, both update_vbo shaders). s0 and s1 are never read at entry. When the workgroup id x sits in
  s3, the program first copies it (`s_mov_b32 s0, s3`) and then reuses s3 as the pointer's high word.
- No shader reads m0, vcc or a lane mask at entry except EXEC, which 6 wave64 shaders save before they branch.

### Wave size
3 shaders are wave32 (cull with 16 threads, and the two Vulkan-Samples particle_calculate with 1), 13 are wave64 (all
with at least 64 threads), and 11 name no lane mask at all, so their dump does not show the wave size. The split
matches "wave32 when the workgroup fits in 32 lanes"; this is observed only and was not checked in Mesa. A lowering
that does not depend on the wave size is the goal: every accepted program keeps each lane on its own data, so the
wave size only decides which lane-mask spellings are legal (exec_lo and vcc_lo in wave32, exec and vcc in wave64).

### Memory, LDS, barriers and atomics
- Loads: raw `buffer_load_dword{,x2,x3,x4}` with `offen` (8 shaders) or `off` plus an SGPR soffset (headless and
  the four Vulkan-Samples n-body shaders), through V#s read from the descriptor set by `s_load_dwordx4`, `x8` (two V#s, the
  storage and the uniform buffer) or `x16`. Constants come from `s_buffer_load_dword*`. All are pixel-stage forms.
- Stores: `buffer_store_dword` (7 shaders), `x2` (1), `x3` (2), `x4` (7); `global_store_dword{,x2}` (3, buffer device
  address); `image_store` (12). No sub-dword or typed buffer store.
- LDS: `ds_write_b128` and `ds_read_b128` in the three particle_calculate shaders. Only the Sascha Willems one has
  `s_barrier` (two): it has 256 threads. The two Vulkan-Samples ones have one thread per workgroup, and the compiler
  emits no barrier.
- Atomics: `buffer_atomic_add` twice in cull, once as a wave-aggregated add (`s_bcnt1_i32_b32 s0, exec_lo`, the first
  active lane elected by `s_ff1_i32_b32` and `s_and_saveexec_b32`, one atomic for the wave).
- Cross-lane: `v_readfirstlane_b32` in headless (of a value loaded from a uniform address), the Sascha Willems
  particle_calculate (of LDS words read at a uniform address) and generate_shading_rate (of values computed from
  constants). No DPP, `v_mbcnt`, `v_permlane`, `ds_swizzle` or `ds_bpermute`. The SDWA moves of the 16-bit shaders are
  per lane.
- Control flow: 17 shaders branch; 7 of them use `s_and_saveexec_b64/b32` or `v_cmpx_*`, the others write EXEC with
  `s_and`/`s_andn2`/`s_nor` on it or branch on SCC and VCC only.

### Per shader
Missing: the forms not covered in `site/status.json` (the `buffer_store_dword*` forms are added by C-1). Card: the
first card after which the shader translates (see [Cards](#cards)).

| Shader | Instr. | Workgroup | Wave | Entry VGPRs | Group-id SGPRs | LDS, barrier | Stores | Missing forms | Card |
|---|---|---|---|---|---|---|---|---|---|
| sascha computecloth/cloth | 496 | 10x10 | 64 | v0 v1 | s4 s5 | | buffer x3, x4 | s_and_saveexec_b64 s_cbranch_execz v_cmpx_{ge,gt}_u32 v_cmpx_lt_f32 v_cmpx_ne_i32 v_lshrrev_b64 | C-4 |
| sascha computecullandlod/cull | 178 | 16 | 32 | v0 | s5 s6 | | buffer, atomic add | buffer_atomic_add s_and_saveexec_b32 s_cbranch_execz v_cmpx_lt_f32_e64 v_cmpx_ngt_f32 | C-8 |
| sascha computeheadless/headless | 27 | 1 | ? | | s3 | | buffer | v_readfirstlane_b32 | C-7 |
| sascha computenbody/particle_calculate | 95 | 256 | 64 | v0 | s3 | ds b128, 2 barriers | buffer, x4 | ds_read_b128 ds_write_b128 s_barrier s_cbranch_execz v_cmpx_gt_u32 v_cmpx_lt_f32 v_lshrrev_b64 v_readfirstlane_b32 | C-7 |
| sascha computenbody/particle_integrate | 17 | 256 | ? | v0 | s3 | | buffer x4 | | C-1 |
| sascha computeparticles/particle | 67 | 256 | 64 | v0 | s3 | | buffer, x2, x3 | s_and_saveexec_b64 s_cbranch_execz v_cmpx_gt_u32 v_cmpx_lt_f32 | C-3 |
| sascha computeraytracing/raytracing | 815 | 16x16 | 64 | v0 v1 | s3 s4 | | image | image_store s_and_saveexec_b64 s_cbranch_execz v_cmpx_{eq,ne}_i32 v_cmpx_neq_f32 v_lshrrev_b64 v_swap_b32 | C-4 |
| sascha computeshader/edgedetect | 62 | 16x16 | ? | v0 v1 | s3 s4 | | image | image_store | C-2 |
| sascha computeshader/emboss | 31 | 16x16 | ? | v0 v1 | s3 s4 | | image | image_store | C-2 |
| sascha computeshader/sharpen | 54 | 16x16 | ? | v0 v1 | s3 s4 | | image | image_store | C-2 |
| vks 16bit_arithmetic/compute_buffer | 104 | 8x8 | ? | v0 v1 | s7 s8 | | image | image_store v_lshrrev_b64 | C-4 |
| vks 16bit_arithmetic/compute_buffer_fp16 | 92 | 8x8 | ? | v0 v1 | s4 s5 | | image | image_store v_pack_b32_f16 v_pk_fmac_f16 | C-4 |
| vks 16bit_arithmetic/compute_buffer_fp16_fallback | 83 | 8x8 | ? | v0 v1 | s7 s8 | | image | image_store v_pack_b32_f16 v_pk_fmac_f16 | C-4 |
| vks async_compute/threshold | 32 | 8x8 | 64 | v0 v1 | s7 s8 | | image | image_store s_cbranch_execz | C-3 |
| vks buffer_device_address/update_vbo | 66 | 8x8 | 64 | v0 v1 | s7 s8 | | global x2 | global_store_dwordx2 v_add_co_ci_u32 v_cos_f32 v_lshlrev_b64 v_sin_f32 v_sin_f32_e64 | C-5 |
| vks compute_nbody/particle_calculate | 71 | 1 | 32 | | s3 | ds b128 | buffer, x4 | ds_read_b128 ds_write_b128 s_cbranch_vccz v_lshrrev_b64 | C-6 |
| vks compute_nbody/particle_integrate | 18 | 1 | ? | | s3 | | buffer x4 | | C-1 |
| vks device_fault/update_vbo | 67 | 8x8 | 64 | v0 v1 | s8 s9 | | global x2 | global_store_dwordx2 v_add_co_ci_u32 v_cos_f32 v_lshlrev_b64 v_sin_f32 v_sin_f32_e64 | C-5 |
| vks fragment_shading_rate_dynamic/generate_shading_rate | 95 | 8x8 | 64 | v0 v1 | s3 s4 | | image | image_store s_cbranch_execz v_lshrrev_b64 v_readfirstlane_b32 | C-7 |
| vks multi_draw_indirect/cull | 127 | 64 | 64 | v0 | s3 | | buffer | s_and_saveexec_b64 s_cbranch_execz v_cmpx_gt_u32 v_cmpx_lt_f32_e64 | C-3 |
| vks multi_draw_indirect/cull_address | 137 | 64 | 64 | v0 | s3 | | global | global_store_dword s_and_saveexec_b64 s_cbranch_execz v_add_co_ci_u32 v_cmpx_gt_u32 v_cmpx_lt_f32_e64 v_lshlrev_b64 | C-5 |
| vks pipeline_binary/binary_demo | 1 | 1 | ? | | | | | | C-1 |
| vks synchronization_2/particle_calculate | 71 | 1 | 32 | | s3 | ds b128 | buffer, x4 | ds_read_b128 ds_write_b128 s_cbranch_vccz v_lshrrev_b64 | C-6 |
| vks synchronization_2/particle_integrate | 18 | 1 | ? | | s3 | | buffer x4 | | C-1 |
| vks timeline_semaphore/game_of_life_init | 33 | 8x8 | 64 | v0 v1 | s3 s4 | | image | image_store | C-2 |
| vks timeline_semaphore/game_of_life_mutate | 18 | 8x8 | 64 | v0 v1 | s5 s6 | | image | image_store | C-2 |
| vks timeline_semaphore/game_of_life_update | 178 | 8x8 | 64 | v0 v1 | s4 s5 | | image | image_store s_cbranch_execz | C-3 |

"?" is a dump without a lane-mask operand. "vks" is Khronos Vulkan-Samples (`vksamples__` in the dump names); a path
that the dump name spells with `glsl__` is shortened.

## Mapping onto a D3D12 compute shader

### Model: one HLSL thread = one console lane = one invocation
A console workgroup is one or more waves of 32 or 64 lanes; each lane runs one invocation. The translation is a
D3D12 compute shader whose `[numthreads(x, y, z)]` is the console workgroup size, dispatched with the same group
counts. Each HLSL thread computes what its console lane computes, from its own registers, with no wave-level state.
This holds as long as no lane reads another lane's registers and no result depends on the number of lanes in a wave
(see [Refused](#refused-cross-lane-and-wave-size-dependent)). The lanes of a partial last wave (100 threads in two
wave64 waves) are disabled at entry on the console and absent on desktop, which is the same.

- **Workgroup size.** RADV takes it from the SPIR-V; a title's comes from its pipeline state (COMPUTE_NUM_THREAD_X,
  Y and Z). The translator gets it as an input (`--numthreads`) and refuses what D3D12 cannot declare (x or y above
  1024, z above 64, more than 1024 threads).
- **SV_GroupID** fills the workgroup-id SGPRs, **SV_GroupThreadID** fills v0, v1 and v2 (as many as the program's
  TIDIG_COMP_CNT enables, `--local-ids`). The console has no dispatch-thread id: the program computes
  `group * size + local` itself, and the translation keeps that arithmetic. A base group offset
  (`vkCmdDispatchBase`, or a title's equivalent) is not in the corpus; the runtime would pass it as a user-data word
  and dispatch from zero, as V-1 does for base vertex.
- **Entry-SGPR map**, as in V-1: each entry SGPR the program reads gets a role, `descriptors` (the descriptor-list
  pointer, whose high word the program completes with RADV's 0xffff8000), `group_id.x|y|z`, or `user:N` (the inline
  user-data word N of the constant words, for push constants). Any other entry register is unset and a read of it
  is refused. The NumWorkgroups pointer becomes a title-memory address whose three words the runtime writes (C-3,
  where the corpus first needs it).
- **Wave size** is an input (`--wave`) used only to refuse a program that spells lane masks of the other width, or
  writes a 64-bit compare mask in wave32 (or a 32-bit one in wave64).

### Memory
- **Loads** are the pixel stage's: `buffer_load_dword*` through `buffer_load32` with the V# range rules of
  `hlsl.MEMORY_HELPERS`, the V# words taken from the constant words (`--buffer-descriptor OFFSET=WORD`) and the
  uniform buffer's words read by `s_buffer_load_dword*` from the same constant words (`--constant-descriptor`).
- **Title memory is read-write**: `RWByteAddressBuffer title_memory[8] : register(u0, space1)`, with the same
  `TitleLookup` over `title_ranges` (t2) and the range count (b1) as the pixel stage. The loads use the same helpers,
  which read a UAV as they read an SRV.
- **UAV stores** (`tools/pixel_aot_ops/forms/stores.py`, shared with the pixel stage): `buffer_store_dword{,x2,x3,x4}` compute each dword's
  address as a load does, apply the OOB_SELECT rule to each dword on its own and drop a dword that fails it; a dword
  that misses title memory is dropped too (a load reads it as zero). glc, slc and dlc change no result here.
  Stores of one lane land in program order. Two lanes or threads that store to one address in the same dispatch
  race on the console and on desktop alike; the translation does not order them, and no test depends on the winner.
- **Order of loads and stores**: C-1 refuses a memory load after a store in the same program (the console orders them
  through `s_waitcnt vscnt` and the cache-invalidate instructions, which C-1 does not model). C-3 lifts this for one
  lane's own addresses (a D3D12 thread observes its own UAV writes in program order); visibility between threads needs
  `DeviceMemoryBarrier`, mapped from `buffer_gl0_inv`/`buffer_gl1_inv` with `s_waitcnt_vscnt`, in the card that first
  needs it.
- **Images** (C-2): `image_load` and `image_store` with `dim:SQ_RSRC_IMG_2D` become `RWTexture2D<float4>` (or
  `<uint4>`) reads and writes, the format taken from the T# (word 1, DATA_FORMAT and NUM_FORMAT) as the pixel stage
  does for sampled images. A typed UAV store converts float to UNORM: D3D12 and RDNA 2 both round to nearest, but the
  tie and NaN rules must be measured on each adapter before a draw relies on them. A typed UAV load of
  R8G8B8A8_UNORM needs `TypedUAVLoadAdditionalFormats`; without it the case is a capability skip (77).
- **NaN payloads.** A float result reaches memory through `asuint` of an HLSL float. C-1 tests finite values only;
  C-4 checks whether a NaN result keeps its payload on both backends, as the pixel stage did for exports.

### groupshared and barriers (C-6)
- LDS becomes `groupshared uint lds[LDS_SIZE / 4]`, the size from COMPUTE_PGM_RSRC2.LDS_SIZE (a title's shader
  metadata; RADV's comes from the shader info). `ds_read_b32..b128` and `ds_write_b32..b128` with their offset fields
  index it by byte address / 4. An address that is not a multiple of the access size, or past the allocation, is
  refused when it is a translation-time constant and checked at run time otherwise (reads 0, write dropped, the RDNA
  out-of-range rule, to be confirmed by a draw).
- `s_barrier` becomes `GroupMemoryBarrierWithGroupSync()`. HLSL requires it in uniform control flow, so it is accepted
  only where the CF-1 walk shows every lane of the workgroup reaches it (`st.ex == "true"` and no divergent branch
  around it); otherwise it is refused.
- **LDS without a barrier.** A compiler may drop `s_barrier` when the workgroup fits one wave, because the lanes of a
  wave run in lockstep. On desktop a workgroup can span several waves (WARP and other adapters report other lane
  counts), so the translation cannot rely on lockstep. Such a program is accepted only when its workgroup has one
  thread (the two Vulkan-Samples particle_calculate shaders) and refused otherwise; inserting barriers is a later
  option with its own evidence.

## Refused: cross-lane and wave-size dependent
A desktop wave has a different size (WARP, NVIDIA 32, AMD 32 or 64) and a different lane order, so anything that
reads another lane or counts lanes cannot be computed by one thread. C-1 refuses, with the card that would accept it:

- **Lane reads**: `v_readfirstlane_b32`, `v_readlane_b32`, `v_writelane_b32` (C-7, only for a value the translator
  proves wave-uniform: one built from SGPRs, constants, the group id and loads from uniform addresses; the result is
  then the value itself, with no wave intrinsic). Any other use stays refused.
- **Lane counts and indices**: `v_mbcnt_*`, `s_bcnt1`, `s_ff1`, `s_flbit` of EXEC, and a lane mask read as a number
  (the register model refuses a saved mask used as data). C-8 recognizes the wave-aggregated atomic idiom of cull as a
  whole (the count of active lanes, one elected lane, one atomic for the wave; with a returned value, the base read back
  to every lane plus the lane's rank) and lowers it to one `InterlockedAdd` per thread. The console's result (which lane gets which slot) already depends on wave scheduling,
  so its test compares the set of slots and the final counter, not the order.
- **Permutations**: DPP (quad DPP is a pixel-stage lowering: compute lanes are not 2x2 pixel quads, so the stage hook
  refuses it), `v_permlane*`, `v_movrel*`, `ds_swizzle_b32`, `ds_permute_b32`, `ds_bpermute_b32` (no card).
- **Pixel-only operations**: `s_wqm_b64`, attribute interpolation, color export, implicit-LOD sampling (no derivatives
  in a compute thread; explicit-LOD `image_sample_lz` is C-2).
- **Wave-size spellings** of the other width, as above.
- **Atomics** (`buffer_atomic_*`, `global_atomic_*`) are C-8. Note for their test: the in-box WARP of Windows 10
  applies an atomic on a descriptor-array UAV four times (`tests/gpu_alias_lookup.cpp`), so that check must report a
  WARP result separately.
- **Control flow** (labels, `s_branch`, `s_cbranch_*`, `s_getpc_b64`) is C-3; a store while the lane may be inactive is
  C-3 too.

## Testing bit-exactly
The pixel draws read back a render target. A compute shader's results are its memory writes, so the check reads back
title memory after the dispatch:

1. **Dispatch and UAV readback.** `offscreen_check <adapter> --check-compute-case <cso> <case>`
   (`tests/compute_aot_render.cpp`) reads a case file: the group counts, the 64 constant words (b0), the title ranges
   and the contents of each title-memory slot before the dispatch, and the contents the reference expects after it.
   It uploads the slots into raw UAV buffers, dispatches the translated shader with the root signature the HLSL
   embeds, copies every slot back and compares every word, the ones the program should leave alone included, so a
   stray or dropped write shows. The first difference prints `compute_mismatch slot= byte= expected= actual=` and
   exits 1; a malformed case exits 2; no hardware adapter exits 77 (a skip).
2. **Adapters.** Each family runs as `compute_aot_<family>_warp` and `compute_aot_<family>_hardware` (RTX 4070 Ti on
   the reference PC), reported per adapter like the pixel stage.
3. **References** are Python integers and exact fractions: binary32 round-to-nearest-even with gradual underflow, the
   unfused, denormal-flushing multiply-add of `v_mac_f32` (`hlsl.mad32`), and the V# rules of the load checks applied
   to stores.
4. **Wrong references.** Each family has plausible wrong lowerings that must make the same dispatch report a mismatch.
   `controls` first checks without a GPU that each one differs from the right reference in some case.
5. **Refusals** (`compute_aot_controls`): each must raise. LDS, barriers, lane reads, lane counts of EXEC, `v_mbcnt`,
   permutations, atomics, images, global and flat stores, sub-dword and typed stores, labels and branches,
   `s_getpc_b64`, messages, whole-quad mode, DPP, interpolation and export in the compute stage; store modifiers and
   operands (tfe, lds, `offset:4096`, a missing or doubled address mode, misaligned or untracked V# registers, data
   width mismatches, unset data); store data still being loaded; a load after a store; a store while the lane may be
   inactive; an entry register without a role; a descriptor pointer with another high word or an undeclared table
   offset; lane masks of the other wave size; invalid contracts (workgroup size, wave size, local-id count, packed
   ids, repeated or unknown roles, overlapping descriptor or user-data words). The pixel stage keeps refusing every
   store.
6. **LLVM round trip.** `compute_aot_check.py binary` assembles every draw program with llvm-mc 15 (wave32 programs with
   `+wavefrontsize32`), disassembles it and checks that it lowers to the same HLSL.
7. **Corpus programs.** `tools/compute_aot.py translate` lowers the three corpus particle_integrate dumps and
   binary_demo with the contracts read from them (s2 descriptors, s3 group id x, one local id, the uniform buffer at
   descriptor 0x10). The draws use programs of the same two shapes written for the tests, so that the tests carry no
   compiled corpus code.

C-1's families:
- `ids`: a 4x2x2 workgroup over 3x2x2 groups stores each thread's packed group id, packed local id and flattened index
  through a V# whose range crosses 4 GiB. Wrong references: group id ignored, group x and y swapped, local x and y
  swapped, local z ignored, SV_DispatchThreadID in place of SV_GroupThreadID.
- `store`: one thread, every V# input a runtime word: offen, idxen, both and neither, soffset and the instruction
  offset; OOB_SELECT 0 to 3 at the last dword inside and the first outside each limit; x2, x3 and x4 windows across
  `num_records`; a later store over an earlier one; 4 GiB carries; a 64-bit stride product. Wrong references: soffset,
  stride, instruction offset or index ignored; no range check; `index > records`; the ISA table's `offset > stride`;
  the offset checked in mode 1; the index checked in mode 2; `offset <= records`; dwords reversed; a whole store dropped
  for one bad dword; stores in reverse order; 32-bit halves summed without carry; a 32-bit stride product.
- `integrate`: the corpus's two particle-integration shapes (64 threads with a voffset, wave64; one thread with the
  index in soffset and dt scaled by a literal, wave32) over 256 particles. Wrong references: fused multiply-add,
  denormals kept, group id ignored, local id ignored, dt from the wrong constant word, the velocity offset ignored.

## Cards
Counts are corpus shaders whose first translatable card it is (`tools/compute_aot.py survey`, "first_card"),
cumulative over the 27.

- **C-1: straight-line compute, thread ids, buffer loads, buffer stores (4, total 4).** The entry contract, the
  read-write title memory, `buffer_store_dword{,x2,x3,x4}`, the dispatch harness and the refusals. Unlocks
  sascha computenbody/particle_integrate, vks compute_nbody/particle_integrate, vks synchronization_2/particle_integrate
  and vks pipeline_binary/binary_demo.
- **C-2: images in the compute stage (+5, total 9).** `image_load`/`image_store` on 2D UAVs and `image_sample_lz`
  (explicit LOD) in compute, with the format conversions measured per adapter. Unlocks edgedetect, emboss, sharpen,
  game_of_life_init and game_of_life_mutate.
- **C-3: control flow (+4, total 13).** CF-1 and CF-2 ([control-flow.md](control-flow.md)) in the compute stage:
  `s_and_saveexec_b64/b32`, `s_cbranch_execz`, `v_cmpx_*`, masked stores (`if (ex)` around the store), a load after a
  store in one lane, the NumWorkgroups words. Unlocks sascha computeparticles/particle, multi_draw_indirect/cull,
  async_compute/threshold and game_of_life_update.
- **C-4: stage-neutral forms (+5, total 18).** `v_lshrrev_b64`, `v_swap_b32`, `v_pack_b32_f16`, `v_pk_fmac_f16`, and the
  NaN-through-store check. Landed as pixel form families with the pixel draws, they count for compute too. Unlocks
  cloth, raytracing and the three 16-bit arithmetic shaders.
- **C-5: global stores (+3, total 21).** `global_store_dword{,x2}` through `title_load32`'s lookup, plus
  `v_add_co_ci_u32`, `v_lshlrev_b64`, `v_sin_f32` and `v_cos_f32` (forms whose exactness must be measured: `v_sin_f32`
  is an approximation on RDNA 2, so its reference is the hardware's, not libm's). Unlocks both update_vbo shaders and
  multi_draw_indirect/cull_address.
- **C-6: LDS and barriers (+2, total 23).** groupshared, `ds_read/write_b32..b128`, `s_barrier` in uniform flow, the
  one-thread rule for LDS without a barrier, and a draw with several desktop waves per workgroup. Unlocks the two
  Vulkan-Samples particle_calculate shaders.
- **C-7: wave-uniform lane reads (+3, total 26).** `v_readfirstlane_b32` of a provably uniform value. Unlocks headless,
  sascha computenbody/particle_calculate and generate_shading_rate.
- **C-8: atomics and the wave-aggregated idiom (+1, total 27).** `buffer_atomic_add` with and without return, the
  aggregation idiom, set-based references. Unlocks sascha computecullandlod/cull.
- **Later, not planned as a card:** subgroup operations proper (`WaveActive*`, ballots, shuffles; the glslang test
  compile has them, the corpus does not), which need either a desktop wave of the console's size
  (`WaveSize` in shader model 6.6, where the adapter supports it) or a groupshared emulation, each with its own
  evidence.

## Reproduction
```bash
# Corpus survey: one compile directory with DIR/compute/*.s; the forms are checked against site/status.json.
python3 -B tools/compute_aot.py survey --isa <isa-main> --json out/compute-corpus.json
# A corpus program, with the contract read from its dump.
python3 -B tools/compute_aot.py translate <isa-main>/compute/sascha__computenbody__particle_integrate.comp.s \
    --numthreads 256 1 1 --wave 64 --sgpr s2=descriptors --sgpr s3=group_id.x --local-ids 1 \
    --constant-descriptor 0x10 --buffer-descriptor 0x0=8 --output out/integrate.hlsl
# Checks.
python3 -B tests/compute_aot_check.py controls
python3 -B tests/compute_aot_check.py binary <llvm-mc> <llvm-objcopy> <libLLVM>
ctest --preset dev --no-tests=error -R '^compute_aot_' -V
```
