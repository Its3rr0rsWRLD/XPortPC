// Runtime ladder R2 (docs/design/runtime.md, section 6): clear and present through the graphics shim.
//
// A console-style program: it imports D3D12CreateDevice and D3D12GetDebugInterface from d3d12_xs.dll
// (it links no desktop d3d12.lib) and allocates title memory through xmem.dll. DXGI is used only to
// pick the adapter; the swap chain comes from the shim's own present path.
//
//   r2_clear warp|hardware clear        3 frames: clear, read the back buffer back, present; every
//                                       pixel must equal the clear colour bit for bit
//   r2_clear warp|hardware wrong_color  control: the same frames compared against a colour one step
//                                       off in green; passes only if the comparison reports a mismatch
//   r2_clear warp unknown_entries       unknown vtable slots and IIDs are logged with the right slot
//                                       index, IID and caller, and fail safely
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "era_title_gpu_api.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string_view>
#include <vector>

using Microsoft::WRL::ComPtr;

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void XMemFree(void* allocation, ULONGLONG attributes);

namespace {

using namespace runtime_test;

// Graphics attribute word recorded at the AMD xmem call sites (tests/xmem_shim_check.cpp).
constexpr ULONGLONG graphics_word = 0xa8004000;
constexpr UINT width = 64;
constexpr UINT height = 64;
constexpr UINT frames = 3;
constexpr UINT row_pitch = width * 4;  // 256: already D3D12_TEXTURE_DATA_PITCH_ALIGNMENT
static_assert(row_pitch % D3D12_TEXTURE_DATA_PITCH_ALIGNMENT == 0);

// Clear colour of frame i, as UNORM8 bytes. Each channel is k/255, which a conforming float-to-UNORM
// conversion maps to exactly k, so the expected bytes are exact.
struct Rgba8 {
    std::uint8_t r, g, b, a;
};
Rgba8 frame_color(UINT frame) { return {static_cast<std::uint8_t>(51 + 40 * frame), 102, static_cast<std::uint8_t>(153 - 20 * frame), 255}; }

// Clears, reads back and presents `frames` frames. Returns false on any API failure; counts pixels
// that differ from the expected colour (frame colour, green raised by `green_offset`) in mismatches.
bool run_frames(Gpu& gpu, int green_offset, unsigned& mismatches)
{
    HWND window = make_window(width, height);
    if (!window) {
        std::fprintf(stderr, "r2: CreateWindowEx failed: %lu\n", GetLastError());
        return false;
    }
    DXGI_SWAP_CHAIN_DESC1 desc{};
    desc.Width = width;
    desc.Height = height;
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2;
    desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    ComPtr<IDXGISwapChain3> chain;
    if (!ok(X2WGfxCreateSwapChainForHwnd(gpu.queue.Get(), window, &desc, nullptr, nullptr, IID_PPV_ARGS(&chain)),
            "X2WGfxCreateSwapChainForHwnd")) {
        DestroyWindow(window);
        return false;
    }

    D3D12_DESCRIPTOR_HEAP_DESC heap_desc{};
    heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    heap_desc.NumDescriptors = desc.BufferCount;
    ComPtr<ID3D12DescriptorHeap> rtv_heap;
    if (!ok(gpu.device->CreateDescriptorHeap(&heap_desc, IID_PPV_ARGS(&rtv_heap)), "CreateDescriptorHeap")) return false;
    const UINT rtv_step = gpu.device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
    std::vector<ComPtr<ID3D12Resource>> buffers(desc.BufferCount);
    for (UINT i = 0; i < desc.BufferCount; ++i) {
        if (!ok(chain->GetBuffer(i, IID_PPV_ARGS(&buffers[i])), "GetBuffer")) return false;
        D3D12_CPU_DESCRIPTOR_HANDLE rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
        rtv.ptr += static_cast<SIZE_T>(i) * rtv_step;
        gpu.device->CreateRenderTargetView(buffers[i].Get(), nullptr, rtv);
    }

    D3D12_HEAP_PROPERTIES readback_heap{};
    readback_heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC readback_desc{};
    readback_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    readback_desc.Width = static_cast<UINT64>(row_pitch) * height;
    readback_desc.Height = 1;
    readback_desc.DepthOrArraySize = 1;
    readback_desc.MipLevels = 1;
    readback_desc.SampleDesc.Count = 1;
    readback_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> readback;
    if (!ok(gpu.device->CreateCommittedResource(&readback_heap, D3D12_HEAP_FLAG_NONE, &readback_desc,
                                                D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&readback)),
            "CreateCommittedResource(readback)")) {
        return false;
    }

    unsigned presents = 0;
    for (UINT frame = 0; frame < frames; ++frame) {
        const UINT index = chain->GetCurrentBackBufferIndex();
        ID3D12Resource* back = buffers[index].Get();
        D3D12_CPU_DESCRIPTOR_HANDLE rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
        rtv.ptr += static_cast<SIZE_T>(index) * rtv_step;
        const Rgba8 color = frame_color(frame);
        const FLOAT clear[4] = {color.r / 255.0f, color.g / 255.0f, color.b / 255.0f, color.a / 255.0f};

        if (!ok(gpu.allocator->Reset(), "allocator Reset") || !ok(gpu.list->Reset(gpu.allocator.Get(), nullptr), "list Reset"))
            return false;
        auto barrier = transition(back, D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_RENDER_TARGET);
        gpu.list->ResourceBarrier(1, &barrier);
        gpu.list->ClearRenderTargetView(rtv, clear, 0, nullptr);
        barrier = transition(back, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
        gpu.list->ResourceBarrier(1, &barrier);
        D3D12_TEXTURE_COPY_LOCATION dst{};
        dst.pResource = readback.Get();
        dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, width, height, 1, row_pitch};
        D3D12_TEXTURE_COPY_LOCATION src{};
        src.pResource = back;
        src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        barrier = transition(back, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_PRESENT);
        gpu.list->ResourceBarrier(1, &barrier);
        if (!ok(gpu.list->Close(), "Close") || !gpu.submit_and_wait()) return false;

        void* mapped = nullptr;
        const D3D12_RANGE read{0, static_cast<SIZE_T>(readback_desc.Width)};
        if (!ok(readback->Map(0, &read, &mapped), "Map")) return false;
        const Rgba8 expected{color.r, static_cast<std::uint8_t>(color.g + green_offset), color.b, color.a};
        unsigned frame_mismatches = 0;
        std::uint32_t first = 0;
        for (UINT y = 0; y < height; ++y) {
            const auto* row = static_cast<const std::uint8_t*>(mapped) + static_cast<SIZE_T>(y) * row_pitch;
            for (UINT x = 0; x < width; ++x) {
                const std::uint8_t* p = row + x * 4;
                if (std::memcmp(p, &expected, 4) != 0) {
                    if (!frame_mismatches) std::memcpy(&first, p, 4);
                    ++frame_mismatches;
                }
            }
        }
        const D3D12_RANGE none{0, 0};
        readback->Unmap(0, &none);
        std::printf("frame=%u buffer=%u expected=%02x%02x%02x%02x mismatches=%u", frame, index, expected.r, expected.g,
                    expected.b, expected.a, frame_mismatches);
        if (frame_mismatches) std::printf(" first=%08x", static_cast<unsigned>(first));
        std::printf("\n");
        mismatches += frame_mismatches;

        const HRESULT present = chain->Present(0, 0);
        std::printf("frame=%u present=0x%08lx\n", frame, static_cast<unsigned long>(present));
        if (!ok(present, "Present")) return false;
        ++presents;
    }
    // Let the last present retire before the swap chain and window go away.
    gpu.list->Reset(gpu.allocator.Get(), nullptr);
    gpu.list->Close();
    const bool drained = gpu.submit_and_wait();
    chain.Reset();
    DestroyWindow(window);
    std::printf("presents=%u\n", presents);
    return drained && presents == frames;
}

int clear_check(bool warp, bool control)
{
    // Title memory first, as a title allocates before it creates its device: the shim then attaches
    // the device to xmem.dll's title GPU registry, which aliases this allocation.
    void* title_memory = XMemAlloc(64 * 1024, graphics_word);
    if (!title_memory) {
        std::fputs("r2: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    int rc = 1;
    {
        Gpu gpu;
        const int created = gpu.create(warp);
        if (created) {
            XMemFree(title_memory, graphics_word);
            return created;
        }
        const auto after_create = counters();
        const std::uint64_t translated =
            X2WTitleGpuTranslate(reinterpret_cast<std::uintptr_t>(title_memory), 64 * 1024);
        std::printf("devices_created=%u title_gpu_state=%d title_gpu_hr=0x%08lx title_translate=0x%llx\n",
                    after_create.devices_created, after_create.title_gpu_state,
                    static_cast<unsigned long>(after_create.title_gpu_hr), static_cast<unsigned long long>(translated));
        // The device must come from the shim, and the title GPU registry must be attached (E_NOTIMPL is
        // the registry's documented answer for a device without existing-heap support).
        bool good = after_create.devices_created == 1;
        if (after_create.title_gpu_state == X2W_GFX_TITLE_GPU_ATTACHED) {
            good = good && translated != 0;
        } else {
            good = good && after_create.title_gpu_state == X2W_GFX_TITLE_GPU_FAILED &&
                   after_create.title_gpu_hr == E_NOTIMPL;
        }

        unsigned mismatches = 0;
        good = run_frames(gpu, control ? 1 : 0, mismatches) && good;
        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        std::printf("mismatches=%u debug_errors=%u shim_presents=%u unknown_slots=%llu unknown_iids=%llu first_uses=%llu\n",
                    mismatches, debug_errors, end.presents, static_cast<unsigned long long>(end.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls),
                    static_cast<unsigned long long>(end.first_uses));
        // Everything this program calls is implemented: no unknown slot or IID may appear.
        good = good && debug_errors == 0 && end.presents == frames && end.unknown_slot_calls == 0 &&
               end.unknown_iid_calls == 0;
        if (control) {
            std::printf("control=%s\n", mismatches ? "mismatch_detected" : "mismatch_missed");
            rc = good && mismatches == width * height * frames ? 0 : 1;
        } else {
            rc = good && mismatches == 0 ? 0 : 1;
        }
    }
    XMemFree(title_memory, graphics_word);
    const auto released = counters();
    std::printf("live_objects=%u\n", released.live_objects);
    return released.live_objects == 0 ? rc : 1;
}

// unknown_entries: sink that records events.
struct Recorded {
    std::vector<X2WGfxEvent> events;
    std::vector<std::string_view> interfaces;
};

void WINAPI record(const X2WGfxEvent* event, void* context)
{
    if (event->kind == X2W_GFX_EVENT_FIRST_USE) return;
    auto* recorded = static_cast<Recorded*>(context);
    X2WGfxEvent copy = *event;
    copy.symbol = copy.detail = nullptr;  // only valid during the call
    recorded->events.push_back(copy);
    recorded->interfaces.push_back(event->interface_name ? event->interface_name : "");
    std::fprintf(stderr, "[sink] %s %s\n", event->symbol, event->detail);
}

using SlotFn = std::uintptr_t(STDMETHODCALLTYPE*)(void*, std::uintptr_t, std::uintptr_t, std::uintptr_t);

// Calls vtable slot `slot` of `object` with three marker arguments.
__declspec(noinline) std::uintptr_t call_slot(void* object, unsigned slot)
{
    auto* table = *static_cast<SlotFn**>(object);
    return table[slot](object, 0x1111, 0x2222, 0x3333);
}

bool in_this_module(const void* address)
{
    HMODULE module = nullptr;
    return GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                              static_cast<LPCWSTR>(address), &module) &&
           module == GetModuleHandleW(nullptr);
}

int unknown_entries_check()
{
    Gpu gpu;
    if (gpu.create(true)) return 1;
    Recorded recorded;
    X2WGfxSetLogSink(record, &recorded);
    bool good = true;
    auto expect = [&](bool condition, const char* what) {
        if (!condition) std::fprintf(stderr, "r2 unknown_entries: %s\n", what);
        good = good && condition;
    };
    const auto before = counters();

    // A known slot logs nothing: ID3D12Device::GetNodeCount is slot 7.
    expect(static_cast<std::uint32_t>(call_slot(gpu.device.Get(), 7)) == 1, "GetNodeCount through slot 7 returns 1");

    struct Case {
        void* object;
        const char* name;
        unsigned slot;
    };
    // The first slot past each public interface, and one far past it.
    // The device and list wrappers end at ID3D12Device10 (79 slots) and ID3D12GraphicsCommandList7 (81).
    const Case cases[] = {{gpu.device.Get(), "ID3D12Device", 79},
                          {gpu.device.Get(), "ID3D12Device", 120},
                          {gpu.queue.Get(), "ID3D12CommandQueue", 19},
                          {gpu.allocator.Get(), "ID3D12CommandAllocator", 9},
                          {gpu.list.Get(), "ID3D12GraphicsCommandList", 81},
                          {gpu.fence.Get(), "ID3D12Fence1", 12}};
    for (const Case& c : cases) {
        const std::size_t seen = recorded.events.size();
        const std::uintptr_t result = call_slot(c.object, c.slot);
        expect(static_cast<HRESULT>(static_cast<std::uint32_t>(result)) == E_NOTIMPL, "unknown slot returns E_NOTIMPL");
        expect(recorded.events.size() == seen + 1, "unknown slot logged once");
        if (recorded.events.size() != seen + 1) continue;
        const X2WGfxEvent& e = recorded.events.back();
        std::printf("slot event: %s slot=%u caller_in_test=%d args=%llx,%llx,%llx\n", c.name, e.slot,
                    in_this_module(e.caller) ? 1 : 0, static_cast<unsigned long long>(e.args[1]),
                    static_cast<unsigned long long>(e.args[2]), static_cast<unsigned long long>(e.args[3]));
        expect(e.kind == X2W_GFX_EVENT_UNKNOWN_SLOT, "event kind is UNKNOWN_SLOT");
        expect(e.slot == c.slot, "event slot index");
        expect(recorded.interfaces.back() == c.name, "event interface name");
        expect(e.args[0] == reinterpret_cast<std::uintptr_t>(c.object), "event this pointer");
        expect(e.args[1] == 0x1111 && e.args[2] == 0x2222 && e.args[3] == 0x3333, "event argument registers");
        expect(in_this_module(e.caller), "event caller inside the calling module");
    }
    // A repeated slot is counted but not logged again.
    const std::size_t seen_before_repeat = recorded.events.size();
    call_slot(gpu.device.Get(), 79);
    expect(recorded.events.size() == seen_before_repeat, "repeated unknown slot not logged again");

    // Unknown IIDs: a made-up one and a public interface the device is not (ID3D12CommandQueue).
    const GUID made_up = {0x7832772d, 0x5250, 0x4f72, {0x9a, 0x51, 0x6b, 0x6e, 0x6f, 0x77, 0x6e, 0x31}};
    const GUID not_device = __uuidof(ID3D12CommandQueue);
    for (const GUID* iid : {&made_up, &not_device}) {
        const std::size_t seen = recorded.events.size();
        void* out = reinterpret_cast<void*>(0x1);
        const HRESULT hr = gpu.device->QueryInterface(*iid, &out);
        expect(hr == E_NOINTERFACE && out == nullptr, "unknown IID fails with E_NOINTERFACE and null output");
        expect(recorded.events.size() == seen + 1, "unknown IID logged once");
        if (recorded.events.size() != seen + 1) continue;
        const X2WGfxEvent& e = recorded.events.back();
        expect(e.kind == X2W_GFX_EVENT_UNKNOWN_IID, "event kind is UNKNOWN_IID");
        expect(IsEqualGUID(e.iid, *iid) != 0, "event IID");
        expect(recorded.interfaces.back() == "ID3D12Device", "IID event interface name");
        expect(in_this_module(e.caller), "IID event caller inside the calling module");
    }
    // Same IID on a different interface is a distinct entry.
    {
        void* out = nullptr;
        const std::size_t seen = recorded.events.size();
        expect(gpu.queue->QueryInterface(made_up, &out) == E_NOINTERFACE && !out, "queue unknown IID fails");
        expect(recorded.events.size() == seen + 1 && recorded.interfaces.back() == "ID3D12CommandQueue",
               "queue unknown IID logged for the queue");
    }
    // Known IIDs still work and log nothing.
    {
        const std::size_t seen = recorded.events.size();
        ComPtr<ID3D12Pageable> pageable;
        ComPtr<ID3D12Fence1> fence1;
        expect(SUCCEEDED(gpu.fence.As(&pageable)) && SUCCEEDED(gpu.fence.As(&fence1)), "fence known IIDs");
        expect(fence1 && fence1->GetCreationFlags() == D3D12_FENCE_FLAG_NONE, "fence creation flags");
        ComPtr<ID3D12Device> parent;
        expect(SUCCEEDED(gpu.list->GetDevice(IID_PPV_ARGS(&parent))) && parent.Get() == gpu.device.Get(),
               "GetDevice returns the wrapped device");
        expect(recorded.events.size() == seen, "known IIDs log nothing");
    }

    const auto after = counters();
    std::printf("unknown_slot_calls=%llu unknown_iid_calls=%llu\n",
                static_cast<unsigned long long>(after.unknown_slot_calls - before.unknown_slot_calls),
                static_cast<unsigned long long>(after.unknown_iid_calls - before.unknown_iid_calls));
    expect(after.unknown_slot_calls - before.unknown_slot_calls == 7, "seven unknown slot calls counted");
    expect(after.unknown_iid_calls - before.unknown_iid_calls == 3, "three unknown IID calls counted");
    X2WGfxSetLogSink(nullptr, nullptr);
    expect(gpu.debug_errors() == 0, "no debug-layer errors");
    std::printf("unknown_entries=%s\n", good ? "pass" : "fail");
    return good ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    const std::string_view mode = argv[1];
    const std::string_view operation = argv[2];
    if (mode != "warp" && mode != "hardware") return 2;
    const bool warp = mode == "warp";
    if (operation == "clear") return clear_check(warp, false);
    if (operation == "wrong_color") return clear_check(warp, true);
    if (operation == "unknown_entries" && warp) return unknown_entries_check();
    return 2;
}
