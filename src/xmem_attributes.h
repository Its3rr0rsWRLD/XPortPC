#pragma once

// The XMemAlloc attribute word, as the desktop title memory layer (src/xmem_title.h) reads it.
//
// Sources, all public:
// - Field layout and the page-size and memory-type enumerations: SlimEra `era.h` (XWine1, MIT, Copyright (c) 2025
//   XWine1; the notice is reproduced in src/xmem_title.cpp). That header describes the Xbox One ERA kernel's
//   XALLOC_ATTRIBUTES union: objectType:14, pageSize:2, allocatorId:8, alignment:5 (log2), memoryType:4,
//   reserved:31.
// - That Series X|S titles pass words in the same layout is supported by the call sites this repository records
//   (tests/xmem_attribute_scan_check.py: the Bink word 0x05e50000 and the AMD word 0xa8004000 decode to sensible
//   heap and graphics requests), not by a published Scarlett header.
// - Microsoft's public Xbox GDK samples (github.com/microsoft/Xbox-GDK-Samples, MIT) build attribute words with
//   MAKE_XALLOC_ATTRIBUTES(allocatorId, objectType, memoryType, pageSize, alignment[, ...]) and the names
//   eXALLOCAllocatorId_MiddlewareReservedMin, XALLOC_MEMTYPE_GRAPHICS_WRITECOMBINE(_GPU_READONLY),
//   XALLOC_PAGESIZE_64KB and XALLOC_ALIGNMENT_64K (Kits/DirectXTex/DirectXTexXboxD3D12X.cpp,
//   Samples/Graphics/FastBlockCompress/FBC_GPU.cpp). The numeric values behind those names are in the GDK's xmem.h,
//   whose reference pages (learn.microsoft.com/gaming/gdk/.../reference/system/xmem) are restricted to the Xbox
//   developer program. Nothing here depends on them: memory types are handled by number, and which numbers are
//   GPU-visible is a configurable desktop policy (X2WXMemConfig::gpu_types).
#include <cstdint>

namespace xmem_attributes {

enum PageSize : std::uint32_t {
    page_4kb = 0,   // XALLOC_PAGESIZE_4KB
    page_64kb = 1,  // XALLOC_PAGESIZE_64KB
    page_4mb = 2,   // XALLOC_PAGESIZE_4MB (ERA); no fourth value is defined
    page_undefined = 3,
};

// ERA numbering: heap, six graphics types, three physical types. Values 10-15 are undefined.
enum MemoryType : std::uint32_t {
    heap = 0,
    graphics_first = 1,
    graphics_last = 6,
    physical_first = 7,
    physical_last = 9,
    memory_type_count = 10,
};

struct Fields {
    std::uint32_t object_type;   // bits 0-13, a tag
    std::uint32_t page_size;     // bits 14-15
    std::uint32_t allocator_id;  // bits 16-23, a tag (per-ID statistics)
    std::uint32_t alignment;     // bits 24-28, log2 of the requested alignment
    std::uint32_t memory_type;   // bits 29-32
    std::uint64_t reserved;      // bits 33-63, must be zero
};

constexpr Fields decode(std::uint64_t word) noexcept
{
    return {
        static_cast<std::uint32_t>(word & 0x3fff),
        static_cast<std::uint32_t>((word >> 14) & 0x3),
        static_cast<std::uint32_t>((word >> 16) & 0xff),
        static_cast<std::uint32_t>((word >> 24) & 0x1f),
        static_cast<std::uint32_t>((word >> 29) & 0xf),
        word >> 33,
    };
}

constexpr std::uint64_t encode(std::uint32_t memory_type, std::uint32_t page_size, std::uint32_t alignment_log2,
                               std::uint32_t allocator_id = 0, std::uint32_t object_type = 0) noexcept
{
    return (std::uint64_t{object_type} & 0x3fff) | (std::uint64_t{page_size} & 0x3) << 14 |
           (std::uint64_t{allocator_id} & 0xff) << 16 | (std::uint64_t{alignment_log2} & 0x1f) << 24 |
           (std::uint64_t{memory_type} & 0xf) << 29;
}

constexpr std::uint64_t page_bytes(std::uint32_t page_size) noexcept
{
    return page_size == page_4kb ? std::uint64_t{4} << 10
           : page_size == page_64kb ? std::uint64_t{64} << 10
           : page_size == page_4mb  ? std::uint64_t{4} << 20
                                    : 0;
}

constexpr bool is_graphics(std::uint32_t memory_type) noexcept
{
    return memory_type >= graphics_first && memory_type <= graphics_last;
}

static_assert(decode(0xa8004000).memory_type == 5 && decode(0xa8004000).page_size == page_64kb &&
              decode(0xa8004000).alignment == 8);
static_assert(decode(0x05e50000).memory_type == heap && decode(0x05e50000).allocator_id == 0xe5 &&
              decode(0x05e50000).alignment == 5);
static_assert(encode(5, page_64kb, 8) == 0xa8004000 && encode(0, page_4kb, 5, 0xe5) == 0x05e50000);
}  // namespace xmem_attributes
