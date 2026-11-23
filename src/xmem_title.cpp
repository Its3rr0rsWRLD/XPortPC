// Desktop title memory layer (src/xmem_title.h).
//
// Parts of the design follow SlimEra's kernelx.cpp (address windows per memory class, placeholder splitting with
// MapViewOfFile3 for physical pages, XMemAlloc routed through replaceable routines keyed by the attribute word).
// No code was copied verbatim; the SlimEra notice is kept because the structure and the ERA constants are derived from
// it:
//
//   MIT License
//
//   Copyright (c) 2025 XWine1
//
//   Permission is hereby granted, free of charge, to any person obtaining a copy
//   of this software and associated documentation files (the "Software"), to deal
//   in the Software without restriction, including without limitation the rights
//   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
//   copies of the Software, and to permit persons to whom the Software is
//   furnished to do so, subject to the following conditions:
//
//   The above copyright notice and this permission notice shall be included in all
//   copies or substantial portions of the Software.
//
//   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
//   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
//   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
//   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
//   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
//   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
//   SOFTWARE.
//
// Desktop memory APIs used (Microsoft Learn, public): VirtualAlloc2 with MEM_ADDRESS_REQUIREMENTS, placeholders
// (MEM_RESERVE_PLACEHOLDER, MEM_REPLACE_PLACEHOLDER, VirtualFree MEM_PRESERVE_PLACEHOLDER / MEM_COALESCE_PLACEHOLDERS),
// MapViewOfFile3 and UnmapViewOfFile2, large pages (GetLargePageMinimum, SeLockMemoryPrivilege,
// MEM_EXTENDED_PARAMETER_NONPAGED_HUGE), and GetWriteWatch / MEM_WRITE_WATCH:
//   https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualalloc2
//   https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-mapviewoffile3
//   https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualfree
//   https://learn.microsoft.com/en-us/windows/win32/memory/large-page-support
//   https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-getwritewatch
#include "xmem_title.h"
#include "common/x2w_redact.h"

#include "era_heap.h"
#include "era_title_gpu.h"
#include "xmem_attributes.h"

#include <algorithm>
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <intrin.h>
#include <limits>
#include <map>
#include <new>
#include <set>
#include <string>
#include <utility>
#include <vector>

#ifndef MEM_RESERVE_PLACEHOLDER
#define MEM_RESERVE_PLACEHOLDER 0x00040000
#endif
#ifndef MEM_REPLACE_PLACEHOLDER
#define MEM_REPLACE_PLACEHOLDER 0x00004000
#endif
#ifndef MEM_PRESERVE_PLACEHOLDER
#define MEM_PRESERVE_PLACEHOLDER 0x00000002
#endif
#ifndef MEM_COALESCE_PLACEHOLDERS
#define MEM_COALESCE_PLACEHOLDERS 0x00000001
#endif
#ifndef MEM_EXTENDED_PARAMETER_NONPAGED_HUGE
#define MEM_EXTENDED_PARAMETER_NONPAGED_HUGE 0x00000010
#endif

namespace {
using namespace xmem_attributes;

constexpr std::uint64_t KiB = 1024, MiB = KiB * 1024, GiB = MiB * 1024;
constexpr std::uint64_t granule = 64 * KiB;  // allocation granularity of x64 Windows; checked at configuration
constexpr std::uint64_t physical_page = 64 * KiB;

// ---- kernelbase entry points (Windows 10 1803+), resolved at run time so older systems fall back ----------------
using VirtualAlloc2Fn = PVOID(WINAPI*)(HANDLE, PVOID, SIZE_T, ULONG, ULONG, MEM_EXTENDED_PARAMETER*, ULONG);
using MapViewOfFile3Fn = PVOID(WINAPI*)(HANDLE, HANDLE, PVOID, ULONG64, SIZE_T, ULONG, ULONG, MEM_EXTENDED_PARAMETER*,
                                        ULONG);
using UnmapViewOfFile2Fn = BOOL(WINAPI*)(HANDLE, PVOID, ULONG);

struct Kernel {
    VirtualAlloc2Fn virtual_alloc2 = nullptr;
    MapViewOfFile3Fn map_view3 = nullptr;
    UnmapViewOfFile2Fn unmap_view2 = nullptr;
};

const Kernel& kernel()
{
    static const Kernel k = [] {
        Kernel r;
        if (HMODULE m = GetModuleHandleW(L"kernelbase.dll")) {
            r.virtual_alloc2 = reinterpret_cast<VirtualAlloc2Fn>(reinterpret_cast<void*>(GetProcAddress(m, "VirtualAlloc2")));
            r.map_view3 = reinterpret_cast<MapViewOfFile3Fn>(reinterpret_cast<void*>(GetProcAddress(m, "MapViewOfFile3")));
            r.unmap_view2 =
                reinterpret_cast<UnmapViewOfFile2Fn>(reinterpret_cast<void*>(GetProcAddress(m, "UnmapViewOfFile2")));
        }
        return r;
    }();
    return k;
}

std::uint64_t align_up(std::uint64_t v, std::uint64_t a) { return (v + a - 1) & ~(a - 1); }
std::uint64_t align_down(std::uint64_t v, std::uint64_t a) { return v & ~(a - 1); }
bool is_pow2(std::uint64_t v) { return v && !(v & (v - 1)); }

// ---- logging --------------------------------------------------------------------------------------------------------
SRWLOCK g_log_lock = SRWLOCK_INIT;
X2WXMemLogSink g_log_sink = nullptr;
void* g_log_context = nullptr;

// Informational lines (configuration, windows, arenas, pools, hooks) reach stderr only with X2W_XMEM_LOG=1, which
// x2w_launch sets for its titles; "unimplemented", "fallback", "slots" and "window" misses always do. A sink set with
// X2WXMemSetLogSink receives every line.
bool informational(const char* kind)
{
    return std::strcmp(kind, "unimplemented") != 0 && std::strcmp(kind, "fallback") != 0 && std::strcmp(kind, "slots") != 0;
}

bool verbose()
{
    static const bool on = [] {
        wchar_t value[8];
        const DWORD n = GetEnvironmentVariableW(L"X2W_XMEM_LOG", value, 8);
        return n > 0 && n < 8 && value[0] != L'0';
    }();
    return on;
}

void log_line(const char* kind, const char* format, ...)
{
    char detail[512];
    va_list args;
    va_start(args, format);
    std::vsnprintf(detail, sizeof(detail), format, args);
    va_end(args);
    char line[600];
    std::snprintf(line, sizeof(line), "xmem %s %s", kind, detail);
    AcquireSRWLockShared(&g_log_lock);
    if (g_log_sink) {
        g_log_sink(line, g_log_context);
    } else if (!informational(kind) || verbose()) {
        std::fprintf(stderr, "[x2w] %s\n", x2w_redact::apply(line).c_str());
        std::fflush(stderr);
    }
    ReleaseSRWLockShared(&g_log_lock);
}

// "unimplemented" and fallback notes are logged once per distinct text (docs/design/runtime.md, section 1, level 3).
SRWLOCK g_once_lock = SRWLOCK_INIT;
std::set<std::string>* g_once = nullptr;

void log_once(const char* kind, const char* format, ...)
{
    char detail[512];
    va_list args;
    va_start(args, format);
    std::vsnprintf(detail, sizeof(detail), format, args);
    va_end(args);
    bool fresh = false;
    AcquireSRWLockExclusive(&g_once_lock);
    try {
        if (!g_once) g_once = new std::set<std::string>;
        fresh = g_once->insert(std::string(kind) + " " + detail).second;
    } catch (const std::bad_alloc&) {
        fresh = true;
    }
    ReleaseSRWLockExclusive(&g_once_lock);
    if (fresh) log_line(kind, "%s", detail);
}

// ---- configuration --------------------------------------------------------------------------------------------------
X2WXMemConfig default_config()
{
    X2WXMemConfig c{};
    c.size = sizeof(c);
    c.layout = X2W_XMEM_LAYOUT_ARENA;
    c.window_mode = X2W_XMEM_WINDOWS_PREFER;
    c.large_pages = 0;
    c.write_watch = 0;
    c.gpu_types = 0x3fe;  // types 1-9
    // SlimEra kernelx.cpp EraVirtualAllocEx: MEM_GRAPHICS reservations in [4 GiB, 1 TiB), other reservations without
    // MEM_TITLE in [2 TiB, 4 TiB). Xbox One ERA values; the Series X|S ranges are not public.
    c.windows[X2W_XMEM_WINDOW_GRAPHICS] = {0x100000000ull, 0x10000000000ull};
    c.windows[X2W_XMEM_WINDOW_SYSTEM] = {0x20000000000ull, 0x40000000000ull};
    c.arena_bytes = 64 * MiB;
    // A raw buffer view holds at most 2^27 32-bit elements (D3D12_REQ_BUFFER_RESOURCE_TEXEL_COUNT_2_TO_EXP), so one
    // title memory slot can show 512 MiB.
    c.arena_max_bytes = 512 * MiB;
    c.arena_max_count = 6;  // of the converter's eight slots: one is the physical pool, one is left for a standalone
    c.physical_pool_bytes = 256 * MiB;
    return c;
}

bool valid(const X2WXMemConfig& c)
{
    if (c.size != sizeof(X2WXMemConfig) || c.layout > X2W_XMEM_LAYOUT_STANDALONE ||
        c.window_mode > X2W_XMEM_WINDOWS_RESERVE || c.large_pages > 1 || c.write_watch > 1 || (c.gpu_types >> 16) ||
        c.arena_max_count > 64)
        return false;
    for (const auto& w : c.windows) {
        if (w.begin > w.end || (w.begin % granule) || (w.end % granule) || w.end > 0x800000000000ull) return false;
    }
    if (!is_pow2(c.arena_bytes) || c.arena_bytes < 4 * MiB || c.arena_max_bytes < c.arena_bytes ||
        !is_pow2(c.arena_max_bytes) || c.arena_max_bytes > 2 * GiB)
        return false;
    if (c.physical_pool_bytes % (4 * MiB) || c.physical_pool_bytes > 4 * GiB) return false;
    return true;
}

bool env(const wchar_t* name, std::string& value)
{
    wchar_t buffer[512];
    const DWORD n = GetEnvironmentVariableW(name, buffer, 512);
    if (n == 0 || n >= 512) return false;
    value.clear();
    for (DWORD i = 0; i < n; ++i) value.push_back(static_cast<char>(buffer[i] < 128 ? buffer[i] : '?'));
    return true;
}

bool parse_u64(const std::string& text, std::uint64_t& out)
{
    if (text.empty()) return false;
    char* end = nullptr;
    const unsigned long long v = std::strtoull(text.c_str(), &end, 0);
    if (!end || *end) return false;
    out = v;
    return true;
}

// X2W_XMEM_WINDOWS: off | prefer | reserve, optionally followed by ":graphics=LO-HI,system=LO-HI" (either part).
bool parse_windows(const std::string& text, X2WXMemConfig& c)
{
    const auto colon = text.find(':');
    const std::string mode = text.substr(0, colon);
    if (mode == "off") c.window_mode = X2W_XMEM_WINDOWS_OFF;
    else if (mode == "prefer") c.window_mode = X2W_XMEM_WINDOWS_PREFER;
    else if (mode == "reserve") c.window_mode = X2W_XMEM_WINDOWS_RESERVE;
    else return false;
    if (colon == std::string::npos) return true;
    std::string rest = text.substr(colon + 1);
    while (!rest.empty()) {
        const auto comma = rest.find(',');
        const std::string item = rest.substr(0, comma);
        rest = comma == std::string::npos ? std::string() : rest.substr(comma + 1);
        const auto eq = item.find('='), dash = item.find('-');
        if (eq == std::string::npos || dash == std::string::npos || dash < eq) return false;
        const std::string name = item.substr(0, eq);
        std::uint64_t lo = 0, hi = 0;
        if (!parse_u64(item.substr(eq + 1, dash - eq - 1), lo) || !parse_u64(item.substr(dash + 1), hi)) return false;
        const int kind = name == "graphics" ? X2W_XMEM_WINDOW_GRAPHICS : name == "system" ? X2W_XMEM_WINDOW_SYSTEM : -1;
        if (kind < 0) return false;
        c.windows[kind] = {lo, hi};
    }
    return true;
}

X2WXMemConfig environment_config()
{
    X2WXMemConfig c = default_config();
    std::string v;
    std::uint64_t n = 0;
    const auto bad = [](const char* name, const std::string& value) {
        log_line("config", "ignored %s=%s (not a valid value)", name, value.c_str());
    };
    if (env(L"X2W_XMEM_LAYOUT", v)) {
        if (v == "arena") c.layout = X2W_XMEM_LAYOUT_ARENA;
        else if (v == "standalone") c.layout = X2W_XMEM_LAYOUT_STANDALONE;
        else bad("X2W_XMEM_LAYOUT", v);
    }
    if (env(L"X2W_XMEM_WINDOWS", v)) {
        X2WXMemConfig t = c;
        if (parse_windows(v, t) && valid(t)) c = t;
        else bad("X2W_XMEM_WINDOWS", v);
    }
    const auto flag = [&](const wchar_t* wname, const char* name, std::uint32_t& field) {
        if (!env(wname, v)) return;
        if (v == "0" || v == "1") field = v == "1";
        else bad(name, v);
    };
    flag(L"X2W_XMEM_LARGE_PAGES", "X2W_XMEM_LARGE_PAGES", c.large_pages);
    flag(L"X2W_XMEM_WRITE_WATCH", "X2W_XMEM_WRITE_WATCH", c.write_watch);
    const auto number = [&](const wchar_t* wname, const char* name, auto apply) {
        if (!env(wname, v)) return;
        X2WXMemConfig t = c;
        if (parse_u64(v, n) && apply(t, n) && valid(t)) c = t;
        else bad(name, v);
    };
    number(L"X2W_XMEM_GPU_TYPES", "X2W_XMEM_GPU_TYPES", [](X2WXMemConfig& t, std::uint64_t x) {
        t.gpu_types = static_cast<std::uint32_t>(x);
        return x <= 0xffff;
    });
    number(L"X2W_XMEM_ARENA_MB", "X2W_XMEM_ARENA_MB", [](X2WXMemConfig& t, std::uint64_t x) {
        t.arena_bytes = x * MiB;
        return x <= 2048;
    });
    number(L"X2W_XMEM_ARENA_MAX_MB", "X2W_XMEM_ARENA_MAX_MB", [](X2WXMemConfig& t, std::uint64_t x) {
        t.arena_max_bytes = x * MiB;
        return x <= 2048;
    });
    number(L"X2W_XMEM_ARENAS", "X2W_XMEM_ARENAS", [](X2WXMemConfig& t, std::uint64_t x) {
        t.arena_max_count = static_cast<std::uint32_t>(x);
        return x <= 64;
    });
    number(L"X2W_XMEM_PHYSICAL_MB", "X2W_XMEM_PHYSICAL_MB", [](X2WXMemConfig& t, std::uint64_t x) {
        t.physical_pool_bytes = x * MiB;
        return x <= 4096;
    });
    return c;
}

// ---- state ----------------------------------------------------------------------------------------------------------
struct Placement {
    std::uintptr_t base = 0;
    std::size_t bytes = 0;
    bool large = false;
    bool write_watch = false;
    std::uint32_t window = 0xffffffff;
    bool placeholder = false;  // carved from a reserved window
};

// A run of a reserved window: one OS placeholder (free) or one allocation that replaced it (used).
struct Piece {
    std::size_t bytes;
    bool free;
};

struct Arena {
    Placement place;
    std::size_t high_water = 0;                  // bytes [high_water, size) have never been handed out (still zero)
    std::map<std::uint64_t, std::uint64_t> free;  // offset -> length
};

struct Record {
    std::size_t bytes;
    std::uint64_t attributes;
    std::uint32_t backing;      // X2WXMemBacking
    std::uintptr_t region;      // arena base, standalone base, or adopted backing base
    std::size_t region_bytes;
    std::size_t extent;         // bytes owned in the region (page-rounded)
    int arena = -1;
    bool gpu = false;
    bool large = false;
    bool write_watch = false;
    std::uint32_t window = 0xffffffff;
    bool placeholder = false;
};

struct Adopted {
    std::uintptr_t backing;
    std::size_t bytes;
};

struct Mapping {
    std::size_t pages;
    std::vector<std::int64_t> physical;  // per 64 KiB page, -1 when nothing is mapped there
    std::vector<std::uintptr_t> ranges;  // registered run bases
};

struct Counters {
    std::uint64_t live_allocations = 0, live_bytes = 0, peak_bytes = 0, total = 0, failed = 0;
    void add(std::size_t bytes)
    {
        ++live_allocations;
        live_bytes += bytes;
        peak_bytes = std::max(peak_bytes, live_bytes);
        ++total;
    }
    void remove(std::size_t bytes)
    {
        --live_allocations;
        live_bytes -= bytes;
    }
};

constexpr std::uint8_t page_free_clean = 0, page_allocated = 1, page_free_dirty = 2;
bool page_is_free(std::uint8_t v) { return v != page_allocated; }

struct Hooks {
    PXMEMALLOC_ROUTINE alloc;
    PXMEMFREE_ROUTINE free;
};

struct State {
    SRWLOCK lock = SRWLOCK_INIT;
    bool configured = false;
    bool memory_exists = false;
    X2WXMemConfig config{};
    bool large_available = false;
    std::size_t large_minimum = 0;
    std::map<std::uintptr_t, Piece> pieces[X2W_XMEM_WINDOW_KINDS];  // RESERVE mode
    std::vector<Arena> arenas;
    std::uint64_t next_arena_bytes = 0;
    std::map<std::uintptr_t, Record> records;
    std::map<std::uintptr_t, Adopted> adopted;              // hook allocation -> backing
    std::map<std::uintptr_t, std::size_t> adopted_backings;  // backing -> live hook allocations in it
    std::map<std::uintptr_t, Mapping> mappings;
    std::vector<Placement> watched;  // write-watched regions (arenas and standalone)
    Counters per_id[256];
    Counters all;
    std::uint64_t standalone = 0, large_page_bytes = 0, window_misses = 0;
    // physical pool
    HANDLE pool = nullptr;
    std::uint8_t* pool_view = nullptr;
    std::vector<std::uint8_t> pool_pages;  // page_free_clean, page_allocated or page_free_dirty
    std::vector<std::uint32_t> pool_mapped;  // per page: number of mapped views
    std::uint64_t pool_free = 0;
};

State& state()
{
    static State* s = new State;  // never destroyed: unloading must not touch D3D12 or OS objects
    return *s;
}

std::atomic<const Hooks*> g_hooks{nullptr};

struct Exclusive {
    SRWLOCK& l;
    explicit Exclusive(SRWLOCK& lock) : l(lock) { AcquireSRWLockExclusive(&l); }
    ~Exclusive() { ReleaseSRWLockExclusive(&l); }
};
struct Shared {
    SRWLOCK& l;
    explicit Shared(SRWLOCK& lock) : l(lock) { AcquireSRWLockShared(&l); }
    ~Shared() { ReleaseSRWLockShared(&l); }
};

bool enable_lock_memory_privilege()
{
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &token)) return false;
    TOKEN_PRIVILEGES privileges{};
    privileges.PrivilegeCount = 1;
    privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
    const bool ok = LookupPrivilegeValueW(nullptr, L"SeLockMemoryPrivilege", &privileges.Privileges[0].Luid) &&
                    AdjustTokenPrivileges(token, FALSE, &privileges, 0, nullptr, nullptr) &&
                    GetLastError() == ERROR_SUCCESS;
    CloseHandle(token);
    return ok;
}

const char* window_name(std::uint32_t w) { return w == X2W_XMEM_WINDOW_GRAPHICS ? "graphics" : "system"; }

// Reserves the free parts of each window as placeholders (RESERVE mode). Caller holds the lock.
void reserve_windows(State& s)
{
    const auto va2 = kernel().virtual_alloc2;
    for (std::uint32_t w = 0; w < X2W_XMEM_WINDOW_KINDS; ++w) {
        const auto& window = s.config.windows[w];
        if (window.begin == window.end) continue;
        std::uint64_t reserved = 0, pieces = 0;
        for (std::uint64_t at = window.begin; at < window.end;) {
            MEMORY_BASIC_INFORMATION info{};
            if (VirtualQuery(reinterpret_cast<void*>(at), &info, sizeof(info)) != sizeof(info)) break;
            const std::uint64_t region_end = std::min<std::uint64_t>(
                reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize, window.end);
            if (info.State == MEM_FREE) {
                const std::uint64_t lo = align_up(at, granule), hi = align_down(region_end, granule);
                if (hi > lo) {
                    void* p = va2(GetCurrentProcess(), reinterpret_cast<void*>(lo), hi - lo,
                                  MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS, nullptr, 0);
                    if (p) {
                        try {
                            s.pieces[w][lo] = {static_cast<std::size_t>(hi - lo), true};
                            reserved += hi - lo;
                            ++pieces;
                        } catch (const std::bad_alloc&) {
                            VirtualFree(p, 0, MEM_RELEASE);
                        }
                    }
                }
            }
            if (region_end <= at) break;
            at = region_end;
        }
        log_line("window", "%s [0x%llx, 0x%llx) reserved %llu bytes in %llu placeholders", window_name(w),
                 static_cast<unsigned long long>(window.begin), static_cast<unsigned long long>(window.end),
                 static_cast<unsigned long long>(reserved), static_cast<unsigned long long>(pieces));
    }
}

// Applies the configuration (environment defaults unless X2WXMemConfigure ran). Caller holds the lock.
void ensure_configured(State& s)
{
    if (s.configured) return;
    s.configured = true;
    if (s.config.size != sizeof(X2WXMemConfig)) s.config = environment_config();
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    if (info.dwAllocationGranularity != granule) {
        log_once("unimplemented", "allocation granularity %lu is not 64 KiB; windows and arenas are off",
                 info.dwAllocationGranularity);
        s.config.window_mode = X2W_XMEM_WINDOWS_OFF;
        s.config.layout = X2W_XMEM_LAYOUT_STANDALONE;
    }
    if (!kernel().virtual_alloc2) {
        log_once("fallback", "VirtualAlloc2 is unavailable; address windows, placeholders and physical pages are off");
        s.config.window_mode = X2W_XMEM_WINDOWS_OFF;
    }
    if (s.config.large_pages) {
        s.large_minimum = GetLargePageMinimum();
        s.large_available = s.large_minimum && enable_lock_memory_privilege();
        if (!s.large_available)
            log_once("fallback", "large pages requested but SeLockMemoryPrivilege is not held; using normal pages");
    }
    s.next_arena_bytes = s.config.arena_bytes;
    const auto& g = s.config.windows[X2W_XMEM_WINDOW_GRAPHICS];
    const auto& y = s.config.windows[X2W_XMEM_WINDOW_SYSTEM];
    static const char* const modes[] = {"off", "prefer", "reserve"};
    log_line("config",
             "layout=%s windows=%s graphics=[0x%llx,0x%llx) system=[0x%llx,0x%llx) large_pages=%s write_watch=%u "
             "gpu_types=0x%x arenas=%llu..%llu MiB x%u physical_pool=%llu MiB",
             s.config.layout == X2W_XMEM_LAYOUT_ARENA ? "arena" : "standalone", modes[s.config.window_mode],
             static_cast<unsigned long long>(g.begin), static_cast<unsigned long long>(g.end),
             static_cast<unsigned long long>(y.begin), static_cast<unsigned long long>(y.end),
             !s.config.large_pages ? "off" : s.large_available ? "on" : "unavailable", s.config.write_watch,
             s.config.gpu_types, static_cast<unsigned long long>(s.config.arena_bytes / MiB),
             static_cast<unsigned long long>(s.config.arena_max_bytes / MiB), s.config.arena_max_count,
             static_cast<unsigned long long>(s.config.physical_pool_bytes / MiB));
    if (s.config.window_mode == X2W_XMEM_WINDOWS_RESERVE) reserve_windows(s);
}

// ---- page placement -------------------------------------------------------------------------------------------------
bool window_enabled(const State& s, std::uint32_t w)
{
    return s.config.window_mode != X2W_XMEM_WINDOWS_OFF && s.config.windows[w].begin < s.config.windows[w].end;
}

// Allocation flags, with a large-page or 1 GiB attribute parameter when asked.
void* commit_at(void* address, std::size_t bytes, ULONG extra, std::uint64_t alignment, const X2WXMemWindow* window,
                bool large, bool huge, bool write_watch)
{
    const auto va2 = kernel().virtual_alloc2;
    ULONG type = MEM_RESERVE | MEM_COMMIT | extra | (large ? MEM_LARGE_PAGES : 0) | (write_watch ? MEM_WRITE_WATCH : 0);
    if (!va2) {
        if (address || alignment > granule) return nullptr;
        return VirtualAlloc(nullptr, bytes, type, PAGE_READWRITE);
    }
    MEM_ADDRESS_REQUIREMENTS requirements{};
    MEM_EXTENDED_PARAMETER parameters[2]{};
    ULONG count = 0;
    if (!address && (window || alignment > granule)) {
        if (window) {
            requirements.LowestStartingAddress = reinterpret_cast<PVOID>(window->begin);
            requirements.HighestEndingAddress = reinterpret_cast<PVOID>(window->end - 1);
        }
        requirements.Alignment = alignment > granule ? alignment : 0;
        parameters[count].Type = MemExtendedParameterAddressRequirements;
        parameters[count].Pointer = &requirements;
        ++count;
    }
    if (huge) {
        parameters[count].Type = MemExtendedParameterAttributeFlags;
        parameters[count].ULong64 = MEM_EXTENDED_PARAMETER_NONPAGED_HUGE;
        ++count;
    }
    return va2(GetCurrentProcess(), address, bytes, type, PAGE_READWRITE, count ? parameters : nullptr, count);
}

// Splits a free placeholder piece so that [start, start + bytes) is one placeholder, marks it used and returns start,
// or 0. Caller holds the lock.
std::uintptr_t take_placeholder(State& s, std::uint32_t w, std::size_t bytes, std::uint64_t alignment)
{
    auto& pieces = s.pieces[w];
    for (auto it = pieces.begin(); it != pieces.end(); ++it) {
        if (!it->second.free) continue;
        const std::uint64_t begin = it->first, end = begin + it->second.bytes;
        const std::uint64_t start = align_up(begin, std::max(alignment, granule));
        if (start < begin || start + bytes > end || start + bytes < start) continue;
        // Split off the head and the tail so [start, start + bytes) is one placeholder.
        if (start > begin) {
            if (!VirtualFree(reinterpret_cast<void*>(begin), start - begin, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER)) {
                log_once("fallback", "placeholder split failed (error %lu)", GetLastError());
                return 0;
            }
            it->second.bytes = static_cast<std::size_t>(start - begin);
            it = pieces.emplace(start, Piece{static_cast<std::size_t>(end - start), true}).first;
        }
        if (start + bytes < end) {
            if (!VirtualFree(reinterpret_cast<void*>(start), bytes, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER)) {
                log_once("fallback", "placeholder split failed (error %lu)", GetLastError());
                return 0;
            }
            it->second.bytes = bytes;
            pieces.emplace(start + bytes, Piece{static_cast<std::size_t>(end - start - bytes), true});
        }
        it->second.free = false;
        return static_cast<std::uintptr_t>(start);
    }
    return 0;
}

// Carves [start, start + bytes) out of a free placeholder piece and commits it. Caller holds the lock.
void* carve(State& s, std::uint32_t w, std::size_t bytes, std::uint64_t alignment, bool large, bool write_watch)
{
    const std::uintptr_t start = take_placeholder(s, w, bytes, alignment);
    if (!start) return nullptr;
    void* p = commit_at(reinterpret_cast<void*>(start), bytes, MEM_REPLACE_PLACEHOLDER, 0, nullptr, large, false,
                        write_watch);
    if (!p) s.pieces[w][start].free = true;  // still a placeholder (split, which is harmless)
    return p;
}

void coalesce(std::map<std::uintptr_t, Piece>& pieces, std::map<std::uintptr_t, Piece>::iterator it)
{
    // Merge with the free neighbours the OS agrees to coalesce (placeholders of one original reservation).
    auto next = std::next(it);
    if (next != pieces.end() && next->second.free && it->first + it->second.bytes == next->first &&
        VirtualFree(reinterpret_cast<void*>(it->first), it->second.bytes + next->second.bytes,
                    MEM_RELEASE | MEM_COALESCE_PLACEHOLDERS)) {
        it->second.bytes += next->second.bytes;
        pieces.erase(next);
    }
    if (it != pieces.begin()) {
        auto prev = std::prev(it);
        if (prev->second.free && prev->first + prev->second.bytes == it->first &&
            VirtualFree(reinterpret_cast<void*>(prev->first), prev->second.bytes + it->second.bytes,
                        MEM_RELEASE | MEM_COALESCE_PLACEHOLDERS)) {
            prev->second.bytes += it->second.bytes;
            pieces.erase(it);
        }
    }
}

// Commits `bytes` (already rounded to whole pages) at `alignment`, trying in order: large (1 GiB, then 2 MiB) pages
// when asked, then normal pages; in the window, then anywhere. Caller holds the lock.
bool place(State& s, std::uint32_t w, std::size_t bytes, std::uint64_t alignment, bool want_large, bool want_watch,
           Placement& out)
{
    bool large = want_large && s.large_available && !want_watch;
    if (want_large && want_watch) log_once("fallback", "write watch and large pages exclude each other; normal pages");
    for (int attempt = 0; attempt < 2; ++attempt) {
        const bool use_large = large && attempt == 0;
        if (!use_large && attempt == 1 && !large) break;
        std::size_t want = use_large ? static_cast<std::size_t>(align_up(bytes, s.large_minimum)) : bytes;
        const std::uint64_t align = use_large ? std::max<std::uint64_t>(alignment, s.large_minimum) : alignment;
        const bool huge = use_large && want >= GiB && want % GiB == 0;
        void* p = nullptr;
        bool placeholder = false;
        std::uint32_t window = 0xffffffff;
        bool watch = want_watch;
        for (int watch_try = 0; watch_try < 2 && !p; ++watch_try) {
            if (watch_try == 1) {
                if (!watch) break;
                watch = false;
                log_once("fallback", "MEM_WRITE_WATCH was refused (error %lu); allocating without write tracking",
                         GetLastError());
            }
            if (window_enabled(s, w)) {
                if (s.config.window_mode == X2W_XMEM_WINDOWS_RESERVE) {
                    p = carve(s, w, want, align, use_large, watch);
                    placeholder = p != nullptr;
                }
                if (!p && huge)
                    p = commit_at(nullptr, want, 0, std::max<std::uint64_t>(align, GiB), &s.config.windows[w], true,
                                  true, false);
                if (!p) p = commit_at(nullptr, want, 0, align, &s.config.windows[w], use_large, false, watch);
                if (p) window = w;
            }
            if (!p && huge) p = commit_at(nullptr, want, 0, std::max<std::uint64_t>(align, GiB), nullptr, true, true, false);
            if (!p) {
                p = commit_at(nullptr, want, 0, align, nullptr, use_large, false, watch);
                if (p && window_enabled(s, w)) {
                    ++s.window_misses;
                    log_once("fallback", "%s window full; placed outside it", window_name(w));
                }
            }
        }
        if (p) {
            out.base = reinterpret_cast<std::uintptr_t>(p);
            out.bytes = want;
            out.large = use_large;
            out.write_watch = watch;
            out.window = window;
            out.placeholder = placeholder;
            if (use_large) s.large_page_bytes += want;
            return true;
        }
        if (use_large) log_once("fallback", "large-page allocation refused (error %lu); using normal pages", GetLastError());
    }
    return false;
}

void unplace(State& s, const Placement& p)
{
    if (p.large) s.large_page_bytes -= p.bytes;
    if (p.placeholder) {
        auto& pieces = s.pieces[p.window];
        auto it = pieces.find(p.base);
        // The size is required (measured: size 0 fails with ERROR_INVALID_PARAMETER, tests/xmem_alias_probe.cpp).
        bool back = VirtualFree(reinterpret_cast<void*>(p.base), p.bytes, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
        if (back && it != pieces.end()) {
            it->second.free = true;
            coalesce(pieces, it);
            return;
        }
        log_once("fallback", "returning an allocation to its placeholder failed (error %lu); released", GetLastError());
        if (it != pieces.end()) pieces.erase(it);
    }
    VirtualFree(reinterpret_cast<void*>(p.base), 0, MEM_RELEASE);
}

void forget_watched(State& s, std::uintptr_t base)
{
    s.watched.erase(std::remove_if(s.watched.begin(), s.watched.end(),
                                   [&](const Placement& p) { return p.base == base; }),
                    s.watched.end());
}

// ---- arenas ---------------------------------------------------------------------------------------------------------
// First fit in one arena. Returns the offset, or UINT64_MAX.
std::uint64_t arena_take(Arena& a, std::uint64_t bytes, std::uint64_t alignment)
{
    for (auto it = a.free.begin(); it != a.free.end(); ++it) {
        const std::uint64_t begin = it->first, end = begin + it->second;
        const std::uint64_t start = align_up(a.place.base + begin, alignment) - a.place.base;
        if (start + bytes > end) continue;
        a.free.erase(it);
        if (start > begin) a.free.emplace(begin, start - begin);
        if (start + bytes < end) a.free.emplace(start + bytes, end - start - bytes);
        return start;
    }
    return std::numeric_limits<std::uint64_t>::max();
}

void arena_give(Arena& a, std::uint64_t offset, std::uint64_t bytes)
{
    auto it = a.free.emplace(offset, bytes).first;
    auto next = std::next(it);
    if (next != a.free.end() && it->first + it->second == next->first) {
        it->second += next->second;
        a.free.erase(next);
    }
    if (it != a.free.begin()) {
        auto prev = std::prev(it);
        if (prev->first + prev->second == it->first) {
            prev->second += it->second;
            a.free.erase(it);
        }
    }
}

// A new arena that can hold `bytes` at `alignment`, or -1. Caller holds the lock.
int arena_create(State& s, std::uint64_t bytes, std::uint64_t alignment)
{
    if (s.arenas.size() >= s.config.arena_max_count) return -1;
    std::uint64_t size = s.next_arena_bytes;
    while (size < bytes + alignment && size < s.config.arena_max_bytes) size *= 2;
    if (size < bytes) return -1;
    Arena a;
    if (!place(s, X2W_XMEM_WINDOW_GRAPHICS, static_cast<std::size_t>(size), 4 * MiB, s.config.large_pages != 0,
               s.config.write_watch != 0, a.place))
        return -1;
    try {
        a.free.emplace(0, a.place.bytes);
        s.arenas.push_back(a);
    } catch (const std::bad_alloc&) {
        unplace(s, a.place);
        return -1;
    }
    if (!era_title_gpu::add_backing(reinterpret_cast<void*>(a.place.base), a.place.bytes)) {
        log_once("unimplemented", "arena 0x%llx could not be registered for the GPU",
                 static_cast<unsigned long long>(a.place.base));
    }
    if (a.place.write_watch) s.watched.push_back(a.place);
    s.next_arena_bytes = std::min<std::uint64_t>(size * 2, s.config.arena_max_bytes);
    log_line("arena", "%zu at 0x%llx bytes=%zu window=%s large_pages=%d write_watch=%d", s.arenas.size() - 1,
             static_cast<unsigned long long>(a.place.base), a.place.bytes,
             a.place.window == 0xffffffff ? "none" : window_name(a.place.window), a.place.large, a.place.write_watch);
    return static_cast<int>(s.arenas.size() - 1);
}

bool gpu_visible(const State& s, std::uint32_t memory_type) { return (s.config.gpu_types >> memory_type) & 1; }

// ---- default routines -----------------------------------------------------------------------------------------------
void* allocate_default(SIZE_T bytes, ULONGLONG attributes) noexcept
{
    const Fields f = decode(attributes);
    State& s = state();
    std::uint8_t* zero_from = nullptr;
    std::size_t zero_bytes = 0;
    void* result = nullptr;
    {
        Exclusive guard(s.lock);
        ensure_configured(s);
        s.memory_exists = true;
        auto& counters = s.per_id[f.allocator_id];
        const auto fail = [&]() -> void* {
            ++counters.failed;
            ++s.all.failed;
            return nullptr;
        };
        if (bytes == 0) return fail();
        if (f.reserved) {
            log_once("unimplemented", "XMemAlloc attributes 0x%llx set reserved bits; refused",
                     static_cast<unsigned long long>(attributes));
            return fail();
        }
        if (f.page_size == page_undefined) {
            log_once("unimplemented", "XMemAlloc page size value 3 (attributes 0x%llx) is undefined; refused",
                     static_cast<unsigned long long>(attributes));
            return fail();
        }
        if (f.memory_type >= memory_type_count) {
            log_once("unimplemented", "XMemAlloc memory type %u (attributes 0x%llx) is undefined; refused",
                     f.memory_type, static_cast<unsigned long long>(attributes));
            return fail();
        }
        if (bytes > (std::uint64_t{1} << 46)) return fail();
        const bool gpu = gpu_visible(s, f.memory_type);
        try {
            if (f.memory_type == heap && !gpu) {
                // The CRT heap, as before (src/era_heap.h).
                void* p = era_heap::allocate(bytes, attributes);
                if (!p) return fail();
                Record r{};
                r.bytes = bytes;
                r.attributes = attributes;
                r.backing = X2W_XMEM_BACKING_HEAP;
                r.region = reinterpret_cast<std::uintptr_t>(p);
                r.region_bytes = r.extent = bytes;
                if (!s.records.emplace(reinterpret_cast<std::uintptr_t>(p), r).second) {
                    era_heap::release(p);
                    return fail();
                }
                counters.add(bytes);
                s.all.add(bytes);
                return p;
            }
            const std::uint64_t page = page_bytes(f.page_size);
            const std::uint64_t alignment = std::max<std::uint64_t>(std::uint64_t{1} << f.alignment, page);
            const std::uint64_t extent = align_up(bytes, page);
            Record r{};
            r.bytes = bytes;
            r.attributes = attributes;
            r.extent = static_cast<std::size_t>(extent);
            r.gpu = gpu;
            std::uintptr_t address = 0;
            if (gpu && s.config.layout == X2W_XMEM_LAYOUT_ARENA && extent <= s.config.arena_max_bytes &&
                alignment <= 4 * MiB) {
                std::uint64_t offset = std::numeric_limits<std::uint64_t>::max();
                int index = -1;
                for (std::size_t i = 0; i < s.arenas.size() && index < 0; ++i) {
                    offset = arena_take(s.arenas[i], extent, alignment);
                    if (offset != std::numeric_limits<std::uint64_t>::max()) index = static_cast<int>(i);
                }
                if (index < 0) {
                    index = arena_create(s, extent, alignment);
                    if (index >= 0) offset = arena_take(s.arenas[index], extent, alignment);
                    if (index < 0 || offset == std::numeric_limits<std::uint64_t>::max()) {
                        if (s.arenas.size() >= s.config.arena_max_count)
                            log_once("slots", "all %u arenas are full; GPU-visible allocations now use standalone "
                                              "allocations, each its own title memory slot", s.config.arena_max_count);
                        index = -1;
                    }
                }
                if (index >= 0) {
                    Arena& a = s.arenas[index];
                    address = a.place.base + offset;
                    r.backing = X2W_XMEM_BACKING_ARENA;
                    r.region = a.place.base;
                    r.region_bytes = a.place.bytes;
                    r.arena = index;
                    r.large = a.place.large;
                    r.write_watch = a.place.write_watch;
                    r.window = a.place.window;
                    // Bytes below the high-water mark were handed out before and are zeroed outside the lock.
                    if (offset < a.high_water) {
                        zero_from = reinterpret_cast<std::uint8_t*>(address);
                        zero_bytes = static_cast<std::size_t>(std::min<std::uint64_t>(a.high_water, offset + extent) - offset);
                    }
                    a.high_water = static_cast<std::size_t>(std::max<std::uint64_t>(a.high_water, offset + extent));
                    if (!era_title_gpu::add_range(reinterpret_cast<void*>(address), bytes, a.place.base, offset,
                                                  static_cast<std::size_t>(extent))) {
                        log_once("unimplemented", "arena allocation 0x%llx could not be registered for the GPU",
                                 static_cast<unsigned long long>(address));
                    }
                }
            }
            if (!address) {
                Placement p;
                const std::uint32_t window = gpu ? X2W_XMEM_WINDOW_GRAPHICS : X2W_XMEM_WINDOW_SYSTEM;
                if (!place(s, window, static_cast<std::size_t>(extent), alignment, f.page_size == page_4mb,
                           gpu && s.config.write_watch, p))
                    return fail();
                address = p.base;
                r.backing = X2W_XMEM_BACKING_STANDALONE;
                r.region = p.base;
                r.region_bytes = p.bytes;
                r.large = p.large;
                r.write_watch = p.write_watch;
                r.window = p.window;
                r.placeholder = p.placeholder;
                if (gpu && !era_title_gpu::track(reinterpret_cast<void*>(address), bytes)) {
                    unplace(s, p);
                    return fail();
                }
                if (p.write_watch) s.watched.push_back(p);
                ++s.standalone;
            }
            s.records.emplace(address, r);
            counters.add(bytes);
            s.all.add(bytes);
            result = reinterpret_cast<void*>(address);
        } catch (const std::bad_alloc&) {
            return fail();
        }
    }
    if (zero_bytes) std::memset(zero_from, 0, zero_bytes);
    return result;
}

void free_default(PVOID address, ULONGLONG attributes) noexcept
{
    if (!address) return;
    State& s = state();
    Exclusive guard(s.lock);
    auto it = s.records.find(reinterpret_cast<std::uintptr_t>(address));
    if (it == s.records.end()) {
        log_once("unimplemented", "XMemFree of 0x%llx, which XMemAllocDefault did not return; passed to the ERA heap",
                 static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(address)));
        era_heap::release_with_attributes(address, attributes);
        return;
    }
    Record r = it->second;
    if (r.attributes != attributes) {
        log_once("note", "XMemFree attributes 0x%llx differ from the allocation's 0x%llx; using the allocation's",
                 static_cast<unsigned long long>(attributes), static_cast<unsigned long long>(r.attributes));
    }
    s.records.erase(it);
    const Fields f = decode(r.attributes);
    s.per_id[f.allocator_id].remove(r.bytes);
    s.all.remove(r.bytes);
    switch (r.backing) {
    case X2W_XMEM_BACKING_HEAP:
        era_heap::release(address);
        break;
    case X2W_XMEM_BACKING_ARENA:
        era_title_gpu::remove_range(address);
        arena_give(s.arenas[r.arena], reinterpret_cast<std::uintptr_t>(address) - r.region, r.extent);
        break;
    case X2W_XMEM_BACKING_STANDALONE: {
        if (r.gpu) era_title_gpu::untrack(address);
        if (r.write_watch) forget_watched(s, r.region);
        Placement p;
        p.base = r.region;
        p.bytes = r.region_bytes;
        p.large = r.large;
        p.window = r.window;
        p.placeholder = r.placeholder;
        unplace(s, p);
        --s.standalone;
        break;
    }
    default:
        break;
    }
}

// The record whose owned bytes hold `address`, or records.end(). Caller holds the lock.
std::map<std::uintptr_t, Record>::const_iterator owner(const State& s, std::uintptr_t address)
{
    auto next = s.records.upper_bound(address);
    if (next == s.records.begin()) return s.records.end();
    auto it = std::prev(next);
    return address - it->first < std::max(it->second.extent, it->second.bytes) ? it : s.records.end();
}

// Registers GPU-visible memory an installed hook returned. Caller holds the lock.
void adopt(State& s, void* p, std::size_t bytes, ULONGLONG attributes)
{
    const auto address = reinterpret_cast<std::uintptr_t>(p);
    if (owner(s, address) != s.records.end()) return;  // carved from the layer's own memory: already reachable
    MEMORY_BASIC_INFORMATION info{};
    if (VirtualQuery(p, &info, sizeof(info)) != sizeof(info) || info.State != MEM_COMMIT) {
        log_once("unimplemented", "hook allocation 0x%llx is not committed memory; not GPU-visible",
                 static_cast<unsigned long long>(address));
        return;
    }
    const auto base = reinterpret_cast<std::uintptr_t>(info.AllocationBase);
    // D3D12 aliases only allocations committed throughout (src/era_gpu_alias.h), so the whole containing
    // allocation must be committed.
    std::uintptr_t end = base;
    bool whole = true;
    for (;;) {
        MEMORY_BASIC_INFORMATION r{};
        if (VirtualQuery(reinterpret_cast<void*>(end), &r, sizeof(r)) != sizeof(r) ||
            reinterpret_cast<std::uintptr_t>(r.AllocationBase) != base)
            break;
        whole = whole && r.State == MEM_COMMIT;
        end = reinterpret_cast<std::uintptr_t>(r.BaseAddress) + r.RegionSize;
    }
    if (!whole || address + bytes > end || address < base || info.Type != MEM_PRIVATE) {
        log_once("unimplemented", "hook allocation 0x%llx is not inside a private allocation committed throughout; "
                                  "not GPU-visible", static_cast<unsigned long long>(address));
        return;
    }
    try {
        auto counted = s.adopted_backings.find(base);
        if (counted == s.adopted_backings.end()) {
            if (!era_title_gpu::add_backing(info.AllocationBase, end - base)) {
                log_once("unimplemented", "hook allocation 0x%llx overlaps registered memory; not GPU-visible",
                         static_cast<unsigned long long>(address));
                return;
            }
            counted = s.adopted_backings.emplace(base, 0).first;
        }
        if (!era_title_gpu::add_range(p, bytes, base, address - base)) {
            if (counted->second == 0) {
                era_title_gpu::remove_backing(base);
                s.adopted_backings.erase(counted);
            }
            log_once("unimplemented", "hook allocation 0x%llx overlaps registered memory; not GPU-visible",
                     static_cast<unsigned long long>(address));
            return;
        }
        ++counted->second;
        s.adopted.emplace(address, Adopted{base, bytes});
        (void)attributes;
    } catch (const std::bad_alloc&) {
    }
}

void unadopt(State& s, void* p)
{
    auto it = s.adopted.find(reinterpret_cast<std::uintptr_t>(p));
    if (it == s.adopted.end()) return;
    era_title_gpu::remove_range(p);
    auto counted = s.adopted_backings.find(it->second.backing);
    if (counted != s.adopted_backings.end() && --counted->second == 0) {
        era_title_gpu::remove_backing(counted->first);
        s.adopted_backings.erase(counted);
    }
    s.adopted.erase(it);
}

bool executable(const void* p)
{
    MEMORY_BASIC_INFORMATION info{};
    return p && VirtualQuery(p, &info, sizeof(info)) == sizeof(info) && info.State == MEM_COMMIT &&
           (info.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY));
}

// ---- physical pages -------------------------------------------------------------------------------------------------
std::uintptr_t pool_key() { return reinterpret_cast<std::uintptr_t>(&state().pool); }

bool ensure_pool(State& s)
{
    if (s.pool) return true;
    const std::uint64_t bytes = s.config.physical_pool_bytes;
    if (!bytes || !kernel().map_view3 || !kernel().unmap_view2) {
        log_once("unimplemented", "title physical pages need MapViewOfFile3 and a nonzero pool");
        return false;
    }
    HANDLE section = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE | SEC_COMMIT,
                                        static_cast<DWORD>(bytes >> 32), static_cast<DWORD>(bytes), nullptr);
    if (!section) {
        log_once("unimplemented", "the physical page pool section could not be created (error %lu)", GetLastError());
        return false;
    }
    auto* view = static_cast<std::uint8_t*>(MapViewOfFile(section, FILE_MAP_ALL_ACCESS, 0, 0, 0));
    if (!view) {
        CloseHandle(section);
        return false;
    }
    try {
        s.pool_pages.assign(static_cast<std::size_t>(bytes / physical_page), 0);
        s.pool_mapped.assign(static_cast<std::size_t>(bytes / physical_page), 0);
    } catch (const std::bad_alloc&) {
        UnmapViewOfFile(view);
        CloseHandle(section);
        return false;
    }
    s.pool = section;
    s.pool_view = view;
    s.pool_free = bytes / physical_page;
    if (!era_title_gpu::add_section_backing(pool_key(), section, static_cast<std::size_t>(bytes)))
        log_once("unimplemented", "the physical page pool could not be registered for the GPU");
    log_line("physical", "pool of %llu pages (%llu MiB)", static_cast<unsigned long long>(s.pool_free),
             static_cast<unsigned long long>(bytes / MiB));
    return true;
}

// Re-registers the mapped runs of a mapping as ranges of the pool. Caller holds the lock.
void register_runs(State&, std::uintptr_t base, Mapping& m)
{
    for (std::uintptr_t r : m.ranges) era_title_gpu::remove_range(reinterpret_cast<void*>(r));
    m.ranges.clear();
    for (std::size_t i = 0; i < m.pages;) {
        if (m.physical[i] < 0) {
            ++i;
            continue;
        }
        std::size_t j = i + 1;
        while (j < m.pages && m.physical[j] == m.physical[j - 1] + 1) ++j;
        const std::uintptr_t run = base + i * physical_page;
        if (era_title_gpu::add_range(reinterpret_cast<void*>(run), (j - i) * physical_page, pool_key(),
                                     static_cast<std::uint64_t>(m.physical[i]) * physical_page)) {
            m.ranges.push_back(run);
        } else {
            log_once("unimplemented", "physical mapping run 0x%llx could not be registered for the GPU",
                     static_cast<unsigned long long>(run));
        }
        i = j;
    }
}

// Splits the placeholder region [base, base + total pages) into one placeholder per 64 KiB page, so each page can hold
// its own view, and records it as a mapping with nothing mapped. Caller holds the lock.
std::map<std::uintptr_t, Mapping>::iterator track_placeholders(State& s, std::uintptr_t base, std::size_t total)
{
    for (std::size_t i = 1; i < total; ++i)
        VirtualFree(reinterpret_cast<void*>(base + (total - i) * physical_page), physical_page,
                    MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
    try {
        Mapping m;
        m.pages = total;
        m.physical.assign(total, -1);
        return s.mappings.emplace(base, std::move(m)).first;
    } catch (const std::bad_alloc&) {
        return s.mappings.end();
    }
}

// A placeholder region for a mapping at `address` (null: anywhere in the system window). Caller holds the lock.
std::map<std::uintptr_t, Mapping>::iterator mapping_for(State& s, std::uintptr_t address, std::size_t pages)
{
    const std::uint64_t bytes = pages * physical_page;
    if (address) {
        auto next = s.mappings.upper_bound(address);
        if (next != s.mappings.begin()) {
            auto it = std::prev(next);
            if (address >= it->first && address + bytes <= it->first + it->second.pages * physical_page) return it;
        }
    }
    const auto va2 = kernel().virtual_alloc2;
    std::uintptr_t base = address;
    std::size_t total = pages;
    void* p = nullptr;
    if (address) {
        MEMORY_BASIC_INFORMATION info{};
        if (VirtualQuery(reinterpret_cast<void*>(address), &info, sizeof(info)) != sizeof(info)) return s.mappings.end();
        if (info.State == MEM_RESERVE && info.Type == MEM_PRIVATE &&
            reinterpret_cast<std::uintptr_t>(info.AllocationBase) == address) {
            // A plain reservation the title made for the mapping (the console reserves with VirtualAlloc). It becomes
            // a placeholder region of the same size, if nothing in it is committed.
            std::uintptr_t end = address;
            for (;;) {
                MEMORY_BASIC_INFORMATION r{};
                if (VirtualQuery(reinterpret_cast<void*>(end), &r, sizeof(r)) != sizeof(r) ||
                    reinterpret_cast<std::uintptr_t>(r.AllocationBase) != address)
                    break;
                if (r.State != MEM_RESERVE) return s.mappings.end();
                end = reinterpret_cast<std::uintptr_t>(r.BaseAddress) + r.RegionSize;
            }
            if (end - address < bytes) return s.mappings.end();
            total = static_cast<std::size_t>((end - address) / physical_page);
            if (!VirtualFree(reinterpret_cast<void*>(address), 0, MEM_RELEASE)) return s.mappings.end();
            log_line("physical", "reservation 0x%llx (%zu pages) adopted for mappings",
                     static_cast<unsigned long long>(address), total);
        } else if (info.State != MEM_FREE) {
            return s.mappings.end();
        }
        p = va2(GetCurrentProcess(), reinterpret_cast<void*>(address), total * physical_page,
                MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS, nullptr, 0);
    } else {
        MEM_ADDRESS_REQUIREMENTS requirements{};
        MEM_EXTENDED_PARAMETER parameter{};
        const auto& w = s.config.windows[X2W_XMEM_WINDOW_SYSTEM];
        if (window_enabled(s, X2W_XMEM_WINDOW_SYSTEM) && s.config.window_mode == X2W_XMEM_WINDOWS_RESERVE) {
            // Already a placeholder of the reserved window; it stays in use for the mapping's lifetime.
            p = reinterpret_cast<void*>(take_placeholder(s, X2W_XMEM_WINDOW_SYSTEM, static_cast<std::size_t>(bytes),
                                                         physical_page));
        }
        if (!p && window_enabled(s, X2W_XMEM_WINDOW_SYSTEM)) {
            requirements.LowestStartingAddress = reinterpret_cast<PVOID>(w.begin);
            requirements.HighestEndingAddress = reinterpret_cast<PVOID>(w.end - 1);
            parameter.Type = MemExtendedParameterAddressRequirements;
            parameter.Pointer = &requirements;
            p = va2(GetCurrentProcess(), nullptr, bytes, MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS,
                    &parameter, 1);
        }
        if (!p) p = va2(GetCurrentProcess(), nullptr, bytes, MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS, nullptr, 0);
        base = reinterpret_cast<std::uintptr_t>(p);
    }
    if (!p) return s.mappings.end();
    return track_placeholders(s, base, total);
}

// XMemVirtualAlloc(MEM_RESERVE | MEM_PHYSICAL [| MEM_LARGE_PAGES | MEM_4MB_PAGES]): a range reserved for later
// XMemMapPhysicalPages / XMemMapPhysicalPagesScatter calls (as AWE reserves with MEM_PHYSICAL). It is made a mapping
// region at once (64 KiB placeholders, nothing mapped), so a map call at any page inside it finds it. A non-null
// address is honoured exactly (it must be 64 KiB aligned and free); a null one is placed on `alignment` (2 MiB with
// large pages, 4 MiB with MEM_4MB_PAGES, else 64 KiB), in the system window when one is in use. Returns 0 with the
// last error set on failure. Caller holds the lock.
std::uintptr_t reserve_physical_range(State& s, std::uintptr_t address, std::size_t pages, std::uint64_t alignment)
{
    const auto va2 = kernel().virtual_alloc2;
    if (!va2) {
        SetLastError(ERROR_NOT_SUPPORTED);
        return 0;
    }
    const std::uint64_t bytes = pages * physical_page;
    void* p = nullptr;
    if (address) {
        p = va2(GetCurrentProcess(), reinterpret_cast<void*>(address), bytes, MEM_RESERVE | MEM_RESERVE_PLACEHOLDER,
                PAGE_NOACCESS, nullptr, 0);
        if (!p) return 0;
    } else {
        const auto& w = s.config.windows[X2W_XMEM_WINDOW_SYSTEM];
        const bool in_window = window_enabled(s, X2W_XMEM_WINDOW_SYSTEM);
        if (in_window && s.config.window_mode == X2W_XMEM_WINDOWS_RESERVE)
            p = reinterpret_cast<void*>(take_placeholder(s, X2W_XMEM_WINDOW_SYSTEM, static_cast<std::size_t>(bytes),
                                                         alignment));
        for (int attempt = in_window ? 0 : 1; !p && attempt < 2; ++attempt) {
            MEM_ADDRESS_REQUIREMENTS requirements{};
            MEM_EXTENDED_PARAMETER parameter{};
            if (attempt == 0) {
                requirements.LowestStartingAddress = reinterpret_cast<PVOID>(w.begin);
                requirements.HighestEndingAddress = reinterpret_cast<PVOID>(w.end - 1);
            }
            requirements.Alignment = static_cast<SIZE_T>(alignment);
            parameter.Type = MemExtendedParameterAddressRequirements;
            parameter.Pointer = &requirements;
            p = va2(GetCurrentProcess(), nullptr, bytes, MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS,
                    &parameter, 1);
        }
        if (!p) {
            // Over-reserve one placeholder, keep the aligned part, give the head and tail back.
            const std::uint64_t padded = bytes + alignment;
            auto* raw = static_cast<unsigned char*>(va2(GetCurrentProcess(), nullptr, padded,
                                                        MEM_RESERVE | MEM_RESERVE_PLACEHOLDER, PAGE_NOACCESS, nullptr, 0));
            if (!raw) return 0;
            const std::uintptr_t start = reinterpret_cast<std::uintptr_t>(raw);
            const std::uintptr_t aligned = static_cast<std::uintptr_t>(align_up(start, alignment));
            const std::uintptr_t end = start + padded;
            if (aligned > start) {
                VirtualFree(raw, aligned - start, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
                VirtualFree(raw, 0, MEM_RELEASE);
            }
            if (aligned + bytes < end) {
                VirtualFree(reinterpret_cast<void*>(aligned), static_cast<SIZE_T>(bytes),
                            MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER);
                VirtualFree(reinterpret_cast<void*>(aligned + bytes), 0, MEM_RELEASE);
            }
            p = reinterpret_cast<void*>(aligned);
            log_once("fallback", "physical reservation: address requirements refused (error %lu); aligned by hand",
                     GetLastError());
        }
    }
    const auto base = reinterpret_cast<std::uintptr_t>(p);
    if (track_placeholders(s, base, pages) == s.mappings.end()) {
        VirtualFree(p, 0, MEM_RELEASE);
        SetLastError(ERROR_NOT_ENOUGH_MEMORY);
        return 0;
    }
    log_line("physical", "reservation 0x%llx (%zu pages, alignment 0x%llx) made for mappings",
             static_cast<unsigned long long>(base), pages, static_cast<unsigned long long>(alignment));
    return base;
}

// Per-export call logging: the first `cap` calls in full ("xmem call ..."), later ones counted (a count line at each
// power of two). Lines are informational: on stderr with X2W_XMEM_LOG=1, which x2w_launch sets.
struct CallCount {
    const char* name;
    unsigned cap;
    std::atomic<unsigned> n{0};
};
CallCount g_calls[] = {
    {"XMemVirtualAlloc", 256},        {"XMemMapPhysicalPages", 256}, {"XMemMapPhysicalPagesScatter", 128},
    {"XMemAllocatePhysicalPages", 64}, {"XMemFreePhysicalPages", 64}, {"XMemAlloc", 32},
    {"XMemFree", 32},                 {"XMemAllocDefault", 32},      {"XMemFreeDefault", 32},
    {"XMemIsToolsMemAvailable", 8},   {"XMemTransferMemory", 32},    {"XMemVirtualQuery", 32},
    {"XMemGetWorkingSetStatistics", 16},
};

CallCount* call_count(const char* name)
{
    for (auto& c : g_calls)
        if (std::strcmp(c.name, name) == 0) return &c;
    return nullptr;
}

// Logs one call line ("xmem call NAME(ARGS) -> RESULT error=N") when the call is within its cap. Keeps the last error.
void log_call_line(const char* name, DWORD error, const char* format, va_list args)
{
    CallCount* c = call_count(name);
    const unsigned i = c ? c->n.fetch_add(1, std::memory_order_relaxed) : 0;
    if (c && i >= c->cap) {
        if (i == c->cap) log_line("call", "%s: %u calls logged; later calls are counted only", name, c->cap);
        else if (!((i + 1) & i)) log_line("call", "%s: %u calls so far", name, i + 1);
        SetLastError(error);
        return;
    }
    char detail[400];
    std::vsnprintf(detail, sizeof(detail), format, args);
    log_line("call", "%s%s error=%lu", name, detail, error);
    SetLastError(error);
}

void log_call(const char* name, const char* format, ...)
{
    const DWORD error = GetLastError();
    va_list args;
    va_start(args, format);
    log_call_line(name, error, format, args);
    va_end(args);
}

// The allocation-type flags spelled out for the call lines.
std::string type_names(DWORD type)
{
    static const std::pair<DWORD, const char*> names[] = {
        {MEM_COMMIT, "MEM_COMMIT"},       {MEM_RESERVE, "MEM_RESERVE"},         {MEM_RESET, "MEM_RESET"},
        {MEM_TOP_DOWN, "MEM_TOP_DOWN"},   {MEM_WRITE_WATCH, "MEM_WRITE_WATCH"}, {MEM_PHYSICAL, "MEM_PHYSICAL"},
        {MEM_RESET_UNDO, "MEM_RESET_UNDO"}, {MEM_LARGE_PAGES, "MEM_LARGE_PAGES"}, {0x80000000u, "MEM_4MB_PAGES"},
    };
    std::string out;
    DWORD rest = type;
    for (const auto& [bit, name] : names) {
        if (!(type & bit)) continue;
        if (!out.empty()) out += '|';
        out += name;
        rest &= ~bit;
    }
    if (rest) {
        char hex[24];
        std::snprintf(hex, sizeof(hex), "%s0x%lx", out.empty() ? "" : "|", rest);
        out += hex;
    }
    return out.empty() ? "0" : out;
}
}  // namespace

namespace xmem_title {
void log_export_call(const char* name, const char* format, ...) noexcept
{
    const DWORD error = GetLastError();
    va_list args;
    va_start(args, format);
    log_call_line(name, error, format, args);
    va_end(args);
}
}  // namespace xmem_title

// ---- exports --------------------------------------------------------------------------------------------------------
static PVOID impl_XMemMapPhysicalPages(PVOID VirtualAddress, ULONG_PTR NumberOfPages, PULONG_PTR PageArray);

static PVOID impl_XMemAllocDefault(SIZE_T dwSize, ULONGLONG dwAttributes)
{
    return allocate_default(dwSize, dwAttributes);
}

static void impl_XMemFreeDefault(PVOID lpAddress, ULONGLONG dwAttributes)
{
    free_default(lpAddress, dwAttributes);
}

static PVOID impl_XMemAlloc(SIZE_T dwSize, ULONGLONG dwAttributes)
{
    const Hooks* hooks = g_hooks.load(std::memory_order_acquire);
    if (!hooks) return allocate_default(dwSize, dwAttributes);
    void* p = hooks->alloc(dwSize, dwAttributes);
    State& s = state();
    if (p && dwSize) {
        Exclusive guard(s.lock);
        ensure_configured(s);
        if (gpu_visible(s, decode(dwAttributes).memory_type)) adopt(s, p, dwSize, dwAttributes);
    }
    return p;
}

static void impl_XMemFree(PVOID lpAddress, ULONGLONG dwAttributes)
{
    const Hooks* hooks = g_hooks.load(std::memory_order_acquire);
    if (!hooks) {
        free_default(lpAddress, dwAttributes);
        return;
    }
    if (lpAddress) {
        State& s = state();
        Exclusive guard(s.lock);
        unadopt(s, lpAddress);
    }
    hooks->free(lpAddress, dwAttributes);
}

extern "C" void WINAPI XMemSetAllocationHooks(PXMEMALLOC_ROUTINE pAllocRoutine, PXMEMFREE_ROUTINE pFreeRoutine)
{
    if (!pAllocRoutine) {
        g_hooks.store(nullptr, std::memory_order_release);
        log_line("hooks", "default routines restored");
        return;
    }
    if (!executable(reinterpret_cast<const void*>(pAllocRoutine)) ||
        !executable(reinterpret_cast<const void*>(pFreeRoutine))) {
        log_once("unimplemented",
                 "XMemSetAllocationHooks(0x%llx, 0x%llx): a routine is null or not executable code (a hooks structure?);"
                 " routines unchanged",
                 static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(pAllocRoutine)),
                 static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(pFreeRoutine)));
        return;
    }
    const Hooks* fresh = new (std::nothrow) Hooks{pAllocRoutine, pFreeRoutine};
    if (!fresh) return;
    g_hooks.store(fresh, std::memory_order_release);  // the previous pair is kept: another thread may be calling it
    log_line("hooks", "installed alloc=0x%llx free=0x%llx",
             static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(pAllocRoutine)),
             static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(pFreeRoutine)));
}

extern "C" void WINAPI XMemCheckDefaultHeaps(void)
{
    State& s = state();
    Shared guard(s.lock);
    std::size_t problems = 0;
    std::uintptr_t previous_end = 0;
    for (const auto& [base, r] : s.records) {
        if (base < previous_end) ++problems;  // overlapping records
        previous_end = base + std::max(r.extent, r.bytes);
        if (r.backing != X2W_XMEM_BACKING_HEAP) {
            MEMORY_BASIC_INFORMATION info{};
            if (VirtualQuery(reinterpret_cast<void*>(base), &info, sizeof(info)) != sizeof(info) ||
                info.State != MEM_COMMIT)
                ++problems;
        }
    }
    for (const Arena& a : s.arenas) {
        std::uint64_t end = 0;
        for (const auto& [offset, bytes] : a.free) {
            if (offset < end || offset + bytes > a.place.bytes) ++problems;
            end = offset + bytes;
        }
    }
    log_line("check", "records=%zu arenas=%zu mappings=%zu problems=%zu", s.records.size(), s.arenas.size(),
             s.mappings.size(), problems);
}

static BOOL impl_XMemAllocatePhysicalPages(DWORD flAllocationType, PULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    State& s = state();
    Exclusive guard(s.lock);
    ensure_configured(s);
    s.memory_exists = true;
    const bool four = (flAllocationType & MEM_4MB_PAGES) != 0;
    const bool sixty_four = (flAllocationType & MEM_LARGE_PAGES) != 0;
    if (!NumberOfPages || !PageArray || four == sixty_four || (four && (*NumberOfPages % 64))) {
        if (NumberOfPages) *NumberOfPages = 0;
        log_once("unimplemented", "XMemAllocatePhysicalPages flags 0x%lx: only MEM_64K_PAGES or MEM_4MB_PAGES (whole "
                                  "runs of 64 pages) are served", flAllocationType);
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    if (!ensure_pool(s)) {
        *NumberOfPages = 0;
        SetLastError(ERROR_NOT_SUPPORTED);
        return FALSE;
    }
    const ULONG_PTR wanted = *NumberOfPages;
    const std::size_t run = four ? 64 : 1;
    ULONG_PTR got = 0;
    for (std::size_t i = 0; i + run <= s.pool_pages.size() && got < wanted; i += run) {
        bool free_run = true;
        for (std::size_t j = 0; j < run && free_run; ++j) free_run = page_is_free(s.pool_pages[i + j]);
        if (!free_run) continue;
        for (std::size_t j = 0; j < run; ++j) {
            // Pages handed out before carry the previous owner's bytes; fresh pool pages are zero.
            if (s.pool_pages[i + j] == page_free_dirty)
                std::memset(s.pool_view + (i + j) * physical_page, 0, physical_page);
            s.pool_pages[i + j] = page_allocated;
            PageArray[got++] = i + j;
        }
    }
    s.pool_free -= got;
    *NumberOfPages = got;
    if (got < wanted)
        log_once("physical", "pool exhausted: asked for %llu pages, gave %llu", static_cast<unsigned long long>(wanted),
                 static_cast<unsigned long long>(got));
    SetLastError(got ? ERROR_SUCCESS : ERROR_OUTOFMEMORY);
    return got > 0;
}

static BOOL impl_XMemFreePhysicalPages(ULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    State& s = state();
    Exclusive guard(s.lock);
    if (NumberOfPages && !PageArray) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    for (ULONG_PTR i = 0; i < NumberOfPages; ++i) {
        if (PageArray[i] >= s.pool_pages.size() || s.pool_pages[PageArray[i]] != page_allocated) {
            SetLastError(ERROR_INVALID_PARAMETER);
            return FALSE;  // validated before any change: a duplicate or unknown page frees nothing
        }
        for (ULONG_PTR j = 0; j < i; ++j) {
            if (PageArray[j] == PageArray[i]) {
                SetLastError(ERROR_INVALID_PARAMETER);
                return FALSE;
            }
        }
    }
    for (ULONG_PTR i = 0; i < NumberOfPages; ++i) {
        if (s.pool_mapped[PageArray[i]])
            log_once("note", "physical page %llu freed while still mapped; the mapping keeps showing it",
                     static_cast<unsigned long long>(PageArray[i]));
        s.pool_pages[PageArray[i]] = page_free_dirty;  // zeroed when handed out again
        ++s.pool_free;
    }
    SetLastError(ERROR_SUCCESS);
    return TRUE;
}

// XMemVirtualAlloc, XMemMapPhysicalPagesScatter, XMemTransferMemory, XMemIsToolsMemAvailable.
// The reference pages (devdocs.xbox.com/reference/system/xmem/functions/) are login-gated and were not read past their
// public one-line descriptions. The contracts below are therefore stated assumptions, not documented behaviour:
//   XMemVirtualAlloc(address, size, type, protect): VirtualAlloc-like, and the allocation type uses the Win32 flag
//     values (winnt.h): MEM_64K_PAGES is MEM_LARGE_PAGES | MEM_PHYSICAL (0x20400000) and MEM_4MB_PAGES is 0x80000000.
//     A real title passes 0x20402000 = MEM_RESERVE | MEM_64K_PAGES. MEM_RESERVE with MEM_PHYSICAL (with or without
//     the page-size bits) and no MEM_COMMIT reserves a range for later physical mapping, as AWE does: the requested
//     address is honoured (64 KiB aligned), a null one is placed on 2 MiB with MEM_LARGE_PAGES, 4 MiB with
//     MEM_4MB_PAGES, else 64 KiB, the size is rounded up to 64 KiB, and the range is a mapping region at once
//     (reserve_physical_range), so XMemMapPhysicalPages / XMemMapPhysicalPagesScatter can map any page in it. With
//     MEM_COMMIT the physical and page-size bits are dropped (logged) and the memory is plain VirtualAlloc memory.
//     The Scatter page's one public line names an XMEM_MAPPABLE flag whose value is not public, so any other bit
//     VirtualAlloc does not define is read as it: stripped (logged once), the size is rounded up to 64 KiB and the
//     range is a plain reservation that the first XMemMapPhysicalPages call at its base adopts (mapping_for).
//     Committed memory is not GPU-visible by itself; GPU visibility comes from XMemAlloc and from physical mappings
//     (register_runs). Every call is logged ("xmem call XMemVirtualAlloc(...)", first 256), with the two stack slots
//     after the four register arguments in case the console signature has more; a NULL result is also logged as
//     "unimplemented" with its reason, so it is never silent.
//   XMemMapPhysicalPagesScatter(addresses, count, pages): MapUserPhysicalPagesScatter-like, one 64 KiB page per entry;
//     a null page array, or a zero entry, unmaps that address. Arguments are validated before anything changes.
//     Page number 0 therefore cannot be mapped through this call (the pool does hand page 0 out).
//   XMemTransferMemory: signature unknown. Accepts any arguments, logs them and returns TRUE without moving data.
//   XMemIsToolsMemAvailable: FALSE (no tools memory on a desktop).
namespace {
// Console page protections combine bits that Win32 treats as exclusive (e.g. 0x3, 0x21, 0x183 seen from a title);
// VirtualAlloc refuses those with ERROR_INVALID_PARAMETER. A value Win32 accepts as-is is kept; any other value is
// mapped to the most permissive desktop equivalent (execute-read-write when an execute bit is set, else
// read-write), dropping the guard/cache modifiers, and logged once.
DWORD desktop_protect(DWORD protect)
{
    if (!protect) return PAGE_READWRITE;
    const DWORD base = protect & 0xffu, modifiers = protect & ~0xffu;
    const bool single = base && !(base & (base - 1));
    if (single && !(modifiers & ~DWORD(PAGE_GUARD | PAGE_NOCACHE | PAGE_WRITECOMBINE)) && base != PAGE_NOACCESS)
        return protect;
    const DWORD mapped = (base & 0xf0u) ? PAGE_EXECUTE_READWRITE : PAGE_READWRITE;
    log_once("note", "XMemVirtualAlloc protect 0x%lx: not a desktop protection; using 0x%lx", protect, mapped);
    return mapped;
}

PVOID virtual_alloc(PVOID Address, SIZE_T Size, DWORD AllocationType, DWORD Protect, const char*& path,
                    std::uint64_t& alignment)
{
    constexpr DWORD mem_4mb_pages = 0x80000000u;
    constexpr DWORD page_bits = MEM_PHYSICAL | MEM_LARGE_PAGES | mem_4mb_pages;
    constexpr DWORD known = MEM_COMMIT | MEM_RESERVE | MEM_RESET | MEM_RESET_UNDO | MEM_TOP_DOWN | MEM_WRITE_WATCH |
                            page_bits;
    const DWORD extra = AllocationType & ~known;
    const DWORD pages = AllocationType & page_bits;
    DWORD type = AllocationType & known & ~page_bits;
    path = "virtualalloc";
    if (extra)
        log_once("note", "XMemVirtualAlloc type 0x%lx: bits 0x%lx read as XMEM_MAPPABLE and stripped",
                 AllocationType, extra);
    if (!(type & (MEM_COMMIT | MEM_RESERVE | MEM_RESET | MEM_RESET_UNDO))) type |= MEM_RESERVE;
    if ((extra || pages) && (type & (MEM_COMMIT | MEM_RESERVE))) {
        Size = (Size + physical_page - 1) / physical_page * physical_page;
        if (Address && (reinterpret_cast<std::uintptr_t>(Address) % physical_page)) {
            path = "refused-unaligned";
            SetLastError(ERROR_INVALID_ADDRESS);
            return nullptr;
        }
    }
    if (!Size) {
        path = "refused-size";
        SetLastError(ERROR_INVALID_PARAMETER);
        return nullptr;
    }
    State& s = state();
    Exclusive guard(s.lock);
    ensure_configured(s);
    s.memory_exists = true;
    if ((pages & (MEM_PHYSICAL | mem_4mb_pages)) && (type & MEM_RESERVE) && !(type & MEM_COMMIT)) {
        alignment = (pages & mem_4mb_pages) ? 4 * MiB : (pages & MEM_LARGE_PAGES) ? 2 * MiB : physical_page;
        path = "physical-reservation";
        return reinterpret_cast<PVOID>(reserve_physical_range(s, reinterpret_cast<std::uintptr_t>(Address),
                                                              static_cast<std::size_t>(Size / physical_page),
                                                              alignment));
    }
    if (pages) {
        log_once("note", "XMemVirtualAlloc type 0x%lx: physical/page-size bits 0x%lx dropped; plain VirtualAlloc",
                 AllocationType, pages);
        if (extra) path = "mappable-reservation";
    } else if (extra) {
        path = "mappable-reservation";
    }
    return VirtualAlloc(Address, Size, type, desktop_protect(Protect));
}
}  // namespace

extern "C" PVOID WINAPI XMemVirtualAlloc(PVOID Address, SIZE_T Size, DWORD AllocationType, DWORD Protect)
{
    // The caller's stack slots for a fifth and sixth argument (readable whatever the caller passed: x64 callers
    // always reserve the home area, and the slots above it are in the caller's frame).
    auto* const ret = static_cast<ULONG_PTR*>(_AddressOfReturnAddress());
    const ULONG_PTR stack5 = ret[5], stack6 = ret[6];
    const char* path = "";
    std::uint64_t alignment = 0;
    PVOID p = virtual_alloc(Address, Size, AllocationType, Protect, path, alignment);
    const DWORD error = p ? ERROR_SUCCESS : GetLastError();
    if (!p)
        log_once("unimplemented", "XMemVirtualAlloc(0x%llx, 0x%llx, 0x%lx, 0x%lx) returned NULL (path %s, error %lu)",
                 static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(Address)),
                 static_cast<unsigned long long>(Size), AllocationType, Protect, path, error);
    SetLastError(error);
    log_call("XMemVirtualAlloc",
             "(addr=0x%llx size=0x%llx type=0x%lx[%s] protect=0x%lx stack5=0x%llx stack6=0x%llx) -> 0x%llx path=%s "
             "align=0x%llx",
             static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(Address)),
             static_cast<unsigned long long>(Size), AllocationType, type_names(AllocationType).c_str(), Protect,
             static_cast<unsigned long long>(stack5), static_cast<unsigned long long>(stack6),
             static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(p)), path,
             static_cast<unsigned long long>(alignment));
    SetLastError(error);
    return p;
}

static BOOL impl_XMemMapPhysicalPagesScatter(PVOID* VirtualAddressArray, ULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    if (!VirtualAddressArray || NumberOfPages > (std::uint64_t{1} << 24)) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return FALSE;
    }
    for (ULONG_PTR i = 0; i < NumberOfPages; ++i) {
        if (!VirtualAddressArray[i] || (reinterpret_cast<std::uintptr_t>(VirtualAddressArray[i]) % physical_page)) {
            log_once("unimplemented", "XMemMapPhysicalPagesScatter entry %llu (0x%llx) is null or not 64 KiB aligned",
                     static_cast<unsigned long long>(i),
                     static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(VirtualAddressArray[i])));
            SetLastError(ERROR_INVALID_PARAMETER);
            return FALSE;
        }
    }
    for (ULONG_PTR i = 0; i < NumberOfPages; ++i) {
        ULONG_PTR page = PageArray ? PageArray[i] : 0;
        const bool unmap = !PageArray || page == 0;
        if (PageArray && page == 0)
            log_once("note", "XMemMapPhysicalPagesScatter: a zero page entry unmaps (page number 0 cannot be mapped here)");
        if (!impl_XMemMapPhysicalPages(VirtualAddressArray[i], 1, unmap ? nullptr : &page)) return FALSE;
    }
    SetLastError(ERROR_SUCCESS);
    return TRUE;
}

extern "C" BOOL WINAPI XMemTransferMemory(ULONG_PTR a0, ULONG_PTR a1, ULONG_PTR a2, ULONG_PTR a3)
{
    SetLastError(ERROR_SUCCESS);
    log_call("XMemTransferMemory", "(0x%llx, 0x%llx, 0x%llx, 0x%llx) -> TRUE", static_cast<unsigned long long>(a0),
             static_cast<unsigned long long>(a1), static_cast<unsigned long long>(a2),
             static_cast<unsigned long long>(a3));
    log_once("unimplemented", "XMemTransferMemory(0x%llx, 0x%llx, 0x%llx, 0x%llx): signature unknown; nothing moved, TRUE",
             static_cast<unsigned long long>(a0), static_cast<unsigned long long>(a1),
             static_cast<unsigned long long>(a2), static_cast<unsigned long long>(a3));
    SetLastError(ERROR_SUCCESS);
    return TRUE;
}

static BOOL impl_XMemIsToolsMemAvailable(void)
{
    return FALSE;
}

static PVOID impl_XMemMapPhysicalPages(PVOID VirtualAddress, ULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    State& s = state();
    Exclusive guard(s.lock);
    ensure_configured(s);
    s.memory_exists = true;
    const auto address = reinterpret_cast<std::uintptr_t>(VirtualAddress);
    if (!NumberOfPages || (address % physical_page) || NumberOfPages > (std::uint64_t{1} << 30) || !ensure_pool(s)) {
        SetLastError(ERROR_INVALID_PARAMETER);
        return nullptr;
    }
    if (PageArray) {
        for (ULONG_PTR i = 0; i < NumberOfPages; ++i) {
            if (PageArray[i] >= s.pool_pages.size() || s.pool_pages[PageArray[i]] != page_allocated) {
                log_once("unimplemented", "XMemMapPhysicalPages page %llu is not an allocated physical page",
                         static_cast<unsigned long long>(PageArray[i]));
                SetLastError(ERROR_INVALID_PARAMETER);
                return nullptr;
            }
        }
    }
    auto it = mapping_for(s, address, static_cast<std::size_t>(NumberOfPages));
    if (it == s.mappings.end()) {
        log_once("unimplemented", "XMemMapPhysicalPages at 0x%llx: the range is neither free, a whole reservation, "
                                  "nor an earlier mapping", static_cast<unsigned long long>(address));
        SetLastError(ERROR_INVALID_ADDRESS);
        return nullptr;
    }
    const std::uintptr_t base = it->first;
    Mapping& m = it->second;
    const std::size_t first = static_cast<std::size_t>(((address ? address : base) - base) / physical_page);
    const auto map3 = kernel().map_view3;
    const auto unmap2 = kernel().unmap_view2;
    bool good = true;
    for (ULONG_PTR i = 0; i < NumberOfPages; ++i) {
        const std::size_t page = first + i;
        void* at = reinterpret_cast<void*>(base + page * physical_page);
        if (m.physical[page] >= 0) {
            unmap2(GetCurrentProcess(), at, MEM_PRESERVE_PLACEHOLDER);
            --s.pool_mapped[static_cast<std::size_t>(m.physical[page])];
            m.physical[page] = -1;
        }
        if (!PageArray) continue;
        if (!map3(s.pool, GetCurrentProcess(), at, PageArray[i] * physical_page, physical_page, MEM_REPLACE_PLACEHOLDER,
                  PAGE_READWRITE, nullptr, 0)) {
            log_once("unimplemented", "MapViewOfFile3 of physical page %llu failed (error %lu)",
                     static_cast<unsigned long long>(PageArray[i]), GetLastError());
            good = false;
            continue;
        }
        m.physical[page] = static_cast<std::int64_t>(PageArray[i]);
        ++s.pool_mapped[PageArray[i]];
    }
    register_runs(s, base, m);
    if (!good) {
        SetLastError(ERROR_NOT_ENOUGH_MEMORY);
        return nullptr;
    }
    SetLastError(ERROR_SUCCESS);
    return reinterpret_cast<void*>(base + first * physical_page);
}

extern "C" HRESULT WINAPI X2WXMemConfigure(const X2WXMemConfig* config)
{
    if (!config || !valid(*config)) return E_INVALIDARG;
    State& s = state();
    Exclusive guard(s.lock);
    if (s.memory_exists) return HRESULT_FROM_WIN32(ERROR_INVALID_STATE);
    if (s.configured) {
        // Only the defaults were applied (by a query); placeholders reserved for them go back.
        for (auto& pieces : s.pieces) {
            for (auto& [base, piece] : pieces) VirtualFree(reinterpret_cast<void*>(base), 0, MEM_RELEASE);
            pieces.clear();
        }
        s.configured = false;
    }
    s.config = *config;
    ensure_configured(s);
    return S_OK;
}

extern "C" HRESULT WINAPI X2WXMemGetConfig(X2WXMemConfig* config)
{
    if (!config || config->size != sizeof(X2WXMemConfig)) return E_INVALIDARG;
    State& s = state();
    Exclusive guard(s.lock);
    ensure_configured(s);
    *config = s.config;
    return S_OK;
}

extern "C" HRESULT WINAPI X2WXMemGetStatistics(uint32_t allocator_id, X2WXMemStatistics* statistics)
{
    if (!statistics || statistics->size != sizeof(X2WXMemStatistics) || (allocator_id > 255 && allocator_id != 0xffffffff))
        return E_INVALIDARG;
    State& s = state();
    Shared guard(s.lock);
    const Counters& c = allocator_id == 0xffffffff ? s.all : s.per_id[allocator_id];
    X2WXMemStatistics out{};
    out.size = sizeof(out);
    out.live_allocations = c.live_allocations;
    out.live_bytes = c.live_bytes;
    out.peak_bytes = c.peak_bytes;
    out.total_allocations = c.total;
    out.failed_allocations = c.failed;
    out.arenas = s.arenas.size();
    for (const Arena& a : s.arenas) out.arena_bytes += a.place.bytes;
    out.standalone = s.standalone;
    out.adopted = s.adopted.size();
    out.large_page_bytes = s.large_page_bytes;
    out.window_misses = s.window_misses;
    out.physical_pages_free = s.pool_free;
    out.physical_pages_total = s.pool_pages.size();
    *statistics = out;
    return S_OK;
}

extern "C" HRESULT WINAPI X2WXMemDescribe(const void* address, X2WXMemAllocationInfo* info)
{
    if (!info || info->size != sizeof(X2WXMemAllocationInfo)) return E_INVALIDARG;
    State& s = state();
    Shared guard(s.lock);
    const auto a = reinterpret_cast<std::uintptr_t>(address);
    X2WXMemAllocationInfo out{};
    out.size = sizeof(out);
    out.window = 0xffffffff;
    auto it = owner(s, a);
    if (it != s.records.end()) {
        const Record& r = it->second;
        out.backing = r.backing;
        out.base = it->first;
        out.bytes = r.bytes;
        out.attributes = r.attributes;
        out.region_base = r.region;
        out.region_bytes = r.region_bytes;
        out.gpu_visible = r.gpu;
        out.large_pages = r.large;
        out.write_watch = r.write_watch;
        out.window = r.window;
        *info = out;
        return S_OK;
    }
    auto adopted = s.adopted.upper_bound(a);
    if (adopted != s.adopted.begin()) {
        --adopted;
        if (a - adopted->first < adopted->second.bytes) {
            out.backing = X2W_XMEM_BACKING_ADOPTED;
            out.base = adopted->first;
            out.bytes = adopted->second.bytes;
            out.region_base = adopted->second.backing;
            out.gpu_visible = 1;
            *info = out;
            return S_OK;
        }
    }
    auto mapping = s.mappings.upper_bound(a);
    if (mapping != s.mappings.begin()) {
        --mapping;
        const std::uint64_t offset = a - mapping->first;
        if (offset < mapping->second.pages * physical_page) {
            const std::size_t page = static_cast<std::size_t>(offset / physical_page);
            if (mapping->second.physical[page] >= 0) {
                out.backing = X2W_XMEM_BACKING_PHYSICAL;
                out.base = mapping->first + page * physical_page;
                out.bytes = physical_page;
                out.region_base = mapping->first;
                out.region_bytes = mapping->second.pages * physical_page;
                out.gpu_visible = 1;
                out.physical_page = static_cast<std::uint64_t>(mapping->second.physical[page]);
                *info = out;
                return S_OK;
            }
        }
    }
    return HRESULT_FROM_WIN32(ERROR_NOT_FOUND);
}

extern "C" HRESULT WINAPI X2WXMemGetWindows(X2WXMemWindow* windows, uint32_t capacity, uint32_t* required)
{
    if (!required) return E_POINTER;
    State& s = state();
    Exclusive guard(s.lock);
    ensure_configured(s);
    *required = X2W_XMEM_WINDOW_KINDS;
    if (capacity < X2W_XMEM_WINDOW_KINDS) return HRESULT_FROM_WIN32(ERROR_INSUFFICIENT_BUFFER);
    if (!windows) return E_POINTER;
    for (std::uint32_t w = 0; w < X2W_XMEM_WINDOW_KINDS; ++w)
        windows[w] = window_enabled(s, w) ? s.config.windows[w] : X2WXMemWindow{0, 0};
    return S_OK;
}

extern "C" HRESULT WINAPI X2WXMemCollectWrites(X2WXMemWriteSink sink, void* context, BOOL reset)
{
    if (!sink) return E_POINTER;
    State& s = state();
    std::vector<std::pair<std::uint64_t, std::uint64_t>> runs;
    {
        Exclusive guard(s.lock);
        ensure_configured(s);
        if (!s.config.write_watch) return E_NOTIMPL;
        constexpr std::size_t chunk_pages = 4096;
        std::vector<void*> hits(chunk_pages);
        try {
            for (const Placement& p : s.watched) {
                for (std::uint64_t at = 0; at < p.bytes; at += chunk_pages * 4096) {
                    const std::uint64_t span = std::min<std::uint64_t>(chunk_pages * 4096, p.bytes - at);
                    ULONG_PTR count = chunk_pages;
                    ULONG granularity = 0;
                    if (GetWriteWatch(reset ? WRITE_WATCH_FLAG_RESET : 0, reinterpret_cast<void*>(p.base + at),
                                      static_cast<SIZE_T>(span), hits.data(), &count, &granularity) != 0)
                        continue;
                    for (ULONG_PTR i = 0; i < count; ++i) {
                        const auto page = reinterpret_cast<std::uintptr_t>(hits[i]);
                        if (!runs.empty() && runs.back().first + runs.back().second == page)
                            runs.back().second += granularity;
                        else
                            runs.emplace_back(page, granularity);
                    }
                }
            }
        } catch (const std::bad_alloc&) {
            return E_OUTOFMEMORY;
        }
    }
    for (const auto& [address, bytes] : runs) sink(address, bytes, context);
    return S_OK;
}

extern "C" X2WXMemLogSink WINAPI X2WXMemSetLogSink(X2WXMemLogSink sink, void* context)
{
    AcquireSRWLockExclusive(&g_log_lock);
    X2WXMemLogSink previous = g_log_sink;
    g_log_sink = sink;
    g_log_context = context;
    ReleaseSRWLockExclusive(&g_log_lock);
    return previous;
}

namespace xmem_title {
bool query_overlay(const void* address, MEMORY_BASIC_INFORMATION& info) noexcept
{
    State& s = state();
    Shared guard(s.lock);
    const auto a = reinterpret_cast<std::uintptr_t>(address);
    for (const Arena& arena : s.arenas) {
        if (a < arena.place.base || a - arena.place.base >= arena.place.bytes) continue;
        auto it = owner(s, a);
        MEMORY_BASIC_INFORMATION out{};
        if (it != s.records.end() && it->second.backing == X2W_XMEM_BACKING_ARENA) {
            out.BaseAddress = reinterpret_cast<void*>(it->first);
            out.AllocationBase = out.BaseAddress;
            out.AllocationProtect = PAGE_READWRITE;
            out.RegionSize = it->second.extent;
            out.State = MEM_COMMIT;
            out.Protect = PAGE_READWRITE;
            out.Type = MEM_PRIVATE;
        } else {
            // The free span of the arena holding the address.
            const std::uint64_t offset = a - arena.place.base;
            std::uint64_t begin = align_down(offset, 4096), end = begin + 4096;
            auto f = arena.free.upper_bound(offset);
            if (f != arena.free.begin()) {
                --f;
                if (offset < f->first + f->second) begin = f->first, end = f->first + f->second;
            }
            out.BaseAddress = reinterpret_cast<void*>(arena.place.base + begin);
            out.RegionSize = static_cast<SIZE_T>(end - begin);
            out.State = MEM_FREE;
            out.Protect = PAGE_NOACCESS;
        }
        info = out;
        return true;
    }
    return false;
}
}

// ---- logged export wrappers (log_call: first N calls in full, the rest counted) ----------------------------------------
extern "C" PVOID WINAPI XMemAllocDefault(SIZE_T dwSize, ULONGLONG dwAttributes)
{
    PVOID p = impl_XMemAllocDefault(dwSize, dwAttributes);
    log_call("XMemAllocDefault", "(size=0x%llx attributes=0x%llx) -> 0x%llx", static_cast<unsigned long long>(dwSize), static_cast<unsigned long long>(dwAttributes), static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(p)));
    return p;
}

extern "C" void WINAPI XMemFreeDefault(PVOID lpAddress, ULONGLONG dwAttributes)
{
    impl_XMemFreeDefault(lpAddress, dwAttributes);
    log_call("XMemFreeDefault", "(addr=0x%llx attributes=0x%llx)", static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(lpAddress)), static_cast<unsigned long long>(dwAttributes));
}

extern "C" PVOID WINAPI XMemAlloc(SIZE_T dwSize, ULONGLONG dwAttributes)
{
    PVOID p = impl_XMemAlloc(dwSize, dwAttributes);
    log_call("XMemAlloc", "(size=0x%llx attributes=0x%llx) -> 0x%llx", static_cast<unsigned long long>(dwSize), static_cast<unsigned long long>(dwAttributes), static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(p)));
    return p;
}

extern "C" void WINAPI XMemFree(PVOID lpAddress, ULONGLONG dwAttributes)
{
    impl_XMemFree(lpAddress, dwAttributes);
    log_call("XMemFree", "(addr=0x%llx attributes=0x%llx)", static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(lpAddress)), static_cast<unsigned long long>(dwAttributes));
}

extern "C" BOOL WINAPI XMemAllocatePhysicalPages(DWORD flAllocationType, PULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    const unsigned long long asked = NumberOfPages ? *NumberOfPages : 0;
    const BOOL ok = impl_XMemAllocatePhysicalPages(flAllocationType, NumberOfPages, PageArray);
    log_call("XMemAllocatePhysicalPages", "(type=0x%lx count=%llu array=0x%llx) -> %d count=%llu first=0x%llx",
             flAllocationType, asked, static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(PageArray)), ok, NumberOfPages ? static_cast<unsigned long long>(*NumberOfPages) : 0ull,
             ok && PageArray && NumberOfPages && *NumberOfPages ? static_cast<unsigned long long>(PageArray[0]) : 0ull);
    return ok;
}

extern "C" BOOL WINAPI XMemFreePhysicalPages(ULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    const BOOL ok = impl_XMemFreePhysicalPages(NumberOfPages, PageArray);
    log_call("XMemFreePhysicalPages", "(count=%llu array=0x%llx) -> %d", static_cast<unsigned long long>(NumberOfPages), static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(PageArray)), ok);
    return ok;
}

extern "C" PVOID WINAPI XMemMapPhysicalPages(PVOID VirtualAddress, ULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    PVOID p = impl_XMemMapPhysicalPages(VirtualAddress, NumberOfPages, PageArray);
    log_call("XMemMapPhysicalPages", "(addr=0x%llx count=%llu array=0x%llx first=0x%llx) -> 0x%llx", static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(VirtualAddress)), static_cast<unsigned long long>(NumberOfPages), static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(PageArray)),
             PageArray && NumberOfPages ? static_cast<unsigned long long>(PageArray[0]) : 0ull, static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(p)));
    return p;
}

extern "C" BOOL WINAPI XMemMapPhysicalPagesScatter(PVOID* VirtualAddressArray, ULONG_PTR NumberOfPages, PULONG_PTR PageArray)
{
    const BOOL ok = impl_XMemMapPhysicalPagesScatter(VirtualAddressArray, NumberOfPages, PageArray);
    log_call("XMemMapPhysicalPagesScatter", "(addresses=0x%llx count=%llu pages=0x%llx first=0x%llx->0x%llx) -> %d",
             static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(VirtualAddressArray)), static_cast<unsigned long long>(NumberOfPages), static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(PageArray)),
             VirtualAddressArray && NumberOfPages
                 ? static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(VirtualAddressArray[0]))
                 : 0ull,
             PageArray && NumberOfPages ? static_cast<unsigned long long>(PageArray[0]) : 0ull, ok);
    return ok;
}

extern "C" BOOL WINAPI XMemIsToolsMemAvailable(void)
{
    const BOOL ok = impl_XMemIsToolsMemAvailable();
    log_call("XMemIsToolsMemAvailable", "() -> %d", ok);
    return ok;
}

// With reserved windows, reserve them while xmem.dll loads, before later DLLs and heaps can take the ranges. Only
// kernel32 calls run here (placeholder reservations and the configuration log line).
BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        wchar_t value[512];
        const DWORD n = GetEnvironmentVariableW(L"X2W_XMEM_WINDOWS", value, 512);
        if (n >= 7 && n < 512 && std::wcsncmp(value, L"reserve", 7) == 0) {
            State& s = state();
            Exclusive guard(s.lock);
            ensure_configured(s);
        }
    }
    return TRUE;
}
