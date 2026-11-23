#include "era_title_gpu.h"

#include "era_query.h"

#include <atomic>
#include <exception>
#include <iterator>
#include <map>
#include <mutex>
#include <new>
#include <type_traits>
#include <utility>

namespace era_title_gpu {
namespace {
struct Backing {
    void* base = nullptr;      // address backing: the allocation; section backing: null
    HANDLE section = nullptr;  // section backing: the mapping handle
    std::size_t bytes = 0;
    bool standalone = false;   // created by track(); dropped with its one range
    era_gpu_alias::Alias alias;
};

struct Range {
    std::size_t bytes;
    std::size_t extent;    // bytes of the backing the allocation owns (>= bytes)
    std::uintptr_t backing;
    std::uint64_t offset;  // byte offset of the range's first byte in the backing (and in its alias buffer)
};

struct State {
    std::mutex lock;  // guards everything below; taken before the table's own lock
    std::map<std::uintptr_t, Backing> backings;
    std::map<std::uintptr_t, Range> ranges;
    Microsoft::WRL::ComPtr<ID3D12Device> device;
    era_title_va::Table table;
};

// Created by the first add or attach and never destroyed: releasing D3D12 objects while the
// process or DLL is unloading is not safe. The pointer is constant-initialized and trivially
// destructible, so loading and unloading the module run no code for it.
std::atomic<State*> registry{nullptr};
static_assert(std::is_trivially_destructible_v<std::atomic<State*>>);

State* existing() noexcept
{
    return registry.load(std::memory_order_acquire);
}

// The registry, created on first use. Returns null when it cannot be allocated; nothing has been
// registered then, and a later call can retry.
State* created() noexcept
{
    if (State* s = existing()) {
        return s;
    }
    State* fresh = nullptr;
    try {
        fresh = new State;  // the std::map members can allocate in their constructors too
    } catch (const std::bad_alloc&) {
        return nullptr;
    }
    State* published = nullptr;
    if (!registry.compare_exchange_strong(published, fresh, std::memory_order_acq_rel,
                                          std::memory_order_acquire)) {
        delete fresh;  // another thread published first; this one never held a device
        return published;
    }
    return fresh;
}

bool wraps(std::uintptr_t base, std::size_t bytes) noexcept
{
    return bytes == 0 || base + bytes < base;
}

// Adds the table entry of a range whose backing is aliased.
bool map_range(State& s, std::uintptr_t base, const Range& range, const Backing& backing) noexcept
{
    return s.table.add(base, range.bytes, backing.alias.buffer->GetGPUVirtualAddress() + range.offset);
}

HRESULT alias(State& s, std::uintptr_t key, Backing& backing) noexcept
{
    const HRESULT hr = backing.section
                           ? era_gpu_alias::open_mapping(s.device.Get(), backing.section, backing.bytes, backing.alias)
                           : era_gpu_alias::open(s.device.Get(), backing.base, backing.bytes, backing.alias);
    if (FAILED(hr)) {
        backing.alias = {};
        return hr;
    }
    for (const auto& [base, range] : s.ranges) {
        if (range.backing == key && !map_range(s, base, range, backing)) {
            for (const auto& [mapped, r] : s.ranges) {
                if (r.backing == key) s.table.remove(mapped);
            }
            backing.alias = {};
            return E_FAIL;
        }
    }
    return S_OK;
}

void unalias(State& s, std::uintptr_t key, Backing& backing) noexcept
{
    if (!backing.alias.buffer) {
        return;
    }
    for (const auto& [base, range] : s.ranges) {
        if (range.backing == key) s.table.remove(base);
    }
    backing.alias = {};
}

bool overlaps_backing(const State& s, std::uintptr_t base, std::size_t bytes) noexcept
{
    for (const auto& [key, backing] : s.backings) {
        if (!backing.base) continue;
        const auto begin = reinterpret_cast<std::uintptr_t>(backing.base);
        if (base < begin + backing.bytes && begin < base + bytes) return true;
    }
    return false;
}

// Registers a range. The caller holds the lock. Nothing is left registered on failure.
bool insert_range(State& s, std::uintptr_t base, std::size_t bytes, std::uintptr_t key, std::uint64_t offset,
                  std::size_t extent)
{
    if (extent < bytes) {
        extent = bytes;
    }
    auto backing = s.backings.find(key);
    if (backing == s.backings.end() || wraps(base, bytes) || offset > backing->second.bytes ||
        bytes > backing->second.bytes - offset) {
        return false;
    }
    if (backing->second.base && reinterpret_cast<std::uintptr_t>(backing->second.base) + offset != base) {
        return false;
    }
    if (!era_query::register_gpu_region(reinterpret_cast<void*>(base), bytes)) {
        return false;  // overlapping
    }
    try {
        auto [entry, inserted] = s.ranges.emplace(base, Range{bytes, extent, key, offset});
        if (!inserted) {
            era_query::unregister_gpu_region(reinterpret_cast<void*>(base));
            return false;
        }
        if (backing->second.alias.buffer && !map_range(s, base, entry->second, backing->second)) {
            s.ranges.erase(entry);
            era_query::unregister_gpu_region(reinterpret_cast<void*>(base));
            return false;
        }
    } catch (const std::bad_alloc&) {
        era_query::unregister_gpu_region(reinterpret_cast<void*>(base));
        return false;
    }
    return true;
}

void erase_range(State& s, std::map<std::uintptr_t, Range>::iterator range) noexcept
{
    const std::uintptr_t base = range->first;
    auto backing = s.backings.find(range->second.backing);
    if (backing != s.backings.end() && backing->second.alias.buffer) {
        s.table.remove(base);
    }
    s.ranges.erase(range);
    era_query::unregister_gpu_region(reinterpret_cast<void*>(base));
}

// The range of an aliased backing holding [address, address + bytes), or ranges.end().
std::map<std::uintptr_t, Range>::iterator find(State& s, std::uint64_t address, std::uint64_t bytes)
{
    if (bytes == 0) {
        bytes = 1;
    }
    auto next = s.ranges.upper_bound(static_cast<std::uintptr_t>(address));
    if (next == s.ranges.begin()) {
        return s.ranges.end();
    }
    auto range = std::prev(next);
    const std::uint64_t offset = address - range->first;
    if (offset >= range->second.bytes || bytes > range->second.bytes - offset) {
        return s.ranges.end();
    }
    auto backing = s.backings.find(range->second.backing);
    if (backing == s.backings.end() || !backing->second.alias.buffer) {
        return s.ranges.end();
    }
    return range;
}

bool add(std::uintptr_t key, Backing backing) noexcept
{
    State* const registry_state = created();
    if (!registry_state) {
        return false;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    if (backing.base && overlaps_backing(s, key, backing.bytes)) {
        return false;
    }
    try {
        auto [entry, inserted] = s.backings.emplace(key, std::move(backing));
        if (!inserted) {
            return false;
        }
        if (s.device) {
            alias(s, key, entry->second);  // a failure leaves the backing unaliased
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}
}

bool track(void* base, std::size_t bytes) noexcept
{
    const auto key = reinterpret_cast<std::uintptr_t>(base);
    if (!base || wraps(key, bytes)) {
        return false;
    }
    State* const registry_state = created();
    if (!registry_state) {
        return false;  // allocation failure before anything was registered
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    if (overlaps_backing(s, key, bytes) || s.backings.count(key)) {
        return false;
    }
    try {
        Backing backing;
        backing.base = base;
        backing.bytes = bytes;
        backing.standalone = true;
        auto [entry, inserted] = s.backings.emplace(key, std::move(backing));
        if (!inserted) {
            return false;
        }
        if (!insert_range(s, key, bytes, key, 0, bytes)) {
            s.backings.erase(entry);
            return false;  // empty, wrapping or overlapping a range, or allocation failure
        }
        if (s.device) {
            alias(s, key, entry->second);  // a failure leaves the allocation tracked, unaliased
        }
    } catch (const std::bad_alloc&) {
        auto range = s.ranges.find(key);
        if (range != s.ranges.end()) erase_range(s, range);
        s.backings.erase(key);
        return false;
    }
    return true;
}

bool untrack(void* base) noexcept
{
    State* const registry_state = existing();
    if (!registry_state) {
        return false;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    auto range = s.ranges.find(reinterpret_cast<std::uintptr_t>(base));
    if (range == s.ranges.end()) {
        return false;
    }
    const std::uintptr_t key = range->second.backing;
    erase_range(s, range);
    auto backing = s.backings.find(key);
    if (backing != s.backings.end() && backing->second.standalone) {
        backing->second.alias = {};
        s.backings.erase(backing);
    }
    return true;
}

bool add_backing(void* base, std::size_t bytes) noexcept
{
    const auto key = reinterpret_cast<std::uintptr_t>(base);
    if (!base || wraps(key, bytes)) {
        return false;
    }
    Backing backing;
    backing.base = base;
    backing.bytes = bytes;
    return add(key, std::move(backing));
}

bool add_section_backing(std::uintptr_t key, HANDLE section, std::size_t bytes) noexcept
{
    if (!section || bytes == 0) {
        return false;
    }
    Backing backing;
    backing.section = section;
    backing.bytes = bytes;
    return add(key, std::move(backing));
}

bool remove_backing(std::uintptr_t key) noexcept
{
    State* const registry_state = existing();
    if (!registry_state) {
        return false;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    auto backing = s.backings.find(key);
    if (backing == s.backings.end()) {
        return false;
    }
    for (auto range = s.ranges.begin(); range != s.ranges.end();) {
        auto next = std::next(range);
        if (range->second.backing == key) erase_range(s, range);
        range = next;
    }
    backing->second.alias = {};
    s.backings.erase(backing);
    return true;
}

bool add_range(void* base, std::size_t bytes, std::uintptr_t backing, std::uint64_t offset, std::size_t extent) noexcept
{
    if (!base) {
        return false;
    }
    State* const registry_state = existing();
    if (!registry_state) {
        return false;  // no backing exists yet
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    try {
        return insert_range(s, reinterpret_cast<std::uintptr_t>(base), bytes, backing, offset, extent);
    } catch (const std::bad_alloc&) {
        return false;
    }
}

bool remove_range(void* base) noexcept
{
    State* const registry_state = existing();
    if (!registry_state) {
        return false;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    auto range = s.ranges.find(reinterpret_cast<std::uintptr_t>(base));
    if (range == s.ranges.end()) {
        return false;
    }
    erase_range(s, range);
    return true;
}

HRESULT attach(ID3D12Device* device) noexcept
{
    if (!device) {
        return E_INVALIDARG;
    }
    D3D12_FEATURE_DATA_EXISTING_HEAPS existing_heaps{};
    if (FAILED(device->CheckFeatureSupport(D3D12_FEATURE_EXISTING_HEAPS, &existing_heaps, sizeof(existing_heaps))) ||
        !existing_heaps.Supported) {
        return E_NOTIMPL;
    }
    State* const registry_state = created();
    if (!registry_state) {
        return E_OUTOFMEMORY;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    if (s.device.Get() != device) {
        for (auto& [key, backing] : s.backings) {
            unalias(s, key, backing);
        }
        s.device = device;
    }
    HRESULT first = S_OK;
    for (auto& [key, backing] : s.backings) {
        if (backing.alias.buffer) {
            continue;
        }
        const HRESULT hr = alias(s, key, backing);
        if (FAILED(hr) && SUCCEEDED(first)) {
            first = hr;
        }
    }
    return first;
}

void detach() noexcept
{
    State* const registry_state = existing();
    if (!registry_state) {
        return;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    for (auto& [key, backing] : s.backings) {
        unalias(s, key, backing);
    }
    s.device.Reset();
}

std::uint64_t translate(std::uint64_t title_address, std::uint64_t bytes) noexcept
{
    const State* const registry_state = existing();
    return registry_state ? registry_state->table.translate(title_address, bytes) : 0;
}

bool locate(std::uint64_t title_address, std::uint64_t bytes, ID3D12Resource** buffer,
            std::uint64_t* offset) noexcept
{
    State* const registry_state = existing();
    if (!buffer || !offset || !registry_state) {
        return false;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    auto range = find(s, title_address, bytes);
    if (range == s.ranges.end()) {
        return false;
    }
    *offset = title_address - range->first + range->second.offset;
    s.backings.at(range->second.backing).alias.buffer.CopyTo(buffer);
    return true;
}

bool shader_view(ShaderView& view) noexcept
{
    State* const registry_state = existing();
    if (!registry_state) {
        // No registry, so no aliased allocations. clear() allocates nothing; even an empty vector's
        // constructor allocates with the debug STL's iterator checks.
        view.ranges.clear();
        view.resources.clear();
        view.unpackable = 0;
        return true;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    try {
        ShaderView result;
        std::map<std::uintptr_t, std::uint32_t> slots;  // backing key -> slot
        struct Pending {
            std::uint64_t begin, end, extent_end, base;
            std::uintptr_t backing;
        };
        bool open = false;
        Pending pending{};
        const auto flush = [&]() {
            if (!open) return;
            open = false;
            const std::uint64_t size = pending.end - pending.begin;
            if (size >= (std::uint64_t{1} << 32) || (pending.begin & 3) || (pending.base & 3) ||
                pending.base + size > (std::uint64_t{1} << 32)) {
                ++result.unpackable;
                return;
            }
            auto [slot, fresh] = slots.emplace(pending.backing, static_cast<std::uint32_t>(result.resources.size()));
            if (fresh) result.resources.push_back(s.backings.at(pending.backing).alias.buffer);
            era_title_va::ShaderRange packed{};
            packed.begin_low = static_cast<std::uint32_t>(pending.begin);
            packed.begin_high = static_cast<std::uint32_t>(pending.begin >> 32);
            packed.end_low = static_cast<std::uint32_t>(pending.end);
            packed.end_high = static_cast<std::uint32_t>(pending.end >> 32);
            packed.slot = slot->second;
            packed.base = static_cast<std::uint32_t>(pending.base);
            result.ranges.push_back(packed);
        };
        for (const auto& [base, range] : s.ranges) {
            const Backing& backing = s.backings.at(range.backing);
            if (!backing.alias.buffer) {
                continue;
            }
            const std::uint64_t begin = base, end = base + range.bytes;
            if (open && pending.backing == range.backing && pending.extent_end == begin &&
                pending.base + (begin - pending.begin) == range.offset) {
                pending.end = end;
                pending.extent_end = begin + range.extent;
                continue;
            }
            flush();
            pending = {begin, end, begin + range.extent, range.offset, range.backing};
            open = true;
        }
        flush();
        view = std::move(result);
    } catch (const std::exception&) {
        return false;
    }
    return true;
}

Counts counts() noexcept
{
    State* const registry_state = existing();
    if (!registry_state) {
        return {0, 0, 0, 0};
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    Counts result{s.ranges.size(), 0, s.backings.size(), 0};
    for (const auto& [base, range] : s.ranges) {
        result.aliased += s.backings.at(range.backing).alias.buffer ? 1 : 0;
    }
    for (const auto& [key, backing] : s.backings) {
        result.aliased_backings += backing.alias.buffer ? 1 : 0;
    }
    return result;
}
}
