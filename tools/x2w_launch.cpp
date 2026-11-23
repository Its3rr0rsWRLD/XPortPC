// x2w_launch: map an EXE with pe_map and route each import to a shim, a packaged DLL, Windows or a stub.
//
// Usage: x2w_launch [--shims DIR]... [--log FILE] [--stall-all] [--timeout SECONDS] [--force-cpu-traps] [--host-identity] [--no-heap-guard]
//                   [--no-trace-calls]
//                   [--xmem NAME=VALUE]... [--sys-config FILE] [--show-program-name]
//                   [--continue-breakpoints|--stop-on-breakpoints] program.exe
//
// Imports resolve in this order:
//   1. DIR\<dll> from a --shims directory, loaded with LoadLibrary (a desktop shim for a console library);
//   2. <dll> beside the program, mapped with pe_map like the program itself;
//   3. the Windows loader's normal search;
//   4. a generated stub that logs "dll!symbol" on its first call and returns 0.
// Every import is reported on stderr as "[x2w] import dll!symbol -> shim|package|windows|stub", so a run
// lists what a program still needs. The program runs on this thread through pe_map_run, and its entry
// point's return value becomes this process's exit code.
//
// Process endings the run log sees, each followed by the final summary: the entry point returning, ExitProcess,
// TerminateProcess on itself, ntdll's NtTerminateProcess/ZwTerminateProcess/RtlExitUserProcess, RaiseFailFastException
// ("fastfail" line), an unhandled exception, --timeout, a console close/Ctrl+C ("console-event" line) and process
// detach. dbghelp!MiniDumpWriteDump (a program's own crash handler) logs the exception it is given and a provisional
// "summary minidump". Only __fastfail (int 29h) and a kill from outside the process end it with no line.
//
// --log FILE writes a run log meant to be pasted into a report. It holds names and addresses only, never
// bytes of the program: the import route totals, each first call to a stub ("stub" when the DLL exists but
// lacks the function, "missing" when no route has the DLL), how far startup got (TLS callbacks, entry, the
// first thread created, the first call into a d3d12* import), the first exception and the first unhandled
// crash (code, module + RVA, last stub called; for a fault in a mapped image also the general registers, values
// only) and the exit code. Each line is written with its own
// WriteFile call, so the log survives a crash. Addresses are given as module+RVA. --timeout ends a run that
// is still going after that many seconds with exit code 124, after logging how far it got. Each distinct C++
// throw (0xe06d7363) is logged as "cpp-throw TYPE at SITE from CALLER": the thrown type's decorated name from
// the ThrowInfo (".?AVruntime_error@std@@") and the first two frames in mapped images, at most 16 lines.
//
// Dynamic loads. The program's imports of LoadLibraryA/W, LoadLibraryExA/W, GetModuleHandleA/W and
// GetProcAddress (from kernel32, kernelbase or the libraryloader API set) bind to hooks here, because PC
// GDK titles reach the Gaming Runtime only that way (xgameruntime.lib loads xgameruntime.dll and resolves
// names at run time). A load whose file name is in a --shims directory loads that shim; anything else goes
// to the Windows loader unchanged. GetProcAddress on a shim answers from the shim's exports; a name the shim
// lacks comes from the Windows DLL of that name when one exists ("windows-fallback"), else null, as
// Windows would. Each distinct load and resolve is logged once, as
// "dynamic-load NAME -> shim|loader|failed" and "dynamic-resolve DLL!NAME -> shim|windows-fallback|missing|windows", on
// stderr and in the run log; tools/shimgen.py --run-log turns those lines into shims.
// --xgr ours|trace|record (or X2W_XGR) sends xgameruntime.dll to the Gaming Runtime gateway instead
// (shims\x2w_xgr.dll, src/xgr/xgr_gateway.cpp, mode passed as X2W_XGR_MODE): "dynamic-load
// xgameruntime.dll -> gateway (MODE)", resolves route "gateway", and nothing falls back to Windows' DLL.
// Shims are loaded with LOAD_WITH_ALTERED_SEARCH_PATH, so DLLs beside a shim (x2w_gdk.dll) resolve.
// The program's environment gets X2W_TITLE (its file name without extension) and X2W_TITLE_DIR (its
// folder) unless they are set; the generated shims use them for save folders and the package path.
// Shims report their own unimplemented paths through the exported x2w_launch_log_shim, as
// "shim-<kind> SYMBOL DETAIL" lines in the run log.
//
// Zen 2 instructions the host CPU lacks fault with STATUS_ILLEGAL_INSTRUCTION. A vectored handler performs
// the ones x2w_cpu_trap.h knows (SHA-NI, CLZERO, RDPID, MONITORX/MWAITX, SSE4a, RDPRU, CLWB) on the faulting
// thread's registers and memory and resumes after the instruction; any other #UD in the program's code is
// logged as module+RVA and a mnemonic and then crashes as usual. The log starts with the Zen 2 features the
// host lacks and ends with a count per trapped instruction, since a trap in a hot loop is slow.
// --xmem NAME=VALUE sets X2W_XMEM_<NAME> (upper-cased) for the run before anything is mapped, configuring the title
// memory layer of the xmem.dll shim (src/xmem_title_api.h; for example --xmem layout=standalone or
// --xmem windows=reserve:graphics=0x100000000-0x10000000000). Each setting is logged.
// --force-cpu-traps is for tests: it overwrites each address listed by the program's export
// x2w_cpu_trap_sites (a null-terminated array of code addresses) with UD2 and keeps the original bytes in a
// side table, so the handler's path runs on every host, whether or not the CPU has the instruction.
//
// System layer. x2w_sys.dll (src/sys, docs/design/system-libs.md) is loaded from a --shims directory (CMake copies
// it into shims/), else from the launcher's shims\ or own folder. X2WSysInit(title folder, title name, config) runs
// before any import is bound and X2WSysShutdown at exit (summary lines on stderr). The config is --sys-config FILE,
// else %X2W_SYS_CONFIG%, else <title folder>\x2w-sys.cfg. Without a config only the documented path rules are active
// (G: to the title folder, T: and D: under %LOCALAPPDATA%\XPortPC\<title>); threading, topology and timing hooks
// stay off until the config has a threads.* or timing.* key. Without x2w_sys.dll the title runs with no system layer
// (an error if --sys-config was given). Precedence for an import that would go to Windows (kernel32, kernelbase,
// api-ms-win-core-*), first match wins: (1) the title-identity answers (GetModuleHandle*, GetModuleFileName*), (2) the
// loader hooks above (LoadLibrary*, GetProcAddress; they also carry the identity answers for GetModuleHandleA/W),
// (3) X2WSysHookLookup, (4) Windows itself. A shim directory or package DLL of the same name still outranks all
// of these. GetProcAddress on a Windows DLL applies the same order. Sys-hooked imports log as
// "windows (x2w sys hook)" and count as windows in the run log.
//
// Heap guard (diagnostic, on by default for now; --no-heap-guard turns it off). The heap-releasing functions of
// Windows and of the C runtime check each pointer against the heap it is handed to and refuse (log, leak) a pointer
// that is not one of its blocks, instead of letting ntdll end the process with 0xc0000374; the process heap is
// validated at milestones to bracket a write that corrupts it. Lines: "heap-guard on", "heap-guard invalid ...",
// "heap-guard corrupted-before M after P", and "heap-guard summary ..." before the final summary. See "heap guard" below.
//
// Recent-calls trace (diagnostic, on by default for now; --no-trace-calls turns it off). Every import routed for the
// program and its package DLLs, and every function GetProcAddress hands them, runs through a thunk that records the
// call in a per-thread 64-entry ring (name, caller, first four integer arguments, RAX on return). A crash, a
// first-chance line and the first breakpoint lines are followed by that thread's last 32 calls; a crash also by the
// main thread's. Lines: "trace-calls on", "recent-calls thread ...", "recent N: ..." (see "recent-calls trace" below).
// With --log the watchdog also scans those rings once a second: a call pending for more than 2 s gets one
// "stalled thread TID(main|program) in dll!NAME(...) for Ns caller=..." line, with the handle's type, name and mode
// for file calls, the object type (and the shim that made it) for waits, and every other thread's pending call as
// " also-pending TID(main|program) dll!NAME(...) for Ns" (see "stall detector" below).
//
// The title sees itself as the process image: its GetModuleHandle(NULL), GetModuleFileName(NULL) and the PEB's
// ImageBaseAddress name the mapped program, not this launcher (see "Module identity" below). --host-identity
// leaves them naming the launcher, for comparison.
//
// Program name. Stderr and the run log call the program title.exe (the program line, module+RVA, callers, mapped-image
// names, dynamic-load/resolve/handle lines, errors); its real file name appears in neither. The launcher prints no
// name read from inside the image. Package and imported DLL names are unchanged. --show-program-name restores the real
// file name, for the launcher's own tests.
#include <windows.h>
#include "../src/common/x2w_redact.h"
#include <tlhelp32.h>
#include <intrin.h>

#include <cctype>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cwctype>
#include <utility>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "x2w_cpu_trap.h"
#include "../src/xmem_title_api.h"  // X2WXMemDescribe's and X2WXMemGetWindows' types, looked up at run time

namespace {

using Resolver = void*(__cdecl*)(const char* dll, const char* name, std::uint32_t ordinal);
using MapImage = void* (*)(const wchar_t*, Resolver, std::uint32_t*, char*, std::size_t);
using MapExport = void* (*)(void*, const char*);
using MapExportResolved = void* (*)(void*, const char*, Resolver);
using RunObserver = void(__cdecl*)(int event, std::uint32_t index, void* address);
using MapRunTraced = int (*)(void*, std::uint32_t*, RunObserver);

MapImage map_image;
MapExport map_export;
MapExportResolved map_export_resolved;
MapRunTraced map_run;
std::vector<std::wstring> shim_dirs;
std::wstring package_dir;
std::map<std::string, HMODULE> shim_modules;
// --xgr MODE (or X2W_XGR): "shim" (default) leaves xgameruntime.dll to the --shims directories and the
// windows-fallback; "ours", "trace" and "record" route it to the gateway (shims\x2w_xgr.dll,
// src/xgr/xgr_gateway.cpp) in that mode, with no fallback to Windows' DLL.
std::string xgr_mode = "shim";
std::wstring launcher_dir;
// The system layer (x2w_sys.dll): hook lookup for Win32 imports, see the header comment.
using SysInit = int(__stdcall*)(const char* title_dir, const char* title_name, const char* config);
using SysLookup = void*(__stdcall*)(const char* dll, const char* symbol);
using SysShutdown = void(__stdcall*)();
SysLookup sys_lookup;
SysShutdown sys_shutdown;
constexpr const char* kXgrName = "xgameruntime.dll";
constexpr const wchar_t* kXgrGateway = L"x2w_xgr.dll";
std::map<std::string, void*> package_images;
std::set<std::string> mapping;  // package DLLs being mapped, to stop import cycles

struct Stub {
    std::string dll;
    std::string symbol;
    bool missing;  // no route has the DLL at all, as opposed to a DLL without this function
    bool d3d12;
    volatile long calls = 0;
};
std::vector<Stub*> stubs;
std::vector<std::uint8_t*> stub_pages;
std::uint8_t* stub_page;
std::size_t stub_used;
constexpr std::size_t kStubBytes = 32;
constexpr std::size_t kWatchBytes = 128;
constexpr std::size_t kStubPage = 1 << 16;

// Run log state. Everything below is written only when --log is given.
HANDLE log_file = INVALID_HANDLE_VALUE;
volatile long armed;         // set once the program starts running, so the launcher's own threads are ignored
volatile long last_stub;     // index + 1 of the stub most recently called, 0 for none
volatile long tls_done, entry_reached, first_thread, first_title_thread, first_d3d12, first_exception, crashed;
volatile long summary_written;  // a final summary line was written (exit, crash, timeout, terminate, process-exit)
volatile long provisional_written;
DWORD watchdog_id;
std::map<std::string, unsigned> route_counts;

struct Region {
    std::string name;  // lower-case file name
    std::uintptr_t base;
    std::size_t size;
    std::wstring path;  // full path the image was mapped from
    std::string label;  // the name logs give the image (the program is title.exe unless --show-program-name)
};
std::vector<Region> regions;  // the program first, then each mapped package DLL

struct Watch {
    std::string dll;
    std::string symbol;
    bool d3d12;  // a d3d12* import (the first-d3d12-call milestone, and a heap-guard check on every call)
    volatile long calls = 0;
};

// Heap guard (on unless --no-heap-guard; see "Heap guard" in the header comment).
bool heap_guard = true;
void heap_milestone(const char* name);
void guard_tick(const char* kind, const std::string& dll, const std::string& symbol, long calls);

// Instructions performed by the #UD handler, and the forced sites (--force-cpu-traps) with their original bytes.
volatile long trap_counts[x2w_cpu::kOpCount];
volatile long trap_seen[x2w_cpu::kOpCount];
volatile long unhandled_logged;
constexpr long kUnhandledLines = 16;
struct Site {
    std::uint8_t bytes[x2w_cpu::kMaxLength];
    std::size_t length;
};
std::map<std::uintptr_t, Site> forced_sites;  // written before the program runs, read-only after

std::string lower(std::string text) {
    for (auto& c : text) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return text;
}

std::wstring widen(const std::string& text) { return std::wstring(text.begin(), text.end()); }

std::string narrow(const std::wstring& text) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (size <= 1) return {};
    std::string out(static_cast<std::size_t>(size - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.c_str(), -1, out.data(), size, nullptr, nullptr);
    return out;
}

bool is_file(const std::wstring& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

std::wstring directory_of(const std::wstring& path) {
    const auto slash = path.find_last_of(L"\\/");
    return slash == std::wstring::npos ? L"." : path.substr(0, slash);
}

std::wstring file_of(const std::wstring& path) {
    const auto slash = path.find_last_of(L"\\/");
    return slash == std::wstring::npos ? path : path.substr(slash + 1);
}

// Logs and stderr name the program title.exe, and no run line holds its real file name, unless
// --show-program-name (for the launcher's own tests). Package and Windows DLL names are unchanged. The launcher
// prints no module-identity string read from inside the image (export directory name, version resource names,
// PDB path); pe_map prints none in its detail text either.
constexpr const char* kHiddenProgram = "title.exe";
bool show_program_name = false;
std::string real_program_name;  // lower-case file name of the program, set once before any log line names it

std::string real_program_dir;  // lower-case folder of the program; never logged, shown as <game>

// The program's folder, in either slash spelling, becomes "<game>" in every line (always; it is never logged).
std::string scrub_program_dir(std::string text) {
    if (real_program_dir.size() < 3) return text;
    for (char slash : {'\\', '/'}) {
        std::string needle = real_program_dir;
        for (char& c : needle) if (c == '\\' || c == '/') c = slash;
        const std::string folded = lower(text);
        std::string out;
        for (std::size_t at = 0; at < text.size();) {
            if (folded.compare(at, needle.size(), needle) == 0) { out += "<game>"; at += needle.size(); }
            else out += text[at++];
        }
        text = out;
    }
    return text;
}

std::string scrub_program_name(std::string text) {
    text = scrub_program_dir(std::move(text));
    if (!show_program_name) text = x2w_redact::apply(x2w_redact::hide_paths(text, real_program_name, kHiddenProgram));
    if (show_program_name || real_program_name.empty()) return text;
    const std::string folded = lower(text);
    std::string out;
    for (std::size_t at = 0; at < text.size();) {
        if (folded.compare(at, real_program_name.size(), real_program_name) == 0) {
            out += kHiddenProgram;
            at += real_program_name.size();
        } else {
            out += text[at++];
        }
    }
    return out;
}

int err_printf(const char* format, ...) {
    char line[2048];
    va_list args;
    va_start(args, format);
    int length = std::vsnprintf(line, sizeof line, format, args);
    va_end(args);
    if (length < 0) return length;
    if (length >= static_cast<int>(sizeof line)) length = static_cast<int>(sizeof line) - 1;
    const std::string text = scrub_program_name(std::string(line, static_cast<std::size_t>(length)));
    return static_cast<int>(std::fwrite(text.data(), 1, text.size(), stderr));
}

void log_line(const char* format, ...) {
    if (log_file == INVALID_HANDLE_VALUE) return;
    char line[4096];  // stall lines carry every other pending call
    va_list args;
    va_start(args, format);
    int length = std::vsnprintf(line, sizeof line - 1, format, args);
    va_end(args);
    if (length < 0) return;
    if (length > static_cast<int>(sizeof line) - 2) length = static_cast<int>(sizeof line) - 2;
    const std::string text = scrub_program_name(std::string(line, static_cast<std::size_t>(length))) + "\n";
    DWORD written = 0;
    // The file is opened for appending only, so lines from different threads never overwrite each other.
    WriteFile(log_file, text.data(), static_cast<DWORD>(text.size()), &written, nullptr);
}

std::size_t image_size(const void* base) {
    const auto* dos = static_cast<const IMAGE_DOS_HEADER*>(base);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(static_cast<const std::uint8_t*>(base) + dos->e_lfanew);
    return nt->OptionalHeader.SizeOfImage;
}

// "module+0xRVA" for an address: the program or a mapped package DLL, a launcher stub, a module the Windows
// loader knows, or the bare address.
void* trace_target(std::uintptr_t at);
void describe(const void* address, char* out, std::size_t capacity) {
    // A recent-calls thunk (a thread start, say) is named as the function it calls.
    if (void* target = trace_target(reinterpret_cast<std::uintptr_t>(address))) address = target;
    const auto at = reinterpret_cast<std::uintptr_t>(address);
    for (const auto& region : regions) {
        if (at >= region.base && at - region.base < region.size) {
            std::snprintf(out, capacity, "%s+0x%llx", region.label.c_str(),
                          static_cast<unsigned long long>(at - region.base));
            return;
        }
    }
    for (const auto* page : stub_pages) {
        const auto start = reinterpret_cast<std::uintptr_t>(page);
        if (at >= start && at - start < kStubPage) {
            std::snprintf(out, capacity, "x2w-stub-page+0x%llx", static_cast<unsigned long long>(at - start));
            return;
        }
    }
    HMODULE module = nullptr;
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCWSTR>(address), &module) && module) {
        wchar_t path[MAX_PATH];
        const DWORD length = GetModuleFileNameW(module, path, MAX_PATH);
        const std::string name = length ? lower(narrow(file_of(path))) : "module";
        std::snprintf(out, capacity, "%s+0x%llx", name.c_str(),
                      static_cast<unsigned long long>(at - reinterpret_cast<std::uintptr_t>(module)));
        return;
    }
    std::snprintf(out, capacity, "0x%llx", static_cast<unsigned long long>(at));
}

std::string last_stub_name() {
    const long index = last_stub;
    if (!index) return "none";
    const Stub* stub = stubs[static_cast<std::size_t>(index - 1)];
    return stub->dll + "!" + stub->symbol;
}

void log_cpu_traps() {
    char line[900];
    long total = 0;
    for (int op = 0; op < x2w_cpu::kOpCount; ++op) total += trap_counts[op];
    int used = std::snprintf(line, sizeof line, "cpu-traps total=%ld", total);
    for (int op = 0; op < x2w_cpu::kOpCount && used > 0 && static_cast<std::size_t>(used) < sizeof line; ++op)
        if (trap_counts[op])
            used += std::snprintf(line + used, sizeof line - used, " %s=%ld", x2w_cpu::op_name(op), trap_counts[op]);
    log_line("%s", line);
}

volatile long breakpoints_continued;  // int3s skipped by breakpoint_continue

void log_flush() {
    if (log_file != INVALID_HANDLE_VALUE) FlushFileBuffers(log_file);
}

void write_summary(const char* how) {
    log_line("summary %s: tls-callbacks=%s entry=%s first-thread=%s d3d12-call=%s crash=%s last-stub=%s", how,
             tls_done ? "done" : "not-done", entry_reached ? "reached" : "not-reached",
             first_thread ? "yes" : "no", first_d3d12 ? "yes" : "no", crashed ? "yes" : "no",
             last_stub_name().c_str());
    log_flush();
}

// The final summary, written once however the run ends: the entry point returning ("exit"), the program
// calling ExitProcess ("exit") or TerminateProcess on itself ("terminate"), an unhandled exception ("crash"),
// --timeout ("timeout"), or, as a last resort, the launcher's own process-detach callback ("process-exit").
void heap_guard_summary();
void log_summary(const char* how) {
    if (InterlockedExchange(&summary_written, 1) != 0) return;
    heap_milestone(how);
    heap_guard_summary();
    log_cpu_traps();
    if (breakpoints_continued) log_line("breakpoints continued %ld", breakpoints_continued);
    write_summary(how);
}

// A provisional summary at the first error exception: a fault the process cannot survive may end it with
// no other line (an exception while the loader starts a thread runs no unhandled-exception filter, and
// __fastfail runs no handler at all), so the log still ends with a summary. A later final summary follows
// it when the process goes on.
void log_provisional_summary() {
    if (summary_written || InterlockedExchange(&provisional_written, 1) != 0) return;
    write_summary("first-fault");
}

void d3d12_milestone(const std::string& dll, const std::string& symbol, const char* route) {
    if (InterlockedExchange(&first_d3d12, 1) == 0)
        log_line("milestone first-d3d12-call %s!%s (%s)", dll.c_str(), symbol.c_str(), route);
}

std::uint8_t* reserve_thunk(std::size_t bytes) {
    if (!stub_page || stub_used + bytes > kStubPage) {
        stub_page = static_cast<std::uint8_t*>(
            VirtualAlloc(nullptr, kStubPage, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
        stub_used = 0;
        if (!stub_page) return nullptr;
        stub_pages.push_back(stub_page);
    }
    std::uint8_t* thunk = stub_page + stub_used;
    stub_used += bytes;
    return thunk;
}

// A stub is reached by a jump from its thunk with the caller's return address on the stack, so it returns
// straight to the program. RCX holds the stub index; the program's own arguments are ignored.
extern "C" std::uint64_t x2w_stub_call(std::uint64_t index) {
    Stub* stub = stubs[static_cast<std::size_t>(index)];
    InterlockedExchange(&last_stub, static_cast<long>(index + 1));
    const long calls = InterlockedIncrement(&stub->calls);
    if (calls == 1) {
        err_printf( "[x2w] call stub %s!%s\n", stub->dll.c_str(), stub->symbol.c_str());
        log_line("first-call %s %s!%s", stub->missing ? "missing" : "stub", stub->dll.c_str(), stub->symbol.c_str());
        if (stub->d3d12) d3d12_milestone(stub->dll, stub->symbol, stub->missing ? "missing" : "stub");
    }
    if (heap_guard) guard_tick(stub->d3d12 ? "d3d12-call" : "stub-call", stub->dll, stub->symbol, calls);
    return 0;
}

void* make_stub(const std::string& dll, const std::string& symbol, bool missing) {
    std::uint8_t* thunk = reserve_thunk(kStubBytes);
    if (!thunk) return nullptr;
    const std::uint64_t index = stubs.size();
    stubs.push_back(new Stub{dll, symbol, missing, dll.rfind("d3d12", 0) == 0});
    const auto handler = reinterpret_cast<std::uint64_t>(&x2w_stub_call);
    thunk[0] = 0x48;  // mov rcx, imm64
    thunk[1] = 0xb9;
    std::memcpy(thunk + 2, &index, 8);
    thunk[10] = 0x48;  // mov rax, imm64
    thunk[11] = 0xb8;
    std::memcpy(thunk + 12, &handler, 8);
    thunk[20] = 0xff;  // jmp rax
    thunk[21] = 0xe0;
    FlushInstructionCache(GetCurrentProcess(), thunk, kStubBytes);
    return thunk;
}

// RCX is the Watch itself (not an index into a vector that a dynamic load may be growing on another thread).
extern "C" void x2w_watch_call(std::uint64_t pointer) {
    Watch* watch = reinterpret_cast<Watch*>(pointer);
    const DWORD error = GetLastError();
    const long calls = InterlockedIncrement(&watch->calls);
    if (watch->d3d12 && calls == 1) d3d12_milestone(watch->dll, watch->symbol, "bound");
    if (heap_guard) guard_tick(watch->d3d12 ? "d3d12-call" : "shim-call", watch->dll, watch->symbol, calls);
    SetLastError(error);
}

// A watched import runs a thunk that records the call and then jumps to the bound function with the caller's
// arguments intact: RCX, RDX, R8, R9 and XMM0-XMM3 are saved around the record call and the stack arguments
// are not touched. On entry RSP is 8 mod 16; four pushes and 0x68 bytes make it 0 mod 16 for the call, with
// the home space at [RSP, RSP+0x20) and the XMM saves above it. Assembled with llvm-mc from:
//   push rcx; push rdx; push r8; push r9; sub rsp, 0x68
//   movdqu [rsp+0x20..0x50], xmm0..xmm3
//   mov rcx, <Watch*>; mov rax, <x2w_watch_call>; call rax
//   movdqu xmm0..xmm3, [rsp+0x20..0x50]; add rsp, 0x68; pop r9; pop r8; pop rdx; pop rcx
//   mov rax, <target>; jmp rax
constexpr std::uint8_t kWatchCode[] = {
    0x51, 0x52, 0x41, 0x50, 0x41, 0x51, 0x48, 0x83, 0xec, 0x68, 0xf3, 0x0f, 0x7f, 0x44, 0x24, 0x20, 0xf3,
    0x0f, 0x7f, 0x4c, 0x24, 0x30, 0xf3, 0x0f, 0x7f, 0x54, 0x24, 0x40, 0xf3, 0x0f, 0x7f, 0x5c, 0x24, 0x50,
    0x48, 0xb9, 0, 0, 0, 0, 0, 0, 0, 0, 0x48, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0xff, 0xd0, 0xf3, 0x0f,
    0x6f, 0x44, 0x24, 0x20, 0xf3, 0x0f, 0x6f, 0x4c, 0x24, 0x30, 0xf3, 0x0f, 0x6f, 0x54, 0x24, 0x40, 0xf3,
    0x0f, 0x6f, 0x5c, 0x24, 0x50, 0x48, 0x83, 0xc4, 0x68, 0x41, 0x59, 0x41, 0x58, 0x5a, 0x59, 0x48, 0xb8,
    0, 0, 0, 0, 0, 0, 0, 0, 0xff, 0xe0};
constexpr std::size_t kWatchIndex = 36, kWatchHandler = 46, kWatchTarget = 92;
static_assert(sizeof kWatchCode == 102 && sizeof kWatchCode <= kWatchBytes);
static_assert(kWatchCode[kWatchIndex - 2] == 0x48 && kWatchCode[kWatchIndex - 1] == 0xb9);
static_assert(kWatchCode[kWatchHandler - 1] == 0xb8 && kWatchCode[kWatchTarget - 1] == 0xb8);

void* make_watch(const std::string& dll, const std::string& symbol, void* target) {
    std::uint8_t* thunk = reserve_thunk(kWatchBytes);
    if (!thunk) return target;
    const auto index = reinterpret_cast<std::uint64_t>(new Watch{dll, symbol, dll.rfind("d3d12", 0) == 0});
    const auto handler = reinterpret_cast<std::uint64_t>(&x2w_watch_call);
    const auto destination = reinterpret_cast<std::uint64_t>(target);
    std::memcpy(thunk, kWatchCode, sizeof kWatchCode);
    std::memcpy(thunk + kWatchIndex, &index, 8);
    std::memcpy(thunk + kWatchHandler, &handler, 8);
    std::memcpy(thunk + kWatchTarget, &destination, 8);
    FlushInstructionCache(GetCurrentProcess(), thunk, kWatchBytes);
    return thunk;
}

// ---------------------------------------------------------------- recent-calls trace (--trace-calls)
// On by default for now (--no-trace-calls turns it off). Every import routed for the program and its package DLLs
// (shim, package, windows, stub) and every code address GetProcAddress hands them is replaced by a 32-byte thunk that
// loads its descriptor (target, "dll!symbol") into R10 and jumps to one shared body. The body is a real frame with
// unwind data (RtlAddFunctionTable), so exceptions and stack walks pass through it: it saves RCX, RDX, R8, R9 and
// XMM0-XMM3, records the call (x2w_trace_enter: descriptor, caller's return address, first four integer arguments)
// in this thread's ring, copies up to 12 stack arguments (bounded by the thread's stack base) into its own outgoing
// area, calls the target with the registers restored, records RAX (x2w_trace_leave) and returns RAX and XMM0 as the
// target left them. RBX, RSI and RDI are pushed and popped; nothing else nonvolatile is touched, and RSP is 0 mod 16
// at both calls. LastError is not changed: the record functions call nothing that sets it, and the one-time ring
// setup saves and restores it. Each thread gets a fixed 64-entry ring from a pool allocated once (no lock, no
// allocation per call); its pointer is in a dynamic TLS slot read straight from the TEB (the launcher keeps no
// implicit TLS, see "slot 0"). Functions that never return, inspect or replace their caller's frame, switch stacks or
// take varargs or a va_list are not wrapped (trace_skip). Data exports are not wrapped: only addresses in an
// executable section of an image, or in executable private memory (stubs), are.
// Lines: "trace-calls on", and at a crash, a first-chance line and the first breakpoint lines, the faulting thread's
// last 32 calls oldest first, "recent-calls thread TID|main calls N" then "recent SEQ: dll!NAME(a1,a2,a3,a4) -> RAX
// caller=module+RVA" (RAX "pending" for a call that has not returned); a crash also gives the main thread's ring.
bool trace_calls = true;
struct TraceDesc {
    void* target;  // at offset 0: the body calls [R10]
    const char* name;
};
struct TraceEntry {
    const TraceDesc* desc;
    std::uint64_t caller;
    std::uint64_t args[4];
    std::uint64_t rax;
    volatile std::uint64_t seq;  // the call's number on its thread, kTraceDone set once it returned; 0 while written
};
static_assert(sizeof(TraceEntry) == 64, "one cache line per entry");
constexpr std::uint64_t kTraceRing = 64, kTraceShown = 32, kTraceDone = 1ull << 63;
struct TraceRing {
    DWORD tid;
    DWORD unused;
    volatile std::uint64_t count;
    std::uint64_t pad[6];
    TraceEntry entries[kTraceRing];
};
constexpr long kTraceRings = 4096;
constexpr long kTraceBreakpointDumps = 8;
TraceRing* trace_pool;
volatile long trace_pool_used;
DWORD trace_slot = TLS_OUT_OF_INDEXES;
DWORD trace_main_tid;
std::uint8_t* trace_body;
SRWLOCK trace_lock = SRWLOCK_INIT;
std::map<void*, void*>* trace_thunks;  // target -> thunk, so every route to one function gets the same thunk
std::vector<std::uint8_t*> trace_pages;
std::size_t trace_used;
constexpr std::size_t kTraceThunk = 32, kTracePage = 1 << 16;

// This thread's ring, made on first use when create is set; null if the pool is used up (marked with 1).
TraceRing* trace_ring(bool create) {
    if (trace_slot == TLS_OUT_OF_INDEXES) return nullptr;
    void* value;
    if (trace_slot < 64) {
        value = reinterpret_cast<void*>(__readgsqword(0x1480 + trace_slot * 8));  // TEB TlsSlots
    } else {
        const DWORD error = GetLastError();
        value = TlsGetValue(trace_slot);  // sets LastError to 0 on success
        SetLastError(error);
    }
    if (value == reinterpret_cast<void*>(1)) return nullptr;
    if (value || !create) return static_cast<TraceRing*>(value);
    const DWORD error = GetLastError();
    const long index = InterlockedIncrement(&trace_pool_used) - 1;
    TraceRing* ring = index < kTraceRings ? &trace_pool[index] : nullptr;
    if (ring) ring->tid = GetCurrentThreadId();
    TlsSetValue(trace_slot, ring ? static_cast<void*>(ring) : reinterpret_cast<void*>(1));
    SetLastError(error);
    return ring;
}

extern "C" std::uint64_t x2w_trace_enter(const TraceDesc* desc, std::uint64_t caller, const std::uint64_t* args) {
    TraceRing* ring = trace_ring(true);
    if (!ring) return 0;
    const std::uint64_t seq = ring->count + 1;
    TraceEntry& entry = ring->entries[(seq - 1) % kTraceRing];
    entry.seq = 0;
    entry.desc = desc;
    entry.caller = caller;
    for (int i = 0; i < 4; ++i) entry.args[i] = args[i];
    entry.rax = 0;
    entry.seq = seq;  // volatile stores are release stores under MSVC on x64
    ring->count = seq;
    return seq;
}

extern "C" void x2w_trace_leave(std::uint64_t seq, std::uint64_t rax) {
    if (!seq) return;
    TraceRing* ring = trace_ring(false);
    if (!ring) return;
    TraceEntry& entry = ring->entries[(seq - 1) % kTraceRing];
    if (entry.seq != seq) return;  // overwritten by 64 later calls, or a fiber that moved threads
    entry.rax = rax;
    entry.seq = seq | kTraceDone;
}

// The shared body, assembled with llvm-mc from:
//   push rbx; push rsi; push rdi; sub rsp, 0xF0                         (prolog, 10 bytes)
//   mov [rsp+0x80..0x98], rcx, rdx, r8, r9; movdqu [rsp+0xA0..0xD0], xmm0..xmm3; mov [rsp+0xE0], r10
//   mov rcx, r10; mov rdx, [rsp+0x108]; lea r8, [rsp+0x80]; mov rax, <x2w_trace_enter>; call rax; mov rbx, rax
//   lea rsi, [rsp+0x130]; lea rdi, [rsp+0x20]; mov rcx, gs:[8]; sub rcx, rsi; shr rcx, 3
//   cmp rcx, 12; jbe 1f; mov ecx, 12; 1: rep movsq                       (stack arguments 5..16)
//   mov rcx..r9, [rsp+0x80..0x98]; movdqu xmm0..xmm3, [rsp+0xA0..0xD0]; mov r10, [rsp+0xE0]; call [r10]
//   mov [rsp+0x80], rax; movdqu [rsp+0xA0], xmm0; mov rcx, rbx; mov rdx, rax; mov rax, <x2w_trace_leave>; call rax
//   mov rax, [rsp+0x80]; movdqu xmm0, [rsp+0xA0]; add rsp, 0xF0; pop rdi; pop rsi; pop rbx; ret
// Entry RSP is 8 mod 16; three pushes and 0xF0 make it 0 mod 16. The caller's return address is at [rsp+0x108] and
// its fifth argument at [rsp+0x130]; the callee's home space is [rsp, rsp+0x20) and its stack arguments follow.
constexpr std::uint8_t kTraceBody[] = {
    0x53, 0x56, 0x57, 0x48, 0x81, 0xec, 0xf0, 0x00, 0x00, 0x00, 0x48, 0x89, 0x8c, 0x24, 0x80, 0x00, 0x00, 0x00, 0x48,
    0x89, 0x94, 0x24, 0x88, 0x00, 0x00, 0x00, 0x4c, 0x89, 0x84, 0x24, 0x90, 0x00, 0x00, 0x00, 0x4c, 0x89, 0x8c, 0x24,
    0x98, 0x00, 0x00, 0x00, 0xf3, 0x0f, 0x7f, 0x84, 0x24, 0xa0, 0x00, 0x00, 0x00, 0xf3, 0x0f, 0x7f, 0x8c, 0x24, 0xb0,
    0x00, 0x00, 0x00, 0xf3, 0x0f, 0x7f, 0x94, 0x24, 0xc0, 0x00, 0x00, 0x00, 0xf3, 0x0f, 0x7f, 0x9c, 0x24, 0xd0, 0x00,
    0x00, 0x00, 0x4c, 0x89, 0x94, 0x24, 0xe0, 0x00, 0x00, 0x00, 0x4c, 0x89, 0xd1, 0x48, 0x8b, 0x94, 0x24, 0x08, 0x01,
    0x00, 0x00, 0x4c, 0x8d, 0x84, 0x24, 0x80, 0x00, 0x00, 0x00, 0x48, 0xb8, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11,
    0x11, 0xff, 0xd0, 0x48, 0x89, 0xc3, 0x48, 0x8d, 0xb4, 0x24, 0x30, 0x01, 0x00, 0x00, 0x48, 0x8d, 0x7c, 0x24, 0x20,
    0x65, 0x48, 0x8b, 0x0c, 0x25, 0x08, 0x00, 0x00, 0x00, 0x48, 0x29, 0xf1, 0x48, 0xc1, 0xe9, 0x03, 0x48, 0x83, 0xf9,
    0x0c, 0x76, 0x05, 0xb9, 0x0c, 0x00, 0x00, 0x00, 0xf3, 0x48, 0xa5, 0x48, 0x8b, 0x8c, 0x24, 0x80, 0x00, 0x00, 0x00,
    0x48, 0x8b, 0x94, 0x24, 0x88, 0x00, 0x00, 0x00, 0x4c, 0x8b, 0x84, 0x24, 0x90, 0x00, 0x00, 0x00, 0x4c, 0x8b, 0x8c,
    0x24, 0x98, 0x00, 0x00, 0x00, 0xf3, 0x0f, 0x6f, 0x84, 0x24, 0xa0, 0x00, 0x00, 0x00, 0xf3, 0x0f, 0x6f, 0x8c, 0x24,
    0xb0, 0x00, 0x00, 0x00, 0xf3, 0x0f, 0x6f, 0x94, 0x24, 0xc0, 0x00, 0x00, 0x00, 0xf3, 0x0f, 0x6f, 0x9c, 0x24, 0xd0,
    0x00, 0x00, 0x00, 0x4c, 0x8b, 0x94, 0x24, 0xe0, 0x00, 0x00, 0x00, 0x41, 0xff, 0x12, 0x48, 0x89, 0x84, 0x24, 0x80,
    0x00, 0x00, 0x00, 0xf3, 0x0f, 0x7f, 0x84, 0x24, 0xa0, 0x00, 0x00, 0x00, 0x48, 0x89, 0xd9, 0x48, 0x89, 0xc2, 0x48,
    0xb8, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0xff, 0xd0, 0x48, 0x8b, 0x84, 0x24, 0x80, 0x00, 0x00, 0x00,
    0xf3, 0x0f, 0x6f, 0x84, 0x24, 0xa0, 0x00, 0x00, 0x00, 0x48, 0x81, 0xc4, 0xf0, 0x00, 0x00, 0x00, 0x5f, 0x5e, 0x5b,
    0xc3};
constexpr std::size_t kTraceEnter = 107, kTraceLeave = 267, kTraceUnwind = 320, kTraceFunction = 352;
static_assert(sizeof kTraceBody == 305 && sizeof kTraceBody <= kTraceUnwind);
static_assert(kTraceBody[kTraceEnter - 2] == 0x48 && kTraceBody[kTraceEnter - 1] == 0xb8);
static_assert(kTraceBody[kTraceLeave - 2] == 0x48 && kTraceBody[kTraceLeave - 1] == 0xb8);
// UNWIND_INFO: version 1, prolog 10 bytes, 5 codes: at 10 ALLOC_LARGE 0xF0 (two slots, size / 8), at 3 PUSH_NONVOL
// rdi, at 2 PUSH_NONVOL rsi, at 1 PUSH_NONVOL rbx; padded to an even count.
constexpr std::uint8_t kTraceUnwindInfo[] = {0x01, 0x0a, 0x05, 0x00, 0x0a, 0x01, 0x1e, 0x00,
                                             0x03, 0x70, 0x02, 0x60, 0x01, 0x30, 0x00, 0x00};

bool trace_init() {
    auto* page = static_cast<std::uint8_t*>(VirtualAlloc(nullptr, 4096, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    trace_pool = static_cast<TraceRing*>(
        VirtualAlloc(nullptr, sizeof(TraceRing) * kTraceRings, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    trace_slot = TlsAlloc();
    if (!page || !trace_pool || trace_slot == TLS_OUT_OF_INDEXES) return false;
    std::memcpy(page, kTraceBody, sizeof kTraceBody);
    const auto enter = reinterpret_cast<std::uint64_t>(&x2w_trace_enter);
    const auto leave = reinterpret_cast<std::uint64_t>(&x2w_trace_leave);
    std::memcpy(page + kTraceEnter, &enter, 8);
    std::memcpy(page + kTraceLeave, &leave, 8);
    std::memcpy(page + kTraceUnwind, kTraceUnwindInfo, sizeof kTraceUnwindInfo);
    auto* function = reinterpret_cast<RUNTIME_FUNCTION*>(page + kTraceFunction);
    function->BeginAddress = 0;
    function->EndAddress = sizeof kTraceBody;
    function->UnwindData = kTraceUnwind;
    DWORD old = 0;
    if (!VirtualProtect(page, 4096, PAGE_EXECUTE_READ, &old)) return false;
    FlushInstructionCache(GetCurrentProcess(), page, 4096);
    if (!RtlAddFunctionTable(function, 1, reinterpret_cast<DWORD64>(page))) return false;
    trace_thunks = new std::map<void*, void*>;
    trace_main_tid = GetCurrentThreadId();
    trace_body = page;
    return true;
}

// Imports that are not wrapped: they never return, unwind or restore a frame, read or switch the caller's stack, are
// called by the exception machinery, or take varargs or a va_list.
bool trace_skip(const std::string& symbol) {
    static const char* const exact[] = {
        "ExitProcess", "ExitThread", "FreeLibraryAndExitThread", "RtlExitUserThread", "RtlExitUserProcess",
        "NtTerminateProcess", "ZwTerminateProcess", "TerminateProcess", "FatalExit", "FatalAppExitA", "FatalAppExitW",
        "RaiseException", "RaiseFailFastException", "RtlRaiseException", "NtRaiseException", "ZwRaiseException",
        "RtlCaptureContext", "RtlCaptureContext2", "RtlRestoreContext", "NtContinue", "ZwContinue", "NtContinueEx",
        "RtlCaptureStackBackTrace", "RtlWalkFrameChain", "_CxxThrowException", "__C_specific_handler",
        "__std_terminate", "terminate", "abort", "exit", "_exit", "_Exit", "quick_exit", "_cexit", "_c_exit",
        "_invoke_watson", "_invalid_parameter_noinfo_noreturn", "__report_gsfailure", "_endthread", "_endthreadex",
        "longjmp", "_longjmp", "setjmp", "_setjmp", "_setjmpex", "__intrinsic_setjmp", "__intrinsic_setjmpex",
        "SwitchToFiber", "ConvertThreadToFiber", "ConvertThreadToFiberEx", "ConvertFiberToThread", "DeleteFiber",
        "__chkstk", "_chkstk", "__alloca_probe", "_alloca_probe", "_alloca_probe_16", "_alloca_probe_8",
        "_resetstkoflw", "__security_check_cookie", "DbgPrint", "DbgPrintEx", "DbgBreakPoint", "DebugBreak"};
    for (const char* name : exact)
        if (symbol == name) return true;
    static const char* const prefixes[] = {"RtlUnwind", "__CxxFrameHandler", "_CxxFrameHandler", "__GSHandlerCheck",
                                           "_except_handler", "__NLG_", "_local_unwind", "__longjmp", "__DestructExceptionObject"};
    for (const char* prefix : prefixes)
        if (symbol.rfind(prefix, 0) == 0) return true;
    std::string folded = symbol;
    for (char& c : folded) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    // printf/scanf families (sprintf, wsprintfW, __stdio_common_vfprintf, ...), va_list takers (vsnprintf, ...).
    return folded.find("printf") != std::string::npos || folded.find("scanf") != std::string::npos ||
           folded.find("va_list") != std::string::npos;
}

// True for an address in an executable section of an image (a mapped one, or one the Windows loader knows), or in
// executable private memory (the launcher's stubs and watch thunks). Data exports are false.
bool trace_is_code(const void* address) {
    const auto at = reinterpret_cast<std::uintptr_t>(address);
    std::uintptr_t base = 0;
    for (const auto& region : regions)
        if (at >= region.base && at - region.base < region.size) base = region.base;
    if (!base) {
        MEMORY_BASIC_INFORMATION info;
        if (!VirtualQuery(address, &info, sizeof info) || info.State != MEM_COMMIT) return false;
        if (info.Type != MEM_IMAGE)
            return (info.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) != 0;
        base = reinterpret_cast<std::uintptr_t>(info.AllocationBase);
    }
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    const std::uintptr_t rva = at - base;
    const IMAGE_SECTION_HEADER* section = IMAGE_FIRST_SECTION(nt);
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++section) {
        const DWORD size = section->Misc.VirtualSize ? section->Misc.VirtualSize : section->SizeOfRawData;
        if (rva >= section->VirtualAddress && rva - section->VirtualAddress < size)
            return (section->Characteristics & IMAGE_SCN_MEM_EXECUTE) != 0;
    }
    return false;
}

bool in_trace_page(std::uintptr_t at) {
    for (const auto* page : trace_pages) {
        const auto start = reinterpret_cast<std::uintptr_t>(page);
        if (at >= start && at - start < kTracePage) return true;
    }
    return false;
}

// The function a thunk calls, for the start address of a thunk, else null.
void* trace_target(std::uintptr_t at) {
    if (!trace_body || !TryAcquireSRWLockShared(&trace_lock)) return nullptr;
    void* target = nullptr;
    for (const auto* page : trace_pages) {
        const auto start = reinterpret_cast<std::uintptr_t>(page);
        if (at >= start && at - start < kTracePage && (at - start) % kTraceThunk == 0 && page[at - start] == 0x49) {
            std::uint64_t desc = 0;
            std::memcpy(&desc, page + (at - start) + 2, 8);
            target = reinterpret_cast<const TraceDesc*>(desc)->target;
        }
    }
    ReleaseSRWLockShared(&trace_lock);
    return target;
}

// The thunk the program gets for dll!symbol at address, or address itself when it is not wrapped.
void* trace_wrap(const std::string& dll, const std::string& symbol, void* address) {
    if (!trace_calls || !trace_body || !address || trace_skip(symbol)) return address;
    AcquireSRWLockExclusive(&trace_lock);
    void* result = address;
    if (!in_trace_page(reinterpret_cast<std::uintptr_t>(address))) {
        void*& thunk = (*trace_thunks)[address];
        if (!thunk && trace_is_code(address)) {
            if (trace_pages.empty() || trace_used + kTraceThunk > kTracePage) {
                auto* page = static_cast<std::uint8_t*>(
                    VirtualAlloc(nullptr, kTracePage, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
                if (page) {
                    trace_pages.push_back(page);
                    trace_used = 0;
                }
            }
            if (!trace_pages.empty() && trace_used + kTraceThunk <= kTracePage) {
                std::uint8_t* code = trace_pages.back() + trace_used;
                trace_used += kTraceThunk;
                auto* desc = new TraceDesc{address, _strdup((dll + "!" + symbol).c_str())};
                const auto pointer = reinterpret_cast<std::uint64_t>(desc);
                const auto body = reinterpret_cast<std::uint64_t>(trace_body);
                std::memset(code, 0xcc, kTraceThunk);
                code[0] = 0x49;  // mov r10, imm64 (the descriptor)
                code[1] = 0xba;
                std::memcpy(code + 2, &pointer, 8);
                code[10] = 0x49;  // mov r11, imm64 (the body)
                code[11] = 0xbb;
                std::memcpy(code + 12, &body, 8);
                code[20] = 0x41;  // jmp r11
                code[21] = 0xff;
                code[22] = 0xe3;
                FlushInstructionCache(GetCurrentProcess(), code, kTraceThunk);
                thunk = code;
            }
        }
        if (thunk) result = thunk;
    }
    ReleaseSRWLockExclusive(&trace_lock);
    return result;
}

void trace_dump(const TraceRing* ring, const char* who) {
    if (!trace_body) return;
    const std::uint64_t count = ring ? ring->count : 0;
    log_line("recent-calls thread %s calls %llu", who, static_cast<unsigned long long>(count));
    if (!ring) return;
    const std::uint64_t first = count > kTraceShown ? count - kTraceShown + 1 : 1;
    for (std::uint64_t n = first; n <= count; ++n) {
        const TraceEntry& entry = ring->entries[(n - 1) % kTraceRing];
        const std::uint64_t seq = entry.seq;
        if ((seq & ~kTraceDone) != n || !entry.desc) continue;
        char caller[160];
        describe(reinterpret_cast<const void*>(entry.caller), caller, sizeof caller);
        char rax[24] = "pending";
        if (seq & kTraceDone) std::snprintf(rax, sizeof rax, "0x%llx", static_cast<unsigned long long>(entry.rax));
        log_line("recent %llu: %s(0x%llx,0x%llx,0x%llx,0x%llx) -> %s caller=%s", static_cast<unsigned long long>(n),
                 entry.desc->name, static_cast<unsigned long long>(entry.args[0]),
                 static_cast<unsigned long long>(entry.args[1]), static_cast<unsigned long long>(entry.args[2]),
                 static_cast<unsigned long long>(entry.args[3]), rax, caller);
    }
}

// The current thread's ring ("main" when it is the program's main thread).
void trace_dump_current() {
    if (!trace_body) return;
    char who[16];
    const DWORD self = GetCurrentThreadId();
    if (self == trace_main_tid) std::snprintf(who, sizeof who, "main");
    else std::snprintf(who, sizeof who, "%lu", self);
    trace_dump(trace_ring(false), who);
}

// The main thread's ring, when the current thread is another one.
void trace_dump_main() {
    if (!trace_body || GetCurrentThreadId() == trace_main_tid) return;
    const long used = trace_pool_used < kTraceRings ? trace_pool_used : kTraceRings;
    const TraceRing* ring = nullptr;
    for (long i = 0; i < used && !ring; ++i)
        if (trace_pool[i].tid == trace_main_tid) ring = &trace_pool[i];
    trace_dump(ring, "main");
}

// ---------------------------------------------------------------- stall detector
// With --log the watchdog (with or without --timeout) scans every thread's recent-calls ring once a second. A thread
// whose newest
// call has been pending for more than 2 s (the same call seen pending in scans at least 2 s apart) is logged once:
// "stalled thread TID(main|program) in dll!NAME(a1,a2,a3,a4) for Ns caller=module+RVA", then for file calls
// (ReadFile, WriteFile, ReadFileEx, GetOverlappedResult, DeviceIoControl, ...) " handle 0x.. handle-type T name N
// overlapped-handle=yes|no", and for waits (WaitForSingleObject(Ex), WaitForMultipleObjects(Ex), ...) per handle
// " handle 0x.. object-type TYPE" plus " created-by WHO" for an event a shim tagged (x2w_launch_tag_handle) and the
// file fields for a File object. What x2w_sys's file hooks know of the handle follows as " opened-as NAME flags=(...)
// type-at-open=T" (X2WSysDescribeHandle). GetFileType, NtQueryInformationFile(FileModeInformation) and the name
// queries can block on a synchronous handle another thread is reading, so they run on a helper thread made without
// loader notifications and are waited for 500 ms; a query still running shows "busy". The same helper adds, for file
// calls, " file-offset N" (SetFilePointerEx FILE_CURRENT) and " file-size N" (GetFileSizeEx), "n/a" for a pipe, and
// the buffer's " buffer 0xADDR State=.. Protect=0x.. Type=.." (VirtualQuery, which cannot block). Reported: the main
// thread (any call; its stall is repeated every 10 s as "for Ns (still)", up to 10 times, without counting against the
// cap) and any thread in a file/IO call. A non-main thread in a wait (INFINITE or 1 s or more) is idle, not stalled, and
// is neither reported nor listed unless --stall-all. "also-pending" lists at most 8 other
// pending calls, only the main thread's and file/IO calls. At most 64 other stall lines.
using SysDescribe = int(__stdcall*)(void* handle, char* out, unsigned capacity);
SysDescribe sys_describe;
struct StallSeen {
    std::uint64_t seq;
    ULONGLONG since;
    bool logged;
    ULONGLONG next_report;  // main thread: when to repeat the line
    int reports;
};
StallSeen* stall_seen;  // one per trace ring, allocated with the pool
long stall_lines;
constexpr long kStallLines = 64;
constexpr ULONGLONG kStallMs = 2000;
constexpr ULONGLONG kStallRepeatMs = 10000;
constexpr int kStallRepeats = 10;
constexpr int kAlsoPending = 8;
bool stall_all;  // --stall-all: report idle waits of other threads too

// Handles the shims created (x2w_launch_tag_handle), for the stall lines.
struct HandleTag {
    void* handle;
    char who[72];
};
constexpr int kHandleTags = 1024;
HandleTag handle_tags[kHandleTags];
SRWLOCK handle_tag_lock = SRWLOCK_INIT;

bool handle_tag(void* handle, char* out, std::size_t capacity) {
    bool found = false;
    AcquireSRWLockShared(&handle_tag_lock);
    for (const auto& tag : handle_tags)
        if (tag.handle == handle) {
            std::snprintf(out, capacity, "%s", tag.who);
            found = true;
            break;
        }
    ReleaseSRWLockShared(&handle_tag_lock);
    return found;
}

struct NtText {  // UNICODE_STRING
    USHORT Length;
    USHORT MaximumLength;
    PWSTR Buffer;
};
struct HandleQuery {
    HANDLE handle;
    volatile long refs;
    volatile long stage;  // 1: type, 2: mode, 3: name, 4: offset, 5: size
    DWORD type;
    LONG mode_status;
    ULONG mode;
    DWORD name_length;  // in wide characters, 0 when no name was found
    bool offset_ok;
    long long offset;
    bool size_ok;
    long long size;
    wchar_t name[520];
};
using NtQueryInformationFileFn = LONG(NTAPI*)(HANDLE, void*, void*, ULONG, ULONG);
using NtQueryObjectFn = LONG(NTAPI*)(HANDLE, ULONG, void*, ULONG, ULONG*);
using NtCreateThreadExFn = LONG(NTAPI*)(HANDLE*, ACCESS_MASK, void*, HANDLE, void*, void*, ULONG, SIZE_T, SIZE_T,
                                        SIZE_T, void*);
NtQueryInformationFileFn nt_query_file;
NtQueryObjectFn nt_query_object;
NtCreateThreadExFn nt_create_thread;

void handle_query_release(HandleQuery* query) {
    if (InterlockedDecrement(&query->refs) == 0) HeapFree(GetProcessHeap(), 0, query);
}

DWORD WINAPI handle_query_thread(void* parameter) {
    auto* query = static_cast<HandleQuery*>(parameter);
    query->type = GetFileType(query->handle);
    query->stage = 1;
    ULONG_PTR iosb[2] = {};
    query->mode_status = nt_query_file ? nt_query_file(query->handle, iosb, &query->mode, sizeof query->mode, 16)
                                       : -1;  // FileModeInformation
    query->stage = 2;
    DWORD length = GetFinalPathNameByHandleW(query->handle, query->name, 512, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (length == 0 || length >= 512) {
        // Pipes and devices have no DOS path: the object name (\Device\NamedPipe\x).
        alignas(8) std::uint8_t buffer[1100];
        ULONG got = 0;
        length = 0;
        if (nt_query_object && nt_query_object(query->handle, 1 /* ObjectNameInformation */, buffer, sizeof buffer, &got) >= 0) {
            const auto* text = reinterpret_cast<const NtText*>(buffer);
            length = text->Buffer ? text->Length / 2 : 0;
            if (length > 511) length = 511;
            if (length) std::memcpy(query->name, text->Buffer, length * 2);
        }
    }
    query->name_length = length;
    query->stage = 3;
    LARGE_INTEGER zero{}, at{};
    query->offset_ok = SetFilePointerEx(query->handle, zero, &at, FILE_CURRENT) != 0;
    query->offset = at.QuadPart;
    query->stage = 4;
    LARGE_INTEGER size{};
    query->size_ok = GetFileSizeEx(query->handle, &size) != 0;
    query->size = size.QuadPart;
    query->stage = 5;
    handle_query_release(query);
    return 0;
}

std::string object_type(HANDLE handle) {
    if (!nt_query_object) return "unknown";
    alignas(8) std::uint8_t buffer[512];
    ULONG got = 0;
    if (nt_query_object(handle, 2 /* ObjectTypeInformation */, buffer, sizeof buffer, &got) < 0) return "invalid";
    const auto* text = reinterpret_cast<const NtText*>(buffer);
    std::string out;
    for (USHORT i = 0; text->Buffer && i < text->Length / 2 && out.size() < 32; ++i)
        out += std::iswalnum(text->Buffer[i]) && text->Buffer[i] < 0x80 ? static_cast<char>(text->Buffer[i]) : '_';
    return out.empty() ? "unknown" : out;
}

// " handle-type T name N overlapped-handle=yes|no" for a file handle, from the helper thread.
std::string file_fields(HANDLE handle) {
    auto* query = static_cast<HandleQuery*>(HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(HandleQuery)));
    if (!query) return " handle-type unknown name unknown overlapped-handle=unknown";
    query->handle = handle;
    query->refs = 2;
    HANDLE thread = nullptr;
    // THREAD_CREATE_FLAGS_SKIP_THREAD_ATTACH: no DllMain, TLS callback or pe_map notification runs on it.
    if (!nt_create_thread || nt_create_thread(&thread, THREAD_ALL_ACCESS, nullptr, GetCurrentProcess(),
                                              reinterpret_cast<void*>(&handle_query_thread), query, 0x2, 0, 0, 0,
                                              nullptr) < 0) {
        thread = nullptr;
        query->refs = 1;
    }
    if (thread) {
        WaitForSingleObject(thread, 500);
        CloseHandle(thread);
    }
    const long stage = query->stage;
    std::string out = " handle-type ";
    if (stage >= 1) {
        const DWORD type = query->type & ~FILE_TYPE_REMOTE;
        out += type == FILE_TYPE_DISK ? "disk" : type == FILE_TYPE_PIPE ? "pipe" : type == FILE_TYPE_CHAR ? "char"
             : (query->type & FILE_TYPE_REMOTE) ? "remote" : "unknown";
    } else {
        out += "busy";
    }
    out += " name ";
    if (stage >= 3 && query->name_length) {
        std::wstring name(query->name, query->name_length);
        if (name.compare(0, 4, L"\\\\?\\") == 0) name = name.substr(4);
        const bool dos = name.size() > 2 && name[1] == L':';
        const auto cut = name.find_last_of(L"\\/");
        std::string shown;
        for (wchar_t c : dos && cut != std::wstring::npos ? name.substr(cut + 1) : name)
            shown += c > 0x20 && c < 0x7f ? static_cast<char>(c) : '_';
        out += dos ? "<path>\\" + shown : shown;
    } else {
        out += stage >= 3 ? "unknown" : "busy";
    }
    out += " overlapped-handle=";
    if (stage >= 2) out += query->mode_status < 0 ? "unknown" : (query->mode & 0x30) ? "no" : "yes";
    else out += "busy";
    char number[48];
    out += " file-offset ";
    if (stage >= 4 && query->offset_ok) {
        std::snprintf(number, sizeof number, "%lld", query->offset);
        out += number;
    } else {
        out += stage >= 4 ? "n/a" : "busy";
    }
    out += " file-size ";
    if (stage >= 5 && query->size_ok) {
        std::snprintf(number, sizeof number, "%lld", query->size);
        out += number;
    } else {
        out += stage >= 5 ? "n/a" : "busy";
    }
    handle_query_release(query);
    return out;
}

std::string handle_fields(HANDLE handle, bool file_call) {
    char text[64];
    std::snprintf(text, sizeof text, " handle 0x%llx", static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(handle)));
    std::string out = text;
    const std::string type = object_type(handle);
    if (!file_call) out += " object-type " + type;
    char who[80];
    if (handle_tag(handle, who, sizeof who)) out += std::string(" created-by ") + who;
    if (file_call || type == "File") out += file_fields(handle);
    char opened[400];
    if (sys_describe && sys_describe(handle, opened, sizeof opened)) out += std::string(" ") + opened;
    return out;
}

bool stall_file_call(const char* symbol) {
    static const char* const names[] = {"ReadFile", "WriteFile", "ReadFileEx", "WriteFileEx", "ReadFileScatter",
                                        "WriteFileGather", "GetOverlappedResult", "GetOverlappedResultEx",
                                        "DeviceIoControl", "NtReadFile", "NtWriteFile", "NtDeviceIoControlFile",
                                        "NtFsControlFile", "FlushFileBuffers", "ConnectNamedPipe", "PeekNamedPipe",
                                        "TransactNamedPipe", "LockFile", "LockFileEx", "CancelSynchronousIo"};
    for (const char* name : names)
        if (std::strcmp(symbol, name) == 0) return true;
    return false;
}

// The call's buffer, for the calls that take one in their first four arguments: "
// buffer 0xADDR State=COMMIT|RESERVE|FREE Protect=0x.. Type=PRIVATE|MAPPED|IMAGE".
std::string stall_buffer(const char* symbol, const std::uint64_t* args) {
    std::uint64_t address;
    if (!std::strcmp(symbol, "ReadFile") || !std::strcmp(symbol, "WriteFile") || !std::strcmp(symbol, "ReadFileEx")
        || !std::strcmp(symbol, "WriteFileEx")) address = args[1];
    else if (!std::strcmp(symbol, "DeviceIoControl")) address = args[2];
    else return "";
    char text[160];
    MEMORY_BASIC_INFORMATION info{};
    if (!address || !VirtualQuery(reinterpret_cast<const void*>(address), &info, sizeof info)) {
        std::snprintf(text, sizeof text, " buffer 0x%llx unqueryable", static_cast<unsigned long long>(address));
        return text;
    }
    std::snprintf(text, sizeof text, " buffer 0x%llx State=%s Protect=0x%lx Type=%s",
                  static_cast<unsigned long long>(address),
                  info.State == MEM_COMMIT ? "COMMIT" : info.State == MEM_RESERVE ? "RESERVE" : "FREE",
                  static_cast<unsigned long>(info.Protect),
                  info.Type == MEM_PRIVATE ? "PRIVATE" : info.Type == MEM_MAPPED ? "MAPPED"
                  : info.Type == MEM_IMAGE ? "IMAGE" : "none");
    return text;
}

// Calls a non-main thread makes while idle (waits on events, semaphores, mutexes, condition variables, ports,
// messages); the timeout argument says how long, when it is one of the first four.
bool stall_idle_wait(const char* symbol, const std::uint64_t* args) {
    struct Wait {
        const char* name;
        int timeout_arg;  // -1: none or not an immediate value (counts as infinite)
    };
    static const Wait waits[] = {{"WaitForSingleObject", 1}, {"WaitForSingleObjectEx", 1},
                                 {"WaitForMultipleObjects", 3}, {"WaitForMultipleObjectsEx", 3},
                                 {"MsgWaitForMultipleObjects", 3}, {"MsgWaitForMultipleObjectsEx", 3},
                                 {"SignalObjectAndWait", 3}, {"NtWaitForSingleObject", -1},
                                 {"ZwWaitForSingleObject", -1}, {"NtWaitForMultipleObjects", -1},
                                 {"SleepConditionVariableCS", 2}, {"SleepConditionVariableSRW", 2},
                                 {"RtlSleepConditionVariableCS", 2}, {"RtlSleepConditionVariableSRW", 2},
                                 {"WaitOnAddress", 3}, {"RtlWaitOnAddress", -1}, {"NtWaitForAlertByThreadId", -1},
                                 {"NtWaitForKeyedEvent", -1}, {"NtRemoveIoCompletion", -1},
                                 {"GetQueuedCompletionStatus", 4}, {"GetQueuedCompletionStatusEx", 5},
                                 {"GetMessageW", -1}, {"GetMessageA", -1}, {"Sleep", 0}, {"SleepEx", 0}};
    for (const Wait& wait : waits) {
        if (std::strcmp(symbol, wait.name) != 0) continue;
        if (wait.timeout_arg < 0 || wait.timeout_arg > 3) return true;
        const std::uint32_t ms = static_cast<std::uint32_t>(args[wait.timeout_arg]);
        return ms == 0xFFFFFFFFu || ms >= 1000;  // any wait of a second or more is a thread idling, not stuck
    }
    return false;
}

// Is this pending call worth a stall line (or an also-pending entry)?
bool stall_listed(DWORD tid, const TraceDesc* desc, const std::uint64_t* args) {
    const char* bang = std::strchr(desc->name, '!');
    const char* symbol = bang ? bang + 1 : desc->name;
    if (tid == trace_main_tid || stall_all) return true;
    if (stall_file_call(symbol)) return true;
    return !stall_idle_wait(symbol, args);
}

void stall_report(DWORD tid, const TraceDesc* desc, std::uint64_t caller, const std::uint64_t* args, ULONGLONG ms,
                  const std::string& others, bool still) {
    if (tid != trace_main_tid && InterlockedIncrement(&stall_lines) > kStallLines) {
        if (stall_lines == kStallLines + 1) log_line("stalled-threads more are not logged");
        return;
    }
    char where[160];
    describe(reinterpret_cast<const void*>(caller), where, sizeof where);
    const char* bang = std::strchr(desc->name, '!');
    const char* symbol = bang ? bang + 1 : desc->name;
    std::string extra;
    if (stall_file_call(symbol)) {
        extra = handle_fields(reinterpret_cast<HANDLE>(args[0]), true) + stall_buffer(symbol, args);
    } else if (!std::strcmp(symbol, "WaitForSingleObject") || !std::strcmp(symbol, "WaitForSingleObjectEx")
               || !std::strcmp(symbol, "NtWaitForSingleObject") || !std::strcmp(symbol, "ZwWaitForSingleObject")) {
        extra = handle_fields(reinterpret_cast<HANDLE>(args[0]), false);
    } else if (!std::strcmp(symbol, "SignalObjectAndWait")) {
        extra = handle_fields(reinterpret_cast<HANDLE>(args[1]), false);
    } else if (!std::strcmp(symbol, "WaitForMultipleObjects") || !std::strcmp(symbol, "WaitForMultipleObjectsEx")
               || !std::strcmp(symbol, "MsgWaitForMultipleObjects") || !std::strcmp(symbol, "MsgWaitForMultipleObjectsEx")
               || !std::strcmp(symbol, "NtWaitForMultipleObjects")) {
        const std::uint64_t count = args[0] < 4 ? args[0] : 4;
        HANDLE handles[4] = {};
        SIZE_T got = 0;
        if (count && ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(args[1]), handles,
                                       count * sizeof(HANDLE), &got) && got == count * sizeof(HANDLE))
            for (std::uint64_t i = 0; i < count; ++i) extra += handle_fields(handles[i], false);
        if (args[0] > 4) extra += " more-handles " + std::to_string(args[0] - 4);
    }
    extra += others;
    log_line("stalled thread %lu(%s) in %s(0x%llx,0x%llx,0x%llx,0x%llx) for %llus%s caller=%s%s", tid,
             tid == trace_main_tid ? "main" : "program", desc->name, static_cast<unsigned long long>(args[0]),
             static_cast<unsigned long long>(args[1]), static_cast<unsigned long long>(args[2]),
             static_cast<unsigned long long>(args[3]), static_cast<unsigned long long>(ms / 1000), still ? " (still)" : "", where,
             extra.c_str());
}

// One scan of every ring (the watchdog, once a second). First every ring's newest call is noted (pending since when),
// then each newly stalled one is logged with every other pending call ("also-pending").
struct PendingCall {
    DWORD tid;
    const TraceDesc* desc;
    std::uint64_t caller;
    std::uint64_t args[4];
    ULONGLONG ms;
    bool report;
    bool still;
};
void stall_scan() {
    if (!trace_body || !stall_seen) return;
    const long used = trace_pool_used < kTraceRings ? trace_pool_used : kTraceRings;
    const ULONGLONG now = GetTickCount64();
    static PendingCall pending[256];  // only the watchdog scans
    int found = 0;
    for (long i = 0; i < used; ++i) {
        const TraceRing& ring = trace_pool[i];
        StallSeen& seen = stall_seen[i];
        const std::uint64_t count = ring.count;
        if (!count || !ring.tid) continue;
        const TraceEntry& entry = ring.entries[(count - 1) % kTraceRing];
        const std::uint64_t seq = entry.seq;
        if (seq != count) {  // returned, or being written
            seen.seq = 0;
            continue;
        }
        PendingCall call{ring.tid, entry.desc, entry.caller, {}, 0, false, false};
        for (int a = 0; a < 4; ++a) call.args[a] = entry.args[a];
        if (entry.seq != seq || !call.desc) continue;
        if (seen.seq != seq) {
            seen.seq = seq;
            seen.since = now;
            seen.logged = false;
        }
        call.ms = now - seen.since;
        if (seen.seq == seq && call.ms >= kStallMs && stall_listed(call.tid, call.desc, call.args)) {
            if (!seen.logged) {
                seen.logged = true;
                seen.reports = 0;
                seen.next_report = now + kStallRepeatMs;
                call.report = true;
            } else if (call.tid == trace_main_tid && seen.reports < kStallRepeats && now >= seen.next_report) {
                ++seen.reports;
                seen.next_report = now + kStallRepeatMs;
                call.report = true;
                call.still = true;
            }
            if (found < 256) pending[found++] = call;  // main, file/IO and (--stall-all) everything else
        }
    }
    for (int i = 0; i < found; ++i) {
        if (!pending[i].report) continue;
        std::string others;
        int listed = 0;
        for (int j = 0; j < found; ++j) {
            if (j == i) continue;
            if (listed == kAlsoPending) {
                others += " also-pending-more";
                break;
            }
            ++listed;
            const PendingCall& o = pending[j];
            char text[256];
            std::snprintf(text, sizeof text, " also-pending %lu(%s) %s(0x%llx,0x%llx,0x%llx,0x%llx) for %llus", o.tid,
                          o.tid == trace_main_tid ? "main" : "program", o.desc->name,
                          static_cast<unsigned long long>(o.args[0]), static_cast<unsigned long long>(o.args[1]),
                          static_cast<unsigned long long>(o.args[2]), static_cast<unsigned long long>(o.args[3]),
                          static_cast<unsigned long long>(o.ms / 1000));
            if (others.size() + std::strlen(text) > 2400) {
                others += " also-pending-more";
                break;
            }
            others += text;
        }
        stall_report(pending[i].tid, pending[i].desc, pending[i].caller, pending[i].args, pending[i].ms, others, pending[i].still);
    }
}

void stall_init() {
    stall_seen = static_cast<StallSeen*>(
        VirtualAlloc(nullptr, sizeof(StallSeen) * kTraceRings, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    const HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    nt_query_file = reinterpret_cast<NtQueryInformationFileFn>(GetProcAddress(ntdll, "NtQueryInformationFile"));
    nt_query_object = reinterpret_cast<NtQueryObjectFn>(GetProcAddress(ntdll, "NtQueryObject"));
    nt_create_thread = reinterpret_cast<NtCreateThreadExFn>(GetProcAddress(ntdll, "NtCreateThreadEx"));
}

void* report(const std::string& dll, const std::string& symbol, const char* route, const char* kind, void* address) {
    err_printf( "[x2w] import %s!%s -> %s\n", dll.c_str(), symbol.c_str(), route);
    ++route_counts[kind];
    // Watch the program's d3d12* imports for the run log and the heap guard, and (heap guard) every shim import, so
    // the guard can check the process heap at those calls; stubs record their own calls.
    const bool bound = address && std::strncmp(kind, "stub", 4) != 0 && std::strcmp(kind, "missing") != 0;
    const bool d3d12 = dll.rfind("d3d12", 0) == 0;
    if (bound && ((d3d12 && (log_file != INVALID_HANDLE_VALUE || heap_guard)) || (heap_guard && std::strcmp(kind, "shim") == 0)))
        return trace_wrap(dll, symbol, make_watch(dll, symbol, address));
    return trace_wrap(dll, symbol, address);
}

// Module identity. A title finds its own resources and files through GetModuleHandle(NULL),
// GetModuleFileName(NULL) and the PEB's ImageBaseAddress, which in this process name x2w_launch.exe. The
// launcher therefore (1) binds the title's and its package DLLs' imports of the library-loader functions
// below to replacements that answer for the mapped images and forward everything else to Windows, and (2)
// sets PEB->ImageBaseAddress to the title's base while the title runs (start_identity). The loader's module
// list is left alone: its entries are linked into ntdll's lists, hash table and base-address tree, which have
// no public API, and an entry without them is not found. Not covered: a function pointer the title gets from
// GetProcAddress (it reaches Windows directly; with the PEB set, GetModuleHandle(NULL) is still right),
// GetCommandLine, the PSAPI and Toolhelp module lists, and debuggers, which still show the launcher.
// --host-identity turns both off.
bool keep_host_identity;

const Region* region_at(std::uintptr_t address) {
    for (const auto& region : regions)
        if (address >= region.base && address - region.base < region.size) return &region;
    return nullptr;
}

const Region* region_of(HMODULE module) {
    for (const auto& region : regions)
        if (reinterpret_cast<std::uintptr_t>(module) == region.base) return &region;
    return nullptr;
}

// A mapped image by the name GetModuleHandle accepts: a file name, with ".dll" assumed without an extension,
// or a full path. Case is ignored, as by Windows.
const Region* region_named(const wchar_t* name) {
    const std::wstring text = name;
    const bool has_path = text.find_first_of(L"\\/") != std::wstring::npos;
    std::string file = lower(narrow(file_of(text)));
    if (file.find('.') == std::string::npos) file += ".dll";
    for (const auto& region : regions) {
        if (has_path ? _wcsicmp(region.path.c_str(), text.c_str()) == 0 : region.name == file) return &region;
    }
    return nullptr;
}

// ---------------------------------------------------------------- dynamic loads (see the header comment)
SRWLOCK dynamic_lock = SRWLOCK_INIT;
std::set<std::string> dynamic_logged;
std::map<HMODULE, std::string> shim_names;  // shim modules loaded by a dynamic load, by handle

void log_dynamic_once(const std::string& line) {
    AcquireSRWLockExclusive(&dynamic_lock);
    const bool first = dynamic_logged.insert(line).second;
    ReleaseSRWLockExclusive(&dynamic_lock);
    if (!first) return;
    err_printf( "[x2w] %s\n", line.c_str());
    log_line("%s", line.c_str());
}

// "name.dll" for a load request: the file component, lower case, with ".dll" when it has no extension.
std::string dll_file_name(const std::wstring& request) {
    std::string name = lower(narrow(file_of(request)));
    if (name.find('.') == std::string::npos) name += ".dll";
    return name;
}

bool xgr_gateway_on() { return xgr_mode != "shim"; }

// The shim for a DLL name from a --shims directory, loading it if needed, or null. With --xgr other
// than shim, xgameruntime.dll is the gateway: x2w_xgr.dll from a --shims directory, else from the
// launcher's own shims directory.
HMODULE shim_for(const std::string& name) {
    std::vector<std::wstring> directories = shim_dirs;
    const bool gateway = name == kXgrName && xgr_gateway_on();
    if (gateway) directories.push_back(launcher_dir + L"\\shims");
    for (const auto& directory : directories) {
        const std::wstring path = directory + L"\\" + (gateway ? std::wstring(kXgrGateway) : widen(name));
        if (!is_file(path)) continue;
        AcquireSRWLockExclusive(&dynamic_lock);
        HMODULE& module = shim_modules[name];
        if (!module) module = LoadLibraryExW(path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
        if (module) shim_names[module] = name;
        HMODULE result = module;
        ReleaseSRWLockExclusive(&dynamic_lock);
        return result;
    }
    return nullptr;
}

std::wstring from_ansi(const char* text) {
    const int size = MultiByteToWideChar(CP_ACP, 0, text, -1, nullptr, 0);
    if (size <= 0) return {};
    std::wstring out(static_cast<std::size_t>(size - 1), L'\0');
    MultiByteToWideChar(CP_ACP, 0, text, -1, out.data(), size);
    return out;
}

HMODULE title_module() { return reinterpret_cast<HMODULE>(regions.empty() ? 0 : regions[0].base); }

HMODULE WINAPI identity_GetModuleHandleW(LPCWSTR name) {
    if (!name) return title_module();
    if (const Region* region = region_named(name)) return reinterpret_cast<HMODULE>(region->base);
    return GetModuleHandleW(name);
}

HMODULE WINAPI identity_GetModuleHandleA(LPCSTR name) {
    if (!name) return title_module();
    const std::wstring wide = from_ansi(name);
    if (const Region* region = region_named(wide.c_str())) return reinterpret_cast<HMODULE>(region->base);
    return GetModuleHandleA(name);
}

// Mapped images keep no reference count, so the PIN and UNCHANGED_REFCOUNT flags change nothing for them.
BOOL identity_handle_ex(DWORD flags, const void* name, bool wide, HMODULE* out) {
    if (!out) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    const Region* region = nullptr;
    if (flags & GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS) {
        region = region_at(reinterpret_cast<std::uintptr_t>(name));
    } else if (!name) {
        region = regions.empty() ? nullptr : &regions[0];
    } else {
        region = wide ? region_named(static_cast<const wchar_t*>(name))
                      : region_named(from_ansi(static_cast<const char*>(name)).c_str());
    }
    if (region) {
        *out = reinterpret_cast<HMODULE>(region->base);
        return TRUE;
    }
    return wide ? GetModuleHandleExW(flags, static_cast<LPCWSTR>(name), out)
                : GetModuleHandleExA(flags, static_cast<LPCSTR>(name), out);
}

BOOL WINAPI identity_GetModuleHandleExW(DWORD flags, LPCWSTR name, HMODULE* out) {
    return identity_handle_ex(flags, name, true, out);
}

BOOL WINAPI identity_GetModuleHandleExA(DWORD flags, LPCSTR name, HMODULE* out) {
    return identity_handle_ex(flags, name, false, out);
}

// Windows semantics for a short buffer: the copy is cut to size - 1 characters and terminated, the
// function returns size and sets ERROR_INSUFFICIENT_BUFFER.
template <typename Char>
DWORD copy_name(const std::basic_string<Char>& name, Char* buffer, DWORD size) {
    if (!buffer || !size) {
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return 0;
    }
    if (name.size() < size) {
        std::memcpy(buffer, name.c_str(), (name.size() + 1) * sizeof(Char));
        return static_cast<DWORD>(name.size());
    }
    std::memcpy(buffer, name.data(), (size - 1) * sizeof(Char));
    buffer[size - 1] = 0;
    SetLastError(ERROR_INSUFFICIENT_BUFFER);
    return size;
}

const Region* region_for_file_name(HMODULE module) {
    if (!module) return regions.empty() ? nullptr : &regions[0];
    return region_of(module);
}

DWORD WINAPI identity_GetModuleFileNameW(HMODULE module, LPWSTR buffer, DWORD size) {
    if (const Region* region = region_for_file_name(module)) return copy_name(region->path, buffer, size);
    return GetModuleFileNameW(module, buffer, size);
}

DWORD WINAPI identity_GetModuleFileNameA(HMODULE module, LPSTR buffer, DWORD size) {
    if (const Region* region = region_for_file_name(module)) {
        const int length = WideCharToMultiByte(CP_ACP, 0, region->path.c_str(), -1, nullptr, 0, nullptr, nullptr);
        std::string ansi(length > 0 ? static_cast<std::size_t>(length - 1) : 0, '\0');
        if (length > 0) WideCharToMultiByte(CP_ACP, 0, region->path.c_str(), -1, ansi.data(), length, nullptr, nullptr);
        return copy_name(ansi, buffer, size);
    }
    return GetModuleFileNameA(module, buffer, size);
}

struct IdentityHook {
    const char* symbol;
    void* replacement;
};
const IdentityHook identity_hooks[] = {
    {"GetModuleHandleW", reinterpret_cast<void*>(&identity_GetModuleHandleW)},
    {"GetModuleHandleA", reinterpret_cast<void*>(&identity_GetModuleHandleA)},
    {"GetModuleHandleExW", reinterpret_cast<void*>(&identity_GetModuleHandleExW)},
    {"GetModuleHandleExA", reinterpret_cast<void*>(&identity_GetModuleHandleExA)},
    {"GetModuleFileNameW", reinterpret_cast<void*>(&identity_GetModuleFileNameW)},
    {"GetModuleFileNameA", reinterpret_cast<void*>(&identity_GetModuleFileNameA)},
};

// The replacement for dll!name when the import would go to Windows, or null. The functions live in kernel32
// (forwarded to kernelbase) and in the library-loader API sets.
void* identity_hook(const std::string& dll, const char* name) {
    if (keep_host_identity || !name) return nullptr;
    if (dll != "kernel32.dll" && dll != "kernelbase.dll" && dll.rfind("api-ms-win-core-libraryloader-", 0) != 0)
        return nullptr;
    for (const auto& hook : identity_hooks)
        if (std::strcmp(hook.symbol, name) == 0) return hook.replacement;
    return nullptr;
}

// The system layer's replacement for dll!name (kernel32, kernelbase, api-ms-win-core-*), or null.
void* sys_hook(const std::string& dll, const char* name) {
    return sys_lookup && name ? sys_lookup(dll.c_str(), name) : nullptr;
}

// PEB->ImageBaseAddress (gs:[0x60] + 0x10). While it holds the title's base, Windows functions that take a
// null module (FindResource, LoadString, the default stack size of new threads) use the title's image. The
// launcher no longer asks Windows for its own module after this point.
void** peb_image_base() {
    auto* peb = reinterpret_cast<std::uint8_t*>(__readgsqword(0x60));
    return reinterpret_cast<void**>(peb + 0x10);
}

void* host_image_base;

void start_identity(void* title) {
    if (keep_host_identity) return;
    host_image_base = InterlockedExchangePointer(peb_image_base(), title);
}

void end_identity() {
    if (host_image_base) InterlockedExchangePointer(peb_image_base(), host_image_base);
}

// ---------------------------------------------------------------- the program's implicit TLS in slot 0
// An EXE built with whole-program optimization (/GL + /LTCG, as every Microsoft GDK sample is) reaches its
// implicit TLS as ThreadLocalStoragePointer[0] + offset without reading _tls_index, since the Windows
// loader always gives the process EXE index 0 (measured on the stand-in samples: UITK's magic statics do
// mov rax, gs:[58h]; mov rcx, [rax], and stayed empty under x2w_launch). Here index 0 is the launcher's.
// pe_map gives the program a carrier DLL's index N whose block the loader fills from the program's
// template on every thread, so the launcher makes entry 0 of each thread's TLS vector point at that same
// block: on every thread that exists when the program is mapped, and in its own TLS callback on each new
// thread's attach; on thread detach it puts its own entry back, so ntdll frees each block once. The alias for a
// new thread is made by pe_map's thread observer (thread_observer below) before pe_map hands the attach to any
// mapped image, and taken down after the last mapped image's detach: Windows calls the launcher's own TLS callback
// (an EXE's) after every DLL's thread attach and before every DLL's thread detach, so a title TLS callback or
// thread_local initializer or destructor compiled for slot 0 otherwise ran with the launcher's empty block in
// entry 0 and wrote the title's TLS data over whatever heap block followed it (seen as faults inside ntdll's
// LdrpInitializeThread walking a module list whose entries had been overwritten). The
// launcher keeps no implicit TLS data of its own (no thread_local, and it is built with
// /Zc:threadSafeInit-, so function-local statics do not use _Init_thread_epoch), so none of its code reads
// entry 0. The run log gets "tls-slot0 index N threads T".
DWORD slot0_index = 0;  // the program's carrier index, 0 when the program has no implicit TLS block
SRWLOCK slot0_lock = SRWLOCK_INIT;
std::map<DWORD, void*>* slot0_saved;  // thread ID -> the launcher's own entry 0 (allocated once, never freed)

bool slot0_alias(void** vector, DWORD thread) {
    if (!vector || !vector[slot0_index] || vector[0] == vector[slot0_index]) return false;
    AcquireSRWLockExclusive(&slot0_lock);
    (*slot0_saved)[thread] = vector[0];
    vector[0] = vector[slot0_index];
    ReleaseSRWLockExclusive(&slot0_lock);
    return true;
}

void slot0_restore(void** vector, DWORD thread) {
    AcquireSRWLockExclusive(&slot0_lock);
    auto it = slot0_saved->find(thread);
    if (it != slot0_saved->end()) {
        if (vector) vector[0] = it->second;
        slot0_saved->erase(it);
    }
    ReleaseSRWLockExclusive(&slot0_lock);
}

void** current_tls_vector() { return reinterpret_cast<void**>(__readgsqword(0x58)); }

// After mapping: the carrier index pe_map wrote to the program's AddressOfIndex, then every thread.
void slot0_start(void* base) {
    const auto* bytes = static_cast<const std::uint8_t*>(base);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(bytes + reinterpret_cast<const IMAGE_DOS_HEADER*>(base)->e_lfanew);
    const auto& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS];
    if (!dir.VirtualAddress) return;
    const auto* tls = reinterpret_cast<const IMAGE_TLS_DIRECTORY64*>(bytes + dir.VirtualAddress);
    if (tls->StartAddressOfRawData == tls->EndAddressOfRawData && !tls->SizeOfZeroFill) return;
    const DWORD index = *reinterpret_cast<const DWORD*>(tls->AddressOfIndex);
    if (!index) return;
    slot0_saved = new std::map<DWORD, void*>;
    slot0_index = index;
    using QueryInfo = LONG(NTAPI*)(HANDLE, ULONG, PVOID, ULONG, PULONG);
    struct BasicInfo {
        LONG exit_status;
        void* teb;
        void* client[2];
        ULONG_PTR affinity;
        LONG priority, base_priority;
    };
    const auto query = reinterpret_cast<QueryInfo>(
        GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryInformationThread"));
    unsigned threads = slot0_alias(current_tls_vector(), GetCurrentThreadId()) ? 1 : 0;
    // Other threads' vectors are written under the loader lock: ntdll replaces a thread's vector (a later DLL
    // with TLS) and builds a new thread's vector under that lock, so the vector read here is the live one.
    using LockLoader = LONG(NTAPI*)(ULONG, ULONG*, PVOID*);
    using UnlockLoader = LONG(NTAPI*)(ULONG, PVOID);
    const HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
    const auto lock_loader = reinterpret_cast<LockLoader>(GetProcAddress(ntdll, "LdrLockLoaderLock"));
    const auto unlock_loader = reinterpret_cast<UnlockLoader>(GetProcAddress(ntdll, "LdrUnlockLoaderLock"));
    PVOID cookie = nullptr;
    const bool locked = lock_loader && unlock_loader && lock_loader(0, nullptr, &cookie) >= 0;
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snapshot != INVALID_HANDLE_VALUE && query) {
        THREADENTRY32 entry{};
        entry.dwSize = sizeof entry;
        for (BOOL more = Thread32First(snapshot, &entry); more; more = Thread32Next(snapshot, &entry)) {
            if (entry.th32OwnerProcessID != GetCurrentProcessId() || entry.th32ThreadID == GetCurrentThreadId()) continue;
            HANDLE thread = OpenThread(THREAD_QUERY_INFORMATION, FALSE, entry.th32ThreadID);
            if (!thread) continue;
            BasicInfo info{};
            if (query(thread, 0 /* ThreadBasicInformation */, &info, sizeof info, nullptr) >= 0 && info.teb) {
                auto** vector = *reinterpret_cast<void***>(static_cast<std::uint8_t*>(info.teb) + 0x58);
                if (slot0_alias(vector, entry.th32ThreadID)) ++threads;
            }
            CloseHandle(thread);
        }
    }
    if (snapshot != INVALID_HANDLE_VALUE) CloseHandle(snapshot);
    if (locked) unlock_loader(0, cookie);
    log_line("tls-slot0 index %lu threads %u", static_cast<unsigned long>(index), threads);
}

// ---------------------------------------------------------------- thread initialization
// pe_map tells the launcher about every thread attach and detach it forwards to the mapped images
// (pe_map_thread_observer): before the first image, before each image's TLS callbacks and entry point, and after
// the last. At the start of an attach the slot-0 alias is made; at the end of a detach it is taken down. Each
// thread's phase is kept in a dynamic TLS slot (TlsAlloc; the launcher has no implicit TLS) for the fault lines'
// " thread-init-phase ..." part. For the first 8 threads after mapping, "thread-init tid N tls-ok images K" (or
// "tls-missing IMAGE index I") says whether every mapped image with TLS data has its block on that thread and,
// with an alias, entry 0 points at the program's block, checked before any mapped image is notified.
enum PhaseCode : std::uintptr_t { PHASE_NONE = 0, PHASE_ATTACH = 1, PHASE_TLS_CALLBACK = 2, PHASE_DLLMAIN = 3,
                                  PHASE_ATTACHED = 4, PHASE_DETACH = 5, PHASE_MAIN = 6, PHASE_WATCHDOG = 7 };
DWORD phase_slot = TLS_OUT_OF_INDEXES;
volatile long mapping_done, thread_init_lines;
constexpr long kThreadInitLines = 8;

void set_phase(PhaseCode code, const void* base = nullptr) {
    if (phase_slot != TLS_OUT_OF_INDEXES)
        TlsSetValue(phase_slot, reinterpret_cast<void*>(reinterpret_cast<std::uintptr_t>(base) | code));
}

// The image's TLS index (as pe_map wrote it) when it has TLS data, else -1.
long long image_tls_index(std::uintptr_t base) {
    const auto* bytes = reinterpret_cast<const std::uint8_t*>(base);
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(bytes + reinterpret_cast<const IMAGE_DOS_HEADER*>(bytes)->e_lfanew);
    const auto& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS];
    if (!dir.VirtualAddress) return -1;
    const auto* tls = reinterpret_cast<const IMAGE_TLS_DIRECTORY64*>(bytes + dir.VirtualAddress);
    if (tls->StartAddressOfRawData == tls->EndAddressOfRawData && !tls->SizeOfZeroFill) return -1;
    return *reinterpret_cast<const DWORD*>(tls->AddressOfIndex);
}

void log_thread_init() {
    if (!InterlockedCompareExchange(&mapping_done, 0, 0) || log_file == INVALID_HANDLE_VALUE) return;
    if (InterlockedIncrement(&thread_init_lines) > kThreadInitLines) return;
    void** vector = current_tls_vector();
    const DWORD tid = GetCurrentThreadId();
    unsigned images = 0;
    const std::size_t count = regions.size();
    for (std::size_t i = 0; i < count; ++i) {
        const long long index = image_tls_index(regions[i].base);
        if (index < 0) continue;
        ++images;
        if (!vector || !vector[index]) {
            log_line("thread-init tid %lu tls-missing %s index %lld", static_cast<unsigned long>(tid),
                     regions[i].label.c_str(), index);
            return;
        }
        if (i == 0 && slot0_index && vector[0] != vector[index]) {
            log_line("thread-init tid %lu tls-missing %s slot0", static_cast<unsigned long>(tid), regions[i].label.c_str());
            return;
        }
    }
    log_line("thread-init tid %lu tls-ok images %u", static_cast<unsigned long>(tid), images);
}

void __cdecl thread_observer(DWORD reason, int phase, void* base) {
    if (reason == DLL_THREAD_ATTACH) {
        if (phase == 0) {
            set_phase(PHASE_ATTACH);
            if (slot0_index) slot0_alias(current_tls_vector(), GetCurrentThreadId());
            log_thread_init();
        } else if (phase == 1) {
            set_phase(PHASE_TLS_CALLBACK, base);
        } else if (phase == 2) {
            set_phase(PHASE_DLLMAIN, base);
        } else {
            set_phase(PHASE_ATTACHED);
        }
    } else if (reason == DLL_THREAD_DETACH) {
        if (phase == 1) set_phase(PHASE_TLS_CALLBACK, base);
        else if (phase == 2) set_phase(PHASE_DLLMAIN, base);
        else set_phase(PHASE_DETACH);
        if (phase == 3 && slot0_index) slot0_restore(current_tls_vector(), GetCurrentThreadId());
    }
}
bool observer_set;

// " thread-init-phase P fn MODULE+0xRVA" for a fault outside the mapped images on a thread that is starting or
// ending (or has not reached mapped code): P is loader-before-attach (no attach forwarded yet: ntdll's own
// thread initialization), attach-begin, tls-callback-of IMAGE, dllmain-of IMAGE, before-thread-fn (every attach
// done; the thread's own function has not left a mapped frame) or detach; fn is the start of the faulting
// function from its unwind data.
std::string thread_init_text(const EXCEPTION_POINTERS* info, const std::string& chain) {
    const auto at = reinterpret_cast<std::uintptr_t>(info->ExceptionRecord->ExceptionAddress);
    if (region_at(at) || phase_slot == TLS_OUT_OF_INDEXES) return {};
    const auto value = reinterpret_cast<std::uintptr_t>(TlsGetValue(phase_slot));
    const auto code = static_cast<PhaseCode>(value & 7);
    const auto image = value & ~std::uintptr_t{7};
    if (code == PHASE_MAIN || code == PHASE_WATCHDOG) return {};
    if (code == PHASE_ATTACHED && chain.rfind(" callers ", 0) == 0) return {};
    std::string phase;
    switch (code) {
    case PHASE_NONE: phase = "loader-before-attach"; break;
    case PHASE_ATTACH: phase = "attach-begin"; break;
    case PHASE_ATTACHED: phase = "before-thread-fn"; break;
    case PHASE_DETACH: phase = "detach"; break;
    default: {
        const Region* region = region_at(image);
        phase = std::string(code == PHASE_TLS_CALLBACK ? "tls-callback-of " : "dllmain-of ")
            + (region ? region->label : std::string("unknown"));
    }
    }
    std::string text = " thread-init-phase " + phase;
    DWORD64 module = 0;
    if (const auto* function = RtlLookupFunctionEntry(static_cast<DWORD64>(at), &module, nullptr)) {
        char where[160];
        describe(reinterpret_cast<const void*>(module + function->BeginAddress), where, sizeof where);
        text += std::string(" fn ") + where;
    }
    return text;
}

// The Windows DLL of a shim's name (the loader's search path, then System32), loaded by full path so it is
// not the shim, or null. Cached (a namespace-scope map: the launcher keeps no function-local statics with
// dynamic initializers, see "The program's implicit TLS in slot 0").
std::map<std::string, HMODULE> twins;
HMODULE windows_twin(const std::string& name) {
    AcquireSRWLockExclusive(&dynamic_lock);
    auto it = twins.find(name);
    if (it == twins.end()) {
        wchar_t found[MAX_PATH];
        std::wstring path;
        if (SearchPathW(nullptr, widen(name).c_str(), nullptr, MAX_PATH, found, nullptr)) path = found;
        bool ours = false;
        for (const auto& directory : shim_dirs)
            if (_wcsicmp(directory_of(path).c_str(), directory.c_str()) == 0) ours = true;
        if (path.empty() || ours) {
            const UINT length = GetSystemDirectoryW(found, MAX_PATH);
            path = std::wstring(found, length) + L"\\" + widen(name);
        }
        HMODULE module = is_file(path) ? LoadLibraryExW(path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH) : nullptr;
        if (module && GetProcAddress(module, "x2w_shimgen_dll")) module = nullptr;  // our own shim again
        it = twins.emplace(name, module).first;
    }
    HMODULE module = it->second;
    ReleaseSRWLockExclusive(&dynamic_lock);
    return module;
}

std::string shim_name_of(HMODULE module) {
    if (!module) return {};  // a shim that failed to load is recorded with a null handle
    AcquireSRWLockShared(&dynamic_lock);
    auto it = shim_names.find(module);
    std::string name = it == shim_names.end() ? std::string() : it->second;
    if (name.empty())
        for (const auto& [key, handle] : shim_modules)
            if (handle == module) name = key;
    ReleaseSRWLockShared(&dynamic_lock);
    return name;
}

void* map_package(const std::string& key);
void* __cdecl resolve(const char* dll, const char* name, std::uint32_t ordinal);
void* crash_hook(const std::string& dll, const char* name);
void* heap_hook(const std::string& dll, const char* name);
void* package_heap_hook(const std::string& dll, void* base, const char* name);

// True for a load request naming a file in the program's folder: a bare name, or a path whose folder is it.
bool package_request(const std::wstring& request) {
    if (request.find_first_of(L"\\/") == std::wstring::npos) return true;
    return _wcsicmp(directory_of(request).c_str(), package_dir.c_str()) == 0;
}

HMODULE WINAPI hook_LoadLibraryExW(LPCWSTR request, HANDLE file, DWORD flags) {
    if (!request) return LoadLibraryExW(request, file, flags);
    const std::string name = dll_file_name(request);
    if (!(flags & (LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_DATAFILE_EXCLUSIVE | LOAD_LIBRARY_AS_IMAGE_RESOURCE))) {
        if (HMODULE shim = shim_for(name)) {
            log_dynamic_once("dynamic-load " + name + " -> " +
                             (name == kXgrName && xgr_gateway_on() ? "gateway (" + xgr_mode + ")" : std::string("shim")));
            return shim;
        }
        // An image pe_map already mapped (the program or a package DLL) is returned as Windows returns a loaded
        // module; a DLL in the program's folder is mapped like a static import of it, so the program never gets
        // a second copy from the Windows loader's search.
        if (const Region* region = region_named(request)) {
            log_dynamic_once("dynamic-load " + name + " -> mapped");
            return reinterpret_cast<HMODULE>(region->base);
        }
        // A load restricted to System32 never reaches the program's folder, under Windows or here.
        const bool system_only = (flags & LOAD_LIBRARY_SEARCH_SYSTEM32) &&
                                 !(flags & (LOAD_LIBRARY_SEARCH_APPLICATION_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS));
        if (!system_only && package_request(request) && is_file(package_dir + L"\\" + widen(name))) {
            if (void* base = map_package(name)) {
                log_dynamic_once("dynamic-load " + name + " -> package");
                return static_cast<HMODULE>(base);
            }
        }
    }
    HMODULE module = LoadLibraryExW(request, file, flags);
    const DWORD error = GetLastError();
    log_dynamic_once("dynamic-load " + name + (module ? " -> loader" : " -> failed"));
    SetLastError(error);
    return module;
}
HMODULE WINAPI hook_LoadLibraryW(LPCWSTR request) { return hook_LoadLibraryExW(request, nullptr, 0); }
HMODULE WINAPI hook_LoadLibraryExA(LPCSTR request, HANDLE file, DWORD flags) {
    if (!request) return LoadLibraryExA(request, file, flags);
    return hook_LoadLibraryExW(from_ansi(request).c_str(), file, flags);
}
HMODULE WINAPI hook_LoadLibraryA(LPCSTR request) { return hook_LoadLibraryExA(request, nullptr, 0); }

// An api-ms-win-core-* API set name is answered with its host module (kernelbase, kernel32 or ntdll, which
// every process has loaded). Windows' GetModuleHandle does not resolve API set names on every build, and a C
// runtime that asks for one and gets null would look its functions up in no module.
HMODULE api_set_host(LPCWSTR request) {
    const std::string name = dll_file_name(request);
    if (name.rfind("api-ms-win-core-", 0) != 0) return nullptr;
    HMODULE host = LoadLibraryExW(request, nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (host) {
        wchar_t path[MAX_PATH];
        const DWORD length = GetModuleFileNameW(host, path, MAX_PATH);
        log_dynamic_once("dynamic-handle " + name + " -> " +
                         (length ? lower(narrow(file_of(std::wstring(path, length)))) : std::string("loader")));
    }
    return host;
}

HMODULE WINAPI hook_GetModuleHandleW(LPCWSTR request) {
    if (request) {
        const std::string name = dll_file_name(request);
        AcquireSRWLockShared(&dynamic_lock);
        auto it = shim_modules.find(name);
        HMODULE shim = it == shim_modules.end() ? nullptr : it->second;
        ReleaseSRWLockShared(&dynamic_lock);
        if (shim) return shim;
    }
    HMODULE module = keep_host_identity ? GetModuleHandleW(request) : identity_GetModuleHandleW(request);
    if (!module && request) {
        const DWORD error = GetLastError();
        if (HMODULE host = api_set_host(request)) return host;
        // A module nothing has loaded is null, as from Windows; the line names what the program asked for.
        log_dynamic_once("dynamic-handle " + dll_file_name(request) + " -> none");
        SetLastError(error);
    }
    return module;
}
HMODULE WINAPI hook_GetModuleHandleA(LPCSTR request) {
    if (!request) return keep_host_identity ? GetModuleHandleA(request) : identity_GetModuleHandleA(request);
    return hook_GetModuleHandleW(from_ansi(request).c_str());
}

void* hook_for(const std::string& dll, const char* name);

// The name a run log line gives a module handle: the shim's DLL name, a mapped image's file name (a null
// handle is the program, as Windows' GetProcAddress takes it), the Windows loader's file name, or
// "unknown-0x<handle>" for a handle none of them knows, so the line still says which handle was asked.
std::string module_label(HMODULE module, const std::string& shim, const Region* region) {
    if (!shim.empty()) return shim;
    if (region) return region->label;
    wchar_t path[MAX_PATH];
    const DWORD length = module ? GetModuleFileNameW(module, path, MAX_PATH) : 0;
    if (length) return lower(narrow(file_of(std::wstring(path, length))));
    char text[40];
    std::snprintf(text, sizeof text, "unknown-0x%llx", static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(module)));
    return text;
}

// GetProcAddress for every import of it in the program and its package DLLs, and for dynamic lookups of
// itself. Only a handle a shim owns is answered from the shim (with the Windows twin as fallback). A mapped
// image (the program, a null handle, or a package DLL) is answered from its export table, forwarders
// included. Any other handle goes to Windows' GetProcAddress unchanged; the launcher's own hooks then replace
// the hooked loader, identity, crash and system-layer functions.
FARPROC WINAPI hook_GetProcAddress(HMODULE module, LPCSTR name) {
    const bool by_ordinal = (reinterpret_cast<std::uintptr_t>(name) >> 16) == 0;
    const std::string symbol = by_ordinal ? "#" + std::to_string(reinterpret_cast<std::uintptr_t>(name))
                                          : std::string(name ? name : "(null)");
    const std::string shim = shim_name_of(module);
    const Region* region = nullptr;
    if (shim.empty()) region = module ? region_of(module) : (keep_host_identity ? nullptr : (regions.empty() ? nullptr : &regions[0]));
    FARPROC address = nullptr;
    const char* route = "missing";
    DWORD error = ERROR_SUCCESS;
    if (!shim.empty()) {
        address = GetProcAddress(module, name);
        const bool gateway = shim == kXgrName && xgr_gateway_on();
        route = address ? (gateway ? "gateway" : "shim") : "missing";
        if (!address && !gateway) {
            // A name the shim lacks comes from Windows' DLL of the same name when there is one (loaded by its
            // System32 path, so it is not the shim): PC GDK's xgameruntime.lib asks for interface entry points
            // (QueryApiImpl, InitializeApiImpl...) that no public document describes and no shim can provide.
            if (HMODULE windows = windows_twin(shim))
                if ((address = GetProcAddress(windows, name))) route = "windows-fallback";
        }
        error = GetLastError();
    } else if (region) {
        if (!by_ordinal && name)
            address = reinterpret_cast<FARPROC>(map_export_resolved ? map_export_resolved(reinterpret_cast<void*>(region->base), name, resolve)
                                                                    : map_export(reinterpret_cast<void*>(region->base), name));
        route = address ? "mapped" : "mapped-missing";
        if (address && !by_ordinal)
            if (void* heap = package_heap_hook(region->name, reinterpret_cast<void*>(region->base), name))
                address = reinterpret_cast<FARPROC>(heap);
        error = address ? ERROR_SUCCESS : ERROR_PROC_NOT_FOUND;
    } else {
        address = GetProcAddress(module, name);
        error = GetLastError();
        route = address ? "windows" : "missing";
    }
    const std::string dll = module_label(module, shim, region);
    // A dynamic lookup of a hooked function in a Windows DLL gets the hook too.
    if (shim.empty() && !region && address && !by_ordinal) {
        if (void* hook = hook_for(dll, name)) address = reinterpret_cast<FARPROC>(hook);
        else if (void* identity = identity_hook(dll, name)) address = reinterpret_cast<FARPROC>(identity);
        else if (void* crash = crash_hook(dll, name)) address = reinterpret_cast<FARPROC>(crash);
        else if (void* heap = heap_hook(dll, name)) address = reinterpret_cast<FARPROC>(heap);
        else if (void* sys = sys_hook(dll, name)) address = reinterpret_cast<FARPROC>(sys);
    }
    // The program gets the recent-calls thunk (the same one a static import of that function has).
    if (address) address = reinterpret_cast<FARPROC>(trace_wrap(dll, symbol, reinterpret_cast<void*>(address)));
    log_dynamic_once("dynamic-resolve " + dll + "!" + symbol + " -> " + route);
    SetLastError(error);
    return address;
}

void* hook_for(const std::string& dll, const char* name) {
    if (!name) return nullptr;
    if (dll != "kernel32.dll" && dll != "kernelbase.dll" && dll.rfind("api-ms-win-core-libraryloader", 0) != 0)
        return nullptr;
    static const std::pair<const char*, void*> hooks[] = {
        {"LoadLibraryA", reinterpret_cast<void*>(&hook_LoadLibraryA)},
        {"LoadLibraryW", reinterpret_cast<void*>(&hook_LoadLibraryW)},
        {"LoadLibraryExA", reinterpret_cast<void*>(&hook_LoadLibraryExA)},
        {"LoadLibraryExW", reinterpret_cast<void*>(&hook_LoadLibraryExW)},
        {"GetModuleHandleA", reinterpret_cast<void*>(&hook_GetModuleHandleA)},
        {"GetModuleHandleW", reinterpret_cast<void*>(&hook_GetModuleHandleW)},
        {"GetProcAddress", reinterpret_cast<void*>(&hook_GetProcAddress)},
    };
    for (const auto& [hooked, address] : hooks)
        if (std::strcmp(hooked, name) == 0) return address;
    return nullptr;
}

// Maps <program folder>\KEY with pe_map once (a static import or a dynamic load of it) and records its
// region, or returns null. The package lock is the dynamic lock's sibling: mapping runs DllMain, which may
// load more DLLs, so it is not held across map_image; the mapping set stops import cycles.
SRWLOCK package_lock = SRWLOCK_INIT;
void* map_package(const std::string& key) {
    const std::wstring local = package_dir + L"\\" + widen(key);
    AcquireSRWLockExclusive(&package_lock);
    void* base = package_images[key];
    const bool start = !base && !mapping.count(key);
    if (start) mapping.insert(key);
    ReleaseSRWLockExclusive(&package_lock);
    if (!start) return base;
    std::uint32_t status = 0;
    char detail[256] = {};
    base = map_image(local.c_str(), resolve, &status, detail, sizeof detail);
    AcquireSRWLockExclusive(&package_lock);
    mapping.erase(key);
    if (base) {
        package_images[key] = base;
        regions.push_back({key, reinterpret_cast<std::uintptr_t>(base), image_size(base), local, key});
    }
    ReleaseSRWLockExclusive(&package_lock);
    if (!base) {
        err_printf( "[x2w] cannot map %s: status %u %s\n", key.c_str(), status, detail);
        log_line("package-map-failed %s status %u %s", key.c_str(), status, detail);
    }
    return base;
}

// ---------------------------------------------------------------- ends of the run the log must see
// With a run log, the program's SetUnhandledExceptionFilter, ExitProcess and TerminateProcess (kernel32,
// kernelbase and their API sets) bind to these. The launcher's own filter stays installed: the program's
// filter is kept and called after the crash line and summary are written, with its answer returned.
// ExitProcess and TerminateProcess of this process write the exit line and summary first.
LPTOP_LEVEL_EXCEPTION_FILTER volatile title_filter;
LONG WINAPI unhandled(EXCEPTION_POINTERS* info);

LPTOP_LEVEL_EXCEPTION_FILTER WINAPI hook_SetUnhandledExceptionFilter(LPTOP_LEVEL_EXCEPTION_FILTER filter) {
    if (filter == unhandled) return title_filter;
    log_dynamic_once("unhandled-filter program filter kept behind the launcher's");
    return reinterpret_cast<LPTOP_LEVEL_EXCEPTION_FILTER>(
        InterlockedExchangePointer(reinterpret_cast<void* volatile*>(&title_filter), reinterpret_cast<void*>(filter)));
}

void log_exit(UINT code, const char* how) {
    if (summary_written) return;
    long calls = 0;
    unsigned missing = 0;
    for (const Stub* stub : stubs) {
        calls += stub->calls;
        missing += stub->missing;
    }
    log_line("exit code 0x%x (%u); stubs %zu (missing %u), stub calls %ld", code, code, stubs.size(), missing, calls);
    log_summary(how);
}

void WINAPI hook_ExitProcess(UINT code) {
    log_exit(code, "exit");
    ExitProcess(code);
}

bool is_this_process(HANDLE process) {
    return process == GetCurrentProcess() || (process && GetProcessId(process) == GetCurrentProcessId());
}

BOOL WINAPI hook_TerminateProcess(HANDLE process, UINT code) {
    if (is_this_process(process)) log_exit(code, "terminate");
    return TerminateProcess(process, code);
}

bool readable(const void* address, std::size_t size);
void exception_text(const EXCEPTION_RECORD* record, char* out, std::size_t capacity);
using QueryThread = LONG(NTAPI*)(HANDLE, ULONG, PVOID, ULONG, PULONG);
QueryThread query_thread;

// RaiseFailFastException ends the process without running any handler: the line and the final summary first.
void WINAPI hook_RaiseFailFastException(PEXCEPTION_RECORD record, PCONTEXT context, DWORD flags) {
    char where[160];
    describe(record ? record->ExceptionAddress : _ReturnAddress(), where, sizeof where);
    log_line("fastfail RaiseFailFastException code 0x%08lx at %s flags 0x%lx last-stub %s",
             record ? record->ExceptionCode : 0ul, where, flags, last_stub_name().c_str());
    log_summary("fastfail");
    using Fn = void(WINAPI*)(PEXCEPTION_RECORD, PCONTEXT, DWORD);
    static const Fn real = reinterpret_cast<Fn>(GetProcAddress(GetModuleHandleW(L"kernelbase.dll"), "RaiseFailFastException"));
    if (real) real(record, context, flags);
    TerminateProcess(GetCurrentProcess(), record ? record->ExceptionCode : 0xC0000602u /* STATUS_FAIL_FAST_EXCEPTION */);
}

// ntdll's process-ending calls, for programs (or their runtimes) that skip kernel32.
using NtTerminate = LONG(NTAPI*)(HANDLE, LONG);
using RtlExit = void(NTAPI*)(LONG);
LONG NTAPI hook_NtTerminateProcess(HANDLE process, LONG status) {
    // A null handle ends every other thread first and is followed by a second call that ends the process.
    if (process && is_this_process(process)) log_exit(static_cast<UINT>(status), "terminate");
    static const auto real = reinterpret_cast<NtTerminate>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtTerminateProcess"));
    return real(process, status);
}
void NTAPI hook_RtlExitUserProcess(LONG status) {
    log_exit(static_cast<UINT>(status), "exit");
    static const auto real = reinterpret_cast<RtlExit>(GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlExitUserProcess"));
    real(status);
}

std::string caller_chain(const EXCEPTION_POINTERS* info);

// dbghelp!MiniDumpWriteDump: a program's own crash handler. The exception it reports (when it passes one from this
// process) is logged with its callers, then a provisional summary, since the handler usually ends the process next.
// The dump itself is written as the program asked.
using MiniDump = BOOL(WINAPI*)(HANDLE, DWORD, HANDLE, int, void*, void*, void*);
BOOL WINAPI hook_MiniDumpWriteDump(HANDLE process, DWORD pid, HANDLE file, int type, void* exception, void* user,
                                   void* callback) {
    struct ExceptionInfo {
        DWORD thread;
        EXCEPTION_POINTERS* pointers;
        BOOL client_pointers;
    };
    const auto* info = static_cast<const ExceptionInfo*>(exception);
    std::string what = "no exception";
    if (info && info->pointers && is_this_process(process) && readable(info->pointers, sizeof(EXCEPTION_POINTERS)) &&
        readable(info->pointers->ExceptionRecord, sizeof(EXCEPTION_RECORD)) &&
        readable(info->pointers->ContextRecord, sizeof(CONTEXT))) {
        char text[512];
        exception_text(info->pointers->ExceptionRecord, text, sizeof text);
        what = text + caller_chain(info->pointers);
    }
    log_line("minidump requested by the program type 0x%x %s last-stub %s", type, what.c_str(), last_stub_name().c_str());
    if (!summary_written) write_summary("minidump");
    static const auto real = [] {
        HMODULE dbghelp = GetModuleHandleW(L"dbghelp.dll");
        if (!dbghelp) dbghelp = LoadLibraryExW(L"dbghelp.dll", nullptr, LOAD_LIBRARY_SEARCH_SYSTEM32);
        return dbghelp ? reinterpret_cast<MiniDump>(GetProcAddress(dbghelp, "MiniDumpWriteDump")) : nullptr;
    }();
    return real ? real(process, pid, file, type, exception, user, callback) : FALSE;
}

void* crash_hook(const std::string& dll, const char* name) {
    if (log_file == INVALID_HANDLE_VALUE || !name) return nullptr;
    if (dll == "ntdll.dll") {
        if (std::strcmp(name, "NtTerminateProcess") == 0 || std::strcmp(name, "ZwTerminateProcess") == 0)
            return reinterpret_cast<void*>(&hook_NtTerminateProcess);
        if (std::strcmp(name, "RtlExitUserProcess") == 0) return reinterpret_cast<void*>(&hook_RtlExitUserProcess);
        return nullptr;
    }
    if (dll == "dbghelp.dll" || dll == "dbgcore.dll")
        return std::strcmp(name, "MiniDumpWriteDump") == 0 ? reinterpret_cast<void*>(&hook_MiniDumpWriteDump) : nullptr;
    const bool base = dll == "kernel32.dll" || dll == "kernelbase.dll";
    const bool errorhandling = base || dll.rfind("api-ms-win-core-errorhandling-", 0) == 0;
    if (std::strcmp(name, "SetUnhandledExceptionFilter") == 0 && errorhandling)
        return reinterpret_cast<void*>(&hook_SetUnhandledExceptionFilter);
    if (std::strcmp(name, "RaiseFailFastException") == 0 && errorhandling)
        return reinterpret_cast<void*>(&hook_RaiseFailFastException);
    if (!base && dll.rfind("api-ms-win-core-processthreads-", 0) != 0) return nullptr;
    if (std::strcmp(name, "ExitProcess") == 0) return reinterpret_cast<void*>(&hook_ExitProcess);
    if (std::strcmp(name, "TerminateProcess") == 0) return reinterpret_cast<void*>(&hook_TerminateProcess);
    return nullptr;
}

// ---------------------------------------------------------------- heap guard
// The program's and its package DLLs' HeapFree, HeapReAlloc, HeapSize, LocalFree and GlobalFree (kernel32, kernelbase,
// api-ms-win-core-heap-*) and the C runtime's free, _free_base, realloc, _realloc_base, _aligned_free, _aligned_realloc,
// _msize and _msize_base (ucrtbase.dll, api-ms-win-crt-heap-*, or a ucrtbase.dll mapped from the package), imported
// or found with GetProcAddress, bind to the hooks below. Each checks whether the pointer can be a block of the heap
// it is handed to (foreign_reason: HeapValidate of a single pointer cannot be used, since with termination on
// corruption a non-block ends the process inside it). A pointer that cannot ("heap-guard invalid API ptr=P heap=H
// owner=O callers ...") is not forwarded: a free or size is skipped (the block leaks), a realloc gets a new block with
// the bytes known to be readable copied. The owner says what the pointer is: xmem-alloc / xmem-virtual (xmem.dll's
// records), image, stack, aligned-block(B) (an _aligned_malloc block given to a plain free), other-heap(H) (in a
// region another heap starts), or unknown(free|reserved|mapped|no-access|misaligned|...). The first 50 are logged,
// the rest counted.
// heap_milestone() validates the whole process heap at the first thread, each xgr query and call (the gateway calls
// x2w_launch_heap_milestone), each d3d12 import call and every 256th stub or shim call; the first failure is
// logged as "heap-guard corrupted-before M after P", P being the last milestone that passed, which brackets the
// call that corrupted it. A heap-corruption exception (0xc0000374) raised anywhere is bracketed the same way
// ("corrupted-before heap-failure at SITE after P", or the check in progress when the check itself raised it).
constexpr long kHeapGuardLines = 50;
volatile long heap_invalid;       // invalid pointers seen
volatile long heap_corrupt;       // a milestone check failed
volatile long heap_guard_ticks;   // stub and shim calls
volatile long heap_first_thread;
SRWLOCK milestone_lock = SRWLOCK_INIT;
char last_good_milestone[200] = "launch";

std::string mapped_frames(const CONTEXT* start, int limit);
std::string stack_scan(const CONTEXT* context, int limit);

void heap_guard_line(const std::string& text) {
    err_printf("[x2w] %s\n", text.c_str());
    log_line("%s", text.c_str());
}

// HeapValidate under SEH: a handle that is no heap at all faults inside ntdll.
bool heap_block_ok(HANDLE heap, const void* block) {
    __try {
        return heap && HeapValidate(heap, 0, block) != FALSE;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

bool copy_guarded(void* to, const void* from, std::size_t bytes) {
    __try {
        std::memcpy(to, from, bytes);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

// _aligned_malloc keeps the heap block's address in the pointer-sized slot below the aligned pointer it returns.
void* aligned_base(const void* p) {
    const auto at = reinterpret_cast<std::uintptr_t>(p);
    const auto slot = (at & ~std::uintptr_t{7}) - sizeof(void*);
    if (!readable(reinterpret_cast<const void*>(slot), sizeof(void*))) return nullptr;
    void* base = *reinterpret_cast<void* const*>(slot);
    const auto start = reinterpret_cast<std::uintptr_t>(base);
    return start && !(start & 0xf) && start < at && at - start <= 0x1008 ? base : nullptr;
}

using XMemDescribeFn = HRESULT(WINAPI*)(const void*, X2WXMemAllocationInfo*);
XMemDescribeFn volatile xmem_describe;
volatile long xmem_describe_looked;

XMemDescribeFn describe_fn() {
    if (!xmem_describe_looked) {
        if (HMODULE xmem = GetModuleHandleW(L"xmem.dll")) {
            xmem_describe = reinterpret_cast<XMemDescribeFn>(GetProcAddress(xmem, "X2WXMemDescribe"));
            InterlockedExchange(&xmem_describe_looked, 1);
        }
    }
    return xmem_describe;
}

// Why `p` cannot be a block of `heap`, or empty when nothing says so (the call is then forwarded). HeapValidate(heap,
// 0, p) cannot be asked: with heap termination on corruption (always on for 64-bit processes) a pointer that is not a
// block ends the process inside that very call. Only facts that rule a block out count: an xmem.dll allocation or
// mapping (not one adopted from the title's own hooks), an image, the calling thread's stack, memory that is not
// committed private memory, a pointer heaps never return (not 16-byte aligned), an _aligned_malloc block handed to a
// plain free, a region another heap's first segment starts. `known` gets the bytes known readable at p.
std::string foreign_reason(const void* p, HANDLE heap, bool aligned_api, std::size_t* known) {
    char text[96];
    const auto at = reinterpret_cast<std::uintptr_t>(p);
    *known = 0;
    if (XMemDescribeFn describe_xmem = describe_fn()) {
        X2WXMemAllocationInfo info{};
        info.size = sizeof info;
        if (describe_xmem(p, &info) == S_OK && info.backing != X2W_XMEM_BACKING_ADOPTED) {
            if (at - info.base < info.bytes) *known = static_cast<std::size_t>(info.bytes - (at - info.base));
            return info.backing == X2W_XMEM_BACKING_PHYSICAL ? "xmem-virtual" : "xmem-alloc";
        }
    }
    if (region_at(at)) return "image";
    ULONG_PTR low = 0, high = 0;
    GetCurrentThreadStackLimits(&low, &high);
    if (at >= low && at < high) {
        *known = static_cast<std::size_t>(high - at);
        return "stack";
    }
    MEMORY_BASIC_INFORMATION info{};
    if (!VirtualQuery(p, &info, sizeof info)) return "unknown(unmapped)";
    if (info.State == MEM_COMMIT && !(info.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        *known = static_cast<std::size_t>(reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize - at);
    if (info.Type == MEM_IMAGE) return "image";
    if (info.State != MEM_COMMIT) return info.State == MEM_FREE ? "unknown(free)" : "unknown(reserved)";
    if (info.Type == MEM_MAPPED) return "unknown(mapped)";
    if (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return "unknown(no-access)";
    if (aligned_api) return {};
    if (void* base = aligned_base(p)) {
        MEMORY_BASIC_INFORMATION block{};
        if (VirtualQuery(base, &block, sizeof block) && block.AllocationBase == info.AllocationBase) {
            std::snprintf(text, sizeof text, "aligned-block(0x%llx)",
                          static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(base)));
            return text;
        }
    }
    if (at & 0xf) return "unknown(misaligned)";
    HANDLE heaps[256];
    const DWORD count = GetProcessHeaps(256, heaps);
    for (DWORD i = 0; i < count && i < 256; ++i) {
        if (heaps[i] == heap || heaps[i] != info.AllocationBase) continue;
        if (heaps[i] == GetProcessHeap()) return "other-heap(process)";
        std::snprintf(text, sizeof text, "other-heap(0x%llx)", static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(heaps[i])));
        return text;
    }
    return {};
}

// The frames in mapped images that called the hook, as the crash lines give them.
std::string guard_callers() {
    CONTEXT context{};
    RtlCaptureContext(&context);
    const std::string frames = mapped_frames(&context, 3);
    if (!frames.empty()) return " callers " + frames;
    const std::string scanned = stack_scan(&context, 3);
    if (!scanned.empty()) return " callers? " + scanned + " (stack-scan)";
    return " callers none";
}

// Logs a refused pointer.
void guard_refuse(const char* api, const void* p, HANDLE heap, const std::string& owner) {
    const DWORD error = GetLastError();
    const long count = InterlockedIncrement(&heap_invalid);
    if (count <= kHeapGuardLines) {
        char text[256];
        std::snprintf(text, sizeof text, "heap-guard invalid %s ptr=0x%llx heap=0x%llx owner=%s", api,
                      static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(p)),
                      static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(heap)), owner.c_str());
        heap_guard_line(text + guard_callers() + " not-forwarded");
        if (count == kHeapGuardLines) heap_guard_line("heap-guard more invalid pointers are counted only");
    }
    SetLastError(error);
}

// A whole-heap HeapValidate that finds corruption may end the process inside the call (0xc0000374), so the name of
// the check in progress is kept where the first-chance handler finds it (heap_guard_fault).
volatile DWORD checking_thread;
char checking_name[200];

void heap_milestone(const char* name) {
    if (!heap_guard || heap_corrupt) return;
    const DWORD error = GetLastError();
    AcquireSRWLockExclusive(&milestone_lock);
    std::snprintf(checking_name, sizeof checking_name, "%s", name);
    InterlockedExchange(reinterpret_cast<volatile long*>(&checking_thread), static_cast<long>(GetCurrentThreadId()));
    const bool ok = heap_block_ok(GetProcessHeap(), nullptr);
    InterlockedExchange(reinterpret_cast<volatile long*>(&checking_thread), 0);
    if (ok) {
        std::snprintf(last_good_milestone, sizeof last_good_milestone, "%s", name);
        ReleaseSRWLockExclusive(&milestone_lock);
    } else if (InterlockedExchange(&heap_corrupt, 1) == 0) {
        const std::string previous = last_good_milestone;
        ReleaseSRWLockExclusive(&milestone_lock);
        heap_guard_line(std::string("heap-guard corrupted-before ") + name + " after " + previous);
        log_flush();
    } else {
        ReleaseSRWLockExclusive(&milestone_lock);
    }
    SetLastError(error);
}

// The first-chance handler's part: a heap-corruption exception (0xc0000374) brackets the corruption between the
// last check that passed and either the check in progress on this thread or the faulting heap call itself.
void heap_guard_fault(const EXCEPTION_RECORD* record) {
    if (!heap_guard || record->ExceptionCode != 0xc0000374u || InterlockedExchange(&heap_corrupt, 1) != 0) return;
    std::string what, previous;
    if (checking_thread == GetCurrentThreadId()) {  // this thread holds milestone_lock
        what = checking_name;
        previous = last_good_milestone;
    } else {
        char where[160];
        describe(record->ExceptionAddress, where, sizeof where);
        what = std::string("heap-failure at ") + where;
        AcquireSRWLockShared(&milestone_lock);
        previous = last_good_milestone;
        ReleaseSRWLockShared(&milestone_lock);
    }
    heap_guard_line("heap-guard corrupted-before " + what + " after " + previous);
    log_flush();
}

// d3d12 calls are checked every time, other stub and shim calls every 256th call over all of them.
void guard_tick(const char* kind, const std::string& dll, const std::string& symbol, long calls) {
    const bool d3d12 = std::strcmp(kind, "d3d12-call") == 0;
    const long tick = d3d12 ? 0 : InterlockedIncrement(&heap_guard_ticks);
    if (heap_corrupt || (!d3d12 && (tick & 255) != 0)) return;
    char name[200];
    std::snprintf(name, sizeof name, "%s %s!%s #%ld", kind, dll.c_str(), symbol.c_str(), calls);
    heap_milestone(name);
}

void heap_guard_summary() {
    if (!heap_guard) return;
    AcquireSRWLockShared(&milestone_lock);
    const std::string last = last_good_milestone;
    ReleaseSRWLockShared(&milestone_lock);
    log_line("heap-guard summary invalid=%ld corrupted=%s last-check=%s", heap_invalid, heap_corrupt ? "yes" : "no",
             last.c_str());
}

// Windows' heap functions.
BOOL WINAPI guard_HeapFree(HANDLE heap, DWORD flags, LPVOID p) {
    std::size_t known = 0;
    if (p) {
        const std::string owner = foreign_reason(p, heap, false, &known);
        if (!owner.empty()) {
            guard_refuse("HeapFree", p, heap, owner);
            return TRUE;
        }
    }
    return HeapFree(heap, flags, p);
}

LPVOID WINAPI guard_HeapReAlloc(HANDLE heap, DWORD flags, LPVOID p, SIZE_T bytes) {
    std::size_t known = 0;
    const std::string owner = p ? foreign_reason(p, heap, false, &known) : std::string();
    if (owner.empty()) return HeapReAlloc(heap, flags, p, bytes);
    guard_refuse("HeapReAlloc", p, heap, owner);
    if (flags & HEAP_REALLOC_IN_PLACE_ONLY) {
        SetLastError(ERROR_NOT_ENOUGH_MEMORY);
        return nullptr;
    }
    void* fresh = HeapAlloc(heap, flags & (HEAP_GENERATE_EXCEPTIONS | HEAP_NO_SERIALIZE | HEAP_ZERO_MEMORY), bytes);
    if (fresh && known) copy_guarded(fresh, p, known < bytes ? known : bytes);
    return fresh;
}

SIZE_T WINAPI guard_HeapSize(HANDLE heap, DWORD flags, LPCVOID p) {
    std::size_t known = 0;
    const std::string owner = p ? foreign_reason(p, heap, false, &known) : std::string();
    if (owner.empty()) return HeapSize(heap, flags, p);
    guard_refuse("HeapSize", p, heap, owner);
    SetLastError(ERROR_INVALID_PARAMETER);
    return static_cast<SIZE_T>(-1);
}

// A moveable LocalAlloc/GlobalAlloc handle is a handle-table entry, 8 mod 16, never a heap block: forwarded unchecked.
bool movable_handle(const void* handle) { return (reinterpret_cast<std::uintptr_t>(handle) & 0xf) == 8; }

HLOCAL WINAPI guard_LocalFree(HLOCAL handle) {
    std::size_t known = 0;
    const std::string owner = handle && !movable_handle(handle) ? foreign_reason(handle, GetProcessHeap(), false, &known) : std::string();
    if (owner.empty()) return LocalFree(handle);
    guard_refuse("LocalFree", handle, GetProcessHeap(), owner);
    return nullptr;
}

HGLOBAL WINAPI guard_GlobalFree(HGLOBAL handle) {
    std::size_t known = 0;
    const std::string owner = handle && !movable_handle(handle) ? foreign_reason(handle, GetProcessHeap(), false, &known) : std::string();
    if (owner.empty()) return GlobalFree(handle);
    guard_refuse("GlobalFree", handle, GetProcessHeap(), owner);
    return nullptr;
}

// The C runtime's heap functions, for Windows' ucrtbase.dll (instance 0) and a package ucrtbase.dll (instance 1).
enum CrtFn { kFree, kFreeBase, kRealloc, kReallocBase, kAlignedFree, kAlignedRealloc, kMsize, kMsizeBase, kMalloc,
             kAlignedMalloc, kCrtFns };
constexpr const char* kCrtNames[kCrtFns] = {"free",  "_free_base", "realloc", "_realloc_base", "_aligned_free",
                                            "_aligned_realloc", "_msize", "_msize_base", "malloc", "_aligned_malloc"};
struct Crt {
    void* fn[kCrtFns];
    HANDLE heap;
    volatile long ready;
};
Crt crts[2];

using FreeFn = void(__cdecl*)(void*);
using ReallocFn = void*(__cdecl*)(void*, std::size_t);
using AlignedReallocFn = void*(__cdecl*)(void*, std::size_t, std::size_t);
using MsizeFn = std::size_t(__cdecl*)(void*);
using MallocFn = void*(__cdecl*)(std::size_t);
using AlignedMallocFn = void*(__cdecl*)(std::size_t, std::size_t);
using HeapHandleFn = std::intptr_t(__cdecl*)();

// Fills an instance from an export lookup; false when the runtime lacks the functions the hooks forward to.
template <typename Lookup>
bool crt_init(int instance, Lookup lookup) {
    Crt& crt = crts[instance];
    if (crt.ready) return crt.ready > 0;
    for (int i = 0; i < kCrtFns; ++i) crt.fn[i] = lookup(kCrtNames[i]);
    const auto heap_handle = reinterpret_cast<HeapHandleFn>(lookup("_get_heap_handle"));
    crt.heap = heap_handle ? reinterpret_cast<HANDLE>(heap_handle()) : GetProcessHeap();
    if (!crt.heap) crt.heap = GetProcessHeap();
    const bool ok = crt.fn[kFree] && crt.fn[kRealloc] && crt.fn[kMalloc];
    InterlockedExchange(&crt.ready, ok ? 1 : -1);
    return ok;
}

template <int I, int F>
void __cdecl guard_crt_free(void* p) {
    std::size_t known = 0;
    if (p) {
        const std::string owner = foreign_reason(p, crts[I].heap, false, &known);
        if (!owner.empty()) {
            guard_refuse(kCrtNames[F], p, crts[I].heap, owner);
            return;
        }
    }
    reinterpret_cast<FreeFn>(crts[I].fn[F])(p);
}

template <int I, int F>
void* __cdecl guard_crt_realloc(void* p, std::size_t bytes) {
    std::size_t known = 0;
    const std::string owner = p ? foreign_reason(p, crts[I].heap, false, &known) : std::string();
    if (owner.empty()) return reinterpret_cast<ReallocFn>(crts[I].fn[F])(p, bytes);
    guard_refuse(kCrtNames[F], p, crts[I].heap, owner);
    if (!bytes) return nullptr;
    void* fresh = reinterpret_cast<MallocFn>(crts[I].fn[kMalloc])(bytes);
    if (fresh && known) copy_guarded(fresh, p, known < bytes ? known : bytes);
    return fresh;
}

template <int I, int F>
std::size_t __cdecl guard_crt_msize(void* p) {
    std::size_t known = 0;
    const std::string owner = p ? foreign_reason(p, crts[I].heap, false, &known) : std::string();
    if (owner.empty()) return reinterpret_cast<MsizeFn>(crts[I].fn[F])(p);
    guard_refuse(kCrtNames[F], p, crts[I].heap, owner);
    return static_cast<std::size_t>(-1);
}

// _aligned_free/_aligned_realloc: the pointer itself must not be foreign, and the slot below it must hold its block.
template <int I>
std::string aligned_reason(void* p, std::size_t* known) {
    std::string owner = foreign_reason(p, crts[I].heap, true, known);
    if (owner.empty() && !aligned_base(p)) owner = "unknown(no-aligned-header)";
    return owner;
}

template <int I>
void __cdecl guard_crt_aligned_free(void* p) {
    std::size_t known = 0;
    if (p) {
        const std::string owner = aligned_reason<I>(p, &known);
        if (!owner.empty()) {
            guard_refuse("_aligned_free", p, crts[I].heap, owner);
            return;
        }
    }
    reinterpret_cast<FreeFn>(crts[I].fn[kAlignedFree])(p);
}

template <int I>
void* __cdecl guard_crt_aligned_realloc(void* p, std::size_t bytes, std::size_t alignment) {
    std::size_t known = 0;
    const std::string owner = p ? aligned_reason<I>(p, &known) : std::string();
    if (owner.empty()) return reinterpret_cast<AlignedReallocFn>(crts[I].fn[kAlignedRealloc])(p, bytes, alignment);
    guard_refuse("_aligned_realloc", p, crts[I].heap, owner);
    if (!bytes || !crts[I].fn[kAlignedMalloc]) return nullptr;
    void* fresh = reinterpret_cast<AlignedMallocFn>(crts[I].fn[kAlignedMalloc])(bytes, alignment);
    if (fresh && known) copy_guarded(fresh, p, known < bytes ? known : bytes);
    return fresh;
}

template <int I>
void* crt_hook(const char* name) {
    void* const hooks[] = {
        reinterpret_cast<void*>(&guard_crt_free<I, kFree>),           reinterpret_cast<void*>(&guard_crt_free<I, kFreeBase>),
        reinterpret_cast<void*>(&guard_crt_realloc<I, kRealloc>),     reinterpret_cast<void*>(&guard_crt_realloc<I, kReallocBase>),
        reinterpret_cast<void*>(&guard_crt_aligned_free<I>),          reinterpret_cast<void*>(&guard_crt_aligned_realloc<I>),
        reinterpret_cast<void*>(&guard_crt_msize<I, kMsize>),         reinterpret_cast<void*>(&guard_crt_msize<I, kMsizeBase>)};
    for (int i = 0; i < kMalloc; ++i)
        if (std::strcmp(kCrtNames[i], name) == 0) return crts[I].fn[i] ? hooks[i] : nullptr;
    return nullptr;
}

bool is_ucrt(const std::string& dll) {
    return dll == "ucrtbase.dll" || dll.rfind("api-ms-win-crt-heap-", 0) == 0;
}

// The heap guard's replacement for dll!name when the import goes to Windows, or null.
void* heap_hook(const std::string& dll, const char* name) {
    if (!heap_guard || !name) return nullptr;
    if (dll == "kernel32.dll" || dll == "kernelbase.dll" || dll.rfind("api-ms-win-core-heap", 0) == 0) {
        const std::pair<const char*, void*> hooks[] = {
            {"HeapFree", reinterpret_cast<void*>(&guard_HeapFree)},
            {"HeapReAlloc", reinterpret_cast<void*>(&guard_HeapReAlloc)},
            {"HeapSize", reinterpret_cast<void*>(&guard_HeapSize)},
            {"LocalFree", reinterpret_cast<void*>(&guard_LocalFree)},
            {"GlobalFree", reinterpret_cast<void*>(&guard_GlobalFree)},
        };
        for (const auto& [hooked, address] : hooks)
            if (std::strcmp(hooked, name) == 0) return address;
        return nullptr;
    }
    if (is_ucrt(dll) && crts[0].ready > 0) return crt_hook<0>(name);
    return nullptr;
}

// The same for a ucrtbase.dll mapped from the package folder.
void* package_heap_hook(const std::string& dll, void* base, const char* name) {
    if (!heap_guard || !name || dll != "ucrtbase.dll" || !base) return nullptr;
    if (!crt_init(1, [base](const char* symbol) { return map_export(base, symbol); })) return nullptr;
    return crt_hook<1>(name);
}

void* __cdecl resolve(const char* dll, const char* name, std::uint32_t ordinal) {
    const std::string key = lower(dll);
    const std::string symbol = name ? std::string(name) : "#" + std::to_string(ordinal);
    const char* lookup = name ? name : MAKEINTRESOURCEA(ordinal);
    for (const auto& directory : shim_dirs) {
        const std::wstring path = directory + L"\\" + widen(key);
        if (!is_file(path)) continue;
        HMODULE& module = shim_modules[key];
        if (!module) module = LoadLibraryExW(path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
        if (module)
            if (void* address = reinterpret_cast<void*>(GetProcAddress(module, lookup)))
                return report(key, symbol, "shim", "shim", address);
        return report(key, symbol, "stub (not in shim)", "stub", make_stub(key, symbol, false));
    }
    const std::wstring local = package_dir + L"\\" + widen(key);
    if (is_file(local)) {
        void* base = map_package(key);
        if (base && name)
            if (void* address = map_export(base, name)) {
                if (void* hook = package_heap_hook(key, base, name))
                    return report(key, symbol, "package (x2w heap guard)", "package", hook);
                return report(key, symbol, "package", "package", address);
            }
        return report(key, symbol, "stub (package)", "stub", make_stub(key, symbol, false));
    }
    // GetModuleHandleA/W have both hooks: the shim lookup first, then the title identity answer.
    if (void* hook = hook_for(key, name))
        return report(key, symbol, identity_hook(key, name) ? "windows (title identity)" : "windows (x2w hook)", "windows",
                      hook);
    if (HMODULE module = LoadLibraryA(dll)) {
        if (void* address = reinterpret_cast<void*>(GetProcAddress(module, lookup))) {
            if (void* hook = identity_hook(key, name)) return report(key, symbol, "windows (title identity)", "windows", hook);
            if (void* hook = crash_hook(key, name)) return report(key, symbol, "windows (x2w crash hook)", "windows", hook);
            if (void* hook = heap_hook(key, name)) return report(key, symbol, "windows (x2w heap guard)", "windows", hook);
            if (void* hook = sys_hook(key, name)) return report(key, symbol, "windows (x2w sys hook)", "windows", hook);
            return report(key, symbol, "windows", "windows", address);
        }
        return report(key, symbol, "stub (not in windows)", "stub", make_stub(key, symbol, false));
    }
    return report(key, symbol, "stub", "missing", make_stub(key, symbol, true));
}

void __cdecl observe_run(int event, std::uint32_t index, void* address) {
    char where[160];
    switch (event) {
    case 0:
        describe(address, where, sizeof where);
        log_line("milestone tls-callback %u at %s", index, where);
        break;
    case 1:
        InterlockedExchange(&tls_done, 1);
        log_line("milestone tls-callbacks-done %u", index);
        break;
    case 2:
        InterlockedExchange(&entry_reached, 1);
        describe(address, where, sizeof where);
        log_line("milestone entry-reached %s", where);
        heap_milestone("entry");
        break;
    default:
        break;
    }
}

// The current thread's description (SetThreadDescription), letters, digits, '_', '.' and '-' only, or empty.
using GetDescription = HRESULT(WINAPI*)(HANDLE, PWSTR*);
GetDescription get_description;
std::string thread_name() {
    if (!get_description) return {};
    PWSTR text = nullptr;
    std::string out;
    if (SUCCEEDED(get_description(GetCurrentThread(), &text)) && text) {
        for (const wchar_t* c = text; *c && out.size() < 48; ++c)
            out += (std::iswalnum(*c) && *c < 0x80) || *c == L'_' || *c == L'.' || *c == L'-' ? static_cast<char>(*c) : '_';
        LocalFree(text);
    }
    return out;
}

void exception_text(const EXCEPTION_RECORD* record, char* out, std::size_t capacity) {
    char where[160];
    describe(record->ExceptionAddress, where, sizeof where);
    const std::string name = thread_name();
    const DWORD self = GetCurrentThreadId();
    int used = std::snprintf(out, capacity, "exception 0x%08lx at %s thread %s%s%s", record->ExceptionCode, where,
                             self == watchdog_id ? "watchdog" : "program", name.empty() ? "" : " thread-name ",
                             name.c_str());
    // Access violations and in-page errors carry the access kind and the address that was touched.
    if ((record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION || record->ExceptionCode == EXCEPTION_IN_PAGE_ERROR)
        && record->NumberParameters >= 2 && used > 0 && static_cast<std::size_t>(used) < capacity) {
        const ULONG_PTR kind = record->ExceptionInformation[0];
        char target[160];
        describe(reinterpret_cast<void*>(record->ExceptionInformation[1]), target, sizeof target);
        std::snprintf(out + used, capacity - used, " %s %s",
                      kind == 0 ? "reading" : kind == 1 ? "writing" : kind == 8 ? "executing" : "accessing", target);
    }
}

// ---------------------------------------------------------------- C++ exceptions (0xe06d7363)
// An MSVC throw passes its ThrowInfo in the record: ExceptionInformation[0] is a magic number, [2] the
// ThrowInfo address and [3] the image base its 32-bit RVAs are relative to. The first catchable type is the
// thrown (most derived) type; its TypeDescriptor holds the decorated name (".?AVruntime_error@std@@").
// A rethrow ("throw;") carries no ThrowInfo and is logged as "rethrow". Only that name and the throw site (the first frame in a mapped image, found by unwinding from the
// RaiseException context) are logged, never the exception object.
constexpr DWORD cpp_exception = 0xe06d7363;
constexpr std::size_t kCppThrowLines = 16;
volatile long cpp_throws;
SRWLOCK cpp_lock = SRWLOCK_INIT;
std::set<std::string> cpp_seen;

bool readable(const void* address, std::size_t size) {
    MEMORY_BASIC_INFORMATION info;
    if (!address || !VirtualQuery(address, &info, sizeof info) || info.State != MEM_COMMIT) return false;
    if (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    const auto end = reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize;
    return reinterpret_cast<std::uintptr_t>(address) + size <= end;
}

std::string thrown_type(const EXCEPTION_RECORD* record) {
    if (record->NumberParameters < 4) return "unknown_parameters";
    const ULONG_PTR magic = record->ExceptionInformation[0];
    if (magic != 0x19930520 && magic != 0x19930521 && magic != 0x19930522) return "unknown_magic";
    const auto base = static_cast<std::uintptr_t>(record->ExceptionInformation[3]);
    const auto* throw_info = reinterpret_cast<const std::int32_t*>(record->ExceptionInformation[2]);
    if (!throw_info) return "rethrow";  // "throw;": the runtime takes the type from the exception in flight
    if (!readable(throw_info, 16)) return "unknown_throw_info";
    const auto* types = reinterpret_cast<const std::int32_t*>(base + static_cast<std::uint32_t>(throw_info[3]));
    if (!readable(types, 8) || types[0] < 1) return "unknown_type_array";
    const auto* catchable = reinterpret_cast<const std::int32_t*>(base + static_cast<std::uint32_t>(types[1]));
    if (!readable(catchable, 8)) return "unknown_catchable_type";
    const char* name = reinterpret_cast<const char*>(base + static_cast<std::uint32_t>(catchable[1]) + 16);
    std::string out;
    for (std::size_t i = 0; i < 160 && readable(name + i, 1) && name[i]; ++i) {
        const char c = name[i];
        const bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' ||
                        c == '.' || c == '?' || c == '@' || c == '$';
        out += ok ? c : '_';
    }
    return out.empty() ? "unknown_name" : out;
}

// The first LIMIT frames in mapped images, unwinding from START, joined by " from ", or empty.
std::string mapped_frames(const CONTEXT* start, int limit) {
    CONTEXT context = *start;
    std::string out;
    int found = 0;
    for (int depth = 0; depth < 48 && context.Rip && found < limit; ++depth) {
        if (region_at(context.Rip)) {
            char where[160];
            describe(reinterpret_cast<void*>(context.Rip), where, sizeof where);
            out += (found++ ? " from " : "") + std::string(where);
        }
        DWORD64 image = 0;
        PRUNTIME_FUNCTION function = RtlLookupFunctionEntry(context.Rip, &image, nullptr);
        if (function) {
            void* handler_data = nullptr;
            DWORD64 frame = 0;
            RtlVirtualUnwind(UNW_FLAG_NHANDLER, image, context.Rip, function, &context, &handler_data, &frame, nullptr);
        } else {
            if (!readable(reinterpret_cast<void*>(context.Rsp), 8)) break;
            context.Rip = *reinterpret_cast<DWORD64*>(context.Rsp);
            context.Rsp += 8;
        }
    }
    return out;
}

// The first two frames in mapped images above RaiseException: "SITE" or "SITE from CALLER". With a static C
// runtime the first is the title's own _CxxThrowException and the second the throwing function.
std::string throw_site(const CONTEXT* start) {
    std::string out = mapped_frames(start, 2);
    if (!out.empty()) return out;
    char where[160];
    describe(reinterpret_cast<void*>(start->Rip), where, sizeof where);  // no mapped frame found
    return where;
}

void log_cpp_throw(EXCEPTION_POINTERS* info) {
    InterlockedIncrement(&cpp_throws);
    const std::string line = "cpp-throw " + thrown_type(info->ExceptionRecord) + " at " + throw_site(info->ContextRecord) + caller_chain(info);
    AcquireSRWLockExclusive(&cpp_lock);
    const bool first = cpp_seen.size() < kCppThrowLines && cpp_seen.insert(line).second;
    ReleaseSRWLockExclusive(&cpp_lock);
    if (!first) return;
    err_printf( "[x2w] %s\n", line.c_str());
    log_line("%s", line.c_str());
}

// The runtime's _CxxThrowException fills ExceptionInformation[3] with RtlPcToFileHeader(ThrowInfo), which
// knows only the Windows loader's modules and gives 0 for a ThrowInfo in an image pe_map mapped. With no base
// it also changes the magic number to the /clr:pure one (0x01994000), which native catch blocks ignore, so
// the throw would go unhandled. Before any frame handler runs, this handler gives a throw whose ThrowInfo lies
// in a mapped image that image's base and, unless the ThrowInfo itself is marked pure (TI_IsPure, 0x8), the
// native magic number back (whichever C runtime threw it). It is registered whether or not there is a run log.
LONG CALLBACK cpp_throw_base(EXCEPTION_POINTERS* info) {
    EXCEPTION_RECORD* record = info->ExceptionRecord;
    if (record->ExceptionCode != cpp_exception || record->NumberParameters < 4) return EXCEPTION_CONTINUE_SEARCH;
    const ULONG_PTR magic = record->ExceptionInformation[0];
    const bool native = magic == 0x19930520 || magic == 0x19930521 || magic == 0x19930522;
    if (!native && magic != 0x01994000) return EXCEPTION_CONTINUE_SEARCH;
    const auto address = static_cast<std::uintptr_t>(record->ExceptionInformation[2]);
    const Region* region = region_at(address);
    if (!region || record->ExceptionInformation[3] == region->base) return EXCEPTION_CONTINUE_SEARCH;
    if (!native) {
        // Pure magic with no base is the runtime's fallback; a real pure throw has TI_IsPure set.
        if (record->ExceptionInformation[3] != 0 || !readable(reinterpret_cast<const void*>(address), 4) ||
            (*reinterpret_cast<const std::uint32_t*>(address) & 0x8))
            return EXCEPTION_CONTINUE_SEARCH;
        record->ExceptionInformation[0] = 0x19930520;
    }
    record->ExceptionInformation[3] = static_cast<ULONG_PTR>(region->base);
    return EXCEPTION_CONTINUE_SEARCH;
}

// The first error-severity exception the program raises, whether or not it handles it. Codes with the
// customer bit are the program's own and are not logged as such; C++ exceptions (0xe06d7363) get their own
// "cpp-throw TYPE at SITE" lines, once per distinct line and at most 16.
// " callers A from B from C" for a fault outside the mapped images (in a Windows DLL, a shim or the
// launcher): the first three frames in mapped images that led there, or nothing.
// When unwinding finds no mapped frame (a frame without unwind data on the way, or a thread that never ran the
// program's code), the stack is scanned from RSP for return addresses into mapped images (a value that follows a
// call instruction): " callers? A B C (stack-scan)". With none of those either: " callers none thread-start X", the
// thread's start address, which says whose thread it is (a Windows DLL's worker, for example).
bool follows_call(std::uintptr_t at) {
    if (!region_at(at) || !region_at(at - 7)) return false;
    const auto* p = reinterpret_cast<const std::uint8_t*>(at);
    if (p[-5] == 0xe8) return true;                                    // call rel32
    if (p[-6] == 0xff && (p[-5] & 0x38) == 0x10) return true;          // call [rip+disp32] / [reg+disp32]
    if (p[-2] == 0xff && (p[-1] & 0x38) == 0x10) return true;          // call reg / [reg]
    if (p[-3] == 0xff && (p[-2] & 0x38) == 0x10) return true;          // call [reg+disp8]
    if (p[-7] == 0xff && (p[-6] & 0x38) == 0x10) return true;          // call [reg+index*s+disp32]
    return p[-4] == 0xff && (p[-3] & 0x38) == 0x10;                    // call [reg+index*s+disp8]
}

std::string stack_scan(const CONTEXT* context, int limit) {
    const auto* tib = reinterpret_cast<const NT_TIB*>(NtCurrentTeb());
    auto at = static_cast<std::uintptr_t>(context->Rsp) & ~std::uintptr_t{7};
    const auto top = reinterpret_cast<std::uintptr_t>(tib->StackBase);
    const std::uintptr_t end = top > at && top - at > 0x10000 ? at + 0x10000 : top;
    std::string out;
    int found = 0;
    for (; at + 8 <= end && found < limit; at += 8) {
        const auto value = *reinterpret_cast<const std::uintptr_t*>(at);
        if (!follows_call(value)) continue;
        char where[160];
        describe(reinterpret_cast<void*>(value), where, sizeof where);
        out += (found++ ? " " : "") + std::string(where);
    }
    return out;
}

std::string caller_chain(const EXCEPTION_POINTERS* info) {
    if (region_at(reinterpret_cast<std::uintptr_t>(info->ExceptionRecord->ExceptionAddress))) return {};
    const std::string frames = mapped_frames(info->ContextRecord, 3);
    if (!frames.empty()) return " callers " + frames;
    if (regions.empty()) return {};
    const std::string scanned = stack_scan(info->ContextRecord, 3);
    if (!scanned.empty()) return " callers? " + scanned + " (stack-scan)";
    void* start = nullptr;
    if (query_thread) query_thread(GetCurrentThread(), 9 /* ThreadQuerySetWin32StartAddress */, &start, sizeof start, nullptr);
    char where[160];
    describe(start, where, sizeof where);
    return std::string(" callers none thread-start ") + where;
}

// " regs rax=0x.. ... rsp=0x.." for an exception in a mapped image: register values only, never memory they point at.
std::string register_text(const EXCEPTION_POINTERS* info) {
    if (!region_at(reinterpret_cast<std::uintptr_t>(info->ExceptionRecord->ExceptionAddress))) return {};
    const CONTEXT* c = info->ContextRecord;
    const std::pair<const char*, DWORD64> regs[] = {
        {"rax", c->Rax}, {"rbx", c->Rbx}, {"rcx", c->Rcx}, {"rdx", c->Rdx}, {"rsi", c->Rsi}, {"rdi", c->Rdi},
        {"r8", c->R8},   {"r9", c->R9},   {"r10", c->R10}, {"r11", c->R11}, {"r12", c->R12}, {"r13", c->R13},
        {"r14", c->R14}, {"r15", c->R15}, {"rbp", c->Rbp}, {"rsp", c->Rsp},
    };
    std::string out = " regs";
    char one[40];
    for (const auto& [name, value] : regs) {
        std::snprintf(one, sizeof one, " %s=0x%llx", name, static_cast<unsigned long long>(value));
        out += one;
    }
    return out;
}

// --continue-breakpoints (the default when no debugger is attached; --stop-on-breakpoints turns it off): an int3 in a
// mapped image (0xCC, or the two-byte CD 03) is logged with its registers and skipped, because a retail title's
// asserts often fall through. At most kBreakpointLines lines; every one is counted ("breakpoints" line before the
// summary). __fastfail (int 29h) reaches no handler in the process and cannot be continued or logged here.
constexpr long kBreakpointLines = 50;
bool continue_breakpoints = false;

LONG CALLBACK breakpoint_continue(EXCEPTION_POINTERS* info) {
    if (info->ExceptionRecord->ExceptionCode != EXCEPTION_BREAKPOINT || !continue_breakpoints) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT* context = info->ContextRecord;
    const auto at = static_cast<std::uintptr_t>(context->Rip);
    if (!region_at(at) || !region_at(at + 1) || !region_at(at - 1)) return EXCEPTION_CONTINUE_SEARCH;
    // Windows reports an int3 at the instruction (RIP already moved back by one): 0xCC at RIP. For CD 03 it moves
    // back by one as well, so RIP is at the 03 byte; a record that names the CD byte itself is handled too.
    const auto* code = reinterpret_cast<const std::uint8_t*>(at);
    std::uintptr_t next = 0;
    if (code[0] == 0xCC) next = at + 1;
    else if (code[0] == 0x03 && code[-1] == 0xCD) next = at + 1;
    else if (code[0] == 0xCD && code[1] == 0x03) next = at + 2;
    if (!next) return EXCEPTION_CONTINUE_SEARCH;
    const long count = InterlockedIncrement(&breakpoints_continued);
    if (count <= kBreakpointLines) {
        char where[160];
        describe(reinterpret_cast<const void*>(at), where, sizeof where);
        const std::string regs = register_text(info);
        err_printf("[x2w] breakpoint continued at %s (count %ld)\n", where, count);
        log_line("breakpoint continued at %s count %ld%s", where, count, regs.c_str());
        if (count <= kTraceBreakpointDumps) trace_dump_current();
        if (count == kBreakpointLines) log_line("breakpoint %ld lines logged; later breakpoints are counted only", count);
    }
    context->Rip = next;
    return EXCEPTION_CONTINUE_EXECUTION;
}

// Error exceptions after the first are logged too, once per code and site and at most kFirstChanceLines in all.
constexpr long kFirstChanceLines = 8;
volatile long first_chance_lines;
std::set<std::string> first_chance_seen;
SRWLOCK first_chance_lock = SRWLOCK_INIT;

LONG CALLBACK first_chance(EXCEPTION_POINTERS* info) {
    const DWORD code = info->ExceptionRecord->ExceptionCode;
    if (armed && code == cpp_exception) log_cpp_throw(info);
    if (armed && code == 0xc0000374u) heap_guard_fault(info->ExceptionRecord);
    if (armed && (code & 0xc0000000u) == 0xc0000000u && !(code & 0x20000000u) && first_chance_lines < kFirstChanceLines) {
        char site[200];
        describe(info->ExceptionRecord->ExceptionAddress, site, sizeof site);
        char key[240];
        std::snprintf(key, sizeof key, "%08lx %s", code, site);
        AcquireSRWLockExclusive(&first_chance_lock);
        const bool fresh = first_chance_seen.size() < static_cast<std::size_t>(kFirstChanceLines) &&
                           first_chance_seen.insert(key).second;
        ReleaseSRWLockExclusive(&first_chance_lock);
        if (fresh) {
            InterlockedIncrement(&first_chance_lines);
            InterlockedExchange(&first_exception, 1);
            char text[512];
            exception_text(info->ExceptionRecord, text, sizeof text);
            const std::string chain = caller_chain(info);
            log_line("first-chance %s last-stub %s%s%s%s", text, last_stub_name().c_str(), chain.c_str(),
                     thread_init_text(info, chain).c_str(), register_text(info).c_str());
            trace_dump_current();
            log_provisional_summary();
        }
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

// An exception nothing handled. The process ends with the exception code as its exit code, without the
// Windows error dialog. A program that installs its own filter replaces this one; the first-chance line
// above is still written.
LONG WINAPI unhandled(EXCEPTION_POINTERS* info) {
    if (InterlockedExchange(&crashed, 1) == 0) {
        char text[512];
        exception_text(info->ExceptionRecord, text, sizeof text);
        const std::string chain = caller_chain(info);
        log_line("crash %s last-stub %s%s%s%s", text, last_stub_name().c_str(), chain.c_str(),
                 thread_init_text(info, chain).c_str(), register_text(info).c_str());
        trace_dump_current();
        trace_dump_main();
        log_summary("crash");
    }
    // The program's own filter (hook_SetUnhandledExceptionFilter) runs after the log is written.
    if (LPTOP_LEVEL_EXCEPTION_FILTER filter = title_filter) return filter(info);
    return EXCEPTION_EXECUTE_HANDLER;
}

bool in_program(std::uintptr_t at) {
    for (const auto& region : regions)
        if (at >= region.base && at - region.base < region.size) return true;
    return false;
}

// #UD in the program's code (the EXE or a mapped package DLL): perform the instruction if it is one the
// host lacks and x2w_cpu_trap.h knows, else name it in the log and let the exception go on.
LONG CALLBACK cpu_trap(EXCEPTION_POINTERS* info) {
    if (info->ExceptionRecord->ExceptionCode != STATUS_ILLEGAL_INSTRUCTION) return EXCEPTION_CONTINUE_SEARCH;
    CONTEXT* context = info->ContextRecord;
    const std::uintptr_t at = static_cast<std::uintptr_t>(context->Rip);
    if (!in_program(at)) return EXCEPTION_CONTINUE_SEARCH;
    std::uint8_t code[x2w_cpu::kMaxLength];
    std::size_t available;
    const auto site = forced_sites.find(at);
    if (site != forced_sites.end()) {
        std::memcpy(code, site->second.bytes, site->second.length);
        available = site->second.length;
    } else {
        available = x2w_cpu::read_code(reinterpret_cast<const void*>(at), code);
    }
    const x2w_cpu::Result result = x2w_cpu::emulate(context, code, available);
    char where[160];
    if (result.op != x2w_cpu::kUnhandled) {
        InterlockedIncrement(&trap_counts[result.op]);
        if (InterlockedExchange(&trap_seen[result.op], 1) == 0) {
            describe(reinterpret_cast<const void*>(at), where, sizeof where);
            err_printf( "[x2w] cpu trap %s at %s\n", x2w_cpu::op_name(result.op), where);
            log_line("cpu-trap first %s at %s", x2w_cpu::op_name(result.op), where);
        }
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    if (InterlockedIncrement(&unhandled_logged) <= kUnhandledLines) {
        describe(reinterpret_cast<const void*>(at), where, sizeof where);
        const char* mnemonic = x2w_cpu::name(code, available);
        err_printf( "[x2w] illegal instruction %s at %s\n", mnemonic, where);
        log_line("cpu-unhandled %s at %s", mnemonic, where);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

// The Zen 2 features this CPU lacks, by what happens to them: emulated by cpu_trap, unhandled (#UD and a
// crash), or silent (an older CPU runs the encoding as another instruction, so nothing traps).
void log_host_features() {
    std::string lists[3];
    std::size_t count = 0;
    const x2w_cpu::Feature* features = x2w_cpu::zen2_features(count);
    for (std::size_t i = 0; i < count; ++i) {
        if (x2w_cpu::host_has(features[i])) continue;
        std::string& list = lists[features[i].handling];
        if (!list.empty()) list += ",";
        list += features[i].name;
    }
    for (auto& list : lists)
        if (list.empty()) list = "none";
    if (lists[0] != "none" || lists[1] != "none" || lists[2] != "none")
        err_printf( "[x2w] host lacks Zen 2 features: emulated=%s unhandled=%s silent=%s\n",
                     lists[0].c_str(), lists[1].c_str(), lists[2].c_str());
    log_line("cpu-host-missing emulated=%s unhandled=%s silent=%s", lists[0].c_str(), lists[1].c_str(),
             lists[2].c_str());
}

// --force-cpu-traps: UD2 over each listed site, the original bytes kept for cpu_trap.
bool force_traps(void* base) {
    const auto* sites = static_cast<const std::uint64_t*>(map_export(base, "x2w_cpu_trap_sites"));
    if (!sites) return false;
    for (; *sites; ++sites) {
        auto* at = reinterpret_cast<std::uint8_t*>(*sites);
        if (!in_program(reinterpret_cast<std::uintptr_t>(at))) return false;
        Site site{};
        site.length = x2w_cpu::read_code(at, site.bytes);
        DWORD old = 0;
        if (site.length < 2 || !VirtualProtect(at, 2, PAGE_EXECUTE_READWRITE, &old)) return false;
        at[0] = 0x0f;
        at[1] = 0x0b;
        VirtualProtect(at, 2, old, &old);
        FlushInstructionCache(GetCurrentProcess(), at, 2);
        forced_sites[reinterpret_cast<std::uintptr_t>(at)] = site;
    }
    log_line("cpu-trap-forced sites %zu", forced_sites.size());
    return true;
}


// The launcher's own TLS callback sees every thread that starts in the process while the program runs.
void NTAPI launch_tls(PVOID, DWORD reason, PVOID) {
    // Process exit by a path no hook saw (ExitProcess from a Windows DLL, the C runtime's exit): the last summary.
    if (reason == DLL_PROCESS_DETACH && armed && log_file != INVALID_HANDLE_VALUE && !summary_written) {
        DWORD code = STILL_ACTIVE;
        if (GetExitCodeProcess(GetCurrentProcess(), &code) && code != STILL_ACTIVE) log_exit(code, "exit");
        else log_summary("process-exit");
    }
    if (slot0_index) {
        if (reason == DLL_THREAD_ATTACH) slot0_alias(current_tls_vector(), GetCurrentThreadId());
        // With pe_map's observer the alias comes down after the mapped images' detach (thread_observer).
        if (reason == DLL_THREAD_DETACH && !observer_set) slot0_restore(current_tls_vector(), GetCurrentThreadId());
    }
    if (reason != DLL_THREAD_ATTACH || !armed || GetCurrentThreadId() == watchdog_id) return;
    if (heap_guard && InterlockedExchange(&heap_first_thread, 1) == 0) heap_milestone("first-thread");
    if (log_file == INVALID_HANDLE_VALUE) return;
    void* start = nullptr;
    if (query_thread) query_thread(GetCurrentThread(), 9 /* ThreadQuerySetWin32StartAddress */, &start, sizeof start,
                                   nullptr);
    char where[160];
    describe(start, where, sizeof where);
    if (InterlockedExchange(&first_thread, 1) == 0) log_line("milestone first-thread start %s", where);
    const auto at = reinterpret_cast<std::uintptr_t>(start);
    if (!regions.empty() && at >= regions[0].base && at - regions[0].base < regions[0].size
        && InterlockedExchange(&first_title_thread, 1) == 0)
        log_line("milestone first-program-thread start %s", where);
}

// The console window closed (or Ctrl+C, log-off, shutdown) while the program ran, for example after a hang: the
// final summary first. Windows ends the process when this returns.
BOOL WINAPI console_closed(DWORD event) {
    if (armed && log_file != INVALID_HANDLE_VALUE && !summary_written) {
        log_line("console-event %lu (%s)", event,
                 event == CTRL_C_EVENT ? "ctrl-c" : event == CTRL_BREAK_EVENT ? "ctrl-break" : event == CTRL_CLOSE_EVENT ? "close"
                 : event == CTRL_LOGOFF_EVENT ? "logoff" : "shutdown");
        log_summary("console-close");
    }
    return FALSE;
}

HANDLE watchdog_ready;

// The watchdog starts before anything is mapped and the launcher waits until it runs, so the loader's thread
// attach for it is over before pe_map has an image to notify: no TLS callback or DllMain of the program or a
// package DLL ever runs on it. (Created later, it raced the program's own process attach.)
DWORD WINAPI watchdog(void* seconds) {
    const auto limit = static_cast<DWORD>(reinterpret_cast<std::uintptr_t>(seconds));
    set_phase(PHASE_WATCHDOG);
    SetEvent(watchdog_ready);
    // Once a second: the stall detector (see "stall detector"). Without --timeout (limit 0) it never ends the run.
    const ULONGLONG end = limit ? GetTickCount64() + static_cast<ULONGLONG>(limit) * 1000 : ~0ull;
    for (ULONGLONG now = GetTickCount64(); now < end; now = GetTickCount64()) {
        Sleep(static_cast<DWORD>(end - now < 1000 ? end - now : 1000));
        stall_scan();
    }
    log_line("timeout still running after %lu s", limit);
    log_summary("timeout");
    err_printf( "[x2w] timeout after %lu s\n", limit);
    TerminateProcess(GetCurrentProcess(), 124);
    return 0;
}

}  // namespace

// Shims (x2w_gdk.dll) find this with GetProcAddress(GetModuleHandle(nullptr), ...) and log through it.
extern "C" __declspec(dllexport) void __cdecl x2w_launch_log_shim(const char* kind, const char* symbol,
                                                                  const char* detail) {
    log_line("shim-%s %s %s", kind ? kind : "?", symbol ? symbol : "?", detail ? detail : "");
}

// The xgr gateway (and any shim) calls this at its own milestones: the heap guard validates the process heap there.
extern "C" __declspec(dllexport) void __cdecl x2w_launch_heap_milestone(const char* name) {
    heap_milestone(name ? name : "shim");
}

// Shims tag the handles they create (an event a title may wait on), so a stall line can name its creator; who null
// drops the tag (the shim is closing the handle). Later tags of a reused handle value replace earlier ones.
extern "C" __declspec(dllexport) void __cdecl x2w_launch_tag_handle(void* handle, const char* who) {
    if (!handle) return;
    AcquireSRWLockExclusive(&handle_tag_lock);
    HandleTag* slot = nullptr;
    for (auto& tag : handle_tags)
        if (tag.handle == handle) { slot = &tag; break; }
    if (!slot && who)
        for (auto& tag : handle_tags)
            if (!tag.handle) { slot = &tag; break; }
    if (slot) {
        if (who) {
            slot->handle = handle;
            std::snprintf(slot->who, sizeof slot->who, "%s", who);
            for (char& c : slot->who) if (c == ' ') c = '_';
        } else {
            slot->handle = nullptr;
        }
    }
    ReleaseSRWLockExclusive(&handle_tag_lock);
}

#pragma section(".CRT$XLB", long, read)
extern "C" __declspec(allocate(".CRT$XLB")) const PIMAGE_TLS_CALLBACK x2w_launch_tls = launch_tls;
#pragma comment(linker, "/include:x2w_launch_tls")
#pragma comment(linker, "/include:_tls_used")

int wmain(int argc, wchar_t** argv) {
    std::vector<std::pair<std::wstring, std::wstring>> xmem_settings;
    std::wstring program, log_path, sys_config;
    unsigned long timeout = 0;
    bool usage = false, force_cpu_traps = false;
    int breakpoint_mode = -1;  // -1: continue unless a debugger is attached
    for (int i = 1; i < argc; ++i) {
        const std::wstring argument = argv[i];
        if (argument == L"--shims" && i + 1 < argc) {
            shim_dirs.push_back(argv[++i]);
        } else if (argument == L"--log" && i + 1 < argc) {
            log_path = argv[++i];
        } else if (argument == L"--host-identity") {
            keep_host_identity = true;
        } else if (argument == L"--stall-all") {
            stall_all = true;
        } else if (argument == L"--timeout" && i + 1 < argc) {
            timeout = wcstoul(argv[++i], nullptr, 10);
        } else if (argument == L"--show-program-name") {
            show_program_name = true;
            SetEnvironmentVariableW(L"X2W_SHOW_PROGRAM_NAME", L"1");
        } else if (argument == L"--continue-breakpoints") {
            breakpoint_mode = 1;
        } else if (argument == L"--stop-on-breakpoints") {
            breakpoint_mode = 0;
        } else if (argument == L"--no-heap-guard") {
            heap_guard = false;
        } else if (argument == L"--heap-guard") {
            heap_guard = true;
        } else if (argument == L"--no-trace-calls") {
            trace_calls = false;
        } else if (argument == L"--trace-calls") {
            trace_calls = true;
        } else if (argument == L"--force-cpu-traps") {
            force_cpu_traps = true;
        } else if (argument == L"--xgr" && i + 1 < argc) {
            xgr_mode = lower(narrow(argv[++i]));
        } else if (argument == L"--sys-config" && i + 1 < argc) {
            sys_config = argv[++i];
        } else if (argument == L"--xmem" && i + 1 < argc) {
            const std::wstring setting = argv[++i];
            const auto equals = setting.find(L'=');
            if (equals == std::wstring::npos || equals == 0) {
                usage = true;
                continue;
            }
            std::wstring name = L"X2W_XMEM_";
            for (wchar_t c : setting.substr(0, equals)) name.push_back(static_cast<wchar_t>(std::towupper(c)));
            xmem_settings.emplace_back(name, setting.substr(equals + 1));
        } else if (program.empty()) {
            program = argument;
        } else {
            usage = true;
        }
    }
    if (xgr_mode == "shim") {
        wchar_t value[16] = {};
        if (GetEnvironmentVariableW(L"X2W_XGR", value, 16)) xgr_mode = lower(narrow(value));
    }
    if (xgr_mode != "shim" && xgr_mode != "ours" && xgr_mode != "trace" && xgr_mode != "record") usage = true;
    if (program.empty() || usage) {
        err_printf( "usage: x2w_launch [--shims DIR]... [--log FILE] [--stall-all] [--timeout SECONDS] [--force-cpu-traps] "
                     "[--host-identity] [--no-heap-guard] [--no-trace-calls] [--xgr shim|ours|trace|record] [--xmem NAME=VALUE]... [--sys-config FILE] [--show-program-name] "
                     "[--continue-breakpoints|--stop-on-breakpoints] program.exe\n");
        return 2;
    }
    if (!log_path.empty()) {
        // Truncate, then reopen for appending only.
        HANDLE created = CreateFileW(log_path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS,
                                     FILE_ATTRIBUTE_NORMAL, nullptr);
        if (created != INVALID_HANDLE_VALUE) CloseHandle(created);
        log_file = CreateFileW(log_path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                               FILE_ATTRIBUTE_NORMAL, nullptr);
        if (log_file == INVALID_HANDLE_VALUE) {
            err_printf( "[x2w] cannot write the log %ls\n", log_path.c_str());
            return 2;
        }
        query_thread = reinterpret_cast<QueryThread>(
            GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryInformationThread"));
        get_description = reinterpret_cast<GetDescription>(
            GetProcAddress(GetModuleHandleW(L"kernelbase.dll"), "GetThreadDescription"));
        SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
        AddVectoredExceptionHandler(1, first_chance);
        SetUnhandledExceptionFilter(unhandled);
        SetConsoleCtrlHandler(console_closed, TRUE);
    }
    // The title memory layer's informational lines (configuration, windows, arenas) belong in a title run's output.
    if (!GetEnvironmentVariableW(L"X2W_XMEM_LOG", nullptr, 0)) SetEnvironmentVariableW(L"X2W_XMEM_LOG", L"1");
    for (const auto& [name, value] : xmem_settings) {
        SetEnvironmentVariableW(name.c_str(), value.c_str());
        err_printf( "[x2w] xmem setting %ls=%ls\n", name.c_str(), value.c_str());
        log_line("xmem setting %ls=%ls", name.c_str(), value.c_str());
    }
    // After the logger, so the logger sees the corrected base.
    AddVectoredExceptionHandler(1, cpp_throw_base);
    continue_breakpoints = breakpoint_mode == 1 || (breakpoint_mode == -1 && !IsDebuggerPresent());
    AddVectoredExceptionHandler(1, breakpoint_continue);
    // Added last, so it runs before the first-chance logger and a performed instruction is not logged as one.
    AddVectoredExceptionHandler(1, cpu_trap);
    wchar_t self[MAX_PATH];
    GetModuleFileNameW(nullptr, self, MAX_PATH);
    launcher_dir = directory_of(self);
    if (xgr_gateway_on()) SetEnvironmentVariableW(L"X2W_XGR_MODE", widen(xgr_mode).c_str());
    HMODULE pe_map = LoadLibraryW((directory_of(self) + L"\\pe_map.dll").c_str());
    if (pe_map) {
        map_image = reinterpret_cast<MapImage>(GetProcAddress(pe_map, "pe_map_image"));
        map_export = reinterpret_cast<MapExport>(GetProcAddress(pe_map, "pe_map_export"));
        map_export_resolved = reinterpret_cast<MapExportResolved>(GetProcAddress(pe_map, "pe_map_export_resolved"));
        map_run = reinterpret_cast<MapRunTraced>(GetProcAddress(pe_map, "pe_map_run_traced"));
        using SetObserver = void* (*)(void*);
        phase_slot = TlsAlloc();
        set_phase(PHASE_MAIN);
        if (const auto set_observer = reinterpret_cast<SetObserver>(GetProcAddress(pe_map, "pe_map_thread_observer"))) {
            set_observer(reinterpret_cast<void*>(&thread_observer));
            observer_set = true;
        }
    }
    if (!map_image || !map_export || !map_run) {
        err_printf( "[x2w] pe_map.dll is missing beside x2w_launch.exe\n");
        log_line("error pe_map.dll is missing beside x2w_launch.exe");
        return 2;
    }
    wchar_t full[MAX_PATH];
    if (!GetFullPathNameW(program.c_str(), MAX_PATH, full, nullptr)) return 2;
    package_dir = directory_of(full);
    const std::string program_name = lower(narrow(file_of(full)));
    real_program_name = program_name;
    real_program_dir = lower(narrow(package_dir));
    while (real_program_dir.size() > 3 && (real_program_dir.back() == '\\' || real_program_dir.back() == '/'))
        real_program_dir.pop_back();
    log_line("x2w-run-log 1");
    log_line("program %s", show_program_name ? program_name.c_str() : kHiddenProgram);
    if (xgr_gateway_on()) log_line("xgr %s", xgr_mode.c_str());
    if (heap_guard) {
        // Windows' C runtime, whose heap functions the guard forwards to (the launcher itself links it).
        HMODULE ucrt = LoadLibraryW(L"ucrtbase.dll");
        if (ucrt) crt_init(0, [ucrt](const char* symbol) { return reinterpret_cast<void*>(GetProcAddress(ucrt, symbol)); });
        log_line("heap-guard on");
    }
    // Before any import is bound: every routed import gets its recent-calls thunk.
    if (trace_calls) {
        trace_calls = trace_init();
        if (trace_calls) stall_init();
        log_line(trace_calls ? "trace-calls on" : "trace-calls unavailable");
    }
    {
        std::wstring stem = file_of(full);
        const auto dot = stem.find_last_of(L'.');
        if (dot != std::wstring::npos) stem = stem.substr(0, dot);
        if (!GetEnvironmentVariableW(L"X2W_TITLE", nullptr, 0)) SetEnvironmentVariableW(L"X2W_TITLE", stem.c_str());
        if (!GetEnvironmentVariableW(L"X2W_TITLE_DIR", nullptr, 0))
            SetEnvironmentVariableW(L"X2W_TITLE_DIR", package_dir.c_str());
    }
    log_host_features();
    // The system layer, before any import is bound.
    struct SysGuard {
        ~SysGuard() {
            if (sys_shutdown) sys_shutdown();
        }
    } sys_guard;
    {
        std::wstring config_full;
        if (!sys_config.empty()) {
            wchar_t config_path[MAX_PATH];
            if (!GetFullPathNameW(sys_config.c_str(), MAX_PATH, config_path, nullptr) || !is_file(config_path)) {
                err_printf( "[x2w] --sys-config: cannot read %ls\n", sys_config.c_str());
                return 2;
            }
            config_full = config_path;
        }
        std::vector<std::wstring> directories = shim_dirs;
        directories.push_back(launcher_dir + L"\\shims");
        directories.push_back(launcher_dir);
        HMODULE sys_module = nullptr;
        for (const auto& directory : directories) {
            const std::wstring path = directory + L"\\x2w_sys.dll";
            if (is_file(path) && (sys_module = LoadLibraryExW(path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH))) break;
        }
        const auto init = sys_module ? reinterpret_cast<SysInit>(GetProcAddress(sys_module, "X2WSysInit")) : nullptr;
        sys_lookup = sys_module ? reinterpret_cast<SysLookup>(GetProcAddress(sys_module, "X2WSysHookLookup")) : nullptr;
        sys_shutdown = sys_module ? reinterpret_cast<SysShutdown>(GetProcAddress(sys_module, "X2WSysShutdown")) : nullptr;
        sys_describe = sys_module ? reinterpret_cast<SysDescribe>(GetProcAddress(sys_module, "X2WSysDescribeHandle")) : nullptr;
        if (!init || !sys_lookup || !sys_shutdown) {
            sys_lookup = nullptr;
            sys_shutdown = nullptr;
            if (!config_full.empty()) {
                err_printf( "[x2w] --sys-config needs x2w_sys.dll in a --shims directory\n");
                return 2;
            }
            err_printf( "[x2w] sys: x2w_sys.dll not found; no system layer\n");
        } else {
            std::wstring stem = file_of(full);
            const auto dot = stem.find_last_of(L'.');
            if (dot != std::wstring::npos) stem = stem.substr(0, dot);
            const std::string title_dir = narrow(package_dir), title_name = narrow(stem), config = narrow(config_full);
            init(title_dir.c_str(), title_name.c_str(), config.empty() ? nullptr : config.c_str());
        }
    }
    // Regions are appended by dynamic loads while other threads read them: no reallocation after this.
    regions.reserve(1024);
    if (log_file != INVALID_HANDLE_VALUE) {  // the stall detector runs with every --log; --timeout adds the kill timer
        // Suspended until its ID is known, so the thread callback can tell it from the program's threads; the
        // launcher then waits until it runs, before mapping anything (see watchdog).
        watchdog_ready = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        HANDLE thread = CreateThread(nullptr, 0, watchdog, reinterpret_cast<void*>(static_cast<std::uintptr_t>(timeout)),
                                     CREATE_SUSPENDED, &watchdog_id);
        if (thread) {
            ResumeThread(thread);
            if (watchdog_ready) WaitForSingleObject(watchdog_ready, 10000);
            CloseHandle(thread);
        }
    }
    std::uint32_t status = 0;
    char detail[512] = {};
    void* base = map_image(full, resolve, &status, detail, sizeof detail);
    if (!base) {
        err_printf( "[x2w] cannot map %ls: status %u %s\n", full, status, detail);
        log_line("map-failed status %u %s", status, detail);
        return 3;
    }
    regions.insert(regions.begin(),
                   Region{program_name, reinterpret_cast<std::uintptr_t>(base), image_size(base), full,
                          show_program_name ? program_name : std::string(kHiddenProgram)});
    slot0_start(base);
    InterlockedExchange(&mapping_done, 1);
    log_line("mapped size 0x%llx", static_cast<unsigned long long>(regions[0].size));
    log_line("imports shim=%u package=%u windows=%u stub=%u missing=%u", route_counts["shim"],
             route_counts["package"], route_counts["windows"], route_counts["stub"], route_counts["missing"]);
    if (force_cpu_traps && !force_traps(base)) {
        err_printf( "[x2w] --force-cpu-traps: no usable x2w_cpu_trap_sites export\n");
        log_line("error no usable x2w_cpu_trap_sites export");
        return 2;
    }
    std::fflush(stderr);
    std::uint32_t exit_code = 0;
    InterlockedExchange(&armed, 1);
    start_identity(base);
    const int ran = map_run(base, &exit_code, log_file != INVALID_HANDLE_VALUE ? observe_run : nullptr);
    end_identity();
    if (slot0_index) slot0_restore(current_tls_vector(), GetCurrentThreadId());
    if (!ran) {
        err_printf( "[x2w] %ls has no runnable entry point\n", full);
        log_line("error no runnable entry point");
        return 4;
    }
    long calls = 0;
    for (const Stub* stub : stubs) calls += stub->calls;
    err_printf( "[x2w] exit code %u; %zu stubs, %ld stub calls\n", exit_code, stubs.size(), calls);
    log_exit(exit_code, "exit");
    return static_cast<int>(exit_code);
}
