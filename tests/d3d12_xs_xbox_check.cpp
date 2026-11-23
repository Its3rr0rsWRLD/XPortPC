// Calls the console-named device exports of the desktop d3d12_xs.dll through named imports
// (src/d3d12_xs_xbox.cpp), and the shim's per-name stubs for exports it does not have.
//
// Neither D3D12XboxCreateDevice nor D3D12ConfigureVirtualMemoryX has a public declaration. The shim takes
// both as eight integer arguments (four registers, four stack slots), so they are declared that way here.
#include <d3d12.h>
#include <windows.h>

#include "d3d12_xs_api.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <string_view>
#include <vector>

using namespace std::literals;

extern "C" __declspec(dllimport) HRESULT WINAPI D3D12XboxCreateDevice(std::uintptr_t, std::uintptr_t, std::uintptr_t,
                                                                      std::uintptr_t, std::uintptr_t, std::uintptr_t,
                                                                      std::uintptr_t, std::uintptr_t);
extern "C" __declspec(dllimport) HRESULT WINAPI D3D12ConfigureVirtualMemoryX(std::uintptr_t, std::uintptr_t,
                                                                             std::uintptr_t, std::uintptr_t,
                                                                             std::uintptr_t, std::uintptr_t,
                                                                             std::uintptr_t, std::uintptr_t);

namespace {

struct Seen {
    std::uint32_t kind;
    std::string symbol;
    std::string detail;
};
std::vector<Seen> g_events;

void WINAPI sink(const X2WGfxEvent* event, void*)
{
    g_events.push_back({event->kind, event->symbol ? event->symbol : "", event->detail ? event->detail : ""});
    std::printf("[event %u] %s %s\n", event->kind, event->symbol ? event->symbol : "", event->detail ? event->detail : "");
}

bool saw(std::uint32_t kind, std::string_view symbol, std::string_view text)
{
    for (const Seen& e : g_events) {
        if (e.kind == kind && e.symbol == symbol && e.detail.find(text) != std::string::npos) return true;
    }
    return false;
}

template <typename T>
std::uintptr_t u(T* p)
{
    return reinterpret_cast<std::uintptr_t>(p);
}

// A stand-in for the creation-parameters struct a title passes: a pattern the hexdump line must show.
struct alignas(16) Params {
    unsigned char bytes[96];
    Params()
    {
        for (unsigned i = 0; i < sizeof(bytes); ++i) bytes[i] = static_cast<unsigned char>(0xa0 + (i & 15));
    }
};

// A queue and a fence on the device, a signal from the queue, and the fence reaching it.
bool device_works(ID3D12Device* device)
{
    if (!device) return false;
    D3D12_COMMAND_QUEUE_DESC desc{};
    desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ID3D12CommandQueue* queue = nullptr;
    ID3D12Fence* fence = nullptr;
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    bool ok = event && SUCCEEDED(device->CreateCommandQueue(&desc, IID_PPV_ARGS(&queue))) &&
              SUCCEEDED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence))) &&
              SUCCEEDED(queue->Signal(fence, 1)) && SUCCEEDED(fence->SetEventOnCompletion(1, event)) &&
              WaitForSingleObject(event, 10000) == WAIT_OBJECT_0 && fence->GetCompletedValue() == 1;
    if (fence) fence->Release();
    if (queue) queue->Release();
    if (event) CloseHandle(event);
    std::printf("device_works=%d\n", ok ? 1 : 0);
    return ok;
}

unsigned devices_created()
{
    X2WGfxCounters counters{};
    counters.size = sizeof(counters);
    return X2WGfxGetCounters(&counters) ? counters.devices_created : 0;
}

// One D3D12XboxCreateDevice call with the given arguments (the out slot is &device), checked end to end.
bool create_case(const char* name, const std::uintptr_t (&args)[8], const char* mapping)
{
    const unsigned before = devices_created();
    g_events.clear();
    const HRESULT hr = D3D12XboxCreateDevice(args[0], args[1], args[2], args[3], args[4], args[5], args[6], args[7]);
    std::printf("%s hr=0x%08lx\n", name, static_cast<unsigned long>(hr));
    const bool logged = saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", mapping) &&
                        saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", "caller=d3d12_xs_xbox_check.exe+0x") &&
                        saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice",
                            "points at 64 readable bytes: a0 a1 a2 a3 a4 a5 a6 a7 a8 a9 aa ab ac ad ae af a0");
    if (!logged) std::printf("%s: expected log lines missing (mapping \"%s\")\n", name, mapping);
    const bool counted = devices_created() == before + 1;
    if (!counted) std::printf("%s: device not counted as created by the shim\n", name);
    return SUCCEEDED(hr) && logged && counted;
}

bool create_checks(bool permuted)
{
    Params params;
    bool ok = true;
    if (!permuted) {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {0, u(&params), u(&IID_ID3D12Device), u(&device), 0, 0, 0, 0};
        ok = create_case("ordered", args, "contract iid=r8(ID3D12Device) out=r9(void**)") && device_works(device);
        if (device) device->Release();
        return ok;
    }
    {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {u(&IID_ID3D12Device), u(&device), u(&params), 0, 0, 0, 0, 0};
        ok = create_case("iid_first", args, "contract iid=rcx(ID3D12Device) out=rdx(void**)") && device_works(device) &&
             ok;
        if (device) device->Release();
    }
    {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {u(&params), u(&IID_ID3D12Device), u(&device), 0, 0, 0, 0, 0};
        ok = create_case("params_first", args, "contract iid=rdx(ID3D12Device) out=r8(void**)") &&
             device_works(device) && ok;
        if (device) device->Release();
    }
    {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {0, u(&params), 0, 0, u(&IID_ID3D12Device), u(&device), 0, 0};
        ok = create_case("stack_args", args, "contract iid=stack0(ID3D12Device) out=stack1(void**)") &&
             device_works(device) && ok;
        if (device) device->Release();
    }
    {
        // A later interface through its own IID: the device is handed out as that interface.
        ID3D12Device1* device = nullptr;
        const std::uintptr_t args[8] = {0, u(&params), u(&IID_ID3D12Device1), u(&device), 0, 0, 0, 0};
        ok = create_case("device1", args, "contract iid=r8(ID3D12Device1) out=r9(void**)") && device_works(device) &&
             ok;
        if (device) device->Release();
    }
    return ok;
}

bool unknown_iid_checks()
{
    Params params;
    // An IID no device implements (the command queue's), and a GUID that is no interface at all.
    const GUID made_up = {0x12345678, 0x9abc, 0xdef0, {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88}};
    bool ok = true;
    for (const GUID* iid : {&IID_ID3D12CommandQueue, &made_up}) {
        g_events.clear();
        void* sentinel = reinterpret_cast<void*>(0x5a5a5a5a);
        void* device = sentinel;
        const unsigned before = devices_created();
        const HRESULT hr = D3D12XboxCreateDevice(0, u(&params), u(iid), u(&device), 0, 0, 0, 0);
        std::printf("unknown_iid hr=0x%08lx\n", static_cast<unsigned long>(hr));
        ok = ok && hr == E_NOTIMPL && device == sentinel && devices_created() == before &&
             saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", "d3d12x-create-device unknown-contract") &&
             saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", "r8=0x");
    }
    // No IID pointer at all, only integers and the params block.
    g_events.clear();
    const HRESULT hr = D3D12XboxCreateDevice(1, 2, u(&params), 3, 4, 5, 6, 7);
    ok = ok && hr == E_NOTIMPL && saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", "unknown-contract");
    return ok;
}

bool configure_checks()
{
    Params params;
    g_events.clear();
    const HRESULT hr = D3D12ConfigureVirtualMemoryX(u(&params), 0x10000, 2, 0, 0, 0, 0, 0);
    std::printf("configure hr=0x%08lx\n", static_cast<unsigned long>(hr));
    const char* symbol = "d3d12_xs!D3D12ConfigureVirtualMemoryX";
    return hr == S_OK && saw(X2W_GFX_EVENT_NOTE, symbol, "caller=d3d12_xs_xbox_check.exe+0x") &&
           saw(X2W_GFX_EVENT_NOTE, symbol, "rdx=0x10000 r8=0x2") &&
           saw(X2W_GFX_EVENT_NOTE, symbol, "rcx=0x") && saw(X2W_GFX_EVENT_NOTE, symbol, ": a0 a1 a2 a3") &&
           saw(X2W_GFX_EVENT_NOTE, symbol, "-> S_OK");
}

using AnyCall = std::uintptr_t(WINAPI*)(std::uintptr_t, std::uintptr_t, std::uintptr_t, std::uintptr_t);

bool unknown_export_checks()
{
    void* a = X2WGfxUnknownExport("D3D12XboxSomethingNew");
    void* again = X2WGfxUnknownExport("D3D12XboxSomethingNew");
    void* b = X2WGfxUnknownExport("D3D12XboxOtherThing");
    // Names the shim exports get no stub: the loader uses the export.
    void* exported = X2WGfxUnknownExport("D3D12XboxCreateDevice");
    void* empty = X2WGfxUnknownExport("");
    std::printf("unknown_export a=%p again=%p b=%p exported=%p empty=%p\n", a, again, b, exported, empty);
    if (!a || a != again || !b || a == b || exported || empty) return false;

    g_events.clear();
    const auto call = reinterpret_cast<AnyCall>(a);
    const std::uintptr_t r1 = call(0x11, 0x22, 0x33, 0x44);
    const std::uintptr_t r2 = call(0x55, 0, 0, 0);
    const std::uintptr_t r3 = reinterpret_cast<AnyCall>(b)(0, 0, 0, 0);
    unsigned lines = 0;
    for (const Seen& e : g_events) lines += e.kind == X2W_GFX_EVENT_UNKNOWN_EXPORT;
    const bool ok = static_cast<HRESULT>(r1) == E_NOTIMPL && static_cast<HRESULT>(r2) == E_NOTIMPL &&
                    static_cast<HRESULT>(r3) == E_NOTIMPL && lines == 2 &&
                    saw(X2W_GFX_EVENT_UNKNOWN_EXPORT, "d3d12_xs!D3D12XboxSomethingNew",
                        "args=0x11,0x22,0x33,0x44 -> E_NOTIMPL") &&
                    saw(X2W_GFX_EVENT_UNKNOWN_EXPORT, "d3d12_xs!D3D12XboxSomethingNew",
                        "caller=d3d12_xs_xbox_check.exe+0x") &&
                    saw(X2W_GFX_EVENT_UNKNOWN_EXPORT, "d3d12_xs!D3D12XboxOtherThing", "-> E_NOTIMPL");
    std::printf("unknown_export lines=%u\n", lines);
    return ok;
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    X2WGfxSetLogSink(&sink, nullptr);
    const std::string_view scenario = argv[1];
    bool passed = false;
    if (scenario == "create_device"sv) {
        passed = create_checks(false);
    } else if (scenario == "create_device_permuted"sv) {
        passed = create_checks(true);
    } else if (scenario == "create_device_unknown_iid"sv) {
        passed = unknown_iid_checks();
    } else if (scenario == "configure_virtual_memory"sv) {
        passed = configure_checks();
    } else if (scenario == "unknown_export"sv) {
        passed = unknown_export_checks();
    } else {
        return 2;
    }
    X2WGfxSetLogSink(nullptr, nullptr);
    std::printf("Desktop d3d12_xs.dll xbox %s: %s\n", argv[1], passed ? "PASS" : "FAIL");
    return passed ? 0 : 1;
}
