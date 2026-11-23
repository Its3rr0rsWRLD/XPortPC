// CPU detiler for GFX10 / GFX10.3 tiled textures (src/gfx10_detile.h).
//
// Per element the address is ElementOffset (src/gfx10_addr.cpp). The swizzle pattern is linear over GF(2), so the
// in-block offset splits into an x part and a (y, z) part that are XORed: the x part is tabulated once per mip and
// the (y, z) part once per row, which keeps the inner loop to a table read, an add, an XOR and a copy.

#include "gfx10_detile.h"

#include <cstring>
#include <vector>

namespace x2w::gfx10
{
namespace
{

std::uint32_t Parity(std::uint32_t v)
{
    v ^= v >> 16;
    v ^= v >> 8;
    v ^= v >> 4;
    v ^= v >> 2;
    v ^= v >> 1;
    return v & 1;
}

// The part of the in-block offset selected by one coordinate (channel 0 = x, 1 = y, 2 = z).
std::uint32_t Part(const Layout& l, std::uint32_t bits, std::uint32_t channel, std::uint32_t value)
{
    std::uint32_t offset = 0;
    for (std::uint32_t i = 0; i < bits; ++i)
    {
        const std::uint32_t mask = static_cast<std::uint32_t>((l.pattern[i] >> (16 * channel)) & 0xffff);
        offset |= Parity(value & mask) << i;
    }
    return offset;
}

inline void CopyElement(std::uint8_t* dst, const std::uint8_t* src, std::uint32_t bytes)
{
    switch (bytes)
    {
    case 1: *dst = *src; break;
    case 2: std::memcpy(dst, src, 2); break;
    case 4: std::memcpy(dst, src, 4); break;
    case 8: std::memcpy(dst, src, 8); break;
    default: std::memcpy(dst, src, 16); break;
    }
}

template <bool kDetile>
bool Copy(const Surface& s, const Layout& l, std::uint8_t* tiled, std::size_t tiled_size, std::uint32_t mip,
          std::uint32_t slice, std::uint8_t* linear, std::uint64_t row_pitch, std::uint64_t slice_pitch,
          std::string* error)
{
    std::string scratch;
    if (error == nullptr) error = &scratch;
    const bool tex3d = s.dimension == Dimension::Tex3D;
    if (mip >= s.mip_levels || (tex3d ? slice != 0 : slice >= (s.depth_or_array < 1 ? 1 : s.depth_or_array)))
    {
        *error = "mip or slice out of range";
        return false;
    }
    if (l.surface_size > tiled_size)
    {
        *error = "tiled data is smaller than the surface (" + std::to_string(tiled_size) + " < " +
                 std::to_string(l.surface_size) + " bytes)";
        return false;
    }
    const MipInfo& mi = l.mips[mip];
    const std::uint32_t bpe = s.element_bytes;
    const std::uint32_t cols = mi.width_elements, rows = mi.height_elements;
    const std::uint32_t slices = tex3d ? mi.depth_slices : 1;
    if (row_pitch < static_cast<std::uint64_t>(cols) * bpe)
    {
        *error = "row pitch smaller than a row of elements";
        return false;
    }

    if (s.mode == SwizzleMode::Linear)
    {
        for (std::uint32_t z = 0; z < slices; ++z)
            for (std::uint32_t y = 0; y < rows; ++y)
            {
                const std::uint64_t at = ElementOffset(s, l, 0, y, tex3d ? z : slice, mip);
                std::uint8_t* row = linear + z * slice_pitch + y * row_pitch;
                if (kDetile) std::memcpy(row, tiled + at, static_cast<std::size_t>(cols) * bpe);
                else std::memcpy(tiled + at, row, static_cast<std::size_t>(cols) * bpe);
            }
        return true;
    }

    const bool micro = l.block_size_log2 == 8;
    const bool in_tail = mi.mip_tail_offset != 0;
    const std::uint32_t bits = l.block_size_log2;
    const std::uint32_t tail_x = in_tail ? mi.tail_x : 0, tail_y = in_tail ? mi.tail_y : 0;
    const std::uint32_t tail_z = in_tail ? mi.tail_z : 0;
    const std::uint32_t pb = mi.pitch / l.block_width;

    // x part: block column (added) and pattern bits (XORed).
    std::vector<std::uint64_t> column(cols);
    std::vector<std::uint32_t> xpart(cols);
    for (std::uint32_t x = 0; x < cols; ++x)
    {
        column[x] = static_cast<std::uint64_t>(x / l.block_width) << bits;
        xpart[x] = Part(l, bits, 0, x + tail_x);
    }

    for (std::uint32_t z = 0; z < slices; ++z)
    {
        const std::uint32_t sl = tex3d ? z : slice;
        std::uint64_t slice_base;
        std::uint32_t zpart = 0;
        if (micro)
        {
            slice_base = l.slice_size * sl + mi.macro_block_offset;
        }
        else
        {
            const std::uint64_t slice_size = l.thick ? l.slice_size * l.block_slices : l.slice_size;
            const std::uint32_t slice_id = l.thick ? sl / l.block_slices : sl;
            slice_base = slice_size * slice_id + mi.macro_block_offset;
            zpart = Part(l, bits, 2, sl + tail_z);
        }
        for (std::uint32_t y = 0; y < rows; ++y)
        {
            const std::uint64_t row_base =
                slice_base + ((static_cast<std::uint64_t>(y / l.block_height) * pb) << bits);
            const std::uint32_t yz = Part(l, bits, 1, y + tail_y) ^ zpart ^ (micro ? 0 : l.pipe_bank_xor_bytes);
            std::uint8_t* row = linear + z * slice_pitch + y * row_pitch;
            for (std::uint32_t x = 0; x < cols; ++x)
            {
                const std::uint64_t at = row_base + column[x] + (xpart[x] ^ yz);
                if (at + bpe > tiled_size)
                {
                    *error = "element address outside the tiled data";
                    return false;
                }
                if (kDetile) CopyElement(row + static_cast<std::size_t>(x) * bpe, tiled + at, bpe);
                else CopyElement(tiled + at, row + static_cast<std::size_t>(x) * bpe, bpe);
            }
        }
    }
    return true;
}

template <bool kDetile>
bool CopyFootprints(const Config& config, const Surface& s, std::uint8_t* tiled, std::size_t tiled_size,
                    std::uint8_t* upload, std::size_t upload_size, const Footprint* footprints,
                    std::uint32_t count, std::string* error)
{
    std::string scratch;
    if (error == nullptr) error = &scratch;
    Layout layout;
    if (!ComputeLayout(config, s, &layout, error)) return false;
    if (count != SubresourceCount(s))
    {
        *error = "expected " + std::to_string(SubresourceCount(s)) + " footprints, got " + std::to_string(count);
        return false;
    }
    const bool tex3d = s.dimension == Dimension::Tex3D;
    for (std::uint32_t i = 0; i < count; ++i)
    {
        const std::uint32_t mip = i % s.mip_levels, slice = i / s.mip_levels;
        const Footprint& f = footprints[i];
        const MipInfo& mi = layout.mips[mip];
        const std::uint32_t cols = (f.width + s.element_width - 1) / s.element_width;
        const std::uint32_t rows = (f.height + s.element_height - 1) / s.element_height;
        const std::uint32_t depth = tex3d ? mi.depth_slices : 1;
        const std::string where = "subresource " + std::to_string(i) + " (mip " + std::to_string(mip) + ")";
        if (cols != mi.width_elements || rows != mi.height_elements || f.depth != depth)
        {
            *error = where + ": footprint " + std::to_string(f.width) + "x" + std::to_string(f.height) + "x" +
                     std::to_string(f.depth) + " does not match the tiled mip (" +
                     std::to_string(mi.width_elements) + "x" + std::to_string(mi.height_elements) + "x" +
                     std::to_string(depth) + " elements)";
            return false;
        }
        const std::uint64_t slice_pitch = static_cast<std::uint64_t>(f.row_pitch) * rows;
        if (f.offset + slice_pitch * depth > upload_size)
        {
            *error = where + ": footprint outside the upload buffer";
            return false;
        }
        if (!Copy<kDetile>(s, layout, tiled, tiled_size, mip, tex3d ? 0 : slice, upload + f.offset, f.row_pitch,
                           slice_pitch, error))
        {
            *error = where + ": " + *error;
            return false;
        }
    }
    return true;
}

}  // namespace

bool DetileSubresource(const Surface& surface, const Layout& layout, const void* tiled, std::size_t tiled_size,
                       std::uint32_t mip, std::uint32_t slice, void* linear, std::uint64_t row_pitch,
                       std::uint64_t slice_pitch, std::string* error)
{
    return Copy<true>(surface, layout, static_cast<std::uint8_t*>(const_cast<void*>(tiled)), tiled_size, mip, slice,
                      static_cast<std::uint8_t*>(linear), row_pitch, slice_pitch, error);
}

bool TileSubresource(const Surface& surface, const Layout& layout, void* tiled, std::size_t tiled_size,
                     std::uint32_t mip, std::uint32_t slice, const void* linear, std::uint64_t row_pitch,
                     std::uint64_t slice_pitch, std::string* error)
{
    return Copy<false>(surface, layout, static_cast<std::uint8_t*>(tiled), tiled_size, mip, slice,
                       static_cast<std::uint8_t*>(const_cast<void*>(linear)), row_pitch, slice_pitch, error);
}

bool DetileToFootprints(const Config& config, const Surface& surface, const void* tiled, std::size_t tiled_size,
                        void* upload, std::size_t upload_size, const Footprint* footprints,
                        std::uint32_t footprint_count, std::string* error)
{
    return CopyFootprints<true>(config, surface, static_cast<std::uint8_t*>(const_cast<void*>(tiled)), tiled_size,
                                static_cast<std::uint8_t*>(upload), upload_size, footprints, footprint_count, error);
}

bool TileFromFootprints(const Config& config, const Surface& surface, void* tiled, std::size_t tiled_size,
                        const void* upload, std::size_t upload_size, const Footprint* footprints,
                        std::uint32_t footprint_count, std::string* error)
{
    return CopyFootprints<false>(config, surface, static_cast<std::uint8_t*>(tiled), tiled_size,
                                 static_cast<std::uint8_t*>(const_cast<void*>(upload)), upload_size, footprints,
                                 footprint_count, error);
}

}  // namespace x2w::gfx10
