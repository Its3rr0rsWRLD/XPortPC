// gdeflate_pack IN OUT [LEVEL]: writes IN as one GDeflate stream (Microsoft's reference encoder, level 1-12, default
// 9). Prints "packed <in bytes> -> <out bytes>". Used by the tests to create DirectStorage fixtures.
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "GDeflate.h"

static bool read_all(const char* path, std::vector<uint8_t>& out) {
    FILE* f = std::fopen(path, "rb");
    if (!f) return false;
    uint8_t buf[65536];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) out.insert(out.end(), buf, buf + n);
    std::fclose(f);
    return true;
}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: gdeflate_pack IN OUT [LEVEL]\n");
        return 2;
    }
    const unsigned level = argc > 3 ? static_cast<unsigned>(std::atoi(argv[3])) : 9u;
    std::vector<uint8_t> in;
    if (!read_all(argv[1], in) || in.empty()) {
        std::fprintf(stderr, "gdeflate_pack: cannot read %s\n", argv[1]);
        return 1;
    }
    std::vector<uint8_t> out(GDeflate::CompressBound(in.size()));
    size_t size = out.size();
    if (!GDeflate::Compress(out.data(), &size, in.data(), in.size(), level, 0)) {
        std::fprintf(stderr, "gdeflate_pack: compression failed\n");
        return 1;
    }
    FILE* f = std::fopen(argv[2], "wb");
    if (!f || std::fwrite(out.data(), 1, size, f) != size) {
        std::fprintf(stderr, "gdeflate_pack: cannot write %s\n", argv[2]);
        return 1;
    }
    std::fclose(f);
    std::printf("packed %zu -> %zu\n", in.size(), size);
    return 0;
}
