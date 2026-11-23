// Console-named d3d12_xs.dll exports with no public declaration (docs/design/runtime.md, section 3,
// "Console device creation"), and the per-name logged stubs for exports the shim does not have.
//
// D3D12XboxCreateDevice and D3D12ConfigureVirtualMemoryX are imported by name by a real title. Neither is
// publicly documented, so both take their arguments as raw integers (four registers, four stack slots) and
// log them with the caller and the first bytes of every argument that is a readable pointer, so an owner log
// shows the real contract.
//
// D3D12XboxCreateDevice assumes, by analogy with the public D3D12CreateDevice(adapter, minimum level, REFIID,
// void**), that one argument (or a field of a creation-parameters struct an argument points at) is the IID of the
// requested interface and another argument (or struct field) is the void** that receives it; find_contract lists
// the search order, ending with two assumed shapes, (params*, REFIID, void**) and (REFIID, params*, void**), that
// accept an IID the shim does not know. The device is the one D3D12CreateDevice hands out (desktop default
// adapter, WARP when that fails), wrapped. Every call logs the first 128 bytes of each readable pointer argument
// as dwords and one "d3d12x-create-device contract ..." line naming where the IID and the out slot were found.
// Without any fit it returns E_NOTIMPL and logs "d3d12x-create-device unknown-contract".
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
// D3D12XboxCreateDevice: bytes of every readable pointer argument logged as dwords, and searched for an IID.
constexpr std::size_t create_dump_bytes = 128;
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
void log_call(const char* symbol, const std::uintptr_t (&args)[arg_count], const void* caller, bool hexdump = true)
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
    for (unsigned i = 0; hexdump && i < arg_count; ++i) {
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

// The first `limit` readable bytes at value as little-endian words of `width` bytes (4: dwords, 8: qwords), one line.
void log_words(const char* symbol, const char* name, std::uintptr_t value, unsigned width,
               std::size_t limit = dump_bytes)
{
    const std::size_t bytes = readable_bytes(value, limit) / width * width;
    if (!bytes) return;
    char line[create_dump_bytes * 3 + 160];
    int n = std::snprintf(line, sizeof(line), "%s=0x%llx as %s (%zu bytes):", name,
                          static_cast<unsigned long long>(value), width == 4 ? "dwords" : "qwords", bytes);
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

void format_guid(const GUID& g, char* out, std::size_t size)
{
    std::snprintf(out, size, "{%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x}", static_cast<unsigned long>(g.Data1),
                  g.Data2, g.Data3, g.Data4[0], g.Data4[1], g.Data4[2], g.Data4[3], g.Data4[4], g.Data4[5], g.Data4[6],
                  g.Data4[7]);
}

// How D3D12XboxCreateDevice's arguments were read: where the IID and the void** were found.
struct Contract {
    GUID iid{};
    const KnownIid* known = nullptr;  // null: an IID the shim does not know (assumed contract)
    std::uintptr_t out = 0;
    bool assumed = false;
    const char* shape = "";  // the assumed shape's name
    char iid_where[48]{};
    char out_where[48]{};
};

// Among the candidate void** slots, the first that holds null (a title clears its out pointer, or a ComPtr starts
// empty), else the first. A params struct passed beside the out slot is writable too but usually not null at +0.
std::uintptr_t pick_out(const std::uintptr_t* slots, unsigned count, unsigned* picked)
{
    for (unsigned k = 0; k < count; ++k) {
        if (*reinterpret_cast<void* const*>(slots[k]) == nullptr) {
            *picked = k;
            return slots[k];
        }
    }
    *picked = 0;
    return count ? slots[0] : 0;
}

// The contract search, in order:
//  1. an argument pointing at a known IID, and a writable void** argument after it;
//  2. a known IID inside the first create_dump_bytes of a pointed-at struct in writable memory whose first qword is not
//     null (inline, or a pointer to it at an 8-aligned offset), and a writable void** argument other than the struct (or, failing that, a pointer to a writable
//     void** at an 8-aligned offset of the same struct);
//  3. assumed (params*, REFIID, void**): rdx points at 16 readable bytes and r8 is a writable void** holding null;
//  4. assumed (REFIID, params*, void**): rcx points at 16 readable bytes and r8 is a writable void** holding null.
bool find_contract(const std::uintptr_t (&args)[arg_count], Contract* c)
{
    // 1.
    for (unsigned i = 0; i < arg_count; ++i) {
        const KnownIid* known = known_iid_at(args[i]);
        if (!known) continue;
        std::uintptr_t slots[arg_count];
        unsigned slot_args[arg_count], n = 0;
        for (unsigned j = i + 1; j < arg_count; ++j) {
            if (args[j] == args[i] || !writable_slot(args[j])) continue;
            slot_args[n] = j;
            slots[n++] = args[j];
        }
        if (!n) continue;
        unsigned picked = 0;
        c->out = pick_out(slots, n, &picked);
        c->known = known;
        c->iid = *known->iid;
        std::snprintf(c->iid_where, sizeof(c->iid_where), "%s", arg_names[i]);
        std::snprintf(c->out_where, sizeof(c->out_where), "%s", arg_names[slot_args[picked]]);
        return true;
    }
    // 2.
    for (unsigned i = 0; i < arg_count; ++i) {
        // Only a struct in writable memory (stack, heap or data): IID constants sit together in read-only data, so
        // the bytes after one unknown IID can hold a known one that is no argument.
        const std::size_t bytes = readable_bytes(args[i], create_dump_bytes);
        // A writable slot holding null is taken for an out pointer, not a struct: scanning past it would read the
        // caller's neighbouring locals.
        if (bytes < sizeof(IID) || !writable_slot(args[i] & ~std::uintptr_t{7})) continue;
        if (writable_slot(args[i]) && *reinterpret_cast<void* const*>(args[i]) == nullptr) continue;
        const KnownIid* known = nullptr;
        std::size_t at = 0;
        bool inline_iid = false;
        for (std::size_t off = 0; off + sizeof(IID) <= bytes && !known; off += 4) {
            if ((known = known_iid_at(args[i] + off)) != nullptr) {
                at = off;
                inline_iid = true;
            }
        }
        for (std::size_t off = 0; off + 8 <= bytes && !known; off += 8) {
            std::uintptr_t p = 0;
            std::memcpy(&p, reinterpret_cast<const void*>(args[i] + off), 8);
            if (p != args[i] && (known = known_iid_at(p)) != nullptr) at = off;
        }
        if (!known) continue;
        std::uintptr_t slots[arg_count];
        unsigned slot_args[arg_count], n = 0;
        for (unsigned j = 0; j < arg_count; ++j) {
            if (j == i || args[j] == args[i] || !writable_slot(args[j]) || known_iid_at(args[j])) continue;
            slot_args[n] = j;
            slots[n++] = args[j];
        }
        c->known = known;
        c->iid = *known->iid;
        std::snprintf(c->iid_where, sizeof(c->iid_where), inline_iid ? "%s+0x%zx" : "%s->[+0x%zx]", arg_names[i], at);
        if (n) {
            unsigned picked = 0;
            c->out = pick_out(slots, n, &picked);
            std::snprintf(c->out_where, sizeof(c->out_where), "%s", arg_names[slot_args[picked]]);
            return true;
        }
        for (std::size_t off = 0; off + 8 <= bytes; off += 8) {
            std::uintptr_t p = 0;
            std::memcpy(&p, reinterpret_cast<const void*>(args[i] + off), 8);
            if (p == args[i] || (inline_iid && off + 8 > at && off < at + sizeof(IID)) || !writable_slot(p) ||
                known_iid_at(p)) {
                continue;
            }
            c->out = p;
            std::snprintf(c->out_where, sizeof(c->out_where), "%s->[+0x%zx]", arg_names[i], off);
            return true;
        }
    }
    // 3. and 4.
    struct Shape {
        unsigned iid, out;
        const char* name;
    };
    const Shape shapes[] = {{1, 2, "(params*, REFIID, void**)"}, {0, 2, "(REFIID, params*, void**)"}};
    for (const Shape& shape : shapes) {
        const std::uintptr_t iid = args[shape.iid], out = args[shape.out];
        // The out slot must hold null (a cleared out pointer), so a writable GUID or struct in that position is not
        // taken for one.
        if (readable_bytes(iid, sizeof(IID)) < sizeof(IID) || !writable_slot(out) || out == iid ||
            *reinterpret_cast<void* const*>(out) != nullptr) {
            continue;
        }
        std::memcpy(&c->iid, reinterpret_cast<const void*>(iid), sizeof(IID));
        c->known = known_iid_at(iid);
        c->assumed = true;
        c->out = out;
        c->shape = shape.name;
        std::snprintf(c->iid_where, sizeof(c->iid_where), "%s", arg_names[shape.iid]);
        std::snprintf(c->out_where, sizeof(c->out_where), "%s", arg_names[shape.out]);
        return true;
    }
    return false;
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
    if (log) {
        log_call(symbol, args, caller, false);
        for (unsigned i = 0; i < arg_count; ++i) log_words(symbol, arg_names[i], args[i], 4, create_dump_bytes);
    }

    Contract contract;
    if (!find_contract(args, &contract)) {
        if (log) {
            log_note(symbol,
                     "d3d12x-create-device unknown-contract: no known device IID (as an argument or inside a "
                     "pointed-at struct) with a writable void**, and neither (params*, REFIID, void**) nor (REFIID, "
                     "params*, void**) fits -> E_NOTIMPL",
                     nullptr);
        }
        return E_NOTIMPL;
    }
    void** out = reinterpret_cast<void**>(contract.out);
    *out = nullptr;
    ID3D12Device* real = nullptr;
    const char* adapter = "default";
    HRESULT hr = create_desktop_device(&real, &adapter);
    // An IID the shim does not know (an assumed contract) hands out the device wrapper as ID3D12Device, whose vtable
    // is the start of the wrapper's, and makes the device answer QueryInterface for that IID from then on.
    if (SUCCEEDED(hr) && !contract.known) d3d12_xs::alias_device_iid(contract.iid);
    if (SUCCEEDED(hr)) hr = d3d12_xs::wrap_device(real, contract.known ? *contract.known->iid : __uuidof(ID3D12Device),
                                                  out, caller);
    if (log) {
        char guid[64], detail[512];
        format_guid(contract.iid, guid, sizeof(guid));
        std::snprintf(detail, sizeof(detail),
                      "d3d12x-create-device contract iid=%s(%s) out=%s(void**)%s%s adapter=%s iid_value=%s -> 0x%08lx",
                      contract.iid_where, contract.known ? contract.known->name : "unknown", contract.out_where,
                      contract.assumed ? " assumed " : "", contract.shape, adapter, guid, static_cast<unsigned long>(hr));
        log_note(symbol, detail, &contract.iid);
    }
    return hr;
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
