#include <windows.h>
#include <cstdint>

static DWORD WINAPI hold_worker(void* ready)
{
    HANDLE park = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!park)
        return 1;
    const DWORD result = SetEvent(ready) ? WaitForSingleObject(park, INFINITE) : 1;
    CloseHandle(park);
    return result;
}

static bool start_test_worker()
{
    // Used only by the process lifetime regression. Wait for the worker to
    // signal that it started, or report an error if it exits first.
    HANDLE ready = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!ready)
        return false;
    HANDLE worker = CreateThread(nullptr, 0, hold_worker, ready, 0, nullptr);
    bool started = false;
    if (worker) {
        HANDLE handles[] = {ready, worker};
        started = WaitForMultipleObjects(2, handles, FALSE, INFINITE) == WAIT_OBJECT_0;
        CloseHandle(worker);
    }
    CloseHandle(ready);
    return started;
}

static bool prepare_test_worker(const wchar_t* flag)
{
    wchar_t value[2];
    return GetEnvironmentVariableW(flag, value, 2) != 1 ||
        value[0] != L'1' || start_test_worker();
}

extern "C" __declspec(dllexport) std::uint32_t read_selector()
{
    if (!prepare_test_worker(L"CPU_EXE_TEST_LIVE_WORKER")) {
        // Distinguish a failed test setup from empty stdin.
        ExitProcess(3);
    }
    BYTE input;
    DWORD count;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE), &input, 1, &count, nullptr) || count != 1)
        return UINT32_MAX;
    return input;
}

static bool write_bytes(DWORD stream, const void* data, DWORD size)
{
    DWORD written;
    return WriteFile(GetStdHandle(stream), data, size, &written, nullptr) && written == size;
}

extern "C" __declspec(dllexport) std::uint32_t emit_trace(const std::uint64_t* words)
{
    // The provider wrote its first two arguments and the result into the entry's buffer.
    return write_bytes(STD_ERROR_HANDLE, words, 16) && write_bytes(STD_OUTPUT_HANDLE, words + 2, 8);
}

extern "C" __declspec(dllexport) DWORD finish_exe(const void* image_base, DWORD code)
{
    // The console fixture uses UCRT stdin rather than read_selector.
    if (!prepare_test_worker(L"CPU_CRC_TEST_LIVE_WORKER"))
        code = 3;
    if (image_base == GetModuleHandleW(nullptr))
        ExitProcess(code);
    return code;
}
