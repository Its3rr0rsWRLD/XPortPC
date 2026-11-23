// xgameruntime.dll gateway (docs/design/runtime.md, section 2, "The Gaming Runtime gateway").
//
// A PC GDK title's static xgameruntime.lib loads xgameruntime.dll and calls six exports:
// InitializeApiImpl, InitializeApiImplEx, InitializeApiImplEx2, UninitializeApiImpl, QueryApiImpl and
// XErrorReport. Each flat API call becomes QueryApiImpl(CLSID_XFooImpl, IID_IXFooImpl, &object) and a
// call through the object's vtable: IUnknown, then the family's flat functions in a fixed, append-only
// order. This DLL answers those queries. It is built as shims\x2w_xgr.dll; x2w_launch --xgr MODE routes
// the title's load of xgameruntime.dll to it and sets X2W_XGR_MODE:
//
//   ours    (default) the classes and slots learned into tools/xgr/interfaces.toml (generated into
//           xgr_table.inc by tools/xgr_gen.py) forward into x2w_gdk.dll's family implementations.
//           An unknown CLSID or IID returns 0x80070032 (HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED)) and is
//           logged with its caller; a slot with no implementation logs its index and returns E_NOTIMPL.
//   trace   every query goes to Windows' own xgameruntime.dll (System32) and the returned interface is
//           wrapped in a proxy whose slots log their index, arguments, caller and result, then call the
//           real slot. This is how the table was learned (the dummy-object technique, but forwarding).
//   record  every query gets a dummy object whose slots only log and return E_NOTIMPL.
//
// Every object's vtable is xgr_stub_table (xgr_thunks.asm): one logging thunk per slot, so no slot
// index can jump into unmapped memory. Log lines go to stderr as "[x2w] xgr-..." and, under x2w_launch,
// into the run log as "shim-xgr-..." lines:
//   xgr-init FUNCTION gdk=.. gs=.. mode=0x.. options=.. -> HRESULT
//   xgr-query CLSID IID NAME -> HRESULT  caller=..            (once per distinct line)
//   xgr-call NAME slot N rcx.. args a1 a2 a3 a4 a5 a6 -> RESULT caller=..   (first X2W_XGR_CALLS per slot+caller, default 4)
//   xgr-unknown-slot NAME slot N caller=..                    (once per slot+caller)
//   xgr-summary NAME slot N calls C                           (at UninitializeApiImpl and process detach)
// X2W_XGR_CALLS=0 turns the per-call lines off in ours mode; trace and record log them by default.
#include <windows.h>
#include <intrin.h>

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include "x2w_gdk.h"

extern "C" void* const xgr_stub_table[];
constexpr unsigned xgr_slots = 256;  // XGR_SLOTS in xgr_thunks.asm

struct XgrClass {
    const char* name;
    GUID clsid;
    void* const* targets;  // slot -> function taking (this, flat args...); null: not implemented
    unsigned count;
};
struct XgrInterface {
    const char* name;
    GUID iid;
    unsigned class_index;
    unsigned slots;  // slots this version has, as far as learned (0: unknown)
};

#include "xgr_table.inc"  // xgr_classes, xgr_class_count, xgr_interfaces, xgr_interface_count

namespace {

enum class Mode { ours, trace, record };

struct Object {
    void* const* vtbl;  // xgr_stub_table
    const XgrClass* klass;
    void* real;  // trace: the Windows runtime's interface
    GUID clsid;
    GUID iid;
    std::string name;
    volatile LONG refs;
};

using LaunchLog = void(__cdecl*)(const char* kind, const char* symbol, const char* detail);
using QueryFn = HRESULT(WINAPI*)(REFCLSID, REFIID, void**);
using InitFn = HRESULT(WINAPI*)(ULONG, ULONG);
using InitExFn = HRESULT(WINAPI*)(ULONG, ULONG, char);
using InitEx2Fn = HRESULT(WINAPI*)(ULONG, ULONG, char, const void*);
using UninitFn = HRESULT(WINAPI*)();
using ErrorReportFn = HRESULT(WINAPI*)(HRESULT, const char*);

struct State {
    std::mutex lock;
    Mode mode = Mode::ours;
    unsigned call_lines = 0;
    HMODULE windows = nullptr;
    bool windows_tried = false;
    std::set<std::string> seen;
    std::map<std::tuple<std::string, unsigned>, unsigned long long> calls;   // (name, slot) -> count
    std::map<std::tuple<std::string, unsigned, uintptr_t>, unsigned> lines;  // (name, slot, caller) -> lines
    std::map<std::pair<void*, std::string>, Object*> proxies;                // trace: (real, iid) -> proxy
    std::map<std::string, Object*> singletons;                               // ours/record: clsid+iid -> object
};

State& state()
{
    static State* s = new State;  // never destroyed: the title may call in during process exit
    return *s;
}

LaunchLog launch_log()
{
    static LaunchLog fn = [] {
        auto found = reinterpret_cast<LaunchLog>(GetProcAddress(GetModuleHandleW(nullptr), "x2w_launch_log_shim"));
        if (!found)
            if (HMODULE launcher = GetModuleHandleW(L"x2w_launch.exe"))
                found = reinterpret_cast<LaunchLog>(GetProcAddress(launcher, "x2w_launch_log_shim"));
        return found;
    }();
    return fn;
}

std::string format(const char* fmt, ...)
{
    char buffer[1024];
    va_list args;
    va_start(args, fmt);
    std::vsnprintf(buffer, sizeof buffer, fmt, args);
    va_end(args);
    return buffer;
}

void emit(const char* kind, const std::string& symbol, const std::string& detail)
{
    std::fprintf(stderr, "[x2w] %s %s %s\n", kind, symbol.c_str(), detail.c_str());
    std::fflush(stderr);
    if (LaunchLog fn = launch_log()) fn(kind, symbol.c_str(), detail.c_str());
}

// Logs once per distinct line.
void emit_once(const char* kind, const std::string& symbol, const std::string& detail)
{
    {
        std::lock_guard<std::mutex> hold(state().lock);
        if (!state().seen.insert(std::string(kind) + " " + symbol + " " + detail).second) return;
    }
    emit(kind, symbol, detail);
}

std::string guid_text(const GUID& g)
{
    return format("%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x", g.Data1, g.Data2, g.Data3, g.Data4[0],
                  g.Data4[1], g.Data4[2], g.Data4[3], g.Data4[4], g.Data4[5], g.Data4[6], g.Data4[7]);
}

std::string lower(std::string text)
{
    for (char& c : text) c = static_cast<char>(c >= 'A' && c <= 'Z' ? c - 'A' + 'a' : c);
    return text;
}

// "module+0xRVA" for a code address: the mapped title (GetModuleHandle(nullptr) under x2w_launch),
// a loader module, or the raw address.
std::string where(const void* address)
{
    const auto value = reinterpret_cast<uintptr_t>(address);
    if (auto title = reinterpret_cast<const unsigned char*>(GetModuleHandleW(nullptr))) {
        const auto* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(title);
        const auto* nt = reinterpret_cast<const IMAGE_NT_HEADERS64*>(title + dos->e_lfanew);
        const auto base = reinterpret_cast<uintptr_t>(title);
        if (value >= base && value < base + nt->OptionalHeader.SizeOfImage) {
            wchar_t path[MAX_PATH];
            std::string name = "title";
            if (GetEnvironmentVariableW(L"X2W_TITLE", path, MAX_PATH)) {
                char narrow[MAX_PATH];
                WideCharToMultiByte(CP_UTF8, 0, path, -1, narrow, MAX_PATH, nullptr, nullptr);
                name = lower(narrow) + ".exe";
            }
            return format("%s+0x%llx", name.c_str(), static_cast<unsigned long long>(value - base));
        }
    }
    HMODULE module = nullptr;
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           static_cast<LPCWSTR>(address), &module)) {
        char path[MAX_PATH];
        const DWORD used = GetModuleFileNameA(module, path, MAX_PATH);
        std::string name(path, used);
        const auto slash = name.find_last_of("\\/");
        if (slash != std::string::npos) name = name.substr(slash + 1);
        return format("%s+0x%llx", lower(name).c_str(),
                      static_cast<unsigned long long>(value - reinterpret_cast<uintptr_t>(module)));
    }
    return format("0x%llx", static_cast<unsigned long long>(value));
}

Mode mode()
{
    static const Mode m = [] {
        char value[32] = {};
        GetEnvironmentVariableA("X2W_XGR_MODE", value, sizeof value);
        const std::string text = lower(value);
        Mode result = text == "trace" ? Mode::trace : text == "record" ? Mode::record : Mode::ours;
        char calls[16] = {};
        unsigned lines = result == Mode::ours ? 0 : 4;
        if (GetEnvironmentVariableA("X2W_XGR_CALLS", calls, sizeof calls)) lines = std::strtoul(calls, nullptr, 10);
        state().call_lines = lines;
        emit("xgr-mode", result == Mode::trace ? "trace" : result == Mode::record ? "record" : "ours",
             format("classes=%u interfaces=%u call-lines=%u", xgr_class_count, xgr_interface_count, lines));
        return result;
    }();
    return m;
}

// Windows' own xgameruntime.dll (trace mode only), by its System32 path so it is never this DLL.
HMODULE windows_runtime()
{
    std::lock_guard<std::mutex> hold(state().lock);
    if (!state().windows_tried) {
        state().windows_tried = true;
        wchar_t path[MAX_PATH];
        const UINT length = GetSystemDirectoryW(path, MAX_PATH);
        std::wstring full = std::wstring(path, length) + L"\\xgameruntime.dll";
        state().windows = LoadLibraryExW(full.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
        if (!state().windows && SearchPathW(nullptr, L"xgameruntime.dll", nullptr, MAX_PATH, path, nullptr)) {
            HMODULE found = LoadLibraryExW(path, nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
            if (found && GetProcAddress(found, "x2w_xgr_gateway")) found = nullptr;  // ourselves
            state().windows = found;
        }
    }
    return state().windows;
}

template <typename Fn>
Fn windows_export(const char* name)
{
    HMODULE module = windows_runtime();
    return module ? reinterpret_cast<Fn>(GetProcAddress(module, name)) : nullptr;
}

const XgrInterface* find_interface(REFIID iid)
{
    for (unsigned i = 0; i < xgr_interface_count; ++i)
        if (IsEqualGUID(xgr_interfaces[i].iid, iid)) return &xgr_interfaces[i];
    return nullptr;
}
const XgrClass* find_class(REFCLSID clsid)
{
    for (unsigned i = 0; i < xgr_class_count; ++i)
        if (IsEqualGUID(xgr_classes[i].clsid, clsid)) return &xgr_classes[i];
    return nullptr;
}

std::string label(REFCLSID clsid, REFIID iid)
{
    if (const XgrInterface* known = find_interface(iid)) return known->name;
    if (const XgrClass* klass = find_class(clsid)) return std::string(klass->name) + "{" + guid_text(iid) + "}";
    return "{" + guid_text(clsid) + "}{" + guid_text(iid) + "}";
}

Object* new_object(REFCLSID clsid, REFIID iid, const XgrClass* klass, void* real)
{
    auto* object = new Object;
    object->vtbl = xgr_stub_table;
    object->klass = klass;
    object->real = real;
    object->clsid = clsid;
    object->iid = iid;
    object->name = label(clsid, iid);
    object->refs = 1;
    return object;
}

// A singleton per (CLSID, IID) for ours and record: the runtime's objects are process-wide.
Object* singleton(REFCLSID clsid, REFIID iid, const XgrClass* klass)
{
    const std::string key = guid_text(clsid) + guid_text(iid);
    std::lock_guard<std::mutex> hold(state().lock);
    Object*& object = state().singletons[key];
    if (!object) object = new_object(clsid, iid, klass, nullptr);
    return object;
}

Object* proxy_for(REFCLSID clsid, REFIID iid, void* real)
{
    const auto key = std::make_pair(real, guid_text(iid));
    std::lock_guard<std::mutex> hold(state().lock);
    Object*& object = state().proxies[key];
    if (!object) object = new_object(clsid, iid, find_class(clsid), real);
    return object;
}

// ---------------------------------------------------------------- IUnknown for every object
using RealQI = HRESULT(STDMETHODCALLTYPE*)(void*, REFIID, void**);
using RealRef = ULONG(STDMETHODCALLTYPE*)(void*);

void** real_vtbl(Object* object) { return *reinterpret_cast<void***>(object->real); }

HRESULT STDMETHODCALLTYPE object_QueryInterface(Object* self, REFIID iid, void** out)
{
    if (!out) return E_POINTER;
    *out = nullptr;
    if (self->real) {
        void* real = nullptr;
        const HRESULT hr = reinterpret_cast<RealQI>(real_vtbl(self)[0])(self->real, iid, &real);
        emit_once("xgr-qi", self->name, format("%s -> 0x%08lx", label(self->clsid, iid).c_str(), hr));
        if (SUCCEEDED(hr) && real) *out = proxy_for(self->clsid, iid, real);
        return hr;
    }
    static const GUID unknown = {0x00000000, 0x0000, 0x0000, {0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46}};
    static const GUID agile = {0x94ea2b94, 0xe9cc, 0x49e0, {0xc0, 0xff, 0xee, 0x64, 0xca, 0x8f, 0x5b, 0x90}};
    static const GUID inspectable = {0xAF86E2E0, 0xB12D, 0x4c6a, {0x9C, 0x5A, 0xD7, 0xAA, 0x65, 0x10, 0x1E, 0x90}};
    const XgrInterface* known = find_interface(iid);
    bool ok = IsEqualGUID(iid, self->iid) || IsEqualGUID(iid, unknown) || IsEqualGUID(iid, agile) ||
              IsEqualGUID(iid, inspectable) || mode() == Mode::record ||
              (known && self->klass && &xgr_classes[known->class_index] == self->klass);
    emit_once("xgr-qi", self->name, format("%s -> %s", label(self->clsid, iid).c_str(), ok ? "ok" : "E_NOINTERFACE"));
    if (!ok) return E_NOINTERFACE;
    *out = singleton(self->clsid, known ? iid : self->iid, self->klass);
    return S_OK;
}

ULONG STDMETHODCALLTYPE object_AddRef(Object* self)
{
    if (self->real) reinterpret_cast<RealRef>(real_vtbl(self)[1])(self->real);
    return static_cast<ULONG>(InterlockedIncrement(&self->refs));
}

ULONG STDMETHODCALLTYPE object_Release(Object* self)
{
    if (self->real) reinterpret_cast<RealRef>(real_vtbl(self)[2])(self->real);
    // Objects are kept for the life of the process (titles cache them); the count is only reported.
    const LONG refs = InterlockedDecrement(&self->refs);
    return static_cast<ULONG>(refs > 0 ? refs : 1);
}

void* const iunknown[3] = {reinterpret_cast<void*>(&object_QueryInterface), reinterpret_cast<void*>(&object_AddRef),
                           reinterpret_cast<void*>(&object_Release)};

// Per-thread record of the call in flight, for the result half of an xgr-call line.
struct Pending {
    bool log;
    std::string text;
};
thread_local std::vector<Pending> pending;

void summary()
{
    std::vector<std::pair<std::tuple<std::string, unsigned>, unsigned long long>> rows;
    {
        std::lock_guard<std::mutex> hold(state().lock);
        rows.assign(state().calls.begin(), state().calls.end());
    }
    for (const auto& [key, count] : rows)
        emit("xgr-summary", std::get<0>(key), format("slot %u calls %llu", std::get<1>(key), count));
}

}  // namespace

// ---------------------------------------------------------------- the thunks' C half (xgr_thunks.asm)
extern "C" void* xgr_slot_enter(Object* self, unsigned slot, void** args, void* caller)
{
    const Mode current = mode();
    void* target = nullptr;
    bool known = true;
    if (slot < 3) {
        target = iunknown[slot];
    } else if (self->real) {
        args[0] = self->real;
        target = real_vtbl(self)[slot];
    } else if (self->klass && slot < self->klass->count) {
        target = self->klass->targets[slot];
    }
    if (!target && slot >= 3) known = false;

    bool log = false;
    {
        std::lock_guard<std::mutex> hold(state().lock);
        ++state().calls[std::make_tuple(self->name, slot)];
        if (slot >= 3 && known) {
            unsigned& lines = state().lines[std::make_tuple(self->name, slot, reinterpret_cast<uintptr_t>(caller))];
            if (lines < state().call_lines) {
                ++lines;
                log = true;
            }
        }
    }
    if (!known) {
        emit_once("xgr-unknown-slot", self->name,
                  format("slot %u args 0x%llx 0x%llx 0x%llx caller=%s", slot, (unsigned long long)args[1],
                         (unsigned long long)args[2], (unsigned long long)args[3], where(caller).c_str()));
        if (current != Mode::record) return nullptr;
        // record: also an xgr-call line, so the argument shapes of every new slot are seen.
        emit("xgr-call", self->name,
             format("slot %u args 0x%llx 0x%llx 0x%llx 0x%llx 0x%llx 0x%llx -> E_NOTIMPL caller=%s", slot,
                    (unsigned long long)args[1], (unsigned long long)args[2], (unsigned long long)args[3],
                    (unsigned long long)args[4], (unsigned long long)args[5], (unsigned long long)args[6],
                    where(caller).c_str()));
        return nullptr;
    }
    std::string text;
    if (log)
        text = format("slot %u args 0x%llx 0x%llx 0x%llx 0x%llx 0x%llx 0x%llx", slot, (unsigned long long)args[1],
                      (unsigned long long)args[2], (unsigned long long)args[3], (unsigned long long)args[4],
                      (unsigned long long)args[5], (unsigned long long)args[6]);
    pending.push_back(Pending{log, std::move(text)});
    return target;
}

extern "C" uintptr_t xgr_slot_leave(Object* self, unsigned /*slot*/, uintptr_t result, void* caller)
{
    if (pending.empty()) return result;
    Pending call = std::move(pending.back());
    pending.pop_back();
    if (call.log)
        emit("xgr-call", self->name,
             format("%s -> 0x%llx caller=%s", call.text.c_str(), (unsigned long long)result, where(caller).c_str()));
    return result;
}

// ---------------------------------------------------------------- the six exports
namespace {
struct InitializeOptions {  // the fourth argument of InitializeApiImplEx2 (shape from the prior-art notes)
    UINT32 version;
    BOOLEAN inline_config;
    const char* config;
};

std::string options_text(const void* options)
{
    if (!options) return "null";
    const auto* o = static_cast<const InitializeOptions*>(options);
    size_t length = 0;
    if (o->config && o->inline_config) length = std::strlen(o->config);
    return format("{%u, inline=%u, config=%s%s}", o->version, o->inline_config, o->config ? "set" : "null",
                  o->inline_config ? format(" (%zu chars)", length).c_str() : "");
}

HRESULT initialize(const char* name, ULONG gdk, ULONG gs, int mode_flags, const void* options, void* caller,
                   HRESULT (*forward)(ULONG, ULONG, char, const void*))
{
    HRESULT hr = S_OK;
    if (mode() == Mode::trace) {
        hr = forward ? forward(gdk, gs, static_cast<char>(mode_flags), options) : E_NOTIMPL;
    } else if (mode() == Mode::ours) {
        hr = x2w_impl_XGameRuntimeInitialize();
    }
    emit("xgr-init", name,
         format("gdk=%lu gs=%lu mode=0x%x options=%s -> 0x%08lx caller=%s", gdk, gs, mode_flags & 0xff,
                options_text(options).c_str(), hr, where(caller).c_str()));
    return hr;
}
}  // namespace

extern "C" {

int x2w_xgr_gateway(void) { return 1; }

HRESULT WINAPI InitializeApiImpl(ULONG gdk, ULONG gs)
{
    return initialize("InitializeApiImpl", gdk, gs, -1, nullptr, _ReturnAddress(),
                      [](ULONG g, ULONG s, char, const void*) -> HRESULT {
                          auto fn = windows_export<InitFn>("InitializeApiImpl");
                          return fn ? fn(g, s) : E_NOTIMPL;
                      });
}

HRESULT WINAPI InitializeApiImplEx(ULONG gdk, ULONG gs, char flags)
{
    return initialize("InitializeApiImplEx", gdk, gs, static_cast<unsigned char>(flags), nullptr, _ReturnAddress(),
                      [](ULONG g, ULONG s, char m, const void*) -> HRESULT {
                          auto fn = windows_export<InitExFn>("InitializeApiImplEx");
                          return fn ? fn(g, s, m) : E_NOTIMPL;
                      });
}

HRESULT WINAPI InitializeApiImplEx2(ULONG gdk, ULONG gs, char flags, const void* options)
{
    return initialize("InitializeApiImplEx2", gdk, gs, static_cast<unsigned char>(flags), options, _ReturnAddress(),
                      [](ULONG g, ULONG s, char m, const void* o) -> HRESULT {
                          auto fn = windows_export<InitEx2Fn>("InitializeApiImplEx2");
                          return fn ? fn(g, s, m, o) : E_NOTIMPL;
                      });
}

HRESULT WINAPI UninitializeApiImpl(void)
{
    HRESULT hr = S_OK;
    if (mode() == Mode::trace) {
        auto fn = windows_export<UninitFn>("UninitializeApiImpl");
        hr = fn ? fn() : E_NOTIMPL;
    } else if (mode() == Mode::ours) {
        x2w_impl_XGameRuntimeUninitialize();
    }
    emit("xgr-init", "UninitializeApiImpl", format("-> 0x%08lx caller=%s", hr, where(_ReturnAddress()).c_str()));
    summary();
    return hr;
}

HRESULT WINAPI QueryApiImpl(REFCLSID clsid, REFIID iid, void** out)
{
    void* caller = _ReturnAddress();
    if (!out) return E_POINTER;
    *out = nullptr;
    HRESULT hr = S_OK;
    const Mode current = mode();
    if (current == Mode::trace) {
        auto fn = windows_export<QueryFn>("QueryApiImpl");
        void* real = nullptr;
        hr = fn ? fn(clsid, iid, &real) : E_NOTIMPL;
        if (SUCCEEDED(hr) && real) *out = proxy_for(clsid, iid, real);
    } else if (current == Mode::record) {
        *out = singleton(clsid, iid, find_class(clsid));
    } else {
        const XgrInterface* known = find_interface(iid);
        const XgrClass* klass = find_class(clsid);
        if (known && klass && &xgr_classes[known->class_index] == klass) {
            *out = singleton(clsid, iid, klass);
        } else {
            hr = static_cast<HRESULT>(0x80070032L);  // HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED)
        }
    }
    emit_once("xgr-query", label(clsid, iid),
              format("clsid=%s iid=%s -> 0x%08lx caller=%s", guid_text(clsid).c_str(), guid_text(iid).c_str(), hr,
                     where(caller).c_str()));
    return hr;
}

HRESULT WINAPI XErrorReport(HRESULT status, const char* message)
{
    emit("xgr-error-report", format("0x%08lx", status), message ? message : "(null)");
    if (mode() == Mode::trace)
        if (auto fn = windows_export<ErrorReportFn>("XErrorReport")) return fn(status, message);
    return S_OK;
}

}  // extern "C"

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_DETACH && reserved) summary();  // process exit; FreeLibrary leaves it to Uninitialize
    return TRUE;
}
