#pragma once

#include <cstdint>
#include <map>
#include <mutex>
#include <vector>

// Title GPU addresses on desktop D3D12.
// On the console a graphics allocation's CPU pointer is also its GPU virtual address: titles
// pass those addresses to D3D12 calls and store them in buffers that shaders read (the BVH
// builder's input records hold such 64-bit addresses). A desktop D3D12 resource gets a GPU
// virtual address chosen by the driver instead. This table maps title address ranges to the
// desktop GPU virtual address of the resource that holds the same bytes (see era_gpu_alias).
namespace era_title_va {
struct Range {
    std::uint64_t title_begin;
    std::uint64_t title_end;  // exclusive
    std::uint64_t gpu_begin;  // desktop GPU virtual address of title_begin
};

// Layout of TitleRange in src/title_va_lookup.hlsli (StructuredBuffer stride 24).
struct ShaderRange {
    std::uint32_t begin_low;
    std::uint32_t begin_high;
    std::uint32_t end_low;
    std::uint32_t end_high;
    std::uint32_t slot;  // descriptor index of the buffer that aliases the range
    std::uint32_t base;  // byte offset of the range's first byte in that buffer (0 for shader_ranges)
};
static_assert(sizeof(ShaderRange) == 24);

// Packs sorted, non-overlapping ranges for the shader lookup; slot i is ranges[i]. Returns false
// and leaves `packed` empty when the ranges are unsorted or overlap, when a range is 4 GiB or
// longer, which a raw buffer view cannot cover, or when a range does not start on a 4-byte
// boundary, which would misalign raw DWORD offsets.
bool shader_ranges(const std::vector<Range>& ranges, std::vector<ShaderRange>& packed);

class Table {
public:
    // Ranges must not overlap. Returns false for an empty, wrapping or overlapping title range,
    // a zero or wrapping GPU range, or allocation failure.
    bool add(std::uint64_t title_begin, std::uint64_t size, std::uint64_t gpu_begin);
    bool remove(std::uint64_t title_begin);
    // Desktop GPU virtual address of title_address when [title_address, title_address + bytes)
    // lies inside one range; 0 otherwise. A byte count of 0 is treated as 1.
    std::uint64_t translate(std::uint64_t title_address, std::uint64_t bytes = 1) const;
    // Ranges sorted by title_begin, for a shader-side lookup table.
    std::vector<Range> ranges() const;

private:
    mutable std::mutex lock_;
    std::map<std::uint64_t, Range> ranges_;  // title_begin -> range
};
}
