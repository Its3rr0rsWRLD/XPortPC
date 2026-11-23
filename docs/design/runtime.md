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
  unwinding work through mapped frames), gives implicit TLS data (`__declspec(thread)`, `thread_local`) a loader-owned
  index through a carrier DLL, and runs TLS callbacks in order, for a started EXE also on thread attach and detach and
  on process detach. Title code runs unchanged.
- The title sees itself as the process image: `x2w_launch` binds its `GetModuleHandle{A,W,ExA,ExW}` and
  `GetModuleFileName{A,W}` imports to replacements that answer for the mapped images, and sets
  `PEB->ImageBaseAddress` to the title while it runs (`--host-identity` turns both off).
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
| Closed: implicit TLS data (`native_launch_tls`, `native_launch_tls_crt`, `cpu_native_tls_value`) | Was: any title with `thread_local` data failed to map | Carrier DLL per image: ntdll owns the index and every thread's block (`docs/experiments.md`, "Implicit TLS data and module identity under x2w_launch") |
| Closed for the title's imports: `GetModuleHandle(NULL)`, `GetModuleFileName(NULL)`, PEB image base (`native_launch_identity`) | Was: resource loads and self-lookup went to `x2w_launch.exe` | Import replacements plus PEB `ImageBaseAddress`; the loader's module list, `GetProcAddress`ed pointers to these functions and `GetCommandLine` still name the launcher |
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

Measured on the five stand-in GDK samples (Microsoft's public Xbox-GDK-Samples built for PC, 2026-11-22):
every one loads `xgameruntime.dll` and asks it only for `QueryApiImpl`, `InitializeApiImpl`,
`InitializeApiImplEx`, `InitializeApiImplEx2`, `XErrorReport` and `UninitializeApiImpl`. The PC runtime's
boundary is therefore an interface query, not the flat API names, and no public document describes those
interfaces, so the generated shims cannot serve PC GDK builds; the launcher passes names a shim lacks to the
Windows DLL of that name (`windows-fallback`) so such programs keep running and their logs stay useful.
Whether console builds import the flat names is what the first console report will show.

### The Gaming Runtime gateway (PC GDK builds)

`shims\x2w_xgr.dll` (`src/xgr`, `cmake/x2w_xgr.cmake`) is an `xgameruntime.dll` with the six entry points a
PC GDK title's static `xgameruntime.lib` resolves: `InitializeApiImpl`, `InitializeApiImplEx`,
`InitializeApiImplEx2(gdkVer, gsVer, mode, options)`, `UninitializeApiImpl`, `QueryApiImpl(clsid, iid, out)` and
`XErrorReport`. Each flat call is `QueryApiImpl(CLSID_XFooImpl, IID)` followed by a vtable call (IUnknown, then the
family's functions in a fixed order) and `Release`. `x2w_launch --xgr MODE` (or `X2W_XGR`) loads the gateway for
the title's `xgameruntime.dll`, with no `windows-fallback`:

- `ours`: the classes, interfaces and slots in `tools/xgr/interfaces.toml` forward into x2w_gdk.dll's family
  code (wrappers generated by `tools/xgr_gen.py` from the table and the shimgen specs; functions x2w_gdk lacks are in
  `src/xgr/xgr_extra.cpp`). An unknown CLSID or IID returns `0x80070032` and is logged with its caller.
- `trace`: queries go to Windows' own `xgameruntime.dll`; every returned interface is wrapped in a proxy whose
  slots log index, arguments, result and caller, then call the real slot.
- `record`: every query gets a dummy object whose slots log and return `E_NOTIMPL`.

Every object's vtable is a table of 256 logging thunks (`xgr_thunks.asm`), so an unknown slot logs its index and
returns `E_NOTIMPL` instead of jumping into unmapped memory. The table's facts come only from our own evidence: the
`xgameruntime.lib` thunks linked into our builds of Microsoft's public samples (each loads the CLSID, and the IID
when it differs, before `QueryApiImpl`, then `mov rax,[rax+8*slot]` before a CFG call, then slot 2), read by
`tools/pc_jobs/run_xgr.ps1` through the builds' own PDBs, and trace runs. XTaskQueue/XAsync stay x2w_gdk's
hand-written code rather than libHttpClient's MIT implementation: it already serves the generated shims and the
gateway from one process-wide copy, and vendoring libHttpClient's ~5.4k-line task library would mean replacing
that module; libHttpClient's source remains the reference if behaviour differs.

PC GDK samples are built with /GL + /LTCG, so their code reads implicit TLS as `ThreadLocalStoragePointer[0]`
without `_tls_index`; `x2w_launch` therefore aliases slot 0 of every thread to the program's TLS block
(`tls-slot0` in the run log).

### Console audio hardware: silent

`chad.dll` (XDsp*), `xapu.dll` (XApu*) and `acphal.dll` (AcpHal*, Apu*) drive the console's audio hardware. Nothing
about them is public, so their shims (specs `tools/shimgen/specs/{chad,xapu,acphal}.toml`, code in `src/gdk/gdk_console.cpp`)
are logged stubs that make a title carry on without sound; the title's audio then goes through the XAudio2 path in
`x2w_sys`, or nowhere. Every assumption:

- Each function takes six register-width arguments (only rcx, rdx, r8 and r9 are logged; the first eight calls of each
  function are logged with their arguments, then one note). The real signatures are unknown; nothing is dereferenced
  without a `VirtualQuery` check.
- Return value 0 (`S_OK`). `XApuGetResultCount` returns 0 and `XApuDequeueResult` returns 0 and writes nothing: the
  hardware never produces a result.
- `XDspConnectWithMaximumStreamLimit`, `XApuConnect`, `AcpHalCreate` and `AcpHalAllocateShapeContexts` write a fresh
  non-null handle (a zeroed 256-byte heap block, safe to read as zeros) into the first argument that points to writable
  memory whose first 8 bytes are zero (an output slot). An argument that is small, null, read-only or already non-zero
  is never written.
- `ApuAlloc` and `ApuCreateHeap` return the address of a zeroed `VirtualAlloc` block, tracked in a table; the size is the
  first argument in (0, 1 GiB] that is not a tracked block (64 KiB when none is). `ApuFree` releases a tracked block
  named by either of the first two arguments. `ApuIsVirtualAddressValid` is TRUE for an address inside a tracked block.
  `ApuMapApuAddress` and `ApuMapVirtualAddress` return their first argument (identity map).

`xcrdapi.dll`'s `DStorageGetFactory(REFIID, void**)` has the public DirectStorage signature and forwards to
`x2w_sys.dll`'s `X2wDStorageGetFactory` (loaded from the shim folder if the launcher has not loaded it), so it returns
the host DirectStorage factory or the fallback status described in `docs/design/system-libs.md`.

`xg_xs.dll` (texture layout): `XGCreateTextureComputer` writes a logging COM-style object to its second argument
(assumed `(desc, &out)`, as the public XG address computers): `IUnknown` plus 64 slots, each logging its index and
arguments and returning `E_NOTIMPL`; `E_POINTER` when the output is not writable. `XGSuggestSwizzleMode` returns 0, taken
as the linear/standard mode, the one a title can always read back without detiling.

xmem additions (`src/xmem_title.cpp`; the reference pages are login-gated, so these are assumptions too):
`XMemVirtualAlloc` is `VirtualAlloc`-like, reads any allocation-type bit `VirtualAlloc` lacks as XMEM_MAPPABLE or
64 KiB pages (stripped, size rounded to 64 KiB) and makes a plain reservation that `XMemMapPhysicalPages` adopts;
`XMemMapPhysicalPagesScatter(addresses, count, pages)` is `MapUserPhysicalPagesScatter`-like, one 64 KiB page per entry
(a null array or a zero entry unmaps, so physical page 0 cannot be mapped by it); `XMemTransferMemory` logs its
arguments and returns TRUE without moving anything; `XMemIsToolsMemAvailable` returns FALSE. GPU-visible memory still
enters through `XMemAlloc` and physical mappings (the title GPU registry); committed `XMemVirtualAlloc` memory is not
registered.

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
| device | `ID3D12Device` through `ID3D12Device10` + debug layer in dev builds | create calls translated one by one; version N is answered only when the desktop device implements it; `QueryInterface` of an unknown IID is logged and fails with `E_NOINTERFACE` |
| command queue | `ID3D12CommandQueue` | `ExecuteCommandLists` unwraps lists; fences map 1:1; present goes through a DXGI swap chain the shim owns |
| command allocator / list | same; lists through `ID3D12GraphicsCommandList7` | each record call becomes the desktop call with title GPU addresses translated (`X2WTitleGpuTranslate`), wrapped resources unwrapped (also inside barriers, copy locations and render-pass resolves) and descriptors remapped |
| pipeline state | desktop PSO | built from translated shaders (below); cached |
| root signature | desktop root signature | console blob deserialized, console-only flags dropped, converter parameters appended |
| descriptor heap | shader-visible desktop heap + shadow table | below |
| resource / heap | wrapped `ID3D12Resource2` / `ID3D12Heap1` over the desktop objects; buffers in title memory are aliases (section 4) | a buffer's `GetGPUVirtualAddress` is a title address (section 4, "Buffers the title creates") |
| command signature | wrapped `ID3D12CommandSignature` | keeps the record layout for `ExecuteIndirect` (below) |

Vtable slots. The wrappers use the public desktop method order. That the console interfaces share this order is an
assumption that the first owner logs test: every slot past the public ones, and every slot at all in dev builds, first
goes through a logging thunk (interface, slot index, caller RVA, four argument registers). A title calling a slot we
have not implemented stops with that line as its first unimplemented call.

### Console device creation

A real title imports `d3d12_xs.dll!D3D12XboxCreateDevice` and `d3d12_xs.dll!D3D12ConfigureVirtualMemoryX` by name.
Neither is publicly documented, so their contracts are **assumptions**, kept in one file
(`src/d3d12_xs_xbox.cpp`) and checked against the next owner log:

- Both take their arguments as raw integers: the four argument registers and the first four stack slots. Every call
  (the first 16 per export) logs one line with the caller (`module+0xRVA`; `image@0xBASE+0xRVA` for an image the
  loader does not name, such as a title mapped by `pe_map`) and all eight values, then one line per argument that is a
  committed, readable pointer (checked with `VirtualQuery`) with up to its first 64 bytes in hex. Stack slots the caller
  did not pass are logged as whatever the caller's frame holds there.
- `D3D12XboxCreateDevice`, by analogy with the public `D3D12CreateDevice(adapter, minimum level, REFIID, void**)`: the
  first argument pointing at a known device IID (`ID3D12Device` through `ID3D12Device10`, or `IUnknown`), and the first
  writable, 8-byte-aligned pointer argument after it, are taken as the requested IID and the `void**` that receives the
  device. The device is the one our `D3D12CreateDevice` export hands out (desktop default adapter, WARP when that fails;
  the adapter and the creation-parameters struct, if the title passes them, are logged but not read), wrapped and
  queried for that IID. The chosen mapping is logged as `d3d12x-create-device contract iid=<arg>(<interface>)
  out=<arg>(void**) adapter=<default|warp> -> <HRESULT>`. With no such pair it returns `E_NOTIMPL` and logs
  `d3d12x-create-device unknown-contract`, so the owner's next log shows the arguments to read the real contract from.
- `D3D12ConfigureVirtualMemoryX` is logged the same way and returns `S_OK` with no effect: desktop D3D12 has no
  virtual-memory configuration for the shim to forward to.

Any other export a title asks `d3d12_xs.dll` for by name can be routed to `X2WGfxUnknownExport(name)`
(`src/d3d12_xs_api.h`): one stub per distinct name that logs `d3d12_xs!<name>`, its caller and four argument registers
on its first call (event `X2W_GFX_EVENT_UNKNOWN_EXPORT`) and returns `E_NOTIMPL`. The launcher's own stub for a name a
shim lacks returns 0, which reads as `S_OK` to an HRESULT caller; routing `d3d12_xs.dll` misses through
`X2WGfxUnknownExport` instead is a launcher change.

### Descriptors

Converted shaders read descriptors as hardware words (V#, T#, S#) from memory, as the console GPU does; the converter
already tracks them (`tools/pixel_aot_ops/bindings.py`, [pixel-bindings.md](pixel-bindings.md)).

- **Buffers (V#):** the converted shader decodes base and range from the V# words and loads (and stores) through
  `TitleLookup` (`src/title_va_lookup.hlsli`) at the title GPU address. No desktop descriptor per buffer is needed.
  As built in R4b, a V# read from a descriptor table gets its words from the buffer view the title created through
  the API, encoded when the view is written (base = the view's title GPU address); the shim passes the words of a
  draw's buffer reads in the frame words (from byte 512), or the title's own V# words when it wrote hardware words
  into the table (R6). Typed loads are exact for views with a gfx10 buffer format and typed stores for R32_UINT and
  R32_SINT views; a typed access through any other view skips the draw.
- **As built in R4:** the translator resolves every descriptor load to (descriptor table, byte offset) at
  translation time, since the converter already tracks descriptor loads by key, and the shim resolves that to the
  slot of the title heap the table points into at draw time. This is a CPU-side TextureLookup: no T# search on the
  GPU and no SM 6.6 heap indexing.
- **Descriptors written as hardware words (R6, built).** Consoles expose descriptor memory directly, so titles write
  T#, S# and V# words into heap memory themselves, or copy them with `memcpy`. The shim lets the words in title memory
  decide, at draw and dispatch time, on the CPU (`src/d3d12_xs_descriptors.h`, `src/gfx10_descriptors.h`):
  - An API write (`Create*View`, `CreateSampler`) still creates the desktop descriptor in the shadow heap, and now also
    writes *marker words* into the slot's title memory: a reserved descriptor type (T# `TYPE` 4, V# `TYPE` 1) naming
    the slot and its generation. A `memcpy` of the 32 bytes copies a reference to that view; a later rewrite of the
    source slot makes the copy a miss. `CopyDescriptors*` copies the bytes too (an API view gets its own marker).
  - Any other non-zero words are hardware words and are decoded with the GFX10.3 field layouts of Mesa's register
    database (`src/amd/registers/gfx10-rsrc.json`, `gfx6.json`; MIT), as Mesa's `ac_descriptors.c` builds them. A
    T# becomes a desktop 2D texture: base address (word 0 holds address bits 39:8 with the pipe/bank XOR ORed into
    the low bits, `ac_set_mutable_tex_desc_fields`; taken out for the `_X`/`_T` swizzle modes by block size),
    `FORMAT` (58 formats with a DXGI equivalent, including BC1-BC7 and the B5G6R5-style ones with their channel
    order), width/height, `MAX_MIP` + 1 levels in the resource and `BASE_LEVEL`..`LAST_LEVEL` in the SRV, `MIN_LOD`
    as `ResourceMinLODClamp`, `SW_MODE` and the XOR for the detiler (`x2w_gfx10_detile`, section 4), and `DST_SEL`
    as the SRV's component mapping. The title's bytes (from the base address, addrlib's surface size, read on the
    CPU at the title address, which is the memory the TitleLookup alias maps) are hashed; textures are cached by
    the T# words and that hash, created and filled on a shim copy queue (synchronously, on a cache miss), and
    recycled with the descriptor blocks' fences (1024 entries). An S# becomes a cached desktop sampler (address
    modes, min/mag/mip filters, anisotropy, min/max reduction, LOD range and bias, border type, comparison function).
    A constant-buffer V# becomes a root CBV at the alias of its base address, after a check that `num_records` (times
    the stride) lies in one title allocation. A compute buffer V# is copied into the dispatch's frame words, where
    the translated program applies its range check itself.
  - Refused with a reason and counted as a TextureLookup miss: T# types other than 2D, DCC compression, array slices,
    a custom linear pitch, formats without a DXGI equivalent; S# half-border clamps, border colours from the table,
    unnormalized coordinates, degamma overrides, a secondary LOD bias; V# swizzling or `ADD_TID`.
  - Not modelled (accepted): `BC_SWIZZLE`, `TRUNC_COORD`, anisotropy thresholds and biases, `PERF_*` hints,
    `MIP_POINT_PRECLAMP`; `MIP_FILTER_NONE` is point between levels with the LOD clamped to `MIN_LOD`. The texture is
    read when the draw is recorded, not when the GPU executes it; a title that writes texture memory between
    recording and submission is not seen. Constant reads past a V#'s `num_records` read the alias, not zero.
- **Inline samplers (R6, built):** an S# a program builds with `s_mov` is reported by the translator with its words
  and decoded when the pipeline is created (a sampler without a desktop equivalent refuses the pipeline); draws bind
  the cached desktop sampler in its slot.
- **Compute tables (R6, built):** compute containers may bind descriptor tables; T#s, an S# and buffer V#s are bound
  as above, constant-buffer V#s and storage images read from a table are refused.
- **Root signature budget (R6):** the push words, the TitleLookup range count, the base vertex and start instance and
  the vertex and pixel stages' buffer V# words (R4b, from byte 512) are one constant buffer, the *frame words* (64
  words and 3 more, then 128 V# words; `FrameWords`), written per draw or dispatch into a 1024-byte slice of the
  shim's upload ring (256 chunks of 64 KiB, recycled with the same fences as the descriptor blocks) and bound as one
  root CBV. The converter parameters take 17 of the 64 root DWORDs (they took 46; pixel constant slots 2 and 3 add
  4), leaving 47 for the title's own.

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

**Performance, honestly.** The converter is Python and DXC is slow to start; one process each per shader cost about
0.39 s per shader cold on the owner's PC (R3), almost all of it start-up. The path:

- **Done: a translator service.** `d3d12_xs.dll` keeps a pool of `tools/pso_service.py` processes
  (`src/d3d12_xs_translator.h`): each has the converter imported once and DXC's library (`IDxcCompiler3`, the
  `dxcompiler.dll` beside `dxc.exe`) loaded in process, and takes framed requests over its stdin/stdout. The first is
  started at device creation; the pool grows while requests wait (at most cores - 1, 8 at most). A pipeline's shaders
  and pipelines from several title threads translate in parallel. If no service can run, or one fails mid-request, the
  shim falls back to one `tools/pso_translate.py` process per shader. Output, cache format and keys are unchanged:
  the paths write byte-identical DXIL and HLSL (`runtime_r3_translator_paths_warp`, `runtime_r3_translator_bench`).
- **Done: ahead of time.** The shim records every console shader it sees in the title's cache directory
  (`manifest.txt`, `inputs\`, `translator.json`; `tools/pso_cache.py`). `tools/precompile_cache.py <title>`
  translates the recorded set on all cores, recomputing each key with the current converter fingerprint, so the next
  launch is all cache hits (README, "Shader cache for a title"). `X2W_TRANSLATE=defer` records without translating
  (the pipeline fails), for a fast recording run. Misses still translate at creation.
- **Later:** port the converter's lowering to C++ inside the graphics shim, checked against the Python converter on the
  whole draw-check suite and corpus (identical HLSL text, or identical bit-exact draws). Only then is creation-time
  translation of a title that creates pipelines while running free of a process round trip.

Measured numbers are in [experiments.md](../experiments.md#translator-service-and-ahead-of-time-cache-runtime-rung-r3).

**Pixel input layout.** A pixel program's input VGPRs are set by SPI_PS_INPUT_ENA and SPI_PS_INPUT_ADDR
([pixel-bindings.md](pixel-bindings.md#input-vgprs)). Container version 2 (`X2W_SHADER_CONTAINER_VERSION`,
`src/d3d12_xs_api.h`) lets a pixel container point `stage_info_offset` at an `X2WShaderPixelInfo` record holding both
words (ADDR 0 meaning equal to ENA); `parse_container` refuses bits above 15 as malformed and leaves the rest of the
check (ENA a subset of ADDR, a barycentric input) to the translator, which refuses with its reason. The shim adds
`"ps_input_ena"` (and `"ps_input_addr"` when it differs) to the pixel roles only when the layout is not the default,
persp_center alone, so the roles, keys and input ids of every container without a record, and of every version 1
container, are unchanged. The roles are part of the key and of the manifest's input id, so the translator service and
`tools/precompile_cache.py` receive the layout with them (`tools/pso_translate.py` passes it to `PixelBindings`); the
converter fingerprint's tag is `x2w-pso-translate-6` in the shim and in `tools/pso_cache.py`. A version 1 container
with a nonzero pixel `stage_info_offset` is still malformed. Tests: `tests/runtime/psin_scene.cpp` (a pixel program
reading pos_x, pos_y, pos_z and front_face, two triangles of either facing at depths 0.25 and 0.75 into an
R32G32B32A32_FLOAT target, bit for bit against a CPU reference; wrong references for the pixel corner, a flipped
face, z ignored and w for z; refused controls for a version 1 container, an ADDR that also reserves pos_w, a version 1
record and high bits), `tests/runtime/psin_programs_check.py` (the program and the roles offline). R3 keeps writing
version 1 containers.

### The rest of the public desktop surface

Titles query later interface versions and call their methods, so the wrappers cover the public desktop D3D12 surface in
public method order: `ID3D12Device1` to `ID3D12Device10` (79 slots), `ID3D12GraphicsCommandList1` to
`ID3D12GraphicsCommandList7` (81 slots), `ID3D12Resource2` (17), `ID3D12Heap1` (10), `ID3D12CommandSignature` (8).
Slots past those still go to the logging thunks. A method of a version the desktop object lacks is logged once and
returns `E_NOTIMPL` (or nothing). Everything forwards with arguments unwrapped and GPU addresses translated, except:

| Entry | Handling |
|---|---|
| `ID3D12Device2::CreatePipelineState` | the stream is walked (every subobject type through `RASTERIZER2`); desktop bytecode is passed through; console VS/PS or CS containers go through the same translation as `CreateGraphicsPipelineState`/`CreateComputePipelineState` and the stream is copied with the DXIL in place (input layout emptied), keeping every other subobject and default; console mesh or amplification shaders and console shaders with a serialized root signature are **refused** (`E_NOTIMPL`) |
| `ExecuteIndirect` | records without address fields run in place; records with vertex/index buffer views or root CBV/SRV/UAV addresses are rewritten on the GPU first (below); indirect `DispatchRays` and indirect commands of a translated pipeline are **refused** |
| `CreatePipelineLibrary` | **refused** with `DXGI_ERROR_UNSUPPORTED` (libraries load pipelines by description, bypassing translation; drivers may refuse them the same way) |
| `CreateMetaCommand` | **refused** with `E_NOTIMPL` (driver-defined parameters may hold GPU addresses) |
| `BuildRaytracingAccelerationStructure` | addresses in the description and bottom-level geometry translated on the CPU; a top-level build with instances is **refused** (its instance descriptions in GPU memory hold bottom-level title addresses) |
| `DispatchRays` | table addresses translated; a state object with local root signatures is **refused** (shader records may hold title addresses or descriptor handles) |
| `CreateSamplerFeedbackUnorderedAccessView` into a title heap | **refused** (no slot kind yet) |
| `WriteBufferImmediate`, `SOSetTargets`, acceleration-structure SRVs, postbuild info, AS copies | destination addresses translated |
| `BeginEvent`/`EndEvent`/`SetMarker` (PIX) | forwarded |

**ExecuteIndirect with title addresses** (`src/d3d12_xs_indirect.h`). The argument records a title writes (often from
the GPU) hold title GPU addresses. Before the desktop call the shim records a compute pass
(`src/d3d12_xs_indirect.hlsl`, embedded at build time) that copies the records the argument buffer holds into a buffer
of its own and translates every address field through a snapshot of all translated ranges (title begin, end, desktop
begin; `X2WTitleGpuGetTranslations`); an address no range holds is copied unchanged, as for API calls. The desktop
`ExecuteIndirect` reads the copy, with the title's count buffer. The pass restores the pipeline, the compute root
signature and its arguments, and predication afterwards. It needs a dispatch, so it is refused in bundles and render
passes. Barriers: none for an UPLOAD argument buffer; otherwise legacy `INDIRECT_ARGUMENT` <-> `NON_PIXEL_SHADER_RESOURCE`
transitions (the argument buffer must be in exactly `INDIRECT_ARGUMENT`), or enhanced buffer barriers once the list has
used `Barrier`. The copies are held by the command allocator and reused after its `Reset`.

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

What exists (the title memory layer, `src/xmem_title.h`; details and measurements in
[experiments.md](../experiments.md#title-memory-layer)):

- `XMemAlloc`/`XMemFree` go through replaceable routines (`XMemSetAllocationHooks`, `XMemAllocDefault`,
  `XMemFreeDefault`) and read the ERA attribute word: heap memory from the CRT (`era_heap`); every other defined
  memory type page-backed with its page size (4 KB, 64 KB, 4 MB) and alignment, placed in a graphics or system
  address window (`VirtualAlloc2` address requirements, or placeholders reserved over the windows when titles need
  fixed ranges), optionally on large pages and with `MEM_WRITE_WATCH`. Title physical pages
  (`XMemAllocatePhysicalPages` / `XMemMapPhysicalPages`) are views of a pagefile section in 64 KiB placeholders.
- GPU-visible allocations are registered with `era_title_gpu` (and `era_query`). By default they are carved from a
  few committed arenas, each one backing; a backing (arena, standalone allocation, adopted hook memory or the
  physical pool) gets one desktop alias once a device is attached (`X2WTitleGpuAttach`):
  `OpenExistingHeapFromAddress` or `OpenExistingHeapFromFileMapping` plus one placed buffer (`era_gpu_alias`). CPU
  writes are seen by the GPU and GPU writes by the CPU once the GPU work completes. Opening the heap locks the whole
  backing in memory (measured).
- `era_title_va` maps each allocation's range to desktop GPU addresses. `X2WTitleGpuTranslate` / `X2WTitleGpuLocate`
  serve API calls; `X2WTitleGpuGetShaderView` packs the sorted ranges that `TitleLookup` searches in shaders, each
  with its slot and its offset in the slot's buffer, so any number of allocations needs at most one slot per
  backing (the converter has eight).

**Recommended first approach: alias everything in system memory.** Every buffer the title creates in its memory is a
view of the alias, every title GPU address passed to an API call goes through `X2WTitleGpuTranslate`, every address a
shader reads from memory goes through `TitleLookup`. This is correct with no write tracking at all, because both sides
see the same bytes after fences. It is slow on discrete GPUs (all GPU traffic crosses PCIe), and that is accepted
until R5.

Textures cannot alias: desktop textures have opaque layouts, and the console layout is tiled. So:

- Textures, render targets and depth buffers are desktop `DEFAULT` resources in VRAM.
- The title's bytes for a texture are converted on upload (detiling, below) and copied in.
- CPU writes to texture memory after creation are found by write tracking (below) and re-uploaded before the next
  submit that uses them.
- A shader that reads texture memory as a buffer (rare) misses in `TitleLookup` and is logged.

### Textures: detiling

The console GPU reads textures in its hardware tiled layouts (swizzle modes). The desktop texture's layout is the
driver's, so the shim converts the title's bytes to linear rows on upload. The conversion is a port of AMD's addrlib as
published in Mesa (`src/amd/addrlib`, MIT; Mesa 26.2.6), the library Mesa's RADV and radeonsi use to lay out RDNA2
textures:

- `src/gfx10_swizzle_pattern.h`: addrlib's GFX10/GFX10.3 swizzle-pattern tables, unchanged (the oracle check below
  verifies them byte for byte against the pinned file).
- `src/gfx10_addr.h` / `.cpp`: surface layout (`ComputeLayout`: block size, padding, mip offsets, mip tail placement)
  and element addressing (`ElementOffset`), ported from `gfx10addrlib.cpp` and `addrlib2.cpp`.
- `src/gfx10_detile.h` / `.cpp`: the CPU detiler (and the inverse, tiling). No D3D12 types, so it builds and is tested
  on Linux against addrlib itself. Static library `x2w_gfx10_detile`.

**Entry point.** One call per texture:

```cpp
bool x2w::gfx10::DetileToFootprints(const Config& config, const Surface& surface,
                                    const void* tiled, std::size_t tiled_size,      // title bytes from the base
                                    void* upload, std::size_t upload_size,          // mapped upload buffer
                                    const Footprint* footprints, std::uint32_t count, // GetCopyableFootprints
                                    std::string* error);
```

- `Config`: the GPU's `GB_ADDR_CONFIG` (pipes, packers; pipe interleave must be 256 B) and `rb_plus` (true for
  GFX10.3/RDNA2, which selects addrlib's RB+ tables; false for GFX10.1).
- `Surface`: 2D (also arrays and cubes) or 3D; swizzle mode (the hardware `SW_MODE` value, addrlib's
  `AddrSwizzleMode`); element size 1-16 bytes and element size in pixels (4x4 for BC1-BC7); mip-0 size; array size
  or depth; mip count; the descriptor's pipe/bank XOR.
- `footprints`: `D3D12_PLACED_SUBRESOURCE_FOOTPRINT` values (offset, width, height, depth, row pitch) of the desktop
  texture, one per subresource in D3D12 order (mip + slice * mips). Each must match the subresource's size in pixels;
  then the call fills every footprint, and the shim issues one `CopyTextureRegion` per subresource (or passes the
  same data to `UpdateSubresources`).
- It returns false, with a reason, for a surface addrlib rejects or this port does not cover, `tiled_size` smaller
  than the surface (addrlib's `surfSize`), a footprint that does not match, or a footprint that does not fit in `upload_size` (sized as
  `GetCopyableFootprints` sizes it: the last row of a subresource ends at its last element, not at the row pitch).
  It never reads outside `tiled` or writes outside `upload`.

Modes covered: `SW_LINEAR`, `SW_256B_S/D`, `SW_4KB_S/D`, `SW_4KB_S_X/D_X`, `SW_64KB_S/D`, `SW_64KB_S_T/D_T`,
`SW_64KB_Z_X/S_X/D_X/R_X`, and on GFX10.3 `SW_VAR_Z_X/R_X`: every mode addrlib has a swizzle pattern for on these
parts (`SW_4KB_R_X` has none and is refused). 3D surfaces use the thick layouts addrlib uses for 3D S/D modes and the
thin ones for Z/R. Pipe/bank XOR, mip tails and block-compressed formats are included. Not covered: MSAA, quad-buffer
stereo, 1D resources, 96-bit linear formats, a linear pitch other than addrlib's 256-byte alignment, and DCC (a
DCC-compressed texture's bytes are not plain texels; its metadata is not decoded).

Assumptions, to be checked against the owner's logs (call names, argument values, never data):

1. The console GPU follows addrlib's GFX10.3 rules with some `GB_ADDR_CONFIG`. The value is not known; the shader
   ISA target (gfx1013) does not settle RB+ either way. Both rule sets and every pipe/packer combination addrlib's
   tables cover are tested, so the choice is a configuration value, not code. Where a title asks the API for a
   texture's size or alignment, the logged answers constrain the configuration; otherwise it is a per-title setting.
2. A texture's bytes start at its base address in title memory and span addrlib's `surfSize`, mips smallest-first as
   addrlib lays them out; array slices are `sliceSize` apart.
3. The upload calls are not known yet. What the shim needs from them is the `Surface` fields (from the texture's
   creation parameters or its T# words: format, size, mip count, `SW_MODE`, pipe/bank XOR) and the base address.
   Today the entry point is called by tests only.
4. A texture written after creation (by the CPU) is re-detiled whole on the next upload; finer tracking can come later.

Tests:

| Test | Where | What |
|---|---|---|
| `tests/gfx10_addr_oracle_check.py` | Linux/macOS | builds addrlib from the pinned Mesa tarball and compares, for 21 configurations (all 17 GFX10.3 pipe/packer combinations addrlib's tables cover, Navi10 at 4/8/16 pipes, Navi14), 2D and 3D, 17 modes, 12 formats (5 element sizes, BC1-BC7), 16 sizes and 1/3/full mips: every surface's layout, 61 million random and corner element addresses (`Addr2ComputeSurfaceAddrFromCoord`), and whole-surface tiling and detiling against `Addr2CopyMemToSurface`/`Addr2CopySurfaceToMem` (663 thousand subresources); a negative control (wrong RB+ setting) must mismatch |
| `gfx10_detile_roundtrip` | ctest, CPU | tile then detile through D3D12-shaped footprints is the identity; tiled bytes equal an element-by-element `ElementOffset` reference; no two elements share an address; a flipped tiled byte changes exactly one output byte; wrong footprints, short input and unsupported modes are refused |
| `runtime_r4_scene_tiled_*`, `runtime_r4_wrong_swizzle_*` | ctest, GPU | R4's two textures come from GFX10.3 tiled bytes in title memory (`SW_64KB_R_X` with 4 mips, mip 0 in the tail, and `SW_4KB_S_X`, both with a pipe/bank XOR), detiled into the desktop textures' footprints and sampled: the frame equals the CPU reference bit for bit. Control: texture 0 detiled as `SW_64KB_S_X` must differ |
| `runtime_r4_detile_upload_*` | ctest, GPU | 11 surfaces (2D, arrays, 3D; R8 to RGBA32, BC1/BC4/BC7; linear, 256 B, 4 KiB and 64 KiB modes) detiled from title memory into `GetCopyableFootprints`, copied in through the shim, read back and compared element for element. Control: a wrong pipe/bank XOR must differ |

Speed: about 2 GB/s for a 4096x4096 RGBA8 mip chain on one CPU core (Linux container); BC7 is faster per byte. A
compute-shader detiler is not built: the CPU path keeps the entry point the same, and a GPU path can replace its body
if upload time matters.

**After R5, performance:** promote hot buffers to VRAM. The candidates are buffers only the GPU writes (UAV targets) or
the CPU writes rarely (static vertex/index data). Each keeps a system-memory alias for CPU access. CPU writes are tracked
per 4 KiB page, by `MEM_WRITE_WATCH` (`X2W_XMEM_WRITE_WATCH=1` and `X2WXMemCollectWrites`;
`OpenExistingHeapFromAddress` accepts such memory, measured on WARP and an RTX 4070 Ti) or by guard pages and a
vectored handler. Dirty
pages are copied to VRAM before each submit. GPU-written ranges the CPU reads (query results, readbacks) stay
aliased.

**Buffers the title creates through the device** (`src/d3d12_xs_resources.h`). A title stores the
`GetGPUVirtualAddress` of its buffers in memory that shaders and indirect records read, so that address must be a title
address that the same translation serves as XMem memory. Decided with the memory registry: every buffer created
through the shim's device gets a title GPU address, registered with `xmem.dll` (`X2WTitleGpuRegisterResource`), so
`X2WTitleGpuTranslate`/`Locate` answer for it and `TitleLookup` finds it in the shader view.

- CPU-visible heaps (UPLOAD, READBACK, GPU_UPLOAD, CUSTOM with CPU access): the buffer's mapped CPU pointer, kept
  mapped for its life, so CPU pointer and GPU address are equal as on the console.
- Placed in a heap opened from title memory (`OpenExistingHeapFromAddress`): the heap's address plus the offset; when
  that span is already an XMem allocation, nothing new is registered.
- Everything else (DEFAULT, reserved, other placed buffers): a range of process address space reserved for the buffer
  (`MEM_RESERVE`, no access, 64 KiB granularity), so it never collides with title memory.
- READBACK buffers, buffers that deny shader resources and buffers of 4 GiB or more are registered for API translation
  only, not for `TitleLookup`. A shader-visible buffer without UAV access (UPLOAD) gets a null UAV in the title-memory
  table (stores to it write nothing). Every shader-visible registered buffer takes one of the converter's 8
  title-memory slots, so a title with many such buffers runs into that limit (draws are then refused, logged).
- Textures have no GPU address. Without `xmem.dll` the address is the desktop one (identity), noted once.
- Releasing the wrapper unregisters the range and frees the reservation.

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
criteria pass on WARP and hardware except "textures created from tiled bytes" through the title's own calls: the
console's texture upload path is not public, so the default scene uploads linear rows. The detiler (section 4,
"Textures: detiling") is built and tested, and the scene's `tiled` mode creates its textures from tiled bytes through
it; hooking it to the title's upload calls waits for an owner log that shows them.
R4b (`tests/runtime/r4b_scene.cpp`) adds vertex fetch through buffer V#s from descriptor tables, pixel constant slots
2 and 3 and pixel stores to title memory through a UAV's V# ([experiments.md](../experiments.md#buffer-vs-from-descriptor-tables-four-pixel-constant-slots-pixel-stores-runtime-rung-r4b)).

R5 program: `tests/runtime/r5_frames.cpp`: a compute queue moves particles in title memory with a translated gfx1013
compute program (`r5_cs.s`) and the direct queue draws them with the R3 programs, with cross-queue fences, for 600
frames (design choices, tests and frame times in
[experiments.md](../experiments.md#compute-and-a-frame-loop-runtime-rung-r5)). Its exit criteria pass on WARP and
hardware. The shim's descriptor blocks are recycled once the GPU is done with them, so a long run no longer exhausts
them.

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
   first-unimplemented-call line. Extend `tests/native/launch_check.py` to check the JSON. Implicit TLS in
   `pe_map` and the title's module identity are done (`cpu_native_tls_value` now matches Windows).
2. **Graphics shim skeleton for R2.** A desktop DLL under the graphics name exporting device creation, wrapping
   device/queue/allocator/list/fence/swap chain over desktop D3D12 in public method order with logging thunks for
   unknown slots and IIDs; attaches the device to `era_title_gpu`. Test `tests/runtime/r2_clear.cpp` (clear, present,
   readback, wrong-color control) on WARP and hardware.
3. **Pipeline-time translation and cache for R3.** `CreateGraphicsPipelineState` in the shim calls the converter
   out of process (`python tools/vertex_aot.py` / `pixel_aot.py` + DXC) keyed by bytecode hash, writes the DXIL cache,
   and logs refusals; `tests/runtime/r3_triangle.cpp` draws a triangle from llvm-mc-assembled gfx1013 programs and
   checks the frame against the CPU reference and the second-run cache hit.
