// Runtime ladder R4 (docs/design/runtime.md, section 6): a textured, constant-buffered, depth-tested scene of several
// draws, translated by the graphics shim at pipeline creation.
//
// A console-style program, as r3_triangle.cpp: device, root signature, descriptor heaps, views, textures and pipeline
// come from d3d12_xs.dll, title memory from xmem.dll. The programs are llvm-mc 15 assemblies of tests/runtime/r4_*.s
// (r4_programs.h) in the console container of d3d12_xs_api.h. Each frame draws three quads with DrawIndexedInstanced
// from one vertex buffer and one index buffer in title memory, each with its own base vertex (the quad's four
// vertices) and start instance (its depth in a second title allocation, read by the instance index). Per draw, the
// title points a descriptor table at three descriptors of its shader-visible CBV/SRV/UAV heap: the vertex program's
// constant buffer (the quad's offset), the texture and the pixel program's constant buffer (a tint), both CBVs at
// title GPU addresses; a second table holds the point sampler. The pixel program samples the texture through the T#
// and S#, scales it by the tint and takes alpha from a root constant. Depth test LESS on a D32_FLOAT buffer.
//
//   r4_scene warp|hardware cold             X2W_CACHE_DIR\r4_scene emptied first: both shaders translated
//   r4_scene warp|hardware warm             after cold: both shaders from the on-disk cache
//   r4_scene warp|hardware wrong_reference  control: green one step higher in every covered pixel of the reference;
//                                           passes only if exactly the covered pixels differ
//   r4_scene warp|hardware missing_view     control: the texture view of draw 1 is never created. Each frame must
//                                           report one TextureLookup miss and equal the reference in which draw 1
//                                           samples zero (black, its alpha unchanged)
//   r4_scene warp|hardware missing_memory   control: the depth allocation is freed before drawing, so its loads miss
//                                           in TitleLookup. TitleLookup misses must be reported and the frame equal
//                                           the reference in which every draw has depth 0
//
// Every mode renders two 64x64 R8G8B8A8_UNORM frames (clear colour and depth, three draws, read back, present) and
// compares every pixel with the CPU reference. The reference is exact: quads are pixel-aligned rectangles (no pixel
// centre on an edge), each texel covers at least 3x3 pixels with sample points at least 1/6 texel from its edges,
// texels are even (so a tint of 0.5 halves them exactly), and depths are 0.25, 0.5 and 0.75. Also required in every
// mode: no refusal, no debug-layer error, no unknown slot or IID, every wrapper released, and zero lookup misses of the
// kind the mode does not cause.
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "era_title_gpu_api.h"
#include "r4_programs.h"

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
constexpr UINT draws = 3;
constexpr UINT texels = 8;  // 8x8 textures
constexpr std::uint8_t clear_rgba[4] = {10, 20, 30, 255};
constexpr SIZE_T title_bytes = 64 * 1024;

// The quads, in pixels (y down): size, position, texture, u flipped, depth (from the instance data), tint, alpha.
struct Quad {
    int w, h, x, y;
    int texture;
    bool flip;
    float depth;
    float tint[3];
    std::uint8_t alpha;
};
constexpr Quad quads[draws] = {
    {32, 32, 8, 8, 0, false, 0.5f, {1.0f, 0.5f, 1.0f}, 100},
    {32, 32, 20, 14, 1, true, 0.25f, {0.5f, 1.0f, 1.0f}, 150},
    {24, 32, 28, 24, 0, false, 0.75f, {1.0f, 1.0f, 0.5f}, 200},
};

// Title memory A: constants, vertex and index buffers. CBVs are 256-byte aligned.
constexpr std::size_t vs_constants_offset = 0x0000;  // draw k at + 256 k: float2 offset (clip units)
constexpr std::size_t ps_constants_offset = 0x0400;  // draw k at + 512 k: a 512-byte CBV, its float4 tint at + 0x110
constexpr std::size_t ps_constants_bytes = 512, ps_tint_offset = 0x110;
constexpr std::size_t vertices_offset = 0x1000;      // 4 vertices per quad: float4 (x, y, u, v)
constexpr std::size_t indices_offset = 0x1200;       // 6 uint16
// Title memory B: the depth of instance k at 16 k.

// The title's root signature.
constexpr UINT root_table = 0;      // table: CBV b0, SRV t0, CBV b1 (one per draw, 3 descriptors)
constexpr UINT root_samplers = 1;   // table: sampler s0
constexpr UINT root_vertices = 2;   // root SRV t1: the vertex buffer (title address)
constexpr UINT root_instances = 3;  // 2 root constants b2: title address of the instance depths
constexpr UINT root_alpha = 4;      // 1 root constant b3: the alpha (binary32)
constexpr UINT table_size = 3;

std::uint8_t texel(int texture, int tx, int ty, int c)
{
    return static_cast<std::uint8_t>(2 * ((tx * 29 + ty * 13 + c * 7 + texture * 61) % 128));
}

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

// The entry SGPRs of r4_vs.s and r4_ps.s.
std::vector<X2WShaderBinding> vertex_bindings()
{
    return {{2, X2W_SHADER_BINDING_ROOT_WORD, root_vertices, 0},
            {3, X2W_SHADER_BINDING_ROOT_WORD, root_vertices, 1},
            {4, X2W_SHADER_BINDING_BASE_VERTEX, 0, 0},
            {5, X2W_SHADER_BINDING_START_INSTANCE, 0, 0},
            {6, X2W_SHADER_BINDING_TABLE, root_table, 0},
            {8, X2W_SHADER_BINDING_ROOT_WORD, root_instances, 0},
            {9, X2W_SHADER_BINDING_ROOT_WORD, root_instances, 1}};
}
std::vector<X2WShaderBinding> pixel_bindings()
{
    return {{2, X2W_SHADER_BINDING_INTERP, 0, 0},
            {3, X2W_SHADER_BINDING_TABLE, root_table, 0},
            {4, X2W_SHADER_BINDING_TABLE, root_samplers, 0},
            {5, X2W_SHADER_BINDING_ROOT_WORD, root_alpha, 0}};
}

// The reference frame. `depths` replaces the quads' depths, `black` (a draw index or -1) samples zero for one draw,
// `green` is added to the green of every covered pixel.
std::vector<std::uint8_t> reference(const float (&depths)[draws], int black, int green, unsigned& covered)
{
    std::vector<std::uint8_t> out(static_cast<std::size_t>(width) * height * 4);
    std::vector<float> depth(static_cast<std::size_t>(width) * height, 1.0f);
    std::vector<bool> hit(depth.size());
    for (std::size_t p = 0; p < depth.size(); ++p) std::memcpy(&out[4 * p], clear_rgba, 4);
    for (UINT k = 0; k < draws; ++k) {
        const Quad& q = quads[k];
        for (int py = q.y; py < q.y + q.h; ++py) {
            for (int px = q.x; px < q.x + q.w; ++px) {
                const std::size_t p = static_cast<std::size_t>(py) * width + px;
                if (!(depths[k] < depth[p])) continue;
                depth[p] = depths[k];
                hit[p] = true;
                // Pixel centre (px + 0.5) maps to u = (px - x + 0.5) / w; the texel is floor(u * 8), mirrored when
                // flipped (u' = 1 - u, never on a texel edge here).
                int tx = ((2 * (px - q.x) + 1) * static_cast<int>(texels)) / (2 * q.w);
                const int ty = ((2 * (py - q.y) + 1) * static_cast<int>(texels)) / (2 * q.h);
                if (q.flip) tx = static_cast<int>(texels) - 1 - tx;
                for (int c = 0; c < 3; ++c) {
                    const int value = static_cast<int>(k) == black ? 0 : texel(q.texture, tx, ty, c);
                    out[4 * p + c] = static_cast<std::uint8_t>(q.tint[c] == 1.0f ? value : value / 2);
                }
                out[4 * p + 3] = q.alpha;
            }
        }
    }
    covered = 0;
    for (std::size_t p = 0; p < depth.size(); ++p) {
        if (!hit[p]) continue;
        ++covered;
        out[4 * p + 1] = static_cast<std::uint8_t>(out[4 * p + 1] + green);
    }
    return out;
}

ComPtr<ID3D12RootSignature> title_root_signature(ID3D12Device* device)
{
    D3D12_DESCRIPTOR_RANGE1 ranges[table_size]{};
    ranges[0] = {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 0};
    ranges[1] = {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 1};
    ranges[2] = {D3D12_DESCRIPTOR_RANGE_TYPE_CBV, 1, 1, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 2};
    D3D12_DESCRIPTOR_RANGE1 sampler{D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_NONE, 0};
    D3D12_ROOT_PARAMETER1 params[5]{};
    params[root_table].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[root_table].DescriptorTable = {table_size, ranges};
    params[root_table].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    params[root_samplers].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[root_samplers].DescriptorTable = {1, &sampler};
    params[root_samplers].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    params[root_vertices].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
    params[root_vertices].Descriptor = {1, 0, D3D12_ROOT_DESCRIPTOR_FLAG_NONE};
    params[root_vertices].ShaderVisibility = D3D12_SHADER_VISIBILITY_VERTEX;
    params[root_instances].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[root_instances].Constants = {2, 0, 2};
    params[root_instances].ShaderVisibility = D3D12_SHADER_VISIBILITY_VERTEX;
    params[root_alpha].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[root_alpha].Constants = {3, 0, 1};
    params[root_alpha].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = 5;
    desc.Desc_1_1.pParameters = params;
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

double seconds_since(const LARGE_INTEGER& start)
{
    LARGE_INTEGER now, frequency;
    QueryPerformanceCounter(&now);
    QueryPerformanceFrequency(&frequency);
    return double(now.QuadPart - start.QuadPart) / double(frequency.QuadPart);
}

HRESULT create_pipeline(ID3D12Device* device, ID3D12RootSignature* root, ComPtr<ID3D12PipelineState>& pso, double* ms)
{
    const auto vs = container(X2W_SHADER_STAGE_VERTEX, r4_vs, sizeof(r4_vs), vertex_bindings());
    const auto ps = container(X2W_SHADER_STAGE_PIXEL, r4_ps, sizeof(r4_ps), pixel_bindings());
    D3D12_GRAPHICS_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root;
    desc.VS = {vs.data(), vs.size()};
    desc.PS = {ps.data(), ps.size()};
    desc.BlendState.RenderTarget[0].RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    desc.SampleMask = 0xffffffffu;
    desc.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    desc.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    desc.RasterizerState.DepthClipEnable = TRUE;
    desc.DepthStencilState.DepthEnable = TRUE;
    desc.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ALL;
    desc.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_LESS;
    desc.DSVFormat = DXGI_FORMAT_D32_FLOAT;
    desc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    desc.NumRenderTargets = 1;
    desc.RTVFormats[0] = DXGI_FORMAT_R8G8B8A8_UNORM;
    desc.SampleDesc.Count = 1;
    LARGE_INTEGER start;
    QueryPerformanceCounter(&start);
    const HRESULT hr = device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso));
    if (ms) *ms = 1000.0 * seconds_since(start);
    return hr;
}

std::wstring cache_directory()
{
    wchar_t root[1024];
    const DWORD n = GetEnvironmentVariableW(L"X2W_CACHE_DIR", root, 1024);
    if (!n || n >= 1024) return {};
    return std::wstring(root) + L"\\r4_scene";
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
    unsigned notes = 0;
    std::string details;
};

void WINAPI record(const X2WGfxEvent* event, void* context)
{
    if (event->kind == X2W_GFX_EVENT_FIRST_USE) return;
    std::fprintf(stderr, "[sink] %s %s\n", event->symbol, event->detail);
    auto* recorded = static_cast<Recorded*>(context);
    if (event->kind == X2W_GFX_EVENT_REFUSED) ++recorded->refused;
    if (event->kind == X2W_GFX_EVENT_NOTE) ++recorded->notes;
    recorded->details += event->detail;
    recorded->details += '\n';
}

ComPtr<ID3D12Resource> buffer(ID3D12Device* device, D3D12_HEAP_TYPE type, UINT64 bytes, D3D12_RESOURCE_STATES state)
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
    ComPtr<ID3D12Resource> out;
    ok(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr, IID_PPV_ARGS(&out)),
       "CreateCommittedResource(buffer)");
    return out;
}

// The scene's GPU objects, created through the shim as a title creates them.
struct Scene {
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pso;
    ComPtr<ID3D12DescriptorHeap> views, samplers, rtv_heap, dsv_heap;
    ComPtr<ID3D12Resource> textures[2], upload, depth, readback;
    ComPtr<IDXGISwapChain3> chain;
    HWND window = nullptr;
    ~Scene()
    {
        chain.Reset();
        if (window) DestroyWindow(window);
    }
};

bool create_scene(Gpu& gpu, Scene& s, std::uint8_t* title, bool skip_view)
{
    ID3D12Device* device = gpu.device.Get();
    // Heaps: the title's CBV/SRV/UAV and sampler heaps (shader visible), desktop RTV and DSV heaps.
    D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, draws * table_size,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.views)), "CreateDescriptorHeap(views)")) return false;
    hd = {D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER, 1, D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.samplers)), "CreateDescriptorHeap(samplers)")) return false;
    hd = {D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 1, D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.rtv_heap)), "CreateDescriptorHeap(rtv)")) return false;
    hd = {D3D12_DESCRIPTOR_HEAP_TYPE_DSV, 1, D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.dsv_heap)), "CreateDescriptorHeap(dsv)")) return false;
    const UINT view_step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    const UINT sampler_step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER);
    std::printf("increments view=%u sampler=%u\n", view_step, sampler_step);
    if (view_step != 32 || sampler_step != 16) return false;

    // Textures: 8x8 R8G8B8A8_UNORM, uploaded row by row through an upload buffer.
    constexpr UINT texture_pitch = D3D12_TEXTURE_DATA_PITCH_ALIGNMENT;
    s.upload = buffer(device, D3D12_HEAP_TYPE_UPLOAD, 2 * texture_pitch * texels, D3D12_RESOURCE_STATE_GENERIC_READ);
    if (!s.upload) return false;
    std::uint8_t* mapped = nullptr;
    if (!ok(s.upload->Map(0, nullptr, reinterpret_cast<void**>(&mapped)), "Map(upload)")) return false;
    for (int t = 0; t < 2; ++t)
        for (UINT ty = 0; ty < texels; ++ty)
            for (UINT tx = 0; tx < texels; ++tx)
                for (int c = 0; c < 4; ++c)
                    mapped[t * texture_pitch * texels + ty * texture_pitch + tx * 4 + c] =
                        c == 3 ? 255 : texel(t, tx, ty, c);
    s.upload->Unmap(0, nullptr);
    D3D12_HEAP_PROPERTIES vram{};
    vram.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC td{};
    td.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    td.Width = texels;
    td.Height = texels;
    td.DepthOrArraySize = 1;
    td.MipLevels = 1;
    td.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    td.SampleDesc.Count = 1;
    for (auto& texture : s.textures)
        if (!ok(device->CreateCommittedResource(&vram, D3D12_HEAP_FLAG_NONE, &td, D3D12_RESOURCE_STATE_COPY_DEST,
                                                nullptr, IID_PPV_ARGS(&texture)),
                "CreateCommittedResource(texture)"))
            return false;
    D3D12_RESOURCE_DESC dd = td;
    dd.Width = width;
    dd.Height = height;
    dd.Format = DXGI_FORMAT_D32_FLOAT;
    dd.Flags = D3D12_RESOURCE_FLAG_ALLOW_DEPTH_STENCIL;
    D3D12_CLEAR_VALUE clear_depth{};
    clear_depth.Format = DXGI_FORMAT_D32_FLOAT;
    clear_depth.DepthStencil.Depth = 1.0f;
    if (!ok(device->CreateCommittedResource(&vram, D3D12_HEAP_FLAG_NONE, &dd, D3D12_RESOURCE_STATE_DEPTH_WRITE,
                                            &clear_depth, IID_PPV_ARGS(&s.depth)),
            "CreateCommittedResource(depth)"))
        return false;
    device->CreateDepthStencilView(s.depth.Get(), nullptr, s.dsv_heap->GetCPUDescriptorHandleForHeapStart());
    s.readback = buffer(device, D3D12_HEAP_TYPE_READBACK, static_cast<UINT64>(row_pitch) * height,
                        D3D12_RESOURCE_STATE_COPY_DEST);
    if (!s.readback) return false;

    // Views. Draw k's table: [3k] the vertex constants, [3k+1] its texture, [3k+2] the pixel constants.
    const D3D12_CPU_DESCRIPTOR_HANDLE start = s.views->GetCPUDescriptorHandleForHeapStart();
    const auto at = [&](UINT index) { return D3D12_CPU_DESCRIPTOR_HANDLE{start.ptr + SIZE_T(index) * view_step}; };
    const std::uint64_t base = reinterpret_cast<std::uintptr_t>(title);
    for (UINT k = 0; k < draws; ++k) {
        D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{base + vs_constants_offset + 256 * k, 256};
        device->CreateConstantBufferView(&cbv, at(table_size * k));
        if (!(skip_view && k == 1)) {
            D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
            srv.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
            srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
            srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
            srv.Texture2D.MipLevels = 1;
            device->CreateShaderResourceView(s.textures[quads[k].texture].Get(), &srv, at(table_size * k + 1));
        }
        cbv = {base + ps_constants_offset + ps_constants_bytes * k, static_cast<UINT>(ps_constants_bytes)};
        device->CreateConstantBufferView(&cbv, at(table_size * k + 2));
    }
    D3D12_SAMPLER_DESC point{};
    point.Filter = D3D12_FILTER_MIN_MAG_MIP_POINT;
    point.AddressU = point.AddressV = point.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
    point.MaxLOD = D3D12_FLOAT32_MAX;
    device->CreateSampler(&point, s.samplers->GetCPUDescriptorHandleForHeapStart());

    // Texture upload.
    if (!ok(gpu.allocator->Reset(), "allocator Reset") || !ok(gpu.list->Reset(gpu.allocator.Get(), nullptr), "list Reset"))
        return false;
    for (int t = 0; t < 2; ++t) {
        D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
        dst.pResource = s.textures[t].Get();
        dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.pResource = s.upload.Get();
        src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        src.PlacedFootprint.Offset = static_cast<UINT64>(t) * texture_pitch * texels;
        src.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, texels, texels, 1, texture_pitch};
        gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        const auto barrier = transition(s.textures[t].Get(), D3D12_RESOURCE_STATE_COPY_DEST,
                                        D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        gpu.list->ResourceBarrier(1, &barrier);
    }
    if (!ok(gpu.list->Close(), "Close") || !gpu.submit_and_wait()) return false;

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

// Draws one frame and counts the pixels that differ from `expected`; false on API failure.
bool draw_frame(Gpu& gpu, Scene& s, std::uint8_t* title, std::uint8_t* instances,
                const std::vector<std::uint8_t>& expected, unsigned& mismatches)
{
    ID3D12Device* device = gpu.device.Get();
    const UINT index = s.chain->GetCurrentBackBufferIndex();
    ComPtr<ID3D12Resource> back;
    if (!ok(s.chain->GetBuffer(index, IID_PPV_ARGS(&back)), "GetBuffer")) return false;
    const D3D12_CPU_DESCRIPTOR_HANDLE rtv = s.rtv_heap->GetCPUDescriptorHandleForHeapStart();
    const D3D12_CPU_DESCRIPTOR_HANDLE dsv = s.dsv_heap->GetCPUDescriptorHandleForHeapStart();
    device->CreateRenderTargetView(back.Get(), nullptr, rtv);
    if (!ok(gpu.allocator->Reset(), "allocator Reset") ||
        !ok(gpu.list->Reset(gpu.allocator.Get(), s.pso.Get()), "list Reset"))
        return false;
    ID3D12GraphicsCommandList* list = gpu.list.Get();
    auto barrier = transition(back.Get(), D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_RENDER_TARGET);
    list->ResourceBarrier(1, &barrier);
    const FLOAT clear[4] = {clear_rgba[0] / 255.0f, clear_rgba[1] / 255.0f, clear_rgba[2] / 255.0f, 1.0f};
    list->ClearRenderTargetView(rtv, clear, 0, nullptr);
    list->ClearDepthStencilView(dsv, D3D12_CLEAR_FLAG_DEPTH, 1.0f, 0, 0, nullptr);
    list->OMSetRenderTargets(1, &rtv, FALSE, &dsv);
    const D3D12_VIEWPORT viewport{0, 0, float(width), float(height), 0, 1};
    const D3D12_RECT scissor{0, 0, LONG(width), LONG(height)};
    list->RSSetViewports(1, &viewport);
    list->RSSetScissorRects(1, &scissor);
    ID3D12DescriptorHeap* heaps[2] = {s.views.Get(), s.samplers.Get()};
    list->SetDescriptorHeaps(2, heaps);
    list->SetGraphicsRootSignature(s.root.Get());
    const std::uint64_t base = reinterpret_cast<std::uintptr_t>(title);
    const std::uint64_t instance_address = reinterpret_cast<std::uintptr_t>(instances);
    const UINT instance_words[2] = {static_cast<UINT>(instance_address), static_cast<UINT>(instance_address >> 32)};
    // Title GPU addresses, as a console title passes them.
    list->SetGraphicsRootShaderResourceView(root_vertices, base + vertices_offset);
    list->SetGraphicsRoot32BitConstants(root_instances, 2, instance_words, 0);
    list->SetGraphicsRootDescriptorTable(root_samplers, s.samplers->GetGPUDescriptorHandleForHeapStart());
    const D3D12_INDEX_BUFFER_VIEW ib{base + indices_offset, 6 * sizeof(std::uint16_t), DXGI_FORMAT_R16_UINT};
    list->IASetIndexBuffer(&ib);
    list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    const D3D12_GPU_DESCRIPTOR_HANDLE table = s.views->GetGPUDescriptorHandleForHeapStart();
    const UINT step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    for (UINT k = 0; k < draws; ++k) {
        float alpha = quads[k].alpha / 255.0f;
        UINT alpha_word;
        std::memcpy(&alpha_word, &alpha, 4);
        list->SetGraphicsRoot32BitConstant(root_alpha, alpha_word, 0);
        list->SetGraphicsRootDescriptorTable(root_table, {table.ptr + UINT64(table_size) * k * step});
        list->DrawIndexedInstanced(6, 1, 0, static_cast<INT>(4 * k), k);
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
    std::printf("mismatches=%u", mismatches);
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
    const bool missing_view = mode == "missing_view", missing_memory = mode == "missing_memory";
    const std::wstring cache = cache_directory();
    if (cache.empty()) {
        std::fputs("r4: X2W_CACHE_DIR must name the test's cache root\n", stderr);
        return 1;
    }
    if (cold) {
        count_files(cache, L"*.dxil", true);
        count_files(cache, L"*.bind", true);
    }
    float depths[draws];
    for (UINT k = 0; k < draws; ++k) depths[k] = missing_memory ? 0.0f : quads[k].depth;
    unsigned covered = 0;
    const auto expected = reference(depths, missing_view ? 1 : -1, wrong ? 1 : 0, covered);
    std::printf("covered_pixels=%u\n", covered);

    // Title memory before the device, as a title allocates it.
    auto* title = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    auto* instances = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    if (!title || !instances) {
        std::fputs("r4: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    std::memset(title, 0, title_bytes);
    std::memset(instances, 0, title_bytes);
    std::uint16_t indices[6] = {0, 1, 2, 2, 1, 3};
    std::memcpy(title + indices_offset, indices, sizeof(indices));
    for (UINT k = 0; k < draws; ++k) {
        const Quad& q = quads[k];
        // Clip coordinates of a quad at the origin (exact in binary32: multiples of 1/32), and the offset to its place.
        const float corners[4][2] = {{0, 0}, {float(q.w), 0}, {0, float(q.h)}, {float(q.w), float(q.h)}};
        for (int v = 0; v < 4; ++v) {
            const float u = (v & 1) ? 1.0f : 0.0f, t = (v & 2) ? 1.0f : 0.0f;
            const float vertex[4] = {corners[v][0] / 32.0f - 1.0f, 1.0f - corners[v][1] / 32.0f, q.flip ? 1.0f - u : u, t};
            std::memcpy(title + vertices_offset + 16 * (4 * k + v), vertex, sizeof(vertex));
        }
        const float offset[2] = {q.x / 32.0f, -q.y / 32.0f};
        std::memcpy(title + vs_constants_offset + 256 * k, offset, sizeof(offset));
        // The tint past the first 256 bytes (r4_ps.s); the buffer's first float4 is another tint, which a translation
        // that read the wrong word, or a root CBV that stopped short of the window, would show.
        const float tint[4] = {q.tint[0], q.tint[1], q.tint[2], 1.0f}, decoy[4] = {0.25f, 0.25f, 0.25f, 1.0f};
        std::memcpy(title + ps_constants_offset + ps_constants_bytes * k + ps_tint_offset, tint, sizeof(tint));
        std::memcpy(title + ps_constants_offset + ps_constants_bytes * k, decoy, sizeof(decoy));
        std::memcpy(instances + 16 * k, &q.depth, 4);
    }

    Recorded recorded;
    int rc = 1;
    {
        Gpu gpu;
        const int created = gpu.create(warp);
        if (created) {
            XMemFree(title, graphics_word);
            XMemFree(instances, graphics_word);
            return created;
        }
        X2WGfxSetLogSink(record, &recorded);
        const auto start = counters();
        bool good = start.title_gpu_state == X2W_GFX_TITLE_GPU_ATTACHED;
        std::printf("title_gpu_state=%d\n", start.title_gpu_state);
        {
            Scene scene;
            scene.root = title_root_signature(gpu.device.Get());
            double ms = 0;
            const HRESULT hr = scene.root ? create_pipeline(gpu.device.Get(), scene.root.Get(), scene.pso, &ms) : E_FAIL;
            std::printf("pso_create_ms=%.3f hr=0x%08lx mode=%s\n", ms, static_cast<unsigned long>(hr),
                        std::string(mode).c_str());
            good = good && SUCCEEDED(hr) && create_scene(gpu, scene, title, missing_view);
            if (missing_memory) {
                // The allocation's view leaves the title memory table; the root constants still hold its address.
                XMemFree(instances, graphics_word);
            }
            unsigned frame_mismatch[frames] = {};
            for (UINT f = 0; good && f < frames; ++f) good = draw_frame(gpu, scene, title, instances, expected,
                                                                        frame_mismatch[f]);
            const unsigned want = wrong ? covered : 0;
            for (UINT f = 0; f < frames; ++f) good = good && frame_mismatch[f] == want;
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
        std::printf("shaders_translated=%u shaders_cached=%u cache_files=%u+%u refused=%u draws_refused=%u "
                    "title_lookup_misses=%llu texture_lookup_misses=%llu debug_errors=%u unknown_slots=%llu "
                    "unknown_iids=%llu\n",
                    translated, cached, dxil, bind, recorded.refused, end.draws_refused - start.draws_refused,
                    title_misses, texture_misses, debug_errors,
                    static_cast<unsigned long long>(end.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls));
        good = good && debug_errors == 0 && recorded.refused == 0 && end.unknown_slot_calls == 0 &&
               end.unknown_iid_calls == 0 && dxil == 2 && bind == 2;
        if (cold) good = good && translated == 2 && cached == 0;
        if (warm) good = good && translated == 0 && cached == 2;
        good = good && (missing_memory ? title_misses > 0 : title_misses == 0);
        good = good && texture_misses == (missing_view ? frames : 0);
        if (missing_view) good = good && recorded.details.find("TextureLookup miss") != std::string::npos;
        rc = good ? 0 : 1;
        X2WGfxSetLogSink(nullptr, nullptr);
    }
    XMemFree(title, graphics_word);
    if (!missing_memory) XMemFree(instances, graphics_word);
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
        mode == "missing_memory")
        return scene_check(adapter == "warp", mode);
    return 2;
}
