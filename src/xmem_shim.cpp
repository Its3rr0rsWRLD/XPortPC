// Desktop xmem.dll exporting the four functions the package DLLs import by name.
// Call shapes come from the observed call sites, not from a published header:
//   XMemAlloc(size, attributes) and XMemFree(allocation, attributes): Bink and AMD callers.
//   XMemVirtualQuery(process, address, buffer): the four BVH callers pass no length, supply a
//     zeroed 64-byte buffer and test the 32-bit result.
//   XMemGetWorkingSetStatistics(selector, output): the seven AMD callers test the 32-bit
//     result and use zero when it fails.
// Graphics allocations go through era_title_gpu, which registers them with era_query and, once a
// D3D12 device is attached to the registry, gives them desktop GPU addresses. The exports are
// unchanged; nothing here loads D3D12.
#include "era_heap.h"
#include "era_query.h"
#include "era_title_gpu.h"
#include "era_title_gpu_api.h"

#include <cstdint>
#include <limits>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace {
// The BVH callers' query buffer. era_query writes at most its first 0x31 bytes.
constexpr std::size_t query_buffer_bytes = 64;

bool is_graphics(std::uint64_t attributes) noexcept
{
    const auto type = era_heap::decode(attributes).memory_type;
    return type >= 1 && type <= 6;
}
}

extern "C" void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes)
{
    void* allocation = era_heap::allocate(bytes, attributes);
    // Desktop policy: graphics memory types count as GPU-intended for XMemVirtualQuery.
    if (allocation && is_graphics(attributes) && !era_title_gpu::track(allocation, bytes)) {
        era_heap::release_with_attributes(allocation, attributes);
        return nullptr;
    }
    return allocation;
}

extern "C" void XMemFree(void* allocation, ULONGLONG attributes)
{
    if (allocation && is_graphics(attributes)) {
        era_title_gpu::untrack(allocation);
    }
    era_heap::release_with_attributes(allocation, attributes);
}

extern "C" BOOL XMemVirtualQuery(HANDLE process, LPCVOID address, void* buffer)
{
    return era_query::query(process, address, buffer, query_buffer_bytes) != 0;
}

// No public reference defines the selector or the output units, so report the call as
// unsupported. Every observed caller treats a failed call as contributing zero.
extern "C" BOOL XMemGetWorkingSetStatistics(UINT32 selector, void* statistics)
{
    UNREFERENCED_PARAMETER(selector);
    UNREFERENCED_PARAMETER(statistics);
    SetLastError(ERROR_NOT_SUPPORTED);
    return FALSE;
}

extern "C" int32_t X2WTitleGpuAttach(void* device)
{
    return static_cast<int32_t>(era_title_gpu::attach(static_cast<ID3D12Device*>(device)));
}

extern "C" void X2WTitleGpuDetach(void)
{
    era_title_gpu::detach();
}

extern "C" uint64_t X2WTitleGpuTranslate(uint64_t title_address, uint64_t bytes)
{
    return era_title_gpu::translate(title_address, bytes);
}

extern "C" int32_t X2WTitleGpuLocate(uint64_t title_address, uint64_t bytes, void** resource, uint64_t* offset)
{
    if (!resource || !offset) {
        return E_POINTER;
    }
    ID3D12Resource* buffer = nullptr;
    if (!era_title_gpu::locate(title_address, bytes, &buffer, offset)) {
        return HRESULT_FROM_WIN32(ERROR_NOT_FOUND);
    }
    *resource = buffer;
    return S_OK;
}

extern "C" int32_t X2WTitleGpuGetShaderView(X2WTitleGpuRange* ranges, void** resources, uint32_t capacity, uint32_t* required)
{
    if (!required) {
        return E_POINTER;
    }
    era_title_gpu::ShaderView view;
    if (!era_title_gpu::shader_view(view)) {
        return E_FAIL;
    }
    if (view.ranges.size() > static_cast<std::size_t>(std::numeric_limits<uint32_t>::max())) {
        return E_FAIL;
    }
    const uint32_t count = static_cast<uint32_t>(view.ranges.size());
    *required = count;
    if (capacity < count) {
        return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
    }
    if (count > 0 && (!ranges || !resources)) {
        return E_POINTER;
    }
    for (uint32_t i = 0; i < count; ++i) {
        ranges[i].begin_low = view.ranges[i].begin_low;
        ranges[i].begin_high = view.ranges[i].begin_high;
        ranges[i].end_low = view.ranges[i].end_low;
        ranges[i].end_high = view.ranges[i].end_high;
        ranges[i].slot = view.ranges[i].slot;
        ranges[i].reserved = view.ranges[i].reserved;

        ID3D12Resource* const res = view.resources[i].Get();
        if (res) {
            res->AddRef();
        }
        resources[i] = res;
    }
    return S_OK;
}
