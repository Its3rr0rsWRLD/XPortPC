// R6 descriptor work, toward rung R6 (docs/design/runtime.md, "Descriptors written as hardware words"): the R4 scene with its
// descriptors written by the title straight into descriptor-heap memory as hardware words, as console titles do.
//
// A console-style program, as r4_scene.cpp: device, root signature, heaps and pipelines from d3d12_xs.dll, memory
// from xmem.dll. Each frame draws three quads (DrawIndexedInstanced, one table per draw). The title writes, through
// the heaps' CPU handles (title memory), the words a console shader loads (tests/runtime/r6_words.h):
//   draw 0  vertex constants: a V# at the draw's offset; texture: a T# of texture 0; pixel constants: a V#; sampler
//           table: an S#, point, clamp;
//   draw 1  vertex constants: a CBV created through the API (CreateConstantBufferView: the API path beside the raw
//           one); texture: a T# of texture 1 whose DST_SEL is (Z, X, 1, W); pixel constants: the 32 bytes of an
//           API-written CBV copied by memcpy from a spare slot; sampler table: an S#, point, u WRAP;
//   draw 2  as draw 0 (the same T# words: one desktop texture for both), drawn with a second pipeline whose pixel
//           program sets its S# with s_mov (an inline sampler, u MIRROR; tests/runtime/r6_ps_inline.s).
// Draws 1 and 2 have u from 0 to 2, so the address modes show. The textures live in title texture memory: 8x8 RGBA8,
// texture 0 with 4 mips (MAX_MIP 3, the T# views levels 0..3), texture 1 with 1.
//
//   r6_rawdesc_scene warp|hardware raw            textures in SW_LINEAR layout; both frames equal the reference
//   r6_rawdesc_scene warp|hardware tiled          textures in GFX10.3 layouts (texture 0 SW_64KB_R_X, XOR 0x8b, mip 0
//                                                 in the tail; texture 1 SW_4KB_S_X, XOR 0x6; 16 pipes, 16 packers,
//                                                 the shim's default X2W_GB_ADDR_CONFIG), detiled by the shim
//   r6_rawdesc_scene warp|hardware wrong_swizzle  control: as tiled, but texture 0's T# says SW_64KB_S_X: every frame
//                                                 must differ from the reference
//   r6_rawdesc_scene warp|hardware wrong_dst_sel  control: as raw, compared with the reference that ignores DST_SEL:
//                                                 exactly the pixels where the two references differ must mismatch
//   r6_rawdesc_scene warp|hardware rewrite        between the frames the title rewrites draw 0's T# (DST_SEL (Y, Z,
//                                                 X, W)), the bytes of texture 1 (same T#) and the u mode of the
//                                                 wrap S# (to CLAMP). Frame 1 must equal the new reference, and
//                                                 differ from the old one in exactly the pixels where the references
//                                                 differ (a stale cache shows the old frame)
//
// Every mode: two 64x64 R8G8B8A8_UNORM frames read back and compared with the CPU reference (exact: pixel-aligned
// quads, sample points at least 1/4 texel from texel edges, even texels, tints of 1 or 0.5); no refusal, no
// TextureLookup or TitleLookup miss, no debug-layer error, no unknown slot or IID; raw descriptor reads counted; the
// shim created 2 desktop textures (4 in rewrite: draw 0's new words and texture 1's new bytes), 3 samplers (clamp,
// wrap, the inline mirror; rewrite's clamp S# is the first one's), and every wrapper is released.
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "era_title_gpu_api.h"
#include "gfx10_detile.h"
#include "r4_programs.h"
#include "r6_programs.h"
#include "r6_words.h"

#include <algorithm>
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
constexpr UINT frames = 2;
constexpr UINT draws = 3;
constexpr UINT texels = 8;
constexpr std::uint8_t clear_rgba[4] = {10, 20, 30, 255};
constexpr SIZE_T title_bytes = 64 * 1024;
constexpr SIZE_T texture_bytes = 128 * 1024;
constexpr std::size_t texture_offsets[2] = {0, 64 * 1024};

// Address modes as the reference applies them.
enum class Address { clamp, wrap, mirror };

struct Quad {
    int w, h, x, y;
    int texture;
    float u_range;
    float depth;
    float tint[3];
    std::uint8_t alpha;
};
constexpr Quad quads[draws] = {
    {32, 32, 8, 8, 0, 1.0f, 0.5f, {1.0f, 0.5f, 1.0f}, 100},
    {32, 32, 20, 14, 1, 2.0f, 0.25f, {0.5f, 1.0f, 1.0f}, 150},
    {32, 32, 28, 24, 0, 2.0f, 0.75f, {1.0f, 1.0f, 0.5f}, 200},
};

constexpr std::size_t vs_constants_offset = 0x0000;
constexpr std::size_t ps_constants_offset = 0x0400;
constexpr std::size_t vertices_offset = 0x1000;
constexpr std::size_t indices_offset = 0x1200;

constexpr UINT root_table = 0;
constexpr UINT root_samplers = 1;
constexpr UINT root_vertices = 2;
constexpr UINT root_instances = 3;
constexpr UINT root_alpha = 4;
constexpr UINT table_size = 3;
constexpr UINT spare_slot = draws * table_size;  // the API-written CBV whose words draw 1's pixel constants copy
constexpr UINT view_slots = spare_slot + 1;

// Texel c of (tx, ty) of mip `mip` of `texture`; `version` 1 is texture 1's rewritten content. Mip 0 values are
// even (a tint of 0.5 halves them exactly); smaller mips (never sampled) get other values.
std::uint8_t texel(int texture, int version, UINT mip, int tx, int ty, int c)
{
    if (c == 3) return 255;
    if (mip) return static_cast<std::uint8_t>(17 * mip + 3 * tx + 5 * ty + c);
    const int seed = texture * 61 + version * 37;
    return static_cast<std::uint8_t>(2 * ((tx * 29 + ty * 13 + c * 7 + seed) % 128));
}

const x2w::gfx10::Config addr_config{x2w::gfx10::MakeGbAddrConfig(4, 4), true, true};

x2w::gfx10::Surface surface(int texture, bool tiled)
{
    x2w::gfx10::Surface s;
    s.mode = !tiled ? x2w::gfx10::SwizzleMode::Linear
                    : texture == 0 ? x2w::gfx10::SwizzleMode::R_64KB_X : x2w::gfx10::SwizzleMode::S_4KB_X;
    s.element_bytes = 4;
    s.width = s.height = texels;
    s.mip_levels = texture == 0 ? 4 : 1;
    s.pipe_bank_xor = !tiled ? 0 : texture == 0 ? 0x8b : 0x6;
    return s;
}

// Writes texture `t` into title texture memory in its layout, as the console GPU would find it.
bool write_texture(std::uint8_t* memory, int t, bool tiled, int version)
{
    const x2w::gfx10::Surface s = surface(t, tiled);
    std::vector<x2w::gfx10::Footprint> fp(s.mip_levels);
    std::vector<std::uint8_t> linear;
    for (UINT m = 0; m < s.mip_levels; ++m) {
        const UINT size = std::max(texels >> m, 1u);
        fp[m] = {linear.size(), size, size, 1, size * 4};
        for (UINT ty = 0; ty < size; ++ty)
            for (UINT tx = 0; tx < size; ++tx)
                for (int c = 0; c < 4; ++c) linear.push_back(texel(t, version, m, tx, ty, c));
    }
    std::string error;
    if (!x2w::gfx10::TileFromFootprints(addr_config, s, memory + texture_offsets[t], texture_bytes - texture_offsets[t],
                                        linear.data(), linear.size(), fp.data(), s.mip_levels, &error)) {
        std::fprintf(stderr, "r6: TileFromFootprints(texture %d): %s\n", t, error.c_str());
        return false;
    }
    return true;
}

// The T# of texture `t`, with `sel` as its DST_SEL.
r6::Image image(std::uint8_t* memory, int t, bool tiled, const std::uint32_t (&sel)[4], bool wrong_swizzle)
{
    const x2w::gfx10::Surface s = surface(t, tiled);
    r6::Image i;
    i.va = reinterpret_cast<std::uintptr_t>(memory + texture_offsets[t]);
    i.pipe_bank_xor = s.pipe_bank_xor;
    i.width = i.height = texels;
    std::memcpy(i.sel, sel, sizeof(sel));
    i.max_mip = i.last_level = s.mip_levels - 1;
    i.sw_mode = static_cast<std::uint32_t>(wrong_swizzle ? x2w::gfx10::SwizzleMode::S_64KB_X : s.mode);
    return i;
}

constexpr std::uint32_t identity_sel[4] = {r6::sel_x, r6::sel_y, r6::sel_z, r6::sel_w};
constexpr std::uint32_t draw1_sel[4] = {r6::sel_z, r6::sel_x, r6::sel_1, r6::sel_w};
constexpr std::uint32_t rewritten_sel[4] = {r6::sel_y, r6::sel_z, r6::sel_x, r6::sel_w};

// What one frame shows, for the reference.
struct State {
    const std::uint32_t* sel[draws];  // DST_SEL per draw
    Address address[draws];           // u address mode per draw
    int version[2];                   // texture contents
};

int address(Address mode, int index)
{
    switch (mode) {
    case Address::clamp: return std::min(index, static_cast<int>(texels) - 1);
    case Address::wrap: return index % static_cast<int>(texels);
    default: {
        const int m = index % (2 * static_cast<int>(texels));
        return m < static_cast<int>(texels) ? m : 2 * static_cast<int>(texels) - 1 - m;
    }
    }
}

std::vector<std::uint8_t> reference(const State& state, unsigned& covered)
{
    std::vector<std::uint8_t> out(static_cast<std::size_t>(width) * height * 4);
    std::vector<float> depth(static_cast<std::size_t>(width) * height, 1.0f);
    for (std::size_t p = 0; p < depth.size(); ++p) std::memcpy(&out[4 * p], clear_rgba, 4);
    covered = 0;
    for (UINT k = 0; k < draws; ++k) {
        const Quad& q = quads[k];
        for (int py = q.y; py < q.y + q.h; ++py) {
            for (int px = q.x; px < q.x + q.w; ++px) {
                const std::size_t p = static_cast<std::size_t>(py) * width + px;
                if (!(q.depth < depth[p])) continue;
                if (depth[p] == 1.0f) ++covered;
                depth[p] = q.depth;
                // The pixel centre's texel: floor(u * 8) with u = (px - x + 0.5) / w * range (never on an edge).
                const int range = static_cast<int>(q.u_range);
                const int s = ((2 * (px - q.x) + 1) * static_cast<int>(texels) * range) / (2 * q.w);
                const int tx = address(state.address[k], s);
                const int ty = ((2 * (py - q.y) + 1) * static_cast<int>(texels)) / (2 * q.h);
                std::uint8_t value[4];
                for (int c = 0; c < 4; ++c) value[c] = texel(q.texture, state.version[q.texture], 0, tx, ty, c);
                for (int c = 0; c < 3; ++c) {
                    const std::uint32_t sel = state.sel[k][c];
                    const int v = sel == r6::sel_0 ? 0 : sel == r6::sel_1 ? 255 : value[sel - r6::sel_x];
                    out[4 * p + c] = static_cast<std::uint8_t>(q.tint[c] == 1.0f ? v : v / 2);
                }
                out[4 * p + 3] = q.alpha;
            }
        }
    }
    return out;
}

unsigned differences(const std::vector<std::uint8_t>& a, const std::vector<std::uint8_t>& b)
{
    unsigned n = 0;
    for (std::size_t p = 0; p < a.size(); p += 4) n += std::memcmp(&a[p], &b[p], 4) != 0;
    return n;
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
    ComPtr<ID3DBlob> blob, errors;
    if (!ok(D3D12SerializeVersionedRootSignature(&desc, &blob, &errors), "D3D12SerializeVersionedRootSignature"))
        return {};
    ComPtr<ID3D12RootSignature> root;
    if (!ok(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)),
            "CreateRootSignature"))
        return {};
    return root;
}

HRESULT create_pipeline(ID3D12Device* device, ID3D12RootSignature* root, bool inline_sampler,
                        ComPtr<ID3D12PipelineState>& pso)
{
    const std::vector<X2WShaderBinding> vb = {{2, X2W_SHADER_BINDING_ROOT_WORD, root_vertices, 0},
                                              {3, X2W_SHADER_BINDING_ROOT_WORD, root_vertices, 1},
                                              {4, X2W_SHADER_BINDING_BASE_VERTEX, 0, 0},
                                              {5, X2W_SHADER_BINDING_START_INSTANCE, 0, 0},
                                              {6, X2W_SHADER_BINDING_TABLE, root_table, 0},
                                              {8, X2W_SHADER_BINDING_ROOT_WORD, root_instances, 0},
                                              {9, X2W_SHADER_BINDING_ROOT_WORD, root_instances, 1}};
    std::vector<X2WShaderBinding> pb = {{2, X2W_SHADER_BINDING_INTERP, 0, 0},
                                        {3, X2W_SHADER_BINDING_TABLE, root_table, 0},
                                        {5, X2W_SHADER_BINDING_ROOT_WORD, root_alpha, 0}};
    if (!inline_sampler) pb.push_back({4, X2W_SHADER_BINDING_TABLE, root_samplers, 0});
    const auto vs = r6::container(X2W_SHADER_STAGE_VERTEX, r4_vs, sizeof(r4_vs), vb);
    const auto ps = inline_sampler ? r6::container(X2W_SHADER_STAGE_PIXEL, r6_ps_inline, sizeof(r6_ps_inline), pb)
                                   : r6::container(X2W_SHADER_STAGE_PIXEL, r4_ps, sizeof(r4_ps), pb);
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
    return device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso));
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

struct Scene {
    ComPtr<ID3D12RootSignature> root;
    ComPtr<ID3D12PipelineState> pso, pso_inline;
    ComPtr<ID3D12DescriptorHeap> views, samplers, rtv_heap, dsv_heap;
    ComPtr<ID3D12Resource> depth, readback;
    ComPtr<IDXGISwapChain3> chain;
    HWND window = nullptr;
    ~Scene()
    {
        chain.Reset();
        if (window) DestroyWindow(window);
    }
    std::uint8_t* view(UINT slot) const
    {
        return reinterpret_cast<std::uint8_t*>(views->GetCPUDescriptorHandleForHeapStart().ptr) + 32 * slot;
    }
    std::uint8_t* sampler(UINT slot) const
    {
        return reinterpret_cast<std::uint8_t*>(samplers->GetCPUDescriptorHandleForHeapStart().ptr) + 16 * slot;
    }
};

bool create_scene(Gpu& gpu, Scene& s)
{
    ID3D12Device* device = gpu.device.Get();
    D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, view_slots,
                                  D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.views)), "CreateDescriptorHeap(views)")) return false;
    hd = {D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER, 2, D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.samplers)), "CreateDescriptorHeap(samplers)")) return false;
    hd = {D3D12_DESCRIPTOR_HEAP_TYPE_RTV, 1, D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.rtv_heap)), "CreateDescriptorHeap(rtv)")) return false;
    hd = {D3D12_DESCRIPTOR_HEAP_TYPE_DSV, 1, D3D12_DESCRIPTOR_HEAP_FLAG_NONE, 0};
    if (!ok(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&s.dsv_heap)), "CreateDescriptorHeap(dsv)")) return false;
    D3D12_HEAP_PROPERTIES vram{};
    vram.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC dd{};
    dd.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    dd.Width = width;
    dd.Height = height;
    dd.DepthOrArraySize = 1;
    dd.MipLevels = 1;
    dd.Format = DXGI_FORMAT_D32_FLOAT;
    dd.SampleDesc.Count = 1;
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

// The descriptors of the header comment, written by the title into heap memory (and two through the API).
void write_descriptors(ID3D12Device* device, Scene& s, std::uint8_t* title, std::uint8_t* textures, bool tiled,
                       bool wrong_swizzle)
{
    const std::uint64_t base = reinterpret_cast<std::uintptr_t>(title);
    const D3D12_CPU_DESCRIPTOR_HANDLE start = s.views->GetCPUDescriptorHandleForHeapStart();
    for (UINT k = 0; k < draws; ++k) {
        std::uint8_t* table = s.view(table_size * k);
        if (k == 1) {
            const D3D12_CONSTANT_BUFFER_VIEW_DESC cbv{base + vs_constants_offset + 256 * k, 256};
            device->CreateConstantBufferView(&cbv, {start.ptr + 32 * SIZE_T(table_size * k)});
            const D3D12_CONSTANT_BUFFER_VIEW_DESC spare{base + ps_constants_offset + 256 * k, 256};
            device->CreateConstantBufferView(&spare, {start.ptr + 32 * SIZE_T(spare_slot)});
            std::memcpy(table + 64, s.view(spare_slot), 32);  // the title copies the descriptor's 32 bytes
        } else {
            r6::write_buffer(table, base + vs_constants_offset + 256 * k, 256);
            r6::write_buffer(table + 64, base + ps_constants_offset + 256 * k, 256);
        }
        image(textures, quads[k].texture, tiled, k == 1 ? draw1_sel : identity_sel, wrong_swizzle && quads[k].texture == 0)
            .write(table + 32);
    }
    r6::write_sampler(s.sampler(0), r6::clamp_last_texel, r6::clamp_last_texel);
    r6::write_sampler(s.sampler(1), r6::wrap, r6::clamp_last_texel);
}

bool draw_frame(Gpu& gpu, Scene& s, std::uint8_t* title, std::uint8_t* instances, std::vector<std::uint8_t>& pixels)
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
    list->SetGraphicsRootShaderResourceView(root_vertices, base + vertices_offset);
    list->SetGraphicsRoot32BitConstants(root_instances, 2, instance_words, 0);
    const D3D12_INDEX_BUFFER_VIEW ib{base + indices_offset, 6 * sizeof(std::uint16_t), DXGI_FORMAT_R16_UINT};
    list->IASetIndexBuffer(&ib);
    list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    const D3D12_GPU_DESCRIPTOR_HANDLE table = s.views->GetGPUDescriptorHandleForHeapStart();
    const D3D12_GPU_DESCRIPTOR_HANDLE samplers = s.samplers->GetGPUDescriptorHandleForHeapStart();
    for (UINT k = 0; k < draws; ++k) {
        if (k == 2) list->SetPipelineState(s.pso_inline.Get());
        float alpha = quads[k].alpha / 255.0f;
        UINT alpha_word;
        std::memcpy(&alpha_word, &alpha, 4);
        list->SetGraphicsRoot32BitConstant(root_alpha, alpha_word, 0);
        list->SetGraphicsRootDescriptorTable(root_table, {table.ptr + UINT64(table_size) * k * 32});
        list->SetGraphicsRootDescriptorTable(root_samplers, {samplers.ptr + 16 * UINT64(k == 1 ? 1 : 0)});
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
    pixels.assign(static_cast<const std::uint8_t*>(mapped), static_cast<const std::uint8_t*>(mapped) + read.End);
    const D3D12_RANGE none{0, 0};
    s.readback->Unmap(0, &none);
    const HRESULT present = s.chain->Present(0, 0);
    std::printf("present=0x%08lx\n", static_cast<unsigned long>(present));
    return SUCCEEDED(present);
}

// Pixels of `pixels` that differ from `expected`, with the first printed.
unsigned mismatches(const std::vector<std::uint8_t>& pixels, const std::vector<std::uint8_t>& expected, const char* name)
{
    unsigned n = 0;
    for (std::size_t p = 0; p < expected.size(); p += 4) {
        if (std::memcmp(&pixels[p], &expected[p], 4) == 0) continue;
        if (!n) {
            std::uint32_t got, want;
            std::memcpy(&got, &pixels[p], 4);
            std::memcpy(&want, &expected[p], 4);
            std::printf("%s first_pixel=(%zu,%zu) got=%08x want=%08x\n", name, (p / 4) % width, (p / 4) / width,
                        static_cast<unsigned>(got), static_cast<unsigned>(want));
        }
        ++n;
    }
    std::printf("%s mismatches=%u\n", name, n);
    return n;
}

int scene_check(bool warp, std::string_view mode)
{
    const bool tiled = mode == "tiled" || mode == "wrong_swizzle";
    const bool wrong_swizzle = mode == "wrong_swizzle", wrong_dst_sel = mode == "wrong_dst_sel";
    const bool rewrite = mode == "rewrite";
    State before{{identity_sel, draw1_sel, identity_sel}, {Address::clamp, Address::wrap, Address::mirror}, {0, 0}};
    State after = before;
    if (rewrite) {
        after.sel[0] = rewritten_sel;
        after.address[1] = Address::clamp;
        after.version[1] = 1;
    }
    State ignoring_sel = before;
    for (auto& sel : ignoring_sel.sel) sel = identity_sel;
    unsigned covered = 0;
    const auto expected0 = reference(before, covered);
    const auto expected1 = reference(after, covered);
    const auto no_sel = reference(ignoring_sel, covered);
    std::printf("covered_pixels=%u dst_sel_pixels=%u rewritten_pixels=%u\n", covered, differences(expected0, no_sel),
                differences(expected0, expected1));

    auto* title = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    auto* instances = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    auto* textures = static_cast<std::uint8_t*>(XMemAlloc(texture_bytes, graphics_word));
    if (!title || !instances || !textures) {
        std::fputs("r6: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    std::memset(title, 0, title_bytes);
    std::memset(instances, 0, title_bytes);
    std::memset(textures, 0, texture_bytes);
    if (!write_texture(textures, 0, tiled, 0) || !write_texture(textures, 1, tiled, 0)) return 1;
    const std::uint16_t indices[6] = {0, 1, 2, 2, 1, 3};
    std::memcpy(title + indices_offset, indices, sizeof(indices));
    for (UINT k = 0; k < draws; ++k) {
        const Quad& q = quads[k];
        const float corners[4][2] = {{0, 0}, {float(q.w), 0}, {0, float(q.h)}, {float(q.w), float(q.h)}};
        for (int v = 0; v < 4; ++v) {
            const float vertex[4] = {corners[v][0] / 32.0f - 1.0f, 1.0f - corners[v][1] / 32.0f,
                                     (v & 1) ? q.u_range : 0.0f, (v & 2) ? 1.0f : 0.0f};
            std::memcpy(title + vertices_offset + 16 * (4 * k + v), vertex, sizeof(vertex));
        }
        const float offset[2] = {q.x / 32.0f, -q.y / 32.0f};
        std::memcpy(title + vs_constants_offset + 256 * k, offset, sizeof(offset));
        const float tint[4] = {q.tint[0], q.tint[1], q.tint[2], 1.0f};
        std::memcpy(title + ps_constants_offset + 256 * k, tint, sizeof(tint));
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
            XMemFree(textures, graphics_word);
            return created;
        }
        X2WGfxSetLogSink(record, &recorded);
        const auto start = counters();
        bool good = start.title_gpu_state == X2W_GFX_TITLE_GPU_ATTACHED;
        {
            Scene scene;
            scene.root = title_root_signature(gpu.device.Get());
            const HRESULT hr = scene.root ? create_pipeline(gpu.device.Get(), scene.root.Get(), false, scene.pso) : E_FAIL;
            const HRESULT hr2 =
                scene.root ? create_pipeline(gpu.device.Get(), scene.root.Get(), true, scene.pso_inline) : E_FAIL;
            std::printf("pso=0x%08lx pso_inline=0x%08lx mode=%s\n", static_cast<unsigned long>(hr),
                        static_cast<unsigned long>(hr2), std::string(mode).c_str());
            good = good && SUCCEEDED(hr) && SUCCEEDED(hr2) && create_scene(gpu, scene);
            if (good) write_descriptors(gpu.device.Get(), scene, title, textures, tiled, wrong_swizzle);
            std::vector<std::uint8_t> pixels[frames];
            for (UINT f = 0; good && f < frames; ++f) {
                if (f == 1 && rewrite) {
                    // The GPU is done with frame 0 (draw_frame waits): the title rewrites words and texels.
                    image(textures, 0, tiled, rewritten_sel, false).write(scene.view(1));
                    r6::write_sampler(scene.sampler(1), r6::clamp_last_texel, r6::clamp_last_texel);
                    good = write_texture(textures, 1, tiled, 1);
                }
                good = good && draw_frame(gpu, scene, title, instances, pixels[f]);
            }
            if (good) {
                const unsigned m0 = mismatches(pixels[0], wrong_dst_sel ? no_sel : expected0, "frame0");
                const unsigned m1 = mismatches(pixels[1], wrong_dst_sel ? no_sel : expected1, "frame1");
                if (wrong_swizzle) {
                    good = m0 > 0 && m1 > 0;
                } else if (wrong_dst_sel) {
                    const unsigned want = differences(expected0, no_sel);
                    good = want > 0 && m0 == want && m1 == want;
                } else {
                    good = m0 == 0 && m1 == 0;
                }
                if (rewrite) {
                    // The stale-cache control: frame 1 against the frame-0 reference.
                    const unsigned stale = mismatches(pixels[1], expected0, "frame1_vs_old_reference");
                    const unsigned want = differences(expected0, expected1);
                    good = good && want > 0 && stale == want;
                }
                if (wrong_swizzle || wrong_dst_sel || rewrite)
                    std::printf("control=%s\n", good ? "mismatch_detected" : "mismatch_missed");
            }
            gpu.list->Reset(gpu.allocator.Get(), nullptr);
            gpu.list->Close();
            good = gpu.submit_and_wait() && good;
        }
        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        const unsigned long long title_misses = end.title_lookup_misses - start.title_lookup_misses;
        const unsigned long long texture_misses = end.texture_lookup_misses - start.texture_lookup_misses;
        const unsigned long long raw_reads = end.raw_descriptor_reads - start.raw_descriptor_reads;
        const unsigned uploads = end.raw_texture_uploads - start.raw_texture_uploads;
        const unsigned samplers = end.raw_samplers_created - start.raw_samplers_created;
        std::printf("refused=%u draws_refused=%u title_lookup_misses=%llu texture_lookup_misses=%llu raw_reads=%llu "
                    "raw_texture_uploads=%u raw_samplers=%u debug_errors=%u unknown_slots=%llu unknown_iids=%llu\n",
                    recorded.refused, end.draws_refused - start.draws_refused, title_misses, texture_misses, raw_reads,
                    uploads, samplers, debug_errors, static_cast<unsigned long long>(end.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls));
        // Per frame: 3 T#s, 3 S#s (draws 0 and 1's tables, draw 2's inline sampler) and 4 V#s (draw 1's two constant
        // buffers are API views): 10 reads of hardware words.
        good = good && debug_errors == 0 && recorded.refused == 0 && end.unknown_slot_calls == 0 &&
               end.unknown_iid_calls == 0 && title_misses == 0 && texture_misses == 0 && raw_reads == 10ull * frames &&
               uploads == (rewrite ? 4u : 2u) && samplers == 3;
        rc = good ? 0 : 1;
        X2WGfxSetLogSink(nullptr, nullptr);
    }
    XMemFree(title, graphics_word);
    XMemFree(instances, graphics_word);
    XMemFree(textures, graphics_word);
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
    if (mode == "raw" || mode == "tiled" || mode == "wrong_swizzle" || mode == "wrong_dst_sel" || mode == "rewrite")
        return scene_check(adapter == "warp", mode);
    return 2;
}
