#include "sys_paths.h"

#include "sys_common.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <intrin.h>

#include <cstdio>

#include <algorithm>
#include <atomic>
#include <cwctype>
#include <mutex>
#include <unordered_map>

namespace x2w_sys::paths {
namespace {

std::wstring lower(std::wstring s) {
    for (auto& c : s) c = static_cast<wchar_t>(std::towlower(c));
    return s;
}

std::wstring normalize_slashes(std::wstring s) {
    std::replace(s.begin(), s.end(), L'/', L'\\');
    return s;
}

void strip_trailing_backslashes(std::wstring& s) {
    while (s.size() > 3 && s.back() == L'\\') s.pop_back();
    if (s.size() == 3 && s[1] == L':' && s[2] == L'\\') s.pop_back();  // "G:\" -> "G:"
}

bool is_drive_form(const std::wstring& s) {
    return s.size() >= 2 && std::iswalpha(s[0]) && s[1] == L':' && (s.size() == 2 || s[2] == L'\\');
}

std::wstring replace_all_ci(std::wstring text, const std::wstring& token, const std::wstring& value) {
    const std::wstring lt = lower(token);
    for (;;) {
        const size_t pos = lower(text).find(lt);
        if (pos == std::wstring::npos) break;
        text.replace(pos, token.size(), value);
    }
    return text;
}

}  // namespace

void Map::set_context(const Context& ctx) {
    ctx_ = ctx;
    if (ctx_.local_app_data.empty()) ctx_.local_app_data = widen(get_env("LOCALAPPDATA"));
}

std::wstring Map::expand(const std::wstring& text) const {
    std::wstring xport = ctx_.local_app_data + L"\\XPortPC\\" + ctx_.title_name;
    std::wstring out = replace_all_ci(text, L"%XPORT%", xport);
    out = replace_all_ci(out, L"%TITLEDIR%", ctx_.title_dir);
    out = replace_all_ci(out, L"%LOCALAPPDATA%", ctx_.local_app_data);
    out = replace_all_ci(out, L"%TITLE%", ctx_.title_name);
    return out;
}

bool Map::add_rule(const std::string& spec, std::string* error) {
    auto fail = [&](const char* why) {
        if (error) *error = why;
        return false;
    };
    const size_t arrow = spec.find("->");
    if (arrow == std::string::npos) return fail("missing '->'");
    const std::wstring from_raw = widen(trim(spec.substr(0, arrow)));
    std::string rest = trim(spec.substr(arrow + 2));
    Rule rule;
    rule.spec = spec;
    // Trailing flag words.
    for (bool again = true; again;) {
        again = false;
        const size_t sp = rest.find_last_of(" \t");
        if (sp == std::string::npos) break;
        const std::string word = rest.substr(sp + 1);
        if (word == "ro") rule.read_only = again = true;
        else if (word == "mkdir") rule.mkdir = again = true;
        if (again) rest = trim(rest.substr(0, sp));
    }
    if (rest.empty()) return fail("empty target");
    std::wstring from = normalize_slashes(from_raw);
    if (!is_drive_form(from)) return fail("source must start with a drive letter such as G:\\");
    strip_trailing_backslashes(from);
    std::wstring to = normalize_slashes(expand(widen(rest)));
    if (to.find(L'%') != std::wstring::npos) return fail("unknown variable in target");
    if (!is_drive_form(to)) return fail("target must be an absolute drive path");
    strip_trailing_backslashes(to);
    rule.from = from;
    rule.to = to;
    for (auto& r : rules_) {
        if (lower(r.from) == lower(from)) {  // same source: the later rule replaces it
            r = rule;
            return true;
        }
    }
    rules_.push_back(rule);
    std::stable_sort(rules_.begin(), rules_.end(),
                     [](const Rule& a, const Rule& b) { return a.from.size() > b.from.size(); });
    return true;
}

void Map::add_default_rules() {
    add_rule("G:\\ -> %TITLEDIR%");
    add_rule("T:\\ -> %XPORT%\\temp mkdir");
    add_rule("D:\\ -> %XPORT%\\scratch mkdir");
}

void Map::clear() { rules_.clear(); }

Result Map::remap(const std::wstring& input) const {
    Result res;
    res.path = input;
    if (input.empty() || rules_.empty()) return res;
    std::wstring p = normalize_slashes(input);
    std::wstring prefix;
    if (p.compare(0, 4, L"\\\\?\\") == 0) {
        prefix = p.substr(0, 4);
        p = p.substr(4);
    }
    if (!is_drive_form(p) || (p.size() > 2 && p[2] != L'\\')) return res;
    for (size_t i = 0; i < rules_.size(); ++i) {
        const Rule& r = rules_[i];
        const size_t n = r.from.size();
        if (p.size() < n || _wcsnicmp(p.c_str(), r.from.c_str(), n) != 0) continue;
        if (p.size() != n && p[n] != L'\\') continue;
        res.remapped = true;
        res.deny_write = r.read_only;
        res.mkdir = r.mkdir;
        res.rule_index = i;
        res.path = prefix + r.to + p.substr(n);
        return res;
    }
    return res;
}

// ---------------------------------------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------------------------------------
namespace {

Map g_map;
Stats g_stats;
std::atomic<unsigned> g_distinct_logged{0};
constexpr unsigned kMaxDistinctPathLogs = 512;

void ensure_dir(const std::wstring& dir) {
    size_t floor = 3;
    if (dir.compare(0, 4, L"\\\\?\\") == 0) floor = 7;
    if (dir.size() <= floor) return;
    const DWORD a = GetFileAttributesW(dir.c_str());
    if (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY)) return;
    const size_t cut = dir.find_last_of(L'\\');
    if (cut != std::wstring::npos && cut >= floor) ensure_dir(dir.substr(0, cut));
    CreateDirectoryW(dir.c_str(), nullptr);
}

void ensure_parent(const std::wstring& path) {
    const size_t cut = path.find_last_of(L'\\');
    if (cut != std::wstring::npos) ensure_dir(path.substr(0, cut));
}

struct Prepared {
    std::wstring path;
    bool use_original = true;
};

// Returns false when the call must fail (read-only rule); the last error is set.
bool prepare(LPCWSTR in, bool write_intent, bool create_intent, Prepared& out) {
    if (!in || !*in) return true;
    const Result r = g_map.remap(in);
    if (!r.remapped) return true;
    const Rule& rule = g_map.rule(r.rule_index);
    const std::string from_utf8 = narrow(in);
    log_once("pathrule:" + rule.spec, "path rule %s -> %s (first use: %s -> %s)", narrow(rule.from).c_str(),
             narrow(rule.to).c_str(), from_utf8.c_str(), narrow(r.path).c_str());
    if (g_distinct_logged.load(std::memory_order_relaxed) < kMaxDistinctPathLogs) {
        if (log_once("path:" + narrow(lower(in)), "path remap %s -> %s", from_utf8.c_str(), narrow(r.path).c_str()))
            g_distinct_logged.fetch_add(1, std::memory_order_relaxed);
    }
    if (write_intent && r.deny_write) {
        InterlockedIncrement64(reinterpret_cast<volatile LONG64*>(&g_stats.denied));
        log_once("pathdeny:" + rule.spec, "path rule %s is read only: write-like call on %s denied",
                 narrow(rule.from).c_str(), from_utf8.c_str());
        SetLastError(ERROR_ACCESS_DENIED);
        return false;
    }
    InterlockedIncrement64(reinterpret_cast<volatile LONG64*>(&g_stats.remaps));
    if (create_intent && r.mkdir) ensure_parent(r.path);
    out.path = r.path;
    out.use_original = false;
    return true;
}

std::wstring from_acp(LPCSTR s) {
    if (!s) return {};
    const int n = MultiByteToWideChar(CP_ACP, 0, s, -1, nullptr, 0);
    if (n <= 1) return {};
    std::wstring w(static_cast<size_t>(n - 1), L'\0');
    MultiByteToWideChar(CP_ACP, 0, s, -1, w.data(), n);
    return w;
}

inline LPCWSTR use(const Prepared& p, LPCWSTR original) { return p.use_original ? original : p.path.c_str(); }

constexpr DWORD kWriteAccess = GENERIC_WRITE | GENERIC_ALL | FILE_WRITE_DATA | FILE_APPEND_DATA | DELETE |
                               FILE_WRITE_ATTRIBUTES | FILE_WRITE_EA;

bool creates(DWORD disposition) {
    return disposition == CREATE_NEW || disposition == CREATE_ALWAYS || disposition == OPEN_ALWAYS ||
           disposition == TRUNCATE_EXISTING;
}

// ---- open log and the handle table ----------------------------------------------------------------------
// The first kMaxOpenLogs opens through the hooks are logged ("file-open NAME -> handle 0x.. access= share= disp=
// flags=(...) type=disk|pipe|char|remote|unknown"); every handle the title opened is kept with its flags until
// CloseHandle, so ReadFile/WriteFile can tell an overlapped (asynchronous) handle cheaply.
struct OpenInfo {
    DWORD flags = 0;
    DWORD type = FILE_TYPE_UNKNOWN;
    std::string name;  // as logged
};
SRWLOCK g_handles_lock = SRWLOCK_INIT;
std::unordered_map<HANDLE, OpenInfo>* g_handles;  // never freed: hooks may run during process exit
std::atomic<long> g_handle_count{0};
std::atomic<unsigned> g_opens_logged{0};
std::atomic<unsigned> g_sync_async_logged{0};
constexpr unsigned kMaxOpenLogs = 400, kMaxSyncAsyncLogs = 32;

// The name a log line shows: device names (\\.\pipe\x, CONIN$, NUL) verbatim, drive paths whole (the log
// redaction turns them into <path>\leaf), any other path with folders as <path>\leaf.
std::string shown_name(const std::wstring& path) {
    if (path.compare(0, 4, L"\\\\.\\") == 0) return narrow(path);
    std::wstring p = path;
    if (p.compare(0, 4, L"\\\\?\\") == 0) p = p.substr(4);
    if (is_drive_form(p)) return narrow(path);
    const size_t cut = p.find_last_of(L"\\/");
    if (cut == std::wstring::npos) return narrow(p);
    return "<path>\\" + narrow(p.substr(cut + 1));
}

const char* type_name(DWORD type) {
    switch (type & ~FILE_TYPE_REMOTE) {
        case FILE_TYPE_DISK: return "disk";
        case FILE_TYPE_PIPE: return "pipe";
        case FILE_TYPE_CHAR: return "char";
        default: return (type & FILE_TYPE_REMOTE) ? "remote" : "unknown";
    }
}

const char* disp_name(DWORD disp) {
    switch (disp) {
        case CREATE_NEW: return "CREATE_NEW";
        case CREATE_ALWAYS: return "CREATE_ALWAYS";
        case OPEN_EXISTING: return "OPEN_EXISTING";
        case OPEN_ALWAYS: return "OPEN_ALWAYS";
        case TRUNCATE_EXISTING: return "TRUNCATE_EXISTING";
        default: return "?";
    }
}

std::string flag_text(DWORD flags) {
    static const struct { DWORD bit; const char* name; } kFlags[] = {
        {FILE_FLAG_WRITE_THROUGH, "WRITE_THROUGH"}, {FILE_FLAG_OVERLAPPED, "OVERLAPPED"},
        {FILE_FLAG_NO_BUFFERING, "NO_BUFFERING"}, {FILE_FLAG_RANDOM_ACCESS, "RANDOM_ACCESS"},
        {FILE_FLAG_SEQUENTIAL_SCAN, "SEQUENTIAL_SCAN"}, {FILE_FLAG_DELETE_ON_CLOSE, "DELETE_ON_CLOSE"},
        {FILE_FLAG_BACKUP_SEMANTICS, "BACKUP_SEMANTICS"}, {FILE_FLAG_POSIX_SEMANTICS, "POSIX_SEMANTICS"},
        {FILE_FLAG_OPEN_REPARSE_POINT, "OPEN_REPARSE_POINT"}, {FILE_FLAG_OPEN_NO_RECALL, "OPEN_NO_RECALL"}};
    std::string out;
    DWORD rest = flags;
    for (const auto& f : kFlags)
        if (flags & f.bit) {
            if (!out.empty()) out += '|';
            out += f.name;
            rest &= ~f.bit;
        }
    if (rest) {
        char hex[16];
        std::snprintf(hex, sizeof hex, "0x%lx", static_cast<unsigned long>(rest));
        if (!out.empty()) out += '|';
        out += hex;
    }
    return "(" + out + ")";
}

void after_open(const std::wstring& path, HANDLE h, DWORD access, DWORD share, DWORD disp, DWORD flags) {
    const DWORD error = GetLastError();
    const bool ok = h != INVALID_HANDLE_VALUE && h != nullptr;
    OpenInfo info;
    info.flags = flags;
    info.name = shown_name(path);
    if (ok) {
        info.type = GetFileType(h);
        AcquireSRWLockExclusive(&g_handles_lock);
        if (!g_handles) g_handles = new std::unordered_map<HANDLE, OpenInfo>;
        (*g_handles)[h] = info;
        g_handle_count.store(static_cast<long>(g_handles->size()), std::memory_order_relaxed);
        ReleaseSRWLockExclusive(&g_handles_lock);
    }
    if (g_opens_logged.fetch_add(1, std::memory_order_relaxed) < kMaxOpenLogs) {
        char result[48];
        if (ok) std::snprintf(result, sizeof result, "handle 0x%llx", static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(h)));
        else std::snprintf(result, sizeof result, "failed error %lu", error);
        log("file-open %s -> %s access=0x%lx share=0x%lx disp=%s flags=%s type=%s", info.name.c_str(), result,
            static_cast<unsigned long>(access), static_cast<unsigned long>(share), disp_name(disp),
            flag_text(flags).c_str(), ok ? type_name(info.type) : "none");
    }
    SetLastError(error);
}

bool find_open(HANDLE h, OpenInfo* out) {
    if (g_handle_count.load(std::memory_order_relaxed) == 0) return false;
    AcquireSRWLockShared(&g_handles_lock);
    bool found = false;
    if (g_handles) {
        const auto it = g_handles->find(h);
        if (it != g_handles->end()) {
            found = true;
            if (out) *out = it->second;
        }
    }
    ReleaseSRWLockShared(&g_handles_lock);
    return found;
}

using NtQueryInformationFileFn = LONG(NTAPI*)(HANDLE, void*, void*, ULONG, ULONG);

// FILE_SYNCHRONOUS_IO_ALERT | FILE_SYNCHRONOUS_IO_NONALERT clear in FileModeInformation: an asynchronous handle.
bool handle_is_async(HANDLE h) {
    static const auto query = reinterpret_cast<NtQueryInformationFileFn>(
        GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtQueryInformationFile"));
    if (!query) return true;
    ULONG_PTR iosb[2] = {};
    ULONG mode = 0;
    if (query(h, iosb, &mode, sizeof mode, 16 /* FileModeInformation */) < 0) return true;
    return (mode & (0x10 | 0x20)) == 0;
}

// ReadFile/WriteFile with lpOverlapped null on a handle opened with FILE_FLAG_OVERLAPPED. Windows then has no file
// position to use (a disk file fails with ERROR_INVALID_PARAMETER) and waits on the file handle itself, which is how a
// console-style title that expects such a call to block can hang or fail. Issued here with a private OVERLAPPED and
// event at the handle's file pointer (disk files; the pointer is moved past the bytes done) and waited for.
BOOL sync_io_on_async(HANDLE h, const OpenInfo& info, void* buffer, DWORD size, LPDWORD done_out, bool write,
                      void* caller) {
    if (g_sync_async_logged.fetch_add(1, std::memory_order_relaxed) < kMaxSyncAsyncLogs)
        log("sync-%s-on-async-handle handle 0x%llx name %s type %s size 0x%lx caller=0x%llx (issued with a private "
            "OVERLAPPED and waited for)", write ? "write" : "read",
            static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(h)), info.name.c_str(), type_name(info.type),
            static_cast<unsigned long>(size), static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(caller)));
    OVERLAPPED o{};
    o.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!o.hEvent) return FALSE;
    const bool disk = (info.type & ~FILE_TYPE_REMOTE) == FILE_TYPE_DISK;
    LARGE_INTEGER pos{};
    if (disk) {
        const LARGE_INTEGER zero{};
        if (SetFilePointerEx(h, zero, &pos, FILE_CURRENT)) {
            o.Offset = pos.LowPart;
            o.OffsetHigh = static_cast<DWORD>(pos.HighPart);
        }
    }
    BOOL ok = write ? WriteFile(h, buffer, size, nullptr, &o) : ReadFile(h, buffer, size, nullptr, &o);
    DWORD done = 0;
    DWORD error = ok ? ERROR_SUCCESS : GetLastError();
    if (ok || error == ERROR_IO_PENDING) {
        ok = GetOverlappedResult(h, &o, &done, TRUE);
        error = ok ? ERROR_SUCCESS : GetLastError();
    }
    if (!ok && !write && error == ERROR_HANDLE_EOF) {  // a synchronous read at the end returns TRUE with 0 bytes
        ok = TRUE;
        error = ERROR_SUCCESS;
    }
    if (disk && ok) {
        pos.QuadPart += done;
        SetFilePointerEx(h, pos, nullptr, FILE_BEGIN);
    }
    CloseHandle(o.hEvent);
    if (done_out) *done_out = done;
    SetLastError(error);
    return ok;
}

BOOL WINAPI h_ReadFile(HANDLE h, LPVOID buffer, DWORD size, LPDWORD done, LPOVERLAPPED ov) {
    OpenInfo info;
    if (!ov && find_open(h, &info) && (info.flags & FILE_FLAG_OVERLAPPED) && handle_is_async(h))
        return sync_io_on_async(h, info, buffer, size, done, false, _ReturnAddress());
    return ReadFile(h, buffer, size, done, ov);
}

BOOL WINAPI h_WriteFile(HANDLE h, LPCVOID buffer, DWORD size, LPDWORD done, LPOVERLAPPED ov) {
    OpenInfo info;
    if (!ov && find_open(h, &info) && (info.flags & FILE_FLAG_OVERLAPPED) && handle_is_async(h))
        return sync_io_on_async(h, info, const_cast<void*>(buffer), size, done, true, _ReturnAddress());
    return WriteFile(h, buffer, size, done, ov);
}

BOOL WINAPI h_CloseHandle(HANDLE h) {
    if (g_handle_count.load(std::memory_order_relaxed) != 0) {
        AcquireSRWLockExclusive(&g_handles_lock);
        if (g_handles && g_handles->erase(h))
            g_handle_count.store(static_cast<long>(g_handles->size()), std::memory_order_relaxed);
        ReleaseSRWLockExclusive(&g_handles_lock);
    }
    return CloseHandle(h);
}

HANDLE WINAPI h_CreateFileW(LPCWSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD flags,
                            HANDLE tmpl) {
    Prepared p;
    const bool write = (access & kWriteAccess) != 0 || creates(disp) || (flags & FILE_FLAG_DELETE_ON_CLOSE);
    if (!prepare(name, write, write && (creates(disp) || (access & kWriteAccess)), p)) {
        after_open(name ? name : L"", INVALID_HANDLE_VALUE, access, share, disp, flags);
        return INVALID_HANDLE_VALUE;
    }
    HANDLE h = CreateFileW(use(p, name), access, share, sa, disp, flags, tmpl);
    after_open(use(p, name) ? use(p, name) : L"", h, access, share, disp, flags);
    return h;
}

HANDLE WINAPI h_CreateFileA(LPCSTR name, DWORD access, DWORD share, LPSECURITY_ATTRIBUTES sa, DWORD disp, DWORD flags,
                            HANDLE tmpl) {
    const std::wstring w = from_acp(name);
    return h_CreateFileW(w.empty() ? nullptr : w.c_str(), access, share, sa, disp, flags, tmpl);
}

HANDLE WINAPI h_CreateFile2(LPCWSTR name, DWORD access, DWORD share, DWORD disp,
                            LPCREATEFILE2_EXTENDED_PARAMETERS params) {
    Prepared p;
    const bool write = (access & kWriteAccess) != 0 || creates(disp);
    const DWORD flags = params ? params->dwFileFlags | params->dwFileAttributes | params->dwSecurityQosFlags : 0;
    if (!prepare(name, write, write, p)) {
        after_open(name ? name : L"", INVALID_HANDLE_VALUE, access, share, disp, flags);
        return INVALID_HANDLE_VALUE;
    }
    HANDLE h = CreateFile2(use(p, name), access, share, disp, params);
    after_open(use(p, name) ? use(p, name) : L"", h, access, share, disp, flags);
    return h;
}

HANDLE WINAPI h_FindFirstFileW(LPCWSTR name, LPWIN32_FIND_DATAW data) {
    Prepared p;
    prepare(name, false, false, p);
    return FindFirstFileW(use(p, name), data);
}

HANDLE WINAPI h_FindFirstFileExW(LPCWSTR name, FINDEX_INFO_LEVELS level, LPVOID data, FINDEX_SEARCH_OPS op, LPVOID filter,
                                 DWORD flags) {
    Prepared p;
    prepare(name, false, false, p);
    return FindFirstFileExW(use(p, name), level, data, op, filter, flags);
}

DWORD WINAPI h_GetFileAttributesW(LPCWSTR name) {
    Prepared p;
    prepare(name, false, false, p);
    return GetFileAttributesW(use(p, name));
}

DWORD WINAPI h_GetFileAttributesA(LPCSTR name) {
    const std::wstring w = from_acp(name);
    return h_GetFileAttributesW(w.empty() ? nullptr : w.c_str());
}

BOOL WINAPI h_GetFileAttributesExW(LPCWSTR name, GET_FILEEX_INFO_LEVELS level, LPVOID info) {
    Prepared p;
    prepare(name, false, false, p);
    return GetFileAttributesExW(use(p, name), level, info);
}

BOOL WINAPI h_SetFileAttributesW(LPCWSTR name, DWORD attrs) {
    Prepared p;
    if (!prepare(name, true, false, p)) return FALSE;
    return SetFileAttributesW(use(p, name), attrs);
}

BOOL WINAPI h_CreateDirectoryW(LPCWSTR name, LPSECURITY_ATTRIBUTES sa) {
    Prepared p;
    if (!prepare(name, true, true, p)) return FALSE;
    return CreateDirectoryW(use(p, name), sa);
}

BOOL WINAPI h_RemoveDirectoryW(LPCWSTR name) {
    Prepared p;
    if (!prepare(name, true, false, p)) return FALSE;
    return RemoveDirectoryW(use(p, name));
}

BOOL WINAPI h_DeleteFileW(LPCWSTR name) {
    Prepared p;
    if (!prepare(name, true, false, p)) return FALSE;
    return DeleteFileW(use(p, name));
}

BOOL WINAPI h_MoveFileExW(LPCWSTR from, LPCWSTR to, DWORD flags) {
    Prepared a, b;
    if (!prepare(from, true, false, a)) return FALSE;
    if (!prepare(to, true, true, b)) return FALSE;
    return MoveFileExW(use(a, from), to ? use(b, to) : nullptr, flags);
}

BOOL WINAPI h_MoveFileW(LPCWSTR from, LPCWSTR to) { return h_MoveFileExW(from, to, 0); }

BOOL WINAPI h_CopyFileW(LPCWSTR from, LPCWSTR to, BOOL fail_if_exists) {
    Prepared a, b;
    prepare(from, false, false, a);
    if (!prepare(to, true, true, b)) return FALSE;
    return CopyFileW(use(a, from), use(b, to), fail_if_exists);
}

BOOL WINAPI h_GetDiskFreeSpaceExW(LPCWSTR dir, PULARGE_INTEGER avail, PULARGE_INTEGER total, PULARGE_INTEGER freeb) {
    Prepared p;
    prepare(dir, false, false, p);
    return GetDiskFreeSpaceExW(dir ? use(p, dir) : nullptr, avail, total, freeb);
}

const HookEntry kHooks[] = {
    {"CreateFileW", reinterpret_cast<void*>(&h_CreateFileW)},
    {"CreateFileA", reinterpret_cast<void*>(&h_CreateFileA)},
    {"CreateFile2", reinterpret_cast<void*>(&h_CreateFile2)},
    {"ReadFile", reinterpret_cast<void*>(&h_ReadFile)},
    {"WriteFile", reinterpret_cast<void*>(&h_WriteFile)},
    {"CloseHandle", reinterpret_cast<void*>(&h_CloseHandle)},
    {"FindFirstFileW", reinterpret_cast<void*>(&h_FindFirstFileW)},
    {"FindFirstFileExW", reinterpret_cast<void*>(&h_FindFirstFileExW)},
    {"GetFileAttributesW", reinterpret_cast<void*>(&h_GetFileAttributesW)},
    {"GetFileAttributesA", reinterpret_cast<void*>(&h_GetFileAttributesA)},
    {"GetFileAttributesExW", reinterpret_cast<void*>(&h_GetFileAttributesExW)},
    {"SetFileAttributesW", reinterpret_cast<void*>(&h_SetFileAttributesW)},
    {"CreateDirectoryW", reinterpret_cast<void*>(&h_CreateDirectoryW)},
    {"RemoveDirectoryW", reinterpret_cast<void*>(&h_RemoveDirectoryW)},
    {"DeleteFileW", reinterpret_cast<void*>(&h_DeleteFileW)},
    {"MoveFileExW", reinterpret_cast<void*>(&h_MoveFileExW)},
    {"MoveFileW", reinterpret_cast<void*>(&h_MoveFileW)},
    {"CopyFileW", reinterpret_cast<void*>(&h_CopyFileW)},
    {"GetDiskFreeSpaceExW", reinterpret_cast<void*>(&h_GetDiskFreeSpaceExW)},
};

}  // namespace

bool describe_handle(void* handle, std::string* out) {
    OpenInfo info;
    if (!find_open(static_cast<HANDLE>(handle), &info)) return false;
    if (out) *out = "opened-as " + info.name + " flags=" + flag_text(info.flags) + " type-at-open=" + type_name(info.type);
    return true;
}

Map& global_map() { return g_map; }
Stats& global_stats() { return g_stats; }

void apply_config_line(const std::string& key, const std::string& value) {
    if (key != "map") return;
    std::string error;
    if (!g_map.add_rule(value, &error)) log("config: bad map rule '%s': %s", value.c_str(), error.c_str());
}

void log_summary() {
    log("paths: %llu remapped calls, %llu denied by read-only rules, %zu rules", g_stats.remaps, g_stats.denied,
        g_map.size());
}

const HookEntry* hooks(size_t* count) {
    *count = sizeof kHooks / sizeof kHooks[0];
    return kHooks;
}

}  // namespace x2w_sys::paths
