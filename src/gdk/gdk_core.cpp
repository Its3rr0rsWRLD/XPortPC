// x2w_gdk.dll support: logging of unimplemented paths, forwarding to a PC runtime DLL, title identity.
#include "gdk_internal.h"

#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <map>
#include <mutex>
#include <set>
#include <utility>

namespace x2w {

std::wstring widen(const std::string& text)
{
    if (text.empty()) return {};
    const int size = MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0);
    std::wstring out(static_cast<size_t>(size), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), out.data(), size);
    return out;
}

std::string narrow(const std::wstring& text)
{
    if (text.empty()) return {};
    const int size =
        WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr);
    std::string out(static_cast<size_t>(size), '\0');
    WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), out.data(), size, nullptr, nullptr);
    return out;
}

std::string env(const char* name)
{
    const std::wstring wide = widen(name);
    const DWORD size = GetEnvironmentVariableW(wide.c_str(), nullptr, 0);
    if (!size) return {};
    std::wstring value(size, L'\0');
    const DWORD used = GetEnvironmentVariableW(wide.c_str(), value.data(), size);
    value.resize(used);
    return narrow(value);
}

std::string format(const char* fmt, ...)
{
    char buffer[512];
    va_list args;
    va_start(args, fmt);
    std::vsnprintf(buffer, sizeof buffer, fmt, args);
    va_end(args);
    return buffer;
}

namespace {

std::wstring module_path()
{
    wchar_t path[MAX_PATH * 2];
    const DWORD used = GetModuleFileNameW(nullptr, path, static_cast<DWORD>(std::size(path)));
    return std::wstring(path, used);
}

std::string safe_component(const std::string& text)
{
    std::string out;
    for (const char c : text) {
        const bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' ||
                        c == '_' || c == '.';
        out += ok ? c : '_';
    }
    while (!out.empty() && out.back() == '.') out.pop_back();
    return out.empty() ? "title" : out;
}

}  // namespace

std::string title_name()
{
    std::string name = env("X2W_TITLE");
    if (name.empty()) {
        std::wstring path = module_path();
        const auto slash = path.find_last_of(L"\\/");
        if (slash != std::wstring::npos) path = path.substr(slash + 1);
        const auto dot = path.find_last_of(L'.');
        if (dot != std::wstring::npos) path = path.substr(0, dot);
        name = narrow(path);
    }
    return safe_component(name);
}

std::string title_dir()
{
    std::string dir = env("X2W_TITLE_DIR");
    if (dir.empty()) {
        std::wstring path = module_path();
        const auto slash = path.find_last_of(L"\\/");
        dir = narrow(slash == std::wstring::npos ? L"." : path.substr(0, slash));
    }
    while (dir.size() > 3 && (dir.back() == '\\' || dir.back() == '/')) dir.pop_back();
    return dir;
}

std::wstring save_dir()
{
    std::string root = env("X2W_SAVE_ROOT");
    if (root.empty()) {
        std::string local = env("LOCALAPPDATA");
        if (local.empty()) local = title_dir();
        root = local + "\\XPortPC\\saves";
    }
    return widen(root + "\\" + title_name());
}

}  // namespace x2w

namespace {

struct LogState {
    SRWLOCK lock = SRWLOCK_INIT;
    std::set<std::pair<std::string, std::string>> seen;
    std::string first;
    X2WShimLogSink sink = nullptr;
    void* sink_context = nullptr;
};
LogState& log_state()
{
    static LogState* state = new LogState;  // never destroyed: shims may log during process exit
    return *state;
}
std::atomic<uint32_t> g_unimplemented{0};

using LaunchLog = void(__cdecl*)(const char* kind, const char* symbol, const char* detail);
LaunchLog launch_log()
{
    // x2w_launch exports this to put shim events into its run log (tools/x2w_launch.cpp).
    // GetModuleHandle(nullptr) is the title once x2w_launch has set the PEB's image base to it, so the
    // launcher is also looked up by name.
    static LaunchLog fn = [] {
        auto found = reinterpret_cast<LaunchLog>(GetProcAddress(GetModuleHandleW(nullptr), "x2w_launch_log_shim"));
        if (!found)
            if (HMODULE launcher = GetModuleHandleW(L"x2w_launch.exe"))
                found = reinterpret_cast<LaunchLog>(GetProcAddress(launcher, "x2w_launch_log_shim"));
        return found;
    }();
    return fn;
}

// Logs once per distinct (symbol, detail). Returns false when it was already logged.
bool emit(const char* kind, const char* symbol, const char* detail, bool count)
{
    auto& state = log_state();
    const std::string sym = symbol ? symbol : "?", det = detail ? detail : "";
    X2WShimLogSink sink;
    void* context;
    AcquireSRWLockExclusive(&state.lock);
    if (!state.seen.emplace(sym, det).second) {
        ReleaseSRWLockExclusive(&state.lock);
        return false;
    }
    if (count && state.first.empty()) state.first = sym + " " + det;
    sink = state.sink;
    context = state.sink_context;
    ReleaseSRWLockExclusive(&state.lock);
    if (count) g_unimplemented.fetch_add(1);
    std::fprintf(stderr, "[x2w] %s %s %s\n", kind, sym.c_str(), det.c_str());
    std::fflush(stderr);
    if (LaunchLog fn = launch_log()) fn(kind, sym.c_str(), det.c_str());
    if (sink) sink(kind, sym.c_str(), det.c_str(), context);
    return true;
}

std::string where(const void* address)
{
    HMODULE module = nullptr;
    if (address && GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                      static_cast<LPCWSTR>(address), &module)) {
        wchar_t path[MAX_PATH];
        const DWORD used = GetModuleFileNameW(module, path, MAX_PATH);
        std::wstring name(path, used);
        const auto slash = name.find_last_of(L"\\/");
        if (slash != std::wstring::npos) name = name.substr(slash + 1);
        return x2w::format("%s+0x%llx", x2w::narrow(name).c_str(),
                           static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(address) -
                                                           reinterpret_cast<uintptr_t>(module)));
    }
    return x2w::format("0x%llx", static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(address)));
}

// ---------------------------------------------------------------- forwarding
struct Family {
    bool decided = false;
    HMODULE module = nullptr;
};

bool family_enabled(const std::string& family, bool by_default)
{
    const std::string setting = x2w::env("X2W_FORWARD");
    if (setting.empty()) return by_default;
    if (setting == "all" || setting == "1") return true;
    if (setting == "none" || setting == "0") return false;
    bool enabled = by_default;
    size_t start = 0;
    while (start <= setting.size()) {
        size_t end = setting.find(',', start);
        if (end == std::string::npos) end = setting.size();
        std::string item = setting.substr(start, end - start);
        if (!item.empty() && item[0] == '-') {
            if (item.substr(1) == family) enabled = false;
        } else if (item == family || item == "all") {
            enabled = true;
        }
        start = end + 1;
    }
    return enabled;
}

HMODULE load_forward_dll(const std::string& family, const std::string& dll, const std::string& anchor)
{
    std::string dir = x2w::env("X2W_FORWARD_DIR");
    if (dir.empty()) {
        wchar_t system[MAX_PATH];
        const UINT used = GetSystemDirectoryW(system, MAX_PATH);
        dir = x2w::narrow(std::wstring(system, used));
    }
    const std::string path = dir + "\\" + dll;
    const std::string symbol = "x2w_gdk!forward." + family;
    HMODULE module = LoadLibraryExW(x2w::widen(path).c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!module) {
        emit("note", symbol.c_str(), x2w::format("%s not loadable (error %lu), using the fallback", path.c_str(),
                                                 GetLastError()).c_str(), false);
        return nullptr;
    }
    // A console DLL name can equal the PC one; never forward into one of our own generated shims.
    if (GetProcAddress(module, "x2w_shimgen_dll")) {
        emit("note", symbol.c_str(), x2w::format("%s is a generated shim, using the fallback", path.c_str()).c_str(),
             false);
        FreeLibrary(module);
        return nullptr;
    }
    if (!anchor.empty() && !GetProcAddress(module, anchor.c_str())) {
        emit("note", symbol.c_str(),
             x2w::format("%s lacks %s, using the fallback", path.c_str(), anchor.c_str()).c_str(), false);
        FreeLibrary(module);
        return nullptr;
    }
    emit("forward", symbol.c_str(), x2w::format("to %s", path.c_str()).c_str(), false);
    return module;
}

}  // namespace

extern "C" X2W_GDK_API void x2w_unimplemented(const char* symbol, const char* detail) noexcept
{
    emit("unimplemented", symbol, detail, true);
}

extern "C" X2W_GDK_API void x2w_stub_called(const char* symbol, const char* detail, const void* caller) noexcept
{
    const std::string text = std::string(detail ? detail : "") + ", first caller " + where(caller);
    emit("unimplemented", symbol, text.c_str(), true);
}

extern "C" X2W_GDK_API void x2w_note(const char* symbol, const char* detail) noexcept
{
    emit("note", symbol, detail, false);
}

extern "C" X2W_GDK_API void* x2w_forward_resolve(const char* family, const char* dll, const char* anchor,
                                                 const char* name, int enabled_by_default) noexcept
{
    static SRWLOCK lock = SRWLOCK_INIT;
    static std::map<std::string, Family>* families = new std::map<std::string, Family>;
    if (!family || !dll || !name) return nullptr;
    AcquireSRWLockExclusive(&lock);
    Family& entry = (*families)[family];
    if (!entry.decided) {
        entry.decided = true;
        if (family_enabled(family, enabled_by_default != 0)) entry.module = load_forward_dll(family, dll, anchor ? anchor : "");
    }
    HMODULE module = entry.module;
    ReleaseSRWLockExclusive(&lock);
    if (!module) return nullptr;
    void* address = reinterpret_cast<void*>(GetProcAddress(module, name));
    if (!address) {
        const std::string symbol = std::string("x2w_gdk!forward.") + family;
        emit("note", symbol.c_str(), x2w::format("%s lacks %s, using the fallback", dll, name).c_str(), false);
    }
    return address;
}

extern "C" X2W_GDK_API void X2WShimSetLogSink(X2WShimLogSink sink, void* context) noexcept
{
    auto& state = log_state();
    AcquireSRWLockExclusive(&state.lock);
    state.sink = sink;
    state.sink_context = context;
    ReleaseSRWLockExclusive(&state.lock);
}

extern "C" X2W_GDK_API uint32_t X2WShimUnimplementedCount(void) noexcept { return g_unimplemented.load(); }

extern "C" X2W_GDK_API size_t X2WShimFirstUnimplemented(char* buffer, size_t size) noexcept
{
    auto& state = log_state();
    AcquireSRWLockShared(&state.lock);
    const std::string first = state.first;
    ReleaseSRWLockShared(&state.lock);
    if (buffer && size) {
        const size_t n = first.size() < size - 1 ? first.size() : size - 1;
        memcpy(buffer, first.data(), n);
        buffer[n] = '\0';
    }
    return first.size();
}
