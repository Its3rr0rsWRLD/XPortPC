#include "sys_dstorage.h"

#include "sys_common.h"
#include "sys_gdeflate.h"
#include "sys_paths.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <utility>

#include "libdeflate.h"

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

// Every file handle of ours is opened overlapped (open_ours): Windows serializes synchronous I/O on one file object, so
// a synchronous read of ours could hold up anyone else using the handle (the console GetHandle slot gives it to the
// title), and theirs ours. Each read has its own event and offset and is waited for here.
bool read_exact(HANDLE file, uint64_t offset, void* buf, uint32_t size) {
    uint8_t* p = static_cast<uint8_t*>(buf);
    uint32_t done = 0;
    HANDLE event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!event) return false;
    bool ok = true;
    while (done < size) {
        OVERLAPPED ov{};
        const uint64_t at = offset + done;
        ov.Offset = static_cast<DWORD>(at);
        ov.OffsetHigh = static_cast<DWORD>(at >> 32);
        ov.hEvent = event;
        ResetEvent(event);
        DWORD got = 0;
        if (!ReadFile(file, p + done, size - done, nullptr, &ov) && GetLastError() != ERROR_IO_PENDING) { ok = false; break; }
        if (!GetOverlappedResult(file, &ov, &got, TRUE) || got == 0) { ok = false; break; }
        done += got;
    }
    CloseHandle(event);
    return ok;
}

// Read-only, overlapped, sharing everything: the title may hold the same archive open with any share mode.
HANDLE open_ours(const std::wstring& path, DWORD extra_flags) {
    return CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                       OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED | extra_flags, nullptr);
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
                     "directstorage: compression format %u has no decoder registered (X2WSysInit registers GDeflate, format 1)",
                     r.compression);
            return fail(X2W_E_DS_UNSUPPORTED_COMPRESSION);
        }
    }
    // File, through the path map.
    const paths::Result mapped = paths::global_map().remap(r.path);
    if (mapped.remapped)
        log_once("ds:path:" + narrow(mapped.path), "directstorage: path remap %s -> %s", narrow(r.path).c_str(), narrow(mapped.path).c_str());
    HANDLE file = open_ours(mapped.path, FILE_FLAG_SEQUENTIAL_SCAN);
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

// ===============================================================================================================
// Our own DirectStorage (sys_dstorage.h, "Our own DirectStorage").
// ===============================================================================================================
namespace x2w_sys::ds {
namespace {

using U = uintptr_t;
constexpr int kSlots = 64;

std::string hex_args(U a1, U a2, U a3, U a4) {
    char b[160];
    std::snprintf(b, sizeof b, "%#llx %#llx %#llx %#llx", static_cast<unsigned long long>(a1),
                  static_cast<unsigned long long>(a2), static_cast<unsigned long long>(a3), static_cast<unsigned long long>(a4));
    return b;
}

// True when [p, p+n) is committed and readable (write: writable) memory of this process.
bool mem_ok(const void* p, size_t n, bool write) {
    uintptr_t at = reinterpret_cast<uintptr_t>(p);
    if (at < 0x10000 || n == 0) return false;
    const uintptr_t end = at + n;
    if (end < at) return false;
    constexpr DWORD w = PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    constexpr DWORD r = w | PAGE_READONLY | PAGE_EXECUTE_READ;
    while (at < end) {
        MEMORY_BASIC_INFORMATION mbi{};
        if (!VirtualQuery(reinterpret_cast<void*>(at), &mbi, sizeof mbi)) return false;
        if (mbi.State != MEM_COMMIT || (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS)) || !(mbi.Protect & (write ? w : r)))
            return false;
        at = reinterpret_cast<uintptr_t>(mbi.BaseAddress) + mbi.RegionSize;
    }
    return true;
}

std::string safe_cstr(const char* s) {
    std::string out;
    if (!s) return out;
    for (size_t i = 0; i < 96 && mem_ok(s + i, 1, false) && s[i]; ++i) out.push_back(s[i] >= 0x20 && s[i] < 0x7f ? s[i] : '?');
    return out;
}

// d3d12_xs.dll's wrappers -> the desktop object (no reference added); the object itself otherwise.
IUnknown* unwrap_gfx(IUnknown* o) {
    using Fn = IUnknown*(WINAPI*)(IUnknown*);
    static std::atomic<Fn> cached{nullptr};
    Fn fn = cached.load();
    if (!fn) {
        if (HMODULE m = GetModuleHandleW(L"d3d12_xs.dll")) fn = reinterpret_cast<Fn>(GetProcAddress(m, "X2WGfxUnwrap"));
        if (fn) cached.store(fn);
    }
    if (!o || !fn) return o;
    IUnknown* real = fn(o);
    return real ? real : o;
}

enum class Kind : int { factory, file, queue, status, count };
const char* kind_name(Kind k) {
    switch (k) {
    case Kind::factory: return "factory";
    case Kind::file: return "file";
    case Kind::queue: return "queue";
    case Kind::status: return "status-array";
    default: return "?";
    }
}

std::atomic<long> g_live{0};
std::mutex g_alias_mutex;
std::vector<GUID> g_alias[static_cast<int>(Kind::count)];  // IIDs a creation call asked for, answered by QueryInterface

void add_alias(Kind k, const GUID& g) {
    std::lock_guard<std::mutex> lock(g_alias_mutex);
    auto& v = g_alias[static_cast<int>(k)];
    for (const auto& e : v) if (IsEqualGUID(e, g)) return;
    if (v.size() < 16) v.push_back(g);
}
bool has_alias(Kind k, const GUID& g) {
    std::lock_guard<std::mutex> lock(g_alias_mutex);
    for (const auto& e : g_alias[static_cast<int>(k)]) if (IsEqualGUID(e, g)) return true;
    return false;
}

struct Obj {
    const void* const* vtbl;
    std::atomic<long> refs{1};
    Kind kind;
    Abi abi;
};

void* g_vt[static_cast<int>(Kind::count)][kSlots];
U dispatch(Obj* self, int slot, U a1, U a2, U a3, U a4);
template <int N>
U STDMETHODCALLTYPE thunk(Obj* self, U a1, U a2, U a3, U a4) { return dispatch(self, N, a1, a2, a3, a4); }
template <size_t... I>
void fill_vt(void** vt, std::index_sequence<I...>) { ((vt[I] = reinterpret_cast<void*>(&thunk<static_cast<int>(I)>)), ...); }
const void* const* vtable_of(Kind k) {
    static std::once_flag once;
    std::call_once(once, [] {
        for (auto& vt : g_vt) fill_vt(vt, std::make_index_sequence<kSlots>{});
    });
    return const_cast<const void* const*>(g_vt[static_cast<int>(k)]);
}
template <class T>
T* as(const void* p, Kind k) {
    if (!p || !mem_ok(p, sizeof(void*), false)) return nullptr;
    return *static_cast<const void* const* const*>(p) == vtable_of(k) ? static_cast<T*>(const_cast<void*>(p)) : nullptr;
}

struct Factory : Obj {};
Factory g_factory[2];

struct File : Obj {
    HANDLE h = INVALID_HANDLE_VALUE;
    std::wstring path;
    std::mutex m;
};

struct StatusEntry {
    std::atomic<int> done{1};
    std::atomic<HRESULT> hr{S_OK};
};
struct StatusArray : Obj {
    uint32_t capacity = 0;
    std::unique_ptr<StatusEntry[]> e;
    std::string name;
};

struct Op {
    enum T : uint8_t { request, status, signal, set_event } t = request;
    // request
    File* file = nullptr;
    uint64_t offset = 0;
    const uint8_t* src_mem = nullptr;
    uint32_t src_size = 0;
    uint32_t codec = kNone;  // kNone, kGDeflate, kZlib, or a registered format
    uint32_t out_size = 0;
    uint8_t dest_type = pc::kDestMemory;
    void* dest_mem = nullptr;
    ID3D12Resource* res = nullptr;
    uint64_t res_offset = 0;
    UINT sub = 0;
    D3D12_BOX box{};
    uint64_t tag = 0;
    HRESULT reject = S_OK;  // refused at enqueue (already logged)
    bool cancelled = false;
    // status / signal / event
    StatusArray* arr = nullptr;
    uint32_t index = 0;
    ID3D12Fence* fence = nullptr;
    uint64_t value = 0;
    HANDLE event = nullptr;
};
constexpr uint32_t kZlib = 0x100;  // internal id: console ZlibDecompress (RFC 1950)

struct Gpu;  // GPU destination state of a queue (copy queue on the desktop device)

struct Queue : Obj {
    std::mutex m;
    std::condition_variable cv, idle_cv;
    std::deque<Op> pending, submitted;
    size_t inflight = 0;
    bool stop = false, closed = false;
    uint64_t pending_since = 0;
    uint16_t capacity = 0;
    int8_t priority = 0;
    uint64_t source_type = 0;
    std::string name;
    ID3D12Device* device = nullptr;  // desktop device (pc desc), referenced
    Gpu* gpu = nullptr;
    // errors
    std::mutex err_m;
    uint32_t failures = 0;
    HRESULT first_failure = S_OK;
    HANDLE error_event = nullptr;
    std::thread worker;
};

void destroy_gpu(Gpu* g);
HRESULT run_gpu(Queue* q, Op& op, const uint8_t* data);
HRESULT gpu_staging(Queue* q, Op& op, uint8_t** out, uint64_t* size);

void release_obj(Obj* o);

void fail(Queue* q, HRESULT hr) {
    std::lock_guard<std::mutex> lock(q->err_m);
    if (q->failures++ == 0) {
        q->first_failure = hr;
        SetEvent(q->error_event);
    }
}

bool decode(uint32_t codec, const uint8_t* in, size_t in_size, uint8_t* out, size_t out_size) {
    if (codec == kZlib) {
        thread_local libdeflate_decompressor* d = libdeflate_alloc_decompressor();
        size_t actual = 0;
        return d && libdeflate_zlib_decompress(d, in, in_size, out, out_size, &actual) == LIBDEFLATE_SUCCESS &&
               actual == out_size;
    }
    Decompressor fn;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        auto it = g_decoders.find(codec);
        if (it != g_decoders.end()) fn = it->second;
    }
    if (fn) return fn(in, in_size, out, out_size);
    if (codec == kGDeflate) return gdeflate_decompress(in, in_size, out, out_size);
    return false;
}
bool codec_known(uint32_t codec) {
    if (codec == kNone || codec == kGDeflate || codec == kZlib) return true;
    std::lock_guard<std::mutex> lock(g_mutex);
    return g_decoders.count(codec) != 0;
}

bool file_read(File* f, uint64_t offset, void* buf, uint32_t size) {
    return f && f->h != INVALID_HANDLE_VALUE && read_exact(f->h, offset, buf, size);
}

// One request: read (file or memory), decode, write to memory or hand to the GPU path.
HRESULT execute(Queue* q, Op& op) {
    if (op.cancelled) return S_OK;
    if (FAILED(op.reject)) return op.reject;
    ++g_stats.requests;
    const bool gpu = op.dest_type != pc::kDestMemory;
    uint8_t* out = static_cast<uint8_t*>(op.dest_mem);
    uint64_t out_cap = op.out_size;
    if (gpu) {
        const HRESULT hr = gpu_staging(q, op, &out, &out_cap);
        if (FAILED(hr)) return hr;
    } else if (!out || !mem_ok(out, op.out_size, true)) {
        log_once("dsx:baddest", "directstorage: request destination %p (%u bytes) is not writable memory", op.dest_mem, op.out_size);
        return X2W_E_DS_BAD_DESTINATION;
    }
    if (op.out_size > out_cap) return E_INVALIDARG;
    // Source bytes.
    std::vector<uint8_t> staging;
    const uint8_t* src = op.src_mem;
    if (op.file) {
        if (op.codec == kNone) {
            const uint32_t n = std::min<uint32_t>(op.src_size, op.out_size);
            if (!file_read(op.file, op.offset, out, n)) return HRESULT_FROM_WIN32(GetLastError() ? GetLastError() : ERROR_READ_FAULT);
            g_stats.bytes_read += n;
            g_stats.bytes_out += n;
            return gpu ? run_gpu(q, op, out) : S_OK;
        }
        try {
            staging.resize(op.src_size);
        } catch (...) {
            return E_OUTOFMEMORY;
        }
        if (!file_read(op.file, op.offset, staging.data(), op.src_size))
            return HRESULT_FROM_WIN32(GetLastError() ? GetLastError() : ERROR_READ_FAULT);
        src = staging.data();
    } else if (!src || !mem_ok(src, op.src_size, false)) {
        log_once("dsx:badsrc", "directstorage: request memory source %p (%u bytes) is not readable", op.src_mem, op.src_size);
        return E_INVALIDARG;
    }
    g_stats.bytes_read += op.src_size;
    if (op.codec == kNone) {
        std::memcpy(out, src, std::min<uint32_t>(op.src_size, op.out_size));
    } else if (!decode(op.codec, src, op.src_size, out, op.out_size)) {
        log_once("dsx:decode:" + std::to_string(op.codec), "directstorage: decoding a format %#x request failed (%u -> %u bytes)",
                 op.codec, op.src_size, op.out_size);
        return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    }
    g_stats.bytes_out += op.out_size;
    return gpu ? run_gpu(q, op, out) : S_OK;
}

void release_op(Op& op) {
    if (op.file) release_obj(op.file);
    if (op.arr) release_obj(op.arr);
    if (op.fence) op.fence->Release();
    if (op.res) op.res->Release();
    op.file = nullptr;
    op.arr = nullptr;
    op.fence = nullptr;
    op.res = nullptr;
}

struct PoolJob {
    Queue* q;
    Op* op;
    HRESULT hr;
    std::atomic<long>* left;
    HANDLE done;
};
void CALLBACK pool_job(PTP_CALLBACK_INSTANCE, void* ctx) {
    auto* j = static_cast<PoolJob*>(ctx);
    j->hr = execute(j->q, *j->op);
    if (j->left->fetch_sub(1) == 1) SetEvent(j->done);
}

// Runs a run of requests: memory destinations on the thread pool, GPU ones on this thread. Returns the first failure.
bool poolable(const Op& op) { return op.dest_type == pc::kDestMemory && !op.cancelled && SUCCEEDED(op.reject); }
HRESULT run_requests(Queue* q, Op* ops, size_t n) {
    HRESULT first = S_OK;
    auto note = [&](HRESULT hr) {
        if (FAILED(hr)) {
            ++g_stats.failed;
            fail(q, hr);
            log_once("dsx:fail:" + std::to_string(static_cast<uint32_t>(hr)), "directstorage: a request failed with %#lx",
                     static_cast<unsigned long>(hr));
            if (SUCCEEDED(first)) first = hr;
        }
    };
    std::vector<PoolJob> jobs;
    for (size_t i = 0; i < n; ++i)
        if (poolable(ops[i])) jobs.push_back({q, &ops[i], S_OK, nullptr, nullptr});
    const bool parallel = jobs.size() > 1;
    std::atomic<long> left{static_cast<long>(jobs.size())};
    HANDLE done = nullptr;
    if (parallel) {
        done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
        tag_handle(done, "x2w_sys directstorage batch-done event");
        for (auto& j : jobs) {
            j.left = &left;
            j.done = done;
            if (!TrySubmitThreadpoolCallback(&pool_job, &j, nullptr)) pool_job(nullptr, &j);
        }
    }
    for (size_t i = 0; i < n; ++i)
        if (!(parallel && poolable(ops[i]))) note(execute(q, ops[i]));
    if (parallel) {
        WaitForSingleObject(done, INFINITE);
        tag_handle(done, nullptr);
        CloseHandle(done);
        for (auto& j : jobs) note(j.hr);
    }
    return first;
}

void process(Queue* q, std::vector<Op>& batch, HRESULT& seg) {
    size_t i = 0;
    while (i < batch.size()) {
        size_t j = i;
        while (j < batch.size() && batch[j].t == Op::request) ++j;
        if (j > i) {
            const HRESULT hr = run_requests(q, batch.data() + i, j - i);
            if (FAILED(hr) && SUCCEEDED(seg)) seg = hr;
        }
        if (j < batch.size()) {
            Op& op = batch[j];
            switch (op.t) {
            case Op::status:
                if (op.arr && op.index < op.arr->capacity) {
                    op.arr->e[op.index].hr = seg;
                    op.arr->e[op.index].done = 1;
                }
                seg = S_OK;
                break;
            case Op::signal:
                if (op.fence) op.fence->Signal(op.value);
                seg = S_OK;
                break;
            case Op::set_event:
                if (op.event) SetEvent(op.event);
                break;
            default: break;
            }
            ++j;
        }
        i = j;
    }
    for (auto& op : batch) release_op(op);
}

uint64_t now_ms() { return GetTickCount64(); }

void submit_locked(Queue* q) {
    if (q->pending.empty()) return;
    q->inflight += q->pending.size();
    for (auto& op : q->pending) q->submitted.push_back(std::move(op));
    q->pending.clear();
    q->cv.notify_all();
}

void worker(Queue* q) {
    HRESULT seg = S_OK;
    for (;;) {
        std::vector<Op> batch;
        {
            std::unique_lock<std::mutex> lock(q->m);
            for (;;) {
                if (!q->submitted.empty()) break;
                if (q->stop) return;
                // Console slots: if Submit was not recognized, entries left unsubmitted for 5 ms are submitted
                // (completing early is always allowed; never completing would hang the title).
                if (q->abi == Abi::console && !q->pending.empty() && now_ms() - q->pending_since >= 5) {
                    log_once("dsx:autoflush", "directstorage: console queue submitted %zu entries left unsubmitted for 5 ms",
                             q->pending.size());
                    submit_locked(q);
                    break;
                }
                if (q->abi == Abi::console && !q->pending.empty()) q->cv.wait_for(lock, std::chrono::milliseconds(2));
                else q->cv.wait(lock);
            }
            batch.reserve(q->submitted.size());
            for (auto& op : q->submitted) batch.push_back(std::move(op));
            q->submitted.clear();
        }
        process(q, batch, seg);
        {
            std::lock_guard<std::mutex> lock(q->m);
            q->inflight -= batch.size();
        }
        q->idle_cv.notify_all();
    }
}

void enqueue(Queue* q, Op&& op) {
    std::lock_guard<std::mutex> lock(q->m);
    if (q->closed) {
        log_once("dsx:closed", "directstorage: enqueue on a closed queue ignored");
        release_op(op);
        return;
    }
    if (op.t == Op::status && op.arr && op.index < op.arr->capacity) op.arr->e[op.index].done = 0;
    if (q->pending.empty()) q->pending_since = now_ms();
    q->pending.push_back(std::move(op));
    q->cv.notify_all();
    if (q->pending.size() > std::max<size_t>(1, q->capacity / 2)) submit_locked(q);  // auto-submit past half capacity
}

void drain(Queue* q) {
    std::unique_lock<std::mutex> lock(q->m);
    submit_locked(q);
    q->idle_cv.wait(lock, [q] { return q->inflight == 0; });
}

void release_obj(Obj* o) {
    if (!o) return;
    if (o->kind == Kind::factory) return;  // static singletons
    if (--o->refs != 0) return;
    --g_live;
    switch (o->kind) {
    case Kind::file: {
        auto* f = static_cast<File*>(o);
        if (f->h != INVALID_HANDLE_VALUE) {
            paths::forget_handle(f->h);
            CloseHandle(f->h);
        }
        delete f;
        break;
    }
    case Kind::status: delete static_cast<StatusArray*>(o); break;
    case Kind::queue: {
        auto* q = static_cast<Queue*>(o);
        drain(q);
        {
            std::lock_guard<std::mutex> lock(q->m);
            q->stop = true;
        }
        q->cv.notify_all();
        q->worker.join();
        destroy_gpu(q->gpu);
        if (q->device) q->device->Release();
        tag_handle(q->error_event, nullptr);
        CloseHandle(q->error_event);
        delete q;
        break;
    }
    default: break;
    }
}

HRESULT hand_out(Obj* o, Kind k, const GUID* riid, void** ppv) {
    if (riid) add_alias(k, *riid);
    *ppv = o;
    return S_OK;
}

bool known_iid(Kind k, Abi, const GUID& g) {
    if (IsEqualGUID(g, IID_IUnknown)) return true;
    switch (k) {
    case Kind::factory: if (IsEqualGUID(g, pc::IID_Factory)) return true; break;
    case Kind::file: if (IsEqualGUID(g, pc::IID_File)) return true; break;
    case Kind::queue:
        if (IsEqualGUID(g, pc::IID_Queue) || IsEqualGUID(g, pc::IID_Queue1) || IsEqualGUID(g, pc::IID_Queue2)) return true;
        break;
    case Kind::status: if (IsEqualGUID(g, pc::IID_StatusArray)) return true; break;
    default: break;
    }
    return has_alias(k, g);
}


// ---- GPU destinations ------------------------------------------------------------------------------------------
// One copy queue per DirectStorage queue on its (desktop) device; requests are decoded straight into a persistently
// mapped upload buffer, copied, and waited for before the next one, so fences and statuses enqueued after them see
// the data. Resources must be in D3D12_RESOURCE_STATE_COMMON (DirectStorage's own rule), which copy queues promote.
// Texture data is expected in the GetCopyableFootprints layout of the destination; a tightly packed region (rows of
// exactly the row size) is also accepted and laid out on the way.
struct Gpu {
    ID3D12CommandQueue* queue = nullptr;
    ID3D12CommandAllocator* alloc = nullptr;
    ID3D12GraphicsCommandList* list = nullptr;
    ID3D12Fence* fence = nullptr;
    HANDLE event = nullptr;
    uint64_t value = 0;
    ID3D12Resource* upload = nullptr;
    uint64_t upload_size = 0;
    uint8_t* mapped = nullptr;
    // The current request's layout.
    std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> fp;
    std::vector<UINT> rows;
    std::vector<UINT64> row_size;
    uint64_t total = 0;
    bool tight = false;
    // A copy that did not complete in time may still be running: its allocator, list and upload buffer are never
    // reset or released while it might be (later GPU requests fail instead).
    bool stuck = false;
};
void destroy_gpu(Gpu* g) {
    if (!g) return;
    if (g->fence && g->event && g->fence->GetCompletedValue() < g->value) {
        g->fence->SetEventOnCompletion(g->value, g->event);
        WaitForSingleObject(g->event, 2000);
    }
    if (g->fence && g->fence->GetCompletedValue() < g->value) {
        log_once("dsx:gpu:leak", "directstorage: a GPU copy is still running at queue release; its buffers are kept");
        return;  // the GPU may still read them
    }
    if (g->upload) g->upload->Release();
    if (g->list) g->list->Release();
    if (g->alloc) g->alloc->Release();
    if (g->queue) g->queue->Release();
    if (g->fence) g->fence->Release();
    if (g->event) CloseHandle(g->event);
    delete g;
}
HRESULT gpu_init(Queue* q) {
    if (q->gpu) return S_OK;
    if (!q->device) return E_INVALIDARG;
    auto* g = new Gpu;
    D3D12_COMMAND_QUEUE_DESC qd{};
    qd.Type = D3D12_COMMAND_LIST_TYPE_COPY;
    HRESULT hr = q->device->CreateCommandQueue(&qd, __uuidof(ID3D12CommandQueue), reinterpret_cast<void**>(&g->queue));
    if (SUCCEEDED(hr)) hr = q->device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_COPY, __uuidof(ID3D12CommandAllocator), reinterpret_cast<void**>(&g->alloc));
    if (SUCCEEDED(hr)) hr = q->device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_COPY, g->alloc, nullptr, __uuidof(ID3D12GraphicsCommandList), reinterpret_cast<void**>(&g->list));
    if (SUCCEEDED(hr)) hr = g->list->Close();
    if (SUCCEEDED(hr)) hr = q->device->CreateFence(0, D3D12_FENCE_FLAG_NONE, __uuidof(ID3D12Fence), reinterpret_cast<void**>(&g->fence));
    g->event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (FAILED(hr) || !g->event) {
        log_once("dsx:gpu:init", "directstorage: copy queue creation failed (%#lx)", static_cast<unsigned long>(hr));
        destroy_gpu(g);
        return FAILED(hr) ? hr : E_FAIL;
    }
    q->gpu = g;
    log("directstorage: copy queue created for GPU destinations");
    return S_OK;
}
HRESULT gpu_upload(Queue* q, uint64_t size) {
    Gpu* g = q->gpu;
    if (g->upload_size >= size) return S_OK;
    if (g->upload) g->upload->Release();
    g->upload = nullptr;
    g->mapped = nullptr;
    g->upload_size = 0;
    const uint64_t want = std::max<uint64_t>((size + 0xFFFF) & ~0xFFFFull, 1 << 20);
    D3D12_HEAP_PROPERTIES hp{};
    hp.Type = D3D12_HEAP_TYPE_UPLOAD;
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width = want;
    d.Height = 1;
    d.DepthOrArraySize = 1;
    d.MipLevels = 1;
    d.SampleDesc.Count = 1;
    d.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    HRESULT hr = q->device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d, D3D12_RESOURCE_STATE_GENERIC_READ, nullptr,
                                                    __uuidof(ID3D12Resource), reinterpret_cast<void**>(&g->upload));
    if (SUCCEEDED(hr)) {
        D3D12_RANGE none{0, 0};
        hr = g->upload->Map(0, &none, reinterpret_cast<void**>(&g->mapped));
    }
    if (FAILED(hr)) {
        log_once("dsx:gpu:upload", "directstorage: upload buffer of %llu bytes failed (%#lx)", static_cast<unsigned long long>(want),
                 static_cast<unsigned long>(hr));
        return hr;
    }
    g->upload_size = want;
    return S_OK;
}
HRESULT gpu_staging(Queue* q, Op& op, uint8_t** out, uint64_t* cap) {
    HRESULT hr = gpu_init(q);
    if (FAILED(hr)) return hr;
    Gpu* g = q->gpu;
    if (g->stuck) return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
    g->fp.clear();
    g->rows.clear();
    g->row_size.clear();
    g->tight = false;
    g->total = op.out_size;
    if (op.dest_type != pc::kDestBuffer) {
        D3D12_RESOURCE_DESC d = op.res->GetDesc();
        UINT first = op.sub, count = 1;
        if (op.dest_type == pc::kDestTextureRegion) {
            const D3D12_BOX& b = op.box;
            if (b.right <= b.left || b.bottom <= b.top || b.back <= b.front) return E_INVALIDARG;
            d.Width = b.right - b.left;
            d.Height = b.bottom - b.top;
            d.DepthOrArraySize = static_cast<UINT16>(d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE3D ? b.back - b.front : 1);
            d.MipLevels = 1;
            d.Alignment = 0;
            first = 0;
        } else {
            const UINT layers = d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE3D ? 1 : d.DepthOrArraySize;
            const UINT all = d.MipLevels * layers;
            if (first >= all) return E_INVALIDARG;
            count = all - first;
        }
        g->fp.resize(count);
        g->rows.resize(count);
        g->row_size.resize(count);
        g->total = 0;
        q->device->GetCopyableFootprints(&d, first, count, 0, g->fp.data(), g->rows.data(), g->row_size.data(), &g->total);
        if (g->total == UINT64_MAX || !g->total) return E_INVALIDARG;
        if (op.out_size != g->total) {
            uint64_t packed = 0;
            for (UINT i = 0; i < count; ++i) packed += g->row_size[i] * g->rows[i] * g->fp[i].Footprint.Depth;
            if (count == 1 && op.out_size == packed) {
                g->tight = true;
                log_once("dsx:gpu:tight", "directstorage: texture data taken as tightly packed rows (%u bytes; footprint layout %llu)",
                         op.out_size, static_cast<unsigned long long>(g->total));
            } else {
                log_once("dsx:gpu:size", "directstorage: texture request of %u bytes; the destination's footprint layout is %llu",
                         op.out_size, static_cast<unsigned long long>(g->total));
                if (op.out_size > g->total) return E_INVALIDARG;
            }
        }
    }
    // Tightly packed data is decoded at the end of the buffer and laid out at the start.
    const uint64_t need = g->tight ? ((g->total + 255) & ~255ull) + op.out_size : std::max<uint64_t>(g->total, op.out_size);
    hr = gpu_upload(q, need);
    if (FAILED(hr)) return hr;
    *out = g->tight ? g->mapped + ((g->total + 255) & ~255ull) : g->mapped;
    if (g->tight && ((g->total + 255) & ~255ull) + op.out_size > g->upload_size) return E_OUTOFMEMORY;
    *cap = op.out_size;
    return S_OK;
}
HRESULT run_gpu(Queue* q, Op& op, const uint8_t* data) {
    Gpu* g = q->gpu;
    if (!g) return E_FAIL;
    if (g->tight) {
        const auto& f = g->fp[0];
        const uint64_t rs = g->row_size[0];
        for (UINT z = 0; z < f.Footprint.Depth; ++z)
            for (UINT y = 0; y < g->rows[0]; ++y)
                std::memmove(g->mapped + f.Offset + (static_cast<uint64_t>(z) * g->rows[0] + y) * f.Footprint.RowPitch,
                             data + (static_cast<uint64_t>(z) * g->rows[0] + y) * rs, rs);
    }
    HRESULT hr = g->alloc->Reset();
    if (SUCCEEDED(hr)) hr = g->list->Reset(g->alloc, nullptr);
    if (FAILED(hr)) return hr;
    if (op.dest_type == pc::kDestBuffer) {
        g->list->CopyBufferRegion(op.res, op.res_offset, g->upload, 0, op.out_size);
    } else {
        for (size_t i = 0; i < g->fp.size(); ++i) {
            D3D12_TEXTURE_COPY_LOCATION dst{}, src{};
            dst.pResource = op.res;
            dst.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            dst.SubresourceIndex = op.sub + static_cast<UINT>(i);
            src.pResource = g->upload;
            src.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            src.PlacedFootprint = g->fp[i];
            if (op.dest_type == pc::kDestTextureRegion)
                g->list->CopyTextureRegion(&dst, op.box.left, op.box.top, op.box.front, &src, nullptr);
            else
                g->list->CopyTextureRegion(&dst, 0, 0, 0, &src, nullptr);
        }
    }
    hr = g->list->Close();
    if (FAILED(hr)) return hr;
    ID3D12CommandList* lists[] = {g->list};
    g->queue->ExecuteCommandLists(1, lists);
    hr = g->queue->Signal(g->fence, ++g->value);
    if (FAILED(hr)) return hr;
    if (g->fence->GetCompletedValue() < g->value) {
        g->fence->SetEventOnCompletion(g->value, g->event);
        if (WaitForSingleObject(g->event, 30000) != WAIT_OBJECT_0) {
            log_once("dsx:gpu:timeout", "directstorage: a GPU copy did not complete in 30 s");
            g->stuck = true;
            return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
        }
    }
    if (g->fence->GetCompletedValue() == UINT64_MAX) return static_cast<HRESULT>(0x887A0005L);  // DXGI_ERROR_DEVICE_REMOVED
    return S_OK;
}

// ---- factory -------------------------------------------------------------------------------------------------
HRESULT create_queue(Abi abi, const uint8_t* d, const GUID* riid, void** ppv) {
    if (!mem_ok(d, abi == Abi::pc ? sizeof(pc::QueueDesc) : 24, false)) return E_INVALIDARG;
    auto* q = new Queue;
    q->vtbl = vtable_of(Kind::queue);
    q->kind = Kind::queue;
    q->abi = abi;
    std::memcpy(&q->source_type, d, 8);
    std::memcpy(&q->capacity, d + 8, 2);
    std::memcpy(&q->priority, d + 10, 1);
    const char* name = nullptr;
    std::memcpy(&name, d + 16, 8);
    q->name = safe_cstr(name);
    if (abi == Abi::pc) {
        ID3D12Device* dev = nullptr;
        std::memcpy(&dev, d + 24, 8);
        if (dev) {
            q->device = reinterpret_cast<ID3D12Device*>(unwrap_gfx(dev));
            q->device->AddRef();
        }
    }
    if (q->source_type > 1)
        log_once("dsx:desc:src", "directstorage: queue desc SourceType %#llx not understood (raw desc %s)",
                 static_cast<unsigned long long>(q->source_type),
                 hex_args(reinterpret_cast<const U*>(d)[0], reinterpret_cast<const U*>(d)[1], reinterpret_cast<const U*>(d)[2], 0).c_str());
    if (q->capacity < 0x80 || q->capacity > 0x2000) {
        log_once("dsx:desc:cap", "directstorage: queue capacity %u outside 128..8192; using 1024", q->capacity);
        q->capacity = 1024;
    }
    q->error_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    tag_handle(q->error_event, "x2w_sys directstorage queue error event");
    ++g_live;
    q->worker = std::thread([q] { worker(q); });
    log("directstorage: queue created (%s abi, capacity %u, priority %d, source %s, name \"%s\"%s)", abi == Abi::pc ? "pc" : "console",
        q->capacity, q->priority, q->source_type ? "memory" : "file", q->name.c_str(), q->device ? ", device" : "");
    return hand_out(q, Kind::queue, riid, ppv);
}

HRESULT open_file(Abi abi, const wchar_t* path, const GUID* riid, void** ppv) {
    std::wstring p;
    for (size_t i = 0; i < 1024 && mem_ok(path + i, 2, false) && path[i]; ++i) p.push_back(path[i]);
    const paths::Result mapped = paths::global_map().remap(p);
    if (mapped.remapped)
        log_once("ds:path:" + narrow(mapped.path), "directstorage: path remap %s -> %s", narrow(p).c_str(), narrow(mapped.path).c_str());
    HANDLE h = open_ours(mapped.path, 0);
    if (h == INVALID_HANDLE_VALUE) {
        const DWORD e = GetLastError();
        log_once("dsx:open:" + narrow(p), "directstorage: OpenFile %s failed (win32 %lu)", narrow(p).c_str(), e);
        *ppv = nullptr;
        return HRESULT_FROM_WIN32(e);
    }
    auto* f = new File;
    f->vtbl = vtable_of(Kind::file);
    f->kind = Kind::file;
    f->abi = abi;
    f->h = h;
    f->path = mapped.path;
    ++g_live;
    return hand_out(f, Kind::file, riid, ppv);
}

HRESULT create_status(Abi abi, uint32_t capacity, const char* name, const GUID* riid, void** ppv) {
    if (capacity == 0 || capacity > (1u << 20)) return E_INVALIDARG;
    auto* s = new StatusArray;
    s->vtbl = vtable_of(Kind::status);
    s->kind = Kind::status;
    s->abi = abi;
    s->capacity = capacity;
    s->e.reset(new StatusEntry[capacity]);
    s->name = safe_cstr(name);
    ++g_live;
    return hand_out(s, Kind::status, riid, ppv);
}

const GUID* iid_arg(U a) { return mem_ok(reinterpret_cast<const void*>(a), sizeof(GUID), false) ? reinterpret_cast<const GUID*>(a) : nullptr; }
bool out_arg(U a) { return mem_ok(reinterpret_cast<const void*>(a), sizeof(void*), true); }

bool looks_like_path(U a) {
    const auto* w = reinterpret_cast<const wchar_t*>(a);
    if (!mem_ok(w, 4, false)) return false;
    return w[0] >= 0x20 && w[0] < 0xD800 && w[1] >= 0x20 && w[1] < 0xD800;
}

U factory_call(Factory* f, int slot, U a1, U a2, U a3, U a4) {
    enum M { cq, of, cs, setter } m;
    if (f->abi == Abi::pc && slot <= 7) {
        m = slot == 3 ? cq : slot == 4 ? of : slot == 5 ? cs : setter;
    } else if (a1 >= 0x10000 && mem_ok(reinterpret_cast<void*>(a1), 8, false) && iid_arg(a2) && out_arg(a3)) {
        m = looks_like_path(a1) ? of : cq;  // (desc | path, riid, ppv)
    } else if (a1 >= 1 && a1 <= 0x10000 && (a2 == 0 || mem_ok(reinterpret_cast<void*>(a2), 1, false)) && iid_arg(a3) && out_arg(a4)) {
        m = cs;  // (capacity, name, riid, ppv)
    } else {
        m = setter;
    }
    static const char* names[] = {"CreateQueue", "OpenFile", "CreateStatusArray", "setter"};
    if (m == cq || m == of) *reinterpret_cast<void**>(a3) = nullptr;
    if (m == cs) *reinterpret_cast<void**>(a4) = nullptr;
    log_once("dsx:factory:" + std::to_string(slot) + ":" + names[m], "directstorage: factory slot %d served as %s (args %s)", slot,
             names[m], hex_args(a1, a2, a3, a4).c_str());
    switch (m) {
    case cq: {
        if (!out_arg(a3)) return E_POINTER;
        if (const GUID* g = iid_arg(a2)) log_once("dsx:iid:q:" + guid_string(*g), "directstorage: CreateQueue riid=%s", guid_string(*g).c_str());
        return create_queue(f->abi, reinterpret_cast<const uint8_t*>(a1), iid_arg(a2), reinterpret_cast<void**>(a3));
    }
    case of: {
        if (!out_arg(a3)) return E_POINTER;
        if (const GUID* g = iid_arg(a2)) log_once("dsx:iid:f:" + guid_string(*g), "directstorage: OpenFile riid=%s", guid_string(*g).c_str());
        return open_file(f->abi, reinterpret_cast<const wchar_t*>(a1), iid_arg(a2), reinterpret_cast<void**>(a3));
    }
    case cs: {
        if (!out_arg(a4)) return E_POINTER;
        if (const GUID* g = iid_arg(a3)) log_once("dsx:iid:s:" + guid_string(*g), "directstorage: CreateStatusArray riid=%s", guid_string(*g).c_str());
        return create_status(f->abi, static_cast<uint32_t>(a1), reinterpret_cast<const char*>(a2), iid_arg(a3), reinterpret_cast<void**>(a4));
    }
    default: return S_OK;  // SetDebugFlags, SetStagingBufferSize, SetCpuAffinity, GetStats: accepted
    }
}

// ---- requests -------------------------------------------------------------------------------------------------
bool take_file(Op& op, IUnknown* src) {
    File* f = as<File>(src, Kind::file);
    if (!f) {
        log_once("dsx:notourfile", "directstorage: request source file %p is not a file this factory opened", static_cast<void*>(src));
        op.reject = E_INVALIDARG;
        return false;
    }
    ++f->refs;
    op.file = f;
    return true;
}

void enqueue_pc_request(Queue* q, const pc::Request* r) {
    Op op;
    if (!mem_ok(r, sizeof *r, false)) {
        log_once("dsx:badreq", "directstorage: EnqueueRequest with an unreadable request %p", static_cast<const void*>(r));
        return;
    }
    const uint8_t fmt = r->Options.CompressionFormat;
    op.codec = fmt;
    op.tag = r->CancellationTag;
    for (uint8_t b : r->Options.Reserved1)
        if (b) { log_once("dsx:pc:res1", "directstorage: request Options.Reserved1 is not zero"); break; }
    if (r->Options.Reserved) log_once("dsx:pc:res", "directstorage: request Options.Reserved %#llx is not zero", static_cast<unsigned long long>(r->Options.Reserved));
    if (r->Options.SourceType == pc::kSourceFile) {
        take_file(op, r->Source.File.Source);
        op.offset = r->Source.File.Offset;
        op.src_size = r->Source.File.Size;
    } else {
        op.src_mem = static_cast<const uint8_t*>(r->Source.Memory.Source);
        op.src_size = r->Source.Memory.Size;
    }
    op.out_size = fmt == kNone ? op.src_size : r->UncompressedSize;
    if (fmt != kNone && !codec_known(fmt)) {
        ++g_stats.unsupported;
        log_once("dsx:codec:" + std::to_string(fmt), "directstorage: compression format %u has no decoder", fmt);
        op.reject = X2W_E_DS_UNSUPPORTED_COMPRESSION;
    }
    op.dest_type = static_cast<uint8_t>(r->Options.DestinationType);
    switch (op.dest_type) {
    case pc::kDestMemory:
        op.dest_mem = r->Destination.Memory.Buffer;
        if (r->Destination.Memory.Size < op.out_size) {
            log_once("dsx:pc:memsize", "directstorage: memory destination of %u bytes is smaller than the request's %u",
                     r->Destination.Memory.Size, op.out_size);
            op.reject = E_INVALIDARG;
        }
        break;
    case pc::kDestBuffer:
        op.res = r->Destination.Buffer.Resource;
        op.res_offset = r->Destination.Buffer.Offset;
        if (r->Destination.Buffer.Size != op.out_size) {
            log_once("dsx:pc:bufsize", "directstorage: buffer destination of %u bytes for a %u-byte request", r->Destination.Buffer.Size, op.out_size);
            if (r->Destination.Buffer.Size < op.out_size) op.reject = E_INVALIDARG;
        }
        break;
    case pc::kDestTextureRegion:
        op.res = r->Destination.Texture.Resource;
        op.sub = r->Destination.Texture.SubresourceIndex;
        op.box = r->Destination.Texture.Region;
        break;
    case pc::kDestMultipleSubresources:
        op.res = r->Destination.MultipleSubresources.Resource;
        op.sub = r->Destination.MultipleSubresources.FirstSubresource;
        break;
    default:
        log_once("dsx:pc:dest:" + std::to_string(op.dest_type), "directstorage: destination type %u is not implemented", op.dest_type);
        op.reject = E_NOTIMPL;
        break;
    }
    if (op.res) {
        op.res = reinterpret_cast<ID3D12Resource*>(unwrap_gfx(op.res));
        op.res->AddRef();
        if (!q->device) {
            log_once("dsx:pc:nodevice", "directstorage: GPU destination on a queue created without a device");
            op.reject = E_INVALIDARG;
        }
    }
    enqueue(q, std::move(op));
}

// Console DSTORAGE_REQUEST (dstorage_xs.h): Options (8), Destination/DestinationPageArray+Offset (16),
// DestinationSize (4, padded), File+FileOffset | Source | SourcePageArray+Offset (16), SourceSize, IntermediateSize,
// CancellationTag, Name: 72 bytes.
constexpr size_t kConsoleRequestSize = 72;
void enqueue_console_request(Queue* q, const uint8_t* r) {
    Op op;
    uint64_t opt = 0, dst = 0, src0 = 0, src1 = 0, tag = 0;
    uint32_t dst_size = 0, src_size = 0, inter = 0;
    std::memcpy(&opt, r, 8);
    std::memcpy(&dst, r + 8, 8);
    std::memcpy(&dst_size, r + 24, 4);
    std::memcpy(&src0, r + 32, 8);
    std::memcpy(&src1, r + 40, 8);
    std::memcpy(&src_size, r + 48, 4);
    std::memcpy(&inter, r + 52, 4);
    std::memcpy(&tag, r + 56, 8);
    const bool zlib = opt & 1;
    const uint32_t bcpack = (opt >> 1) & 0xF;
    const uint32_t swizzle = (opt >> 5) & 0xFFFF;
    const bool dst_pages = (opt >> 21) & 1;
    const bool src_memory = (opt >> 22) & 1;
    const bool src_pages = (opt >> 23) & 1;
    const uint64_t reserved = opt >> 24;
    log_once("dsx:con:first", "directstorage: first console request options %#llx dest %#llx/%u src %#llx %#llx/%u inter %u",
             static_cast<unsigned long long>(opt), static_cast<unsigned long long>(dst), dst_size,
             static_cast<unsigned long long>(src0), static_cast<unsigned long long>(src1), src_size, inter);
    op.tag = tag;
    op.src_size = src_size;
    op.out_size = dst_size;
    op.codec = zlib ? kZlib : kNone;
    op.dest_mem = reinterpret_cast<void*>(dst);
    if (src_memory) op.src_mem = reinterpret_cast<const uint8_t*>(src0);
    else if (take_file(op, reinterpret_cast<IUnknown*>(src0))) op.offset = src1;
    if (reserved) log_once("dsx:con:res", "directstorage: console request reserved option bits %#llx", static_cast<unsigned long long>(reserved));
    if (bcpack) {
        ++g_stats.unsupported;
        log_once("dsx:con:bcpack:" + std::to_string(bcpack), "directstorage: BCPack mode %u is not implemented (request fails)", bcpack);
        op.reject = X2W_E_DS_UNSUPPORTED_COMPRESSION;
    } else if (inter) {
        log_once("dsx:con:inter", "directstorage: IntermediateSize %u without BCPack ignored", inter);
    }
    if (swizzle) log_once("dsx:con:swz:" + std::to_string(swizzle), "directstorage: swizzle mode %u not applied (bytes copied linearly)", swizzle);
    if (dst_pages || src_pages) {
        log_once("dsx:con:pages", "directstorage: physical-page %s arrays are not implemented (request fails)",
                 dst_pages ? "destination" : "source");
        op.reject = E_NOTIMPL;
    }
    if (!zlib && src_size != dst_size)
        log_once("dsx:con:sizes", "directstorage: uncompressed request with SourceSize %u != DestinationSize %u", src_size, dst_size);
    enqueue(q, std::move(op));
}

bool fence_qi(void* p) {
#if defined(_MSC_VER)
    __try {
        ID3D12Fence* f = nullptr;
        if (SUCCEEDED(static_cast<IUnknown*>(p)->QueryInterface(__uuidof(ID3D12Fence), reinterpret_cast<void**>(&f))) && f) {
            f->Release();
            return true;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
    }
#else
    (void)p;
#endif
    return false;
}
bool looks_like_fence(U a) {
    void* p = reinterpret_cast<void*>(a);
    if (!mem_ok(p, 8, false)) return false;
    void* vt = *static_cast<void**>(p);
    if (!mem_ok(vt, 12 * sizeof(void*), false)) return false;
    return fence_qi(p);
}

void enqueue_status(Queue* q, StatusArray* s, uint32_t index) {
    if (index >= s->capacity) {
        log_once("dsx:status:idx", "directstorage: EnqueueStatus index %u past capacity %u", index, s->capacity);
        return;
    }
    Op op;
    op.t = Op::status;
    ++s->refs;
    op.arr = s;
    op.index = index;
    enqueue(q, std::move(op));
}
void enqueue_signal(Queue* q, ID3D12Fence* fence, uint64_t value) {
    if (!fence) return;
    Op op;
    op.t = Op::signal;
    fence->AddRef();
    op.fence = fence;
    op.value = value;
    enqueue(q, std::move(op));
}

void query(Queue* q, uint8_t* info, size_t desc_size) {
    size_t slots;
    {
        std::lock_guard<std::mutex> lock(q->m);
        slots = q->pending.size() + q->submitted.size();
    }
    std::memset(info, 0, desc_size + 4);
    std::memcpy(info, &q->source_type, 8);
    std::memcpy(info + 8, &q->capacity, 2);
    std::memcpy(info + 10, &q->priority, 1);
    if (q->abi == Abi::pc && desc_size >= 32) std::memcpy(info + 24, &q->device, 8);  // no name pointer kept
    const uint16_t empty = static_cast<uint16_t>(q->capacity > slots ? q->capacity - slots : 0);
    const uint16_t until = static_cast<uint16_t>(q->capacity / 2 > slots ? q->capacity / 2 - slots : 1);
    std::memcpy(info + desc_size, &empty, 2);
    std::memcpy(info + desc_size + 2, &until, 2);
}

U queue_call(Queue* q, int slot, U a1, U a2, U a3, U a4) {
    const char* served = "?";
    U ret = 0;
    // Console slots 3..5: (request*), (status array, index), (fence, value): told apart by the first argument.
    int m = slot;
    if (q->abi == Abi::console && slot >= 3 && slot <= 5) {
        if (as<StatusArray>(reinterpret_cast<void*>(a1), Kind::status)) m = 4;
        else if (looks_like_fence(a1)) m = 5;
        else if (mem_ok(reinterpret_cast<void*>(a1), kConsoleRequestSize, false)) m = 3;
        else m = -1;
    }
    switch (m) {
    case 3:
        served = "EnqueueRequest";
        if (q->abi == Abi::pc) enqueue_pc_request(q, reinterpret_cast<const pc::Request*>(a1));
        else enqueue_console_request(q, reinterpret_cast<const uint8_t*>(a1));
        break;
    case 4: {
        served = "EnqueueStatus";
        if (auto* s = as<StatusArray>(reinterpret_cast<void*>(a1), Kind::status)) enqueue_status(q, s, static_cast<uint32_t>(a2));
        else log_once("dsx:status:notours", "directstorage: EnqueueStatus with an object that is not our status array");
        break;
    }
    case 5: served = "EnqueueSignal"; enqueue_signal(q, reinterpret_cast<ID3D12Fence*>(a1), a2); break;
    case 6: {
        served = "Submit";
        std::lock_guard<std::mutex> lock(q->m);
        submit_locked(q);
        break;
    }
    case 7: {
        served = "CancelRequestsWithTag";
        std::lock_guard<std::mutex> lock(q->m);
        for (auto* d : {&q->pending, &q->submitted})
            for (auto& op : *d)
                if (op.t == Op::request && (op.tag & a1) == a2) op.cancelled = true;
        break;
    }
    case 8: {
        served = "Close";
        drain(q);
        std::lock_guard<std::mutex> lock(q->m);
        q->closed = true;
        break;
    }
    case 9: served = "GetErrorEvent"; ret = reinterpret_cast<U>(q->error_event); break;
    case 10: {
        served = "RetrieveErrorRecord";
        auto* rec = reinterpret_cast<uint8_t*>(a1);
        if (mem_ok(rec, 16, true)) {
            std::lock_guard<std::mutex> lock(q->err_m);
            const uint32_t zero = 0;
            std::memcpy(rec, &q->failures, 4);
            std::memcpy(rec + 8, &q->first_failure, 4);
            std::memcpy(rec + 12, &zero, 4);  // DSTORAGE_COMMAND_TYPE_REQUEST
        }
        break;
    }
    case 11: {
        served = "Query";
        const size_t desc = q->abi == Abi::pc ? 32 : 24;
        if (mem_ok(reinterpret_cast<void*>(a1), desc + 4, true)) query(q, reinterpret_cast<uint8_t*>(a1), desc);
        break;
    }
    case 12: {
        served = "EnqueueSetEvent";
        Op op;
        op.t = Op::set_event;
        op.event = reinterpret_cast<HANDLE>(a1);
        enqueue(q, std::move(op));
        break;
    }
    case 13:
        if (q->abi == Abi::pc) {
            served = "GetCompressionSupport";
            const uint32_t fmt = static_cast<uint8_t>(a1);
            ret = (fmt == kNone || codec_known(fmt)) ? 0x4u /* DSTORAGE_COMPRESSION_SUPPORT_CPU_FALLBACK */ : 0u;
        } else {
            served = "Query1";
            if (mem_ok(reinterpret_cast<void*>(a1), 36, true)) query(q, reinterpret_cast<uint8_t*>(a1), 32);
        }
        break;
    default:
        log_once("dsx:queue:unk:" + std::to_string(slot), "directstorage: queue slot %d not implemented (args %s); E_NOTIMPL", slot,
                 hex_args(a1, a2, a3, a4).c_str());
        return static_cast<U>(static_cast<uint32_t>(E_NOTIMPL));
    }
    log_once("dsx:queue:" + std::to_string(slot) + ":" + served, "directstorage: queue slot %d served as %s (args %s)", slot, served,
             hex_args(a1, a2, a3, a4).c_str());
    return ret;
}

U status_call(StatusArray* s, int slot, U a1, U a2, U a3, U a4) {
    const uint32_t i = static_cast<uint32_t>(a1);
    if (slot != 3 && slot != 4) {
        log_once("dsx:status:unk:" + std::to_string(slot), "directstorage: status-array slot %d not implemented (args %s); E_NOTIMPL",
                 slot, hex_args(a1, a2, a3, a4).c_str());
        return static_cast<uint32_t>(E_NOTIMPL);
    }
    if (i >= s->capacity) return slot == 3 ? 0 : static_cast<uint32_t>(E_INVALIDARG);
    const bool done = s->e[i].done.load() != 0;
    const HRESULT hr = s->e[i].hr.load();
    if (s->abi == Abi::pc) {
        if (slot == 3) return done ? 1 : 0;                                       // IsComplete
        return static_cast<uint32_t>(done ? hr : static_cast<HRESULT>(0x8000000AL));  // GetHResult (E_PENDING)
    }
    // Console: the public order of IsComplete and GetHResult is not known, so both slots answer a value that reads
    // right as either: 0 while pending (false / S_OK), 1 when complete and successful (true / S_FALSE), the failure
    // code when complete and failed (non-zero low byte, so it is also true).
    log_once("dsx:status:con:" + std::to_string(slot), "directstorage: console status-array slot %d answers IsComplete|GetHResult", slot);
    if (!done) return 0;
    if (SUCCEEDED(hr)) return 1;
    uint32_t v = static_cast<uint32_t>(hr);
    if ((v & 0xFF) == 0) v |= 1;
    return v;
}

U file_call(File* f, int slot, U a1, U a2, U a3, U a4) {
    if (slot == 3) {
        log_once("dsx:file:close", "directstorage: file slot 3 served as Close");
        std::lock_guard<std::mutex> lock(f->m);
        // Requests already enqueued hold the object; the handle stays until the last reference (reads after an
        // explicit Close fail on the console too, so closing early is not needed for correctness).
        return 0;
    }
    if (slot == 4) {
        if (f->abi == Abi::pc) {
            log_once("dsx:file:info", "directstorage: file slot 4 served as GetFileInformation");
            auto* info = reinterpret_cast<BY_HANDLE_FILE_INFORMATION*>(a1);
            if (!mem_ok(info, sizeof *info, true)) return static_cast<uint32_t>(E_POINTER);
            return GetFileInformationByHandle(f->h, info) ? S_OK : static_cast<uint32_t>(HRESULT_FROM_WIN32(GetLastError()));
        }
        log_once("dsx:file:handle", "directstorage: console file slot 4 served as GetHandle (args %s)", hex_args(a1, a2, a3, a4).c_str());
        if (mem_ok(reinterpret_cast<void*>(a1), sizeof(HANDLE), true)) {
            // The title gets our overlapped handle: its synchronous ReadFile/WriteFile on it are issued overlapped
            // by the file hooks (sys_paths.cpp, sync_io_on_async).
            paths::register_handle(f->h, f->path, FILE_FLAG_OVERLAPPED);
            *reinterpret_cast<HANDLE*>(a1) = f->h;
        }
        return S_OK;
    }
    log_once("dsx:file:unk:" + std::to_string(slot), "directstorage: file slot %d not implemented (args %s); E_NOTIMPL", slot,
             hex_args(a1, a2, a3, a4).c_str());
    return static_cast<uint32_t>(E_NOTIMPL);
}

U dispatch(Obj* self, int slot, U a1, U a2, U a3, U a4) {
    switch (slot) {
    case 0: {
        const GUID* g = iid_arg(a1);
        void** out = reinterpret_cast<void**>(a2);
        if (!out_arg(a2)) return static_cast<uint32_t>(E_POINTER);
        if (g && known_iid(self->kind, self->abi, *g)) {
            if (self->kind != Kind::factory) ++self->refs;
            *out = self;
            return S_OK;
        }
        *out = nullptr;
        log_once("dsx:qi:" + std::string(kind_name(self->kind)) + (g ? guid_string(*g) : "null"),
                 "directstorage: %s QueryInterface %s: E_NOINTERFACE", kind_name(self->kind), g ? guid_string(*g).c_str() : "(null)");
        return static_cast<uint32_t>(E_NOINTERFACE);
    }
    case 1: return self->kind == Kind::factory ? 1 : static_cast<U>(++self->refs);
    case 2: {
        if (self->kind == Kind::factory) return 1;
        const long left = self->refs.load() - 1;
        release_obj(self);
        return static_cast<U>(left);
    }
    default: break;
    }
    switch (self->kind) {
    case Kind::factory: return factory_call(static_cast<Factory*>(self), slot, a1, a2, a3, a4);
    case Kind::queue: return queue_call(static_cast<Queue*>(self), slot, a1, a2, a3, a4);
    case Kind::status: return status_call(static_cast<StatusArray*>(self), slot, a1, a2, a3, a4);
    case Kind::file: return file_call(static_cast<File*>(self), slot, a1, a2, a3, a4);
    default: return static_cast<uint32_t>(E_NOTIMPL);
    }
}

}  // namespace

std::string guid_string(const GUID& g) {
    char b[64];
    std::snprintf(b, sizeof b, "%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x", static_cast<unsigned long>(g.Data1), g.Data2, g.Data3,
                  g.Data4[0], g.Data4[1], g.Data4[2], g.Data4[3], g.Data4[4], g.Data4[5], g.Data4[6], g.Data4[7]);
    return b;
}

long own_object_count() { return g_live.load(); }

HRESULT get_own_factory(Abi abi, REFIID iid, void** out) {
    if (!out) return E_POINTER;
    Factory& f = g_factory[static_cast<int>(abi)];
    f.vtbl = vtable_of(Kind::factory);
    f.kind = Kind::factory;
    f.abi = abi;
    if (!IsEqualGUID(iid, pc::IID_Factory))
        log_once("dsx:served:" + guid_string(iid), "dstorage-factory iid=%s served-as IDStorageFactory (%s abi)", guid_string(iid).c_str(),
                 abi == Abi::pc ? "pc" : "console");
    add_alias(Kind::factory, iid);
    *out = &f;
    return S_OK;
}

}  // namespace x2w_sys::ds

extern "C" {
HRESULT WINAPI X2wDStorageGetFactory(REFIID iid, void** out) {
    using namespace x2w_sys::ds;
    if (!out) return E_POINTER;
    *out = nullptr;
    const bool pc = IsEqualGUID(iid, pc::IID_Factory);
    x2w_sys::log_once("ds:getfactory:" + guid_string(iid), "directstorage: DStorageGetFactory riid=%s%s", guid_string(iid).c_str(),
                      pc ? " (IDStorageFactory)" : "");
    // The public runtime serves the public interface; everything else (the console's interfaces) is ours.
    if (pc) {
        if (auto fn = resolve_get_factory()) return fn(iid, out);
    }
    return get_own_factory(pc ? Abi::pc : Abi::console, iid, out);
}

// One synchronous fallback read into host memory: the flat entry a gateway (or a stand-in for one) uses without
// the C++ Queue. compression is a DSTORAGE_COMPRESSION_FORMAT value; size is the stored byte count and
// uncompressed_size the decoded count (ignored when compression is 0). Returns S_OK or the request's failure.
HRESULT WINAPI X2wDStorageFallbackRead(const wchar_t* path, uint64_t offset, uint32_t size, uint32_t compression,
                                       uint32_t uncompressed_size, void* dest) {
    if (!path || !dest) return E_POINTER;
    x2w_sys::ds::Request r;
    r.path = path;
    r.offset = offset;
    r.size = size;
    r.compression = compression;
    r.uncompressed_size = uncompressed_size;
    r.dest_memory = dest;
    return x2w_sys::ds::run_request(r).hr;
}
}
