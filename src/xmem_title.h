#pragma once

// Desktop title memory layer behind xmem.dll's XMem exports (src/xmem_title_api.h).
//
// Model (docs/experiments.md, "Title memory layer"):
// - Attribute words are read with the ERA XALLOC_ATTRIBUTES layout (src/xmem_attributes.h). Memory type 0 is the CRT
//   heap (src/era_heap.h, unchanged). Every other defined type is page-backed: committed with VirtualAlloc2 on a
//   boundary of max(page size, requested alignment), 4 KB / 64 KB / 4 MB pages as the page-size field says, sized in
//   whole pages and zero-filled.
// - GPU-visible memory types (a configurable mask; by default graphics 1-6 and physical 7-9) are registered with the
//   title GPU registry (src/era_title_gpu.h), so X2WTitleGpuTranslate and TitleLookup in translated shaders reach
//   them once a D3D12 device is attached. In the default arena layout they are carved from a few committed arenas,
//   each one desktop alias, so the number of allocations does not count against the converter's eight title memory
//   slots; each allocation is still its own range, so a freed allocation misses in TitleLookup.
// - Address windows: page-backed memory is placed with VirtualAlloc2 address requirements in a graphics or a system
//   window (by default SlimEra's ERA ranges, [4 GiB, 1 TiB) and [2 TiB, 4 TiB)), or carved from placeholders
//   reserved over the windows' free parts. The windows in use are logged.
// - Large pages back arenas and 4 MB-page allocations when enabled and SeLockMemoryPrivilege can be held (2 MiB
//   desktop large pages; 1 GiB pages for allocations that are whole multiples of 1 GiB); otherwise normal pages,
//   logged once.
// - Optional MEM_WRITE_WATCH on GPU-visible memory, read back with X2WXMemCollectWrites.
// - XMemSetAllocationHooks installs replaceable routines; XMemAllocDefault/XMemFreeDefault stay callable. GPU-visible
//   memory a hook returns from outside the layer's own allocations is registered by its containing VirtualAlloc
//   allocation ("adopted").
// - Title physical pages: a pagefile-backed section is the physical pool; mappings are MapViewOfFile3 views into
//   64 KiB placeholders, so several addresses can show one page. The pool is one GPU alias and every mapped run is a
//   range of it.
// Everything is process-wide and thread-safe.
#include "xmem_title_api.h"

#include <cstddef>

namespace xmem_title {
// Replaces the MEMORY_BASIC_INFORMATION written for `address` when it lies inside an arena: a live allocation reads as
// its own committed private allocation (base, page-rounded size), arena space that no allocation holds reads as
// MEM_FREE. Returns false (info untouched) for any other address.
bool query_overlay(const void* address, MEMORY_BASIC_INFORMATION& info) noexcept;
// One "xmem call NAME<formatted> error=<last error>" line for an export, within the export's call cap (src/xmem_title.cpp,
// g_calls). Keeps the last error.
void log_export_call(const char* name, const char* format, ...) noexcept;
}
