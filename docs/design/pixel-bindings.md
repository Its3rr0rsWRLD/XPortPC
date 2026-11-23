# Pixel stage: binding descriptions

Status: implemented (`tools/pixel_aot_ops/bindings.py`, `lower(bindings=...)`), checked by the `bindings` and
`texdims` draw families (`tests/pixel_aot_draws/bindings.py`, `tests/pixel_aot_draws/texdims.py`) and used for every corpus pixel shader by `tools/corpus_translate.py`.

## The problem

The fixed contract of `lower(program, texture_sgpr, interp_sgpr, sampler, constant_descriptor, ...)` names one
descriptor table whose pointer has a high word of 0, a T# at offset 0 (and optionally one more), one constant-buffer V#,
sampler words set by `s_mov`, and one sample per texture. RADV programs do not fit it: they complete each 32-bit
descriptor-set pointer with `s_movk_i32 s(n+1), 0x8000` (high word 0xffff8000), load samplers from memory, put textures
and constant buffers at any offset of several sets, read inline push constants from user SGPRs and sample one texture
many times. Before this change, 72 of the 250 corpus pixel shaders translated and almost every other refusal was that
contract.

## The description

`bindings.PixelBindings` describes the bindings of one program; nothing in it is inferred by the translator:

| Field | Meaning |
|---|---|
| `sgprs` | entry SGPR -> role: `descriptors` (set 0 pointer), `descriptors.N` (N 1..7), `interp` (interpolation base copied into m0), `push:W` (push-constant word W) |
| `textures` | key of a 32-byte T# -> texture slot 0..7 |
| `samplers` | sampler slot 0..3 -> key of a 16-byte S# loaded from memory, or the four words `s_mov` sets (an immutable sampler RADV inlines) |
| `constant_buffers` | key of a 16-byte constant-buffer V# (read by `s_buffer_load`) -> constant slot 0..3 |
| `push_constants` | the constant slot that holds the push words |
| `buffers` | key of a buffer V# -> index of its first word in `params` (as `buffer_descriptors` of the fixed contract) |
| `storage_images` | key of a storage-image T# -> (slot, format), as `storage_images` of the fixed contract |
| `descriptor_high` | the high word the program completes a pointer with (default RADV's 0xffff8000) |
| `dimensions` | texture slot -> `2d`, `2d_array`, `cube` or `3d`, or the T#'s eight words when they are known (see "Texture dimensions"); a slot not listed is 2D |
| `constant_sizes` | constant slot -> bytes of its window, a multiple of 16 from 256 to 65536 (see "Constant windows"); a slot not listed binds 256 |
| `ps_input_ena`, `ps_input_addr` | SPI_PS_INPUT_ENA and SPI_PS_INPUT_ADDR (see "Input VGPRs"); default persp_center alone, ADDR equal to ENA |

A key is the byte offset in set 0, or `SET_STRIDE * N + offset` in set N, as in the compute stage. `check()` refuses a
malformed description: an unknown or repeated role, a slot used twice, a key that is not 16-byte aligned, two
descriptors that overlap. `names()` lists what every entry SGPR and declared descriptor is bound to.

HLSL names and registers (bound by `tests/pixel_aot_render.cpp`; `tests/pixel_aot_vs.hlsl` holds the root signature):

| Slot | Texture | Sampler | Constants |
|---|---|---|---|
| 0 | `tex` (t0) | `samp` (s0) | `params` (b0) |
| 1 | `tex1` (t1) | `samp1` (s1) | `params1` (b2) |
| 2 | `tex2` (t3) | `samp2` (s2) | `params2` (b3) |
| 3..7 | `tex3`..`tex7` (t4..t8) | `samp3` (s3) | `params3` (b4) |

t2 and b1 stay the title ranges and their count. The harness's samplers are all point samplers with clamp addressing;
a title's S# words are memory the translator does not see, so a sampler is named, not interpreted.

## Texture dimensions

Each T# declares its dimension. When the descriptor's eight words are known, the dimension is their TYPE field (word
3, bits 28..31; AMD's `SQ_RSRC_IMG_*` values 9 2D, 10 3D, 11 cube, 13 2D array, `bindings.type_dimension`; 1D and
MSAA types are refused); otherwise it is the name the description gives. A texture is declared, and bound by the
harness, as:

| Dimension | HLSL type | Harness view ('X2WD' case section, `tests/pixel_aot_render.cpp`) |
|---|---|---|
| `2d` | `Texture2D<float4>` | `TEXTURE2D` (the existing textures) |
| `2d_array` | `Texture2DArray<float4>` | `TEXTURE2DARRAY` of its slices |
| `cube` | `Texture2DArray<float4>` | `TEXTURE2DARRAY` of its six faces, slices 0..5 = +X, -X, +Y, -Y, +Z, -Z |
| `3d` | `Texture3D<float4>` | `TEXTURE3D` |

An image instruction's `dim:` must be the dimension its texture is bound with, and the 2D-only forms (the explicit-level
samples, loads, level queries and gathers) refuse a texture of another dimension. `image_sample` of each dimension
(`forms/mimg.py`, `dimensioned_coordinate`) reads a three-word address (a range or an NSA list) and lowers as follows.

- **3D**: `tex.Sample(samp, float3(s, t, r))`. r is normalized like s and t (RDNA addresses a 3D image with three
  normalized coordinates); all three enter the implicit level, so each must be an affine helper-lane value, as a 2D
  coordinate must.
- **2D array**: `tex.Sample(samp, float3(s, t, slice))`. The slice is an unnormalized index. Whether the texture
  unit rounds or truncates a fractional slice is not established here (Mesa rounds it to even in the shader under
  its `lower_array_layer_round_even` option, which the corpus programs show as a `v_rndne_f32` before the sample,
  and Mesa's older radeonsi fix rounded it only on some generations), and an S# is named, not interpreted, so the
  slice must be an integer value: a `v_rndne`, `v_floor`, `v_ceil` or
  `v_trunc` result (no output modifier), a `v_cvt_f32_i32`/`u32` result, an integral immediate or a copy of one
  (`Lowering.integral`). Such a slice reads the same slice under either rule, and under Direct3D's rounded index; a
  slice beyond the array is clamped to [0, size - 1] by both (Vulkan requires it and RADV emits no clamp). Any other
  slice is refused ("An array slice must be an integer value").
- **Cube**: the program computes AMD's face coordinates with `v_cubeid`, `v_cubesc`, `v_cubetc` and `v_cubema` (the
  `cube` family checks those): s = sc / |ma| + 1.5 and t = tc / |ma| + 1.5, with `v_cubema` returning 2 ma, lie in
  [1, 2] on the face, and the face is the `v_cubeid` result. Two lowerings are possible: rebuild a direction from
  (s, t, face) for `TextureCube.Sample`, or sample a `Texture2DArray` view of the six faces at (s - 1, t - 1, face).
  The second is the bit-exact one and is what is emitted
  (`precise float3 faceN = float3(s - 1.0f, t - 1.0f, face); tex.Sample(samp, faceN)`): the face is the program's
  own, so a tie between two major axes keeps `v_cubeid`'s rule (z, then y, then x), which a desktop cube projection
  need not follow; the face coordinate is the program's value, where a projection would divide again with its own
  rounding; and the implicit level comes from the derivatives of the face coordinates, as on the console, not of
  the direction. s - 1 and t - 1 are exact for s and t in [0.5, 2], and the face index is an integer, so Direct3D's
  rounded slice is exactly it. The face must be a `v_cubeid` result without clamp, or a copy of one
  (`Lowering.cube_faces`). s and t are quotients, not affine in the interpolated coordinate, so they need only be
  helper-lane values: any whole-quad VALU result whose VGPR operands are helper-lane values (`Lowering.quad_defined`,
  `valu_f32.helper_defined`). How an adapter takes their derivatives (coarse or fine) is then not proven, and the
  draws use one-level textures. Not modelled: a face coordinate outside [1, 2] (s = 2 or a coordinate pushed past an
  edge by rounding), where the hardware's seamless cube addressing may read the neighbouring face and this lowering
  reads the clamped edge of the face, and bilinear footprints that straddle a face edge.
  The [1, 2] range and the 1.5 offset are the convention of Mesa's and LLVM's AMD cube lowering; the console's
  texture unit was not measured.

The `texdims` draw family (`tests/pixel_aot_draws/texdims.py`) checks the three dimensions with programs shaped as
RADV writes them and Python references: an 8x8 array of four slices read at integral, rounded (2.7, ties 1.5 and
2.5) and clamped (-0.6, 9.0) slices; the six faces of an 8x8 cube read through directions on every face (major
coordinate 0.5, 1 and 4) and through the two kinds of tie at a face edge; an 8x8x4 3D texture read at the centre of
each depth slice, below and above the texture and with two coordinates exchanged through an NSA address; and a
bilinear read of each dimension at texel centres through the harness's bilinear sampler (s4), where the filter
weights are exactly 1 and 0. Wrong references (the slice truncated, a tie rounded up, the face swapped with its
opposite, a tie broken toward the other axis, r read as a slice index, the axis order ignored, a neighbouring texel
for the bilinear reads) must each be reported as mismatches.

### Cube arrays

A gfx10 cube T# (TYPE 11) may hold several cubes (its array range); the program then passes the face word face + 8 *
layer, as Mesa's `ac_prepare_cube_coords` writes it: a `v_cubeid` result plus 8.0 times an integral layer, through
`v_madmk_f32`/`v_fmamk_f32 layer, 0x41000000, face` or `v_mad_f32`/`v_fma_f32`/`v_fmac_f32` with the 8.0 literal on
one factor (`valu_f32.note_cube_layer`, `Lowering.cube_layers`; copies keep it). The layer must be an integer value
(`Lowering.integral`, as an array slice: the corpus's two texturecubemaparray programs convert a push word with
`v_cvt_f32_i32`, a GLSL float layer is `v_rndne`'d), with no negation, clamp or output modifier. The texture is bound
as a `Texture2DArray` view of its 6 N faces, cube n at slices 6 n .. 6 n + 5 (harness 'X2WD' kind 4), and every form
that samples a cube (image_sample, _b, _l, _lz; `forms/mimg.py`, `cube_face`) reads slice face + 6 * layer, with the
layer first clamped to [0, N - 1] (N from `GetDimensions`): Vulkan clamps a cube array's layer, not the slice, and
RADV emits no clamp, so the texture unit applies it; Direct3D's own slice clamp would send a layer past the end to the
last face of the last cube. Face and layer are small integers, so face + 8 layer and the slice are exact. A dimension
name `cube_array` is the same binding as `cube` (either takes `dim:SQ_RSRC_IMG_CUBE`, and a plain `v_cubeid` face reads
cube 0). Not modelled: a NaN layer (only `v_rndne` and the other rounding results could give one; it reads layer 0
here). The `cube_array` draw family checks the four forms on a three-cube, four-level 8x8 array at every face, every
cube, layers past either end and rounded float layers, with wrong references for the layer ignored, the face word used
as the slice, face and layer mixed up (layer + 6 face) and the slice clamped instead of the layer.

## Constant windows

A constant slot binds 256 bytes (16 uint4) unless `constant_sizes` gives it a window, up to 65536 bytes (4096 uint4, a
D3D12 constant buffer view's limit). An `s_buffer_load` at an immediate offset that is not wholly inside the window is
refused ("Constant read exceeds binding"). `params<k>[]` is declared with the uint4 up to the highest word the program
reads, at least 16, so a program that reads no further than 256 bytes declares and reads what it did before whatever
window it is given; a load at a run-time offset declares the whole window, and a dword of it that is not wholly inside
the window reads 0, as AMD's range check returns past num_records (the compute stage's dynamic constant loads). The
vertex stage sizes `params` the same way (vertex_aot.py, CONSTANT_BYTES).

The window is the bytes the runtime binds: `tools/pso_translate.py` writes it as a sixth field (after the flags field) of the constants
line of the bindings sidecar when the translation declares more than 16 uint4, and the shim's root CBV covers that many bytes
of title memory (`src/d3d12_xs_pipeline.cpp`, TableRef::window; the runtime R4 scene's pixel program reads its tint at
byte 0x110). The harness binds larger buffers through the case's 'X2WK' section (`tests/pixel_aot_render.cpp`); the
`pxcb` draw family checks windows of 0x400 and 0x800 bytes, through two slots, and a run-time offset that reads 0 past
the window though the bound buffer holds words there.

## Input VGPRs

A pixel program's input VGPRs are given by SPI_PS_INPUT_ADDR and SPI_PS_INPUT_ENA (AMD's register layout, Mesa sid.h
S_0286CC_*_ENA, bits 0..15: persp_sample, persp_center, persp_centroid, persp_pull_model, linear_sample, linear_center,
linear_centroid, line_stipple, pos_x, pos_y, pos_z, pos_w, front_face, ancillary, sample_coverage, pos_fixed_pt). The
inputs whose ADDR bit is set take VGPRs from v0 in bit order (two for a barycentric pair, three for pull_model, one for
the others), and those whose ENA bit is set too are loaded; ENA is a subset of ADDR and has a barycentric input. ACO sets
ADDR equal to ENA. `bindings.input_vgprs` gives the layout. At run time the layout comes from a version 2 console
container's `X2WShaderPixelInfo` record (`src/d3d12_xs_api.h`; docs/design/runtime.md, "Pixel input layout"), which
the shim passes to `tools/pso_translate.py` as the pixel roles' `ps_input_ena` and `ps_input_addr`.

Lowered inputs: persp_center (bary_i, bary_j, what `v_interp` reads; the desktop interpolates at the pixel centre), and
from the HLSL inputs `SV_Position` and `SV_IsFrontFace`: pos_x and pos_y the pixel centre (x + 0.5, y + 0.5), pos_z the
depth and pos_w the clip-space w (a Direct3D pixel shader's SV_Position.w is w, and the RADV dumps divide by
gl_FragCoord.w as a product with POS_W, so POS_W is w, not 1 / w); pos_fixed_pt the integer pixel x in bits 0..15 and y
in bits 16..31 (what an a16 image address reads); front_face a binary32 that is positive for a front face (ACO tests it
as 0 < v; +1.0 and -1.0 are given). A read of any other input (ancillary, sample_coverage, the other barycentrics,
line_stipple) or of a VGPR that ADDR reserves and ENA does not load is refused with the input's name ("Read of input
VGPR v2 (ancillary), ..."). The default description, persp_center alone, is v0 and v1 as before, and its HLSL is
unchanged.

The RADV dumps do not print the registers, so `tests/corpus/ps-inputs.tsv` records ENA for the corpus shaders whose
inputs are not persp_center alone, from the GLSL builtins each reads (gl_FragCoord components, ivec2(gl_FragCoord.xy),
gl_FrontFacing, gl_ShadingRateEXT) and confirmed in the dump. The `pxcb` draw family checks pos_x..pos_w, front_face
and pos_fixed_pt, arithmetic on the pixel centre, and an ADDR wider than ENA. The harness's triangle has depth 0 and
w 1 everywhere and is front-facing: z and w are told apart, w from 1 / w and the back face are not drawn.

## Resolution

Under a description every descriptor load goes through the compute stage's word-by-word resolve
(`forms/smem.compute_descriptor_load`, now also claimed when `st.descriptor_words` is set): the address pair must be a
set pointer and the description's high word, and each destination word becomes the word of the declared descriptor
that covers it (`(name, j)` for a T#, `(tag, j)` for an S# or constant-buffer V#, a `params` word for a buffer V#). One
load may span several descriptors (`s_load_dwordx16` of a T# and two S#s). An SGPR offset must hold a translation-time
constant. A word no descriptor covers is refused ("Descriptor table word is not a tracked descriptor"), as is a pointer
with another high word or of an undeclared set ("Unresolved descriptor-list pointer"). `s_buffer_load` reads through
the four words of constant slot k as `params<k>`; a sample needs the eight words of a declared T# and the four words of
a declared sampler. An entry SGPR without a role has no value, so reading it is refused. The fixed contract's one
sample per texture is not required; the program must end with its done export.

The fixed-contract arguments are unchanged and keep their forms (`smem.texture_descriptor`, the `s_load` branch of
`smem.scalar_load`), so every program they lowered keeps byte-identical HLSL. A description equivalent to the fixed
contract (texture 0 and sampler 0, constant slot 0, texture slot 1) emits the same declarations in the same order.

## Corpus

`tools/corpus_translate.py` derives each shader's description from its RADV dump (`derive_bindings`, the approach of
the compute stage's corpus contract): entry SGPRs are those read before they are written; the one copied into m0 is
`interp`; one whose pair the program completes with a constant high word and loads through is a set pointer (the lowest
set 0); any other read entry SGPR is a push word; each loaded descriptor is classified by its first use. With it, 125
of the 250 corpus pixel shaders translate (72 before; those 72 keep byte-identical HLSL), and all 125 compile with DXC.
The remaining refusals were forms, not bindings: other image dimensions and dmasks, sample coordinates the helper-lane
rule does not prove, and a few dynamic descriptor indices ("Scalar load offset register must hold a known constant").
With 2D samples of any dmask and the wider helper-lane rule (immediates, copies, v_sub/v_mul/v_mad/v_mad*k and flat
attributes under whole-quad execution, also after a sample; the `sample_shapes` draw family), 140 translate and compile.
With texture dimensions (each T#'s dimension is the `dim:` of the image instruction that first uses it, as the
layout's image view type would give it), 158 translate and all 158 compile with DXC; the 140 keep byte-identical
HLSL. Of the 23 shaders that stopped at a cube, 2D-array or 3D `image_sample`, 18 translate; the other five stop
elsewhere: two irradiance-cube programs and the spherical environment map sample at loop-carried or non-affine
coordinates ("Unsupported texture coordinate"), and two more at unrelated forms.
With constant windows and input VGPRs, 173 translate and compile with DXC (167 before; those keep byte-identical HLSL).
Of the five shaders refused at "Constant read exceeds binding", the shadow-map quad translates; the other four stop at a
2D-array sample coordinate, a scalar bitfield operand, an interpolation context and an execution-mask move. Of the
eleven refused at a read of v2 (an input VGPR), five translate (gl_FragCoord.z, .z / .w, .xy); the other six stop at the
variable-rate shading input (ancillary, not lowered), a storage-image load, a binary16 literal of v_fma_mix (two), a
masked write and an interpolation context.
With cube arrays ("Cube arrays"), the two texturecubemaparray programs (skybox and reflect, `image_sample_l` of face +
8 layer) translate: 191 of the 250 translate and compile with DXC (189 before; those keep byte-identical HLSL).
