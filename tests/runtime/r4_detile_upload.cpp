// Detiled texture upload through the graphics shim (docs/design/runtime.md, "Textures: detiling").
//
// For a set of synthetic GFX10.3 tiled surfaces (2D, 2D arrays and 3D; uncompressed 1-16 byte and BC1/BC4/BC7
// elements; linear, 256 B, 4 KiB, 64 KiB thin and thick modes with pipe/bank XOR; full and partial mip chains, so
// mip tails are included), the title's bytes are written into title memory (XMemAlloc, graphics) by
// x2w::gfx10::TileFromFootprints from random data. The upload then does what the shim will do for a title texture:
// GetCopyableFootprints of the desktop texture, DetileToFootprints from title memory into the upload buffer,
// CopyTextureRegion of every subresource. Every subresource is copied back to a readback buffer and every element is
// compared with the random data. The device, resources and command lists come from d3d12_xs.dll, as in R4.
//
//   r4_detile_upload warp|hardware
//
// Control: one more surface is detiled with a wrong pipe/bank XOR; its readback must differ.
// Exit codes: 0 pass, 1 fail, 2 usage, 77 no hardware adapter.
#include "runtime_common.h"
#include "gfx10_detile.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <string>
#include <string_view>
#include <vector>

using Microsoft::WRL::ComPtr;

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void XMemFree(void* allocation, ULONGLONG attributes);

namespace {

using namespace runtime_test;
namespace g = x2w::gfx10;

constexpr ULONGLONG graphics_word = 0xa8004000;  // tests/xmem_shim_check.cpp
const g::Config config{g::MakeGbAddrConfig(4, 4), true, true};  // GFX10.3, 16 pipes, 16 packers

struct Case {
    const char* name;
    DXGI_FORMAT format;
    std::uint32_t bpe, block;
    g::Dimension dimension;
    g::SwizzleMode mode;
    std::uint32_t width, height, depth_or_array, mips;  // mips 0: full chain
    std::uint32_t pipe_bank_xor;
};

const Case cases[] = {
    {"rgba8_2d_64kb_r_x", DXGI_FORMAT_R8G8B8A8_UNORM, 4, 1, g::Dimension::Tex2D, g::SwizzleMode::R_64KB_X, 300, 200,
     1, 0, 0x8b},
    {"bc1_array3_4kb_s_x", DXGI_FORMAT_BC1_UNORM, 8, 4, g::Dimension::Tex2D, g::SwizzleMode::S_4KB_X, 256, 128, 3, 0,
     0x6},
    {"bc7_2d_64kb_s_x", DXGI_FORMAT_BC7_UNORM, 16, 4, g::Dimension::Tex2D, g::SwizzleMode::S_64KB_X, 132, 68, 1, 0,
     0xcd},
    {"r8_2d_64kb_d_x", DXGI_FORMAT_R8_UNORM, 1, 1, g::Dimension::Tex2D, g::SwizzleMode::D_64KB_X, 1000, 7, 1, 4,
     0x3f},
    {"rgba16_array6_64kb_z_x", DXGI_FORMAT_R16G16B16A16_UINT, 8, 1, g::Dimension::Tex2D, g::SwizzleMode::Z_64KB_X,
     64, 64, 6, 7, 0x41},
    {"rgba32_2d_256b_s", DXGI_FORMAT_R32G32B32A32_UINT, 16, 1, g::Dimension::Tex2D, g::SwizzleMode::S_256B, 50, 50, 1,
     3, 0},
    {"rg16_2d_linear", DXGI_FORMAT_R16G16_UINT, 4, 1, g::Dimension::Tex2D, g::SwizzleMode::Linear, 77, 33, 1, 3, 0},
    {"rgba8_3d_64kb_s", DXGI_FORMAT_R8G8B8A8_UNORM, 4, 1, g::Dimension::Tex3D, g::SwizzleMode::S_64KB, 37, 19, 23, 0,
     0},
    {"r16_3d_64kb_d_x", DXGI_FORMAT_R16_UINT, 2, 1, g::Dimension::Tex3D, g::SwizzleMode::D_64KB_X, 64, 32, 16, 4,
     0x9a},
    {"bc4_3d_4kb_s_x", DXGI_FORMAT_BC4_UNORM, 8, 4, g::Dimension::Tex3D, g::SwizzleMode::S_4KB_X, 64, 64, 8, 0, 0x5},
    {"rgba8_3d_64kb_r_x", DXGI_FORMAT_R8G8B8A8_UNORM, 4, 1, g::Dimension::Tex3D, g::SwizzleMode::R_64KB_X, 70, 40, 9,
     0, 0x77},
};

g::Surface surface_of(const Case& c)
{
    g::Surface s;
    s.dimension = c.dimension;
    s.mode = c.mode;
    s.element_bytes = c.bpe;
    s.element_width = s.element_height = c.block;
    s.width = c.width;
    s.height = c.height;
    s.depth_or_array = c.depth_or_array;
    std::uint32_t full = 1;
    for (std::uint32_t v = std::max({c.width, c.height, c.dimension == g::Dimension::Tex3D ? c.depth_or_array : 1u});
         v > 1; v >>= 1)
        ++full;
    s.mip_levels = c.mips ? c.mips : full;
    s.pipe_bank_xor = c.pipe_bank_xor;
    return s;
}

// Uploads one case and returns the number of elements whose readback differs, or -1 on an API failure.
long long run_case(Gpu& gpu, const Case& c, std::mt19937& rng, std::uint32_t detile_xor_flip)
{
    ID3D12Device* device = gpu.device.Get();
    const g::Surface s = surface_of(c);
    g::Layout layout;
    std::string error;
    if (!g::ComputeLayout(config, s, &layout, &error)) {
        std::fprintf(stderr, "%s: ComputeLayout: %s\n", c.name, error.c_str());
        return -1;
    }
    const std::uint32_t count = g::SubresourceCount(s);

    // The source data: random elements, tight rows, per subresource.
    std::vector<g::Footprint> tight(count);
    std::vector<std::uint8_t> source;
    for (std::uint32_t i = 0; i < count; ++i) {
        const g::MipInfo& mi = layout.mips[i % s.mip_levels];
        const std::uint32_t depth = s.dimension == g::Dimension::Tex3D ? mi.depth_slices : 1;
        // Footprint sizes are the mip's size in pixels, as D3D12 reports them.
        tight[i] = {source.size(), std::max(c.width >> (i % s.mip_levels), 1u),
                    std::max(c.height >> (i % s.mip_levels), 1u), depth, mi.width_elements * c.bpe};
        const std::size_t bytes = static_cast<std::size_t>(mi.width_elements) * c.bpe * mi.height_elements * depth;
        const std::size_t at = source.size();
        source.resize(at + bytes);
        for (std::size_t b = at; b < source.size(); ++b) source[b] = static_cast<std::uint8_t>(rng());
    }

    // The title's tiled bytes, in title memory.
    auto* title = static_cast<std::uint8_t*>(XMemAlloc(static_cast<SIZE_T>(layout.surface_size), graphics_word));
    if (!title) {
        std::fprintf(stderr, "%s: XMemAlloc(%llu) failed\n", c.name, static_cast<unsigned long long>(layout.surface_size));
        return -1;
    }
    std::memset(title, 0, static_cast<std::size_t>(layout.surface_size));
    if (!g::TileFromFootprints(config, s, title, static_cast<std::size_t>(layout.surface_size), source.data(),
                               source.size(), tight.data(), count, &error)) {
        std::fprintf(stderr, "%s: TileFromFootprints: %s\n", c.name, error.c_str());
        XMemFree(title, graphics_word);
        return -1;
    }

    // The desktop texture and its copyable footprints.
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = s.dimension == g::Dimension::Tex3D ? D3D12_RESOURCE_DIMENSION_TEXTURE3D
                                                        : D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width = c.width;
    desc.Height = c.height;
    desc.DepthOrArraySize = static_cast<UINT16>(c.depth_or_array);
    desc.MipLevels = static_cast<UINT16>(s.mip_levels);
    desc.Format = c.format;
    desc.SampleDesc.Count = 1;
    std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> placed(count);
    UINT64 total = 0;
    device->GetCopyableFootprints(&desc, 0, count, 0, placed.data(), nullptr, nullptr, &total);
    std::vector<g::Footprint> fp(count);
    for (std::uint32_t i = 0; i < count; ++i)
        fp[i] = {placed[i].Offset, placed[i].Footprint.Width, placed[i].Footprint.Height, placed[i].Footprint.Depth,
                 placed[i].Footprint.RowPitch};

    D3D12_HEAP_PROPERTIES vram{};
    vram.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_HEAP_PROPERTIES up{};
    up.Type = D3D12_HEAP_TYPE_UPLOAD;
    D3D12_HEAP_PROPERTIES rb{};
    rb.Type = D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC bd{};
    bd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    bd.Width = total;
    bd.Height = 1;
    bd.DepthOrArraySize = 1;
    bd.MipLevels = 1;
    bd.SampleDesc.Count = 1;
    bd.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> texture, upload, readback;
    if (!ok(device->CreateCommittedResource(&vram, D3D12_HEAP_FLAG_NONE, &desc, D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                            IID_PPV_ARGS(&texture)),
            "CreateCommittedResource(texture)") ||
        !ok(device->CreateCommittedResource(&up, D3D12_HEAP_FLAG_NONE, &bd, D3D12_RESOURCE_STATE_GENERIC_READ, nullptr,
                                            IID_PPV_ARGS(&upload)),
            "CreateCommittedResource(upload)") ||
        !ok(device->CreateCommittedResource(&rb, D3D12_HEAP_FLAG_NONE, &bd, D3D12_RESOURCE_STATE_COPY_DEST, nullptr,
                                            IID_PPV_ARGS(&readback)),
            "CreateCommittedResource(readback)")) {
        XMemFree(title, graphics_word);
        return -1;
    }

    // The upload path: detile into the footprints, copy every subresource.
    std::uint8_t* mapped = nullptr;
    if (!ok(upload->Map(0, nullptr, reinterpret_cast<void**>(&mapped)), "Map(upload)")) return -1;
    std::memset(mapped, 0, static_cast<std::size_t>(total));
    g::Surface detile_as = s;
    detile_as.pipe_bank_xor ^= detile_xor_flip;
    LARGE_INTEGER t0, t1, frequency;
    QueryPerformanceCounter(&t0);
    const bool detiled = g::DetileToFootprints(config, detile_as, title, static_cast<std::size_t>(layout.surface_size),
                                               mapped, static_cast<std::size_t>(total), fp.data(), count, &error);
    QueryPerformanceCounter(&t1);
    QueryPerformanceFrequency(&frequency);
    upload->Unmap(0, nullptr);
    XMemFree(title, graphics_word);
    if (!detiled) {
        std::fprintf(stderr, "%s: DetileToFootprints: %s\n", c.name, error.c_str());
        return -1;
    }
    if (!ok(gpu.allocator->Reset(), "allocator Reset") || !ok(gpu.list->Reset(gpu.allocator.Get(), nullptr), "list Reset"))
        return -1;
    for (std::uint32_t i = 0; i < count; ++i) {
        D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
        dst.pResource = texture.Get();
        dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        dst.SubresourceIndex = i;
        src.pResource = upload.Get();
        src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        src.PlacedFootprint = placed[i];
        gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    }
    const auto barrier = transition(texture.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COPY_SOURCE);
    gpu.list->ResourceBarrier(1, &barrier);
    for (std::uint32_t i = 0; i < count; ++i) {
        D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
        src.pResource = texture.Get();
        src.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        src.SubresourceIndex = i;
        dst.pResource = readback.Get();
        dst.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dst.PlacedFootprint = placed[i];
        gpu.list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
    }
    if (!ok(gpu.list->Close(), "Close") || !gpu.submit_and_wait()) return -1;

    void* back = nullptr;
    const D3D12_RANGE read{0, static_cast<SIZE_T>(total)};
    if (!ok(readback->Map(0, &read, &back), "Map(readback)")) return -1;
    long long differing = 0;
    for (std::uint32_t i = 0; i < count; ++i) {
        const g::MipInfo& mi = layout.mips[i % s.mip_levels];
        const std::uint32_t row_bytes = mi.width_elements * c.bpe;
        for (std::uint32_t z = 0; z < tight[i].depth; ++z)
            for (std::uint32_t y = 0; y < mi.height_elements; ++y) {
                const std::uint8_t* want = source.data() + tight[i].offset + (static_cast<std::size_t>(z) *
                                           mi.height_elements + y) * row_bytes;
                const std::uint8_t* got = static_cast<const std::uint8_t*>(back) + placed[i].Offset +
                                          (static_cast<std::size_t>(z) * placed[i].Footprint.Height / c.block + y) *
                                              placed[i].Footprint.RowPitch;
                for (std::uint32_t x = 0; x < mi.width_elements; ++x)
                    differing += std::memcmp(want + x * c.bpe, got + x * c.bpe, c.bpe) != 0;
            }
    }
    const D3D12_RANGE none{0, 0};
    readback->Unmap(0, &none);
    std::printf("surface=%s mode=%s %s %ux%ux%u mips=%u subresources=%u tiled_bytes=%llu detile_ms=%.3f "
                "differing_elements=%lld\n",
                c.name, g::SwizzleModeName(s.mode), s.dimension == g::Dimension::Tex3D ? "3D" : "2D", c.width, c.height,
                c.depth_or_array, s.mip_levels, count, static_cast<unsigned long long>(layout.surface_size),
                1000.0 * double(t1.QuadPart - t0.QuadPart) / double(frequency.QuadPart), differing);
    return differing;
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    const std::string_view adapter = argv[1];
    if (adapter != "warp" && adapter != "hardware") return 2;
    Gpu gpu;
    const int created = gpu.create(adapter == "warp");
    if (created) return created;
    std::mt19937 rng(20261122);
    bool good = true;
    for (const Case& c : cases) good = run_case(gpu, c, rng, 0) == 0 && good;
    // Control: the first case detiled with a wrong pipe/bank XOR must not read back equal.
    const long long control = run_case(gpu, cases[0], rng, 0x3);
    std::printf("control=%s\n", control > 0 ? "mismatch_detected" : "mismatch_missed");
    good = good && control > 0;
    const unsigned debug_errors = gpu.debug_errors();
    std::printf("debug_errors=%u result=%s\n", debug_errors, good && debug_errors == 0 ? "pass" : "fail");
    return good && debug_errors == 0 ? 0 : 1;
}
