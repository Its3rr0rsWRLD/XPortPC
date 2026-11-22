// Run the generated EXE entry with its RIP-relative operands bound to the source image.
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cwchar>
#include <cstring>

using Resolver = void* (*)(const char*, const char*, std::uint32_t);
extern "C" __declspec(dllimport) void* pe_map_image(const wchar_t*, Resolver, std::uint32_t*, char*, size_t);
extern "C" __declspec(dllimport) void* pe_map_export(void*, const char*);
extern "C" __declspec(dllimport) int pe_map_release(void*);
extern "C" int lifted_bind_image(std::uint64_t);
extern "C" void lifted_unbind_image();
int translated_entry();

static void* resolve(const char* dll, const char* name, std::uint32_t)
{
    // The translated entry already imports the same two fixture DLLs.
    if (!name || (_stricmp(dll, "cpu_exe_io.dll") && _stricmp(dll, "cpu_import_provider.dll")))
        return nullptr;
    return reinterpret_cast<void*>(GetProcAddress(GetModuleHandleA(dll), name));
}

int wmain(int argc, wchar_t** argv)
{
    if (argc != 4) return 3;
    void* preferred = reinterpret_cast<void*>(std::wcstoull(argv[2], nullptr, 16));
    const auto expected_slot = std::wcstoull(argv[3], nullptr, 16);
    // Occupying even the first page prevents a preferred-base mapping. It may already be occupied.
    void* reservation = VirtualAlloc(preferred, 4096, MEM_RESERVE, PAGE_NOACCESS);
    std::uint32_t status = 0;
    char detail[256]{};
    void* base = pe_map_image(argv[1], resolve, &status, detail, sizeof(detail));
    if (reservation) VirtualFree(reservation, 0, MEM_RELEASE);
    if (!base) {
        std::fprintf(stderr, "map failed (%u): %s\n", status, detail);
        return 3;
    }
    int code = 3;
    if (base != preferred && lifted_bind_image(reinterpret_cast<std::uintptr_t>(base)) == 0) {
        auto* slot = static_cast<const std::uint64_t*>(pe_map_export(base, "selector_result"));
        if (slot && *slot == UINT64_MAX) {
            code = translated_entry();
            if (*slot != expected_slot) code = 3;
        }
        lifted_unbind_image();
    }
    return pe_map_release(base) ? code : 3;
}
