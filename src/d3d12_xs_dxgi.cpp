// DXGI hooks of the d3d12_xs.dll graphics shim (d3d12_xs_wrap.h, install_dxgi_hooks).
//
// A title's dxgi.dll imports resolve to the desktop dxgi.dll, so a title that creates a swap chain hands DXGI the
// command queue the shim gave it: a wrapper DXGI cannot use. Two hooks, installed at the first device creation:
//
// - Swap chain creation. The swap chain methods of DXGI's factory vtables (IDXGIFactory::CreateSwapChain,
//   IDXGIFactory2::CreateSwapChainForHwnd/ForCoreWindow/ForComposition; public method order of dxgi.h/dxgi1_2.h)
//   are replaced in place. A wrapped queue is unwrapped before DXGI sees it, and the swap chain DXGI returns is
//   wrapped (its GetDevice is the wrapped queue, its presents are counted). Any other device argument is passed
//   through untouched. Every call logs one "d3d12x-dxgi-swap-chain" line with the result.
// - Factory creation. The dxgi.dll imports CreateDXGIFactory, CreateDXGIFactory1 and CreateDXGIFactory2 of the image
//   that created the device (the title) are routed through logging wrappers that call the desktop functions, log
//   one "d3d12x-dxgi-factory" line with the result, and install the swap chain hook on the new factory's vtable
//   (a debug factory may use another one). A factory created before the device was not seen; its swap chains are
//   still hooked when its vtable is the one already patched.
//
// The vtables live in dxgi.dll's read-only data; each slot is written once under VirtualProtect and the protection
// is restored. The hooks never change what DXGI does with a desktop queue.
#include <d3d12.h>
#include <dxgi1_4.h>

#include "d3d12_xs_wrap.h"

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace d3d12_xs {
namespace {

// Public vtable slots (IUnknown 0-2, IDXGIObject 3-6, IDXGIFactory 7-11, IDXGIFactory1 12-13, IDXGIFactory2 14-24).
constexpr unsigned slot_create_swap_chain = 10;
constexpr unsigned slot_for_hwnd = 15;
constexpr unsigned slot_for_core_window = 16;
constexpr unsigned slot_for_composition = 24;
constexpr unsigned hooked_slots[] = {slot_create_swap_chain, slot_for_hwnd, slot_for_core_window, slot_for_composition};
constexpr unsigned hook_count = sizeof(hooked_slots) / sizeof(hooked_slots[0]);

struct PatchedTable {
    void** vtable;
    void* original[hook_count];  // null: slot not patched in this table (the interface does not have it)
};
constexpr unsigned max_tables = 8;
PatchedTable g_tables[max_tables];
std::atomic<unsigned> g_table_count;
SRWLOCK g_lock = SRWLOCK_INIT;

constexpr unsigned logged_calls = 64;
std::atomic<unsigned> g_swap_chain_logs;
std::atomic<unsigned> g_factory_logs;

void* original_for(const void* self, unsigned hook)
{
    void** vtable = *static_cast<void** const*>(self);
    AcquireSRWLockShared(&g_lock);
    void* found = nullptr;
    for (unsigned i = 0; i < g_table_count.load() && !found; ++i) {
        if (g_tables[i].vtable == vtable) found = g_tables[i].original[hook];
    }
    ReleaseSRWLockShared(&g_lock);
    return found;
}

void format_guid(const GUID& g, char* out, std::size_t size)
{
    std::snprintf(out, size, "{%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x}", static_cast<unsigned long>(g.Data1),
                  g.Data2, g.Data3, g.Data4[0], g.Data4[1], g.Data4[2], g.Data4[3], g.Data4[4], g.Data4[5], g.Data4[6],
                  g.Data4[7]);
}

void log_swap_chain(const char* method, IUnknown* device, IUnknown* real_queue, const char* shape, HRESULT hr,
                    const void* chain, const void* caller)
{
    if (g_swap_chain_logs.fetch_add(1) >= logged_calls) return;
    char symbol[96], where[MAX_PATH + 48], detail[MAX_PATH + 384];
    std::snprintf(symbol, sizeof(symbol), "dxgi!IDXGIFactory::%s", method);
    describe_caller(caller, where, sizeof(where));
    std::snprintf(detail, sizeof(detail),
                  "d3d12x-dxgi-swap-chain %s device=%s(0x%llx) %s caller=%s -> 0x%08lx swap_chain=%s(0x%llx)", method,
                  real_queue ? "wrapped-queue(unwrapped for DXGI)" : "not-a-shim-queue(passed through)",
                  static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(device)), shape, where,
                  static_cast<unsigned long>(hr), real_queue && SUCCEEDED(hr) ? "wrapped" : "desktop",
                  static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(chain)));
    log_note(symbol, detail, nullptr);
}

void describe_desc1(const DXGI_SWAP_CHAIN_DESC1* desc, char* out, std::size_t size)
{
    if (!desc) {
        std::snprintf(out, size, "desc=null");
        return;
    }
    std::snprintf(out, size, "%ux%u format=%u buffers=%u effect=%u flags=0x%x", desc->Width, desc->Height,
                  static_cast<unsigned>(desc->Format), desc->BufferCount, static_cast<unsigned>(desc->SwapEffect),
                  desc->Flags);
}

// Wraps a swap chain created on an unwrapped queue, through the out pointer DXGI wrote; on failure the out pointer
// is cleared and the error returned.
template <class Chain>
HRESULT finish(IUnknown* device, IUnknown* real_queue, HRESULT hr, Chain** out)
{
    if (!real_queue || FAILED(hr) || !out || !*out) return hr;
    Chain* real = *out;
    *out = nullptr;
    const HRESULT wrap_hr = wrap_dxgi_swap_chain(device, real, __uuidof(Chain), reinterpret_cast<void**>(out));
    return FAILED(wrap_hr) ? wrap_hr : hr;
}

using CreateSwapChainFn = HRESULT(STDMETHODCALLTYPE*)(IDXGIFactory*, IUnknown*, DXGI_SWAP_CHAIN_DESC*,
                                                      IDXGISwapChain**);
using ForHwndFn = HRESULT(STDMETHODCALLTYPE*)(IDXGIFactory2*, IUnknown*, HWND, const DXGI_SWAP_CHAIN_DESC1*,
                                              const DXGI_SWAP_CHAIN_FULLSCREEN_DESC*, IDXGIOutput*, IDXGISwapChain1**);
using ForCoreWindowFn = HRESULT(STDMETHODCALLTYPE*)(IDXGIFactory2*, IUnknown*, IUnknown*, const DXGI_SWAP_CHAIN_DESC1*,
                                                    IDXGIOutput*, IDXGISwapChain1**);
using ForCompositionFn = HRESULT(STDMETHODCALLTYPE*)(IDXGIFactory2*, IUnknown*, const DXGI_SWAP_CHAIN_DESC1*,
                                                     IDXGIOutput*, IDXGISwapChain1**);

HRESULT STDMETHODCALLTYPE hook_create_swap_chain(IDXGIFactory* self, IUnknown* device, DXGI_SWAP_CHAIN_DESC* desc,
                                                 IDXGISwapChain** out)
{
    const auto original = reinterpret_cast<CreateSwapChainFn>(original_for(self, 0));
    if (!original) return E_FAIL;
    IUnknown* real_queue = real_queue_of(device);
    HRESULT hr = original(self, real_queue ? real_queue : device, desc, out);
    hr = finish(device, real_queue, hr, out);
    char shape[160];
    if (desc) {
        std::snprintf(shape, sizeof(shape), "hwnd=0x%llx %ux%u format=%u buffers=%u windowed=%d",
                      static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(desc->OutputWindow)),
                      desc->BufferDesc.Width, desc->BufferDesc.Height, static_cast<unsigned>(desc->BufferDesc.Format),
                      desc->BufferCount, desc->Windowed ? 1 : 0);
    } else {
        std::snprintf(shape, sizeof(shape), "desc=null");
    }
    log_swap_chain("CreateSwapChain", device, real_queue, shape, hr, out ? *out : nullptr, X2W_RETURN_ADDRESS());
    return hr;
}

HRESULT STDMETHODCALLTYPE hook_for_hwnd(IDXGIFactory2* self, IUnknown* device, HWND window,
                                        const DXGI_SWAP_CHAIN_DESC1* desc,
                                        const DXGI_SWAP_CHAIN_FULLSCREEN_DESC* fullscreen, IDXGIOutput* restrict_to,
                                        IDXGISwapChain1** out)
{
    const auto original = reinterpret_cast<ForHwndFn>(original_for(self, 1));
    if (!original) return E_FAIL;
    IUnknown* real_queue = real_queue_of(device);
    HRESULT hr = original(self, real_queue ? real_queue : device, window, desc, fullscreen, restrict_to, out);
    hr = finish(device, real_queue, hr, out);
    char d[96], shape[160];
    describe_desc1(desc, d, sizeof(d));
    std::snprintf(shape, sizeof(shape), "hwnd=0x%llx %s fullscreen_desc=%d",
                  static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(window)), d, fullscreen ? 1 : 0);
    log_swap_chain("CreateSwapChainForHwnd", device, real_queue, shape, hr, out ? *out : nullptr, X2W_RETURN_ADDRESS());
    return hr;
}

HRESULT STDMETHODCALLTYPE hook_for_core_window(IDXGIFactory2* self, IUnknown* device, IUnknown* window,
                                               const DXGI_SWAP_CHAIN_DESC1* desc, IDXGIOutput* restrict_to,
                                               IDXGISwapChain1** out)
{
    const auto original = reinterpret_cast<ForCoreWindowFn>(original_for(self, 2));
    if (!original) return E_FAIL;
    IUnknown* real_queue = real_queue_of(device);
    HRESULT hr = original(self, real_queue ? real_queue : device, window, desc, restrict_to, out);
    hr = finish(device, real_queue, hr, out);
    char d[96], shape[160];
    describe_desc1(desc, d, sizeof(d));
    std::snprintf(shape, sizeof(shape), "core_window=0x%llx %s",
                  static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(window)), d);
    log_swap_chain("CreateSwapChainForCoreWindow", device, real_queue, shape, hr, out ? *out : nullptr,
                   X2W_RETURN_ADDRESS());
    return hr;
}

HRESULT STDMETHODCALLTYPE hook_for_composition(IDXGIFactory2* self, IUnknown* device, const DXGI_SWAP_CHAIN_DESC1* desc,
                                               IDXGIOutput* restrict_to, IDXGISwapChain1** out)
{
    const auto original = reinterpret_cast<ForCompositionFn>(original_for(self, 3));
    if (!original) return E_FAIL;
    IUnknown* real_queue = real_queue_of(device);
    HRESULT hr = original(self, real_queue ? real_queue : device, desc, restrict_to, out);
    hr = finish(device, real_queue, hr, out);
    char shape[96];
    describe_desc1(desc, shape, sizeof(shape));
    log_swap_chain("CreateSwapChainForComposition", device, real_queue, shape, hr, out ? *out : nullptr,
                   X2W_RETURN_ADDRESS());
    return hr;
}

void* const g_hooks[hook_count] = {reinterpret_cast<void*>(&hook_create_swap_chain),
                                   reinterpret_cast<void*>(&hook_for_hwnd),
                                   reinterpret_cast<void*>(&hook_for_core_window),
                                   reinterpret_cast<void*>(&hook_for_composition)};

bool write_slot(void** slot, void* value)
{
    DWORD old = 0;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) return false;
    InterlockedExchangePointer(slot, value);
    DWORD ignored = 0;
    VirtualProtect(slot, sizeof(void*), old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), slot, sizeof(void*));
    return true;
}

// Patches the vtable `factory` uses, once; `slots` is the number of public slots the interface it was obtained as
// has (IDXGIFactory: 12, IDXGIFactory2 and later: 25 or more), so a slot past them is never written.
void patch_vtable(IUnknown* factory, unsigned slots)
{
    void** vtable = *reinterpret_cast<void***>(factory);
    AcquireSRWLockExclusive(&g_lock);
    const unsigned n = g_table_count.load();
    PatchedTable* table = nullptr;
    for (unsigned i = 0; i < n && !table; ++i) {
        if (g_tables[i].vtable == vtable) table = &g_tables[i];
    }
    if (!table && n < max_tables) {
        table = &g_tables[n];
        table->vtable = vtable;
        g_table_count.store(n + 1);
    }
    unsigned patched = 0;
    for (unsigned h = 0; table && h < hook_count; ++h) {
        const unsigned slot = hooked_slots[h];
        if (slot >= slots || table->original[h] || vtable[slot] == g_hooks[h]) continue;
        void* original = vtable[slot];
        table->original[h] = original;
        if (write_slot(&vtable[slot], g_hooks[h])) {
            ++patched;
        } else {
            table->original[h] = nullptr;
        }
    }
    ReleaseSRWLockExclusive(&g_lock);
    if (patched) {
        char detail[160];
        std::snprintf(detail, sizeof(detail), "d3d12x-dxgi-hook factory vtable 0x%llx: %u swap chain slot(s) hooked",
                      static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(vtable)), patched);
        log_note("d3d12_xs!dxgi", detail, nullptr);
    }
}

// Patches every factory interface vtable `factory` answers for (IDXGIFactory..IDXGIFactory4 share one in current
// DXGI; each distinct vtable is patched once).
void patch_factory(IUnknown* factory)
{
    if (!factory) return;
    struct Version {
        const IID* iid;
        unsigned slots;
    };
    const Version versions[] = {{&__uuidof(IDXGIFactory), 12}, {&__uuidof(IDXGIFactory1), 14},
                                {&__uuidof(IDXGIFactory2), 25}, {&__uuidof(IDXGIFactory3), 26},
                                {&__uuidof(IDXGIFactory4), 28}};
    for (const Version& v : versions) {
        IUnknown* as = nullptr;
        if (FAILED(factory->QueryInterface(*v.iid, reinterpret_cast<void**>(&as))) || !as) continue;
        patch_vtable(as, v.slots);
        as->Release();
    }
}

void log_factory(const char* name, UINT flags, REFIID riid, HRESULT hr, void* factory, const void* caller)
{
    if (g_factory_logs.fetch_add(1) >= logged_calls) return;
    char symbol[64], guid[64], where[MAX_PATH + 48], detail[MAX_PATH + 256];
    std::snprintf(symbol, sizeof(symbol), "dxgi!%s", name);
    format_guid(riid, guid, sizeof(guid));
    describe_caller(caller, where, sizeof(where));
    std::snprintf(detail, sizeof(detail), "d3d12x-dxgi-factory %s flags=0x%x iid=%s caller=%s -> 0x%08lx factory=0x%llx",
                  name, flags, guid, where, static_cast<unsigned long>(hr),
                  static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(factory)));
    log_note(symbol, detail, &riid);
}

using Factory0Fn = HRESULT(WINAPI*)(REFIID, void**);
using Factory2Fn = HRESULT(WINAPI*)(UINT, REFIID, void**);
std::atomic<Factory0Fn> g_real_factory;
std::atomic<Factory0Fn> g_real_factory1;
std::atomic<Factory2Fn> g_real_factory2;

HRESULT after_factory(const char* name, UINT flags, REFIID riid, HRESULT hr, void** out, const void* caller)
{
    void* factory = out ? *out : nullptr;
    if (SUCCEEDED(hr) && factory) patch_factory(static_cast<IUnknown*>(factory));
    log_factory(name, flags, riid, hr, factory, caller);
    return hr;
}

HRESULT WINAPI hook_factory(REFIID riid, void** out)
{
    const Factory0Fn real = g_real_factory.load();
    const HRESULT hr = real ? real(riid, out) : E_FAIL;
    return after_factory("CreateDXGIFactory", 0, riid, hr, out, X2W_RETURN_ADDRESS());
}

HRESULT WINAPI hook_factory1(REFIID riid, void** out)
{
    const Factory0Fn real = g_real_factory1.load();
    const HRESULT hr = real ? real(riid, out) : E_FAIL;
    return after_factory("CreateDXGIFactory1", 0, riid, hr, out, X2W_RETURN_ADDRESS());
}

HRESULT WINAPI hook_factory2(UINT flags, REFIID riid, void** out)
{
    const Factory2Fn real = g_real_factory2.load();
    const HRESULT hr = real ? real(flags, riid, out) : E_FAIL;
    return after_factory("CreateDXGIFactory2", flags, riid, hr, out, X2W_RETURN_ADDRESS());
}

// The base of the image holding `address`: a loader module, or an image pe_map mapped (allocation base with "MZ").
HMODULE image_of(const void* address)
{
    HMODULE module = nullptr;
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCSTR>(address), &module)) {
        return module;
    }
    MEMORY_BASIC_INFORMATION info{};
    if (VirtualQuery(address, &info, sizeof(info)) != sizeof(info) || !info.AllocationBase || info.State != MEM_COMMIT)
        return nullptr;
    MEMORY_BASIC_INFORMATION head{};
    if (VirtualQuery(info.AllocationBase, &head, sizeof(head)) != sizeof(head) || head.State != MEM_COMMIT ||
        (head.Protect & (PAGE_NOACCESS | PAGE_GUARD)) || *static_cast<const std::uint16_t*>(info.AllocationBase) != 0x5a4d)
        return nullptr;
    return static_cast<HMODULE>(info.AllocationBase);
}

bool readable(const void* p, std::size_t bytes)
{
    MEMORY_BASIC_INFORMATION info{};
    if (VirtualQuery(p, &info, sizeof(info)) != sizeof(info) || info.State != MEM_COMMIT ||
        (info.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return false;
    const auto end = reinterpret_cast<std::uintptr_t>(info.BaseAddress) + info.RegionSize;
    return reinterpret_cast<std::uintptr_t>(p) + bytes <= end;
}

// Routes the image's dxgi.dll factory imports through the logging wrappers. Returns the number of entries changed.
unsigned route_factory_imports(HMODULE image, HMODULE dxgi)
{
    auto* base = reinterpret_cast<unsigned char*>(image);
    const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (!readable(dos, sizeof(*dos)) || dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(base + dos->e_lfanew);
    if (!readable(nt, sizeof(*nt)) || nt->Signature != IMAGE_NT_SIGNATURE ||
        nt->OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC)
        return 0;
    const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress || !dir.Size) return 0;
    struct Target {
        const char* name;
        void* real;
        void* hook;
    };
    const Target targets[] = {
        {"CreateDXGIFactory", reinterpret_cast<void*>(GetProcAddress(dxgi, "CreateDXGIFactory")),
         reinterpret_cast<void*>(&hook_factory)},
        {"CreateDXGIFactory1", reinterpret_cast<void*>(GetProcAddress(dxgi, "CreateDXGIFactory1")),
         reinterpret_cast<void*>(&hook_factory1)},
        {"CreateDXGIFactory2", reinterpret_cast<void*>(GetProcAddress(dxgi, "CreateDXGIFactory2")),
         reinterpret_cast<void*>(&hook_factory2)},
    };
    unsigned changed = 0;
    for (auto* desc = reinterpret_cast<const IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress);
         readable(desc, sizeof(*desc)) && desc->Name; ++desc) {
        const char* module = reinterpret_cast<const char*>(base + desc->Name);
        if (!readable(module, 9) || _stricmp(module, "dxgi.dll") != 0) continue;
        auto* iat = reinterpret_cast<void**>(base + desc->FirstThunk);
        for (; readable(iat, sizeof(void*)) && *iat; ++iat) {
            // By resolved address: the loader (or pe_map) already bound the entry to the desktop function.
            for (const Target& t : targets) {
                if (!t.real || *iat != t.real) continue;
                if (write_slot(iat, t.hook)) ++changed;
            }
        }
    }
    return changed;
}

constexpr unsigned max_images = 16;
HMODULE g_images[max_images];
unsigned g_image_count;
SRWLOCK g_image_lock = SRWLOCK_INIT;
INIT_ONCE g_once = INIT_ONCE_STATIC_INIT;

BOOL CALLBACK install_once(PINIT_ONCE, PVOID, PVOID*)
{
    // A factory of our own: its vtable is the one titles' factories use.
    HMODULE dxgi = LoadLibraryW(L"dxgi.dll");
    if (!dxgi) return TRUE;
    g_real_factory.store(reinterpret_cast<Factory0Fn>(reinterpret_cast<void*>(GetProcAddress(dxgi, "CreateDXGIFactory"))));
    g_real_factory1.store(
        reinterpret_cast<Factory0Fn>(reinterpret_cast<void*>(GetProcAddress(dxgi, "CreateDXGIFactory1"))));
    g_real_factory2.store(
        reinterpret_cast<Factory2Fn>(reinterpret_cast<void*>(GetProcAddress(dxgi, "CreateDXGIFactory2"))));
    IDXGIFactory2* factory = nullptr;
    const Factory2Fn create = g_real_factory2.load();
    if (create && SUCCEEDED(create(0, __uuidof(IDXGIFactory2), reinterpret_cast<void**>(&factory))) && factory) {
        patch_factory(factory);
        factory->Release();
    } else {
        log_note("d3d12_xs!dxgi", "d3d12x-dxgi-hook no DXGI factory; swap chain creation not hooked", nullptr);
    }
    return TRUE;
}

}  // namespace

void install_dxgi_hooks(const void* caller)
{
    InitOnceExecuteOnce(&g_once, install_once, nullptr, nullptr);
    HMODULE image = caller ? image_of(caller) : nullptr;
    HMODULE self = image_of(reinterpret_cast<const void*>(&install_dxgi_hooks));
    HMODULE dxgi = GetModuleHandleW(L"dxgi.dll");
    if (!image || image == self || !dxgi) return;
    AcquireSRWLockExclusive(&g_image_lock);
    bool seen = false;
    for (unsigned i = 0; i < g_image_count; ++i) seen = seen || g_images[i] == image;
    if (!seen && g_image_count < max_images) g_images[g_image_count++] = image;
    ReleaseSRWLockExclusive(&g_image_lock);
    if (seen) return;
    const unsigned changed = route_factory_imports(image, dxgi);
    char where[MAX_PATH + 48], detail[MAX_PATH + 160];
    describe_caller(image, where, sizeof(where));
    std::snprintf(detail, sizeof(detail), "d3d12x-dxgi-hook image %s: %u dxgi.dll factory import(s) routed through logging",
                  where, changed);
    log_note("d3d12_xs!dxgi", detail, nullptr);
}

}  // namespace d3d12_xs
