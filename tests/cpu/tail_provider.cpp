// Imports for tail_import.asm. Each records its integer arguments in three words at output and returns a
// value that depends on all of them. ALTER_RETURN changes only the returned value.
#include <cstdint>

using Word = std::uint64_t;

static Word result(Word value) {
#ifdef ALTER_RETURN
    return value + 1;
#else
    return value;
#endif
}

extern "C" Word mix3(Word first, Word second, Word* output) {
    output[0] = first;
    output[1] = second;
    output[2] = first - second + 11;
    return result(output[2] * 3 + (first >> 5));
}

extern "C" Word mix4(Word first, Word second, Word* output, Word fourth) {
    output[0] = first;
    output[1] = second;
    output[2] = fourth;
    return result(((first - second) * 3) ^ fourth);
}
