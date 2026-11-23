// Source-built title with implicit TLS data and no C runtime. Its own TLS directory has a template with
// three __declspec(thread) values (one a pointer that base relocations fix up), declares a zero fill of
// kZeroFill bytes, and has one TLS callback. The main thread and two worker threads read and write their own
// copies, through the compiler's TLS access and through gs:[0x58][_tls_index] directly. The process exit
// code records which checks held: 0x13f when all did, under Windows and under x2w_launch alike. On
// DLL_PROCESS_DETACH the callback writes the main thread's value to standard output. The zero fill is
// declared but never read: Windows sizes and clears it as it likes, and the carrier passes the field on.
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" ULONG _tls_index = 0;

#pragma section(".tls", read, write)
#pragma section(".tls$ZZZ", read, write)
// The template runs from _tls_start to _tls_end, as in the C runtime's tlssup.c; the compiler places
// __declspec(thread) data in .tls$ between them.
extern "C" __declspec(allocate(".tls")) char _tls_start = 0;
extern "C" __declspec(allocate(".tls$ZZZ")) char _tls_end = 0;

namespace {
constexpr DWORD kZeroFill = 256;
constexpr int kTemplate = 0x5eed1234;  // tests/native/launch_title_check.py changes it in a copy
constexpr int kMainValue = 0x600d;
constexpr DWORD kWorkers = 2;

volatile int g_anchor;

struct Event {
    DWORD reason;
    DWORD thread;
    int value;
};
Event events[32];
volatile LONG event_count;
volatile unsigned char* main_block;
}  // namespace

__declspec(thread) int t_value = kTemplate;
__declspec(thread) unsigned long long t_pair[2] = {0x1111222233334444ull, 0};
__declspec(thread) volatile int* t_anchor = &g_anchor;

namespace {
struct TlsDirectory {
    void* start;
    void* end;
    ULONG* index;
    PIMAGE_TLS_CALLBACK* callbacks;
    DWORD zero_fill;
    DWORD characteristics;
};

void write_text(const char* text) {
    DWORD length = 0;
    while (text[length]) ++length;
    DWORD written = 0;
    WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), text, length, &written, nullptr);
}

void hex(char* out, DWORD value) {
    for (int i = 7; i >= 0; --i, value >>= 4) out[i] = "0123456789abcdef"[value & 15];
}

// This thread's TLS block as title code finds it: TEB.ThreadLocalStoragePointer[_tls_index].
volatile unsigned char* tls_block() {
    auto* const* vector = reinterpret_cast<unsigned char* const*>(__readgsqword(0x58));
    return vector ? vector[_tls_index] : nullptr;
}

DWORD template_size() {
    return static_cast<DWORD>(reinterpret_cast<ULONG_PTR>(&_tls_end) - reinterpret_cast<ULONG_PTR>(&_tls_start));
}

// The compiler's address of t_value lies in this thread's block at the offset its initializer has in the
// image's template.
bool block_matches() {
    volatile unsigned char* block = tls_block();
    if (!block) return false;
    const auto* value = reinterpret_cast<volatile unsigned char*>(&t_value);
    const DWORD size = template_size();
    if (value < block || value + sizeof(int) > block + size) return false;
    const auto offset = static_cast<DWORD>(value - block);
    const volatile unsigned char* initial = reinterpret_cast<volatile unsigned char*>(&_tls_start) + offset;
    const int linked = initial[0] | initial[1] << 8 | initial[2] << 16 | initial[3] << 24;
    return linked == kTemplate;
}

bool sees_template() { return t_value == kTemplate && t_pair[0] == 0x1111222233334444ull && t_pair[1] == 0 && t_anchor == &g_anchor; }

DWORD WINAPI worker(void* argument) {
    const int number = static_cast<int>(reinterpret_cast<ULONG_PTR>(argument));
    DWORD bits = 0;
    if (sees_template()) bits |= 1;
    if (block_matches()) bits |= 2;
    t_value = 0x1000 + number;
    t_pair[1] = static_cast<unsigned long long>(number);
    if (t_value == 0x1000 + number && t_pair[1] == static_cast<unsigned long long>(number)) bits |= 4;
    // A worker has its own block.
    if (tls_block() && tls_block() != main_block) bits |= 8;
    return bits;
}
}  // namespace

extern "C" void NTAPI tls_title_callback(PVOID, DWORD reason, PVOID) {
    const LONG slot = InterlockedIncrement(&event_count) - 1;
    if (slot < 32) events[slot] = {reason, GetCurrentThreadId(), t_value};
    if (reason == DLL_PROCESS_DETACH) {
        char line[] = "process-detach main=00000000\r\n";
        hex(line + 20, static_cast<DWORD>(t_value));
        write_text(line);
    }
}

#pragma section(".tlscb", read)
extern "C" __declspec(allocate(".tlscb")) PIMAGE_TLS_CALLBACK tls_title_callbacks[] = {tls_title_callback, nullptr};

extern "C" const TlsDirectory _tls_used = {&_tls_start, &_tls_end, &_tls_index, tls_title_callbacks, kZeroFill, 0};

extern "C" DWORD tls_entry(void*) {
    DWORD code = 0x100;
    const DWORD main_thread = GetCurrentThreadId();
    // The process attach ran once, on this thread, before the entry point, and saw the template.
    const LONG attached = event_count;
    if (attached == 1 && events[0].reason == DLL_PROCESS_ATTACH && events[0].thread == main_thread
        && events[0].value == kTemplate)
        code |= 0x10;
    if (sees_template()) code |= 0x01;
    if (block_matches()) code |= 0x02;
    main_block = tls_block();
    t_value = kMainValue;
    t_pair[1] = 0xabc;

    HANDLE threads[kWorkers];
    DWORD ids[kWorkers];
    DWORD results[kWorkers] = {};
    bool joined = true;
    for (DWORD i = 0; i < kWorkers; ++i) {
        threads[i] = CreateThread(nullptr, 0, worker, reinterpret_cast<void*>(static_cast<ULONG_PTR>(i + 1)), 0, &ids[i]);
        if (!threads[i]) ExitProcess(0xE0000001u);
        // One at a time, so each worker's attach and detach are ordered.
        joined = joined && WaitForSingleObject(threads[i], 10000) == WAIT_OBJECT_0
            && GetExitCodeThread(threads[i], &results[i]);
        CloseHandle(threads[i]);
    }
    if (!joined) ExitProcess(0xE0000002u);
    bool workers_ok = true;
    for (DWORD i = 0; i < kWorkers; ++i) workers_ok = workers_ok && results[i] == 0xf;
    if (workers_ok) code |= 0x04;
    // The workers' writes went to their own blocks: this thread's values and zero fill are unchanged.
    if (t_value == kMainValue && t_pair[1] == 0xabc) code |= 0x08;
    // Each worker's TLS callback saw the template on thread attach and its own value on thread detach.
    const LONG seen = event_count < 32 ? event_count : 32;
    bool callbacks_ok = true;
    for (DWORD i = 0; i < kWorkers; ++i) {
        int attach = 0, detach = 0;
        for (LONG k = 0; k < seen; ++k) {
            if (events[k].thread != ids[i]) continue;
            if (events[k].reason == DLL_THREAD_ATTACH && events[k].value == kTemplate) ++attach;
            else if (events[k].reason == DLL_THREAD_DETACH && events[k].value == static_cast<int>(0x1000 + i + 1)) ++detach;
            else callbacks_ok = false;
        }
        callbacks_ok = callbacks_ok && attach == 1 && detach == 1;
    }
    if (callbacks_ok) code |= 0x20;
    ExitProcess(code);
}
