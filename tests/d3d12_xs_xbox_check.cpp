// Calls the console-named device exports of the desktop d3d12_xs.dll through named imports
// (src/d3d12_xs_xbox.cpp), and the shim's per-name stubs for exports it does not have.
//
// Neither D3D12XboxCreateDevice nor D3D12ConfigureVirtualMemoryX has a public declaration. The shim takes
// both as eight integer arguments (four registers, four stack slots), so they are declared that way here.
#include <d3d12.h>
#include <dxgi1_4.h>
#include <windows.h>

#include "d3d12_xs_api.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <string>
#include <utility>
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
    unsigned char bytes[128];
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
                            "as dwords (128 bytes): a3a2a1a0 a7a6a5a4 abaaa9a8 afaeadac a3a2a1a0");
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
    const HRESULT hr = D3D12ConfigureVirtualMemoryX(u(&params), 0x10000, 2, 0, 0, 0, 0x400000000ull, 0);
    std::printf("configure hr=0x%08lx\n", static_cast<unsigned long>(hr));
    const char* symbol = "d3d12_xs!D3D12ConfigureVirtualMemoryX";
    return hr == S_OK && saw(X2W_GFX_EVENT_NOTE, symbol, "caller=d3d12_xs_xbox_check.exe+0x") &&
           saw(X2W_GFX_EVENT_NOTE, symbol, "rdx=0x10000 r8=0x2") &&
           saw(X2W_GFX_EVENT_NOTE, symbol, "rcx=0x") && saw(X2W_GFX_EVENT_NOTE, symbol, ": a0 a1 a2 a3") &&
           saw(X2W_GFX_EVENT_NOTE, symbol, "as dwords (64 bytes): a3a2a1a0 a7a6a5a4") &&
           saw(X2W_GFX_EVENT_NOTE, symbol, "stack2=0x400000000 = 16384 MiB") &&
           !saw(X2W_GFX_EVENT_NOTE, symbol, "stack3=0x0 =") &&  // control: only stack2 is read as a size
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


// The three argument orders a title may use (D3D12CreateDevice-like, params first, IID first), each with a known IID
// and with an IID the shim does not know (a console-only device IID: the assumed contracts), and a params struct that
// holds the IID pointer and the out pointer itself.
bool order_checks()
{
    Params params;
    bool ok = true;
    {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {0, u(&params), u(&IID_ID3D12Device), u(&device), 0, 0, 0, 0};
        ok = create_case("adapter_params_iid_out", args, "contract iid=r8(ID3D12Device) out=r9(void**)") &&
             device_works(device) && ok;
        if (device) device->Release();
    }
    {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {u(&params), u(&IID_ID3D12Device), u(&device), 0, 0, 0, 0, 0};
        ok = create_case("params_iid_out", args, "contract iid=rdx(ID3D12Device) out=r8(void**)") &&
             device_works(device) && ok;
        if (device) device->Release();
    }
    {
        // rdx (the params struct) is writable too; the out slot is the one holding null.
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {u(&IID_ID3D12Device), u(&params), u(&device), 0, 0, 0, 0, 0};
        ok = create_case("iid_params_out", args, "contract iid=rcx(ID3D12Device) out=r8(void**)") &&
             device_works(device) && ok;
        if (device) device->Release();
        Params fresh;
        ok = ok && std::memcmp(&params, &fresh, sizeof(params)) == 0;  // nothing written into the params struct
    }
    // A console-only IID: handed out as the device wrapper, and the device answers QueryInterface for it after.
    static const GUID console_iid = {0x7a1e0001, 0x2b3c, 0x4d5e, {0x8f, 0x90, 0xa1, 0xb2, 0xc3, 0xd4, 0xe5, 0xf6}};
    {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {u(&params), u(&console_iid), u(&device), 0, 0, 0, 0, 0};
        ok = create_case("assumed_params_iid_out", args,
                         "contract iid=rdx(unknown) out=r8(void**) assumed (params*, REFIID, void**)") &&
             saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", "iid_value={7a1e0001-2b3c-4d5e-8f90-a1b2c3d4e5f6}") &&
             device_works(device) && ok;
        void* again = nullptr;
        const bool qi = device && SUCCEEDED(device->QueryInterface(console_iid, &again)) && again == device;
        std::printf("assumed qi=%d\n", qi ? 1 : 0);
        ok = ok && qi;
        if (again) static_cast<IUnknown*>(again)->Release();
        if (device) device->Release();
    }
    {
        ID3D12Device* device = nullptr;
        const std::uintptr_t args[8] = {u(&console_iid), u(&params), u(&device), 0, 0, 0, 0, 0};
        ok = create_case("assumed_iid_params_out", args,
                         "contract iid=rcx(unknown) out=r8(void**) assumed (REFIID, params*, void**)") &&
             device_works(device) && ok;
        if (device) device->Release();
    }
    {
        // A creation-parameters struct carrying the IID pointer at +0x10 and the out pointer at +0x18.
        ID3D12Device* device = nullptr;
        struct alignas(16) Create {
            std::uint32_t version = 1, flags = 0;
            std::uint64_t reserved = 0;
            const IID* iid = &IID_ID3D12Device;
            void** out = nullptr;
            std::uint64_t tail[12] = {};
        } create;
        create.out = reinterpret_cast<void**>(&device);
        const unsigned before = devices_created();
        g_events.clear();
        const HRESULT hr = D3D12XboxCreateDevice(u(&create), 0, 0, 0, 0, 0, 0, 0);
        std::printf("struct_fields hr=0x%08lx\n", static_cast<unsigned long>(hr));
        ok = SUCCEEDED(hr) && devices_created() == before + 1 &&
             saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice",
                 "contract iid=rcx->[+0x10](ID3D12Device) out=rcx->[+0x18](void**)") &&
             saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", "rcx=0x") &&
             saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!D3D12XboxCreateDevice", "as dwords (128 bytes): 00000001 00000000") &&
             device_works(device) && ok;
        if (device) device->Release();
    }
    return ok;
}

// Raw vtable calls past the public desktop methods: logged with the slot index and E_NOTIMPL, never a jump into
// whatever follows the desktop vtable. Unknown IIDs are logged and refused.
using RawSlot = std::uintptr_t(STDMETHODCALLTYPE*)(void*, std::uintptr_t, std::uintptr_t, std::uintptr_t,
                                                   std::uintptr_t, std::uintptr_t);

std::uintptr_t call_slot(void* object, unsigned slot, std::uintptr_t a1)
{
    void* const* vtable = *static_cast<void* const* const*>(object);
    return reinterpret_cast<RawSlot>(vtable[slot])(object, a1, 0x22, 0x33, 0x44, 0x55);
}

bool slot_case(const char* tag, void* object, unsigned slot, const char* symbol)
{
    g_events.clear();
    const std::uintptr_t r = call_slot(object, slot, 0x11);
    char text[96];
    std::snprintf(text, sizeof(text), "d3d12x-%s-unknown-slot %u args rdx=0x11 r8=0x22 r9=0x33 stack0=0x44 stack1=0x55",
                  tag, slot);
    const bool ok = static_cast<HRESULT>(static_cast<std::uint32_t>(r)) == E_NOTIMPL && (r >> 32) == 0 &&
                    saw(X2W_GFX_EVENT_UNKNOWN_SLOT, symbol, text) &&
                    saw(X2W_GFX_EVENT_UNKNOWN_SLOT, symbol, "caller=d3d12_xs_xbox_check.exe+0x");
    std::printf("slot %s %u -> 0x%llx %s\n", tag, slot, static_cast<unsigned long long>(r), ok ? "ok" : "MISSING");
    return ok;
}

bool qi_case(const char* name, IUnknown* object, const char* symbol)
{
    const GUID made_up = {0x0badf00d, 0x1111, 0x2222, {0x33, 0x33, 0x44, 0x44, 0x55, 0x55, 0x66, 0x66}};
    g_events.clear();
    void* out = reinterpret_cast<void*>(0x1);
    const HRESULT hr = object->QueryInterface(made_up, &out);
    const bool ok = hr == E_NOINTERFACE && out == nullptr &&
                    saw(X2W_GFX_EVENT_UNKNOWN_IID, symbol, "iid={0badf00d-1111-2222-3333-444455556666}");
    std::printf("qi %s -> 0x%08lx %s\n", name, static_cast<unsigned long>(hr), ok ? "ok" : "MISSING");
    return ok;
}

bool unknown_slot_checks()
{
    Params params;
    ID3D12Device* device = nullptr;
    const std::uintptr_t args[8] = {0, u(&params), u(&IID_ID3D12Device), u(&device), 0, 0, 0, 0};
    if (!create_case("slots_device", args, "contract iid=r8(ID3D12Device) out=r9(void**)")) return false;
    bool ok = slot_case("device", device, 80, "d3d12_xs!ID3D12Device::slot80") &&
              slot_case("device", device, 120, "d3d12_xs!ID3D12Device::slot120") &&
              qi_case("device", device, "d3d12_xs!ID3D12Device::QueryInterface");

    D3D12_COMMAND_QUEUE_DESC qdesc{};
    qdesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ID3D12CommandQueue* queue = nullptr;
    ID3D12CommandAllocator* allocator = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    ID3D12Fence* fence = nullptr;
    ID3D12Resource* resource = nullptr;
    ID3D12Heap* heap = nullptr;
    ID3D12DescriptorHeap* views = nullptr;
    ID3D12DescriptorHeap* rtvs = nullptr;
    D3D12_HEAP_PROPERTIES props{};
    props.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC rdesc{};
    rdesc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    rdesc.Width = 65536;
    rdesc.Height = 1;
    rdesc.DepthOrArraySize = 1;
    rdesc.MipLevels = 1;
    rdesc.SampleDesc.Count = 1;
    rdesc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    D3D12_HEAP_DESC hdesc{};
    hdesc.SizeInBytes = 65536;
    hdesc.Properties.Type = D3D12_HEAP_TYPE_DEFAULT;
    hdesc.Flags = D3D12_HEAP_FLAG_ALLOW_ONLY_BUFFERS;
    D3D12_DESCRIPTOR_HEAP_DESC vdesc{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 16, D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    D3D12_DESCRIPTOR_HEAP_DESC rtdesc{D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 4, D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    const bool made =
        SUCCEEDED(device->CreateCommandQueue(&qdesc, IID_PPV_ARGS(&queue))) &&
        SUCCEEDED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) &&
        SUCCEEDED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator, nullptr, IID_PPV_ARGS(&list))) &&
        SUCCEEDED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence))) &&
        SUCCEEDED(device->CreateCommittedResource(&props, D3D12_HEAP_FLAG_NONE, &rdesc, D3D12_RESOURCE_STATE_COMMON,
                                                  nullptr, IID_PPV_ARGS(&resource))) &&
        SUCCEEDED(device->CreateHeap(&hdesc, IID_PPV_ARGS(&heap))) &&
        SUCCEEDED(device->CreateDescriptorHeap(&vdesc, IID_PPV_ARGS(&views))) &&
        SUCCEEDED(device->CreateDescriptorHeap(&rtdesc, IID_PPV_ARGS(&rtvs)));
    std::printf("objects made=%d\n", made ? 1 : 0);
    ok = ok && made;
    if (made) {
        ok = slot_case("queue", queue, 19, "d3d12_xs!ID3D12CommandQueue::slot19") &&
             slot_case("queue", queue, 40, "d3d12_xs!ID3D12CommandQueue::slot40") &&
             qi_case("queue", queue, "d3d12_xs!ID3D12CommandQueue::QueryInterface") &&
             slot_case("allocator", allocator, 9, "d3d12_xs!ID3D12CommandAllocator::slot9") &&
             qi_case("allocator", allocator, "d3d12_xs!ID3D12CommandAllocator::QueryInterface") &&
             slot_case("list", list, 81, "d3d12_xs!ID3D12GraphicsCommandList::slot81") &&
             slot_case("list", list, 200, "d3d12_xs!ID3D12GraphicsCommandList::slot200") &&
             qi_case("list", list, "d3d12_xs!ID3D12GraphicsCommandList::QueryInterface") &&
             slot_case("fence", fence, 12, "d3d12_xs!ID3D12Fence1::slot12") &&
             qi_case("fence", fence, "d3d12_xs!ID3D12Fence1::QueryInterface") &&
             slot_case("resource", resource, 17, "d3d12_xs!ID3D12Resource::slot17") &&
             qi_case("resource", resource, "d3d12_xs!ID3D12Resource::QueryInterface") &&
             slot_case("heap", heap, 10, "d3d12_xs!ID3D12Heap::slot10") &&
             qi_case("heap", heap, "d3d12_xs!ID3D12Heap::QueryInterface") &&
             slot_case("descriptor-heap", views, 11, "d3d12_xs!ID3D12DescriptorHeap::slot11") &&
             qi_case("descriptor-heap", views, "d3d12_xs!ID3D12DescriptorHeap::QueryInterface") &&
             slot_case("view-heap", rtvs, 11, "d3d12_xs!ID3D12DescriptorHeap(RTV/DSV)::slot11") &&
             qi_case("view-heap", rtvs, "d3d12_xs!ID3D12DescriptorHeap(RTV/DSV)::QueryInterface") && ok;
        // Known slots still forward: the RTV heap's start handle is the desktop heap's, and the queue still works.
        D3D12_DESCRIPTOR_HEAP_DESC got = rtvs->GetDesc();
        ok = ok && got.Type == D3D12_DESCRIPTOR_HEAP_TYPE_RTV && got.NumDescriptors == 4 &&
             rtvs->GetCPUDescriptorHandleForHeapStart().ptr != 0 && list->Close() == S_OK;
        ID3D12CommandList* lists[] = {list};
        queue->ExecuteCommandLists(1, lists);
        HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        ok = ok && SUCCEEDED(queue->Signal(fence, 1)) && SUCCEEDED(fence->SetEventOnCompletion(1, event)) &&
             WaitForSingleObject(event, 10000) == WAIT_OBJECT_0;
        CloseHandle(event);
    }
    for (IUnknown* object : std::initializer_list<IUnknown*>{rtvs, views, heap, resource, fence, list, allocator, queue})
        if (object) object->Release();
    device->Release();
    return ok;
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM w, LPARAM l)
{
    return DefWindowProcW(window, message, w, l);
}

// A title's own DXGI calls with the shim's wrapped queue: the factory comes from the desktop CreateDXGIFactory2 (an
// import of this executable, routed through the shim's logging), CreateSwapChainForHwnd gets the wrapped queue on a
// hidden window, and three frames are cleared and presented.
bool swap_chain_checks()
{
    Params params;
    ID3D12Device* device = nullptr;
    const std::uintptr_t args[8] = {0, u(&params), u(&IID_ID3D12Device), u(&device), 0, 0, 0, 0};
    if (!create_case("swap_device", args, "contract iid=r8(ID3D12Device) out=r9(void**)")) return false;
    bool ok = saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!dxgi", "d3d12x-dxgi-hook image d3d12_xs_xbox_check.exe") &&
              saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!dxgi", "factory import(s) routed") &&
              !saw(X2W_GFX_EVENT_NOTE, "d3d12_xs!dxgi", ": 0 dxgi.dll factory import(s)");

    WNDCLASSW wc{};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"x2w_xbox_swap_chain";
    RegisterClassW(&wc);
    HWND window = CreateWindowExW(0, wc.lpszClassName, L"x2w", WS_OVERLAPPEDWINDOW, 0, 0, 256, 256, nullptr, nullptr,
                                  wc.hInstance, nullptr);  // never shown

    D3D12_COMMAND_QUEUE_DESC qdesc{};
    qdesc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ID3D12CommandQueue* queue = nullptr;
    IDXGIFactory2* factory = nullptr;
    IDXGISwapChain1* chain1 = nullptr;
    IDXGISwapChain3* chain = nullptr;
    g_events.clear();
    HRESULT factory_hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
    ok = ok && window && SUCCEEDED(factory_hr) &&
         saw(X2W_GFX_EVENT_NOTE, "dxgi!CreateDXGIFactory2", "d3d12x-dxgi-factory CreateDXGIFactory2 flags=0x0") &&
         saw(X2W_GFX_EVENT_NOTE, "dxgi!CreateDXGIFactory2", "-> 0x00000000");
    std::printf("factory hr=0x%08lx logged=%d\n", static_cast<unsigned long>(factory_hr), ok ? 1 : 0);
    ok = ok && SUCCEEDED(device->CreateCommandQueue(&qdesc, IID_PPV_ARGS(&queue)));

    DXGI_SWAP_CHAIN_DESC1 desc{};
    desc.Width = 256;
    desc.Height = 256;
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2;
    desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    g_events.clear();
    const HRESULT chain_hr =
        ok ? factory->CreateSwapChainForHwnd(queue, window, &desc, nullptr, nullptr, &chain1) : E_FAIL;
    std::printf("swap chain hr=0x%08lx\n", static_cast<unsigned long>(chain_hr));
    ok = ok && SUCCEEDED(chain_hr) && chain1 &&
         saw(X2W_GFX_EVENT_NOTE, "dxgi!IDXGIFactory::CreateSwapChainForHwnd",
             "d3d12x-dxgi-swap-chain CreateSwapChainForHwnd device=wrapped-queue(unwrapped for DXGI)") &&
         saw(X2W_GFX_EVENT_NOTE, "dxgi!IDXGIFactory::CreateSwapChainForHwnd", "256x256 format=28 buffers=2") &&
         saw(X2W_GFX_EVENT_NOTE, "dxgi!IDXGIFactory::CreateSwapChainForHwnd", "-> 0x00000000 swap_chain=wrapped");
    ok = ok && SUCCEEDED(chain1->QueryInterface(IID_PPV_ARGS(&chain)));
    if (ok) {
        // The swap chain's device is the wrapped queue.
        ID3D12CommandQueue* back = nullptr;
        ok = SUCCEEDED(chain->GetDevice(IID_PPV_ARGS(&back))) && back == queue;
        if (back) back->Release();
        std::printf("swap chain device is wrapped queue=%d\n", ok ? 1 : 0);
    }

    ID3D12DescriptorHeap* rtvs = nullptr;
    ID3D12CommandAllocator* allocator = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    ID3D12Fence* fence = nullptr;
    HANDLE event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    D3D12_DESCRIPTOR_HEAP_DESC hdesc{D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 2, D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    ok = ok && SUCCEEDED(device->CreateDescriptorHeap(&hdesc, IID_PPV_ARGS(&rtvs))) &&
         SUCCEEDED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) &&
         SUCCEEDED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator, nullptr, IID_PPV_ARGS(&list))) &&
         SUCCEEDED(list->Close()) && SUCCEEDED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)));
    X2WGfxCounters before{};
    before.size = sizeof(before);
    X2WGfxGetCounters(&before);
    const UINT increment = ok ? device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV) : 0;
    unsigned presented = 0;
    for (UINT64 frame = 1; ok && frame <= 3; ++frame) {
        const UINT index = chain->GetCurrentBackBufferIndex();
        ID3D12Resource* buffer = nullptr;
        ok = SUCCEEDED(chain->GetBuffer(index, IID_PPV_ARGS(&buffer)));
        if (!ok) break;
        D3D12_CPU_DESCRIPTOR_HANDLE rtv = rtvs->GetCPUDescriptorHandleForHeapStart();
        rtv.ptr += static_cast<SIZE_T>(index) * increment;
        device->CreateRenderTargetView(buffer, nullptr, rtv);
        ok = SUCCEEDED(allocator->Reset()) && SUCCEEDED(list->Reset(allocator, nullptr));
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = buffer;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = D3D12_RESOURCE_STATE_PRESENT;
        barrier.Transition.StateAfter = D3D12_RESOURCE_STATE_RENDER_TARGET;
        list->ResourceBarrier(1, &barrier);
        const float color[4] = {0.1f * static_cast<float>(frame), 0.2f, 0.3f, 1.0f};
        list->ClearRenderTargetView(rtv, color, 0, nullptr);
        std::swap(barrier.Transition.StateBefore, barrier.Transition.StateAfter);
        list->ResourceBarrier(1, &barrier);
        ok = ok && SUCCEEDED(list->Close());
        ID3D12CommandList* lists[] = {list};
        queue->ExecuteCommandLists(1, lists);
        const HRESULT present_hr = chain->Present(0, 0);
        std::printf("frame %llu present=0x%08lx\n", static_cast<unsigned long long>(frame),
                    static_cast<unsigned long>(present_hr));
        ok = ok && SUCCEEDED(present_hr) && SUCCEEDED(queue->Signal(fence, frame)) &&
             SUCCEEDED(fence->SetEventOnCompletion(frame, event)) && WaitForSingleObject(event, 10000) == WAIT_OBJECT_0;
        presented += ok ? 1 : 0;
        buffer->Release();
    }
    X2WGfxCounters after{};
    after.size = sizeof(after);
    X2WGfxGetCounters(&after);
    std::printf("presented=%u counted=%u\n", presented, after.presents - before.presents);
    ok = ok && presented == 3 && after.presents - before.presents == 3;

    // A swap chain on a desktop queue (not the shim's) is passed through and not wrapped.
    if (ok) {
        ID3D12Device* desktop = nullptr;
        ID3D12CommandQueue* desktop_queue = nullptr;
        IDXGISwapChain1* plain = nullptr;
        HWND other = CreateWindowExW(0, wc.lpszClassName, L"x2w", WS_OVERLAPPEDWINDOW, 0, 0, 64, 64, nullptr, nullptr,
                                     wc.hInstance, nullptr);
        g_events.clear();
        // The desktop d3d12.dll's export: this executable's D3D12CreateDevice import is the shim's.
        using CreateFn = HRESULT(WINAPI*)(IUnknown*, D3D_FEATURE_LEVEL, REFIID, void**);
        HMODULE d3d12 = LoadLibraryW(L"d3d12.dll");
        const auto create = d3d12 ? reinterpret_cast<CreateFn>(reinterpret_cast<void*>(GetProcAddress(d3d12, "D3D12CreateDevice")))
                                  : nullptr;
        const bool made = create && SUCCEEDED(create(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&desktop))) &&
                          SUCCEEDED(desktop->CreateCommandQueue(&qdesc, IID_PPV_ARGS(&desktop_queue))) &&
                          SUCCEEDED(factory->CreateSwapChainForHwnd(desktop_queue, other, &desc, nullptr, nullptr, &plain));
        ok = made && saw(X2W_GFX_EVENT_NOTE, "dxgi!IDXGIFactory::CreateSwapChainForHwnd",
                         "device=not-a-shim-queue(passed through)") &&
             saw(X2W_GFX_EVENT_NOTE, "dxgi!IDXGIFactory::CreateSwapChainForHwnd", "swap_chain=desktop");
        std::printf("desktop queue passthrough=%d\n", ok ? 1 : 0);
        if (plain) plain->Release();
        if (desktop_queue) desktop_queue->Release();
        if (desktop) desktop->Release();
        if (other) DestroyWindow(other);
    }

    if (event) CloseHandle(event);
    for (IUnknown* object : std::initializer_list<IUnknown*>{fence, list, allocator, rtvs, chain, chain1, queue, factory})
        if (object) object->Release();
    device->Release();
    if (window) DestroyWindow(window);
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
    } else if (scenario == "create_device_orders"sv) {
        passed = order_checks();
    } else if (scenario == "unknown_slots"sv) {
        passed = unknown_slot_checks();
    } else if (scenario == "dxgi_swap_chain"sv) {
        passed = swap_chain_checks();
    } else {
        return 2;
    }
    X2WGfxSetLogSink(nullptr, nullptr);
    std::printf("Desktop d3d12_xs.dll xbox %s: %s\n", argv[1], passed ? "PASS" : "FAIL");
    return passed ? 0 : 1;
}
