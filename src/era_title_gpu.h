#pragma once

#include "era_gpu_alias.h"
#include "era_title_va.h"

#include <cstddef>
#include <cstdint>
#include <vector>

// Graphics allocations as the title's GPU sees them.
// On the console a graphics allocation is GPU-visible at its CPU address as soon as it exists.
// This process-wide registry holds two kinds of record:
// - a backing: desktop memory that D3D12 can open as one existing heap (a VirtualAlloc allocation, aliased with
//   OpenExistingHeapFromAddress, or a pagefile section, aliased with OpenExistingHeapFromFileMapping). Once a device
//   is attached, each backing gets one era_gpu_alias buffer, which is one title memory slot for translated shaders;
// - a range: a title address range whose bytes are bytes [offset, offset + size) of one backing. Ranges are what
//   era_query reports as GPU-intended, what X2WTitleGpuTranslate translates and what TitleLookup finds.
// An xmem arena is one backing holding many ranges (one per live allocation), a physical page pool is one section
// backing whose ranges are the title's mapped views, and a standalone allocation is a backing with one range at
// offset 0 (track/untrack below, the original interface):
// - backings that exist at attach time are aliased then;
// - later ones are aliased when they are added.
// A D3D12 layer can then translate title GPU addresses, find the buffer and offset behind one, or take a snapshot for
// the shader lookup (src/title_va_lookup.hlsli), in which ranges of one backing share its slot.
//
// The registry is created by the first add or attach and never destroyed, so unloading the module releases no D3D12
// object. The other functions never create it; without it they behave as for an empty registry. All functions are
// thread-safe. The registry does not wait for GPU work: releasing memory the GPU still uses is a title error on the
// console as well.
namespace era_title_gpu {
// Records a standalone graphics allocation: a backing over [base, base + bytes) with one range covering it, registered
// with era_query as GPU-intended. With a device attached it is also aliased; if aliasing fails the allocation stays
// tracked without a desktop GPU address. Returns false for null, empty, wrapping or overlapping input, or allocation
// failure. An allocation failure, including one while creating the registry, registers nothing, and the same call can
// be retried.
bool track(void* base, std::size_t bytes) noexcept;
// Drops a standalone allocation (its range and backing) or any other range starting at base, with its alias,
// translation and era_query registration. Returns false when base starts no range.
bool untrack(void* base) noexcept;

// A backing over the committed VirtualAlloc allocation [base, base + bytes), keyed by base, holding no range yet.
// Returns false for null, empty, wrapping, a backing overlapping another, or allocation failure.
bool add_backing(void* base, std::size_t bytes) noexcept;
// A backing over the first `bytes` of a section, keyed by `key` (any value no other backing uses, such as an address
// the caller owns). The handle must stay open while the backing exists.
bool add_section_backing(std::uintptr_t key, HANDLE section, std::size_t bytes) noexcept;
// Drops a backing with every range it holds. Returns false when key names no backing.
bool remove_backing(std::uintptr_t key) noexcept;
// A range [base, base + bytes) holding bytes [offset, offset + bytes) of the backing `backing`, registered with
// era_query. For an address backing the range must be the backing's own bytes (base == backing + offset). Returns
// false for null, empty, wrapping or overlapping input, an unknown backing, a span outside it, or allocation failure.
// `extent` (at least `bytes`; 0 means `bytes`) is how much of the backing the allocation owns, such as its whole
// pages: shader_view merges a range with the next range of the same backing that starts at the end of its extent,
// so page-rounding slack does not split one slot's ranges. Translation and locate use `bytes` only.
bool add_range(void* base, std::size_t bytes, std::uintptr_t backing, std::uint64_t offset,
               std::size_t extent = 0) noexcept;
// Drops the range starting at base (not its backing). Returns false when base starts no range.
bool remove_range(void* base) noexcept;

// Uses `device` for every backing and for later ones. Returns:
// - S_OK when every backing is aliased;
// - E_INVALIDARG for a null device;
// - E_NOTIMPL, without changing anything, when the device does not support existing heaps;
// - E_OUTOFMEMORY, without changing anything, when the registry cannot be created;
// - otherwise the first aliasing failure, after trying every backing.
// Attaching the same device again retries backings that are not aliased. Attaching a different
// device drops every alias first.
HRESULT attach(ID3D12Device* device) noexcept;
// Drops every alias and the device. Backings and ranges stay.
void detach() noexcept;

// Desktop GPU virtual address of [title_address, title_address + bytes), or 0 when the span is not
// inside one range of an aliased backing. A byte count of 0 is treated as 1.
std::uint64_t translate(std::uint64_t title_address, std::uint64_t bytes = 1) noexcept;
// The aliasing buffer and byte offset in it for [title_address, title_address + bytes). The buffer is
// returned with a reference added. Returns false when the span is not inside one range of an aliased backing.
bool locate(std::uint64_t title_address, std::uint64_t bytes, ID3D12Resource** buffer,
            std::uint64_t* offset) noexcept;

struct ShaderView {
    // Sorted by title address. A range is merged with the next range of the same backing when that one starts at the
    // end of its extent (add_range) at the matching backing offset; the merged range then also covers the slack.
    // `slot` names
    // resources[slot]; `base` is the range's byte offset in that buffer.
    std::vector<era_title_va::ShaderRange> ranges;
    std::vector<Microsoft::WRL::ComPtr<ID3D12Resource>> resources;  // one per aliased backing in use
    std::size_t unpackable = 0;  // ranges left out: 4 GiB or longer, not 4-byte aligned, or ending past 4 GiB in
                                 // their buffer (a shader offset is 32 bits)
};
// The ranges of aliased backings, and the registered desktop buffers registered with `shader` set (one slot each),
// packed for TitleLookup. Returns false only on allocation failure.
bool shader_view(ShaderView& view) noexcept;

struct Counts {
    std::size_t tracked;           // title ranges (not registered desktop buffers)
    std::size_t aliased;           // of those, ranges whose backing is aliased
    std::size_t backings;          // title memory backings
    std::size_t aliased_backings;
    std::size_t external;          // desktop buffers registered with register_resource
};
Counts counts() noexcept;

// Desktop buffers at title addresses (the D3D12 layer's address model, docs/design/runtime.md section 4): a buffer a
// title creates through the D3D12 layer has a title GPU address the layer chose (a reserved or mapped range of this
// process, so it never overlaps a title range). It is held as a backing of its own with one range at offset 0, not
// aliased and not registered with era_query; untrack, remove_range and remove_backing refuse it. Registering maps
// [title_address, + bytes) to the buffer's desktop GPU address for translate/locate and, when `shader` is set, packs
// it for TitleLookup. The registry holds a reference on the buffer until unregister_resource. Works with or without
// an attached device. Returns false for a null or empty span, a buffer without a GPU address, an overlap or
// allocation failure.
bool register_resource(std::uint64_t title_address, std::uint64_t bytes, ID3D12Resource* buffer,
                       bool shader) noexcept;
// Drops a registered buffer. Returns false when title_address does not start one.
bool unregister_resource(std::uint64_t title_address) noexcept;
// Every translated range (aliased allocations and registered buffers) sorted by title address, with its desktop
// GPU address: what an API-side or GPU-side rewrite of title addresses needs.
bool translations(std::vector<era_title_va::Range>& out) noexcept;
}
