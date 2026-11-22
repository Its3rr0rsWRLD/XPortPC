# Pixel stage: binding descriptions

Status: implemented (`tools/pixel_aot_ops/bindings.py`, `lower(bindings=...)`), checked by the `bindings` draw family
(`tests/pixel_aot_draws/bindings.py`) and used for every corpus pixel shader by `tools/corpus_translate.py`.

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
Cube, 2D-array and 3D samples (21 shaders) need a texture dimension in the description and the harness, and stay refused.
