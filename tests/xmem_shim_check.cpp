// Calls the desktop xmem.dll through named imports, as the package DLLs do.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string_view>

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void XMemFree(void* allocation, ULONGLONG attributes);
extern "C" __declspec(dllimport) BOOL XMemVirtualQuery(HANDLE process, LPCVOID address, void* buffer);
extern "C" __declspec(dllimport) BOOL XMemGetWorkingSetStatistics(UINT32 selector, void* statistics);

using namespace std::literals;
using Byte = unsigned char;

namespace {
// Attribute words and selector recorded at the Bink, AMD and BVH call sites.
constexpr ULONGLONG bink_word = 0x05e50000;
constexpr ULONGLONG amd_word = 0xa8004000;
constexpr UINT32 amd_selector = 0x20000001;

struct QueryBuffer {
    MEMORY_BASIC_INFORMATION info;
    std::array<Byte, 16> tail;
};
static_assert(offsetof(QueryBuffer, tail) == 0x30 && sizeof(QueryBuffer) == 64);

// The BVH callers' post-query predicates, as modeled in memory_query_check.cpp, applied to the
// 32-bit result they test.
bool caller_accepts(const QueryBuffer& buffer, BOOL returned, bool source)
{
    return returned && (buffer.tail[0] & 3) && (buffer.info.State & 0x1000) &&
           (!source || (buffer.info.Protect & 6));
}

BOOL ask(const void* address, QueryBuffer& buffer, HANDLE process = GetCurrentProcess())
{
    buffer = {};
    std::fill(buffer.tail.begin() + 1, buffer.tail.end(), Byte{0xa5});
    return XMemVirtualQuery(process, address, &buffer);
}

bool export_checks()
{
    HMODULE module = GetModuleHandleW(L"xmem.dll");
    if (!module) return false;
    unsigned found = 0;
    for (const char* name : {"XMemAlloc", "XMemFree", "XMemVirtualQuery", "XMemGetWorkingSetStatistics"}) {
        if (!GetProcAddress(module, name)) return false;
        ++found;
    }
    // The named imports in this executable resolve to the same module.
    HMODULE owner = nullptr;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            reinterpret_cast<LPCWSTR>(GetProcAddress(module, "XMemAlloc")), &owner) ||
        owner != module) return false;
    // Routing graphics memory through era_title_gpu must not make xmem.dll load D3D12.
    if (GetModuleHandleW(L"d3d12.dll")) return false;
    std::printf("exports=%u\n", found);
    return true;
}

bool allocation_checks()
{
    // Bink: heap memory, 32-byte alignment, zero-filled.
    auto* heap = static_cast<Byte*>(XMemAlloc(97, bink_word));
    if (!heap || reinterpret_cast<std::uintptr_t>(heap) % 32 ||
        !std::all_of(heap, heap + 97, [](Byte b) { return b == 0; })) return false;
    std::fill_n(heap, 97, Byte{0x51});
    XMemFree(heap, bink_word);

    // AMD: graphics memory, committed read/write on the allocation granularity, freed by XMemFree.
    auto* gpu = static_cast<Byte*>(XMemAlloc(512, amd_word));
    MEMORY_BASIC_INFORMATION info{};
    if (!gpu || VirtualQuery(gpu, &info, sizeof(info)) != sizeof(info) || info.State != MEM_COMMIT ||
        info.Protect != PAGE_READWRITE || reinterpret_cast<std::uintptr_t>(gpu) % (std::size_t{64} << 10) ||
        !std::all_of(gpu, gpu + 512, [](Byte b) { return b == 0; })) return false;
    std::fill_n(gpu, 512, Byte{0x51});
    XMemFree(gpu, amd_word);
    if (VirtualQuery(gpu, &info, sizeof(info)) != sizeof(info) || info.State != MEM_FREE) return false;

    // Rejections pass straight through, and freeing null is a no-op for both types.
    XMemFree(nullptr, bink_word);
    XMemFree(nullptr, amd_word);
    return XMemAlloc(0, bink_word) == nullptr && XMemAlloc(64, bink_word | (ULONGLONG{1} << 40)) == nullptr &&
           XMemAlloc(512, (amd_word & ~(ULONGLONG{15} << 29)) | (ULONGLONG{7} << 29)) == nullptr;
}

bool query_checks()
{
    QueryBuffer buffer;
    // Graphics memory from XMemAlloc is registered, so both caller predicates accept it.
    auto* gpu = XMemAlloc(4096, amd_word);
    if (!gpu) return false;
    BOOL ok = ask(gpu, buffer);
    if (!ok || buffer.tail[0] != 1 || !caller_accepts(buffer, ok, false) || !caller_accepts(buffer, ok, true) ||
        !std::all_of(buffer.tail.begin() + 1, buffer.tail.end(), [](Byte b) { return b == 0xa5; })) return false;
    // A real handle to this process behaves like the pseudo-handle.
    HANDLE self = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, GetCurrentProcessId());
    if (!self) return false;
    ok = ask(static_cast<Byte*>(gpu) + 100, buffer, self);
    CloseHandle(self);
    if (!ok || buffer.tail[0] != 1) return false;
    // After XMemFree the region is gone and no longer registered.
    XMemFree(gpu, amd_word);
    ok = ask(gpu, buffer);
    if (!ok || buffer.info.State != MEM_FREE || buffer.tail[0] != 0 || caller_accepts(buffer, ok, false)) return false;
    // A freshly reused address must not inherit the old registration.
    auto* again = XMemAlloc(4096, amd_word);
    if (!again) return false;
    XMemFree(again, amd_word);

    // Heap memory is not GPU-intended under the desktop policy: the tail check fails.
    auto* heap = XMemAlloc(257, bink_word);
    if (!heap) return false;
    ok = ask(heap, buffer);
    const bool heap_rejected = ok && buffer.info.State == MEM_COMMIT && buffer.tail[0] == 0 &&
                               !caller_accepts(buffer, ok, false);
    XMemFree(heap, bink_word);
    if (!heap_rejected) return false;

    // An address outside user space fails without touching the buffer.
    buffer = {};
    buffer.tail.fill(0xd7);
    const BOOL outside = XMemVirtualQuery(GetCurrentProcess(), reinterpret_cast<LPCVOID>(0xffff800000000000ull), &buffer);
    if (outside || buffer.info.State != 0 ||
        !std::all_of(buffer.tail.begin(), buffer.tail.end(), [](Byte b) { return b == 0xd7; })) return false;
    SetLastError(ERROR_SUCCESS);
    const BOOL null_output = XMemVirtualQuery(GetCurrentProcess(), &buffer, nullptr);
    const DWORD null_error = GetLastError();
    std::printf("query_cases=7 null_output_error=%lu\n", null_error);
    return !null_output && null_error == ERROR_NOACCESS;
}

bool working_set_checks()
{
    std::array<std::uint64_t, 4> statistics;
    statistics.fill(0x5a5a5a5a5a5a5a5aull);
    SetLastError(ERROR_SUCCESS);
    const BOOL ok = XMemGetWorkingSetStatistics(amd_selector, statistics.data());
    const DWORD error = GetLastError();
    // The AMD callers use the 64-bit value at +8 on success and zero otherwise.
    const std::uint64_t used = ok ? statistics[1] : 0;
    const bool untouched = std::all_of(statistics.begin(), statistics.end(),
                                       [](std::uint64_t v) { return v == 0x5a5a5a5a5a5a5a5aull; });
    std::printf("working_set_result=%d last_error=%lu caller_value=%llu\n", ok, error,
                static_cast<unsigned long long>(used));
    return !ok && error == ERROR_NOT_SUPPORTED && used == 0 && untouched;
}
}

int main(int argc, char** argv)
{
    if (argc != 2) {
        return 2;
    }
    const std::string_view scenario = argv[1];
    bool passed;
    if (scenario == "exports"sv) {
        passed = export_checks();
    } else if (scenario == "allocation"sv) {
        passed = allocation_checks();
    } else if (scenario == "query"sv) {
        passed = query_checks();
    } else if (scenario == "working_set"sv) {
        passed = working_set_checks();
    } else {
        return 2;
    }
    std::printf("Desktop xmem.dll %s: %s\n", argv[1], passed ? "PASS" : "FAIL");
    return passed ? 0 : 1;
}
