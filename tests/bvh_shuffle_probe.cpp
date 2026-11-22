#include "bvh_fixture.h"
#include "ShuffleDefault.h"
#include "Shuffle16.h"
#include "Shuffle32.h"
#include "Shuffle64.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <map>
#include <stdexcept>
#include <vector>

using namespace bvh_fixture;
namespace {
constexpr Word lanesPerGroup = 64;
constexpr Word groups = 9;
constexpr Word fields = 16;

// The input values and requested lanes are different across groups, so a
// broadcast or a half-local shuffle cannot accidentally satisfy the oracle.
std::vector<Row> make_inputs() {
    std::vector<Row> inputs;
    inputs.reserve(groups * lanesPerGroup);
    for (Word group = 0; group < groups; ++group) {
        for (Word t = 0; t < lanesPerGroup; ++t) {
            Word value = (0xf0000001u ^ (group * 0x051f3a19u)) +
                         ((t + 1u) * 0x319dbu);
            if (group == 2) value = t == 31 || t == 32 ? 0xffffffffu - t : value;
            if (group == 5) value ^= t & 1u ? 0x80000000u : 0u;
            if (group == 8) value = (t * 0x9e3779b9u) ^ (group << 27);
            Word dynamic = (t * 29u + group * 13u + (t / 32u) * 7u) & 63u;
            inputs.push_back({value, group, dynamic, t ^ 31u});
        }
    }
    return inputs;
}

struct Mismatch {
    Word count = 0;
    Word inverseWitness = 0;
    Word firstThread = 0;
    Word firstField = 0;
    Word firstExpected = 0;
    Word firstActual = 0;
    void compare(Word actual, Word expected, Word thread, Word field, bool inverse = false) {
        if (actual == expected) return;
        if (count++ == 0) {
            firstThread = thread;
            firstField = field;
            firstExpected = expected;
            firstActual = actual;
        }
        if (inverse) ++inverseWitness;
    }
};

// Inverse by enumeration rather than copying the shader's expression: this
// checks that 7*n+3 is actually a permutation at the reported native width.
Word inverse_affine(Word index, Word width) {
    Word result = width;
    for (Word candidate = 0; candidate < width; ++candidate) {
        if ((7u * candidate + 3u) % width != index) continue;
        if (result != width) throw std::runtime_error("Affine permutation is not one-to-one");
        result = candidate;
    }
    if (result == width) throw std::runtime_error("Affine permutation has no inverse");
    return result;
}

bool query_capability(ID3D12Device* device, Word forced) {
    D3D12_FEATURE_DATA_D3D12_OPTIONS1 caps{};
    D3D12_FEATURE_DATA_SHADER_MODEL model{D3D_SHADER_MODEL_6_6};
#if defined(OFFSCREEN_AGILITY_620) && defined(__ID3D12Device16_INTERFACE_DEFINED__)
    ComPtr<ID3D12Device16> query;
    check(device->QueryInterface(IID_PPV_ARGS(&query)), "Get Agility shuffle capabilities");
    check(query->CheckFeatureSupport1(D3D12_FEATURE_D3D12_OPTIONS1, &caps, sizeof(caps), 620),
          "Query shuffle wave range");
    check(query->CheckFeatureSupport1(D3D12_FEATURE_SHADER_MODEL, &model, sizeof(model), 620),
          "Query shuffle shader model");
#else
    check(device->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS1, &caps, sizeof(caps)),
          "Query shuffle wave range");
    check(device->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL, &model, sizeof(model)),
          "Query shuffle shader model");
#endif
    std::printf("native_lane_range=%u..%u shader_model_capped_at_6_6=0x%x forced_width=%u\n",
                caps.WaveLaneCountMin, caps.WaveLaneCountMax, model.HighestShaderModel, forced);
    if (!caps.WaveOps) return false;
    if (!forced) return model.HighestShaderModel >= D3D_SHADER_MODEL_6_5;
    return model.HighestShaderModel >= D3D_SHADER_MODEL_6_6 &&
           caps.WaveLaneCountMin <= forced && caps.WaveLaneCountMax >= forced;
}
} // namespace

bool check_bvh_shuffle(ID3D12Device* device, Word forced) {
    if (forced != 0 && forced != 16 && forced != 32 && forced != 64)
        throw std::runtime_error("Expected default, 16, 32 or 64 native lanes");
    if (!query_capability(device, forced)) return false;
    D3D12_SHADER_BYTECODE bytecode{};
    switch (forced) {
    case 16: bytecode = {Shuffle16, sizeof(Shuffle16)}; break;
    case 32: bytecode = {Shuffle32, sizeof(Shuffle32)}; break;
    case 64: bytecode = {Shuffle64, sizeof(Shuffle64)}; break;
    default: bytecode = {ShuffleDefault, sizeof(ShuffleDefault)}; break;
    }
    auto inputs = make_inputs();
    constexpr Word count = groups * lanesPerGroup;
    constexpr UINT bytes = count * fields * sizeof(Word);
    auto source = upload(device, inputs);
    auto output = make_buffer(device, bytes, D3D12_HEAP_TYPE_DEFAULT,
                              D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
    auto readback = make_buffer(device, bytes, D3D12_HEAP_TYPE_READBACK,
                                D3D12_RESOURCE_STATE_COPY_DEST);
    Kernel shader(device, bytecode);
    ComputeCommands cmd(device, shader.pipeline.Get());
    auto* list = cmd.list.Get();
    transition(list, output.Get(), D3D12_RESOURCE_STATE_COMMON,
               D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    list->SetComputeRootSignature(shader.root.Get());
    list->SetComputeRootShaderResourceView(0, source->GetGPUVirtualAddress());
    list->SetComputeRootUnorderedAccessView(1, output->GetGPUVirtualAddress());
    list->Dispatch(groups, 1, 1);
    transition(list, output.Get(), D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
               D3D12_RESOURCE_STATE_COPY_SOURCE);
    list->CopyBufferRegion(readback.Get(), 0, output.Get(), 0, bytes);
    cmd.submit_and_wait(device);
    auto results = read(readback.Get(), count * fields);

    // Do NOT infer physical wave membership from thread-order/32 or /64.
    // WaveReadLaneFirst(SV_GroupIndex) provides an independent grouping key;
    // each physical wave supplies its own lane IDs and source values.
    std::map<std::pair<Word, Word>, std::vector<Word>> waves;
    for (Word index = 0; index < count; ++index)
        waves[{index / lanesPerGroup, results[index * fields + 2]}].push_back(index);

    Mismatch difference;
    Word non_involution_witnesses = 0;
    bool can_distinguish_inverse = false;
    for (const auto& [key, threads] : waves) {
        const Word width = results[threads.front() * fields + 1];
        if (!width || width > lanesPerGroup || (width & (width - 1u)))
            throw std::runtime_error("Invalid reported wave width");
        if (forced && width != forced) throw std::runtime_error("Forced native wave width was ignored");
        if (width >= 16) can_distinguish_inverse = true;
        if (threads.size() != width) throw std::runtime_error("Physical wave has incomplete lanes");
        std::vector<Word> values(width, 0);
        std::vector<bool> seen(width, false);
        for (Word index : threads) {
            const Word* record = results.data() + index * fields;
            const Word lane = record[0];
            if (record[1] != width || lane >= width || seen[lane])
                throw std::runtime_error("Invalid or repeated native lane assignment");
            seen[lane] = true;
            values[lane] = inputs[index][0];
            difference.compare(record[3], values[lane], index, 3);
        }
        for (bool occupied : seen)
            if (!occupied) throw std::runtime_error("Native lane assignment has a hole");
        for (Word index : threads) {
            const Word* r = results.data() + index * fields;
            const Word lane = r[0];
            const Word affine = (7u * lane + 3u) % width;
            const Word inverse = inverse_affine(lane, width);
            const Word dynamic = inputs[index][2] % width;
            if (affine != inverse) ++non_involution_witnesses;
            const std::array<Word, fields> expected = {
                lane, width, key.second, inputs[index][0],
                affine, values[affine], inverse, values[inverse],
                values[(lane + 1u) % width], values[width - 1u - lane],
                values[lane ^ (width / 2u)], values[lane],
                dynamic, values[dynamic], values[width - 1u], values[0]
            };
            for (Word field = 0; field < fields; ++field) {
                const bool inverseWitness = field == 5 && r[field] == values[inverse];
                difference.compare(r[field], expected[field], index, field, inverseWitness);
            }
        }
    }
    // At widths 4 and 8 the affine routing is self-inverse: their passing
    // results cannot distinguish forward routing from the inverse WARP bug.
    // Widths 16/32/64 must provide non-involutive witnesses.
    if (can_distinguish_inverse && !non_involution_witnesses)
        throw std::runtime_error("No non-involutive routing witness generated");
    std::printf("shuffle_forced_width=%u groups=%u threads=%u waves=%zu inverse_route_witnesses=%u "
                "mismatches=%u inverse_mismatch_matches=%u\n",
                forced, groups, count, waves.size(), non_involution_witnesses,
                difference.count, difference.inverseWitness);
    if (difference.count) {
        std::fprintf(stderr, "first_shuffle_mismatch thread=%u field=%u expected=%08x actual=%08x\n",
                     difference.firstThread, difference.firstField,
                     difference.firstExpected, difference.firstActual);
        throw std::runtime_error("Independent WaveReadLaneAt oracle mismatch");
    }
    return true;
}
