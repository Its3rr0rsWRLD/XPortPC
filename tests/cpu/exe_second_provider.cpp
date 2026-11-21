#include <cstdint>

using Word = std::uint64_t;

extern "C" __declspec(dllimport) std::uint32_t emit_trace(const Word*);

extern "C" __declspec(dllexport) Word accumulate_args(Word first, Word second, Word* trace)
{
    // Record the first provider's observation before reusing the trace buffer.
    if (!emit_trace(trace))
        return 0;
    trace[0] = first;
    trace[1] = second;
    trace[2] = first + second + 17;
    return trace[2];
}
