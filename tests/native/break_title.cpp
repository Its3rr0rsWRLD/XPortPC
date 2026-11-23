// Source-built program with breakpoints in its own code, without a C runtime (tests/native/break_check.py):
// break_ops (tests/native/break_ops.asm) runs a one-byte and a two-byte int3 with RAX = 0x1122334455667788 and returns
// 42, then the program runs __debugbreak(). Under x2w_launch's default --continue-breakpoints all three are skipped and
// the exit code is 0 (1 if break_ops returned anything else); with --stop-on-breakpoints the first one ends the run.
#include <windows.h>
#include <intrin.h>

#pragma runtime_checks("", off)

extern "C" unsigned long long break_ops();

extern "C" DWORD break_entry(void*)
{
    const unsigned long long r = break_ops();
    __debugbreak();
    return r == 42 ? 0 : 1;
}
