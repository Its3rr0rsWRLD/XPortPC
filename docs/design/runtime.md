# Runtime: from source-built programs to real titles

Status: plan. Nothing here runs a title yet. This document says how the existing pieces (launcher, `pe_map`, `xmem.dll`,
title GPU addresses, the gfx1013 converter) become a runtime that can start a real title, and how progress is measured.

Rules this plan keeps:

- **Pure translation, no emulation.** Console APIs are implemented on desktop Windows APIs, as DXVK and vkd3d-proton
  implement D3D on Vulkan. The console GPU's command processor is not simulated. Performance matters at every step.
- **Sources.** This repository, public documentation and general knowledge. No game files, dumps, leaked SDKs or
  headers, or credentials. Our dev loop uses only source-built test programs.
- **Real titles.** The owner runs his own titles with permission and reports works / does not work plus the logs our
  tools write (section 7). Those logs never contain title code or assets.

## 1. Process model

```
x2w_launch.exe [--shims DIR]... title.exe
  -> pe_map.dll: pe_map_image(title, resolve)   map, relocate, bind imports, register .pdata
  -> pe_map_run                                 TLS callbacks, then the entry point on this thread
  -> exit code of the entry point = process exit code
```

What exists (`tools/x2w_launch.cpp`, `tools/pe_map.cpp`, test `tests/native/launch_check.py` with
`tests/native/fake_title.cpp`):

- `pe_map` maps an x64 image away from its preferred base, applies DIR64/HIGHLOW relocations, binds ordinary and delay
  imports through a host resolver, sets section protections, registers `.pdata` with `RtlAddFunctionTable` (so SEH and
  unwinding work through mapped frames) and runs TLS callbacks in order. Title code runs unchanged.
- Import resolution order, per `dll!symbol`, first hit wins:
  1. `DIR\<dll>` in a `--shims` directory, loaded with `LoadLibrary` (our desktop implementation of a console library).
     If the shim DLL exists but lacks the symbol, the import becomes a stub ("stub (not in shim)").
  2. `<dll>` beside the program, mapped with `pe_map` like the program (the title's own DLLs). Cycles are cut.
  3. The Windows loader's normal search.
  4. A generated stub: a 32-byte thunk that logs `[x2w] call stub dll!symbol` on its first call and returns 0.
- Every import is reported on stderr as `[x2w] import dll!symbol -> shim|package|windows|stub`.

Known gaps, all measured by existing tests and to be closed in this order as titles need them:

| Gap | Effect on a title | Fix |
|---|---|---|
| Implicit TLS (`__declspec(thread)`): `pe_map` refuses a non-empty TLS template (`cpu_native_tls_value`) | Any CRT-linked title fails to map | Allocate the index, fill each thread's TLS slot from the template, run callbacks on thread attach |
| `GetModuleHandle(NULL)`, PEB image base, module list still name the host | Resource loads and self-lookup go to `x2w_launch.exe` | Patch PEB `ImageBaseAddress` and add a loader-list entry, or hook the few kernel32 calls |
| Stubs ignore arguments and return 0 | A stubbed call that must succeed fails silently later | Stubs log the first N calls with RCX/RDX/R8/R9 and the caller RVA; a per-symbol return override file |
| Windows route for names Windows also has | A console DLL with a desktop namesake binds to a desktop DLL with other semantics | The report marks every `windows` route; a deny-list forces such names to the shim directory |

Shim DLL layout. One desktop DLL per console DLL name, with the console name, in `out/shims/`. Each is a thin export
table over static libraries in `src/` that are tested on their own (as `xmem.dll` is over `era_heap`, `era_query`,
`era_title_gpu`):

| Shim | Contents |
|---|---|
| memory (`xmem.dll`, exists) | `era_heap`, `era_query`, `era_title_gpu`, title GPU address table |
| graphics | console D3D12 layer over desktop D3D12 (section 3) |
| runtime services | GDK-style services: forwarders to the PC Gaming Runtime, or our own code (section 2) |
| kernel/base | the console base library's functions that differ from desktop kernel32, plus forwarders |
| audio, input | XAudio2 forwarders and own codecs; GameInput forwarder |

The import names the console DLLs export are not publicly documented. The real surface is learned from the import tables
of the owner's titles, which the game report (section 7) lists by name. Shims are written against that list, ordered by
how many reported titles import each symbol.

Logging of unimplemented calls has three levels, all on by default and written to `x2w-<pid>.log` as well as stderr:

1. **import** (bind time): every import and its route.
2. **stub call** (run time): first call of each stub, with arguments and caller RVA; counts at exit.
3. **unimplemented path inside a shim**: a shim function that receives arguments it does not handle calls
   `x2w_unimplemented("dll!symbol", detail)` once per distinct detail and returns a documented failure code. A shim
   never guesses a success it cannot deliver.

The first entry of levels 2 and 3, in time order, is the run's **first unimplemented call**. It is the most useful single
line in a report and the launcher prints it again at exit.

## 2. System libraries

Categories of console imports, and the strategy for each. The public-docs map of which GDK APIs also exist on PC is the
`gdk-pc-map` planning card (public Microsoft Learn GDK pages, read 2026-11-22). In short:

| Category | Public PC equivalent | Strategy |
|---|---|---|
| Win32 subset (files, threads, sync, sockets, WinHTTP) | Same APIs (the GDK's shared Win32 games family) | Route to Windows. Console-only flags and paths are fixed in the base shim |
| Gaming Runtime flat APIs: XGameRuntime, XTaskQueue/XAsync, XSystem, XPackage, XGameSave, XUser, XStore, XGameUI | Same headers on PC through the PC Gaming Runtime | Forward where it works unpackaged; own fallbacks otherwise (below) |
| Xbox services (Xbl*, libHttpClient), xCurl | Same flat C APIs on PC | Forward; offline failure codes when sign-in is unavailable |
| Input: GameInput, XInput | GameInput redist, XInput | Forward |
| Audio: XAudio2 | Windows XAudio2 | Forward the common API; XMA decode is our own code if PC has none |
| Memory: XMem extensions | none | Own code (`xmem.dll`, exists) |
| Graphics: console D3D12 | desktop D3D12 | Own code (section 3) |
| Lifecycle (suspend/constrain/resume), Game DVR, console networking, console storage | none | Own code: no-op or a fixed answer, logged |

Rules:

- **Forward only where the API matches, and measure the match.** A shared header name does not prove the same
  behavior or the same exports. A separate task maps the exact overlap; until a symbol is on that measured list, it is
  implemented or stubbed, not forwarded.
- **Package identity.** The PC Gaming Runtime documents Store, save, user and package APIs for Store-packaged games.
  How they behave in an unpackaged process is not documented. Each forwarder therefore has an own fallback: local-file
  saves under `%LOCALAPPDATA%\XPortPC\<title>`, an offline local user, an owned license, the package root as the
  title's folder. The fallback is the default; forwarding is opt-in per title once measured.
- **Identity answers.** `XSystemGetDeviceType` and similar queries return a Series X value, since titles branch on it.
- Every own implementation is a static library with a source-built test, like `era_heap` and `era_query` today.

Shim generation (`tools/shimgen.py`, specs in `tools/shimgen/specs/*.toml`, built by `cmake/x2w_shimgen.cmake`).
The console import DLL names are not public, so shims are generated from a title's measured import list:

```
python -B tools/x2w_report.py TITLE.exe --out out/x2w-report
python -B tools/shimgen.py --report out/x2w-report/report.json --out out/shimgen/title
cmake --preset dev -DX2W_SHIM_REPORT=out/x2w-report/report.json   # builds them into out/build/dev/shims
```

Each export of a generated DLL is a forwarder (only when `X2W_FORWARD` turns its family on; off by default,
per the rule above), a call into `x2w_gdk.dll` (the hand-written family modules in `src/gdk`: XGameRuntime,
XTaskQueue, XAsync, XSystem, XUser, XGameSave, XPackage, XGameUI; one process-wide copy, so handles work
across DLLs), or a typed stub that zeroes out-params and returns the spec's documented default. Functions
no spec describes get an untyped stub (0, or `E_NOTIMPL` for `*Async`/`*Result` names). Stubs log their first
call through `x2w_unimplemented`, which also reaches the run log. Overrides (`--override FILE.toml`,
`X2W_SHIM_OVERRIDES`) change any function's body or return value per title.

PC GDK builds do not import the Gaming Runtime: `xgameruntime.lib` loads `xgameruntime.dll` and resolves
names at run time. `x2w_launch` therefore hooks the program's `LoadLibrary*`, `GetModuleHandle*` and
`GetProcAddress` imports: a load whose name is in a `--shims` directory gets the shim (a generated
`xgameruntime.dll` with every spec function is always built), and each load and resolve is logged once
(`dynamic-load`, `dynamic-resolve`). `tools/shimgen.py --run-log` turns those lines into shims.

## 3. Graphics: console D3D12 over desktop D3D12

The console D3D12 surface beyond the public desktop API is **not publicly documented**. What we may use:

- the public D3D12 documentation and DirectX-Specs (desktop semantics, which the console API shares in large part);
- the behavior of our own source-built programs written against the public desktop `d3d12.h`;
- logs from the owner's titles: which exports, interface methods (vtable slots) and IIDs are called, with argument
  values and return codes, never code or data blobs;
- the GPU ISA (AMD's public RDNA documentation, LLVM's AMDGPU backend), which the converter already uses.

No leaked headers. Where those sources do not determine a behavior, the call is logged as unimplemented.

### Objects

The title gets objects from our graphics shim and calls them through vtables. Each wrapper holds the desktop object:

| Console object | Desktop object | Translation |
|---|---|---|
| device | `ID3D12Device` (newest available) + debug layer in dev builds | create calls translated one by one; `QueryInterface` of an unknown IID is logged and fails with `E_NOINTERFACE` |
| command queue | `ID3D12CommandQueue` | `ExecuteCommandLists` unwraps lists; fences map 1:1; present goes through a DXGI swap chain the shim owns |
| command allocator / list | same | each record call becomes the desktop call with title GPU addresses translated (`X2WTitleGpuTranslate`) and descriptors remapped |
| pipeline state | desktop PSO | built from translated shaders (below); cached |
| root signature | desktop root signature | console blob deserialized, console-only flags dropped, converter parameters appended |
| descriptor heap | shader-visible desktop heap + shadow table | below |
| resource / heap | desktop resource; buffers in title memory are aliases (section 4) | layout and state rules below |

Vtable slots. The wrappers use the public desktop method order. That the console interfaces share this order is an
assumption that the first owner logs test: every slot past the public ones, and every slot at all in dev builds, first
goes through a logging thunk (interface, slot index, caller RVA, four argument registers). A title calling a slot we
have not implemented stops with that line as its first unimplemented call.

### Descriptors

Converted shaders read descriptors as hardware words (V#, T#, S#) from memory, as the console GPU does; the converter
already tracks them (`tools/pixel_aot_ops/bindings.py`, [pixel-bindings.md](pixel-bindings.md)).

- **Buffers (V#):** already handled. The converted shader decodes base and range from the V# words and loads through
  `TitleLookup` (`src/title_va_lookup.hlsli`) from the title GPU address. No desktop descriptor per buffer is needed.
- **As built in R4:** the translator resolves every descriptor load to (descriptor table, byte offset) at
  translation time, since the converter already tracks descriptor loads by key, and the shim resolves that to the
  slot of the title heap the table points into at draw time. This is a CPU-side TextureLookup: no T# search on the
  GPU and no SM 6.6 heap indexing, and it is exact for descriptors written through the API. The plan below (T# words
  in title memory, a GPU search) is kept for titles that write or copy descriptor words themselves, which R4 does not
  handle (their reads are misses).
- **Textures and storage images (T#):** a desktop SRV/UAV is needed. The shim creates it when the title creates the
  view through the API and records `(title address of the image, format, dims) -> heap index` in a sorted table, the
  same shape as `TitleRange`. A new `TextureLookup` helper finds the index from the T# words; the shader then uses
  SM 6.6 `ResourceDescriptorHeap[index]`. A T# with no recorded view is a lookup miss: sample returns zero and the
  miss is counted.
- **Samplers (S#):** decoded to `D3D12_SAMPLER_DESC` on the CPU when written through the API, cached, and indexed
  through `SamplerDescriptorHeap` the same way.
- **API-written descriptors** (`Create*View` into a console heap): the shim writes the hardware words the console
  shader expects into the title-visible heap memory **and** the desktop descriptor into the shadow heap. Writing
  hardware words needs their bit layout, which the public RDNA ISA documents.

### Pipelines and shaders

`Create*PipelineState` is where shader translation happens:

1. Hash each shader's bytecode plus the pipeline state the translation depends on. Look the hash up in the on-disk
   cache (`%LOCALAPPDATA%\XPortPC\cache\<title>\<hash>.dxil`). A hit skips to step 4.
2. Choose the input: if the bytecode carries a DXIL module that `tools/dxil_retarget.py` retargets and that uses no
   console-only intrinsic, retarget it (cheap, binds by root signature). Otherwise translate the gfx1013 program:
   `tools/pixel_aot.py` / `vertex_aot.py` / `compute_aot.py` -> HLSL -> DXC -> DXIL. Which input titles provide is a
   per-title census question (section 7).
3. A refusal from the converter (an unsupported form, a refused control-flow shape) fails the PSO with a logged reason
   naming the form. It does not substitute a different shader.
4. Create the desktop PSO with the translated root signature.

**Performance, honestly.** The converter is Python and DXC is slow; translating at PSO creation would stall the title for
seconds per pipeline. The path:

- **Now (R3-R5):** translate at creation, synchronously. Acceptable for test programs with a handful of pipelines.
- **Next:** an ahead-of-time pass. The first run of a title records each pipeline's inputs (bytecode hash and the
  state the translation needs) in the cache index; `x2w_aot_cache` translates the recorded set offline in parallel
  processes; later runs hit the cache. Misses still translate synchronously and are logged.
- **Later:** port the converter's lowering to C++ inside the graphics shim, checked against the Python converter on the
  whole draw-check suite and corpus (identical HLSL text, or identical bit-exact draws). Only then is creation-time
  translation fast enough for titles that create pipelines while running.

### Console-only features

- Features with a desktop equivalent (mesh shaders, DXR, sampler feedback, VRS, ExecuteIndirect) map to it.
- Features with none are logged and fail cleanly with the documented error code.
- **Raw command buffers.** If a title builds GPU command packets itself (in memory, not through API calls), there are no
  calls to translate. Pure translation cannot run that title, and we do not emulate the command processor. The game
  report detects it (draws in the frame with no draw calls through the API, or submissions of memory we never saw
  recorded) and reports the title as unsupported for that reason.

## 4. Memory

The console has one address space: a graphics allocation's CPU pointer is also its GPU virtual address, and titles
store those addresses in memory that shaders read. Desktop GPUs have their own address space and, on discrete parts,
their own memory.

What exists:

- `XMemAlloc` graphics types get their own `VirtualAlloc` region (`era_heap`), registered as GPU memory
  (`era_query`) and tracked by `era_title_gpu`.
- Once a device is attached (`X2WTitleGpuAttach`), each region gets a desktop alias without copies:
  `OpenExistingHeapFromAddress` plus one placed buffer (`era_gpu_alias`). CPU writes are seen by the GPU and GPU writes
  by the CPU once the GPU work completes.
- `era_title_va` maps title ranges to desktop GPU addresses. `X2WTitleGpuTranslate` / `X2WTitleGpuLocate` serve API
  calls; `X2WTitleGpuGetShaderView` packs the sorted ranges that `TitleLookup` searches in shaders.

**Recommended first approach: alias everything in system memory.** Every buffer the title creates in its memory is a
view of the alias, every title GPU address passed to an API call goes through `X2WTitleGpuTranslate`, every address a
shader reads from memory goes through `TitleLookup`. This is correct with no write tracking at all, because both sides
see the same bytes after fences. It is slow on discrete GPUs (all GPU traffic crosses PCIe), and that is accepted
until R5.

Textures cannot alias: desktop textures have opaque layouts, and the console layout is tiled. So:

- Textures, render targets and depth buffers are desktop `DEFAULT` resources in VRAM.
- The title's bytes for a texture are converted on upload (detiling; `tools/bc7_tiles.py` holds the first tiling code)
  and copied in.
- CPU writes to texture memory after creation are found by write tracking (below) and re-uploaded before the next
  submit that uses them.
- A shader that reads texture memory as a buffer (rare) misses in `TitleLookup` and is logged.

**After R5, performance:** promote hot buffers to VRAM. The candidates are buffers only the GPU writes (UAV targets) or
the CPU writes rarely (static vertex/index data). Each keeps a system-memory alias for CPU access. CPU writes are tracked
per 4 KiB page, by `MEM_WRITE_WATCH` (`GetWriteWatch`, set when `era_heap` allocates; whether
`OpenExistingHeapFromAddress` accepts such memory must be measured) or by guard pages and a vectored handler. Dirty
pages are copied to VRAM before each submit. GPU-written ranges the CPU reads (query results, readbacks) stay
aliased.

**Not modelled:** the console's page types and caching (the six graphics memory types are policy only, see
`era_heap`), and any GPU-side page table manipulation (tiled/reserved resources map to desktop reserved resources).

## 5. Threading and timing

Title CPU code runs natively, so most threading is just Windows. Differences to handle:

- **Core counts and affinity.** Titles may pin threads to fixed core masks for the console's core layout. The base
  shim remaps affinity masks and thread ideal processors onto the host's cores (modulo the host count, keeping
  distinct threads on distinct cores where possible) and logs each remap.
- **CPU features.** The console CPU is Zen 2. Instructions a host CPU lacks (for example AMD-only ones on an Intel host,
  or AVX2 on an old CPU) fault with `STATUS_ILLEGAL_INSTRUCTION`. A vectored handler in `x2w_launch`
  (`tools/x2w_cpu_trap.h`) performs a fixed set on the faulting thread's CONTEXT and resumes after the instruction:
  SHA-NI, CLZERO, RDPID, MONITORX/MWAITX (as a pause), SSE4a, RDPRU (MPERF and APERF read the TSC) and CLWB (as
  CLFLUSH). For anything else it records the module+RVA and the instruction's mnemonic (not its bytes) and lets the
  title crash. The run log lists the Zen 2 features the host lacks at startup and a count per trapped instruction at
  the end, since each trap costs an exception round trip. This is where the CPU lifters can fit (below).
- **Timers.** QPC frequency, GPU timestamp frequency and refresh rate differ; titles read them through APIs, which we
  answer with the host's values. Hard-coded assumptions show up as wrong pacing and are logged, not patched.
- **CPU-GPU synchronization.** Fences map 1:1. A title that polls memory the GPU writes works under aliasing (section
  4) once the GPU work has completed; it cannot see writes mid-submit.
- **Frame pacing.** Present intervals map to the DXGI swap chain with a waitable object; lifecycle events (suspend,
  constrain) are never raised.
- **Task queues.** Forwarded `XTaskQueue` uses the Windows thread pool, as on PC.

Where the CPU lifters fit. The `cpu_*_aot` tools translate source-built x64 functions to C++. A title that already runs
natively does not need them. Their only roles in this design:

1. Replacing a function that uses an instruction the host faults on, when the vectored handler is too slow (hot loops).
   The replacement is lifted from the title's own code at the user's site, never stored in the repo or a report.
2. Possibly, later, redirecting inlined API code (code the console library compiles into the title instead of calling
   an import) to our shim. Whether titles contain such code is measured first.

Until a title report shows either case, the lifters are frozen: kept building and tested, with no new instruction work.

## 6. Milestone ladder

The status site shows one number, the **furthest rung** whose exit criteria pass in CI (R1-R5) or in an owner
report (R6). Each rung has a source-built program in `tests/runtime/` that is a console-style title in the sense that
it imports our shim DLLs by their console-facing names and runs only under `x2w_launch`.

| Rung | Program does | Exit criteria (all must hold, WARP and hardware) |
|---|---|---|
| **R1** start and exit | allocates memory through `xmem.dll`, calls a missing import, exits | exits with the expected code under `x2w_launch`; machine-readable import report `x2w-imports.json` lists every import with route and implemented/stub/missing; first unimplemented call recorded with caller RVA; Windows loader refuses it (control) |
| **R2** clear and present | creates device, queue, swap chain, list through the graphics shim; clears; presents 3 frames | 3 presents succeed; readback of the back buffer equals the clear color; a wrong clear color fails (control); debug layer reports no errors |
| **R3** triangle | creates a PSO from gfx1013 vertex and pixel programs (assembled by llvm-mc, as today) | the PSO's shaders are translated at creation and written to the cache; second run hits the cache; frame equals the CPU reference bit for bit; a wrong reference fails |
| **R4** textures, constants, depth, several draws | textures created from tiled bytes, CBVs at title addresses, depth test, 3+ draws | frame equals the CPU reference; `TitleLookup` and `TextureLookup` miss counts are 0; remove one view and the miss is reported |
| **R5** compute and a frame loop | compute writes a buffer the next draw reads; 600 frames | frames equal the reference at sampled frames; cache hit rate 100% after frame 1; frame time measured and published (not gated) |
| **R6** real title, first frame | owner runs his title | owner reports the first present of a frame from the title's renderer, with a game report (section 7) showing it |

Today: the launcher test (`launch_check.py`) already starts and exits a source-built program with import lines on
stderr, so R1 is mostly there. Missing for R1: the JSON report, argument and caller logging in stubs, and the
first-unimplemented-call line. Furthest rung today: none.

R2 program: `tests/runtime/r2_clear.cpp` over the graphics shim skeleton in `d3d12_xs.dll` (work item 2; tests and
wrapped interfaces in [experiments.md](../experiments.md#graphics-shim-skeleton-runtime-rung-r2)). It runs directly,
not under `x2w_launch`, until `pe_map` maps implicit TLS.

R4 program: `tests/runtime/r4_scene.cpp`, over title descriptor heaps (`src/d3d12_xs_descriptors.h`) and draw-time
descriptor resolution (design choices and tests in
[experiments.md](../experiments.md#title-descriptor-heaps-textures-constants-and-depth-runtime-rung-r4)). Its exit
criteria pass on WARP and hardware except "textures created from tiled bytes": the console's texture upload path is
not public, so the scene uploads linear rows; detiling moves to R5 once an owner log shows the upload calls.

R3 program: `tests/runtime/r3_triangle.cpp`, with pipeline-time translation and the cache in
`src/d3d12_xs_pipeline.h` (work item 3; design choices and tests in
[experiments.md](../experiments.md#pipeline-time-translation-runtime-rung-r3)). Its shaders come in a console
bytecode container that our own tests define (`X2WShaderContainer`, `src/d3d12_xs_api.h`): the container real titles
use is not public and is learned from owner logs, then parsed by the same single function.

## 7. Game report

`x2w_report` is the tool the owner runs on his own titles, from his own copy. It produces one Markdown file and one
JSON file meant to be pasted or attached publicly. It has two parts.

**Static part** (reads the files; runs no title code):

- every imported DLL and symbol, with the route it would take and state `implemented` / `stub` / `missing`, grouped
  per DLL with counts; symbol names are API names and are fine to publish;
- PE facts: sections (names, sizes, flags), TLS template present, delay imports, exports count;
- shader and pipeline census, if the title ships shader files the tools can parse: count per stage; for gfx1013
  programs, the forms used and which are not covered (`site/status.json` covered set), as `tools/pso_readiness.py`
  and `tools/scan_unsupported_shaders.py` do now; whether a retargetable DXIL module is present.

**Run part** (`x2w_launch --report`):

- the import report and the first unimplemented call (function, arguments as integers, caller RVA);
- graphics: interfaces and vtable slots called with counts, PSOs created, translated, cache hits, refused (with the
  refused form or shape), `TitleLookup`/`TextureLookup` misses, frames presented, first frame time;
- the crash site if it ends abnormally: exception code, faulting module and RVA, the mnemonic at that RVA, stack as
  module+RVA list, the last 20 log lines;
- host: Windows build, CPU model and features, GPU, driver, commit of XPortPC.

**Never in a report**: code bytes, disassembly beyond one mnemonic, shader bytecode or ISA, HLSL generated from a title
shader, file contents, strings from the title's data, textures, screenshots of the title. Shader identity is a hash.
The report writer has an allow-list of fields; anything else is dropped, and `tests/game_report_check.py` runs it on a
source-built program with planted strings and code bytes and fails if any appears in the output.

## 8. What stops or shrinks

- **Shader-form chasing becomes background work driven by real pipeline hits.** Forms are added when a game report lists
  them as blocking a pipeline, ordered by how many reported pipelines they block, not by corpus share. The corpus and
  the per-form draw checks stay as the regression suite, and every new form keeps the existing rules (bit-exact draw,
  wrong-reference control, LLVM round trip).
- **Stage and control-flow cards** (vertex V-4 onward, compute C-5 onward, CF-2f to CF-2h) continue only where a rung
  or a report needs them. R3 needs V-1/V-2 drawing on both adapters; R5 needs C-1 to C-4.
- **Archive and offline-inventory tools** (shader archives, resource probes) stop growing. The pipeline-creation log
  replaces archive scanning as the source of which shaders matter: it lists exactly what the title creates.
- **CPU lifters** are frozen (section 5).
- **New work** takes the freed time: launcher gaps (TLS, PEB), the graphics shim, `TextureLookup`, the cache and AOT
  pass, the game report.

## First work items

1. **R1 report.** `x2w_launch --report FILE`: JSON import report (per DLL, route, implemented/stub/missing), stubs
   logging their first calls' four argument registers and caller RVA, `x2w_unimplemented()` for shims, the
   first-unimplemented-call line. Extend `tests/native/launch_check.py` to check the JSON. Then implicit TLS in
   `pe_map` (turns `cpu_native_tls_value` from expected refusal to match).
2. **Graphics shim skeleton for R2.** A desktop DLL under the graphics name exporting device creation, wrapping
   device/queue/allocator/list/fence/swap chain over desktop D3D12 in public method order with logging thunks for
   unknown slots and IIDs; attaches the device to `era_title_gpu`. Test `tests/runtime/r2_clear.cpp` (clear, present,
   readback, wrong-color control) on WARP and hardware.
3. **Pipeline-time translation and cache for R3.** `CreateGraphicsPipelineState` in the shim calls the converter
   out of process (`python tools/vertex_aot.py` / `pixel_aot.py` + DXC) keyed by bytecode hash, writes the DXIL cache,
   and logs refusals; `tests/runtime/r3_triangle.cpp` draws a triangle from llvm-mc-assembled gfx1013 programs and
   checks the frame against the CPU reference and the second-run cache hit.
