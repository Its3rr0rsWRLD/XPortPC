// Runtime ladder R3 (docs/design/runtime.md, section 6): a triangle from gfx1013 programs, translated by the graphics
// shim at pipeline creation.
//
// A console-style program: device, root signature and pipeline come from d3d12_xs.dll (no desktop d3d12.lib), title
// memory from xmem.dll. The vertex and pixel programs are llvm-mc 15 assemblies of tests/runtime/r3_*.s
// (r3_programs.h), each wrapped in the console bytecode container of d3d12_xs_api.h. The vertex program reads the
// three positions from a vertex buffer in title memory and the colour from a constant buffer in title memory, both
// through title GPU addresses the program receives in user SGPRs from two root parameters (a root SRV and a root
// CBV); the pixel program exports the colour it reads flat.
//
//   r3_triangle warp|hardware cold             X2W_CACHE_DIR\r3_triangle emptied first: both shaders translated
//   r3_triangle warp|hardware warm             after cold: both shaders from the on-disk cache, none translated
//   r3_triangle warp|hardware wrong_reference  control: the frame against a reference whose triangle colour is one
//                                              step off in green; passes only if exactly the covered pixels differ
//   r3_triangle warp|hardware stream           after cold: the pipeline created as a pipeline-state stream
//                                              (ID3D12Device2::CreatePipelineState, with an input layout the shim
//                                              must drop) through the same translation; both shaders from the cache
//   r3_triangle warp|hardware stream_wrong_reference  the stream pipeline's control
//   r3_triangle warp refused                   a vertex program the translator refuses fails the pipeline with
//                                              E_NOTIMPL and one REFUSED event naming the refused export, also when
//                                              it comes in a stream
//
// Each drawing mode renders one 64x64 R8G8B8A8_UNORM frame (clear, draw, read back, present) and compares every
// pixel with a CPU reference: pixel centres strictly inside the triangle (exact integer edge functions; the vertices
// are chosen so no centre lies on an edge) take the triangle colour, the others the clear colour, each channel k/255.
// It prints the CreateGraphicsPipelineState time (pso_create_ms).
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "era_title_gpu_api.h"
#include "r3_programs.h"

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
constexpr std::uint8_t clear_rgba[4] = {10, 20, 30, 255};
constexpr std::uint8_t triangle_rgba[4] = {200, 100, 50, 255};
// Vertices in pixels (y down). Integer coordinates are exact under any subpixel snapping.
constexpr int vertices[3][2] = {{9, 5}, {57, 19}, {16, 53}};
// Title memory layout: constants at 0 (a root CBV must be 256-byte aligned), positions at 256.
constexpr std::size_t constants_offset = 0;
constexpr std::size_t positions_offset = 256;
constexpr SIZE_T title_bytes = 64 * 1024;

// Root parameters of the title's root signature, and the SGPRs the vertex container binds to their words.
constexpr UINT root_constants = 0;  // root CBV b0: the colour
constexpr UINT root_positions = 1;  // root SRV t0: the vertex buffer

// Container (d3d12_xs_api.h) around one program.
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
    if (!bindings.empty()) std::memcpy(out.data() + sizeof(header), bindings.data(), bindings.size() * sizeof(bindings[0]));
    std::memcpy(out.data() + header.code_offset, code, bytes);
    return out;
}

std::vector<X2WShaderBinding> vertex_bindings()
{
    return {{2, X2W_SHADER_BINDING_ROOT_WORD, root_positions, 0}, {3, X2W_SHADER_BINDING_ROOT_WORD, root_positions, 1},
            {4, X2W_SHADER_BINDING_ROOT_WORD, root_constants, 0}, {5, X2W_SHADER_BINDING_ROOT_WORD, root_constants, 1}};
}

// Twice the edge function of (a, b) at the centre of pixel (x, y): exact in integers.
long long edge(const int a[2], const int b[2], int x, int y)
{
    const long long px = 2 * x + 1, py = 2 * y + 1;
    return (2LL * b[0] - 2 * a[0]) * (py - 2LL * a[1]) - (2LL * b[1] - 2 * a[1]) * (px - 2LL * a[0]);
}

// The reference frame; false if a pixel centre lies on an edge (the data would depend on the fill rule).
bool reference(int green_offset, std::vector<std::uint8_t>& out, unsigned& covered)
{
    out.assign(static_cast<std::size_t>(width) * height * 4, 0);
    covered = 0;
    for (UINT y = 0; y < height; ++y) {
        for (UINT x = 0; x < width; ++x) {
            const long long e0 = edge(vertices[0], vertices[1], x, y), e1 = edge(vertices[1], vertices[2], x, y),
                            e2 = edge(vertices[2], vertices[0], x, y);
            if (!e0 || !e1 || !e2) return false;
            const bool inside = (e0 > 0 && e1 > 0 && e2 > 0) || (e0 < 0 && e1 < 0 && e2 < 0);
            std::uint8_t* p = &out[(static_cast<std::size_t>(y) * width + x) * 4];
            std::memcpy(p, inside ? triangle_rgba : clear_rgba, 4);
            if (inside) {
                p[1] = static_cast<std::uint8_t>(p[1] + green_offset);
                ++covered;
            }
        }
    }
    return true;
}

ComPtr<ID3D12RootSignature> title_root_signature(ID3D12Device* device)
{
    D3D12_ROOT_PARAMETER1 params[2]{};
    params[root_constants].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    params[root_constants].Descriptor = {0, 0, D3D12_ROOT_DESCRIPTOR_FLAG_NONE};
    params[root_constants].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    params[root_positions].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
    params[root_positions].Descriptor = {0, 0, D3D12_ROOT_DESCRIPTOR_FLAG_NONE};
    params[root_positions].ShaderVisibility = D3D12_SHADER_VISIBILITY_VERTEX;
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = 2;
    desc.Desc_1_1.pParameters = params;
    // A typical title's flags: the deny flags must not hide the converter's parameters (the shim drops them).
    desc.Desc_1_1.Flags = D3D12_ROOT_SIGNATURE_FLAG_DENY_HULL_SHADER_ROOT_ACCESS |
                          D3D12_ROOT_SIGNATURE_FLAG_DENY_DOMAIN_SHADER_ROOT_ACCESS |
                          D3D12_ROOT_SIGNATURE_FLAG_DENY_GEOMETRY_SHADER_ROOT_ACCESS;
    ComPtr<ID3DBlob> blob, errors;
    // d3d12_xs.dll's export, as a title imports it.
    if (!ok(D3D12SerializeVersionedRootSignature(&desc, &blob, &errors), "D3D12SerializeVersionedRootSignature"))
        return {};
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

template <D3D12_PIPELINE_STATE_SUBOBJECT_TYPE Type, class Inner>
struct alignas(void*) Sub {
    D3D12_PIPELINE_STATE_SUBOBJECT_TYPE type = Type;
    Inner inner;
};

// The same pipeline as a stream. The input layout names an attribute the translated vertex program does not read;
// the shim replaces it with an empty one, as for CreateGraphicsPipelineState.
HRESULT create_stream_pipeline(ID3D12Device* device, ID3D12RootSignature* root, const std::vector<std::uint8_t>& vs,
                               const std::vector<std::uint8_t>& ps, ComPtr<ID3D12PipelineState>& pso, double* ms)
{
    static const D3D12_INPUT_ELEMENT_DESC element = {"POSITION", 0, DXGI_FORMAT_R32G32B32A32_FLOAT, 0, 0,
                                                     D3D12_INPUT_CLASSIFICATION_PER_VERTEX_DATA, 0};
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
    stream.vs.inner = {vs.data(), vs.size()};
    stream.ps.inner = {ps.data(), ps.size()};
    stream.layout.inner = {&element, 1};
    stream.rs.inner.FillMode = D3D12_FILL_MODE_SOLID;
    stream.rs.inner.CullMode = D3D12_CULL_MODE_NONE;
    stream.rs.inner.DepthClipEnable = TRUE;
    stream.topology.inner = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    stream.rt.inner.NumRenderTargets = 1;
    stream.rt.inner.RTFormats[0] = DXGI_FORMAT_R8G8B8A8_UNORM;
    ComPtr<ID3D12Device2> device2;
    if (!ok(device->QueryInterface(IID_PPV_ARGS(&device2)), "QueryInterface(ID3D12Device2)")) return E_NOINTERFACE;
    const D3D12_PIPELINE_STATE_STREAM_DESC desc{sizeof(stream), &stream};
    LARGE_INTEGER start;
    QueryPerformanceCounter(&start);
    const HRESULT hr = device2->CreatePipelineState(&desc, IID_PPV_ARGS(&pso));
    if (ms) *ms = 1000.0 * seconds_since(start);
    return hr;
}

HRESULT create_pipeline(ID3D12Device* device, ID3D12RootSignature* root, const std::vector<std::uint8_t>& vs,
                        const std::vector<std::uint8_t>& ps, ComPtr<ID3D12PipelineState>& pso, double* ms)
{
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
    return std::wstring(root) + L"\\r3_triangle";
}

// Empties the title's cache directory (cold mode). Only *.dxil files directly inside it are removed.
bool empty_cache(const std::wstring& dir)
{
    WIN32_FIND_DATAW found;
    HANDLE find = FindFirstFileW((dir + L"\\*.dxil").c_str(), &found);
    if (find == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_FILE_NOT_FOUND || GetLastError() == ERROR_PATH_NOT_FOUND;
    bool good = true;
    do {
        good = DeleteFileW((dir + L"\\" + found.cFileName).c_str()) && good;
    } while (FindNextFileW(find, &found));
    FindClose(find);
    return good;
}

unsigned cached_files(const std::wstring& dir)
{
    WIN32_FIND_DATAW found;
    HANDLE find = FindFirstFileW((dir + L"\\*.dxil").c_str(), &found);
    if (find == INVALID_HANDLE_VALUE) return 0;
    unsigned count = 0;
    do ++count;
    while (FindNextFileW(find, &found));
    FindClose(find);
    return count;
}

// Records everything the sink receives except first uses; prints refusals and notes.
struct Recorded {
    unsigned refused = 0;
    std::string details;
};

void WINAPI record(const X2WGfxEvent* event, void* context)
{
    if (event->kind == X2W_GFX_EVENT_FIRST_USE) return;
    std::fprintf(stderr, "[sink] %s %s\n", event->symbol, event->detail);
    auto* recorded = static_cast<Recorded*>(context);
    if (event->kind == X2W_GFX_EVENT_REFUSED) {
        ++recorded->refused;
        recorded->details += event->detail;
        recorded->details += '\n';
    }
}

// Draws one frame and compares it; returns false on API failure.
bool draw_frame(Gpu& gpu, ID3D12RootSignature* root, ID3D12PipelineState* pso, std::uintptr_t title,
                const std::vector<std::uint8_t>& expected, unsigned& mismatches)
{
    HWND window = make_window(width, height);
    if (!window) return false;
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
    heap_desc.NumDescriptors = 1;
    ComPtr<ID3D12DescriptorHeap> rtv_heap;
    if (!ok(gpu.device->CreateDescriptorHeap(&heap_desc, IID_PPV_ARGS(&rtv_heap)), "CreateDescriptorHeap")) return false;
    const UINT index = chain->GetCurrentBackBufferIndex();
    ComPtr<ID3D12Resource> back;
    if (!ok(chain->GetBuffer(index, IID_PPV_ARGS(&back)), "GetBuffer")) return false;
    const D3D12_CPU_DESCRIPTOR_HANDLE rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
    gpu.device->CreateRenderTargetView(back.Get(), nullptr, rtv);

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
            "CreateCommittedResource(readback)"))
        return false;

    if (!ok(gpu.allocator->Reset(), "allocator Reset") || !ok(gpu.list->Reset(gpu.allocator.Get(), pso), "list Reset"))
        return false;
    auto barrier = transition(back.Get(), D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_RENDER_TARGET);
    gpu.list->ResourceBarrier(1, &barrier);
    const FLOAT clear[4] = {clear_rgba[0] / 255.0f, clear_rgba[1] / 255.0f, clear_rgba[2] / 255.0f, clear_rgba[3] / 255.0f};
    gpu.list->ClearRenderTargetView(rtv, clear, 0, nullptr);
    gpu.list->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
    const D3D12_VIEWPORT viewport{0, 0, float(width), float(height), 0, 1};
    const D3D12_RECT scissor{0, 0, LONG(width), LONG(height)};
    gpu.list->RSSetViewports(1, &viewport);
    gpu.list->RSSetScissorRects(1, &scissor);
    gpu.list->SetGraphicsRootSignature(root);
    // Title GPU addresses, as a console title passes them; the shim gives desktop D3D12 their aliases.
    gpu.list->SetGraphicsRootConstantBufferView(root_constants, title + constants_offset);
    gpu.list->SetGraphicsRootShaderResourceView(root_positions, title + positions_offset);
    gpu.list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    gpu.list->DrawInstanced(3, 1, 0, 0);
    barrier = transition(back.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
    gpu.list->ResourceBarrier(1, &barrier);
    D3D12_TEXTURE_COPY_LOCATION dst{};
    dst.pResource = readback.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, width, height, 1, row_pitch};
    D3D12_TEXTURE_COPY_LOCATION src{};
    src.pResource = back.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    barrier = transition(back.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_PRESENT);
    gpu.list->ResourceBarrier(1, &barrier);
    if (!ok(gpu.list->Close(), "Close") || !gpu.submit_and_wait()) return false;

    void* mapped = nullptr;
    const D3D12_RANGE read{0, static_cast<SIZE_T>(readback_desc.Width)};
    if (!ok(readback->Map(0, &read, &mapped), "Map")) return false;
    std::uint32_t first = 0, first_at = 0;
    for (UINT y = 0; y < height; ++y) {
        const auto* row = static_cast<const std::uint8_t*>(mapped) + static_cast<SIZE_T>(y) * row_pitch;
        for (UINT x = 0; x < width; ++x) {
            const std::uint8_t* want = &expected[(static_cast<std::size_t>(y) * width + x) * 4];
            if (std::memcmp(row + x * 4, want, 4) != 0) {
                if (!mismatches) {
                    std::memcpy(&first, row + x * 4, 4);
                    first_at = y * width + x;
                }
                ++mismatches;
            }
        }
    }
    const D3D12_RANGE none{0, 0};
    readback->Unmap(0, &none);
    std::printf("mismatches=%u", mismatches);
    if (mismatches) std::printf(" first_pixel=%u first=%08x", first_at, static_cast<unsigned>(first));
    std::printf("\n");
    const HRESULT present = chain->Present(0, 0);
    std::printf("present=0x%08lx\n", static_cast<unsigned long>(present));
    gpu.list->Reset(gpu.allocator.Get(), nullptr);
    gpu.list->Close();
    const bool drained = gpu.submit_and_wait();
    chain.Reset();
    DestroyWindow(window);
    return SUCCEEDED(present) && drained;
}

int triangle_check(bool warp, std::string_view mode)
{
    const bool stream = mode == "stream" || mode == "stream_wrong_reference";
    const bool cold = mode == "cold", warm = mode == "warm" || mode == "stream",
               control = mode == "wrong_reference" || mode == "stream_wrong_reference";
    const std::wstring cache = cache_directory();
    if (cache.empty()) {
        std::fputs("r3: X2W_CACHE_DIR must name the test's cache root\n", stderr);
        return 1;
    }
    if (cold && !empty_cache(cache)) {
        std::fputs("r3: cannot empty the cache directory\n", stderr);
        return 1;
    }
    std::vector<std::uint8_t> expected;
    unsigned covered = 0;
    if (!reference(control ? 1 : 0, expected, covered)) {
        std::fputs("r3: a pixel centre lies on a triangle edge; choose other vertices\n", stderr);
        return 1;
    }
    std::printf("covered_pixels=%u\n", covered);

    // Title memory before the device, as a title allocates it: the shim attaches the device to xmem.dll's registry.
    auto* title = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    if (!title) {
        std::fputs("r3: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    float color[4], positions[3][4];
    for (int c = 0; c < 4; ++c) color[c] = triangle_rgba[c] / 255.0f;
    for (int v = 0; v < 3; ++v) {
        positions[v][0] = vertices[v][0] / 32.0f - 1.0f;  // exact in binary32
        positions[v][1] = 1.0f - vertices[v][1] / 32.0f;
        positions[v][2] = 0.0f;
        positions[v][3] = 1.0f;
    }
    std::memcpy(title + constants_offset, color, sizeof(color));
    std::memcpy(title + positions_offset, positions, sizeof(positions));

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
        std::printf("title_gpu_state=%d title_gpu_hr=0x%08lx\n", start.title_gpu_state,
                    static_cast<unsigned long>(start.title_gpu_hr));
        ComPtr<ID3D12RootSignature> root = title_root_signature(gpu.device.Get());
        const auto vs = container(X2W_SHADER_STAGE_VERTEX, r3_vs, sizeof(r3_vs), vertex_bindings());
        const auto ps = container(X2W_SHADER_STAGE_PIXEL, r3_ps, sizeof(r3_ps), {{2, X2W_SHADER_BINDING_INTERP, 0, 0}});
        ComPtr<ID3D12PipelineState> pso;
        double ms = 0;
        const HRESULT hr = !root     ? E_FAIL
                           : stream ? create_stream_pipeline(gpu.device.Get(), root.Get(), vs, ps, pso, &ms)
                                    : create_pipeline(gpu.device.Get(), root.Get(), vs, ps, pso, &ms);
        std::printf("pso_create_ms=%.3f hr=0x%08lx mode=%s\n", ms, static_cast<unsigned long>(hr),
                    std::string(mode).c_str());
        good = good && SUCCEEDED(hr);
        unsigned mismatches = 0;
        if (good) good = draw_frame(gpu, root.Get(), pso.Get(), reinterpret_cast<std::uintptr_t>(title), expected, mismatches);
        pso.Reset();
        root.Reset();
        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        const unsigned translated = end.shaders_translated - start.shaders_translated;
        const unsigned cached = end.shaders_cached - start.shaders_cached;
        const unsigned files = cached_files(cache);
        std::printf("shaders_translated=%u shaders_cached=%u cache_files=%u refused=%u draws_refused=%u "
                    "debug_errors=%u unknown_slots=%llu unknown_iids=%llu\n",
                    translated, cached, files, recorded.refused, end.draws_refused, debug_errors,
                    static_cast<unsigned long long>(end.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls));
        good = good && debug_errors == 0 && recorded.refused == 0 && end.unknown_slot_calls == 0 &&
               end.unknown_iid_calls == 0 && files == 2;
        if (cold) good = good && translated == 2 && cached == 0;
        if (warm) good = good && translated == 0 && cached == 2;
        if (control) {
            std::printf("control=%s\n", mismatches == covered ? "mismatch_detected" : "mismatch_missed");
            rc = good && mismatches == covered ? 0 : 1;
        } else {
            rc = good && mismatches == 0 ? 0 : 1;
        }
        X2WGfxSetLogSink(nullptr, nullptr);
    }
    XMemFree(title, graphics_word);
    const auto released = counters();
    std::printf("live_objects=%u\n", released.live_objects);
    return released.live_objects == 0 ? rc : 1;
}

int refused_check()
{
    Gpu gpu;
    if (gpu.create(true)) return 1;
    Recorded recorded;
    X2WGfxSetLogSink(record, &recorded);
    const auto start = counters();
    ComPtr<ID3D12RootSignature> root = title_root_signature(gpu.device.Get());
    const auto vs = container(X2W_SHADER_STAGE_VERTEX, r3_refused_vs, sizeof(r3_refused_vs), vertex_bindings());
    const auto ps = container(X2W_SHADER_STAGE_PIXEL, r3_ps, sizeof(r3_ps), {{2, X2W_SHADER_BINDING_INTERP, 0, 0}});
    ComPtr<ID3D12PipelineState> pso;
    const HRESULT hr = root ? create_pipeline(gpu.device.Get(), root.Get(), vs, ps, pso, nullptr) : E_FAIL;
    // A container with a stage that does not match its slot is refused before any translation.
    ComPtr<ID3D12PipelineState> swapped;
    const HRESULT swapped_hr = root ? create_pipeline(gpu.device.Get(), root.Get(), ps, vs, swapped, nullptr) : E_FAIL;
    // The same refusal through a pipeline-state stream.
    ComPtr<ID3D12PipelineState> streamed;
    const HRESULT stream_hr =
        root ? create_stream_pipeline(gpu.device.Get(), root.Get(), vs, ps, streamed, nullptr) : E_FAIL;
    const auto end = counters();
    X2WGfxSetLogSink(nullptr, nullptr);
    std::printf("hr=0x%08lx swapped_hr=0x%08lx stream_hr=0x%08lx refused_events=%u pipelines_refused=%u "
                "translated=%u\n",
                static_cast<unsigned long>(hr), static_cast<unsigned long>(swapped_hr),
                static_cast<unsigned long>(stream_hr), recorded.refused, end.pipelines_refused - start.pipelines_refused,
                end.shaders_translated - start.shaders_translated);
    const bool named = recorded.details.find("mrt0 is not a vertex-shader export") != std::string::npos;
    const bool good = hr == E_NOTIMPL && !pso && swapped_hr == E_NOTIMPL && !swapped && stream_hr == E_NOTIMPL &&
                      !streamed && recorded.refused == 3 && end.pipelines_refused - start.pipelines_refused == 3 && named &&
                      end.shaders_translated == start.shaders_translated && gpu.debug_errors() == 0;
    std::printf("refused=%s\n", good ? "pass" : "fail");
    return good ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc != 3) return 2;
    const std::string_view adapter = argv[1];
    const std::string_view mode = argv[2];
    if (adapter != "warp" && adapter != "hardware") return 2;
    const bool warp = adapter == "warp";
    if (mode == "cold" || mode == "warm" || mode == "wrong_reference" || mode == "stream" ||
        mode == "stream_wrong_reference")
        return triangle_check(warp, mode);
    if (mode == "refused" && warp) return refused_check();
    return 2;
}
