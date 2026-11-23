#include "sys_threads.h"

#include "sys_common.h"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <set>

namespace x2w_sys::threads {

// ---------------------------------------------------------------------------------------------------------
// Core mapping
// ---------------------------------------------------------------------------------------------------------
void CoreMap::configure(std::vector<uint32_t> host_cpus, uint32_t console_cores) {
    host_ = std::move(host_cpus);
    if (host_.empty()) host_.push_back(0);
    console_cores_ = console_cores ? console_cores : 8;
}

uint32_t CoreMap::map_core(uint32_t c) const {
    if (host_.empty()) return c;
    return host_[c % host_.size()];
}

uint32_t CoreMap::unmap_core(uint32_t host_cpu) const {
    for (uint32_t c = 0; c < console_cores_; ++c)
        if (map_core(c) == host_cpu) return c;
    return host_cpu;
}

uint64_t CoreMap::map_mask(uint64_t m) const {
    uint64_t out = 0;
    for (uint32_t i = 0; i < 64; ++i)
        if (m & (1ull << i)) out |= 1ull << map_core(i % console_cores_);
    return out;
}

uint64_t CoreMap::unmap_mask(uint64_t host_mask) const {
    uint64_t out = 0;
    for (uint32_t c = 0; c < console_cores_ && c < 64; ++c)
        if (host_mask & (1ull << map_core(c))) out |= 1ull << c;
    return out;
}

std::vector<uint32_t> order_host_cpus(uint64_t allowed, const std::vector<uint64_t>& core_masks) {
    std::vector<uint32_t> first, rest;
    std::set<uint32_t> placed;
    for (uint64_t cm : core_masks) {
        const uint64_t m = cm & allowed;
        bool took = false;
        for (uint32_t i = 0; i < 64; ++i) {
            if (!(m & (1ull << i))) continue;
            if (!took) {
                first.push_back(i);
                took = true;
            } else {
                rest.push_back(i);
            }
            placed.insert(i);
        }
    }
    for (uint32_t i = 0; i < 64; ++i)
        if ((allowed & (1ull << i)) && !placed.count(i)) first.push_back(i);
    first.insert(first.end(), rest.begin(), rest.end());
    return first;
}

// ---------------------------------------------------------------------------------------------------------
// Process state
// ---------------------------------------------------------------------------------------------------------
namespace {
Config g_config;
CoreMap g_map;
LONG64 g_qpc_calls = 0;
LONG g_affinity_remaps = 0;

uint32_t reported_cores() { return g_config.virtual_cores ? g_config.virtual_cores : 0; }
uint64_t reported_mask(uint32_t n) { return n >= 64 ? ~0ull : ((1ull << n) - 1); }

std::vector<uint64_t> host_core_masks() {
    std::vector<uint64_t> masks;
    DWORD len = 0;
    GetLogicalProcessorInformationEx(RelationProcessorCore, nullptr, &len);
    if (!len) return masks;
    std::vector<uint8_t> buf(len);
    if (!GetLogicalProcessorInformationEx(RelationProcessorCore,
                                          reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(buf.data()), &len))
        return masks;
    for (size_t off = 0; off < len;) {
        auto* e = reinterpret_cast<SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(buf.data() + off);
        if (e->Relationship == RelationProcessorCore && e->Processor.GroupMask[0].Group == 0)
            masks.push_back(e->Processor.GroupMask[0].Mask);
        off += e->Size;
    }
    return masks;
}
}  // namespace

Config& config() { return g_config; }
CoreMap& core_map() { return g_map; }

void init_from_host() {
    DWORD_PTR proc = 0, sys = 0;
    GetProcessAffinityMask(GetCurrentProcess(), &proc, &sys);
    auto order = order_host_cpus(static_cast<uint64_t>(proc), host_core_masks());
    g_map.configure(order, g_config.console_cores);
    std::string list;
    for (size_t i = 0; i < g_config.console_cores; ++i)
        list += (i ? "," : "") + std::to_string(i) + "->" + std::to_string(g_map.map_core(static_cast<uint32_t>(i)));
    log("threads: console cores %u over %zu host logical CPUs: %s", g_config.console_cores, order.size(), list.c_str());
    if (g_config.virtual_cores) log("threads: reporting %u cores (host has %zu)", g_config.virtual_cores, order.size());
    if (g_config.qpc_frequency) log("timing: QueryPerformanceFrequency reports %llu Hz", static_cast<unsigned long long>(g_config.qpc_frequency));
}

void apply_config_line(const std::string& key, const std::string& value) {
    auto num = [&] { return static_cast<uint64_t>(std::strtoull(value.c_str(), nullptr, 0)); };
    if (key == "threads.console_cores") g_config.console_cores = static_cast<uint32_t>(num());
    else if (key == "threads.virtual_cores") g_config.virtual_cores = static_cast<uint32_t>(num());
    else if (key == "threads.clamp_time_critical") g_config.clamp_time_critical = value == "on" || value == "1";
    else if (key == "timing.qpc_frequency") g_config.qpc_frequency = num();
    else if (key == "threads.l1_kib") g_config.l1_kib = static_cast<uint32_t>(num());
    else if (key == "threads.l2_kib") g_config.l2_kib = static_cast<uint32_t>(num());
    else if (key == "threads.l3_kib") g_config.l3_kib = static_cast<uint32_t>(num());
    else if (key == "threads.cores_per_l3") g_config.cores_per_l3 = static_cast<uint32_t>(num());
}

void log_summary() {
    log("threads: %ld affinity/ideal-processor remaps, %lld QPC calls", g_affinity_remaps,
        static_cast<long long>(g_qpc_calls));
}

// ---------------------------------------------------------------------------------------------------------
// Synthetic topology
// ---------------------------------------------------------------------------------------------------------
std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION> synth_slpi(const Config& cfg) {
    std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION> out;
    const uint32_t n = cfg.virtual_cores;
    for (uint32_t i = 0; i < n; ++i) {
        SYSTEM_LOGICAL_PROCESSOR_INFORMATION core{};
        core.ProcessorMask = static_cast<ULONG_PTR>(1ull << i);
        core.Relationship = RelationProcessorCore;
        core.ProcessorCore.Flags = 0;
        out.push_back(core);
    }
    auto cache = [&](ULONG_PTR mask, BYTE level, DWORD kib, PROCESSOR_CACHE_TYPE type, BYTE assoc) {
        SYSTEM_LOGICAL_PROCESSOR_INFORMATION c{};
        c.ProcessorMask = mask;
        c.Relationship = RelationCache;
        c.Cache.Level = level;
        c.Cache.Associativity = assoc;
        c.Cache.LineSize = 64;
        c.Cache.Size = kib * 1024;
        c.Cache.Type = type;
        out.push_back(c);
    };
    for (uint32_t i = 0; i < n; ++i) {
        const auto m = static_cast<ULONG_PTR>(1ull << i);
        cache(m, 1, cfg.l1_kib, CacheData, 8);
        cache(m, 1, cfg.l1_kib, CacheInstruction, 8);
        cache(m, 2, cfg.l2_kib, CacheUnified, 8);
    }
    const uint32_t per = cfg.cores_per_l3 ? cfg.cores_per_l3 : n;
    for (uint32_t first = 0; first < n; first += per) {
        uint64_t m = 0;
        for (uint32_t i = first; i < std::min(n, first + per); ++i) m |= 1ull << i;
        cache(static_cast<ULONG_PTR>(m), 3, cfg.l3_kib, CacheUnified, 16);
    }
    SYSTEM_LOGICAL_PROCESSOR_INFORMATION numa{};
    numa.ProcessorMask = static_cast<ULONG_PTR>(reported_mask(n));
    numa.Relationship = RelationNumaNode;
    numa.NumaNode.NodeNumber = 0;
    out.push_back(numa);
    SYSTEM_LOGICAL_PROCESSOR_INFORMATION pkg{};
    pkg.ProcessorMask = static_cast<ULONG_PTR>(reported_mask(n));
    pkg.Relationship = RelationProcessorPackage;
    out.push_back(pkg);
    return out;
}

namespace {
// NUMA_NODE_RELATIONSHIP and CACHE_RELATIONSHIP end in { WORD GroupCount; GROUP_AFFINITY GroupMask; } in current
// SDKs and in { BYTE Reserved[20]; GROUP_AFFINITY GroupMask; } in older ones; the count sits just before the mask.
void set_group_count(GROUP_AFFINITY* mask) {
    const WORD one = 1;
    std::memcpy(reinterpret_cast<uint8_t*>(mask) - sizeof one, &one, sizeof one);
}

template <typename Fill>
void append_ex(std::vector<uint8_t>& out, LOGICAL_PROCESSOR_RELATIONSHIP rel, size_t body, Fill fill) {
    const size_t header = offsetof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX, Processor);
    std::vector<uint8_t> rec(header + body, 0);
    auto* e = reinterpret_cast<SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX*>(rec.data());
    e->Relationship = rel;
    e->Size = static_cast<DWORD>(rec.size());
    fill(*e);
    out.insert(out.end(), rec.begin(), rec.end());
}
}  // namespace

std::vector<uint8_t> synth_slpi_ex(const Config& cfg, LOGICAL_PROCESSOR_RELATIONSHIP rel) {
    std::vector<uint8_t> out;
    const uint32_t n = cfg.virtual_cores;
    const bool all = rel == RelationAll;
    auto gm = [](uint64_t m) {
        GROUP_AFFINITY g{};
        g.Mask = static_cast<KAFFINITY>(m);
        g.Group = 0;
        return g;
    };
    if (rel == RelationProcessorCore || all) {
        for (uint32_t i = 0; i < n; ++i)
            append_ex(out, RelationProcessorCore, sizeof(PROCESSOR_RELATIONSHIP), [&](SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX& e) {
                e.Processor.Flags = 0;
                e.Processor.GroupCount = 1;
                e.Processor.GroupMask[0] = gm(1ull << i);
            });
    }
    if (rel == RelationNumaNode || all) {
        append_ex(out, RelationNumaNode, sizeof(NUMA_NODE_RELATIONSHIP), [&](SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX& e) {
            e.NumaNode.NodeNumber = 0;
            set_group_count(&e.NumaNode.GroupMask);
            e.NumaNode.GroupMask = gm(reported_mask(n));
        });
    }
    if (rel == RelationCache || all) {
        auto cache = [&](uint64_t mask, BYTE level, DWORD kib, PROCESSOR_CACHE_TYPE type, BYTE assoc) {
            append_ex(out, RelationCache, sizeof(CACHE_RELATIONSHIP), [&](SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX& e) {
                e.Cache.Level = level;
                e.Cache.Associativity = assoc;
                e.Cache.LineSize = 64;
                e.Cache.CacheSize = kib * 1024;
                e.Cache.Type = type;
                set_group_count(&e.Cache.GroupMask);
                e.Cache.GroupMask = gm(mask);
            });
        };
        for (uint32_t i = 0; i < n; ++i) {
            cache(1ull << i, 1, cfg.l1_kib, CacheData, 8);
            cache(1ull << i, 1, cfg.l1_kib, CacheInstruction, 8);
            cache(1ull << i, 2, cfg.l2_kib, CacheUnified, 8);
        }
        const uint32_t per = cfg.cores_per_l3 ? cfg.cores_per_l3 : n;
        for (uint32_t first = 0; first < n; first += per) {
            uint64_t m = 0;
            for (uint32_t i = first; i < std::min(n, first + per); ++i) m |= 1ull << i;
            cache(m, 3, cfg.l3_kib, CacheUnified, 16);
        }
    }
    if (rel == RelationProcessorPackage || all) {
        append_ex(out, RelationProcessorPackage, sizeof(PROCESSOR_RELATIONSHIP), [&](SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX& e) {
            e.Processor.Flags = 0;
            e.Processor.GroupCount = 1;
            e.Processor.GroupMask[0] = gm(reported_mask(n));
        });
    }
    if (rel == RelationGroup || all) {
        append_ex(out, RelationGroup, sizeof(GROUP_RELATIONSHIP), [&](SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX& e) {
            e.Group.MaximumGroupCount = 1;
            e.Group.ActiveGroupCount = 1;
            e.Group.GroupInfo[0].MaximumProcessorCount = static_cast<BYTE>(n);
            e.Group.GroupInfo[0].ActiveProcessorCount = static_cast<BYTE>(n);
            e.Group.GroupInfo[0].ActiveProcessorMask = static_cast<KAFFINITY>(reported_mask(n));
        });
    }
    return out;
}

// ---------------------------------------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------------------------------------
namespace {

void note_remap(const char* api, uint64_t from, uint64_t to) {
    InterlockedIncrement(&g_affinity_remaps);
    if (from != to)
        log_once(std::string("thr:") + api + ":" + std::to_string(from) + ">" + std::to_string(to),
                 "threads: %s %#llx -> %#llx", api, static_cast<unsigned long long>(from), static_cast<unsigned long long>(to));
}

DWORD_PTR WINAPI h_SetThreadAffinityMask(HANDLE thread, DWORD_PTR mask) {
    const uint64_t host = g_map.map_mask(mask);
    note_remap("SetThreadAffinityMask", mask, host);
    if (host == 0) return ::SetThreadAffinityMask(thread, mask);  // all-zero stays an error from Windows
    const DWORD_PTR previous = ::SetThreadAffinityMask(thread, static_cast<DWORD_PTR>(host));
    return previous ? static_cast<DWORD_PTR>(g_map.unmap_mask(previous)) : 0;
}

DWORD WINAPI h_SetThreadIdealProcessor(HANDLE thread, DWORD ideal) {
    if (ideal == MAXIMUM_PROCESSORS) return ::SetThreadIdealProcessor(thread, ideal);
    const DWORD host = g_map.map_core(ideal);
    note_remap("SetThreadIdealProcessor", ideal, host);
    const DWORD prev = ::SetThreadIdealProcessor(thread, host);
    return prev == static_cast<DWORD>(-1) ? prev : (prev == MAXIMUM_PROCESSORS ? prev : g_map.unmap_core(prev));
}

BOOL WINAPI h_SetThreadIdealProcessorEx(HANDLE thread, PPROCESSOR_NUMBER ideal, PPROCESSOR_NUMBER previous) {
    if (!ideal) return ::SetThreadIdealProcessorEx(thread, ideal, previous);
    PROCESSOR_NUMBER mapped = *ideal;
    if (mapped.Group == 0) {
        mapped.Number = static_cast<BYTE>(g_map.map_core(ideal->Number));
        note_remap("SetThreadIdealProcessorEx", ideal->Number, mapped.Number);
    }
    const BOOL ok = ::SetThreadIdealProcessorEx(thread, &mapped, previous);
    if (ok && previous && previous->Group == 0) previous->Number = static_cast<BYTE>(g_map.unmap_core(previous->Number));
    return ok;
}

BOOL WINAPI h_SetProcessAffinityMask(HANDLE process, DWORD_PTR mask) {
    const uint64_t host = g_map.map_mask(mask);
    note_remap("SetProcessAffinityMask", mask, host);
    return ::SetProcessAffinityMask(process, host ? static_cast<DWORD_PTR>(host) : mask);
}

BOOL WINAPI h_GetProcessAffinityMask(HANDLE process, PDWORD_PTR proc, PDWORD_PTR sys) {
    DWORD_PTR p = 0, s = 0;
    if (!::GetProcessAffinityMask(process, &p, &s)) return FALSE;
    const uint64_t cp = g_map.unmap_mask(p);
    const uint64_t cs = g_config.virtual_cores ? reported_mask(g_config.virtual_cores) : g_map.unmap_mask(s);
    if (proc) *proc = static_cast<DWORD_PTR>(cp);
    if (sys) *sys = static_cast<DWORD_PTR>(cs);
    return TRUE;
}

DWORD WINAPI h_GetCurrentProcessorNumber() { return g_map.unmap_core(::GetCurrentProcessorNumber()); }

BOOL WINAPI h_SetThreadPriority(HANDLE thread, int priority) {
    log_once("thrprio:" + std::to_string(priority), "threads: SetThreadPriority %d", priority);
    if (priority == THREAD_PRIORITY_TIME_CRITICAL && g_config.clamp_time_critical) {
        log_once("thrprio:clamp", "threads: THREAD_PRIORITY_TIME_CRITICAL clamped to HIGHEST (threads.clamp_time_critical)");
        priority = THREAD_PRIORITY_HIGHEST;
    }
    return ::SetThreadPriority(thread, priority);
}

void WINAPI h_GetSystemInfo(LPSYSTEM_INFO info) {
    ::GetSystemInfo(info);
    if (info && g_config.virtual_cores) {
        info->dwNumberOfProcessors = g_config.virtual_cores;
        info->dwActiveProcessorMask = static_cast<DWORD_PTR>(reported_mask(g_config.virtual_cores));
        log_once("sysinfo", "threads: GetSystemInfo reports %u processors", g_config.virtual_cores);
    }
}

void WINAPI h_GetNativeSystemInfo(LPSYSTEM_INFO info) {
    ::GetNativeSystemInfo(info);
    if (info && g_config.virtual_cores) {
        info->dwNumberOfProcessors = g_config.virtual_cores;
        info->dwActiveProcessorMask = static_cast<DWORD_PTR>(reported_mask(g_config.virtual_cores));
    }
}

DWORD WINAPI h_GetActiveProcessorCount(WORD group) {
    if (g_config.virtual_cores && (group == 0 || group == ALL_PROCESSOR_GROUPS)) return g_config.virtual_cores;
    return ::GetActiveProcessorCount(group);
}

DWORD WINAPI h_GetMaximumProcessorCount(WORD group) {
    if (g_config.virtual_cores && (group == 0 || group == ALL_PROCESSOR_GROUPS)) return g_config.virtual_cores;
    return ::GetMaximumProcessorCount(group);
}

BOOL WINAPI h_GetLogicalProcessorInformation(PSYSTEM_LOGICAL_PROCESSOR_INFORMATION buffer, PDWORD length) {
    if (!g_config.virtual_cores) return ::GetLogicalProcessorInformation(buffer, length);
    static const auto recs = synth_slpi(g_config);
    const DWORD need = static_cast<DWORD>(recs.size() * sizeof(recs[0]));
    log_once("slpi", "threads: GetLogicalProcessorInformation synthesized (%u cores)", g_config.virtual_cores);
    if (!length) { SetLastError(ERROR_INVALID_PARAMETER); return FALSE; }
    if (!buffer || *length < need) {
        *length = need;
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return FALSE;
    }
    std::memcpy(buffer, recs.data(), need);
    *length = need;
    return TRUE;
}

BOOL WINAPI h_GetLogicalProcessorInformationEx(LOGICAL_PROCESSOR_RELATIONSHIP rel, PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX buffer,
                                               PDWORD length) {
    if (!g_config.virtual_cores) return ::GetLogicalProcessorInformationEx(rel, buffer, length);
    const auto recs = synth_slpi_ex(g_config, rel);
    if (recs.empty()) return ::GetLogicalProcessorInformationEx(rel, buffer, length);
    log_once("slpiex", "threads: GetLogicalProcessorInformationEx synthesized (%u cores)", g_config.virtual_cores);
    if (!length) { SetLastError(ERROR_INVALID_PARAMETER); return FALSE; }
    const DWORD need = static_cast<DWORD>(recs.size());
    if (!buffer || *length < need) {
        *length = need;
        SetLastError(ERROR_INSUFFICIENT_BUFFER);
        return FALSE;
    }
    std::memcpy(buffer, recs.data(), need);
    *length = need;
    return TRUE;
}

BOOL WINAPI h_QueryPerformanceFrequency(LARGE_INTEGER* f) {
    if (!::QueryPerformanceFrequency(f)) return FALSE;
    if (g_config.qpc_frequency && f) f->QuadPart = static_cast<LONGLONG>(g_config.qpc_frequency);
    return TRUE;
}

BOOL WINAPI h_QueryPerformanceCounter(LARGE_INTEGER* c) {
    if (!::QueryPerformanceCounter(c)) return FALSE;
    InterlockedIncrement64(&g_qpc_calls);
    if (g_config.qpc_frequency && c) {
        static const uint64_t host_freq = [] {
            LARGE_INTEGER f{};
            ::QueryPerformanceFrequency(&f);
            return static_cast<uint64_t>(f.QuadPart);
        }();
        c->QuadPart = static_cast<LONGLONG>(mul_div_u64(static_cast<uint64_t>(c->QuadPart), g_config.qpc_frequency, host_freq));
    }
    return TRUE;
}

const HookEntry kHooks[] = {
    {"SetThreadAffinityMask", reinterpret_cast<void*>(&h_SetThreadAffinityMask)},
    {"SetThreadIdealProcessor", reinterpret_cast<void*>(&h_SetThreadIdealProcessor)},
    {"SetThreadIdealProcessorEx", reinterpret_cast<void*>(&h_SetThreadIdealProcessorEx)},
    {"SetProcessAffinityMask", reinterpret_cast<void*>(&h_SetProcessAffinityMask)},
    {"GetProcessAffinityMask", reinterpret_cast<void*>(&h_GetProcessAffinityMask)},
    {"GetCurrentProcessorNumber", reinterpret_cast<void*>(&h_GetCurrentProcessorNumber)},
    {"SetThreadPriority", reinterpret_cast<void*>(&h_SetThreadPriority)},
    {"GetSystemInfo", reinterpret_cast<void*>(&h_GetSystemInfo)},
    {"GetNativeSystemInfo", reinterpret_cast<void*>(&h_GetNativeSystemInfo)},
    {"GetActiveProcessorCount", reinterpret_cast<void*>(&h_GetActiveProcessorCount)},
    {"GetMaximumProcessorCount", reinterpret_cast<void*>(&h_GetMaximumProcessorCount)},
    {"GetLogicalProcessorInformation", reinterpret_cast<void*>(&h_GetLogicalProcessorInformation)},
    {"GetLogicalProcessorInformationEx", reinterpret_cast<void*>(&h_GetLogicalProcessorInformationEx)},
    {"QueryPerformanceFrequency", reinterpret_cast<void*>(&h_QueryPerformanceFrequency)},
    {"QueryPerformanceCounter", reinterpret_cast<void*>(&h_QueryPerformanceCounter)},
};

}  // namespace

const HookEntry* hooks(size_t* count) {
    *count = sizeof kHooks / sizeof kHooks[0];
    return kHooks;
}

}  // namespace x2w_sys::threads
