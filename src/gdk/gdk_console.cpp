// Console-only libraries with no public documentation or desktop equivalent (docs/design/runtime.md,
// "Console audio hardware: silent"): xcrdapi.dll (DirectStorage entry), chad.dll / xapu.dll / acphal.dll (audio
// hardware) and xg_xs.dll (texture layout). Their signatures are NOT public, so each one is a logged stub that
// accepts six register-width arguments, never dereferences an argument without a VirtualQuery check, and succeeds.
// Nothing here comes from SDK headers or from title files; every shape below is a stated assumption.
#include "gdk_internal.h"

#include <algorithm>
#include <atomic>
#include <intrin.h>
#include <map>
#include <mutex>
#include <utility>

namespace {

// ---- logging: the first calls of each function with their arguments, then one note ---------------------------
constexpr int kLoggedCalls = 8;

void log_call(const char* symbol, std::atomic<int>& calls, uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3,
              const void* caller) noexcept
{
    const int n = calls.fetch_add(1);
    if (n < kLoggedCalls)
        x2w_stub_called(symbol, x2w::format("call %d rcx=0x%llx rdx=0x%llx r8=0x%llx r9=0x%llx", n + 1,
                                            (unsigned long long)a0, (unsigned long long)a1, (unsigned long long)a2,
                                            (unsigned long long)a3).c_str(), caller);
    else if (n == kLoggedCalls)
        x2w_note(symbol, "further calls are not logged");
}

#define X2W_LOG_CALL(symbol) \
    do { \
        static std::atomic<int> x2w_calls{0}; \
        log_call(symbol, x2w_calls, a0, a1, a2, a3, _ReturnAddress()); \
    } while (0)

// True when [p, p+bytes) is committed, writable memory (a guard page or no-access page is not).
bool writable(const void* p, size_t bytes) noexcept
{
    if (!p) return false;
    auto at = reinterpret_cast<uintptr_t>(p);
    const uintptr_t end = at + bytes;
    if (end < at) return false;
    while (at < end) {
        MEMORY_BASIC_INFORMATION info{};
        if (VirtualQuery(reinterpret_cast<void*>(at), &info, sizeof(info)) != sizeof(info) || info.State != MEM_COMMIT ||
            (info.Protect & (PAGE_GUARD | PAGE_NOACCESS)) ||
            !(info.Protect & (PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)))
            return false;
        at = reinterpret_cast<uintptr_t>(info.BaseAddress) + info.RegionSize;
    }
    return true;
}

// ---- fake handles: small zeroed blocks, distinct and non-null, safe to read as zeros --------------------------
uintptr_t make_handle() noexcept
{
    return reinterpret_cast<uintptr_t>(HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, 256));
}

// Writes a fresh handle to the first argument that points to writable, zero-initialised 8 bytes (an output slot).
void write_handle(const uintptr_t (&args)[4]) noexcept
{
    for (uintptr_t a : args) {
        if (a && a >= 0x10000 && writable(reinterpret_cast<void*>(a), sizeof(uintptr_t)) &&
            *reinterpret_cast<const uintptr_t*>(a) == 0) {
            if (const uintptr_t handle = make_handle()) *reinterpret_cast<uintptr_t*>(a) = handle;
            return;
        }
    }
}

// ---- tracked APU memory ----------------------------------------------------------------------------------------
std::mutex g_apu_lock;
std::map<uintptr_t, size_t> g_apu;  // base -> bytes

uintptr_t apu_track(size_t bytes) noexcept
{
    void* p = VirtualAlloc(nullptr, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!p) return 0;
    std::lock_guard<std::mutex> lock(g_apu_lock);
    try {
        g_apu.emplace(reinterpret_cast<uintptr_t>(p), bytes);
    } catch (...) {
        VirtualFree(p, 0, MEM_RELEASE);
        return 0;
    }
    return reinterpret_cast<uintptr_t>(p);
}

bool apu_tracked_base(uintptr_t a)
{
    std::lock_guard<std::mutex> lock(g_apu_lock);
    return g_apu.count(a) != 0;
}

bool apu_contains(uintptr_t a)
{
    std::lock_guard<std::mutex> lock(g_apu_lock);
    auto it = g_apu.upper_bound(a);
    if (it == g_apu.begin()) return false;
    --it;
    return a < it->first + it->second;
}

// The size of a request: the first argument in (0, 1 GiB] that is not a tracked heap or allocation.
size_t apu_request_bytes(const uintptr_t (&args)[4]) noexcept
{
    for (uintptr_t a : args)
        if (a && a <= (uintptr_t{1} << 30) && !apu_tracked_base(a)) return static_cast<size_t>(a);
    return 64 * 1024;
}

// ---- the texture computer object: IUnknown + 64 logging slots --------------------------------------------------
constexpr size_t kSlots = 64;
HRESULT (STDMETHODCALLTYPE* g_vtable[3 + kSlots])();  // filled once

// IID_IUnknown, spelled out: WIN32_LEAN_AND_MEAN leaves IUnknown undeclared and uuid.lib is not linked.
const GUID kIUnknown = {0, 0, 0, {0xC0, 0, 0, 0, 0, 0, 0, 0x46}};

struct TextureComputer {
    const void* const* vtable;
    LONG refs;
};

HRESULT STDMETHODCALLTYPE tc_query(TextureComputer* self, const IID& iid, void** out)
{
    if (!out) return E_POINTER;
    if (IsEqualGUID(iid, kIUnknown)) {
        InterlockedIncrement(&self->refs);
        *out = self;
        return S_OK;
    }
    *out = nullptr;
    x2w_unimplemented("xg_xs!XGTextureComputer::QueryInterface", "interface other than IUnknown; E_NOINTERFACE");
    return E_NOINTERFACE;
}
ULONG STDMETHODCALLTYPE tc_addref(TextureComputer* self) { return static_cast<ULONG>(InterlockedIncrement(&self->refs)); }
ULONG STDMETHODCALLTYPE tc_release(TextureComputer* self)
{
    const LONG left = InterlockedDecrement(&self->refs);
    if (left == 0) HeapFree(GetProcessHeap(), 0, self);
    return static_cast<ULONG>(left);
}

template <size_t N>
HRESULT STDMETHODCALLTYPE tc_slot(void* self, uintptr_t a1, uintptr_t a2, uintptr_t a3)
{
    static std::atomic<int> calls{0};
    const std::string name = x2w::format("xg_xs!XGTextureComputer::slot%zu", N);
    log_call(name.c_str(), calls, reinterpret_cast<uintptr_t>(self), a1, a2, a3, _ReturnAddress());
    return E_NOTIMPL;
}

template <size_t... I>
void fill_slots(std::index_sequence<I...>)
{
    ((g_vtable[3 + I] = reinterpret_cast<HRESULT(STDMETHODCALLTYPE*)()>(&tc_slot<I>)), ...);
}

const void* const* texture_computer_vtable()
{
    static std::once_flag once;
    std::call_once(once, [] {
        g_vtable[0] = reinterpret_cast<HRESULT(STDMETHODCALLTYPE*)()>(&tc_query);
        g_vtable[1] = reinterpret_cast<HRESULT(STDMETHODCALLTYPE*)()>(&tc_addref);
        g_vtable[2] = reinterpret_cast<HRESULT(STDMETHODCALLTYPE*)()>(&tc_release);
        fill_slots(std::make_index_sequence<kSlots>{});
    });
    return reinterpret_cast<const void* const*>(g_vtable);
}

}  // namespace

// ---- xcrdapi.dll -----------------------------------------------------------------------------------------------
// https://github.com/microsoft/DirectStorage#readme : DStorageGetFactory(REFIID, void**). Forwarded to x2w_sys.dll's
// X2wDStorageGetFactory (src/sys/sys_dstorage.cpp), loaded from this DLL's folder when the launcher has not loaded it.
X2W_GDK_API HRESULT x2w_impl_DStorageGetFactory(REFIID riid, void** factory) noexcept
{
    using Fn = HRESULT(WINAPI*)(REFIID, void**);
    static Fn fn = [] () -> Fn {
        HMODULE sys = GetModuleHandleW(L"x2w_sys.dll");
        if (!sys) {
            HMODULE self = nullptr;
            wchar_t path[MAX_PATH]{};
            if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   reinterpret_cast<LPCWSTR>(&x2w_impl_DStorageGetFactory), &self) &&
                GetModuleFileNameW(self, path, MAX_PATH)) {
                std::wstring dir(path);
                dir.resize(dir.find_last_of(L'\\') == std::wstring::npos ? 0 : dir.find_last_of(L'\\') + 1);
                sys = LoadLibraryExW((dir + L"x2w_sys.dll").c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
            }
        }
        return sys ? reinterpret_cast<Fn>(GetProcAddress(sys, "X2wDStorageGetFactory")) : nullptr;
    }();
    if (!fn) {
        x2w_unimplemented("xcrdapi!DStorageGetFactory", "x2w_sys.dll with X2wDStorageGetFactory not found; E_NOTIMPL");
        if (factory) *factory = nullptr;
        return E_NOTIMPL;
    }
    return fn(riid, factory);
}

// ---- chad.dll, xapu.dll: connect-style calls hand out a fake handle, the rest succeed ---------------------------
#define X2W_PLAIN(name, symbol) \
    X2W_GDK_API HRESULT x2w_impl_##name(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept \
    { \
        X2W_LOG_CALL(symbol); \
        return S_OK; \
    }
#define X2W_HANDLE(name, symbol) \
    X2W_GDK_API HRESULT x2w_impl_##name(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept \
    { \
        X2W_LOG_CALL(symbol); \
        write_handle({a0, a1, a2, a3}); \
        return S_OK; \
    }

X2W_PLAIN(XDspActivate, "chad!XDspActivate")
X2W_HANDLE(XDspConnectWithMaximumStreamLimit, "chad!XDspConnectWithMaximumStreamLimit")
X2W_PLAIN(XDspDeactivate, "chad!XDspDeactivate")
X2W_PLAIN(XDspDisconnect, "chad!XDspDisconnect")
X2W_PLAIN(XDspSubmitCommand, "chad!XDspSubmitCommand")

X2W_HANDLE(XApuConnect, "xapu!XApuConnect")
X2W_PLAIN(XApuDequeueResult, "xapu!XApuDequeueResult")
X2W_PLAIN(XApuDisconnect, "xapu!XApuDisconnect")
X2W_PLAIN(XApuEnqueueCommand, "xapu!XApuEnqueueCommand")
X2W_GDK_API uint32_t x2w_impl_XApuGetResultCount(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("xapu!XApuGetResultCount");
    return 0;
}

// ---- acphal.dll -------------------------------------------------------------------------------------------------
X2W_HANDLE(AcpHalAllocateShapeContexts, "acphal!AcpHalAllocateShapeContexts")
X2W_HANDLE(AcpHalCreate, "acphal!AcpHalCreate")
X2W_PLAIN(AcpHalReleaseShapeContexts, "acphal!AcpHalReleaseShapeContexts")

// ApuAlloc / ApuCreateHeap: VirtualAlloc'd, zeroed, tracked; the pointer is the return value (assumed).
X2W_GDK_API uintptr_t x2w_impl_ApuAlloc(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("acphal!ApuAlloc");
    return apu_track(apu_request_bytes({a0, a1, a2, a3}));
}
X2W_GDK_API uintptr_t x2w_impl_ApuCreateHeap(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("acphal!ApuCreateHeap");
    return apu_track(apu_request_bytes({a0, a1, a2, a3}));
}
X2W_GDK_API HRESULT x2w_impl_ApuFree(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("acphal!ApuFree");
    for (uintptr_t a : {a0, a1}) {
        std::lock_guard<std::mutex> lock(g_apu_lock);
        auto it = g_apu.find(a);
        if (it != g_apu.end()) {
            VirtualFree(reinterpret_cast<void*>(a), 0, MEM_RELEASE);
            g_apu.erase(it);
            break;
        }
    }
    return S_OK;
}
X2W_GDK_API BOOL x2w_impl_ApuIsVirtualAddressValid(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("acphal!ApuIsVirtualAddressValid");
    return apu_contains(a0) || apu_contains(a1);
}
X2W_GDK_API uintptr_t x2w_impl_ApuMapApuAddress(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("acphal!ApuMapApuAddress");
    return a0;
}
X2W_GDK_API uintptr_t x2w_impl_ApuMapVirtualAddress(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("acphal!ApuMapVirtualAddress");
    return a0;
}

// ---- xg_xs.dll --------------------------------------------------------------------------------------------------
// Assumed shape (the public XG texture-address computers are (desc, &computer)): the object goes to the second argument.
X2W_GDK_API HRESULT x2w_impl_XGCreateTextureComputer(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("xg_xs!XGCreateTextureComputer");
    if (!writable(reinterpret_cast<void*>(a1), sizeof(void*))) return E_POINTER;
    auto* object = static_cast<TextureComputer*>(HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(TextureComputer)));
    if (!object) return E_OUTOFMEMORY;
    object->vtable = texture_computer_vtable();
    object->refs = 1;
    *reinterpret_cast<void**>(a1) = object;
    return S_OK;
}
// 0 is the conservative answer: the linear/standard mode (assumed enum value; docs/design/runtime.md).
X2W_GDK_API uint32_t x2w_impl_XGSuggestSwizzleMode(uintptr_t a0, uintptr_t a1, uintptr_t a2, uintptr_t a3, uintptr_t, uintptr_t) noexcept
{
    X2W_LOG_CALL("xg_xs!XGSuggestSwizzleMode");
    return 0;
}
