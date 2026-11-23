// The desktop title memory layer through xmem.dll's exports (src/xmem_title_api.h), one scenario per process because
// the layer's configuration is process-wide:
//
//   xmem_title_check attributes        every defined memory type x page size x alignment x size: alignment, whole
//                                      zeroed pages, backing, GPU registration (XMemVirtualQuery tail), statistics per
//                                      allocator ID, release; undefined words are refused and counted
//   xmem_title_check reuse             arena first fit hands a freed block out again, zeroed
//   xmem_title_check standalone        X2W_XMEM_LAYOUT_STANDALONE: each allocation its own VirtualAlloc2 region,
//                                      MEM_FREE after XMemFree, no arena
//   xmem_title_check windows           default (prefer) windows: GPU-visible memory in the graphics window, other
//                                      page-backed memory in the system window; a configured window is honoured
//   xmem_title_check reserve           reserve mode: the window's free space is held as placeholders (a foreign
//                                      VirtualAlloc there fails), allocations are carved from it and coalesce back
//   xmem_title_check hooks             XMemSetAllocationHooks: routing, chaining to the defaults, adoption of hook
//                                      memory as GPU-visible, refusal of a non-code routine, restoring the defaults
//   xmem_title_check physical          XMemAllocatePhysicalPages / XMemMapPhysicalPages / XMemFreePhysicalPages: two
//                                      addresses showing one page, remapping, 4 MB runs, adopted reservations,
//                                      refusals, zeroing on reuse
//   xmem_title_check write_watch       X2WXMemCollectWrites reports exactly the written pages
//   xmem_title_check large_pages       4 MB-page and arena allocations with large pages requested (served with large
//                                      pages when the privilege is held, otherwise logged and served normally)
//   xmem_title_check config            X2WXMemConfigure validation and ordering; the environment overrides
//                                      (run with X2W_XMEM_* set by CTest)
//   xmem_title_check gpu_warp|gpu_hardware
//                                      with a D3D12 device attached: every kind of GPU-visible allocation (arena at
//                                      several offsets, standalone, physical mapping, adopted hook memory, large
//                                      pages) is translated, located and read and written by GPU copies; 300
//                                      allocations fit in at most 8 slots; freed memory is no longer found
//
// Each scenario also checks its own negative controls (a wrong expectation must be detected) and prints
// "xmem_title <scenario>: PASS|FAIL". Exit codes: 0 pass, 1 fail, 2 usage, 77 no adapter (GPU scenarios).
#include "era_title_gpu_api.h"
#include "xmem_title_api.h"

#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iterator>
#include <string>
#include <utility>
#include <string_view>
#include <vector>

extern "C" __declspec(dllimport) BOOL XMemVirtualQuery(HANDLE process, LPCVOID address, void* buffer);

using Microsoft::WRL::ComPtr;
using namespace std::literals;

namespace {
constexpr std::uint64_t KiB = 1024, MiB = 1024 * KiB, GiB = 1024 * MiB;

std::uint64_t word(std::uint32_t type, std::uint32_t page, std::uint32_t align, std::uint32_t id = 0)
{
    return (std::uint64_t{type} << 29) | (std::uint64_t{align} << 24) | (std::uint64_t{id} << 16) |
           (std::uint64_t{page} << 14);
}
std::uint64_t page_bytes(std::uint32_t page) { return page == 0 ? 4 * KiB : page == 1 ? 64 * KiB : 4 * MiB; }
std::uintptr_t addr(const void* p) { return reinterpret_cast<std::uintptr_t>(p); }

bool failed = false;
void expect(bool condition, const char* what)
{
    if (!condition) {
        std::printf("FAILED: %s\n", what);
        failed = true;
    }
}

struct Logs {
    std::vector<std::string> lines;
    bool has(std::string_view text) const
    {
        for (const auto& l : lines)
            if (l.find(text) != std::string::npos) return true;
        return false;
    }
};
Logs logs;
void WINAPI capture(const char* line, void*)
{
    logs.lines.emplace_back(line);
    std::printf("log: %s\n", line);
}

struct Query {
    MEMORY_BASIC_INFORMATION info;
    unsigned char tail[16];
};
Query query(const void* p)
{
    Query q{};
    XMemVirtualQuery(GetCurrentProcess(), p, &q);
    return q;
}

X2WXMemAllocationInfo describe(const void* p)
{
    X2WXMemAllocationInfo info{};
    info.size = sizeof(info);
    if (FAILED(X2WXMemDescribe(p, &info))) info.backing = X2W_XMEM_BACKING_NONE;
    return info;
}

X2WXMemStatistics stats(std::uint32_t id = 0xffffffff)
{
    X2WXMemStatistics s{};
    s.size = sizeof(s);
    X2WXMemGetStatistics(id, &s);
    return s;
}

X2WXMemConfig config()
{
    X2WXMemConfig c{};
    c.size = sizeof(c);
    X2WXMemGetConfig(&c);
    return c;
}

bool zeroed(const void* p, std::size_t n)
{
    const auto* b = static_cast<const unsigned char*>(p);
    return std::all_of(b, b + n, [](unsigned char v) { return v == 0; });
}

// --- attributes -------------------------------------------------------------------------------------------------------
bool attributes()
{
    const X2WXMemConfig c = config();
    unsigned served = 0, arena = 0, standalone = 0, gpu = 0, controls = 0;
    for (std::uint32_t type = 0; type <= 9; ++type) {
        for (std::uint32_t page : {0u, 1u, 2u}) {
            for (std::uint32_t align : {0u, 5u, 12u, 16u, 20u, 22u, 23u}) {
                for (std::size_t bytes : {std::size_t{1}, std::size_t{4097}, std::size_t{65537}}) {
                    const std::uint32_t id = (type * 7 + page * 3 + align) & 0xff;
                    const std::uint64_t w = word(type, page, align, id);
                    const auto before = stats(id);
                    auto* p = static_cast<unsigned char*>(XMemAlloc(bytes, w));
                    if (!p) {
                        std::printf("type=%u page=%u align=%u bytes=%zu refused\n", type, page, align, bytes);
                        failed = true;
                        continue;
                    }
                    ++served;
                    const auto info = describe(p);
                    const bool page_backed = type != 0;
                    const std::uint64_t alignment = std::max<std::uint64_t>(std::uint64_t{1} << std::max(align, 4u),
                                                                            page_backed ? page_bytes(page) : 1);
                    const bool is_gpu = (c.gpu_types >> type) & 1;
                    const auto q = query(p);
                    const bool good =
                        addr(p) % alignment == 0 && zeroed(p, bytes) && info.base == addr(p) && info.bytes == bytes &&
                        info.attributes == w && info.gpu_visible == unsigned(is_gpu) &&
                        info.backing == (type == 0 ? X2W_XMEM_BACKING_HEAP
                                         : alignment > 4 * MiB ? X2W_XMEM_BACKING_STANDALONE
                                                               : X2W_XMEM_BACKING_ARENA) &&
                        q.tail[0] == (is_gpu ? 1 : 0) && (!page_backed || (q.info.State == MEM_COMMIT &&
                                                                           q.info.Protect == PAGE_READWRITE &&
                                                                           addr(q.info.AllocationBase) == addr(p) &&
                                                                           q.info.RegionSize >= bytes &&
                                                                           q.info.RegionSize % page_bytes(page) == 0));
                    if (!good) {
                        std::printf("type=%u page=%u align=%u bytes=%zu p=%p backing=%u gpu=%u tail=%u state=%lx "
                                    "region=%zu base_ok=%d\n", type, page, align, bytes, static_cast<void*>(p),
                                    info.backing, info.gpu_visible, q.tail[0], q.info.State,
                                    static_cast<std::size_t>(q.info.RegionSize), addr(q.info.AllocationBase) == addr(p));
                        failed = true;
                    }
                    // Control: a pointer half an alignment off must fail the same predicate.
                    controls += (addr(p) + alignment / 2) % alignment != 0;
                    arena += info.backing == X2W_XMEM_BACKING_ARENA;
                    standalone += info.backing == X2W_XMEM_BACKING_STANDALONE;
                    gpu += info.gpu_visible;
                    std::memset(p, 0x5a, bytes);
                    const auto during = stats(id);
                    expect(during.live_allocations == before.live_allocations + 1 &&
                               during.live_bytes == before.live_bytes + bytes,
                           "per-allocator statistics count the allocation");
                    XMemFree(p, w);
                    const auto after = stats(id);
                    expect(after.live_allocations == before.live_allocations && after.live_bytes == before.live_bytes,
                           "per-allocator statistics drop it on XMemFree");
                    if (page_backed) {
                        const auto freed = query(p);
                        expect(freed.tail[0] == 0 && freed.info.State == MEM_FREE, "freed memory reads as MEM_FREE");
                    }
                }
            }
        }
    }
    // Refusals: undefined memory types, page size 3, a reserved bit, zero bytes.
    const auto before = stats();
    unsigned refused = 0;
    for (std::uint32_t type = 10; type <= 15; ++type) refused += XMemAlloc(64, word(type, 1, 0)) == nullptr;
    refused += XMemAlloc(64, word(5, 3, 0)) == nullptr;
    refused += XMemAlloc(64, word(5, 1, 0) | (std::uint64_t{1} << 40)) == nullptr;
    refused += XMemAlloc(0, word(5, 1, 0)) == nullptr;
    const auto after = stats();
    expect(refused == 9 && after.failed_allocations == before.failed_allocations + 9, "nine refusals counted");
    expect(logs.has("memory type 10") && logs.has("page size value 3") && logs.has("reserved bits"),
           "refusals are logged");
    XMemFree(nullptr, word(5, 1, 0));
    std::printf("served=%u arena=%u standalone=%u gpu=%u refused=%u controls=%u\n", served, arena, standalone, gpu,
                refused, controls);
    expect(served == 10 * 3 * 7 * 3 && controls == served, "every case served and every control detected");
    expect(stats().arenas >= 1 && stats().live_allocations == 0, "arenas exist and nothing is live");
    XMemCheckDefaultHeaps();
    expect(logs.has("problems=0"), "XMemCheckDefaultHeaps finds no problem");
    return !failed;
}

// --- reuse -------------------------------------------------------------------------------------------------------------
bool reuse()
{
    unsigned recycled = 0;
    for (std::size_t bytes : {std::size_t{256}, std::size_t{70000}, std::size_t{3 * MiB}}) {
        const auto w = word(5, 1, 8);
        auto* a = static_cast<unsigned char*>(XMemAlloc(bytes, w));
        expect(a != nullptr, "first allocation");
        if (!a) continue;
        std::memset(a, 0xa5, bytes);
        XMemFree(a, w);
        auto* b = static_cast<unsigned char*>(XMemAlloc(bytes, w));
        expect(b != nullptr && zeroed(b, bytes), "the next allocation is zero-filled");
        recycled += a == b;
        XMemFree(b, w);
    }
    std::printf("recycled=%u\n", recycled);
    // Control: the zero check is only meaningful when the dirty block came back.
    expect(recycled == 3, "arena first fit returned each freed block");
    return !failed;
}

// --- standalone --------------------------------------------------------------------------------------------------------
bool standalone()
{
    X2WXMemConfig c = config();
    expect(c.layout == X2W_XMEM_LAYOUT_STANDALONE, "X2W_XMEM_LAYOUT=standalone was applied");
    for (std::uint32_t page : {0u, 1u, 2u}) {
        const auto w = word(3, page, 0);
        auto* p = XMemAlloc(5000, w);
        MEMORY_BASIC_INFORMATION info{};
        VirtualQuery(p, &info, sizeof(info));
        expect(p && info.AllocationBase == p && info.State == MEM_COMMIT && addr(p) % page_bytes(page) == 0,
               "a standalone allocation is its own region");
        expect(describe(p).backing == X2W_XMEM_BACKING_STANDALONE && query(p).tail[0] == 1, "standalone, registered");
        XMemFree(p, w);
        VirtualQuery(p, &info, sizeof(info));
        expect(info.State == MEM_FREE, "released to MEM_FREE");
    }
    expect(stats().arenas == 0, "no arena in the standalone layout");
    return !failed;
}

// --- windows -----------------------------------------------------------------------------------------------------------
bool in_window(const void* p, const X2WXMemWindow& w) { return addr(p) >= w.begin && addr(p) < w.end; }

bool windows()
{
    X2WXMemWindow w[2]{};
    std::uint32_t required = 0;
    expect(SUCCEEDED(X2WXMemGetWindows(w, 2, &required)) && required == 2, "two windows");
    std::printf("graphics=[0x%llx,0x%llx) system=[0x%llx,0x%llx)\n", static_cast<unsigned long long>(w[0].begin),
                static_cast<unsigned long long>(w[0].end), static_cast<unsigned long long>(w[1].begin),
                static_cast<unsigned long long>(w[1].end));
    expect(w[0].begin == 0x100000000ull && w[0].end == 0x10000000000ull && w[1].begin == 0x20000000000ull &&
               w[1].end == 0x40000000000ull, "the ERA defaults");
    expect(logs.has("graphics=[0x100000000,0x10000000000)"), "the windows are logged");
    void* g = XMemAlloc(4096, word(1, 1, 0));
    void* big = XMemAlloc(8 * MiB, word(2, 2, 23));  // alignment above 4 MiB: standalone, graphics window
    expect(g && in_window(g, w[0]) && big && in_window(big, w[0]) && addr(big) % (8 * MiB) == 0,
           "GPU-visible memory lies in the graphics window");
    XMemFree(g, word(1, 1, 0));
    XMemFree(big, word(2, 2, 23));
    // Control: the two classes go to disjoint windows, so the placement is the class's, not a coincidence.
    expect(!in_window(g, w[1]) && !in_window(big, w[1]), "control: GPU-visible memory is not in the system window");
    expect(stats().window_misses == 0, "no window miss");
    return !failed;
}

// Run with X2W_XMEM_WINDOWS=reserve:graphics=0x300000000000-0x300040000000,system=0x310000000000-0x310040000000
// and X2W_XMEM_GPU_TYPES=0x7e (types 7-9 page-backed, not GPU-visible).
bool reserve()
{
    X2WXMemWindow w[2]{};
    std::uint32_t required = 0;
    X2WXMemGetWindows(w, 2, &required);
    expect(w[0].begin == 0x300000000000ull && w[0].end == 0x300040000000ull && w[1].begin == 0x310000000000ull,
           "the configured windows");
    // The reservation ran while xmem.dll loaded (before this test's log sink existed), so check the address space.
    MEMORY_BASIC_INFORMATION held{};
    VirtualQuery(reinterpret_cast<void*>(0x300000000000ull), &held, sizeof(held));
    std::printf("window_state=0x%lx region=%zu\n", held.State, static_cast<std::size_t>(held.RegionSize));
    expect(held.State == MEM_RESERVE && held.RegionSize == 1 * GiB, "the whole graphics window is one placeholder");
    // Nobody else can take the window now.
    void* foreign = VirtualAlloc(reinterpret_cast<void*>(0x300010000000ull), 64 * KiB, MEM_RESERVE | MEM_COMMIT,
                                 PAGE_READWRITE);
    expect(foreign == nullptr, "a foreign VirtualAlloc in the reserved window fails");
    if (foreign) VirtualFree(foreign, 0, MEM_RELEASE);
    // Control: the same call just outside the windows succeeds.
    void* outside = VirtualAlloc(reinterpret_cast<void*>(0x320000000000ull), 64 * KiB, MEM_RESERVE | MEM_COMMIT,
                                 PAGE_READWRITE);
    expect(outside != nullptr, "control: the same call outside the windows succeeds");
    if (outside) VirtualFree(outside, 0, MEM_RELEASE);

    // Standalone carving (alignment above 4 MiB) in the graphics window, then everything back and one block that
    // needs the whole window except the head: only possible if the placeholders coalesced.
    std::vector<void*> blocks;
    const auto w23 = word(4, 2, 23);
    for (int i = 0; i < 16; ++i) {
        void* p = XMemAlloc(8 * MiB, w23);
        expect(p && in_window(p, w[0]) && addr(p) % (8 * MiB) == 0 && describe(p).backing == X2W_XMEM_BACKING_STANDALONE,
               "carved in the graphics window");
        std::memset(p, 0x77, 8 * MiB);
        blocks.push_back(p);
    }
    for (void* p : blocks) XMemFree(p, w23);
    // 128 MiB at the window's start spans all sixteen freed blocks: only possible if their placeholders coalesced
    // (without coalescing it would land in the untouched tail, so the address is the control).
    const auto w_all = word(4, 2, 23);
    void* whole = XMemAlloc(128 * MiB, w_all);
    expect(whole && whole == blocks[0], "freed placeholders coalesced into one free range");
    if (whole) {
        expect(zeroed(whole, 1 * MiB), "carved memory is zero");
        XMemFree(whole, w_all);
    }
    // System window: page-backed types outside the GPU mask.
    void* sys = XMemAlloc(100000, word(8, 1, 0));
    expect(sys && in_window(sys, w[1]) && describe(sys).gpu_visible == 0 && query(sys).tail[0] == 0,
           "non-GPU page-backed memory is carved in the system window");
    XMemFree(sys, word(8, 1, 0));
    // A physical-page mapping at a fresh address is carved from the system window's placeholders.
    ULONG_PTR page = 0, count = 1;
    void* mapped = XMemAllocatePhysicalPages(MEM_64K_PAGES, &count, &page) ? XMemMapPhysicalPages(nullptr, 1, &page) : nullptr;
    expect(mapped && in_window(mapped, w[1]) && describe(mapped).backing == X2W_XMEM_BACKING_PHYSICAL,
           "a physical mapping in the system window");
    // An arena too.
    void* tiny = XMemAlloc(4096, word(1, 0, 0));
    expect(tiny && in_window(tiny, w[0]) && describe(tiny).backing == X2W_XMEM_BACKING_ARENA, "an arena in the window");
    XMemFree(tiny, word(1, 0, 0));
    expect(stats().window_misses == 0, "no window miss");
    return !failed;
}

// --- hooks -------------------------------------------------------------------------------------------------------------
struct HookState {
    unsigned allocs = 0, frees = 0;
    unsigned char* pool = nullptr;  // the hook's own VirtualAlloc block, 4 MiB
    std::size_t used = 0;
    void* parent = nullptr;  // an XMemAllocDefault block the hook carves from
    std::size_t parent_used = 0;
} hook;

PVOID WINAPI hook_alloc(SIZE_T bytes, ULONGLONG attributes)
{
    ++hook.allocs;
    const unsigned type = static_cast<unsigned>((attributes >> 29) & 0xf);
    if (type == 3 && hook.pool) {  // graphics type 3: the hook's own memory
        void* p = hook.pool + hook.used;
        hook.used += (bytes + 0xffff) & ~std::size_t{0xffff};
        return p;
    }
    if (type == 4 && hook.parent) {  // graphics type 4: carved from a default allocation
        void* p = static_cast<unsigned char*>(hook.parent) + hook.parent_used;
        hook.parent_used += (bytes + 255) & ~std::size_t{255};
        return p;
    }
    return XMemAllocDefault(bytes, attributes);
}

void WINAPI hook_free(PVOID p, ULONGLONG attributes)
{
    ++hook.frees;
    const unsigned type = static_cast<unsigned>((attributes >> 29) & 0xf);
    if (type == 3 || type == 4) return;
    XMemFreeDefault(p, attributes);
}

bool hooks()
{
    hook.pool = static_cast<unsigned char*>(VirtualAlloc(nullptr, 4 * MiB, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    hook.parent = XMemAllocDefault(1 * MiB, word(5, 1, 0));
    XMemSetAllocationHooks(hook_alloc, hook_free);
    expect(logs.has("hooks installed"), "installation logged");
    // Routed through the hook, which chains to the defaults.
    void* a = XMemAlloc(1000, word(1, 1, 0));
    expect(a && hook.allocs == 1 && describe(a).backing == X2W_XMEM_BACKING_ARENA && query(a).tail[0] == 1,
           "a chained allocation comes from the defaults");
    XMemFree(a, word(1, 1, 0));
    expect(hook.frees == 1, "XMemFree calls the hook's free routine");
    // The hook's own memory becomes GPU-visible (adopted) for its lifetime.
    void* own = XMemAlloc(8192, word(3, 1, 0));
    const auto own_info = describe(own);
    expect(own == hook.pool + 0 && own_info.backing == X2W_XMEM_BACKING_ADOPTED && own_info.region_base == addr(hook.pool) &&
               query(own).tail[0] == 1 && stats().adopted == 1, "hook memory is adopted as GPU-visible");
    void* own2 = XMemAlloc(4096, word(3, 1, 0));
    expect(own2 && query(own2).tail[0] == 1 && stats().adopted == 2, "a second block of the same region");
    XMemFree(own, word(3, 1, 0));
    expect(query(own).tail[0] == 0 && query(own2).tail[0] == 1 && stats().adopted == 1, "freeing drops only that block");
    XMemFree(own2, word(3, 1, 0));
    expect(stats().adopted == 0 && query(own2).tail[0] == 0, "nothing adopted after both are freed");
    // Memory carved from a default allocation is already reachable: nothing to adopt.
    void* carved = XMemAlloc(512, word(4, 1, 0));
    expect(carved && stats().adopted == 0 && query(carved).tail[0] == 1, "carved hook memory is covered by its parent");
    XMemFree(carved, word(4, 1, 0));
    // A heap-type request through the hook is not GPU-visible and is not adopted.
    void* h = XMemAlloc(64, word(0, 0, 4));
    expect(h && stats().adopted == 0 && query(h).tail[0] == 0, "heap memory stays CPU-only");
    XMemFree(h, word(0, 0, 4));
    // A non-code first argument (a structure?) is refused; the routines stay.
    static std::uint64_t structure[4] = {1, 2, 3, 4};
    PXMEMALLOC_ROUTINE not_code = nullptr;
    const void* data = structure;
    std::memcpy(&not_code, &data, sizeof(not_code));
    XMemSetAllocationHooks(not_code, nullptr);
    expect(logs.has("not executable code"), "a structure pointer is refused and logged");
    const unsigned before = hook.allocs;
    void* still = XMemAlloc(64, word(1, 0, 0));
    expect(hook.allocs == before + 1, "the installed hook is still in place");
    XMemFree(still, word(1, 0, 0));
    // Null restores the defaults.
    XMemSetAllocationHooks(nullptr, nullptr);
    const unsigned calls = hook.allocs;
    void* d = XMemAlloc(64, word(1, 0, 0));
    expect(d && hook.allocs == calls && describe(d).backing == X2W_XMEM_BACKING_ARENA, "defaults restored");
    XMemFree(d, word(1, 0, 0));
    // Control: the counts must be exact (a missing or doubled routing would change them).
    std::printf("hook_allocs=%u hook_frees=%u\n", hook.allocs, hook.frees);
    expect(hook.allocs == 6 && hook.frees == 6, "exact hook call counts");
    XMemFreeDefault(hook.parent, word(5, 1, 0));
    VirtualFree(hook.pool, 0, MEM_RELEASE);
    return !failed;
}

// --- physical pages ----------------------------------------------------------------------------------------------------
bool physical()
{
    ULONG_PTR pages[4] = {};
    ULONG_PTR count = 4;
    expect(XMemAllocatePhysicalPages(MEM_64K_PAGES, &count, pages) && count == 4, "four 64 KiB pages");
    const auto total = stats();
    expect(total.physical_pages_total == 256 * MiB / (64 * KiB) && total.physical_pages_free == total.physical_pages_total - 4,
           "pool accounting");
    auto* first = static_cast<unsigned char*>(XMemMapPhysicalPages(nullptr, 4, pages));
    expect(first && addr(first) % (64 * KiB) == 0 && zeroed(first, 4 * 64 * KiB), "mapped, zero");
    if (!first) return false;
    for (int i = 0; i < 4; ++i) std::memset(first + i * 64 * KiB, 0x10 + i, 64 * KiB);
    // The same pages at a second address, in reverse order.
    ULONG_PTR reversed[4] = {pages[3], pages[2], pages[1], pages[0]};
    auto* second = static_cast<unsigned char*>(XMemMapPhysicalPages(nullptr, 4, reversed));
    expect(second && second != first && second[0] == 0x13 && second[3 * 64 * KiB] == 0x10, "two addresses, one page");
    second[5] = 0xee;
    expect(first[3 * 64 * KiB + 5] == 0xee, "a write through one address is seen through the other");
    const auto info = describe(second + 64 * KiB + 7);
    expect(info.backing == X2W_XMEM_BACKING_PHYSICAL && info.physical_page == pages[2] &&
               info.base == addr(second) + 64 * KiB && query(second).tail[0] == 1, "described and GPU-registered");
    // Remap the first page of the first mapping to page 2.
    ULONG_PTR one = pages[2];
    expect(XMemMapPhysicalPages(first, 1, &one) == first && first[0] == 0x12, "remapped in place");
    // Unmap the last page.
    expect(XMemMapPhysicalPages(first + 3 * 64 * KiB, 1, nullptr) == first + 3 * 64 * KiB &&
               describe(first + 3 * 64 * KiB).backing == X2W_XMEM_BACKING_NONE && query(first + 3 * 64 * KiB).tail[0] == 0,
           "unmapped");
    // A title's own reservation is taken over.
    void* reservation = VirtualAlloc(nullptr, 1 * MiB, MEM_RESERVE, PAGE_NOACCESS);
    expect(XMemMapPhysicalPages(reservation, 2, pages) == reservation && static_cast<unsigned char*>(reservation)[0] == 0x10,
           "a reservation becomes a mapping");
    expect(logs.has("adopted for mappings"), "logged");
    // Refusals (each must change nothing): committed memory, unaligned address, unknown page, bad flags, bad free.
    void* committed = VirtualAlloc(nullptr, 64 * KiB, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    ULONG_PTR unknown = 1u << 30;
    count = 1;
    ULONG_PTR scratch = 0;
    const bool refusals = XMemMapPhysicalPages(committed, 1, pages) == nullptr &&
                          XMemMapPhysicalPages(first + 4096, 1, pages) == nullptr &&
                          XMemMapPhysicalPages(nullptr, 1, &unknown) == nullptr &&
                          !XMemAllocatePhysicalPages(0, &count, &scratch) && count == 0 &&
                          !XMemFreePhysicalPages(1, &unknown);
    expect(refusals, "refusals");
    VirtualFree(committed, 0, MEM_RELEASE);
    ULONG_PTR duplicate[2] = {pages[0], pages[0]};
    expect(!XMemFreePhysicalPages(2, duplicate) && stats().physical_pages_free == total.physical_pages_free,
           "a duplicate page frees nothing");
    // 4 MB runs: 64 consecutive pages starting on a 64-page boundary.
    std::vector<ULONG_PTR> run(64);
    count = 64;
    expect(XMemAllocatePhysicalPages(MEM_4MB_PAGES, &count, run.data()) && count == 64 && run[0] % 64 == 0 &&
               run[63] == run[0] + 63, "a 4 MB run");
    count = 63;
    expect(!XMemAllocatePhysicalPages(MEM_4MB_PAGES, &count, run.data() + 0) && count == 0, "a partial 4 MB run refused");
    auto* large = static_cast<unsigned char*>(XMemMapPhysicalPages(nullptr, 64, run.data()));
    expect(large != nullptr, "a 4 MB run maps");
    XMemFreePhysicalPages(64, run.data());
    // Freed pages come back zeroed.
    expect(XMemFreePhysicalPages(4, pages), "free four pages");
    count = 4;
    ULONG_PTR again[4] = {};
    expect(XMemAllocatePhysicalPages(MEM_64K_PAGES, &count, again) && count == 4, "reallocate");
    const bool same = std::equal(std::begin(again), std::end(again), std::begin(pages));
    auto* view = static_cast<unsigned char*>(XMemMapPhysicalPages(nullptr, 4, again));
    expect(view && zeroed(view, 4 * 64 * KiB), "reused pages are zero");
    std::printf("physical_recycled=%d\n", same);
    expect(same, "control: the dirty pages were the ones handed out again");
    XMemFreePhysicalPages(4, again);
    return !failed;
}

// --- write watch -------------------------------------------------------------------------------------------------------
struct Runs {
    std::vector<std::pair<std::uint64_t, std::uint64_t>> runs;
};
void WINAPI collect(std::uint64_t address, std::uint64_t bytes, void* context)
{
    static_cast<Runs*>(context)->runs.emplace_back(address, bytes);
}

bool write_watch()
{
    const auto w = word(5, 1, 0);
    auto* p = static_cast<unsigned char*>(XMemAlloc(64 * 4096, w));
    expect(p && describe(p).write_watch == 1, "write-watched");
    if (!p) return false;
    Runs initial;
    X2WXMemCollectWrites(collect, &initial, TRUE);  // clears the zero-fill and first-touch writes
    Runs none;
    expect(SUCCEEDED(X2WXMemCollectWrites(collect, &none, FALSE)) && none.runs.empty(), "nothing written yet");
    p[0] = 1;
    p[5 * 4096 + 9] = 2;
    p[6 * 4096] = 3;
    Runs seen;
    X2WXMemCollectWrites(collect, &seen, TRUE);
    for (const auto& [a, n] : seen.runs) std::printf("run 0x%llx +%llu\n", static_cast<unsigned long long>(a),
                                                    static_cast<unsigned long long>(n));
    using Run = std::pair<std::uint64_t, std::uint64_t>;
    expect(seen.runs.size() == 2 && seen.runs[0] == Run{addr(p), 4096} && seen.runs[1] == Run{addr(p) + 5 * 4096, 2 * 4096},
           "exactly the written pages, coalesced");
    Runs after;
    X2WXMemCollectWrites(collect, &after, FALSE);
    expect(after.runs.empty(), "reset clears them");
    XMemFree(p, w);
    return !failed;
}

// --- large pages -------------------------------------------------------------------------------------------------------
bool large_pages()
{
    const auto w = word(2, 2, 0);
    auto* p = static_cast<unsigned char*>(XMemAlloc(6 * MiB, w));
    const auto info = describe(p);
    const bool granted = !logs.has("SeLockMemoryPrivilege is not held") && !logs.has("large-page allocation refused");
    std::printf("large_pages=%s large_page_bytes=%llu minimum=%zu\n", granted ? "granted" : "unavailable",
                static_cast<unsigned long long>(stats().large_page_bytes), GetLargePageMinimum());
    expect(p && addr(p) % (4 * MiB) == 0 && zeroed(p, 6 * MiB), "served on a 4 MiB boundary");
    expect(info.large_pages == unsigned(granted) && (stats().large_page_bytes > 0) == granted,
           "large pages exactly when granted");
    if (!granted)
        expect(logs.has("large pages requested") || logs.has("large-page allocation refused"), "the fallback is logged");
    std::memset(p, 1, 6 * MiB);
    XMemFree(p, w);
    return !failed;
}

// --- config ------------------------------------------------------------------------------------------------------------
// Run with X2W_XMEM_ARENA_MB=16, X2W_XMEM_GPU_TYPES=0x7e, X2W_XMEM_PHYSICAL_MB=8 and X2W_XMEM_LAYOUT=bogus.
bool configuration()
{
    X2WXMemConfig c = config();
    expect(c.arena_bytes == 16 * MiB && c.gpu_types == 0x7e && c.physical_pool_bytes == 8 * MiB &&
               c.layout == X2W_XMEM_LAYOUT_ARENA, "environment overrides applied, the bogus one ignored");
    expect(logs.has("ignored X2W_XMEM_LAYOUT=bogus"), "the bogus value is logged");
    X2WXMemConfig bad = c;
    bad.arena_bytes = 3 * MiB;
    expect(X2WXMemConfigure(&bad) == E_INVALIDARG, "a non-power-of-two arena is refused");
    bad = c;
    bad.windows[0] = {0x1000, 0x2000};
    expect(X2WXMemConfigure(&bad) == E_INVALIDARG, "an unaligned window is refused");
    bad = c;
    bad.size = 4;
    expect(X2WXMemConfigure(&bad) == E_INVALIDARG && X2WXMemConfigure(nullptr) == E_INVALIDARG, "bad size, null");
    X2WXMemConfig good = c;
    good.arena_bytes = 8 * MiB;
    expect(X2WXMemConfigure(&good) == S_OK && config().arena_bytes == 8 * MiB, "configured before the first allocation");
    void* p = XMemAlloc(100, word(1, 0, 0));
    expect(p && stats().arena_bytes == 8 * MiB, "the configured arena size is used");
    expect(X2WXMemConfigure(&good) == HRESULT_FROM_WIN32(ERROR_INVALID_STATE), "refused once memory exists");
    void* q = XMemAlloc(100, word(7, 0, 0));
    expect(q && describe(q).gpu_visible == 0 && describe(q).backing == X2W_XMEM_BACKING_STANDALONE,
           "type 7 is outside the GPU mask");
    XMemFree(p, word(1, 0, 0));
    XMemFree(q, word(7, 0, 0));
    return !failed;
}

// --- GPU ---------------------------------------------------------------------------------------------------------------
struct Gpu {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12Fence> fence;
    UINT64 value = 0;
    HANDLE event = nullptr;

    int create(bool warp)
    {
        ComPtr<IDXGIFactory4> factory;
        if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) return 1;
        ComPtr<IDXGIAdapter1> adapter;
        if (warp) {
            factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter));
        } else {
            ComPtr<IDXGIAdapter1> candidate;
            for (UINT i = 0; !adapter && factory->EnumAdapters1(i, &candidate) != DXGI_ERROR_NOT_FOUND; ++i) {
                DXGI_ADAPTER_DESC1 desc{};
                if (SUCCEEDED(candidate->GetDesc1(&desc)) && !(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)) adapter = candidate;
            }
        }
        if (!adapter) return 77;
        DXGI_ADAPTER_DESC1 desc{};
        adapter->GetDesc1(&desc);
        std::printf("adapter=%ls\n", desc.Description);
        if (FAILED(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)))) return 1;
        D3D12_COMMAND_QUEUE_DESC q{};
        q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        if (FAILED(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue))) ||
            FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator))) ||
            FAILED(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
                                             IID_PPV_ARGS(&list))) ||
            FAILED(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence))))
            return 1;
        list->Close();
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        return 0;
    }
    ComPtr<ID3D12Resource> buffer(D3D12_HEAP_TYPE type, UINT64 bytes, D3D12_RESOURCE_STATES state)
    {
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = type;
        D3D12_RESOURCE_DESC desc{};
        desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        desc.Width = bytes;
        desc.Height = 1;
        desc.DepthOrArraySize = 1;
        desc.MipLevels = 1;
        desc.SampleDesc.Count = 1;
        desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r;
        device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state, nullptr, IID_PPV_ARGS(&r));
        return r;
    }
    bool run()
    {
        list->Close();
        ID3D12CommandList* lists[] = {list.Get()};
        queue->ExecuteCommandLists(1, lists);
        queue->Signal(fence.Get(), ++value);
        if (fence->GetCompletedValue() < value) {
            fence->SetEventOnCompletion(value, event);
            if (WaitForSingleObject(event, 20000) != WAIT_OBJECT_0) return false;
        }
        return SUCCEEDED(device->GetDeviceRemovedReason());
    }
};

// The GPU reads 256 bytes at the title address through X2WTitleGpuLocate and writes 256 bytes after them; both must
// match what the CPU sees at the title address.
bool gpu_roundtrip(Gpu& gpu, unsigned char* title, unsigned seed)
{
    for (int i = 0; i < 256; ++i) title[i] = static_cast<unsigned char>(seed ^ i);
    void* resource = nullptr;
    std::uint64_t offset = 0;
    if (FAILED(X2WTitleGpuLocate(addr(title), 512, &resource, &offset)) || !resource) return false;
    ComPtr<ID3D12Resource> buffer;
    buffer.Attach(static_cast<ID3D12Resource*>(resource));
    auto readback = gpu.buffer(D3D12_HEAP_TYPE_READBACK, 256, D3D12_RESOURCE_STATE_COPY_DEST);
    auto upload = gpu.buffer(D3D12_HEAP_TYPE_UPLOAD, 256, D3D12_RESOURCE_STATE_GENERIC_READ);
    void* mapped = nullptr;
    upload->Map(0, nullptr, &mapped);
    for (int i = 0; i < 256; ++i) static_cast<unsigned char*>(mapped)[i] = static_cast<unsigned char>(~seed ^ i);
    upload->Unmap(0, nullptr);
    gpu.allocator->Reset();
    gpu.list->Reset(gpu.allocator.Get(), nullptr);
    gpu.list->CopyBufferRegion(readback.Get(), 0, buffer.Get(), offset, 256);
    gpu.list->CopyBufferRegion(buffer.Get(), offset + 256, upload.Get(), 0, 256);
    if (!gpu.run()) return false;
    readback->Map(0, nullptr, &mapped);
    bool good = std::memcmp(mapped, title, 256) == 0;
    D3D12_RANGE none{0, 0};
    readback->Unmap(0, &none);
    for (int i = 0; i < 256; ++i) good = good && title[256 + i] == static_cast<unsigned char>(~seed ^ i);
    return good;
}

std::uint32_t slots_in_view(std::uint32_t* range_count)
{
    std::uint32_t required = 0;
    X2WTitleGpuGetShaderView(nullptr, nullptr, 0, &required);
    std::vector<X2WTitleGpuRange> ranges(required);
    std::vector<void*> resources(required);
    if (required && FAILED(X2WTitleGpuGetShaderView(ranges.data(), resources.data(), required, &required))) return 0xffffffff;
    std::vector<void*> distinct;
    std::uint32_t max_slot = 0;
    for (std::uint32_t i = 0; i < required; ++i) {
        if (std::find(distinct.begin(), distinct.end(), resources[i]) == distinct.end()) distinct.push_back(resources[i]);
        max_slot = std::max(max_slot, ranges[i].slot + 1);
        if (resources[i]) static_cast<IUnknown*>(resources[i])->Release();
    }
    *range_count = required;
    return distinct.size() == max_slot ? max_slot : 0xfffffffe;
}

PVOID WINAPI gpu_hook_alloc(SIZE_T, ULONGLONG) { return hook.pool + 64 * KiB; }
void WINAPI gpu_hook_free(PVOID, ULONGLONG) {}

int gpu(bool warp)
{
    Gpu g;
    if (const int created = g.create(warp)) return created;
    const HRESULT attached = X2WTitleGpuAttach(g.device.Get());
    std::printf("attach=0x%08lx\n", static_cast<unsigned long>(attached));
    if (attached == E_NOTIMPL) {
        std::puts("existing heaps are not supported by this adapter");
        return 77;
    }
    expect(SUCCEEDED(attached), "attach");
    unsigned kinds = 0;
    // Arena allocations at several offsets, with every page size.
    std::vector<std::pair<unsigned char*, std::uint64_t>> live;
    for (std::uint32_t i = 0; i < 300; ++i) {
        const auto w = word(1 + i % 6, i % 10 == 0 ? 2 : i % 2, (i * 5) % 17, i & 0xff);
        auto* p = static_cast<unsigned char*>(XMemAlloc(512 + (i % 7) * 3000, w));
        expect(p != nullptr, "300 allocations");
        live.emplace_back(p, w);
    }
    unsigned roundtrips = 0;
    for (std::size_t i = 0; i < live.size(); i += 37) roundtrips += gpu_roundtrip(g, live[i].first, static_cast<unsigned>(i));
    expect(roundtrips == (live.size() + 36) / 37, "arena allocations are read and written by the GPU");
    kinds += roundtrips == (live.size() + 36) / 37;
    // Standalone (alignment above 4 MiB).
    auto* big = static_cast<unsigned char*>(XMemAlloc(9 * MiB, word(2, 2, 23)));
    expect(big && describe(big).backing == X2W_XMEM_BACKING_STANDALONE && gpu_roundtrip(g, big + 5 * MiB, 3),
           "a standalone allocation");
    kinds += big && gpu_roundtrip(g, big, 4);
    // Physical mapping: the second page of a reversed pair.
    ULONG_PTR pages[2] = {};
    ULONG_PTR count = 2;
    XMemAllocatePhysicalPages(MEM_64K_PAGES, &count, pages);
    ULONG_PTR reversed[2] = {pages[1], pages[0]};
    auto* mapped = static_cast<unsigned char*>(XMemMapPhysicalPages(nullptr, 2, reversed));
    expect(mapped && gpu_roundtrip(g, mapped + 64 * KiB, 5), "a physical mapping");
    kinds += mapped && gpu_roundtrip(g, mapped, 6);
    // Adopted hook memory at an offset inside the hook's block.
    hook.pool = static_cast<unsigned char*>(VirtualAlloc(nullptr, 1 * MiB, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
    XMemSetAllocationHooks(gpu_hook_alloc, gpu_hook_free);
    auto* adopted = static_cast<unsigned char*>(XMemAlloc(4096, word(3, 1, 0)));
    XMemSetAllocationHooks(nullptr, nullptr);
    expect(adopted == hook.pool + 64 * KiB && describe(adopted).backing == X2W_XMEM_BACKING_ADOPTED &&
               gpu_roundtrip(g, adopted, 7), "adopted hook memory");
    kinds += adopted && gpu_roundtrip(g, adopted + 1024, 8);
    std::uint32_t ranges = 0;
    const std::uint32_t slots = slots_in_view(&ranges);
    std::printf("allocations=%zu ranges=%u slots=%u arenas=%llu kinds=%u\n", live.size() + 3, ranges, slots,
                static_cast<unsigned long long>(stats().arenas), kinds);
    expect(slots <= 8 && ranges >= 4, "300+ allocations fit in at most 8 title memory slots");
    expect(kinds == 4, "every kind of GPU-visible memory reached the GPU");
    // Freed memory is gone from the GPU's view; neighbours stay.
    const std::uint64_t freed = addr(live[10].first);
    XMemFree(live[10].first, live[10].second);
    void* none = nullptr;
    std::uint64_t offset = 0;
    expect(X2WTitleGpuTranslate(freed, 4) == 0 &&
               X2WTitleGpuLocate(freed, 4, &none, &offset) == HRESULT_FROM_WIN32(ERROR_NOT_FOUND) &&
               X2WTitleGpuTranslate(addr(live[11].first), 4) != 0, "a freed allocation is no longer found");
    // Control: memory the layer never saw is not found (a registry that answered for everything would pass above).
    void* plain = VirtualAlloc(nullptr, 64 * KiB, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    expect(X2WTitleGpuTranslate(addr(plain), 4) == 0, "control: unregistered memory is not translated");
    VirtualFree(plain, 0, MEM_RELEASE);
    for (std::size_t i = 0; i < live.size(); ++i)
        if (i != 10) XMemFree(live[i].first, live[i].second);
    XMemFree(big, word(2, 2, 23));
    X2WTitleGpuDetach();
    return failed ? 1 : 0;
}
}  // namespace

int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    X2WXMemSetLogSink(capture, nullptr);
    const std::string_view scenario = argv[1];
    int rc = 2;
    if (scenario == "attributes") rc = attributes() ? 0 : 1;
    else if (scenario == "reuse") rc = reuse() ? 0 : 1;
    else if (scenario == "standalone") rc = standalone() ? 0 : 1;
    else if (scenario == "windows") rc = windows() ? 0 : 1;
    else if (scenario == "reserve") rc = reserve() ? 0 : 1;
    else if (scenario == "hooks") rc = hooks() ? 0 : 1;
    else if (scenario == "physical") rc = physical() ? 0 : 1;
    else if (scenario == "write_watch") rc = write_watch() ? 0 : 1;
    else if (scenario == "large_pages") rc = large_pages() ? 0 : 1;
    else if (scenario == "config") rc = configuration() ? 0 : 1;
    else if (scenario == "gpu_warp" || scenario == "gpu_hardware") rc = gpu(scenario == "gpu_warp");
    if (rc == 2) return 2;
    std::printf("xmem_title %s: %s\n", argv[1], rc == 0 ? "PASS" : rc == 77 ? "SKIP" : "FAIL");
    return rc;
}
