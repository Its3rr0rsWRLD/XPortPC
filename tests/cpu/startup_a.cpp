// First of two CRT-free DLLs for the startup fixture. It keeps the shared logs and a value set by
// its initializer, so a dependent that initializes too early reads zero. Its TLS callback owns the slot.
#include "startup_tls.h"
#include <intrin.h>

#pragma runtime_checks("", off)

namespace {
char g_log[64];
volatile LONG g_length;
volatile LONG g_a_value;
DWORD g_tls_slot = TLS_OUT_OF_INDEXES;
SRWLOCK g_tls_lock = SRWLOCK_INIT;
StartupTlsEvent g_tls_events[startup_tls_capacity];
unsigned g_tls_count;

void record_tls(DWORD reason) {
    const DWORD thread = GetCurrentThreadId();
    const DWORD value = static_cast<DWORD>(reinterpret_cast<ULONG_PTR>(TlsGetValue(g_tls_slot)));
    AcquireSRWLockExclusive(&g_tls_lock);
    if (g_tls_count < startup_tls_capacity) {
        auto& event = g_tls_events[g_tls_count++];
        event.thread = thread;
        event.reason = reason;
        event.value = value;
    }
    ReleaseSRWLockExclusive(&g_tls_lock);
}
}  // namespace

extern "C" void NTAPI a_tls_callback(PVOID, DWORD reason, PVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_tls_slot = TlsAlloc();
        if (g_tls_slot != TLS_OUT_OF_INDEXES && !TlsSetValue(g_tls_slot, reinterpret_cast<void*>(1))) {
            TlsFree(g_tls_slot);
            g_tls_slot = TLS_OUT_OF_INDEXES;
        }
    }
    if (g_tls_slot == TLS_OUT_OF_INDEXES) return;
    if (reason == DLL_PROCESS_DETACH) {
        TlsFree(g_tls_slot);
        g_tls_slot = TLS_OUT_OF_INDEXES;
    } else {
        record_tls(reason);
    }
}

ULONG a_tls_index;
#pragma section(".tlscb", read)
extern "C" __declspec(allocate(".tlscb")) PIMAGE_TLS_CALLBACK a_tls_callbacks[] = {a_tls_callback, nullptr};
extern "C" const TlsDirectory _tls_used = {nullptr, nullptr, &a_tls_index, a_tls_callbacks, 0, 0};

extern "C" __declspec(dllexport) DWORD a_tls_slot() { return g_tls_slot; }

// The caller provides room for startup_tls_capacity entries. Copy under the lock because the
// mapped host may have other threads. Keep the critical section free of loader calls.
extern "C" __declspec(dllexport) unsigned a_tls_snapshot(StartupTlsEvent* out) {
    AcquireSRWLockShared(&g_tls_lock);
    const unsigned count = g_tls_count;
    __movsb(reinterpret_cast<unsigned char*>(out), reinterpret_cast<const unsigned char*>(g_tls_events),
            static_cast<size_t>(count) * sizeof(StartupTlsEvent));
    ReleaseSRWLockShared(&g_tls_lock);
    return count;
}

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
