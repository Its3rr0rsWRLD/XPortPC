// Title descriptor heaps of the graphics shim (d3d12_xs_descriptors.h).
//
// No dynamic initializers or TLS (as the rest of the shim): the registry is a constant-initialized lock and a
// pointer to a vector created on the first registration.
#include "d3d12_xs_descriptors.h"
#include "d3d12_xs_pipeline.h"
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

// A buffer view's V# (d3d12_xs_descriptors.h, Buffer views).
struct Encoded {
    BufferForm form = BufferForm::none;
    std::uint32_t words[4] = {};
    const char* why = nullptr;
};

Encoded unencoded(const char* why)
{
    Encoded out;
    out.form = BufferForm::unencoded;
    out.why = why;
    return out;
}

constexpr std::uint32_t fmt_32_uint = 20, fmt_32_sint = 21, fmt_32_float = 22;

Encoded encode_buffer(ID3D12Resource* resource, DXGI_FORMAT format, UINT64 first, UINT count, UINT structure,
                      bool raw, bool default_mapping)
{
    std::uint64_t element = 0, records = 0;
    std::uint32_t stride = 0, oob = 0, fmt = fmt_32_float;
    BufferForm form;
    if (raw) {
        if (format != DXGI_FORMAT_R32_TYPELESS) return unencoded("a raw buffer view whose format is not R32_TYPELESS");
        element = 4;
        records = std::uint64_t(count) * 4;
        oob = 3;
        form = BufferForm::raw;
    } else if (structure) {
        if (structure >= 0x4000) return unencoded("a structure stride past the V#'s 14-bit stride field");
        element = structure;
        records = count;
        stride = structure;
        form = BufferForm::structured;
    } else {
        element = format_bytes(format);
        if (!element) return unencoded("a typed buffer view of a format the shim does not encode");
        records = count;
        stride = static_cast<std::uint32_t>(element);
        const bool integer = format == DXGI_FORMAT_R32_UINT || format == DXGI_FORMAT_R32_SINT;
        if (integer) fmt = format == DXGI_FORMAT_R32_UINT ? fmt_32_uint : fmt_32_sint;
        form = integer && default_mapping ? BufferForm::typed_int : BufferForm::typed_other;
    }
    if (records > 0xffffffffull) return unencoded("a buffer view past the V#'s 32-bit num_records");
    if (!resource) return unencoded("a buffer view without a resource");
    const std::uint64_t bytes = std::uint64_t(count) * element;
    const std::uint64_t title = pipeline::title_address_of(resource, first * element, bytes ? bytes : 1);
    if (!title) return unencoded("the view's resource is not in title memory, so it has no title GPU address");
    if (title >> 48) return unencoded("a title GPU address past the V#'s 48-bit base");
    Encoded out;
    out.form = form;
    out.words[0] = static_cast<std::uint32_t>(title);
    out.words[1] = static_cast<std::uint32_t>(title >> 32) | stride << 16;
    out.words[2] = static_cast<std::uint32_t>(records);
    out.words[3] = 4u | 5u << 3 | 6u << 6 | 7u << 9 | fmt << 12 | 1u << 24 | oob << 28;
    return out;
}

Encoded encode_srv(ID3D12Resource* resource, const D3D12_SHADER_RESOURCE_VIEW_DESC* desc)
{
    if (!desc || desc->ViewDimension != D3D12_SRV_DIMENSION_BUFFER) return {};
    return encode_buffer(resource, desc->Format, desc->Buffer.FirstElement, desc->Buffer.NumElements,
                         desc->Buffer.StructureByteStride, (desc->Buffer.Flags & D3D12_BUFFER_SRV_FLAG_RAW) != 0,
                         desc->Shader4ComponentMapping == D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING);
}

Encoded encode_uav(ID3D12Resource* resource, ID3D12Resource* counter, const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc)
{
    if (!desc || desc->ViewDimension != D3D12_UAV_DIMENSION_BUFFER) return {};
    if (counter) return unencoded("a UAV with a counter resource (UAV counters are not translated)");
    return encode_buffer(resource, desc->Format, desc->Buffer.FirstElement, desc->Buffer.NumElements,
                         desc->Buffer.StructureByteStride, (desc->Buffer.Flags & D3D12_BUFFER_UAV_FLAG_RAW) != 0, true);
}

}  // namespace

UINT format_bytes(DXGI_FORMAT format)
{
    switch (format) {
    case DXGI_FORMAT_R32G32B32A32_FLOAT: case DXGI_FORMAT_R32G32B32A32_UINT: case DXGI_FORMAT_R32G32B32A32_SINT:
        return 16;
    case DXGI_FORMAT_R32G32B32_FLOAT: case DXGI_FORMAT_R32G32B32_UINT: case DXGI_FORMAT_R32G32B32_SINT:
        return 12;
    case DXGI_FORMAT_R32G32_FLOAT: case DXGI_FORMAT_R32G32_UINT: case DXGI_FORMAT_R32G32_SINT:
    case DXGI_FORMAT_R16G16B16A16_FLOAT: case DXGI_FORMAT_R16G16B16A16_UNORM: case DXGI_FORMAT_R16G16B16A16_UINT:
    case DXGI_FORMAT_R16G16B16A16_SNORM: case DXGI_FORMAT_R16G16B16A16_SINT:
        return 8;
    case DXGI_FORMAT_R32_FLOAT: case DXGI_FORMAT_R32_UINT: case DXGI_FORMAT_R32_SINT:
    case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UINT: case DXGI_FORMAT_R8G8B8A8_SNORM:
    case DXGI_FORMAT_R8G8B8A8_SINT: case DXGI_FORMAT_R16G16_FLOAT: case DXGI_FORMAT_R16G16_UNORM:
    case DXGI_FORMAT_R16G16_UINT: case DXGI_FORMAT_R16G16_SNORM: case DXGI_FORMAT_R16G16_SINT:
    case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_R10G10B10A2_UINT: case DXGI_FORMAT_R11G11B10_FLOAT:
        return 4;
    case DXGI_FORMAT_R16_FLOAT: case DXGI_FORMAT_R16_UNORM: case DXGI_FORMAT_R16_UINT: case DXGI_FORMAT_R16_SNORM:
    case DXGI_FORMAT_R16_SINT: case DXGI_FORMAT_R8G8_UNORM: case DXGI_FORMAT_R8G8_UINT: case DXGI_FORMAT_R8G8_SNORM:
    case DXGI_FORMAT_R8G8_SINT:
        return 2;
    case DXGI_FORMAT_R8_UNORM: case DXGI_FORMAT_R8_UINT: case DXGI_FORMAT_R8_SNORM: case DXGI_FORMAT_R8_SINT:
        return 1;
    default:
        return 0;
    }
}

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

// The descriptor's bytes in the heap's title memory: a buffer view's V# words, zeros for anything else.
void write_words(Heap& heap, std::uint32_t index, const Slot& slot)
{
    std::uint8_t* at = heap.base + std::size_t(index) * heap.increment;
    std::memset(at, 0, heap.increment);
    if (slot.buffer != BufferForm::none && slot.buffer != BufferForm::unencoded)
        std::memcpy(at, slot.vsharp, sizeof(slot.vsharp));
}

void end_write(Heap& heap, std::uint32_t index, SlotKind kind, std::uint64_t address = 0, std::uint32_t size = 0,
               const Encoded& buffer = Encoded())
{
    Slot& slot = heap.slots[index];
    slot.kind = kind;
    ++slot.generation;
    slot.cbv_address = address;
    slot.cbv_size = size;
    slot.buffer = buffer.form;
    std::memcpy(slot.vsharp, buffer.words, sizeof(slot.vsharp));
    slot.buffer_why = buffer.why;
    write_words(heap, index, slot);
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
    // The V# needs the title-memory registry, which takes its own lock: encode outside ours.
    ReleaseSRWLockExclusive(&g_lock);
    const Encoded buffer = encode_srv(resource, desc);
    AcquireSRWLockExclusive(&g_lock);
    if (!(heap = locate(handle, &index))) {
        ReleaseSRWLockExclusive(&g_lock);
        return true;  // the heap went away meanwhile
    }
    end_write(*heap, index, SlotKind::srv, 0, 0, buffer);
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
    ReleaseSRWLockExclusive(&g_lock);
    const Encoded buffer = encode_uav(resource, counter, desc);
    AcquireSRWLockExclusive(&g_lock);
    if (!(heap = locate(handle, &index))) {
        ReleaseSRWLockExclusive(&g_lock);
        return true;
    }
    end_write(*heap, index, SlotKind::uav, 0, 0, buffer);
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
            write_words(*d, di + i, slot);
        }
    }
    ReleaseSRWLockExclusive(&g_lock);
    if (why) note(symbol, why);
    return true;
}

Resolved resolve(std::uint64_t table, std::uint32_t offset, SlotKind kind, std::uint32_t bound_serial, bool buffer)
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
        out.kind = slot.kind;
        out.buffer = slot.buffer;
        if (buffer) {
            if (slot.kind != SlotKind::srv && slot.kind != SlotKind::uav) {
                out.why = slot.kind == SlotKind::empty ? "no view was created at the descriptor"
                                                       : "the descriptor holds a view that is not a buffer SRV or UAV";
            } else if (slot.buffer == BufferForm::none) {
                out.why = "the descriptor holds a view that is not a buffer view";
            } else if (slot.buffer == BufferForm::unencoded) {
                out.why = slot.buffer_why;
            } else if (kind == SlotKind::uav && slot.kind != SlotKind::uav) {
                out.why = "a store through a buffer SRV (a store needs a UAV)";
            } else {
                out.found = true;
                std::memcpy(out.vsharp, slot.vsharp, sizeof(out.vsharp));
            }
        } else if (slot.kind != kind) {
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
