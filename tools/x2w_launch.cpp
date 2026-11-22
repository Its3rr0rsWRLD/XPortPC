// x2w_launch: map an EXE with pe_map and route each import to a shim, a packaged DLL, Windows or a stub.
//
// Usage: x2w_launch [--shims DIR]... [--log FILE] [--timeout SECONDS] program.exe
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
// is still going after that many seconds with exit code 124, after logging how far it got.
#include <windows.h>

#include <cctype>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace {

using Resolver = void*(__cdecl*)(const char* dll, const char* name, std::uint32_t ordinal);
using MapImage = void* (*)(const wchar_t*, Resolver, std::uint32_t*, char*, std::size_t);
using MapExport = void* (*)(void*, const char*);
using RunObserver = void(__cdecl*)(int event, std::uint32_t index, void* address);
using MapRunTraced = int (*)(void*, std::uint32_t*, RunObserver);

MapImage map_image;
MapExport map_export;
MapRunTraced map_run;
std::vector<std::wstring> shim_dirs;
std::wstring package_dir;
std::map<std::string, HMODULE> shim_modules;
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
DWORD watchdog_id;
std::map<std::string, unsigned> route_counts;

struct Region {
    std::string name;
    std::uintptr_t base;
    std::size_t size;
};
std::vector<Region> regions;  // the program first, then each mapped package DLL

struct Watch {
    std::string dll;
    std::string symbol;
    volatile long calls = 0;
};
std::vector<Watch*> watches;

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

void log_line(const char* format, ...) {
    if (log_file == INVALID_HANDLE_VALUE) return;
    char line[1024];
    va_list args;
    va_start(args, format);
    int length = std::vsnprintf(line, sizeof line - 1, format, args);
    va_end(args);
    if (length < 0) return;
    if (length > static_cast<int>(sizeof line) - 2) length = static_cast<int>(sizeof line) - 2;
    line[length++] = '\n';
    DWORD written = 0;
    // The file is opened for appending only, so lines from different threads never overwrite each other.
    WriteFile(log_file, line, static_cast<DWORD>(length), &written, nullptr);
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
            std::snprintf(out, capacity, "%s+0x%llx", region.name.c_str(),
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

void log_summary(const char* how) {
    log_line("summary %s: tls-callbacks=%s entry=%s first-thread=%s d3d12-call=%s crash=%s last-stub=%s", how,
             tls_done ? "done" : "not-done", entry_reached ? "reached" : "not-reached",
             first_thread ? "yes" : "no", first_d3d12 ? "yes" : "no", crashed ? "yes" : "no",
             last_stub_name().c_str());
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
        std::fprintf(stderr, "[x2w] call stub %s!%s\n", stub->dll.c_str(), stub->symbol.c_str());
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
    std::fprintf(stderr, "[x2w] import %s!%s -> %s\n", dll.c_str(), symbol.c_str(), route);
    ++route_counts[kind];
    // Watch the program's d3d12* imports for the run log; stubs record their own first call.
    if (log_file != INVALID_HANDLE_VALUE && address && std::strncmp(kind, "stub", 4) != 0
        && std::strcmp(kind, "missing") != 0 && dll.rfind("d3d12", 0) == 0)
        return make_watch(dll, symbol, address);
    return address;
}

void* __cdecl resolve(const char* dll, const char* name, std::uint32_t ordinal) {
    const std::string key = lower(dll);
    const std::string symbol = name ? std::string(name) : "#" + std::to_string(ordinal);
    const char* lookup = name ? name : MAKEINTRESOURCEA(ordinal);
    for (const auto& directory : shim_dirs) {
        const std::wstring path = directory + L"\\" + widen(key);
        if (!is_file(path)) continue;
        HMODULE& module = shim_modules[key];
        if (!module) module = LoadLibraryW(path.c_str());
        if (module)
            if (void* address = reinterpret_cast<void*>(GetProcAddress(module, lookup)))
                return report(key, symbol, "shim", "shim", address);
        return report(key, symbol, "stub (not in shim)", "stub", make_stub(key, symbol, false));
    }
    const std::wstring local = package_dir + L"\\" + widen(key);
    if (is_file(local)) {
        void*& base = package_images[key];
        if (!base && !mapping.count(key)) {
            mapping.insert(key);
            std::uint32_t status = 0;
            char detail[256] = {};
            base = map_image(local.c_str(), resolve, &status, detail, sizeof detail);
            mapping.erase(key);
            if (!base) {
                std::fprintf(stderr, "[x2w] cannot map %s: status %u %s\n", key.c_str(), status, detail);
                log_line("package-map-failed %s status %u %s", key.c_str(), status, detail);
            } else {
                regions.push_back({key, reinterpret_cast<std::uintptr_t>(base), image_size(base)});
            }
        }
        if (base && name)
            if (void* address = map_export(base, name)) return report(key, symbol, "package", "package", address);
        return report(key, symbol, "stub (package)", "stub", make_stub(key, symbol, false));
    }
    if (HMODULE module = LoadLibraryA(dll)) {
        if (void* address = reinterpret_cast<void*>(GetProcAddress(module, lookup)))
            return report(key, symbol, "windows", "windows", address);
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

void exception_text(const EXCEPTION_RECORD* record, char* out, std::size_t capacity) {
    char where[160];
    describe(record->ExceptionAddress, where, sizeof where);
    int used = std::snprintf(out, capacity, "exception 0x%08lx at %s thread %s", record->ExceptionCode, where,
                             GetCurrentThreadId() == watchdog_id ? "watchdog" : "program");
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

// The first error-severity exception the program raises, whether or not it handles it. Codes with the
// customer bit (such as C++ exceptions, 0xe06d7363) are the program's own and are not logged.
LONG CALLBACK first_chance(EXCEPTION_POINTERS* info) {
    const DWORD code = info->ExceptionRecord->ExceptionCode;
    if (armed && (code & 0xc0000000u) == 0xc0000000u && !(code & 0x20000000u)
        && InterlockedExchange(&first_exception, 1) == 0) {
        char text[512];
        exception_text(info->ExceptionRecord, text, sizeof text);
        log_line("first-chance %s last-stub %s", text, last_stub_name().c_str());
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
        log_line("crash %s last-stub %s", text, last_stub_name().c_str());
        log_summary("crash");
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

using QueryThread = LONG(NTAPI*)(HANDLE, ULONG, PVOID, ULONG, PULONG);
QueryThread query_thread;

// The launcher's own TLS callback sees every thread that starts in the process while the program runs.
void NTAPI launch_tls(PVOID, DWORD reason, PVOID) {
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

DWORD WINAPI watchdog(void* seconds) {
    const auto limit = static_cast<DWORD>(reinterpret_cast<std::uintptr_t>(seconds));
    Sleep(limit * 1000);
    log_line("timeout still running after %lu s", limit);
    log_summary("timeout");
    std::fprintf(stderr, "[x2w] timeout after %lu s\n", limit);
    TerminateProcess(GetCurrentProcess(), 124);
    return 0;
}

}  // namespace

#pragma section(".CRT$XLB", long, read)
extern "C" __declspec(allocate(".CRT$XLB")) const PIMAGE_TLS_CALLBACK x2w_launch_tls = launch_tls;
#pragma comment(linker, "/include:x2w_launch_tls")
#pragma comment(linker, "/include:_tls_used")

int wmain(int argc, wchar_t** argv) {
    std::wstring program, log_path;
    unsigned long timeout = 0;
    bool usage = false;
    for (int i = 1; i < argc; ++i) {
        const std::wstring argument = argv[i];
        if (argument == L"--shims" && i + 1 < argc) {
            shim_dirs.push_back(argv[++i]);
        } else if (argument == L"--log" && i + 1 < argc) {
            log_path = argv[++i];
        } else if (argument == L"--timeout" && i + 1 < argc) {
            timeout = wcstoul(argv[++i], nullptr, 10);
        } else if (program.empty()) {
            program = argument;
        } else {
            usage = true;
        }
    }
    if (program.empty() || usage) {
        std::fprintf(stderr, "usage: x2w_launch [--shims DIR]... [--log FILE] [--timeout SECONDS] program.exe\n");
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
            std::fprintf(stderr, "[x2w] cannot write the log %ls\n", log_path.c_str());
            return 2;
        }
        query_thread = reinterpret_cast<QueryThread>(
            GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryInformationThread"));
        SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
        AddVectoredExceptionHandler(1, first_chance);
        SetUnhandledExceptionFilter(unhandled);
    }
    wchar_t self[MAX_PATH];
    GetModuleFileNameW(nullptr, self, MAX_PATH);
    HMODULE pe_map = LoadLibraryW((directory_of(self) + L"\\pe_map.dll").c_str());
    if (pe_map) {
        map_image = reinterpret_cast<MapImage>(GetProcAddress(pe_map, "pe_map_image"));
        map_export = reinterpret_cast<MapExport>(GetProcAddress(pe_map, "pe_map_export"));
        map_run = reinterpret_cast<MapRunTraced>(GetProcAddress(pe_map, "pe_map_run_traced"));
    }
    if (!map_image || !map_export || !map_run) {
        std::fprintf(stderr, "[x2w] pe_map.dll is missing beside x2w_launch.exe\n");
        log_line("error pe_map.dll is missing beside x2w_launch.exe");
        return 2;
    }
    wchar_t full[MAX_PATH];
    if (!GetFullPathNameW(program.c_str(), MAX_PATH, full, nullptr)) return 2;
    package_dir = directory_of(full);
    const std::string program_name = lower(narrow(file_of(full)));
    log_line("x2w-run-log 1");
    log_line("program %s", program_name.c_str());
    std::uint32_t status = 0;
    char detail[512] = {};
    void* base = map_image(full, resolve, &status, detail, sizeof detail);
    if (!base) {
        std::fprintf(stderr, "[x2w] cannot map %ls: status %u %s\n", full, status, detail);
        log_line("map-failed status %u %s", status, detail);
        return 3;
    }
    regions.insert(regions.begin(), Region{program_name, reinterpret_cast<std::uintptr_t>(base), image_size(base)});
    unsigned missing_stubs = 0;
    for (const Stub* stub : stubs) missing_stubs += stub->missing;
    log_line("mapped size 0x%llx", static_cast<unsigned long long>(regions[0].size));
    log_line("imports shim=%u package=%u windows=%u stub=%u missing=%u", route_counts["shim"],
             route_counts["package"], route_counts["windows"], route_counts["stub"], route_counts["missing"]);
    if (log_file != INVALID_HANDLE_VALUE && timeout) {
        // Suspended until its ID is known, so the thread callback can tell it from the program's threads.
        HANDLE thread = CreateThread(nullptr, 0, watchdog, reinterpret_cast<void*>(static_cast<std::uintptr_t>(timeout)),
                                     CREATE_SUSPENDED, &watchdog_id);
        if (thread) {
            ResumeThread(thread);
            CloseHandle(thread);
        }
    }
    std::fflush(stderr);
    std::uint32_t exit_code = 0;
    InterlockedExchange(&armed, 1);
    if (!map_run(base, &exit_code, log_file != INVALID_HANDLE_VALUE ? observe_run : nullptr)) {
        std::fprintf(stderr, "[x2w] %ls has no runnable entry point\n", full);
        log_line("error no runnable entry point");
        return 4;
    }
    long calls = 0;
    for (const Stub* stub : stubs) calls += stub->calls;
    std::fprintf(stderr, "[x2w] exit code %u; %zu stubs, %ld stub calls\n", exit_code, stubs.size(), calls);
    log_line("exit code 0x%x (%u); stubs %zu (missing %u), stub calls %ld", exit_code, exit_code, stubs.size(),
             missing_stubs, calls);
    log_summary("exit");
    return static_cast<int>(exit_code);
}
