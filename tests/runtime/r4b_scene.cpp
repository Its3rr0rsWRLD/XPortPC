// Runtime ladder R4b (docs/design/runtime.md, section 6): vertex fetch through buffer V#s read from a descriptor
// table, pixel constant slots 2 and 3, and a pixel shader storing to title memory through a UAV's V#.
//
// A console-style program, as r4_scene.cpp: device, root signature, descriptor heap, views and pipeline come from
// d3d12_xs.dll, title memory from xmem.dll. The programs are assemblies of tests/runtime/r4b_*.s (r4b_programs.h)
// in the console container of d3d12_xs_api.h. One title allocation holds the vertex records, the colour records, 16
// constant buffers and the store target. The buffer views are created over the title-memory alias of that allocation
// (X2WTitleGpuLocate gives its desktop resource), as a title creates views over its own buffer resources: the shim
// encodes each buffer view's V# (base = the view's title GPU address) when the view is written.
//
// Each frame draws four quads, each with DrawInstanced(4, 1, 4k, 0) as a triangle strip and its own 7-descriptor
// table: [0] the positions (structured SRV, stride 24, FirstElement 1), [1] the colours (structured SRV, stride 20,
// NumElements 12, so quad 3's vertices are past num_records and read zero), [2] the store target (typed R32_UINT
// UAV, FirstElement 2, NumElements 3), [3..6] four CBVs at title addresses (pixel constant slots 0..3). The vertex
// program fetches x, y, z, w (dwordx4 at index base + id) and the colour (dwordx4 at offset 4 of its record). The
// pixel program exports red and green from the colour, blue and alpha from slots 0 and 1, and stores slot 3's word at
// the index in slot 2 (quad k: index k, so quad 3's store is past num_records and dropped).
//
//   r4b_scene warp|hardware cold             X2W_CACHE_DIR\r4b_scene emptied first: three translations (the vertex
//                                            program read-only, the pixel program, which stores, and the vertex
//                                            program again with title memory writable)
//   r4b_scene warp|hardware warm             after cold: all three from the on-disk cache
//   r4b_scene warp|hardware wrong_reference  control: green one step higher in every covered pixel and every stored
//                                            word one higher; passes only if exactly those pixels and words differ
//   r4b_scene warp|hardware missing_view     control: draw 1's position SRV is never created. One TextureLookup miss
//                                            per frame; quad 1 is not drawn (its positions read zero) and stores
//                                            nothing
//   r4b_scene warp|hardware wrong_format     control: the UAVs are R32_FLOAT views. A typed store through them is not
//                                            translated exactly, so every draw is refused (logged); the frame is the
//                                            clear colour and the store target is untouched
//
// Every mode renders two 64x64 R8G8B8A8_UNORM frames and compares every pixel and the store target's eight words
// (reset to a sentinel before each frame) with the CPU reference. Quads are pixel-aligned rectangles (no pixel centre
// on an edge), colours are k/255 (exported exactly as UNORM), and every value is a raw word, so the reference is
// exact. Also required: no debug-layer error, no unknown slot or IID, every wrapper released, no TitleLookup miss, and
// no refusal or TextureLookup miss beyond what the mode causes.
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "era_title_gpu_api.h"
#include "r4b_programs.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
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
constexpr UINT frames = 2;
constexpr UINT draws = 4;
constexpr std::uint8_t clear_rgba[4] = {16, 32, 48, 255};
constexpr SIZE_T title_bytes = 64 * 1024;
constexpr std::uint32_t sentinel = 0xdeadbeefu;

// The quads, in pixels (y down): size, position, and the four colour channels (k/255) of its pixels.
struct Quad {
    int w, h, x, y;
    std::uint8_t rgba[4];
    std::uint32_t stored;  // the word the pixel program stores at index k
};
constexpr Quad quads[draws] = {
    {16, 16, 4, 4, {200, 30, 90, 255}, 0x11111111u},
    {32, 16, 28, 4, {60, 220, 140, 180}, 0x2222abcdu},
    {24, 32, 4, 28, {120, 80, 250, 120}, 0x33330001u},
    {24, 24, 36, 32, {170, 110, 20, 60}, 0x4444fffeu},  // colours past num_records: red and green read zero
};

// Title memory layout.
constexpr std::size_t positions_offset = 0x0000;  // 17 records of 24 bytes: x, y, z, w, two junk words
constexpr UINT position_stride = 24;
constexpr std::size_t colours_offset = 0x03c0;    // 16 records of 20 bytes: junk, r, g, z, w (960 = 48 * 20)
constexpr UINT colour_stride = 20;
constexpr UINT colour_records = 12;               // the view's NumElements: quad 3's records are past it
constexpr std::size_t constants_offset = 0x1000;  // draw k, slot j at + 0x400 k + 0x100 j
constexpr std::size_t target_offset = 0x3000;     // 8 words; the UAV covers words 2..4
constexpr UINT target_first = 2, target_count = 3, target_words = 8;

constexpr UINT root_table = 0;
constexpr UINT table_size = 7;

std::vector<std::uint8_t> container(X2WShaderStage stage, const std::uint8_t* code, std::size_t bytes,
                                    const std::vector<X2WShaderBinding>& bindings)
{
    X2WShaderContainer header{};
    header.magic = X2W_SHADER_CONTAINER_MAGIC;
    header.version = X2W_SHADER_CONTAINER_VERSION;
    header.stage = stage;
    header.binding_count = static_cast<std::uint32_t>(bindings.size());
    header.binding_offset = sizeof(header);
    header.code_offset = static_cast<std::uint32_t>(sizeof(header) + bindings.size() * sizeof(X2WShaderBinding));
    header.code_bytes = static_cast<std::uint32_t>(bytes);
    std::vector<std::uint8_t> out(header.code_offset + bytes);
    std::memcpy(out.data(), &header, sizeof(header));
    std::memcpy(out.data() + sizeof(header), bindings.data(), bindings.size() * sizeof(bindings[0]));
    std::memcpy(out.data() + header.code_offset, code, bytes);
    return out;
}

// The entry SGPRs of r4b_vs.s and r4b_ps.s: both stages read the draw's one table.
std::vector<X2WShaderBinding> vertex_bindings()
{
    return {{2, X2W_SHADER_BINDING_BASE_VERTEX, 0, 0}, {4, X2W_SHADER_BINDING_TABLE, root_table, 0}};
}
std::vector<X2WShaderBinding> pixel_bindings()
{
    return {{2, X2W_SHADER_BINDING_INTERP, 0, 0}, {3, X2W_SHADER_BINDING_TABLE, root_table, 0}};
}

// The reference frame and store target. `absent` (a draw index or -1) is not drawn; `bump` is added to the green of
// every covered pixel and to every stored word; `nothing` draws no quad.
std::vector<std::uint8_t> reference(int absent, int bump, bool nothing, unsigned& covered,
                                    std::uint32_t (&target)[target_words])
{
    std::vector<std::uint8_t> out(static_cast<std::size_t>(width) * height * 4);
    for (std::size_t p = 0; p < out.size() / 4; ++p) std::memcpy(&out[4 * p], clear_rgba, 4);
    for (auto& word : target) word = sentinel;
    covered = 0;
    for (UINT k = 0; k < draws && !nothing; ++k) {
        if (static_cast<int>(k) == absent) continue;
        const Quad& q = quads[k];
        std::uint8_t rgba[4];
        std::memcpy(rgba, q.rgba, 4);
        if (k == 3) rgba[0] = rgba[1] = 0;  // its colour records are past the view's num_records
        rgba[1] = static_cast<std::uint8_t>(rgba[1] + bump);
        for (int py = q.y; py < q.y + q.h; ++py)
            for (int px = q.x; px < q.x + q.w; ++px) {
                std::memcpy(&out[(static_cast<std::size_t>(py) * width + px) * 4], rgba, 4);
                ++covered;
            }
        if (k < target_count) target[target_first + k] = q.stored + static_cast<std::uint32_t>(bump);
    }
    return out;
}

ComPtr<ID3D12RootSignature> title_root_signature(ID3D12Device* device)
{
    D3D12_DESCRIPTOR_RANGE1 ranges[3]{};
    ranges[0] = {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 2, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 0};
    ranges[1] = {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 2};
    ranges[2] = {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 4, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 3};
    D3D12_ROOT_PARAMETER1 param{};
    param.ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    param.DescriptorTable = {3, ranges};
    param.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = 1;
    desc.Desc_1_1.pParameters = &param;
    desc.Desc_1_1.Flags = D3D12_ROOT_SIGNATURE_FLAG_DENY_HULL_SHADER_ROOT_ACCESS |
                          D3D12_ROOT_SIGNATURE_FLAG_DENY_DOMAIN_SHADER_ROOT_ACCESS |
                          D3D12_ROOT_SIGNATURE_FLAG_DENY_GEOMETRY_SHADER_ROOT_ACCESS;
    ComPtr<ID3DBlob> blob, errors;
    if (!ok(D3D12SerializeVersionedRootSignature(&desc, &blob, &errors), "D3D12SerializeVersionedRootSignature")) {
        if (errors) std::fprintf(stderr, "%s\n", static_cast<const char*>(errors->GetBufferPointer()));
        return {};
    }
    ComPtr<ID3D12RootSignature> root;
    if (!ok(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)),
            "CreateRootSignature"))
        return {};
    return root;
}

HRESULT create_pipeline(ID3D12Device* device, ID3D12RootSignature* root, ComPtr<ID3D12PipelineState>& pso)
{
    const auto vs = container(X2W_SHADER_STAGE_VERTEX, r4b_vs, sizeof(r4b_vs), vertex_bindings());
    const auto ps = container(X2W_SHADER_STAGE_PIXEL, r4b_ps, sizeof(r4b_ps), pixel_bindings());
    D3D12_GRAPHICS_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root;
    desc.VS = {vs.data(), vs.size()};
    desc.PS = {ps.data(), ps.size()};
    desc.BlendState.RenderTarget[0].RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    desc.SampleMask = 0xffffffffu;
    desc.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    desc.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    desc.RasterizerState.DepthClipEnable = TRUE;
    desc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    desc.NumRenderTargets = 1;
    desc.RTVFormats[0] = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    return device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso));
}

std::wstring cache_directory()
{
    wchar_t root[1024];
    const DWORD n = GetEnvironmentVariableW(L"X2W_CACHE_DIR", root, 1024);
    if (!n || n >= 1024) return {};
    return std::wstring(root) + L"\\r4b_scene";
}

unsigned count_files(const std::wstring& dir, const wchar_t* pattern, bool remove)
{
    WIN32_FIND_DATAW found;
    HANDLE find = FindFirstFileW((dir + L"\\" + pattern).c_str(), &found);
    if (find == INVALID_HANDLE_VALUE) return 0;
    unsigned count = 0;
    do {
        if (remove) DeleteFileW((dir + L"\\" + found.cFileName).c_str());
        ++count;
    } while (FindNextFileW(find, &found));
    FindClose(find);
    return count;
}

struct Recorded {
    unsigned refused = 0;
    std::string details;
};

void WINAPI record(const X2WGfxEvent* event, void* context)
{
    if (event->kind == X2W_GFX_EVENT_FIRST_USE) return;
    std::fprintf(stderr, "[sink] %s %s\n", event->symbol, event->detail);
    auto* recorded = static_cast<Recorded*>(context);
    if (event->kind == X2W_GFX_EVENT_REFUSED) ++recorded->refused;
    recorded->details += event->detail;
    recorded->details += '\n';
}

ComPtr<ID3D12Resource> readback_buffer(ID3D12Device* device, UINT64 bytes)
{
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    desc.Width = bytes;
    desc.Height = 1;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.SampleDesc.Count = 1;
    desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> out;
    ok(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                       IID_PPV_ARGS(&out)),
       "CreateCommittedResource(readback)");
    return out;
}

struct Scene {
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pso;
    ComPtr<ID3D12DescriptorHeap> views, rtv_heap;
    ComPtr<ID3D12Resource> readback;
    ComPtr<IDXGISwapChain3> chain;
    HWND window = nullptr;
    ~Scene()
    {
        chain.Reset();
        if (window) DestroyWindow(window);
    }
};

bool create_scene(Gpu& gpu, Scene& s, std::uint8_t* title, bool skip_view, bool float_uav)
{
    ID3D12Device* device = gpu.device.Get();
    D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, draws * table_size,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.views)), "CreateDescriptorHeap(views)")) return false;
    hd = {D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 1, D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.rtv_heap)), "CreateDescriptorHeap(rtv)")) return false;
    const UINT view_step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    if (view_step != 32) return false;
    s.readback = readback_buffer(device, static_cast<UINT64>(row_pitch) * height);
    if (!s.readback) return false;

    // The title's buffer resource: the desktop alias of its allocation.
    const std::uint64_t base = reinterpret_cast<std::uintptr_t>(title);
    ID3D12Resource* raw = nullptr;
    std::uint64_t alias_offset = 0;
    if (!ok(X2WTitleGpuLocate(base, title_bytes, reinterpret_cast<void**>(&raw), &alias_offset), "X2WTitleGpuLocate"))
        return false;
    ComPtr<ID3D12Resource> buffer;
    buffer.Attach(raw);
    std::printf("alias_offset=%llu\n", static_cast<unsigned long long>(alias_offset));
    if (alias_offset != 0) return false;  // the allocation starts its alias, so element offsets are title offsets

    const D3D12_CPU_DESCRIPTOR_HANDLE start = s.views->GetCPUDescriptorHandleForHeapStart();
    const auto at = [&](UINT index) { return D3D12_CPU_DESCRIPTOR_HANDLE{start.ptr + SIZE_T(index) * view_step}; };
    for (UINT k = 0; k < draws; ++k) {
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = DXGI_FORMAT_UNKNOWN;
        srv.ViewDimension = D3D12_SRV_DIMENSION_BUFFER;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        if (!(skip_view && k == 1)) {
            srv.Buffer.FirstElement = positions_offset / position_stride + 1;
            srv.Buffer.NumElements = 4 * draws;
            srv.Buffer.StructureByteStride = position_stride;
            device->CreateShaderResourceView(buffer.Get(), &srv, at(table_size * k));
        }
        srv.Buffer.FirstElement = colours_offset / colour_stride;
        srv.Buffer.NumElements = colour_records;
        srv.Buffer.StructureByteStride = colour_stride;
        device->CreateShaderResourceView(buffer.Get(), &srv, at(table_size * k + 1));
        D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
        uav.Format = float_uav ? DXGI_FORMAT_R32_FLOAT : DXGI_FORMAT_R32_UINT;
        uav.ViewDimension = D3D12_UAV_DIMENSION_BUFFER;
        uav.Buffer.FirstElement = target_offset / 4 + target_first;
        uav.Buffer.NumElements = target_count;
        device->CreateUnorderedAccessView(buffer.Get(), nullptr, &uav, at(table_size * k + 2));
        for (UINT j = 0; j < 4; ++j) {
            const D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{base + constants_offset + 0x400 * k + 0x100 * j, 256};
            device->CreateConstantBufferView(&cbv, at(table_size * k + 3 + j));
        }
    }
    // The shim writes each buffer view's V# into the heap's title memory: check the position V# of draw 0.
    std::uint32_t words[4];
    std::memcpy(words, reinterpret_cast<const void*>(start.ptr), sizeof(words));
    const std::uint64_t first = base + positions_offset + position_stride;
    std::printf("position_vsharp=%08x %08x %08x %08x\n", words[0], words[1], words[2], words[3]);
    if (words[0] != static_cast<std::uint32_t>(first) ||
        words[1] != (static_cast<std::uint32_t>(first >> 32) | position_stride << 16) || words[2] != 4 * draws ||
        (words[3] >> 28 & 3) != 0)
        return false;

    s.window = make_window(width, height);
    if (!s.window) return false;
    DXGI_SWAP_CHAIN_DESC1 desc{};
    desc.Width = width;
    desc.Height = height;
    desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2;
    desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
    return ok(X2WGfxCreateSwapChainForHwnd(gpu.queue.Get(), s.window, &desc, nullptr, nullptr, IID_PPV_ARGS(&s.chain)),
              "X2WGfxCreateSwapChainForHwnd");
}

// Draws one frame and counts the pixels and store-target words that differ from the reference.
bool draw_frame(Gpu& gpu, Scene& s, std::uint8_t* title, const std::vector<std::uint8_t>& expected,
                const std::uint32_t (&target)[target_words], unsigned& mismatches, unsigned& word_mismatches)
{
    ID3D12Device* device = gpu.device.Get();
    auto* words = reinterpret_cast<std::uint32_t*>(title + target_offset);
    for (UINT i = 0; i < target_words; ++i) words[i] = sentinel;
    const UINT index = s.chain->GetCurrentBackBufferIndex();
    ComPtr<ID3D12Resource> back;
    if (!ok(s.chain->GetBuffer(index, IID_PPV_ARGS(&back)), "GetBuffer")) return false;
    const D3D12_CPU_DESCRIPTOR_HANDLE rtv = s.rtv_heap->GetCPUDescriptorHandleForHeapStart();
    device->CreateRenderTargetView(back.Get(), nullptr, rtv);
    if (!ok(gpu.allocator->Reset(), "allocator Reset") ||
        !ok(gpu.list->Reset(gpu.allocator.Get(), s.pso.Get()), "list Reset"))
        return false;
    ID3D12GraphicsCommandList* list = gpu.list.Get();
    auto barrier = transition(back.Get(), D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_RENDER_TARGET);
    list->ResourceBarrier(1, &barrier);
    const FLOAT clear[4] = {clear_rgba[0] / 255.0f, clear_rgba[1] / 255.0f, clear_rgba[2] / 255.0f, 1.0f};
    list->ClearRenderTargetView(rtv, clear, 0, nullptr);
    list->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
    const D3D12_VIEWPORT viewport{0, 0, float(width), float(height), 0, 1};
    const D3D12_RECT scissor{0, 0, LONG(width), LONG(height)};
    list->RSSetViewports(1, &viewport);
    list->RSSetScissorRects(1, &scissor);
    ID3D12DescriptorHeap* heaps[1] = {s.views.Get()};
    list->SetDescriptorHeaps(1, heaps);
    list->SetGraphicsRootSignature(s.root.Get());
    list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP);
    const D3D12_GPU_DESCRIPTOR_HANDLE table = s.views->GetGPUDescriptorHandleForHeapStart();
    const UINT step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    for (UINT k = 0; k < draws; ++k) {
        list->SetGraphicsRootDescriptorTable(root_table, {table.ptr + UINT64(table_size) * k * step});
        list->DrawInstanced(4, 1, 4 * k, 0);
    }
    barrier = transition(back.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
    list->ResourceBarrier(1, &barrier);
    D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
    dst.pResource = s.readback.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, width, height, 1, row_pitch};
    src.pResource = back.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    barrier = transition(back.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_PRESENT);
    list->ResourceBarrier(1, &barrier);
    if (!ok(list->Close(), "Close") || !gpu.submit_and_wait()) return false;

    void* mapped = nullptr;
    const D3D12_RANGE read{0, static_cast<SIZE_T>(row_pitch) * height};
    if (!ok(s.readback->Map(0, &read, &mapped), "Map")) return false;
    mismatches = 0;
    std::uint32_t first = 0, want = 0, first_at = 0;
    for (UINT y = 0; y < height; ++y) {
        const auto* row = static_cast<const std::uint8_t*>(mapped) + static_cast<SIZE_T>(y) * row_pitch;
        for (UINT x = 0; x < width; ++x) {
            const std::uint8_t* expect = &expected[(static_cast<std::size_t>(y) * width + x) * 4];
            if (std::memcmp(row + x * 4, expect, 4) != 0) {
                if (!mismatches) {
                    std::memcpy(&first, row + x * 4, 4);
                    std::memcpy(&want, expect, 4);
                    first_at = y * width + x;
                }
                ++mismatches;
            }
        }
    }
    const D3D12_RANGE none{0, 0};
    s.readback->Unmap(0, &none);
    // The store target is title memory: the CPU sees the GPU's writes once the work has completed.
    word_mismatches = 0;
    std::printf("target=");
    for (UINT i = 0; i < target_words; ++i) {
        std::printf("%08x%s", words[i], i + 1 < target_words ? " " : "\n");
        word_mismatches += words[i] != target[i];
    }
    std::printf("mismatches=%u word_mismatches=%u", mismatches, word_mismatches);
    if (mismatches)
        std::printf(" first_pixel=(%u,%u) got=%08x want=%08x", first_at % width, first_at / width,
                    static_cast<unsigned>(first), static_cast<unsigned>(want));
    std::printf("\n");
    const HRESULT present = s.chain->Present(0, 0);
    std::printf("present=0x%08lx\n", static_cast<unsigned long>(present));
    return SUCCEEDED(present);
}

int scene_check(bool warp, std::string_view mode)
{
    const bool cold = mode == "cold", warm = mode == "warm", wrong = mode == "wrong_reference";
    const bool missing_view = mode == "missing_view", wrong_format = mode == "wrong_format";
    const std::wstring cache = cache_directory();
    if (cache.empty()) {
        std::fputs("r4b: X2W_CACHE_DIR must name the test's cache root\n", stderr);
        return 1;
    }
    if (cold) {
        count_files(cache, L"*.dxil", true);
        count_files(cache, L"*.bind", true);
    }
    unsigned covered = 0;
    std::uint32_t target[target_words];
    const auto expected = reference(missing_view ? 1 : -1, wrong ? 1 : 0, wrong_format, covered, target);
    unsigned stored = 0;
    for (auto word : target) stored += word != sentinel;
    std::printf("covered_pixels=%u stored_words=%u\n", covered, stored);

    auto* title = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    if (!title) {
        std::fputs("r4b: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    std::memset(title, 0, title_bytes);
    // Junk around the records: a reader that ignores the stride, FirstElement or the record offset reads it.
    for (std::size_t i = 0; i < 0x1000; i += 4) {
        const std::uint32_t junk = 0x7fc00000u | static_cast<std::uint32_t>(i);
        std::memcpy(title + i, &junk, 4);
    }
    for (UINT k = 0; k < draws; ++k) {
        const Quad& q = quads[k];
        const float corners[4][2] = {{float(q.x), float(q.y)}, {float(q.x + q.w), float(q.y)},
                                     {float(q.x), float(q.y + q.h)}, {float(q.x + q.w), float(q.y + q.h)}};
        for (int v = 0; v < 4; ++v) {
            // Clip coordinates (multiples of 1/32, exact in binary32), records from FirstElement 1.
            const float position[4] = {corners[v][0] / 32.0f - 1.0f, 1.0f - corners[v][1] / 32.0f, 0.5f, 1.0f};
            std::memcpy(title + positions_offset + position_stride * (1 + 4 * k + v), position, sizeof(position));
            const float colour[4] = {q.rgba[0] / 255.0f, q.rgba[1] / 255.0f, 0.25f, 0.75f};
            std::memcpy(title + colours_offset + colour_stride * (4 * k + v) + 4, colour, sizeof(colour));
        }
        for (UINT j = 0; j < 4; ++j) {
            std::uint32_t cb[64];
            for (UINT w = 0; w < 64; ++w) cb[w] = 0x5a000000u | (k << 16) | (j << 8) | w;  // junk words
            const float blue = q.rgba[2] / 255.0f, alpha = q.rgba[3] / 255.0f;
            if (j == 0) std::memcpy(&cb[0], &blue, 4);
            if (j == 1) std::memcpy(&cb[1], &alpha, 4);
            if (j == 2) cb[2] = k;
            if (j == 3) cb[3] = q.stored;
            std::memcpy(title + constants_offset + 0x400 * k + 0x100 * j, cb, sizeof(cb));
        }
    }

    Recorded recorded;
    int rc = 1;
    {
        Gpu gpu;
        const int created = gpu.create(warp);
        if (created) {
            XMemFree(title, graphics_word);
            return created;
        }
        X2WGfxSetLogSink(record, &recorded);
        const auto start = counters();
        bool good = start.title_gpu_state == X2W_GFX_TITLE_GPU_ATTACHED;
        std::printf("title_gpu_state=%d mode=%s\n", start.title_gpu_state, std::string(mode).c_str());
        {
            Scene scene;
            scene.root = title_root_signature(gpu.device.Get());
            const HRESULT hr = scene.root ? create_pipeline(gpu.device.Get(), scene.root.Get(), scene.pso) : E_FAIL;
            std::printf("pso_hr=0x%08lx\n", static_cast<unsigned long>(hr));
            good = good && SUCCEEDED(hr) && create_scene(gpu, scene, title, missing_view, wrong_format);
            unsigned frame_mismatch[frames] = {}, word_mismatch[frames] = {};
            for (UINT f = 0; good && f < frames; ++f)
                good = draw_frame(gpu, scene, title, expected, target, frame_mismatch[f], word_mismatch[f]);
            for (UINT f = 0; f < frames; ++f)
                good = good && frame_mismatch[f] == (wrong ? covered : 0) && word_mismatch[f] == (wrong ? stored : 0);
            if (wrong) std::printf("control=%s\n", good ? "mismatch_detected" : "mismatch_missed");
            gpu.list->Reset(gpu.allocator.Get(), nullptr);
            gpu.list->Close();
            good = gpu.submit_and_wait() && good;
        }
        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        const unsigned translated = end.shaders_translated - start.shaders_translated;
        const unsigned cached = end.shaders_cached - start.shaders_cached;
        const unsigned dxil = count_files(cache, L"*.dxil", false), bind = count_files(cache, L"*.bind", false);
        const unsigned long long title_misses = end.title_lookup_misses - start.title_lookup_misses;
        const unsigned long long texture_misses = end.texture_lookup_misses - start.texture_lookup_misses;
        const unsigned draws_refused = end.draws_refused - start.draws_refused;
        std::printf("shaders_translated=%u shaders_cached=%u cache_files=%u+%u refused=%u draws_refused=%u "
                    "title_lookup_misses=%llu texture_lookup_misses=%llu debug_errors=%u unknown_slots=%llu "
                    "unknown_iids=%llu\n",
                    translated, cached, dxil, bind, recorded.refused, draws_refused, title_misses, texture_misses,
                    debug_errors, static_cast<unsigned long long>(end.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls));
        // Three translations: the vertex program read-only, the pixel program (which stores), and the vertex program
        // again with title memory writable (d3d12_xs_pipeline.cpp, create_graphics_pipeline).
        good = good && debug_errors == 0 && end.unknown_slot_calls == 0 && end.unknown_iid_calls == 0 && dxil == 3 &&
               bind == 3 && title_misses == 0 && end.pipelines_refused == start.pipelines_refused;
        if (cold) good = good && translated == 3 && cached == 0;
        if (warm) good = good && translated == 0 && cached == 3;
        good = good && texture_misses == (missing_view ? frames : 0);
        if (missing_view) good = good && recorded.details.find("TextureLookup miss") != std::string::npos;
        if (wrong_format) {
            good = good && draws_refused == draws * frames && recorded.refused == draws * frames &&
                   recorded.details.find("accessed typed") != std::string::npos;
        } else {
            good = good && draws_refused == 0 && recorded.refused == 0;
        }
        rc = good ? 0 : 1;
        X2WGfxSetLogSink(nullptr, nullptr);
    }
    XMemFree(title, graphics_word);
    const auto released = counters();
    std::printf("live_objects=%u result=%s\n", released.live_objects, rc == 0 && !released.live_objects ? "pass" : "fail");
    return released.live_objects == 0 ? rc : 1;
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    const std::string_view adapter = argv[1];
    const std::string_view mode = argv[2];
    if (adapter != "warp" && adapter != "hardware") return 2;
    if (mode == "cold" || mode == "warm" || mode == "wrong_reference" || mode == "missing_view" ||
        mode == "wrong_format")
        return scene_check(adapter == "warp", mode);
    return 2;
}
