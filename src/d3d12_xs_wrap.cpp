// Wrapper objects of the d3d12_xs.dll graphics shim (d3d12_xs_wrap.h).
//
// Each wrapper is a final class with single inheritance from the public desktop interface, so its
// compiler vtable is exactly the public method order; install_vtable then swaps in a copy that
// continues with logging thunks. No wrapper declares a virtual destructor or any virtual method
// beyond the interface. Methods forward to the desktop object and log their first use.
#include "d3d12_xs_wrap.h"
#include "d3d12_xs_api.h"
#include "d3d12_xs_descriptors.h"
#include "d3d12_xs_indirect.h"
#include "d3d12_xs_pipeline.h"
#include "d3d12_xs_resources.h"

#include <d3d12sdklayers.h>
#include <dxgi1_4.h>
#include <wrl/client.h>

#include <atomic>
#include <cstdint>
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

// A method of a later interface version that the desktop object does not implement: logged once, then the method
// returns the given value (nothing for void). A title only reaches it through a vtable it did not QueryInterface for.
void log_missing_version(Kind kind, const char* method)
{
    char symbol[160];
    std::snprintf(symbol, sizeof(symbol), "d3d12_xs!%s::%s", interface_name(kind), method);
    log_refused_call(symbol, "the desktop object does not implement the interface version of this method; not called");
}
#define X2W_REQUIRE(version, ...)                                                                \
    do {                                                                                         \
        if (!(version)) {                                                                        \
            log_missing_version(kind, __func__);                                                 \
            return __VA_ARGS__;                                                                  \
        }                                                                                        \
    } while (0)

// Refuses a call with a logged reason: "<interface>::<method>: <why>".
void refuse_call(Kind kind, const char* method, const char* why)
{
    char symbol[160];
    std::snprintf(symbol, sizeof(symbol), "d3d12_xs!%s::%s", interface_name(kind), method);
    log_refused_call(symbol, why);
}
#define X2W_REFUSE(why) refuse_call(kind, __func__, why)

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
    using interface_type = Interface;

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
        if (IsEqualIID(riid, __uuidof(IUnknown)) || static_cast<Derived*>(this)->implements(riid)) {
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

// IIDs D3D12XboxCreateDevice handed the device out through without knowing them (alias_device_iid): the device
// answers QueryInterface for them with itself, so a title that asks again for its console device IID gets the
// same object.
constexpr unsigned max_device_aliases = 8;
GUID g_device_aliases[max_device_aliases];
std::atomic<unsigned> g_device_alias_count;
SRWLOCK g_alias_lock = SRWLOCK_INIT;

bool is_device_alias(REFIID riid)
{
    AcquireSRWLockShared(&g_alias_lock);
    bool found = false;
    for (unsigned i = 0; i < g_device_alias_count.load() && !found; ++i) found = IsEqualGUID(g_device_aliases[i], riid);
    ReleaseSRWLockShared(&g_alias_lock);
    return found;
}

class Device;
std::atomic<Device*> g_attached_device;
HRESULT device_query(Device* device, REFIID riid, void** out, const void* caller);
pipeline::TitleViews* device_views(Device* device);
indirect::Rewriter* device_rewriter(Device* device);

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
    ~Allocator() { indirect::recycle(keep_); }
    static bool implements(REFIID riid)
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12CommandAllocator));
    }
    // The shim's buffers that lists recording into this allocator read (ExecuteIndirect rewrites).
    indirect::Keep& keep() { return keep_; }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
    // A reset allocator's command memory is free, so the GPU has finished its lists: their rewrite buffers are too.
    HRESULT STDMETHODCALLTYPE Reset() override
    {
        X2W_USE();
        const HRESULT hr = real_->Reset();
        if (SUCCEEDED(hr)) indirect::recycle(keep_);
        return hr;
    }

private:
    indirect::Keep keep_;
};

D3D12_RESOURCE_DESC resource_desc(ID3D12Resource* resource)
{
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_DESC desc{};
    resource->GetDesc(&desc);
    return desc;
#else
    return resource->GetDesc();
#endif
}
D3D12_HEAP_DESC heap_desc(ID3D12Heap* heap)
{
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_HEAP_DESC desc{};
    heap->GetDesc(&desc);
    return desc;
#else
    return heap->GetDesc();
#endif
}

// A resource the title created through the device (d3d12_xs_resources.h): a buffer's GPU virtual address is its
// title address. real_ is the desktop resource.
class Resource final : public Wrapper<Resource, ID3D12Resource2, Kind::resource>, DeviceRef {
public:
    Resource(ID3D12Resource* real, Device* device, const resources::TitleAddress& address)
        : Wrapper(static_cast<ID3D12Resource2*>(real)), DeviceRef(device), address_(address)
    {
        real->QueryInterface(IID_PPV_ARGS(&r1_));
        real->QueryInterface(IID_PPV_ARGS(&r2_));
        install();
    }
    ~Resource() { resources::release(real_, address_); }
    bool implements(REFIID riid) const
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12Resource)) ||
               (r1_ && IsEqualIID(riid, __uuidof(ID3D12Resource1))) ||
               (r2_ && IsEqualIID(riid, __uuidof(ID3D12Resource2)));
    }
    std::uint64_t title_address() const { return address_.title; }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
    HRESULT STDMETHODCALLTYPE Map(UINT subresource, const D3D12_RANGE* range, void** data) override
    {
        X2W_USE();
        return real_->Map(subresource, range, data);
    }
    void STDMETHODCALLTYPE Unmap(UINT subresource, const D3D12_RANGE* range) override
    {
        X2W_USE();
        real_->Unmap(subresource, range);
    }
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_DESC* STDMETHODCALLTYPE GetDesc(D3D12_RESOURCE_DESC* ret) override
    {
        X2W_USE();
        return real_->GetDesc(ret);
    }
#else
    D3D12_RESOURCE_DESC STDMETHODCALLTYPE GetDesc() override
    {
        X2W_USE();
        return real_->GetDesc();
    }
#endif
    D3D12_GPU_VIRTUAL_ADDRESS STDMETHODCALLTYPE GetGPUVirtualAddress() override
    {
        X2W_USE();
        return address_.title;
    }
    HRESULT STDMETHODCALLTYPE WriteToSubresource(UINT subresource, const D3D12_BOX* box, const void* data, UINT row_pitch,
                                                 UINT depth_pitch) override
    {
        X2W_USE();
        return real_->WriteToSubresource(subresource, box, data, row_pitch, depth_pitch);
    }
    HRESULT STDMETHODCALLTYPE ReadFromSubresource(void* data, UINT row_pitch, UINT depth_pitch, UINT subresource,
                                                  const D3D12_BOX* box) override
    {
        X2W_USE();
        return real_->ReadFromSubresource(data, row_pitch, depth_pitch, subresource, box);
    }
    HRESULT STDMETHODCALLTYPE GetHeapProperties(D3D12_HEAP_PROPERTIES* properties, D3D12_HEAP_FLAGS* flags) override
    {
        X2W_USE();
        return real_->GetHeapProperties(properties, flags);
    }
    HRESULT STDMETHODCALLTYPE GetProtectedResourceSession(REFIID riid, void** session) override
    {
        X2W_USE();
        X2W_REQUIRE(r1_, E_NOINTERFACE);
        return r1_->GetProtectedResourceSession(riid, session);
    }
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_DESC1* STDMETHODCALLTYPE GetDesc1(D3D12_RESOURCE_DESC1* ret) override
    {
        X2W_USE();
        if (!r2_) {
            *ret = {};
            X2W_REQUIRE(r2_, ret);
        }
        return r2_->GetDesc1(ret);
    }
#else
    D3D12_RESOURCE_DESC1 STDMETHODCALLTYPE GetDesc1() override
    {
        X2W_USE();
        X2W_REQUIRE(r2_, D3D12_RESOURCE_DESC1{});
        return r2_->GetDesc1();
    }
#endif

private:
    resources::TitleAddress address_;
    ComPtr<ID3D12Resource1> r1_;
    ComPtr<ID3D12Resource2> r2_;
};

// A heap the title created or opened through the device. `existing_address` is the address an existing heap was
// opened from (OpenExistingHeapFromAddress), so buffers placed in it get title addresses inside that memory.
class Heap final : public Wrapper<Heap, ID3D12Heap1, Kind::heap>, DeviceRef {
public:
    Heap(ID3D12Heap* real, Device* device, std::uint64_t existing_address)
        : Wrapper(static_cast<ID3D12Heap1*>(real)), DeviceRef(device), existing_address_(existing_address)
    {
        real->QueryInterface(IID_PPV_ARGS(&h1_));
        install();
    }
    bool implements(REFIID riid) const
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12Heap)) ||
               (h1_ && IsEqualIID(riid, __uuidof(ID3D12Heap1)));
    }
    std::uint64_t existing_address() const { return existing_address_; }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_HEAP_DESC* STDMETHODCALLTYPE GetDesc(D3D12_HEAP_DESC* ret) override
    {
        X2W_USE();
        return real_->GetDesc(ret);
    }
#else
    D3D12_HEAP_DESC STDMETHODCALLTYPE GetDesc() override
    {
        X2W_USE();
        return real_->GetDesc();
    }
#endif
    HRESULT STDMETHODCALLTYPE GetProtectedResourceSession(REFIID riid, void** session) override
    {
        X2W_USE();
        X2W_REQUIRE(h1_, E_NOINTERFACE);
        return h1_->GetProtectedResourceSession(riid, session);
    }

private:
    std::uint64_t existing_address_;
    ComPtr<ID3D12Heap1> h1_;
};

// A command signature with the layout of its records (d3d12_xs_indirect.h).
class CommandSignature final : public Wrapper<CommandSignature, ID3D12CommandSignature, Kind::command_signature>,
                               DeviceRef {
public:
    CommandSignature(ID3D12CommandSignature* real, Device* device, const indirect::Layout& layout)
        : Wrapper(real), DeviceRef(device), layout_(layout)
    {
        install();
    }
    static bool implements(REFIID riid)
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12CommandSignature));
    }
    const indirect::Layout& layout() const { return layout_; }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS

private:
    indirect::Layout layout_;
};

template <class W>
W* as_wrapper(const void* object, Kind want)
{
    Kind kind;
    if (!wrapper_kind(object, &kind) || kind != want) return nullptr;
    return static_cast<W*>(reinterpret_cast<typename W::interface_type*>(const_cast<void*>(object)));
}

// The private-data key that marks a state object whose subobjects include a local root signature (DispatchRays
// refuses it: its shader records may hold title addresses or title descriptor handles).
constexpr GUID local_root_guid = {0x6b1a3c52, 0x0f6e, 0x4f0e, {0x9a, 0x5d, 0x58, 0x32, 0x57, 0x52, 0xe0, 0x10}};

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

// An RTV or DSV heap: desktop descriptors, forwarded unchanged. Wrapped only so its vtable continues with the
// logging thunks (a console-only method past the public slots is logged, not a jump past the desktop vtable) and
// QueryInterface logs IIDs it does not know.
class ViewHeap final : public Wrapper<ViewHeap, ID3D12DescriptorHeap, Kind::view_heap>, DeviceRef {
public:
    ViewHeap(ID3D12DescriptorHeap* real, Device* device) : Wrapper(real), DeviceRef(device) { install(); }
    static bool implements(REFIID riid)
    {
        return is_pageable_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12DescriptorHeap));
    }

    X2W_D3D12_OBJECT_METHODS
    X2W_DEVICE_CHILD_METHODS
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_DESCRIPTOR_HEAP_DESC* STDMETHODCALLTYPE GetDesc(D3D12_DESCRIPTOR_HEAP_DESC* ret) override
    {
        X2W_USE();
        return real_->GetDesc(ret);
    }
    D3D12_CPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE GetCPUDescriptorHandleForHeapStart(D3D12_CPU_DESCRIPTOR_HANDLE* ret) override
    {
        X2W_USE();
        return real_->GetCPUDescriptorHandleForHeapStart(ret);
    }
    D3D12_GPU_DESCRIPTOR_HANDLE* STDMETHODCALLTYPE GetGPUDescriptorHandleForHeapStart(D3D12_GPU_DESCRIPTOR_HANDLE* ret) override
    {
        X2W_USE();
        return real_->GetGPUDescriptorHandleForHeapStart(ret);
    }
#else
    D3D12_DESCRIPTOR_HEAP_DESC STDMETHODCALLTYPE GetDesc() override
    {
        X2W_USE();
        return real_->GetDesc();
    }
    D3D12_CPU_DESCRIPTOR_HANDLE STDMETHODCALLTYPE GetCPUDescriptorHandleForHeapStart() override
    {
        X2W_USE();
        return real_->GetCPUDescriptorHandleForHeapStart();
    }
    D3D12_GPU_DESCRIPTOR_HANDLE STDMETHODCALLTYPE GetGPUDescriptorHandleForHeapStart() override
    {
        X2W_USE();
        return real_->GetGPUDescriptorHandleForHeapStart();
    }
#endif
};

// The title heap behind a wrapper, or null for a desktop heap.
const descriptors::Heap* title_heap(ID3D12DescriptorHeap* heap)
{
    Kind kind;
    if (!wrapper_kind(heap, &kind) || kind != Kind::descriptor_heap) return nullptr;
    return &static_cast<DescriptorHeap*>(heap)->state();
}

class List final : public Wrapper<List, ID3D12GraphicsCommandList7, Kind::list>, DeviceRef {
public:
    List(ID3D12GraphicsCommandList* real, Device* device, Allocator* allocator, ID3D12PipelineState* state)
        : Wrapper(static_cast<ID3D12GraphicsCommandList7*>(real)), DeviceRef(device),
          args_(new (std::nothrow) pipeline::RootArgs()), replay_(new (std::nothrow) ComputeReplay()),
          allocator_(allocator), current_pso_(state)
    {
        if (args_) args_->clear();
        if (replay_) replay_->clear();
        real->QueryInterface(IID_PPV_ARGS(&l1_));
        real->QueryInterface(IID_PPV_ARGS(&l2_));
        real->QueryInterface(IID_PPV_ARGS(&l3_));
        real->QueryInterface(IID_PPV_ARGS(&l4_));
        real->QueryInterface(IID_PPV_ARGS(&l5_));
        real->QueryInterface(IID_PPV_ARGS(&l6_));
        real->QueryInterface(IID_PPV_ARGS(&l7_));
        install();
    }
    ~List()
    {
        pipeline::release_blocks(device_views(device_), blocks_);
        delete args_;
        delete compute_.args;
        delete replay_;
    }
    pipeline::BlockUse* blocks() { return &blocks_; }
    bool implements(REFIID riid) const
    {
        return is_d3d12_child_iid(riid) || IsEqualIID(riid, __uuidof(ID3D12CommandList)) ||
               IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList)) ||
               (l1_ && IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList1))) ||
               (l2_ && IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList2))) ||
               (l3_ && IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList3))) ||
               (l4_ && IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList4))) ||
               (l5_ && IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList5))) ||
               (l6_ && IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList6))) ||
               (l7_ && IsEqualIID(riid, __uuidof(ID3D12GraphicsCommandList7)));
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
        compute_root_ = nullptr;
        if (replay_) replay_->clear();
        predication_ = {};
        in_render_pass_ = false;
        enhanced_ = false;
        state_object_local_root_ = false;
    }
    void set_pipeline(ID3D12PipelineState* state)
    {
        current_pso_ = state;
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
        allocator_ = as_wrapper<Allocator>(allocator, Kind::allocator);
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
        real_->CopyBufferRegion(unwrap(dst), dst_offset, unwrap(src), src_offset, bytes);
    }
    void STDMETHODCALLTYPE CopyTextureRegion(const D3D12_TEXTURE_COPY_LOCATION* dst, UINT x, UINT y, UINT z,
                                             const D3D12_TEXTURE_COPY_LOCATION* src, const D3D12_BOX* box) override
    {
        X2W_USE();
        D3D12_TEXTURE_COPY_LOCATION d{}, s{};
        if (dst) {
            d = *dst;
            d.pResource = unwrap(dst->pResource);
        }
        if (src) {
            s = *src;
            s.pResource = unwrap(src->pResource);
        }
        real_->CopyTextureRegion(dst ? &d : nullptr, x, y, z, src ? &s : nullptr, box);
    }
    void STDMETHODCALLTYPE CopyResource(ID3D12Resource* dst, ID3D12Resource* src) override
    {
        X2W_USE();
        real_->CopyResource(unwrap(dst), unwrap(src));
    }
    void STDMETHODCALLTYPE CopyTiles(ID3D12Resource* tiled, const D3D12_TILED_RESOURCE_COORDINATE* start,
                                     const D3D12_TILE_REGION_SIZE* size, ID3D12Resource* buffer, UINT64 offset,
                                     D3D12_TILE_COPY_FLAGS flags) override
    {
        X2W_USE();
        real_->CopyTiles(unwrap(tiled), start, size, unwrap(buffer), offset, flags);
    }
    void STDMETHODCALLTYPE ResolveSubresource(ID3D12Resource* dst, UINT dst_sub, ID3D12Resource* src, UINT src_sub,
                                              DXGI_FORMAT format) override
    {
        X2W_USE();
        real_->ResolveSubresource(unwrap(dst), dst_sub, unwrap(src), src_sub, format);
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
        std::vector<D3D12_RESOURCE_BARRIER> desktop;
        if (!barriers || !count) {
            real_->ResourceBarrier(count, barriers);
            return;
        }
        try {
            desktop.assign(barriers, barriers + count);
        } catch (...) {
            X2W_REFUSE("out of memory unwrapping barriers; not recorded");
            return;
        }
        for (D3D12_RESOURCE_BARRIER& b : desktop) {
            if (b.Type == D3D12_RESOURCE_BARRIER_TYPE_TRANSITION) {
                b.Transition.pResource = unwrap(b.Transition.pResource);
            } else if (b.Type == D3D12_RESOURCE_BARRIER_TYPE_ALIASING) {
                b.Aliasing.pResourceBefore = unwrap(b.Aliasing.pResourceBefore);
                b.Aliasing.pResourceAfter = unwrap(b.Aliasing.pResourceAfter);
            } else if (b.Type == D3D12_RESOURCE_BARRIER_TYPE_UAV) {
                b.UAV.pResource = unwrap(b.UAV.pResource);
            }
        }
        real_->ResourceBarrier(count, desktop.data());
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
        compute_root_ = root;
        if (replay_) replay_->clear();
        real_->SetComputeRootSignature(root);
    }
    void STDMETHODCALLTYPE SetGraphicsRootSignature(ID3D12RootSignature* root) override
    {
        X2W_USE();
        has_root_ = pipeline::root_info(root, &root_);
        if (args_) args_->clear();
        real_->SetGraphicsRootSignature(root);
    }
    // As SetGraphicsRootDescriptorTable (R6): a table of a title compute root signature is recorded for
    // bind_for_dispatch.
    void STDMETHODCALLTYPE SetComputeRootDescriptorTable(UINT index, D3D12_GPU_DESCRIPTOR_HANDLE base) override
    {
        X2W_USE();
        if (compute_.has_root && index < compute_.root.title_params &&
            compute_.root.types[index] == D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE) {
            compute_.record_address(index, base.ptr);
            return;
        }
        if (descriptors::is_title_handle(base.ptr)) {
            log_refused("d3d12_xs!ID3D12GraphicsCommandList::SetComputeRootDescriptorTable",
                        "a title-heap table for a root signature not created through the shim; not set", true);
            return;
        }
        if (replay_) replay_->table(index, base);
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
        if (replay_) replay_->constants(index, 1, &data, offset);
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
        if (data && replay_) replay_->constants(index, count, data, offset);
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
        const D3D12_GPU_VIRTUAL_ADDRESS desktop = pipeline::translate_address(address, 4);
        if (replay_) replay_->view(index, ComputeReplay::cbv, desktop);
        real_->SetComputeRootConstantBufferView(index, desktop);
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
        const D3D12_GPU_VIRTUAL_ADDRESS desktop = pipeline::translate_address(address, 4);
        if (replay_) replay_->view(index, ComputeReplay::srv, desktop);
        real_->SetComputeRootShaderResourceView(index, desktop);
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
        const D3D12_GPU_VIRTUAL_ADDRESS desktop = pipeline::translate_address(address, 4);
        if (replay_) replay_->view(index, ComputeReplay::uav, desktop);
        real_->SetComputeRootUnorderedAccessView(index, desktop);
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
        if (views && count <= D3D12_SO_BUFFER_SLOT_COUNT) {
            D3D12_STREAM_OUTPUT_BUFFER_VIEW desktop[D3D12_SO_BUFFER_SLOT_COUNT];
            for (UINT i = 0; i < count; ++i) {
                desktop[i] = views[i];
                desktop[i].BufferLocation = pipeline::translate_address(views[i].BufferLocation, views[i].SizeInBytes);
                desktop[i].BufferFilledSizeLocation = pipeline::translate_address(views[i].BufferFilledSizeLocation, 4);
            }
            real_->SOSetTargets(start, count, desktop);
            return;
        }
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
        real_->ClearUnorderedAccessViewUint(gpu, cpu, unwrap(resource), values, count, rects);
    }
    void STDMETHODCALLTYPE ClearUnorderedAccessViewFloat(D3D12_GPU_DESCRIPTOR_HANDLE gpu, D3D12_CPU_DESCRIPTOR_HANDLE cpu,
                                                         ID3D12Resource* resource, const FLOAT values[4], UINT count,
                                                         const D3D12_RECT* rects) override
    {
        X2W_USE();
        if (title_uav_clear(gpu, cpu)) return;
        real_->ClearUnorderedAccessViewFloat(gpu, cpu, unwrap(resource), values, count, rects);
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
        real_->DiscardResource(unwrap(resource), region);
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
        real_->ResolveQueryData(heap, type, start, count, unwrap(dst), offset);
    }
    void STDMETHODCALLTYPE SetPredication(ID3D12Resource* buffer, UINT64 offset, D3D12_PREDICATION_OP op) override
    {
        X2W_USE();
        predication_ = {unwrap(buffer), offset, op};
        real_->SetPredication(unwrap(buffer), offset, op);
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
    // ExecuteIndirect (d3d12_xs_indirect.h): records with title addresses are rewritten by a compute pass first.
    void STDMETHODCALLTYPE ExecuteIndirect(ID3D12CommandSignature* signature, UINT max_commands, ID3D12Resource* args,
                                           UINT64 args_offset, ID3D12Resource* count, UINT64 count_offset) override
    {
        X2W_USE();
        const CommandSignature* wrapped = as_wrapper<CommandSignature>(signature, Kind::command_signature);
        if (!wrapped) {
            X2W_REFUSE("a command signature not created through the shim (its records are unknown); not executed");
            return;
        }
        const indirect::Layout& layout = wrapped->layout();
        if (layout.refused) {
            X2W_REFUSE((std::string(layout.refused) + "; not executed").c_str());
            return;
        }
        const bool dispatch = layout.op == indirect::Op::dispatch;
        if (dispatch ? compute_.translated : translated_) {
            log_refused("d3d12_xs!ID3D12GraphicsCommandList::ExecuteIndirect",
                        "indirect commands with a translated pipeline are not executed: its converter parameters "
                        "(push words, draw bases) come from root arguments recorded on the CPU",
                        true);
            return;
        }
        ID3D12Resource* desktop_args = unwrap(args);
        ID3D12Resource* executed = desktop_args;
        UINT64 executed_offset = args_offset;
        if (layout.field_count && max_commands) {
            if (real_->GetType() == D3D12_COMMAND_LIST_TYPE_BUNDLE || in_render_pass_) {
                log_refused("d3d12_xs!ID3D12GraphicsCommandList::ExecuteIndirect",
                            "indirect records with GPU addresses in a bundle or a render pass: the address rewrite "
                            "needs a dispatch, which is not allowed there; not executed",
                            true);
                return;
            }
            if (!allocator_ || !desktop_args) {
                log_refused("d3d12_xs!ID3D12GraphicsCommandList::ExecuteIndirect",
                            "indirect records with GPU addresses without a shim allocator or argument buffer; not "
                            "executed",
                            true);
                return;
            }
            // Only records the argument buffer holds can be read; the copy still has room for max_commands.
            const UINT64 width = resource_desc(desktop_args).Width;
            const UINT64 available = width > args_offset ? (width - args_offset) / layout.stride : 0;
            const UINT commands = static_cast<UINT>(available < max_commands ? available : max_commands);
            if (UINT64(max_commands) * layout.stride > (UINT64(256) << 20) || !commands) {
                log_refused("d3d12_xs!ID3D12GraphicsCommandList::ExecuteIndirect",
                            "indirect records with GPU addresses: no record fits the argument buffer, or more than "
                            "256 MiB of records; not executed",
                            true);
                return;
            }
            if (predication_.buffer) real_->SetPredication(nullptr, 0, D3D12_PREDICATION_OP_EQUAL_ZERO);
            std::string why;
            ID3D12Resource* rewritten = nullptr;
            const bool good = indirect::record(device_rewriter(device_), real_, enhanced_ ? l7_.Get() : nullptr,
                                               desktop_args, args_offset, commands, layout, allocator_->keep(),
                                               &rewritten, why);
            // The pass set its own pipeline and compute root signature (and suspended predication): restore them.
            if (current_pso_) real_->SetPipelineState(current_pso_);
            if (compute_root_) {
                real_->SetComputeRootSignature(compute_root_);
                if (replay_) replay_->apply(real_);
            }
            if (predication_.buffer) real_->SetPredication(predication_.buffer, predication_.offset, predication_.op);
            if (!good) {
                log_refused("d3d12_xs!ID3D12GraphicsCommandList::ExecuteIndirect",
                            ("indirect records with GPU addresses not rewritten: " + why + "; not executed").c_str(),
                            true);
                return;
            }
            executed = rewritten;
            executed_offset = 0;
        }
        if (dispatch) {
            if (!compute_.bind(device_views(device_), real_, heaps_, &ours_bound_, &blocks_)) return;
        } else if (!bind_draw(0, 0)) {
            return;
        }
        real_->ExecuteIndirect(unwrap(signature), max_commands, executed, executed_offset, unwrap(count), count_offset);
    }

    // ID3D12GraphicsCommandList1
    void STDMETHODCALLTYPE AtomicCopyBufferUINT(ID3D12Resource* dst, UINT64 dst_offset, ID3D12Resource* src,
                                                UINT64 src_offset, UINT dependencies,
                                                ID3D12Resource* const* dependent_resources,
                                                const D3D12_SUBRESOURCE_RANGE_UINT64* ranges) override
    {
        X2W_USE();
        X2W_REQUIRE(l1_);
        std::vector<ID3D12Resource*> deps;
        if (dependent_resources && !unwrap_array(dependencies, dependent_resources, deps)) return;
        l1_->AtomicCopyBufferUINT(unwrap(dst), dst_offset, unwrap(src), src_offset, dependencies,
                                  dependent_resources ? deps.data() : nullptr, ranges);
    }
    void STDMETHODCALLTYPE AtomicCopyBufferUINT64(ID3D12Resource* dst, UINT64 dst_offset, ID3D12Resource* src,
                                                  UINT64 src_offset, UINT dependencies,
                                                  ID3D12Resource* const* dependent_resources,
                                                  const D3D12_SUBRESOURCE_RANGE_UINT64* ranges) override
    {
        X2W_USE();
        X2W_REQUIRE(l1_);
        std::vector<ID3D12Resource*> deps;
        if (dependent_resources && !unwrap_array(dependencies, dependent_resources, deps)) return;
        l1_->AtomicCopyBufferUINT64(unwrap(dst), dst_offset, unwrap(src), src_offset, dependencies,
                                    dependent_resources ? deps.data() : nullptr, ranges);
    }
    void STDMETHODCALLTYPE OMSetDepthBounds(FLOAT min, FLOAT max) override
    {
        X2W_USE();
        X2W_REQUIRE(l1_);
        l1_->OMSetDepthBounds(min, max);
    }
    void STDMETHODCALLTYPE SetSamplePositions(UINT per_pixel, UINT pixels, D3D12_SAMPLE_POSITION* positions) override
    {
        X2W_USE();
        X2W_REQUIRE(l1_);
        l1_->SetSamplePositions(per_pixel, pixels, positions);
    }
    void STDMETHODCALLTYPE ResolveSubresourceRegion(ID3D12Resource* dst, UINT dst_sub, UINT x, UINT y,
                                                    ID3D12Resource* src, UINT src_sub, D3D12_RECT* rect,
                                                    DXGI_FORMAT format, D3D12_RESOLVE_MODE mode) override
    {
        X2W_USE();
        X2W_REQUIRE(l1_);
        l1_->ResolveSubresourceRegion(unwrap(dst), dst_sub, x, y, unwrap(src), src_sub, rect, format, mode);
    }
    void STDMETHODCALLTYPE SetViewInstanceMask(UINT mask) override
    {
        X2W_USE();
        X2W_REQUIRE(l1_);
        l1_->SetViewInstanceMask(mask);
    }
    // ID3D12GraphicsCommandList2: the destinations are GPU addresses (title addresses translated).
    void STDMETHODCALLTYPE WriteBufferImmediate(UINT count, const D3D12_WRITEBUFFERIMMEDIATE_PARAMETER* params,
                                                const D3D12_WRITEBUFFERIMMEDIATE_MODE* modes) override
    {
        X2W_USE();
        X2W_REQUIRE(l2_);
        std::vector<D3D12_WRITEBUFFERIMMEDIATE_PARAMETER> desktop;
        if (params && count) {
            try {
                desktop.assign(params, params + count);
            } catch (...) {
                return;
            }
            for (auto& p : desktop) p.Dest = pipeline::translate_address(p.Dest, 4);
        }
        l2_->WriteBufferImmediate(count, params ? desktop.data() : nullptr, modes);
    }
    // ID3D12GraphicsCommandList3
    void STDMETHODCALLTYPE SetProtectedResourceSession(ID3D12ProtectedResourceSession* session) override
    {
        X2W_USE();
        X2W_REQUIRE(l3_);
        l3_->SetProtectedResourceSession(session);
    }
    // ID3D12GraphicsCommandList4
    void STDMETHODCALLTYPE BeginRenderPass(UINT count, const D3D12_RENDER_PASS_RENDER_TARGET_DESC* targets,
                                           const D3D12_RENDER_PASS_DEPTH_STENCIL_DESC* depth,
                                           D3D12_RENDER_PASS_FLAGS flags) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        const auto unwrap_ending = [](D3D12_RENDER_PASS_ENDING_ACCESS& e) {
            if (e.Type == D3D12_RENDER_PASS_ENDING_ACCESS_TYPE_RESOLVE) {
                e.Resolve.pSrcResource = unwrap(e.Resolve.pSrcResource);
                e.Resolve.pDstResource = unwrap(e.Resolve.pDstResource);
            }
        };
        std::vector<D3D12_RENDER_PASS_RENDER_TARGET_DESC> rts;
        if (targets && count) {
            try {
                rts.assign(targets, targets + count);
            } catch (...) {
                return;
            }
            for (auto& rt : rts) unwrap_ending(rt.EndingAccess);
        }
        D3D12_RENDER_PASS_DEPTH_STENCIL_DESC ds{};
        if (depth) {
            ds = *depth;
            unwrap_ending(ds.DepthEndingAccess);
            unwrap_ending(ds.StencilEndingAccess);
        }
        in_render_pass_ = true;
        l4_->BeginRenderPass(count, targets ? rts.data() : nullptr, depth ? &ds : nullptr, flags);
    }
    void STDMETHODCALLTYPE EndRenderPass() override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        in_render_pass_ = false;
        l4_->EndRenderPass();
    }
    // Meta commands cannot exist here: ID3D12Device5::CreateMetaCommand is refused.
    void STDMETHODCALLTYPE InitializeMetaCommand(ID3D12MetaCommand* command, const void* data, SIZE_T size) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        l4_->InitializeMetaCommand(command, data, size);
    }
    void STDMETHODCALLTYPE ExecuteMetaCommand(ID3D12MetaCommand* command, const void* data, SIZE_T size) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        l4_->ExecuteMetaCommand(command, data, size);
    }
    // Acceleration structures: the addresses in the description are translated on the CPU. Bottom-level geometry
    // descriptions are CPU memory and are translated too; a top-level build reads instance descriptions (holding
    // bottom-level addresses) from GPU memory, which the shim does not rewrite yet, so it is refused.
    void STDMETHODCALLTYPE BuildRaytracingAccelerationStructure(
        const D3D12_BUILD_RAYTRACING_ACCELERATION_STRUCTURE_DESC* desc, UINT postbuild_count,
        const D3D12_RAYTRACING_ACCELERATION_STRUCTURE_POSTBUILD_INFO_DESC* postbuild) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        if (!desc) return;
        D3D12_BUILD_RAYTRACING_ACCELERATION_STRUCTURE_DESC copy = *desc;
        copy.DestAccelerationStructureData = pipeline::translate_address(desc->DestAccelerationStructureData, 4);
        copy.SourceAccelerationStructureData = pipeline::translate_address(desc->SourceAccelerationStructureData, 4);
        copy.ScratchAccelerationStructureData = pipeline::translate_address(desc->ScratchAccelerationStructureData, 4);
        std::vector<D3D12_RAYTRACING_GEOMETRY_DESC> geometry;
        std::vector<const D3D12_RAYTRACING_GEOMETRY_DESC*> pointers;
        if (desc->Inputs.Type == D3D12_RAYTRACING_ACCELERATION_STRUCTURE_TYPE_TOP_LEVEL) {
            if (desc->Inputs.NumDescs) {
                X2W_REFUSE("a top-level build with instances: the instance descriptions in GPU memory hold title "
                           "addresses of bottom-level structures, which are not rewritten; not built");
                return;
            }
        } else {
            try {
                geometry.resize(desc->Inputs.NumDescs);
                pointers.resize(desc->Inputs.NumDescs);
            } catch (...) {
                return;
            }
            for (UINT i = 0; i < desc->Inputs.NumDescs; ++i) {
                const D3D12_RAYTRACING_GEOMETRY_DESC* g =
                    desc->Inputs.DescsLayout == D3D12_ELEMENTS_LAYOUT_ARRAY ? &desc->Inputs.pGeometryDescs[i]
                                                                           : desc->Inputs.ppGeometryDescs[i];
                geometry[i] = *g;
                if (g->Type == D3D12_RAYTRACING_GEOMETRY_TYPE_TRIANGLES) {
                    auto& t = geometry[i].Triangles;
                    t.Transform3x4 = pipeline::translate_address(t.Transform3x4, 48);
                    t.IndexBuffer = pipeline::translate_address(t.IndexBuffer, 4);
                    t.VertexBuffer.StartAddress = pipeline::translate_address(t.VertexBuffer.StartAddress, 4);
                } else if (g->Type == D3D12_RAYTRACING_GEOMETRY_TYPE_PROCEDURAL_PRIMITIVE_AABBS) {
                    auto& b = geometry[i].AABBs;
                    b.AABBs.StartAddress = pipeline::translate_address(b.AABBs.StartAddress, 4);
                } else {
                    X2W_REFUSE("a geometry type the shim does not know; not built");
                    return;
                }
                pointers[i] = &geometry[i];
            }
            if (desc->Inputs.DescsLayout == D3D12_ELEMENTS_LAYOUT_ARRAY) copy.Inputs.pGeometryDescs = geometry.data();
            else copy.Inputs.ppGeometryDescs = pointers.data();
        }
        std::vector<D3D12_RAYTRACING_ACCELERATION_STRUCTURE_POSTBUILD_INFO_DESC> post;
        if (postbuild && postbuild_count) {
            try {
                post.assign(postbuild, postbuild + postbuild_count);
            } catch (...) {
                return;
            }
            for (auto& p : post) p.DestBuffer = pipeline::translate_address(p.DestBuffer, 8);
        }
        l4_->BuildRaytracingAccelerationStructure(&copy, postbuild_count, postbuild ? post.data() : nullptr);
    }
    void STDMETHODCALLTYPE EmitRaytracingAccelerationStructurePostbuildInfo(
        const D3D12_RAYTRACING_ACCELERATION_STRUCTURE_POSTBUILD_INFO_DESC* desc, UINT count,
        const D3D12_GPU_VIRTUAL_ADDRESS* sources) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        D3D12_RAYTRACING_ACCELERATION_STRUCTURE_POSTBUILD_INFO_DESC copy{};
        if (desc) {
            copy = *desc;
            copy.DestBuffer = pipeline::translate_address(desc->DestBuffer, 8);
        }
        std::vector<D3D12_GPU_VIRTUAL_ADDRESS> translated;
        if (sources && count) {
            try {
                translated.resize(count);
            } catch (...) {
                return;
            }
            for (UINT i = 0; i < count; ++i) translated[i] = pipeline::translate_address(sources[i], 4);
        }
        l4_->EmitRaytracingAccelerationStructurePostbuildInfo(desc ? &copy : nullptr, count,
                                                              sources ? translated.data() : nullptr);
    }
    void STDMETHODCALLTYPE CopyRaytracingAccelerationStructure(
        D3D12_GPU_VIRTUAL_ADDRESS dst, D3D12_GPU_VIRTUAL_ADDRESS src,
        D3D12_RAYTRACING_ACCELERATION_STRUCTURE_COPY_MODE mode) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        l4_->CopyRaytracingAccelerationStructure(pipeline::translate_address(dst, 4), pipeline::translate_address(src, 4),
                                                 mode);
    }
    void STDMETHODCALLTYPE SetPipelineState1(ID3D12StateObject* state) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        std::uint32_t flag = 0;
        UINT size = sizeof(flag);
        state_object_local_root_ =
            state && SUCCEEDED(state->GetPrivateData(local_root_guid, &size, &flag)) && size == sizeof(flag) && flag;
        l4_->SetPipelineState1(state);
    }
    // The shader tables' addresses are translated. A state object with local root signatures is refused: its
    // shader records may hold title GPU addresses or title descriptor handles in memory, which are not rewritten.
    void STDMETHODCALLTYPE DispatchRays(const D3D12_DISPATCH_RAYS_DESC* desc) override
    {
        X2W_USE();
        X2W_REQUIRE(l4_);
        if (state_object_local_root_) {
            X2W_REFUSE("a state object with local root signatures: its shader records may hold title addresses "
                       "that are not rewritten; not dispatched");
            return;
        }
        if (!desc) return;
        D3D12_DISPATCH_RAYS_DESC copy = *desc;
        copy.RayGenerationShaderRecord.StartAddress =
            pipeline::translate_address(desc->RayGenerationShaderRecord.StartAddress, desc->RayGenerationShaderRecord.SizeInBytes);
        copy.MissShaderTable.StartAddress =
            pipeline::translate_address(desc->MissShaderTable.StartAddress, desc->MissShaderTable.SizeInBytes);
        copy.HitGroupTable.StartAddress =
            pipeline::translate_address(desc->HitGroupTable.StartAddress, desc->HitGroupTable.SizeInBytes);
        copy.CallableShaderTable.StartAddress =
            pipeline::translate_address(desc->CallableShaderTable.StartAddress, desc->CallableShaderTable.SizeInBytes);
        l4_->DispatchRays(&copy);
    }
    // ID3D12GraphicsCommandList5
    void STDMETHODCALLTYPE RSSetShadingRate(D3D12_SHADING_RATE rate, const D3D12_SHADING_RATE_COMBINER* combiners) override
    {
        X2W_USE();
        X2W_REQUIRE(l5_);
        l5_->RSSetShadingRate(rate, combiners);
    }
    void STDMETHODCALLTYPE RSSetShadingRateImage(ID3D12Resource* image) override
    {
        X2W_USE();
        X2W_REQUIRE(l5_);
        l5_->RSSetShadingRateImage(unwrap(image));
    }
    // ID3D12GraphicsCommandList6. Console mesh pipelines are refused at creation, so a mesh pipeline here is desktop.
    void STDMETHODCALLTYPE DispatchMesh(UINT x, UINT y, UINT z) override
    {
        X2W_USE();
        X2W_REQUIRE(l6_);
        if (translated_) {
            log_refused("d3d12_xs!ID3D12GraphicsCommandList::DispatchMesh",
                        "DispatchMesh with a translated vertex pipeline bound; not dispatched", true);
            return;
        }
        if (!bind_draw(0, 0)) return;
        l6_->DispatchMesh(x, y, z);
    }
    // ID3D12GraphicsCommandList7: enhanced barriers, with resources unwrapped. From the first one on, the shim's own
    // barriers in this recording are enhanced barriers too.
    void STDMETHODCALLTYPE Barrier(UINT count, const D3D12_BARRIER_GROUP* groups) override
    {
        X2W_USE();
        X2W_REQUIRE(l7_);
        enhanced_ = true;
        if (!groups || !count) {
            l7_->Barrier(count, groups);
            return;
        }
        std::vector<D3D12_BARRIER_GROUP> copy;
        std::vector<D3D12_TEXTURE_BARRIER> textures;
        std::vector<D3D12_BUFFER_BARRIER> buffers;
        try {
            copy.assign(groups, groups + count);
            std::size_t t = 0, b = 0;
            for (const auto& g : copy) {
                if (g.Type == D3D12_BARRIER_TYPE_TEXTURE) t += g.NumBarriers;
                if (g.Type == D3D12_BARRIER_TYPE_BUFFER) b += g.NumBarriers;
            }
            textures.reserve(t);
            buffers.reserve(b);
        } catch (...) {
            X2W_REFUSE("out of memory unwrapping barriers; not recorded");
            return;
        }
        for (auto& g : copy) {
            if (g.Type == D3D12_BARRIER_TYPE_TEXTURE && g.pTextureBarriers) {
                const std::size_t first = textures.size();
                for (UINT i = 0; i < g.NumBarriers; ++i) {
                    textures.push_back(g.pTextureBarriers[i]);
                    textures.back().pResource = unwrap(textures.back().pResource);
                }
                g.pTextureBarriers = textures.data() + first;
            } else if (g.Type == D3D12_BARRIER_TYPE_BUFFER && g.pBufferBarriers) {
                const std::size_t first = buffers.size();
                for (UINT i = 0; i < g.NumBarriers; ++i) {
                    buffers.push_back(g.pBufferBarriers[i]);
                    buffers.back().pResource = unwrap(buffers.back().pResource);
                }
                g.pBufferBarriers = buffers.data() + first;
            }
        }
        l7_->Barrier(count, copy.data());
    }

private:
    // Compute root arguments as forwarded to desktop D3D12 (title addresses translated), replayed after the shim's
    // own compute pass (ExecuteIndirect rewrites) changed the compute root signature.
    struct ComputeReplay {
        enum Type : std::uint8_t { none = 0, table_arg, constants_arg, cbv, srv, uav };
        Type type[pipeline::max_title_params];
        std::uint64_t value[pipeline::max_title_params];
        std::uint64_t set[pipeline::max_title_params];  // constants: which of the 64 words were set
        std::uint32_t words[pipeline::max_title_params][64];
        void clear()
        {
            std::memset(type, 0, sizeof(type));
            std::memset(set, 0, sizeof(set));
        }
        void table(UINT index, D3D12_GPU_DESCRIPTOR_HANDLE base)
        {
            if (index >= pipeline::max_title_params) return;
            type[index] = Type::table_arg;
            value[index] = base.ptr;
        }
        void view(UINT index, Type t, D3D12_GPU_VIRTUAL_ADDRESS address)
        {
            if (index >= pipeline::max_title_params) return;
            type[index] = t;
            value[index] = address;
        }
        void constants(UINT index, UINT count, const void* data, UINT offset)
        {
            if (index >= pipeline::max_title_params || offset >= 64 || count > 64 - offset) return;
            type[index] = Type::constants_arg;
            std::memcpy(&words[index][offset], data, count * 4);
            for (UINT i = 0; i < count; ++i) set[index] |= std::uint64_t(1) << (offset + i);
        }
        void apply(ID3D12GraphicsCommandList* list) const
        {
            for (UINT i = 0; i < pipeline::max_title_params; ++i) {
                switch (type[i]) {
                case Type::table_arg: list->SetComputeRootDescriptorTable(i, {value[i]}); break;
                case Type::cbv: list->SetComputeRootConstantBufferView(i, value[i]); break;
                case Type::srv: list->SetComputeRootShaderResourceView(i, value[i]); break;
                case Type::uav: list->SetComputeRootUnorderedAccessView(i, value[i]); break;
                case Type::constants_arg:
                    for (UINT w = 0; w < 64; ++w)
                        if (set[i] >> w & 1) list->SetComputeRoot32BitConstant(i, words[i][w], w);
                    break;
                default: break;
                }
            }
        }
    };
    struct Predication {
        ID3D12Resource* buffer = nullptr;
        UINT64 offset = 0;
        D3D12_PREDICATION_OP op = D3D12_PREDICATION_OP_EQUAL_ZERO;
    };

    ComPtr<ID3D12GraphicsCommandList1> l1_;
    ComPtr<ID3D12GraphicsCommandList2> l2_;
    ComPtr<ID3D12GraphicsCommandList3> l3_;
    ComPtr<ID3D12GraphicsCommandList4> l4_;
    ComPtr<ID3D12GraphicsCommandList5> l5_;
    ComPtr<ID3D12GraphicsCommandList6> l6_;
    ComPtr<ID3D12GraphicsCommandList7> l7_;
    pipeline::RootArgs* args_;
    ComputeReplay* replay_;
    Allocator* allocator_;                     // the allocator this recording uses (not referenced: the title's)
    ID3D12PipelineState* current_pso_;         // as the title set it (not referenced)
    ID3D12RootSignature* compute_root_ = nullptr;
    Predication predication_;
    bool in_render_pass_ = false;
    bool enhanced_ = false;                    // the recording has used enhanced barriers
    bool state_object_local_root_ = false;     // the state object set by SetPipelineState1 has local root signatures
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
        real_->UpdateTileMappings(unwrap(resource), regions, starts, sizes, unwrap(heap), ranges, flags, heap_offsets,
                                  tile_counts, mapping_flags);
    }
    void STDMETHODCALLTYPE CopyTileMappings(ID3D12Resource* dst, const D3D12_TILED_RESOURCE_COORDINATE* dst_start,
                                            ID3D12Resource* src, const D3D12_TILED_RESOURCE_COORDINATE* src_start,
                                            const D3D12_TILE_REGION_SIZE* size, D3D12_TILE_MAPPING_FLAGS flags) override
    {
        X2W_USE();
        real_->CopyTileMappings(unwrap(dst), dst_start, unwrap(src), src_start, size, flags);
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
        return real_->GetDesc(ret);
    }
#else
    D3D12_COMMAND_QUEUE_DESC STDMETHODCALLTYPE GetDesc() override
    {
        X2W_USE();
        return real_->GetDesc();
    }
#endif
};

class Device final : public Wrapper<Device, ID3D12Device10, Kind::device> {
public:
    explicit Device(ID3D12Device* real)
        : Wrapper(static_cast<ID3D12Device10*>(real)), views_(pipeline::create_title_views(real)),
          rewriter_(indirect::create_rewriter(real))
    {
        real->QueryInterface(IID_PPV_ARGS(&d1_));
        real->QueryInterface(IID_PPV_ARGS(&d2_));
        real->QueryInterface(IID_PPV_ARGS(&d3_));
        real->QueryInterface(IID_PPV_ARGS(&d4_));
        real->QueryInterface(IID_PPV_ARGS(&d5_));
        real->QueryInterface(IID_PPV_ARGS(&d6_));
        real->QueryInterface(IID_PPV_ARGS(&d7_));
        real->QueryInterface(IID_PPV_ARGS(&d8_));
        real->QueryInterface(IID_PPV_ARGS(&d9_));
        real->QueryInterface(IID_PPV_ARGS(&d10_));
        install();
    }
    ~Device()
    {
        indirect::destroy_rewriter(rewriter_);
        pipeline::destroy_title_views(views_);
        if (attached_ && detach_) {
            detach_();
            g_attached_device.store(nullptr);
        }
    }
    bool implements(REFIID riid) const
    {
        return IsEqualIID(riid, __uuidof(ID3D12Object)) || IsEqualIID(riid, __uuidof(ID3D12Device)) ||
               (d1_ && IsEqualIID(riid, __uuidof(ID3D12Device1))) || (d2_ && IsEqualIID(riid, __uuidof(ID3D12Device2))) ||
               (d3_ && IsEqualIID(riid, __uuidof(ID3D12Device3))) || (d4_ && IsEqualIID(riid, __uuidof(ID3D12Device4))) ||
               (d5_ && IsEqualIID(riid, __uuidof(ID3D12Device5))) || (d6_ && IsEqualIID(riid, __uuidof(ID3D12Device6))) ||
               (d7_ && IsEqualIID(riid, __uuidof(ID3D12Device7))) || (d8_ && IsEqualIID(riid, __uuidof(ID3D12Device8))) ||
               (d9_ && IsEqualIID(riid, __uuidof(ID3D12Device9))) || (d10_ && IsEqualIID(riid, __uuidof(ID3D12Device10))) ||
               is_device_alias(riid);
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
        return hand_out(new (std::nothrow) List(list, this, as_wrapper<Allocator>(allocator, Kind::allocator), state), list,
                        riid, out, X2W_RETURN_ADDRESS());
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
        if (!desc || !out) return real_->CreateDescriptorHeap(desc, riid, out);
        if (!descriptors::title_increment(desc->Type)) {
            *out = nullptr;
            ID3D12DescriptorHeap* real = nullptr;
            const HRESULT hr = real_->CreateDescriptorHeap(desc, IID_PPV_ARGS(&real));
            if (FAILED(hr)) return hr;
            return hand_out(new (std::nothrow) ViewHeap(real, this), real, riid, out, X2W_RETURN_ADDRESS());
        }
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
        resource = unwrap(resource);
        // An acceleration structure's view names it by GPU address.
        D3D12_SHADER_RESOURCE_VIEW_DESC copy{};
        if (desc && desc->ViewDimension == D3D12_SRV_DIMENSION_RAYTRACING_ACCELERATION_STRUCTURE) {
            copy = *desc;
            copy.RaytracingAccelerationStructure.Location =
                pipeline::translate_address(desc->RaytracingAccelerationStructure.Location, 4);
            desc = &copy;
        }
        if (descriptors::write_srv(descriptor.ptr, resource, desc)) return;
        real_->CreateShaderResourceView(resource, desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateUnorderedAccessView(ID3D12Resource* resource, ID3D12Resource* counter,
                                                     const D3D12_UNORDERED_ACCESS_VIEW_DESC* desc,
                                                     D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        resource = unwrap(resource);
        counter = unwrap(counter);
        if (descriptors::write_uav(descriptor.ptr, resource, counter, desc)) return;
        real_->CreateUnorderedAccessView(resource, counter, desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateRenderTargetView(ID3D12Resource* resource, const D3D12_RENDER_TARGET_VIEW_DESC* desc,
                                                  D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateRenderTargetView(unwrap(resource), desc, descriptor);
    }
    void STDMETHODCALLTYPE CreateDepthStencilView(ID3D12Resource* resource, const D3D12_DEPTH_STENCIL_VIEW_DESC* desc,
                                                  D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        real_->CreateDepthStencilView(unwrap(resource), desc, descriptor);
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
        return real_->GetResourceAllocationInfo(ret, mask, count, descs);
    }
    D3D12_HEAP_PROPERTIES* STDMETHODCALLTYPE GetCustomHeapProperties(D3D12_HEAP_PROPERTIES* ret, UINT node_mask,
                                                                     D3D12_HEAP_TYPE type) override
    {
        X2W_USE();
        return real_->GetCustomHeapProperties(ret, node_mask, type);
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
        return make_resource(riid, out, heap, 0, 0, [&](REFIID iid, void** p) {
            return real_->CreateCommittedResource(heap, flags, desc, state, clear, iid, p);
        });
    }
    HRESULT STDMETHODCALLTYPE CreateHeap(const D3D12_HEAP_DESC* desc, REFIID riid, void** out) override
    {
        X2W_USE();
        return make_heap(riid, out, 0, [&](REFIID iid, void** p) { return real_->CreateHeap(desc, iid, p); });
    }
    HRESULT STDMETHODCALLTYPE CreatePlacedResource(ID3D12Heap* heap, UINT64 offset, const D3D12_RESOURCE_DESC* desc,
                                                   D3D12_RESOURCE_STATES state, const D3D12_CLEAR_VALUE* clear,
                                                   REFIID riid, void** out) override
    {
        X2W_USE();
        D3D12_HEAP_PROPERTIES properties{};
        const std::uint64_t existing = placed_heap(heap, &properties);
        return make_resource(riid, out, heap ? &properties : nullptr, existing, offset, [&](REFIID iid, void** p) {
            return real_->CreatePlacedResource(unwrap(heap), offset, desc, state, clear, iid, p);
        });
    }
    HRESULT STDMETHODCALLTYPE CreateReservedResource(const D3D12_RESOURCE_DESC* desc, D3D12_RESOURCE_STATES state,
                                                     const D3D12_CLEAR_VALUE* clear, REFIID riid, void** out) override
    {
        X2W_USE();
        return make_resource(riid, out, nullptr, 0, 0, [&](REFIID iid, void** p) {
            return real_->CreateReservedResource(desc, state, clear, iid, p);
        });
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
        if (!desc || !out) return real_->CreateCommandSignature(desc, root, riid, out);
        *out = nullptr;
        ID3D12CommandSignature* signature = nullptr;
        const HRESULT hr = real_->CreateCommandSignature(desc, root, IID_PPV_ARGS(&signature));
        if (FAILED(hr)) return hr;
        return hand_out(new (std::nothrow) CommandSignature(signature, this, indirect::describe(*desc)), signature,
                        riid, out, X2W_RETURN_ADDRESS());
    }
    void STDMETHODCALLTYPE GetResourceTiling(ID3D12Resource* resource, UINT* tiles, D3D12_PACKED_MIP_INFO* packed,
                                             D3D12_TILE_SHAPE* shape, UINT* tilings, UINT first,
                                             D3D12_SUBRESOURCE_TILING* out) override
    {
        X2W_USE();
        real_->GetResourceTiling(unwrap(resource), tiles, packed, shape, tilings, first, out);
    }
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    LUID* STDMETHODCALLTYPE GetAdapterLuid(LUID* ret) override
    {
        X2W_USE();
        return real_->GetAdapterLuid(ret);
    }
#else
    LUID STDMETHODCALLTYPE GetAdapterLuid() override
    {
        X2W_USE();
        return real_->GetAdapterLuid();
    }
#endif

    // --- resources and heaps: wrapped (d3d12_xs_resources.h) ----------------------------------------------------

    // Creates a desktop resource through `create` (as ID3D12Resource) and hands it out wrapped with its title address.
    // A null output is a support check and is forwarded with the title's riid.
    template <class Create>
    HRESULT make_resource(REFIID riid, void** out, const D3D12_HEAP_PROPERTIES* heap, std::uint64_t existing,
                          std::uint64_t offset, Create create)
    {
        if (!out) return create(riid, nullptr);
        *out = nullptr;
        ID3D12Resource* resource = nullptr;
        const HRESULT hr = create(__uuidof(ID3D12Resource), reinterpret_cast<void**>(&resource));
        if (FAILED(hr)) return hr;
        if (hr == S_FALSE || !resource) return hr;
        const resources::TitleAddress address = resources::assign(resource, heap, existing, offset);
        return hand_out(new (std::nothrow) Resource(resource, this, address), resource, riid, out, X2W_RETURN_ADDRESS());
    }
    template <class Create>
    HRESULT make_heap(REFIID riid, void** out, std::uint64_t existing, Create create)
    {
        if (!out) return create(riid, nullptr);
        *out = nullptr;
        ID3D12Heap* heap = nullptr;
        const HRESULT hr = create(__uuidof(ID3D12Heap), reinterpret_cast<void**>(&heap));
        if (FAILED(hr)) return hr;
        if (hr == S_FALSE || !heap) return hr;
        return hand_out(new (std::nothrow) Heap(heap, this, existing), heap, riid, out, X2W_RETURN_ADDRESS());
    }
    // The heap properties of the heap a resource is placed in, and the address it was opened from (0 if none).
    static std::uint64_t placed_heap(ID3D12Heap* heap, D3D12_HEAP_PROPERTIES* properties)
    {
        if (!heap) return 0;
        *properties = heap_desc(unwrap(heap)).Properties;
        const Heap* wrapped = as_wrapper<Heap>(heap, Kind::heap);
        return wrapped ? wrapped->existing_address() : 0;
    }
    template <class Create>
    HRESULT make_list(REFIID riid, void** out, Create create)
    {
        if (!out) return create(riid, nullptr);
        *out = nullptr;
        ID3D12GraphicsCommandList* list = nullptr;
        const HRESULT hr = create(__uuidof(ID3D12GraphicsCommandList), reinterpret_cast<void**>(&list));
        if (FAILED(hr)) return hr;
        return hand_out(new (std::nothrow) List(list, this, nullptr, nullptr), list, riid, out, X2W_RETURN_ADDRESS());
    }
    static std::vector<ID3D12Pageable*> unwrap_pageables(UINT count, ID3D12Pageable* const* objects, bool* good)
    {
        std::vector<ID3D12Pageable*> desktop;
        *good = !objects || unwrap_array(count, objects, desktop);
        return desktop;
    }
    // A state object whose subobjects include a local root signature is marked (List::DispatchRays refuses it).
    static void mark_state_object(const D3D12_STATE_OBJECT_DESC* desc, void* object, REFIID riid)
    {
        if (!desc || !object) return;
        std::uint32_t local = 0;
        for (UINT i = 0; i < desc->NumSubobjects && desc->pSubobjects; ++i)
            if (desc->pSubobjects[i].Type == D3D12_STATE_SUBOBJECT_TYPE_LOCAL_ROOT_SIGNATURE) local = 1;
        ComPtr<ID3D12StateObject> state;
        if (local && SUCCEEDED(static_cast<IUnknown*>(object)->QueryInterface(IID_PPV_ARGS(&state))))
            state->SetPrivateData(local_root_guid, sizeof(local), &local);
        (void)riid;
    }

    // --- ID3D12Device1 ----------------------------------------------------------------------------------------
    // A pipeline library stores and loads pipelines by description, which would bypass translation; D3D12 lets a
    // driver refuse libraries with DXGI_ERROR_UNSUPPORTED, and titles fall back to creating pipelines.
    HRESULT STDMETHODCALLTYPE CreatePipelineLibrary(const void* blob, SIZE_T size, REFIID riid, void** out) override
    {
        X2W_USE();
        (void)blob;
        (void)size;
        (void)riid;
        if (out) *out = nullptr;
        X2W_REFUSE("pipeline libraries would load pipelines without translation -> DXGI_ERROR_UNSUPPORTED");
        return DXGI_ERROR_UNSUPPORTED;
    }
    HRESULT STDMETHODCALLTYPE SetEventOnMultipleFenceCompletion(ID3D12Fence* const* fences, const UINT64* values,
                                                                UINT count, D3D12_MULTIPLE_FENCE_WAIT_FLAGS flags,
                                                                HANDLE event) override
    {
        X2W_USE();
        X2W_REQUIRE(d1_, E_NOTIMPL);
        std::vector<ID3D12Fence*> desktop;
        if (fences && !unwrap_array(count, fences, desktop)) return E_OUTOFMEMORY;
        return d1_->SetEventOnMultipleFenceCompletion(fences ? desktop.data() : nullptr, values, count, flags, event);
    }
    HRESULT STDMETHODCALLTYPE SetResidencyPriority(UINT count, ID3D12Pageable* const* objects,
                                                   const D3D12_RESIDENCY_PRIORITY* priorities) override
    {
        X2W_USE();
        X2W_REQUIRE(d1_, E_NOTIMPL);
        bool good;
        auto desktop = unwrap_pageables(count, objects, &good);
        if (!good) return E_OUTOFMEMORY;
        return d1_->SetResidencyPriority(count, objects ? desktop.data() : nullptr, priorities);
    }
    // --- ID3D12Device2: pipeline state streams go through translation (pipeline::create_pipeline_state). ---------
    HRESULT STDMETHODCALLTYPE CreatePipelineState(const D3D12_PIPELINE_STATE_STREAM_DESC* desc, REFIID riid,
                                                  void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d2_, E_NOTIMPL);
        return pipeline::create_pipeline_state(d2_.Get(), desc, riid, out);
    }
    // --- ID3D12Device3 ----------------------------------------------------------------------------------------
    HRESULT STDMETHODCALLTYPE OpenExistingHeapFromAddress(const void* address, REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d3_, E_NOTIMPL);
        return make_heap(riid, out, reinterpret_cast<std::uintptr_t>(address),
                         [&](REFIID iid, void** p) { return d3_->OpenExistingHeapFromAddress(address, iid, p); });
    }
    HRESULT STDMETHODCALLTYPE OpenExistingHeapFromFileMapping(HANDLE mapping, REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d3_, E_NOTIMPL);
        return make_heap(riid, out, 0,
                         [&](REFIID iid, void** p) { return d3_->OpenExistingHeapFromFileMapping(mapping, iid, p); });
    }
    HRESULT STDMETHODCALLTYPE EnqueueMakeResident(D3D12_RESIDENCY_FLAGS flags, UINT count, ID3D12Pageable* const* objects,
                                                  ID3D12Fence* fence, UINT64 value) override
    {
        X2W_USE();
        X2W_REQUIRE(d3_, E_NOTIMPL);
        bool good;
        auto desktop = unwrap_pageables(count, objects, &good);
        if (!good) return E_OUTOFMEMORY;
        return d3_->EnqueueMakeResident(flags, count, objects ? desktop.data() : nullptr, unwrap(fence), value);
    }
    // --- ID3D12Device4 ----------------------------------------------------------------------------------------
    HRESULT STDMETHODCALLTYPE CreateCommandList1(UINT node_mask, D3D12_COMMAND_LIST_TYPE type,
                                                 D3D12_COMMAND_LIST_FLAGS flags, REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d4_, E_NOTIMPL);
        return make_list(riid, out, [&](REFIID iid, void** p) { return d4_->CreateCommandList1(node_mask, type, flags, iid, p); });
    }
    HRESULT STDMETHODCALLTYPE CreateProtectedResourceSession(const D3D12_PROTECTED_RESOURCE_SESSION_DESC* desc,
                                                             REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d4_, E_NOTIMPL);
        return d4_->CreateProtectedResourceSession(desc, riid, out);
    }
    HRESULT STDMETHODCALLTYPE CreateCommittedResource1(const D3D12_HEAP_PROPERTIES* heap, D3D12_HEAP_FLAGS flags,
                                                       const D3D12_RESOURCE_DESC* desc, D3D12_RESOURCE_STATES state,
                                                       const D3D12_CLEAR_VALUE* clear,
                                                       ID3D12ProtectedResourceSession* session, REFIID riid,
                                                       void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d4_, E_NOTIMPL);
        return make_resource(riid, out, heap, 0, 0, [&](REFIID iid, void** p) {
            return d4_->CreateCommittedResource1(heap, flags, desc, state, clear, session, iid, p);
        });
    }
    HRESULT STDMETHODCALLTYPE CreateHeap1(const D3D12_HEAP_DESC* desc, ID3D12ProtectedResourceSession* session,
                                          REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d4_, E_NOTIMPL);
        return make_heap(riid, out, 0, [&](REFIID iid, void** p) { return d4_->CreateHeap1(desc, session, iid, p); });
    }
    HRESULT STDMETHODCALLTYPE CreateReservedResource1(const D3D12_RESOURCE_DESC* desc, D3D12_RESOURCE_STATES state,
                                                      const D3D12_CLEAR_VALUE* clear,
                                                      ID3D12ProtectedResourceSession* session, REFIID riid,
                                                      void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d4_, E_NOTIMPL);
        return make_resource(riid, out, nullptr, 0, 0, [&](REFIID iid, void** p) {
            return d4_->CreateReservedResource1(desc, state, clear, session, iid, p);
        });
    }
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_ALLOCATION_INFO* STDMETHODCALLTYPE GetResourceAllocationInfo1(
        D3D12_RESOURCE_ALLOCATION_INFO* ret, UINT mask, UINT count, const D3D12_RESOURCE_DESC* descs,
        D3D12_RESOURCE_ALLOCATION_INFO1* info) override
    {
        X2W_USE();
        if (!d4_) *ret = {};
        X2W_REQUIRE(d4_, ret);
        return d4_->GetResourceAllocationInfo1(ret, mask, count, descs, info);
    }
#else
    D3D12_RESOURCE_ALLOCATION_INFO STDMETHODCALLTYPE GetResourceAllocationInfo1(
        UINT mask, UINT count, const D3D12_RESOURCE_DESC* descs, D3D12_RESOURCE_ALLOCATION_INFO1* info) override
    {
        X2W_USE();
        X2W_REQUIRE(d4_, D3D12_RESOURCE_ALLOCATION_INFO{});
        return d4_->GetResourceAllocationInfo1(mask, count, descs, info);
    }
#endif
    // --- ID3D12Device5 ----------------------------------------------------------------------------------------
    HRESULT STDMETHODCALLTYPE CreateLifetimeTracker(ID3D12LifetimeOwner* owner, REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d5_, E_NOTIMPL);
        return d5_->CreateLifetimeTracker(owner, riid, out);
    }
    void STDMETHODCALLTYPE RemoveDevice() override
    {
        X2W_USE();
        X2W_REQUIRE(d5_);
        d5_->RemoveDevice();
    }
    HRESULT STDMETHODCALLTYPE EnumerateMetaCommands(UINT* count, D3D12_META_COMMAND_DESC* descs) override
    {
        X2W_USE();
        X2W_REQUIRE(d5_, E_NOTIMPL);
        return d5_->EnumerateMetaCommands(count, descs);
    }
    HRESULT STDMETHODCALLTYPE EnumerateMetaCommandParameters(REFGUID command, D3D12_META_COMMAND_PARAMETER_STAGE stage,
                                                             UINT* total, UINT* count,
                                                             D3D12_META_COMMAND_PARAMETER_DESC* descs) override
    {
        X2W_USE();
        X2W_REQUIRE(d5_, E_NOTIMPL);
        return d5_->EnumerateMetaCommandParameters(command, stage, total, count, descs);
    }
    // Meta-command parameters are driver-defined and may hold GPU addresses the shim cannot find and translate.
    HRESULT STDMETHODCALLTYPE CreateMetaCommand(REFGUID command, UINT node_mask, const void* data, SIZE_T size,
                                                REFIID riid, void** out) override
    {
        X2W_USE();
        (void)command;
        (void)node_mask;
        (void)data;
        (void)size;
        (void)riid;
        if (out) *out = nullptr;
        X2W_REFUSE("meta-command parameters may hold GPU addresses the shim cannot translate -> E_NOTIMPL");
        return E_NOTIMPL;
    }
    HRESULT STDMETHODCALLTYPE CreateStateObject(const D3D12_STATE_OBJECT_DESC* desc, REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d5_, E_NOTIMPL);
        const HRESULT hr = d5_->CreateStateObject(desc, riid, out);
        if (SUCCEEDED(hr) && out) mark_state_object(desc, *out, riid);
        return hr;
    }
    void STDMETHODCALLTYPE GetRaytracingAccelerationStructurePrebuildInfo(
        const D3D12_BUILD_RAYTRACING_ACCELERATION_STRUCTURE_INPUTS* inputs,
        D3D12_RAYTRACING_ACCELERATION_STRUCTURE_PREBUILD_INFO* info) override
    {
        X2W_USE();
        X2W_REQUIRE(d5_);
        d5_->GetRaytracingAccelerationStructurePrebuildInfo(inputs, info);
    }
    D3D12_DRIVER_MATCHING_IDENTIFIER_STATUS STDMETHODCALLTYPE CheckDriverMatchingIdentifier(
        D3D12_SERIALIZED_DATA_TYPE type, const D3D12_SERIALIZED_DATA_DRIVER_MATCHING_IDENTIFIER* identifier) override
    {
        X2W_USE();
        X2W_REQUIRE(d5_, D3D12_DRIVER_MATCHING_IDENTIFIER_UNSUPPORTED_TYPE);
        return d5_->CheckDriverMatchingIdentifier(type, identifier);
    }
    // --- ID3D12Device6 ----------------------------------------------------------------------------------------
    HRESULT STDMETHODCALLTYPE SetBackgroundProcessingMode(D3D12_BACKGROUND_PROCESSING_MODE mode,
                                                          D3D12_MEASUREMENTS_ACTION action, HANDLE event,
                                                          BOOL* further) override
    {
        X2W_USE();
        X2W_REQUIRE(d6_, E_NOTIMPL);
        return d6_->SetBackgroundProcessingMode(mode, action, event, further);
    }
    // --- ID3D12Device7 ----------------------------------------------------------------------------------------
    HRESULT STDMETHODCALLTYPE AddToStateObject(const D3D12_STATE_OBJECT_DESC* addition, ID3D12StateObject* existing,
                                               REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d7_, E_NOTIMPL);
        const HRESULT hr = d7_->AddToStateObject(addition, existing, riid, out);
        if (SUCCEEDED(hr) && out) {
            mark_state_object(addition, *out, riid);
            std::uint32_t flag = 0;
            UINT size = sizeof(flag);
            ComPtr<ID3D12StateObject> state;
            if (existing && SUCCEEDED(existing->GetPrivateData(local_root_guid, &size, &flag)) && flag &&
                SUCCEEDED(static_cast<IUnknown*>(*out)->QueryInterface(IID_PPV_ARGS(&state))))
                state->SetPrivateData(local_root_guid, sizeof(flag), &flag);
        }
        return hr;
    }
    HRESULT STDMETHODCALLTYPE CreateProtectedResourceSession1(const D3D12_PROTECTED_RESOURCE_SESSION_DESC1* desc,
                                                              REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d7_, E_NOTIMPL);
        return d7_->CreateProtectedResourceSession1(desc, riid, out);
    }
    // --- ID3D12Device8 ----------------------------------------------------------------------------------------
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_ALLOCATION_INFO* STDMETHODCALLTYPE GetResourceAllocationInfo2(
        D3D12_RESOURCE_ALLOCATION_INFO* ret, UINT mask, UINT count, const D3D12_RESOURCE_DESC1* descs,
        D3D12_RESOURCE_ALLOCATION_INFO1* info) override
    {
        X2W_USE();
        if (!d8_) *ret = {};
        X2W_REQUIRE(d8_, ret);
        return d8_->GetResourceAllocationInfo2(ret, mask, count, descs, info);
    }
#else
    D3D12_RESOURCE_ALLOCATION_INFO STDMETHODCALLTYPE GetResourceAllocationInfo2(
        UINT mask, UINT count, const D3D12_RESOURCE_DESC1* descs, D3D12_RESOURCE_ALLOCATION_INFO1* info) override
    {
        X2W_USE();
        X2W_REQUIRE(d8_, D3D12_RESOURCE_ALLOCATION_INFO{});
        return d8_->GetResourceAllocationInfo2(mask, count, descs, info);
    }
#endif
    HRESULT STDMETHODCALLTYPE CreateCommittedResource2(const D3D12_HEAP_PROPERTIES* heap, D3D12_HEAP_FLAGS flags,
                                                       const D3D12_RESOURCE_DESC1* desc, D3D12_RESOURCE_STATES state,
                                                       const D3D12_CLEAR_VALUE* clear,
                                                       ID3D12ProtectedResourceSession* session, REFIID riid,
                                                       void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d8_, E_NOTIMPL);
        return make_resource(riid, out, heap, 0, 0, [&](REFIID iid, void** p) {
            return d8_->CreateCommittedResource2(heap, flags, desc, state, clear, session, iid, p);
        });
    }
    HRESULT STDMETHODCALLTYPE CreatePlacedResource1(ID3D12Heap* heap, UINT64 offset, const D3D12_RESOURCE_DESC1* desc,
                                                    D3D12_RESOURCE_STATES state, const D3D12_CLEAR_VALUE* clear,
                                                    REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d8_, E_NOTIMPL);
        D3D12_HEAP_PROPERTIES properties{};
        const std::uint64_t existing = placed_heap(heap, &properties);
        return make_resource(riid, out, heap ? &properties : nullptr, existing, offset, [&](REFIID iid, void** p) {
            return d8_->CreatePlacedResource1(unwrap(heap), offset, desc, state, clear, iid, p);
        });
    }
    // A sampler-feedback view in a title descriptor heap has no slot kind there yet.
    void STDMETHODCALLTYPE CreateSamplerFeedbackUnorderedAccessView(ID3D12Resource* target, ID3D12Resource* feedback,
                                                                    D3D12_CPU_DESCRIPTOR_HANDLE descriptor) override
    {
        X2W_USE();
        X2W_REQUIRE(d8_);
        if (descriptors::is_title_handle(descriptor.ptr)) {
            X2W_REFUSE("a sampler-feedback UAV in a title descriptor heap is not translated; not written");
            return;
        }
        d8_->CreateSamplerFeedbackUnorderedAccessView(unwrap(target), unwrap(feedback), descriptor);
    }
    void STDMETHODCALLTYPE GetCopyableFootprints1(const D3D12_RESOURCE_DESC1* desc, UINT first, UINT count, UINT64 base,
                                                  D3D12_PLACED_SUBRESOURCE_FOOTPRINT* layouts, UINT* rows,
                                                  UINT64* row_bytes, UINT64* total) override
    {
        X2W_USE();
        X2W_REQUIRE(d8_);
        d8_->GetCopyableFootprints1(desc, first, count, base, layouts, rows, row_bytes, total);
    }
    // --- ID3D12Device9 ----------------------------------------------------------------------------------------
    HRESULT STDMETHODCALLTYPE CreateShaderCacheSession(const D3D12_SHADER_CACHE_SESSION_DESC* desc, REFIID riid,
                                                       void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d9_, E_NOTIMPL);
        return d9_->CreateShaderCacheSession(desc, riid, out);
    }
    HRESULT STDMETHODCALLTYPE ShaderCacheControl(D3D12_SHADER_CACHE_KIND_FLAGS kinds,
                                                 D3D12_SHADER_CACHE_CONTROL_FLAGS control) override
    {
        X2W_USE();
        X2W_REQUIRE(d9_, E_NOTIMPL);
        return d9_->ShaderCacheControl(kinds, control);
    }
    HRESULT STDMETHODCALLTYPE CreateCommandQueue1(const D3D12_COMMAND_QUEUE_DESC* desc, REFIID creator, REFIID riid,
                                                  void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d9_, E_NOTIMPL);
        if (!out) return d9_->CreateCommandQueue1(desc, creator, riid, nullptr);
        *out = nullptr;
        ID3D12CommandQueue* queue = nullptr;
        const HRESULT hr = d9_->CreateCommandQueue1(desc, creator, IID_PPV_ARGS(&queue));
        if (FAILED(hr)) return hr;
        return hand_out(new (std::nothrow) Queue(queue, this), queue, riid, out, X2W_RETURN_ADDRESS());
    }
    // --- ID3D12Device10 ---------------------------------------------------------------------------------------
    HRESULT STDMETHODCALLTYPE CreateCommittedResource3(const D3D12_HEAP_PROPERTIES* heap, D3D12_HEAP_FLAGS flags,
                                                       const D3D12_RESOURCE_DESC1* desc, D3D12_BARRIER_LAYOUT layout,
                                                       const D3D12_CLEAR_VALUE* clear,
                                                       ID3D12ProtectedResourceSession* session, UINT castable_count,
                                                       const DXGI_FORMAT* castable, REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d10_, E_NOTIMPL);
        return make_resource(riid, out, heap, 0, 0, [&](REFIID iid, void** p) {
            return d10_->CreateCommittedResource3(heap, flags, desc, layout, clear, session, castable_count, castable,
                                                  iid, p);
        });
    }
    HRESULT STDMETHODCALLTYPE CreatePlacedResource2(ID3D12Heap* heap, UINT64 offset, const D3D12_RESOURCE_DESC1* desc,
                                                    D3D12_BARRIER_LAYOUT layout, const D3D12_CLEAR_VALUE* clear,
                                                    UINT castable_count, const DXGI_FORMAT* castable, REFIID riid,
                                                    void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d10_, E_NOTIMPL);
        D3D12_HEAP_PROPERTIES properties{};
        const std::uint64_t existing = placed_heap(heap, &properties);
        return make_resource(riid, out, heap ? &properties : nullptr, existing, offset, [&](REFIID iid, void** p) {
            return d10_->CreatePlacedResource2(unwrap(heap), offset, desc, layout, clear, castable_count, castable, iid,
                                               p);
        });
    }
    HRESULT STDMETHODCALLTYPE CreateReservedResource2(const D3D12_RESOURCE_DESC* desc, D3D12_BARRIER_LAYOUT layout,
                                                      const D3D12_CLEAR_VALUE* clear,
                                                      ID3D12ProtectedResourceSession* session, UINT castable_count,
                                                      const DXGI_FORMAT* castable, REFIID riid, void** out) override
    {
        X2W_USE();
        X2W_REQUIRE(d10_, E_NOTIMPL);
        return make_resource(riid, out, nullptr, 0, 0, [&](REFIID iid, void** p) {
            return d10_->CreateReservedResource2(desc, layout, clear, session, castable_count, castable, iid, p);
        });
    }

    indirect::Rewriter* rewriter() const { return rewriter_; }

    pipeline::TitleViews* views() const { return views_; }

private:
    bool attached_ = false;
    void (*detach_)() = nullptr;
    pipeline::TitleViews* views_;
    indirect::Rewriter* rewriter_;
    ComPtr<ID3D12Device1> d1_;
    ComPtr<ID3D12Device2> d2_;
    ComPtr<ID3D12Device3> d3_;
    ComPtr<ID3D12Device4> d4_;
    ComPtr<ID3D12Device5> d5_;
    ComPtr<ID3D12Device6> d6_;
    ComPtr<ID3D12Device7> d7_;
    ComPtr<ID3D12Device8> d8_;
    ComPtr<ID3D12Device9> d9_;
    ComPtr<ID3D12Device10> d10_;
};

DeviceRef::DeviceRef(Device* device) : device_(device) { device_->AddRef(); }
DeviceRef::~DeviceRef() { device_->Release(); }

HRESULT device_query(Device* device, REFIID riid, void** out, const void* caller)
{
    return device->query(riid, out, caller);
}

pipeline::TitleViews* device_views(Device* device) { return device->views(); }
indirect::Rewriter* device_rewriter(Device* device) { return device->rewriter(); }

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
              std::is_final_v<DescriptorHeap> && std::is_final_v<ViewHeap> && std::is_final_v<Resource> && std::is_final_v<Heap> &&
              std::is_final_v<CommandSignature>);

IUnknown* real_of(const void* object)
{
    Kind kind;
    if (!wrapper_kind(object, &kind)) return nullptr;
    // `object` is the interface base at offset 0 of the wrapper (single inheritance).
    void* base = const_cast<void*>(object);
    switch (kind) {
    case Kind::device: return static_cast<Device*>(static_cast<ID3D12Device10*>(base))->real();
    case Kind::queue: return static_cast<Queue*>(static_cast<ID3D12CommandQueue*>(base))->real();
    case Kind::allocator: return static_cast<Allocator*>(static_cast<ID3D12CommandAllocator*>(base))->real();
    case Kind::list: return static_cast<List*>(static_cast<ID3D12GraphicsCommandList7*>(base))->real();
    case Kind::fence: return static_cast<Fence*>(static_cast<ID3D12Fence1*>(base))->real();
    case Kind::swap_chain: return static_cast<SwapChain*>(static_cast<IDXGISwapChain3*>(base))->real();
    case Kind::descriptor_heap:
        return static_cast<DescriptorHeap*>(static_cast<ID3D12DescriptorHeap*>(base))->real();
    case Kind::view_heap: return static_cast<ViewHeap*>(static_cast<ID3D12DescriptorHeap*>(base))->real();
    case Kind::resource: return static_cast<Resource*>(static_cast<ID3D12Resource2*>(base))->real();
    case Kind::heap: return static_cast<Heap*>(static_cast<ID3D12Heap1*>(base))->real();
    case Kind::command_signature:
        return static_cast<CommandSignature*>(static_cast<ID3D12CommandSignature*>(base))->real();
    default: return nullptr;
    }
}

}  // namespace

void alias_device_iid(REFIID riid)
{
    if (is_device_alias(riid)) return;
    AcquireSRWLockExclusive(&g_alias_lock);
    const unsigned n = g_device_alias_count.load();
    if (n < max_device_aliases) {
        g_device_aliases[n] = riid;
        g_device_alias_count.store(n + 1);
    }
    ReleaseSRWLockExclusive(&g_alias_lock);
}

HRESULT wrap_device(ID3D12Device* real, REFIID riid, void** out, const void* caller)
{
    auto* device = new (std::nothrow) Device(real);
    if (!device) {
        real->Release();
        return E_OUTOFMEMORY;
    }
    count_device();
    install_dxgi_hooks(caller);
    device->attach_title_gpu();
    pipeline::prestart_translator();
    const HRESULT hr = device->query(riid, out, caller);
    device->Release();
    return hr;
}

IUnknown* real_queue_of(IUnknown* object)
{
    Kind kind;
    if (!wrapper_kind(object, &kind) || kind != Kind::queue) return nullptr;
    return static_cast<Queue*>(static_cast<ID3D12CommandQueue*>(object))->real();
}

HRESULT wrap_dxgi_swap_chain(IUnknown* wrapped_queue, IDXGISwapChain* real, REFIID riid, void** out)
{
    *out = nullptr;
    Kind kind;
    if (!real || !wrapper_kind(wrapped_queue, &kind) || kind != Kind::queue) return E_INVALIDARG;
    IDXGISwapChain3* chain3 = nullptr;
    HRESULT hr = real->QueryInterface(IID_PPV_ARGS(&chain3));
    real->Release();
    if (FAILED(hr)) return hr;
    auto* wrapped = new (std::nothrow) SwapChain(chain3, static_cast<Queue*>(static_cast<ID3D12CommandQueue*>(wrapped_queue)));
    return hand_out(wrapped, chain3, riid, out, nullptr);
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

extern "C" X2W_GFX_API IUnknown* WINAPI X2WGfxUnwrap(IUnknown* object)
{
    return object ? d3d12_xs::real_of(object) : nullptr;
}

