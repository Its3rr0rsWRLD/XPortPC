#pragma once

// Pipeline translation of the d3d12_xs.dll graphics shim (runtime rung R3, docs/design/runtime.md section 3).
//
// Root signatures. Every root signature created through the shim is the title's description (console-only flag bits
// and DENY_*_ROOT_ACCESS flags dropped) with the converter's parameters appended (ConverterParam). The converter's
// registers live in spaces 1000 and 1001 (tools/pso_translate.py), so they never meet the title's own. A RootInfo
// record is attached to the desktop object as private data.
//
// Pipelines. A shader whose bytecode is a console container (X2WShaderContainer, parse_container) is translated:
// the key is SHA-256 over the converter's fingerprint, the stage, the entry contract derived from the container and
// the code; %LOCALAPPDATA%\XPortPC\cache\<title>\<key>.dxil is used when present, otherwise tools/pso_translate.py
// runs out of process (Python + DXC) and writes it. A refusal fails the pipeline with E_NOTIMPL and an
// X2W_GFX_EVENT_REFUSED event naming the refused form. A PsoInfo record (which root words feed which push words) is
// attached to the desktop pipeline as private data.
//
// Draws. bind_for_draw supplies the converter parameters before a draw of a translated pipeline: the push words
// from the recorded root arguments (title GPU addresses as the title passed them: the shader looks them up with
// TitleLookup), and the title-memory view of xmem.dll (X2WTitleGpuGetShaderView) as a shader-visible heap the shim
// owns, a ranges buffer and their count.
//
// Configuration (environment, until the launcher passes it): X2W_PYTHON (default python.exe), X2W_TOOLS (the
// tools directory; default <directory of d3d12_xs.dll>\tools), X2W_DXC (default dxc.exe), X2W_LLVM_LIB (optional
// libLLVM for disassembly), X2W_CACHE_DIR (replaces %LOCALAPPDATA%\XPortPC\cache), X2W_TITLE (default: the
// executable's base name).

#include <d3d12.h>

#include <cstdint>

namespace d3d12_xs {
namespace pipeline {

// Converter root parameters, appended after the title's parameters in this order.
enum ConverterParam : unsigned {
    param_range_count = 0,  // root constants b1 space1000: title_range_count
    param_ranges = 1,       // root SRV t2 space1000: StructuredBuffer<TitleRange> title_ranges
    param_memory = 2,       // table: SRV t0..t7 space1001: ByteAddressBuffer title_memory[8]
    param_push_words = 3,   // root constants b3 space1000: uint4 push_words[8]
    converter_params = 4
};
constexpr unsigned push_word_count = 32;
constexpr unsigned title_memory_slots = 8;
constexpr unsigned max_title_params = 64;

struct RootInfo {
    std::uint32_t magic;
    std::uint32_t title_params;  // index of the first converter parameter
    std::uint8_t types[max_title_params];      // D3D12_ROOT_PARAMETER_TYPE of each title parameter
    std::uint8_t constants[max_title_params];  // Num32BitValues of root-constant parameters
};

struct PushSource {
    std::uint8_t parameter;
    std::uint8_t word;
};

struct PsoInfo {
    std::uint32_t magic;
    std::uint32_t push_count;
    PushSource push[push_word_count];
};

// Root arguments recorded by a command list (graphics bindings), indexed by root parameter.
struct RootArgs {
    std::uint64_t address[max_title_params];
    std::uint32_t constants[max_title_params][64];
    void clear();
};

class TitleViews;

HRESULT create_root_signature(ID3D12Device* device, UINT node_mask, const void* blob, SIZE_T size, REFIID riid,
                              void** out);
HRESULT create_graphics_pipeline(ID3D12Device* device, const D3D12_GRAPHICS_PIPELINE_STATE_DESC* desc, REFIID riid,
                                 void** out);
HRESULT create_compute_pipeline(ID3D12Device* device, const D3D12_COMPUTE_PIPELINE_STATE_DESC* desc, REFIID riid,
                                void** out);

// Starts the first translator service in the background (at device creation), unless X2W_TRANSLATE says otherwise.
void prestart_translator();

// The records attached at creation, or false for an object the shim did not create this way.
bool root_info(ID3D12RootSignature* root, RootInfo* info);
bool pso_info(ID3D12PipelineState* state, PsoInfo* info);

TitleViews* create_title_views(ID3D12Device* device);
void destroy_title_views(TitleViews* views);

// Sets the converter parameters for a draw of a translated pipeline on the desktop list. `title_heap` is the
// CBV/SRV/UAV heap the title bound on this list (null for none); `ours_bound` tracks whether the shim's heap is
// bound. Returns false, after logging, when the draw cannot be bound; the caller then skips the draw.
bool bind_for_draw(TitleViews* views, ID3D12GraphicsCommandList* list, const RootInfo& root, const PsoInfo& pso,
                   const RootArgs& args, ID3D12DescriptorHeap* title_heap, bool* ours_bound);

// Title GPU address -> desktop GPU address through xmem.dll (X2WTitleGpuTranslate), or the address unchanged when
// it is not title memory (a desktop resource's address) or xmem.dll is not loaded.
std::uint64_t translate_address(std::uint64_t address, std::uint64_t bytes);

}  // namespace pipeline
}  // namespace d3d12_xs
