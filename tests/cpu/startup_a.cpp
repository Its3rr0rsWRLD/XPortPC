// First of two CRT-free DLLs for the startup fixture. It has no dependencies, keeps the shared event log
// and a value set by its own initializer, so a dependent that initializes too early reads zero.
#include <windows.h>
#include <intrin.h>

#pragma runtime_checks("", off)

namespace {
char g_log[64];
volatile LONG g_length;
volatile LONG g_a_value;
}  // namespace

extern "C" __declspec(dllexport) void a_log(char event) {
    const LONG slot = _InterlockedIncrement(&g_length) - 1;
    if (slot < static_cast<LONG>(sizeof(g_log))) g_log[slot] = event;
}

// Copies the log to out and returns its length; out must hold 64 bytes.
extern "C" __declspec(dllexport) unsigned a_snapshot(char* out) {
    LONG length = g_length;
    if (length > static_cast<LONG>(sizeof(g_log))) length = sizeof(g_log);
    // An explicit copy: at /O2 MSVC turns a byte loop into a memcpy call, which a CRT-free DLL cannot link.
    if (length > 0) {
        __movsb(reinterpret_cast<unsigned char*>(out), reinterpret_cast<const unsigned char*>(g_log),
                static_cast<size_t>(length));
    }
    return static_cast<unsigned>(length);
}

extern "C" __declspec(dllexport) unsigned a_value() { return static_cast<unsigned>(g_a_value); }

extern "C" BOOL WINAPI a_main(HINSTANCE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        a_log('a');
#ifdef ALTER
        g_a_value = 9;
#else
        g_a_value = 7;
#endif
    }
    return TRUE;
}
