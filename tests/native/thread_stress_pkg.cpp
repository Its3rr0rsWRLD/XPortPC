// Package DLL of the thread-start stress title (tests/native/thread_stress_title.cpp): built with the static C
// runtime, so it has its own implicit TLS (a template value and a thread_local std::string with a dynamic
// initializer) and its DllMain receives DLL_THREAD_ATTACH/DETACH. Every thread checks that its block starts from
// the template before DllMain or the title touches it; stress_pkg_bad() counts the checks that failed.
#include <windows.h>

#include <atomic>
#include <string>

namespace {
constexpr unsigned kTemplate = 0x2b9d0e41u;
std::atomic<long> failures{0};
constexpr unsigned kMark = 0x600d600du;
thread_local unsigned p_value = kTemplate;
thread_local unsigned p_mark = kMark;
thread_local std::string p_name = "pkg";
}  // namespace

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID) {
    if (reason == DLL_THREAD_ATTACH && (p_value != kTemplate || p_name != "pkg")) ++failures;
    // On detach the runtime's TLS callback has already destroyed p_name; trivial data is still there.
    if (reason == DLL_THREAD_DETACH && p_mark != kMark) ++failures;
    return TRUE;
}

extern "C" __declspec(dllexport) int __cdecl stress_pkg_touch(int value) {
    if (p_value != kTemplate || p_name != "pkg") ++failures;
    p_value = static_cast<unsigned>(value);
    p_name = "pkg-" + std::to_string(value);
    Sleep(0);
    return p_value == static_cast<unsigned>(value) && p_name == "pkg-" + std::to_string(value);
}

extern "C" __declspec(dllexport) long __cdecl stress_pkg_bad() { return failures.load(); }
