#pragma once

// XPortPC-specific exports of the desktop d3d12_xs.dll graphics shim (src/d3d12_xs_shim.cpp).
// The console-facing exports (D3D12CreateDevice and the root-signature functions) keep their
// desktop d3d12.h declarations; this header adds what has no public console name:
// - a present path the shim owns (the console's present entry point is not publicly documented;
//   it is mapped onto this once an owner log shows which call presents);
// - the logging interface for first uses and unimplemented entries;
// - counters for tests and the game report.
//
// Logging interface. The shim reports four kinds of events. Without a sink they are written to
// stderr in the launcher's "[x2w] ..." style. A sink replaces that output; it is the hook the
// launcher's x2w_unimplemented()/report code attaches to later (docs/design/runtime.md, section 1,
// level 3). Events of kind UNKNOWN_SLOT and UNKNOWN_IID are reported once per distinct
// (interface, slot) or (interface, IID); every call is counted.

#include <stdint.h>
#include <windows.h>
#include <dxgi1_2.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef X2W_GFX_API
#ifdef X2W_GFX_EXPORTS
#define X2W_GFX_API __declspec(dllexport)
#else
#define X2W_GFX_API __declspec(dllimport)
#endif
#endif

typedef enum X2WGfxEventKind {
    X2W_GFX_EVENT_FIRST_USE = 1,     // first call of a wrapped method in this process
    X2W_GFX_EVENT_UNKNOWN_SLOT = 2,  // vtable slot past the interface's public methods; returned E_NOTIMPL
    X2W_GFX_EVENT_UNKNOWN_IID = 3,   // QueryInterface of an IID the wrapper does not implement; E_NOINTERFACE
    X2W_GFX_EVENT_NOTE = 4,          // shim decisions worth a line (title GPU attach, passthrough IIDs)
    X2W_GFX_EVENT_REFUSED = 5        // a pipeline or draw the shim cannot translate; detail names the refused form
} X2WGfxEventKind;

typedef struct X2WGfxEvent {
    uint32_t kind;               // X2WGfxEventKind
    uint32_t slot;               // vtable slot index (UNKNOWN_SLOT), otherwise 0
    const char* interface_name;  // public desktop interface the wrapper implements, e.g. "ID3D12Device"
    const char* symbol;          // "d3d12_xs!ID3D12Device::CreateFence", "d3d12_xs!ID3D12Device::slot47"
    const char* detail;          // human-readable rest of the line (IID, caller, arguments)
    GUID iid;                    // UNKNOWN_IID and passthrough notes, otherwise zero
    const void* caller;          // return address of the call into the shim
    uint64_t args[4];            // this pointer, then RDX, R8, R9 as integers (UNKNOWN_SLOT)
} X2WGfxEvent;

typedef void (WINAPI* X2WGfxLogSink)(const X2WGfxEvent* event, void* context);

// Replaces the sink (null restores stderr output). Returns the previous sink.
X2W_GFX_API X2WGfxLogSink WINAPI X2WGfxSetLogSink(X2WGfxLogSink sink, void* context);

typedef struct X2WGfxCounters {
    uint32_t size;                // set by the caller to sizeof(X2WGfxCounters)
    uint32_t live_objects;        // wrapper objects not yet released
    uint32_t devices_created;     // devices created through D3D12CreateDevice
    uint32_t presents;            // successful Present/Present1 calls through wrapped swap chains
    uint64_t first_uses;          // distinct wrapped methods called so far
    uint64_t unknown_slot_calls;  // every call into an unknown vtable slot
    uint64_t unknown_iid_calls;   // every QueryInterface that failed for an unknown IID
    int32_t title_gpu_state;      // X2WGfxTitleGpuState
    int32_t title_gpu_hr;         // HRESULT of the last X2WTitleGpuAttach, when one was made
    uint32_t shaders_translated;  // console shaders translated at pipeline creation (cache misses that succeeded)
    uint32_t shaders_cached;      // console shaders whose translation came from the on-disk cache
    uint32_t pipelines_refused;   // pipeline creations failed with a logged REFUSED event
    uint32_t draws_refused;       // draws not recorded because their bindings cannot be supplied (logged)
    // Lookup misses (runtime rung R4). TitleLookup: loads of translated shaders from a title GPU address that no
    // title memory range holds (they read zero), counted on the GPU; the count covers GPU work that has completed.
    // TextureLookup: descriptors a translated draw reads from a title descriptor table (T#, S#, constant-buffer V#)
    // where the table's heap holds no view of that kind (the draw reads a null view, a point sampler or zeros).
    uint64_t title_lookup_misses;
    uint64_t texture_lookup_misses;
} X2WGfxCounters;

typedef enum X2WGfxTitleGpuState {
    X2W_GFX_TITLE_GPU_NOT_TRIED = 0,
    X2W_GFX_TITLE_GPU_NO_XMEM = 1,    // xmem.dll is not loaded in the process: nothing to attach
    X2W_GFX_TITLE_GPU_ATTACHED = 2,   // X2WTitleGpuAttach returned S_OK
    X2W_GFX_TITLE_GPU_FAILED = 3      // X2WTitleGpuAttach failed; title_gpu_hr says why
} X2WGfxTitleGpuState;

// Returns FALSE when counters is null or counters->size is too small.
X2W_GFX_API BOOL WINAPI X2WGfxGetCounters(X2WGfxCounters* counters);

// The shim-owned present path: IDXGIFactory2::CreateSwapChainForHwnd on the desktop factory with
// the desktop queue behind a wrapped command queue, returned as a wrapped swap chain (public
// IDXGISwapChain3 method order) through riid. A queue that is not a shim queue is refused with
// E_INVALIDARG.
X2W_GFX_API HRESULT WINAPI X2WGfxCreateSwapChainForHwnd(IUnknown* queue, HWND window,
    const DXGI_SWAP_CHAIN_DESC1* desc, const DXGI_SWAP_CHAIN_FULLSCREEN_DESC* fullscreen_desc,
    IDXGIOutput* restrict_to_output, REFIID riid, void** swap_chain);

// Console bytecode container for source-built programs (runtime rung R3, docs/design/runtime.md section 3).
// The container real titles hand to Create*PipelineState is not publicly documented; it is learned from
// owner logs (the shim logs the first bytes' magic of any bytecode it does not recognise) and parsed by
// the same single function (d3d12_xs::pipeline::parse_container) once known. This container is what our
// own test programs use, and holds what the translation needs and nothing it does not:
//   X2WShaderContainer header, then binding_count X2WShaderBinding records at binding_offset, then the
//   raw gfx1013 code (code_bytes, a multiple of 4, ending in s_endpgm) at code_offset. Little-endian.
// A binding names an entry SGPR and where its value comes from: one 32-bit word of a root parameter of
// the pipeline's root signature (a root CBV/SRV/UAV's title GPU address: word 0 low, 1 high; a root
// constant: its index), the low 32 bits of a descriptor table's address (a descriptor-table root parameter;
// the program completes the pair with a constant high word and loads T#, S# and V# words through it at byte
// offsets: 32 bytes per CBV/SRV/UAV descriptor, 16 per sampler, the increments GetDescriptorHandleIncrementSize
// reports for title heaps), the draw's base vertex or start instance (vertex stage), or the pixel stage's
// interpolation base. Bytecode without the magic is desktop bytecode and is passed to desktop D3D12 unchanged.
#define X2W_SHADER_CONTAINER_MAGIC 0x53573258u  // "X2WS"
#define X2W_SHADER_CONTAINER_VERSION 1u

typedef enum X2WShaderStage { X2W_SHADER_STAGE_VERTEX = 0, X2W_SHADER_STAGE_PIXEL = 1 } X2WShaderStage;
typedef enum X2WShaderBindingKind {
    X2W_SHADER_BINDING_ROOT_WORD = 1,  // root_parameter, word
    X2W_SHADER_BINDING_INTERP = 2,     // pixel stage: the SGPR copied into m0 for v_interp_*
    X2W_SHADER_BINDING_TABLE = 3,      // root_parameter (a descriptor table): low word of the table's address
    X2W_SHADER_BINDING_BASE_VERTEX = 4,    // vertex stage: the draw's base vertex (StartVertexLocation or
                                           // BaseVertexLocation); the hardware vertex id starts at 0
    X2W_SHADER_BINDING_START_INSTANCE = 5  // vertex stage: the draw's start instance; the instance id starts at 0
} X2WShaderBindingKind;

typedef struct X2WShaderContainer {
    uint32_t magic;           // X2W_SHADER_CONTAINER_MAGIC
    uint32_t version;         // X2W_SHADER_CONTAINER_VERSION
    uint32_t stage;           // X2WShaderStage
    uint32_t binding_count;   // at most 32
    uint32_t binding_offset;  // byte offset of the bindings from the start of the container
    uint32_t code_offset;     // byte offset of the code, 4-byte aligned
    uint32_t code_bytes;
    uint32_t reserved;        // 0
} X2WShaderContainer;

typedef struct X2WShaderBinding {
    uint32_t sgpr;            // entry SGPR number, 0..105
    uint32_t kind;            // X2WShaderBindingKind
    uint32_t root_parameter;  // ROOT_WORD, TABLE: root parameter index in the pipeline's root signature
    uint32_t word;            // ROOT_WORD: 32-bit word of that parameter; TABLE: 0
} X2WShaderBinding;

#ifdef __cplusplus
}
#endif
