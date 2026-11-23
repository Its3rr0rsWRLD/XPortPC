#include "check.h"
#include "sys_hooks.h"
#include "sys_paths.h"
#include "../../src/common/x2w_redact.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <string>

using namespace x2w_sys;
using namespace x2w_sys::paths;

namespace {
std::wstring make_temp_root() {
    wchar_t base[MAX_PATH];
    GetTempPathW(MAX_PATH, base);
    std::wstring root = std::wstring(base) + L"x2w_sys_paths_" + std::to_wstring(GetCurrentProcessId());
    CreateDirectoryW(root.c_str(), nullptr);
    return root;
}

void make_dirs(const std::wstring& p) {
    const size_t cut = p.find_last_of(L'\\');
    if (cut != std::wstring::npos && cut > 3 && GetFileAttributesW(p.c_str()) == INVALID_FILE_ATTRIBUTES) {
        make_dirs(p.substr(0, cut));
        CreateDirectoryW(p.c_str(), nullptr);
    }
}

void write_file(const std::wstring& path, const char* text) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    DWORD n = 0;
    WriteFile(h, text, static_cast<DWORD>(strlen(text)), &n, nullptr);
    CloseHandle(h);
}

void remove_tree(const std::wstring& dir) {
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW((dir + L"\\*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            const std::wstring n = fd.cFileName;
            if (n == L"." || n == L"..") continue;
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) remove_tree(dir + L"\\" + n);
            else DeleteFileW((dir + L"\\" + n).c_str());
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    RemoveDirectoryW(dir.c_str());
}

template <typename F>
F hook(const char* name) { return reinterpret_cast<F>(X2WSysHookLookup("kernel32.dll", name)); }
}  // namespace

int main() {
    chk::capture();

    // ---- redaction (x2w_redact.h): UNC paths and an account-name leaf are hidden; device names stay ----------
    {
        char user[256] = {};
        const DWORD had = GetEnvironmentVariableA("USERNAME", user, sizeof user);
        SetEnvironmentVariableA("USERNAME", "SomeUser");
        CHECK(x2w_redact::hide_paths("open \\\\srv\\share\\dir\\a.bin (5)", "", "") == std::string("open <path>\\a.bin (5)"));
        CHECK(x2w_redact::hide_paths("at \\\\?\\UNC\\srv\\s\\b.txt", "", "") == std::string("at <path>\\b.txt"));
        CHECK(x2w_redact::hide_paths("at \\\\?\\C:\\x\\c.txt", "", "") == std::string("at <path>\\c.txt"));
        CHECK(x2w_redact::hide_paths("pipe \\\\.\\pipe\\x2w", "", "") == std::string("pipe \\\\.\\pipe\\x2w"));
        CHECK(x2w_redact::hide_paths("home C:\\Users\\someuser", "", "") == std::string("home <path>"));
        CHECK(x2w_redact::hide_paths("file C:\\Users\\someuser\\d.txt", "", "") == std::string("file <path>\\d.txt"));
        SetEnvironmentVariableA("USERNAME", had && had < sizeof user ? user : nullptr);
    }

    // ---- pure remapping -------------------------------------------------------------------------------
    {
        Map m;
        Context c;
        c.title_dir = L"C:\\Titles\\Foo";
        c.title_name = L"Foo";
        c.local_app_data = L"C:\\Users\\u\\AppData\\Local";
        m.set_context(c);
        m.add_default_rules();
        CHECK_EQ(m.size(), 3u);
        auto r = m.remap(L"G:\\data\\a.pak");
        CHECK(r.remapped && r.path == L"C:\\Titles\\Foo\\data\\a.pak");
        r = m.remap(L"g:/data/a.pak");  // case and slash
        CHECK(r.remapped && r.path == L"C:\\Titles\\Foo\\data\\a.pak");
        r = m.remap(L"G:");
        CHECK(r.remapped && r.path == L"C:\\Titles\\Foo");
        r = m.remap(L"G:\\");
        CHECK(r.remapped && r.path == L"C:\\Titles\\Foo\\");
        r = m.remap(L"\\\\?\\G:\\x");
        CHECK(r.remapped && r.path == L"\\\\?\\C:\\Titles\\Foo\\x");
        r = m.remap(L"T:\\cache\\1.bin");
        CHECK(r.remapped && r.mkdir && r.path == L"C:\\Users\\u\\AppData\\Local\\XPortPC\\Foo\\temp\\cache\\1.bin");
        r = m.remap(L"D:\\s");
        CHECK(r.remapped && r.path == L"C:\\Users\\u\\AppData\\Local\\XPortPC\\Foo\\scratch\\s");
        // Not remapped: other drives, drive-relative, UNC, relative, a longer name that starts like a rule.
        CHECK(!m.remap(L"C:\\Windows").remapped);
        CHECK(!m.remap(L"G:foo").remapped);
        CHECK(!m.remap(L"\\\\server\\G:\\x").remapped);
        CHECK(!m.remap(L"data\\a.pak").remapped);
        CHECK(!m.remap(L"").remapped);
        // Longest prefix and replacement of an equal source.
        CHECK(m.add_rule("G:\\Save -> C:\\Elsewhere\\Save"));
        r = m.remap(L"G:\\Save\\slot1");
        CHECK(r.remapped && r.path == L"C:\\Elsewhere\\Save\\slot1");
        r = m.remap(L"G:\\SaveGames\\x");  // component boundary: only the G: rule matches
        CHECK(r.remapped && r.path == L"C:\\Titles\\Foo\\SaveGames\\x");
        CHECK(m.add_rule("g:\\ -> C:\\Other"));
        CHECK_EQ(m.size(), 4u);
        CHECK(m.remap(L"G:\\a").path == L"C:\\Other\\a");
        // Bad rules.
        std::string err;
        CHECK(!m.add_rule("G:\\ C:\\x", &err));
        CHECK(!m.add_rule("foo -> C:\\x", &err));
        CHECK(!m.add_rule("X:\\ -> relative\\dir", &err));
        CHECK(!m.add_rule("X:\\ -> %NOPE%\\x", &err));
        CHECK(!m.add_rule("X:\\ ->", &err));
        // Flags.
        CHECK(m.add_rule("M:\\ -> C:\\ro ro mkdir"));
        r = m.remap(L"M:\\f");
        CHECK(r.deny_write && r.mkdir);
    }

    // ---- hooked file system -------------------------------------------------------------------------
    const std::wstring root = make_temp_root();
    const std::wstring title = root + L"\\title";
    const std::wstring lad = root + L"\\lad";
    make_dirs(title + L"\\data");
    make_dirs(lad);
    write_file(title + L"\\data\\a.txt", "hello");
    {
        Map& m = global_map();
        m.clear();
        Context c;
        c.title_dir = title;
        c.title_name = L"Foo";
        c.local_app_data = lad;
        m.set_context(c);
        m.add_default_rules();
        CHECK(m.add_rule(("R:\\ -> " + narrow(root) + "\\rodir ro").c_str()));
        make_dirs(root + L"\\rodir");
        write_file(root + L"\\rodir\\r.txt", "ro");
    }
    auto pCreateFileW = hook<HANDLE(WINAPI*)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE)>("CreateFileW");
    auto pAttr = hook<DWORD(WINAPI*)(LPCWSTR)>("GetFileAttributesW");
    auto pAttrEx = hook<BOOL(WINAPI*)(LPCWSTR, GET_FILEEX_INFO_LEVELS, LPVOID)>("GetFileAttributesExW");
    auto pFindEx = hook<HANDLE(WINAPI*)(LPCWSTR, FINDEX_INFO_LEVELS, LPVOID, FINDEX_SEARCH_OPS, LPVOID, DWORD)>("FindFirstFileExW");
    auto pMkdir = hook<BOOL(WINAPI*)(LPCWSTR, LPSECURITY_ATTRIBUTES)>("CreateDirectoryW");
    auto pDel = hook<BOOL(WINAPI*)(LPCWSTR)>("DeleteFileW");
    auto pMove = hook<BOOL(WINAPI*)(LPCWSTR, LPCWSTR, DWORD)>("MoveFileExW");
    auto pRmdir = hook<BOOL(WINAPI*)(LPCWSTR)>("RemoveDirectoryW");
    CHECK(pCreateFileW && pAttr && pAttrEx && pFindEx && pMkdir && pDel && pMove && pRmdir);
    CHECK(X2WSysHookLookup("kernel32.dll", "HeapAlloc") == nullptr);
    CHECK(X2WSysHookLookup("user32.dll", "CreateFileW") == nullptr);
    CHECK(X2WSysHookLookup("api-ms-win-core-file-l1-1-0.dll", "CreateFileW") == X2WSysHookLookup("kernel32.dll", "CreateFileW"));
    if (!(pCreateFileW && pAttr && pAttrEx && pFindEx && pMkdir && pDel && pMove && pRmdir)) return finish("sys_paths");

    // G: read side, three different calls.
    CHECK(pAttr(L"G:\\data\\a.txt") != INVALID_FILE_ATTRIBUTES);
    WIN32_FILE_ATTRIBUTE_DATA ad{};
    CHECK(pAttrEx(L"G:\\data\\a.txt", GetFileExInfoStandard, &ad) && ad.nFileSizeLow == 5);
    {
        HANDLE h = pCreateFileW(L"G:\\data\\a.txt", GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        CHECK(h != INVALID_HANDLE_VALUE);
        char buf[8] = {};
        DWORD n = 0;
        if (h != INVALID_HANDLE_VALUE) { ReadFile(h, buf, 8, &n, nullptr); CloseHandle(h); }
        CHECK(n == 5 && std::string(buf, n) == "hello");
    }
    {
        WIN32_FIND_DATAW fd{};
        HANDLE h = pFindEx(L"G:\\data\\*", FindExInfoBasic, &fd, FindExSearchNameMatch, nullptr, 0);
        bool found = false;
        if (h != INVALID_HANDLE_VALUE) {
            do { if (std::wstring(fd.cFileName) == L"a.txt") found = true; } while (FindNextFileW(h, &fd));
            FindClose(h);
        }
        CHECK(found);
    }
    // Control: a missing file under G: fails; the same relative name did not appear anywhere else.
    CHECK(pAttr(L"G:\\data\\missing.txt") == INVALID_FILE_ATTRIBUTES);
    CHECK(pAttr((title + L"\\data\\a.txt").c_str()) != INVALID_FILE_ATTRIBUTES);  // unmapped path passes through

    // T: write side: parent folders appear on demand under the XPortPC folder.
    const std::wstring temp = lad + L"\\XPortPC\\Foo\\temp";
    {
        HANDLE h = pCreateFileW(L"T:\\sub\\dir\\f.bin", GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr);
        CHECK(h != INVALID_HANDLE_VALUE);
        DWORD n = 0;
        if (h != INVALID_HANDLE_VALUE) { WriteFile(h, "abc", 3, &n, nullptr); CloseHandle(h); }
        CHECK(GetFileAttributesW((temp + L"\\sub\\dir\\f.bin").c_str()) != INVALID_FILE_ATTRIBUTES);
    }
    CHECK(pMove(L"T:\\sub\\dir\\f.bin", L"T:\\moved\\g.bin", MOVEFILE_REPLACE_EXISTING));
    CHECK(GetFileAttributesW((temp + L"\\moved\\g.bin").c_str()) != INVALID_FILE_ATTRIBUTES);
    CHECK(pMkdir(L"D:\\one\\two", nullptr));
    CHECK(GetFileAttributesW((lad + L"\\XPortPC\\Foo\\scratch\\one\\two").c_str()) != INVALID_FILE_ATTRIBUTES);
    CHECK(pRmdir(L"D:\\one\\two"));
    CHECK(pDel(L"T:\\moved\\g.bin"));
    CHECK(GetFileAttributesW((temp + L"\\moved\\g.bin").c_str()) == INVALID_FILE_ATTRIBUTES);

    // Read-only rule: reads work, writes fail with access denied, nothing is created.
    {
        HANDLE h = pCreateFileW(L"R:\\r.txt", GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, 0, nullptr);
        CHECK(h != INVALID_HANDLE_VALUE);
        if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
        SetLastError(0);
        HANDLE w = pCreateFileW(L"R:\\new.txt", GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr);
        CHECK(w == INVALID_HANDLE_VALUE && GetLastError() == ERROR_ACCESS_DENIED);
        CHECK(GetFileAttributesW((root + L"\\rodir\\new.txt").c_str()) == INVALID_FILE_ATTRIBUTES);
        CHECK(!pDel(L"R:\\r.txt") && GetLastError() == ERROR_ACCESS_DENIED);
    }

    // Each rule and each distinct path is logged once, however often it is used.
    CHECK_EQ(chk::count("path rule G:"), 1);
    CHECK_EQ(chk::count("path rule T:"), 1);
    CHECK_EQ(chk::count("path remap <path>\\a.txt ->")  /* drive paths are redacted (x2w_redact.h) */, 1);
    CHECK(chk::count("read only") == 1 || chk::count("is read only") >= 1);
    CHECK(global_stats().remaps > 10);
    CHECK(global_stats().denied >= 2);

    remove_tree(root);
    return finish("sys_paths");
}
