// x2w_launch: map an EXE with pe_map and route each import to a shim, a packaged DLL, Windows or a stub.
//
// Usage: x2w_launch [--shims DIR]... program.exe
//
// Imports resolve in this order:
//   1. DIR\<dll> from a --shims directory, loaded with LoadLibrary (a desktop shim for a console library);
//   2. <dll> beside the program, mapped with pe_map like the program itself;
//   3. the Windows loader's normal search;
//   4. a generated stub that logs "dll!symbol" on its first call and returns 0.
// Every import is reported on stderr as "[x2w] import dll!symbol -> shim|package|windows|stub", so a run
// lists what a program still needs. The program runs on this thread through pe_map_run, and its entry
// point's return value becomes this process's exit code.
#include <windows.h>

#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace {

using Resolver = void*(__cdecl*)(const char* dll, const char* name, std::uint32_t ordinal);
using MapImage = void* (*)(const wchar_t*, Resolver, std::uint32_t*, char*, std::size_t);
using MapExport = void* (*)(void*, const char*);
using MapRun = int (*)(void*, std::uint32_t*);

MapImage map_image;
MapExport map_export;
MapRun map_run;
std::vector<std::wstring> shim_dirs;
std::wstring package_dir;
std::map<std::string, HMODULE> shim_modules;
std::map<std::string, void*> package_images;
std::set<std::string> mapping;  // package DLLs being mapped, to stop import cycles

struct Stub {
    std::string dll;
    std::string symbol;
    volatile long calls = 0;
};
std::vector<Stub*> stubs;
std::uint8_t* stub_page;
std::size_t stub_used;
constexpr std::size_t kStubBytes = 32;
constexpr std::size_t kStubPage = 1 << 16;

std::string lower(std::string text) {
    for (auto& c : text) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return text;
}

std::wstring widen(const std::string& text) { return std::wstring(text.begin(), text.end()); }

bool is_file(const std::wstring& path) {
    const DWORD attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

std::wstring directory_of(const std::wstring& path) {
    const auto slash = path.find_last_of(L"\\/");
    return slash == std::wstring::npos ? L"." : path.substr(0, slash);
}

// A stub is reached by a jump from its thunk with the caller's return address on the stack, so it returns
// straight to the program. RCX holds the stub index; the program's own arguments are ignored.
extern "C" std::uint64_t x2w_stub_call(std::uint64_t index) {
    Stub* stub = stubs[static_cast<std::size_t>(index)];
    if (InterlockedIncrement(&stub->calls) == 1)
        std::fprintf(stderr, "[x2w] call stub %s!%s\n", stub->dll.c_str(), stub->symbol.c_str());
    return 0;
}

void* make_stub(const std::string& dll, const std::string& symbol) {
    if (!stub_page || stub_used + kStubBytes > kStubPage) {
        stub_page = static_cast<std::uint8_t*>(
            VirtualAlloc(nullptr, kStubPage, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
        stub_used = 0;
        if (!stub_page) return nullptr;
    }
    const std::uint64_t index = stubs.size();
    stubs.push_back(new Stub{dll, symbol});
    std::uint8_t* thunk = stub_page + stub_used;
    stub_used += kStubBytes;
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

void* report(const std::string& dll, const std::string& symbol, const char* route, void* address) {
    std::fprintf(stderr, "[x2w] import %s!%s -> %s\n", dll.c_str(), symbol.c_str(), route);
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
                return report(key, symbol, "shim", address);
        return report(key, symbol, "stub (not in shim)", make_stub(key, symbol));
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
            if (!base) std::fprintf(stderr, "[x2w] cannot map %s: status %u %s\n", key.c_str(), status, detail);
        }
        if (base && name)
            if (void* address = map_export(base, name)) return report(key, symbol, "package", address);
        return report(key, symbol, "stub (package)", make_stub(key, symbol));
    }
    if (HMODULE module = LoadLibraryA(dll))
        if (void* address = reinterpret_cast<void*>(GetProcAddress(module, lookup)))
            return report(key, symbol, "windows", address);
    return report(key, symbol, "stub", make_stub(key, symbol));
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    std::wstring program;
    for (int i = 1; i < argc; ++i) {
        const std::wstring argument = argv[i];
        if (argument == L"--shims" && i + 1 < argc) {
            shim_dirs.push_back(argv[++i]);
        } else if (program.empty()) {
            program = argument;
        } else {
            program.clear();
            break;
        }
    }
    if (program.empty()) {
        std::fprintf(stderr, "usage: x2w_launch [--shims DIR]... program.exe\n");
        return 2;
    }
    wchar_t self[MAX_PATH];
    GetModuleFileNameW(nullptr, self, MAX_PATH);
    HMODULE pe_map = LoadLibraryW((directory_of(self) + L"\\pe_map.dll").c_str());
    if (pe_map) {
        map_image = reinterpret_cast<MapImage>(GetProcAddress(pe_map, "pe_map_image"));
        map_export = reinterpret_cast<MapExport>(GetProcAddress(pe_map, "pe_map_export"));
        map_run = reinterpret_cast<MapRun>(GetProcAddress(pe_map, "pe_map_run"));
    }
    if (!map_image || !map_export || !map_run) {
        std::fprintf(stderr, "[x2w] pe_map.dll is missing beside x2w_launch.exe\n");
        return 2;
    }
    wchar_t full[MAX_PATH];
    if (!GetFullPathNameW(program.c_str(), MAX_PATH, full, nullptr)) return 2;
    package_dir = directory_of(full);
    std::uint32_t status = 0;
    char detail[512] = {};
    void* base = map_image(full, resolve, &status, detail, sizeof detail);
    if (!base) {
        std::fprintf(stderr, "[x2w] cannot map %ls: status %u %s\n", full, status, detail);
        return 3;
    }
    std::fflush(stderr);
    std::uint32_t exit_code = 0;
    if (!map_run(base, &exit_code)) {
        std::fprintf(stderr, "[x2w] %ls has no runnable entry point\n", full);
        return 4;
    }
    long calls = 0;
    for (const Stub* stub : stubs) calls += stub->calls;
    std::fprintf(stderr, "[x2w] exit code %u; %zu stubs, %ld stub calls\n", exit_code, stubs.size(), calls);
    return static_cast<int>(exit_code);
}
