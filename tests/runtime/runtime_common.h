#pragma once

// Device, queue, list, fence, window and debug-layer helpers shared by the runtime ladder programs
// (tests/runtime/r2_clear.cpp, r3_triangle.cpp). Everything goes through the graphics shim: D3D12CreateDevice
// and D3D12GetDebugInterface are d3d12_xs.dll's exports. DXGI is used only to pick the adapter.
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include "d3d12_xs_api.h"

#include <cstdint>
#include <cstdio>
#include <vector>

namespace runtime_test {

using Microsoft::WRL::ComPtr;

bool ok(HRESULT hr, const char* what)
{
    if (SUCCEEDED(hr)) return true;
    std::fprintf(stderr, "runtime: %s failed: 0x%08lx\n", what, static_cast<unsigned long>(hr));
    return false;
}

ComPtr<IDXGIAdapter1> pick_adapter(bool warp)
{
    ComPtr<IDXGIFactory6> factory;
    if (!ok(CreateDXGIFactory2(0, IID_PPV_ARGS(&factory)), "CreateDXGIFactory2")) return {};
    ComPtr<IDXGIAdapter1> adapter;
    if (warp) {
        ok(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)), "EnumWarpAdapter");
        return adapter;
    }
    for (UINT i = 0; factory->EnumAdapterByGpuPreference(i, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE,
                                                         IID_PPV_ARGS(adapter.ReleaseAndGetAddressOf())) != DXGI_ERROR_NOT_FOUND;
         ++i) {
        DXGI_ADAPTER_DESC1 desc{};
        if (FAILED(adapter->GetDesc1(&desc)) || (desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)) continue;
        // Support check through the shim: a null output is forwarded to desktop D3D12.
        if (SUCCEEDED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, __uuidof(ID3D12Device), nullptr)))
            return adapter;
    }
    return {};
}

X2WGfxCounters counters()
{
    X2WGfxCounters c{};
    c.size = sizeof(c);
    X2WGfxGetCounters(&c);
    return c;
}

struct Gpu {
    ComPtr<ID3D12InfoQueue> messages;
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    HANDLE event = nullptr;
    UINT64 fence_value = 0;

    ~Gpu()
    {
        if (event) CloseHandle(event);
    }

    // Returns 77 when no hardware adapter is visible, 1 on failure, 0 when created.
    int create(bool warp)
    {
        ComPtr<ID3D12Debug> debug;
        if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
        std::printf("debug_layer=%s\n", debug ? "enabled" : "unavailable");
        auto adapter = pick_adapter(warp);
        if (!adapter) {
            if (warp) return 1;
            std::puts("No D3D12-capable hardware adapter visible");
            return 77;
        }
        DXGI_ADAPTER_DESC1 desc{};
        adapter->GetDesc1(&desc);
        std::printf("adapter=%ls vendor=%04x device=%04x\n", desc.Description, desc.VendorId, desc.DeviceId);
        if (!ok(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "D3D12CreateDevice"))
            return 1;
        if (debug && !ok(device.As(&messages), "QueryInterface(ID3D12InfoQueue)")) return 1;
        D3D12_COMMAND_QUEUE_DESC queue_desc{};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (!ok(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)), "CreateCommandQueue") ||
            !ok(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)),
                "CreateCommandAllocator") ||
            !ok(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                          IID_PPV_ARGS(&list)),
                "CreateCommandList") ||
            !ok(list->Close(), "Close") ||
            !ok(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence")) {
            return 1;
        }
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        return event ? 0 : 1;
    }

    bool submit_and_wait()
    {
        ID3D12CommandList* lists[] = {list.Get()};
        queue->ExecuteCommandLists(1, lists);
        ++fence_value;
        if (!ok(queue->Signal(fence.Get(), fence_value), "Signal")) return false;
        if (fence->GetCompletedValue() < fence_value) {
            if (!ok(fence->SetEventOnCompletion(fence_value, event), "SetEventOnCompletion")) return false;
            if (WaitForSingleObject(event, 10000) != WAIT_OBJECT_0) {
                std::fputs("runtime: fence wait timed out\n", stderr);
                return false;
            }
        }
        return fence->GetCompletedValue() >= fence_value && ok(device->GetDeviceRemovedReason(), "device");
    }

    // Debug-layer errors (and corruption) since the last call; warnings are printed, not counted.
    unsigned debug_errors()
    {
        if (!messages) return 0;
        unsigned errors = 0;
        const UINT64 count = messages->GetNumStoredMessagesAllowedByRetrievalFilter();
        for (UINT64 i = 0; i < count; ++i) {
            SIZE_T bytes = 0;
            if (FAILED(messages->GetMessage(i, nullptr, &bytes))) continue;
            std::vector<std::uint8_t> storage(bytes);
            auto* msg = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
            if (FAILED(messages->GetMessage(i, msg, &bytes))) continue;
            if (msg->Severity <= D3D12_MESSAGE_SEVERITY_WARNING) {
                std::fprintf(stderr, "D3D12 %d: %s\n", msg->ID, msg->pDescription);
                if (msg->Severity < D3D12_MESSAGE_SEVERITY_WARNING) ++errors;
            }
        }
        messages->ClearStoredMessages();
        return errors;
    }
};

D3D12_RESOURCE_BARRIER transition(ID3D12Resource* resource, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
{
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = resource;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = before;
    barrier.Transition.StateAfter = after;
    return barrier;
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM w, LPARAM l)
{
    return DefWindowProcW(window, message, w, l);
}

HWND make_window(UINT width, UINT height)
{
    WNDCLASSW wc{};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"x2w_runtime_test";
    RegisterClassW(&wc);
    RECT rect{0, 0, static_cast<LONG>(width), static_cast<LONG>(height)};
    AdjustWindowRect(&rect, WS_OVERLAPPEDWINDOW, FALSE);
    HWND window = CreateWindowExW(0, wc.lpszClassName, L"XPortPC runtime test", WS_OVERLAPPEDWINDOW, 0, 0,
                                  rect.right - rect.left, rect.bottom - rect.top, nullptr, nullptr, wc.hInstance,
                                  nullptr);
    if (window) ShowWindow(window, SW_SHOWNOACTIVATE);
    return window;
}

}  // namespace runtime_test
