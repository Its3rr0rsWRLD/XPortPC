// Wrapper objects of the d3d12_xs.dll graphics shim (d3d12_xs_wrap.h).
//
// Each wrapper is a final class with single inheritance from the public desktop interface, so its
// compiler vtable is exactly the public method order; install_vtable then swaps in a copy that
// continues with logging thunks. No wrapper declares a virtual destructor or any virtual method
// beyond the interface. Methods forward to the desktop object and log their first use.
#include "d3d12_xs_wrap.h"
#include "d3d12_xs_api.h"

#include <d3d12sdklayers.h>
#include <dxgi1_4.h>
#include <wrl/client.h>

#include <atomic>
#include <cstdio>
#include <new>
#include <type_traits>
#include <vector>

using Microsoft::WRL::ComPtr;

namespace d3d12_xs {
namespace {

// First use of the enclosing wrapped method in this process. The flag is zero-initialized static
// storage, so no guard variable (and no TLS) is generated.
#define X2W_USE()                                                                    \
    do {                                                                             \
        static std::atomic<bool> x2w_seen_;                                          \
        if (!x2w_seen_.exchange(true, std::memory_order_relaxed))                    \
            log_first_use(kind, __func__, X2W_RETURN_ADDRESS());                     \
    } while (0)

IUnknown* real_of(const void* object);

// The desktop object behind a wrapper, or the pointer itself when it is a desktop object (for
// example a resource, which is not wrapped). COM single inheritance keeps the pointer valid as T.
template <class T>
T* unwrap(T* object)
{
    if (IUnknown* real = real_of(object)) return reinterpret_cast<T*>(real);
    return object;
}

template <class T>
bool unwrap_array(UINT count, T* const* in, std::vector<T*>& out)
{
    try {
        out.resize(count);
    } catch (...) {
        return false;
    }
    for (UINT i = 0; i < count; ++i) out[i] = unwrap(in[i]);
    return true;
}

template <class Derived, class Interface, Kind K>
class Wrapper : public Interface {
public:
    static constexpr Kind kind = K;

    explicit Wrapper(Interface* real) : real_(real) { count_object(1); }
    ~Wrapper()
    {
        if (real_) real_->Release();
        count_object(-1);
    }
    Interface* real() const { return real_; }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** out) override
    {
        return query(riid, out, X2W_RETURN_ADDRESS());
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs_; }
    ULONG STDMETHODCALLTYPE Release() override
    {
        const ULONG left = --refs_;
        if (!left) delete static_cast<Derived*>(this);
        return left;
    }

    HRESULT query(REFIID riid, void** out, const void* caller)
    {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (IsEqualIID(riid, __uuidof(IUnknown)) || Derived::implements(riid)) {
            AddRef();
            *out = static_cast<Interface*>(this);
            return S_OK;
        }
        HRESULT hr = E_NOINTERFACE;
        if (static_cast<Derived*>(this)->passthrough(riid, out, &hr)) return hr;
        log_unknown_iid(K, riid, caller);
        return E_NOINTERFACE;
    }
    bool passthrough(REFIID, void**, HRESULT*) { return false; }

protected:
    void install() { install_vtable(static_cast<Interface*>(this), K); }

    Interface* real_;
    std::atomic<ULONG> refs_{1};
};

// Hands a new wrapper to the caller through riid. Takes the creation reference.
template <class W>
HRESULT hand_out(W* wrapper, IUnknown* real, REFIID riid, void** out, const void* caller)
{
    if (!wrapper) {
        real->Release();
        return E_OUTOFMEMORY;
    }
    const HRESULT hr = wrapper->query(riid, out, caller);
    wrapper->Release();
    return hr;
}

// ID3D12Object methods (slots 3-6), forwarded.
#define X2W_D3D12_OBJECT_METHODS                                                                     \
    HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID guid, UINT* size, void* data) override          \
    {                                                                                                \
        X2W_USE();                                                                                   \
        return real_->GetPrivateData(guid, size, data);                                              \
    }                                                                                                \
    HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid, UINT size, const void* data) override     \
    {                                                                                                \
        X2W_USE();                                                                                   \
        return real_->SetPrivateData(guid, size, data);                                              \
    }                                                                                                \
    HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID guid, const IUnknown* data) override   \
    {                                                                                                \
        X2W_USE();                                                                                   \
        return real_->SetPrivateDataInterface(guid, data);                                           \
    }                                                                                                \
    HRESULT STDMETHODCALLTYPE SetName(LPCWSTR name) override                                         \
    {                                                                                                \
        X2W_USE();                                                                                   \
        return real_->SetName(name);                                                                 \
    }

class Device;
std::atomic<Device*> g_attached_device;
HRESULT device_query(Device* device, REFIID riid, void** out, const void* caller);

// ID3D12DeviceChild::GetDevice (slot 7): the wrapped device.
#define X2W_DEVICE_CHILD_METHODS                                                                     \
    HRESULT STDMETHODCALLTYPE GetDevice(REFIID riid, void** out) override                            \
    {                                                                                                \
        X2W_USE();                                                                                   \
        return device_query(device_, riid, out, X2W_RETURN_ADDRESS());                               \
    }

bool is_d3d12_child_iid(REFIID riid)
{
    return IsEqualIID(riid, __uuidof(ID3D12Object)) || IsEqualIID(riid, __uuidof(ID3D12DeviceChild));
}
bool is_pageable_iid(REFIID riid) { return is_d3d12_child_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12Pageable)); }

// Children keep their device alive, as desktop D3D12 objects do.
class DeviceRef {
public:
    explicit DeviceRef(Device* device);
    ~DeviceRef();
    Device* device_;
};

class Fence final : public Wrapper<Fence, ID3D12Fence1, Kind::fence>, DeviceRef {
public:
    Fence(ID3D12Fence* real, Device* device, D3D12_FENCE_FLAGS flags)
        : Wrapper(static_cast<ID3D12Fence1*>(real)), DeviceRef(device), flags_(flags)
    {
        install();
    }
    static bool implements(REFIID riid)
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12Fence)) ||
               IsEqualIID(riid, __uuidof(ID3D12Fence1));
    }
    ID3D12Fence* fence() const { return static_cast<ID3D12Fence*>(real_); }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
    UINT64 STDMETHODCALLTYPE GetCompletedValue() override
    {
        X2W_USE();
        return fence()->GetCompletedValue();
    }
    HRESULT STDMETHODCALLTYPE SetEventOnCompletion(UINT64 value, HANDLE event) override
    {
        X2W_USE();
        return fence()->SetEventOnCompletion(value, event);
    }
    HRESULT STDMETHODCALLTYPE Signal(UINT64 value) override
    {
        X2W_USE();
        return fence()->Signal(value);
    }
    // The desktop object is created as ID3D12Fence, so the flags it was created with are kept here
    // instead of requiring ID3D12Fence1 from the runtime.
    D3D12_FENCE_FLAGS STDMETHODCALLTYPE GetCreationFlags() override
    {
        X2W_USE();
        return flags_;
    }

private:
    D3D12_FENCE_FLAGS flags_;
};

class Allocator final : public Wrapper<Allocator, ID3D12CommandAllocator, Kind::allocator>, DeviceRef {
public:
    Allocator(ID3D12CommandAllocator* real, Device* device) : Wrapper(real), DeviceRef(device) { install(); }
    static bool implements(REFIID riid)
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12CommandAllocator));
    }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
    HRESULT STDMETHODCALLTYPE Reset() override
    {
        X2W_USE();
        return real_->Reset();
    }
};

class List final : public Wrapper<List, ID3D12GraphicsCommandList, Kind::list>, DeviceRef {
public:
    List(ID3D12GraphicsCommandList* real, Device* device) : Wrapper(real), DeviceRef(device) { install(); }
    static bool implements(REFIID riid)
    {
        return is_d3d12_child_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12CommandList)) ||
               IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList));
    }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
    D3D12_COMMAND_LIST_TYPE STDMETHODCALLTYPE GetType() override
    {
        X2W_USE();
        return real_->GetType();
    }
    HRESULT STDMETHODCALLTYPE Close() override
    {
        X2W_USE();
        return real_->Close();
    }
    HRESULT STDMETHODCALLTYPE Reset(ID3D12CommandAllocator* allocator, ID3D12PipelineState* state) override
    {
        X2W_USE();
        return real_->Reset(unwrap(allocator), state);
    }
    void STDMETHODCALLTYPE ClearState(ID3D12PipelineState* state) override
    {
        X2W_USE();
        real_->ClearState(state);
    }
    void STDMETHODCALLTYPE DrawInstanced(UINT vertices, UINT instances, UINT first_vertex, UINT first_instance) override
    {
        X2W_USE();
        real_->DrawInstanced(vertices, instances, first_vertex, first_instance);
    }
    void STDMETHODCALLTYPE DrawIndexedInstanced(UINT indices, UINT instances, UINT first_index, INT base_vertex,
                                                UINT first_instance) override
    {
        X2W_USE();
        real_->DrawIndexedInstanced(indices, instances, first_index, base_vertex, first_instance);
    }
    void STDMETHODCALLTYPE Dispatch(UINT x, UINT y, UINT z) override
    {
        X2W_USE();
        real_->Dispatch(x, y, z);
    }
    void STDMETHODCALLTYPE CopyBufferRegion(ID3D12Resource* dst, UINT64 dst_offset, ID3D12Resource* src,
                                            UINT64 src_offset, UINT64 bytes) override
    {
        X2W_USE();
        real_->CopyBufferRegion(dst, dst_offset, src, src_offset, bytes);
    }
    void STDMETHODCALLTYPE CopyTextureRegion(const D3D12_TEXTURE_COPY_LOCATION* dst, UINT x, UINT y, UINT z,
                                             const D3D12_TEXTURE_COPY_LOCATION* src, const D3D12_BOX* box) override
    {
        X2W_USE();
        real_->CopyTextureRegion(dst, x, y, z, src, box);
    }
    void STDMETHODCALLTYPE CopyResource(ID3D12Resource* dst, ID3D12Resource* src) override
    {
        X2W_USE();
        real_->CopyResource(dst, src);
    }
    void STDMETHODCALLTYPE CopyTiles(ID3D12Resource* tiled, const D3D12_TILED_RESOURCE_COORDINATE* start,
                                     const D3D12_TILE_REGION_SIZE* size, ID3D12Resource* buffer, UINT64 offset,
                                     D3D12_TILE_COPY_FLAGS flags) override
    {
        X2W_USE();
        real_->CopyTiles(tiled, start, size, buffer, offset, flags);
    }
    void STDMETHODCALLTYPE ResolveSubresource(ID3D12Resource* dst, UINT dst_sub, ID3D12Resource* src, UINT src_sub,
                                              DXGI_FORMAT format) override
    {
        X2W_USE();
        real_->ResolveSubresource(dst, dst_sub, src, src_sub, format);
    }
    void STDMETHODCALLTYPE IASetPrimitiveTopology(D3D12_PRIMITIVE_TOPOLOGY topology) override
    {
        X2W_USE();
        real_->IASetPrimitiveTopology(topology);
    }
    void STDMETHODCALLTYPE RSSetViewports(UINT count, const D3D12_VIEWPORT* viewports) override
    {
        X2W_USE();
        real_->RSSetViewports(count, viewports);
    }
    void STDMETHODCALLTYPE RSSetScissorRects(UINT count, const D3D12_RECT* rects) override
    {
        X2W_USE();
        real_->RSSetScissorRects(count, rects);
    }
    void STDMETHODCALLTYPE OMSetBlendFactor(const FLOAT factor[4]) override
    {
        X2W_USE();
        real_->OMSetBlendFactor(factor);
    }
    void STDMETHODCALLTYPE OMSetStencilRef(UINT ref) override
    {
        X2W_USE();
        real_->OMSetStencilRef(ref);
    }
    void STDMETHODCALLTYPE SetPipelineState(ID3D12PipelineState* state) override
    {
        X2W_USE();
        real_->SetPipelineState(state);
    }
    void STDMETHODCALLTYPE ResourceBarrier(UINT count, const D3D12_RESOURCE_BARRIER* barriers) override
    {
        X2W_USE();
        real_->ResourceBarrier(count, barriers);
    }
    void STDMETHODCALLTYPE ExecuteBundle(ID3D12GraphicsCommandList* bundle) override
    {
        X2W_USE();
        real_->ExecuteBundle(unwrap(bundle));
    }
    void STDMETHODCALLTYPE SetDescriptorHeaps(UINT count, ID3D12DescriptorHeap* const* heaps) override
    {
        X2W_USE();
        real_->SetDescriptorHeaps(count, heaps);
    }
    void STDMETHODCALLTYPE SetComputeRootSignature(ID3D12RootSignature* root) override
    {
        X2W_USE();
        real_->SetComputeRootSignature(root);
    }
    void STDMETHODCALLTYPE SetGraphicsRootSignature(ID3D12RootSignature* root) override
    {
        X2W_USE();
        real_->SetGraphicsRootSignature(root);
    }
    void STDMETHODCALLTYPE SetComputeRootDescriptorTable(UINT index, D3D12_GPU_DESCRIPTOR_HANDLE base) override
    {
        X2W_USE();
        real_->SetComputeRootDescriptorTable(index, base);
    }
    void STDMETHODCALLTYPE SetGraphicsRootDescriptorTable(UINT index, D3D12_GPU_DESCRIPTOR_HANDLE base) override
    {
        X2W_USE();
        real_->SetGraphicsRootDescriptorTable(index, base);
    }
    void STDMETHODCALLTYPE SetComputeRoot32BitConstant(UINT index, UINT data, UINT offset) override
    {
        X2W_USE();
        real_->SetComputeRoot32BitConstant(index, data, offset);
    }
    void STDMETHODCALLTYPE SetGraphicsRoot32BitConstant(UINT index, UINT data, UINT offset) override
    {
        X2W_USE();
        real_->SetGraphicsRoot32BitConstant(index, data, offset);
    }
    void STDMETHODCALLTYPE SetComputeRoot32BitConstants(UINT index, UINT count, const void* data, UINT offset) override
    {
        X2W_USE();
        real_->SetComputeRoot32BitConstants(index, count, data, offset);
    }
    void STDMETHODCALLTYPE SetGraphicsRoot32BitConstants(UINT index, UINT count, const void* data, UINT offset) override
    {
        X2W_USE();
        real_->SetGraphicsRoot32BitConstants(index, count, data, offset);
    }
    // Root GPU addresses are desktop addresses here. Title GPU address translation
    // (X2WTitleGpuTranslate) belongs to the memory work, not this skeleton.
    void STDMETHODCALLTYPE SetComputeRootConstantBufferView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        real_->SetComputeRootConstantBufferView(index, address);
    }
    void STDMETHODCALLTYPE SetGraphicsRootConstantBufferView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        real_->SetGraphicsRootConstantBufferView(index, address);
    }
    void STDMETHODCALLTYPE SetComputeRootShaderResourceView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        real_->SetComputeRootShaderResourceView(index, address);
    }
    void STDMETHODCALLTYPE SetGraphicsRootShaderResourceView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        real_->SetGraphicsRootShaderResourceView(index, address);
    }
    void STDMETHODCALLTYPE SetComputeRootUnorderedAccessView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        real_->SetComputeRootUnorderedAccessView(index, address);
    }
    void STDMETHODCALLTYPE SetGraphicsRootUnorderedAccessView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        real_->SetGraphicsRootUnorderedAccessView(index, address);
    }
    void STDMETHODCALLTYPE IASetIndexBuffer(const D3D12_INDEX_BUFFER_VIEW* view) override
    {
        X2W_USE();
        real_->IASetIndexBuffer(view);
    }
    void STDMETHODCALLTYPE IASetVertexBuffers(UINT start, UINT count, const D3D12_VERTEX_BUFFER_VIEW* views) override
    {
        X2W_USE();
        real_->IASetVertexBuffers(start, count, views);
    }
    void STDMETHODCALLTYPE SOSetTargets(UINT start, UINT count, const D3D12_STREAM_OUTPUT_BUFFER_VIEW* views) override
    {
        X2W_USE();
        real_->SOSetTargets(start, count, views);
    }
    void STDMETHODCALLTYPE OMSetRenderTargets(UINT count, const D3D12_CPU_DESCRIPTOR_HANDLE* targets, BOOL single,
                                              const D3D12_CPU_DESCRIPTOR_HANDLE* depth) override
    {
        X2W_USE();
        real_->OMSetRenderTargets(count, targets, single, depth);
    }
    void STDMETHODCALLTYPE ClearDepthStencilView(D3D12_CPU_DESCRIPTOR_HANDLE view, D3D12_CLEAR_FLAGS flags, FLOAT depth,
                                                 UINT8 stencil, UINT count, const D3D12_RECT* rects) override
    {
        X2W_USE();
        real_->ClearDepthStencilView(view, flags, depth, stencil, count, rects);
    }
    void STDMETHODCALLTYPE ClearRenderTargetView(D3D12_CPU_DESCRIPTOR_HANDLE view, const FLOAT color[4], UINT count,
                                                 const D3D12_RECT* rects) override
    {
        X2W_USE();
        real_->ClearRenderTargetView(view, color, count, rects);
    }
    void STDMETHODCALLTYPE ClearUnorderedAccessViewUint(D3D12_GPU_DESCRIPTOR_HANDLE gpu, D3D12_CPU_DESCRIPTOR_HANDLE cpu,
                                                        ID3D12Resource* resource, const UINT values[4], UINT count,
                                                        const D3D12_RECT* rects) override
    {
        X2W_USE();
        real_->ClearUnorderedAccessViewUint(gpu, cpu, resource, values, count, rects);
    }
    void STDMETHODCALLTYPE ClearUnorderedAccessViewFloat(D3D12_GPU_DESCRIPTOR_HANDLE gpu, D3D12_CPU_DESCRIPTOR_HANDLE cpu,
                                                         ID3D12Resource* resource, const FLOAT values[4], UINT count,
                                                         const D3D12_RECT* rects) override
    {
        X2W_USE();
        real_->ClearUnorderedAccessViewFloat(gpu, cpu, resource, values, count, rects);
    }
    void STDMETHODCALLTYPE DiscardResource(ID3D12Resource* resource, const D3D12_DISCARD_REGION* region) override
    {
        X2W_USE();
        real_->DiscardResource(resource, region);
    }
    void STDMETHODCALLTYPE BeginQuery(ID3D12QueryHeap* heap, D3D12_QUERY_TYPE type, UINT index) override
    {
        X2W_USE();
        real_->BeginQuery(heap, type, index);
    }
    void STDMETHODCALLTYPE EndQuery(ID3D12QueryHeap* heap, D3D12_QUERY_TYPE type, UINT index) override
    {
        X2W_USE();
        real_->EndQuery(heap, type, index);
    }
    void STDMETHODCALLTYPE ResolveQueryData(ID3D12QueryHeap* heap, D3D12_QUERY_TYPE type, UINT start, UINT count,
                                            ID3D12Resource* dst, UINT64 offset) override
    {
        X2W_USE();
        real_->ResolveQueryData(heap, type, start, count, dst, offset);
    }
    void STDMETHODCALLTYPE SetPredication(ID3D12Resource* buffer, UINT64 offset, D3D12_PREDICATION_OP op) override
    {
        X2W_USE();
        real_->SetPredication(buffer, offset, op);
    }
    void STDMETHODCALLTYPE SetMarker(UINT metadata, const void* data, UINT size) override
    {
        X2W_USE();
        real_->SetMarker(metadata, data, size);
    }
    void STDMETHODCALLTYPE BeginEvent(UINT metadata, const void* data, UINT size) override
    {
        X2W_USE();
        real_->BeginEvent(metadata, data, size);
    }
    void STDMETHODCALLTYPE EndEvent() override
    {
        X2W_USE();
        real_->EndEvent();
    }
    void STDMETHODCALLTYPE ExecuteIndirect(ID3D12CommandSignature* signature, UINT max_commands, ID3D12Resource* args,
                                           UINT64 args_offset, ID3D12Resource* count, UINT64 count_offset) override
    {
        X2W_USE();
        real_->ExecuteIndirect(signature, max_commands, args, args_offset, count, count_offset);
    }
};

class Queue final : public Wrapper<Queue, ID3D12CommandQueue, Kind::queue>, DeviceRef {
public:
    Queue(ID3D12CommandQueue* real, Device* device) : Wrapper(real), DeviceRef(device) { install(); }
    static bool implements(REFIID riid)
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12CommandQueue));
    }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
    void STDMETHODCALLTYPE UpdateTileMappings(ID3D12Resource* resource, UINT regions,
                                              const D3D12_TILED_RESOURCE_COORDINATE* starts,
                                              const D3D12_TILE_REGION_SIZE* sizes, ID3D12Heap* heap, UINT ranges,
                                              const D3D12_TILE_RANGE_FLAGS* flags, const UINT* heap_offsets,
                                              const UINT* tile_counts, D3D12_TILE_MAPPING_FLAGS mapping_flags) override
    {
        X2W_USE();
        real_->UpdateTileMappings(resource, regions, starts, sizes, heap, ranges, flags, heap_offsets, tile_counts,
                                  mapping_flags);
    }
    void STDMETHODCALLTYPE CopyTileMappings(ID3D12Resource* dst, const D3D12_TILED_RESOURCE_COORDINATE* dst_start,
                                            ID3D12Resource* src, const D3D12_TILED_RESOURCE_COORDINATE* src_start,
                                            const D3D12_TILE_REGION_SIZE* size, D3D12_TILE_MAPPING_FLAGS flags) override
    {
        X2W_USE();
        real_->CopyTileMappings(dst, dst_start, src, src_start, size, flags);
    }
    void STDMETHODCALLTYPE ExecuteCommandLists(UINT count, ID3D12CommandList* const* lists) override
    {
        X2W_USE();
        std::vector<ID3D12CommandList*> desktop;
        if (!unwrap_array(count, lists, desktop)) {
            log_note("d3d12_xs!ID3D12CommandQueue::ExecuteCommandLists", "out of memory unwrapping lists; not executed",
                     nullptr);
            return;
        }
        real_->ExecuteCommandLists(count, desktop.data());
    }
    void STDMETHODCALLTYPE SetMarker(UINT metadata, const void* data, UINT size) override
    {
        X2W_USE();
        real_->SetMarker(metadata, data, size);
    }
    void STDMETHODCALLTYPE BeginEvent(UINT metadata, const void* data, UINT size) override
    {
        X2W_USE();
        real_->BeginEvent(metadata, data, size);
    }
    void STDMETHODCALLTYPE EndEvent() override
    {
        X2W_USE();
        real_->EndEvent();
    }
    HRESULT STDMETHODCALLTYPE Signal(ID3D12Fence* fence, UINT64 value) override
    {
        X2W_USE();
        return real_->Signal(unwrap(fence), value);
    }
    HRESULT STDMETHODCALLTYPE Wait(ID3D12Fence* fence, UINT64 value) override
    {
        X2W_USE();
        return real_->Wait(unwrap(fence), value);
    }
    HRESULT STDMETHODCALLTYPE GetTimestampFrequency(UINT64* frequency) override
    {
        X2W_USE();
        return real_->GetTimestampFrequency(frequency);
    }
    HRESULT STDMETHODCALLTYPE GetClockCalibration(UINT64* gpu, UINT64* cpu) override
    {
        X2W_USE();
        return real_->GetClockCalibration(gpu, cpu);
    }
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_COMMAND_QUEUE_DESC* STDMETHODCALLTYPE GetDesc(D3D12_COMMAND_QUEUE_DESC* ret) override
    {
        X2W_USE();
        *ret = real_->GetDesc();
        return ret;
    }
#else
    D3D12_COMMAND_QUEUE_DESC STDMETHODCALLTYPE GetDesc() override
    {
        X2W_USE();
        return real_->GetDesc();
    }
#endif
};

class Device final : public Wrapper<Device, ID3D12Device, Kind::device> {
public:
    explicit Device(ID3D12Device* real) : Wrapper(real) { install(); }
    ~Device()
    {
        if (attached_ && detach_) {
            detach_();
            g_attached_device.store(nullptr);
        }
    }
    static bool implements(REFIID riid)
    {
        return IsEqualIID(riid, __uuidof(ID3D12Object)) || IsEqualIID(riid, __uuidof(ID3D12Device));
    }
    // Debug-layer interfaces are handed out as the desktop objects: they are developer tools that
    // take no wrapped arguments, and the R2 check reads the debug layer's messages through them.
    bool passthrough(REFIID riid, void** out, HRESULT* hr)
    {
        if (!IsEqualIID(riid, __uuidof(ID3D12InfoQueue)) && !IsEqualIID(riid, __uuidof(ID3D12DebugDevice))) {
            return false;
        }
        *hr = real_->QueryInterface(riid, out);
        static std::atomic<bool> noted;
        if (!noted.exchange(true)) {
            log_note("d3d12_xs!ID3D12Device::QueryInterface", "debug-layer interface handed out unwrapped", &riid);
        }
        return true;
    }

    // Attaches the title GPU registry of xmem.dll (era_title_gpu) to the desktop device, when the
    // process has loaded xmem.dll. No link-time dependency: d3d12_xs.dll loads without xmem.dll.
    void attach_title_gpu()
    {
        HMODULE xmem = GetModuleHandleW(L"xmem.dll");
        if (!xmem) {
            set_title_gpu(X2W_GFX_TITLE_GPU_NO_XMEM, S_OK);
            log_note("d3d12_xs!D3D12CreateDevice", "xmem.dll not loaded; no title GPU registry attached", nullptr);
            return;
        }
        using AttachFn = std::int32_t (*)(void*);
        auto attach = reinterpret_cast<AttachFn>(reinterpret_cast<void*>(GetProcAddress(xmem, "X2WTitleGpuAttach")));
        detach_ = reinterpret_cast<void (*)()>(reinterpret_cast<void*>(GetProcAddress(xmem, "X2WTitleGpuDetach")));
        if (!attach || !detach_) {
            set_title_gpu(X2W_GFX_TITLE_GPU_FAILED, E_NOINTERFACE);
            log_note("d3d12_xs!D3D12CreateDevice", "xmem.dll lacks X2WTitleGpuAttach/Detach", nullptr);
            return;
        }
        // The registry aliases memory for one device at a time, and attaching a second device would
        // drop the first one's aliases. The first device keeps it; later devices are noted.
        Device* expected = nullptr;
        if (!g_attached_device.compare_exchange_strong(expected, this)) {
            log_note("d3d12_xs!D3D12CreateDevice", "title GPU registry already attached to an earlier device", nullptr);
            return;
        }
        const HRESULT hr = attach(real_);
        attached_ = SUCCEEDED(hr);
        if (!attached_) g_attached_device.store(nullptr);
        set_title_gpu(attached_ ? X2W_GFX_TITLE_GPU_ATTACHED : X2W_GFX_TITLE_GPU_FAILED, hr);
        char detail[96];
        std::snprintf(detail, sizeof(detail), "X2WTitleGpuAttach -> 0x%08lx", static_cast<unsigned long>(hr));
        log_note("d3d12_xs!D3D12CreateDevice", detail, nullptr);
    }

    UINT STDMETHODCALLTYPE GetNodeCount() override
    {
        X2W_USE();
        return real_->GetNodeCount();
    }
    X2W_D3D12_OBJECT_METHODS
    HRESULT STDMETHODCALLTYPE CreateCommandQueue(const D3D12_COMMAND_QUEUE_DESC* desc, REFIID riid, void** out) override
    {
        X2W_USE();
        if (!out) return real_->CreateCommandQueue(desc, riid, nullptr);
        *out = nullptr;
        ID3D12CommandQueue* queue = nullptr;
        const HRESULT hr = real_->CreateCommandQueue(desc, IID_PPV_ARGS(&queue));
        if (FAILED(hr)) return hr;
        return hand_out(new (std::nothrow) Queue(queue, this), queue, riid, out, X2W_RETURN_ADDRESS());
    }
    HRESULT STDMETHODCALLTYPE CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE type, REFIID riid, void** out) override
    {
        X2W_USE();
        if (!out) return real_->CreateCommandAllocator(type, riid, nullptr);
        *out = nullptr;
        ID3D12CommandAllocator* allocator = nullptr;
        const HRESULT hr = real_->CreateCommandAllocator(type, IID_PPV_ARGS(&allocator));
        if (FAILED(hr)) return hr;
        return hand_out(new (std::nothrow) Allocator(allocator, this), allocator, riid, out, X2W_RETURN_ADDRESS());
    }
    // Pipeline translation (R3) goes here; until then the desktop description is forwarded as is.
    HRESULT STDMETHODCALLTYPE CreateGraphicsPipelineState(const D3D12_GRAPHICS_PIPELINE_STATE_DESC* desc, REFIID riid,
                                                          void** out) override
    {
        X2W_USE();
        return real_->CreateGraphicsPipelineState(desc, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreateComputePipelineState(const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc, REFIID riid,
                                                         void** out) override
    {
        X2W_USE();
        return real_->CreateComputePipelineState(desc, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreateCommandList(UINT node_mask, D3D12_COMMAND_LIST_TYPE type,
                                                ID3D12CommandAllocator* allocator, ID3D12PipelineState* state,
                                                REFIID riid, void** out) override
    {
        X2W_USE();
        if (!out) return real_->CreateCommandList(node_mask, type, unwrap(allocator), state, riid, nullptr);
        *out = nullptr;
        ID3D12GraphicsCommandList* list = nullptr;
        const HRESULT hr = real_->CreateCommandList(node_mask, type, unwrap(allocator), state, IID_PPV_ARGS(&list));
        if (FAILED(hr)) return hr;
        return hand_out(new (std::nothrow) List(list, this), list, riid, out, X2W_RETURN_ADDRESS());
    }
    HRESULT STDMETHODCALLTYPE CheckFeatureSupport(D3D12_FEATURE feature, void* data, UINT size) override
    {
        X2W_USE();
        return real_->CheckFeatureSupport(feature, data, size);
    }
    HRESULT STDMETHODCALLTYPE CreateDescriptorHeap(const D3D12_DESCRIPTOR_HEAP_DESC* desc, REFIID riid,
                                                   void** out) override
    {
        X2W_USE();
        return real_->CreateDescriptorHeap(desc, riid, out);
    }
    UINT STDMETHODCALLTYPE GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE type) override
    {
        X2W_USE();
        return real_->GetDescriptorHandleIncrementSize(type);
    }
    HRESULT STDMETHODCALLTYPE CreateRootSignature(UINT node_mask, const void* blob, SIZE_T size, REFIID riid,
                                                  void** out) override
    {
        X2W_USE();
        return real_->CreateRootSignature(node_mask, blob, size, riid, out);
    }
    void STDMETHODCALLTYPE CreateConstantBufferView(const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc,
                                                    D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateConstantBufferView(desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateShaderResourceView(ID3D12Resource* resource, const D3D12_SHADER_RESOURCE_VIEW_DESC* desc,
                                                    D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateShaderResourceView(resource, desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateUnorderedAccessView(ID3D12Resource* resource, ID3D12Resource* counter,
                                                     const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc,
                                                     D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateUnorderedAccessView(resource, counter, desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateRenderTargetView(ID3D12Resource* resource, const D3D12_RENDER_TARGET_VIEW_DESC* desc,
                                                  D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateRenderTargetView(resource, desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateDepthStencilView(ID3D12Resource* resource, const D3D12_DEPTH_STENCIL_VIEW_DESC* desc,
                                                  D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateDepthStencilView(resource, desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateSampler(const D3D12_SAMPLER_DESC* desc, D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateSampler(desc, descriptor);
    }
    void STDMETHODCALLTYPE CopyDescriptors(UINT dst_count, const D3D12_CPU_DESCRIPTOR_HANDLE* dst_starts,
                                           const UINT* dst_sizes, UINT src_count,
                                           const D3D12_CPU_DESCRIPTOR_HANDLE* src_starts, const UINT* src_sizes,
                                           D3D12_DESCRIPTOR_HEAP_TYPE type) override
    {
        X2W_USE();
        real_->CopyDescriptors(dst_count, dst_starts, dst_sizes, src_count, src_starts, src_sizes, type);
    }
    void STDMETHODCALLTYPE CopyDescriptorsSimple(UINT count, D3D12_CPU_DESCRIPTOR_HANDLE dst,
                                                 D3D12_CPU_DESCRIPTOR_HANDLE src, D3D12_DESCRIPTOR_HEAP_TYPE type) override
    {
        X2W_USE();
        real_->CopyDescriptorsSimple(count, dst, src, type);
    }
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_ALLOCATION_INFO* STDMETHODCALLTYPE GetResourceAllocationInfo(D3D12_RESOURCE_ALLOCATION_INFO* ret,
                                                                                UINT mask, UINT count,
                                                                                const D3D12_RESOURCE_DESC* descs) override
    {
        X2W_USE();
        *ret = real_->GetResourceAllocationInfo(mask, count, descs);
        return ret;
    }
    D3D12_HEAP_PROPERTIES* STDMETHODCALLTYPE GetCustomHeapProperties(D3D12_HEAP_PROPERTIES* ret, UINT node_mask,
                                                                     D3D12_HEAP_TYPE type) override
    {
        X2W_USE();
        *ret = real_->GetCustomHeapProperties(node_mask, type);
        return ret;
    }
#else
    D3D12_RESOURCE_ALLOCATION_INFO STDMETHODCALLTYPE GetResourceAllocationInfo(UINT mask, UINT count,
                                                                               const D3D12_RESOURCE_DESC* descs) override
    {
        X2W_USE();
        return real_->GetResourceAllocationInfo(mask, count, descs);
    }
    D3D12_HEAP_PROPERTIES STDMETHODCALLTYPE GetCustomHeapProperties(UINT node_mask, D3D12_HEAP_TYPE type) override
    {
        X2W_USE();
        return real_->GetCustomHeapProperties(node_mask, type);
    }
#endif
    HRESULT STDMETHODCALLTYPE CreateCommittedResource(const D3D12_HEAP_PROPERTIES* heap, D3D12_HEAP_FLAGS flags,
                                                      const D3D12_RESOURCE_DESC* desc, D3D12_RESOURCE_STATES state,
                                                      const D3D12_CLEAR_VALUE* clear, REFIID riid, void** out) override
    {
        X2W_USE();
        return real_->CreateCommittedResource(heap, flags, desc, state, clear, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreateHeap(const D3D12_HEAP_DESC* desc, REFIID riid, void** out) override
    {
        X2W_USE();
        return real_->CreateHeap(desc, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreatePlacedResource(ID3D12Heap* heap, UINT64 offset, const D3D12_RESOURCE_DESC* desc,
                                                   D3D12_RESOURCE_STATES state, const D3D12_CLEAR_VALUE* clear,
                                                   REFIID riid, void** out) override
    {
        X2W_USE();
        return real_->CreatePlacedResource(heap, offset, desc, state, clear, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreateReservedResource(const D3D12_RESOURCE_DESC* desc, D3D12_RESOURCE_STATES state,
                                                     const D3D12_CLEAR_VALUE* clear, REFIID riid, void** out) override
    {
        X2W_USE();
        return real_->CreateReservedResource(desc, state, clear, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreateSharedHandle(ID3D12DeviceChild* object, const SECURITY_ATTRIBUTES* attributes,
                                                 DWORD access, LPCWSTR name, HANDLE* handle) override
    {
        X2W_USE();
        return real_->CreateSharedHandle(unwrap(object), attributes, access, name, handle);
    }
    // Opened objects (a shared fence, for example) are returned as desktop objects.
    HRESULT STDMETHODCALLTYPE OpenSharedHandle(HANDLE handle, REFIID riid, void** out) override
    {
        X2W_USE();
        return real_->OpenSharedHandle(handle, riid, out);
    }
    HRESULT STDMETHODCALLTYPE OpenSharedHandleByName(LPCWSTR name, DWORD access, HANDLE* handle) override
    {
        X2W_USE();
        return real_->OpenSharedHandleByName(name, access, handle);
    }
    HRESULT STDMETHODCALLTYPE MakeResident(UINT count, ID3D12Pageable* const* objects) override
    {
        X2W_USE();
        std::vector<ID3D12Pageable*> desktop;
        if (!unwrap_array(count, objects, desktop)) return E_OUTOFMEMORY;
        return real_->MakeResident(count, desktop.data());
    }
    HRESULT STDMETHODCALLTYPE Evict(UINT count, ID3D12Pageable* const* objects) override
    {
        X2W_USE();
        std::vector<ID3D12Pageable*> desktop;
        if (!unwrap_array(count, objects, desktop)) return E_OUTOFMEMORY;
        return real_->Evict(count, desktop.data());
    }
    HRESULT STDMETHODCALLTYPE CreateFence(UINT64 initial, D3D12_FENCE_FLAGS flags, REFIID riid, void** out) override
    {
        X2W_USE();
        if (!out) return real_->CreateFence(initial, flags, riid, nullptr);
        *out = nullptr;
        ID3D12Fence* fence = nullptr;
        const HRESULT hr = real_->CreateFence(initial, flags, IID_PPV_ARGS(&fence));
        if (FAILED(hr)) return hr;
        return hand_out(new (std::nothrow) Fence(fence, this, flags), fence, riid, out, X2W_RETURN_ADDRESS());
    }
    HRESULT STDMETHODCALLTYPE GetDeviceRemovedReason() override
    {
        X2W_USE();
        return real_->GetDeviceRemovedReason();
    }
    void STDMETHODCALLTYPE GetCopyableFootprints(const D3D12_RESOURCE_DESC* desc, UINT first, UINT count, UINT64 base,
                                                 D3D12_PLACED_SUBRESOURCE_FOOTPRINT* layouts, UINT* rows,
                                                 UINT64* row_bytes, UINT64* total) override
    {
        X2W_USE();
        real_->GetCopyableFootprints(desc, first, count, base, layouts, rows, row_bytes, total);
    }
    HRESULT STDMETHODCALLTYPE CreateQueryHeap(const D3D12_QUERY_HEAP_DESC* desc, REFIID riid, void** out) override
    {
        X2W_USE();
        return real_->CreateQueryHeap(desc, riid, out);
    }
    HRESULT STDMETHODCALLTYPE SetStablePowerState(BOOL enable) override
    {
        X2W_USE();
        return real_->SetStablePowerState(enable);
    }
    HRESULT STDMETHODCALLTYPE CreateCommandSignature(const D3D12_COMMAND_SIGNATURE_DESC* desc,
                                                     ID3D12RootSignature* root, REFIID riid, void** out) override
    {
        X2W_USE();
        return real_->CreateCommandSignature(desc, root, riid, out);
    }
    void STDMETHODCALLTYPE GetResourceTiling(ID3D12Resource* resource, UINT* tiles, D3D12_PACKED_MIP_INFO* packed,
                                             D3D12_TILE_SHAPE* shape, UINT* tilings, UINT first,
                                             D3D12_SUBRESOURCE_TILING* out) override
    {
        X2W_USE();
        real_->GetResourceTiling(resource, tiles, packed, shape, tilings, first, out);
    }
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    LUID* STDMETHODCALLTYPE GetAdapterLuid(LUID* ret) override
    {
        X2W_USE();
        *ret = real_->GetAdapterLuid();
        return ret;
    }
#else
    LUID STDMETHODCALLTYPE GetAdapterLuid() override
    {
        X2W_USE();
        return real_->GetAdapterLuid();
    }
#endif

private:
    bool attached_ = false;
    void (*detach_)() = nullptr;
};

DeviceRef::DeviceRef(Device* device) : device_(device) { device_->AddRef(); }
DeviceRef::~DeviceRef() { device_->Release(); }

HRESULT device_query(Device* device, REFIID riid, void** out, const void* caller)
{
    return device->query(riid, out, caller);
}

class SwapChain final : public Wrapper<SwapChain, IDXGISwapChain3, Kind::swap_chain> {
public:
    SwapChain(IDXGISwapChain3* real, Queue* queue) : Wrapper(real), queue_(queue)
    {
        queue_->AddRef();
        install();
    }
    ~SwapChain() { queue_->Release(); }
    static bool implements(REFIID riid)
    {
        return IsEqualIID(riid, __uuidof(IDXGIObject)) || IsEqualIID(riid, __uuidof(IDXGIDeviceSubObject)) ||
               IsEqualIID(riid, __uuidof(IDXGISwapChain)) || IsEqualIID(riid, __uuidof(IDXGISwapChain1)) ||
               IsEqualIID(riid, __uuidof(IDXGISwapChain2)) || IsEqualIID(riid, __uuidof(IDXGISwapChain3));
    }

    HRESULT STDMETHODCALLTYPE SetPrivateData(REFGUID guid, UINT size, const void* data) override
    {
        X2W_USE();
        return real_->SetPrivateData(guid, size, data);
    }
    HRESULT STDMETHODCALLTYPE SetPrivateDataInterface(REFGUID guid, const IUnknown* object) override
    {
        X2W_USE();
        return real_->SetPrivateDataInterface(guid, object);
    }
    HRESULT STDMETHODCALLTYPE GetPrivateData(REFGUID guid, UINT* size, void* data) override
    {
        X2W_USE();
        return real_->GetPrivateData(guid, size, data);
    }
    HRESULT STDMETHODCALLTYPE GetParent(REFIID riid, void** parent) override
    {
        X2W_USE();
        return real_->GetParent(riid, parent);
    }
    // A D3D12 swap chain's device is its command queue: the wrapped one.
    HRESULT STDMETHODCALLTYPE GetDevice(REFIID riid, void** out) override
    {
        X2W_USE();
        return queue_->query(riid, out, X2W_RETURN_ADDRESS());
    }
    HRESULT STDMETHODCALLTYPE Present(UINT interval, UINT flags) override
    {
        X2W_USE();
        const HRESULT hr = real_->Present(interval, flags);
        if (SUCCEEDED(hr) && !(flags & DXGI_PRESENT_TEST)) count_present();
        return hr;
    }
    HRESULT STDMETHODCALLTYPE GetBuffer(UINT index, REFIID riid, void** surface) override
    {
        X2W_USE();
        return real_->GetBuffer(index, riid, surface);
    }
    HRESULT STDMETHODCALLTYPE SetFullscreenState(BOOL fullscreen, IDXGIOutput* target) override
    {
        X2W_USE();
        return real_->SetFullscreenState(fullscreen, target);
    }
    HRESULT STDMETHODCALLTYPE GetFullscreenState(BOOL* fullscreen, IDXGIOutput** target) override
    {
        X2W_USE();
        return real_->GetFullscreenState(fullscreen, target);
    }
    HRESULT STDMETHODCALLTYPE GetDesc(DXGI_SWAP_CHAIN_DESC* desc) override
    {
        X2W_USE();
        return real_->GetDesc(desc);
    }
    HRESULT STDMETHODCALLTYPE ResizeBuffers(UINT count, UINT width, UINT height, DXGI_FORMAT format, UINT flags) override
    {
        X2W_USE();
        return real_->ResizeBuffers(count, width, height, format, flags);
    }
    HRESULT STDMETHODCALLTYPE ResizeTarget(const DXGI_MODE_DESC* mode) override
    {
        X2W_USE();
        return real_->ResizeTarget(mode);
    }
    HRESULT STDMETHODCALLTYPE GetContainingOutput(IDXGIOutput** output) override
    {
        X2W_USE();
        return real_->GetContainingOutput(output);
    }
    HRESULT STDMETHODCALLTYPE GetFrameStatistics(DXGI_FRAME_STATISTICS* stats) override
    {
        X2W_USE();
        return real_->GetFrameStatistics(stats);
    }
    HRESULT STDMETHODCALLTYPE GetLastPresentCount(UINT* count) override
    {
        X2W_USE();
        return real_->GetLastPresentCount(count);
    }
    HRESULT STDMETHODCALLTYPE GetDesc1(DXGI_SWAP_CHAIN_DESC1* desc) override
    {
        X2W_USE();
        return real_->GetDesc1(desc);
    }
    HRESULT STDMETHODCALLTYPE GetFullscreenDesc(DXGI_SWAP_CHAIN_FULLSCREEN_DESC* desc) override
    {
        X2W_USE();
        return real_->GetFullscreenDesc(desc);
    }
    HRESULT STDMETHODCALLTYPE GetHwnd(HWND* window) override
    {
        X2W_USE();
        return real_->GetHwnd(window);
    }
    HRESULT STDMETHODCALLTYPE GetCoreWindow(REFIID riid, void** window) override
    {
        X2W_USE();
        return real_->GetCoreWindow(riid, window);
    }
    HRESULT STDMETHODCALLTYPE Present1(UINT interval, UINT flags, const DXGI_PRESENT_PARAMETERS* parameters) override
    {
        X2W_USE();
        const HRESULT hr = real_->Present1(interval, flags, parameters);
        if (SUCCEEDED(hr) && !(flags & DXGI_PRESENT_TEST)) count_present();
        return hr;
    }
    BOOL STDMETHODCALLTYPE IsTemporaryMonoSupported() override
    {
        X2W_USE();
        return real_->IsTemporaryMonoSupported();
    }
    HRESULT STDMETHODCALLTYPE GetRestrictToOutput(IDXGIOutput** output) override
    {
        X2W_USE();
        return real_->GetRestrictToOutput(output);
    }
    HRESULT STDMETHODCALLTYPE SetBackgroundColor(const DXGI_RGBA* color) override
    {
        X2W_USE();
        return real_->SetBackgroundColor(color);
    }
    HRESULT STDMETHODCALLTYPE GetBackgroundColor(DXGI_RGBA* color) override
    {
        X2W_USE();
        return real_->GetBackgroundColor(color);
    }
    HRESULT STDMETHODCALLTYPE SetRotation(DXGI_MODE_ROTATION rotation) override
    {
        X2W_USE();
        return real_->SetRotation(rotation);
    }
    HRESULT STDMETHODCALLTYPE GetRotation(DXGI_MODE_ROTATION* rotation) override
    {
        X2W_USE();
        return real_->GetRotation(rotation);
    }
    HRESULT STDMETHODCALLTYPE SetSourceSize(UINT width, UINT height) override
    {
        X2W_USE();
        return real_->SetSourceSize(width, height);
    }
    HRESULT STDMETHODCALLTYPE GetSourceSize(UINT* width, UINT* height) override
    {
        X2W_USE();
        return real_->GetSourceSize(width, height);
    }
    HRESULT STDMETHODCALLTYPE SetMaximumFrameLatency(UINT latency) override
    {
        X2W_USE();
        return real_->SetMaximumFrameLatency(latency);
    }
    HRESULT STDMETHODCALLTYPE GetMaximumFrameLatency(UINT* latency) override
    {
        X2W_USE();
        return real_->GetMaximumFrameLatency(latency);
    }
    HANDLE STDMETHODCALLTYPE GetFrameLatencyWaitableObject() override
    {
        X2W_USE();
        return real_->GetFrameLatencyWaitableObject();
    }
    HRESULT STDMETHODCALLTYPE SetMatrixTransform(const DXGI_MATRIX_3X2_F* matrix) override
    {
        X2W_USE();
        return real_->SetMatrixTransform(matrix);
    }
    HRESULT STDMETHODCALLTYPE GetMatrixTransform(DXGI_MATRIX_3X2_F* matrix) override
    {
        X2W_USE();
        return real_->GetMatrixTransform(matrix);
    }
    UINT STDMETHODCALLTYPE GetCurrentBackBufferIndex() override
    {
        X2W_USE();
        return real_->GetCurrentBackBufferIndex();
    }
    HRESULT STDMETHODCALLTYPE CheckColorSpaceSupport(DXGI_COLOR_SPACE_TYPE space, UINT* support) override
    {
        X2W_USE();
        return real_->CheckColorSpaceSupport(space, support);
    }
    HRESULT STDMETHODCALLTYPE SetColorSpace1(DXGI_COLOR_SPACE_TYPE space) override
    {
        X2W_USE();
        return real_->SetColorSpace1(space);
    }
    HRESULT STDMETHODCALLTYPE ResizeBuffers1(UINT count, UINT width, UINT height, DXGI_FORMAT format, UINT flags,
                                             const UINT* node_masks, IUnknown* const* queues) override
    {
        X2W_USE();
        std::vector<IUnknown*> desktop;
        if (queues && !unwrap_array(count, queues, desktop)) return E_OUTOFMEMORY;
        return real_->ResizeBuffers1(count, width, height, format, flags, node_masks, queues ? desktop.data() : nullptr);
    }

private:
    Queue* queue_;
};

static_assert(std::is_final_v<Device> && std::is_final_v<Queue> && std::is_final_v<Allocator> &&
              std::is_final_v<List> && std::is_final_v<Fence> && std::is_final_v<SwapChain>);

IUnknown* real_of(const void* object)
{
    Kind kind;
    if (!wrapper_kind(object, &kind)) return nullptr;
    // `object` is the interface base at offset 0 of the wrapper (single inheritance).
    auto* base = static_cast<IUnknown*>(const_cast<void*>(object));
    switch (kind) {
    case Kind::device: return static_cast<Device*>(static_cast<ID3D12Device*>(base))->real();
    case Kind::queue: return static_cast<Queue*>(static_cast<ID3D12CommandQueue*>(base))->real();
    case Kind::allocator: return static_cast<Allocator*>(static_cast<ID3D12CommandAllocator*>(base))->real();
    case Kind::list: return static_cast<List*>(static_cast<ID3D12GraphicsCommandList*>(base))->real();
    case Kind::fence: return static_cast<Fence*>(static_cast<ID3D12Fence1*>(base))->real();
    case Kind::swap_chain: return static_cast<SwapChain*>(static_cast<IDXGISwapChain3*>(base))->real();
    default: return nullptr;
    }
}

}  // namespace

HRESULT wrap_device(ID3D12Device* real, REFIID riid, void** out, const void* caller)
{
    auto* device = new (std::nothrow) Device(real);
    if (!device) {
        real->Release();
        return E_OUTOFMEMORY;
    }
    count_device();
    device->attach_title_gpu();
    const HRESULT hr = device->query(riid, out, caller);
    device->Release();
    return hr;
}

HRESULT create_swap_chain_for_hwnd(IUnknown* queue, HWND window, const DXGI_SWAP_CHAIN_DESC1* desc,
                                   const DXGI_SWAP_CHAIN_FULLSCREEN_DESC* fullscreen_desc,
                                   IDXGIOutput* restrict_to_output, REFIID riid, void** out, const void* caller)
{
    if (!out) return E_POINTER;
    *out = nullptr;
    Kind kind;
    if (!wrapper_kind(queue, &kind) || kind != Kind::queue) return E_INVALIDARG;
    auto* wrapped_queue = static_cast<Queue*>(static_cast<ID3D12CommandQueue*>(queue));

    ComPtr<IDXGIFactory2> factory;
    HRESULT hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
    if (FAILED(hr)) return hr;
    ComPtr<IDXGISwapChain1> chain1;
    hr = factory->CreateSwapChainForHwnd(wrapped_queue->real(), window, desc, fullscreen_desc, restrict_to_output,
                                         &chain1);
    if (FAILED(hr)) return hr;
    IDXGISwapChain3* chain3 = nullptr;
    hr = chain1->QueryInterface(IID_PPV_ARGS(&chain3));
    if (FAILED(hr)) return hr;
    auto* wrapped = new (std::nothrow) SwapChain(chain3, wrapped_queue);
    return hand_out(wrapped, chain3, riid, out, caller);
}

}  // namespace d3d12_xs
