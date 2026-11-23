// era_title_gpu under allocation failure, without a GPU. xmem.dll calls track while servicing
// XMemAlloc, and the first call creates the registry, so an allocation failure behind these
// noexcept entry points must come back as false instead of ending the process. This program
// replaces the global operator new so that one chosen allocation fails, then fails every allocation
// of a first track (registry creation included) and of a later one, one at a time. Each failure
// must leave nothing tracked or registered with era_query, and the call is then retried.
#include "era_query.h"
#include "era_title_gpu.h"

#include <windows.h>

#include <crtdbg.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <new>
#include "test_guard.h"

namespace {
long allocations_until_failure = -1;  // the allocation at this count fails once; -1: none fails
long failed_allocations = 0;
}

void* operator new(std::size_t bytes)
{
    if (allocations_until_failure == 0) {
        allocations_until_failure = -1;
        ++failed_allocations;
        throw std::bad_alloc();
    }
    if (allocations_until_failure > 0) {
        --allocations_until_failure;
    }
    if (void* block = std::malloc(bytes ? bytes : 1)) {
        return block;
    }
    throw std::bad_alloc();
}

void operator delete(void* block) noexcept
{
    std::free(block);
}

void operator delete(void* block, std::size_t) noexcept
{
    std::free(block);
}

namespace {
int failures = 0;

void expect(bool condition, const char* what, long point)
{
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s (failure point %ld)\n", what, point);
        ++failures;
    }
}

// era_query's tail flag: set for regions registered as GPU-intended.
bool registered(const void* address)
{
    unsigned char buffer[era_query::tail_offset + 1]{};
    return era_query::query(GetCurrentProcess(), address, buffer, sizeof(buffer)) != 0 &&
           (buffer[era_query::tail_offset] & era_query::tail_registered) != 0;
}

// Fails allocation 0, 1, 2, ... of one track call in turn, calling again after each failure, until
// a call finishes before its failure point. Returns the number of failures handled, or -1.
long sweep(void* base, std::size_t bytes, const char* phase)
{
    const auto address = reinterpret_cast<std::uint64_t>(base);
    for (long point = 0; point < 1000; ++point) {
        failed_allocations = 0;
        allocations_until_failure = point;
        const bool tracked = era_title_gpu::track(base, bytes);
        allocations_until_failure = -1;
        if (failed_allocations == 0) {
            expect(tracked, "track succeeds when no allocation fails", point);
            expect(registered(base) && era_title_gpu::counts().tracked == 1, "tracked and registered", point);
            std::printf("%s: %ld allocation failures handled, then tracked\n", phase, point);
            return failures ? -1 : point;
        }
        expect(!tracked, "track reports the allocation failure", point);
        expect(!registered(base), "no era_query registration is left", point);
        expect(era_title_gpu::counts().tracked == 0, "no tracked allocation is left", point);
        expect(era_title_gpu::translate(address) == 0, "nothing translates", point);
        if (failures) {
            return -1;
        }
    }
    expect(false, "the sweep ended", 1000);
    return -1;
}
}

int main()
{
    test_guard::install("era_title_gpu_alloc_check", 25);  // below the ctest TIMEOUT (CMakeLists.txt)
    // An exception escaping a noexcept function ends in abort(); the guard reports it on stderr and exits instead of
    // showing the debug CRT's dialog, so the test fails at once rather than waiting.

    constexpr std::size_t bytes = 64 * 1024;
    void* base = VirtualAlloc(nullptr, bytes, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!base) {
        std::fprintf(stderr, "FAIL: VirtualAlloc\n");
        return 1;
    }
    const auto address = reinterpret_cast<std::uint64_t>(base);

    // Before the first track nothing exists, and the other entry points must not create it: with the
    // next allocation set to fail, none of them may allocate.
    test_guard::stage("entry points before the first track");
    era_title_gpu::ShaderView view;
    ID3D12Resource* buffer = nullptr;
    std::uint64_t offset = 0;
    failed_allocations = 0;
    allocations_until_failure = 0;
    const bool empty = era_title_gpu::counts().tracked == 0 && era_title_gpu::translate(address) == 0 &&
                       !era_title_gpu::locate(address, 4, &buffer, &offset) && era_title_gpu::shader_view(view) &&
                       view.ranges.empty() && view.resources.empty() && !era_title_gpu::untrack(base);
    era_title_gpu::detach();
    allocations_until_failure = -1;
    expect(empty && failed_allocations == 0, "the other entry points create nothing before the first track", -1);

    test_guard::stage("first track sweep");
    const long first = sweep(base, bytes, "first track");
    expect(era_title_gpu::untrack(base) && !registered(base), "untrack after the first sweep", -1);
    test_guard::stage("later track sweep");
    const long later = sweep(base, bytes, "later track");
    expect(era_title_gpu::untrack(base) && !registered(base), "untrack after the later sweep", -1);
    // The first track also creates the registry, so it has more allocations that can fail.
    expect(later >= 1 && first > later, "the first sweep covers the registry's creation", -1);
    VirtualFree(base, 0, MEM_RELEASE);

    if (failures == 0) {
        std::printf("era_title_gpu_alloc: passed\n");
    }
    return failures ? 1 : 0;
}
