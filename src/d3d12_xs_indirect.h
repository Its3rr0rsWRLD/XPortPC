#pragma once

// ExecuteIndirect with title GPU addresses in its argument buffer (docs/design/runtime.md, section 3).
//
// An indirect argument record can hold GPU addresses: vertex and index buffer views, root CBV/SRV/UAV addresses.
// A title writes title addresses there (d3d12_xs_resources.h), often from the GPU, and desktop D3D12 would read them
// as desktop addresses. So before the desktop ExecuteIndirect the shim records a compute pass that copies the
// records the call can read into a buffer of its own, translating each address field through the ranges xmem.dll
// translates (snapshot at record time; d3d12_xs_indirect.hlsl), and the desktop call reads that copy. Records
// without address fields (draw, dispatch and mesh arguments, root constants) are executed in place.
//
// The pass changes command-list state that the list wrapper restores afterwards: the pipeline state, the compute
// root signature and its arguments, and predication (suspended around the pass). It cannot run in a bundle or in a
// render pass (no dispatch is allowed there); those calls are refused. Barriers: an argument buffer in an UPLOAD heap
// (always GENERIC_READ) needs none. Otherwise, with legacy barriers the argument buffer must be in exactly
// D3D12_RESOURCE_STATE_INDIRECT_ARGUMENT, as ExecuteIndirect requires, and is moved to
// NON_PIXEL_SHADER_RESOURCE for the pass and back; a list that has recorded enhanced barriers (Barrier) gets enhanced
// buffer barriers instead, from and back to EXECUTE_INDIRECT / INDIRECT_ARGUMENT. The shim's output buffers are
// held by the command allocator the list records into and reused once that allocator is reset.

#include <d3d12.h>
#include <wrl/client.h>

#include <cstdint>
#include <string>
#include <vector>

namespace d3d12_xs {
namespace indirect {

constexpr unsigned max_fields = 16;

enum class Op : std::uint8_t { none, draw, draw_indexed, dispatch, dispatch_mesh, dispatch_rays };

struct Layout {
    UINT stride = 0;
    UINT field_count = 0;          // 64-bit address fields per record
    UINT fields[max_fields] = {};  // their byte offsets
    Op op = Op::none;
    bool constants = false;        // root constants are set per record
    const char* refused = nullptr; // why the signature cannot be executed by the shim, or null
};
Layout describe(const D3D12_COMMAND_SIGNATURE_DESC& desc);

class Rewriter;
Rewriter* create_rewriter(ID3D12Device* device);
void destroy_rewriter(Rewriter* rewriter);

// Buffers one command allocator's recordings read, returned to the rewriter's pool when it is reset.
struct Keep {
    struct Held {
        Microsoft::WRL::ComPtr<ID3D12Resource> buffer;
        UINT64 bytes;
        bool upload;
    };
    Rewriter* owner = nullptr;
    std::vector<Held> held;
};
void recycle(Keep& keep);

// Records the rewrite of `commands` records of `layout` read from `source` (a desktop buffer) at `offset`. On success
// `*out` is the shim's buffer holding the translated records at offset 0, in INDIRECT_ARGUMENT state (or with
// INDIRECT_ARGUMENT access after enhanced barriers), held by `keep`. `enhanced` is the list's
// ID3D12GraphicsCommandList7 when it records enhanced barriers, otherwise null.
bool record(Rewriter* rewriter, ID3D12GraphicsCommandList* list, ID3D12GraphicsCommandList7* enhanced,
            ID3D12Resource* source, UINT64 offset, UINT commands, const Layout& layout, Keep& keep,
            ID3D12Resource** out, std::string& why);

}  // namespace indirect
}  // namespace d3d12_xs
