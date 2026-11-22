# Shader corpus sources (docs/coverage/corpus-gfx1013.tsv)

Measures which gfx1013 instruction forms open-source shaders use. Counts come from `tools/shader_corpus.py`
over ISA dumps; the table's header comments carry the totals.

The 250 pixel-shader dumps are committed in [tests/corpus/isa/pixel](../../tests/corpus/README.md) with the two
licenses. `tools/corpus_translate.py` runs each whole program through the pixel translator and writes
`corpus-translate.tsv`: translated, or the first refusal with its reason and the form or check that raised it. "All
covered" (every form covered by a test) is not the same as translated; that file gives both. The `corpus_translate`
test compiles every translated shader with DXC.

## Compiler route

Mesa RADV 25.2.8 (Ubuntu `mesa-vulkan-drivers` 25.2.8-0ubuntu0.24.04.5) on the null winsys, no GPU:
`RADV_FORCE_FAMILY=GFX1013` (upper case; `gfx1013` and `gfx1010` are rejected) selects chip GFX1013 directly,
so no other chip was substituted. `RADV_DEBUG=shaders,nocache,nongg` prints the ACO ISA as LLVM-style text.
GLSL goes to SPIR-V with glslangValidator 15.1.0 (`-V --target-env vulkan1.3`). `tools/shader_corpus_build/`
holds the driver: `reflect.py` reads descriptors, push constants and stage interfaces from the SPIR-V,
`pipe.c` builds one pipeline (dynamic rendering, 1.3), `build_corpus.py` groups shaders into programs and splits
the dump per stage. Build `pipe.c` with `gcc pipe.c -o pipe -lvulkan`; paths in `build_corpus.py` are for the
container that produced the data.

Choices that affect the counts:
- `nongg`: gfx10 RADV otherwise compiles the vertex stage as an NGG shader, which adds primitive-export boilerplate
  (`s_sendmsg GS_ALLOC_REQ`, wave-count branches). The legacy VS path is closer to what a game's vertex shader looks like.
- Vertex and pixel shaders are compiled as pairs (same directory and file stem; a lone fragment shader gets the
  vertex shader in its directory whose outputs cover its inputs), so unused interpolants are pruned. Each shader
  is counted once.
- Vertex input is float4/int4/uint4 per location; pixel outputs are RGBA8 (UNORM, SINT or UINT); depth is D32.
- "other" is geometry and tessellation shaders. Tessellation pipelines crash RADV's null winsys after the ISA
  is printed; those dumps were kept when they ended in `s_endpgm`. In a pipeline with tessellation or geometry,
  the vertex shader is merged (LS/ES) and counted under "other".
- Loops with known trip counts are unrolled by the compiler, so loop counts are low relative to the source.
- ACO emits some branches itself (`s_cbranch_execz` around discards and divergent blocks), so "has a branch"
  is not the same as "source has an if".
- ACO targets gfx1013 as gfx10.1: `v_mac_f32` instead of gfx10.3's `v_fmac_f32`, no ray-tracing image ops
  (RADV does not use them below gfx10.3), and `v_interp_p1/p2_f32` pixel interpolation.

## Sources

| Source | URL | Commit | License | Shaders compiled (pixel / vertex / compute / other) |
| --- | --- | --- | --- | --- |
| SaschaWillems/Vulkan `shaders/glsl` | https://github.com/SaschaWillems/Vulkan | d2d49bf7f2d8469ad9fee47b2a43b430d7e10e1b (2026-11-09) | MIT | 140 / 138 / 10 / 13 of 312 source files |
| KhronosGroup/Vulkan-Samples `shaders` | https://github.com/KhronosGroup/Vulkan-Samples | 0a97dba1e71b8fa191afb012b784ebad477ccf5a (2026-11-16) | Apache-2.0 | 110 / 106 / 17 / 10 of 285 source files |

Together: 250 pixel, 244 vertex, 27 compute, 23 other = 544 shaders, which is what the table counts.
Files that did not compile were GLSL that glslang rejects for Vulkan (desktop-only or extension use), mesh/task or
ray-tracing stages, subpass-input shaders (the builder uses dynamic rendering), a few fragment shaders with no
matching vertex shader.

## Not in the table

- KhronosGroup/glslang `Test/` (commit 6334e1549a49989e04b5329a6a39a328247fd6ed): 108 pixel / 90 vertex / 90 compute
  compiled of 1705 files. Left out because the files are mostly small conformance tests, many with no license
  header, in a repository that mixes several licenses. Its counts were only used as a cross-check.
- GPUOpen FidelityFX SDK (commit 7539ae8b6568ad29ed78a753404351daf3b5cca7): not used. Per-file headers say MIT, but
  `docs/license.md` grants redistribution "in binary form only" and says "No reverse engineering, decompilation, or
  disassembly", which conflicts with dumping ISA. The shaders are also HLSL and no DXC was available here.
- HLSL sources (Sascha `shaders/hlsl`, Vulkan-Samples `.hlsl`): same programs as the GLSL ones, or need DXC.
- Slang sources: no Slang compiler available.
