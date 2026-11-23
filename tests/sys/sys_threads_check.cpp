#include "check.h"
#include "sys_hooks.h"
#include "sys_threads.h"

#include <cstring>
#include <thread>

using namespace x2w_sys;
using namespace x2w_sys::threads;

namespace {
template <typename F>
F hook(const char* name) { return reinterpret_cast<F>(X2WSysHookLookup("kernel32.dll", name)); }

int count_relationship(const std::vector<uint8_t>& buf, LOGICAL_PROCESSOR_RELATIONSHIP rel, bool* sizes_ok) {
    int n = 0;
    size_t off = 0;
    *sizes_ok = true;
    while (off < buf.size()) {
        const auto* e = reinterpret_cast<const SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(buf.data() + off);
        if (e->Size < sizeof(DWORD) * 2 || off + e->Size > buf.size()) { *sizes_ok = false; break; }
        if (e->Relationship == rel) ++n;
        off += e->Size;
    }
    if (off != buf.size()) *sizes_ok = false;
    return n;
}
}  // namespace

int main() {
    chk::capture();

    // ---- pure core map ------------------------------------------------------------------------------
    {
        CoreMap m;
        m.configure({0, 2, 4, 6, 1, 3, 5, 7}, 8);
        CHECK_EQ(m.map_core(0), 0u);
        CHECK_EQ(m.map_core(1), 2u);
        CHECK_EQ(m.map_core(4), 1u);
        CHECK_EQ(m.map_core(9), 2u);  // folds modulo the list
        CHECK_EQ(m.map_mask(0b0011), (1ull << 0) | (1ull << 2));
        CHECK_EQ(m.map_mask(0xFF), 0xFFull);
        CHECK_EQ(m.unmap_core(2), 1u);
        CHECK_EQ(m.unmap_mask((1ull << 0) | (1ull << 2)), 0b0011ull);
        CHECK_EQ(m.unmap_mask(0xFF), 0xFFull);
        // Fewer host CPUs than console cores: modulo, and the inverse picks the lowest console core.
        CoreMap four;
        four.configure({0, 1, 2, 3}, 8);
        CHECK_EQ(four.map_core(5), 1u);
        CHECK_EQ(four.map_mask(0xFF), 0xFull);
        CHECK_EQ(four.unmap_core(1), 1u);
        CHECK_EQ(four.unmap_mask(0xF), 0xFFull);
        // Control: a wrong expectation must differ.
        CHECK(m.map_mask(0b0010) != (1ull << 1));
    }
    {
        // Six SMT cores, twelve logical CPUs (pairs 0-1, 2-3, ...): one logical CPU per core comes first.
        const std::vector<uint64_t> cores = {0x3, 0xC, 0x30, 0xC0, 0x300, 0xC00};
        auto o = order_host_cpus(0xFFF, cores);
        const std::vector<uint32_t> want = {0, 2, 4, 6, 8, 10, 1, 3, 5, 7, 9, 11};
        CHECK(o == want);
        o = order_host_cpus(0xFF0, cores);  // process affinity excludes CPUs 0..3
        const std::vector<uint32_t> want2 = {4, 6, 8, 10, 5, 7, 9, 11};
        CHECK(o == want2);
        o = order_host_cpus(0xF, {});  // no topology: bit order
        const std::vector<uint32_t> want3 = {0, 1, 2, 3};
        CHECK(o == want3);
    }
    CHECK_EQ(mul_div_u64(10'000'000ull * 3600 * 24 * 30, 1'000'000'000ull, 10'000'000ull), 3600ull * 24 * 30 * 1'000'000'000ull);
    CHECK_EQ(mul_div_u64(12345, 3, 2), 18517ull);

    // ---- affinity hooks on the live process ----------------------------------------------------------
    config() = Config{};
    init_from_host();
    auto pAff = hook<DWORD_PTR(WINAPI*)(HANDLE, DWORD_PTR)>("SetThreadAffinityMask");
    auto pIdeal = hook<DWORD(WINAPI*)(HANDLE, DWORD)>("SetThreadIdealProcessor");
    auto pIdealEx = hook<BOOL(WINAPI*)(HANDLE, PPROCESSOR_NUMBER, PPROCESSOR_NUMBER)>("SetThreadIdealProcessorEx");
    auto pGetProc = hook<BOOL(WINAPI*)(HANDLE, PDWORD_PTR, PDWORD_PTR)>("GetProcessAffinityMask");
    auto pPrio = hook<BOOL(WINAPI*)(HANDLE, int)>("SetThreadPriority");
    auto pCpu = hook<DWORD(WINAPI*)()>("GetCurrentProcessorNumber");
    CHECK(pAff && pIdeal && pIdealEx && pGetProc && pPrio && pCpu);
    if (!(pAff && pIdeal && pIdealEx && pGetProc && pPrio && pCpu)) return finish("sys_threads");

    DWORD_PTR proc = 0, sys = 0;
    GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys);
    std::thread worker([&] {
        // Console core 3 -> mapped host CPU; verify through Windows.
        const uint32_t host3 = core_map().map_core(3);
        const DWORD_PTR prev = pAff(GetCurrentThread(), 1ull << 3);
        CHECK(prev != 0);
        // The previous mask is reported in console numbering: the thread had the whole process mask.
        CHECK_EQ(static_cast<uint64_t>(prev), core_map().unmap_mask(proc));
        const DWORD_PTR now = ::SetThreadAffinityMask(GetCurrentThread(), 1ull << host3);  // read back the real mask
        CHECK_EQ(static_cast<uint64_t>(now), 1ull << host3);
        CHECK_EQ(pCpu(), core_map().unmap_core(::GetCurrentProcessorNumber()));
        // Two console cores -> two host bits.
        CHECK(pAff(GetCurrentThread(), 0b101) != 0);
        const DWORD_PTR two = ::SetThreadAffinityMask(GetCurrentThread(), proc);
        CHECK_EQ(static_cast<uint64_t>(two), core_map().map_mask(0b101));
        // Ideal processor.
        pIdeal(GetCurrentThread(), 2);
        const DWORD prev_ideal = pIdeal(GetCurrentThread(), 1);
        if (core_map().host_count() >= 8) CHECK_EQ(prev_ideal, 2u);  // reported back in console numbering
        PROCESSOR_NUMBER pn{0, 4, 0}, old{};
        CHECK(pIdealEx(GetCurrentThread(), &pn, &old));
        PROCESSOR_NUMBER pn2{0, 1, 0};
        CHECK(pIdealEx(GetCurrentThread(), &pn2, &old));
        if (core_map().host_count() >= 8) CHECK_EQ(old.Number, 4);
        // Priorities pass through; TIME_CRITICAL is clamped only when configured.
        CHECK(pPrio(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL));
        CHECK_EQ(GetThreadPriority(GetCurrentThread()), THREAD_PRIORITY_TIME_CRITICAL);
        config().clamp_time_critical = true;
        CHECK(pPrio(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL));
        CHECK_EQ(GetThreadPriority(GetCurrentThread()), THREAD_PRIORITY_HIGHEST);
        config().clamp_time_critical = false;
    });
    worker.join();
    DWORD_PTR cp = 0, cs = 0;
    CHECK(pGetProc(GetCurrentProcess(), &cp, &cs));
    CHECK_EQ(static_cast<uint64_t>(cp), core_map().unmap_mask(proc));
    CHECK(chk::count("SetThreadAffinityMask") >= 1 || core_map().map_core(3) == 3u);

    // ---- reported topology --------------------------------------------------------------------------
    auto pSys = hook<void(WINAPI*)(LPSYSTEM_INFO)>("GetSystemInfo");
    auto pSysN = hook<void(WINAPI*)(LPSYSTEM_INFO)>("GetNativeSystemInfo");
    auto pActive = hook<DWORD(WINAPI*)(WORD)>("GetActiveProcessorCount");
    auto pSlpi = hook<BOOL(WINAPI*)(PSYSTEM_LOGICAL_PROCESSOR_INFORMATION, PDWORD)>("GetLogicalProcessorInformation");
    auto pSlpiEx = hook<BOOL(WINAPI*)(LOGICAL_PROCESSOR_RELATIONSHIP, PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX, PDWORD)>("GetLogicalProcessorInformationEx");
    CHECK(pSys && pSysN && pActive && pSlpi && pSlpiEx);
    if (!(pSys && pSysN && pActive && pSlpi && pSlpiEx)) return finish("sys_threads");

    // Not configured: the host answer passes through.
    {
        SYSTEM_INFO host{}, got{};
        ::GetSystemInfo(&host);
        pSys(&got);
        CHECK_EQ(got.dwNumberOfProcessors, host.dwNumberOfProcessors);
    }
    config().virtual_cores = 8;
    {
        SYSTEM_INFO si{};
        pSys(&si);
        CHECK_EQ(si.dwNumberOfProcessors, 8u);
        CHECK_EQ(static_cast<uint64_t>(si.dwActiveProcessorMask), 0xFFull);
        SYSTEM_INFO sn{};
        pSysN(&sn);
        CHECK_EQ(sn.dwNumberOfProcessors, 8u);
        CHECK_EQ(pActive(0), 8u);
        CHECK_EQ(pActive(ALL_PROCESSOR_GROUPS), 8u);
        CHECK_EQ(pActive(7), ::GetActiveProcessorCount(7));  // other groups: host answer
        DWORD_PTR p = 0, s = 0;
        CHECK(pGetProc(GetCurrentProcess(), &p, &s));
        CHECK_EQ(static_cast<uint64_t>(s), 0xFFull);
    }
    {
        DWORD len = 0;
        SetLastError(0);
        CHECK(!pSlpi(nullptr, &len) && GetLastError() == ERROR_INSUFFICIENT_BUFFER && len > 0);
        std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION> v(len / sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION));
        CHECK(pSlpi(v.data(), &len));
        int cores = 0, l1d = 0, l2 = 0, l3 = 0, numa = 0, pkg = 0;
        uint64_t l3size = 0;
        for (const auto& r : v) {
            if (r.Relationship == RelationProcessorCore) ++cores;
            if (r.Relationship == RelationNumaNode) ++numa;
            if (r.Relationship == RelationProcessorPackage) { ++pkg; CHECK_EQ(static_cast<uint64_t>(r.ProcessorMask), 0xFFull); }
            if (r.Relationship == RelationCache) {
                if (r.Cache.Level == 1 && r.Cache.Type == CacheData) ++l1d;
                if (r.Cache.Level == 2) ++l2;
                if (r.Cache.Level == 3) { ++l3; l3size = r.Cache.Size; }
            }
        }
        CHECK_EQ(cores, 8);
        CHECK_EQ(l1d, 8);
        CHECK_EQ(l2, 8);
        CHECK_EQ(l3, 2);  // 4 cores per L3 by default
        CHECK_EQ(l3size, 4096ull * 1024);
        CHECK_EQ(numa, 1);
        CHECK_EQ(pkg, 1);
        len = 4;  // too small: the required size comes back
        SetLastError(0);
        CHECK(!pSlpi(v.data(), &len) && GetLastError() == ERROR_INSUFFICIENT_BUFFER && len == v.size() * sizeof v[0]);
    }
    {
        DWORD len = 0;
        SetLastError(0);
        CHECK(!pSlpiEx(RelationProcessorCore, nullptr, &len) && GetLastError() == ERROR_INSUFFICIENT_BUFFER && len > 0);
        std::vector<uint8_t> buf(len);
        CHECK(pSlpiEx(RelationProcessorCore, reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(buf.data()), &len));
        bool ok = false;
        CHECK_EQ(count_relationship(buf, RelationProcessorCore, &ok), 8);
        CHECK(ok);
        const auto* first = reinterpret_cast<const SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(buf.data());
        CHECK_EQ(first->Processor.GroupCount, 1);
        CHECK_EQ(static_cast<uint64_t>(first->Processor.GroupMask[0].Mask), 1ull);
        // RelationAll: every kind, record sizes add up exactly.
        len = 0;
        pSlpiEx(RelationAll, nullptr, &len);
        std::vector<uint8_t> all(len);
        CHECK(pSlpiEx(RelationAll, reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(all.data()), &len));
        CHECK_EQ(count_relationship(all, RelationProcessorCore, &ok), 8);
        CHECK(ok);
        CHECK_EQ(count_relationship(all, RelationCache, &ok), 8 * 3 + 2);
        CHECK_EQ(count_relationship(all, RelationNumaNode, &ok), 1);
        CHECK_EQ(count_relationship(all, RelationProcessorPackage, &ok), 1);
        CHECK_EQ(count_relationship(all, RelationGroup, &ok), 1);
        const auto* grp = reinterpret_cast<const SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(all.data());
        (void)grp;
    }
    config().virtual_cores = 0;

    // ---- timing -------------------------------------------------------------------------------------
    {
        auto pF = hook<BOOL(WINAPI*)(LARGE_INTEGER*)>("QueryPerformanceFrequency");
        auto pC = hook<BOOL(WINAPI*)(LARGE_INTEGER*)>("QueryPerformanceCounter");
        CHECK(pF && pC);
        if (pF && pC) {
            LARGE_INTEGER hf{}, f{};
            ::QueryPerformanceFrequency(&hf);
            CHECK(pF(&f));
            CHECK_EQ(f.QuadPart, hf.QuadPart);  // not configured: host values
            config().qpc_frequency = 1'000'000'000ull;
            CHECK(pF(&f));
            CHECK_EQ(f.QuadPart, 1'000'000'000ll);
            LARGE_INTEGER h0{}, h1{}, c0{}, c1{};
            ::QueryPerformanceCounter(&h0);
            pC(&c0);
            Sleep(120);
            pC(&c1);
            ::QueryPerformanceCounter(&h1);
            const double scaled = double(c1.QuadPart - c0.QuadPart) / double(f.QuadPart);
            const double host = double(h1.QuadPart - h0.QuadPart) / double(hf.QuadPart);
            // Same elapsed time through both clocks (the scaled pair brackets a slightly shorter span).
            CHECK(scaled > 0.10 && scaled <= host + 0.001 && host - scaled < 0.02);
            // Monotonic.
            LARGE_INTEGER prev{};
            bool mono = true;
            for (int i = 0; i < 1000; ++i) {
                LARGE_INTEGER c{};
                pC(&c);
                if (c.QuadPart < prev.QuadPart) mono = false;
                prev = c;
            }
            CHECK(mono);
            config().qpc_frequency = 0;
        }
    }
    return finish("sys_threads");
}
