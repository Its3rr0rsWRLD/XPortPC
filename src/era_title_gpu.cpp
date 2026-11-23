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
struct Entry {
    std::size_t bytes;
    era_gpu_alias::Alias alias;
    // A desktop buffer the D3D12 layer registered at a title address (register_resource): no XMem memory and no
    // alias; `external` holds the buffer for the whole range.
    Microsoft::WRL::ComPtr<ID3D12Resource> external;
    bool shader = true;  // packed for TitleLookup (shader_view)
};

ID3D12Resource* buffer_of(const Entry& entry) noexcept
{
    return entry.external ? entry.external.Get() : entry.alias.buffer.Get();
}

struct State {
    std::mutex lock;  // guards entries and device; taken before the table's own lock
    std::map<std::uintptr_t, Entry> entries;
    Microsoft::WRL::ComPtr<ID3D12Device> device;
    era_title_va::Table table;
};

// Created by the first track or attach and never destroyed: releasing D3D12 objects while the
// process or DLL is unloading is not safe. The pointer is constant-initialized and trivially
// destructible, so loading and unloading the module run no code for it.
std::atomic<State*> registry{nullptr};
static_assert(std::is_trivially_destructible_v<std::atomic<State*>>);

// The registry if it exists. The other entry points never create it, and without it they behave
// as for an empty registry.
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

HRESULT alias(State& s, std::uintptr_t base, Entry& entry) noexcept
{
    HRESULT hr = era_gpu_alias::open(s.device.Get(), reinterpret_cast<void*>(base), entry.bytes, entry.alias);
    if (FAILED(hr)) {
        entry.alias = {};
        return hr;
    }
    if (!s.table.add(base, entry.bytes, entry.alias.buffer->GetGPUVirtualAddress())) {
        entry.alias = {};
        return E_FAIL;
    }
    return S_OK;
}

void unalias(State& s, std::uintptr_t base, Entry& entry) noexcept
{
    if (entry.alias.buffer) {
        s.table.remove(base);
        entry.alias = {};
    }
}

// The aliased entry holding [address, address + bytes), or entries.end().
std::map<std::uintptr_t, Entry>::iterator find(State& s, std::uint64_t address, std::uint64_t bytes)
{
    if (bytes == 0) {
        bytes = 1;
    }
    auto next = s.entries.upper_bound(static_cast<std::uintptr_t>(address));
    if (next == s.entries.begin()) {
        return s.entries.end();
    }
    auto entry = std::prev(next);
    const std::uint64_t offset = address - entry->first;
    if (!buffer_of(entry->second) || offset >= entry->second.bytes || bytes > entry->second.bytes - offset) {
        return s.entries.end();
    }
    return entry;
}
}

bool track(void* base, std::size_t bytes) noexcept
{
    if (!base || bytes == 0) {
        return false;
    }
    State* const registry_state = created();
    if (!registry_state) {
        return false;  // allocation failure before anything was registered
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    if (!era_query::register_gpu_region(base, bytes)) {
        return false;  // empty, wrapping or overlapping
    }
    const auto key = reinterpret_cast<std::uintptr_t>(base);
    try {
        auto [entry, inserted] = s.entries.emplace(key, Entry{bytes, {}});
        if (!inserted) {
            era_query::unregister_gpu_region(base);
            return false;
        }
        if (s.device) {
            alias(s, key, entry->second);  // a failure leaves the allocation tracked, unaliased
        }
    } catch (const std::bad_alloc&) {
        era_query::unregister_gpu_region(base);
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
    auto entry = s.entries.find(reinterpret_cast<std::uintptr_t>(base));
    if (entry == s.entries.end() || entry->second.external) {
        return false;
    }
    unalias(s, entry->first, entry->second);
    s.entries.erase(entry);
    era_query::unregister_gpu_region(base);
    return true;
}

HRESULT attach(ID3D12Device* device) noexcept
{
    if (!device) {
        return E_INVALIDARG;
    }
    D3D12_FEATURE_DATA_EXISTING_HEAPS existing{};
    if (FAILED(device->CheckFeatureSupport(D3D12_FEATURE_EXISTING_HEAPS, &existing, sizeof(existing))) ||
        !existing.Supported) {
        return E_NOTIMPL;
    }
    State* const registry_state = created();
    if (!registry_state) {
        return E_OUTOFMEMORY;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    if (s.device.Get() != device) {
        for (auto& [base, entry] : s.entries) {
            unalias(s, base, entry);
        }
        s.device = device;
    }
    HRESULT first = S_OK;
    for (auto& [base, entry] : s.entries) {
        if (entry.alias.buffer || entry.external) {
            continue;
        }
        const HRESULT hr = alias(s, base, entry);
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
    for (auto& [base, entry] : s.entries) {
        unalias(s, base, entry);
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
    auto entry = find(s, title_address, bytes);
    if (entry == s.entries.end()) {
        return false;
    }
    *offset = title_address - entry->first;
    *buffer = buffer_of(entry->second);
    (*buffer)->AddRef();
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
        return true;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    try {
        ShaderView result;
        std::vector<era_title_va::Range> ranges;
        for (const auto& range : s.table.ranges()) {
            if (s.entries.at(static_cast<std::uintptr_t>(range.title_begin)).shader) {
                ranges.push_back(range);
            }
        }
        if (!era_title_va::shader_ranges(ranges, result.ranges)) {
            return false;
        }
        result.resources.reserve(ranges.size());
        for (const auto& range : ranges) {
            result.resources.push_back(buffer_of(s.entries.at(static_cast<std::uintptr_t>(range.title_begin))));
        }
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
        return {0, 0};
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    Counts result{0, 0, 0};
    for (const auto& [base, entry] : s.entries) {
        if (entry.external) {
            ++result.external;
            continue;
        }
        ++result.tracked;
        result.aliased += entry.alias.buffer ? 1 : 0;
    }
    return result;
}

bool register_resource(std::uint64_t title_address, std::uint64_t bytes, ID3D12Resource* buffer,
                       bool shader) noexcept
{
    if (!title_address || !bytes || !buffer || title_address + bytes < title_address) {
        return false;
    }
    const D3D12_GPU_VIRTUAL_ADDRESS gpu = buffer->GetGPUVirtualAddress();
    if (!gpu) {
        return false;
    }
    State* const registry_state = created();
    if (!registry_state) {
        return false;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    const auto key = static_cast<std::uintptr_t>(title_address);
    // No overlap with a tracked allocation or another registered buffer.
    auto next = s.entries.lower_bound(key);
    if (next != s.entries.end() && next->first < title_address + bytes) {
        return false;
    }
    if (next != s.entries.begin()) {
        auto before = std::prev(next);
        if (before->first + before->second.bytes > title_address) {
            return false;
        }
    }
    try {
        Entry entry{static_cast<std::size_t>(bytes), {}, buffer, shader};
        auto [at, inserted] = s.entries.emplace(key, std::move(entry));
        if (!inserted) {
            return false;
        }
        if (!s.table.add(title_address, bytes, gpu)) {
            s.entries.erase(at);
            return false;
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}

bool unregister_resource(std::uint64_t title_address) noexcept
{
    State* const registry_state = existing();
    if (!registry_state) {
        return false;
    }
    State& s = *registry_state;
    std::lock_guard<std::mutex> guard(s.lock);
    auto entry = s.entries.find(static_cast<std::uintptr_t>(title_address));
    if (entry == s.entries.end() || !entry->second.external) {
        return false;
    }
    s.table.remove(entry->first);
    s.entries.erase(entry);
    return true;
}

bool translations(std::vector<era_title_va::Range>& out) noexcept
{
    State* const registry_state = existing();
    out.clear();
    if (!registry_state) {
        return true;
    }
    try {
        out = registry_state->table.ranges();
    } catch (const std::exception&) {
        return false;
    }
    return true;
}
}
