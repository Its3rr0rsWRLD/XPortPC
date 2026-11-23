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
