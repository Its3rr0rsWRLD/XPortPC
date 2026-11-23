#pragma once

// Title descriptor heaps of the d3d12_xs.dll graphics shim (runtime rung R4, docs/design/runtime.md section 3).
//
// A CBV/SRV/UAV or sampler heap the title creates is a wrapper (d3d12_xs_wrap.cpp) over a desktop shadow heap of the
// same type and size that is never shader visible. Its handles are title addresses: the heap owns a block of process
// memory of count * increment bytes, the CPU handle of descriptor i is base + i * increment and, for a shader-visible
// heap, so is the GPU handle (one address space, as on the console). The title-facing increments are the sizes of the
// hardware descriptors a console shader loads: 32 bytes (a T#) for CBV/SRV/UAV heaps and 16 bytes (an S#) for samplers.
// RTV and DSV heaps are desktop heaps, unwrapped.
//
// Writes through the API (Create*View, CreateSampler, CopyDescriptors*) create the desktop descriptor in the shadow
// heap at the same index and record what the slot holds (Slot). They also write marker words into the slot's title
// memory (write_marker): a reserved descriptor type that names the slot and its generation, so a title that copies
// descriptor memory itself (memcpy of a whole descriptor) copies a reference to that desktop descriptor, and a title
// that writes hardware words over it replaces it. Translated shaders resolve a descriptor-table read at translation
// time (tools/pso_translate.py) to (table root parameter, byte offset), and the shim resolves that at draw time
// (resolve): the words in title memory decide. A marker resolves to the slot it names (if that slot still holds
// the same generation); any other non-zero words are hardware words (a T#, S# or V# the title wrote itself, runtime
// R6 descriptors), which d3d12_xs_pipeline.cpp decodes (src/gfx10_descriptors.h); all-zero words are no descriptor.
//
// All functions take the registry lock; the records are read only through the functions below.

#include <d3d12.h>

#include <cstdint>
#include <vector>

namespace d3d12_xs {
namespace descriptors {

constexpr UINT view_increment = 32;     // CBV/SRV/UAV: one T# (the larger of a T# and a V#)
constexpr UINT sampler_increment = 16;  // one S#

enum class SlotKind : std::uint8_t { empty = 0, srv, uav, cbv, sampler };
const char* slot_kind_name(SlotKind kind);

struct Slot {
    SlotKind kind = SlotKind::empty;
    std::uint32_t generation = 0;      // incremented on every write; identifies the descriptor's contents
    std::uint64_t cbv_address = 0;     // CBV: the title GPU address the title passed (BufferLocation)
    std::uint32_t cbv_size = 0;
};

// One wrapped heap. Owned by its wrapper; registered while it lives.
struct Heap {
    D3D12_DESCRIPTOR_HEAP_DESC desc{};         // as the title created it
    std::uint32_t serial = 0;                  // unique per heap in the process, never reused
    std::uint8_t* base = nullptr;              // title memory: the CPU (and GPU) handle of descriptor 0
    UINT increment = 0;                        // title-facing increment
    ID3D12Device* device = nullptr;            // desktop device
    D3D12_CPU_DESCRIPTOR_HANDLE shadow{};      // desktop handle of descriptor 0 in the shadow heap
    UINT desktop_increment = 0;
    std::vector<Slot> slots;
};

// Sets up `heap` (memory, slots, serial) for a desktop shadow heap and registers it. False when out of memory.
bool create(Heap& heap, ID3D12Device* device, const D3D12_DESCRIPTOR_HEAP_DESC& desc, ID3D12DescriptorHeap* shadow);
void destroy(Heap& heap);

// The title-facing increment of a heap type, or 0 for types the shim does not wrap (RTV, DSV).
UINT title_increment(D3D12_DESCRIPTOR_HEAP_TYPE type);

// Writes through the API. Each returns false when `handle` is not in a wrapped heap (the caller forwards it to the
// desktop device unchanged). `translated` is the desktop view description (title addresses already translated).
bool write_cbv(std::uint64_t handle, const D3D12_CONSTANT_BUFFER_VIEW_DESC* title,
               const D3D12_CONSTANT_BUFFER_VIEW_DESC* translated);
bool write_srv(std::uint64_t handle, ID3D12Resource* resource, const D3D12_SHADER_RESOURCE_VIEW_DESC* desc);
bool write_uav(std::uint64_t handle, ID3D12Resource* resource, ID3D12Resource* counter,
               const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc);
bool write_sampler(std::uint64_t handle, const D3D12_SAMPLER_DESC* desc);

// Whether a handle lies in a wrapped heap.
bool is_title_handle(std::uint64_t handle);

// Copies `count` descriptors between handles. Returns false when neither range is in a wrapped heap (forward), true
// when copied or when refused (a copy between a wrapped and a desktop heap, or a range past its heap: logged).
bool copy(UINT count, std::uint64_t dst, std::uint64_t src, D3D12_DESCRIPTOR_HEAP_TYPE type);

// A descriptor a draw reads: table handle (the title's GPU handle) + byte offset. `kind` is what the shader expects.
// found: an API-written descriptor of that kind (its marker words, possibly copied by the title). raw: hardware
// words the title wrote (`words`; 8 for a CBV/SRV/UAV slot, 4 for a sampler), for the caller to decode.
struct Resolved {
    bool found = false;
    bool raw = false;
    const char* why = nullptr;              // when neither found nor raw
    std::uint32_t serial = 0, index = 0, generation = 0;
    D3D12_CPU_DESCRIPTOR_HANDLE shadow{};   // the desktop descriptor (srv, sampler)
    std::uint64_t cbv_address = 0;          // cbv
    std::uint32_t words[8] = {};            // raw
};
// `bound_serial` is the serial of the heap of this type the title bound on the list (0 for none): D3D12 requires a
// table to point into it.
Resolved resolve(std::uint64_t table, std::uint32_t offset, SlotKind kind, std::uint32_t bound_serial);
// The four words of a buffer V# at a 16-byte aligned table offset of a CBV/SRV/UAV table (half a descriptor slot: a
// console packs V#s 16 bytes apart). raw is set when they are hardware words; a slot holding an API-written view
// (its marker) or zeros is not raw, with the reason in `why`.
Resolved resolve_buffer_words(std::uint64_t table, std::uint32_t offset, std::uint32_t bound_serial);

}  // namespace descriptors
}  // namespace d3d12_xs
