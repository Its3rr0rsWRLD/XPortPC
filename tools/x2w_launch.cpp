// x2w_launch: map an EXE with pe_map and route each import to a shim, a packaged DLL, Windows or a stub.
//
// Usage: x2w_launch [--shims DIR]... [--log FILE] [--timeout SECONDS] [--force-cpu-traps] [--host-identity]
//                   [--xmem NAME=VALUE]... [--sys-config FILE] [--show-program-name] program.exe
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
// --log FILE writes a run log meant to be pasted into a report. It holds names and addresses only, never
// bytes of the program: the import route totals, each first call to a stub ("stub" when the DLL exists but
// lacks the function, "missing" when no route has the DLL), how far startup got (TLS callbacks, entry, the
// first thread created, the first call into a d3d12* import), the first exception and the first unhandled
// crash (code, module + RVA, last stub called) and the exit code. Each line is written with its own
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
// The title sees itself as the process image: its GetModuleHandle(NULL), GetModuleFileName(NULL) and the PEB's
// ImageBaseAddress name the mapped program, not this launcher (see "Module identity" below). --host-identity
// leaves them naming the launcher, for comparison.
//
// Program name. Stderr and the run log call the program title.exe (the program line, module+RVA, callers, mapped-image
// names, dynamic-load/resolve/handle lines, errors); its real file name appears in neither. The launcher prints no
// name read from inside the image. Package and imported DLL names are unchanged. --show-program-name restores the real
// file name, for the launcher's own tests.
#include <windows.h>
#include <tlhelp32.h>

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
    volatile long calls = 0;
};
std::vector<Watch*> watches;

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

std::string scrub_program_name(std::string text) {
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
    char line[1024];
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
void describe(const void* address, char* out, std::size_t capacity) {
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
void log_summary(const char* how) {
    if (InterlockedExchange(&summary_written, 1) != 0) return;
    log_cpu_traps();
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
    if (InterlockedIncrement(&stub->calls) == 1) {
        err_printf( "[x2w] call stub %s!%s\n", stub->dll.c_str(), stub->symbol.c_str());
        log_line("first-call %s %s!%s", stub->missing ? "missing" : "stub", stub->dll.c_str(), stub->symbol.c_str());
        if (stub->d3d12) d3d12_milestone(stub->dll, stub->symbol, stub->missing ? "missing" : "stub");
    }
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

extern "C" void x2w_watch_call(std::uint64_t index) {
    Watch* watch = watches[static_cast<std::size_t>(index)];
    if (InterlockedIncrement(&watch->calls) == 1) d3d12_milestone(watch->dll, watch->symbol, "bound");
}

// A watched import runs a thunk that records the call and then jumps to the bound function with the caller's
// arguments intact: RCX, RDX, R8, R9 and XMM0-XMM3 are saved around the record call and the stack arguments
// are not touched. On entry RSP is 8 mod 16; four pushes and 0x68 bytes make it 0 mod 16 for the call, with
// the home space at [RSP, RSP+0x20) and the XMM saves above it. Assembled with llvm-mc from:
//   push rcx; push rdx; push r8; push r9; sub rsp, 0x68
//   movdqu [rsp+0x20..0x50], xmm0..xmm3
//   mov rcx, <index>; mov rax, <x2w_watch_call>; call rax
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
    const std::uint64_t index = watches.size();
    watches.push_back(new Watch{dll, symbol});
    const auto handler = reinterpret_cast<std::uint64_t>(&x2w_watch_call);
    const auto destination = reinterpret_cast<std::uint64_t>(target);
    std::memcpy(thunk, kWatchCode, sizeof kWatchCode);
    std::memcpy(thunk + kWatchIndex, &index, 8);
    std::memcpy(thunk + kWatchHandler, &handler, 8);
    std::memcpy(thunk + kWatchTarget, &destination, 8);
    FlushInstructionCache(GetCurrentProcess(), thunk, kWatchBytes);
    return thunk;
}

void* report(const std::string& dll, const std::string& symbol, const char* route, const char* kind, void* address) {
    err_printf( "[x2w] import %s!%s -> %s\n", dll.c_str(), symbol.c_str(), route);
    ++route_counts[kind];
    // Watch the program's d3d12* imports for the run log; stubs record their own first call.
    if (log_file != INVALID_HANDLE_VALUE && address && std::strncmp(kind, "stub", 4) != 0
        && std::strcmp(kind, "missing") != 0 && dll.rfind("d3d12", 0) == 0)
        return make_watch(dll, symbol, address);
    return address;
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
// thread's attach; on thread detach it puts its own entry back, so ntdll frees each block once. The
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
    log_line("tls-slot0 index %lu threads %u", static_cast<unsigned long>(index), threads);
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
        else if (void* sys = sys_hook(dll, name)) address = reinterpret_cast<FARPROC>(sys);
    }
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

void* crash_hook(const std::string& dll, const char* name) {
    if (log_file == INVALID_HANDLE_VALUE || !name) return nullptr;
    const bool base = dll == "kernel32.dll" || dll == "kernelbase.dll";
    if (std::strcmp(name, "SetUnhandledExceptionFilter") == 0 &&
        (base || dll.rfind("api-ms-win-core-errorhandling-", 0) == 0))
        return reinterpret_cast<void*>(&hook_SetUnhandledExceptionFilter);
    if (!base && dll.rfind("api-ms-win-core-processthreads-", 0) != 0) return nullptr;
    if (std::strcmp(name, "ExitProcess") == 0) return reinterpret_cast<void*>(&hook_ExitProcess);
    if (std::strcmp(name, "TerminateProcess") == 0) return reinterpret_cast<void*>(&hook_TerminateProcess);
    return nullptr;
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
            if (void* address = map_export(base, name)) return report(key, symbol, "package", "package", address);
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
    const std::string line = "cpp-throw " + thrown_type(info->ExceptionRecord) + " at " + throw_site(info->ContextRecord);
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
std::string caller_chain(const EXCEPTION_POINTERS* info) {
    if (region_at(reinterpret_cast<std::uintptr_t>(info->ExceptionRecord->ExceptionAddress))) return {};
    const std::string frames = mapped_frames(info->ContextRecord, 3);
    return frames.empty() ? std::string() : " callers " + frames;
}

// Error exceptions after the first are logged too, once per code and site and at most kFirstChanceLines in all.
constexpr long kFirstChanceLines = 8;
volatile long first_chance_lines;
std::set<std::string> first_chance_seen;
SRWLOCK first_chance_lock = SRWLOCK_INIT;

LONG CALLBACK first_chance(EXCEPTION_POINTERS* info) {
    const DWORD code = info->ExceptionRecord->ExceptionCode;
    if (armed && code == cpp_exception) log_cpp_throw(info);
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
            log_line("first-chance %s last-stub %s%s", text, last_stub_name().c_str(), caller_chain(info).c_str());
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
        log_line("crash %s last-stub %s%s", text, last_stub_name().c_str(), caller_chain(info).c_str());
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

using QueryThread = LONG(NTAPI*)(HANDLE, ULONG, PVOID, ULONG, PULONG);
QueryThread query_thread;

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
        if (reason == DLL_THREAD_DETACH) slot0_restore(current_tls_vector(), GetCurrentThreadId());
    }
    if (reason != DLL_THREAD_ATTACH || !armed || log_file == INVALID_HANDLE_VALUE) return;
    if (GetCurrentThreadId() == watchdog_id) return;
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

HANDLE watchdog_ready;

// The watchdog starts before anything is mapped and the launcher waits until it runs, so the loader's thread
// attach for it is over before pe_map has an image to notify: no TLS callback or DllMain of the program or a
// package DLL ever runs on it. (Created later, it raced the program's own process attach.)
DWORD WINAPI watchdog(void* seconds) {
    const auto limit = static_cast<DWORD>(reinterpret_cast<std::uintptr_t>(seconds));
    SetEvent(watchdog_ready);
    Sleep(limit * 1000);
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

#pragma section(".CRT$XLB", long, read)
extern "C" __declspec(allocate(".CRT$XLB")) const PIMAGE_TLS_CALLBACK x2w_launch_tls = launch_tls;
#pragma comment(linker, "/include:x2w_launch_tls")
#pragma comment(linker, "/include:_tls_used")

int wmain(int argc, wchar_t** argv) {
    std::vector<std::pair<std::wstring, std::wstring>> xmem_settings;
    std::wstring program, log_path, sys_config;
    unsigned long timeout = 0;
    bool usage = false, force_cpu_traps = false;
    for (int i = 1; i < argc; ++i) {
        const std::wstring argument = argv[i];
        if (argument == L"--shims" && i + 1 < argc) {
            shim_dirs.push_back(argv[++i]);
        } else if (argument == L"--log" && i + 1 < argc) {
            log_path = argv[++i];
        } else if (argument == L"--host-identity") {
            keep_host_identity = true;
        } else if (argument == L"--timeout" && i + 1 < argc) {
            timeout = wcstoul(argv[++i], nullptr, 10);
        } else if (argument == L"--show-program-name") {
            show_program_name = true;
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
        err_printf( "usage: x2w_launch [--shims DIR]... [--log FILE] [--timeout SECONDS] [--force-cpu-traps] "
                     "[--host-identity] [--xgr shim|ours|trace|record] [--xmem NAME=VALUE]... [--sys-config FILE] [--show-program-name] program.exe\n");
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
    log_line("x2w-run-log 1");
    log_line("program %s", show_program_name ? program_name.c_str() : kHiddenProgram);
    if (xgr_gateway_on()) log_line("xgr %s", xgr_mode.c_str());
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
    if (log_file != INVALID_HANDLE_VALUE && timeout) {
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
