#include <csetjmp>
extern "C" {
#include "blast/blast.h"
}

static word indexed_slot(word sp, int delta, word offset, unsigned width) {
    const word frame_size = static_cast<word>(-delta);
    if (offset > frame_size || width > frame_size - offset) std::abort();
    return sp + delta + offset;
}

struct Context {
    Data& data;
    blast_in input;
    blast_out output;
    alignas(16) unsigned char stack[16384]{};
    std::jmp_buf resume;
    word environment{};
    unsigned jump_result{};

    word callback(word target, word context, word buffer, word count) const {
        if (target && target == word(input))
            return input(reinterpret_cast<void*>(context), reinterpret_cast<unsigned char**>(buffer));
        if (target && target == word(output))
            return static_cast<unsigned>(output(reinterpret_cast<void*>(context),
                                                reinterpret_cast<unsigned char*>(buffer), static_cast<unsigned>(count)));
        std::abort();
    }
};
