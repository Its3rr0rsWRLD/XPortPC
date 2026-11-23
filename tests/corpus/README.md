# Corpus ISA: open-source pixel shaders compiled for gfx1013

`isa/pixel/` holds the 250 pixel-shader ISA dumps that `docs/coverage/corpus-gfx1013.tsv` and
`docs/coverage/corpus-shaders.tsv` count, one file per shader. `tools/corpus_translate.py` translates them end to end
and writes `docs/coverage/corpus-translate.tsv`; the `corpus_translate` test compiles every translated one with DXC.

## Origin

Each file is the ACO disassembly that Mesa RADV 25.2.8 printed (`RADV_FORCE_FAMILY=GFX1013`,
`RADV_DEBUG=shaders,nocache,nongg`, null winsys, no GPU) for one GLSL fragment shader compiled with glslangValidator
15.1.0 (`-V --target-env vulkan1.3`), reduced to the `disasm:` body under a `# Pixel Shader` line. The route, the
choices that affect the code and the builder (`tools/shader_corpus_build/`) are described in
[docs/coverage/corpus-sources.md](../../docs/coverage/corpus-sources.md). A line is `mnemonic operands ; hex words`;
`BBn:` lines are block labels. The file name is `<source>__<path in its shaders directory>.s`, with `/` written as
`__`.

| Prefix | Source | Commit | License | Files |
| --- | --- | --- | --- | --- |
| `sascha__` | SaschaWillems/Vulkan `shaders/glsl`, https://github.com/SaschaWillems/Vulkan | d2d49bf7f2d8469ad9fee47b2a43b430d7e10e1b | MIT, [LICENSE-SaschaWillems-Vulkan.md](LICENSE-SaschaWillems-Vulkan.md) | 140 |
| `vksamples__` | KhronosGroup/Vulkan-Samples `shaders`, https://github.com/KhronosGroup/Vulkan-Samples | 0a97dba1e71b8fa191afb012b784ebad477ccf5a | Apache-2.0, [LICENSE-KhronosGroup-Vulkan-Samples.txt](LICENSE-KhronosGroup-Vulkan-Samples.txt) | 110 |

These files are compiled forms of those shaders, not the sources: the change is the compilation described above.
The copyright of each shader stays with its authors as its source file states (for Vulkan-Samples, per-file headers
such as Arm Limited and Contributors, Sascha Willems, Mobica Limited, Qualcomm Innovation Center, Google, Holochip,
Nintendo; for SaschaWillems/Vulkan, Sascha Willems). The license texts are copied unchanged from the commits above.
Vulkan-Samples has no NOTICE file at that commit. No game files or commercial shaders are included.

## Other stages (`isa/stages/`)

`isa/stages/` holds the 22 tessellation and geometry programs of the same two sources, compiled by the same route
with NGG on (no `nongg`) and with `--pair-geom` (`tools/shader_corpus_build/build_corpus.py`), so that each geometry
shader that has no vertex shader of its own is built behind the vertex shader of its directory whose outputs cover
its inputs: an `<geom>+<vert>.s` file is one merged ES+GS program. The first line names the hardware stage RADV
compiled each API stage as. `tools/stage_corpus_report.py` surveys them and translates the NGG geometry programs with
`tools/geometry_aot.py` (docs/design/stages.md). 12 files are `sascha__` (MIT) and 10 `vksamples__` (Apache-2.0), under
the same licenses and copyright as above.

The pairing and the builder's grouping by file stem leave some programs unlike an application's: the three
`*.tesc.s` files come from pipelines without a vertex shader (RADV compiled the HS alone), and in the
`shader_object` pairings only the position reaches a fragment shader, so the geometry shaders export pos0 only.
