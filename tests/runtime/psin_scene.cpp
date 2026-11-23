// Runtime pixel input layout (docs/design/runtime.md, "Pixel input layout"): a pixel program whose input VGPRs are
// not persp_center alone, translated by the graphics shim from a version 2 console container that carries its
// SPI_PS_INPUT_ENA/ADDR (X2WShaderPixelInfo, d3d12_xs_api.h).
//
// The vertex program is R3's (tests/runtime/r3_vs.s: positions from a vertex buffer in title memory). The pixel
// program (tests/runtime/psin_ps.s, psin_programs.h) has ENA = ADDR = persp_center | pos_x | pos_y | pos_z |
// front_face and exports (pos_x * pos_y, pos_y, pos_z, front_face) to an R32G32B32A32_FLOAT target. Two triangles
// are drawn without culling: a clockwise (front-facing) one at depth 0.25 and a counter-clockwise (back-facing) one at
// depth 0.75, both with w = 1. Every pixel is compared bit for bit with a CPU reference: a pixel centre strictly
// inside a triangle (exact integer edge functions; no centre lies on an edge) holds ((x + 0.5) * (y + 0.5), y + 0.5,
// z, +1.0 front or -1.0 back), every other pixel the clear value.
//
//   psin_scene warp|hardware cold             X2W_CACHE_DIR\psin_scene emptied first: both shaders translated
//   psin_scene warp|hardware wrong_reference  after cold: both shaders from the cache; the frame must equal the
//                                             reference, and each wrong reference must differ in every covered pixel:
//                                             the pixel corner for the centre (x, y without + 0.5), the face flipped,
//                                             z ignored (0, the offline harness's depth), w for z (1)
//   psin_scene warp refused                   controls: the same program in a version 1 container (no record, so the
//                                             default persp_center layout: v2 is unset) and in a version 2 container
//                                             whose ADDR also reserves pos_w (v5 is then pos_w, not loaded) are
//                                             refused by the translator with those reasons; a version 1 pixel
//                                             container with a stage_info_offset, and a record with bits above 15,
//                                             are malformed and refused before translation
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "psin_programs.h"
#include "r3_programs.h"
#include "xmem_title_api.h"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <string_view>
#include <vector>
#include "../test_guard.h"

using Microsoft::WRL::ComPtr;

namespace {

using namespace runtime_test;

constexpr ULONGLONG graphics_word = 0xa8004000;  // tests/xmem_shim_check.cpp
constexpr UINT width = 64;
constexpr UINT height = 64;
constexpr UINT texel = 16;
constexpr UINT row_pitch = width * texel;  // 1024: a multiple of D3D12_TEXTURE_DATA_PITCH_ALIGNMENT
constexpr float clear_value = -2.0f;
// SPI_PS_INPUT_ENA: persp_center (1), pos_x (8), pos_y (9), pos_z (10), front_face (12).
constexpr std::uint32_t psin_ena = 0x1702;
constexpr std::uint32_t pos_w_bit = 1u << 11;
// Vertices in pixels (y down), integer so exact under any subpixel snapping. Triangle 0 is clockwise on screen (front
// facing under FrontCounterClockwise = FALSE), triangle 1 counter-clockwise (back facing).
constexpr int vertices[2][3][2] = {{{3, 2}, {40, 7}, {6, 34}}, {{61, 28}, {30, 61}, {60, 60}}};
constexpr float depths[2] = {0.25f, 0.75f};
constexpr std::size_t constants_offset = 0;
constexpr std::size_t positions_offset = 256;
constexpr SIZE_T title_bytes = 64 * 1024;
constexpr UINT root_constants = 0;  // root CBV b0: the vertex program's colour (unused by the pixel program)
constexpr UINT root_positions = 1;  // root SRV t0: the vertex buffer

// Container (d3d12_xs_api.h) around one program, optionally with a pixel record at stage_info_offset.
std::vector<std::uint8_t> container(X2WShaderStage stage, const std::uint8_t* code, std::size_t bytes,
                                    const std::vector<X2WShaderBinding>& bindings, std::uint32_t version,
                                    const X2WShaderPixelInfo* pixel)
{
    X2WShaderContainer header{};
    header.magic = X2W_SHADER_CONTAINER_MAGIC;
    header.version = version;
    header.stage = stage;
    header.binding_count = static_cast<std::uint32_t>(bindings.size());
    header.binding_offset = sizeof(header);
    std::uint32_t at = static_cast<std::uint32_t>(sizeof(header) + bindings.size() * sizeof(X2WShaderBinding));
    if (pixel) {
        header.stage_info_offset = at;
        at += sizeof(X2WShaderPixelInfo);
    }
    header.code_offset = at;
    header.code_bytes = static_cast<std::uint32_t>(bytes);
    std::vector<std::uint8_t> out(header.code_offset + bytes);
    std::memcpy(out.data(), &header, sizeof(header));
    if (!bindings.empty()) std::memcpy(out.data() + sizeof(header), bindings.data(), bindings.size() * sizeof(bindings[0]));
    if (pixel) std::memcpy(out.data() + header.stage_info_offset, pixel, sizeof(*pixel));
    std::memcpy(out.data() + header.code_offset, code, bytes);
    return out;
}

std::vector<std::uint8_t> vertex_container()
{
    return container(X2W_SHADER_STAGE_VERTEX, r3_vs, sizeof(r3_vs),
                     {{2, X2W_SHADER_BINDING_ROOT_WORD, root_positions, 0},
                      {3, X2W_SHADER_BINDING_ROOT_WORD, root_positions, 1},
                      {4, X2W_SHADER_BINDING_ROOT_WORD, root_constants, 0},
                      {5, X2W_SHADER_BINDING_ROOT_WORD, root_constants, 1}},
                     X2W_SHADER_CONTAINER_VERSION, nullptr);
}

long long edge(const int a[2], const int b[2], int x, int y)
{
    const long long px = 2 * x + 1, py = 2 * y + 1;
    return (2LL * b[0] - 2 * a[0]) * (py - 2LL * a[1]) - (2LL * b[1] - 2 * a[1]) * (px - 2LL * a[0]);
}

// How a reference differs from the console's inputs (the wrong references).
enum class Wrong { none, corner, face_flipped, z_ignored, w_for_z };

// The reference frame (four binary32 per pixel); false if a pixel centre lies on an edge or the triangles overlap.
bool reference(Wrong wrong, std::vector<float>& out, unsigned& covered)
{
    out.assign(static_cast<std::size_t>(width) * height * 4, clear_value);
    covered = 0;
    for (UINT y = 0; y < height; ++y) {
        for (UINT x = 0; x < width; ++x) {
            int inside_of = -1;
            for (int t = 0; t < 2; ++t) {
                const auto& v = vertices[t];
                const long long e0 = edge(v[0], v[1], x, y), e1 = edge(v[1], v[2], x, y), e2 = edge(v[2], v[0], x, y);
                if (!e0 || !e1 || !e2) return false;
                if ((e0 > 0 && e1 > 0 && e2 > 0) || (e0 < 0 && e1 < 0 && e2 < 0)) {
                    if (inside_of >= 0) return false;
                    inside_of = t;
                }
            }
            if (inside_of < 0) continue;
            ++covered;
            float* p = &out[(static_cast<std::size_t>(y) * width + x) * 4];
            const float offset = wrong == Wrong::corner ? 0.0f : 0.5f;
            const float fx = float(x) + offset, fy = float(y) + offset;
            p[0] = fx * fy;
            p[1] = fy;
            p[2] = wrong == Wrong::z_ignored ? 0.0f : wrong == Wrong::w_for_z ? 1.0f : depths[inside_of];
            const bool front = inside_of == 0;
            p[3] = (front != (wrong == Wrong::face_flipped)) ? 1.0f : -1.0f;
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
    ComPtr<ID3DBlob> blob, errors;
    if (!ok(D3D12SerializeVersionedRootSignature(&desc, &blob, &errors), "D3D12SerializeVersionedRootSignature"))
        return {};
    ComPtr<ID3D12RootSignature> root;
    if (!ok(device->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(), IID_PPV_ARGS(&root)),
            "CreateRootSignature"))
        return {};
    return root;
}

HRESULT create_pipeline(ID3D12Device* device, ID3D12RootSignature* root, const std::vector<std::uint8_t>& vs,
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
    desc.RasterizerState.FrontCounterClockwise = FALSE;
    desc.RasterizerState.DepthClipEnable = TRUE;
    desc.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    desc.NumRenderTargets = 1;
    desc.RTVFormats[0] = DXGI_FORMAT_R32G32B32A32_FLOAT;
    desc.SampleDesc.Count = 1;
    return device->CreateGraphicsPipelineState(&desc, IID_PPV_ARGS(&pso));
}

std::wstring cache_directory()
{
    wchar_t root[1024];
    const DWORD n = GetEnvironmentVariableW(L"X2W_CACHE_DIR", root, 1024);
    if (!n || n >= 1024) return {};
    return std::wstring(root) + L"\\psin_scene";
}

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

// Draws both triangles into an R32G32B32A32_FLOAT target and reads it back into `frame`.
bool draw(Gpu& gpu, ID3D12RootSignature* root, ID3D12PipelineState* pso, std::uintptr_t title,
          std::vector<float>& frame)
{
    D3D12_HEAP_PROPERTIES default_heap{};
    default_heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC target_desc{};
    target_desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    target_desc.Width = width;
    target_desc.Height = height;
    target_desc.DepthOrArraySize = 1;
    target_desc.MipLevels = 1;
    target_desc.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
    target_desc.SampleDesc.Count = 1;
    target_desc.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    D3D12_CLEAR_VALUE clear{};
    clear.Format = DXGI_FORMAT_R32G32B32A32_FLOAT;
    for (float& c : clear.Color) c = clear_value;
    ComPtr<ID3D12Resource> target;
    if (!ok(gpu.device->CreateCommittedResource(&default_heap, D3D12_HEAP_FLAG_NONE, &target_desc,
                                                D3D12_RESOURCE_STATE_RENDER_TARGET, &clear, IID_PPV_ARGS(&target)),
            "CreateCommittedResource(target)"))
        return false;
    D3D12_DESCRIPTOR_HEAP_DESC heap_desc{};
    heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    heap_desc.NumDescriptors = 1;
    ComPtr<ID3D12DescriptorHeap> rtv_heap;
    if (!ok(gpu.device->CreateDescriptorHeap(&heap_desc, IID_PPV_ARGS(&rtv_heap)), "CreateDescriptorHeap")) return false;
    const D3D12_CPU_DESCRIPTOR_HANDLE rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
    gpu.device->CreateRenderTargetView(target.Get(), nullptr, rtv);
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
    gpu.list->ClearRenderTargetView(rtv, clear.Color, 0, nullptr);
    gpu.list->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
    const D3D12_VIEWPORT viewport{0, 0, float(width), float(height), 0, 1};
    const D3D12_RECT scissor{0, 0, LONG(width), LONG(height)};
    gpu.list->RSSetViewports(1, &viewport);
    gpu.list->RSSetScissorRects(1, &scissor);
    gpu.list->SetGraphicsRootSignature(root);
    gpu.list->SetGraphicsRootConstantBufferView(root_constants, title + constants_offset);
    gpu.list->SetGraphicsRootShaderResourceView(root_positions, title + positions_offset);
    gpu.list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    gpu.list->DrawInstanced(6, 1, 0, 0);
    auto barrier = transition(target.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
    gpu.list->ResourceBarrier(1, &barrier);
    D3D12_TEXTURE_COPY_LOCATION dst{};
    dst.pResource = readback.Get();
    dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dst.PlacedFootprint.Footprint = {DXGI_FORMAT_R32G32B32A32_FLOAT, width, height, 1, row_pitch};
    D3D12_TEXTURE_COPY_LOCATION src{};
    src.pResource = target.Get();
    src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    if (!ok(gpu.list->Close(), "Close") || !gpu.submit_and_wait()) return false;
    void* mapped = nullptr;
    const D3D12_RANGE read{0, static_cast<SIZE_T>(readback_desc.Width)};
    if (!ok(readback->Map(0, &read, &mapped), "Map")) return false;
    frame.resize(static_cast<std::size_t>(width) * height * 4);
    for (UINT y = 0; y < height; ++y)
        std::memcpy(&frame[static_cast<std::size_t>(y) * width * 4],
                    static_cast<const std::uint8_t*>(mapped) + static_cast<SIZE_T>(y) * row_pitch, width * texel);
    const D3D12_RANGE none{0, 0};
    readback->Unmap(0, &none);
    return true;
}

// Pixels whose four words differ from the reference (bit for bit).
unsigned mismatches(const std::vector<float>& frame, const std::vector<float>& expected, const char* name)
{
    unsigned count = 0;
    for (std::size_t i = 0; i < static_cast<std::size_t>(width) * height; ++i) {
        if (std::memcmp(&frame[i * 4], &expected[i * 4], texel) == 0) continue;
        if (!count) {
            std::uint32_t got[4], want[4];
            std::memcpy(got, &frame[i * 4], texel);
            std::memcpy(want, &expected[i * 4], texel);
            std::printf("%s first_pixel=%zu got=%08x,%08x,%08x,%08x want=%08x,%08x,%08x,%08x\n", name, i, got[0],
                        got[1], got[2], got[3], want[0], want[1], want[2], want[3]);
        }
        ++count;
    }
    return count;
}

std::uint8_t* make_title()
{
    auto* title = static_cast<std::uint8_t*>(XMemAlloc(title_bytes, graphics_word));
    if (!title) return nullptr;
    const float color[4] = {1.0f, 0.5f, 0.25f, 1.0f};
    float positions[6][4];
    for (int t = 0; t < 2; ++t) {
        for (int v = 0; v < 3; ++v) {
            float* p = positions[t * 3 + v];
            p[0] = vertices[t][v][0] / 32.0f - 1.0f;  // exact in binary32
            p[1] = 1.0f - vertices[t][v][1] / 32.0f;
            p[2] = depths[t];
            p[3] = 1.0f;
        }
    }
    std::memcpy(title + constants_offset, color, sizeof(color));
    std::memcpy(title + positions_offset, positions, sizeof(positions));
    return title;
}

int scene_check(bool warp, bool cold)
{
    const std::wstring cache = cache_directory();
    if (cache.empty()) {
        std::fputs("psin: X2W_CACHE_DIR must name the test's cache root\n", stderr);
        return 1;
    }
    if (cold && !empty_cache(cache)) {
        std::fputs("psin: cannot empty the cache directory\n", stderr);
        return 1;
    }
    std::vector<float> expected;
    unsigned covered = 0;
    if (!reference(Wrong::none, expected, covered)) {
        std::fputs("psin: a pixel centre lies on an edge or the triangles overlap; choose other vertices\n", stderr);
        return 1;
    }
    std::printf("covered_pixels=%u\n", covered);
    std::uint8_t* title = make_title();
    if (!title) {
        std::fputs("psin: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    Recorded recorded;
    int rc = 1;
    {
        Gpu gpu;
        if (const int created = gpu.create(warp)) {
            XMemFree(title, graphics_word);
            return created;
        }
        X2WGfxSetLogSink(record, &recorded);
        const auto start = counters();
        ComPtr<ID3D12RootSignature> root = title_root_signature(gpu.device.Get());
        const X2WShaderPixelInfo layout{psin_ena, 0};
        const auto vs = vertex_container();
        const auto ps = container(X2W_SHADER_STAGE_PIXEL, psin_ps, sizeof(psin_ps), {}, X2W_SHADER_CONTAINER_VERSION,
                                  &layout);
        ComPtr<ID3D12PipelineState> pso;
        const HRESULT hr = root ? create_pipeline(gpu.device.Get(), root.Get(), vs, ps, pso) : E_FAIL;
        std::printf("pso_hr=0x%08lx\n", static_cast<unsigned long>(hr));
        std::vector<float> frame;
        bool good = SUCCEEDED(hr) && draw(gpu, root.Get(), pso.Get(), reinterpret_cast<std::uintptr_t>(title), frame);
        if (good) {
            const unsigned bad = mismatches(frame, expected, "reference");
            std::printf("mismatches=%u\n", bad);
            good = bad == 0;
            if (!cold) {
                const struct { Wrong wrong; const char* name; } wrongs[] = {
                    {Wrong::corner, "corner"}, {Wrong::face_flipped, "face_flipped"},
                    {Wrong::z_ignored, "z_ignored"}, {Wrong::w_for_z, "w_for_z"}};
                for (const auto& w : wrongs) {
                    std::vector<float> wrong;
                    unsigned n = 0;
                    reference(w.wrong, wrong, n);
                    const unsigned differ = mismatches(frame, wrong, w.name);
                    std::printf("control=%s %s differ=%u\n", w.name, differ == covered ? "mismatch_detected"
                                                                                       : "mismatch_missed", differ);
                    good = good && differ == covered;
                }
            }
        }
        pso.Reset();
        root.Reset();
        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        const unsigned translated = end.shaders_translated - start.shaders_translated;
        const unsigned cached = end.shaders_cached - start.shaders_cached;
        std::printf("shaders_translated=%u shaders_cached=%u refused=%u draws_refused=%u debug_errors=%u "
                    "title_lookup_misses=%llu\n",
                    translated, cached, recorded.refused, end.draws_refused - start.draws_refused, debug_errors,
                    static_cast<unsigned long long>(end.title_lookup_misses - start.title_lookup_misses));
        good = good && debug_errors == 0 && recorded.refused == 0 && end.draws_refused == start.draws_refused &&
               (cold ? translated == 2 && cached == 0 : translated == 0 && cached == 2);
        rc = good ? 0 : 1;
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
    ComPtr<ID3D12RootSignature> root = title_root_signature(gpu.device.Get());
    const auto vs = vertex_container();
    struct Case {
        const char* name;
        std::vector<std::uint8_t> ps;
        const char* reason;
    };
    const X2WShaderPixelInfo wide{psin_ena, psin_ena | pos_w_bit}, high{psin_ena | 0x10000u, 0},
        good_layout{psin_ena, 0};
    std::vector<Case> cases;
    cases.push_back({"version1", container(X2W_SHADER_STAGE_PIXEL, psin_ps, sizeof(psin_ps), {}, 1, nullptr),
                     "Read of unset vector register v2"});
    cases.push_back({"addr_pos_w", container(X2W_SHADER_STAGE_PIXEL, psin_ps, sizeof(psin_ps), {},
                                             X2W_SHADER_CONTAINER_VERSION, &wide),
                     "Read of input VGPR v5 (pos_w)"});
    cases.push_back({"version1_record", container(X2W_SHADER_STAGE_PIXEL, psin_ps, sizeof(psin_ps), {}, 1,
                                                  &good_layout),
                     "malformed container header"});
    cases.push_back({"high_bits", container(X2W_SHADER_STAGE_PIXEL, psin_ps, sizeof(psin_ps), {},
                                            X2W_SHADER_CONTAINER_VERSION, &high),
                     "malformed pixel input layout"});
    bool good = root.Get() != nullptr;
    for (const Case& c : cases) {
        const unsigned before = recorded.refused;
        const std::size_t text = recorded.details.size();
        ComPtr<ID3D12PipelineState> pso;
        const HRESULT hr = root ? create_pipeline(gpu.device.Get(), root.Get(), vs, c.ps, pso) : E_FAIL;
        const bool named = recorded.details.find(c.reason, text) != std::string::npos;
        const bool pass = hr == E_NOTIMPL && !pso && recorded.refused == before + 1 && named;
        std::printf("case=%s hr=0x%08lx refused=%s\n", c.name, static_cast<unsigned long>(hr), pass ? "pass" : "fail");
        good = good && pass;
    }
    X2WGfxSetLogSink(nullptr, nullptr);
    const unsigned debug_errors = gpu.debug_errors();
    good = good && debug_errors == 0;
    std::printf("debug_errors=%u refused=%s\n", debug_errors, good ? "pass" : "fail");
    return good ? 0 : 1;
}

}  // namespace

int main(int argc, char** argv)
{
    test_guard::install("psin_scene", 110);  // below the ctest TIMEOUT (CMakeLists.txt)
    if (argc != 3) return 2;
    const std::string_view adapter = argv[1];
    const std::string_view mode = argv[2];
    if (adapter != "warp" && adapter != "hardware") return 2;
    const bool warp = adapter == "warp";
    if (mode == "cold" || mode == "wrong_reference") return scene_check(warp, mode == "cold");
    if (mode == "refused" && warp) return refused_check();
    return 2;
}
