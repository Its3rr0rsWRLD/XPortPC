// GFX10 / GFX10.3 texture address computation (src/gfx10_addr.h).
//
// Provenance: a port of the colour-surface parts of AMD's addrlib as published in Mesa 26.2.6
// (src/amd/addrlib; release tarball sha256 b9436b3e1a8be76fbd4823dc884f90596ab7c6ac5e1867a305e66ffccfb31a92):
//   src/gfx10/gfx10addrlib.cpp  SwizzleModeTable, Block256_3d, HwlInitGlobalParams (pipe/packer decode and
//                               m_colorBaseIndex), GetSwizzlePatternInfo, GetMaxNumMipsInTail,
//                               HwlComputePipeBankXor, ComputeSurfaceInfoMicroTiled, ComputeSurfaceInfoMacroTiled,
//                               HwlComputeSurfaceInfoLinear, ComputeSurfaceAddrFromCoordMicroTiled/MacroTiled,
//                               ValidateNonSwModeParams/ValidateSwModeParams (the colour, single-sample subset)
//   src/gfx10/gfx10addrlib.h    swizzle-mode masks, GetMipSize, IsInMipTail, GetBankXorBits, HwlIsThin/HwlIsThick,
//                               GetSwizzlePatternFromPatternInfo
//   src/core/addrlib2.cpp       Block256_2d, Block1K_3d, ComputeThinBlockDimension, ComputeThickBlockDimension,
//                               GetMipTailDim, ComputeSurfaceAddrFromCoordLinear
//   src/core/addrlib.cpp        ComputeOffsetFromSwizzlePattern
//   src/core/addrelemlib.cpp    AdjustSurfaceInfo (block-compressed sizes in elements, rounded up)
// One deliberate difference: addrlib addresses single-sample tiled surfaces through an "equation" derived from the
// swizzle pattern (ConvertSwizzlePatternToEquation); this port evaluates the swizzle pattern itself, as addrlib does
// for MSAA and in its own CPU copy routines (HwlCopyMemToSurface). The two agree; tests/gfx10_addr_oracle checks it
// against addrlib for every mode, element size and configuration. The pattern also covers the 3D SW_64KB_D_X
// 8/16-byte-element RB+ case, for which addrlib builds no equation (its address function refuses it, its copy
// routine handles it; the oracle uses the copy routine there).
//
// Original notice of the ported files:
//
//   Copyright (C) 2007-2026 Advanced Micro Devices, Inc. All rights reserved.
//   SPDX-License-Identifier: MIT

#include "gfx10_addr.h"

#include "gfx10_swizzle_pattern.h"

#include <algorithm>
#include <cstring>

namespace x2w::gfx10
{
namespace
{
using namespace tables;

struct ModeFlags
{
    bool linear, b256, b4k, b64k, var, z, std_, disp, rot, xor_, t, rtopt;
};

// Gfx10Lib::SwizzleModeTable (Linear 256B 4KB 64KB Var Z Std Disp Rot XOR T RtOpt).
ModeFlags Flags(std::uint32_t m)
{
    switch (m)
    {
    case 0: return {1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
    case 1: return {0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0};
    case 2: return {0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0};
    case 5: return {0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0};
    case 6: return {0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0};
    case 9: return {0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0};
    case 10: return {0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0};
    case 17: return {0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 1, 0};
    case 18: return {0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0};
    case 21: return {0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0};
    case 22: return {0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0};
    case 23: return {0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1};  // SW_4KB_R_X: valid mode, but addrlib has no pattern
    case 24: return {0, 0, 0, 1, 0, 1, 0, 0, 0, 1, 0, 0};
    case 25: return {0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0};
    case 26: return {0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0};
    case 27: return {0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 1};
    case 28: return {0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0};
    case 31: return {0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1};
    default: return {};
    }
}

bool Valid(const ModeFlags& f)
{
    return f.linear || f.b256 || f.b4k || f.b64k || f.var;
}

constexpr std::uint32_t Bit(SwizzleMode m)
{
    return 1u << static_cast<std::uint32_t>(m);
}

// gfx10addrlib.h: Gfx10Rsrc3dSwModeMask.
constexpr std::uint32_t kRsrc3dMask = Bit(SwizzleMode::Linear) | Bit(SwizzleMode::S_4KB) | Bit(SwizzleMode::S_64KB) |
                                      Bit(SwizzleMode::S_64KB_T) | Bit(SwizzleMode::S_4KB_X) |
                                      Bit(SwizzleMode::Z_64KB_X) | Bit(SwizzleMode::S_64KB_X) |
                                      Bit(SwizzleMode::D_64KB_X) | Bit(SwizzleMode::R_64KB_X) |
                                      Bit(SwizzleMode::Z_VAR_X) | Bit(SwizzleMode::R_VAR_X);

struct Dim2 { std::uint32_t w, h; };
struct Dim3 { std::uint32_t w, h, d; };
constexpr Dim2 kBlock256_2d[] = {{16, 16}, {16, 8}, {8, 8}, {8, 4}, {4, 4}};
constexpr Dim3 kBlock256_3d[] = {{8, 4, 8}, {4, 4, 8}, {4, 4, 4}, {4, 2, 4}, {2, 2, 4}};
constexpr Dim3 kBlock1K_3d[] = {{16, 8, 8}, {8, 8, 8}, {8, 8, 4}, {8, 4, 4}, {4, 4, 4}};

constexpr std::uint32_t kColumnBits = 2;
constexpr std::uint32_t kBankBits = 4;
constexpr std::uint32_t kPipeInterleaveLog2 = 8;

std::uint32_t Log2(std::uint32_t v)
{
    std::uint32_t r = 0;
    while (v > 1)
    {
        v >>= 1;
        ++r;
    }
    return r;
}

std::uint32_t PowTwoAlign(std::uint32_t x, std::uint32_t align)
{
    return (x + (align - 1)) & ~(align - 1);
}

std::uint32_t ShiftCeil(std::uint32_t a, std::uint32_t b)
{
    return (a >> b) + (((a & ((1u << b) - 1)) != 0) ? 1 : 0);
}

std::uint32_t MipDim(std::uint32_t mip0, std::uint32_t mip)
{
    return ShiftCeil(mip0 < 1 ? 1 : mip0, mip);
}

struct Pipes
{
    std::uint32_t pipes_log2 = 0;
    std::uint32_t pkrs_log2 = 0;
    std::uint32_t color_base_index = 0;
    std::uint32_t block_var_log2 = 0;
};

bool DecodeConfig(const Config& config, Pipes* p, std::string* error)
{
    const std::uint32_t num_pipes = config.gb_addr_config & 7u;
    const std::uint32_t interleave = (config.gb_addr_config >> 3) & 7u;
    const std::uint32_t pkrs = (config.gb_addr_config >> 8) & 7u;
    if (num_pipes > 6)
    {
        *error = "GB_ADDR_CONFIG.NUM_PIPES out of range";
        return false;
    }
    // addrlib asserts a 256-byte pipe interleave; its swizzle patterns do not exist for any other value.
    if (interleave != 0)
    {
        *error = "GB_ADDR_CONFIG.PIPE_INTERLEAVE_SIZE must be 256 bytes";
        return false;
    }
    p->pipes_log2 = num_pipes;
    p->color_base_index = num_pipes * 5;
    if (config.rb_plus)
    {
        p->pkrs_log2 = pkrs;
        if (pkrs > num_pipes || num_pipes - pkrs > 2)
        {
            *error = "GB_ADDR_CONFIG: NUM_PKRS must satisfy pkrs <= pipes <= pkrs + 2 (log2)";
            return false;
        }
        if (pkrs >= 2) p->color_base_index += (2 * pkrs - 2) * 5;
        p->block_var_log2 = num_pipes + 14;
    }
    return true;
}

std::uint32_t BlockSizeLog2(const ModeFlags& f, const Pipes& p)
{
    if (f.b256 || f.linear) return 8;
    if (f.b4k) return 12;
    if (f.b64k) return 16;
    if (f.var) return p.block_var_log2;
    return 0;
}

bool IsThick(Dimension dim, const ModeFlags& f)
{
    return dim == Dimension::Tex3D && (f.std_ || f.disp);
}

template <std::size_t N>
const ADDR_SW_PATINFO* Pick(const ADDR_SW_PATINFO (&table)[N], std::uint32_t index)
{
    return index < N ? &table[index] : nullptr;
}

#define X2W_PAT(name) (rb ? Pick(GFX10_##name##_RBPLUS_PATINFO, index) : Pick(GFX10_##name##_PATINFO, index))

// Gfx10Lib::GetSwizzlePatternInfo, numFrag == 1.
const ADDR_SW_PATINFO* PatternInfo(SwizzleMode mode, Dimension dim, std::uint32_t elem_log2, const Pipes& p, bool rb)
{
    const ModeFlags f = Flags(static_cast<std::uint32_t>(mode));
    const std::uint32_t index = f.xor_ ? (p.color_base_index + elem_log2) : elem_log2;
    if (f.var)
    {
        if (p.block_var_log2 == 0) return nullptr;
        if (f.rtopt) return Pick(GFX10_SW_VAR_R_X_1xaa_RBPLUS_PATINFO, index);
        if (f.z) return Pick(GFX10_SW_VAR_Z_X_1xaa_RBPLUS_PATINFO, index);
        return nullptr;
    }
    if (f.linear) return nullptr;
    if (dim == Dimension::Tex3D)
    {
        if ((kRsrc3dMask & Bit(mode)) == 0) return nullptr;
        if (f.rtopt) return mode == SwizzleMode::R_64KB_X ? X2W_PAT(SW_64K_R_X_1xaa) : nullptr;
        if (f.z) return X2W_PAT(SW_64K_Z_X_1xaa);
        if (f.disp) return mode == SwizzleMode::D_64KB_X ? X2W_PAT(SW_64K_D3_X) : nullptr;
        if (f.b4k)
        {
            if (mode == SwizzleMode::S_4KB) return X2W_PAT(SW_4K_S3);
            return X2W_PAT(SW_4K_S3_X);
        }
        if (mode == SwizzleMode::S_64KB) return X2W_PAT(SW_64K_S3);
        if (mode == SwizzleMode::S_64KB_X) return X2W_PAT(SW_64K_S3_X);
        return X2W_PAT(SW_64K_S3_T);
    }
    if (f.b256) return mode == SwizzleMode::S_256B ? X2W_PAT(SW_256_S) : X2W_PAT(SW_256_D);
    if (f.b4k)
    {
        switch (mode)
        {
        case SwizzleMode::S_4KB: return X2W_PAT(SW_4K_S);
        case SwizzleMode::S_4KB_X: return X2W_PAT(SW_4K_S_X);
        case SwizzleMode::D_4KB: return X2W_PAT(SW_4K_D);
        case SwizzleMode::D_4KB_X: return X2W_PAT(SW_4K_D_X);
        default: return nullptr;  // SW_4KB_R_X
        }
    }
    switch (mode)
    {
    case SwizzleMode::R_64KB_X: return X2W_PAT(SW_64K_R_X_1xaa);
    case SwizzleMode::Z_64KB_X: return X2W_PAT(SW_64K_Z_X_1xaa);
    case SwizzleMode::D_64KB: return X2W_PAT(SW_64K_D);
    case SwizzleMode::D_64KB_X: return X2W_PAT(SW_64K_D_X);
    case SwizzleMode::D_64KB_T: return X2W_PAT(SW_64K_D_T);
    case SwizzleMode::S_64KB: return X2W_PAT(SW_64K_S);
    case SwizzleMode::S_64KB_X: return X2W_PAT(SW_64K_S_X);
    case SwizzleMode::S_64KB_T: return X2W_PAT(SW_64K_S_T);
    default: return nullptr;
    }
}
#undef X2W_PAT

// Gfx10Lib::GetSwizzlePatternFromPatternInfo.
void FullPattern(const ADDR_SW_PATINFO& info, std::uint64_t (&out)[20])
{
    std::memcpy(&out[0], GFX10_SW_PATTERN_NIBBLE01[info.nibble01Idx], 8 * sizeof(std::uint64_t));
    std::memcpy(&out[8], GFX10_SW_PATTERN_NIBBLE2[info.nibble2Idx], 4 * sizeof(std::uint64_t));
    std::memcpy(&out[12], GFX10_SW_PATTERN_NIBBLE3[info.nibble3Idx], 4 * sizeof(std::uint64_t));
    std::memcpy(&out[16], GFX10_SW_PATTERN_NIBBLE4[info.nibble4Idx], 4 * sizeof(std::uint64_t));
}

std::uint32_t Parity(std::uint32_t v)
{
    v ^= v >> 16;
    v ^= v >> 8;
    v ^= v >> 4;
    v ^= v >> 2;
    v ^= v >> 1;
    return v & 1;
}

// Lib::ComputeOffsetFromSwizzlePattern (sample 0).
std::uint32_t PatternOffset(const std::uint64_t* pattern, std::uint32_t bits, std::uint32_t x, std::uint32_t y,
                            std::uint32_t z)
{
    std::uint32_t offset = 0;
    for (std::uint32_t i = 0; i < bits; ++i)
    {
        const std::uint64_t p = pattern[i];
        const std::uint32_t v = Parity((x & static_cast<std::uint32_t>(p & 0xffff)) ^
                                       (y & static_cast<std::uint32_t>((p >> 16) & 0xffff)) ^
                                       (z & static_cast<std::uint32_t>((p >> 32) & 0xffff)));
        offset |= v << i;
    }
    return offset;
}

}  // namespace

const char* SwizzleModeName(SwizzleMode mode)
{
    switch (mode)
    {
    case SwizzleMode::Linear: return "SW_LINEAR";
    case SwizzleMode::S_256B: return "SW_256B_S";
    case SwizzleMode::D_256B: return "SW_256B_D";
    case SwizzleMode::S_4KB: return "SW_4KB_S";
    case SwizzleMode::D_4KB: return "SW_4KB_D";
    case SwizzleMode::S_64KB: return "SW_64KB_S";
    case SwizzleMode::D_64KB: return "SW_64KB_D";
    case SwizzleMode::S_64KB_T: return "SW_64KB_S_T";
    case SwizzleMode::D_64KB_T: return "SW_64KB_D_T";
    case SwizzleMode::S_4KB_X: return "SW_4KB_S_X";
    case SwizzleMode::D_4KB_X: return "SW_4KB_D_X";
    case SwizzleMode::Z_64KB_X: return "SW_64KB_Z_X";
    case SwizzleMode::S_64KB_X: return "SW_64KB_S_X";
    case SwizzleMode::D_64KB_X: return "SW_64KB_D_X";
    case SwizzleMode::R_64KB_X: return "SW_64KB_R_X";
    case SwizzleMode::Z_VAR_X: return "SW_VAR_Z_X";
    case SwizzleMode::R_VAR_X: return "SW_VAR_R_X";
    }
    return "SW_?";
}

bool ParseSwizzleMode(const char* name, SwizzleMode* mode)
{
    for (std::uint32_t m = 0; m < 32; ++m)
    {
        const auto candidate = static_cast<SwizzleMode>(m);
        if (std::strcmp(SwizzleModeName(candidate), "SW_?") != 0 && std::strcmp(SwizzleModeName(candidate), name) == 0)
        {
            *mode = candidate;
            return true;
        }
    }
    return false;
}

bool ComputeLayout(const Config& config, const Surface& s, Layout* out, std::string* error)
{
    std::string scratch;
    if (error == nullptr) error = &scratch;
    *out = Layout{};
    Pipes pipes;
    if (!DecodeConfig(config, &pipes, error)) return false;

    const std::uint32_t mode_index = static_cast<std::uint32_t>(s.mode);
    const ModeFlags f = Flags(mode_index);
    if (mode_index >= 32 || !Valid(f))
    {
        *error = "invalid swizzle mode";
        return false;
    }
    const std::uint32_t bpe = s.element_bytes;
    if (bpe != 1 && bpe != 2 && bpe != 4 && bpe != 8 && bpe != 16)
    {
        *error = "element size must be 1, 2, 4, 8 or 16 bytes";
        return false;
    }
    if (s.element_width == 0 || s.element_height == 0 || s.width == 0 || s.mip_levels == 0 ||
        s.mip_levels > kMaxMips)
    {
        *error = "invalid surface size or mip count";
        return false;
    }
    if (s.dimension != Dimension::Tex2D && s.dimension != Dimension::Tex3D)
    {
        *error = "only 2D (and 2D array) and 3D surfaces are covered";
        return false;
    }
    const bool tex3d = s.dimension == Dimension::Tex3D;
    const bool compressed = s.element_width > 1 || s.element_height > 1;
    // ValidateSwModeParams, colour single-sample subset.
    if (tex3d && (kRsrc3dMask & Bit(s.mode)) == 0)
    {
        *error = "swizzle mode not valid for 3D surfaces";
        return false;
    }
    if (f.z && (bpe > 8 || compressed))
    {
        *error = "Z-order swizzle needs an uncompressed element of at most 8 bytes";
        return false;
    }
    if (f.var && pipes.block_var_log2 == 0)
    {
        *error = "SW_VAR_* modes exist only with RB+ (GFX10.3)";
        return false;
    }

    // AdjustSurfaceInfo: block-compressed surfaces are laid out in elements.
    const std::uint32_t width = (s.width + s.element_width - 1) / s.element_width;
    const std::uint32_t height = (s.height < 1 ? 1 : (s.height + s.element_height - 1) / s.element_height);
    const std::uint32_t num_slices = s.depth_or_array < 1 ? 1 : s.depth_or_array;
    const std::uint32_t mips = s.mip_levels;
    const std::uint32_t elem_log2 = Log2(bpe);
    const std::uint32_t block_log2 = BlockSizeLog2(f, pipes);
    out->block_size_log2 = block_log2;
    out->first_mip_in_tail = mips;

    // The texels of each mip, as D3D counts them (pixel size max(1, size >> mip), then rounded up to whole
    // elements). addrlib pads with ShiftCeil sizes, which are never smaller.
    for (std::uint32_t i = 0; i < mips; ++i)
    {
        const std::uint32_t pw = std::max(s.width >> i, 1u), ph = std::max(std::max(s.height, 1u) >> i, 1u);
        out->mips[i].width_elements = (pw + s.element_width - 1) / s.element_width;
        out->mips[i].height_elements = (ph + s.element_height - 1) / s.element_height;
        out->mips[i].depth_slices = tex3d ? std::max(num_slices >> i, 1u) : num_slices;
    }

    if (f.linear)
    {
        // Gfx10Lib::HwlComputeSurfaceInfoLinear (SW_LINEAR, no customised pitch).
        const std::uint32_t pitch_align = 256 / bpe;
        const std::uint32_t mip_depth = tex3d ? num_slices : 1;
        std::uint64_t slice_size = 0;
        for (int i = static_cast<int>(mips) - 1; i >= 0; --i)
        {
            const std::uint32_t mw = MipDim(width, i), mh = MipDim(height, i);
            const std::uint32_t pitch = PowTwoAlign(mw, pitch_align);
            out->mips[i].pitch = pitch;
            out->mips[i].height = mh;
            out->mips[i].depth = mip_depth;
            out->mips[i].offset = slice_size;
            out->mips[i].macro_block_offset = slice_size;
            slice_size += static_cast<std::uint64_t>(pitch) * mh * bpe;
        }
        out->pitch = out->mips[0].pitch;
        out->height = height;
        out->num_slices = num_slices;
        out->slice_size = slice_size;
        out->surface_size = slice_size * num_slices;
        out->block_width = pitch_align;
        out->block_height = 1;
        out->block_slices = 1;
        return true;
    }

    const ADDR_SW_PATINFO* info = PatternInfo(s.mode, s.dimension, elem_log2, pipes, config.rb_plus);
    if (info == nullptr)
    {
        *error = "addrlib has no swizzle pattern for this mode, dimension and configuration";
        return false;
    }
    FullPattern(*info, out->pattern);

    // ComputeBlockDimensionForSurf.
    const bool thick = IsThick(s.dimension, f);
    out->thick = thick;
    if (thick)
    {
        const std::uint32_t in_1kb = block_log2 - 10;
        const std::uint32_t average = in_1kb / 3, rest = in_1kb % 3;
        out->block_width = kBlock1K_3d[elem_log2].w << average;
        out->block_height = kBlock1K_3d[elem_log2].h << (average + (rest / 2));
        out->block_slices = kBlock1K_3d[elem_log2].d << (average + ((rest != 0) ? 1 : 0));
    }
    else
    {
        const std::uint32_t num_ele = block_log2 - elem_log2;
        const std::uint32_t log2_width = (num_ele + 1) / 2;
        out->block_width = 1u << log2_width;
        out->block_height = 1u << (num_ele - log2_width);
        out->block_slices = 1;
    }

    // Pipe/bank XOR: Gfx10Lib::ComputeSurfaceAddrFromCoordMacroTiled.
    if (f.xor_ && !f.b256)
    {
        const std::uint32_t block_mask = (1u << block_log2) - 1;
        const std::uint32_t pipe_mask = (1u << pipes.pipes_log2) - 1;
        const std::uint32_t bank_bits =
            block_log2 > kPipeInterleaveLog2 + pipes.pipes_log2 + kColumnBits
                ? std::min(block_log2 - kPipeInterleaveLog2 - pipes.pipes_log2 - kColumnBits, kBankBits)
                : 0;
        const std::uint32_t bank_mask = ((1u << bank_bits) - 1) << (pipes.pipes_log2 + kColumnBits);
        out->pipe_bank_xor_bytes = ((s.pipe_bank_xor & (pipe_mask | bank_mask)) << kPipeInterleaveLog2) & block_mask;
    }

    const std::uint32_t bw = out->block_width, bh = out->block_height, bd = out->block_slices;
    const std::uint32_t block_size = 1u << block_log2;

    if (f.b256)
    {
        if (tex3d)
        {
            *error = "256-byte swizzle modes are not valid for 3D surfaces";
            return false;
        }
        // Gfx10Lib::ComputeSurfaceInfoMicroTiled.
        out->pitch = PowTwoAlign(width, bw);
        out->height = PowTwoAlign(height, bh);
        out->num_slices = num_slices;
        std::uint64_t slice_size = 0;
        for (int i = static_cast<int>(mips) - 1; i >= 0; --i)
        {
            const std::uint32_t pitch = PowTwoAlign(MipDim(width, i), bw);
            const std::uint32_t mh = PowTwoAlign(MipDim(height, i), bh);
            out->mips[i].pitch = pitch;
            out->mips[i].height = mh;
            out->mips[i].depth = 1;
            out->mips[i].offset = slice_size;
            out->mips[i].macro_block_offset = slice_size;
            slice_size += static_cast<std::uint64_t>(pitch) * mh * bpe;
        }
        out->slice_size = slice_size;
        out->surface_size = slice_size * num_slices;
        return true;
    }

    // Gfx10Lib::ComputeSurfaceInfoMacroTiled.
    out->pitch = PowTwoAlign(width, bw);
    out->height = PowTwoAlign(height, bh);
    out->num_slices = PowTwoAlign(num_slices, bd);
    if (mips == 1)
    {
        out->slice_size = static_cast<std::uint64_t>(out->pitch) * out->height * bpe;
        out->surface_size = out->slice_size * out->num_slices;
        out->mips[0].pitch = out->pitch;
        out->mips[0].height = out->height;
        out->mips[0].depth = tex3d ? out->num_slices : 1;
        return true;
    }

    // GetMipTailDim.
    Dim3 tail_max{bw, bh, bd};
    if (thick)
    {
        const std::uint32_t dim = block_log2 % 3;
        if (dim == 0) tail_max.h >>= 1;
        else if (dim == 1) tail_max.w >>= 1;
        else tail_max.d >>= 1;
    }
    else
    {
        tail_max.w >>= 1;
    }
    const std::uint32_t mip0_depth = thick ? num_slices : 1;
    // GetMaxNumMipsInTail.
    std::uint32_t effective_log2 = block_log2;
    if (thick) effective_log2 -= (block_log2 - 8) / 3;
    const std::uint32_t max_mips_in_tail =
        (effective_log2 <= 11) ? (1 + (1u << (effective_log2 - 9))) : (effective_log2 - 4);

    Dim3 fixed_tail = tail_max;
    if (config.ds_mipmap_htile_fix && f.z && elem_log2 <= 1)
    {
        fixed_tail.w /= kBlock256_2d[elem_log2].w / kBlock256_2d[2].w;
        fixed_tail.h /= kBlock256_2d[elem_log2].h / kBlock256_2d[2].h;
    }

    std::uint32_t first_in_tail = mips;
    std::uint64_t chain_slice_size = 0;
    std::uint64_t mip_size[kMaxMips] = {}, mip_slice_size[kMaxMips] = {};
    for (std::uint32_t i = 0; i < mips; ++i)
    {
        const std::uint32_t mw = MipDim(width, i), mh = MipDim(height, i), md = MipDim(mip0_depth, i);
        // IsInMipTail.
        if (mw <= fixed_tail.w && mh <= fixed_tail.h && (mips - i) <= max_mips_in_tail)
        {
            first_in_tail = i;
            chain_slice_size += block_size / bd;
            break;
        }
        const std::uint32_t pitch = PowTwoAlign(mw, bw);
        const std::uint32_t ph = PowTwoAlign(mh, bh);
        const std::uint32_t pd = PowTwoAlign(md, bd);
        const std::uint64_t slice_size = static_cast<std::uint64_t>(pitch) * ph * bpe;
        mip_size[i] = slice_size * pd;
        mip_slice_size[i] = slice_size * bd;
        chain_slice_size += slice_size;
        out->mips[i].pitch = pitch;
        out->mips[i].height = ph;
        out->mips[i].depth = tex3d ? out->num_slices : 1;
    }
    out->slice_size = chain_slice_size;
    out->surface_size = chain_slice_size * out->num_slices;
    out->first_mip_in_tail = first_in_tail;

    std::uint64_t offset = 0, macro_offset = 0;
    std::uint32_t tail_max_depth = 0;
    if (first_in_tail != mips)
    {
        tail_max_depth = MipDim(mip0_depth, first_in_tail);
        offset = static_cast<std::uint64_t>(block_size) * PowTwoAlign(tail_max_depth, bd) / bd;
        macro_offset = block_size;
    }
    for (int i = static_cast<int>(first_in_tail) - 1; i >= 0; --i)
    {
        out->mips[i].offset = offset;
        out->mips[i].macro_block_offset = macro_offset;
        out->mips[i].mip_tail_offset = 0;
        offset += mip_size[i];
        macro_offset += mip_slice_size[i];
    }
    std::uint32_t pitch = tail_max.w, tail_height = tail_max.h;
    const std::uint32_t depth = thick ? PowTwoAlign(tail_max_depth, kBlock256_3d[elem_log2].d) : 1;
    tail_max_depth = thick ? (depth / kBlock256_3d[elem_log2].d) : 1;
    for (std::uint32_t i = first_in_tail; i < mips; ++i)
    {
        const std::uint32_t m = max_mips_in_tail - 1 - (i - first_in_tail);
        const std::uint32_t mip_offset = (m > 6) ? (16u << m) : (m << 8);
        MipInfo& mi = out->mips[i];
        mi.offset = static_cast<std::uint64_t>(mip_offset) * tail_max_depth;
        mi.mip_tail_offset = mip_offset;
        mi.macro_block_offset = 0;
        mi.pitch = pitch;
        mi.height = tail_height;
        mi.depth = tex3d ? out->num_slices : 1;
        std::uint32_t mip_x = ((mip_offset >> 9) & 1) | ((mip_offset >> 10) & 2) | ((mip_offset >> 11) & 4) |
                              ((mip_offset >> 12) & 8) | ((mip_offset >> 13) & 16) | ((mip_offset >> 14) & 32);
        std::uint32_t mip_y = ((mip_offset >> 8) & 1) | ((mip_offset >> 9) & 2) | ((mip_offset >> 10) & 4) |
                              ((mip_offset >> 11) & 8) | ((mip_offset >> 12) & 16) | ((mip_offset >> 13) & 32);
        if (block_log2 & 1)
        {
            const std::uint32_t t = mip_x;
            mip_x = mip_y;
            mip_y = t;
            if (elem_log2 & 1)
            {
                mip_y = (mip_y << 1) | (mip_x & 1);
                mip_x = mip_x >> 1;
            }
        }
        if (!thick)
        {
            mi.tail_x = mip_x * kBlock256_2d[elem_log2].w;
            mi.tail_y = mip_y * kBlock256_2d[elem_log2].h;
            pitch = std::max(pitch >> 1, kBlock256_2d[elem_log2].w);
            tail_height = std::max(tail_height >> 1, kBlock256_2d[elem_log2].h);
        }
        else
        {
            mi.tail_x = mip_x * kBlock256_3d[elem_log2].w;
            mi.tail_y = mip_y * kBlock256_3d[elem_log2].h;
            pitch = std::max(pitch >> 1, kBlock256_3d[elem_log2].w);
            tail_height = std::max(tail_height >> 1, kBlock256_3d[elem_log2].h);
        }
        mi.tail_z = 0;
    }
    return true;
}

std::uint64_t ElementOffset(const Surface& s, const Layout& l, std::uint32_t x, std::uint32_t y,
                            std::uint32_t slice, std::uint32_t mip)
{
    const MipInfo& mi = l.mips[mip];
    const std::uint32_t bpe = s.element_bytes;
    const ModeFlags f = Flags(static_cast<std::uint32_t>(s.mode));
    if (f.linear)
    {
        // Lib::ComputeSurfaceAddrFromCoordLinear.
        return l.slice_size * slice + mi.offset + (static_cast<std::uint64_t>(y) * mi.pitch + x) * bpe;
    }
    const std::uint32_t pb = mi.pitch / l.block_width;
    const std::uint64_t block_index = static_cast<std::uint64_t>(y / l.block_height) * pb + x / l.block_width;
    if (f.b256)
    {
        // Gfx10Lib::ComputeSurfaceAddrFromCoordMicroTiled.
        return l.slice_size * slice + mi.macro_block_offset + block_index * 256 +
               PatternOffset(l.pattern, 8, x, y, 0);
    }
    // Gfx10Lib::ComputeSurfaceAddrFromCoordMacroTiled.
    const bool in_tail = mi.mip_tail_offset != 0;
    const std::uint64_t slice_size = l.thick ? l.slice_size * l.block_slices : l.slice_size;
    const std::uint32_t slice_id = l.thick ? slice / l.block_slices : slice;
    const std::uint32_t tx = in_tail ? x + mi.tail_x : x;
    const std::uint32_t ty = in_tail ? y + mi.tail_y : y;
    const std::uint32_t tz = in_tail ? slice + mi.tail_z : slice;
    const std::uint32_t block_offset = PatternOffset(l.pattern, l.block_size_log2, tx, ty, tz);
    return slice_size * slice_id + mi.macro_block_offset + (block_index << l.block_size_log2) +
           (block_offset ^ l.pipe_bank_xor_bytes);
}

std::uint32_t ComputePipeBankXor(const Config& config, SwizzleMode mode, std::uint32_t surface_index)
{
    Pipes pipes;
    std::string error;
    if (!DecodeConfig(config, &pipes, &error)) return 0;
    const ModeFlags f = Flags(static_cast<std::uint32_t>(mode));
    if (!f.xor_ || f.t) return 0;
    const std::uint32_t block_log2 = BlockSizeLog2(f, pipes);
    const std::uint32_t bank_bits =
        block_log2 > kPipeInterleaveLog2 + pipes.pipes_log2 + kColumnBits
            ? std::min(block_log2 - kPipeInterleaveLog2 - pipes.pipes_log2 - kColumnBits, kBankBits)
            : 0;
    static const std::uint32_t rot[4][8] = {{0, 1, 0, 1, 0, 1, 0, 1},
                                           {0, 2, 1, 3, 2, 0, 3, 1},
                                           {0, 4, 2, 6, 1, 5, 3, 7},
                                           {0, 8, 4, 12, 2, 10, 6, 14}};
    if (bank_bits == 0) return 0;
    return rot[bank_bits - 1][surface_index % 8] << (pipes.pipes_log2 + kColumnBits);
}

}  // namespace x2w::gfx10
