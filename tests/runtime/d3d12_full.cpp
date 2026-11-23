// The graphics shim's public desktop D3D12 surface past the first interface versions (docs/design/runtime.md,
// section 3): ID3D12Device1..10, ID3D12GraphicsCommandList1..7, wrapped resources, heaps and command signatures,
// the title address model of buffers the title creates (section 4), ExecuteIndirect with title addresses in its
// argument records, and enhanced barriers.
//
// A console-style program: everything comes from d3d12_xs.dll and xmem.dll (no desktop d3d12.lib).
//
//   d3d12_full warp|hardware versions                  QueryInterface of every interface version, a forwarded
//                                                      method of each, the buffer address model, refused entries,
//                                                      unknown slots past the new public counts
//   d3d12_full warp|hardware indirect                  ExecuteIndirect draws whose records hold title addresses of a
//                                                      vertex buffer and a root CBV in title memory, from an UPLOAD
//                                                      argument buffer with a count buffer and from a DEFAULT one
//                                                      (legacy barriers); the frame must equal the CPU reference
//   d3d12_full warp|hardware indirect_wrong_reference  control: the reference with two record colours swapped;
//                                                      passes only if exactly those pixels differ
//   d3d12_full warp|hardware enhanced                  the indirect frame with enhanced barriers only (Barrier,
//                                                      CreateCommittedResource3); 77 when the device lacks them
//   d3d12_full warp|hardware enhanced_wrong_reference  its control
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter or no enhanced-barrier support.
#include "runtime_common.h"
#include "era_title_gpu_api.h"

#include "d3d12_full_ps.h"
#include "d3d12_full_vs.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <string_view>
#include <vector>

using Microsoft::WRL::ComPtr;

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void XMemFree(void* allocation, ULONGLONG attributes);

namespace {

using namespace runtime_test;

constexpr ULONGLONG graphics_word = 0xa8004000;  // tests/xmem_shim_check.cpp
constexpr UINT width = 64;
constexpr UINT height = 64;
constexpr UINT row_pitch = width * 4;
constexpr SIZE_T title_bytes = 64 * 1024;
constexpr std::uint8_t clear_rgba[4] = {10, 20, 30, 255};

// The three rectangles the indirect records draw (pixels, y down, half-open) and their colours.
struct Rect {
    int x0, y0, x1, y1;
    std::uint8_t rgba[4];
};
constexpr Rect rects[3] = {{0, 0, 32, 32, {200, 40, 10, 255}},
                           {32, 0, 64, 32, {20, 180, 60, 255}},
                           {0, 40, 64, 56, {90, 90, 250, 255}}};
// Title memory: colour i at 256 * i (root CBVs are 256-byte aligned), the six vertices of rectangle i at 1024 + 256 i.
constexpr std::size_t colour_offset(int i) { return 256 * std::size_t(i); }
constexpr std::size_t vertex_offset(int i) { return 1024 + 256 * std::size_t(i); }

// One indirect record: a vertex buffer view, a root CBV, a draw (d3d12_xs_indirect.h layout: tightly packed).
#pragma pack(push, 4)
struct Record {
    D3D12_VERTEX_BUFFER_VIEW vbv;
    D3D12_GPU_VIRTUAL_ADDRESS cbv;
    D3D12_DRAW_ARGUMENTS draw;
};
#pragma pack(pop)
static_assert(sizeof(Record) == 40);

std::vector<std::uint8_t> reference(bool swapped)
{
    std::vector<std::uint8_t> out(std::size_t(width) * height * 4);
    for (UINT y = 0; y < height; ++y) {
        for (UINT x = 0; x < width; ++x) {
            const std::uint8_t* c = clear_rgba;
            for (int r = 0; r < 3; ++r) {
                if (int(x) >= rects[r].x0 && int(x) < rects[r].x1 && int(y) >= rects[r].y0 && int(y) < rects[r].y1) {
                    const int shown = swapped && r < 2 ? 1 - r : r;
                    c = rects[shown].rgba;
                }
            }
            std::memcpy(&out[(std::size_t(y) * width + x) * 4], c, 4);
        }
    }
    return out;
}

D3D12_RESOURCE_DESC buffer_desc(UINT64 bytes, D3D12_RESOURCE_FLAGS flags = D3D12_RESOURCE_FLAG_NONE)
{
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = bytes;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    desc.Flags = flags;
    return desc;
}

D3D12_RESOURCE_DESC1 desc1(const D3D12_RESOURCE_DESC& d)
{
    D3D12_RESOURCE_DESC1 out{};
    out.Dimension = d.Dimension;
    out.Alignment = d.Alignment;
    out.Width = d.Width;
    out.Height = d.Height;
    out.DepthOrArraySize = d.DepthOrArraySize;
    out.MipLevels = d.MipLevels;
    out.Format = d.Format;
    out.SampleDesc = d.SampleDesc;
    out.Layout = d.Layout;
    out.Flags = d.Flags;
    return out;
}

ComPtr<ID3D12Resource> committed(ID3D12Device* device, D3D12_HEAP_TYPE type, const D3D12_RESOURCE_DESC& desc,
                                 D3D12_RESOURCE_STATES state, const D3D12_CLEAR_VALUE* clear = nullptr)
{
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = type;
    ComPtr<ID3D12Resource> out;
    if (!ok(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, clear, IID_PPV_ARGS(&out)),
            "CreateCommittedResource"))
        return {};
    return out;
}

ComPtr<ID3D12Resource> committed3(ID3D12Device10* device, D3D12_HEAP_TYPE type, const D3D12_RESOURCE_DESC& desc,
                                  D3D12_BARRIER_LAYOUT layout, const D3D12_CLEAR_VALUE* clear = nullptr)
{
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = type;
    const D3D12_RESOURCE_DESC1 d = desc1(desc);
    ComPtr<ID3D12Resource> out;
    if (!ok(device->CreateCommittedResource3(&heap, D3D12_HEAP_FLAG_NONE, &d, layout, clear, nullptr, 0, nullptr,
                                             IID_PPV_ARGS(&out)),
            "CreateCommittedResource3"))
        return {};
    return out;
}

// A pipeline-state stream subobject in the CD3DX12 layout.
template <D3D12_PIPELINE_STATE_SUBOBJECT_TYPE Type, class Inner>
struct alignas(void*) Sub {
    D3D12_PIPELINE_STATE_SUBOBJECT_TYPE type = Type;
    Inner inner;
};

// Records the sink receives except first uses.
struct Recorded {
    unsigned refused = 0, slots = 0, iids = 0;
    std::string details;
};

void WINAPI record(const X2WGfxEvent* event, void* context)
{
    if (event->kind == X2W_GFX_EVENT_FIRST_USE) return;
    std::fprintf(stderr, "[sink] %s %s\n", event->symbol, event->detail);
    auto* r = static_cast<Recorded*>(context);
    if (event->kind == X2W_GFX_EVENT_REFUSED) ++r->refused;
    if (event->kind == X2W_GFX_EVENT_UNKNOWN_SLOT) ++r->slots;
    if (event->kind == X2W_GFX_EVENT_UNKNOWN_IID) ++r->iids;
    r->details += event->symbol;
    r->details += ' ';
    r->details += event->detail;
    r->details += '\n';
}

using SlotFn = std::uintptr_t(STDMETHODCALLTYPE*)(void*, std::uintptr_t, std::uintptr_t, std::uintptr_t);
__declspec(noinline) std::uintptr_t call_slot(void* object, unsigned slot)
{
    auto* table = *static_cast<SlotFn**>(object);
    return table[slot](object, 0x1111, 0x2222, 0x3333);
}

struct Check {
    bool good = true;
    void operator()(bool condition, const char* what)
    {
        if (!condition) std::fprintf(stderr, "d3d12_full: %s\n", what);
        good = good && condition;
    }
};

// QueryInterface of `iids` on `object`: a bit per IID that succeeded; each success must return `object` itself.
template <std::size_t N>
unsigned versions(IUnknown* object, const GUID* const (&iids)[N], Check& check)
{
    unsigned mask = 0;
    for (std::size_t i = 0; i < N; ++i) {
        void* out = reinterpret_cast<void*>(0x1);
        const HRESULT hr = object->QueryInterface(*iids[i], &out);
        if (SUCCEEDED(hr)) {
            check(out == static_cast<void*>(object), "a version QueryInterface returns the wrapper itself");
            static_cast<IUnknown*>(out)->Release();
            mask |= 1u << i;
        } else {
            check(hr == E_NOINTERFACE && out == nullptr, "an unsupported version fails with E_NOINTERFACE");
        }
    }
    return mask;
}

int versions_check(bool warp)
{
    void* title = XMemAlloc(title_bytes, graphics_word);
    if (!title) return 1;
    int rc = 1;
    {
        Gpu gpu;
        const int created = gpu.create(warp);
        if (created) {
            XMemFree(title, graphics_word);
            return created;
        }
        Recorded recorded;
        X2WGfxSetLogSink(record, &recorded);
        Check check;
        const auto start = counters();

        const GUID* const device_iids[] = {&__uuidof(ID3D12Device1), &__uuidof(ID3D12Device2), &__uuidof(ID3D12Device3),
                                           &__uuidof(ID3D12Device4), &__uuidof(ID3D12Device5), &__uuidof(ID3D12Device6),
                                           &__uuidof(ID3D12Device7), &__uuidof(ID3D12Device8), &__uuidof(ID3D12Device9),
                                           &__uuidof(ID3D12Device10)};
        const GUID* const list_iids[] = {&__uuidof(ID3D12GraphicsCommandList1), &__uuidof(ID3D12GraphicsCommandList2),
                                         &__uuidof(ID3D12GraphicsCommandList3), &__uuidof(ID3D12GraphicsCommandList4),
                                         &__uuidof(ID3D12GraphicsCommandList5), &__uuidof(ID3D12GraphicsCommandList6),
                                         &__uuidof(ID3D12GraphicsCommandList7)};
        const unsigned device_mask = versions(gpu.device.Get(), device_iids, check);
        const unsigned list_mask = versions(gpu.list.Get(), list_iids, check);
        std::printf("device_versions=0x%03x list_versions=0x%02x\n", device_mask, list_mask);
        // Every D3D12 runtime since Windows 10 1809 has these.
        check((device_mask & 0x1f) == 0x1f, "ID3D12Device1..5 are answered");
        check((list_mask & 0xf) == 0xf, "ID3D12GraphicsCommandList1..4 are answered");
        const auto bits = [](unsigned v) {
            unsigned n = 0;
            for (; v; v &= v - 1) ++n;
            return n;
        };
        const unsigned failed_iids = 10 - bits(device_mask) + 7 - bits(list_mask);

        ComPtr<ID3D12Device4> d4;
        ComPtr<ID3D12Device8> d8;
        ComPtr<ID3D12Device10> d10;
        gpu.device.As(&d4);
        if (!d4) {
            std::fputs("d3d12_full: no ID3D12Device4\n", stderr);
            X2WGfxSetLogSink(nullptr, nullptr);
            XMemFree(title, graphics_word);
            return 1;
        }
        if (device_mask & (1u << 7)) gpu.device.As(&d8);
        if (device_mask & (1u << 9)) gpu.device.As(&d10);

        // The buffer address model (d3d12_xs_resources.h).
        {
            ComPtr<ID3D12Resource> vram = committed(gpu.device.Get(), D3D12_HEAP_TYPE_DEFAULT, buffer_desc(65536),
                                                    D3D12_RESOURCE_STATE_COMMON);
            ComPtr<ID3D12Resource> upload = committed(gpu.device.Get(), D3D12_HEAP_TYPE_UPLOAD, buffer_desc(4096),
                                                      D3D12_RESOURCE_STATE_GENERIC_READ);
            D3D12_RESOURCE_DESC tex = buffer_desc(0);
            tex.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            tex.Width = 16;
            tex.Height = 16;
            tex.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
            tex.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
            ComPtr<ID3D12Resource> texture = committed(gpu.device.Get(), D3D12_HEAP_TYPE_DEFAULT, tex,
                                                       D3D12_RESOURCE_STATE_COMMON);
            check(vram && upload && texture, "resources created");
            if (vram && upload && texture) {
                const std::uint64_t va = vram->GetGPUVirtualAddress();
                const std::uint64_t desktop = X2WTitleGpuTranslate(va, 4);
                void* located = nullptr;
                std::uint64_t offset = 1;
                const HRESULT lhr = X2WTitleGpuLocate(va + 64, 4, &located, &offset);
                std::uint64_t located_va = 0;
                if (SUCCEEDED(lhr)) {
                    located_va = static_cast<ID3D12Resource*>(located)->GetGPUVirtualAddress();
                    static_cast<IUnknown*>(located)->Release();
                }
                std::printf("default_title=0x%llx desktop=0x%llx located_offset=%llu\n",
                            static_cast<unsigned long long>(va), static_cast<unsigned long long>(desktop),
                            static_cast<unsigned long long>(offset));
                check(va && desktop && desktop != va, "a DEFAULT buffer has a registered title address");
                check(SUCCEEDED(lhr) && offset == 64 && located_va == desktop, "X2WTitleGpuLocate finds the buffer");
                MEMORY_BASIC_INFORMATION info{};
                check(VirtualQuery(reinterpret_cast<void*>(va), &info, sizeof(info)) && info.State == MEM_RESERVE,
                      "the title address is a reserved range of the process");
                void* mapped = nullptr;
                check(SUCCEEDED(upload->Map(0, nullptr, &mapped)) &&
                          reinterpret_cast<std::uintptr_t>(mapped) == upload->GetGPUVirtualAddress(),
                      "an UPLOAD buffer's GPU address is its mapped CPU pointer");
                upload->Unmap(0, nullptr);
                check(X2WTitleGpuTranslate(upload->GetGPUVirtualAddress(), 4) != 0, "the UPLOAD buffer is registered");
                check(texture->GetGPUVirtualAddress() == 0, "a texture has no GPU address");
                ComPtr<ID3D12Resource2> r2;
                check(FAILED(vram.As(&r2)) || r2.Get() == vram.Get(), "ID3D12Resource2 is the wrapper");
                vram.Reset();
                check(X2WTitleGpuTranslate(va, 4) == 0, "a released buffer is unregistered");
            }
        }
        // Heaps: placed buffers, and a heap opened from process memory (OpenExistingHeapFromAddress).
        {
            D3D12_HEAP_DESC hd{};
            hd.SizeInBytes = 1 << 20;
            hd.Properties.Type = D3D12_HEAP_TYPE_DEFAULT;
            hd.Flags = D3D12_HEAP_FLAG_ALLOW_ONLY_BUFFERS;
            ComPtr<ID3D12Heap> heap;
            check(ok(d4->CreateHeap1(&hd, nullptr, IID_PPV_ARGS(&heap)), "CreateHeap1"), "ID3D12Device4::CreateHeap1");
            ComPtr<ID3D12Resource> placed;
            const D3D12_RESOURCE_DESC placed_desc = buffer_desc(65536);
            if (heap)
                check(ok(gpu.device->CreatePlacedResource(heap.Get(), 65536, &placed_desc,
                                                          D3D12_RESOURCE_STATE_COMMON, nullptr, IID_PPV_ARGS(&placed)),
                         "CreatePlacedResource"),
                      "CreatePlacedResource into a wrapped heap");
            if (placed) check(X2WTitleGpuTranslate(placed->GetGPUVirtualAddress(), 4) != 0, "a placed buffer is registered");
            ComPtr<ID3D12Device3> d3;
            gpu.device.As(&d3);
            void* memory = VirtualAlloc(nullptr, 1 << 16, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
            ComPtr<ID3D12Heap> opened;
            const HRESULT ohr = memory ? d3->OpenExistingHeapFromAddress(memory, IID_PPV_ARGS(&opened)) : E_FAIL;
            if (SUCCEEDED(ohr)) {
                ComPtr<ID3D12Resource> in_memory;
                D3D12_RESOURCE_DESC bd = buffer_desc(4096);
                bd.Flags = D3D12_RESOURCE_FLAG_ALLOW_CROSS_ADAPTER;
                check(ok(gpu.device->CreatePlacedResource(opened.Get(), 0, &bd, D3D12_RESOURCE_STATE_COMMON, nullptr,
                                                          IID_PPV_ARGS(&in_memory)),
                         "CreatePlacedResource(existing heap)"),
                      "a buffer placed in an existing heap");
                if (in_memory)
                    check(in_memory->GetGPUVirtualAddress() == reinterpret_cast<std::uintptr_t>(memory),
                          "a buffer in a heap opened from memory has that memory's address");
            } else {
                std::printf("open_existing_heap=0x%08lx (not supported here)\n", static_cast<unsigned long>(ohr));
            }
            opened.Reset();
            if (memory) VirtualFree(memory, 0, MEM_RELEASE);
            if (heap) {
                ID3D12Pageable* pageable[] = {heap.Get()};
                const D3D12_RESIDENCY_PRIORITY priority[] = {D3D12_RESIDENCY_PRIORITY_NORMAL};
                ComPtr<ID3D12Device1> d1;
                gpu.device.As(&d1);
                check(ok(d1->SetResidencyPriority(1, pageable, priority), "SetResidencyPriority"),
                      "ID3D12Device1::SetResidencyPriority unwraps the heap");
                check(ok(d3->EnqueueMakeResident(D3D12_RESIDENCY_FLAG_NONE, 1, pageable, gpu.fence.Get(), 1),
                         "EnqueueMakeResident"),
                      "ID3D12Device3::EnqueueMakeResident unwraps the heap and fence");
            }
        }
        // Device4..10 creation entries.
        {
            ComPtr<ID3D12GraphicsCommandList> list1;
            check(ok(d4->CreateCommandList1(0, D3D12_COMMAND_LIST_TYPE_DIRECT, D3D12_COMMAND_LIST_FLAG_NONE,
                                            IID_PPV_ARGS(&list1)),
                     "CreateCommandList1"),
                  "ID3D12Device4::CreateCommandList1");
            if (list1) {
                check(ok(list1->Reset(gpu.allocator.Get(), nullptr), "Reset") && ok(list1->Close(), "Close"),
                      "a CreateCommandList1 list records");
            }
            D3D12_RESOURCE_ALLOCATION_INFO1 info1{};
            const D3D12_RESOURCE_DESC bd = buffer_desc(65536);
            const D3D12_RESOURCE_ALLOCATION_INFO a1 = d4->GetResourceAllocationInfo1(0, 1, &bd, &info1);
            check(a1.SizeInBytes >= 65536, "ID3D12Device4::GetResourceAllocationInfo1");
            if (d8) {
                const D3D12_RESOURCE_DESC1 bd1 = desc1(bd);
                const D3D12_RESOURCE_ALLOCATION_INFO a2 = d8->GetResourceAllocationInfo2(0, 1, &bd1, nullptr);
                check(a2.SizeInBytes >= 65536, "ID3D12Device8::GetResourceAllocationInfo2");
                D3D12_HEAP_PROPERTIES heap{};
                heap.Type = D3D12_HEAP_TYPE_DEFAULT;
                ComPtr<ID3D12Resource> r;
                check(ok(d8->CreateCommittedResource2(&heap, D3D12_HEAP_FLAG_NONE, &bd1, D3D12_RESOURCE_STATE_COMMON,
                                                      nullptr, nullptr, IID_PPV_ARGS(&r)),
                         "CreateCommittedResource2") &&
                          X2WTitleGpuTranslate(r->GetGPUVirtualAddress(), 4) != 0,
                      "ID3D12Device8::CreateCommittedResource2 gives a registered title address");
            }
            if (d10) {
                ComPtr<ID3D12Resource> r = committed3(d10.Get(), D3D12_HEAP_TYPE_DEFAULT, bd, D3D12_BARRIER_LAYOUT_UNDEFINED);
                check(r && X2WTitleGpuTranslate(r->GetGPUVirtualAddress(), 4) != 0,
                      "ID3D12Device10::CreateCommittedResource3 gives a registered title address");
            }
        }
        // Refused entries: they fail with the documented code and a REFUSED line.
        {
            ComPtr<ID3D12Device1> d1;
            gpu.device.As(&d1);
            void* library = reinterpret_cast<void*>(0x1);
            check(d1->CreatePipelineLibrary(nullptr, 0, __uuidof(ID3D12PipelineLibrary), &library) == DXGI_ERROR_UNSUPPORTED &&
                      !library,
                  "CreatePipelineLibrary is refused with DXGI_ERROR_UNSUPPORTED");
            ComPtr<ID3D12Device5> d5;
            gpu.device.As(&d5);
            const GUID command = {0x12345678, 0x1, 0x2, {0, 1, 2, 3, 4, 5, 6, 7}};
            void* meta = reinterpret_cast<void*>(0x1);
            check(d5->CreateMetaCommand(command, 0, nullptr, 0, __uuidof(ID3D12MetaCommand), &meta) == E_NOTIMPL && !meta,
                  "CreateMetaCommand is refused with E_NOTIMPL");
            // A mesh-shader stream whose shader is a console container is refused before translation.
            const std::uint32_t code[1] = {0xbf810000u};  // s_endpgm
            std::uint8_t container[sizeof(X2WShaderContainer) + 4]{};
            X2WShaderContainer header{};
            header.magic = X2W_SHADER_CONTAINER_MAGIC;
            header.version = X2W_SHADER_CONTAINER_VERSION;
            header.stage = X2W_SHADER_STAGE_VERTEX;
            header.binding_offset = sizeof(header);
            header.code_offset = sizeof(header);
            header.code_bytes = 4;
            std::memcpy(container, &header, sizeof(header));
            std::memcpy(container + sizeof(header), code, 4);
            struct {
                Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_MS, D3D12_SHADER_BYTECODE> ms;
                Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_PS, D3D12_SHADER_BYTECODE> ps;
            } stream{{D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_MS, {container, sizeof(container)}},
                     {D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_PS, {d3d12_full_ps, sizeof(d3d12_full_ps)}}};
            const D3D12_PIPELINE_STATE_STREAM_DESC sd{sizeof(stream), &stream};
            ComPtr<ID3D12Device2> d2;
            gpu.device.As(&d2);
            ComPtr<ID3D12PipelineState> mesh;
            check(d2->CreatePipelineState(&sd, IID_PPV_ARGS(&mesh)) == E_NOTIMPL && !mesh,
                  "a console mesh-shader stream is refused with E_NOTIMPL");
        }
        // Unknown slots past the new public counts.
        {
            ComPtr<ID3D12Resource> buffer = committed(gpu.device.Get(), D3D12_HEAP_TYPE_DEFAULT, buffer_desc(256),
                                                      D3D12_RESOURCE_STATE_COMMON);
            D3D12_HEAP_DESC hd{};
            hd.SizeInBytes = 65536;
            hd.Properties.Type = D3D12_HEAP_TYPE_DEFAULT;
            ComPtr<ID3D12Heap> heap;
            gpu.device->CreateHeap(&hd, IID_PPV_ARGS(&heap));
            D3D12_INDIRECT_ARGUMENT_DESC arg{};
            arg.Type = D3D12_INDIRECT_ARGUMENT_TYPE_DRAW;
            D3D12_COMMAND_SIGNATURE_DESC sig{};
            sig.ByteStride = sizeof(D3D12_DRAW_ARGUMENTS);
            sig.NumArgumentDescs = 1;
            sig.pArgumentDescs = &arg;
            ComPtr<ID3D12CommandSignature> signature;
            gpu.device->CreateCommandSignature(&sig, nullptr, IID_PPV_ARGS(&signature));
            check(buffer && heap && signature, "slot-check objects created");
            struct Case {
                void* object;
                unsigned slot;
            };
            const Case cases[] = {{gpu.device.Get(), 79}, {gpu.list.Get(), 81}, {buffer.Get(), 17},
                                  {heap.Get(), 10},       {signature.Get(), 8}};
            for (const Case& c : cases) {
                if (!c.object) continue;
                check(static_cast<HRESULT>(static_cast<std::uint32_t>(call_slot(c.object, c.slot))) == E_NOTIMPL,
                      "a slot past the public methods returns E_NOTIMPL");
            }
            check(recorded.slots == 5, "each unknown slot is logged");
        }

        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        X2WGfxSetLogSink(nullptr, nullptr);
        std::printf("refused=%u unknown_slots=%llu unknown_iids=%llu (expected %u) debug_errors=%u\n", recorded.refused,
                    static_cast<unsigned long long>(end.unknown_slot_calls - start.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls - start.unknown_iid_calls), failed_iids,
                    debug_errors);
        check(recorded.refused == 3, "three refusals (pipeline library, meta command, mesh stream)");
        check(end.unknown_iid_calls - start.unknown_iid_calls == failed_iids, "only unsupported versions are unknown");
        check(debug_errors == 0, "no debug-layer errors");
        rc = check.good ? 0 : 1;
        std::printf("versions=%s\n", check.good ? "pass" : "fail");
    }
    XMemFree(title, graphics_word);
    const auto released = counters();
    std::printf("live_objects=%u\n", released.live_objects);
    return released.live_objects == 0 ? rc : 1;
}

// --- ExecuteIndirect with title addresses -----------------------------------------------------------------------

ComPtr<ID3D12RootSignature> root_signature(ID3D12Device* device)
{
    D3D12_ROOT_PARAMETER1 param{};
    param.ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    param.Descriptor = {0, 0, D3D12_ROOT_DESCRIPTOR_FLAG_DATA_STATIC_WHILE_SET_AT_EXECUTE};
    param.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = 1;
    desc.Desc_1_1.pParameters = &param;
    desc.Desc_1_1.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
    ComPtr<ID3DBlob> blob, errors;
    if (!ok(D3D12SerializeVersionedRootSignature(&desc, &blob, &errors), "D3D12SerializeVersionedRootSignature"))
        return {};
    ComPtr<ID3D12RootSignature> root;
    ok(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)),
       "CreateRootSignature");
    return root;
}

// A desktop pipeline through ID3D12Device2::CreatePipelineState (a stream with desktop bytecode is passed through).
ComPtr<ID3D12PipelineState> stream_pipeline(ID3D12Device* device, ID3D12RootSignature* root)
{
    static const D3D12_INPUT_ELEMENT_DESC element = {"POSITION", 0, DXGI_FORMAT_R32G32_FLOAT, 0, 0,
                                                     D3D12_INPUT_CLASSIFICATION_PER_VERTEX_DATA, 0};
    D3D12_RASTERIZER_DESC rs{};
    rs.FillMode = D3D12_FILL_MODE_SOLID;
    rs.CullMode = D3D12_CULL_MODE_NONE;
    rs.DepthClipEnable = TRUE;
    D3D12_DEPTH_STENCIL_DESC ds{};
    D3D12_RT_FORMAT_ARRAY rt{};
    rt.NumRenderTargets = 1;
    rt.RTFormats[0] = DXGI_FORMAT_R8G8B8A8_UNORM;
    struct {
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_ROOT_SIGNATURE, ID3D12RootSignature*> root;
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_VS, D3D12_SHADER_BYTECODE> vs;
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_PS, D3D12_SHADER_BYTECODE> ps;
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_INPUT_LAYOUT, D3D12_INPUT_LAYOUT_DESC> layout;
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_RASTERIZER, D3D12_RASTERIZER_DESC> rs;
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_DEPTH_STENCIL, D3D12_DEPTH_STENCIL_DESC> ds;
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_PRIMITIVE_TOPOLOGY, D3D12_PRIMITIVE_TOPOLOGY_TYPE> topology;
        Sub<D3D12_PIPELINE_STATE_SUBOBJECT_TYPE_RENDER_TARGET_FORMATS, D3D12_RT_FORMAT_ARRAY> rt;
    } stream{};
    stream.root.inner = root;
    stream.vs.inner = {d3d12_full_vs, sizeof(d3d12_full_vs)};
    stream.ps.inner = {d3d12_full_ps, sizeof(d3d12_full_ps)};
    stream.layout.inner = {&element, 1};
    stream.rs.inner = rs;
    stream.ds.inner = ds;
    stream.topology.inner = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    stream.rt.inner = rt;
    ComPtr<ID3D12Device2> d2;
    if (!ok(device->QueryInterface(IID_PPV_ARGS(&d2)), "QueryInterface(ID3D12Device2)")) return {};
    const D3D12_PIPELINE_STATE_STREAM_DESC desc{sizeof(stream), &stream};
    ComPtr<ID3D12PipelineState> pso;
    ok(d2->CreatePipelineState(&desc, IID_PPV_ARGS(&pso)), "CreatePipelineState(stream)");
    return pso;
}

void write_records(Record* out, std::uintptr_t title, const int* which, int count)
{
    for (int i = 0; i < count; ++i) {
        const int r = which[i];
        out[i].vbv = {title + vertex_offset(r), 6 * 8, 8};
        out[i].cbv = title + colour_offset(r);
        out[i].draw = {6, 1, 0, 0};
    }
}

int indirect_check(bool warp, bool enhanced, bool control)
{
    auto* title = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    if (!title) return 1;
    for (int r = 0; r < 3; ++r) {
        float colour[4];
        for (int c = 0; c < 4; ++c) colour[c] = rects[r].rgba[c] / 255.0f;
        std::memcpy(title + colour_offset(r), colour, sizeof(colour));
        const float x0 = rects[r].x0 / 32.0f - 1, x1 = rects[r].x1 / 32.0f - 1;
        const float y0 = 1 - rects[r].y0 / 32.0f, y1 = 1 - rects[r].y1 / 32.0f;
        const float v[6][2] = {{x0, y0}, {x1, y0}, {x0, y1}, {x1, y0}, {x1, y1}, {x0, y1}};
        std::memcpy(title + vertex_offset(r), v, sizeof(v));
    }
    const std::uintptr_t title_va = reinterpret_cast<std::uintptr_t>(title);
    const std::vector<std::uint8_t> expected = reference(control);
    int rc = 1;
    {
        Gpu gpu;
        const int created = gpu.create(warp);
        if (created) {
            XMemFree(title, graphics_word);
            return created;
        }
        Recorded recorded;
        X2WGfxSetLogSink(record, &recorded);
        Check check;
        const auto start = counters();
        check(start.title_gpu_state == X2W_GFX_TITLE_GPU_ATTACHED, "title GPU registry attached");
        ComPtr<ID3D12Device10> d10;
        ComPtr<ID3D12GraphicsCommandList7> list7;
        if (enhanced) {
            D3D12_FEATURE_DATA_D3D12_OPTIONS12 o12{};
            const bool supported =
                SUCCEEDED(gpu.device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS12, &o12, sizeof(o12))) &&
                o12.EnhancedBarriersSupported && SUCCEEDED(gpu.device.As(&d10)) && SUCCEEDED(gpu.list.As(&list7));
            if (!supported) {
                std::puts("enhanced barriers not supported on this device");
                X2WGfxSetLogSink(nullptr, nullptr);
                XMemFree(title, graphics_word);
                return 77;
            }
        }
        ComPtr<ID3D12RootSignature> root = root_signature(gpu.device.Get());
        ComPtr<ID3D12PipelineState> pso = root ? stream_pipeline(gpu.device.Get(), root.Get()) : nullptr;
        D3D12_INDIRECT_ARGUMENT_DESC args[3]{};
        args[0].Type = D3D12_INDIRECT_ARGUMENT_TYPE_VERTEX_BUFFER_VIEW;
        args[0].VertexBuffer.Slot = 0;
        args[1].Type = D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT_BUFFER_VIEW;
        args[1].ConstantBufferView.RootParameterIndex = 0;
        args[2].Type = D3D12_INDIRECT_ARGUMENT_TYPE_DRAW;
        D3D12_COMMAND_SIGNATURE_DESC sd{};
        sd.ByteStride = sizeof(Record);
        sd.NumArgumentDescs = 3;
        sd.pArgumentDescs = args;
        ComPtr<ID3D12CommandSignature> signature;
        check(root && pso && ok(gpu.device->CreateCommandSignature(&sd, root.Get(), IID_PPV_ARGS(&signature)),
                                "CreateCommandSignature"),
              "pipeline and command signature");

        // Records: an UPLOAD buffer with four slots, two valid (rectangles 0 and 1) and two garbage the count buffer
        // excludes; a DEFAULT buffer (copied from an UPLOAD staging buffer) with rectangle 2.
        const D3D12_RESOURCE_DESC rt_desc = [] {
            D3D12_RESOURCE_DESC d = buffer_desc(0, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
            d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
            d.Width = width;
            d.Height = height;
            d.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
            d.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
            return d;
        }();
        D3D12_CLEAR_VALUE clear{};
        clear.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        for (int c = 0; c < 4; ++c) clear.Color[c] = clear_rgba[c] / 255.0f;
        ComPtr<ID3D12Resource> upload_args, count_buffer, staging, default_args, target, readback;
        if (enhanced) {
            upload_args = committed3(d10.Get(), D3D12_HEAP_TYPE_UPLOAD, buffer_desc(4 * sizeof(Record)),
                                     D3D12_BARRIER_LAYOUT_UNDEFINED);
            count_buffer = committed3(d10.Get(), D3D12_HEAP_TYPE_UPLOAD, buffer_desc(256), D3D12_BARRIER_LAYOUT_UNDEFINED);
            staging = committed3(d10.Get(), D3D12_HEAP_TYPE_UPLOAD, buffer_desc(sizeof(Record)), D3D12_BARRIER_LAYOUT_UNDEFINED);
            default_args = committed3(d10.Get(), D3D12_HEAP_TYPE_DEFAULT, buffer_desc(sizeof(Record)),
                                      D3D12_BARRIER_LAYOUT_UNDEFINED);
            target = committed3(d10.Get(), D3D12_HEAP_TYPE_DEFAULT, rt_desc, D3D12_BARRIER_LAYOUT_RENDER_TARGET, &clear);
            readback = committed3(d10.Get(), D3D12_HEAP_TYPE_READBACK, buffer_desc(row_pitch * height),
                                  D3D12_BARRIER_LAYOUT_UNDEFINED);
        } else {
            upload_args = committed(gpu.device.Get(), D3D12_HEAP_TYPE_UPLOAD, buffer_desc(4 * sizeof(Record)),
                                    D3D12_RESOURCE_STATE_GENERIC_READ);
            count_buffer = committed(gpu.device.Get(), D3D12_HEAP_TYPE_UPLOAD, buffer_desc(256),
                                     D3D12_RESOURCE_STATE_GENERIC_READ);
            staging = committed(gpu.device.Get(), D3D12_HEAP_TYPE_UPLOAD, buffer_desc(sizeof(Record)),
                                D3D12_RESOURCE_STATE_GENERIC_READ);
            default_args = committed(gpu.device.Get(), D3D12_HEAP_TYPE_DEFAULT, buffer_desc(sizeof(Record)),
                                     D3D12_RESOURCE_STATE_COPY_DEST);
            target = committed(gpu.device.Get(), D3D12_HEAP_TYPE_DEFAULT, rt_desc, D3D12_RESOURCE_STATE_RENDER_TARGET,
                               &clear);
            readback = committed(gpu.device.Get(), D3D12_HEAP_TYPE_READBACK, buffer_desc(row_pitch * height),
                                 D3D12_RESOURCE_STATE_COPY_DEST);
        }
        check(upload_args && count_buffer && staging && default_args && target && readback, "resources created");
        unsigned mismatches = ~0u;
        if (check.good) {
            Record* records = nullptr;
            check(SUCCEEDED(upload_args->Map(0, nullptr, reinterpret_cast<void**>(&records))), "Map(records)");
            const int valid[2] = {0, 1};
            write_records(records, title_va, valid, 2);
            for (int i = 2; i < 4; ++i) {  // never executed (count 2): addresses no range holds
                records[i].vbv = {0xdead0000ull, 48, 8};
                records[i].cbv = 0xbeef0000ull;
                records[i].draw = {6, 1, 0, 0};
            }
            upload_args->Unmap(0, nullptr);
            std::uint32_t* count = nullptr;
            check(SUCCEEDED(count_buffer->Map(0, nullptr, reinterpret_cast<void**>(&count))), "Map(count)");
            *count = 2;
            count_buffer->Unmap(0, nullptr);
            Record* staged = nullptr;
            check(SUCCEEDED(staging->Map(0, nullptr, reinterpret_cast<void**>(&staged))), "Map(staging)");
            const int third[1] = {2};
            write_records(staged, title_va, third, 1);
            staging->Unmap(0, nullptr);

            D3D12_DESCRIPTOR_HEAP_DESC hd{};
            hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
            hd.NumDescriptors = 1;
            ComPtr<ID3D12DescriptorHeap> rtv_heap;
            check(ok(gpu.device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&rtv_heap)), "CreateDescriptorHeap"), "rtv heap");
            const D3D12_CPU_DESCRIPTOR_HANDLE rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
            gpu.device->CreateRenderTargetView(target.Get(), nullptr, rtv);

            ID3D12GraphicsCommandList* list = gpu.list.Get();
            check(ok(gpu.allocator->Reset(), "allocator Reset") && ok(list->Reset(gpu.allocator.Get(), pso.Get()), "Reset"),
                  "list reset");
            list->CopyBufferRegion(default_args.Get(), 0, staging.Get(), 0, sizeof(Record));
            if (enhanced) {
                D3D12_BUFFER_BARRIER b{};
                b.SyncBefore = D3D12_BARRIER_SYNC_COPY;
                b.SyncAfter = D3D12_BARRIER_SYNC_EXECUTE_INDIRECT;
                b.AccessBefore = D3D12_BARRIER_ACCESS_COPY_DEST;
                b.AccessAfter = D3D12_BARRIER_ACCESS_INDIRECT_ARGUMENT;
                b.pResource = default_args.Get();
                b.Size = UINT64_MAX;
                D3D12_BARRIER_GROUP g{};
                g.Type = D3D12_BARRIER_TYPE_BUFFER;
                g.NumBarriers = 1;
                g.pBufferBarriers = &b;
                list7->Barrier(1, &g);
            } else {
                const D3D12_RESOURCE_BARRIER b = transition(default_args.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
                                                            D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT);
                list->ResourceBarrier(1, &b);
            }
            list->ClearRenderTargetView(rtv, clear.Color, 0, nullptr);
            list->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
            const D3D12_VIEWPORT viewport{0, 0, float(width), float(height), 0, 1};
            const D3D12_RECT scissor{0, 0, LONG(width), LONG(height)};
            list->RSSetViewports(1, &viewport);
            list->RSSetScissorRects(1, &scissor);
            list->SetGraphicsRootSignature(root.Get());
            list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            list->ExecuteIndirect(signature.Get(), 4, upload_args.Get(), 0, count_buffer.Get(), 0);
            list->ExecuteIndirect(signature.Get(), 1, default_args.Get(), 0, nullptr, 0);
            if (enhanced) {
                D3D12_TEXTURE_BARRIER t{};
                t.SyncBefore = D3D12_BARRIER_SYNC_RENDER_TARGET;
                t.SyncAfter = D3D12_BARRIER_SYNC_COPY;
                t.AccessBefore = D3D12_BARRIER_ACCESS_RENDER_TARGET;
                t.AccessAfter = D3D12_BARRIER_ACCESS_COPY_SOURCE;
                t.LayoutBefore = D3D12_BARRIER_LAYOUT_RENDER_TARGET;
                t.LayoutAfter = D3D12_BARRIER_LAYOUT_COPY_SOURCE;
                t.pResource = target.Get();
                t.Subresources.IndexOrFirstMipLevel = 0xffffffffu;  // all subresources
                D3D12_BARRIER_GROUP g{};
                g.Type = D3D12_BARRIER_TYPE_TEXTURE;
                g.NumBarriers = 1;
                g.pTextureBarriers = &t;
                list7->Barrier(1, &g);
            } else {
                const D3D12_RESOURCE_BARRIER b = transition(target.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET,
                                                            D3D12_RESOURCE_STATE_COPY_SOURCE);
                list->ResourceBarrier(1, &b);
            }
            D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
            dst.pResource = readback.Get();
            dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, width, height, 1, row_pitch};
            src.pResource = target.Get();
            src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
            check(ok(list->Close(), "Close"), "list closed");
            if (check.good) check(gpu.submit_and_wait(), "submitted");
            if (check.good) {
                const std::uint8_t* pixels = nullptr;
                const D3D12_RANGE all{0, row_pitch * height};
                if (SUCCEEDED(readback->Map(0, &all, (void**)&pixels))) {
                    mismatches = 0;
                    unsigned first = ~0u;
                    for (std::size_t i = 0; i < expected.size(); i += 4) {
                        if (std::memcmp(pixels + i, &expected[i], 4)) {
                            if (first == ~0u) first = unsigned(i / 4);
                            ++mismatches;
                        }
                    }
                    if (first != ~0u)
                        std::printf("first_mismatch=(%u,%u) got=%u,%u,%u,%u\n", first % width, first / width,
                                    pixels[first * 4], pixels[first * 4 + 1], pixels[first * 4 + 2], pixels[first * 4 + 3]);
                    const D3D12_RANGE none{0, 0};
                    readback->Unmap(0, &none);
                }
            }
        }
        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        X2WGfxSetLogSink(nullptr, nullptr);
        const unsigned long long rewrites = end.indirect_rewrites - start.indirect_rewrites;
        std::printf("mismatches=%u indirect_rewrites=%llu refused=%u draws_refused=%u debug_errors=%u mode=%s%s\n",
                    mismatches, rewrites, recorded.refused, end.draws_refused - start.draws_refused, debug_errors,
                    enhanced ? "enhanced" : "legacy", control ? "_wrong_reference" : "");
        check(rewrites == 2, "both ExecuteIndirect calls were rewritten");
        check(recorded.refused == 0 && debug_errors == 0, "no refusal and no debug-layer error");
        const unsigned swapped_pixels = 2 * 32 * 32;
        if (control) {
            std::printf("control=%s\n", mismatches == swapped_pixels ? "mismatch_detected" : "mismatch_missed");
            check(mismatches == swapped_pixels, "the wrong reference differs in exactly the swapped rectangles");
        } else {
            check(mismatches == 0, "the frame equals the reference");
        }
        rc = check.good ? 0 : 1;
    }
    XMemFree(title, graphics_word);
    const auto released = counters();
    std::printf("live_objects=%u\n", released.live_objects);
    return released.live_objects == 0 ? rc : 1;
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    const std::string_view adapter = argv[1], mode = argv[2];
    if (adapter != "warp" && adapter != "hardware") return 2;
    const bool warp = adapter == "warp";
    if (mode == "versions") return versions_check(warp);
    if (mode == "indirect") return indirect_check(warp, false, false);
    if (mode == "indirect_wrong_reference") return indirect_check(warp, false, true);
    if (mode == "enhanced") return indirect_check(warp, true, false);
    if (mode == "enhanced_wrong_reference") return indirect_check(warp, true, true);
    return 2;
}
