// Source-built program for the launcher's recent-calls trace, without a C runtime (tests/native/trace_check.py).
// It makes calls with known results through its imports and through GetProcAddress, then acts on X2W_TRACE_MODE:
//   (unset)  exits 0 when every result was right through the thunks, else 1 + the first wrong step;
//   crash    writes through a null pointer on the main thread;
//   break    runs __debugbreak() (continued by the launcher) and exits as above;
//   thread   a second thread calls MulDiv(2, 3, 1) and writes through a null pointer while the main thread waits.
// The calls, in order: MulDiv(6, 7, 1) = 42, SetLastError(1234), GetLastError() = 1234 (LastError survives the
// thunks), lstrlenA("trace") = 5, MultiByteToWideChar(CP_UTF8, 0, "abc", 3, buffer, 8) = 3 (six arguments, two on the
// stack), GetProcAddress(kernel32, "MulDiv") then MulDiv(3, 5, 1) = 15 through that pointer.
#include <windows.h>
#include <intrin.h>

#pragma runtime_checks("", off)

using MulDivFn = int(WINAPI*)(int, int, int);

static DWORD WINAPI crash_thread(void*)
{
    if (MulDiv(2, 3, 1) != 6) return 1;
    *static_cast<volatile int*>(nullptr) = 6;
    return 0;
}

static bool mode_is(const wchar_t* mode, const wchar_t* want)
{
    for (; *mode && *want; ++mode, ++want)
        if (*mode != *want) return false;
    return *mode == *want;
}

extern "C" DWORD trace_entry(void*)
{
    wchar_t mode[16] = {};
    GetEnvironmentVariableW(L"X2W_TRACE_MODE", mode, 16);
    DWORD failed = 0;
    if (MulDiv(6, 7, 1) != 42) failed = failed ? failed : 2;
    SetLastError(1234);
    if (GetLastError() != 1234) failed = failed ? failed : 3;
    if (lstrlenA("trace") != 5) failed = failed ? failed : 4;
    wchar_t wide[8] = {};
    if (MultiByteToWideChar(CP_UTF8, 0, "abc", 3, wide, 8) != 3 || wide[0] != L'a' || wide[2] != L'c')
        failed = failed ? failed : 5;
    auto dynamic = reinterpret_cast<MulDivFn>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "MulDiv"));
    if (!dynamic || dynamic(3, 5, 1) != 15) failed = failed ? failed : 6;
    if (mode_is(mode, L"crash")) *static_cast<volatile int*>(nullptr) = 1;
    if (mode_is(mode, L"break")) __debugbreak();
    if (mode_is(mode, L"thread")) {
        HANDLE thread = CreateThread(nullptr, 0, crash_thread, nullptr, 0, nullptr);
        if (thread) WaitForSingleObject(thread, 30000);
        return 7;
    }
    return failed ? 1 + failed : 0;
}
