# System libraries: paths, threading, GameInput, XAudio2, DirectStorage

Status: implemented as source-built modules with tests (`tests/sys`, ctest names `sys_*`), wired into `x2w_launch`
(ctest `native_launch_sys`, a source-built title run under the launcher). Nothing here has run a real title yet. Sources: public Microsoft documentation (GDK local-storage overview, GameInput and XAudio2 references, the
public DirectStorage repository's developer guidance) and general Win32 knowledge. No game files, dumps or leaked SDKs.

Code lives in `src/sys` as one static library (`x2w_sys_lib`) and one DLL (`x2w_sys.dll`, exports in `sys_exports.def`).
All modules log through `x2w_sys::log` (`[x2w] ...` on stderr and the debugger); repeated events are logged once.

## Integration for shimgen and the launcher

1. Call `X2WSysInit(title_dir, title_name, config_path_or_null)` once before binding imports. The config file is, in order,
   the argument, `%X2W_SYS_CONFIG%`, or `<title_dir>\x2w-sys.cfg`. Call `X2WSysShutdown()` at exit for the summary lines.
   `x2w_launch` does both: `--sys-config FILE` is the argument, the title folder is the EXE's folder and the title name
   its file name without extension. The launcher loads `x2w_sys.dll` from a `--shims` directory (CMake copies it into
   `shims/`), else from its own `shims\` or folder; `--sys-config` without the DLL is an error, and without a config
   or the DLL the title runs as before.
2. Win32 imports (kernel32, kernelbase, `api-ms-win-core-*`): for each import, ask `X2WSysHookLookup(dll, symbol)`; a
   non-null result replaces the import. Precedence in `x2w_launch` for an import that would go to Windows, first match
   wins: (a) title identity (`GetModuleHandle*`, `GetModuleFileName*`), (b) the launcher's loader hooks (`LoadLibrary*`,
   `GetProcAddress`; `GetModuleHandleA/W` there also give the identity answer), (c) `X2WSysHookLookup`, (d) Windows. A shim
   directory or package DLL with the same name still outranks all of them. `GetProcAddress` on a Windows DLL follows the
   same order. A sys-hooked import is reported as `windows (x2w sys hook)`.
   Active hooks: the path hooks answer when at least one rule exists (the G:/T:/D: defaults count); the threading,
   topology and timing hooks answer only when the config has a `threads.*` or `timing.*` key. With neither, the calls go
   to Windows unchanged. Names covered:
   CreateFileW/A, CreateFile2, FindFirstFileW/ExW, GetFileAttributesW/A/ExW, SetFileAttributesW, CreateDirectoryW,
   RemoveDirectoryW, DeleteFileW, MoveFileW/ExW, CopyFileW, GetDiskFreeSpaceExW, SetThreadAffinityMask,
   SetThreadIdealProcessor/Ex, Set/GetProcessAffinityMask, GetCurrentProcessorNumber, SetThreadPriority, GetSystemInfo,
   GetNativeSystemInfo, GetActiveProcessorCount, GetMaximumProcessorCount, GetLogicalProcessorInformation/Ex,
   QueryPerformanceFrequency/Counter.
3. Console-named libraries: the console DLL names for input, audio and storage are learned from title import tables, not
   assumed. Once known, a shim for that name forwards these symbols (signatures match the public PC APIs):

   | Public API | x2w_sys.dll export |
   |---|---|
   | `GameInputCreate(IGameInput**)` | `X2wGameInputCreate` (PC runtime), `X2wGameInputCreateV0` (console v0 facade, via shims/gameinput.dll) |
   | `XAudio2Create(IXAudio2**, UINT32, XAUDIO2_PROCESSOR)` | `X2wXAudio2Create` |
   | `DStorageGetFactory(REFIID, void**)` | `X2wDStorageGetFactory` |

   Fallback state APIs (`X2wGameInputFallback*`, `x2w_sys::ds::Queue`, `x2w_sys::audio::check_format`) are for the gateway.
   `X2wDStorageFallbackRead(path, offset, size, compression, uncompressed_size, dest)` is a flat synchronous fallback
   read (GDeflate decoded for format 1) for gateways and test titles.
4. `x2w_sys.dll` is copied into the `shims` directory by CMake (target `x2w_shims`); which console DLL names forward to its
   exports is still shimgen's decision.

## Config (`x2w-sys.cfg`)

`key value` or `key=value`, `#` comments.

| Key | Meaning |
|---|---|
| `map <from> -> <to> [ro] [mkdir]` | path rule; variables `%TITLEDIR%`, `%TITLE%`, `%LOCALAPPDATA%`, `%XPORT%` (= `%LOCALAPPDATA%\XPortPC\%TITLE%`). A rule with the same source replaces the earlier one; longest source wins |
| `paths.defaults off` | skip the default rules |
| `paths.clean_temp off` | keep `T:` contents between runs |
| `threads.console_cores N` (8), `threads.virtual_cores N` (0 = report host), `threads.clamp_time_critical on` | |
| `threads.l1_kib`, `l2_kib`, `l3_kib`, `cores_per_l3` | reported cache sizes: configured values, not measured console facts |
| `timing.qpc_frequency HZ` | report this frequency and scale the counter to it |
| `gameinput.dll`, `audio.dll`, `directstorage.dll` | runtime to try first (`off` for GameInput/DirectStorage forces the fallback) |

## 1. Paths

Public GDK local-storage overview: installed game data is drive `G:` (read only on console), temporary storage is `T:`
(deleted when the title ends), the development scratch partition is `D:` (development only). Persistent local storage and
mounted DLC have no fixed letter (the title obtains them from XPersistentLocalStorageGetPath / XPackageGetMountPath), so the
gateway registers them with `paths::global_map().add_rule(...)`. Defaults: `G:` to the title folder, `T:` and `D:` to
`%XPORT%\temp` and `%XPORT%\scratch` (parents created on write). `T:` is emptied at init (only when it still points at
the default folder). `ro` is available but off for `G:`. Each rule is logged on first use and each distinct path once (first
512). Drive-relative, UNC and relative paths are never remapped; `..` segments are not collapsed.

## 2. Threading and timing

Console core numbers map through an ordered host CPU list (one logical CPU per physical core first, then SMT siblings,
within the process affinity), modulo its length. Masks and ideal processors go console to host; previous values and
`GetCurrentProcessorNumber` come back in console numbering. With `threads.virtual_cores`, GetSystemInfo and the processor
count and topology calls report that many cores (core, L1/L2 per core, L3 per `cores_per_l3`, one NUMA node, one package,
one group). Priorities pass through (TIME_CRITICAL can be clamped).

## 3. GameInput

Console titles. A title built against the GDK's GameInput.h imports `gameinput.dll!GameInputCreate` and calls the v0
`IGameInput` vtable. The GameInput runtime Windows ships implements a newer interface with different slots, so such a
title must not reach it: the `gameinput.dll` shim in `shims/` (src/sys/gameinput_shim.cpp, export `GameInputCreate`)
returns `X2wGameInputCreateV0`'s facade (src/sys/sys_gameinput_v0.h). The facade follows the v0 layout from the public
reference, answers gamepad readings from XInput (GameInputGamepadState), reports connected pads to device callbacks, and
logs the first calls of each method ("shim-gameinput METHOD ARGS" in the run log); slots past the known ones log their
index and arguments and return E_NOTIMPL. `X2W_GAMEINPUT_PADS=off` hides the pads; `X2W_GAMEINPUT_LOG_CALLS=N` sets how
many calls per method are logged (8). Test: ctest `native_launch_gameinput`.

PC titles. `X2wGameInputCreate` forwards to `GameInputRedist.dll` or `GameInput.dll` (skipping x2w's own shim, and trying
System32's GameInput.dll by full path). Without either, an XInput fallback enumerates pads and reports state in GameInput
button bits; `X2wGameInputCreate` then returns `X2W_E_GAMEINPUT_FALLBACK` (0xA2570001).

## 4. XAudio2

Forwards `XAudio2Create` to `xaudio2_9.dll`. `check_format` classifies submitted wave formats: PCM, MS ADPCM and float pass
through; XMA1/XMA2 (tags 0x0165/0x0166) are parsed (XMA2WAVEFORMATEX fields), logged once and reported as decode-required;
unknown tags are rejected. Console-only XAudio2 extensions are not public and are not handled.

## 5. DirectStorage

Forwards `DStorageGetFactory` to `dstorage.dll` (NuGet Microsoft.Direct3D.DirectStorage). Fallback `ds::Queue`: ReadFile on
a worker thread, destinations as host pointers or title addresses (resolver; default accepts committed writable memory),
paths through the path map, per-format decompressor callbacks. GDeflate (format 1) is Microsoft's public reference decoder (Apache-2.0, over NVIDIA's libdeflate fork, MIT with
Apache-2.0 additions) vendored in `third_party/gdeflate` with notices; `X2WSysInit` registers it with
`ds::register_decompressor(ds::kGDeflate, ...)`. `sys_gdeflate.cpp` validates the stream header and tile offsets against
the stored and decoded sizes before decoding. Tests create fixtures with the reference encoder (`sys_gdeflate`,
`gdeflate_pack`). The library alone registers nothing; an unregistered format fails with `X2W_E_DS_UNSUPPORTED_COMPRESSION`
(logged once).
