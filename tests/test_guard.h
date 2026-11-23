// Bounds a test process: it ends by itself, with a line on stderr, whatever goes wrong.
//
// A test that crashes must not leave Windows Error Reporting behind it. An unhandled exception normally starts
// WerFault.exe in the crashing process's job; on the hidden PC worker that process can wait for a consent or upload
// that never comes, and a caller waiting for the whole process tree (a script job) then waits forever. The guard
// therefore ends the process itself on an unhandled exception, a CRT abort, assertion or invalid parameter, and after
// a wall-clock limit (a watchdog thread), each time with one FATAL line that names the stage the test reached.
//
// The guard allocates nothing through operator new (era_title_gpu_alloc_check replaces it) and is header-only.
//
// Public APIs used (Microsoft Learn): SetUnhandledExceptionFilter, SetErrorMode, TerminateProcess, CreateThread,
// _set_abort_behavior, _set_invalid_parameter_handler, _CrtSetReportMode.
#pragma once

#include <windows.h>

#include <crtdbg.h>

#include <cstdarg>
#include <cstdio>
#include <cstdlib>

namespace test_guard {

inline volatile const char* g_stage = "start";
inline const char* g_name = "test";
inline DWORD g_seconds = 0;

inline void write_stderr(const char* format, ...) noexcept
{
    char line[512];
    va_list args;
    va_start(args, format);
    const int length = std::vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (length <= 0) return;
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_ERROR_HANDLE), line,
              static_cast<DWORD>(length < static_cast<int>(sizeof(line)) ? length : sizeof(line) - 1), &written,
              nullptr);
}

[[noreturn]] inline void end(UINT code) noexcept
{
    TerminateProcess(GetCurrentProcess(), code);
    ExitProcess(code);  // not reached
}

// Names what the test is doing now; the FATAL line reports the last stage set. Pass a string literal.
inline void stage(const char* name) noexcept
{
    g_stage = name;
}

inline LONG WINAPI unhandled(EXCEPTION_POINTERS* info) noexcept
{
    const EXCEPTION_RECORD* record = info ? info->ExceptionRecord : nullptr;
    write_stderr("FATAL: %s: unhandled exception 0x%08lx at %p during stage '%s'\n", g_name,
                 record ? record->ExceptionCode : 0ul, record ? record->ExceptionAddress : nullptr,
                 const_cast<const char*>(g_stage));
    end(3);
}

inline void invalid_parameter(const wchar_t*, const wchar_t*, const wchar_t*, unsigned, uintptr_t) noexcept
{
    write_stderr("FATAL: %s: CRT invalid parameter during stage '%s'\n", g_name, const_cast<const char*>(g_stage));
    end(3);
}

inline DWORD WINAPI watchdog(void*) noexcept
{
    Sleep(g_seconds * 1000);
    write_stderr("FATAL: %s: still running after %lu s (stage '%s'); ending the process\n", g_name, g_seconds,
                 const_cast<const char*>(g_stage));
    end(124);
}

// Call first in main. `seconds` should be below the test's ctest TIMEOUT, so the test reports its own stage before
// ctest has to kill it; 0 installs no watchdog. X2W_TEST_WATCHDOG_S overrides it.
inline void install(const char* name, DWORD seconds) noexcept
{
    g_name = name;
    char text[16];
    const DWORD length = GetEnvironmentVariableA("X2W_TEST_WATCHDOG_S", text, sizeof(text));
    if (length > 0 && length < sizeof(text)) seconds = static_cast<DWORD>(std::strtoul(text, nullptr, 10));
    g_seconds = seconds;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
    SetUnhandledExceptionFilter(unhandled);
    _set_invalid_parameter_handler(invalid_parameter);
    _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
    _CrtSetReportMode(_CRT_ERROR, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ERROR, _CRTDBG_FILE_STDERR);
    _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ASSERT, _CRTDBG_FILE_STDERR);
    // Each line reaches the log even if the process is ended mid-run.
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    if (seconds) {
        if (HANDLE thread = CreateThread(nullptr, 64 * 1024, watchdog, nullptr, STACK_SIZE_PARAM_IS_A_RESERVATION,
                                         nullptr)) {
            CloseHandle(thread);
        }
    }
}

}  // namespace test_guard
