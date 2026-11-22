// Title descriptor heaps of the graphics shim (d3d12_xs_descriptors.h).
//
// No dynamic initializers or TLS (as the rest of the shim): the registry is a constant-initialized lock and a
// pointer to a vector created on the first registration.
#include "d3d12_xs_descriptors.h"
#include "d3d12_xs_wrap.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
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
        // Copy through a temporary so overlapping ranges in one heap behave as the desktop copy.
        std::vector<Slot> moved(s->slots.begin() + si, s->slots.begin() + si + count);
        for (UINT i = 0; i < count; ++i) {
            Slot& slot = d->slots[di + i];
            const std::uint32_t generation = slot.generation + 1;
            slot = moved[i];
            slot.generation = generation;
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
        const Slot& slot = heap->slots[index];
        out.serial = heap->serial;
        out.index = index;
        out.generation = slot.generation;
        if (slot.kind != kind) {
            out.why = slot.kind == SlotKind::empty ? "no view was created at the descriptor"
                                                   : "the descriptor holds another kind of view";
        } else {
            out.found = true;
            out.shadow = shadow_at(*heap, index);
            out.cbv_address = slot.cbv_address;
        }
    }
    ReleaseSRWLockShared(&g_lock);
    return out;
}

}  // namespace descriptors
}  // namespace d3d12_xs
