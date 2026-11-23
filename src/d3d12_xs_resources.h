#pragma once

// The address model of buffers a title creates through the d3d12_xs.dll graphics shim (docs/design/runtime.md,
// section 4, "Buffers the title creates through the device").
//
// On the console one address space holds both CPU pointers and GPU virtual addresses, and titles store GPU addresses
// in memory that shaders and the command processor read. A desktop buffer has a driver-chosen GPU address in another
// space. So every buffer created through the shim's device gets a title GPU address, which its wrapper's
// GetGPUVirtualAddress returns, and the address is registered with xmem.dll's title GPU registry
// (X2WTitleGpuRegisterResource). From then on the same translation serves it as serves XMem memory:
// X2WTitleGpuTranslate for API calls (root views, vertex and index buffer views, ExecuteIndirect argument rewrites)
// and TitleLookup for translated shaders.
//
// Which title address:
// - a buffer in a heap the CPU can map (UPLOAD, READBACK, GPU_UPLOAD, CUSTOM with a CPU page property): its mapped
//   CPU pointer, kept mapped for the buffer's life, so the CPU pointer is the GPU address as on the console;
// - a buffer placed in a heap opened from title memory (OpenExistingHeapFromAddress): the heap's address plus the
//   offset; when that span is already title memory xmem.dll translates (an XMem allocation), nothing is registered;
// - any other buffer (DEFAULT heaps, reserved buffers, placed buffers in other heaps): a range of process address
//   space reserved for it (MEM_RESERVE, no access, rounded up to 64 KiB), so it cannot collide with title memory.
// READBACK buffers, buffers that deny shader resources and buffers of 4 GiB or more are registered for API translation
// only (no shader reads them, and TitleLookup ranges are below 4 GiB). A shader-visible buffer without UAV access (an
// UPLOAD buffer) gets a null UAV in the title-memory table: translated shaders read it, stores to it write nothing.
// Textures have no GPU virtual address and get none.
//
// Without xmem.dll in the process (or without its registration export) there is no registry: the title address is
// the desktop GPU address (identity), and the first such buffer is noted once.

#include <d3d12.h>

#include <cstdint>
#include <vector>

namespace d3d12_xs {
namespace resources {

struct TitleAddress {
    std::uint64_t title = 0;    // what GetGPUVirtualAddress returns; 0 for a texture
    std::uint64_t bytes = 0;
    void* reservation = nullptr;  // MEM_RESERVE range to free, or null
    bool registered = false;
    bool mapped = false;          // the shim holds one Map of subresource 0
};

// Picks and registers the title address of a desktop resource. `heap` is the heap properties of a committed
// resource, or of the heap a placed resource lives in (null when unknown, for example a reserved resource);
// `existing_heap_address` is the address an existing heap was opened from (0 otherwise) and `offset` the placed
// offset in it.
TitleAddress assign(ID3D12Resource* desktop, const D3D12_HEAP_PROPERTIES* heap, std::uint64_t existing_heap_address,
                    std::uint64_t offset);
void release(ID3D12Resource* desktop, TitleAddress& address);

// One translated range as the GPU rewrite of title addresses reads it (d3d12_xs_indirect.hlsl, stride 24).
struct Translation {
    std::uint32_t title_begin[2];
    std::uint32_t title_end[2];
    std::uint32_t gpu_begin[2];
};
static_assert(sizeof(Translation) == 24);
// Every translated range now (X2WTitleGpuGetTranslations), sorted. False when xmem.dll cannot answer; an empty list
// when it is not loaded.
bool translations(std::vector<Translation>& out);

}  // namespace resources
}  // namespace d3d12_xs
