#include "check.h"
#include "sys_hooks.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <string>

namespace {
void put_file(const std::string& path, const std::string& text) {
    HANDLE h = CreateFileA(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    DWORD n = 0;
    WriteFile(h, text.data(), static_cast<DWORD>(text.size()), &n, nullptr);
    CloseHandle(h);
}
void rm_rf(const std::string& dir) {
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA((dir + "\\*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            const std::string n = fd.cFileName;
            if (n == "." || n == "..") continue;
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) rm_rf(dir + "\\" + n);
            else DeleteFileA((dir + "\\" + n).c_str());
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }
    RemoveDirectoryA(dir.c_str());
}
}  // namespace

int main() {
    chk::capture();
    char tmp[MAX_PATH];
    GetTempPathA(MAX_PATH, tmp);
    const std::string root = std::string(tmp) + "x2w_sys_hooks_" + std::to_string(GetCurrentProcessId());
    const std::string title = root + "\\Game";
    const std::string lad = root + "\\lad";
    CreateDirectoryA(root.c_str(), nullptr);
    CreateDirectoryA(title.c_str(), nullptr);
    CreateDirectoryA(lad.c_str(), nullptr);
    CreateDirectoryA((lad + "\\XPortPC").c_str(), nullptr);
    CreateDirectoryA((lad + "\\XPortPC\\Game").c_str(), nullptr);
    CreateDirectoryA((lad + "\\XPortPC\\Game\\temp").c_str(), nullptr);
    CreateDirectoryA((lad + "\\XPortPC\\Game\\temp\\old").c_str(), nullptr);
    CreateDirectoryA((lad + "\\XPortPC\\Game\\scratch").c_str(), nullptr);
    put_file(lad + "\\XPortPC\\Game\\temp\\old\\stale.bin", "stale");
    put_file(lad + "\\XPortPC\\Game\\scratch\\keep.bin", "keep");
    SetEnvironmentVariableA("LOCALAPPDATA", lad.c_str());
    const std::string cfg = root + "\\x2w-sys.cfg";
    put_file(cfg,
             "# test config\n"
             "map P:\\ -> %XPORT%\\persist mkdir\n"
             "map X:\\media -> %TITLEDIR%\\media\n"
             "map bogus rule\n"
             "threads.virtual_cores = 8\n"
             "timing.qpc_frequency 1000000000\n");

    CHECK_EQ(X2WSysInit(title.c_str(), "Game", cfg.c_str()), 0);
    CHECK_EQ(chk::count("paths: rule G: -> "), 1);
    CHECK_EQ(chk::count("paths: rule P: -> "), 1);
    CHECK_EQ(chk::count("paths: rule X:\\media -> "), 1);
    CHECK_EQ(chk::count("bad map rule 'bogus rule'"), 1);
    CHECK_EQ(chk::count("threads: reporting 8 cores"), 1);
    CHECK_EQ(chk::count("QueryPerformanceFrequency reports 1000000000 Hz"), 1);
    // T: is cleared at start, D: is not.
    CHECK(GetFileAttributesA((lad + "\\XPortPC\\Game\\temp\\old\\stale.bin").c_str()) == INVALID_FILE_ATTRIBUTES);
    CHECK(GetFileAttributesA((lad + "\\XPortPC\\Game\\temp").c_str()) != INVALID_FILE_ATTRIBUTES);
    CHECK(GetFileAttributesA((lad + "\\XPortPC\\Game\\scratch\\keep.bin").c_str()) != INVALID_FILE_ATTRIBUTES);
    CHECK_EQ(chk::count("cleared temporary storage"), 1);

    // The lookup serves every module's Win32 names under the right dll names.
    const char* names[] = {"CreateFileW", "FindFirstFileExW", "GetFileAttributesExW", "CreateDirectoryW", "SetThreadAffinityMask",
                           "SetThreadIdealProcessor", "GetSystemInfo", "GetLogicalProcessorInformationEx",
                           "QueryPerformanceCounter", "QueryPerformanceFrequency", "GetCurrentProcessorNumber"};
    for (const char* n : names) {
        CHECK(X2WSysHookLookup("kernel32.dll", n) != nullptr);
        CHECK(X2WSysHookLookup("KERNEL32.DLL", n) == X2WSysHookLookup("kernelbase.dll", n));
    }
    CHECK(X2WSysHookLookup("kernel32.dll", "HeapAlloc") == nullptr);
    CHECK(X2WSysHookLookup("xgameruntime.dll", "CreateFileW") == nullptr);
    CHECK(X2WSysHookLookup(nullptr, "CreateFileW") == nullptr);

    // End to end: a P: write lands under the XPortPC folder and the configured topology is visible.
    using CreateFileWFn = HANDLE(WINAPI*)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
    auto create = reinterpret_cast<CreateFileWFn>(X2WSysHookLookup("kernel32.dll", "CreateFileW"));
    HANDLE h = create(L"P:\\slot0\\save.dat", GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr);
    CHECK(h != INVALID_HANDLE_VALUE);
    if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
    CHECK(GetFileAttributesA((lad + "\\XPortPC\\Game\\persist\\slot0\\save.dat").c_str()) != INVALID_FILE_ATTRIBUTES);
    auto sysinfo = reinterpret_cast<void(WINAPI*)(LPSYSTEM_INFO)>(X2WSysHookLookup("kernel32.dll", "GetSystemInfo"));
    SYSTEM_INFO si{};
    sysinfo(&si);
    CHECK_EQ(si.dwNumberOfProcessors, 8u);

    X2WSysShutdown();
    CHECK_EQ(chk::count("paths: 1 remapped calls") + chk::count("paths: 2 remapped calls"), 1);
    CHECK(chk::count("audio: formats seen") == 1 && chk::count("directstorage: fallback") == 1);

    // A user rule that moves T: elsewhere keeps its folder out of the cleaner.
    chk::capture();
    put_file(cfg, "map T:\\ -> %TITLEDIR%\\mytemp\n");
    CreateDirectoryA((title + "\\mytemp").c_str(), nullptr);
    put_file(title + "\\mytemp\\file", "x");
    CHECK_EQ(X2WSysInit(title.c_str(), "Game", cfg.c_str()), 0);
    CHECK(GetFileAttributesA((title + "\\mytemp\\file").c_str()) != INVALID_FILE_ATTRIBUTES);
    CHECK_EQ(chk::count("cleared temporary storage"), 0);

    rm_rf(root);
    return finish("sys_hooks");
}
