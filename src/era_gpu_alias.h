#pragma once

#include <cstdint>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <d3d12.h>
#include <wrl/client.h>

// Desktop GPU access to title memory without copies.
// On the console the GPU reads and writes a graphics allocation at the title's own CPU address.
// On desktop D3D12, ID3D12Device3::OpenExistingHeapFromAddress turns an existing VirtualAlloc
// allocation (such as an xmem graphics allocation from era_heap) into a heap. One buffer placed
// over it gives the same bytes a desktop GPU virtual address. CPU writes through the title
// pointer are seen by the GPU and GPU writes are seen through the title pointer once the GPU
// work has completed. The heap is system memory, so GPU access goes over the bus.
namespace era_gpu_alias {
struct Alias {
    Microsoft::WRL::ComPtr<ID3D12Heap> heap;
    // Spans the first `size` bytes of the allocation, created in D3D12_RESOURCE_STATE_COMMON
    // with unordered access allowed. Its GPU virtual address corresponds to the base pointer.
    Microsoft::WRL::ComPtr<ID3D12Resource> buffer;
    std::uint64_t size = 0;
};

// base must be the start of an allocation committed throughout, as returned by VirtualAlloc, and the
// allocation must cover size bytes. Opening the heap locks every page of the allocation in memory
// (measured with tests/xmem_alias_probe.cpp: the working set grows by the allocation's size). Returns
// E_INVALIDARG without calling D3D12 when base is not the start of an allocation or any part of it
// is not committed, E_INVALIDARG for other bad arguments or a too-small
// allocation, E_NOTIMPL when the device does not support existing heaps, or the failing D3D12
// HRESULT.
HRESULT open(ID3D12Device* device, void* base, std::uint64_t size, Alias& alias) noexcept;

// The same for a file mapping (a pagefile-backed section, such as the title physical page pool): the heap is
// ID3D12Device3::OpenExistingHeapFromFileMapping of `section`, and the buffer spans its first `size` bytes, so
// buffer offset n is section offset n. Every view of the section shares the bytes. Returns E_INVALIDARG for a null
// section or size, E_NOTIMPL as above, or the failing D3D12 HRESULT.
HRESULT open_mapping(ID3D12Device* device, HANDLE section, std::uint64_t size, Alias& alias) noexcept;
}
