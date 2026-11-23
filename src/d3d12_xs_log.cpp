// Logging, counters and extended vtables of the d3d12_xs.dll graphics shim (d3d12_xs_wrap.h).
//
// Everything here is constant-initialized (no dynamic initializers, no thread_local), so the DLL
// keeps an empty TLS template and loads the same through LoadLibrary and pe_map.
#include "d3d12_xs_wrap.h"
#include "d3d12_xs_api.h"
#include "d3d12_xs_pipeline.h"

#include <atomic>
#include <cstdio>
#include <cstring>
#include <utility>

namespace d3d12_xs {
namespace {

constexpr unsigned kind_count = static_cast<unsigned>(Kind::count);

// Entries before the vptr: MSVC keeps the complete-object locator at [-1]; the Itanium ABI keeps
// offset-to-top and type info at [-2] and [-1]. They are copied so the extended table looks like
// the compiler's table to anything that reads them.
#ifdef _MSC_VER
constexpr unsigned prefix_slots = 1;
#else
constexpr unsigned prefix_slots = 2;
#endif

void* g_tables[kind_count][prefix_slots + vtable_slots];
INIT_ONCE g_table_once[kind_count] = {INIT_ONCE_STATIC_INIT, INIT_ONCE_STATIC_INIT, INIT_ONCE_STATIC_INIT,
                                      INIT_ONCE_STATIC_INIT, INIT_ONCE_STATIC_INIT, INIT_ONCE_STATIC_INIT,
                                      INIT_ONCE_STATIC_INIT, INIT_ONCE_STATIC_INIT, INIT_ONCE_STATIC_INIT,
                                      INIT_ONCE_STATIC_INIT};
static_assert(kind_count == 10, "one INIT_ONCE per wrapper kind");
std::atomic<bool> g_slot_seen[kind_count][vtable_slots];

struct SeenIid {
    unsigned kind;
    GUID iid;
};
constexpr unsigned max_seen_iids = 128;
SeenIid g_seen_iids[max_seen_iids];
unsigned g_seen_iid_count;

SRWLOCK g_lock = SRWLOCK_INIT;
X2WGfxLogSink g_sink;
void* g_sink_context;

std::atomic<std::uint32_t> g_live_objects;
std::atomic<std::uint32_t> g_devices;
std::atomic<std::uint32_t> g_presents;
std::atomic<std::uint64_t> g_first_uses;
std::atomic<std::uint64_t> g_unknown_slots;
std::atomic<std::uint64_t> g_unknown_iids;
std::atomic<std::int32_t> g_title_gpu_state;
std::atomic<std::int32_t> g_title_gpu_hr;
std::atomic<std::uint32_t> g_shaders_translated;
std::atomic<std::uint32_t> g_shaders_cached;
std::atomic<std::uint32_t> g_pipelines_refused;
std::atomic<std::uint32_t> g_draws_refused;
std::atomic<std::uint64_t> g_texture_misses;
std::atomic<std::uint64_t> g_raw_reads;
std::atomic<std::uint32_t> g_raw_uploads;
std::atomic<std::uint32_t> g_raw_samplers;
std::atomic<std::uint64_t> g_indirect_rewrites;

// Distinct refused calls already logged (log_refused_call): a hash of symbol and detail.
constexpr unsigned max_refused_calls = 256;
std::uint64_t g_refused_calls[max_refused_calls];
unsigned g_refused_call_count;

using Thunk = std::uintptr_t(STDMETHODCALLTYPE*)(void*, std::uintptr_t, std::uintptr_t, std::uintptr_t);

// One thunk per slot index. x64 callers clean nothing on return, so a thunk declared with three
// integer arguments is safe whatever the real method's arguments are; RDX/R8/R9 are logged as found.
template <unsigned Slot>
std::uintptr_t STDMETHODCALLTYPE unknown_slot(void* self, std::uintptr_t a1, std::uintptr_t a2, std::uintptr_t a3)
{
    return log_unknown_slot(self, Slot, X2W_RETURN_ADDRESS(), a1, a2, a3);
}

template <unsigned... I>
struct ThunkTable {
    static constexpr Thunk entries[sizeof...(I)] = {&unknown_slot<I>...};
};
template <unsigned... I>
constexpr ThunkTable<I...> make_thunks(std::integer_sequence<unsigned, I...>) { return {}; }
using Thunks = decltype(make_thunks(std::make_integer_sequence<unsigned, vtable_slots>{}));

BOOL CALLBACK fill_table(PINIT_ONCE, PVOID parameter, PVOID*)
{
    auto* args = static_cast<std::pair<unsigned, void* const*>*>(parameter);
    const unsigned kind = args->first;
    void* const* compiler = args->second;
    void** table = g_tables[kind];
    for (unsigned i = 0; i < prefix_slots; ++i) table[i] = compiler[static_cast<int>(i) - static_cast<int>(prefix_slots)];
    const unsigned known = public_slots(static_cast<Kind>(kind));
    for (unsigned slot = 0; slot < vtable_slots; ++slot) {
        table[prefix_slots + slot] = slot < known ? compiler[slot] : reinterpret_cast<void*>(Thunks::entries[slot]);
    }
    return TRUE;
}

// "module.dll+0x1234" when the address is inside a loader module, else the absolute address.
void describe_address(const void* address, char* out, std::size_t size)
{
    HMODULE module = nullptr;
    char path[MAX_PATH]{};
    if (address &&
        GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCSTR>(address), &module) &&
        GetModuleFileNameA(module, path, MAX_PATH)) {
        const char* name = path;
        for (const char* p = path; *p; ++p) {
            if (*p == '\\' || *p == '/') name = p + 1;
        }
        std::snprintf(out, size, "%s+0x%llx", name,
                      static_cast<unsigned long long>(static_cast<const char*>(address) -
                                                      reinterpret_cast<const char*>(module)));
        return;
    }
    std::snprintf(out, size, "0x%llx", static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(address)));
}

void format_guid(const GUID& g, char* out, std::size_t size)
{
    std::snprintf(out, size, "{%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x}", static_cast<unsigned long>(g.Data1),
                  g.Data2, g.Data3, g.Data4[0], g.Data4[1], g.Data4[2], g.Data4[3], g.Data4[4], g.Data4[5], g.Data4[6],
                  g.Data4[7]);
}

void emit(const X2WGfxEvent& event)
{
    AcquireSRWLockShared(&g_lock);
    X2WGfxLogSink sink = g_sink;
    void* context = g_sink_context;
    if (sink) {
        sink(&event, context);
    } else {
        const char* verb = event.kind == X2W_GFX_EVENT_FIRST_USE ? "first use"
                           : event.kind == X2W_GFX_EVENT_NOTE    ? "note"
                           : event.kind == X2W_GFX_EVENT_REFUSED ? "refused"
                                                                 : "unimplemented";
        std::fprintf(stderr, "[x2w] %s %s %s\n", verb, event.symbol, event.detail);
        std::fflush(stderr);
    }
    ReleaseSRWLockShared(&g_lock);
}

}  // namespace

const char* interface_name(Kind kind)
{
    switch (kind) {
    case Kind::device: return "ID3D12Device";
    case Kind::queue: return "ID3D12CommandQueue";
    case Kind::allocator: return "ID3D12CommandAllocator";
    case Kind::list: return "ID3D12GraphicsCommandList";
    case Kind::fence: return "ID3D12Fence1";
    case Kind::swap_chain: return "IDXGISwapChain3";
    case Kind::descriptor_heap: return "ID3D12DescriptorHeap";
    case Kind::resource: return "ID3D12Resource";
    case Kind::heap: return "ID3D12Heap";
    case Kind::command_signature: return "ID3D12CommandSignature";
    default: return "unknown";
    }
}

void install_vtable(void* object, Kind kind)
{
    const unsigned k = static_cast<unsigned>(kind);
    std::pair<unsigned, void* const*> args{k, *static_cast<void* const* const*>(object)};
    InitOnceExecuteOnce(&g_table_once[k], fill_table, &args, nullptr);
    *static_cast<void**>(object) = &g_tables[k][prefix_slots];
}

bool wrapper_kind(const void* object, Kind* kind)
{
    if (!object) return false;
    const void* vptr = *static_cast<void* const*>(object);
    for (unsigned k = 0; k < kind_count; ++k) {
        if (vptr == &g_tables[k][prefix_slots]) {
            if (kind) *kind = static_cast<Kind>(k);
            return true;
        }
    }
    return false;
}

void log_first_use(Kind kind, const char* method, const void* caller)
{
    g_first_uses.fetch_add(1, std::memory_order_relaxed);
    char symbol[160], where[MAX_PATH + 32], detail[MAX_PATH + 64];
    std::snprintf(symbol, sizeof(symbol), "d3d12_xs!%s::%s", interface_name(kind), method);
    describe_address(caller, where, sizeof(where));
    std::snprintf(detail, sizeof(detail), "caller=%s", where);
    X2WGfxEvent event{};
    event.kind = X2W_GFX_EVENT_FIRST_USE;
    event.interface_name = interface_name(kind);
    event.symbol = symbol;
    event.detail = detail;
    event.caller = caller;
    emit(event);
}

void log_unknown_iid(Kind kind, REFIID riid, const void* caller)
{
    g_unknown_iids.fetch_add(1, std::memory_order_relaxed);
    const unsigned k = static_cast<unsigned>(kind);
    bool first = true;
    AcquireSRWLockExclusive(&g_lock);
    for (unsigned i = 0; i < g_seen_iid_count; ++i) {
        if (g_seen_iids[i].kind == k && IsEqualGUID(g_seen_iids[i].iid, riid)) first = false;
    }
    // Past max_seen_iids every further distinct IID is reported, which repeats lines but drops none.
    if (first && g_seen_iid_count < max_seen_iids) g_seen_iids[g_seen_iid_count++] = {k, riid};
    ReleaseSRWLockExclusive(&g_lock);
    if (!first) return;

    char symbol[160], guid[64], where[MAX_PATH + 32], detail[MAX_PATH + 160];
    std::snprintf(symbol, sizeof(symbol), "d3d12_xs!%s::QueryInterface", interface_name(kind));
    format_guid(riid, guid, sizeof(guid));
    describe_address(caller, where, sizeof(where));
    std::snprintf(detail, sizeof(detail), "iid=%s caller=%s -> E_NOINTERFACE", guid, where);
    X2WGfxEvent event{};
    event.kind = X2W_GFX_EVENT_UNKNOWN_IID;
    event.interface_name = interface_name(kind);
    event.symbol = symbol;
    event.detail = detail;
    event.iid = riid;
    event.caller = caller;
    emit(event);
}

void log_note(const char* symbol, const char* detail, const GUID* iid)
{
    X2WGfxEvent event{};
    event.kind = X2W_GFX_EVENT_NOTE;
    event.symbol = symbol;
    event.detail = detail;
    if (iid) event.iid = *iid;
    emit(event);
}

void log_refused(const char* symbol, const char* detail, bool draw)
{
    (draw ? g_draws_refused : g_pipelines_refused).fetch_add(1);
    X2WGfxEvent event{};
    event.kind = X2W_GFX_EVENT_REFUSED;
    event.symbol = symbol;
    event.detail = detail;
    emit(event);
}

void log_refused_call(const char* symbol, const char* detail)
{
    std::uint64_t hash = 1469598103934665603ull;  // FNV-1a over both strings
    for (const char* text : {symbol, "\n", detail})
        for (const char* p = text; p && *p; ++p) hash = (hash ^ static_cast<unsigned char>(*p)) * 1099511628211ull;
    bool first = true;
    AcquireSRWLockExclusive(&g_lock);
    for (unsigned i = 0; i < g_refused_call_count; ++i) first = first && g_refused_calls[i] != hash;
    if (first && g_refused_call_count < max_refused_calls) g_refused_calls[g_refused_call_count++] = hash;
    ReleaseSRWLockExclusive(&g_lock);
    if (!first) return;
    X2WGfxEvent event{};
    event.kind = X2W_GFX_EVENT_REFUSED;
    event.symbol = symbol;
    event.detail = detail;
    emit(event);
}

void count_indirect_rewrite() { g_indirect_rewrites.fetch_add(1); }

void count_texture_miss() { g_texture_misses.fetch_add(1); }
void count_raw(unsigned reads, unsigned uploads, unsigned samplers)
{
    if (reads) g_raw_reads.fetch_add(reads);
    if (uploads) g_raw_uploads.fetch_add(uploads);
    if (samplers) g_raw_samplers.fetch_add(samplers);
}

void count_shader(bool cached) { (cached ? g_shaders_cached : g_shaders_translated).fetch_add(1); }

std::uintptr_t log_unknown_slot(void* self, unsigned slot, const void* caller, std::uintptr_t a1, std::uintptr_t a2,
                                std::uintptr_t a3)
{
    g_unknown_slots.fetch_add(1, std::memory_order_relaxed);
    Kind kind = Kind::count;
    // A thunk is only reachable through one of our tables, so the lookup cannot fail; the guard
    // keeps a stray call from indexing out of bounds.
    if (!wrapper_kind(self, &kind) || slot >= vtable_slots) return static_cast<std::uint32_t>(E_NOTIMPL);
    if (g_slot_seen[static_cast<unsigned>(kind)][slot].exchange(true)) return static_cast<std::uint32_t>(E_NOTIMPL);

    char symbol[160], where[MAX_PATH + 32], detail[MAX_PATH + 192];
    std::snprintf(symbol, sizeof(symbol), "d3d12_xs!%s::slot%u", interface_name(kind), slot);
    describe_address(caller, where, sizeof(where));
    std::snprintf(detail, sizeof(detail), "past %u public slots caller=%s args=0x%llx,0x%llx,0x%llx -> E_NOTIMPL",
                  public_slots(kind), where, static_cast<unsigned long long>(a1), static_cast<unsigned long long>(a2),
                  static_cast<unsigned long long>(a3));
    X2WGfxEvent event{};
    event.kind = X2W_GFX_EVENT_UNKNOWN_SLOT;
    event.slot = slot;
    event.interface_name = interface_name(kind);
    event.symbol = symbol;
    event.detail = detail;
    event.caller = caller;
    event.args[0] = reinterpret_cast<std::uintptr_t>(self);
    event.args[1] = a1;
    event.args[2] = a2;
    event.args[3] = a3;
    emit(event);
    // The HRESULT in EAX, zero-extended: a method returning HRESULT sees a failure. A method
    // returning a pointer or a count sees a non-null value, so the logged line is the one to read.
    return static_cast<std::uint32_t>(E_NOTIMPL);
}

void count_object(int delta) { g_live_objects.fetch_add(static_cast<std::uint32_t>(delta)); }
void count_device() { g_devices.fetch_add(1); }
void count_present() { g_presents.fetch_add(1); }
void set_title_gpu(int state, HRESULT hr)
{
    g_title_gpu_hr.store(hr);
    g_title_gpu_state.store(state);
}

}  // namespace d3d12_xs

extern "C" X2W_GFX_API X2WGfxLogSink WINAPI X2WGfxSetLogSink(X2WGfxLogSink sink, void* context)
{
    using namespace d3d12_xs;
    AcquireSRWLockExclusive(&g_lock);
    X2WGfxLogSink previous = g_sink;
    g_sink = sink;
    g_sink_context = sink ? context : nullptr;
    ReleaseSRWLockExclusive(&g_lock);
    return previous;
}

extern "C" X2W_GFX_API BOOL WINAPI X2WGfxGetCounters(X2WGfxCounters* counters)
{
    using namespace d3d12_xs;
    if (!counters || counters->size < sizeof(X2WGfxCounters)) return FALSE;
    counters->live_objects = g_live_objects.load();
    counters->devices_created = g_devices.load();
    counters->presents = g_presents.load();
    counters->first_uses = g_first_uses.load();
    counters->unknown_slot_calls = g_unknown_slots.load();
    counters->unknown_iid_calls = g_unknown_iids.load();
    counters->title_gpu_state = g_title_gpu_state.load();
    counters->title_gpu_hr = g_title_gpu_hr.load();
    counters->shaders_translated = g_shaders_translated.load();
    counters->shaders_cached = g_shaders_cached.load();
    counters->pipelines_refused = g_pipelines_refused.load();
    counters->draws_refused = g_draws_refused.load();
    counters->title_lookup_misses = pipeline::title_lookup_misses();
    counters->texture_lookup_misses = g_texture_misses.load();
    counters->raw_descriptor_reads = g_raw_reads.load();
    counters->raw_texture_uploads = g_raw_uploads.load();
    counters->raw_samplers_created = g_raw_samplers.load();
    counters->indirect_rewrites = g_indirect_rewrites.load();
    return TRUE;
}
