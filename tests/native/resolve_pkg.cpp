// A CRT-free package DLL for tests/native/resolve_check.py: x2w_launch maps it from the title's folder like a
// title-shipped C++ runtime. Its probe asks Windows for kernel32 by name and looks up two synchronization
// functions in it, as a C++ runtime does at startup; its fault probe hands a Windows function a bad pointer
// that the function catches itself. It holds no title code or data.
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" BOOL WINAPI resolve_pkg_main(HINSTANCE, DWORD, LPVOID) { return TRUE; }

// 1 when kernel32's SleepConditionVariableCS and WakeAllConditionVariable resolve and behave, else 0.
extern "C" __declspec(dllexport) int ResolvePkgProbe() {
    HMODULE kernel32 = GetModuleHandleW(L"kernel32.dll");
    if (!kernel32) return 0;
    using Sleep = BOOL(WINAPI*)(PCONDITION_VARIABLE, PCRITICAL_SECTION, DWORD);
    using WakeAll = void(WINAPI*)(PCONDITION_VARIABLE);
    auto sleep = reinterpret_cast<Sleep>(GetProcAddress(kernel32, "SleepConditionVariableCS"));
    auto wake = reinterpret_cast<WakeAll>(GetProcAddress(kernel32, "WakeAllConditionVariable"));
    if (!sleep || !wake) return 0;
    CONDITION_VARIABLE condition = CONDITION_VARIABLE_INIT;
    CRITICAL_SECTION section;
    InitializeCriticalSection(&section);
    EnterCriticalSection(&section);
    wake(&condition);
    const BOOL woke = sleep(&condition, &section, 1);  // nobody wakes it: times out
    const DWORD error = GetLastError();
    LeaveCriticalSection(&section);
    DeleteCriticalSection(&section);
    return !woke && error == ERROR_TIMEOUT ? 1 : 0;
}

// lstrlenA of an unreadable address: Windows raises an access violation inside its own code, handles it and
// returns 0. The result is used after the call, so the call is not a tail jump and this frame stays.
extern "C" __declspec(dllexport) int ResolvePkgFault(const char* bad) {
    const int length = lstrlenA(bad);
    return length == 0 ? 1 : 2 + length;
}
