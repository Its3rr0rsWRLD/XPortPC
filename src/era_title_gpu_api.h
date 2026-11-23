#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef X2W_TITLE_GPU_API
#if defined(_WIN32) || defined(__CYGWIN__)
#ifdef X2W_TITLE_GPU_EXPORTS
#define X2W_TITLE_GPU_API __declspec(dllexport)
#else
#define X2W_TITLE_GPU_API __declspec(dllimport)
#endif
#else
#define X2W_TITLE_GPU_API
#endif
#endif

// Layout of TitleRange in src/title_va_lookup.hlsli (StructuredBuffer stride 24).
typedef struct X2WTitleGpuRange {
    uint32_t begin_low;
    uint32_t begin_high;
    uint32_t end_low;
    uint32_t end_high;
    uint32_t slot;
    uint32_t reserved;
} X2WTitleGpuRange;

#ifdef __cplusplus
static_assert(sizeof(X2WTitleGpuRange) == 24, "X2WTitleGpuRange must be 24 bytes");
#endif

// Attaches device for every tracked allocation and later ones.
// Returns S_OK, E_INVALIDARG, E_NOTIMPL, E_OUTOFMEMORY or D3D12 error.
X2W_TITLE_GPU_API int32_t X2WTitleGpuAttach(void* device);

// Drops every alias and the device reference. Tracked allocations stay tracked.
X2W_TITLE_GPU_API void X2WTitleGpuDetach(void);

// Desktop GPU virtual address for [title_address, title_address + bytes), or 0 if unmapped.
X2W_TITLE_GPU_API uint64_t X2WTitleGpuTranslate(uint64_t title_address, uint64_t bytes);

// Locates the underlying ID3D12Resource and byte offset for [title_address, title_address + bytes).
// Returns S_OK and AddRefs *resource, E_POINTER on null out-pointers, or HRESULT_FROM_WIN32(ERROR_NOT_FOUND).
X2W_TITLE_GPU_API int32_t X2WTitleGpuLocate(uint64_t title_address, uint64_t bytes, void** resource, uint64_t* offset);

// Packs the shader lookup table and AddRefs each returned resource.
// Two-call capacity pattern: sets *required. If capacity < *required, returns ERROR_INSUFFICIENT_BUFFER.
X2W_TITLE_GPU_API int32_t X2WTitleGpuGetShaderView(X2WTitleGpuRange* ranges, void** resources, uint32_t capacity, uint32_t* required);

// Desktop buffers at title addresses (the graphics shim's address model, docs/design/runtime.md section 4). The
// graphics shim picks a title GPU address for each buffer a title creates through it (a range of this process that
// no XMem allocation can occupy) and registers it here, so X2WTitleGpuTranslate/Locate answer for it and, unless
// X2W_TITLE_GPU_REGISTER_NO_SHADER is set, TitleLookup finds it in the shader view. The registry keeps a reference
// on the resource until it is unregistered. Returns S_OK, E_POINTER, or E_INVALIDARG (empty span, no GPU address,
// overlap, out of memory).
#define X2W_TITLE_GPU_REGISTER_NO_SHADER 0x1u
X2W_TITLE_GPU_API int32_t X2WTitleGpuRegisterResource(uint64_t title_address, uint64_t bytes, void* resource, uint32_t flags);
// Returns S_OK or HRESULT_FROM_WIN32(ERROR_NOT_FOUND).
X2W_TITLE_GPU_API int32_t X2WTitleGpuUnregisterResource(uint64_t title_address);

// Every translated range (aliased XMem allocations and registered buffers), sorted by title address, with its
// desktop GPU address. Same two-call capacity pattern as X2WTitleGpuGetShaderView.
typedef struct X2WTitleGpuTranslation {
    uint64_t title_begin;
    uint64_t title_end;  // exclusive
    uint64_t gpu_begin;  // desktop GPU virtual address of title_begin
} X2WTitleGpuTranslation;
X2W_TITLE_GPU_API int32_t X2WTitleGpuGetTranslations(X2WTitleGpuTranslation* ranges, uint32_t capacity, uint32_t* required);

#ifdef __cplusplus
}
#endif
