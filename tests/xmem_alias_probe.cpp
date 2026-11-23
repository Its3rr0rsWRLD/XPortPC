// Measurement fixture for the title memory layer (src/xmem_title.h): which kinds of desktop memory D3D12 can alias
// with ID3D12Device3::OpenExistingHeapFromAddress / OpenExistingHeapFromFileMapping, whether the aliased bytes are
// coherent both ways after GPU work completes, and what opening the heap does to the working set.
//
//   xmem_alias_probe warp|hardware
//
// Prints one "probe <case> ..." line per case and exits 0 once every case has run (a refused case is a result, not a
// failure). Exits 77 without the adapter, 1 when the device cannot be created or a GPU copy cannot be submitted.
// Cases:
//   committed        VirtualAlloc MEM_RESERVE|MEM_COMMIT, 64 MiB, untouched before the heap is opened
//   partial          64 MiB reserved, first 16 MiB committed
//   write_watch      committed with MEM_WRITE_WATCH; GetWriteWatch after a CPU write and after a GPU write
//   placeholder      VirtualAlloc2 placeholder split in two, the first half replaced with a committed allocation
//   window           VirtualAlloc2 with address requirements [4 GiB, 1 TiB) and 4 MiB alignment
//   view_address     a SEC_COMMIT pagefile section view passed to OpenExistingHeapFromAddress
//   mapping_commit   OpenExistingHeapFromFileMapping of a SEC_COMMIT section, placed buffer at 1 MiB
//   mapping_reserve  the same with a SEC_RESERVE section whose view commits only its first 4 MiB
//   large_pages      MEM_LARGE_PAGES after enabling SeLockMemoryPrivilege (normally not held)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <psapi.h>
#include <wrl/client.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string_view>
#include "test_guard.h"

using Microsoft::WRL::ComPtr;

namespace {
constexpr std::uint64_t MiB = std::uint64_t{1} << 20;

using VirtualAlloc2Fn = PVOID(WINAPI*)(HANDLE, PVOID, SIZE_T, ULONG, ULONG, MEM_EXTENDED_PARAMETER*, ULONG);
using MapViewOfFile3Fn = PVOID(WINAPI*)(HANDLE, HANDLE, PVOID, ULONG64, SIZE_T, ULONG, ULONG,
                                        MEM_EXTENDED_PARAMETER*, ULONG);

template <typename T>
T kernelbase(const char* name)
{
    HMODULE module = GetModuleHandleW(L"kernelbase.dll");
    return module ? reinterpret_cast<T>(reinterpret_cast<void*>(GetProcAddress(module, name))) : nullptr;
}

std::uint64_t working_set()
{
    PROCESS_MEMORY_COUNTERS counters{};
    counters.cb = sizeof(counters);
    return GetProcessMemoryInfo(GetCurrentProcess(), &counters, sizeof(counters)) ? counters.WorkingSetSize : 0;
}

struct Gpu {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12Device3> device3;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    UINT64 value = 0;
    HANDLE event = nullptr;

    int create(bool warp)
    {
        ComPtr<IDXGIFactory4> factory;
        if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) return 1;
        ComPtr<IDXGIAdapter1> adapter;
        if (warp) {
            factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter));
        } else {
            ComPtr<IDXGIAdapter1> candidate;
            for (UINT i = 0; !adapter && factory->EnumAdapters1(i, &candidate) != DXGI_ERROR_NOT_FOUND; ++i) {
                DXGI_ADAPTER_DESC1 desc{};
                if (SUCCEEDED(candidate->GetDesc1(&desc)) && !(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE))
                    adapter = candidate;
            }
        }
        if (!adapter) return 77;
        DXGI_ADAPTER_DESC1 desc{};
        adapter->GetDesc1(&desc);
        std::printf("adapter=%ls vendor=0x%04x device=0x%04x\n", desc.Description, desc.VendorId, desc.DeviceId);
        if (FAILED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device))) ||
            FAILED(device.As(&device3)))
            return 1;
        D3D12_COMMAND_QUEUE_DESC q{};
        q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue))) ||
            FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) ||
            FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                             IID_PPV_ARGS(&list))) ||
            FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence))))
            return 1;
        list->Close();
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        return event ? 0 : 1;
    }

    ComPtr<ID3D12Resource> buffer(D3D12_HEAP_TYPE type, UINT64 bytes, D3D12_RESOURCE_STATES state)
    {
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = type;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = bytes;
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r;
        device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr, IID_PPV_ARGS(&r));
        return r;
    }

    ComPtr<ID3D12Resource> placed(ID3D12Heap* heap, UINT64 offset, UINT64 bytes, HRESULT* hr)
    {
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = bytes;
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS | D3D12_RESOURCE_FLAG_ALLOW_CROSS_ADAPTER;
        ComPtr<ID3D12Resource> r;
        *hr = device->CreatePlacedResource(heap, offset, &desc, D3D12_RESOURCE_STATE_COMMON, nullptr,
                                           IID_PPV_ARGS(&r));
        return r;
    }

    bool run()
    {
        const HRESULT closed = list->Close();
        if (FAILED(closed)) {
            std::printf("probe close_hr=0x%08lx\n", static_cast<unsigned long>(closed));
            return false;
        }
        ID3D12CommandList* lists[] = {list.Get()};
        queue->ExecuteCommandLists(1, lists);
        if (FAILED(queue->Signal(fence.Get(), ++value))) return false;
        if (fence->GetCompletedValue() < value) {
            fence->SetEventOnCompletion(value, event);
            if (WaitForSingleObject(event, 10000) != WAIT_OBJECT_0) return false;
        }
        return SUCCEEDED(device->GetDeviceRemovedReason());
    }
};

// CPU writes 256 bytes at cpu, the GPU reads them through the buffer at `offset`; the GPU writes the next 256 bytes
// and the CPU reads them through cpu. Returns "both", "gpu_read_only", "cpu_read_only", "none" or "submit_failed".
const char* roundtrip(Gpu& gpu, ID3D12Resource* buffer, UINT64 offset, std::uint8_t* cpu)
{
    for (int i = 0; i < 256; ++i) cpu[i] = static_cast<std::uint8_t>(0x5a ^ i);
    auto readback = gpu.buffer(D3D12_HEAP_TYPE_READBACK, 256, D3D12_RESOURCE_STATE_COPY_DEST);
    auto upload = gpu.buffer(D3D12_HEAP_TYPE_UPLOAD, 256, D3D12_RESOURCE_STATE_GENERIC_READ);
    if (!readback || !upload) return "submit_failed";
    void* mapped = nullptr;
    upload->Map(0, nullptr, &mapped);
    for (int i = 0; i < 256; ++i) static_cast<std::uint8_t*>(mapped)[i] = static_cast<std::uint8_t>(0xc3 ^ i);
    upload->Unmap(0, nullptr);
    gpu.allocator->Reset();
    gpu.list->Reset(gpu.allocator.Get(), nullptr);
    gpu.list->CopyBufferRegion(readback.Get(), 0, buffer, offset, 256);
    gpu.list->CopyBufferRegion(buffer, offset + 256, upload.Get(), 0, 256);
    if (!gpu.run()) return "submit_failed";
    readback->Map(0, nullptr, &mapped);
    bool gpu_read = true, cpu_read = true;
    for (int i = 0; i < 256; ++i) {
        gpu_read = gpu_read && static_cast<std::uint8_t*>(mapped)[i] == static_cast<std::uint8_t>(0x5a ^ i);
        cpu_read = cpu_read && cpu[256 + i] == static_cast<std::uint8_t>(0xc3 ^ i);
    }
    D3D12_RANGE none{0, 0};
    readback->Unmap(0, &none);
    return gpu_read && cpu_read ? "both" : gpu_read ? "gpu_read_only" : cpu_read ? "cpu_read_only" : "none";
}

void removed(Gpu& gpu, const char* after)
{
    std::printf("probe device_after_%s removed=0x%08lx\n", after,
                static_cast<unsigned long>(gpu.device->GetDeviceRemovedReason()));
}

// Opens a heap over [base, ...) with OpenExistingHeapFromAddress, places a 2 MiB buffer at 0 and checks coherence.
void address_case(Gpu& gpu, const char* name, void* base, std::uint8_t* cpu = nullptr)
{
    const std::uint64_t before = working_set();
    ComPtr<ID3D12Heap> heap;
    const HRESULT hr = gpu.device3->OpenExistingHeapFromAddress(base, IID_PPV_ARGS(&heap));
    const std::uint64_t after = working_set();
    std::printf("probe %s open_hr=0x%08lx", name, static_cast<unsigned long>(hr));
    if (SUCCEEDED(hr)) {
        HRESULT placed_hr = E_FAIL;
        auto buffer = gpu.placed(heap.Get(), 0, 2 * MiB, &placed_hr);
        std::printf(" heap_bytes=%llu working_set_delta=%lld placed_hr=0x%08lx",
                    static_cast<unsigned long long>(heap->GetDesc().SizeInBytes),
                    static_cast<long long>(after - before), static_cast<unsigned long>(placed_hr));
        if (buffer) std::printf(" coherence=%s", roundtrip(gpu, buffer.Get(), 0, cpu ? cpu : static_cast<std::uint8_t*>(base)));
    }
    std::printf("\n");
}

bool enable_lock_memory()
{
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &token)) return false;
    TOKEN_PRIVILEGES privileges{};
    privileges.PrivilegeCount = 1;
    privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
    bool ok = LookupPrivilegeValueW(nullptr, L"SeLockMemoryPrivilege", &privileges.Privileges[0].Luid) &&
              AdjustTokenPrivileges(token, FALSE, &privileges, 0, nullptr, nullptr) &&
              GetLastError() == ERROR_SUCCESS;
    CloseHandle(token);
    return ok;
}
}  // namespace

int main(int argc, char** argv)
{
    test_guard::install("xmem_alias_probe", 50);  // below the ctest TIMEOUT (CMakeLists.txt)
    if (argc != 2) return 2;
    const std::string_view adapter = argv[1];
    if (adapter != "warp" && adapter != "hardware") return 2;
    Gpu gpu;
    if (const int created = gpu.create(adapter == "warp")) return created;
    D3D12_FEATURE_DATA_EXISTING_HEAPS existing{};
    gpu.device->CheckFeatureSupport(D3D12_FEATURE_EXISTING_HEAPS, &existing, sizeof(existing));
    std::printf("existing_heaps=%d\n", existing.Supported);
    const auto va2 = kernelbase<VirtualAlloc2Fn>("VirtualAlloc2");
    const auto map3 = kernelbase<MapViewOfFile3Fn>("MapViewOfFile3");
    std::printf("virtual_alloc2=%d map_view3=%d large_page_minimum=%zu\n", va2 != nullptr, map3 != nullptr,
                GetLargePageMinimum());

    {
        void* p = VirtualAlloc(nullptr, 64 * MiB, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        address_case(gpu, "committed", p);
        removed(gpu, "committed_open");
        VirtualFree(p, 0, MEM_RELEASE);
        removed(gpu, "committed_release");
    }
    {
        // A fresh device-independent check: a submission with no aliasing at all.
        auto upload = gpu.buffer(D3D12_HEAP_TYPE_UPLOAD, 256, D3D12_RESOURCE_STATE_GENERIC_READ);
        auto target = gpu.buffer(D3D12_HEAP_TYPE_DEFAULT, 256, D3D12_RESOURCE_STATE_COPY_DEST);
        gpu.allocator->Reset();
        gpu.list->Reset(gpu.allocator.Get(), nullptr);
        gpu.list->CopyBufferRegion(target.Get(), 0, upload.Get(), 0, 256);
        std::printf("probe plain_submit ok=%d\n", gpu.run());
    }
    {
        auto* p = static_cast<std::uint8_t*>(
            VirtualAlloc(nullptr, 64 * MiB, MEM_RESERVE | MEM_COMMIT | MEM_WRITE_WATCH, PAGE_READWRITE));
        std::printf("probe write_watch alloc=%d\n", p != nullptr);
        if (p) {
            ResetWriteWatch(p, 64 * MiB);
            ComPtr<ID3D12Heap> heap;
            const HRESULT hr = gpu.device3->OpenExistingHeapFromAddress(p, IID_PPV_ARGS(&heap));
            std::printf("probe write_watch open_hr=0x%08lx", static_cast<unsigned long>(hr));
            if (SUCCEEDED(hr)) {
                HRESULT placed_hr = E_FAIL;
                auto buffer = gpu.placed(heap.Get(), 0, 2 * MiB, &placed_hr);
                if (buffer) {
                    // roundtrip writes 256 CPU bytes at page 0 and the GPU writes bytes 256..511 (same page), so
                    // test the GPU write on its own page first.
                    ResetWriteWatch(p, 64 * MiB);
                    auto upload = gpu.buffer(D3D12_HEAP_TYPE_UPLOAD, 256, D3D12_RESOURCE_STATE_GENERIC_READ);
                    gpu.allocator->Reset();
                    gpu.list->Reset(gpu.allocator.Get(), nullptr);
                    gpu.list->CopyBufferRegion(buffer.Get(), 65536, upload.Get(), 0, 256);
                    gpu.run();
                    void* hits[64];
                    ULONG_PTR count = 64;
                    ULONG granularity = 0;
                    GetWriteWatch(0, p, 64 * MiB, hits, &count, &granularity);
                    std::printf(" gpu_write_pages=%llu", static_cast<unsigned long long>(count));
                    p[3 * 4096] = 1;
                    count = 64;
                    GetWriteWatch(0, p, 64 * MiB, hits, &count, &granularity);
                    std::printf(" cpu_plus_gpu_pages=%llu granularity=%lu coherence=%s",
                                static_cast<unsigned long long>(count), granularity,
                                roundtrip(gpu, buffer.Get(), 1 * MiB, p + 1 * MiB));
                }
            }
            std::printf("\n");
            VirtualFree(p, 0, MEM_RELEASE);
        }
    }
    if (va2) {
        void* p = va2(GetCurrentProcess(), nullptr, 64 * MiB, MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS,
                      nullptr, 0);
        const BOOL split = p && VirtualFree(p, 32 * MiB, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
        void* q = split ? va2(GetCurrentProcess(), p, 32 * MiB, MEM_RESERVE | MEM_COMMIT | MEM_REPLACE_PLACEHOLDER,
                              PAGE_READWRITE, nullptr, 0)
                        : nullptr;
        MEMORY_BASIC_INFORMATION info{};
        if (q) VirtualQuery(q, &info, sizeof(info));
        std::printf("probe placeholder split=%d replaced=%d base_matches=%d region=%llu\n", split, q != nullptr,
                    q && info.AllocationBase == q, static_cast<unsigned long long>(info.RegionSize));
        if (q) address_case(gpu, "placeholder", q);
        // Back to a placeholder, then the halves coalesce and the whole range is released.
        const BOOL back = q && VirtualFree(q, 0, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
        const DWORD back_error = back ? 0 : GetLastError();
        const BOOL back_sized = !back && q && VirtualFree(q, 32 * MiB, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
        const BOOL coalesced = p && VirtualFree(p, 64 * MiB, MEM_RELEASE | MEM_COALESCE_PLACEHOLDERS);
        const BOOL released = p && VirtualFree(p, 0, MEM_RELEASE);
        std::printf("probe placeholder_release back_size0=%d error=%lu back_sized=%d coalesced=%d released=%d\n", back,
                    back_error, back_sized, coalesced, released);

        MEM_ADDRESS_REQUIREMENTS requirements{};
        requirements.LowestStartingAddress = reinterpret_cast<PVOID>(0x100000000ull);
        requirements.HighestEndingAddress = reinterpret_cast<PVOID>(0xffffffffffull);
        requirements.Alignment = 4 * MiB;
        MEM_EXTENDED_PARAMETER parameter{};
        parameter.Type = MemExtendedParameterAddressRequirements;
        parameter.Pointer = &requirements;
        void* w = va2(GetCurrentProcess(), nullptr, 8 * MiB, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE, &parameter, 1);
        std::printf("probe window address=0x%llx error=%lu\n",
                    static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(w)), w ? 0ul : GetLastError());
        if (w) {
            address_case(gpu, "window", w);
            VirtualFree(w, 0, MEM_RELEASE);
        }
    }
    {
        HANDLE section = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE | SEC_COMMIT, 0,
                                            static_cast<DWORD>(64 * MiB), nullptr);
        auto* view = section ? static_cast<std::uint8_t*>(MapViewOfFile(section, FILE_MAP_ALL_ACCESS, 0, 0, 0)) : nullptr;
        if (view) address_case(gpu, "view_address", view);
        if (view) {
            const std::uint64_t before = working_set();
            ComPtr<ID3D12Heap> heap;
            const HRESULT hr = gpu.device3->OpenExistingHeapFromFileMapping(section, IID_PPV_ARGS(&heap));
            const std::uint64_t after = working_set();
            std::printf("probe mapping_commit open_hr=0x%08lx", static_cast<unsigned long>(hr));
            if (SUCCEEDED(hr)) {
                HRESULT placed_hr = E_FAIL;
                auto buffer = gpu.placed(heap.Get(), 1 * MiB, 2 * MiB, &placed_hr);
                std::printf(" heap_bytes=%llu working_set_delta=%lld placed_hr=0x%08lx",
                            static_cast<unsigned long long>(heap->GetDesc().SizeInBytes),
                            static_cast<long long>(after - before), static_cast<unsigned long>(placed_hr));
                if (buffer) std::printf(" coherence=%s", roundtrip(gpu, buffer.Get(), 0, view + 1 * MiB));
                // A second view of the same section at another address sees the GPU's bytes.
                auto* second = static_cast<std::uint8_t*>(MapViewOfFile(section, FILE_MAP_ALL_ACCESS, 0, 0, 0));
                if (second) {
                    std::printf(" second_view=%s", std::memcmp(second + 1 * MiB, view + 1 * MiB, 512) == 0 ? "same" : "differs");
                    UnmapViewOfFile(second);
                }
            }
            std::printf("\n");
            UnmapViewOfFile(view);
        }
        if (section) CloseHandle(section);
    }
    {
        HANDLE section = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE | SEC_RESERVE, 0,
                                            static_cast<DWORD>(64 * MiB), nullptr);
        auto* view = section ? static_cast<std::uint8_t*>(MapViewOfFile(section, FILE_MAP_ALL_ACCESS, 0, 0, 0)) : nullptr;
        if (view) VirtualAlloc(view, 4 * MiB, MEM_COMMIT, PAGE_READWRITE);
        if (view) {
            ComPtr<ID3D12Heap> heap;
            const HRESULT hr = gpu.device3->OpenExistingHeapFromFileMapping(section, IID_PPV_ARGS(&heap));
            std::printf("probe mapping_reserve open_hr=0x%08lx", static_cast<unsigned long>(hr));
            if (SUCCEEDED(hr)) {
                HRESULT placed_hr = E_FAIL;
                auto buffer = gpu.placed(heap.Get(), 1 * MiB, 2 * MiB, &placed_hr);
                std::printf(" heap_bytes=%llu placed_hr=0x%08lx",
                            static_cast<unsigned long long>(heap->GetDesc().SizeInBytes),
                            static_cast<unsigned long>(placed_hr));
                if (buffer) std::printf(" coherence=%s", roundtrip(gpu, buffer.Get(), 0, view + 1 * MiB));
            }
            std::printf("\n");
            UnmapViewOfFile(view);
        }
        if (section) CloseHandle(section);
    }
    {
        const bool privilege = enable_lock_memory();
        const SIZE_T large = GetLargePageMinimum();
        void* p = large ? VirtualAlloc(nullptr, 4 * large, MEM_RESERVE | MEM_COMMIT | MEM_LARGE_PAGES, PAGE_READWRITE)
                        : nullptr;
        std::printf("probe large_pages privilege=%d alloc=%d error=%lu\n", privilege, p != nullptr,
                    p ? 0ul : GetLastError());
        if (p) {
            address_case(gpu, "large_pages_alias", p);
            VirtualFree(p, 0, MEM_RELEASE);
        }
    }
    {
        void* p = VirtualAlloc(nullptr, 64 * MiB, MEM_RESERVE, PAGE_NOACCESS);
        VirtualAlloc(p, 16 * MiB, MEM_COMMIT, PAGE_READWRITE);
        address_case(gpu, "partial", p);
        VirtualFree(p, 0, MEM_RELEASE);
    }
    removed(gpu, "partial");
    std::printf("probe done\n");
    return 0;
}
