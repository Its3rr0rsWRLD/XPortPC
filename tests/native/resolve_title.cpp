// Source-built, CRT-free title for tests/native/resolve_check.py: dynamic module lookups under x2w_launch.
// It imports kernel32.dll and x2w_resolve_pkg.dll (tests/native/resolve_pkg.cpp), which the check copies
// beside it so the launcher maps it as a package DLL. Exit code bits, 0x3f when everything works:
//   1    GetModuleHandleW(L"kernel32.dll") + GetProcAddress of SleepConditionVariableCS and
//        WakeAllConditionVariable from the title, and the functions behave
//   2    the same lookups from the package DLL (ResolvePkgProbe)
//   4    GetModuleHandleW, LoadLibraryW and GetProcAddress of the package DLL agree with its static import
//   8    LoadLibraryW(L"kernel32.dll") is the module GetModuleHandleW returns, and its file name is kernel32's
//   0x10 GetModuleHandleW(L"api-ms-win-core-synch-l1-2-0.dll") gives a module that exports
//        SleepConditionVariableCS (x2w_launch only; Windows does not answer API set names on every build)
//   0x20 a lookup of a name kernel32 lacks fails with ERROR_PROC_NOT_FOUND
// X2W_RESOLVE_MODE in the environment adds an ending for the run log:
//   fault  the package DLL hands lstrlenA a bad pointer (handled inside Windows), then ExitProcess(code)
//   crash  the title installs its own unhandled-exception filter, which ends the process with 0x66, then
//          writes through a null pointer
// It is never a title and holds no title code or data.
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" __declspec(dllimport) int ResolvePkgProbe();
extern "C" __declspec(dllimport) int ResolvePkgFault(const char* bad);

namespace {
using Sleep = BOOL(WINAPI*)(PCONDITION_VARIABLE, PCRITICAL_SECTION, DWORD);
using WakeAll = void(WINAPI*)(PCONDITION_VARIABLE);

bool synch_works(HMODULE module) {
    if (!module) return false;
    auto sleep = reinterpret_cast<Sleep>(GetProcAddress(module, "SleepConditionVariableCS"));
    auto wake = reinterpret_cast<WakeAll>(GetProcAddress(module, "WakeAllConditionVariable"));
    if (!sleep || !wake) return false;
    CONDITION_VARIABLE condition = CONDITION_VARIABLE_INIT;
    CRITICAL_SECTION section;
    InitializeCriticalSection(&section);
    EnterCriticalSection(&section);
    wake(&condition);
    const BOOL woke = sleep(&condition, &section, 1);
    const DWORD error = GetLastError();
    LeaveCriticalSection(&section);
    DeleteCriticalSection(&section);
    return !woke && error == ERROR_TIMEOUT;
}

bool ends_with_kernel32(const wchar_t* path, DWORD length) {
    const wchar_t tail[] = L"\\kernel32.dll";
    const DWORD n = sizeof tail / sizeof tail[0] - 1;
    if (length < n) return false;
    for (DWORD i = 0; i < n; ++i) {
        wchar_t c = path[length - n + i];
        if (c >= L'A' && c <= L'Z') c = static_cast<wchar_t>(c - L'A' + L'a');
        if (c != tail[i]) return false;
    }
    return true;
}

LONG WINAPI title_filter(EXCEPTION_POINTERS*) {
    TerminateProcess(GetCurrentProcess(), 0x66);
    return EXCEPTION_EXECUTE_HANDLER;
}

bool mode_is(const char* want) {
    char mode[16];
    const DWORD length = GetEnvironmentVariableA("X2W_RESOLVE_MODE", mode, sizeof mode);
    if (length == 0 || length >= sizeof mode) return false;
    for (DWORD i = 0; i <= length; ++i)
        if (mode[i] != want[i]) return false;
    return true;
}
}  // namespace

extern "C" DWORD resolve_entry(void*) {
    DWORD code = 0;
    HMODULE kernel32 = GetModuleHandleW(L"kernel32.dll");
    if (synch_works(kernel32)) code |= 1;
    if (ResolvePkgProbe() == 1) code |= 2;
    HMODULE package = GetModuleHandleW(L"x2w_resolve_pkg.dll");
    if (package && LoadLibraryW(L"x2w_resolve_pkg.dll") == package &&
        GetProcAddress(package, "ResolvePkgProbe") == reinterpret_cast<FARPROC>(&ResolvePkgProbe))
        code |= 4;
    wchar_t path[MAX_PATH];
    const DWORD length = GetModuleFileNameW(kernel32, path, MAX_PATH);
    if (kernel32 && LoadLibraryW(L"kernel32.dll") == kernel32 && ends_with_kernel32(path, length)) code |= 8;
    if (synch_works(GetModuleHandleW(L"api-ms-win-core-synch-l1-2-0.dll"))) code |= 0x10;
    SetLastError(0);
    if (kernel32 && !GetProcAddress(kernel32, "X2wNoSuchFunction") && GetLastError() == ERROR_PROC_NOT_FOUND)
        code |= 0x20;
    if (mode_is("fault")) {
        if (ResolvePkgFault(reinterpret_cast<const char*>(static_cast<ULONG_PTR>(0x10))) == 1) code |= 0x40;
        ExitProcess(code);
    }
    if (mode_is("crash")) {
        SetUnhandledExceptionFilter(title_filter);
        *static_cast<volatile DWORD*>(nullptr) = code;
    }
    return code;
}
