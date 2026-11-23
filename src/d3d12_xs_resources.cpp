// The address model of buffers a title creates through the graphics shim (d3d12_xs_resources.h).
#include "d3d12_xs_resources.h"

#include "d3d12_xs_wrap.h"
#include "era_title_gpu_api.h"

#include <atomic>
#include <cstdio>

namespace d3d12_xs {
namespace resources {
namespace {

using RegisterFn = std::int32_t (*)(std::uint64_t, std::uint64_t, void*, std::uint32_t);
using UnregisterFn = std::int32_t (*)(std::uint64_t);
using TranslateFn = std::uint64_t (*)(std::uint64_t, std::uint64_t);
using TranslationsFn = std::int32_t (*)(X2WTitleGpuTranslation*, std::uint32_t, std::uint32_t*);

template <class Fn>
Fn xmem_export(const char* name)
{
    HMODULE xmem = GetModuleHandleW(L"xmem.dll");
    return xmem ? reinterpret_cast<Fn>(reinterpret_cast<void*>(GetProcAddress(xmem, name))) : nullptr;
}

D3D12_RESOURCE_DESC desc_of(ID3D12Resource* resource)
{
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_DESC desc{};
    resource->GetDesc(&desc);
    return desc;
#else
    return resource->GetDesc();
#endif
}

bool cpu_visible(const D3D12_HEAP_PROPERTIES* heap)
{
    if (!heap) return false;
    switch (static_cast<int>(heap->Type)) {
    case D3D12_HEAP_TYPE_UPLOAD:
    case D3D12_HEAP_TYPE_READBACK:
    case 5:  // D3D12_HEAP_TYPE_GPU_UPLOAD (newer headers)
        return true;
    case D3D12_HEAP_TYPE_CUSTOM:
        return heap->CPUPageProperty == D3D12_CPU_PAGE_PROPERTY_WRITE_COMBINE ||
               heap->CPUPageProperty == D3D12_CPU_PAGE_PROPERTY_WRITE_BACK;
    default:
        return false;
    }
}

constexpr std::uint64_t reservation_granularity = 64 * 1024;
constexpr std::uint64_t shader_range_limit = std::uint64_t(1) << 32;

}  // namespace

TitleAddress assign(ID3D12Resource* desktop, const D3D12_HEAP_PROPERTIES* heap, std::uint64_t existing_heap_address,
                    std::uint64_t offset)
{
    TitleAddress out;
    const D3D12_RESOURCE_DESC desc = desc_of(desktop);
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER || !desc.Width) return out;
    const D3D12_GPU_VIRTUAL_ADDRESS gpu = desktop->GetGPUVirtualAddress();
    out.bytes = desc.Width;
    const auto register_fn = xmem_export<RegisterFn>("X2WTitleGpuRegisterResource");
    if (!register_fn || !gpu) {
        out.title = gpu;
        static std::atomic<bool> noted;
        if (!register_fn && !noted.exchange(true)) {
            log_note("d3d12_xs!ID3D12Device::CreateCommittedResource",
                     "xmem.dll (X2WTitleGpuRegisterResource) not loaded; buffer GPU addresses are desktop addresses",
                     nullptr);
        }
        return out;
    }

    const bool readback = heap && heap->Type == D3D12_HEAP_TYPE_READBACK;
    std::uint32_t flags = 0;
    if (readback || desc.Width >= shader_range_limit) flags |= X2W_TITLE_GPU_REGISTER_NO_SHADER;

    if (existing_heap_address) {
        out.title = existing_heap_address + offset;
        const auto translate = xmem_export<TranslateFn>("X2WTitleGpuTranslate");
        if (translate && translate(out.title, desc.Width)) return out;  // already title memory xmem.dll aliases
    } else if (cpu_visible(heap)) {
        void* mapped = nullptr;
        const D3D12_RANGE nothing{0, 0};
        if (SUCCEEDED(desktop->Map(0, readback ? nullptr : &nothing, &mapped)) && mapped) {
            out.title = reinterpret_cast<std::uintptr_t>(mapped);
            out.mapped = true;
        }
    }
    if (!out.title) {
        const std::uint64_t bytes = (desc.Width + reservation_granularity - 1) & ~(reservation_granularity - 1);
        out.reservation = VirtualAlloc(nullptr, static_cast<SIZE_T>(bytes), MEM_RESERVE, PAGE_NOACCESS);
        if (!out.reservation) {
            out.title = gpu;
            log_note("d3d12_xs!ID3D12Device::CreateCommittedResource",
                     "cannot reserve a title address range; the buffer keeps its desktop GPU address", nullptr);
            return out;
        }
        out.title = reinterpret_cast<std::uintptr_t>(out.reservation);
    }
    const std::int32_t hr = register_fn(out.title, desc.Width, desktop, flags);
    out.registered = hr >= 0;
    if (!out.registered) {
        char detail[160];
        std::snprintf(detail, sizeof(detail),
                      "X2WTitleGpuRegisterResource(0x%llx, %llu) -> 0x%08lx; the buffer keeps its desktop GPU address",
                      static_cast<unsigned long long>(out.title), static_cast<unsigned long long>(desc.Width),
                      static_cast<unsigned long>(hr));
        log_note("d3d12_xs!ID3D12Device::CreateCommittedResource", detail, nullptr);
        if (out.reservation) VirtualFree(out.reservation, 0, MEM_RELEASE);
        if (out.mapped) desktop->Unmap(0, nullptr);
        out.reservation = nullptr;
        out.mapped = false;
        out.title = gpu;
    }
    return out;
}

void release(ID3D12Resource* desktop, TitleAddress& address)
{
    if (address.registered) {
        if (const auto unregister_fn = xmem_export<UnregisterFn>("X2WTitleGpuUnregisterResource"))
            unregister_fn(address.title);
    }
    if (address.mapped && desktop) {
        const D3D12_RANGE nothing{0, 0};
        desktop->Unmap(0, &nothing);
    }
    if (address.reservation) VirtualFree(address.reservation, 0, MEM_RELEASE);
    address = {};
}

bool translations(std::vector<Translation>& out)
{
    out.clear();
    const auto get = xmem_export<TranslationsFn>("X2WTitleGpuGetTranslations");
    if (!get) return true;
    std::uint32_t required = 0;
    std::int32_t hr = get(nullptr, 0, &required);
    if (!required) return hr >= 0 || hr == static_cast<std::int32_t>(HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER));
    std::vector<X2WTitleGpuTranslation> ranges;
    try {
        ranges.resize(required);
        hr = get(ranges.data(), required, &required);
        if (hr < 0) return false;
        ranges.resize(required);
        out.reserve(ranges.size());
    } catch (...) {
        return false;
    }
    for (const X2WTitleGpuTranslation& r : ranges) {
        Translation t{};
        t.title_begin[0] = static_cast<std::uint32_t>(r.title_begin);
        t.title_begin[1] = static_cast<std::uint32_t>(r.title_begin >> 32);
        t.title_end[0] = static_cast<std::uint32_t>(r.title_end);
        t.title_end[1] = static_cast<std::uint32_t>(r.title_end >> 32);
        t.gpu_begin[0] = static_cast<std::uint32_t>(r.gpu_begin);
        t.gpu_begin[1] = static_cast<std::uint32_t>(r.gpu_begin >> 32);
        out.push_back(t);
    }
    return true;
}

}  // namespace resources
}  // namespace d3d12_xs
