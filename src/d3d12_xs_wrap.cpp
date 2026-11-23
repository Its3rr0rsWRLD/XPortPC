// Wrapper objects of the d3d12_xs.dll graphics shim (d3d12_xs_wrap.h).
//
// Each wrapper is a final class with single inheritance from the public desktop interface, so its
// compiler vtable is exactly the public method order; install_vtable then swaps in a copy that
// continues with logging thunks. No wrapper declares a virtual destructor or any virtual method
// beyond the interface. Methods forward to the desktop object and log their first use.
#include "d3d12_xs_wrap.h"
#include "d3d12_xs_api.h"
#include "d3d12_xs_descriptors.h"
#include "d3d12_xs_pipeline.h"

#include <d3d12sdklayers.h>
#include <dxgi1_4.h>
#include <wrl/client.h>

#include <atomic>
#include <cstring>
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
pipeline::TitleViews* device_views(Device* device);

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

// A title CBV/SRV/UAV or sampler heap (d3d12_xs_descriptors.h): title handles over a desktop shadow heap that is
// never shader visible. real_ is the shadow heap.
class DescriptorHeap final : public Wrapper<DescriptorHeap, ID3D12DescriptorHeap, Kind::descriptor_heap>, DeviceRef {
public:
    DescriptorHeap(ID3D12DescriptorHeap* shadow, Device* device) : Wrapper(shadow), DeviceRef(device) { install(); }
    ~DescriptorHeap() { descriptors::destroy(state_); }
    static bool implements(REFIID riid)
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12DescriptorHeap));
    }
    bool init(ID3D12Device* desktop, const D3D12_DESCRIPTOR_HEAP_DESC& desc)
    {
        return descriptors::create(state_, desktop, desc, real_);
    }
    const descriptors::Heap& state() const { return state_; }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_DESCRIPTOR_HEAP_DESC* STDMETHODCALLTYPE GetDesc(D3D12_DESCRIPTOR_HEAP_DESC* ret) override
    {
        X2W_USE();
        *ret = state_.desc;
        return ret;
    }
    D3D12_CPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE GetCPUDescriptorHandleForHeapStart(D3D12_CPU_DESCRIPTOR_HANDLE* ret) override
    {
        X2W_USE();
        ret->ptr = reinterpret_cast<SIZE_T>(state_.base);
        return ret;
    }
    D3D12_GPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE GetGPUDescriptorHandleForHeapStart(D3D12_GPU_DESCRIPTOR_HANDLE* ret) override
    {
        X2W_USE();
        ret->ptr = gpu_start();
        return ret;
    }
#else
    D3D12_DESCRIPTOR_HEAP_DESC STDMETHODCALLTYPE GetDesc() override
    {
        X2W_USE();
        return state_.desc;
    }
    D3D12_CPU_DESCRIPTOR_HANDLE STDMETHODCALLTYPE GetCPUDescriptorHandleForHeapStart() override
    {
        X2W_USE();
        return {reinterpret_cast<SIZE_T>(state_.base)};
    }
    D3D12_GPU_DESCRIPTOR_HANDLE STDMETHODCALLTYPE GetGPUDescriptorHandleForHeapStart() override
    {
        X2W_USE();
        return {gpu_start()};
    }
#endif

private:
    // One address space: a shader-visible heap's GPU handles are its CPU handles. As on desktop, a heap that is not
    // shader visible has no GPU handles.
    UINT64 gpu_start() const
    {
        return state_.desc.Flags & D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE ? reinterpret_cast<UINT64>(state_.base) : 0;
    }
    descriptors::Heap state_;
};

// The title heap behind a wrapper, or null for a desktop heap.
const descriptors::Heap* title_heap(ID3D12DescriptorHeap* heap)
{
    Kind kind;
    if (!wrapper_kind(heap, &kind) || kind != Kind::descriptor_heap) return nullptr;
    return &static_cast<DescriptorHeap*>(heap)->state();
}

class List final : public Wrapper<List, ID3D12GraphicsCommandList, Kind::list>, DeviceRef {
public:
    List(ID3D12GraphicsCommandList* real, Device* device) : Wrapper(real), DeviceRef(device), args_(new (std::nothrow) pipeline::RootArgs())
    {
        if (args_) args_->clear();
        install();
    }
    ~List()
    {
        pipeline::release_blocks(device_views(device_), blocks_);
        delete args_;
        delete compute_.args;
    }
    pipeline::BlockUse* blocks() { return &blocks_; }
    static bool implements(REFIID riid)
    {
        return is_d3d12_child_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12CommandList)) ||
               IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList));
    }

    // Graphics state the converter's bindings depend on (d3d12_xs_pipeline.h), recorded as the title sets it.
    void reset_state(ID3D12PipelineState* state)
    {
        has_root_ = false;
        set_pipeline(state);
        heaps_ = {};
        ours_bound_ = false;
        if (args_) args_->clear();
        compute_.reset();
    }
    void set_pipeline(ID3D12PipelineState* state)
    {
        translated_ = pipeline::pso_info(state, &pso_);
        compute_.translated = pipeline::compute_pso_info(state, &compute_.pso);
    }
    void record_address(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address)
    {
        if (args_ && index < pipeline::max_title_params) args_->address[index] = address;
    }
    void record_constants(UINT index, UINT count, const void* data, UINT offset)
    {
        if (!args_ || index >= pipeline::max_title_params || offset >= 64 || count > 64 - offset) return;
        std::memcpy(&args_->constants[index][offset], data, count * 4);
    }
    // Before a draw: the converter parameters of a translated pipeline. False skips the draw (logged).
    bool bind_draw(std::uint32_t base_vertex, std::uint32_t start_instance)
    {
        if (!translated_) {
            if (has_root_) pipeline::set_placeholders(real_, root_);
            return true;
        }
        if (!has_root_ || !args_) {
            log_refused("d3d12_xs!ID3D12GraphicsCommandList::Draw",
                        "draw skipped: a translated pipeline drawn without a root signature created through the shim",
                        true);
            return false;
        }
        return pipeline::bind_for_draw(device_views(device_), real_, root_, pso_, *args_, heaps_,
                                       {base_vertex, start_instance}, &ours_bound_, &blocks_);
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
        // A new recording: the blocks the previous one read are protected by its submissions' stamps only.
        pipeline::release_blocks(device_views(device_), blocks_);
        reset_state(state);
        return real_->Reset(unwrap(allocator), state);
    }
    void STDMETHODCALLTYPE ClearState(ID3D12PipelineState* state) override
    {
        X2W_USE();
        reset_state(state);
        real_->ClearState(state);
    }
    // A translated vertex program receives the base vertex and start instance in user SGPRs (bind_for_draw) and adds
    // them itself, as on the console: the desktop draw starts both its vertex and instance ids at 0.
    void STDMETHODCALLTYPE DrawInstanced(UINT vertices, UINT instances, UINT first_vertex, UINT first_instance) override
    {
        X2W_USE();
        if (!bind_draw(first_vertex, first_instance)) return;
        if (translated_) real_->DrawInstanced(vertices, instances, 0, 0);
        else real_->DrawInstanced(vertices, instances, first_vertex, first_instance);
    }
    void STDMETHODCALLTYPE DrawIndexedInstanced(UINT indices, UINT instances, UINT first_index, INT base_vertex,
                                                UINT first_instance) override
    {
        X2W_USE();
        if (!bind_draw(static_cast<std::uint32_t>(base_vertex), first_instance)) return;
        if (translated_) real_->DrawIndexedInstanced(indices, instances, first_index, 0, 0);
        else real_->DrawIndexedInstanced(indices, instances, first_index, base_vertex, first_instance);
    }
    void STDMETHODCALLTYPE Dispatch(UINT x, UINT y, UINT z) override
    {
        X2W_USE();
        if (compute_.bind(device_views(device_), real_, heaps_, &ours_bound_, &blocks_)) real_->Dispatch(x, y, z);
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
        set_pipeline(state);
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
    // Title heaps are recorded, not bound: desktop D3D12 sees the shim's heaps, bound before a translated draw. A
    // desktop heap (one the shim did not create) is bound as given, and translated draws are then refused.
    void STDMETHODCALLTYPE SetDescriptorHeaps(UINT count, ID3D12DescriptorHeap* const* heaps) override
    {
        X2W_USE();
        heaps_ = {};
        std::vector<ID3D12DescriptorHeap*> desktop;
        for (UINT i = 0; heaps && i < count; ++i) {
            if (!heaps[i]) continue;
            if (const descriptors::Heap* heap = title_heap(heaps[i])) {
                (heap->desc.Type == D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER ? heaps_.samplers : heaps_.views) = heap->serial;
            } else {
                desktop.push_back(heaps[i]);
            }
        }
        if (!desktop.empty()) {
            heaps_.foreign = true;
            ours_bound_ = false;
            real_->SetDescriptorHeaps(static_cast<UINT>(desktop.size()), desktop.data());
        }
    }
    void STDMETHODCALLTYPE SetComputeRootSignature(ID3D12RootSignature* root) override
    {
        X2W_USE();
        compute_.set_root(root);
        real_->SetComputeRootSignature(root);
    }
    void STDMETHODCALLTYPE SetGraphicsRootSignature(ID3D12RootSignature* root) override
    {
        X2W_USE();
        has_root_ = pipeline::root_info(root, &root_);
        if (args_) args_->clear();
        real_->SetGraphicsRootSignature(root);
    }
    void STDMETHODCALLTYPE SetComputeRootDescriptorTable(UINT index, D3D12_GPU_DESCRIPTOR_HANDLE base) override
    {
        X2W_USE();
        if (descriptors::is_title_handle(base.ptr)) {
            log_refused("d3d12_xs!ID3D12GraphicsCommandList::SetComputeRootDescriptorTable",
                        "a compute table in a title heap is not translated (console compute comes with R5); not set",
                        true);
            return;
        }
        real_->SetComputeRootDescriptorTable(index, base);
    }
    // A table of a title root signature is recorded (its parameter is a placeholder on desktop); bind_for_draw
    // resolves what translated shaders read from it.
    void STDMETHODCALLTYPE SetGraphicsRootDescriptorTable(UINT index, D3D12_GPU_DESCRIPTOR_HANDLE base) override
    {
        X2W_USE();
        if (has_root_ && index < root_.title_params && root_.types[index] == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) {
            record_address(index, base.ptr);
            return;
        }
        if (descriptors::is_title_handle(base.ptr)) {
            log_refused("d3d12_xs!ID3D12GraphicsCommandList::SetGraphicsRootDescriptorTable",
                        "a title-heap table for a root signature not created through the shim; not set", true);
            return;
        }
        real_->SetGraphicsRootDescriptorTable(index, base);
    }
    void STDMETHODCALLTYPE SetComputeRoot32BitConstant(UINT index, UINT data, UINT offset) override
    {
        X2W_USE();
        compute_.record_constants(index, 1, &data, offset);
        real_->SetComputeRoot32BitConstant(index, data, offset);
    }
    void STDMETHODCALLTYPE SetGraphicsRoot32BitConstant(UINT index, UINT data, UINT offset) override
    {
        X2W_USE();
        record_constants(index, 1, &data, offset);
        real_->SetGraphicsRoot32BitConstant(index, data, offset);
    }
    void STDMETHODCALLTYPE SetComputeRoot32BitConstants(UINT index, UINT count, const void* data, UINT offset) override
    {
        X2W_USE();
        if (data) compute_.record_constants(index, count, data, offset);
        real_->SetComputeRoot32BitConstants(index, count, data, offset);
    }
    void STDMETHODCALLTYPE SetGraphicsRoot32BitConstants(UINT index, UINT count, const void* data, UINT offset) override
    {
        X2W_USE();
        if (data) record_constants(index, count, data, offset);
        real_->SetGraphicsRoot32BitConstants(index, count, data, offset);
    }
    // Root GPU addresses: a title GPU address becomes its desktop alias (X2WTitleGpuTranslate); any other address
    // is passed through. A graphics address is also recorded as the title passed it, for the push words of a
    // translated pipeline.
    void STDMETHODCALLTYPE SetComputeRootConstantBufferView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        compute_.record_address(index, address);
        real_->SetComputeRootConstantBufferView(index, pipeline::translate_address(address, 4));
    }
    void STDMETHODCALLTYPE SetGraphicsRootConstantBufferView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        record_address(index, address);
        real_->SetGraphicsRootConstantBufferView(index, pipeline::translate_address(address, 4));
    }
    void STDMETHODCALLTYPE SetComputeRootShaderResourceView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        compute_.record_address(index, address);
        real_->SetComputeRootShaderResourceView(index, pipeline::translate_address(address, 4));
    }
    void STDMETHODCALLTYPE SetGraphicsRootShaderResourceView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        record_address(index, address);
        real_->SetGraphicsRootShaderResourceView(index, pipeline::translate_address(address, 4));
    }
    void STDMETHODCALLTYPE SetComputeRootUnorderedAccessView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        compute_.record_address(index, address);
        real_->SetComputeRootUnorderedAccessView(index, pipeline::translate_address(address, 4));
    }
    void STDMETHODCALLTYPE SetGraphicsRootUnorderedAccessView(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address) override
    {
        X2W_USE();
        record_address(index, address);
        real_->SetGraphicsRootUnorderedAccessView(index, pipeline::translate_address(address, 4));
    }
    void STDMETHODCALLTYPE IASetIndexBuffer(const D3D12_INDEX_BUFFER_VIEW* view) override
    {
        X2W_USE();
        if (view) {
            D3D12_INDEX_BUFFER_VIEW desktop = *view;
            desktop.BufferLocation = pipeline::translate_address(view->BufferLocation, view->SizeInBytes);
            real_->IASetIndexBuffer(&desktop);
            return;
        }
        real_->IASetIndexBuffer(view);
    }
    void STDMETHODCALLTYPE IASetVertexBuffers(UINT start, UINT count, const D3D12_VERTEX_BUFFER_VIEW* views) override
    {
        X2W_USE();
        if (views && count <= D3D12_IA_VERTEX_INPUT_RESOURCE_SLOT_COUNT) {
            D3D12_VERTEX_BUFFER_VIEW desktop[D3D12_IA_VERTEX_INPUT_RESOURCE_SLOT_COUNT];
            for (UINT i = 0; i < count; ++i) {
                desktop[i] = views[i];
                desktop[i].BufferLocation = pipeline::translate_address(views[i].BufferLocation, views[i].SizeInBytes);
            }
            real_->IASetVertexBuffers(start, count, desktop);
            return;
        }
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
        if (title_uav_clear(gpu, cpu)) return;
        real_->ClearUnorderedAccessViewUint(gpu, cpu, resource, values, count, rects);
    }
    void STDMETHODCALLTYPE ClearUnorderedAccessViewFloat(D3D12_GPU_DESCRIPTOR_HANDLE gpu, D3D12_CPU_DESCRIPTOR_HANDLE cpu,
                                                         ID3D12Resource* resource, const FLOAT values[4], UINT count,
                                                         const D3D12_RECT* rects) override
    {
        X2W_USE();
        if (title_uav_clear(gpu, cpu)) return;
        real_->ClearUnorderedAccessViewFloat(gpu, cpu, resource, values, count, rects);
    }
    // A UAV clear through title-heap handles needs a shader-visible desktop copy of the view; not translated yet.
    bool title_uav_clear(D3D12_GPU_DESCRIPTOR_HANDLE gpu, D3D12_CPU_DESCRIPTOR_HANDLE cpu)
    {
        if (!descriptors::is_title_handle(gpu.ptr) && !descriptors::is_title_handle(cpu.ptr)) return false;
        log_refused("d3d12_xs!ID3D12GraphicsCommandList::ClearUnorderedAccessView",
                    "a UAV clear through title-heap descriptors is not translated; not cleared", true);
        return true;
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

private:
    pipeline::RootArgs* args_;
    pipeline::RootInfo root_{};
    pipeline::PsoInfo pso_{};
    bool has_root_ = false;
    bool translated_ = false;
    bool ours_bound_ = false;
    pipeline::BoundHeaps heaps_;
    pipeline::BlockUse blocks_;  // the shim heap blocks this recording reads (R5 recycling)
    // Compute state (runtime rung R5): the compute root signature and arguments are separate from the graphics
    // ones in D3D12; the pipeline and the descriptor heaps are shared.
    struct ComputeState {
        pipeline::RootArgs* args = new (std::nothrow) pipeline::RootArgs();
        pipeline::RootInfo root{};
        pipeline::PsoInfo pso{};
        bool has_root = false;
        bool translated = false;
        void reset()
        {
            has_root = false;
            if (args) args->clear();
        }
        void set_root(ID3D12RootSignature* signature)
        {
            has_root = pipeline::root_info(signature, &root);
            if (args) args->clear();
        }
        void record_address(UINT index, D3D12_GPU_VIRTUAL_ADDRESS address)
        {
            if (args && index < pipeline::max_title_params) args->address[index] = address;
        }
        void record_constants(UINT index, UINT count, const void* data, UINT offset)
        {
            if (!args || index >= pipeline::max_title_params || offset >= 64 || count > 64 - offset) return;
            std::memcpy(&args->constants[index][offset], data, count * 4);
        }
        // Before a dispatch: the converter parameters of a translated pipeline. False skips it (logged).
        bool bind(pipeline::TitleViews* views, ID3D12GraphicsCommandList* list, const pipeline::BoundHeaps& heaps,
                  bool* ours_bound, pipeline::BlockUse* use)
        {
            if (!translated) {
                if (has_root) pipeline::set_compute_placeholders(list, root);
                return true;
            }
            if (!has_root || !args) {
                log_refused("d3d12_xs!ID3D12GraphicsCommandList::Dispatch",
                            "dispatch skipped: a translated pipeline dispatched without a compute root signature "
                            "created through the shim",
                            true);
                return false;
            }
            return pipeline::bind_for_dispatch(views, list, root, pso, *args, heaps, ours_bound, use);
        }
    } compute_;
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
        // Stamp the shim heap blocks the lists read with a fence the shim signals after them on this queue.
        std::vector<pipeline::BlockUse*> uses;
        for (UINT i = 0; i < count; ++i) {
            Kind kind;
            if (lists[i] && wrapper_kind(lists[i], &kind) && kind == Kind::list)
                uses.push_back(static_cast<List*>(lists[i])->blocks());
        }
        if (!uses.empty())
            pipeline::submitted_blocks(device_views(device_), real_, uses.data(), static_cast<unsigned>(uses.size()));
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
    explicit Device(ID3D12Device* real) : Wrapper(real), views_(pipeline::create_title_views(real)) { install(); }
    ~Device()
    {
        pipeline::destroy_title_views(views_);
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
    // Console shaders are translated here (d3d12_xs_pipeline.h); desktop bytecode is forwarded.
    HRESULT STDMETHODCALLTYPE CreateGraphicsPipelineState(const D3D12_GRAPHICS_PIPELINE_STATE_DESC* desc, REFIID riid,
                                                          void** out) override
    {
        X2W_USE();
        return pipeline::create_graphics_pipeline(real_, desc, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreateComputePipelineState(const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc, REFIID riid,
                                                         void** out) override
    {
        X2W_USE();
        return pipeline::create_compute_pipeline(real_, desc, riid, out);
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
    // CBV/SRV/UAV and sampler heaps are title heaps (d3d12_xs_descriptors.h) over a desktop shadow heap that is not
    // shader visible; RTV and DSV heaps are desktop heaps.
    HRESULT STDMETHODCALLTYPE CreateDescriptorHeap(const D3D12_DESCRIPTOR_HEAP_DESC* desc, REFIID riid,
                                                   void** out) override
    {
        X2W_USE();
        if (!desc || !out || !descriptors::title_increment(desc->Type)) return real_->CreateDescriptorHeap(desc, riid, out);
        *out = nullptr;
        D3D12_DESCRIPTOR_HEAP_DESC shadow_desc = *desc;
        shadow_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        ID3D12DescriptorHeap* shadow = nullptr;
        const HRESULT hr = real_->CreateDescriptorHeap(&shadow_desc, IID_PPV_ARGS(&shadow));
        if (FAILED(hr)) return hr;
        auto* heap = new (std::nothrow) DescriptorHeap(shadow, this);
        if (heap && !heap->init(real_, *desc)) {
            heap->Release();
            return E_OUTOFMEMORY;
        }
        return hand_out(heap, shadow, riid, out, X2W_RETURN_ADDRESS());
    }
    UINT STDMETHODCALLTYPE GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE type) override
    {
        X2W_USE();
        if (const UINT title = descriptors::title_increment(type)) return title;
        return real_->GetDescriptorHandleIncrementSize(type);
    }
    HRESULT STDMETHODCALLTYPE CreateRootSignature(UINT node_mask, const void* blob, SIZE_T size, REFIID riid,
                                                  void** out) override
    {
        X2W_USE();
        return pipeline::create_root_signature(real_, node_mask, blob, size, riid, out);
    }
    // Views in title heaps go to the shadow heap and are recorded (d3d12_xs_descriptors.h); a CBV's title GPU address
    // becomes its alias in the desktop view and stays recorded as the title passed it.
    void STDMETHODCALLTYPE CreateConstantBufferView(const D3D12_CONSTANT_BUFFER_VIEW_DESC* desc,
                                                    D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        D3D12_CONSTANT_BUFFER_VIEW_DESC desktop{};
        if (desc) {
            desktop = *desc;
            desktop.BufferLocation = pipeline::translate_address(desc->BufferLocation, desc->SizeInBytes);
        }
        if (descriptors::write_cbv(descriptor.ptr, desc, desc ? &desktop : nullptr)) return;
        real_->CreateConstantBufferView(desc ? &desktop : nullptr, descriptor);
    }
    void STDMETHODCALLTYPE CreateShaderResourceView(ID3D12Resource* resource, const D3D12_SHADER_RESOURCE_VIEW_DESC* desc,
                                                    D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        if (descriptors::write_srv(descriptor.ptr, resource, desc)) return;
        real_->CreateShaderResourceView(resource, desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateUnorderedAccessView(ID3D12Resource* resource, ID3D12Resource* counter,
                                                     const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc,
                                                     D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        if (descriptors::write_uav(descriptor.ptr, resource, counter, desc)) return;
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
        if (descriptors::write_sampler(descriptor.ptr, desc)) return;
        real_->CreateSampler(desc, descriptor);
    }
    // Copies between title heaps copy the shadow descriptors and their records; copies between desktop heaps are
    // forwarded. Ranges are walked descriptor by descriptor, as the desktop runtime pairs them.
    void STDMETHODCALLTYPE CopyDescriptors(UINT dst_count, const D3D12_CPU_DESCRIPTOR_HANDLE* dst_starts,
                                           const UINT* dst_sizes, UINT src_count,
                                           const D3D12_CPU_DESCRIPTOR_HANDLE* src_starts, const UINT* src_sizes,
                                           D3D12_DESCRIPTOR_HEAP_TYPE type) override
    {
        X2W_USE();
        bool title = false;
        for (UINT i = 0; dst_starts && i < dst_count; ++i) title = title || descriptors::is_title_handle(dst_starts[i].ptr);
        for (UINT i = 0; src_starts && i < src_count; ++i) title = title || descriptors::is_title_handle(src_starts[i].ptr);
        if (!title || !descriptors::title_increment(type)) {
            real_->CopyDescriptors(dst_count, dst_starts, dst_sizes, src_count, src_starts, src_sizes, type);
            return;
        }
        const UINT increment = descriptors::title_increment(type);
        UINT d = 0, s = 0, d_at = 0, s_at = 0;
        while (d < dst_count && s < src_count) {
            const UINT d_size = dst_sizes ? dst_sizes[d] : 1, s_size = src_sizes ? src_sizes[s] : 1;
            if (d_at == d_size) { ++d; d_at = 0; continue; }
            if (s_at == s_size) { ++s; s_at = 0; continue; }
            const UINT n = (d_size - d_at) < (s_size - s_at) ? d_size - d_at : s_size - s_at;
            descriptors::copy(n, dst_starts[d].ptr + std::uint64_t(d_at) * increment,
                              src_starts[s].ptr + std::uint64_t(s_at) * increment, type);
            d_at += n;
            s_at += n;
        }
    }
    void STDMETHODCALLTYPE CopyDescriptorsSimple(UINT count, D3D12_CPU_DESCRIPTOR_HANDLE dst,
                                                 D3D12_CPU_DESCRIPTOR_HANDLE src, D3D12_DESCRIPTOR_HEAP_TYPE type) override
    {
        X2W_USE();
        if (descriptors::title_increment(type) && descriptors::copy(count, dst.ptr, src.ptr, type)) return;
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

    pipeline::TitleViews* views() const { return views_; }

private:
    bool attached_ = false;
    void (*detach_)() = nullptr;
    pipeline::TitleViews* views_;
};

DeviceRef::DeviceRef(Device* device) : device_(device) { device_->AddRef(); }
DeviceRef::~DeviceRef() { device_->Release(); }

HRESULT device_query(Device* device, REFIID riid, void** out, const void* caller)
{
    return device->query(riid, out, caller);
}

pipeline::TitleViews* device_views(Device* device) { return device->views(); }

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
              std::is_final_v<List> && std::is_final_v<Fence> && std::is_final_v<SwapChain> &&
              std::is_final_v<DescriptorHeap>);

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
    case Kind::descriptor_heap:
        return static_cast<DescriptorHeap*>(static_cast<ID3D12DescriptorHeap*>(base))->real();
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
    pipeline::prestart_translator();
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
