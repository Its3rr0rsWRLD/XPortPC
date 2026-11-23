#pragma once

// Exports of the desktop xmem.dll title memory layer (src/xmem_title.h).
//
// Console-facing names. The Microsoft reference pages for XMem (learn.microsoft.com/gaming/gdk/.../reference/system/
// xmem/...) are restricted to the Xbox developer program, so every signature below comes from public material and is
// cited where it is declared. Where the public material does not settle a detail, the implementation accepts the
// documented shape, checks its inputs defensively and logs anything it cannot serve ("[x2w] xmem ...").
//
// XPortPC-specific names (X2WXMem*) configure the layer and expose what it did, for tests, the launcher and the game
// report.
#include <stdint.h>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef X2W_XMEM_API
#if defined(X2W_TITLE_GPU_EXPORTS)
#define X2W_XMEM_API __declspec(dllexport)
#else
#define X2W_XMEM_API __declspec(dllimport)
#endif
#endif

// --- Console-facing XMem functions ---------------------------------------------------------------------------------
// Signatures: SlimEra era.h (XWine1, MIT), the public reference implementation of the Xbox One ERA kernel's XMem
// surface. The calling convention there is WINAPI, which is the only x64 convention.
typedef PVOID(WINAPI* PXMEMALLOC_ROUTINE)(SIZE_T dwSize, ULONGLONG dwAttributes);
typedef void(WINAPI* PXMEMFREE_ROUTINE)(PVOID lpAddress, ULONGLONG dwAttributes);

// XMemAlloc/XMemFree call the installed routines (XMemAllocDefault/XMemFreeDefault unless replaced).
X2W_XMEM_API PVOID WINAPI XMemAlloc(SIZE_T dwSize, ULONGLONG dwAttributes);
X2W_XMEM_API void WINAPI XMemFree(PVOID lpAddress, ULONGLONG dwAttributes);
X2W_XMEM_API PVOID WINAPI XMemAllocDefault(SIZE_T dwSize, ULONGLONG dwAttributes);
X2W_XMEM_API void WINAPI XMemFreeDefault(PVOID lpAddress, ULONGLONG dwAttributes);
// A null pAllocRoutine restores the defaults (SlimEra). Public search indexes also list a GDK page for an
// XMEM_ALLOCATION_HOOKS structure whose layout is not public; a first argument that is not executable code (such as a
// pointer to such a structure) is refused with a log line and the routines stay as they were.
X2W_XMEM_API void WINAPI XMemSetAllocationHooks(PXMEMALLOC_ROUTINE pAllocRoutine, PXMEMFREE_ROUTINE pFreeRoutine);
// Empty in the ERA kernel (SlimEra); here it validates the layer's own records and logs any inconsistency.
X2W_XMEM_API void WINAPI XMemCheckDefaultHeaps(void);

// Title physical pages. Shapes from Microsoft's public, MIT-licensed Xbox GDK sample
// Samples/Graphics/AdvancedESRAM/PageAllocator.cpp, which calls
//   BOOL  XMemAllocatePhysicalPages(MEM_64K_PAGES, &count, pageArray)   (count in/out, ULONG_PTR page numbers)
//   void* XMemMapPhysicalPages(address, count, pageArray)
//   XMemFreePhysicalPages(count, pageArray)                              (result unused there; BOOL here)
// Page numbers are 64 KiB page indices into the layer's physical pool (as in SlimEra's AllocateTitlePhysicalPages).
// MEM_4MB_PAGES requests whole, 4 MiB-aligned runs of 64 pages. A null address maps at a fresh reservation; a null
// page array unmaps. See docs/experiments.md for what is and is not modelled.
X2W_XMEM_API BOOL WINAPI XMemAllocatePhysicalPages(DWORD flAllocationType, PULONG_PTR NumberOfPages, PULONG_PTR PageArray);
X2W_XMEM_API PVOID WINAPI XMemMapPhysicalPages(PVOID VirtualAddress, ULONG_PTR NumberOfPages, PULONG_PTR PageArray);
X2W_XMEM_API BOOL WINAPI XMemFreePhysicalPages(ULONG_PTR NumberOfPages, PULONG_PTR PageArray);

// Assumed contracts (the reference pages are login-gated; see src/xmem_title.cpp above XMemVirtualAlloc).
X2W_XMEM_API PVOID WINAPI XMemVirtualAlloc(PVOID Address, SIZE_T Size, DWORD AllocationType, DWORD Protect);
X2W_XMEM_API BOOL WINAPI XMemMapPhysicalPagesScatter(PVOID* VirtualAddressArray, ULONG_PTR NumberOfPages, PULONG_PTR PageArray);
X2W_XMEM_API BOOL WINAPI XMemTransferMemory(ULONG_PTR a0, ULONG_PTR a1, ULONG_PTR a2, ULONG_PTR a3);
X2W_XMEM_API BOOL WINAPI XMemIsToolsMemAvailable(void);

// --- XPortPC configuration and introspection ----------------------------------------------------------------------
typedef enum X2WXMemLayout {
    // GPU-visible allocations are carved from a few large committed arenas, each one desktop GPU alias (one title
    // memory slot). Any number of allocations stays within the converter's eight slots.
    X2W_XMEM_LAYOUT_ARENA = 0,
    // Every page-backed allocation is its own VirtualAlloc2 allocation with its own alias (the previous behaviour;
    // XMemFree leaves the range MEM_FREE). More than eight live GPU-visible allocations exceed the converter's slots.
    X2W_XMEM_LAYOUT_STANDALONE = 1,
} X2WXMemLayout;

typedef enum X2WXMemWindowMode {
    X2W_XMEM_WINDOWS_OFF = 0,      // no address requirements
    X2W_XMEM_WINDOWS_PREFER = 1,   // VirtualAlloc2 address requirements; anywhere (logged) when the window is full
    X2W_XMEM_WINDOWS_RESERVE = 2,  // the free parts of each window are reserved as placeholders at configuration
                                   // and allocations are carved from them, so nothing else can take the range
} X2WXMemWindowMode;

typedef enum X2WXMemWindowKind {
    X2W_XMEM_WINDOW_GRAPHICS = 0,  // GPU-visible memory types and arenas
    X2W_XMEM_WINDOW_SYSTEM = 1,    // other page-backed memory and physical-page mappings
    X2W_XMEM_WINDOW_KINDS = 2,
} X2WXMemWindowKind;

typedef struct X2WXMemWindow {
    uint64_t begin;  // inclusive, 64 KiB aligned
    uint64_t end;    // exclusive, 64 KiB aligned; begin == end disables the window
} X2WXMemWindow;

typedef struct X2WXMemConfig {
    uint32_t size;                  // sizeof(X2WXMemConfig)
    uint32_t layout;                // X2WXMemLayout
    uint32_t window_mode;           // X2WXMemWindowMode
    uint32_t large_pages;           // 1: back arenas and 4 MB-page allocations with large pages when the process can
                                    // hold SeLockMemoryPrivilege (falls back, logged)
    uint32_t write_watch;           // 1: allocate GPU-visible memory with MEM_WRITE_WATCH (X2WXMemCollectWrites)
    uint32_t gpu_types;             // bit n set: memory type n is GPU-visible (default 0x3fe: graphics and physical)
    X2WXMemWindow windows[X2W_XMEM_WINDOW_KINDS];
    uint64_t arena_bytes;           // first arena size (later arenas double up to arena_max_bytes)
    uint64_t arena_max_bytes;       // largest arena, and largest allocation an arena serves
    uint32_t arena_max_count;       // arenas before allocations fall back to standalone (logged)
    uint32_t reserved0;
    uint64_t physical_pool_bytes;   // size of the title physical page pool (XMemAllocatePhysicalPages)
} X2WXMemConfig;

// Defaults, overridden by the environment (X2W_XMEM_LAYOUT, X2W_XMEM_WINDOWS, X2W_XMEM_LARGE_PAGES,
// X2W_XMEM_WRITE_WATCH, X2W_XMEM_GPU_TYPES, X2W_XMEM_ARENA_MB, X2W_XMEM_ARENA_MAX_MB, X2W_XMEM_ARENAS,
// X2W_XMEM_PHYSICAL_MB; see docs/experiments.md), are applied by the first XMem call.
// X2WXMemConfigure applies `config` instead; it must come before the first allocation:
// S_OK, E_INVALIDARG (bad size, window or value), or HRESULT_FROM_WIN32(ERROR_INVALID_STATE) once memory exists.
X2W_XMEM_API HRESULT WINAPI X2WXMemConfigure(const X2WXMemConfig* config);
// The configuration in effect (applying the defaults first if no call has yet). E_INVALIDARG for a bad size.
X2W_XMEM_API HRESULT WINAPI X2WXMemGetConfig(X2WXMemConfig* config);

typedef struct X2WXMemStatistics {
    uint32_t size;               // sizeof(X2WXMemStatistics)
    uint32_t reserved0;
    uint64_t live_allocations;   // XMemAllocDefault allocations not yet freed
    uint64_t live_bytes;         // their requested bytes
    uint64_t peak_bytes;
    uint64_t total_allocations;  // successful XMemAllocDefault calls
    uint64_t failed_allocations; // XMemAllocDefault calls that returned null
    uint64_t arenas;             // arenas created (all allocator IDs)
    uint64_t arena_bytes;        // their committed bytes
    uint64_t standalone;         // live standalone page-backed allocations (all allocator IDs)
    uint64_t adopted;            // live hook allocations registered as GPU-visible (all allocator IDs)
    uint64_t large_page_bytes;   // committed bytes backed by large pages
    uint64_t window_misses;      // page-backed allocations placed outside their window
    uint64_t physical_pages_free;
    uint64_t physical_pages_total;
} X2WXMemStatistics;

// allocator_id 0-255 for one allocator ID's counters (the first five fields), or 0xffffffff for all of them.
X2W_XMEM_API HRESULT WINAPI X2WXMemGetStatistics(uint32_t allocator_id, X2WXMemStatistics* statistics);

typedef enum X2WXMemBacking {
    X2W_XMEM_BACKING_NONE = 0,        // not an XMem allocation
    X2W_XMEM_BACKING_HEAP = 1,        // CRT heap (memory type 0)
    X2W_XMEM_BACKING_STANDALONE = 2,  // its own VirtualAlloc2 allocation
    X2W_XMEM_BACKING_ARENA = 3,       // inside an arena
    X2W_XMEM_BACKING_ADOPTED = 4,     // returned by an installed hook and registered as GPU-visible
    X2W_XMEM_BACKING_PHYSICAL = 5,    // a physical-page mapping (XMemMapPhysicalPages)
} X2WXMemBacking;

typedef struct X2WXMemAllocationInfo {
    uint32_t size;          // sizeof(X2WXMemAllocationInfo)
    uint32_t backing;       // X2WXMemBacking
    uint64_t base;          // start of the allocation (or mapped page) holding the address
    uint64_t bytes;         // requested bytes (a mapped page: 65536)
    uint64_t attributes;    // attribute word it was allocated with (0 for a mapping)
    uint64_t region_base;   // the desktop allocation or arena that holds it
    uint64_t region_bytes;
    uint32_t gpu_visible;   // registered for the GPU (TitleLookup and X2WTitleGpuTranslate once a device is attached)
    uint32_t large_pages;   // backed by large pages
    uint32_t write_watch;   // allocated with MEM_WRITE_WATCH
    uint32_t window;        // X2WXMemWindowKind it was placed in, or 0xffffffff for none
    uint64_t physical_page; // a mapping: the 64 KiB physical page number
} X2WXMemAllocationInfo;

// S_OK with `info` describing the allocation holding `address`, or HRESULT_FROM_WIN32(ERROR_NOT_FOUND).
X2W_XMEM_API HRESULT WINAPI X2WXMemDescribe(const void* address, X2WXMemAllocationInfo* info);

// The windows in effect, after configuration (begin == end: disabled).
X2W_XMEM_API HRESULT WINAPI X2WXMemGetWindows(X2WXMemWindow* windows, uint32_t capacity, uint32_t* required);

// Write tracking (X2WXMemConfig::write_watch). Calls `sink` once per run of written 4 KiB pages of write-watched
// memory, in address order, and resets the tracking when `reset` is nonzero. GPU writes are not CPU writes and are
// not reported. Returns S_OK, or E_NOTIMPL when write tracking is off.
typedef void(WINAPI* X2WXMemWriteSink)(uint64_t address, uint64_t bytes, void* context);
X2W_XMEM_API HRESULT WINAPI X2WXMemCollectWrites(X2WXMemWriteSink sink, void* context, BOOL reset);

// Log lines ("xmem <kind> <detail>") go to stderr as "[x2w] ..." unless a sink is set. Returns the previous sink.
typedef void(WINAPI* X2WXMemLogSink)(const char* line, void* context);
X2W_XMEM_API X2WXMemLogSink WINAPI X2WXMemSetLogSink(X2WXMemLogSink sink, void* context);

#ifdef __cplusplus
}
#endif
