// Differential test of src/gfx10_addr.cpp and src/gfx10_detile.cpp against AMD's addrlib (Mesa, MIT), built from
// the pinned Mesa release by tests/gfx10_addr_oracle_check.py. Linux/macOS only; no D3D12.
//
// For every configuration (GFX10.3 RB+ pipe/packer counts, GFX10.1 pipe counts), dimension, swizzle mode, format
// (5 element sizes and BC1-BC7) and a set of sizes and mip counts:
//   1. layout: Addr2ComputeSurfaceInfo vs ComputeLayout (accept/reject, sizes, block, every mip's pitch, height,
//      offsets, tail offset and tail coordinates);
//   2. addresses: Addr2ComputeSurfaceAddrFromCoord vs ElementOffset for random and corner (x, y, slice, mip) samples
//      with random pipe/bank XOR values;
//   3. copies (a subset of sizes): Addr2CopyMemToSurface of random linear data vs TileSubresource (identical tiled
//      bytes) and DetileSubresource of addrlib's tiled bytes (identical linear data).
// A negative control runs the address comparison with the wrong RB+ setting and must find mismatches.
//
// Usage: oracle [--quick]. Prints count lines and "result=pass" or the first mismatches and "result=fail".

#include "addrinterface.h"

#include "gfx10_addr.h"
#include "gfx10_detile.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <set>
#include <string>
#include <vector>

using namespace x2w::gfx10;

namespace
{

void* ADDR_API Alloc(const ADDR_ALLOCSYSMEM_INPUT* in) { return std::malloc(in->sizeInBytes); }
ADDR_E_RETURNCODE ADDR_API Free(const ADDR_FREESYSMEM_INPUT* in) { std::free(in->pVirtAddr); return ADDR_OK; }

struct Chip
{
    const char* name;
    std::uint32_t revision;  // FAMILY_NV revision: 0x28 Navi21 (GFX10.3), 0x01 Navi10, 0x14 Navi14
    std::uint32_t pipes_log2, pkrs_log2;
    bool rb_plus;
    bool htile_fix;
};

ADDR_HANDLE CreateLib(const Chip& chip)
{
    ADDR_CREATE_INPUT in = {};
    ADDR_CREATE_OUTPUT out = {};
    in.size = sizeof(in);
    out.size = sizeof(out);
    in.chipEngine = 0x0000000D;  // CIASICIDGFXENGINE_ARCTICISLAND
    in.chipFamily = 0x8F;        // FAMILY_NV
    in.chipRevision = chip.revision;
    in.callbacks.allocSysMem = Alloc;
    in.callbacks.freeSysMem = Free;
    in.regValue.gbAddrConfig = MakeGbAddrConfig(chip.pipes_log2, chip.pkrs_log2);
    if (AddrCreate(&in, &out) != ADDR_OK) return nullptr;
    return out.hLib;
}

struct Format
{
    const char* name;
    std::uint32_t bpe;
    std::uint32_t block;  // pixels per element edge
    AddrFormat addr;
};

const Format kFormats[] = {
    {"R8", 1, 1, ADDR_FMT_INVALID},     {"R16", 2, 1, ADDR_FMT_INVALID},  {"RGBA8", 4, 1, ADDR_FMT_INVALID},
    {"RGBA16", 8, 1, ADDR_FMT_INVALID}, {"RGBA32", 16, 1, ADDR_FMT_INVALID}, {"BC1", 8, 4, ADDR_FMT_BC1},
    {"BC2", 16, 4, ADDR_FMT_BC2},       {"BC3", 16, 4, ADDR_FMT_BC3},     {"BC4", 8, 4, ADDR_FMT_BC4},
    {"BC5", 16, 4, ADDR_FMT_BC5},       {"BC6H", 16, 4, ADDR_FMT_BC6},    {"BC7", 16, 4, ADDR_FMT_BC7},
};

const SwizzleMode kModes[] = {
    SwizzleMode::Linear,   SwizzleMode::S_256B,   SwizzleMode::D_256B,   SwizzleMode::S_4KB,
    SwizzleMode::D_4KB,    SwizzleMode::S_64KB,   SwizzleMode::D_64KB,   SwizzleMode::S_64KB_T,
    SwizzleMode::D_64KB_T, SwizzleMode::S_4KB_X,  SwizzleMode::D_4KB_X,  SwizzleMode::Z_64KB_X,
    SwizzleMode::S_64KB_X, SwizzleMode::D_64KB_X, SwizzleMode::R_64KB_X, SwizzleMode::Z_VAR_X,
    SwizzleMode::R_VAR_X,
};

struct Size
{
    std::uint32_t w, h, d;
    bool copy;  // also run the whole-surface copy comparison
};

const Size kSizes2D[] = {{1, 1, 1, true},     {7, 5, 1, true},       {64, 64, 1, true},   {100, 37, 3, true},
                         {256, 256, 1, true}, {513, 129, 2, true},   {1920, 1080, 1, false},
                         {36, 68, 6, true},   {4096, 16, 1, false},  {16384, 4, 1, false}};
const Size kSizes3D[] = {{1, 1, 1, true},  {16, 16, 16, true}, {37, 19, 23, true},
                         {128, 64, 32, false}, {5, 300, 9, true}, {256, 256, 64, false}};

struct Counts
{
    unsigned long long cases = 0, layouts = 0, rejected_both = 0, samples = 0, samples_via_copy = 0;
    unsigned long long copy_subresources = 0, copy_bytes = 0, copy_skipped_lut = 0, mismatches = 0;
};

int g_reported = 0;
std::set<std::string> g_no_equation;  // (dimension, mode, element size, RB+) groups addrlib has no equation for
void Mismatch(Counts& c, const std::string& what)
{
    ++c.mismatches;
    if (g_reported++ < 25) std::printf("MISMATCH %s\n", what.c_str());
}

std::uint32_t MaxMips(std::uint32_t w, std::uint32_t h, std::uint32_t d)
{
    std::uint32_t m = 1;
    std::uint32_t v = std::max(w, std::max(h, d));
    while (v > 1) { v >>= 1; ++m; }
    return std::min(m, 16u);
}

struct Case
{
    const Chip* chip;
    ADDR_HANDLE lib;
    Dimension dim;
    SwizzleMode mode;
    const Format* fmt;
    Size size;
    std::uint32_t mips;
    std::uint32_t pbx;
    std::string Name() const
    {
        char buf[256];
        std::snprintf(buf, sizeof(buf), "%s %s %s %s %ux%ux%u mips=%u pbx=0x%x", chip->name,
                      dim == Dimension::Tex3D ? "3D" : "2D", SwizzleModeName(mode), fmt->name, size.w, size.h,
                      size.d, mips, pbx);
        return buf;
    }
};

Surface MakeSurface(const Case& k)
{
    Surface s;
    s.dimension = k.dim;
    s.mode = k.mode;
    s.element_bytes = k.fmt->bpe;
    s.element_width = s.element_height = k.fmt->block;
    s.width = k.size.w;
    s.height = k.size.h;
    s.depth_or_array = k.size.d;
    s.mip_levels = k.mips;
    s.pipe_bank_xor = k.pbx;
    return s;
}

Config MakeConfig(const Chip& chip)
{
    Config c;
    c.gb_addr_config = MakeGbAddrConfig(chip.pipes_log2, chip.pkrs_log2);
    c.rb_plus = chip.rb_plus;
    c.ds_mipmap_htile_fix = chip.htile_fix;
    return c;
}

// Returns true if addrlib accepted the surface. Fills `info`/`mips`.
bool AddrInfo(const Case& k, ADDR2_COMPUTE_SURFACE_INFO_OUTPUT* out, ADDR2_MIP_INFO* mips)
{
    ADDR2_COMPUTE_SURFACE_INFO_INPUT in = {};
    in.size = sizeof(in);
    in.flags.texture = 1;
    in.swizzleMode = static_cast<AddrSwizzleMode>(k.mode);
    in.resourceType = k.dim == Dimension::Tex3D ? ADDR_RSRC_TEX_3D : ADDR_RSRC_TEX_2D;
    in.format = k.fmt->addr;
    in.bpp = k.fmt->bpe * 8;
    in.width = k.size.w;
    in.height = k.size.h;
    in.numSlices = k.size.d;
    in.numMipLevels = k.mips;
    in.numSamples = 1;
    in.numFrags = 1;
    std::memset(out, 0, sizeof(*out));
    std::memset(mips, 0, sizeof(ADDR2_MIP_INFO) * 16);
    out->size = sizeof(*out);
    out->pMipInfo = mips;
    return Addr2ComputeSurfaceInfo(k.lib, &in, out) == ADDR_OK;
}

// addrlib's copy routines take the pipe/bank XOR as the byte value XORed into in-block offsets (not the descriptor
// field Addr2ComputeSurfaceAddrFromCoord takes), so they get the port's derived value; the address comparison checks
// that derivation against addrlib.
ADDR2_COPY_MEMSURFACE_INPUT CopyInput(const Case& k, const Layout& l, void* surface)
{
    ADDR2_COPY_MEMSURFACE_INPUT in = {};
    in.size = sizeof(in);
    in.swizzleMode = static_cast<AddrSwizzleMode>(k.mode);
    in.format = k.fmt->addr;
    in.flags.texture = 1;
    in.resourceType = k.dim == Dimension::Tex3D ? ADDR_RSRC_TEX_3D : ADDR_RSRC_TEX_2D;
    in.bpp = k.fmt->bpe * 8;
    in.unAlignedDims = {k.size.w, k.size.h, k.size.d};
    in.numMipLevels = k.mips;
    in.numSamples = 1;
    in.pbXor = l.pipe_bank_xor_bytes;
    in.pMappedSurface = surface;
    return in;
}

void CheckCase(const Case& k, Counts& c, std::mt19937& rng, bool quick)
{
    if (const char* only = std::getenv("ORACLE_ONLY"))
        if (k.Name().find(only) == std::string::npos) return;
    ++c.cases;
    const Surface s = MakeSurface(k);
    const Config cfg = MakeConfig(*k.chip);
    ADDR2_COMPUTE_SURFACE_INFO_OUTPUT ai;
    ADDR2_MIP_INFO am[16];
    const bool addr_ok = AddrInfo(k, &ai, am);
    Layout l;
    std::string error;
    const bool ours_ok = ComputeLayout(cfg, s, &l, &error);
    if (!addr_ok && !ours_ok)
    {
        ++c.rejected_both;
        return;
    }
    if (addr_ok != ours_ok)
    {
        Mismatch(c, k.Name() + ": addrlib " + (addr_ok ? "accepts" : "rejects") + ", port " +
                        (ours_ok ? "accepts" : "rejects (" + error + ")"));
        return;
    }
    ++c.layouts;
    bool layout_ok = ai.surfSize == l.surface_size && ai.sliceSize == l.slice_size && ai.pitch == l.pitch &&
                     ai.height == l.height && ai.numSlices == l.num_slices && ai.blockWidth == l.block_width &&
                     ai.blockHeight == l.block_height && ai.blockSlices == l.block_slices &&
                     (k.mode == SwizzleMode::Linear || k.mode == SwizzleMode::S_256B || k.mode == SwizzleMode::D_256B ||
                      ai.firstMipIdInTail == l.first_mip_in_tail);
    for (std::uint32_t m = 0; m < k.mips && layout_ok; ++m)
    {
        const MipInfo& mi = l.mips[m];
        layout_ok = am[m].pitch == mi.pitch && am[m].height == mi.height && am[m].offset == mi.offset &&
                    am[m].macroBlockOffset == mi.macro_block_offset && am[m].mipTailOffset == mi.mip_tail_offset &&
                    am[m].mipTailCoordX == mi.tail_x && am[m].mipTailCoordY == mi.tail_y &&
                    am[m].mipTailCoordZ == mi.tail_z;
        if (!layout_ok)
        {
            char buf[512];
            std::snprintf(buf, sizeof(buf),
                          " mip %u: addrlib pitch %u height %u offset %llu macro %llu tail %u (%u,%u,%u) / port "
                          "pitch %u height %u offset %llu macro %llu tail %u (%u,%u,%u)",
                          m, am[m].pitch, am[m].height, (unsigned long long)am[m].offset,
                          (unsigned long long)am[m].macroBlockOffset, am[m].mipTailOffset, am[m].mipTailCoordX,
                          am[m].mipTailCoordY, am[m].mipTailCoordZ, mi.pitch, mi.height,
                          (unsigned long long)mi.offset, (unsigned long long)mi.macro_block_offset,
                          mi.mip_tail_offset, mi.tail_x, mi.tail_y, mi.tail_z);
            Mismatch(c, k.Name() + buf);
            return;
        }
    }
    if (!layout_ok)
    {
        char buf[512];
        std::snprintf(buf, sizeof(buf),
                      " surface: addrlib size %llu slice %llu pitch %u height %u slices %u block %ux%ux%u tail %u / "
                      "port size %llu slice %llu pitch %u height %u slices %u block %ux%ux%u tail %u",
                      (unsigned long long)ai.surfSize, (unsigned long long)ai.sliceSize, ai.pitch, ai.height,
                      ai.numSlices, ai.blockWidth, ai.blockHeight, ai.blockSlices, ai.firstMipIdInTail,
                      (unsigned long long)l.surface_size, (unsigned long long)l.slice_size, l.pitch, l.height,
                      l.num_slices, l.block_width, l.block_height, l.block_slices, l.first_mip_in_tail);
        Mismatch(c, k.Name() + buf);
        return;
    }

    // Addresses.
    const bool tex3d = k.dim == Dimension::Tex3D;
    const int samples = quick ? 24 : 96;
    bool equation_missing = false;
    for (std::uint32_t m = 0; m < k.mips && !equation_missing; ++m)
    {
        const MipInfo& mi = l.mips[m];
        for (int i = 0; i < samples + 4; ++i)
        {
            std::uint32_t x, y, z;
            if (i < 4)
            {
                x = (i & 1) ? mi.width_elements - 1 : 0;
                y = (i & 2) ? mi.height_elements - 1 : 0;
                z = (i & 1) ? mi.depth_slices - 1 : 0;
            }
            else
            {
                x = rng() % mi.width_elements;
                y = rng() % mi.height_elements;
                z = rng() % mi.depth_slices;
            }
            ADDR2_COMPUTE_SURFACE_ADDRFROMCOORD_INPUT in = {};
            ADDR2_COMPUTE_SURFACE_ADDRFROMCOORD_OUTPUT out = {};
            in.size = sizeof(in);
            out.size = sizeof(out);
            in.x = x;
            in.y = y;
            in.slice = z;
            in.mipId = m;
            in.swizzleMode = static_cast<AddrSwizzleMode>(k.mode);
            in.flags.texture = 1;
            in.resourceType = tex3d ? ADDR_RSRC_TEX_3D : ADDR_RSRC_TEX_2D;
            in.bpp = k.fmt->bpe * 8;
            in.unalignedWidth = (k.size.w + k.fmt->block - 1) / k.fmt->block;
            in.unalignedHeight = (k.size.h + k.fmt->block - 1) / k.fmt->block;
            in.numSlices = k.size.d;
            in.numMipLevels = k.mips;
            in.numSamples = 1;
            in.numFrags = 1;
            in.pipeBankXor = k.mode == SwizzleMode::Linear ? 0 : k.pbx;
            if (Addr2ComputeSurfaceAddrFromCoord(k.lib, &in, &out) != ADDR_OK)
            {
                // addrlib has no equation (3D SW_64KB_D_X, 8/16-byte elements, RB+): covered by the copy check.
                equation_missing = true;
                g_no_equation.insert(std::string(tex3d ? "3D " : "2D ") + SwizzleModeName(k.mode) + " " +
                                     std::to_string(k.fmt->bpe) + "B" + (k.chip->rb_plus ? " RB+" : ""));
                break;
            }
            ++c.samples;
            const std::uint64_t ours = ElementOffset(s, l, x, y, z, m);
            if (ours != out.addr)
            {
                char buf[256];
                std::snprintf(buf, sizeof(buf), " (x=%u y=%u slice=%u mip=%u): addrlib 0x%llx port 0x%llx", x, y,
                              z, m, (unsigned long long)out.addr, (unsigned long long)ours);
                Mismatch(c, k.Name() + buf);
                return;
            }
        }
    }

    if (!k.size.copy && !equation_missing) return;
    if (l.surface_size > (64u << 20)) return;
    // addrlib's copy routines do not implement SW_VAR_* (HwlCopyMemToSurface returns ADDR_NOTIMPLEMENTED after
    // overflowing its lookup tables), so VAR modes are checked by addresses only.
    if (k.mode == SwizzleMode::Z_VAR_X || k.mode == SwizzleMode::R_VAR_X) return;
    // Its lookup tables hold 2100 entries (LutAddresser::MaxLutSize); some Z-order patterns need more and overflow
    // the stack. Those surfaces are checked by addresses only.
    {
        std::uint32_t masks[4] = {};
        for (std::uint64_t bit : l.pattern)
            for (int ch = 0; ch < 4; ++ch) masks[ch] |= static_cast<std::uint32_t>((bit >> (16 * ch)) & 0xffff);
        if (masks[0] + masks[1] + masks[2] + masks[3] + 4 > 2100)
        {
            if (equation_missing) Mismatch(c, k.Name() + ": no addrlib oracle (no equation and no copy)");
            ++c.copy_skipped_lut;
            return;
        }
    }
    if (std::getenv("ORACLE_TRACE")) { std::printf("copy %s\n", k.Name().c_str()); std::fflush(stdout); }

    // Whole-surface copies.
    std::vector<std::uint8_t> by_addrlib(l.surface_size, 0xA5), by_port(l.surface_size, 0xA5);
    const std::uint32_t subresources = tex3d ? k.mips : k.mips * k.size.d;
    for (std::uint32_t sub = 0; sub < subresources; ++sub)
    {
        const std::uint32_t m = sub % k.mips, slice = tex3d ? 0 : sub / k.mips;
        const MipInfo& mi = l.mips[m];
        const std::uint32_t row = mi.width_elements * k.fmt->bpe + 3;  // odd pitch on purpose
        const std::uint64_t plane = static_cast<std::uint64_t>(row) * mi.height_elements;
        const std::uint32_t depth = tex3d ? mi.depth_slices : 1;
        std::vector<std::uint8_t> linear(plane * depth), back(plane * depth, 0);
        for (auto& b : linear) b = static_cast<std::uint8_t>(rng());

        ADDR2_COPY_MEMSURFACE_INPUT in = CopyInput(k, l, by_addrlib.data());
        ADDR2_COPY_MEMSURFACE_REGION region = {};
        region.size = sizeof(region);
        region.slice = slice;
        region.mipId = m;
        region.copyDims = {mi.width_elements, mi.height_elements, depth};
        region.pMem = linear.data();
        region.memRowPitch = row;
        region.memSlicePitch = plane;
        if (Addr2CopyMemToSurface(k.lib, &in, &region, 1) != ADDR_OK)
        {
            Mismatch(c, k.Name() + ": Addr2CopyMemToSurface failed");
            return;
        }
        if (!TileSubresource(s, l, by_port.data(), by_port.size(), m, slice, linear.data(), row, plane, &error))
        {
            Mismatch(c, k.Name() + ": TileSubresource: " + error);
            return;
        }
        ++c.copy_subresources;
        c.copy_bytes += static_cast<unsigned long long>(mi.width_elements) * mi.height_elements * depth * k.fmt->bpe;
    }
    if (by_addrlib != by_port)
    {
        std::size_t first = 0;
        while (by_addrlib[first] == by_port[first]) ++first;
        Mismatch(c, k.Name() + ": tiled bytes differ from addrlib's first at offset " + std::to_string(first));
        return;
    }
    // Detile addrlib's bytes and compare with what addrlib reads back.
    for (std::uint32_t sub = 0; sub < subresources; ++sub)
    {
        const std::uint32_t m = sub % k.mips, slice = tex3d ? 0 : sub / k.mips;
        const MipInfo& mi = l.mips[m];
        const std::uint32_t row = mi.width_elements * k.fmt->bpe;
        const std::uint64_t plane = static_cast<std::uint64_t>(row) * mi.height_elements;
        const std::uint32_t depth = tex3d ? mi.depth_slices : 1;
        std::vector<std::uint8_t> expected(plane * depth), ours(plane * depth);
        ADDR2_COPY_MEMSURFACE_INPUT in = CopyInput(k, l, by_addrlib.data());
        ADDR2_COPY_MEMSURFACE_REGION region = {};
        region.size = sizeof(region);
        region.slice = slice;
        region.mipId = m;
        region.copyDims = {mi.width_elements, mi.height_elements, depth};
        region.pMem = expected.data();
        region.memRowPitch = row;
        region.memSlicePitch = plane;
        if (Addr2CopySurfaceToMem(k.lib, &in, &region, 1) != ADDR_OK ||
            !DetileSubresource(s, l, by_addrlib.data(), by_addrlib.size(), m, slice, ours.data(), row, plane,
                               &error) ||
            expected != ours)
        {
            Mismatch(c, k.Name() + ": detiled subresource " + std::to_string(sub) + " differs from addrlib's");
            return;
        }
        if (equation_missing) c.samples_via_copy += static_cast<unsigned long long>(mi.width_elements) *
                                                    mi.height_elements * depth;
    }
}

// Negative control: compare against addrlib with the other RB+ setting; mismatches must appear.
unsigned long long NegativeControl(ADDR_HANDLE rb_plus_lib, std::mt19937& rng)
{
    Chip wrong = {"wrong", 0x28, 4, 4, false, true};
    Config cfg = MakeConfig(wrong);
    unsigned long long found = 0;
    for (SwizzleMode mode : {SwizzleMode::S_64KB_X, SwizzleMode::R_64KB_X, SwizzleMode::D_4KB_X})
    {
        Surface s;
        s.mode = mode;
        s.width = 512;
        s.height = 512;
        Layout l;
        if (!ComputeLayout(cfg, s, &l, nullptr)) continue;
        for (int i = 0; i < 64; ++i)
        {
            ADDR2_COMPUTE_SURFACE_ADDRFROMCOORD_INPUT in = {};
            ADDR2_COMPUTE_SURFACE_ADDRFROMCOORD_OUTPUT out = {};
            in.size = sizeof(in);
            out.size = sizeof(out);
            in.x = rng() % 512;
            in.y = rng() % 512;
            in.swizzleMode = static_cast<AddrSwizzleMode>(mode);
            in.resourceType = ADDR_RSRC_TEX_2D;
            in.bpp = 32;
            in.unalignedWidth = in.unalignedHeight = 512;
            in.numSlices = in.numMipLevels = in.numSamples = in.numFrags = 1;
            if (Addr2ComputeSurfaceAddrFromCoord(rb_plus_lib, &in, &out) == ADDR_OK &&
                out.addr != ElementOffset(s, l, in.x, in.y, 0, 0))
                ++found;
        }
    }
    return found;
}

}  // namespace

int main(int argc, char** argv)
{
    const bool quick = argc > 1 && std::strcmp(argv[1], "--quick") == 0;
    std::vector<Chip> chips;
    // GFX10.3 (RB+): every pipe/packer combination addrlib's tables cover (pkrs <= pipes <= pkrs + 2), which
    // includes Mesa's navi21 (16 pipes, 16 packers), navi21_8pkr, navi22, navi24, vangogh and raphael test configs.
    for (std::uint32_t pipes = 0; pipes <= 6; ++pipes)
        for (std::uint32_t pkrs = pipes >= 2 ? pipes - 2 : 0; pkrs <= pipes && pkrs <= 5; ++pkrs)
        {
            if (pipes == 6 && pkrs == 6) continue;
            static char names[64][32];
            static int n = 0;
            std::snprintf(names[n], sizeof(names[n]), "gfx10.3/p%u/k%u", 1u << pipes, 1u << pkrs);
            chips.push_back({names[n++], 0x28, pipes, pkrs, true, true});
        }
    // GFX10.1: Navi10 (no htile fix) and Navi14.
    for (std::uint32_t pipes : {2u, 3u, 4u})
    {
        static char names[8][32];
        static int n = 0;
        std::snprintf(names[n], sizeof(names[n]), "gfx10.1/navi10/p%u", 1u << pipes);
        chips.push_back({names[n++], 0x01, pipes, 0, false, false});
    }
    chips.push_back({"gfx10.1/navi14/p4", 0x14, 2, 0, false, true});

    Counts c;
    std::mt19937 rng(20261122);
    ADDR_HANDLE control_lib = nullptr;
    for (const Chip& chip : chips)
    {
        ADDR_HANDLE lib = CreateLib(chip);
        if (lib == nullptr)
        {
            std::printf("MISMATCH AddrCreate failed for %s\n", chip.name);
            return 1;
        }
        if (chip.rb_plus && chip.pipes_log2 == 4 && chip.pkrs_log2 == 4) control_lib = lib;
        const bool full = !quick || (chip.rb_plus && chip.pipes_log2 == 4);
        for (Dimension dim : {Dimension::Tex2D, Dimension::Tex3D})
            for (SwizzleMode mode : kModes)
                for (const Format& fmt : kFormats)
                {
                    const Size* sizes = dim == Dimension::Tex3D ? kSizes3D : kSizes2D;
                    const std::size_t count = dim == Dimension::Tex3D ? std::size(kSizes3D) : std::size(kSizes2D);
                    for (std::size_t si = 0; si < count; ++si)
                    {
                        Size size = sizes[si];
                        if (!full && si % 3 != 0) continue;
                        if (fmt.block > 1 && dim == Dimension::Tex2D && (size.w % 4 || size.h % 4))
                        {
                            // D3D12 requires BC mip 0 to be a multiple of 4; addrlib rounds up either way.
                            size.w = (size.w + 3) & ~3u;
                            size.h = (size.h + 3) & ~3u;
                        }
                        const std::uint32_t full_mips = MaxMips(size.w, size.h, dim == Dimension::Tex3D ? size.d : 1);
                        for (std::uint32_t mips : {1u, 3u, full_mips})
                        {
                            if (mips > full_mips) continue;
                            Case k{&chip, lib, dim, mode, &fmt, size, mips, static_cast<std::uint32_t>(rng() & 0xffff)};
                            CheckCase(k, c, rng, quick);
                        }
                    }
                }
        if (lib != control_lib) AddrDestroy(lib);
    }
    const unsigned long long control = control_lib ? NegativeControl(control_lib, rng) : 0;
    if (control_lib) AddrDestroy(control_lib);

    std::printf("configs=%zu cases=%llu layouts_compared=%llu rejected_by_both=%llu\n", chips.size(), c.cases,
                c.layouts, c.rejected_both);
    std::printf("address_samples=%llu elements_compared_by_copy_only=%llu\n", c.samples, c.samples_via_copy);
    std::printf("copy_subresources=%llu copy_bytes=%llu copy_skipped_lut_limit=%llu\n", c.copy_subresources,
                c.copy_bytes, c.copy_skipped_lut);
    std::string groups;
    for (const auto& g : g_no_equation) groups += (groups.empty() ? "" : ", ") + g;
    std::printf("no_addrlib_equation_groups=[%s]\n", groups.c_str());
    std::printf("negative_control_mismatches=%llu (must be > 0)\n", control);
    std::printf("mismatches=%llu\n", c.mismatches);
    const bool pass = c.mismatches == 0 && control > 0 && c.samples > 0;
    std::printf("result=%s\n", pass ? "pass" : "fail");
    return pass ? 0 : 1;
}
