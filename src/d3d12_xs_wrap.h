#pragma once

// Wrapper objects of the d3d12_xs.dll graphics shim: console-facing objects over desktop D3D12/DXGI.
// Translation only: every implemented method forwards to the desktop object, unwrapping arguments
// that are wrappers. Each wrapper uses the public desktop method order of the interface it names,
// and its vtable continues past the public methods with logging thunks (d3d12_xs_log.cpp), so a
// title calling a slot we do not implement gets E_NOTIMPL and one log line with the slot index.
//
// Wrapped: ID3D12Device, ID3D12CommandQueue, ID3D12CommandAllocator, ID3D12GraphicsCommandList,
// ID3D12Fence1, IDXGISwapChain3 and CBV/SRV/UAV and sampler ID3D12DescriptorHeaps (d3d12_xs_descriptors.h).
// Everything else a wrapped method returns (resources, heaps, RTV and DSV heaps, pipeline state, root
// signatures, query heaps) is the desktop object itself.

#include <d3d12.h>
#include <dxgi1_4.h>

#include <cstdint>

namespace d3d12_xs {

enum class Kind : unsigned { device, queue, allocator, list, fence, swap_chain, descriptor_heap, count };

// Public desktop method count of each wrapped interface (IUnknown included), from d3d12.h/dxgi1_4.h.
constexpr unsigned public_slots(Kind kind)
{
    switch (kind) {
    case Kind::device: return 44;      // ID3D12Device
    case Kind::queue: return 19;       // ID3D12CommandQueue
    case Kind::allocator: return 9;    // ID3D12CommandAllocator
    case Kind::list: return 60;        // ID3D12GraphicsCommandList
    case Kind::fence: return 12;       // ID3D12Fence1
    case Kind::swap_chain: return 40;  // IDXGISwapChain3
    case Kind::descriptor_heap: return 11;  // ID3D12DescriptorHeap
    default: return 0;
    }
}
const char* interface_name(Kind kind);

// Every wrapper's vtable has this many entries; slots past public_slots are logging thunks.
constexpr unsigned vtable_slots = 256;

// Installs the extended vtable on a freshly constructed wrapper. `object` points at the wrapper's
// interface base (offset 0 of the object); its current vptr is the compiler's vtable for the class.
void install_vtable(void* object, Kind kind);
// The wrapper kind of `object`, or false when it is not a wrapper of this shim.
bool wrapper_kind(const void* object, Kind* kind);

// Logging (d3d12_xs_log.cpp).
void log_first_use(Kind kind, const char* method, const void* caller);
void log_unknown_iid(Kind kind, REFIID riid, const void* caller);
void log_note(const char* symbol, const char* detail, const GUID* iid);
std::uintptr_t log_unknown_slot(void* self, unsigned slot, const void* caller, std::uintptr_t a1,
                                std::uintptr_t a2, std::uintptr_t a3);
// A refused pipeline (draw=false) or draw (draw=true): counted, and reported as X2W_GFX_EVENT_REFUSED.
void log_refused(const char* symbol, const char* detail, bool draw);
void count_shader(bool cached);
void count_texture_miss();
// Hardware descriptor words resolved (reads), desktop textures filled from them (uploads), samplers created.
void count_raw(unsigned reads, unsigned uploads, unsigned samplers);
void count_object(int delta);
void count_device();
void count_present();
void set_title_gpu(int state, HRESULT hr);

// Wrapping entry points (d3d12_xs_wrap.cpp). wrap_device takes over one reference to `real`;
// `caller` is the title's return address, used when riid is logged as unknown.
HRESULT wrap_device(ID3D12Device* real, REFIID riid, void** out, const void* caller);
HRESULT create_swap_chain_for_hwnd(IUnknown* queue, HWND window, const DXGI_SWAP_CHAIN_DESC1* desc,
                                   const DXGI_SWAP_CHAIN_FULLSCREEN_DESC* fullscreen_desc,
                                   IDXGIOutput* restrict_to_output, REFIID riid, void** out, const void* caller);

}  // namespace d3d12_xs

#if defined(_MSC_VER) && !defined(__clang__)
#include <intrin.h>
#define X2W_RETURN_ADDRESS() _ReturnAddress()
#else
#define X2W_RETURN_ADDRESS() __builtin_return_address(0)
#endif
