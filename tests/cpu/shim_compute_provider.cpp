// Test-only import observer. Each process owns one compute allocation.
// The observer publishes the raw pointer so the verifier can check identity
// across dispatch and release without expecting equal virtual addresses across processes.
#include <windows.h>
#include <cstdint>
#include <cstring>

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T, ULONGLONG);
extern "C" __declspec(dllimport) void XMemFree(void*, ULONGLONG);
bool shim_compute_gpu(unsigned seed, unsigned* output, unsigned words);

namespace {
void* live;
SIZE_T capacity;
ULONGLONG allocated_attributes;

bool publish(const void* data, DWORD size)
{
    DWORD written = 0;
    return WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), data, size, &written, nullptr) && written == size;
}

void event(std::uint64_t kind, std::uint64_t a, std::uint64_t b, std::uint64_t c)
{
    const std::uint64_t record[]{kind, a, b, c};
    if (!publish(record, sizeof(record))) ExitProcess(20);
}
}

extern "C" __declspec(dllexport) SIZE_T compute_request()
{
    char mode[16]{};
    const DWORD len = GetEnvironmentVariableA("X2W_SHIM_COMPUTE_CASE", mode, sizeof(mode));
    if (!len) return 0;
    if (len < sizeof(mode)) {
        if (!std::strcmp(mode, "small")) return 4096;
        if (!std::strcmp(mode, "large")) return 8192;
        if (!std::strcmp(mode, "fail")) return SIZE_MAX;
    }
    ExitProcess(21);
}

extern "C" __declspec(dllexport) void* compute_alloc(SIZE_T bytes, ULONGLONG attributes)
{
    if (live) ExitProcess(22);
    live = XMemAlloc(bytes, attributes);
    capacity = bytes;
    allocated_attributes = attributes;
    event(1, bytes, attributes, reinterpret_cast<UINT_PTR>(live));
    return live;
}

extern "C" __declspec(dllexport) DWORD compute_dispatch(void* ptr, unsigned seed, unsigned words)
{
    event(2, reinterpret_cast<UINT_PTR>(ptr), seed, words);
    if (!ptr || ptr != live || words != 4 || capacity < words * sizeof(unsigned)) return 0;
    if (!shim_compute_gpu(seed, static_cast<unsigned*>(ptr), words)) return 0;
    return publish(ptr, words * sizeof(unsigned));
}

extern "C" __declspec(dllexport) DWORD compute_free(void* ptr, ULONGLONG attributes)
{
    const bool matches = ptr && ptr == live && attributes == allocated_attributes;
    MEMORY_BASIC_INFORMATION info{};
    bool released = false;
    if (matches) {
        XMemFree(ptr, attributes);
        live = nullptr;
        released = VirtualQuery(ptr, &info, sizeof(info)) && info.State == MEM_FREE;
    }
    event(3, reinterpret_cast<UINT_PTR>(ptr), attributes, released);
    return released;
}
