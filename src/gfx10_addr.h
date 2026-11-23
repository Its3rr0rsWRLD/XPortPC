// GFX10 / GFX10.3 (RDNA / RDNA2) texture address computation: where element (x, y, slice, mip) of a tiled colour
// surface lives in memory. Ported from AMD's addrlib as published in Mesa (src/amd/addrlib, MIT); see
// src/gfx10_addr.cpp for the provenance and the original notice, and docs/design/runtime.md ("Textures: detiling").
//
// Scope: single-sample 2D, 2D-array and 3D colour/texture surfaces, any element size of 1-16 bytes, which covers
// block-compressed formats (BC1-BC7) as 8- or 16-byte elements of 4x4 pixels. Swizzle modes: every mode addrlib
// gives a swizzle pattern for on GFX10/GFX10.3 (see SwizzleMode). Not covered: MSAA (numFrags > 1), quad-buffer
// stereo, 1D resources, 96-bit linear formats, custom linear pitch, DCC/HTILE/CMASK metadata.

#pragma once

#include <cstdint>
#include <string>

namespace x2w::gfx10
{

// Values are addrlib's AddrSwizzleMode, which are the hardware SW_MODE field values of the image descriptor.
enum class SwizzleMode : std::uint32_t
{
    Linear  = 0,
    S_256B  = 1,
    D_256B  = 2,
    S_4KB   = 5,
    D_4KB   = 6,
    S_64KB  = 9,
    D_64KB  = 10,
    S_64KB_T = 17,
    D_64KB_T = 18,
    S_4KB_X = 21,
    D_4KB_X = 22,
    Z_64KB_X = 24,
    S_64KB_X = 25,
    D_64KB_X = 26,
    R_64KB_X = 27,
    Z_VAR_X = 28,  // GFX10.3 (RB+) only: block size is 16 KiB * pipes
    R_VAR_X = 31,  // GFX10.3 (RB+) only
};

const char* SwizzleModeName(SwizzleMode mode);
bool ParseSwizzleMode(const char* name, SwizzleMode* mode);

// The GPU's address configuration, as addrlib takes it.
struct Config
{
    // GB_ADDR_CONFIG register value. Fields used: NUM_PIPES [2:0] (log2), PIPE_INTERLEAVE_SIZE [5:3] (must be 0:
    // 256 bytes), MAX_COMPRESSED_FRAGS [7:6] (validated only), NUM_PKRS [10:8] (log2, GFX10.3 only).
    std::uint32_t gb_addr_config = 0;
    // True for GFX10.3 (RDNA2: Navi2x, Van Gogh, Rembrandt...), which addrlib calls "RB+" and which selects the
    // *_RBPLUS swizzle tables. False for GFX10.1 (Navi1x).
    bool rb_plus = true;
    // addrlib's dsMipmapHtileFix (mip tail size of Z modes at 1-2 byte elements): set on every GFX10 part except
    // Navi10.
    bool ds_mipmap_htile_fix = true;
};

// GB_ADDR_CONFIG from field values (log2 of pipes and packers).
constexpr std::uint32_t MakeGbAddrConfig(std::uint32_t pipes_log2, std::uint32_t pkrs_log2)
{
    return (pipes_log2 & 7u) | ((pkrs_log2 & 7u) << 8);
}

enum class Dimension : std::uint32_t
{
    Tex2D = 2,  // also 2D arrays and cube maps (6 slices per cube)
    Tex3D = 3,
};

struct Surface
{
    Dimension dimension = Dimension::Tex2D;
    SwizzleMode mode = SwizzleMode::Linear;
    std::uint32_t element_bytes = 4;   // 1, 2, 4, 8 or 16 (BC1/BC4: 8; BC2/BC3/BC5/BC6H/BC7: 16)
    std::uint32_t element_width = 1;   // pixels per element horizontally (4 for BC formats)
    std::uint32_t element_height = 1;  // pixels per element vertically (4 for BC formats)
    std::uint32_t width = 1;           // pixels, mip 0
    std::uint32_t height = 1;          // pixels, mip 0
    std::uint32_t depth_or_array = 1;  // depth (3D) or array size (2D)
    std::uint32_t mip_levels = 1;      // 1-16
    // The descriptor's pipe/bank XOR (addrlib's pipeBankXor; Mesa's tile_swizzle). Only XOR modes use it.
    std::uint32_t pipe_bank_xor = 0;
};

constexpr std::uint32_t kMaxMips = 16;

struct MipInfo
{
    std::uint32_t pitch = 0;    // elements, padded
    std::uint32_t height = 0;   // elements, padded
    std::uint32_t depth = 0;
    std::uint32_t width_elements = 0;   // texels of this mip in elements: ceil(max(1, width >> mip) / element_width)
    std::uint32_t height_elements = 0;
    std::uint32_t depth_slices = 0;     // 3D: max(1, depth >> mip); 2D: array size
    std::uint64_t offset = 0;              // addrlib ADDR2_MIP_INFO::offset
    std::uint64_t macro_block_offset = 0;  // addrlib ADDR2_MIP_INFO::macroBlockOffset (used for addressing)
    std::uint32_t mip_tail_offset = 0;
    std::uint32_t tail_x = 0, tail_y = 0, tail_z = 0;  // element origin of the mip inside the tail block
};

struct Layout
{
    std::uint32_t block_size_log2 = 0;  // 8, 12, 16 or VAR
    std::uint32_t block_width = 0;      // elements
    std::uint32_t block_height = 0;
    std::uint32_t block_slices = 0;
    std::uint32_t pitch = 0, height = 0, num_slices = 0;  // mip 0, padded, elements
    std::uint64_t slice_size = 0;   // bytes of one slice of the mip chain (addrlib sliceSize)
    std::uint64_t surface_size = 0; // bytes of the whole surface (addrlib surfSize)
    std::uint32_t first_mip_in_tail = 0;  // == mip_levels if none
    bool thick = false;                   // 3D S/D modes: blocks span several slices
    MipInfo mips[kMaxMips];
    // Internal: the swizzle pattern (addrlib ADDR_BIT_SETTING per address bit); zero for linear.
    std::uint64_t pattern[20] = {};
    std::uint32_t pipe_bank_xor_bytes = 0;  // XOR applied to the in-block offset
};

// Computes the layout addrlib's Addr2ComputeSurfaceInfo would. Returns false (and a reason) for parameters addrlib
// rejects or this port does not cover.
bool ComputeLayout(const Config& config, const Surface& surface, Layout* layout, std::string* error);

// Byte offset of element (x, y) of slice `slice` (array slice for 2D, depth slice for 3D) of mip `mip`, relative to
// the surface base. Coordinates are in elements of that mip. Matches addrlib's Addr2ComputeSurfaceAddrFromCoord.
std::uint64_t ElementOffset(const Surface& surface, const Layout& layout, std::uint32_t x, std::uint32_t y,
                            std::uint32_t slice, std::uint32_t mip);

// addrlib Gfx10Lib::HwlComputePipeBankXor: the pipe/bank XOR a driver would pick for its surfIndex-th surface.
std::uint32_t ComputePipeBankXor(const Config& config, SwizzleMode mode, std::uint32_t surface_index);

}  // namespace x2w::gfx10
