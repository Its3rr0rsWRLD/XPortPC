# System libraries: paths, threading, GameInput, XAudio2, DirectStorage

Status: implemented as source-built modules with tests (`tests/sys`, ctest names `sys_*`). Nothing here has run a real
title yet. Sources: public Microsoft documentation (GDK local-storage overview, GameInput and XAudio2 references, the
public DirectStorage repository's developer guidance) and general Win32 knowledge. No game files, dumps or leaked SDKs.

Code lives in `src/sys` as one static library (`x2w_sys_lib`) and one DLL (`x2w_sys.dll`, exports in `sys_exports.def`).
All modules log through `x2w_sys::log` (`[x2w] ...` on stderr and the debugger); repeated events are logged once.

## Integration for shimgen and the launcher

1. Call `X2WSysInit(title_dir, title_name, config_path_or_null)` once before binding imports. The config file is, in order,
   the argument, `%X2W_SYS_CONFIG%`, or `<title_dir>\x2w-sys.cfg`. Call `X2WSysShutdown()` at exit for the summary lines.
2. Win32 imports (kernel32, kernelbase, `api-ms-win-core-*`): for each import, ask `X2WSysHookLookup(dll, symbol)`; a
   non-null result replaces the import, exactly like `identity_hook` in `tools/x2w_launch.cpp`. Names covered:
   CreateFileW/A, CreateFile2, FindFirstFileW/ExW, GetFileAttributesW/A/ExW, SetFileAttributesW, CreateDirectoryW,
   RemoveDirectoryW, DeleteFileW, MoveFileW/ExW, CopyFileW, GetDiskFreeSpaceExW, SetThreadAffinityMask,
   SetThreadIdealProcessor/Ex, Set/GetProcessAffinityMask, GetCurrentProcessorNumber, SetThreadPriority, GetSystemInfo,
   GetNativeSystemInfo, GetActiveProcessorCount, GetMaximumProcessorCount, GetLogicalProcessorInformation/Ex,
   QueryPerformanceFrequency/Counter.
3. Console-named libraries: the console DLL names for input, audio and storage are learned from title import tables, not
   assumed. Once known, a shim for that name forwards these symbols (signatures match the public PC APIs):

   | Public API | x2w_sys.dll export |
   |---|---|
   | `GameInputCreate(IGameInput**)` | `X2wGameInputCreate` |
   | `XAudio2Create(IXAudio2**, UINT32, XAUDIO2_PROCESSOR)` | `X2wXAudio2Create` |
   | `DStorageGetFactory(REFIID, void**)` | `X2wDStorageGetFactory` |

   Fallback state APIs (`X2wGameInputFallback*`, `x2w_sys::ds::Queue`, `x2w_sys::audio::check_format`) are for the gateway.
4. `x2w_sys.dll` is not copied into the `shims` directory by CMake; shimgen decides.

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

Forwards to `GameInputRedist.dll` or `GameInput.dll` (`GameInputCreate`). Without either, an XInput fallback enumerates
pads and reports state in GameInput button bits. A COM `IGameInput` facade over the fallback is not written (needs the
public NuGet header at build time); `X2wGameInputCreate` returns `X2W_E_GAMEINPUT_FALLBACK` (0xA2570001) instead of guessing.

## 4. XAudio2

Forwards `XAudio2Create` to `xaudio2_9.dll`. `check_format` classifies submitted wave formats: PCM, MS ADPCM and float pass
through; XMA1/XMA2 (tags 0x0165/0x0166) are parsed (XMA2WAVEFORMATEX fields), logged once and reported as decode-required;
unknown tags are rejected. Console-only XAudio2 extensions are not public and are not handled.

## 5. DirectStorage

Forwards `DStorageGetFactory` to `dstorage.dll` (NuGet Microsoft.Direct3D.DirectStorage). Fallback `ds::Queue`: ReadFile on
a worker thread, destinations as host pointers or title addresses (resolver; default accepts committed writable memory),
paths through the path map, per-format decompressor callbacks. GDeflate decoding is not built in: the public reference
code is Apache-2.0 over a libdeflate fork; register a decoder with `ds::register_decompressor(ds::kGDeflate, fn)`. Until
then a GDeflate request fails with `X2W_E_DS_UNSUPPORTED_COMPRESSION` (logged once).
