// Source-built, CRT-free title for tests/native/heap_guard_check.py: frees that do not belong to the heap they are
// handed to, under x2w_launch's heap guard (tools/x2w_launch.cpp, "heap guard"). It imports kernel32.dll,
// xmem.dll (XMemAlloc, XMemFree) and ucrtbase.dll (malloc, free). Exit code bits, 0 when everything works:
//   1    an XMemAlloc pointer handed to the C runtime's free() is refused (the block stays usable) and XMemFree
//        then releases it
//   2    HeapFree(GetProcessHeap()) of a stack buffer (static import) is refused and reports success
//   4    the same through GetProcAddress(kernel32, "HeapFree")
//   8    HeapSize of a stack buffer gives (SIZE_T)-1
//   0x10 HeapReAlloc of a stack buffer gives a new heap block holding the buffer's bytes
//   0x20 XMemFree of a HeapAlloc block is ignored: the block is still valid, unchanged, and HeapFree releases it
//   0x40 malloc + free of a C runtime block works
//   0x80 the process heap validates at the end
// X2W_HEAP_MODE=control in the environment does only the stack HeapFree, for a run without the guard.
// It is never a title and holds no title code or data.
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" __declspec(dllimport) void* __cdecl malloc(SIZE_T bytes);
extern "C" __declspec(dllimport) void __cdecl free(void* block);
extern "C" __declspec(dllimport) PVOID WINAPI XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void WINAPI XMemFree(PVOID address, ULONGLONG attributes);

namespace {
using HeapFreeFn = BOOL(WINAPI*)(HANDLE, DWORD, LPVOID);

void fill(volatile unsigned char* bytes, unsigned count, unsigned char seed) {
    for (unsigned i = 0; i < count; ++i) bytes[i] = static_cast<unsigned char>(seed + i);
}

bool holds(const volatile unsigned char* bytes, unsigned count, unsigned char seed) {
    for (unsigned i = 0; i < count; ++i)
        if (bytes[i] != static_cast<unsigned char>(seed + i)) return false;
    return true;
}

bool control_mode() {
    char value[16] = {};
    return GetEnvironmentVariableA("X2W_HEAP_MODE", value, sizeof value) && lstrcmpA(value, "control") == 0;
}
}  // namespace

extern "C" int heap_entry() {
    const HANDLE heap = GetProcessHeap();
    volatile unsigned char stack[96];
    fill(stack, sizeof stack, 0x31);
    if (control_mode()) return HeapFree(heap, 0, const_cast<unsigned char*>(stack)) ? 0 : 2;

    int failed = 0;
    // 1: XMemAlloc memory (the xmem layer's own allocator) given to the C runtime's free.
    auto* xmem = static_cast<volatile unsigned char*>(XMemAlloc(64, 0));
    if (xmem) {
        fill(xmem, 64, 0x10);
        free(const_cast<unsigned char*>(xmem));
        if (!holds(xmem, 64, 0x10)) failed |= 1;
        XMemFree(const_cast<unsigned char*>(xmem), 0);
    } else {
        failed |= 1;
    }
    // 2, 4: a stack buffer handed to HeapFree, imported and looked up.
    if (!HeapFree(heap, 0, const_cast<unsigned char*>(stack))) failed |= 2;
    auto dynamic_free = reinterpret_cast<HeapFreeFn>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "HeapFree"));
    if (!dynamic_free || !dynamic_free(heap, 0, const_cast<unsigned char*>(stack + 16))) failed |= 4;
    if (!holds(stack, sizeof stack, 0x31)) failed |= 2;
    // 8, 0x10: HeapSize and HeapReAlloc of the stack buffer.
    if (HeapSize(heap, 0, const_cast<unsigned char*>(stack)) != static_cast<SIZE_T>(-1)) failed |= 8;
    auto* moved = static_cast<unsigned char*>(HeapReAlloc(heap, 0, const_cast<unsigned char*>(stack), 32));
    if (!moved || !holds(moved, 32, 0x31) || !HeapValidate(heap, 0, moved) || !HeapFree(heap, 0, moved)) failed |= 0x10;
    // 0x20: a heap block handed to XMemFree.
    auto* block = static_cast<volatile unsigned char*>(HeapAlloc(heap, 0, 48));
    if (block) {
        fill(block, 48, 0x60);
        XMemFree(const_cast<unsigned char*>(block), 0);
        if (!HeapValidate(heap, 0, const_cast<unsigned char*>(block)) || !holds(block, 48, 0x60) ||
            !HeapFree(heap, 0, const_cast<unsigned char*>(block)))
            failed |= 0x20;
    } else {
        failed |= 0x20;
    }
    // 0x40: a C runtime block freed by the C runtime.
    auto* crt = static_cast<volatile unsigned char*>(malloc(100));
    if (crt) {
        fill(crt, 100, 0x7);
        free(const_cast<unsigned char*>(crt));
    } else {
        failed |= 0x40;
    }
    if (!HeapValidate(heap, 0, nullptr)) failed |= 0x80;
    return failed;
}
