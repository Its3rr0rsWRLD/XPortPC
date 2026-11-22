#include "era_title_gpu_api.h"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>

#include <cstdint>
#include <vector>

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void XMemFree(void* allocation, ULONGLONG attributes);

extern "C" __declspec(dllexport) int32_t ClientTitleGpuRoundTrip(void* d3d12_device, uint64_t* out_translated)
{
    if (!d3d12_device) {
        return 1;
    }

    // 1. Null device attach returns E_INVALIDARG
    if (X2WTitleGpuAttach(nullptr) != E_INVALIDARG) {
        return 2;
    }

    // 2. Attach valid WARP device
    if (FAILED(X2WTitleGpuAttach(d3d12_device))) {
        return 3;
    }

    // 3. Allocate graphics memory (AMD graphics attribute: 0xa8004000)
    constexpr uint64_t amd_attr = 0xa8004000ULL;
    void* alloc = XMemAlloc(512, amd_attr);
    if (!alloc) {
        X2WTitleGpuDetach();
        return 4;
    }
    const uint64_t title_addr = reinterpret_cast<uint64_t>(alloc);

    // 4. Translate title GPU address
    const uint64_t gpu_addr = X2WTitleGpuTranslate(title_addr, 512);
    if (gpu_addr == 0) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 5;
    }
    if (out_translated) {
        *out_translated = gpu_addr;
    }

    // 5. Locate checks
    void* res = nullptr;
    uint64_t offset = 0;

    // Interior offset +16
    int32_t hr = X2WTitleGpuLocate(title_addr + 16, 32, &res, &offset);
    if (FAILED(hr) || offset != 16 || !res) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 6;
    }
    static_cast<IUnknown*>(res)->Release();
    res = nullptr;

    // Out-of-range locate returns ERROR_NOT_FOUND
    hr = X2WTitleGpuLocate(title_addr + 4096, 16, &res, &offset);
    if (hr != HRESULT_FROM_WIN32(ERROR_NOT_FOUND)) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 7;
    }

    // Null pointers return E_POINTER
    hr = X2WTitleGpuLocate(title_addr, 16, nullptr, &offset);
    if (hr != E_POINTER) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 8;
    }
    hr = X2WTitleGpuLocate(title_addr, 16, &res, nullptr);
    if (hr != E_POINTER) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 9;
    }

    // 6. Two-call GetShaderView
    uint32_t required = 0;
    // Capacity 0 -> ERROR_INSUFFICIENT_BUFFER and sets *required
    hr = X2WTitleGpuGetShaderView(nullptr, nullptr, 0, &required);
    if (hr != HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER) || required == 0) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 10;
    }

    // Null arrays with capacity > 0 -> E_POINTER
    hr = X2WTitleGpuGetShaderView(nullptr, nullptr, required, &required);
    if (hr != E_POINTER) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 11;
    }

    // Sized buffer -> S_OK + range verification + Release() of each returned resource
    std::vector<X2WTitleGpuRange> ranges(required);
    std::vector<void*> resources(required);
    hr = X2WTitleGpuGetShaderView(ranges.data(), resources.data(), required, &required);
    if (FAILED(hr)) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 12;
    }
    bool found = false;
    for (uint32_t i = 0; i < required; ++i) {
        const uint64_t begin = (static_cast<uint64_t>(ranges[i].begin_high) << 32) | ranges[i].begin_low;
        if (begin == title_addr) {
            found = true;
        }
        if (resources[i]) {
            static_cast<IUnknown*>(resources[i])->Release();
        }
    }
    if (!found) {
        XMemFree(alloc, amd_attr);
        X2WTitleGpuDetach();
        return 13;
    }

    // 7. Free and verify translate returns 0
    XMemFree(alloc, amd_attr);
    if (X2WTitleGpuTranslate(title_addr, 512) != 0) {
        X2WTitleGpuDetach();
        return 14;
    }

    // 8. Idempotent double detach
    X2WTitleGpuDetach();
    X2WTitleGpuDetach();

    // 9. Reattach + reallocate round-trip
    if (FAILED(X2WTitleGpuAttach(d3d12_device))) {
        return 15;
    }
    void* alloc2 = XMemAlloc(1024, amd_attr);
    if (!alloc2) {
        X2WTitleGpuDetach();
        return 16;
    }
    const uint64_t title_addr2 = reinterpret_cast<uint64_t>(alloc2);
    const uint64_t gpu_addr2 = X2WTitleGpuTranslate(title_addr2, 1024);
    if (gpu_addr2 == 0) {
        XMemFree(alloc2, amd_attr);
        X2WTitleGpuDetach();
        return 17;
    }
    XMemFree(alloc2, amd_attr);
    X2WTitleGpuDetach();

    return 0;
}
