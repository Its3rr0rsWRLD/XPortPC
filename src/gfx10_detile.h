// CPU detiler for GFX10 / GFX10.3 tiled textures (docs/design/runtime.md, "Textures: detiling").
//
// Entry point for the graphics shim: DetileToFootprints. Given the title's tiled bytes of one texture (all
// subresources, as the console GPU lays them out from the texture's base address) and the desktop copyable
// footprints of the matching desktop texture (ID3D12Device::GetCopyableFootprints), it writes every subresource as
// linear rows into the upload buffer, ready for CopyTextureRegion (or UpdateSubresources). TileFromFootprints is the
// inverse (tests; later, CPU readback of GPU-written textures into title memory).
//
// No D3D12 types here, so the same code builds and is tested on Linux against addrlib (tests/gfx10_addr_oracle).

#pragma once

#include "gfx10_addr.h"

#include <cstddef>
#include <cstdint>
#include <string>

namespace x2w::gfx10
{

// Mirrors D3D12_PLACED_SUBRESOURCE_FOOTPRINT: offset into the upload buffer, size in pixels (width/height) or
// slices (depth), and the row pitch in bytes. For block-compressed formats, a "row" is one row of 4x4 blocks.
struct Footprint
{
    std::uint64_t offset = 0;
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t depth = 0;
    std::uint32_t row_pitch = 0;
};

// D3D12 subresource order: index = mip + array_slice * mip_levels (3D: one subresource per mip).
constexpr std::uint32_t SubresourceCount(const Surface& s)
{
    return s.mip_levels * (s.dimension == Dimension::Tex3D ? 1 : (s.depth_or_array < 1 ? 1 : s.depth_or_array));
}

// Copies one subresource between tiled memory and a linear region. `rows` element rows of `row_elements` elements
// per depth slice are copied (clamped to the mip's size in elements); linear row r of slice z is at
// linear + z * slice_pitch + r * row_pitch. For 2D, `slice` selects the array slice and one slice is copied;
// for 3D, all depth slices of the mip are copied and `slice` must be 0.
bool DetileSubresource(const Surface& surface, const Layout& layout, const void* tiled, std::size_t tiled_size,
                       std::uint32_t mip, std::uint32_t slice, void* linear, std::uint64_t row_pitch,
                       std::uint64_t slice_pitch, std::string* error);
bool TileSubresource(const Surface& surface, const Layout& layout, void* tiled, std::size_t tiled_size,
                     std::uint32_t mip, std::uint32_t slice, const void* linear, std::uint64_t row_pitch,
                     std::uint64_t slice_pitch, std::string* error);

// The shim's entry point. `footprints` has SubresourceCount(surface) entries in D3D12 subresource order; each
// footprint's width/height/depth must equal the subresource's size (mip size in pixels, as D3D12 reports it),
// and each row pitch must hold a row of elements. Returns false, writing nothing more, on the first mismatch, an
// unsupported surface, or `tiled_size` smaller than the surface (addrlib surfSize).
bool DetileToFootprints(const Config& config, const Surface& surface, const void* tiled, std::size_t tiled_size,
                        void* upload, std::size_t upload_size, const Footprint* footprints,
                        std::uint32_t footprint_count, std::string* error);
bool TileFromFootprints(const Config& config, const Surface& surface, void* tiled, std::size_t tiled_size,
                        const void* upload, std::size_t upload_size, const Footprint* footprints,
                        std::uint32_t footprint_count, std::string* error);

}  // namespace x2w::gfx10
