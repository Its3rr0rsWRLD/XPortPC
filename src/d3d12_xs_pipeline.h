#pragma once

// Pipeline translation, root signatures and draw-time bindings of the d3d12_xs.dll graphics shim (runtime rungs R3
// and R4, docs/design/runtime.md section 3).
//
// Root signatures. Every root signature created through the shim is the title's description (console-only flag bits
// and DENY_*_ROOT_ACCESS flags dropped) with the converter's parameters appended (ConverterParam). The converter's
// registers live in spaces 1000 to 1003 (tools/pso_translate.py), so they never meet the title's own. A title
// descriptor-table parameter becomes a one-word root-constant placeholder (b<index>, space 1004): its tables point
// into title heaps (d3d12_xs_descriptors.h), which desktop D3D12 never sees; the shim resolves what a translated
// shader reads from them at draw time. A RootInfo record is attached to the desktop object as private data.
//
// Pipelines. A shader whose bytecode is a console container (X2WShaderContainer, parse_container) is translated:
// the key is SHA-256 over the converter's fingerprint, the stage, the entry contract derived from the container and
// the code; %LOCALAPPDATA%\XPortPC\cache\<title>\<key>.dxil (with the descriptor-table reads in <key>.bind) is
// used when present, otherwise tools/pso_translate.py runs out of process (Python + DXC) and writes both. A refusal
// fails the pipeline with E_NOTIMPL and an X2W_GFX_EVENT_REFUSED event naming the refused form. A PsoInfo record
// (which root words feed which push words, which table descriptors feed which converter slots) is attached to the
// desktop pipeline as private data.
//
// Draws. bind_for_draw supplies the converter parameters before a draw of a translated pipeline: the push words
// from the recorded root arguments (title GPU addresses as the title passed them: the shader looks them up with
// TitleLookup), the title-memory view of xmem.dll (X2WTitleGpuGetShaderView) as a shader-visible heap the shim
// owns, a ranges buffer and their count, the base vertex and start instance, and the descriptors the shader reads
// from title descriptor tables: textures and samplers copied into blocks of the shim's shader-visible heaps (one
// block per distinct set of descriptor contents), constant buffers as root CBVs at the aliases of their title
// addresses, and buffer V#s as descriptor words (the V# each buffer view was encoded with, d3d12_xs_descriptors.h)
// in an upload block per distinct set of words, bound as one root CBV. A table read that finds no view of the
// expected kind is a TextureLookup miss: counted, logged once, and bound to a null SRV, a point sampler, a zero buffer
// or a zero V# (num_records 0), so the shader reads zero and stores nothing. A typed access through a buffer view
// whose format the converter does not lower exactly (anything but R32_UINT and R32_SINT) skips the draw (logged).
//
// Title memory is one table of the xmem.dll view: 8 raw SRVs, the miss counter UAV and the same 8 ranges as raw UAVs.
// A pipeline whose pixel program stores to title memory (pso_translate.py "memory rw") reads and writes it through the
// UAVs in both stages; every other pipeline reads the SRVs.
//
// Configuration (environment, until the launcher passes it): X2W_PYTHON (default python.exe), X2W_TOOLS (the
// tools directory; default <directory of d3d12_xs.dll>\tools), X2W_DXC (default dxc.exe), X2W_LLVM_LIB (optional
// libLLVM for disassembly), X2W_CACHE_DIR (replaces %LOCALAPPDATA%\XPortPC\cache), X2W_TITLE (default: the
// executable's base name).

#include <d3d12.h>

#include <cstdint>

namespace d3d12_xs {
namespace pipeline {

// Converter root parameters, appended after the title's parameters in this order (52 DWORDs in all).
enum ConverterParam : unsigned {
    param_range_count = 0,       // root constants b1 space1000: title_range_count
    param_ranges = 1,            // root SRV t2 space1000: StructuredBuffer<TitleRange> title_ranges
    param_memory = 2,            // table: SRV t0..t7 space1001 title_memory[8], UAV u0 space1000 x2w_lookup_misses,
                                 // UAV u0..u7 space1001 (title_memory[8] of a pipeline that stores)
    param_push_words = 3,        // root constants b3 space1000: uint4 push_words[8] (both stages)
    param_vertex_root = 4,       // root constants b2 space1000 (vertex): base_vertex, start_instance
    param_vertex_constants = 5,  // root CBV b0 space1000 (vertex): the constant buffer of a descriptor table
    param_pixel_constants = 6,   // root CBVs b0..b3 space1003 (pixel): constant slots 0 to 3 (four parameters)
    param_buffer_words = 10,     // root CBV b4 space1000 (both): uint4 vsharp_words[32], the buffer V#s of both stages
    param_textures = 11,         // table (pixel): SRV t0..t8 space1002, texture slots (t2 unused)
    param_samplers = 12,         // table (pixel): samplers s0..s3 space1002
    converter_params = 13
};
constexpr unsigned push_word_count = 32;
constexpr unsigned title_memory_slots = 8;
constexpr unsigned memory_block = 2 * title_memory_slots + 1;  // the SRVs, the miss counter UAV, the UAVs
constexpr unsigned texture_table = 9;
constexpr unsigned sampler_table = 4;
constexpr unsigned pixel_constant_slots = 4;
constexpr unsigned buffer_words = 128;        // vertex V#s at words 0..63, pixel V#s at 64..127
constexpr unsigned pixel_buffer_words = 64;
constexpr unsigned max_title_params = 64;
constexpr unsigned max_table_refs = 24;

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

// A descriptor a translated shader reads from a title descriptor table (tools/pso_translate.py --bindings).
enum class RefKind : std::uint8_t { texture = 0, sampler = 1, constants = 2, buffer = 3 };
constexpr std::uint8_t ref_typed = 1;   // buffer: a typed access (buffer_load_format, buffer_store_format)
constexpr std::uint8_t ref_stored = 2;  // buffer: stored to
struct TableRef {
    std::uint8_t stage;      // X2WShaderStage
    RefKind kind;
    std::uint8_t slot;       // converter slot: texture slot 0..7, sampler slot 0..3, constant slot; buffer: the first
                             // of its four descriptor words (0..60 vertex, 64..124 pixel)
    std::uint8_t parameter;  // the table's root parameter in the title's root signature
    std::uint32_t offset;    // byte offset in the table
    std::uint8_t flags;      // buffer: ref_typed, ref_stored
};

struct PsoInfo {
    std::uint32_t magic;
    std::uint32_t push_count;
    PushSource push[push_word_count];
    std::uint32_t ref_count;
    TableRef refs[max_table_refs];
    std::uint32_t writes_memory;  // title memory is bound as UAVs (a stage stores to it)
};

// Draw arguments the console stage receives in user SGPRs (vertex_aot roles base_vertex, start_instance).
struct DrawBases {
    std::uint32_t base_vertex;
    std::uint32_t start_instance;
};

// The title heaps a list has bound (d3d12_xs_descriptors.h serials; 0 for none) and whether it bound a desktop
// shader-visible heap the shim does not know.
struct BoundHeaps {
    std::uint32_t views = 0;
    std::uint32_t samplers = 0;
    bool foreign = false;
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

// The records attached at creation, or false for an object the shim did not create this way.
bool root_info(ID3D12RootSignature* root, RootInfo* info);
bool pso_info(ID3D12PipelineState* state, PsoInfo* info);

TitleViews* create_title_views(ID3D12Device* device);
void destroy_title_views(TitleViews* views);

// Sets the converter parameters for a draw of a translated pipeline on the desktop list; the caller then draws with
// zero base vertex and start instance. `ours_bound` tracks whether the shim's heaps are bound. Returns false, after
// logging, when the draw cannot be bound; the caller then skips the draw.
bool bind_for_draw(TitleViews* views, ID3D12GraphicsCommandList* list, const RootInfo& root, const PsoInfo& pso,
                   const RootArgs& args, const BoundHeaps& heaps, DrawBases bases, bool* ours_bound);
// The placeholders of the title's descriptor-table parameters, for a draw of a desktop pipeline with a title root
// signature (their registers are in space 1004, which desktop shaders do not declare).
void set_placeholders(ID3D12GraphicsCommandList* list, const RootInfo& root);

// Lookup misses (X2WGfxCounters): TitleLookup misses counted by translated shaders in the device's counter buffer
// (read without waiting; valid once the GPU work has completed), and TextureLookup misses counted at draw time.
std::uint64_t title_lookup_misses();

// Title GPU address -> desktop GPU address through xmem.dll (X2WTitleGpuTranslate), or the address unchanged when
// it is not title memory (a desktop resource's address) or xmem.dll is not loaded.
std::uint64_t translate_address(std::uint64_t address, std::uint64_t bytes);

// The reverse, for buffer views: the title GPU address of [offset, offset + bytes) of `resource`, when that range of
// its desktop GPU addresses lies in one title-memory alias (X2WTitleGpuGetShaderView); 0 otherwise.
std::uint64_t title_address_of(ID3D12Resource* resource, std::uint64_t offset, std::uint64_t bytes);

}  // namespace pipeline
}  // namespace d3d12_xs
