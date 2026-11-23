// Round-trip and control checks of the GFX10 detiler (src/gfx10_detile.h), without addrlib or a GPU. Builds on
// Windows (ctest gfx10_detile_roundtrip) and Linux (tests/gfx10_addr_oracle_check.py). The address function itself is
// checked against addrlib by tests/gfx10_addr_oracle.
//
// For every swizzle mode, 2D and 3D, all five element sizes and BC1/BC7-shaped elements, several sizes and mip
// counts, with D3D12-shaped footprints (256-byte row pitch, 512-byte subresource alignment):
//   1. TileFromFootprints then DetileToFootprints returns the original bytes of every subresource;
//   2. the tiled bytes equal a reference built element by element with ElementOffset (the row-table fast path
//      places every element where the address function says);
//   3. no two elements share a tiled address (the layout is injective);
// and controls: a flipped tiled byte changes exactly one detiled element, a wrong footprint size, a short tiled
// buffer and an unsupported mode are refused.

#include "gfx10_detile.h"

#include <cstdio>
#include <cstring>
#include <random>
#include <string>
#include <vector>

using namespace x2w::gfx10;

namespace
{

struct Shape
{
    const char* name;
    std::uint32_t bpe, block;
};
const Shape kShapes[] = {{"R8", 1, 1}, {"R16", 2, 1}, {"RGBA8", 4, 1}, {"RGBA16", 8, 1}, {"RGBA32", 16, 1},
                         {"BC1", 8, 4}, {"BC7", 16, 4}};

const SwizzleMode kModes[] = {
    SwizzleMode::Linear,   SwizzleMode::S_256B,   SwizzleMode::D_256B,   SwizzleMode::S_4KB,
    SwizzleMode::D_4KB,    SwizzleMode::S_64KB,   SwizzleMode::D_64KB,   SwizzleMode::S_64KB_T,
    SwizzleMode::D_64KB_T, SwizzleMode::S_4KB_X,  SwizzleMode::D_4KB_X,  SwizzleMode::Z_64KB_X,
    SwizzleMode::S_64KB_X, SwizzleMode::D_64KB_X, SwizzleMode::R_64KB_X, SwizzleMode::Z_VAR_X,
    SwizzleMode::R_VAR_X,
};

std::uint64_t Align(std::uint64_t v, std::uint64_t a) { return (v + a - 1) / a * a; }

// D3D12 GetCopyableFootprints shape: width/height in pixels (BC: rounded up to 4), 256-byte row pitch, 512-byte
// placement alignment, total bytes ending at the last element of the last row.
std::vector<Footprint> Footprints(const Surface& s, std::uint64_t* total)
{
    std::vector<Footprint> out;
    std::uint64_t offset = 0;
    const bool tex3d = s.dimension == Dimension::Tex3D;
    for (std::uint32_t i = 0; i < SubresourceCount(s); ++i)
    {
        const std::uint32_t mip = i % s.mip_levels;
        Footprint f;
        f.width = std::max(s.width >> mip, 1u);
        f.height = std::max(s.height >> mip, 1u);
        f.width = static_cast<std::uint32_t>(Align(f.width, s.element_width));
        f.height = static_cast<std::uint32_t>(Align(f.height, s.element_height));
        f.depth = tex3d ? std::max(s.depth_or_array >> mip, 1u) : 1;
        f.row_pitch = static_cast<std::uint32_t>(Align(f.width / s.element_width * s.element_bytes, 256));
        offset = Align(offset, 512);
        f.offset = offset;
        // As D3D12 sizes it: the last row ends at its last element, not at the row pitch.
        offset += static_cast<std::uint64_t>(f.row_pitch) * ((f.height / s.element_height) * f.depth - 1) +
                  static_cast<std::uint64_t>(f.width / s.element_width) * s.element_bytes;
        out.push_back(f);
    }
    *total = offset;
    return out;
}

int g_failures = 0;
void Fail(const std::string& what)
{
    if (g_failures++ < 20) std::printf("FAIL %s\n", what.c_str());
}

unsigned long long g_surfaces = 0, g_elements = 0;

void Check(const Config& cfg, const Surface& s, const std::string& name, std::mt19937& rng)
{
    Layout l;
    std::string error;
    if (!ComputeLayout(cfg, s, &l, &error)) return;  // combination not valid on GFX10 (also refused by addrlib)
    ++g_surfaces;
    std::uint64_t upload_size = 0;
    const std::vector<Footprint> fp = Footprints(s, &upload_size);
    std::vector<std::uint8_t> upload(upload_size), back(upload_size, 0);
    for (auto& b : upload) b = static_cast<std::uint8_t>(rng());
    std::vector<std::uint8_t> tiled(l.surface_size, 0), reference(l.surface_size, 0);

    if (!TileFromFootprints(cfg, s, tiled.data(), tiled.size(), upload.data(), upload.size(), fp.data(),
                            static_cast<std::uint32_t>(fp.size()), &error))
        return Fail(name + ": TileFromFootprints: " + error);
    if (!DetileToFootprints(cfg, s, tiled.data(), tiled.size(), back.data(), back.size(), fp.data(),
                            static_cast<std::uint32_t>(fp.size()), &error))
        return Fail(name + ": DetileToFootprints: " + error);

    // Reference placement and injectivity, element by element.
    std::vector<std::uint8_t> seen(l.surface_size / s.element_bytes + 1, 0);
    std::vector<std::uint64_t> sampled;  // a few element addresses for the flipped-byte control
    const bool tex3d = s.dimension == Dimension::Tex3D;
    for (std::uint32_t i = 0; i < fp.size(); ++i)
    {
        const std::uint32_t mip = i % s.mip_levels, slice = i / s.mip_levels;
        const MipInfo& mi = l.mips[mip];
        const Footprint& f = fp[i];
        for (std::uint32_t z = 0; z < f.depth; ++z)
            for (std::uint32_t y = 0; y < mi.height_elements; ++y)
            {
                const std::uint64_t row = f.offset + (static_cast<std::uint64_t>(z) * mi.height_elements + y) *
                                                         f.row_pitch;
                for (std::uint32_t x = 0; x < mi.width_elements; ++x)
                {
                    const std::uint64_t at = ElementOffset(s, l, x, y, tex3d ? z : slice, mip);
                    if (at + s.element_bytes > reference.size())
                        return Fail(name + ": ElementOffset outside the surface");
                    if (at % s.element_bytes != 0) return Fail(name + ": element address not element-aligned");
                    if (seen[at / s.element_bytes]++) return Fail(name + ": two elements share an address");
                    if ((rng() & 1023) == 0 || sampled.empty()) sampled.push_back(at);
                    std::memcpy(&reference[at], &upload[row + x * s.element_bytes], s.element_bytes);
                    if (std::memcmp(&back[row + x * s.element_bytes], &upload[row + x * s.element_bytes],
                                    s.element_bytes) != 0)
                        return Fail(name + ": round trip differs at subresource " + std::to_string(i));
                    ++g_elements;
                }
            }
    }
    if (reference != tiled) return Fail(name + ": tiled bytes differ from the ElementOffset reference");

    // Control: one flipped tiled byte changes exactly one element of the detiled output.
    if (!sampled.empty())
    {
        tiled[sampled[rng() % sampled.size()] + rng() % s.element_bytes] ^= 0x5a;
        std::vector<std::uint8_t> again(upload_size, 0);
        DetileToFootprints(cfg, s, tiled.data(), tiled.size(), again.data(), again.size(), fp.data(),
                           static_cast<std::uint32_t>(fp.size()), &error);
        std::size_t differing = 0;
        for (std::size_t b = 0; b < again.size(); ++b) differing += again[b] != back[b];
        if (differing != 1) Fail(name + ": flipped byte changed " + std::to_string(differing) + " bytes");
    }
}

void Controls(const Config& cfg)
{
    Surface s;
    s.mode = SwizzleMode::S_64KB_X;
    s.width = 300;
    s.height = 200;
    s.mip_levels = 4;
    Layout l;
    std::string error;
    ComputeLayout(cfg, s, &l, &error);
    std::uint64_t size = 0;
    std::vector<Footprint> fp = Footprints(s, &size);
    std::vector<std::uint8_t> upload(size), tiled(l.surface_size);
    auto expect_refusal = [&](const char* what, bool ok) {
        if (ok) Fail(std::string("control accepted: ") + what);
        else std::printf("control refused (%s): %s\n", what, error.c_str());
    };
    fp[2].width += 1;
    expect_refusal("wrong footprint width", DetileToFootprints(cfg, s, tiled.data(), tiled.size(), upload.data(),
                                                               upload.size(), fp.data(), 4, &error));
    fp[2].width -= 1;
    expect_refusal("short tiled buffer", DetileToFootprints(cfg, s, tiled.data(), tiled.size() - 1, upload.data(),
                                                            upload.size(), fp.data(), 4, &error));
    expect_refusal("upload buffer one byte short", DetileToFootprints(cfg, s, tiled.data(), tiled.size(), upload.data(),
                                                                      upload.size() - 1, fp.data(), 4, &error));
    expect_refusal("missing footprint", DetileToFootprints(cfg, s, tiled.data(), tiled.size(), upload.data(),
                                                           upload.size(), fp.data(), 3, &error));
    Surface r = s;
    r.mode = static_cast<SwizzleMode>(23);  // SW_4KB_R_X: valid hardware mode, no addrlib pattern
    expect_refusal("SW_4KB_R_X", ComputeLayout(cfg, r, &l, &error));
    Surface v = s;
    v.mode = SwizzleMode::R_VAR_X;
    Config gfx101 = cfg;
    gfx101.rb_plus = false;
    gfx101.gb_addr_config = MakeGbAddrConfig(4, 0);
    expect_refusal("SW_VAR_R_X on GFX10.1", ComputeLayout(gfx101, v, &l, &error));
    Surface z = s;
    z.mode = SwizzleMode::Z_64KB_X;
    z.element_bytes = 16;
    z.element_width = z.element_height = 4;
    expect_refusal("Z order BC7", ComputeLayout(cfg, z, &l, &error));
}

}  // namespace

int main()
{
    std::mt19937 rng(7);
    struct Cfg { const char* name; Config c; };
    Cfg configs[] = {
        {"gfx10.3 16 pipes 16 pkrs", {MakeGbAddrConfig(4, 4), true, true}},
        {"gfx10.3 8 pipes 8 pkrs", {MakeGbAddrConfig(3, 3), true, true}},
        {"gfx10.1 16 pipes", {MakeGbAddrConfig(4, 0), false, true}},
    };
    struct Dims { std::uint32_t w, h, d; };
    const Dims sizes2d[] = {{1, 1, 1}, {64, 64, 1}, {100, 36, 3}, {516, 132, 2}, {2048, 8, 1}};
    const Dims sizes3d[] = {{16, 16, 16}, {36, 20, 23}, {68, 64, 9}};
    for (const Cfg& cfg : configs)
        for (Dimension dim : {Dimension::Tex2D, Dimension::Tex3D})
            for (SwizzleMode mode : kModes)
                for (const Shape& shape : kShapes)
                {
                    const Dims* sizes = dim == Dimension::Tex3D ? sizes3d : sizes2d;
                    const int count = dim == Dimension::Tex3D ? 3 : 5;
                    for (int i = 0; i < count; ++i)
                        for (std::uint32_t mips : {1u, 0u})
                        {
                            Surface s;
                            s.dimension = dim;
                            s.mode = mode;
                            s.element_bytes = shape.bpe;
                            s.element_width = s.element_height = shape.block;
                            s.width = sizes[i].w;
                            s.height = sizes[i].h;
                            s.depth_or_array = sizes[i].d;
                            std::uint32_t full = 1;
                            for (std::uint32_t v = std::max(s.width, std::max(s.height, dim == Dimension::Tex3D
                                                                                            ? s.depth_or_array
                                                                                            : 1u));
                                 v > 1; v >>= 1)
                                ++full;
                            s.mip_levels = mips ? mips : full;
                            s.pipe_bank_xor = rng() & 0xffff;
                            char name[200];
                            std::snprintf(name, sizeof(name), "%s %s %s %s %ux%ux%u mips=%u", cfg.name,
                                          dim == Dimension::Tex3D ? "3D" : "2D", SwizzleModeName(mode), shape.name,
                                          s.width, s.height, s.depth_or_array, s.mip_levels);
                            Check(cfg.c, s, name, rng);
                        }
                }
    Controls(configs[0].c);
    std::printf("surfaces=%llu elements=%llu failures=%d\n", g_surfaces, g_elements, g_failures);
    std::printf("result=%s\n", g_failures == 0 && g_surfaces > 0 ? "pass" : "fail");
    return g_failures == 0 && g_surfaces > 0 ? 0 : 1;
}
