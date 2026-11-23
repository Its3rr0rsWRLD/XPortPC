// Desktop xmem.dll. XMemAlloc, XMemFree and the rest of the XMem allocation surface are the title memory
// layer (src/xmem_title.cpp, src/xmem_title_api.h); this file holds the two query functions and the title GPU
// registry exports. Call shapes of the four functions the package DLLs import by name come from the observed call
// sites, not from a published header:
//   XMemAlloc(size, attributes) and XMemFree(allocation, attributes): Bink and AMD callers.
//   XMemVirtualQuery(process, address, buffer): the four BVH callers pass no length, supply a
//     zeroed 64-byte buffer and test the 32-bit result.
//   XMemGetWorkingSetStatistics(selector, output): the seven AMD callers pass 0x20000001 and
//     read the 64-bit value at +8 (zero on failure).
// GPU-visible allocations go through era_title_gpu, which registers them with era_query and, once a
// D3D12 device is attached to the registry, gives them desktop GPU addresses. Nothing here loads
// D3D12. DXGI and gdi32 are delay-loaded.
#include "era_query.h"
#include "era_title_gpu.h"
#include "era_title_gpu_api.h"
#include "xmem_gpu_usage.h"
#include "xmem_title.h"

#include <cstdint>
#include <cstring>
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

// The selector the AMD callers pass, and the offset of the value they read.
constexpr UINT32 gpu_usage_selector = 0x20000001;
constexpr std::size_t gpu_usage_offset = 8;
}

extern "C" BOOL XMemVirtualQuery(HANDLE process, LPCVOID address, void* buffer)
{
    if (era_query::query(process, address, buffer, query_buffer_bytes) == 0) {
        return FALSE;
    }
    // Inside an xmem arena, each allocation reads as its own allocation and unallocated arena space as free, as
    // when every allocation had its own VirtualAlloc region (src/xmem_title.h).
    MEMORY_BASIC_INFORMATION info{};
    if ((process == GetCurrentProcess() || GetProcessId(process) == GetCurrentProcessId()) &&
        xmem_title::query_overlay(address, info)) {
        std::memcpy(buffer, &info, sizeof(info));
    }
    return TRUE;
}

// Desktop policy (docs/experiments.md): writes only +8, with this process's GPU memory in bytes;
// on failure the output is untouched and the callers use zero.
extern "C" BOOL XMemGetWorkingSetStatistics(UINT32 selector, void* statistics)
{
    if (!statistics) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    const auto bytes = selector == gpu_usage_selector ? xmem_gpu_usage::process_bytes() : std::nullopt;
    if (!bytes) {
        SetLastError(ERROR_NOT_SUPPORTED);
        return FALSE;
    }
    std::memcpy(static_cast<unsigned char*>(statistics) + gpu_usage_offset, &*bytes, sizeof(*bytes));
    return TRUE;
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
        ranges[i].base = view.ranges[i].base;

        // The buffer of the range's slot; ranges of one arena or pool share it.
        ID3D12Resource* const res = view.ranges[i].slot < view.resources.size() ? view.resources[view.ranges[i].slot].Get()
                                                                                  : nullptr;
        if (res) {
            res->AddRef();
        }
        resources[i] = res;
    }
    return S_OK;
}

extern "C" int32_t X2WTitleGpuRegisterResource(uint64_t title_address, uint64_t bytes, void* resource, uint32_t flags)
{
    if (!resource) {
        return E_POINTER;
    }
    const bool shader = (flags & X2W_TITLE_GPU_REGISTER_NO_SHADER) == 0;
    return era_title_gpu::register_resource(title_address, bytes, static_cast<ID3D12Resource*>(resource), shader)
               ? S_OK
               : E_INVALIDARG;
}

extern "C" int32_t X2WTitleGpuUnregisterResource(uint64_t title_address)
{
    return era_title_gpu::unregister_resource(title_address) ? S_OK : HRESULT_FROM_WIN32(ERROR_NOT_FOUND);
}

extern "C" int32_t X2WTitleGpuGetTranslations(X2WTitleGpuTranslation* out, uint32_t capacity, uint32_t* required)
{
    if (!required) {
        return E_POINTER;
    }
    std::vector<era_title_va::Range> ranges;
    if (!era_title_gpu::translations(ranges) || ranges.size() > std::numeric_limits<uint32_t>::max()) {
        return E_FAIL;
    }
    const uint32_t count = static_cast<uint32_t>(ranges.size());
    *required = count;
    if (capacity < count) {
        return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
    }
    if (count > 0 && !out) {
        return E_POINTER;
    }
    for (uint32_t i = 0; i < count; ++i) {
        out[i].title_begin = ranges[i].title_begin;
        out[i].title_end = ranges[i].title_end;
        out[i].gpu_begin = ranges[i].gpu_begin;
    }
    return S_OK;
}
