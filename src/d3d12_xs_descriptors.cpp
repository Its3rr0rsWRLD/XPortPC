// Title descriptor heaps of the graphics shim (d3d12_xs_descriptors.h).
//
// No dynamic initializers or TLS (as the rest of the shim): the registry is a constant-initialized lock and a
// pointer to a vector created on the first registration.
#include "d3d12_xs_descriptors.h"
#include "d3d12_xs_wrap.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <new>

namespace d3d12_xs {
namespace descriptors {
namespace {

SRWLOCK g_lock = SRWLOCK_INIT;
std::vector<Heap*>* g_heaps;  // sorted by base
std::atomic<std::uint32_t> g_serial;

std::uint64_t span(const Heap& heap) { return std::uint64_t(heap.desc.NumDescriptors) * heap.increment; }

// The heap and index of a handle, under the lock. Null when the handle is in no wrapped heap or not on a descriptor
// boundary (then `misaligned` is set).
Heap* locate(std::uint64_t handle, std::uint32_t* index, bool* misaligned = nullptr)
{
    if (misaligned) *misaligned = false;
    if (!g_heaps || !handle) return nullptr;
    auto it = std::upper_bound(g_heaps->begin(), g_heaps->end(), handle,
                               [](std::uint64_t h, const Heap* heap) { return h < reinterpret_cast<std::uintptr_t>(heap->base); });
    if (it == g_heaps->begin()) return nullptr;
    Heap* heap = *(it - 1);
    const std::uint64_t at = handle - reinterpret_cast<std::uintptr_t>(heap->base);
    if (at >= span(*heap)) return nullptr;
    if (at % heap->increment) {
        if (misaligned) *misaligned = true;
        return nullptr;
    }
    *index = static_cast<std::uint32_t>(at / heap->increment);
    return heap;
}

D3D12_CPU_DESCRIPTOR_HANDLE shadow_at(const Heap& heap, std::uint32_t index)
{
    D3D12_CPU_DESCRIPTOR_HANDLE h = heap.shadow;
    h.ptr += static_cast<SIZE_T>(index) * heap.desktop_increment;
    return h;
}

void note(const char* symbol, const char* detail) { log_note(symbol, detail, nullptr); }

std::uint32_t* title_words(const Heap& heap, std::uint32_t index)
{
    return reinterpret_cast<std::uint32_t*>(heap.base + std::size_t(index) * heap.increment);
}

// Marker words of an API-written slot. CBV/SRV/UAV (32 bytes): "X2WD", serial, index, then word 3 with TYPE (bits
// 31:28) 4: SQ_RSRC_IMG_RSVD_4 for a T#, and bits 31:30 = 1 (SQ_RSRC_BUF_RSVD_1) for a V#, so the words are no valid
// hardware descriptor; the generation is in its low 28 bits, and words 4-7 are the complements of words 0-3.
// Sampler (16 bytes): an S# has no type field, so "X2WS", serial, index and a check word of them and the generation;
// a title S# with exactly these words would be taken for the marker.
constexpr std::uint32_t view_marker = 0x44573258u;     // "X2WD"
constexpr std::uint32_t sampler_marker = 0x53573258u;  // "X2WS"
std::uint32_t sampler_check(std::uint32_t serial, std::uint32_t index, std::uint32_t generation)
{
    return (generation ^ (serial * 0x9e3779b1u) ^ (index * 0x85ebca6bu)) | 1u;
}

void write_marker(const Heap& heap, std::uint32_t index)
{
    std::uint32_t* w = title_words(heap, index);
    const std::uint32_t generation = heap.slots[index].generation;
    if (heap.increment == view_increment) {
        w[0] = view_marker;
        w[1] = heap.serial;
        w[2] = index;
        w[3] = 0x40000000u | (generation & 0x0fffffffu);
        for (int i = 0; i < 4; ++i) w[4 + i] = ~w[i];
    } else {
        w[0] = sampler_marker;
        w[1] = heap.serial;
        w[2] = index;
        w[3] = sampler_check(heap.serial, index, generation);
    }
}

// The slot `words` name, if they are marker words: (serial, index, generation bits).
bool parse_marker(const std::uint32_t* w, UINT increment, std::uint32_t* serial, std::uint32_t* index,
                  std::uint32_t* generation)
{
    if (increment == view_increment) {
        if (w[0] != view_marker || (w[3] & 0xf0000000u) != 0x40000000u) return false;
        for (int i = 0; i < 4; ++i)
            if (w[4 + i] != ~w[i]) return false;
        *generation = w[3] & 0x0fffffffu;
    } else {
        if (w[0] != sampler_marker) return false;
        *generation = 0;  // checked against the slot below
    }
    *serial = w[1];
    *index = w[2];
    return true;
}

Heap* by_serial(std::uint32_t serial)
{
    if (!g_heaps) return nullptr;
    for (Heap* heap : *g_heaps)
        if (heap->serial == serial) return heap;
    return nullptr;
}

}  // namespace

const char* slot_kind_name(SlotKind kind)
{
    switch (kind) {
    case SlotKind::srv: return "SRV";
    case SlotKind::uav: return "UAV";
    case SlotKind::cbv: return "CBV";
    case SlotKind::sampler: return "sampler";
    default: return "no view";
    }
}

UINT title_increment(D3D12_DESCRIPTOR_HEAP_TYPE type)
{
    return type == D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV ? view_increment
           : type == D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER   ? sampler_increment
                                                          : 0;
}

bool create(Heap& heap, ID3D12Device* device, const D3D12_DESCRIPTOR_HEAP_DESC& desc, ID3D12DescriptorHeap* shadow)
{
    heap.desc = desc;
    heap.increment = title_increment(desc.Type);
    heap.device = device;
    heap.shadow = shadow->GetCPUDescriptorHandleForHeapStart();
    heap.desktop_increment = device->GetDescriptorHandleIncrementSize(desc.Type);
    try {
        heap.slots.resize(desc.NumDescriptors);
    } catch (...) {
        return false;
    }
    const SIZE_T bytes = static_cast<SIZE_T>(span(heap));
    heap.base = static_cast<std::uint8_t*>(VirtualAlloc(nullptr, bytes ? bytes : 1, MEM_RESERVE | MEM_COMMIT,
                                                        PAGE_READWRITE));
    if (!heap.base) return false;
    heap.serial = g_serial.fetch_add(1) + 1;
    AcquireSRWLockExclusive(&g_lock);
    bool good = true;
    if (!g_heaps) g_heaps = new (std::nothrow) std::vector<Heap*>();
    if (g_heaps) {
        try {
            g_heaps->insert(std::upper_bound(g_heaps->begin(), g_heaps->end(), &heap,
                                             [](const Heap* a, const Heap* b) { return a->base < b->base; }),
                            &heap);
        } catch (...) {
            good = false;
        }
    } else {
        good = false;
    }
    ReleaseSRWLockExclusive(&g_lock);
    if (!good) {
        VirtualFree(heap.base, 0, MEM_RELEASE);
        heap.base = nullptr;
    }
    return good;
}

void destroy(Heap& heap)
{
    if (!heap.base) return;
    AcquireSRWLockExclusive(&g_lock);
    if (g_heaps) g_heaps->erase(std::remove(g_heaps->begin(), g_heaps->end(), &heap), g_heaps->end());
    ReleaseSRWLockExclusive(&g_lock);
    VirtualFree(heap.base, 0, MEM_RELEASE);
    heap.base = nullptr;
}

bool is_title_handle(std::uint64_t handle)
{
    AcquireSRWLockShared(&g_lock);
    std::uint32_t index;
    bool misaligned;
    const bool found = locate(handle, &index, &misaligned) || misaligned;
    ReleaseSRWLockShared(&g_lock);
    return found;
}

namespace {

// Common part of the view writes: the slot of `handle` in a heap of `type`, under the exclusive lock (held on
// return when found). Logs and returns true with *slot null for a handle in a heap of another type.
Heap* begin_write(std::uint64_t handle, D3D12_DESCRIPTOR_HEAP_TYPE type, const char* symbol, std::uint32_t* index,
                  bool* refused)
{
    *refused = false;
    AcquireSRWLockExclusive(&g_lock);
    bool misaligned = false;
    Heap* heap = locate(handle, index, &misaligned);
    if (heap && heap->desc.Type == type) return heap;
    ReleaseSRWLockExclusive(&g_lock);
    if (heap || misaligned) {
        note(symbol, heap ? "descriptor handle in a heap of another type; not written"
                          : "descriptor handle between two descriptors of a title heap; not written");
        *refused = true;
    }
    return nullptr;
}

void end_write(Heap& heap, std::uint32_t index, SlotKind kind, std::uint64_t address = 0, std::uint32_t size = 0)
{
    Slot& slot = heap.slots[index];
    slot.kind = kind;
    ++slot.generation;
    slot.cbv_address = address;
    slot.cbv_size = size;
    write_marker(heap, index);
    ReleaseSRWLockExclusive(&g_lock);
}

}  // namespace

bool write_cbv(std::uint64_t handle, const D3D12_CONSTANT_BUFFER_VIEW_DESC* title,
               const D3D12_CONSTANT_BUFFER_VIEW_DESC* translated)
{
    std::uint32_t index;
    bool refused;
    Heap* heap = begin_write(handle, D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,
                             "d3d12_xs!ID3D12Device::CreateConstantBufferView", &index, &refused);
    if (!heap) return refused;
    heap->device->CreateConstantBufferView(translated, shadow_at(*heap, index));
    end_write(*heap, index, SlotKind::cbv, title ? title->BufferLocation : 0, title ? title->SizeInBytes : 0);
    return true;
}

bool write_srv(std::uint64_t handle, ID3D12Resource* resource, const D3D12_SHADER_RESOURCE_VIEW_DESC* desc)
{
    std::uint32_t index;
    bool refused;
    Heap* heap = begin_write(handle, D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,
                             "d3d12_xs!ID3D12Device::CreateShaderResourceView", &index, &refused);
    if (!heap) return refused;
    heap->device->CreateShaderResourceView(resource, desc, shadow_at(*heap, index));
    end_write(*heap, index, SlotKind::srv);
    return true;
}

bool write_uav(std::uint64_t handle, ID3D12Resource* resource, ID3D12Resource* counter,
               const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc)
{
    std::uint32_t index;
    bool refused;
    Heap* heap = begin_write(handle, D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV,
                             "d3d12_xs!ID3D12Device::CreateUnorderedAccessView", &index, &refused);
    if (!heap) return refused;
    heap->device->CreateUnorderedAccessView(resource, counter, desc, shadow_at(*heap, index));
    end_write(*heap, index, SlotKind::uav);
    return true;
}

bool write_sampler(std::uint64_t handle, const D3D12_SAMPLER_DESC* desc)
{
    std::uint32_t index;
    bool refused;
    Heap* heap = begin_write(handle, D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER, "d3d12_xs!ID3D12Device::CreateSampler",
                             &index, &refused);
    if (!heap) return refused;
    heap->device->CreateSampler(desc, shadow_at(*heap, index));
    end_write(*heap, index, SlotKind::sampler);
    return true;
}

bool copy(UINT count, std::uint64_t dst, std::uint64_t src, D3D12_DESCRIPTOR_HEAP_TYPE type)
{
    const char* symbol = "d3d12_xs!ID3D12Device::CopyDescriptors";
    AcquireSRWLockExclusive(&g_lock);
    std::uint32_t di = 0, si = 0;
    bool dst_off = false, src_off = false;
    Heap* d = locate(dst, &di, &dst_off);
    Heap* s = locate(src, &si, &src_off);
    if (!d && !s && !dst_off && !src_off) {
        ReleaseSRWLockExclusive(&g_lock);
        return false;
    }
    const char* why = nullptr;
    if (!d || !s) {
        why = "a copy between a title heap and a desktop heap (or between descriptors) is not translated; not copied";
    } else if (d->desc.Type != type || s->desc.Type != type) {
        why = "heap type does not match the copy's type; not copied";
    } else if (std::uint64_t(di) + count > d->desc.NumDescriptors || std::uint64_t(si) + count > s->desc.NumDescriptors) {
        why = "copy range past the end of a title heap; not copied";
    }
    if (!why && count) {
        d->device->CopyDescriptorsSimple(count, shadow_at(*d, di), shadow_at(*s, si), type);
        // Copy through temporaries so overlapping ranges in one heap behave as the desktop copy. A source whose
        // memory holds its own marker is an API-written view: the destination gets the view and its own marker. Any
        // other source words (hardware words, a marker copied from elsewhere, zeros) are copied as they are.
        std::vector<Slot> moved(s->slots.begin() + si, s->slots.begin() + si + count);
        std::vector<std::uint8_t> bytes(std::size_t(count) * s->increment);
        std::memcpy(bytes.data(), title_words(*s, si), bytes.size());
        std::vector<bool> own(count);
        for (UINT i = 0; i < count; ++i) {
            std::uint32_t serial = 0, index = 0, generation = 0;
            const auto* w = reinterpret_cast<const std::uint32_t*>(bytes.data() + std::size_t(i) * s->increment);
            own[i] = moved[i].kind != SlotKind::empty && parse_marker(w, s->increment, &serial, &index, &generation) &&
                     serial == s->serial && index == si + i;
        }
        for (UINT i = 0; i < count; ++i) {
            Slot& slot = d->slots[di + i];
            const std::uint32_t generation = slot.generation + 1;
            slot = own[i] ? moved[i] : Slot{};
            slot.generation = generation;
            if (own[i]) write_marker(*d, di + i);
            else std::memcpy(title_words(*d, di + i), bytes.data() + std::size_t(i) * s->increment, s->increment);
        }
    }
    ReleaseSRWLockExclusive(&g_lock);
    if (why) note(symbol, why);
    return true;
}

Resolved resolve(std::uint64_t table, std::uint32_t offset, SlotKind kind, std::uint32_t bound_serial)
{
    Resolved out;
    AcquireSRWLockShared(&g_lock);
    std::uint32_t first = 0;
    bool misaligned = false;
    Heap* heap = table ? locate(table, &first, &misaligned) : nullptr;
    const D3D12_DESCRIPTOR_HEAP_TYPE type =
        kind == SlotKind::sampler ? D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER : D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    if (!table) {
        out.why = "descriptor table not set";
    } else if (!heap) {
        out.why = misaligned ? "descriptor table handle between two descriptors" : "descriptor table not in a title heap";
    } else if (heap->desc.Type != type) {
        out.why = "descriptor table in a heap of the wrong type";
    } else if (!(heap->desc.Flags & D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE)) {
        out.why = "descriptor table in a heap that is not shader visible";
    } else if (heap->serial != bound_serial) {
        out.why = "descriptor table in a heap the list has not bound with SetDescriptorHeaps";
    } else if (offset % heap->increment || std::uint64_t(first) + offset / heap->increment >= heap->desc.NumDescriptors) {
        out.why = "descriptor past the end of its heap";
    } else {
        const std::uint32_t index = first + offset / heap->increment;
        out.serial = heap->serial;
        out.index = index;
        out.generation = heap->slots[index].generation;
        // The words in title memory decide (header comment): a marker, hardware words or nothing.
        const std::uint32_t* w = title_words(*heap, index);
        const unsigned count = heap->increment / 4;
        std::uint32_t serial = 0, at = 0, generation = 0;
        bool any = false;
        for (unsigned i = 0; i < count; ++i) any = any || w[i];
        if (!any) {
            out.why = heap->slots[index].kind == SlotKind::empty ? "no view was created at the descriptor"
                                                                 : "the descriptor's memory was cleared";
        } else if (parse_marker(w, heap->increment, &serial, &at, &generation)) {
            const Heap* source = by_serial(serial);
            const Slot* slot = source && source->desc.Type == heap->desc.Type && at < source->slots.size()
                                   ? &source->slots[at] : nullptr;
            const bool current = slot && (heap->increment == view_increment
                                              ? (slot->generation & 0x0fffffffu) == generation
                                              : w[3] == sampler_check(serial, at, slot->generation));
            if (!current) {
                out.why = "the descriptor's words were copied from a view that has since been rewritten or destroyed";
            } else if (slot->kind != kind) {
                out.why = "the descriptor holds another kind of view";
            } else {
                out.found = true;
                out.serial = serial;
                out.index = at;
                out.generation = slot->generation;
                out.shadow = shadow_at(*source, at);
                out.cbv_address = slot->cbv_address;
            }
        } else {
            out.raw = true;
            for (unsigned i = 0; i < count; ++i) out.words[i] = w[i];
        }
    }
    ReleaseSRWLockShared(&g_lock);
    return out;
}

Resolved resolve_buffer_words(std::uint64_t table, std::uint32_t offset, std::uint32_t bound_serial)
{
    // The containing slot decides as resolve() does; the V# is the half of it at the offset.
    const std::uint32_t slot_offset = offset - offset % view_increment;
    Resolved out = resolve(table, slot_offset, SlotKind::uav, bound_serial);
    if (offset % 16) {
        out = Resolved{};
        out.why = "a V# at a table offset that is not a multiple of 16";
        return out;
    }
    if (out.found) {
        out.found = false;
        out.why = "an API-written view where the program reads V# words (the shim has no hardware words for it)";
    } else if (out.raw) {
        if (offset != slot_offset) std::memmove(out.words, out.words + 4, 16);
        std::memset(out.words + 4, 0, 16);
        bool any = false;
        for (int i = 0; i < 4; ++i) any = any || out.words[i];
        if (!any) {
            out.raw = false;
            out.why = "no V# at the descriptor (zero words)";
        }
    } else if (out.why && !std::strcmp(out.why, "the descriptor holds another kind of view")) {
        out.why = "an API-written view where the program reads V# words (the shim has no hardware words for it)";
    }
    return out;
}

}  // namespace descriptors
}  // namespace d3d12_xs
