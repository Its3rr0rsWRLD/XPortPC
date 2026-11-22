// Calls function(x, y, trace) and returns the code of the structured exception it raises, or 0 after
// storing its return value. The CPU tests use it to compare the fault of an original function with
// the fault of its translation.
#include <windows.h>

#include <cstdint>

using word = std::uint64_t;

extern "C" __declspec(dllexport) std::uint32_t guarded_call(word (*function)(word, word, word*), word x, word y,
                                                           word* trace, word* result) {
    __try {
        *result = function(x, y, trace);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return GetExceptionCode();
    }
    return 0;
}
