# Compute stage: design

Status: C-1 to C-4, C-6 and the first part of C-7 are implemented (`tools/compute_aot.py`, checked by
`tests/compute_aot_check.py` and `tests/compute_aot_render.cpp`); C-5, C-8 and the rest of C-7 are proposed. The structure follows [vertex-stage.md](vertex-stage.md):
the instruction lowerings stay in `tools/pixel_aot_ops/forms/` and are shared, and the compute stage adds only its entry
contract, its terminator, its refusals and its test harness. With C-4, 12 of the 27 corpus compute shaders translate
(see [Where C-2 to C-4 stand](#where-c-2-to-c-4-stand)); the projection below was 18. C-7's lane reads add headless
(see [C-7: wave-uniform lane reads](#c-7-wave-uniform-lane-reads)) and descriptor words as data add
game_of_life_update (see [Descriptor words as data](#descriptor-words-as-data)): 14 of 27. Scalar constant loads at a
run-time offset, carried around loops, add 16bit_arithmetic/compute_buffer (see
[Dynamic scalar constant loads](#dynamic-scalar-constant-loads)): 15 of 27. LDS and barriers (C-6) add the three
particle_calculate shaders, the Sascha Willems one with its wave-uniform LDS reads (see
[groupshared and barriers](#groupshared-and-barriers-c-6)): 18 of 27.

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
Implemented in `tools/pixel_aot_ops/forms/lds.py` (compute stage only; the pixel and vertex stages refuse every DS
form and `s_barrier`), with the barrier and wait checks in `tools/compute_aot.py` and the epoch joins in
`control_flow.program`.

- **Model.** LDS is `groupshared uint lds[lds_size / 4]`. `lds_size` is a contract field (`lower_compute(lds_size=...)`):
  the program's LDS allocation in bytes, COMPUTE_PGM_RSRC2.LDS_SIZE times its granule in a title's shader metadata
  (RADV's comes from the shader's shared-variable size; the corpus dumps do not print it, so the corpus run takes it
  from the sample sources: 8 KiB for the Sascha Willems shader, 16 KiB for the two Vulkan-Samples ones). It must be a
  multiple of 16 and at most 32 KiB, D3D12's groupshared limit (gfx10 allows 64 KiB; a larger program is refused).
  A DS form in a program without an allocation is refused.
- **Addresses** are bytes (RDNA 2 ISA guide, 10.4.3 and the DS opcode table in 12.13): ADDR = VGPR + the 16-bit offset
  `{offset1, offset0}`; ds_read2/ds_write2 address their two elements at ADDR + OFFSETn times 4 (b32) or 8 (b64), times
  64 more for the st64 forms. The forms: `ds_read_{b32,b64,b96,b128,u8,i8,u16,i16}`, `ds_write_{b8,b16,b32,b64,b96,b128}`,
  `ds_read2{,st64}_{b32,b64}`, `ds_write2{,st64}_{b32,b64}` (element 0 written first, so with equal offsets element 1
  stays) and the atomics without return `ds_{add,sub}_u32`, `ds_{min,max}_{u32,i32}`, `ds_{and,or,xor}_b32`
  (`InterlockedAdd`, `InterlockedMin` and so on on the groupshared word; the signed min and max as a compare-exchange
  loop, since the array is unsigned). Sub-dword writes are an `InterlockedAnd`/`InterlockedOr` pair on their dword, so
  threads writing other bytes of it keep theirs.
- **Alignment.** Every access must be naturally aligned (2 for a half, 4 for a dword, 8 for b64, 16 for b96 and b128),
  provably at translation time from the address expression (the known trailing zero bits of shifts, products,
  constants and of join variables whose every assignment has them, plus the offset field). An unaligned LDS access
  faults or not, and reads which bytes, by SH_MEM_CONFIG's alignment mode, which a program cannot see: it is refused.
- **Range.** The guide (3.6.1) has an out-of-range LDS access discard its write and read zero; it states the bound as
  "addr > MIN(lds_size, m0)", while 10.4 says M0 is not used by the indexed LDS forms on RDNA 2, so the bound is the
  allocation. Each dword is checked (`lds_load32`, `lds_store32`): with natural alignment and an allocation that is a
  multiple of 16, an element is wholly inside or wholly outside, so the guide's per-access rule and a per-dword check
  agree, and an address equal to the allocation's size is outside it (`addr >= lds_size`; the guide's `>` cannot mean
  that the dword after the allocation is readable). An access at a translation-time constant address outside the
  allocation is refused. An address sum that wraps 32 bits is treated as outside; the guide does not say what the
  hardware does there (its "addr < 0" suggests a signed check) and no draw relies on it.
- **Ordering between threads.** A console workgroup that fits one wave runs in lockstep and its compiler may drop
  barriers (the Vulkan-Samples shaders with one-thread workgroups have none); a desktop workgroup may span several
  waves. The walk keeps, on every path, the LDS accesses since the last barrier (`st.lds_epoch`): an if joins its arms'
  sets, a skipped region joins the set before it, and a loop's header holds the entry's set and every back edge's (one
  dry run reaches that set, since a path's accesses after the header do not depend on it). An access that may conflict
  with one of them, or with itself in another thread, is refused. Two accesses do not conflict when both read, both
  are the same atomic operation, or both are private: the address is S times the flattened local id plus a constant,
  and the windows of the pair at that stride never meet for two different threads of the group. A one-thread group has
  nothing to conflict with.
- **Inactive lanes.** A write or atomic while the lane may be inactive is emitted under `if (ex)`. A read is emitted at
  the address an active lane computes (`lanes.active_value`), so an inactive thread reads where the active ones do and
  its result is masked as any VGPR write is.
- **Wait counts.** A ds_read result is outstanding until `s_waitcnt lgkmcnt(0)` (in `st.pending` beside the scalar
  loads; a nonzero lgkmcnt completes nothing); any instruction that names the register before that wait is refused.
- **Uniform LDS reads.** A read at an address that the uniformity lattice shows workgroup-uniform is shared, so no write
  is in its epoch and every thread reads the same word, which is everything written before the barrier that opened the
  epoch. Its result is a root of the lattice (`compute_aot.uniform_roots`, repeated while a read word feeds another
  read's address), so `v_readfirstlane_b32` of it is lowered (C-7): the Sascha Willems particle_calculate.
- **`s_barrier`** becomes `GroupMemoryBarrierWithGroupSync()`, which every thread of the group must reach: each
  enclosing if's condition and each break condition of an enclosing loop must be in the lattice
  (`compute_aot.check_barriers`; a loop with a lane-local exit is refused). A wave whose lanes are all inactive in a
  region (`s_cbranch_execz`) skips it and so its barriers, while every desktop thread runs them; the other waves'
  barriers still pair as on desktop when that region holds every barrier of the program and is in no loop
  (`compute_aot.check_barrier_skips`), which the Sascha Willems shader's early return is. An `s_barrier` with partial
  EXEC is a whole-wave barrier on the console (a scalar instruction), as on desktop.
- **Loads around the n-body loops** (compute stage only): a loop end whose outstanding vector loads are some of the
  entry's loads (same register values, none of the body's own) may come around the back edge or leave, the header
  keeping the entry's set (a superset of the loads in flight, in issue order); and the arms of a uniform branch that
  leave different loads outstanding join with every load outstanding on either path counted as the newest. A
  `s_cbranch_vccz` in a one-thread group branches on its own compare (a wave of one lane), so the compare need not be
  in the lattice.
- **Refused:** GDS, `ds_swizzle_b32`, `ds_permute_b32` and `ds_bpermute_b32` (they read other lanes), `ds_append`,
  `ds_consume`, `ds_ordered_count` and the GWS forms, the returning atomics and every other DS form.

Draw family `lds` (`tests/compute_aot_check.py`), dispatched through `offscreen_check --check-compute-batch` (one
renderer launch per program, each case and wrong reference reported as `case=N status=pass|mismatch|error`, as
`--check-pixel-batch` does). Program A: 256 threads (four wave64 waves, several desktop waves on every adapter), two
groups; each thread writes its word to A[t] and a marker to B[t] at computed addresses, a barrier, B[t] rewritten through
the offset field, a barrier, and the partner t' = 255 - t's B[t'] and A[t'] read, with A[t' + 1] and A[t' + 64] by
ds_read2_b32. Wrong references: the second barrier removed (the partner's old B word), the offset field ignored, the
read2 element stride 8 or 1 bytes in place of 4. Program B: 64x2 threads (local ids x and y), private initial words,
then nine barrier-separated epochs of one atomic each (add, sub, min and max unsigned and signed, and, or, xor) on eight
shared words per operation, with signed and unsigned extremes among the data; each thread reads its own word back.
Wrong references: the last barrier removed, the offsets ignored, the signed operations unsigned, sub as add. Program C:
16 one-thread groups (no barrier needed): every ds_write and ds_read width, ds_write_b8/b16 into a written dword and
ds_read_u8/i8/u16/i16 back, ds_write2_b32, ds_write2st64_b64, ds_read2_b64, ds_read2st64_b32 and ds_read2_b32, at
run-time addresses from 0 to past the 1 KiB allocation, at its last dwords and far outside it. Wrong references: the
offset fields ignored, the read2/write2 stride of the other width, st64 ignored, out-of-range addresses wrapped, the
byte written as a dword, no sign extension. Program D: the Sascha Willems n-body shape with integers: a region that
waves with no particle skip, a uniform loop over chunks that fills LDS under a nested mask with a zero-filling else arm,
a barrier, a uniform inner loop reading LDS at a uniform address into SGPRs by v_readfirstlane_b32, a second barrier;
three groups of 128 threads with 300 and 200 particles, so whole waves and part of one are inactive. Wrong references:
the else arm's zeros missing, one chunk only, the inner mask ignored, the position or the second word ignored.
`controls` checks the refusals above (contracts, the pixel stage, each alignment, a constant address outside the
allocation, each race, a barrier on one path of a uniform branch, a barrier in a loop with a lane-local exit and in a
skipped region inside a loop or with a barrier after it, reads before the wait, readfirstlane of a per-thread LDS word,
and the refused DS forms), and that A without its first barrier (private words only) is accepted.

Corpus effect: compute 15 to 18 of 27 (sascha computenbody/particle_calculate, vks compute_nbody and
synchronization_2 particle_calculate); the HLSL of the 15 others, and of every pixel and vertex corpus shader, is
unchanged.

## Refused: cross-lane and wave-size dependent
A desktop wave has a different size (WARP, NVIDIA 32, AMD 32 or 64) and a different lane order, so anything that
reads another lane or counts lanes cannot be computed by one thread. C-1 refuses, with the card that would accept it:

- **Lane reads**: `v_readfirstlane_b32`, `v_readlane_b32`, `v_writelane_b32` (C-7 lowers `v_readfirstlane_b32` of a
  value the translator proves wave-uniform, with no wave intrinsic; see
  [C-7: wave-uniform lane reads](#c-7-wave-uniform-lane-reads)). Any other use stays refused.
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
5. **Refusals** (`compute_aot_controls`): each must raise. LDS without an allocation, lane reads, lane counts of EXEC, `v_mbcnt`,
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

## Where C-2 to C-4 stand
Measured with the corpus dumps and contracts deduced from them (entry SGPRs from the table above, each descriptor
classified by the instruction that reads it): 12 of 27 translate. Newly translated: edgedetect, emboss, sharpen,
game_of_life_init, game_of_life_mutate (C-2), sascha computeparticles/particle, async_compute/threshold (C-3) and cloth
(C-4). Still refused among the shaders the projection gave to C-2 to C-4:
- multi_draw_indirect/cull: nested loops whose inner loop leaves through the outer loop's exit (a two-level break),
  which CF-2e does not structure.
- game_of_life_update: reads T# word 1 as data (`s_bfe_u32` of the image width, imageSize), which needs a descriptor
  word model of the bound image (since added, see [Descriptor words as data](#descriptor-words-as-data)).
- raytracing: two uniform buffers (the constant words are one) and `s_buffer_load` at a runtime SGPR offset.
- the three 16bit_arithmetic shaders: `s_buffer_load` at a runtime SGPR offset (the constant words are read only at
  translation-time offsets); since lowered for compute_buffer, see
  [Dynamic scalar constant loads](#dynamic-scalar-constant-loads).

What the cards added:
- **Contract.** `textures={key: 0|1}` (read images, bound as RGBA8 SRVs tex/tex1, t0/t1), `storage_images={key: (slot,
  format)}` (RWTexture2D at u(8 * slot), space 2, as the pixel stage), `sampler=key` (an S# in the descriptor table;
  the harness's static point sampler with clamp addressing), the role `descriptors.N` for the pointer to descriptor set
  N (a key of set N is `N * 0x100000 + offset`; RADV's push-constant pointer is declared this way, its words mapped onto
  params as a buffer V#'s are), and `descriptor_high`. In the compute stage every `s_load_dword*` from a descriptor
  list goes through `smem.compute_descriptor_load`, which resolves each word to the declared descriptor covering it, so
  `s_load_dwordx16` of two adjacent T#s is one load. A title container can be read with upstream's extraction
  (R0Y00/Xbox2Windows#483: `pixel_aot.container_code(stage=5)`, the PSV0 thread dimensions): `translate --container`.
- **C-2.** `image_load` (also with a non-sequential address), `image_sample_lz`/`_l` and their offset forms, and
  `image_store` to `r8g8b8a8_unorm` (binary32 data, binary16 with d16; channels outside the dmask are written as 0,
  the rule ACO's dmask trimming relies on), besides the raw-word formats of the pixel stage. A texel address that does
  not depend on SV_GroupThreadID is shared by the threads of a group and refused, as in the pixel stage. A UNORM store
  of a value whose scaled form lies near a half, and of a NaN, is not checked by the draws (D3D allows a tolerance
  there); a read-write image (a typed UAV load) is not lowered.
- **C-3.** The pixel stage's control-flow walk (`control_flow.program`), unchanged. While a lane may be inactive, a
  store is emitted under `if (ex)` (`stores.guarded`), loads and the VGPR-only forms that the pixel stage still
  refuses there (conversions, integer min/max/med3, bit-field forms, binary64, `v_cvt_pk_*`, SDWA ones) are lowered
  under the masked-write rule (`registers.inactive`). A load after a store is lowered: one D3D12 thread observes its
  own UAV writes in program order, and a load of another lane's store without a barrier is a race on the console too.
  The NumWorkgroups words were not needed by any shader this card unlocks and are not modelled.
- **C-4.** `v_pk_fmac_f16`, `v_pack_b32_f16`, `s_mov_b32 D, src_scc`, `s_mov_b32 null, K`, `v_cndmask_b32` on the
  uniform mask of `s_cselect_b64 D, -1, 0`, the `neg(N)` spelling of an integer inline constant, and `v_fma_mix*` into
  a register that holds an integer word. The NaN-through-store check is not done (the draws store finite values).

Draw families of C-2 to C-4 (each also runs its wrong references; `controls` checks the refusals):
- `image`: image_load at (x - 1, y) through an NSA address and at (x, y) from two T#s of one x16 load, a dmask 0x7
  UNORM store (alpha written 0), reads outside the image (0); and the threshold shape: two bounds, a skip region with
  image_sample_lz at texel centres (edge clamp) and a UNORM store under the narrowed EXEC. Wrong references: the same
  texel twice, x and y swapped, alpha 1, |x| before the conversion, edge clamping of out-of-range loads; no mask, a
  mask on x only, wrapped addressing, b not inverted, the row scale taken from the column scale.
- `cf`: v_cmpx plus s_cbranch_execz around a nested s_and_saveexec region whose store only even words take, then a
  store, a load of the lane's own word after it and a store again; a uniform SCC loop under a v_cmpx mask through
  v_bfe_u32, v_min_u32 and v_cvt_f32_u32. Wrong references: no mask, inner store unconditional or inverted, the load
  reading the value before the inner store, the index not added; no min, one iteration.
- `neutral`: the C-4 forms above plus v_lshrrev_b64 by 0 to 63 and v_cmp_class_f32 of neg(1). Wrong references: the
  packed fma rounded twice, pack halves swapped, the shift masked to 5 bits, SCC inverted, class bit 3, the mix
  addend not negated.

The harness reads two optional sections after the expected memory ('X2WT' read images, 'X2WI' storage images with
their expected texels, see tests/compute_aot_render.cpp) and binds root parameters 4 (two SRVs) and 5 (32 UAVs).

## C-7: wave-uniform lane reads
`v_readfirstlane_b32 sD, S0` (`tools/pixel_aot_ops/forms/lanes.py`, compute stage only) writes the SGPR with S0 of the
first active lane of the wave, or of lane 0 when EXEC is zero. One HLSL thread is one console lane and there is no
console wave on desktop (a desktop wave has another size and lane order), so the lowering never reads another thread.
It is lowered in two cases and refused in every other:

- **One-thread workgroup** (`numthreads` 1x1x1: headless and the n-body shaders whose `LocalSizeId` defaults to 1). The
  wave has one lane, lane 0, which is both the first active lane and the lane read when EXEC is zero, so D is this
  thread's S0 under any EXEC, whatever S0 is.
- **A value the same on every thread of the workgroup.** Every lane of a wave belongs to one workgroup, so a value
  that is uniform over the workgroup is uniform over the wave. What an active lane holds is S0 with each masked write
  (`v = ex ? new : old`, lowering.masked_writes) whose lane bit the current EXEC bit implies replaced by its new word:
  such a lane was active at that write. The lowering emits that value, and again every definition between those
  writes and S0, under new names (`name_r<i>`, `uint rfl<i> = ...`), so that an inactive thread computes the same D as
  the active ones; then a uniform loop bounded by D runs the same trips on every thread, and none runs a trip count
  made from its stale registers. Once the whole text is lowered, `rfl<i>` must be in the uniformity lattice of
  CF-2c (`control_flow.uniform_names`: constants, `params[]` words, pure functions, and in the compute stage
  `group_id`), or the program is refused. The instruction must also run where the wave provably has an active lane
  (EXEC bit true, or the bit of an `s_cbranch_execz` region, control_flow's `live` bits): with EXEC zero the console
  reads lane 0, whose register a masked write may have left at its old value. An SGPR written inside a skipped region
  is poisoned after it, as any other (CF-2c).

Not uniform, and refused: anything that reads `local_id`, a masked write whose bit the current bit does not imply
(read after EXEC is restored), and every load. A load at a uniform address returns one word to all lanes of a
console wave at once, but the desktop threads of one console wave can sit in different desktop waves, and another
thread's store to that address may land between their loads; the corpus's shader of this kind (headless) has
one-thread workgroups and takes the first case. The Sascha Willems particle_calculate
reads LDS words at a uniform address after a barrier, which is C-6 plus a lattice root for LDS after a barrier (now
lowered, see [groupshared and barriers](#groupshared-and-barriers-c-6)).

Corpus: headless translates. generate_shading_rate lowers its two `v_readfirstlane_b32` (masked writes of values built
from constant words, under the execz region) and then stops at `s_buffer_load_dwordx2 s[4:5], s[8:11], s1`, a constant
load at a runtime SGPR offset (a loop index), the blocker of the three 16bit_arithmetic shaders and raytracing too.

Draw family `lanes`: program A, the shading-rate shape (two bounds narrow EXEC under `s_cbranch_execz`, two
constant-built values rounded and read under the narrowed EXEC, one the trip count of a uniform loop after
`s_max_u32` with 1, the other stored); program B, the headless shape (one-thread workgroups, a count loaded at the
group's address, read into an SGPR, a scalar Fibonacci loop). Wrong references: no mask, no max, truncation for
`v_rndne_f32`, the two read values swapped; no group bound, the read value taken as 0, one trip fewer. `controls`
checks the refusals above, `v_readlane_b32`, a vector or m0 destination and the pixel stage.

## Descriptor words as data
A program may read the words of a T# or S# with scalar ALU forms, as imageSize does (game_of_life_update: WIDTH - 1
from T# word 1 bits 30-31 and word 2 bits 0-13, HEIGHT - 1 from word 2 bits 14-29, shifted right by BASE_LEVEL from
word 3 bits 12-15, at least 1, and 0 when word 1 is zero, a null descriptor). The descriptor's words are the runtime's
(the harness writes them), so the contract says where they are: `descriptor_data={key: W}` (`--descriptor-data
OFFSET=WORD`) puts the eight words of the declared T# or storage image at key (four for the S#) in the constant words
W onwards. `forms/smem.compute_descriptor_load` then tracks each word as a `registers.DescriptorWord`: the provenance
`(tag, j)` it always was, for the image and sample forms that bind the descriptor, and its data `params[W + j]`,
which `registers.scalar_u32` returns, so every scalar form reads it as any word. Without `descriptor_data` such a
read stays refused ("Expected a numeric scalar register"). The words must lie inside the 64 and overlap no buffer V#,
user-data word or other descriptor's data. Nothing checks that the data words describe the bound view: the runtime
writes both from one descriptor, and the draws do so (a base level of 1 describes a view whose level 0 is the bound
texture).

game_of_life_update also needs **EXEC = -1** (`s_andn2_b64 exec, -1, exec` for its else arm and `s_mov_b64 exec, -1`
after it). Whole-wave mode stays refused in general, since on the console it turns on lanes that were never active;
in the compute stage it is lowered when every lane of every wave is a thread (the workgroup size a multiple of the
wave size; compute has no kill, so every thread is active at entry and -1 is the set of all threads) and the walk is
in no skipped region or loop (`forms/exec_mask.write_mask`, control_flow's `st.nesting`), so that every thread runs the
code that follows as every lane does on the console.

Draw: `image` program C, the update shape (the size from the T# data words, a texel loaded at the mirrored
coordinate, an if/else in whole-wave form, a UNORM store), with a base level 0, a base level 1 over a larger image,
and a null word 1. Wrong references: word 2's width bits ignored, BASE_LEVEL ignored, the height taken from the width,
the else arm's EXEC not inverted, EXEC not restored to -1. `controls` checks that a T# word read as data without
`descriptor_data` is refused, the invalid `descriptor_data` contracts, and EXEC = -1 in a partial wave (48 threads in
wave64), in a loop, in a skipped region and in the pixel stage. The pixel stage's binding description
(`PixelBindings`) does not take descriptor data yet.

## Dynamic scalar constant loads
`s_buffer_load_dword{,x2,x4,x8,x16} D, V#, sN [offset:K]` whose SGPR offset holds a run-time data word (a loop
counter, a group id, a push word) is lowered by `forms/smem.dynamic_constant_load` in every stage that reads constant
words through a constant-buffer V# (pixel, vertex, compute). The 16bit_arithmetic shaders index their position array
this way inside nested loops, and the corpus vertex shader sascha shadowmappingcascade/depthpass indexes a matrix array
by a push-constant cascade index.

Semantics, per dword j of the load:
- **Unit and alignment.** sN is a byte offset. SMEM reads whole dwords: the two low bits of the address are ignored
  (RDNA 2 ISA, scalar memory), so the read starts at `E = sN & ~3`. The `offset:` field must be a multiple of 4
  (refused otherwise, as for an immediate offset), and dword j reads byte `E + K + 4j`.
- **Range.** The dword is read only when it lies wholly inside the bound constant words: `E + K + 4j + 4 <=
  constant_limit` (256 bytes, the 64 words the pixel and compute contracts bind; 64 KiB in the vertex stage). Any other
  dword reads 0, dword by dword, as AMD's buffer range check returns for a dword past `num_records`. The comparison is
  made without overflow (`E <= limit - 4 - K - 4j`), so a 32-bit sum that would wrap reads 0, and the array index is
  clamped so that the HLSL never reads past `params[]`. The bound is the binding the contract declares, not the V#'s
  `num_records` (whose words are provenance here, not data): the runtime must bind the whole declared range, with
  the title's buffer padded with zeros past its `num_records`. A vertex program with a run-time offset therefore
  declares `params[4096]` and its case binds all 16384 words. A constant slot other than b0 (pixel bindings' params1
  to params3) is accepted only with its 64-word binding.
- **When the offset is read.** The load captures its offset when it issues (`uint smo<i> = sN & ~3u;`) and its words
  in locals (`smw<i>_<j>`), so a later write of sN, which the corpus does to its loop counter while the load is
  outstanding, does not change them.
- Still refused: an offset register that is itself an outstanding load, unset, or a descriptor word; a descriptor load
  (`s_load_dword*` of a descriptor list) at an SGPR offset that is not a translation-time constant (descriptor
  indexing: it selects a T# or V# at run time, which needs descriptor arrays); `s_buffer_load` through a buffer V#
  whose words are data (a storage buffer read by scalar loads, see below).

### Scalar loads and descriptor words across loops
The control-flow walk (CF-1, CF-2e) used to require the same outstanding scalar loads at a loop's entry and at every
back edge and exit. The 16bit_arithmetic shaders issue the load in the outer loop body and wait for it (`s_waitcnt
lgkmcnt(0)`) only in the innermost body, which may run no trip, so the load can stay outstanding around both inner
back edges and into the next outer iteration. The walk now treats outstanding loads as loop-carried state
(`control_flow.carried_pending`):

- **Outstanding set.** An SGPR whose load is outstanding at some back edge or exit is outstanding at the header from
  the first iteration on: the dry run is repeated from the widened entry until no end adds a register (the set only
  grows). This is a superset of the loads really in flight, and only `lgkmcnt(0)` completes a load (a nonzero count is
  refused), so a read of a register that may still be loading, or a write over one, is refused on every path. Back
  edges and exits may have fewer outstanding loads than the header; after the loop the registers of the carried set
  are outstanding.
- **Joining an outstanding word.** The tracked value of a scalar load result is the word the load returns, computed
  when the load issues. A register outstanding at a back edge whose value is a data word is joined as any data word
  (`js_<reg>_<tag>`): the join variable is assigned the loaded word before the console's register holds it, which no
  read can observe, because the register is still outstanding after the join. An outstanding descriptor word (a V#
  being loaded) and an outstanding VGPR load are still refused at a join.
- **A V# register reused for data.** A scalar register that holds a descriptor word at a loop's entry and a data word
  at a back edge (fp16 reuses V# word 3, s11, as its innermost counter) holds one or the other by iteration. It is
  JOIN_POISON at the header and after the loop: the body must write it before it reads it, and any read is refused
  (lowering's poison check). This applies to SGPRs only; a VGPR whose kind differs at a back edge is still refused.

Tests: the compute family `dynsmem` (`tests/compute_aot_check.py`). Program A, 72 one-thread groups: x2 at
`(4g | (g & 3)) + 8` and x1 at the same offset, crossing the end of the 64 words; wrong references: the offset ignored,
no range check (wrapping), a whole load zeroed for one dword outside, the offset as a dword index, the low bits kept.
Program B, the 16bit_arithmetic shape: an outer loop that reloads the constant V#, loads x2 at `8i + 4g`, increments
its offset register while the load is outstanding, and reads the words only in an innermost loop whose counter reuses
V# word 3 (cases with one, two and no inner trips, and offsets past the 64 words); wrong references: the offset
ignored, no range check, the whole load zeroed, the offset read at use, the first iteration's words reused. The vertex
draw `dynamic` (`tests/vertex_aot_check.py`): x4 and x2 at `64 * push0 | (push1 & 3)` up to and past the 64 KiB
binding; wrong references: the offset ignored, wrapped at 64 KiB, the low bits kept in the range check. Refusal
controls in all three checks: a misaligned `offset:` field, an offset register that is an outstanding load or a V#
word, a descriptor load at an SGPR offset, a read before the wait inside the loop, a V# reload over outstanding words,
the zero-trip path's read of a register still loading, and a read of the reused V# register at the middle loop's
header and after it.

Corpus effect: compute 14 to 15 of 27 (16bit_arithmetic/compute_buffer). Still refused:
- compute_buffer_fp16 and its fallback: `v_mov_b32_sdwa ... dst_unused:UNUSED_PRESERVE` into a VGPR that is
  undefined after the loop (it is written only in the body); the next instruction overwrites the kept half, so the
  register is defined, but the register model has no partially defined word.
- generate_shading_rate: one V# (descriptor 0x40) read both by `s_buffer_load` at a run-time offset and by
  `buffer_load_dwordx2 ... offen`, a storage buffer. The compute contract has no path for a scalar load through a
  buffer V# whose words are data (no ByteAddressBuffer path with SMEM's range rule), so it is not lowered.
- raytracing: two V#s from one x16 load (a uniform buffer and a storage buffer of spheres and planes read by
  `s_buffer_load` at run-time offsets): the compute contract binds one constant buffer, and the storage buffer would
  need the same scalar-load path as generate_shading_rate.
Pixel: unchanged (140 of 250); its five "Scalar load offset register must hold a known constant" refusals are
descriptor loads at SGPR offsets (descriptor indexing and descriptor heaps), and its five "Constant read exceeds
binding" refusals are immediate offsets past the 64 bound words, which need a larger constant binding in the pixel
contract and harness. Vertex: 214 to 215 of 244 (shadowmappingcascade/depthpass); descriptor loads at SGPR offsets
stay refused.

The change also fixes a latent bug that the 16bit shader exposed: `vop3p.need_fma_mix` inserted its helpers before
the preamble at first use, which moved every line whose position the control-flow walk had recorded (a loop's dry
run deleted one line too few, dropping a definition before the loop). The helpers are now placed after lowering
(`vop3p.place_fma_mix`, called by the three emitters) at the same place, so the text of every program is unchanged.

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
- **C-6: LDS and barriers (+2, total 23; implemented).** groupshared, the DS reads, writes, read2/write2 and atomics
  above, `s_barrier` in workgroup-uniform flow, the race rule for LDS without a barrier, and a draw with several
  desktop waves per workgroup. Unlocks the two Vulkan-Samples particle_calculate shaders, and with C-7's LDS root the
  Sascha Willems one.
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
