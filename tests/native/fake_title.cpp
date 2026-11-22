// Source-built stand-in for a title, without a C runtime. It imports a console library that a desktop shim
// provides (xmem.dll), Windows (kernel32.dll) and a DLL that nothing provides (x2w_missing.dll), so
// x2w_launch must use all three routes. The exit code records which calls behaved: 0x47 when all did.
#include <windows.h>

#pragma runtime_checks("", off)

extern "C" __declspec(dllimport) void* XMemAlloc(SIZE_T bytes, ULONGLONG attributes);
extern "C" __declspec(dllimport) void XMemFree(void* allocation, ULONGLONG attributes);
extern "C" __declspec(dllimport) int X2wMissingFirst(int value);
extern "C" __declspec(dllimport) int X2wMissingSecond();

extern "C" DWORD exe_entry(void*) {
    DWORD code = 0x40;
    auto* block = static_cast<volatile unsigned char*>(XMemAlloc(64, 0));
    if (block) {
        block[0] = 0x5a;
        block[63] = 0xa5;
        if (block[0] == 0x5a && block[63] == 0xa5) code |= 1;
        XMemFree((void*)block, 0);
    }
    if (GetCurrentThreadId() != 0) code |= 2;
    // Stubs return 0; the first symbol is called twice and must be reported once.
    if (X2wMissingFirst(7) == 0 && X2wMissingFirst(8) == 0 && X2wMissingSecond() == 0) code |= 4;
    return code;
}
