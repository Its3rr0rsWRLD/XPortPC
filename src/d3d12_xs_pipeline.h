#pragma once

// Pipeline translation, root signatures and draw-time bindings of the d3d12_xs.dll graphics shim (runtime rungs R3
// to R6, docs/design/runtime.md section 3).
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
// Compute (R5). create_compute_pipeline translates a compute container the same way (tools/pso_translate.py --stage
// compute, tools/compute_aot.py's lowering); bind_for_dispatch supplies the same converter parameters through the
// compute root arguments before a Dispatch. The compute translation reads and writes title memory through the UAV
// half of the title-memory table. Descriptor tables (R6): a buffer V# the program loads from a table is copied
// from the table's memory into its frame words (the program applies the V#'s range check itself), T#s and the S#
// are bound as for a draw.
//
// Draws. bind_for_draw supplies the converter parameters before a draw of a translated pipeline: the frame words
// (FrameWords: the push words from the recorded root arguments, title GPU addresses as the title passed them since
// the shader looks them up with TitleLookup; the range count; the base vertex and start instance) in a slice of
// the shim's upload ring, the title-memory view of xmem.dll (X2WTitleGpuGetShaderView) as a shader-visible heap the
// shim owns and a ranges buffer, and the descriptors the shader reads from title descriptor tables: textures and
// samplers copied into blocks of the shim's shader-visible heaps (one block per distinct set of descriptor
// contents), constant buffers as root CBVs at the aliases of their title addresses. Hardware words the title wrote
// into a table itself (R6) are decoded (src/gfx10_descriptors.h): a T# becomes a desktop texture the shim fills from
// the title's texture memory (detiled, src/gfx10_detile.h) and caches by the words and a hash of the bytes, an S# a
// cached desktop sampler, a constant-buffer V# a root CBV at its base address. A table read that finds no view of
// the expected kind, or words that do not decode, is a TextureLookup miss: counted, logged once, and bound to a null
// SRV, a point sampler or a zero buffer, so the shader reads zero.
//
// Configuration (environment, until the launcher passes it): X2W_PYTHON (default python.exe), X2W_TOOLS (the
// tools directory; default <directory of d3d12_xs.dll>\tools), X2W_DXC (default dxc.exe), X2W_LLVM_LIB (optional
// libLLVM for disassembly), X2W_CACHE_DIR (replaces %LOCALAPPDATA%\XPortPC\cache), X2W_TITLE (default: the
// executable's base name).

#include <d3d12.h>

#include <cstdint>
#include <vector>

namespace d3d12_xs {
namespace pipeline {

// Converter root parameters, appended after the title's parameters in this order (13 DWORDs in all).
enum ConverterParam : unsigned {
    param_ranges = 0,            // root SRV t2 space1000: StructuredBuffer<TitleRange> title_ranges (2 DWORDs)
    param_memory = 1,            // table: SRV t0..t7 space1001 title_memory[8], UAV u0 space1000 x2w_lookup_misses,
                                 // UAV u0..u7 space1001 (compute: RWByteAddressBuffer title_memory[8]) of the same ranges
    param_frame = 2,             // root CBV b3 space1000: the frame words of the draw or dispatch (FrameWords), a
                                 // slice of the shim's upload ring (2 DWORDs; was 32 + 1 + 2 root constants)
    param_vertex_constants = 3,  // root CBV b0 space1000 (vertex): the constant buffer of a descriptor table
    param_pixel_constants = 4,   // root CBVs b0, b1 space1003 (pixel): constant slots 0 and 1 (two parameters)
    param_textures = 6,          // table: SRV t0..t8 space1002, texture slots (t2 unused); pixel and compute
    param_samplers = 7,          // table: samplers s0..s3 space1002; pixel and compute
    converter_params = 8
};
constexpr unsigned converter_root_dwords = 13;
constexpr unsigned push_word_count = 32;  // root-word bindings of one pipeline
// The frame words (tools/pso_translate.py FRAME_WORDS): 64 words (push words; a compute program's params, with the
// buffer V#s it reads from descriptor tables copied in at the top), then the title range count, the base vertex and
// the start instance. One 512-byte slice (CBV alignment 256) per draw or dispatch.
constexpr unsigned frame_word_count = 64;
struct FrameWords {
    std::uint32_t words[frame_word_count];
    std::uint32_t range_count;
    std::uint32_t base_vertex;
    std::uint32_t start_instance;
    std::uint32_t reserved;
};
constexpr unsigned frame_slice = 512;
static_assert(sizeof(FrameWords) <= frame_slice, "frame words slice");
constexpr unsigned title_memory_slots = 8;
constexpr unsigned memory_block = 2 * title_memory_slots + 1;  // the SRVs, the miss counter UAV, the UAVs (R5)
constexpr unsigned texture_table = 9;
constexpr unsigned sampler_table = 4;
constexpr unsigned pixel_constant_slots = 2;
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

// A descriptor a translated shader reads from a title descriptor table (tools/pso_translate.py --bindings), or an
// inline sampler (S# words set by s_mov in the program, decoded at pipeline creation).
enum class RefKind : std::uint8_t { texture = 0, sampler = 1, constants = 2, buffer = 3, inline_sampler = 4 };
struct TableRef {
    std::uint8_t stage;      // X2WShaderStage
    RefKind kind;
    std::uint8_t slot;       // converter slot: texture slot 0..7, sampler slot 0..3, constant slot; buffer (compute):
                             // the first of its four frame words
    std::uint8_t parameter;  // the table's root parameter in the title's root signature
    std::uint32_t offset;    // byte offset in the table
    std::uint32_t words[4];  // inline_sampler: the S# words
};

struct PsoInfo {
    std::uint32_t magic;
    std::uint32_t push_count;
    PushSource push[push_word_count];
    std::uint32_t ref_count;
    TableRef refs[max_table_refs];
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

// The blocks of the shim's shader-visible heaps (title-memory views, texture and sampler tables) one command list's
// recorded draws and dispatches read (R5). bind_for_draw/bind_for_dispatch add to it; the list releases it when it is
// reset or destroyed (release_blocks), and the queue stamps it on each submission (submitted_blocks), so a block is
// rewritten only once no list holds it and the GPU has finished with it.
struct BlockUse {
    std::vector<std::uint32_t> blocks;  // kind << 24 | index
    // The frame-word ring chunk this recording writes its draws' and dispatches' frame words into, and how many of
    // its slices it has used (R6).
    int frame_chunk = -1;
    std::uint32_t frame_used = 0;
};
void release_blocks(TitleViews* views, BlockUse& use);
void submitted_blocks(TitleViews* views, ID3D12CommandQueue* queue, BlockUse* const* uses, unsigned count);

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
// The record of a translated compute pipeline (R5); pso_info answers false for one.
bool compute_pso_info(ID3D12PipelineState* state, PsoInfo* info);

TitleViews* create_title_views(ID3D12Device* device);
void destroy_title_views(TitleViews* views);

// Sets the converter parameters for a draw of a translated pipeline on the desktop list; the caller then draws with
// zero base vertex and start instance. `ours_bound` tracks whether the shim's heaps are bound. Returns false, after
// logging, when the draw cannot be bound; the caller then skips the draw.
bool bind_for_draw(TitleViews* views, ID3D12GraphicsCommandList* list, const RootInfo& root, const PsoInfo& pso,
                   const RootArgs& args, const BoundHeaps& heaps, DrawBases bases, bool* ours_bound, BlockUse* use);
// The placeholders of the title's descriptor-table parameters, for a draw of a desktop pipeline with a title root
// signature (their registers are in space 1004, which desktop shaders do not declare).
void set_placeholders(ID3D12GraphicsCommandList* list, const RootInfo& root);

// Lookup misses (X2WGfxCounters): TitleLookup misses counted by translated shaders in the device's counter buffer
// (read without waiting; valid once the GPU work has completed), and TextureLookup misses counted at draw time.
std::uint64_t title_lookup_misses();

// The compute counterpart (runtime rung R5): the converter parameters of a translated compute pipeline through the
// compute root arguments, before a Dispatch. Same contract as bind_for_draw.
bool bind_for_dispatch(TitleViews* views, ID3D12GraphicsCommandList* list, const RootInfo& root, const PsoInfo& pso,
                       const RootArgs& args, const BoundHeaps& heaps, bool* ours_bound, BlockUse* use);
// set_placeholders for the compute root arguments.
void set_compute_placeholders(ID3D12GraphicsCommandList* list, const RootInfo& root);

// Title GPU address -> desktop GPU address through xmem.dll (X2WTitleGpuTranslate), or the address unchanged when
// it is not title memory (a desktop resource's address) or xmem.dll is not loaded.
std::uint64_t translate_address(std::uint64_t address, std::uint64_t bytes);

}  // namespace pipeline
}  // namespace d3d12_xs
