// Source-built program for x2w_sys's synchronous-call-on-overlapped-handle fix and x2w_launch's stall detector,
// without a C runtime (tests/native/stall_check.py). Run under x2w_launch with --shims, --log and --timeout:
//   1. opens a temporary file with FILE_FLAG_OVERLAPPED, writes "0123456789" and reads it back in two 4-byte reads and
//      one 2-byte read with lpOverlapped null (the hooks issue each with a private OVERLAPPED and wait), then a read
//      at the end, which returns TRUE with 0 bytes, as a synchronous handle's would;
//   2. makes an outbound named pipe, opens its client end for reading with CreateFileW (synchronous) and blocks the
//      main thread in ReadFile on it; a second thread writes 4 bytes after X2W_STALL_MS milliseconds (default 3500),
//      so the launcher's watchdog sees the ReadFile pending for more than 2 s.
// Exit 0 when every step gave the right result, else 10 + the first wrong step.
#include <windows.h>

#pragma runtime_checks("", off)

static HANDLE g_server;

static DWORD parse_ms()
{
    wchar_t text[16] = {};
    if (!GetEnvironmentVariableW(L"X2W_STALL_MS", text, 16)) return 3500;
    DWORD value = 0;
    for (const wchar_t* c = text; *c >= L'0' && *c <= L'9'; ++c) value = value * 10 + static_cast<DWORD>(*c - L'0');
    return value;
}

static DWORD WINAPI writer(void* ms)
{
    Sleep(static_cast<DWORD>(reinterpret_cast<ULONG_PTR>(ms)));
    DWORD done = 0;
    WriteFile(g_server, "pipe", 4, &done, nullptr);
    return 0;
}

static bool same(const char* a, const char* b, DWORD n)
{
    for (DWORD i = 0; i < n; ++i)
        if (a[i] != b[i]) return false;
    return true;
}

extern "C" DWORD stall_entry(void*)
{
    // 1. Synchronous calls on an overlapped file handle.
    wchar_t path[MAX_PATH + 32];
    DWORD length = GetTempPathW(MAX_PATH, path);
    if (!length || length > MAX_PATH) return 11;
    const wchar_t leaf[] = L"x2w_stall_overlapped.bin";
    for (DWORD i = 0; i < sizeof leaf / sizeof leaf[0]; ++i) path[length + i] = leaf[i];
    HANDLE file = CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED | FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    if (file == INVALID_HANDLE_VALUE) return 12;
    DWORD done = 0;
    if (!WriteFile(file, "0123456789", 10, &done, nullptr) || done != 10) return 13;
    if (SetFilePointer(file, 0, nullptr, FILE_BEGIN) != 0) return 14;
    char buffer[8];
    if (!ReadFile(file, buffer, 4, &done, nullptr) || done != 4 || !same(buffer, "0123", 4)) return 15;
    if (!ReadFile(file, buffer, 4, &done, nullptr) || done != 4 || !same(buffer, "4567", 4)) return 16;
    if (!ReadFile(file, buffer, 4, &done, nullptr) || done != 2 || !same(buffer, "89", 2)) return 17;
    done = 7;
    if (!ReadFile(file, buffer, 4, &done, nullptr) || done != 0) return 18;
    CloseHandle(file);

    // 2. A synchronous pipe read that blocks the main thread.
    const wchar_t* pipe = L"\\\\.\\pipe\\x2w_stall_check";
    g_server = CreateNamedPipeW(pipe, PIPE_ACCESS_OUTBOUND, PIPE_TYPE_BYTE | PIPE_WAIT, 1, 64, 64, 0, nullptr);
    if (g_server == INVALID_HANDLE_VALUE) return 19;
    HANDLE client = CreateFileW(pipe, GENERIC_READ, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (client == INVALID_HANDLE_VALUE) return 20;
    HANDLE thread = CreateThread(nullptr, 0, writer, reinterpret_cast<void*>(static_cast<ULONG_PTR>(parse_ms())), 0, nullptr);
    if (!thread) return 21;
    if (!ReadFile(client, buffer, 4, &done, nullptr) || done != 4 || !same(buffer, "pipe", 4)) return 22;
    WaitForSingleObject(thread, 10000);
    CloseHandle(thread);
    CloseHandle(client);
    CloseHandle(g_server);
    return 0;
}
