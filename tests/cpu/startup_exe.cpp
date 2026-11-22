// CRT-free EXE importing both DLLs and kernel32. Its TLS callback and entry point log into the first
// DLL; the entry point then runs two worker threads in turn, each with a per-thread value kept by TlsAlloc (an
// explicit slot, not implicit __declspec(thread) data) and writes the whole log to standard output.
// Exit code: b_value() | first worker's value << 8 | second worker's << 16 | main thread's << 24.
// A failure ends the process with 0xE0000001 (TlsAlloc), 0xE0000002 (CreateThread), 0xE0000003 (wait timed out),
// 0xE0000004 (wait failed) or 0xE0000005 (unexpected wait result).
#include <windows.h>
#include <intrin.h>

#pragma runtime_checks("", off)

extern "C" __declspec(dllimport) void a_log(char event);
extern "C" __declspec(dllimport) unsigned a_snapshot(char* out);
extern "C" __declspec(dllimport) unsigned b_value();

namespace {
DWORD g_slot;
volatile DWORD g_worker_value;
DWORD g_next_value;

// A failed worker setup or a wait that does not return WAIT_OBJECT_0 must not be consumed as a result: the
// worker could still be writing the shared log or g_worker_value. The EXE ends the whole process with a
// code that names the failure. ExitProcess stops every other thread, which CloseHandle does not: closing a
// handle leaves the thread running. In a mapped image a thread that outlived the entry point would also run
// unmapped code. The codes are reported by the isolated child, never by the host test process.
constexpr UINT TLS_ALLOC_FAILED = 0xE0000001u, CREATE_FAILED = 0xE0000002u, WAIT_TIMED_OUT = 0xE0000003u,
               WAIT_FAILED_CODE = 0xE0000004u, WAIT_UNEXPECTED = 0xE0000005u;
#if defined(TIMEOUT_CONTROL)
constexpr DWORD WAIT_MS = 1;  // control: the worker sleeps far longer than this
#else
constexpr DWORD WAIT_MS = 10000;  // shorter than the harness's 30 s process limit, so the exit code is observed
#endif
#if defined(CREATE_CONTROL)
constexpr SIZE_T STACK_SIZE = static_cast<SIZE_T>(1) << 62;  // control: larger than the address space, so CreateThread
                                                           // fails with ERROR_INVALID_PARAMETER whatever the free memory
#else
constexpr SIZE_T STACK_SIZE = 0;
#endif

DWORD WINAPI worker(void*) {
#ifdef TIMEOUT_CONTROL
    Sleep(500);
#endif
    TlsSetValue(g_slot, reinterpret_cast<void*>(static_cast<ULONG_PTR>(g_next_value)));
    const DWORD seen = static_cast<DWORD>(reinterpret_cast<ULONG_PTR>(TlsGetValue(g_slot)));
    g_worker_value = seen;
    a_log('w');
    a_log(static_cast<char>('0' + seen));
    return 0;
}

void write_line(HANDLE out, const char* prefix, const char* text, unsigned length) {
    char line[96];
    unsigned n = 0;
    for (; prefix[n]; ++n) line[n] = prefix[n];
    // An explicit copy: at /O2 MSVC turns a byte loop into a memcpy call, which a CRT-free EXE cannot link.
    __movsb(reinterpret_cast<unsigned char*>(line + n), reinterpret_cast<const unsigned char*>(text), length);
    n += length;
    line[n++] = '\n';
    DWORD written = 0;
    WriteFile(out, line, n, &written, nullptr);
}
}  // namespace

extern "C" void NTAPI tls_callback(PVOID, DWORD reason, PVOID) {
    if (reason == DLL_PROCESS_ATTACH) a_log('t');
}

extern "C" ULONG tls_index_slot;
ULONG tls_index_slot;

#pragma section(".tlscb", read)
extern "C" __declspec(allocate(".tlscb")) PIMAGE_TLS_CALLBACK tls_callbacks[] = {tls_callback, nullptr};

// The linker finds the TLS directory through this name. Pointer members keep it a constant initializer
// with base relocations; the layout is IMAGE_TLS_DIRECTORY64 with an empty data template.
struct TlsDirectory {
    void* start;
    void* end;
    ULONG* index;
    PIMAGE_TLS_CALLBACK* callbacks;
    DWORD zero_fill;
    DWORD characteristics;
};
extern "C" const TlsDirectory _tls_used = {nullptr, nullptr, &tls_index_slot, tls_callbacks, 0, 0};

extern "C" DWORD WINAPI exe_entry(void*) {
    a_log('e');
    g_slot = TlsAlloc();
    if (g_slot == TLS_OUT_OF_INDEXES) ExitProcess(TLS_ALLOC_FAILED);
    TlsSetValue(g_slot, reinterpret_cast<void*>(1));
    DWORD worker_values[2];
    for (DWORD i = 0; i < 2; ++i) {  // two workers one after the other, so the log order is fixed
        g_next_value = 2 + i;
        HANDLE thread = CreateThread(nullptr, STACK_SIZE, worker, nullptr, 0, nullptr);
        if (!thread) ExitProcess(CREATE_FAILED);
        const DWORD waited = WaitForSingleObject(thread, WAIT_MS);
        if (waited == WAIT_TIMEOUT) ExitProcess(WAIT_TIMED_OUT);
        if (waited == WAIT_FAILED) ExitProcess(WAIT_FAILED_CODE);
        if (waited != WAIT_OBJECT_0) ExitProcess(WAIT_UNEXPECTED);
        CloseHandle(thread);  // the worker has finished; this only releases the handle
        worker_values[i] = g_worker_value;
    }
    const DWORD mine = static_cast<DWORD>(reinterpret_cast<ULONG_PTR>(TlsGetValue(g_slot)));
    a_log('m');
    a_log(static_cast<char>('0' + mine));

    char log[64];
    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    write_line(out, "LOG:", log, a_snapshot(log));
    return b_value() | (worker_values[0] << 8) | (worker_values[1] << 16) | (mine << 24);
}
