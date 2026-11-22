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
    X2W_GFX_EVENT_NOTE = 4           // shim decisions worth a line (title GPU attach, passthrough IIDs)
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

#ifdef __cplusplus
}
#endif
