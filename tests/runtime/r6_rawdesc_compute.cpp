// R6 descriptors: a compute dispatch whose descriptor tables are in title heaps and hold hardware words the title
// wrote itself (docs/design/runtime.md, "Descriptors written as hardware words").
//
// tests/runtime/r6_cs.s, one lane per texel of an 8x8 texture, reads from its CBV/SRV/UAV table a T# (at 0x00) and
// the output's V# (at 0x20), and from its sampler table an S#. Each lane writes 32 bytes at 32 * (8 y + x): its
// texel by image_load, and image_sample_lz at the texel's centre with u moved by the root constant (1.0). The title
// writes the words through the heaps' CPU handles (tests/runtime/r6_words.h):
//   T#  8x8 32_32_32_32_FLOAT in SW_4KB_S_X (pipe/bank XOR 0x5) in title texture memory, DST_SEL (Y, X, Z, 1)
//   S#  point, u WRAP (so u + 1 samples the same texel)
//   V#  the output buffer in title memory, num_records 2016: the last lane's two stores (bytes 2016..2047) are out
//       of range and must leave the buffer's sentinel words
// Texel (x, y) is (x + 8 y + 0.25, -(x + 1), y / 2, 1000 + x y), exact in binary32, so the output is compared word for
// word with the CPU reference (through the title pointer, after the fence).
//
//   r6_rawdesc_compute warp|hardware compute         the output equals the reference, the guard words their sentinel
//   r6_rawdesc_compute warp|hardware wrong_dst_sel   control: compared with the reference that ignores DST_SEL:
//                                                    exactly the words where the two references differ mismatch
//   r6_rawdesc_compute warp|hardware rewrite         after the first dispatch completes the title rewrites the V# (a
//                                                    second output, num_records 2048), the T#'s DST_SEL (identity)
//                                                    and the S#'s u mode (CLAMP: u + 1 samples column 7). The second
//                                                    output must equal the new reference (the last lane written), the
//                                                    first keep the first dispatch's words, and the second output must
//                                                    differ from the old reference (a stale cache)
//
// Also required: no refusal, no TextureLookup or TitleLookup miss, no debug-layer error, 3 raw descriptor reads per
// dispatch, 1 desktop texture (2 in rewrite), 1 sampler (2 in rewrite), every wrapper released.
//
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "era_title_gpu_api.h"
#include "gfx10_detile.h"
#include "r6_programs.h"
#include "r6_words.h"

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

constexpr ULONGLONG graphics_word = 0xa8004000;
constexpr UINT side = 8;
constexpr UINT lanes = side * side;
constexpr UINT lane_bytes = 32;
constexpr UINT output_bytes = lanes * lane_bytes;  // 2048
constexpr UINT short_records = output_bytes - lane_bytes;
constexpr SIZE_T memory_bytes = 64 * 1024;
constexpr std::size_t output_offsets[2] = {0x0000, 0x8000};  // in the output allocation
constexpr std::uint32_t sentinel = 0xdeadbeefu;
constexpr UINT root_views = 0, root_samplers = 1, root_offset = 2;

const x2w::gfx10::Config addr_config{x2w::gfx10::MakeGbAddrConfig(4, 4), true, true};

float texel(UINT x, UINT y, int c)
{
    switch (c) {
    case 0: return float(x + 8 * y) + 0.25f;
    case 1: return -float(x + 1);
    case 2: return float(y) * 0.5f;
    default: return 1000.0f + float(x * y);
    }
}

x2w::gfx10::Surface surface()
{
    x2w::gfx10::Surface s;
    s.mode = x2w::gfx10::SwizzleMode::S_4KB_X;
    s.element_bytes = 16;
    s.width = s.height = side;
    s.pipe_bank_xor = 0x5;
    return s;
}

bool write_texture(std::uint8_t* memory)
{
    std::vector<float> linear;
    for (UINT y = 0; y < side; ++y)
        for (UINT x = 0; x < side; ++x)
            for (int c = 0; c < 4; ++c) linear.push_back(texel(x, y, c));
    const x2w::gfx10::Footprint fp{0, side, side, 1, side * 16};
    std::string error;
    if (!x2w::gfx10::TileFromFootprints(addr_config, surface(), memory, memory_bytes, linear.data(),
                                        linear.size() * 4, &fp, 1, &error)) {
        std::fprintf(stderr, "r6: TileFromFootprints: %s\n", error.c_str());
        return false;
    }
    return true;
}

constexpr std::uint32_t swapped_sel[4] = {r6::sel_y, r6::sel_x, r6::sel_z, r6::sel_1};
constexpr std::uint32_t identity_sel[4] = {r6::sel_x, r6::sel_y, r6::sel_z, r6::sel_w};

// The expected words of an output: lane (x, y) at 8 words per lane; lanes at or past `records` bytes keep the
// sentinel. `clamp_u` samples column 7 (the S#'s u CLAMP with u + 1).
std::vector<std::uint32_t> reference(const std::uint32_t (&sel)[4], bool clamp_u, UINT records)
{
    std::vector<std::uint32_t> out(output_bytes / 4, sentinel);
    for (UINT y = 0; y < side; ++y) {
        for (UINT x = 0; x < side; ++x) {
            const UINT lane = 8 * y + x;
            for (int half = 0; half < 2; ++half) {
                const UINT at = lane * lane_bytes + 16 * half;
                if (at >= records) continue;
                const UINT sx = half && clamp_u ? side - 1 : x;
                for (int c = 0; c < 4; ++c) {
                    const std::uint32_t s = sel[c];
                    const float v = s == r6::sel_0 ? 0.0f : s == r6::sel_1 ? 1.0f : texel(sx, y, static_cast<int>(s - r6::sel_x));
                    std::memcpy(&out[at / 4 + c], &v, 4);
                }
            }
        }
    }
    return out;
}

unsigned compare(const std::uint32_t* got, const std::vector<std::uint32_t>& want, const char* name)
{
    unsigned n = 0;
    for (std::size_t i = 0; i < want.size(); ++i) {
        if (got[i] == want[i]) continue;
        if (!n)
            std::printf("%s first_word=%zu got=%08x want=%08x\n", name, i, static_cast<unsigned>(got[i]),
                        static_cast<unsigned>(want[i]));
        ++n;
    }
    std::printf("%s mismatches=%u\n", name, n);
    return n;
}

unsigned differences(const std::vector<std::uint32_t>& a, const std::vector<std::uint32_t>& b)
{
    unsigned n = 0;
    for (std::size_t i = 0; i < a.size(); ++i) n += a[i] != b[i];
    return n;
}

ComPtr<ID3D12RootSignature> title_root_signature(ID3D12Device* device)
{
    D3D12_DESCRIPTOR_RANGE1 views[2]{};
    views[0] = {D3D12_DESCRIPTOR_RANGE_TYPE_SRV, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 0};
    views[1] = {D3D12_DESCRIPTOR_RANGE_TYPE_UAV, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_DATA_VOLATILE, 1};
    D3D12_DESCRIPTOR_RANGE1 sampler{D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER, 1, 0, 0, D3D12_DESCRIPTOR_RANGE_FLAG_NONE, 0};
    D3D12_ROOT_PARAMETER1 params[3]{};
    params[root_views].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[root_views].DescriptorTable = {2, views};
    params[root_samplers].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[root_samplers].DescriptorTable = {1, &sampler};
    params[root_offset].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[root_offset].Constants = {0, 0, 1};
    D3D12_VERSIONED_ROOT_SIGNATURE_DESC desc{};
    desc.Version = D3D_ROOT_SIGNATURE_VERSION_1_1;
    desc.Desc_1_1.NumParameters = 3;
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

struct Recorded {
    unsigned refused = 0;
};

void WINAPI record(const X2WGfxEvent* event, void* context)
{
    if (event->kind == X2W_GFX_EVENT_FIRST_USE) return;
    std::fprintf(stderr, "[sink] %s %s\n", event->symbol, event->detail);
    if (event->kind == X2W_GFX_EVENT_REFUSED) ++static_cast<Recorded*>(context)->refused;
}

bool dispatch(Gpu& gpu, ID3D12RootSignature* root, ID3D12PipelineState* pso, ID3D12DescriptorHeap* views,
              ID3D12DescriptorHeap* samplers)
{
    if (!ok(gpu.allocator->Reset(), "allocator Reset") || !ok(gpu.list->Reset(gpu.allocator.Get(), pso), "list Reset"))
        return false;
    ID3D12GraphicsCommandList* list = gpu.list.Get();
    ID3D12DescriptorHeap* heaps[2] = {views, samplers};
    list->SetDescriptorHeaps(2, heaps);
    list->SetComputeRootSignature(root);
    list->SetComputeRootDescriptorTable(root_views, views->GetGPUDescriptorHandleForHeapStart());
    list->SetComputeRootDescriptorTable(root_samplers, samplers->GetGPUDescriptorHandleForHeapStart());
    const float offset = 1.0f;
    UINT word;
    std::memcpy(&word, &offset, 4);
    list->SetComputeRoot32BitConstant(root_offset, word, 0);
    list->Dispatch(1, 1, 1);
    return ok(list->Close(), "Close") && gpu.submit_and_wait();
}

int compute_check(bool warp, std::string_view mode)
{
    const bool wrong_dst_sel = mode == "wrong_dst_sel", rewrite = mode == "rewrite";
    auto* textures = static_cast<std::uint8_t*>(XMemAlloc(memory_bytes, graphics_word));
    auto* output = static_cast<std::uint8_t*>(XMemAlloc(memory_bytes, graphics_word));
    if (!textures || !output) {
        std::fputs("r6: XMemAlloc(graphics) failed\n", stderr);
        return 1;
    }
    std::memset(textures, 0, memory_bytes);
    for (SIZE_T i = 0; i < memory_bytes; i += 4) std::memcpy(output + i, &sentinel, 4);
    if (!write_texture(textures)) return 1;
    const auto expected = reference(swapped_sel, false, short_records);
    const auto ignoring_sel = reference(identity_sel, false, short_records);
    const auto expected2 = reference(identity_sel, true, output_bytes);
    std::printf("dst_sel_words=%u rewritten_words=%u\n", differences(expected, ignoring_sel),
                differences(expected, expected2));

    Recorded recorded;
    int rc = 1;
    {
        Gpu gpu;
        const int created = gpu.create(warp);
        if (created) {
            XMemFree(textures, graphics_word);
            XMemFree(output, graphics_word);
            return created;
        }
        X2WGfxSetLogSink(record, &recorded);
        const auto start = counters();
        bool good = start.title_gpu_state == X2W_GFX_TITLE_GPU_ATTACHED;
        {
            ComPtr<ID3D12RootSignature> root = title_root_signature(gpu.device.Get());
            const std::vector<X2WShaderBinding> bindings = {{2, X2W_SHADER_BINDING_TABLE, root_views, 0},
                                                            {3, X2W_SHADER_BINDING_TABLE, root_samplers, 0},
                                                            {4, X2W_SHADER_BINDING_ROOT_WORD, root_offset, 0}};
            const X2WShaderComputeInfo info{{side, side, 1}, 32, 2};
            const auto cs = r6::container(X2W_SHADER_STAGE_COMPUTE, r6_cs, sizeof(r6_cs), bindings, &info);
            D3D12_COMPUTE_PIPELINE_STATE_DESC desc{};
            desc.pRootSignature = root.Get();
            desc.CS = {cs.data(), cs.size()};
            ComPtr<ID3D12PipelineState> pso;
            const HRESULT hr = root ? gpu.device->CreateComputePipelineState(&desc, IID_PPV_ARGS(&pso)) : E_FAIL;
            std::printf("pso=0x%08lx mode=%s\n", static_cast<unsigned long>(hr), std::string(mode).c_str());
            good = good && SUCCEEDED(hr);
            ComPtr<ID3D12DescriptorHeap> views, samplers;
            D3D12_DESCRIPTOR_HEAP_DESC hd{D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV, 2, D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
            good = good && ok(gpu.device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&views)), "CreateDescriptorHeap(views)");
            hd = {D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER, 1, D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE, 0};
            good = good && ok(gpu.device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&samplers)), "CreateDescriptorHeap(samplers)");
            if (good) {
                auto* table = reinterpret_cast<std::uint8_t*>(views->GetCPUDescriptorHandleForHeapStart().ptr);
                auto* sampler = reinterpret_cast<std::uint8_t*>(samplers->GetCPUDescriptorHandleForHeapStart().ptr);
                r6::Image t;
                t.va = reinterpret_cast<std::uintptr_t>(textures);
                t.pipe_bank_xor = surface().pipe_bank_xor;
                t.format = 77;  // GFX10_FORMAT_32_32_32_32_FLOAT
                t.width = t.height = side;
                std::memcpy(t.sel, swapped_sel, sizeof(swapped_sel));
                t.sw_mode = static_cast<std::uint32_t>(surface().mode);
                t.write(table);
                r6::write_buffer(table + 0x20, reinterpret_cast<std::uintptr_t>(output + output_offsets[0]), short_records);
                r6::write_sampler(sampler, r6::wrap, r6::clamp_last_texel);
                good = dispatch(gpu, root.Get(), pso.Get(), views.Get(), samplers.Get());
                const auto* first = reinterpret_cast<const std::uint32_t*>(output + output_offsets[0]);
                if (good) {
                    const unsigned m = compare(first, wrong_dst_sel ? ignoring_sel : expected, "dispatch0");
                    good = wrong_dst_sel ? m == differences(expected, ignoring_sel) && m > 0 : m == 0;
                    // Past the output: untouched.
                    const auto* after = reinterpret_cast<const std::uint32_t*>(output + output_offsets[0] + output_bytes);
                    for (UINT i = 0; i < 64; ++i) good = good && after[i] == sentinel;
                }
                if (good && rewrite) {
                    // The GPU is done with dispatch 0: the title rewrites the V#, the T#'s DST_SEL and the S#.
                    r6::write_buffer(table + 0x20, reinterpret_cast<std::uintptr_t>(output + output_offsets[1]), output_bytes);
                    std::memcpy(t.sel, identity_sel, sizeof(identity_sel));
                    t.write(table);
                    r6::write_sampler(sampler, r6::clamp_last_texel, r6::clamp_last_texel);
                    good = dispatch(gpu, root.Get(), pso.Get(), views.Get(), samplers.Get());
                    const auto* second = reinterpret_cast<const std::uint32_t*>(output + output_offsets[1]);
                    good = good && compare(second, expected2, "dispatch1") == 0 &&
                           compare(first, expected, "dispatch0_after_rewrite") == 0;
                    const unsigned stale = compare(second, expected, "dispatch1_vs_old_reference");
                    good = good && stale == differences(expected, expected2) && stale > 0;
                }
                if (wrong_dst_sel || rewrite) std::printf("control=%s\n", good ? "mismatch_detected" : "mismatch_missed");
            }
        }
        const unsigned debug_errors = gpu.debug_errors();
        const auto end = counters();
        const unsigned long long title_misses = end.title_lookup_misses - start.title_lookup_misses;
        const unsigned long long texture_misses = end.texture_lookup_misses - start.texture_lookup_misses;
        const unsigned long long raw_reads = end.raw_descriptor_reads - start.raw_descriptor_reads;
        const unsigned uploads = end.raw_texture_uploads - start.raw_texture_uploads;
        const unsigned samplers_created = end.raw_samplers_created - start.raw_samplers_created;
        std::printf("refused=%u title_lookup_misses=%llu texture_lookup_misses=%llu raw_reads=%llu raw_texture_uploads=%u "
                    "raw_samplers=%u debug_errors=%u unknown_slots=%llu unknown_iids=%llu\n",
                    recorded.refused, title_misses, texture_misses, raw_reads, uploads, samplers_created, debug_errors,
                    static_cast<unsigned long long>(end.unknown_slot_calls),
                    static_cast<unsigned long long>(end.unknown_iid_calls));
        const unsigned dispatches = rewrite ? 2 : 1;
        good = good && debug_errors == 0 && recorded.refused == 0 && end.unknown_slot_calls == 0 &&
               end.unknown_iid_calls == 0 && title_misses == 0 && texture_misses == 0 && raw_reads == 3ull * dispatches &&
               uploads == dispatches && samplers_created == dispatches;
        rc = good ? 0 : 1;
        X2WGfxSetLogSink(nullptr, nullptr);
    }
    XMemFree(textures, graphics_word);
    XMemFree(output, graphics_word);
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
    if (mode == "compute" || mode == "wrong_dst_sel" || mode == "rewrite") return compute_check(adapter == "warp", mode);
    return 2;
}
