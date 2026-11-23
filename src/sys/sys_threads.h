// Threading and timing: console core numbering mapped onto host logical CPUs, a console-like reported topology,
// and a QueryPerformanceCounter that stays consistent with the frequency it reports.
//
// The console CPU is an 8 core part (docs/design/runtime.md, section 5). Titles pin threads with core numbers
// 0..7. On a host with fewer or more logical CPUs, or with SMT, those numbers are mapped through an ordered list of
// host CPUs: one logical CPU per physical core first, then SMT siblings, so distinct console cores land on
// distinct physical cores where the host has them.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

namespace x2w_sys::threads {

class CoreMap {
public:
    // host_cpus: ordered host logical CPU indices (each < 64). Console core c maps to host_cpus[c % size].
    void configure(std::vector<uint32_t> host_cpus, uint32_t console_cores);
    uint32_t console_cores() const { return console_cores_; }
    uint32_t host_count() const { return static_cast<uint32_t>(host_.size()); }
    uint32_t map_core(uint32_t console_core) const;
    // Host CPU -> the lowest console core mapped onto it (the host number itself if none maps there).
    uint32_t unmap_core(uint32_t host_cpu) const;
    // Every set console bit (below console_cores; higher bits are folded modulo) becomes the host bit.
    uint64_t map_mask(uint64_t console_mask) const;
    // Console bit c is set when the host CPU that core c maps to is in host_mask.
    uint64_t unmap_mask(uint64_t host_mask) const;

private:
    std::vector<uint32_t> host_;
    uint32_t console_cores_ = 8;
};

// Orders `allowed_mask` (the process affinity) with one logical CPU per physical core first. `core_masks` holds
// one mask per physical core (from GetLogicalProcessorInformationEx), may be empty (then plain bit order).
std::vector<uint32_t> order_host_cpus(uint64_t allowed_mask, const std::vector<uint64_t>& core_masks);

struct Config {
    uint32_t console_cores = 8;     // numbering used by the title
    uint32_t virtual_cores = 0;     // 0: report the host topology; else report this many cores
    bool clamp_time_critical = false;
    uint64_t qpc_frequency = 0;     // 0: host frequency
    uint32_t l1_kib = 32, l2_kib = 512, l3_kib = 4096;  // reported cache sizes (configured, not measured)
    uint32_t cores_per_l3 = 4;
};

Config& config();
CoreMap& core_map();
// Build the core map from the host (process affinity + topology). Call after changing config().
void init_from_host();
void apply_config_line(const std::string& key, const std::string& value);
void log_summary();

// Synthetic topology, exposed for tests.
std::vector<SYSTEM_LOGICAL_PROCESSOR_INFORMATION> synth_slpi(const Config& cfg);
// Serialized records for GetLogicalProcessorInformationEx(relationship). Empty for unsupported relationships.
std::vector<uint8_t> synth_slpi_ex(const Config& cfg, LOGICAL_PROCESSOR_RELATIONSHIP rel);

struct HookEntry {
    const char* symbol;
    void* replacement;
};
const HookEntry* hooks(size_t* count);

}  // namespace x2w_sys::threads
