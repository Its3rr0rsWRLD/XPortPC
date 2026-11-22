// This process's GPU memory in bytes, the value XMemGetWorkingSetStatistics publishes.
// process_bytes() reads DXGI; total() combines the readings without OS calls, so
// tests/xmem_shim_check.cpp can feed it synthetic ones.
#pragma once

#include <algorithm>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace xmem_gpu_usage {

// One DXGI adapter (one LUID).
struct Domain {
    bool queried = false;              // local and non-local CurrentUsage both read
    std::uint64_t bytes = 0;           // their sum
    std::vector<std::wstring> devices; // adapter_identity::physical_devices; empty if unknown
};

namespace detail {
inline bool overlap(const Domain& a, const Domain& b) noexcept
{
    return std::any_of(a.devices.begin(), a.devices.end(), [&](const std::wstring& device) {
        return std::binary_search(b.devices.begin(), b.devices.end(), device);
    });
}

// Whether `domain` is the first view of its devices: false for an alias of an earlier domain,
// nothing when that alias disagrees or the devices partly overlap an earlier domain's.
inline std::optional<bool> first_view(const Domain* begin, const Domain& domain) noexcept
{
    if (domain.devices.empty()) return true;
    for (const Domain* other = begin; other != &domain; ++other) {
        if (other->devices == domain.devices) {
            if (other->bytes != domain.bytes) return std::nullopt;
            return false;
        }
        if (overlap(*other, domain)) return std::nullopt;
    }
    return true;
}
}

// Reads every DXGI adapter (xmem_gpu_usage.cpp) and returns total() of the readings.
std::optional<std::uint64_t> process_bytes() noexcept;

// The process total, or nothing unless it is complete and non-duplicated: LUIDs with the same
// devices count once, distinct devices are summed, and an active adapter of unknown identity is
// accepted only when no other adapter is active. Rules: docs/experiments.md, "Desktop xmem.dll".
inline std::optional<std::uint64_t> total(const std::vector<Domain>& domains, bool enumeration_complete) noexcept
{
    const auto failed = [](const Domain& domain) { return !domain.queried; };
    if (!enumeration_complete || domains.empty() || std::any_of(domains.begin(), domains.end(), failed)) {
        return std::nullopt;
    }
    std::uint64_t sum = 0;
    std::size_t active = 0;
    bool unknown_active = false;
    for (const auto& domain : domains) {
        const auto first = detail::first_view(domains.data(), domain);
        if (!first) return std::nullopt;
        if (!*first || domain.bytes == 0) continue;
        if (domain.bytes > UINT64_MAX - sum) return std::nullopt;
        sum += domain.bytes;
        ++active;
        unknown_active |= domain.devices.empty();
    }
    // An adapter of unknown identity may be a second view of any other active one.
    if (unknown_active && active > 1) return std::nullopt;
    return sum;
}

}
