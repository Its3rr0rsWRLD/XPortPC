// Console-named d3d12_xs.dll exports with no public declaration (docs/design/runtime.md, section 3,
// "Console device creation"), and the per-name logged stubs for exports the shim does not have.
//
// D3D12XboxCreateDevice and D3D12ConfigureVirtualMemoryX are imported by name by a real title. Neither is
// publicly documented, so both take their arguments as raw integers (four registers, four stack slots) and
// log them with the caller and the first bytes of every argument that is a readable pointer, so an owner log
// shows the real contract.
//
// D3D12XboxCreateDevice assumes, by analogy with the public D3D12CreateDevice(adapter, minimum level, REFIID,
// void**), that one argument points at the IID of the requested interface and a later argument is the
// void** that receives it. The first argument pointing at a known device IID (ID3D12Device..ID3D12Device10,
// IUnknown) and the first writable, pointer-aligned argument after it are taken as that pair; the device is
// the one D3D12CreateDevice hands out (desktop default adapter, WARP when that fails), wrapped. Without such
// a pair it returns E_NOTIMPL and logs "d3d12x-create-device unknown-contract".
#include <d3d12.h>
#include <dxgi1_4.h>

#include "d3d12_xs_api.h"
#include "d3d12_xs_wrap.h"

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <utility>

namespace {

using d3d12_xs::describe_caller;
using d3d12_xs::log_note;

constexpr unsigned arg_count = 8;  // RCX, RDX, R8, R9, then the first four stack arguments
constexpr std::size_t dump_bytes = 64;
// Calls logged in full per export; later calls are counted only (both are expected once per process).
constexpr unsigned logged_calls = 16;

const char* const arg_names[arg_count] = {"rcx", "rdx", "r8", "r9", "stack0", "stack1", "stack2", "stack3"};

bool readable_protect(DWORD protect)
{
    if (protect & (PAGE_GUARD | PAGE_NOACCESS)) return false;
    return (protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                       PAGE_EXECUTE_WRITECOPY)) != 0;
}

bool writable_protect(DWORD protect)
{
    if (protect & (PAGE_GUARD | PAGE_NOACCESS)) return false;
    return (protect & (PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) != 0;
}

// Bytes readable at value, at most want (0 when value is not a committed, readable address). Stops at the
// end of the region holding value.
std::size_t readable_bytes(std::uintptr_t value, std::size_t want)
{
    if (value < 0x10000) return 0;
    MEMORY_BASIC_INFORMATION info{};
    if (VirtualQuery(reinterpret_cast<const void*>(value), &info, sizeof(info)) != sizeof(info)) return 0;
    if (info.State != MEM_COMMIT || !readable_protect(info.Protect)) return 0;
    const std::uintptr_t end = reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize;
    return end - value < want ? end - value : want;
}

bool writable_slot(std::uintptr_t value)
{
    if (value < 0x10000 || (value & 7)) return false;
    MEMORY_BASIC_INFORMATION info{};
    if (VirtualQuery(reinterpret_cast<const void*>(value), &info, sizeof(info)) != sizeof(info)) return false;
    if (info.State != MEM_COMMIT || !writable_protect(info.Protect)) return false;
    const std::uintptr_t end = reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize;
    return end - value >= sizeof(void*);
}

// One line with the caller and all arguments, then one line per readable pointer argument.
void log_call(const char* symbol, const std::uintptr_t (&args)[arg_count], const void* caller)
{
    char where[MAX_PATH + 48];
    describe_caller(caller, where, sizeof(where));
    char line[MAX_PATH + 512];
    int n = std::snprintf(line, sizeof(line), "caller=%s", where);
    for (unsigned i = 0; i < arg_count && n > 0 && static_cast<std::size_t>(n) < sizeof(line); ++i) {
        n += std::snprintf(line + n, sizeof(line) - static_cast<std::size_t>(n), " %s=0x%llx", arg_names[i],
                           static_cast<unsigned long long>(args[i]));
    }
    log_note(symbol, line, nullptr);
    for (unsigned i = 0; i < arg_count; ++i) {
        const std::size_t bytes = readable_bytes(args[i], dump_bytes);
        if (!bytes) continue;
        const auto* p = reinterpret_cast<const unsigned char*>(args[i]);
        char dump[dump_bytes * 3 + 128];
        int m = std::snprintf(dump, sizeof(dump), "%s=0x%llx points at %zu readable bytes:", arg_names[i],
                              static_cast<unsigned long long>(args[i]), bytes);
        for (std::size_t b = 0; b < bytes && m > 0 && static_cast<std::size_t>(m) < sizeof(dump); ++b) {
            m += std::snprintf(dump + m, sizeof(dump) - static_cast<std::size_t>(m), " %02x", p[b]);
        }
        log_note(symbol, dump, nullptr);
    }
}

// The first 64 readable bytes at value as little-endian words of `width` bytes (4: dwords, 8: qwords), one line.
void log_words(const char* symbol, const char* name, std::uintptr_t value, unsigned width)
{
    const std::size_t bytes = readable_bytes(value, dump_bytes) / width * width;
    if (!bytes) return;
    char line[dump_bytes * 3 + 128];
    int n = std::snprintf(line, sizeof(line), "%s=0x%llx as %s:", name, static_cast<unsigned long long>(value),
                          width == 4 ? "dwords" : "qwords");
    for (std::size_t off = 0; off < bytes && n > 0 && static_cast<std::size_t>(n) < sizeof(line); off += width) {
        unsigned long long word = 0;
        std::memcpy(&word, reinterpret_cast<const void*>(value + off), width);
        n += std::snprintf(line + n, sizeof(line) - static_cast<std::size_t>(n), width == 4 ? " %08llx" : " %016llx",
                           word);
    }
    log_note(symbol, line, nullptr);
}

struct KnownIid {
    const IID* iid;
    const char* name;
};

const KnownIid known_iids[] = {
    {&__uuidof(ID3D12Device), "ID3D12Device"},     {&__uuidof(ID3D12Device1), "ID3D12Device1"},
    {&__uuidof(ID3D12Device2), "ID3D12Device2"},   {&__uuidof(ID3D12Device3), "ID3D12Device3"},
    {&__uuidof(ID3D12Device4), "ID3D12Device4"},   {&__uuidof(ID3D12Device5), "ID3D12Device5"},
    {&__uuidof(ID3D12Device6), "ID3D12Device6"},   {&__uuidof(ID3D12Device7), "ID3D12Device7"},
    {&__uuidof(ID3D12Device8), "ID3D12Device8"},   {&__uuidof(ID3D12Device9), "ID3D12Device9"},
    {&__uuidof(ID3D12Device10), "ID3D12Device10"}, {&__uuidof(IUnknown), "IUnknown"},
};

const KnownIid* known_iid_at(std::uintptr_t value)
{
    if (readable_bytes(value, sizeof(IID)) < sizeof(IID)) return nullptr;
    for (const KnownIid& known : known_iids) {
        if (std::memcmp(reinterpret_cast<const void*>(value), known.iid, sizeof(IID)) == 0) return &known;
    }
    return nullptr;
}

// The desktop device D3D12CreateDevice would create for a null adapter, or WARP's when there is none.
HRESULT create_desktop_device(ID3D12Device** real, const char** adapter)
{
    *adapter = "default";
    HRESULT hr = D3D12CreateDevice(nullptr, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(real));
    if (SUCCEEDED(hr)) return hr;
    IDXGIFactory4* factory = nullptr;
    IDXGIAdapter* warp = nullptr;
    HRESULT warp_hr = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
    if (SUCCEEDED(warp_hr)) warp_hr = factory->EnumWarpAdapter(IID_PPV_ARGS(&warp));
    if (SUCCEEDED(warp_hr)) warp_hr = D3D12CreateDevice(warp, D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(real));
    if (warp) warp->Release();
    if (factory) factory->Release();
    if (FAILED(warp_hr)) return hr;
    *adapter = "warp";
    return warp_hr;
}

std::atomic<unsigned> g_create_calls;
std::atomic<unsigned> g_configure_calls;

// Unknown exports by name: one thunk per table index, the name copied into the table on first request.
constexpr unsigned max_unknown_exports = 64;
constexpr std::size_t max_export_name = 128;
char g_export_names[max_unknown_exports][max_export_name];
unsigned g_export_count;
std::atomic<bool> g_export_logged[max_unknown_exports];
SRWLOCK g_export_lock = SRWLOCK_INIT;

std::uintptr_t unknown_export_call(unsigned index, const void* caller, std::uintptr_t a0, std::uintptr_t a1,
                                   std::uintptr_t a2, std::uintptr_t a3)
{
    if (index < max_unknown_exports && !g_export_logged[index].exchange(true)) {
        char symbol[max_export_name + 16], where[MAX_PATH + 48], detail[MAX_PATH + 192];
        std::snprintf(symbol, sizeof(symbol), "d3d12_xs!%s", g_export_names[index]);
        describe_caller(caller, where, sizeof(where));
        std::snprintf(detail, sizeof(detail), "unknown export caller=%s args=0x%llx,0x%llx,0x%llx,0x%llx -> E_NOTIMPL",
                      where, static_cast<unsigned long long>(a0), static_cast<unsigned long long>(a1),
                      static_cast<unsigned long long>(a2), static_cast<unsigned long long>(a3));
        d3d12_xs::log_unknown_export(symbol, detail, caller, a0, a1, a2, a3);
    }
    // E_NOTIMPL in EAX, zero-extended, as the vtable slot thunks return it.
    return static_cast<std::uint32_t>(E_NOTIMPL);
}

using ExportThunk = std::uintptr_t(WINAPI*)(std::uintptr_t, std::uintptr_t, std::uintptr_t, std::uintptr_t);

// x64 callers clean nothing on return, so four integer parameters are safe whatever the caller passes.
template <unsigned Index>
std::uintptr_t WINAPI unknown_export(std::uintptr_t a0, std::uintptr_t a1, std::uintptr_t a2, std::uintptr_t a3)
{
    return unknown_export_call(Index, X2W_RETURN_ADDRESS(), a0, a1, a2, a3);
}

template <unsigned... I>
struct ExportThunks {
    static constexpr ExportThunk entries[sizeof...(I)] = {&unknown_export<I>...};
};
template <unsigned... I>
constexpr ExportThunks<I...> make_export_thunks(std::integer_sequence<unsigned, I...>) { return {}; }
using Thunks = decltype(make_export_thunks(std::make_integer_sequence<unsigned, max_unknown_exports>{}));

}  // namespace

extern "C" HRESULT WINAPI d3d12_xs_XboxCreateDevice(std::uintptr_t a0, std::uintptr_t a1, std::uintptr_t a2,
                                                    std::uintptr_t a3, std::uintptr_t s0, std::uintptr_t s1,
                                                    std::uintptr_t s2, std::uintptr_t s3)
{
    const void* caller = X2W_RETURN_ADDRESS();
    const char* symbol = "d3d12_xs!D3D12XboxCreateDevice";
    const std::uintptr_t args[arg_count] = {a0, a1, a2, a3, s0, s1, s2, s3};
    const bool log = g_create_calls.fetch_add(1) < logged_calls;
    if (log) log_call(symbol, args, caller);

    for (unsigned i = 0; i < arg_count; ++i) {
        const KnownIid* known = known_iid_at(args[i]);
        if (!known) continue;
        for (unsigned j = i + 1; j < arg_count; ++j) {
            if (args[j] == args[i] || !writable_slot(args[j])) continue;
            void** out = reinterpret_cast<void**>(args[j]);
            *out = nullptr;
            ID3D12Device* real = nullptr;
            const char* adapter = "default";
            HRESULT hr = create_desktop_device(&real, &adapter);
            if (SUCCEEDED(hr)) hr = d3d12_xs::wrap_device(real, *known->iid, out, caller);
            if (log) {
                char detail[256];
                std::snprintf(detail, sizeof(detail),
                              "d3d12x-create-device contract iid=%s(%s) out=%s(void**) adapter=%s -> 0x%08lx",
                              arg_names[i], known->name, arg_names[j], adapter, static_cast<unsigned long>(hr));
                log_note(symbol, detail, known->iid);
            }
            return hr;
        }
    }
    if (log) {
        log_note(symbol,
                 "d3d12x-create-device unknown-contract: no argument points at a known device IID with a writable "
                 "void** after it -> E_NOTIMPL",
                 nullptr);
    }
    return E_NOTIMPL;
}

extern "C" HRESULT WINAPI d3d12_xs_ConfigureVirtualMemoryX(std::uintptr_t a0, std::uintptr_t a1, std::uintptr_t a2,
                                                           std::uintptr_t a3, std::uintptr_t s0, std::uintptr_t s1,
                                                           std::uintptr_t s2, std::uintptr_t s3)
{
    const void* caller = X2W_RETURN_ADDRESS();
    const std::uintptr_t args[arg_count] = {a0, a1, a2, a3, s0, s1, s2, s3};
    if (g_configure_calls.fetch_add(1) < logged_calls) {
        const char* symbol = "d3d12_xs!D3D12ConfigureVirtualMemoryX";
        log_call(symbol, args, caller);
        // rcx: the struct as dwords (a real title's starts 0, 4); rdx: an array of pointers, as qwords.
        log_words(symbol, "rcx", a0, 4);
        log_words(symbol, "rdx", a1, 8);
        // stack2 was 0x400000000 (16 GiB) in a real title's call: plausibly a size (a virtual range the title wants
        // configured); logged as one so the owner log shows it. Nothing here acts on it.
        if (s2 && !(s2 & 0xffff)) {
            char detail[128];
            std::snprintf(detail, sizeof(detail), "d3d12x-configure-virtual-memory stack2=0x%llx = %llu MiB (if a size)",
                          static_cast<unsigned long long>(s2), static_cast<unsigned long long>(s2 >> 20));
            log_note(symbol, detail, nullptr);
        }
        log_note(symbol,
                 "d3d12x-configure-virtual-memory accepted (no effect on desktop); nothing written through any "
                 "argument -> S_OK",
                 nullptr);
    }
    return S_OK;
}

extern "C" X2W_GFX_API void* WINAPI X2WGfxUnknownExport(const char* name)
{
    if (!name || !*name) return nullptr;
    const std::size_t length = strnlen(name, max_export_name);
    if (length >= max_export_name) return nullptr;
    HMODULE self = nullptr;
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCSTR>(&X2WGfxUnknownExport), &self) &&
        GetProcAddress(self, name)) {
        return nullptr;
    }
    void* thunk = nullptr;
    AcquireSRWLockExclusive(&g_export_lock);
    for (unsigned i = 0; i < g_export_count && !thunk; ++i) {
        if (std::strcmp(g_export_names[i], name) == 0) thunk = reinterpret_cast<void*>(Thunks::entries[i]);
    }
    if (!thunk && g_export_count < max_unknown_exports) {
        std::memcpy(g_export_names[g_export_count], name, length + 1);
        thunk = reinterpret_cast<void*>(Thunks::entries[g_export_count]);
        ++g_export_count;
    }
    ReleaseSRWLockExclusive(&g_export_lock);
    return thunk;
}
