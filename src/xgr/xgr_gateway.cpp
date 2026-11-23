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
//           A query this table does not list (unknown CLSID, unknown IID, or an IID of another class) still
//           succeeds: it returns a logging fallback object (log "xgr-fallback"), whose every slot logs its
//           index and first four arguments ("xgr-unknown-slot") and answers E_NOTIMPL (or, for a known class
//           with a `fallback` in the table, that class's "not available" HRESULT, E_GAMEUSER_NO_DEFAULT_USER
//           for XUser). A slot with no implementation in a listed interface answers the same way. A title
//           therefore never gets E_NOINTERFACE / a null interface from a missing class, and a missing method
//           is a logged failure code, never a jump into unmapped memory. X2W_XGR_STRICT=1 restores the old
//           answer to an unlisted query, 0x80070032 (HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED)).
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
#include "../common/x2w_redact.h"
#include <intrin.h>

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <set>
#include <cstdlib>
#include <string>
#include <tuple>
#include <vector>

#include "x2w_gdk.h"
#include "xgr_types.h"

extern "C" void* const xgr_stub_table[];
constexpr unsigned xgr_slots = 256;  // XGR_SLOTS in xgr_thunks.asm

struct XgrClass {
    const char* name;
    GUID clsid;
    long fallback_hr;  // what a slot with no implementation answers (tools/xgr/interfaces.toml, `fallback`)
};
struct XgrInterface {
    const char* name;
    GUID iid;
    unsigned class_index;  // into xgr_classes
    void* const* targets;  // slot -> function taking (this, flat args...); null: not implemented
    unsigned count;
    void* const* inferred;              // slot -> function for a guessed (untraced) slot; served only with X2W_XGR_INFERRED=1
    const char* const* inferred_names;  // slot -> the guessed function's name (logged), or null
};

#include "xgr_table.inc"  // xgr_classes, xgr_class_count, xgr_interfaces, xgr_interface_count

namespace {

enum class Mode { ours, trace, record };

struct Object {
    void* const* vtbl;  // xgr_stub_table
    const XgrInterface* iface;  // ours: the learned interface; null in record and trace
    void* real;  // trace: the Windows runtime's interface
    GUID clsid;
    GUID iid;
    std::string name;
    long fallback_hr;  // ours: what an unimplemented slot answers (E_NOTIMPL unless the class says otherwise)
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

// x2w_launch's heap guard validates the process heap at each of these (tools/x2w_launch.cpp, "heap guard").
using HeapMilestone = void(__cdecl*)(const char* name);
void heap_milestone(const char* fmt, ...)
{
    static HeapMilestone fn = [] {
        auto found = reinterpret_cast<HeapMilestone>(GetProcAddress(GetModuleHandleW(nullptr), "x2w_launch_heap_milestone"));
        if (!found)
            if (HMODULE launcher = GetModuleHandleW(L"x2w_launch.exe"))
                found = reinterpret_cast<HeapMilestone>(GetProcAddress(launcher, "x2w_launch_heap_milestone"));
        return found;
    }();
    if (!fn) return;
    const DWORD error = GetLastError();
    char name[200];
    va_list args;
    va_start(args, fmt);
    std::vsnprintf(name, sizeof name, fmt, args);
    va_end(args);
    fn(name);
    SetLastError(error);
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
    std::fprintf(stderr, "[x2w] %s\n", x2w_redact::apply(std::string(kind) + " " + symbol + " " + detail).c_str());
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

bool strict()
{
    static const bool value = [] {
        char text[8] = {};
        return GetEnvironmentVariableA("X2W_XGR_STRICT", text, sizeof text) && text[0] == '1';
    }();
    return value;
}

// X2W_XGR_INFERRED=1 serves the table's inferred slots (positions guessed, not traced). Off by default: a wrong
// guess that writes through an argument corrupts the title's memory, where an unserved slot only fails.
bool serve_inferred()
{
    static const bool value = [] {
        char text[8] = {};
        return GetEnvironmentVariableA("X2W_XGR_INFERRED", text, sizeof text) && text[0] == '1';
    }();
    return value;
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
    const XgrClass* klass = find_class(clsid);
    if (const XgrInterface* known = find_interface(iid))
        if (klass && &xgr_classes[known->class_index] == klass) return known->name;
    if (klass) return std::string(klass->name) + "{" + guid_text(iid) + "}";
    return "{" + guid_text(clsid) + "}{" + guid_text(iid) + "}";
}

Object* new_object(REFCLSID clsid, REFIID iid, const XgrInterface* iface, void* real)
{
    auto* object = new Object;
    object->vtbl = xgr_stub_table;
    object->iface = iface;
    object->real = real;
    object->clsid = clsid;
    object->iid = iid;
    object->name = label(clsid, iid);
    const XgrClass* klass = find_class(clsid);
    object->fallback_hr = klass && klass->fallback_hr ? klass->fallback_hr : static_cast<long>(E_NOTIMPL);
    object->refs = 1;
    return object;
}

// A singleton per (CLSID, IID) for ours and record: the runtime's objects are process-wide.
Object* singleton(REFCLSID clsid, REFIID iid, const XgrInterface* iface)
{
    const std::string key = guid_text(clsid) + guid_text(iid);
    std::lock_guard<std::mutex> hold(state().lock);
    Object*& object = state().singletons[key];
    if (!object) object = new_object(clsid, iid, iface, nullptr);
    return object;
}

Object* proxy_for(REFCLSID clsid, REFIID iid, void* real)
{
    const auto key = std::make_pair(real, guid_text(iid));
    std::lock_guard<std::mutex> hold(state().lock);
    Object*& object = state().proxies[key];
    if (!object) object = new_object(clsid, iid, nullptr, real);
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
    // A fallback object (no table entry behind it) says yes to every IID: refusing would hard-fail a title
    // whose next step is a slot call we log and answer anyway.
    const bool fallback = !self->iface;
    bool ok = IsEqualGUID(iid, self->iid) || IsEqualGUID(iid, unknown) || IsEqualGUID(iid, agile) ||
              IsEqualGUID(iid, inspectable) || mode() == Mode::record || fallback ||
              (known && self->iface && known->class_index == self->iface->class_index);
    emit_once("xgr-qi", self->name, format("%s -> %s", label(self->clsid, iid).c_str(), ok ? "ok" : "E_NOINTERFACE"));
    if (!ok) return E_NOINTERFACE;
    if (fallback) {
        const bool plain = IsEqualGUID(iid, unknown) || IsEqualGUID(iid, agile) || IsEqualGUID(iid, inspectable);
        *out = singleton(self->clsid, plain ? self->iid : iid, nullptr);
        return S_OK;
    }
    *out = singleton(self->clsid, known && self->iface ? iid : self->iid, known && self->iface ? known : self->iface);
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

// What a slot with no implementation runs when its object's class has a "not available" HRESULT other than
// E_NOTIMPL (the thunk answers E_NOTIMPL itself when given no function). The values are tools/xgr_gen.py FALLBACKS.
namespace {
HRESULT fallback_no_default_user() noexcept { return static_cast<HRESULT>(0x89245106L); }  // E_GAMEUSER_NO_DEFAULT_USER

HRESULT answer_s_ok() noexcept { return S_OK; }
HRESULT answer_s_false() noexcept { return S_FALSE; }
HRESULT answer_e_fail() noexcept { return E_FAIL; }
HRESULT answer_e_pending() noexcept { return static_cast<HRESULT>(0x8000000AL); }  // E_PENDING

void* fallback_function(long hr)
{
    switch (static_cast<unsigned long>(hr)) {
    case 0x89245106ul: return reinterpret_cast<void*>(&fallback_no_default_user);
    case 0x00000000ul: return reinterpret_cast<void*>(&answer_s_ok);
    case 0x00000001ul: return reinterpret_cast<void*>(&answer_s_false);
    case 0x80004005ul: return reinterpret_cast<void*>(&answer_e_fail);
    case 0x8000000Aul: return reinterpret_cast<void*>(&answer_e_pending);
    default: return nullptr;  // E_NOTIMPL
    }
}

// X2W_XGR_SLOT_ANSWER="NAME:SLOT=HR[;NAME:SLOT=HR]..." (e.g. IXNetworkingImpl_bf2346b2:15=0) makes an unknown slot
// answer HR (0, 1, 0x80004005, 0x8000000a or the class fallback) without touching its arguments, so an owner can
// try answers for an unidentified slot without a rebuild.
bool slot_answer_override(const std::string& name, unsigned slot, long& hr)
{
    char buffer[2048];
    const DWORD error = GetLastError();  // an unset variable sets ERROR_ENVVAR_NOT_FOUND; the title's value is kept
    const DWORD n = GetEnvironmentVariableA("X2W_XGR_SLOT_ANSWER", buffer, sizeof buffer);
    SetLastError(error);
    // Defaults when the variable is unset, from real-title traces (args only, nothing written):
    //   IXUserImpl slot 33 is called with (queue, context, callback, token*), the shape of
    //   XUserRegisterForChangeEvent; registering succeeds (no events are ever raised offline).
    static const char kDefaults[] = "IXUserImpl:33=0";
    if (n >= sizeof buffer) return false;
    const std::string spec = n ? std::string(buffer, n) : std::string(kDefaults), key = name + ":" + std::to_string(slot) + "=";
    std::size_t at = 0;
    while (at < spec.size()) {
        std::size_t end = spec.find(';', at);
        if (end == std::string::npos) end = spec.size();
        const std::string item = spec.substr(at, end - at);
        if (item.compare(0, key.size(), key) == 0) {
            hr = static_cast<long>(std::strtoul(item.c_str() + key.size(), nullptr, 0));
            return true;
        }
        at = end + 1;
    }
    return false;
}
}  // namespace

// ---------------------------------------------------------------- the thunks' C half (xgr_thunks.asm)
extern "C" void* xgr_slot_enter(Object* self, unsigned slot, void** args, void* caller)
{
    if (slot >= 3) heap_milestone("xgr-call %s.%u", self->name.c_str(), slot);
    const Mode current = mode();
    void* target = nullptr;
    bool known = true;
    if (slot < 3) {
        target = iunknown[slot];
    } else if (self->real) {
        args[0] = self->real;
        target = real_vtbl(self)[slot];
    } else if (self->iface && slot < self->iface->count) {
        target = self->iface->targets[slot];
    }
    // A guessed slot: its name for the log, and its function only when asked for (X2W_XGR_INFERRED=1).
    const char* guess = nullptr;
    if (!target && slot >= 3 && !self->real && self->iface && slot < self->iface->count && self->iface->inferred_names)
        guess = self->iface->inferred_names[slot];
    if (guess && serve_inferred() && self->iface->inferred && self->iface->inferred[slot]) {
        target = self->iface->inferred[slot];
        emit_once("xgr-assume", format("%s.%u", self->name.c_str(), slot),
                  format("%s slot %u taken to be %s (inferred, not traced; X2W_XGR_INFERRED=1)", self->name.c_str(),
                         slot, guess));
    }
    if (!target && slot >= 3) known = false;

    bool log = false;
    bool unknown_log = false;
    {
        std::lock_guard<std::mutex> hold(state().lock);
        ++state().calls[std::make_tuple(self->name, slot)];
        // An unnamed slot's lines carry its argument values and caller, so each call can be a new line: the first
        // 8 per slot are logged (a hot slot would otherwise grow the log and the seen set without bound).
        if (!known) {
            unsigned& lines = state().lines[std::make_tuple(self->name, slot, ~uintptr_t{0})];
            if (lines < 8) {
                ++lines;
                unknown_log = true;
            }
        }
        if (slot >= 3 && known) {
            unsigned& lines = state().lines[std::make_tuple(self->name, slot, reinterpret_cast<uintptr_t>(caller))];
            if (lines < state().call_lines) {
                ++lines;
                log = true;
            }
        }
    }
    if (!known) {
        // Never read or write through the arguments of a slot we cannot name from facts: only their values are logged.
        const bool ours = current == Mode::ours;
        long answer = self->fallback_hr;
        const bool overridden = ours && slot_answer_override(self->name, slot, answer);
        if (overridden && !fallback_function(answer) && answer != static_cast<long>(0x80004001L)) {
            emit_once("xgr-slot-answer", self->name, format("slot %u: X2W_XGR_SLOT_ANSWER value 0x%08lx is not one of "
                                                             "0, 1, 0x80004005, 0x8000000a, 0x89245106; E_NOTIMPL", slot,
                                                             static_cast<unsigned long>(answer)));
            answer = static_cast<long>(0x80004001L);
        } else if (overridden)
            emit_once("xgr-slot-answer", self->name, format("slot %u answers 0x%08lx (X2W_XGR_SLOT_ANSWER)", slot,
                                                             static_cast<unsigned long>(answer)));
        if (unknown_log)
            emit_once("xgr-unknown-slot", self->name,
                      format("slot %u args 0x%llx 0x%llx 0x%llx 0x%llx -> 0x%08lx%s%s%s caller=%s", slot,
                             (unsigned long long)args[1], (unsigned long long)args[2], (unsigned long long)args[3],
                             (unsigned long long)args[4], ours ? static_cast<unsigned long>(answer) : 0x80004001ul,
                             guess ? " (inferred " : "", guess ? guess : "", guess ? ", not served)" : "",
                             where(caller).c_str()));
        if (current == Mode::ours) return fallback_function(answer);  // null: E_NOTIMPL
        if (current != Mode::record) return nullptr;
        // record: also an xgr-call line, so the argument shapes of every new slot are seen.
        if (unknown_log)
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

extern "C" uintptr_t xgr_slot_leave(Object* self, unsigned slot, uintptr_t result, void* caller)
{
    if (slot >= 3) heap_milestone("xgr-return %s.%u", self->name.c_str(), slot);
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
    {
        // Before any lookup (the first 512 calls), so a crash inside the lookup still names the query.
        static volatile long entered = 0;
        if (InterlockedIncrement(&entered) <= 512)
            emit("xgr-query-enter", guid_text(clsid),
                 format("clsid=%s iid=%s caller=%s", guid_text(clsid).c_str(), guid_text(iid).c_str(), where(caller).c_str()));
    }
    heap_milestone("xgr-query %s", guid_text(clsid).c_str());
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
        *out = singleton(clsid, iid, nullptr);
    } else {
        const XgrInterface* known = find_interface(iid);
        const XgrClass* klass = find_class(clsid);
        if (known && klass && &xgr_classes[known->class_index] == klass) {
            *out = singleton(clsid, iid, known);
        } else if (strict()) {
            hr = static_cast<HRESULT>(0x80070032L);  // HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED)
        } else {
            // Not in the table: a logging fallback object, so the title's next call is a logged failure code
            // (E_NOTIMPL, or the class's own) and not a null interface it may dereference or stall on.
            const char* why = !klass ? "unknown CLSID" : known ? "IID of another class" : "unlisted IID of a known class";
            *out = singleton(clsid, iid, nullptr);
            emit_once("xgr-fallback", label(clsid, iid),
                      format("clsid=%s iid=%s %s: slots log and answer 0x%08lx caller=%s", guid_text(clsid).c_str(),
                             guid_text(iid).c_str(), why, static_cast<unsigned long>(static_cast<Object*>(*out)->fallback_hr),
                             where(caller).c_str()));
        }
    }
    emit_once("xgr-query", label(clsid, iid),
              format("clsid=%s iid=%s -> 0x%08lx caller=%s", guid_text(clsid).c_str(), guid_text(iid).c_str(), hr,
                     where(caller).c_str()));
    heap_milestone("xgr-query-exit %s", label(clsid, iid).c_str());
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

// ---------------------------------------------------------------- X2W_XGR_PEEK (diagnostics)
// X2W_XGR_PEEK="RVA:LEN,..." (hex RVAs in the title): at the title's first C++ throws, log those bytes of
// the title as hex ("xgr-peek"), the thread's word at offset 4 of its implicit TLS block (the C runtime's
// _Init_thread_epoch, given X2W_XGR_TLS_INDEX=RVA of _tls_index) and the thrown object's first words and
// any std::string-shaped members (MSVC layout) at offsets 24 and 56 ("xgr-throw-object"). For finding why a
// title throws under x2w_launch; off unless set.
namespace {
std::string peek_hex(const unsigned char* p, size_t n)
{
    std::string out;
    for (size_t i = 0; i < n; ++i) out += format("%02x", p[i]);
    return out;
}

std::string msvc_string(const unsigned char* at)
{
    const auto size = *reinterpret_cast<const size_t*>(at + 16);
    const auto capacity = *reinterpret_cast<const size_t*>(at + 24);
    if (size > 4096 || capacity < size) return format("(not a string: size %zu cap %zu)", size, capacity);
    const char* text = capacity > 15 ? *reinterpret_cast<const char* const*>(at) : reinterpret_cast<const char*>(at);
    std::string out;
    for (size_t i = 0; i < size && i < 160; ++i) {
        const char c = text[i];
        out += (c >= 0x20 && c < 0x7f) ? c : '.';
    }
    return "\"" + out + "\"";
}

void peek_body(const EXCEPTION_RECORD* record)
{
        auto* title = reinterpret_cast<const unsigned char*>(GetModuleHandleW(nullptr));
        char spec[4096] = {};
        GetEnvironmentVariableA("X2W_XGR_PEEK", spec, sizeof spec);
        for (char* item = std::strtok(spec, ","); item; item = std::strtok(nullptr, ",")) {
            char* colon = std::strchr(item, ':');
            const unsigned long rva = std::strtoul(item, nullptr, 16);
            const unsigned long length = colon ? std::strtoul(colon + 1, nullptr, 16) : 8;
            emit("xgr-peek", format("0x%lx", rva), peek_hex(title + rva, length > 64 ? 64 : length));
        }
        char index_rva[32] = {};
        if (GetEnvironmentVariableA("X2W_XGR_TLS_INDEX", index_rva, sizeof index_rva)) {
            const DWORD index = *reinterpret_cast<const DWORD*>(title + std::strtoul(index_rva, nullptr, 16));
            auto* const* vector = reinterpret_cast<unsigned char* const*>(__readgsqword(0x58));
            emit("xgr-peek", "tls", format("index %lu block %p epoch %d thread %lu", index, vector ? vector[index] : nullptr,
                                           vector && vector[index] ? *reinterpret_cast<const int*>(vector[index] + 4) : 0,
                                           GetCurrentThreadId()));
        }
        const auto* object = reinterpret_cast<const unsigned char*>(record->ExceptionInformation[1]);
        if (object)
            emit("xgr-throw-object", format("%p", object),
                 peek_hex(object, 88) + " id=" + msvc_string(object + 24) + " message=" + msvc_string(object + 56));
}

void peek_fault() { emit("xgr-peek", "fault", ""); }

volatile LONG peek_count = 0;
LONG CALLBACK peek_handler(EXCEPTION_POINTERS* info)
{
    const EXCEPTION_RECORD* record = info->ExceptionRecord;
    if (record->ExceptionCode != 0xE06D7363 || record->NumberParameters < 3) return EXCEPTION_CONTINUE_SEARCH;
    if (InterlockedIncrement(&peek_count) > 4) return EXCEPTION_CONTINUE_SEARCH;
    __try {
        peek_body(record);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        peek_fault();
    }
    return EXCEPTION_CONTINUE_SEARCH;
}
}  // namespace

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_ATTACH && GetEnvironmentVariableA("X2W_XGR_PEEK", nullptr, 0))
        AddVectoredExceptionHandler(1, peek_handler);
    if (reason == DLL_PROCESS_DETACH && reserved) summary();  // process exit; FreeLibrary leaves it to Uninitialize
    return TRUE;
}
