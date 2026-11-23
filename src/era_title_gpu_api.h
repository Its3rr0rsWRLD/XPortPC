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
    uint32_t base;  // byte offset of begin in the slot's buffer; ranges of one arena or pool share a slot
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

#ifdef __cplusplus
}
#endif
