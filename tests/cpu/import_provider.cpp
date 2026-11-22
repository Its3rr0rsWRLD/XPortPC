#include <cstdint>

#ifdef LIVE_WORKER
#include <windows.h>
// The exe_start fixtures start no worker themselves. This variant leaves one alive and ready before
// mix_args returns, so the body returns while a worker remains. CPU_EXE_TEST_BODY_HANG=1 makes mix_args
// block instead, for a control in which the body never returns.
extern "C" __declspec(dllimport) std::uint32_t start_live_worker();
#endif

using Word = std::uint64_t;

extern "C" Word mix_args(Word first, Word second, Word* output) {
#ifdef LIVE_WORKER
    if (!start_live_worker())
        ExitProcess(3);  // keep a failed test setup distinct from a wrong result
    wchar_t hang[2];
    if (GetEnvironmentVariableW(L"CPU_EXE_TEST_BODY_HANG", hang, 2) == 1 && hang[0] == L'1')
        Sleep(INFINITE);  // control: the body never returns
#endif
    output[0] = first;
    output[1] = second;
    output[2] = first - second + 11;
#ifdef ALTER_RETURN
    return output[2] + 1;
#else
    return output[2];
#endif
}
