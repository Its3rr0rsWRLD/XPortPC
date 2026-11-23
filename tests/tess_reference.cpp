// Command-line wrapper of the D3D11 reference tessellator (tests/third_party/d3d11_tessellator, Microsoft, MIT) for
// tests/tess_aot_check.py (docs/design/stages.md, card T-1, the tessellator check).
//
// Reads one patch per line from stdin:
//     <tri|quad> <integer|pow2|fractional_odd|fractional_even> <triangle_cw|triangle_ccw> F0 F1 F2 F3 [F4 F5]
// The factors are binary32 words in hex, in SV_TessFactor then SV_InsideTessFactor order: four for a triangle (the
// U==0, V==0, W==0 edges, then inside), six for a quad (U==0, V==0, U==1, V==1, then inside U and V). For each line it
// prints "points N u v ..." and "indices M i ...", the domain points as binary32 words in hex and the triangle list
// indices in the order the tessellator produces them (CHWTessellator: the fixed-function hardware reference, which
// processes the raw factors itself, as the hardware does with the factors the hull shader writes).
#include "third_party/d3d11_tessellator/tessellator.hpp"

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>

namespace {
float word_float(const std::string& text)
{
    const std::uint32_t bits = static_cast<std::uint32_t>(std::stoul(text, nullptr, 16));
    float value;
    std::memcpy(&value, &bits, 4);
    return value;
}

std::uint32_t float_word(float value)
{
    std::uint32_t bits;
    std::memcpy(&bits, &value, 4);
    return bits;
}
}

int main()
{
    auto tessellator = std::make_unique<CHWTessellator>();
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        std::istringstream in(line);
        std::string domain, partitioning, topology, token;
        in >> domain >> partitioning >> topology;
        float f[6]{};
        int count = 0;
        while (in >> token) {
            if (count == 6) {
                std::fprintf(stderr, "tess_reference: more than six factors\n");
                return 2;
            }
            f[count++] = word_float(token);
        }
        PIPE_TESSELLATOR_PARTITIONING part;
        if (partitioning == "integer") part = PIPE_TESSELLATOR_PARTITIONING_INTEGER;
        else if (partitioning == "pow2") part = PIPE_TESSELLATOR_PARTITIONING_POW2;
        else if (partitioning == "fractional_odd") part = PIPE_TESSELLATOR_PARTITIONING_FRACTIONAL_ODD;
        else if (partitioning == "fractional_even") part = PIPE_TESSELLATOR_PARTITIONING_FRACTIONAL_EVEN;
        else {
            std::fprintf(stderr, "tess_reference: unknown partitioning %s\n", partitioning.c_str());
            return 2;
        }
        PIPE_TESSELLATOR_OUTPUT_PRIMITIVE primitive;
        if (topology == "triangle_cw") primitive = PIPE_TESSELLATOR_OUTPUT_TRIANGLE_CW;
        else if (topology == "triangle_ccw") primitive = PIPE_TESSELLATOR_OUTPUT_TRIANGLE_CCW;
        else {
            std::fprintf(stderr, "tess_reference: unknown topology %s\n", topology.c_str());
            return 2;
        }
        tessellator->Init(part, primitive);
        if (domain == "tri" && count == 4) {
            tessellator->TessellateTriDomain(f[0], f[1], f[2], f[3]);
        } else if (domain == "quad" && count == 6) {
            tessellator->TessellateQuadDomain(f[0], f[1], f[2], f[3], f[4], f[5]);
        } else {
            std::fprintf(stderr, "tess_reference: domain %s with %d factors\n", domain.c_str(), count);
            return 2;
        }
        const int points = tessellator->GetPointCount(), indices = tessellator->GetIndexCount();
        const DOMAIN_POINT* point = tessellator->GetPoints();
        const int* index = tessellator->GetIndices();
        std::printf("points %d", points);
        for (int i = 0; i < points; ++i)
            std::printf(" %08x %08x", float_word(point[i].u), float_word(point[i].v));
        std::printf("\nindices %d", indices);
        for (int i = 0; i < indices; ++i) std::printf(" %d", index[i]);
        std::printf("\n");
    }
    return 0;
}
