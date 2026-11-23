#include "sys_dstorage.h"

#include "sys_common.h"
#include "sys_paths.h"

#include <map>

namespace x2w_sys::ds {
namespace {
std::mutex g_mutex;
HMODULE g_module = nullptr;
GetFactoryFn g_get_factory = nullptr;
bool g_resolved = false;
std::string g_override;
Stats g_stats;
std::map<uint32_t, Decompressor> g_decoders;
Resolver g_resolver;

bool read_exact(HANDLE file, uint64_t offset, void* buf, uint32_t size) {
    uint8_t* p = static_cast<uint8_t*>(buf);
    uint32_t done = 0;
    while (done < size) {
        OVERLAPPED ov{};
        const uint64_t at = offset + done;
        ov.Offset = static_cast<DWORD>(at);
        ov.OffsetHigh = static_cast<DWORD>(at >> 32);
        DWORD got = 0;
        if (!ReadFile(file, p + done, size - done, &got, &ov) || got == 0) return false;
        done += got;
    }
    return true;
}
}  // namespace

Stats& stats() { return g_stats; }

void register_decompressor(uint32_t format, Decompressor fn) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_decoders[format] = std::move(fn);
}

void set_resolver(Resolver fn) {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_resolver = std::move(fn);
}

void* default_resolve(uint64_t address, uint64_t size) {
    if (!address || !size) return nullptr;
    uint64_t at = address;
    const uint64_t end = address + size;
    while (at < end) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (!VirtualQuery(reinterpret_cast<void*>(static_cast<uintptr_t>(at)), &mbi, sizeof mbi)) return nullptr;
        constexpr DWORD writable = PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
        if (mbi.State != MEM_COMMIT || !(mbi.Protect & writable) || (mbi.Protect & PAGE_GUARD)) return nullptr;
        at = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    }
    return reinterpret_cast<void*>(static_cast<uintptr_t>(address));
}

Result run_request(const Request& r) {
    Result res;
    res.user = r.user;
    ++g_stats.requests;
    auto fail = [&](HRESULT hr) {
        res.hr = hr;
        ++g_stats.failed;
        return res;
    };
    // Destination.
    const uint32_t out_size = r.compression == kNone ? r.size : r.uncompressed_size;
    void* dest = r.dest_memory;
    if (!dest) {
        Resolver resolver;
        { std::lock_guard<std::mutex> lock(g_mutex); resolver = g_resolver; }
        dest = resolver ? resolver(r.dest_title_address, out_size) : default_resolve(r.dest_title_address, out_size);
    }
    if (!dest) {
        log_once("ds:baddest", "directstorage: fallback request destination did not resolve (title address %#llx, %u bytes)",
                 static_cast<unsigned long long>(r.dest_title_address), out_size);
        return fail(X2W_E_DS_BAD_DESTINATION);
    }
    // Decoder, before touching the file.
    Decompressor decoder;
    if (r.compression != kNone) {
        std::lock_guard<std::mutex> lock(g_mutex);
        auto it = g_decoders.find(r.compression);
        if (it != g_decoders.end()) decoder = it->second;
        if (!decoder) {
            ++g_stats.unsupported;
            log_once("ds:codec:" + std::to_string(r.compression),
                     "directstorage: compression format %u has no decoder registered (GDeflate CPU decode is not built in)",
                     r.compression);
            return fail(X2W_E_DS_UNSUPPORTED_COMPRESSION);
        }
    }
    // File, through the path map.
    const paths::Result mapped = paths::global_map().remap(r.path);
    if (mapped.remapped)
        log_once("ds:path:" + narrow(mapped.path), "directstorage: path remap %s -> %s", narrow(r.path).c_str(), narrow(mapped.path).c_str());
    HANDLE file = CreateFileW(mapped.path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file == INVALID_HANDLE_VALUE) return fail(HRESULT_FROM_WIN32(GetLastError()));
    bool ok;
    if (r.compression == kNone) {
        ok = read_exact(file, r.offset, dest, r.size);
        if (ok) { res.bytes = r.size; g_stats.bytes_read += r.size; g_stats.bytes_out += r.size; }
    } else {
        std::vector<uint8_t> staging(r.size);
        ok = read_exact(file, r.offset, staging.data(), r.size);
        if (ok) {
            g_stats.bytes_read += r.size;
            ok = decoder(staging.data(), staging.size(), dest, r.uncompressed_size);
            if (ok) { res.bytes = r.uncompressed_size; g_stats.bytes_out += r.uncompressed_size; }
            else { CloseHandle(file); return fail(E_FAIL); }
        }
    }
    const DWORD err = GetLastError();
    CloseHandle(file);
    if (!ok) return fail(HRESULT_FROM_WIN32(err ? err : ERROR_READ_FAULT));
    return res;
}

Queue::Queue() : thread_([this] { worker(); }) {}

Queue::~Queue() {
    {
        std::lock_guard<std::mutex> lock(m_);
        stop_ = true;
    }
    cv_.notify_all();
    thread_.join();
}

void Queue::enqueue(const Request& r) {
    {
        std::lock_guard<std::mutex> lock(m_);
        pending_.push_back(r);
        ++outstanding_;
    }
    cv_.notify_one();
}

std::vector<Result> Queue::submit_and_wait() {
    std::unique_lock<std::mutex> lock(m_);
    done_cv_.wait(lock, [this] { return outstanding_ == 0; });
    std::vector<Result> out;
    out.swap(results_);
    return out;
}

void Queue::worker() {
    for (;;) {
        Request r;
        {
            std::unique_lock<std::mutex> lock(m_);
            cv_.wait(lock, [this] { return stop_ || !pending_.empty(); });
            if (pending_.empty()) return;
            r = std::move(pending_.front());
            pending_.pop_front();
        }
        const Result res = run_request(r);
        {
            std::lock_guard<std::mutex> lock(m_);
            results_.push_back(res);
            --outstanding_;
        }
        done_cv_.notify_all();
    }
}

GetFactoryFn resolve_get_factory(const char* override_dll) {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_resolved) return g_get_factory;
    g_resolved = true;
    std::string first = override_dll ? override_dll : (g_override.empty() ? get_env("X2W_DSTORAGE_DLL") : g_override);
    if (first == "off") {
        log("directstorage: runtime disabled by configuration; using the ReadFile fallback");
        return nullptr;
    }
    std::vector<std::wstring> names;
    if (!first.empty()) names.push_back(widen(first));
    names.push_back(L"dstorage.dll");
    for (const auto& n : names) {
        HMODULE m = LoadLibraryExW(n.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!m) continue;
        auto fn = reinterpret_cast<GetFactoryFn>(GetProcAddress(m, "DStorageGetFactory"));
        if (!fn) { FreeLibrary(m); continue; }
        g_module = m;
        g_get_factory = fn;
        log("directstorage: forwarding DStorageGetFactory to %s", narrow(n).c_str());
        return fn;
    }
    log("directstorage: dstorage.dll not found; using the ReadFile fallback");
    return nullptr;
}

void reset_for_test() {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_module) FreeLibrary(g_module);
    g_module = nullptr;
    g_get_factory = nullptr;
    g_resolved = false;
    g_stats = {};
    g_decoders.clear();
    g_resolver = nullptr;
}

void apply_config_line(const std::string& key, const std::string& value) {
    if (key == "directstorage.dll") g_override = value;
}

}  // namespace x2w_sys::ds

extern "C" {
HRESULT WINAPI X2wDStorageGetFactory(REFIID iid, void** out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    auto fn = x2w_sys::ds::resolve_get_factory();
    if (fn) return fn(iid, out);
    x2w_sys::log_once("ds:factory", "directstorage: DStorageGetFactory has no runtime to forward to; returning the fallback status");
    return x2w_sys::ds::X2W_E_DSTORAGE_FALLBACK;
}
}
