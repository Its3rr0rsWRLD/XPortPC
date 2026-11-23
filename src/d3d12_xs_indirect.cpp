// ExecuteIndirect argument rewrites (d3d12_xs_indirect.h).
#include "d3d12_xs_indirect.h"

#include "d3d12_xs_resources.h"
#include "d3d12_xs_wrap.h"

#include "d3d12_xs_indirect_cs.h"  // x2w_indirect_cs: d3d12_xs_indirect.hlsl, built by DXC (CMakeLists.txt)

#include <algorithm>
#include <cstring>
#include <mutex>
#include <new>

using Microsoft::WRL::ComPtr;

namespace d3d12_xs {
namespace indirect {

Layout describe(const D3D12_COMMAND_SIGNATURE_DESC& desc)
{
    Layout layout;
    layout.stride = desc.ByteStride;
    UINT at = 0;
    const auto field = [&](UINT offset) {
        if (layout.field_count == max_fields) {
            layout.refused = "more than 16 address fields in one record";
            return;
        }
        layout.fields[layout.field_count++] = offset;
    };
    for (UINT i = 0; i < desc.NumArgumentDescs && desc.pArgumentDescs; ++i) {
        const D3D12_INDIRECT_ARGUMENT_DESC& a = desc.pArgumentDescs[i];
        switch (static_cast<int>(a.Type)) {
        case D3D12_INDIRECT_ARGUMENT_TYPE_DRAW: layout.op = Op::draw; at += sizeof(D3D12_DRAW_ARGUMENTS); break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_DRAW_INDEXED:
            layout.op = Op::draw_indexed;
            at += sizeof(D3D12_DRAW_INDEXED_ARGUMENTS);
            break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH:
            layout.op = Op::dispatch;
            at += sizeof(D3D12_DISPATCH_ARGUMENTS);
            break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_VERTEX_BUFFER_VIEW:
            field(at);
            at += sizeof(D3D12_VERTEX_BUFFER_VIEW);
            break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_INDEX_BUFFER_VIEW:
            field(at);
            at += sizeof(D3D12_INDEX_BUFFER_VIEW);
            break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT:
            layout.constants = true;
            at += 4 * a.Constant.Num32BitValuesToSet;
            break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_CONSTANT_BUFFER_VIEW:
        case D3D12_INDIRECT_ARGUMENT_TYPE_SHADER_RESOURCE_VIEW:
        case D3D12_INDIRECT_ARGUMENT_TYPE_UNORDERED_ACCESS_VIEW:
            field(at);
            at += sizeof(D3D12_GPU_VIRTUAL_ADDRESS);
            break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH_RAYS:
            layout.op = Op::dispatch_rays;
            layout.refused = "indirect DispatchRays (shader tables and their records hold title addresses the shim "
                             "does not rewrite)";
            at += sizeof(D3D12_DISPATCH_RAYS_DESC);
            break;
        case D3D12_INDIRECT_ARGUMENT_TYPE_DISPATCH_MESH:
            layout.op = Op::dispatch_mesh;
            at += sizeof(D3D12_DISPATCH_MESH_ARGUMENTS);
            break;
        case 11:  // D3D12_INDIRECT_ARGUMENT_TYPE_INCREMENTING_CONSTANT (newer headers): a root constant
            layout.constants = true;
            at += 4;
            break;
        default:
            layout.refused = "an indirect argument type the shim does not know";
            break;
        }
    }
    if (!layout.refused && at > desc.ByteStride) layout.refused = "the arguments do not fit the byte stride";
    if (!layout.refused && desc.ByteStride % 4) layout.refused = "a byte stride that is not a multiple of 4";
    return layout;
}

class Rewriter {
public:
    explicit Rewriter(ID3D12Device* device) : device_(device) {}

    bool ready(std::string& why)
    {
        std::lock_guard<std::mutex> guard(lock_);
        if (pso_) return true;
        if (failed_) {
            why = "the rewrite pipeline could not be created";
            return false;
        }
        D3D12_ROOT_PARAMETER params[4]{};
        params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        params[0].Constants = {0, 0, constant_words};
        params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
        params[1].Descriptor = {0, 0};
        params[2].ParameterType = D3D12_ROOT_PARAMETER_TYPE_SRV;
        params[2].Descriptor = {1, 0};
        params[3].ParameterType = D3D12_ROOT_PARAMETER_TYPE_UAV;
        params[3].Descriptor = {0, 0};
        D3D12_ROOT_SIGNATURE_DESC desc{};
        desc.NumParameters = 4;
        desc.pParameters = params;
        ComPtr<ID3DBlob> blob, errors;
        D3D12_COMPUTE_PIPELINE_STATE_DESC pso{};
        if (FAILED(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &blob, &errors)) ||
            FAILED(device_->CreateRootSignature(0, blob->GetBufferPointer(), blob->GetBufferSize(),
                                                IID_PPV_ARGS(&root_)))) {
            failed_ = true;
            why = "the rewrite root signature could not be created";
            return false;
        }
        pso.pRootSignature = root_.Get();
        pso.CS = {x2w_indirect_cs, sizeof(x2w_indirect_cs)};
        if (FAILED(device_->CreateComputePipelineState(&pso, IID_PPV_ARGS(&pso_)))) {
            failed_ = true;
            root_.Reset();
            why = "the rewrite pipeline could not be created";
            return false;
        }
        return true;
    }

    // A pooled or new buffer of at least `bytes`: DEFAULT with UAV access, or UPLOAD (mapped: *mapped).
    ComPtr<ID3D12Resource> buffer(UINT64 bytes, bool upload, void** mapped)
    {
        bytes = std::max<UINT64>((bytes + 255) & ~UINT64(255), 256);
        {
            std::lock_guard<std::mutex> guard(lock_);
            auto& pool = upload ? uploads_ : defaults_;
            auto best = pool.end();
            for (auto it = pool.begin(); it != pool.end(); ++it)
                if (it->bytes >= bytes && (best == pool.end() || it->bytes < best->bytes)) best = it;
            if (best != pool.end()) {
                ComPtr<ID3D12Resource> found = best->buffer;
                pool.erase(best);
                if (upload && FAILED(found->Map(0, nullptr, mapped))) return {};
                return found;
            }
        }
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = upload ? D3D12_HEAP_TYPE_UPLOAD : D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = bytes;
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        desc.Flags = upload ? D3D12_RESOURCE_FLAG_NONE : D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        ComPtr<ID3D12Resource> made;
        if (FAILED(device_->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc,
                                                    upload ? D3D12_RESOURCE_STATE_GENERIC_READ
                                                           : D3D12_RESOURCE_STATE_COMMON,
                                                    nullptr, IID_PPV_ARGS(&made))))
            return {};
        if (upload && FAILED(made->Map(0, nullptr, mapped))) return {};
        return made;
    }
    void give_back(Keep::Held& held)
    {
        if (held.upload) held.buffer->Unmap(0, nullptr);
        std::lock_guard<std::mutex> guard(lock_);
        (held.upload ? uploads_ : defaults_).push_back(std::move(held));
    }

    ID3D12RootSignature* root() const { return root_.Get(); }
    ID3D12PipelineState* pso() const { return pso_.Get(); }

    static constexpr UINT constant_words = 24;

private:
    ID3D12Device* device_;  // the desktop device; the owning wrapper outlives this object
    std::mutex lock_;
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pso_;
    bool failed_ = false;
    std::vector<Keep::Held> defaults_, uploads_;
};

Rewriter* create_rewriter(ID3D12Device* device) { return new (std::nothrow) Rewriter(device); }
void destroy_rewriter(Rewriter* rewriter) { delete rewriter; }

void recycle(Keep& keep)
{
    if (keep.owner)
        for (Keep::Held& held : keep.held) keep.owner->give_back(held);
    keep.held.clear();
}

namespace {

D3D12_RESOURCE_DESC desc_of(ID3D12Resource* resource)
{
#ifdef WIDL_EXPLICIT_AGGREGATE_RETURNS
    D3D12_RESOURCE_DESC desc{};
    resource->GetDesc(&desc);
    return desc;
#else
    return resource->GetDesc();
#endif
}

D3D12_RESOURCE_BARRIER transition(ID3D12Resource* resource, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
{
    D3D12_RESOURCE_BARRIER b{};
    b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource = resource;
    b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore = before;
    b.Transition.StateAfter = after;
    return b;
}

D3D12_BUFFER_BARRIER buffer_barrier(ID3D12Resource* resource, D3D12_BARRIER_SYNC sync_before,
                                    D3D12_BARRIER_SYNC sync_after, D3D12_BARRIER_ACCESS access_before,
                                    D3D12_BARRIER_ACCESS access_after)
{
    D3D12_BUFFER_BARRIER b{};
    b.SyncBefore = sync_before;
    b.SyncAfter = sync_after;
    b.AccessBefore = access_before;
    b.AccessAfter = access_after;
    b.pResource = resource;
    b.Offset = 0;
    b.Size = UINT64_MAX;
    return b;
}

void buffer_barriers(ID3D12GraphicsCommandList7* list, UINT count, const D3D12_BUFFER_BARRIER* barriers)
{
    D3D12_BARRIER_GROUP group{};
    group.Type = D3D12_BARRIER_TYPE_BUFFER;
    group.NumBarriers = count;
    group.pBufferBarriers = barriers;
    list->Barrier(1, &group);
}

}  // namespace

bool record(Rewriter* rewriter, ID3D12GraphicsCommandList* list, ID3D12GraphicsCommandList7* enhanced,
            ID3D12Resource* source, UINT64 offset, UINT commands, const Layout& layout, Keep& keep,
            ID3D12Resource** out, std::string& why)
{
    *out = nullptr;
    if (!rewriter || !rewriter->ready(why)) {
        if (why.empty()) why = "no rewrite pipeline";
        return false;
    }
    if (!source || !commands) {
        why = "no argument buffer or no commands";
        return false;
    }
    const D3D12_RESOURCE_DESC desc = desc_of(source);
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_BUFFER || offset >= desc.Width || offset % 4) {
        why = "the argument offset is outside the argument buffer or not 4-byte aligned";
        return false;
    }
    const UINT64 limit64 = desc.Width - offset;
    const UINT64 out_bytes = UINT64(commands) * layout.stride;
    if (out_bytes > 0xffffffffull) {
        why = "more than 4 GiB of argument records";
        return false;
    }
    std::vector<resources::Translation> ranges;
    if (!resources::translations(ranges)) {
        why = "X2WTitleGpuGetTranslations failed";
        return false;
    }
    void* mapped = nullptr;
    ComPtr<ID3D12Resource> table = rewriter->buffer(ranges.size() * sizeof(resources::Translation), true, &mapped);
    ComPtr<ID3D12Resource> dest = rewriter->buffer(out_bytes, false, nullptr);
    if (!table || !dest) {
        why = "out of memory for the rewrite buffers";
        return false;
    }
    if (!ranges.empty()) std::memcpy(mapped, ranges.data(), ranges.size() * sizeof(ranges[0]));
    keep.owner = rewriter;
    try {
        keep.held.push_back({table, ranges.size() * sizeof(resources::Translation), true});
        keep.held.push_back({dest, out_bytes, false});
    } catch (...) {
        why = "out of memory";
        return false;
    }

    // An UPLOAD buffer stays in GENERIC_READ, which includes both reads, and needs no barrier; any other buffer
    // moves from indirect-argument reads to shader reads for the pass and back.
    D3D12_HEAP_PROPERTIES heap{};
    const bool upload = SUCCEEDED(source->GetHeapProperties(&heap, nullptr)) && heap.Type == D3D12_HEAP_TYPE_UPLOAD;
    // Before: the title's buffer becomes readable by the pass.
    if (upload) {
    } else if (enhanced) {
        const D3D12_BUFFER_BARRIER before =
            buffer_barrier(source, D3D12_BARRIER_SYNC_EXECUTE_INDIRECT, D3D12_BARRIER_SYNC_COMPUTE_SHADING,
                           D3D12_BARRIER_ACCESS_INDIRECT_ARGUMENT, D3D12_BARRIER_ACCESS_SHADER_RESOURCE);
        buffer_barriers(enhanced, 1, &before);
    } else {
        const D3D12_RESOURCE_BARRIER before = transition(source, D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT,
                                                         D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        list->ResourceBarrier(1, &before);
    }

    std::uint32_t constants[Rewriter::constant_words] = {};
    constants[0] = commands;
    constants[1] = layout.stride;
    constants[2] = static_cast<std::uint32_t>(std::min<UINT64>(limit64, 0xffffffffull));
    constants[3] = static_cast<std::uint32_t>(ranges.size());
    constants[4] = layout.field_count;
    for (UINT f = 0; f < layout.field_count; ++f) constants[8 + f] = layout.fields[f];
    list->SetComputeRootSignature(rewriter->root());
    list->SetPipelineState(rewriter->pso());
    list->SetComputeRoot32BitConstants(0, Rewriter::constant_words, constants, 0);
    list->SetComputeRootShaderResourceView(1, source->GetGPUVirtualAddress() + offset);
    list->SetComputeRootShaderResourceView(2, table->GetGPUVirtualAddress());
    list->SetComputeRootUnorderedAccessView(3, dest->GetGPUVirtualAddress());
    list->Dispatch((commands + 63) / 64, 1, 1);

    // After: the copy and the title's buffer are indirect arguments again.
    if (enhanced) {
        const D3D12_BUFFER_BARRIER after[2] = {
            buffer_barrier(dest.Get(), D3D12_BARRIER_SYNC_COMPUTE_SHADING, D3D12_BARRIER_SYNC_EXECUTE_INDIRECT,
                           D3D12_BARRIER_ACCESS_UNORDERED_ACCESS, D3D12_BARRIER_ACCESS_INDIRECT_ARGUMENT),
            buffer_barrier(source, D3D12_BARRIER_SYNC_COMPUTE_SHADING, D3D12_BARRIER_SYNC_EXECUTE_INDIRECT,
                           D3D12_BARRIER_ACCESS_SHADER_RESOURCE, D3D12_BARRIER_ACCESS_INDIRECT_ARGUMENT)};
        buffer_barriers(enhanced, upload ? 1 : 2, after);
    } else if (upload) {
        const D3D12_RESOURCE_BARRIER after =
            transition(dest.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT);
        list->ResourceBarrier(1, &after);
    } else {
        // The copy was promoted from COMMON to UNORDERED_ACCESS by the pass's write.
        const D3D12_RESOURCE_BARRIER after[2] = {
            transition(dest.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT),
            transition(source, D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT)};
        list->ResourceBarrier(2, after);
    }
    count_indirect_rewrite();
    *out = dest.Get();
    return true;
}

}  // namespace indirect
}  // namespace d3d12_xs
