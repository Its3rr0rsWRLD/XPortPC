// Runtime ladder R5 (docs/design/runtime.md, section 6): compute and a sustained frame loop through the graphics shim.
//
// A console-style program: device, queues, root signatures and pipelines come from d3d12_xs.dll (no desktop
// d3d12.lib), title memory from xmem.dll. Each of 600 frames
//   1. records on a compute list (D3D12_COMMAND_LIST_TYPE_COMPUTE) a dispatch of the gfx1013 compute program
//      tests/runtime/r5_cs.s (r5_programs.h), which reads the particle states in title memory, moves every particle
//      by its velocity, writes the state back and writes the particle's quad (six clip-space positions) into a vertex
//      buffer in title memory; the program gets both title GPU addresses through root UAVs, the quad half-size through
//      a root constant and its particle index from the workgroup id and local id;
//   2. submits it on a compute queue that first waits for the previous frame's graphics work (it must not overwrite
//      vertices a draw still reads), and signals a compute fence;
//   3. records on the direct queue's list, which waits for that compute fence, one draw per particle with the R3
//      programs (tests/runtime/r3_vs.s reads the six positions through a root SRV of title memory, r3_ps.s exports the
//      particle's colour from a root CBV of title memory), and presents.
// The shim translates the three programs at pipeline creation (cache in X2W_CACHE_DIR\r5_frames).
//
//   r5_frames warp|hardware cold             cache emptied first: all three shaders translated, then 600 frames
//   r5_frames warp|hardware warm             after cold: all three shaders from the cache, then 600 frames
//   r5_frames warp|hardware wrong_reference  control: the sampled frames against a reference 16 compute steps stale
//                                            (what a missing cross-queue wait could show); passes only if exactly
//                                            the pixels that differ between the two references mismatch, and some do
//   r5_frames warp|hardware view_churn       after cold: as warm, and each frame allocates title memory and frees
//                                            an older allocation, so the title-memory view changes 600 times (the
//                                            shim recycles its 256 view blocks once the GPU is done with them)
//   r5_frames warp refused                   a compute program the translator refuses (ds_bpermute_b32) fails
//                                            CreateComputePipelineState with E_NOTIMPL and one REFUSED event; a
//                                            compute container in a vertex slot and a vertex container in the
//                                            compute slot are refused before translation
//
// Checks of the frame modes: frames 0, 1, 149, 299, 449 and 599 are read back and compared with a CPU reference bit
// for bit; after the loop the particle states and the vertex buffer in title memory (read by the CPU through the
// alias) equal the reference's binary32 words; no shader is translated or loaded after the pipelines exist (the cache
// hit rate of the loop is 100%); no debug-layer error; no wrapper object alive at exit; the process's handle count
// and private bytes do not grow between frame 100 and frame 599. Frame time (the interval between successive
// Present returns) is printed as frame_ms_avg/p50/p99/max and is not gated.
//
// The reference. 256x256 R8G8B8A8_UNORM, clear colour, then each particle's axis-aligned quad in its colour, in
// draw order. Positions are multiples of 1/32 pixel: every edge sits at an odd multiple of 1/32 pixel and velocities
// are even multiples, so no pixel centre lies on an edge in any frame (the data does not depend on the fill rule),
// and every value is exact in binary32, so the GPU's additions equal the CPU's. Frame f shows the state after f + 1
// updates.
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "era_title_gpu_api.h"
#include "r3_programs.h"
#include "r5_programs.h"

#include <psapi.h>

#include <algorithm>
#include <cmath>
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
constexpr UINT width = 256;
constexpr UINT height = 256;
constexpr UINT row_pitch = width * 4;
constexpr UINT frames = 600;
constexpr UINT samples[] = {0, 1, 149, 299, 449, 599};
constexpr UINT sample_count = sizeof(samples) / sizeof(samples[0]);
constexpr UINT stale_steps = 16;  // wrong_reference
constexpr UINT particles = 8;
constexpr UINT group_size = 4;  // r5_cs.s: workgroup 4x1x1
constexpr UINT vertex_stride_bytes = 128;  // r5_cs.s: 8 float4 per particle, 6 used
constexpr std::uint8_t clear_rgba[4] = {10, 20, 30, 255};
// Title memory layout: colours at 256 * k (a root CBV is 256-byte aligned), states at 4096, vertices at 8192.
constexpr std::size_t states_offset = 4096;
constexpr std::size_t vertices_offset = 8192;
constexpr SIZE_T title_bytes = 64 * 1024;

// Particles in 1/32 pixel units (y down): centre (odd), velocity per frame (even), colour.
struct Particle {
    int x, y, vx, vy;
    std::uint8_t rgba[4];
};
constexpr int half_size = 6 * 32;  // the quad half-size: 6 pixels
constexpr Particle initial[particles] = {
    {40 * 32 + 1, 40 * 32 + 3, 4, 2, {200, 100, 50, 255}},   {200 * 32 + 5, 60 * 32 + 1, -6, 2, {30, 220, 90, 255}},
    {128 * 32 + 7, 128 * 32 + 9, 2, -4, {250, 250, 20, 255}}, {70 * 32 + 11, 200 * 32 + 13, 6, -2, {90, 40, 230, 255}},
    {180 * 32 + 15, 180 * 32 + 17, -4, -6, {255, 255, 255, 255}}, {100 * 32 + 19, 30 * 32 + 21, 0, 6, {140, 10, 160, 255}},
    {30 * 32 + 23, 128 * 32 + 25, 6, 0, {0, 128, 128, 255}},   {150 * 32 + 27, 100 * 32 + 29, -2, -2, {255, 0, 64, 255}},
};

// Root parameters of the title's root signatures, and the SGPRs the containers bind to their words.
constexpr UINT gfx_constants = 0;  // root CBV b0: the colour
constexpr UINT gfx_positions = 1;  // root SRV t0: the vertex buffer
constexpr UINT cs_states = 0;      // root UAV u0: the particle states
constexpr UINT cs_vertices = 1;    // root UAV u1: the vertex buffer
constexpr UINT cs_half = 2;        // root constants b0: the quad half-size (binary32)

// pixels -> clip space, exact in binary32 for multiples of 1/32 pixel inside the target.
float clip_x(int x32) { return float(x32) / (32.0f * 128.0f) - 1.0f; }
float clip_y(int y32) { return 1.0f - float(y32) / (32.0f * 128.0f); }
float clip_dx(int dx32) { return float(dx32) / (32.0f * 128.0f); }
float clip_dy(int dy32) { return -float(dy32) / (32.0f * 128.0f); }
std::uint32_t bits(float value)
{
    std::uint32_t out;
    std::memcpy(&out, &value, 4);
    return out;
}

// Container (d3d12_xs_api.h) around one program; a compute container also gets its X2WShaderComputeInfo.
std::vector<std::uint8_t> container(X2WShaderStage stage, const std::uint8_t* code, std::size_t bytes,
                                    const std::vector<X2WShaderBinding>& bindings)
{
    X2WShaderContainer header{};
    header.magic = X2W_SHADER_CONTAINER_MAGIC;
    header.version = X2W_SHADER_CONTAINER_VERSION;
    header.stage = stage;
    header.binding_count = static_cast<std::uint32_t>(bindings.size());
    header.binding_offset = sizeof(header);
    std::uint32_t at = static_cast<std::uint32_t>(sizeof(header) + bindings.size() * sizeof(X2WShaderBinding));
    const X2WShaderComputeInfo info{{group_size, 1, 1}, 32, 1};
    if (stage == X2W_SHADER_STAGE_COMPUTE) {
        header.stage_info_offset = at;
        at += sizeof(info);
    }
    header.code_offset = at;
    header.code_bytes = static_cast<std::uint32_t>(bytes);
    std::vector<std::uint8_t> out(header.code_offset + bytes);
    std::memcpy(out.data(), &header, sizeof(header));
    if (!bindings.empty()) std::memcpy(out.data() + sizeof(header), bindings.data(), bindings.size() * sizeof(bindings[0]));
    if (header.stage_info_offset) std::memcpy(out.data() + header.stage_info_offset, &info, sizeof(info));
    std::memcpy(out.data() + header.code_offset, code, bytes);
    return out;
}

std::vector<X2WShaderBinding> vertex_bindings()
{
    return {{2, X2W_SHADER_BINDING_ROOT_WORD, gfx_positions, 0}, {3, X2W_SHADER_BINDING_ROOT_WORD, gfx_positions, 1},
            {4, X2W_SHADER_BINDING_ROOT_WORD, gfx_constants, 0}, {5, X2W_SHADER_BINDING_ROOT_WORD, gfx_constants, 1}};
}

std::vector<X2WShaderBinding> compute_bindings()
{
    return {{2, X2W_SHADER_BINDING_ROOT_WORD, cs_states, 0},   {3, X2W_SHADER_BINDING_ROOT_WORD, cs_states, 1},
            {4, X2W_SHADER_BINDING_ROOT_WORD, cs_vertices, 0}, {5, X2W_SHADER_BINDING_ROOT_WORD, cs_vertices, 1},
            {6, X2W_SHADER_BINDING_ROOT_WORD, cs_half, 0},     {7, X2W_SHADER_BINDING_GROUP_ID, 0, 0}};
}

// The reference frame after `steps` compute updates; false if a pixel centre lies on an edge or a quad leaves the
// target.
bool reference(UINT steps, std::vector<std::uint8_t>& out)
{
    out.assign(static_cast<std::size_t>(width) * height * 4, 0);
    for (std::size_t i = 0; i < out.size(); i += 4) std::memcpy(&out[i], clear_rgba, 4);
    for (const Particle& p : initial) {
        const long long cx = p.x + static_cast<long long>(steps) * p.vx, cy = p.y + static_cast<long long>(steps) * p.vy;
        const long long x0 = cx - half_size, x1 = cx + half_size, y0 = cy - half_size, y1 = cy + half_size;
        if (x0 < 0 || y0 < 0 || x1 > 32LL * width || y1 > 32LL * height) return false;
        for (long long e : {x0, x1, y0, y1})
            if (e % 32 == 16) return false;
        for (UINT y = 0; y < height; ++y) {
            const long long centre_y = 32LL * y + 16;
            if (centre_y < y0 || centre_y >= y1) continue;
            for (UINT x = 0; x < width; ++x) {
                const long long centre_x = 32LL * x + 16;
                if (centre_x >= x0 && centre_x < x1)
                    std::memcpy(&out[(static_cast<std::size_t>(y) * width + x) * 4], p.rgba, 4);
            }
        }
    }
    return true;
}

// The title-memory words the CPU expects after `steps` updates: states (cx, cy, vx, vy) and the six positions'
// x, y (z = 0, w = 1 written once by the CPU) per particle.
void expected_memory(UINT steps, std::vector<std::uint32_t>& states, std::vector<std::uint32_t>& vertices)
{
    states.assign(particles * 4, 0);
    vertices.assign(particles * vertex_stride_bytes / 4, 0);
    for (UINT k = 0; k < particles; ++k) {
        const Particle& p = initial[k];
        float cx = clip_x(p.x), cy = clip_y(p.y);
        const float vx = clip_dx(p.vx), vy = clip_dy(p.vy);
        for (UINT s = 0; s < steps; ++s) {
            cx = cx + vx;  // as r5_cs.s adds, one binary32 addition per update
            cy = cy + vy;
        }
        const float h = clip_dx(half_size);
        states[k * 4 + 0] = bits(cx);
        states[k * 4 + 1] = bits(cy);
        states[k * 4 + 2] = bits(vx);
        states[k * 4 + 3] = bits(vy);
        const float x0 = cx - h, y0 = cy - h, x1 = h + cx, y1 = h + cy;
        const float corners[6][2] = {{x0, y0}, {x1, y0}, {x0, y1}, {x1, y0}, {x1, y1}, {x0, y1}};
        for (UINT v = 0; v < 6; ++v) {
            std::uint32_t* w = &vertices[(k * vertex_stride_bytes) / 4 + v * 4];
            w[0] = bits(corners[v][0]);
            w[1] = bits(corners[v][1]);
            w[2] = bits(0.0f);
            w[3] = bits(1.0f);
        }
    }
}

ComPtr<ID3D12RootSignature> make_root(ID3D12Device* device, const D3D12_ROOT_PARAMETER1* params, UINT count,
                                      D3D12_ROOT_SIGNATURE_FLAGS flags)
{
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = count;
    desc.Desc_1_1.pParameters = params;
    desc.Desc_1_1.Flags = flags;
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

ComPtr<ID3D12RootSignature> graphics_root(ID3D12Device* device)
{
    D3D12_ROOT_PARAMETER1 params[2]{};
    params[gfx_constants].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
    params[gfx_constants].Descriptor = {0, 0, D3D12_ROOT_DESCRIPTOR_FLAG_NONE};
    params[gfx_constants].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    params[gfx_positions].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
    params[gfx_positions].Descriptor = {0, 0, D3D12_ROOT_DESCRIPTOR_FLAG_NONE};
    params[gfx_positions].ShaderVisibility = D3D12_SHADER_VISIBILITY_VERTEX;
    return make_root(device, params, 2, D3D12_ROOT_SIGNATURE_FLAG_DENY_HULL_SHADER_ROOT_ACCESS);
}

ComPtr<ID3D12RootSignature> compute_root(ID3D12Device* device)
{
    D3D12_ROOT_PARAMETER1 params[3]{};
    params[cs_states].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
    params[cs_states].Descriptor = {0, 0, D3D12_ROOT_DESCRIPTOR_FLAG_NONE};
    params[cs_vertices].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
    params[cs_vertices].Descriptor = {1, 0, D3D12_ROOT_DESCRIPTOR_FLAG_NONE};
    params[cs_half].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[cs_half].Constants = {0, 0, 1};
    for (auto& p : params) p.ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
    return make_root(device, params, 3, D3D12_ROOT_SIGNATURE_FLAG_NONE);
}

double seconds_since(const LARGE_INTEGER& start)
{
    LARGE_INTEGER now, frequency;
    QueryPerformanceCounter(&now);
    QueryPerformanceFrequency(&frequency);
    return double(now.QuadPart - start.QuadPart) / double(frequency.QuadPart);
}

HRESULT graphics_pipeline(ID3D12Device* device, ID3D12RootSignature* root, const std::vector<std::uint8_t>& vs,
                          const std::vector<std::uint8_t>& ps, ComPtr<ID3D12PipelineState>& pso)
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
    return device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso));
}

HRESULT compute_pipeline(ID3D12Device* device, ID3D12RootSignature* root, const std::vector<std::uint8_t>& cs,
                         ComPtr<ID3D12PipelineState>& pso)
{
    D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};
    desc.pRootSignature = root;
    desc.CS = {cs.data(), cs.size()};
    return device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pso));
}

std::wstring cache_directory()
{
    wchar_t root[1024];
    const DWORD n = GetEnvironmentVariableW(L"X2W_CACHE_DIR", root, 1024);
    if (!n || n >= 1024) return {};
    return std::wstring(root) + L"\\r5_frames";
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

struct ProcessUse {
    DWORD handles = 0;
    SIZE_T private_bytes = 0;
};

ProcessUse process_use()
{
    ProcessUse use;
    GetProcessHandleCount(GetCurrentProcess(), &use.handles);
    PROCESS_MEMORY_COUNTERS_EX memory{};
    memory.cb = sizeof(memory);
    if (K32GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory), sizeof(memory)))
        use.private_bytes = memory.PrivateUsage;
    return use;
}

bool wait_fence(ID3D12Fence* fence, UINT64 value, HANDLE event)
{
    if (fence->GetCompletedValue() >= value) return true;
    if (!ok(fence->SetEventOnCompletion(value, event), "SetEventOnCompletion")) return false;
    if (WaitForSingleObject(event, 20000) != WAIT_OBJECT_0) {
        std::fputs("r5: fence wait timed out\n", stderr);
        return false;
    }
    return true;
}

void pump_messages()
{
    MSG message;
    while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
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
    ComPtr<ID3D12Resource> buffer;
    ok(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                       IID_PPV_ARGS(&buffer)),
       "CreateCommittedResource(readback)");
    return buffer;
}

// Counts the pixels of a read-back frame that differ from `expected`.
unsigned compare(ID3D12Resource* readback, const std::vector<std::uint8_t>& expected, unsigned* first_at,
                 std::uint32_t* first)
{
    void* mapped = nullptr;
    const D3D12_RANGE read{0, static_cast<SIZE_T>(row_pitch) * height};
    if (!ok(readback->Map(0, &read, &mapped), "Map")) return ~0u;
    unsigned mismatches = 0;
    for (UINT y = 0; y < height; ++y) {
        const auto* row = static_cast<const std::uint8_t*>(mapped) + static_cast<SIZE_T>(y) * row_pitch;
        for (UINT x = 0; x < width; ++x) {
            if (std::memcmp(row + x * 4, &expected[(static_cast<std::size_t>(y) * width + x) * 4], 4) != 0) {
                if (!mismatches) {
                    *first_at = y * width + x;
                    std::memcpy(first, row + x * 4, 4);
                }
                ++mismatches;
            }
        }
    }
    const D3D12_RANGE none{0, 0};
    readback->Unmap(0, &none);
    return mismatches;
}

unsigned differing(const std::vector<std::uint8_t>& a, const std::vector<std::uint8_t>& b)
{
    unsigned count = 0;
    for (std::size_t i = 0; i < a.size(); i += 4) count += std::memcmp(&a[i], &b[i], 4) != 0;
    return count;
}

struct Loop {
    unsigned sample_mismatches[sample_count] = {};
    std::vector<double> frame_ms;
    unsigned debug_errors = 0;
    ProcessUse at_100, at_599;
    bool api_good = false;
};

// The 600-frame loop. Everything it creates is released before it returns.
bool run_frames(Gpu& gpu, ID3D12RootSignature* groot, ID3D12PipelineState* gpso, ID3D12RootSignature* croot,
                ID3D12PipelineState* cpso, std::uintptr_t title, const std::vector<std::uint8_t>* expected, bool churn,
                Loop& loop)
{
    // churn: each frame allocates graphics title memory and frees the allocation of three frames before, so the
    // title-memory view changes every frame (600 views, more than the shim's 256 view blocks): the shim must reuse
    // blocks the GPU has finished with. An allocation is freed only after every frame whose view held it is done.
    void* churned[frames] = {};
    ID3D12Device* device = gpu.device.Get();
    HWND window = make_window(width, height);
    if (!window) return false;
    bool good = true;
    {
        D3D12_COMMAND_QUEUE_DESC queue_desc{};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_COMPUTE;
        ComPtr<ID3D12CommandQueue> cqueue;
        ComPtr<ID3D12CommandAllocator> callocators[2], gallocators[2];
        ComPtr<ID3D12GraphicsCommandList> clist;
        ComPtr<ID3D12Fence> cfence;
        good = ok(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&cqueue)), "CreateCommandQueue(compute)") &&
               ok(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&cfence)), "CreateFence(compute)");
        for (int i = 0; good && i < 2; ++i) {
            good = ok(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COMPUTE, IID_PPV_ARGS(&callocators[i])),
                      "CreateCommandAllocator(compute)") &&
                   ok(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&gallocators[i])),
                      "CreateCommandAllocator(direct)");
        }
        good = good && ok(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COMPUTE, callocators[0].Get(), nullptr,
                                                    IID_PPV_ARGS(&clist)),
                          "CreateCommandList(compute)") &&
               ok(clist->Close(), "Close(compute)");

        DXGI_SWAP_CHAIN_DESC1 desc{};
        desc.Width = width;
        desc.Height = height;
        desc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        desc.SampleDesc.Count = 1;
        desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
        desc.BufferCount = 2;
        desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD;
        ComPtr<IDXGISwapChain3> chain;
        good = good && ok(X2WGfxCreateSwapChainForHwnd(gpu.queue.Get(), window, &desc, nullptr, nullptr,
                                                      IID_PPV_ARGS(&chain)),
                          "X2WGfxCreateSwapChainForHwnd");
        D3D12_DESCRIPTOR_HEAP_DESC heap_desc{};
        heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        heap_desc.NumDescriptors = 2;
        ComPtr<ID3D12DescriptorHeap> rtv_heap;
        ComPtr<ID3D12Resource> back[2];
        D3D12_CPU_DESCRIPTOR_HANDLE rtv[2]{};
        good = good && ok(device->CreateDescriptorHeap(&heap_desc, IID_PPV_ARGS(&rtv_heap)), "CreateDescriptorHeap");
        for (UINT i = 0; good && i < 2; ++i) {
            good = ok(chain->GetBuffer(i, IID_PPV_ARGS(&back[i])), "GetBuffer");
            rtv[i] = rtv_heap->GetCPUDescriptorHandleForHeapStart();
            rtv[i].ptr += static_cast<SIZE_T>(i) * device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
            if (good) device->CreateRenderTargetView(back[i].Get(), nullptr, rtv[i]);
        }
        ComPtr<ID3D12Resource> readbacks[sample_count];
        for (UINT s = 0; good && s < sample_count; ++s) {
            readbacks[s] = readback_buffer(device, static_cast<UINT64>(row_pitch) * height);
            good = readbacks[s] != nullptr;
        }

        const std::uint32_t half_bits = bits(clip_dx(half_size));
        const FLOAT clear[4] = {clear_rgba[0] / 255.0f, clear_rgba[1] / 255.0f, clear_rgba[2] / 255.0f,
                                clear_rgba[3] / 255.0f};
        const D3D12_VIEWPORT viewport{0, 0, float(width), float(height), 0, 1};
        const D3D12_RECT scissor{0, 0, LONG(width), LONG(height)};
        LARGE_INTEGER last{};
        QueryPerformanceCounter(&last);
        UINT next_sample = 0;
        for (UINT f = 0; good && f < frames; ++f) {
            const UINT slot = f % 2;
            // The allocators of frame f - 2 are free once its graphics work (which waited for its compute) is done.
            if (f >= 2 && !wait_fence(gpu.fence.Get(), f - 1, gpu.event)) {
                good = false;
                break;
            }
            if (churn) {
                churned[f] = XMemAlloc(64 * 1024, graphics_word);
                if (!churned[f]) {
                    std::fputs("r5: XMemAlloc(graphics) failed in the churn loop\n", stderr);
                    good = false;
                    break;
                }
                // Frame f - 3's view was the last to hold it, and frame f - 2 is done (waited above).
                if (f >= 3) {
                    XMemFree(churned[f - 3], graphics_word);
                    churned[f - 3] = nullptr;
                }
            }
            // Compute: move the particles, write the quads.
            good = ok(callocators[slot]->Reset(), "compute allocator Reset") &&
                   ok(clist->Reset(callocators[slot].Get(), cpso), "compute list Reset");
            if (!good) break;
            clist->SetComputeRootSignature(croot);
            clist->SetComputeRootUnorderedAccessView(cs_states, title + states_offset);
            clist->SetComputeRootUnorderedAccessView(cs_vertices, title + vertices_offset);
            clist->SetComputeRoot32BitConstant(cs_half, half_bits, 0);
            clist->Dispatch(particles / group_size, 1, 1);
            good = ok(clist->Close(), "compute Close");
            // Not before the previous frame's draws have read the vertices (gpu.fence reaches f after frame f - 1).
            if (f) good = good && ok(cqueue->Wait(gpu.fence.Get(), f), "compute queue Wait");
            ID3D12CommandList* clists[] = {clist.Get()};
            if (good) cqueue->ExecuteCommandLists(1, clists);
            good = good && ok(cqueue->Signal(cfence.Get(), f + 1), "compute queue Signal");

            // Graphics: one draw per particle from the vertices the dispatch wrote.
            const UINT index = chain->GetCurrentBackBufferIndex();
            const bool sampled = next_sample < sample_count && samples[next_sample] == f;
            good = good && ok(gallocators[slot]->Reset(), "direct allocator Reset") &&
                   ok(gpu.list->Reset(gallocators[slot].Get(), gpso), "direct list Reset");
            if (!good) break;
            auto barrier = transition(back[index].Get(), D3D12_RESOURCE_STATE_PRESENT, D3D12_RESOURCE_STATE_RENDER_TARGET);
            gpu.list->ResourceBarrier(1, &barrier);
            gpu.list->ClearRenderTargetView(rtv[index], clear, 0, nullptr);
            gpu.list->OMSetRenderTargets(1, &rtv[index], FALSE, nullptr);
            gpu.list->RSSetViewports(1, &viewport);
            gpu.list->RSSetScissorRects(1, &scissor);
            gpu.list->SetGraphicsRootSignature(groot);
            gpu.list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            for (UINT k = 0; k < particles; ++k) {
                gpu.list->SetGraphicsRootConstantBufferView(gfx_constants, title + 256 * k);
                gpu.list->SetGraphicsRootShaderResourceView(gfx_positions, title + vertices_offset + vertex_stride_bytes * k);
                gpu.list->DrawInstanced(6, 1, 0, 0);
            }
            if (sampled) {
                barrier = transition(back[index].Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
                gpu.list->ResourceBarrier(1, &barrier);
                D3D12_TEXTURE_COPY_LOCATION dst{};
                dst.pResource = readbacks[next_sample].Get();
                dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
                dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R8G8B8A8_UNORM, width, height, 1, row_pitch};
                D3D12_TEXTURE_COPY_LOCATION src{};
                src.pResource = back[index].Get();
                src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
                barrier = transition(back[index].Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_PRESENT);
                ++next_sample;
            } else {
                barrier = transition(back[index].Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_PRESENT);
            }
            gpu.list->ResourceBarrier(1, &barrier);
            good = ok(gpu.list->Close(), "direct Close") && ok(gpu.queue->Wait(cfence.Get(), f + 1), "direct queue Wait");
            ID3D12CommandList* glists[] = {gpu.list.Get()};
            if (good) gpu.queue->ExecuteCommandLists(1, glists);
            good = good && ok(gpu.queue->Signal(gpu.fence.Get(), f + 1), "direct queue Signal") &&
                   ok(chain->Present(0, 0), "Present");
            const double ms = 1000.0 * seconds_since(last);
            QueryPerformanceCounter(&last);
            loop.frame_ms.push_back(ms);
            pump_messages();
            if (f % 100 == 99) loop.debug_errors += gpu.debug_errors();
            if (f == 100) loop.at_100 = process_use();
            if (f == frames - 1) loop.at_599 = process_use();
        }
        // Drain both queues, the presents included, before anything is released.
        gpu.fence_value = frames + 1;
        good = good && ok(gpu.queue->Signal(gpu.fence.Get(), frames + 1), "direct queue Signal") &&
               ok(cqueue->Signal(cfence.Get(), frames + 1), "compute queue Signal") &&
               wait_fence(gpu.fence.Get(), frames + 1, gpu.event) && wait_fence(cfence.Get(), frames + 1, gpu.event) &&
               ok(device->GetDeviceRemovedReason(), "device");
        if (good) {
            for (UINT s = 0; s < sample_count; ++s) {
                unsigned first_at = 0;
                std::uint32_t first = 0;
                loop.sample_mismatches[s] = compare(readbacks[s].Get(), expected[s], &first_at, &first);
                std::printf("frame=%u mismatches=%u", samples[s], loop.sample_mismatches[s]);
                if (loop.sample_mismatches[s]) std::printf(" first_pixel=%u first=%08x", first_at, static_cast<unsigned>(first));
                std::printf("\n");
            }
        }
        loop.api_good = good;
        for (void*& block : churned)
            if (block) {
                XMemFree(block, graphics_word);
                block = nullptr;
            }
        std::puts("loop: releasing");
        for (auto& b : back) b.Reset();
        chain.Reset();
        std::puts("loop: swap chain released");
    }
    std::puts("loop: objects released");
    DestroyWindow(window);
    pump_messages();
    std::puts("loop: window destroyed");
    return good;
}

int frames_check(bool warp, std::string_view mode)
{
    const bool cold = mode == "cold", warm = mode == "warm", control = mode == "wrong_reference";
    const bool churn = mode == "view_churn";
    const std::wstring cache = cache_directory();
    if (cache.empty()) {
        std::fputs("r5: X2W_CACHE_DIR must name the test's cache root\n", stderr);
        return 1;
    }
    if (cold && !empty_cache(cache)) {
        std::fputs("r5: cannot empty the cache directory\n", stderr);
        return 1;
    }
    std::vector<std::uint8_t> expected[sample_count], right[sample_count];
    unsigned control_differs[sample_count] = {};
    for (UINT s = 0; s < sample_count; ++s) {
        if (!reference(samples[s] + 1, right[s]) ||
            (control && !reference(samples[s] + 1 >= stale_steps ? samples[s] + 1 - stale_steps : 0, expected[s]))) {
            std::fputs("r5: a pixel centre lies on a quad edge or a quad leaves the target; choose other particles\n",
                       stderr);
            return 1;
        }
        if (!control) expected[s] = right[s];
        control_differs[s] = differing(right[s], expected[s]);
    }
    for (UINT steps = 0; steps <= frames; ++steps) {
        std::vector<std::uint8_t> frame;
        if (!reference(steps, frame)) {
            std::fprintf(stderr, "r5: the reference is ambiguous or leaves the target after %u steps\n", steps);
            return 1;
        }
    }

    auto* title = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    if (!title) {
        std::fputs("r5: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    std::vector<std::uint32_t> states0, vertices0, states_end, vertices_end;
    expected_memory(0, states0, vertices0);
    expected_memory(frames, states_end, vertices_end);
    std::memset(title, 0, title_bytes);
    for (UINT k = 0; k < particles; ++k) {
        float color[4];
        for (int c = 0; c < 4; ++c) color[c] = initial[k].rgba[c] / 255.0f;
        std::memcpy(title + 256 * k, color, sizeof(color));
    }
    std::memcpy(title + states_offset, states0.data(), states0.size() * 4);
    std::memcpy(title + vertices_offset, vertices0.data(), vertices0.size() * 4);

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
        ComPtr<ID3D12RootSignature> groot = graphics_root(gpu.device.Get()), croot = compute_root(gpu.device.Get());
        const auto vs = container(X2W_SHADER_STAGE_VERTEX, r3_vs, sizeof(r3_vs), vertex_bindings());
        const auto ps = container(X2W_SHADER_STAGE_PIXEL, r3_ps, sizeof(r3_ps), {{2, X2W_SHADER_BINDING_INTERP, 0, 0}});
        const auto cs = container(X2W_SHADER_STAGE_COMPUTE, r5_cs, sizeof(r5_cs), compute_bindings());
        ComPtr<ID3D12PipelineState> gpso, cpso;
        LARGE_INTEGER t0;
        QueryPerformanceCounter(&t0);
        const HRESULT chr = croot ? compute_pipeline(gpu.device.Get(), croot.Get(), cs, cpso) : E_FAIL;
        const double cms = 1000.0 * seconds_since(t0);
        QueryPerformanceCounter(&t0);
        const HRESULT ghr = groot ? graphics_pipeline(gpu.device.Get(), groot.Get(), vs, ps, gpso) : E_FAIL;
        const double gms = 1000.0 * seconds_since(t0);
        std::printf("compute_pso_ms=%.3f hr=0x%08lx graphics_pso_ms=%.3f hr=0x%08lx mode=%s\n", cms,
                    static_cast<unsigned long>(chr), gms, static_cast<unsigned long>(ghr), std::string(mode).c_str());
        good = good && SUCCEEDED(chr) && SUCCEEDED(ghr);
        const auto before_loop = counters();
        Loop loop;
        if (good)
            good = run_frames(gpu, groot.Get(), gpso.Get(), croot.Get(), cpso.Get(),
                              reinterpret_cast<std::uintptr_t>(title), expected, churn, loop);
        const auto after_loop = counters();

        // Title memory after the loop, as the CPU sees it through the alias.
        const bool states_ok = std::memcmp(title + states_offset, states_end.data(), states_end.size() * 4) == 0;
        const bool vertices_ok = std::memcmp(title + vertices_offset, vertices_end.data(), vertices_end.size() * 4) == 0;
        std::printf("title_states=%s title_vertices=%s\n", states_ok ? "match" : "mismatch",
                    vertices_ok ? "match" : "mismatch");

        if (!loop.frame_ms.empty()) {
            std::vector<double> sorted(loop.frame_ms.begin() + 1, loop.frame_ms.end());
            std::sort(sorted.begin(), sorted.end());
            double sum = 0;
            for (double v : sorted) sum += v;
            const auto at = [&](double q) {
                return sorted[std::min(sorted.size() - 1, static_cast<std::size_t>(std::ceil(q * sorted.size())) - 1)];
            };
            std::printf("frames=%zu first_frame_ms=%.3f frame_ms_avg=%.3f frame_ms_p50=%.3f frame_ms_p99=%.3f "
                        "frame_ms_max=%.3f\n",
                        loop.frame_ms.size(), loop.frame_ms[0], sorted.empty() ? 0.0 : sum / sorted.size(),
                        sorted.empty() ? 0.0 : at(0.50), sorted.empty() ? 0.0 : at(0.99),
                        sorted.empty() ? 0.0 : sorted.back());
        }
        const long long handle_growth = static_cast<long long>(loop.at_599.handles) - loop.at_100.handles;
        const long long private_growth =
            static_cast<long long>(loop.at_599.private_bytes) - static_cast<long long>(loop.at_100.private_bytes);
        std::printf("handles_f100=%lu handles_f599=%lu private_kb_f100=%llu private_kb_f599=%llu\n",
                    loop.at_100.handles, loop.at_599.handles,
                    static_cast<unsigned long long>(loop.at_100.private_bytes / 1024),
                    static_cast<unsigned long long>(loop.at_599.private_bytes / 1024));
        gpso.Reset();
        cpso.Reset();
        groot.Reset();
        croot.Reset();
        const unsigned debug_errors = loop.debug_errors + gpu.debug_errors();
        const auto end = counters();
        const unsigned translated = before_loop.shaders_translated - start.shaders_translated;
        const unsigned cached = before_loop.shaders_cached - start.shaders_cached;
        const unsigned loop_shaders = (after_loop.shaders_translated - before_loop.shaders_translated) +
                                      (after_loop.shaders_cached - before_loop.shaders_cached);
        const unsigned files = cached_files(cache);
        const unsigned long long title_misses = end.title_lookup_misses - start.title_lookup_misses;
        std::printf("shaders_translated=%u shaders_cached=%u loop_shader_loads=%u cache_files=%u refused=%u "
                    "draws_refused=%u title_lookup_misses=%llu debug_errors=%u unknown_slots=%llu unknown_iids=%llu\n",
                    translated, cached, loop_shaders, files, recorded.refused, end.draws_refused, title_misses,
                    debug_errors,
                    static_cast<unsigned long long>(end.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls));
        good = good && loop.api_good && debug_errors == 0 && title_misses == 0 && recorded.refused == 0 && end.draws_refused == 0 &&
               end.unknown_slot_calls == 0 && end.unknown_iid_calls == 0 && files == 3 && loop_shaders == 0 &&
               states_ok && vertices_ok && handle_growth <= 16 && private_growth < 8 * 1024 * 1024 &&
               loop.frame_ms.size() == frames;
        if (cold) good = good && translated == 3 && cached == 0;
        if (warm || churn) good = good && translated == 0 && cached == 3;
        bool frames_ok = true;
        for (UINT s = 0; s < sample_count; ++s) {
            if (control)
                frames_ok = frames_ok && control_differs[s] > 0 && loop.sample_mismatches[s] == control_differs[s];
            else
                frames_ok = frames_ok && loop.sample_mismatches[s] == 0;
        }
        if (control) std::printf("control=%s\n", frames_ok ? "mismatch_detected" : "mismatch_missed");
        rc = good && frames_ok ? 0 : 1;
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
    ComPtr<ID3D12RootSignature> groot = graphics_root(gpu.device.Get()), croot = compute_root(gpu.device.Get());
    const auto refused = container(X2W_SHADER_STAGE_COMPUTE, r5_refused_cs, sizeof(r5_refused_cs), compute_bindings());
    const auto cs = container(X2W_SHADER_STAGE_COMPUTE, r5_cs, sizeof(r5_cs), compute_bindings());
    const auto vs = container(X2W_SHADER_STAGE_VERTEX, r3_vs, sizeof(r3_vs), vertex_bindings());
    const auto ps = container(X2W_SHADER_STAGE_PIXEL, r3_ps, sizeof(r3_ps), {{2, X2W_SHADER_BINDING_INTERP, 0, 0}});
    ComPtr<ID3D12PipelineState> a, b, c;
    const HRESULT hr = croot ? compute_pipeline(gpu.device.Get(), croot.Get(), refused, a) : E_FAIL;
    // Stage mismatches are refused before any translation.
    const HRESULT vs_in_cs = croot ? compute_pipeline(gpu.device.Get(), croot.Get(), vs, b) : E_FAIL;
    const HRESULT cs_in_vs = groot ? graphics_pipeline(gpu.device.Get(), groot.Get(), cs, ps, c) : E_FAIL;
    const auto end = counters();
    X2WGfxSetLogSink(nullptr, nullptr);
    std::printf("hr=0x%08lx vs_in_cs=0x%08lx cs_in_vs=0x%08lx refused_events=%u pipelines_refused=%u translated=%u\n",
                static_cast<unsigned long>(hr), static_cast<unsigned long>(vs_in_cs),
                static_cast<unsigned long>(cs_in_vs), recorded.refused, end.pipelines_refused - start.pipelines_refused,
                end.shaders_translated - start.shaders_translated);
    const bool named = recorded.details.find("a cross-lane permutation is refused") != std::string::npos;
    const bool good = hr == E_NOTIMPL && !a && vs_in_cs == E_NOTIMPL && !b && cs_in_vs == E_NOTIMPL && !c &&
                      recorded.refused == 3 && end.pipelines_refused - start.pipelines_refused == 3 && named &&
                      end.shaders_translated == start.shaders_translated && gpu.debug_errors() == 0;
    std::printf("refused=%s\n", good ? "pass" : "fail");
    return good ? 0 : 1;
}

}  // namespace

// A crash prints its code and the module-relative address (stdout is unbuffered, so the lines before it survive).
LONG WINAPI report_crash(EXCEPTION_POINTERS* info)
{
    HMODULE module = nullptr;
    const void* at = info->ExceptionRecord->ExceptionAddress;
    wchar_t name[MAX_PATH] = L"?";
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCWSTR>(at), &module))
        GetModuleFileNameW(module, name, MAX_PATH);
    std::fprintf(stderr, "r5: exception 0x%08lx at %ls+0x%llx\n",
                 static_cast<unsigned long>(info->ExceptionRecord->ExceptionCode), name,
                 static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(at) -
                                                 reinterpret_cast<std::uintptr_t>(module)));
    return EXCEPTION_EXECUTE_HANDLER;
}

int main(int argc, char** argv)
{
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    SetUnhandledExceptionFilter(report_crash);
    if (argc != 3) return 2;
    const std::string_view adapter = argv[1];
    const std::string_view mode = argv[2];
    if (adapter != "warp" && adapter != "hardware") return 2;
    const bool warp = adapter == "warp";
    if (mode == "cold" || mode == "warm" || mode == "wrong_reference" || mode == "view_churn")
        return frames_check(warp, mode);
    if (mode == "refused" && warp) return refused_check();
    return 2;
}
