// Event sink for the lifecycle fixtures. It is CRT-free and loaded by the test host before the fixture DLLs,
// so it outlives them: the destructors and detach notifications of the DLLs under test can still log here.
#include <windows.h>
#include <intrin.h>

#pragma runtime_checks("", off)

namespace {
// An explicit copy: at /O2 MSVC turns a byte loop into a memcpy call, which a CRT-free DLL cannot link.
void copy_bytes(char* destination, const char* source, LONG count) {
    if (count > 0) {
        __movsb(reinterpret_cast<unsigned char*>(destination), reinterpret_cast<const unsigned char*>(source),
                static_cast<size_t>(count));
    }
}
}  // namespace

namespace {
char g_text[1024];
volatile LONG g_length;
}  // namespace

// Appends "token," to the log. Tokens that do not fit are dropped whole.
extern "C" __declspec(dllexport) void sink_log(const char* token) {
    LONG size = 0;
    while (token[size]) ++size;
    const LONG start = _InterlockedExchangeAdd(&g_length, size + 1);
    if (start + size + 1 > static_cast<LONG>(sizeof(g_text))) return;
    copy_bytes(g_text + start, token, size);
    g_text[start + size] = ',';
}

// Copies the log into out (capacity bytes) and returns its length.
extern "C" __declspec(dllexport) unsigned sink_snapshot(char* out, unsigned capacity) {
    LONG length = g_length;
    if (length > static_cast<LONG>(sizeof(g_text))) length = sizeof(g_text);
    if (static_cast<unsigned>(length) > capacity) length = static_cast<LONG>(capacity);
    copy_bytes(out, g_text, length);
    return static_cast<unsigned>(length);
}

extern "C" BOOL WINAPI sink_main(HINSTANCE, DWORD, LPVOID) { return TRUE; }
